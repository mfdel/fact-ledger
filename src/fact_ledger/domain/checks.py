"""Identity checks, invariants and the MRR bridge (S2-03 to S2-05).

Each identity id has a Python entry: its terms, their time offsets and its formula. The YAML
``equation`` stays documentation for people. A drift test keeps the two in step.
"""

import calendar
from collections.abc import Callable, Iterable, Sequence
from datetime import date, timedelta
from decimal import Decimal
from enum import StrEnum
from itertools import product
from typing import NamedTuple

from fact_ledger.domain.enums import (
    CheckStatus,
    DefinitionStatus,
    Dimension,
    FindingKind,
    PeriodType,
)
from fact_ledger.domain.models import (
    Dictionary,
    Identity,
    Metric,
    Observation,
    Period,
    Qualifier,
)
from fact_ledger.domain.paths import (
    CheckResult,
    Comparison,
    ComputationPath,
    Finding,
    aligned_period,
    direct_path,
    is_outside,
    metric_of,
    pair_tolerance,
    period_of,
    qualifier_of,
)


class _Offset(StrEnum):
    """Where a term is read, relative to the anchor period (D3.3)."""

    SAME = "same"
    END = "end"
    START = "start"
    YEAR_BEFORE = "year_before"
    TRAILING_12M = "trailing_12m"


class Index(NamedTuple):
    """Rows that can fill an identity term, and ambiguous rows that never can (D3.5)."""

    resolved: dict[tuple[str, Period], list[Observation]]
    unusable: dict[tuple[str, Period], list[tuple[str, Observation]]]


class EqualityRun(NamedTuple):
    """The computed paths of one equality at one anchor. Their comparisons give the status."""

    identity_id: str
    anchor: Period
    paths: list[ComputationPath]
    reason: str
    qualifier: Qualifier = Qualifier()


class _Condition(NamedTuple):
    skip: str = ""
    assumption: str = ""
    used: tuple[Observation, ...] = ()


class _Equality(NamedTuple):
    target: str
    inputs: tuple[tuple[str, _Offset], ...]
    formula: Callable[..., Decimal]  # input values in ``inputs`` order, in stored units
    twelve_months: bool = False
    # S3-24, decision 28: used when only this formula matches a target row.
    alternate: Callable[..., Decimal] | None = None


class _Inequality(NamedTuple):
    lhs: str
    rhs: tuple[str, _Offset]
    at_least: bool
    condition: Callable[[Index, Observation, Observation], _Condition] | None = None


_GROWTH = "arr grew more than 30% over those 12 months, arr[t] / arr[t-12m] - 1 > 0.30"
_SCOPE = "revenue_services plus revenue_hardware is below 10% of revenue_recognised"
_SCOPE_TERMS = ("revenue_services", "revenue_hardware")


def _point(day: date) -> Period:
    return Period(day, day, PeriodType.POINT_IN_TIME)


def year_before(day: date) -> date:
    """The same day 12 months earlier. A month end stays a month end (2025-02-28 -> 2024-02-29)."""
    last = calendar.monthrange(day.year - 1, day.month)[1]
    if day.day == calendar.monthrange(day.year, day.month)[1]:
        return date(day.year - 1, day.month, last)
    return date(day.year - 1, day.month, min(day.day, last))


def _twelve_months(period: Period) -> bool:
    return period.type in {PeriodType.FY, PeriodType.TTM} and period.start == year_before(
        period.end
    ) + timedelta(days=1)


def _periods(anchor: Period, offset: _Offset) -> tuple[Period, ...]:
    """D3.3: an exact date or window, never "the previous observation in the store"."""
    match offset:
        case _Offset.SAME:
            return (anchor,)
        case _Offset.END:
            return (_point(anchor.end),)
        case _Offset.START:
            return (_point(anchor.start - timedelta(days=1)),)
        case _Offset.YEAR_BEFORE:
            return (_point(year_before(anchor.end)),)
        case _Offset.TRAILING_12M:
            start = year_before(anchor.end) + timedelta(days=1)
            return tuple(Period(start, anchor.end, t) for t in (PeriodType.FY, PeriodType.TTM))


def _period_text(period: Period) -> str:
    if period.type is PeriodType.POINT_IN_TIME:
        return f"at {period.end}"
    return f"for {period.type} {period.start} to {period.end}"


def _lookup(
    index: Index, metric_id: str, periods: Sequence[Period]
) -> tuple[list[Observation], str]:
    """The rows of a term, or the D4.2 reason why no row can fill it."""
    rows = [r for p in periods for r in index.resolved.get((metric_id, p), [])]
    if rows:
        return rows, ""
    for word, row in (u for p in periods for u in index.unusable.get((metric_id, p), [])):
        return [], f"only an {word} value for {metric_id}: {row.observation_id}"
    return [], f"{metric_id} not observed {_period_text(periods[0])}"


def _terms(
    index: Index, inputs: Sequence[tuple[str, _Offset]], anchor: Period
) -> tuple[list[list[Observation]], str]:
    terms = []
    for metric_id, offset in inputs:
        rows, reason = _lookup(index, metric_id, _periods(anchor, offset))
        if reason:
            return [], reason
        terms.append(rows)
    return terms, ""


def _units(rows: Iterable[Observation], dictionary: Dictionary) -> str:
    """D3.5: currency terms share one unit and currency. A percent term is in points."""
    money: set[str] = set()
    for row in rows:
        dimension = metric_of(dictionary, row.metric_id).dimension
        if dimension is Dimension.CURRENCY:
            money.add(row.currency or row.unit)
        elif dimension is Dimension.PERCENT and row.unit != "percent":
            return f"unit differs: {row.unit} and percent"
    return "currency differs: " + " and ".join(sorted(money)) if len(money) > 1 else ""


def _computed(
    identity_id: str,
    target: Metric,
    inputs: Sequence[Observation],
    formula: Callable[..., Decimal],
    period: Period,
) -> ComputationPath | str:
    """A computed path, or "zero denominator". D1.4: each input moves up by its own precision,
    one at a time, and the changes of the result add up to the precision of the path.
    """
    values = [o.value for o in inputs]
    try:
        value = formula(*values)
        precision = sum(
            (
                abs(formula(*values[:i], values[i] + o.stated_precision, *values[i + 1 :]) - value)
                for i, o in enumerate(inputs)
                if o.stated_precision
            ),
            Decimal(0),
        )
    except ZeroDivisionError:
        return "zero denominator"
    money = target.dimension is Dimension.CURRENCY
    return ComputationPath(
        metric_id=target.metric_id,
        period=period,
        value=value,
        unit=inputs[0].unit if money else "percent",
        currency=inputs[0].currency if money else None,
        precision=precision,
        identity_id=identity_id,
        observations=tuple(inputs),
        # The check index gives every input the same qualifier.
        qualifier=qualifier_of(inputs[0]),
    )


def _arr_condition(index: Index, arr: Observation, revenue: Observation) -> _Condition:
    """D4.3: growth is required. The services share is tested when observed, else assumed."""
    priors, reason = _lookup(index, "arr", _periods(period_of(arr), _Offset.YEAR_BEFORE))
    if reason:
        return _Condition(skip=reason)
    if any(p.value == 0 for p in priors):
        return _Condition(skip="zero denominator")
    if any(arr.value / p.value - 1 <= Decimal("0.30") for p in priors):
        return _Condition(skip=f"condition not met: {_GROWTH}")
    # The largest row of each term: the share condition must hold for every stated value.
    other = [
        max(rows, key=lambda r: r.value)
        for term in _SCOPE_TERMS
        if (rows := index.resolved.get((term, period_of(revenue))))
    ]
    if sum((o.value for o in other), Decimal(0)) >= Decimal("0.10") * revenue.value:
        return _Condition(skip=f"condition not met: {_SCOPE}")
    assumption = _SCOPE if len(other) < len(_SCOPE_TERMS) else ""
    return _Condition(assumption=assumption, used=(*priors, *other))


EQUALITIES: dict[str, _Equality] = {
    "arr_from_mrr": _Equality("arr", (("mrr", _Offset.SAME),), lambda mrr: mrr * 12),
    "net_new_arr_from_arr": _Equality(
        "net_new_arr",
        (("arr", _Offset.END), ("arr", _Offset.START)),
        lambda end, start: end - start,
    ),
    "nrr_from_bridge": _Equality(
        "nrr",
        (
            ("arr", _Offset.START),
            ("mrr_expansion", _Offset.SAME),
            ("mrr_contraction", _Offset.SAME),
            ("mrr_churned", _Offset.SAME),
        ),
        lambda arr, expansion, contraction, churned: (
            100 * (arr + 12 * (expansion - contraction - churned)) / arr
        ),
        twelve_months=True,
    ),
    "grr_from_bridge": _Equality(
        "grr",
        (("arr", _Offset.START), ("mrr_contraction", _Offset.SAME), ("mrr_churned", _Offset.SAME)),
        lambda arr, contraction, churned: 100 * (arr - 12 * (contraction + churned)) / arr,
        twelve_months=True,
    ),
    "churn_logo_annual_from_monthly": _Equality(
        "churn_logo_annual",
        (("churn_logo_monthly", _Offset.SAME),),
        lambda monthly: 100 * (1 - (1 - monthly / 100) ** 12),
    ),
    # S3-19: the core listed-company IFRS identities.
    "gross_profit_from_revenue": _Equality(
        "gross_profit",
        (("revenue_recognised", _Offset.SAME), ("cost_of_sales", _Offset.SAME)),
        lambda revenue, cost: revenue - cost,
    ),
    "ebitda_from_ebit": _Equality(
        "ebitda",
        (("ebit", _Offset.SAME), ("d_and_a", _Offset.SAME)),
        lambda ebit, d_and_a: ebit + d_and_a,
    ),
    "gross_margin_from_revenue": _Equality(
        "gross_margin",
        (("gross_profit", _Offset.SAME), ("revenue_recognised", _Offset.SAME)),
        lambda gross_profit, revenue: 100 * gross_profit / revenue,
    ),
    "ebitda_margin_from_revenue": _Equality(
        "ebitda_margin",
        (("ebitda", _Offset.SAME), ("revenue_recognised", _Offset.SAME)),
        lambda ebitda, revenue: 100 * ebitda / revenue,
    ),
    "ebitda_adjusted_margin_from_revenue": _Equality(
        "ebitda_adjusted_margin",
        (("ebitda_adjusted", _Offset.SAME), ("revenue_recognised", _Offset.SAME)),
        lambda ebitda_adjusted, revenue: 100 * ebitda_adjusted / revenue,
    ),
    "ebit_margin_from_revenue": _Equality(
        "ebit_margin",
        (("ebit", _Offset.SAME), ("revenue_recognised", _Offset.SAME)),
        lambda ebit, revenue: 100 * ebit / revenue,
    ),
    "net_margin_from_revenue": _Equality(
        "net_margin",
        (("net_income", _Offset.SAME), ("revenue_recognised", _Offset.SAME)),
        lambda net_income, revenue: 100 * net_income / revenue,
    ),
    # S3-24. income_tax_expense is stored unsigned, so a tax credit also matches.
    "net_income_from_ebt": _Equality(
        "net_income",
        (("ebt", _Offset.SAME), ("income_tax_expense", _Offset.SAME)),
        lambda ebt, tax: ebt - tax,
        alternate=lambda ebt, tax: ebt + tax,
    ),
}

INEQUALITIES: dict[str, _Inequality] = {
    "nrr_ge_grr": _Inequality("nrr", ("grr", _Offset.SAME), at_least=True),
    "arr_ge_revenue_recognised": _Inequality(
        "arr", ("revenue_recognised", _Offset.TRAILING_12M), at_least=True, condition=_arr_condition
    ),
    "customers_paying_le_users_registered": _Inequality(
        "customers_paying", ("users_registered", _Offset.SAME), at_least=False
    ),
    "seats_active_le_seats_licensed": _Inequality(
        "seats_active", ("seats_licensed", _Offset.SAME), at_least=False
    ),
}

BRIDGE_ID = "mrr_bridge"
# D5.2. The target is the closing MRR, at the end of the window of the flows.
BRIDGE = _Equality(
    "mrr",
    (
        ("mrr", _Offset.START),
        ("mrr_new", _Offset.SAME),
        ("mrr_expansion", _Offset.SAME),
        ("mrr_reactivation", _Offset.SAME),
        ("mrr_contraction", _Offset.SAME),
        ("mrr_churned", _Offset.SAME),
    ),
    lambda opening, new, expansion, reactivation, contraction, churned: (
        opening + new + expansion + reactivation - contraction - churned
    ),
)


def _check(
    identity_id: str,
    entity_id: str,
    period: Period | None,
    *,
    ran: bool,
    violated: bool,
    reason: str,
) -> CheckResult:
    """Section 6: violated if any combination is, held if one ran, else not checked."""
    status = (
        CheckStatus.VIOLATED if violated else CheckStatus.HELD if ran else CheckStatus.NOT_CHECKED
    )
    return CheckResult(
        identity_id=identity_id, entity_id=entity_id, period=period, status=status, reason=reason
    )


def _anchors(index: Index, metric_ids: Iterable[str]) -> list[Period]:
    """D4.2: a check with no observed anchor term reports nothing, not a list of skips."""
    wanted = set(metric_ids)
    return sorted({p for (m, p) in index.resolved if m in wanted})


def _near_a_target(
    path: ComputationPath, targets: Iterable[Observation], dictionary: Dictionary
) -> bool:
    dimension = metric_of(dictionary, path.metric_id).dimension
    return any(
        abs(t.value - path.value) <= pair_tolerance(direct_path(t, dictionary), path, dimension)
        for t in targets
        if (t.unit, t.currency) == (path.unit, path.currency)
    )


def _equality(
    identity: Identity, rule: _Equality, index: Index, dictionary: Dictionary
) -> list[EqualityRun]:
    """D3.1 and D3.2: one computed path per combination of input rows, for the target only."""
    target = metric_of(dictionary, rule.target)
    runs = []
    for anchor in _anchors(index, [rule.target]):
        paths: list[ComputationPath] = []
        terms, reason = _terms(index, rule.inputs, anchor)
        if rule.twelve_months and not _twelve_months(anchor):
            terms, reason = [], f"condition not met: {rule.target} covers 12 months"
        targets = index.resolved[rule.target, anchor]
        for inputs in product(*terms) if terms else ():
            # A target in another currency is not comparable. It must not hide the other targets.
            skips = [_units((*inputs, t), dictionary) for t in targets]
            path = ("" if "" in skips else skips[0]) or _computed(
                identity.identity_id, target, inputs, rule.formula, anchor
            )
            if (
                rule.alternate
                and not isinstance(path, str)
                and not _near_a_target(path, targets, dictionary)
            ):
                other = _computed(identity.identity_id, target, inputs, rule.alternate, anchor)
                if not isinstance(other, str) and _near_a_target(other, targets, dictionary):
                    path = other
            if isinstance(path, str):
                reason = reason or path
            else:
                paths.append(path)
        runs.append(EqualityRun(identity.identity_id, anchor, paths, reason))
    return runs


def _inequality(
    entity_id: str, identity: Identity, rule: _Inequality, index: Index, dictionary: Dictionary
) -> tuple[list[CheckResult], list[Finding]]:
    """D1.6 and D4.1: a violation beyond the margin is always a finding, whatever its size."""
    dimension = metric_of(dictionary, rule.lhs).dimension
    checks, findings = [], []
    for anchor in _anchors(index, [rule.lhs]):
        rhs_rows, reason = _lookup(index, rule.rhs[0], _periods(anchor, rule.rhs[1]))
        ran, violated, assumption = False, False, ""
        for lhs, rhs in product(index.resolved[rule.lhs, anchor], rhs_rows):
            condition = rule.condition(index, lhs, rhs) if rule.condition else _Condition()
            skip = _units((lhs, rhs), dictionary) or condition.skip
            if skip:
                reason = reason or skip
                continue
            ran, assumption = True, assumption or condition.assumption
            a, b = direct_path(lhs, dictionary), direct_path(rhs, dictionary)
            margin = pair_tolerance(a, b, dimension)
            if a.value < b.value - margin if rule.at_least else a.value > b.value + margin:
                violated = True
                findings.append(
                    Finding(
                        kind=FindingKind.INVARIANT,
                        divergence=None,
                        entity_id=entity_id,
                        subject=identity.identity_id,
                        period=anchor,
                        left=a,
                        right=(b, *(direct_path(o, dictionary) for o in condition.used)),
                        assumption=condition.assumption,
                    )
                )
        reason = assumption if ran else reason
        checks.append(
            _check(
                identity.identity_id, entity_id, anchor, ran=ran, violated=violated, reason=reason
            )
        )
    return checks, findings


def _bridge(
    entity_id: str, index: Index, dictionary: Dictionary
) -> tuple[list[CheckResult], list[Finding]]:
    """D5: check only. A missing term is never zero, and no term is derived to close it."""
    mrr = metric_of(dictionary, "mrr")
    checks, findings = [], []
    for anchor in _anchors(index, (m for m, _ in BRIDGE.inputs[1:])):
        closing, reason = _lookup(index, "mrr", _periods(anchor, _Offset.END))
        terms, reason = _terms(index, BRIDGE.inputs, anchor) if closing else ([], reason)
        ran = violated = False
        for close, *inputs in product(closing, *terms) if terms else ():
            computed = _units((close, *inputs), dictionary) or _computed(
                BRIDGE_ID, mrr, inputs, BRIDGE.formula, _point(anchor.end)
            )
            if isinstance(computed, str):
                reason = reason or computed
                continue
            ran, left = True, direct_path(close, dictionary)
            margin = pair_tolerance(left, computed, mrr.dimension)
            if abs(left.value - computed.value) > margin:
                violated = True
                findings.append(
                    Finding(
                        kind=FindingKind.BRIDGE,
                        divergence=None,
                        entity_id=entity_id,
                        subject=BRIDGE_ID,
                        period=anchor,
                        left=left,
                        right=(computed,),
                    )
                )
        reason = "" if ran else reason
        checks.append(
            _check(BRIDGE_ID, entity_id, anchor, ran=ran, violated=violated, reason=reason)
        )
    return checks, findings


def build_index(
    rows: Iterable[Observation], paths: dict[str, ComputationPath], dictionary: Dictionary
) -> dict[Qualifier, Index]:
    """One index per qualifier (check index key 4): a term can
    never cross a segment, a region or a basis, because each qualifier only ever sees its own
    rows. Only stored resolved rows fill a term. An ambiguous row never does, inferred or not.
    """
    indexes: dict[Qualifier, Index] = {}
    for row in rows:
        path = paths[row.observation_id]
        index = indexes.setdefault(qualifier_of(row), Index({}, {}))
        if row.definition_status is DefinitionStatus.RESOLVED:
            index.resolved.setdefault((row.metric_id, period_of(row)), []).append(row)
        elif path.inferred:
            index.unusable.setdefault((path.metric_id, path.period), []).append(("inferred", row))
        else:
            keys = [(row.metric_id, period_of(row))]
            keys += [
                (c, aligned_period(row, metric_of(dictionary, c)))
                for c in row.candidate_metric_ids
                if c in dictionary.metric_ids
            ]
            for key in keys:
                index.unusable.setdefault(key, []).append(("ambiguous", row))
    return indexes


def _candidates(index: Index, rule: _Equality) -> list[Period]:
    """Anchors that the input rows give where the target has no row. A START term gives none:
    each entry with one also has a SAME or an END term.
    """
    same = {m for m, offset in rule.inputs if offset is _Offset.SAME}
    end = {m for m, offset in rule.inputs if offset is _Offset.END}
    anchors = {p for m, p in index.resolved if m in same}
    anchors |= {
        Period(year_before(p.end) + timedelta(days=1), p.end, PeriodType.FY)
        for m, p in index.resolved
        if m in end
    }
    return sorted(
        a
        for a in anchors
        if (rule.target, a) not in index.resolved and (_twelve_months(a) or not rule.twelve_months)
    )


def derive(index: Index, dictionary: Dictionary) -> list[ComputationPath]:
    """The computed paths for a target that has no row (S4-01). It is not an S2 check, so it
    makes no ``EqualityRun``. Only stored rows are terms, so no fill feeds another.
    """
    paths: list[ComputationPath] = []
    for identity in dictionary.identities:
        rule = EQUALITIES.get(identity.identity_id)
        if rule is None:
            continue
        target = metric_of(dictionary, rule.target)
        for anchor in _candidates(index, rule):
            terms, _ = _terms(index, rule.inputs, anchor)
            for inputs in product(*terms) if terms else ():
                path = _units(inputs, dictionary) or _computed(
                    identity.identity_id, target, inputs, rule.formula, anchor
                )
                if not isinstance(path, str):
                    paths.append(path)
    return paths


def run_checks(
    entity_id: str, index: Index, dictionary: Dictionary
) -> tuple[list[CheckResult], list[Finding], list[EqualityRun]]:
    """Invariant and bridge results, and the computed paths of the equalities.

    An identity with no Python entry gives one visible "no evaluator" skip per call. The
    caller runs this once per qualifier and tags its own
    qualifier onto every result it gets back.
    """
    checks: list[CheckResult] = []
    findings: list[Finding] = []
    runs: list[EqualityRun] = []
    for identity in dictionary.identities:
        identity_id = identity.identity_id
        if identity_id in EQUALITIES:
            runs += _equality(identity, EQUALITIES[identity_id], index, dictionary)
            continue
        if identity_id in INEQUALITIES:
            found = _inequality(entity_id, identity, INEQUALITIES[identity_id], index, dictionary)
        elif identity_id == BRIDGE_ID:
            found = _bridge(entity_id, index, dictionary)
        else:
            skip = _check(
                identity_id, entity_id, None, ran=False, violated=False, reason="no evaluator"
            )
            found = [skip], []
        checks += found[0]
        findings += found[1]
    return checks, findings, runs


def equality_checks(
    entity_id: str, runs: Iterable[EqualityRun], comparisons: Sequence[Comparison]
) -> list[CheckResult]:
    """Held when each comparison with a direct path of the target is inside tolerance.

    An inferred row never changes a check status (D2.9).
    """
    checks = []
    for run in runs:
        keys = {p.key for p in run.paths}
        ran = [
            c
            for c in comparisons
            if c.divergence is not None
            and len({c.a.key, c.b.key} & keys) == 1
            and not (c.a.inferred or c.b.inferred or (c.a.identity_id and c.b.identity_id))
        ]
        violated = any(map(is_outside, ran))
        checks.append(
            _check(
                run.identity_id,
                entity_id,
                run.anchor,
                ran=bool(ran),
                violated=violated,
                reason="" if ran else run.reason,
            ).model_copy(update={"qualifier": run.qualifier})
        )
    return checks
