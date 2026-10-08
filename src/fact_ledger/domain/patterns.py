"""The A3 pattern checks: conspicuous absence and projection discontinuity."""

from collections.abc import Iterable
from datetime import date
from decimal import Decimal
from itertools import groupby
from typing import NamedTuple

from fact_ledger.domain.checks import build_index, derive, year_before
from fact_ledger.domain.enums import DefinitionStatus, FindingKind
from fact_ledger.domain.models import Dictionary, Observation, Qualifier
from fact_ledger.domain.paths import Finding, direct_path, period_of, qualifier_of, rank
from fact_ledger.domain.rules import PROJECTION_MARGIN, PROJECTION_METRICS

_YEAR = 12


def _months(start: date, end: date) -> int:
    return (end.year - start.year) * 12 + end.month - start.month


def cagr(start: Observation, end: Observation) -> Decimal:
    """The yearly growth rate in points. A span that is not a whole number of years is annualized.

    The caller gives a span of 12 months or more and positive values.
    """
    months = _months(start.period_end, end.period_end)
    return 100 * ((end.value / start.value) ** (Decimal(_YEAR) / months) - 1)


def _usable(row: Observation) -> bool:
    return row.definition_status is DefinitionStatus.RESOLVED and not row.is_derived


def _projection_finding(
    plan: Observation, actuals: list[Observation], dictionary: Dictionary
) -> Finding | None:
    like = [
        r
        for r in actuals
        if (r.metric_id, r.period_type, r.unit, r.currency, qualifier_of(r))
        == (plan.metric_id, plan.period_type, plan.unit, plan.currency, Qualifier())
        and r.period_end < plan.period_end
    ]
    # The best-ranked row (D2.5) at each date: the sort puts it last, so it wins the dict.
    best = {
        r.period_end: r
        for r in sorted(like, key=lambda r: rank(direct_path(r, dictionary)), reverse=True)
    }
    # `last` is the latest actual row that has an actual row 12 months before it.
    day = next((d for d in sorted(best, reverse=True) if year_before(d) in best), None)
    if day is None:
        return None
    first, last = best[year_before(day)], best[day]
    if _months(day, plan.period_end) < _YEAR or min(first.value, last.value, plan.value) <= 0:
        return None
    if cagr(last, plan) - cagr(first, last) <= PROJECTION_MARGIN:
        return None
    return Finding(
        kind=FindingKind.PROJECTION,
        divergence=None,
        entity_id=plan.entity_id,
        subject=plan.metric_id,
        period=period_of(plan),
        left=direct_path(plan, dictionary),
        right=(direct_path(first, dictionary), direct_path(last, dictionary)),
    )


class Absence(NamedTuple):
    entity_id: str
    metric_id: str


def expected_metrics(dictionary: Dictionary, sector: str) -> frozenset[str]:
    """The metrics that ``expected_for`` marks for the sector. An empty result is a typo, and
    an empty set would hide every absence, so it raises.
    """
    expected = frozenset(m.metric_id for m in dictionary.metrics if sector in m.expected_for)
    if not expected:
        codes = sorted({c for m in dictionary.metrics for c in m.expected_for})
        raise ValueError(f"unknown sector {sector!r}: expected_for holds {', '.join(codes)}")
    return expected


def _present(actuals: list[Observation], dictionary: Dictionary) -> set[str]:
    """A row or a fill of any qualifier makes a metric present (S4 decision 17)."""
    paths = {r.observation_id: direct_path(r, dictionary) for r in actuals}
    present: set[str] = set()
    for index in build_index(actuals, paths, dictionary).values():
        present |= {m for m, _ in index.resolved}
        present |= {p.metric_id for p in derive(index, dictionary)}
    return present


def patterns(
    observations: Iterable[Observation], dictionary: Dictionary, sector: str | None
) -> tuple[list[Absence], list[Finding]]:
    """Run the pattern checks on every entity. Rows are sorted first, so the input order never
    changes the result. A row with an undefined metric has no dimension, so it is out, as in
    ``validate``. With no sector, the absence check does not run.
    """
    expected = expected_metrics(dictionary, sector) if sector is not None else frozenset[str]()
    rows = sorted(observations, key=lambda o: (o.entity_id, o.observation_id))
    absences: list[Absence] = []
    findings: list[Finding] = []
    for entity_id, group in groupby(rows, key=lambda o: o.entity_id):
        # Grouped before the undefined-metric filter, so an entity whose rows are all undefined
        # still gets an empty present set and every expected metric reports as absent.
        entity_rows = [o for o in group if o.metric_id in dictionary.metric_ids]
        every_actual = [r for r in entity_rows if not r.is_projection]
        actuals = [r for r in every_actual if _usable(r)]
        if expected:
            missing = expected - _present(every_actual, dictionary)
            absences += [Absence(entity_id, m) for m in sorted(missing)]
        for plan in entity_rows:
            if (
                plan.is_projection
                and plan.metric_id in PROJECTION_METRICS
                and _usable(plan)
                and qualifier_of(plan) == Qualifier()
                and (finding := _projection_finding(plan, actuals, dictionary))
            ):
                findings.append(finding)
    return absences, findings
