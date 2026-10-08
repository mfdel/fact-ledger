"""Computation paths, findings and the pairwise ``compare`` of the A2 validator.

Pure domain records. A path is the derivation shape of architecture doc section 2.1 in memory:
nothing writes it to the store in S2.
"""

from decimal import Decimal

from fact_ledger.domain.enums import (
    CheckStatus,
    Dimension,
    DivergenceClass,
    FindingKind,
    PeriodType,
    StockOrFlow,
)
from fact_ledger.domain.models import (
    Dictionary,
    Identity,
    Metric,
    Observation,
    Period,
    Qualifier,
    _Frozen,
)
from fact_ledger.domain.rules import MIN_RELIABILITY, POLICY_BY_DIMENSION, RELATIVE_TOLERANCE

_WITHIN = frozenset({DivergenceClass.CORROBORATED, DivergenceClass.CONSISTENT})


class Reading(_Frozen):
    """How the report reads one stored ambiguous row (D2.6 to D2.8). Never written to the store.

    ``inferred`` with no ``sources`` is a direct reading. With ``sources`` it is inherited from
    the direct readings of its label group. A reading that is not inferred keeps its own D2.6
    match in ``metric_id`` and ``basis`` when it has one (a row in a label conflict).
    """

    observation: Observation
    inferred: bool
    metric_id: str | None = None
    basis: tuple[Observation, ...] = ()
    sources: tuple[Reading, ...] = ()
    reason: str = ""


class ComputationPath(_Frozen):
    """A direct observation, or a value that an identity computes from observed inputs."""

    metric_id: str
    period: Period
    value: Decimal
    unit: str
    currency: str | None
    precision: Decimal | None
    identity_id: str | None = None
    label_key: str | None = None
    observations: tuple[Observation, ...]
    reading: Reading | None = None
    qualifier: Qualifier = Qualifier()

    @property
    def origin_ids(self) -> frozenset[str]:
        return frozenset(o.effective_origin_id for o in self.observations)

    @property
    def reliability(self) -> int:
        """The weakest input (architecture doc 3.4)."""
        return min(o.reliability for o in self.observations)

    @property
    def inferred(self) -> bool:
        return self.reading is not None and self.reading.inferred

    @property
    def locators(self) -> tuple[str, ...]:
        return tuple(f"{o.document_id}#{o.locator}" for o in self.observations)

    @property
    def key(self) -> tuple[str, tuple[str, ...]]:
        return self.identity_id or "", tuple(o.observation_id for o in self.observations)


class Comparison(_Frozen):
    a: ComputationPath
    b: ComputationPath
    tolerance: Decimal | None  # None: no comparison ran, see reason
    divergence: DivergenceClass | None
    reason: str = ""


class Finding(_Frozen):
    """One question-worthy disagreement. It cites paths, never a merged value."""

    kind: FindingKind
    divergence: DivergenceClass | None
    entity_id: str
    subject: str
    period: Period
    left: ComputationPath
    right: tuple[ComputationPath, ...]
    assumption: str = ""  # a validity condition that no observed value tests (D4.3)


class CheckResult(_Frozen):
    """One status per identity, anchor period and qualifier (D4.2). A skip is never a pass."""

    identity_id: str
    entity_id: str
    period: Period | None  # None only when no evaluator exists for the identity
    status: CheckStatus
    reason: str = ""  # why not checked, or the assumption of a check that ran
    qualifier: Qualifier = Qualifier()


class Report(_Frozen):
    readings: tuple[Reading, ...]
    comparisons: tuple[Comparison, ...]
    findings: tuple[Finding, ...]
    checks: tuple[CheckResult, ...]


def period_of(row: Observation) -> Period:
    return Period(row.period_start, row.period_end, row.period_type)


def aligned_period(row: Observation, metric: Metric) -> Period:
    """D2.6: the ambiguity covers the period type too. "Revenue 2024" can be year-end ARR."""
    if metric.stock_or_flow is StockOrFlow.STOCK:
        return Period(row.period_end, row.period_end, PeriodType.POINT_IN_TIME)
    return period_of(row)


def text_key(label: str) -> str:
    return " ".join(label.casefold().split())


def qualifier_of(row: Observation) -> Qualifier:
    """The one place that reads a row's qualifier.
    ``text_key`` folds case and whitespace, so two spellings of one segment or region never
    split one group. A row with no segment and no region on the reported basis gives
    ``Qualifier()``, the group row every S1, S2 and S3 fixture has today.
    """
    return Qualifier(
        segment=text_key(row.segment) if row.segment else "",
        region=text_key(row.region) if row.region else "",
        basis=row.basis,
    )


def direct_path(
    row: Observation, dictionary: Dictionary, reading: Reading | None = None
) -> ComputationPath:
    metric_id, period = row.metric_id, period_of(row)
    if reading is not None and reading.inferred and reading.metric_id is not None:
        metric_id = reading.metric_id
        period = aligned_period(row, metric_of(dictionary, metric_id))
    return ComputationPath(
        metric_id=metric_id,
        period=period,
        value=row.value,
        unit=row.unit,
        currency=row.currency,
        precision=row.stated_precision,
        label_key=dictionary.alias_owner(row.stated_label) or text_key(row.stated_label),
        observations=(row,),
        reading=reading,
        qualifier=qualifier_of(row),
    )


def metric_of(dictionary: Dictionary, metric_id: str) -> Metric:
    return next(m for m in dictionary.metrics if m.metric_id == metric_id)


def identity_of(dictionary: Dictionary, identity_id: str) -> Identity:
    return next(i for i in dictionary.identities if i.identity_id == identity_id)


def rank(path: ComputationPath) -> tuple[Decimal, bool, str]:
    """D2.5 step 3: the most precise value first, then a direct observation, then the lower id."""
    return path.precision or Decimal(0), path.identity_id is not None, path.key[1][0]


def pair_tolerance(a: ComputationPath, b: ComputationPath, dimension: Dimension) -> Decimal:
    """D1.1: stated precisions add up. The relative term covers the same noise, so ``max``.

    The caller gives the dimension of the terms, not a policy: ``inequality`` has no value of its
    own (D1.2), and every dimension has one (D1.3).
    """
    precision = (a.precision or Decimal(0)) + (b.precision or Decimal(0))
    relative = RELATIVE_TOLERANCE[POLICY_BY_DIMENSION[dimension]]
    return max(precision, relative * max(abs(a.value), abs(b.value)))


def _classify(a: ComputationPath, b: ComputationPath, within: bool) -> DivergenceClass:
    """D2.4, the first rule that matches."""
    independent = a.origin_ids.isdisjoint(b.origin_ids)
    if within:
        corroborated = independent and not (a.inferred or b.inferred)
        return DivergenceClass.CORROBORATED if corroborated else DivergenceClass.CONSISTENT
    if min(a.reliability, b.reliability) < MIN_RELIABILITY:
        return DivergenceClass.UNRESOLVABLE
    if a.identity_id is None and b.identity_id is None and a.label_key != b.label_key:
        return DivergenceClass.DEFINITIONAL
    if a.origin_ids == b.origin_ids:
        return DivergenceClass.INCONSISTENT
    return DivergenceClass.CONTESTED if independent else DivergenceClass.UNRESOLVABLE


def compare(a: ComputationPath, b: ComputationPath, dimension: Dimension) -> Comparison:
    """Compare two paths of one metric (S2-01, S2-02). S2 never converts a currency."""
    reason = ""
    if a.period != b.period:
        reason = "period not aligned"
    elif a.currency != b.currency:
        reason = "currency differs"
    elif a.unit != b.unit:
        reason = "unit differs"
    if reason:
        return Comparison(a=a, b=b, tolerance=None, divergence=None, reason=reason)
    allowed = pair_tolerance(a, b, dimension)
    divergence = _classify(a, b, abs(a.value - b.value) <= allowed)
    return Comparison(a=a, b=b, tolerance=allowed, divergence=divergence)


def is_outside(comparison: Comparison) -> bool:
    return comparison.divergence is not None and comparison.divergence not in _WITHIN
