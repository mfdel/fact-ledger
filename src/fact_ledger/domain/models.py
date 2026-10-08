"""Core records: Observation, Metric, Identity (architecture doc sections 2.1 and 2.2).

Rules encoded here:
- ``as_of_date`` (what the value describes) and ``published_date`` (when it was said) are
  separate. No ordering is enforced between them: a projection is published before its as-of date.
- ``definition_status = ambiguous`` is a valid end state, but it must name its candidate metrics.
- A derived observation carries its identity and inputs, so asserted and computed values stay apart.
"""

from collections.abc import Iterable
from datetime import date
from decimal import Decimal
from typing import Annotated, NamedTuple, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from fact_ledger.domain.enums import (
    Basis,
    BiasDirection,
    DefinitionStatus,
    Dimension,
    PeriodType,
    SourceType,
    StockOrFlow,
    TolerancePolicy,
)

Id = Annotated[str, Field(min_length=1)]
# A value that says what an observation is, or where it is. An empty string says nothing.
Text = Annotated[str, Field(min_length=1)]
Reliability = Annotated[int, Field(ge=1, le=5)]


class Period(NamedTuple):
    """A query key for ``FactStore.find``.

    Matched exactly, never by ``end`` alone: FY 2024, Q4 2024 and a point-in-time row
    can share a ``period_end``, and a match on that column only would hide the
    period-alignment error the validator must find.
    """

    start: date
    end: date
    type: PeriodType


class Qualifier(NamedTuple):
    """One comparison group inside a metric and period: the
    comparison group, the D2.6 match index, the D2.7 label group and the check
    index all key on this. Build it with ``paths.qualifier_of``, never by hand from a row,
    so ``segment`` and ``region`` are always folded through ``text_key`` first.
    """

    segment: str = ""
    region: str = ""
    basis: Basis = Basis.REPORTED


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Derivation(_Frozen):
    identity_id: Id
    input_observation_ids: tuple[Id, ...] = Field(min_length=1)


class Observation(_Frozen):
    """One asserted value, about one entity, for one metric, over one period, from one origin."""

    observation_id: Id
    entity_id: Id
    metric_id: Id

    value: Decimal
    unit: Text
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    stated_precision: Decimal | None = Field(default=None, ge=0)

    period_start: date
    period_end: date
    period_type: PeriodType
    as_of_date: date
    published_date: date

    origin_id: Id
    # Who the source says the figure comes from, when that is not the source itself.
    cited_origin_id: Id | None = None
    document_id: Id
    locator: Text
    source_type: SourceType
    reliability: Reliability
    bias_direction: BiasDirection = BiasDirection.UNKNOWN

    # A qualifier is part of the identity of the fact, in the same way as
    # period_type and currency. None/None/reported is the group row on its own reported basis.
    segment: Text | None = None
    region: Text | None = None
    basis: Basis = Basis.REPORTED

    stated_label: Text
    definition_status: DefinitionStatus = DefinitionStatus.RESOLVED
    candidate_metric_ids: tuple[Id, ...] = ()

    derivation: Derivation | None = None
    confidence: Reliability | None = None

    @property
    def effective_origin_id(self) -> Id:
        return self.cited_origin_id or self.origin_id

    @model_validator(mode="after")
    def _check_invariants(self) -> Self:
        if self.period_end < self.period_start:
            msg = "period_end must not be before period_start"
            raise ValueError(msg)
        if self.period_type is PeriodType.POINT_IN_TIME and self.period_start != self.period_end:
            msg = "a point-in-time observation must have period_start == period_end"
            raise ValueError(msg)
        ambiguous = self.definition_status is DefinitionStatus.AMBIGUOUS
        if ambiguous and not self.candidate_metric_ids:
            msg = "an ambiguous observation must list candidate_metric_ids"
            raise ValueError(msg)
        if not ambiguous and self.candidate_metric_ids:
            msg = "candidate_metric_ids is only valid when definition_status is ambiguous"
            raise ValueError(msg)
        if ambiguous and self.metric_id in self.candidate_metric_ids:
            msg = "an ambiguous metric_id must not be one of its own candidate_metric_ids"
            raise ValueError(msg)
        if self.metric_id.endswith("_unspecified") and not ambiguous:
            msg = "a metric_id ending in _unspecified must have definition_status ambiguous"
            raise ValueError(msg)
        return self

    @property
    def is_derived(self) -> bool:
        return self.derivation is not None

    @property
    def is_projection(self) -> bool:
        """As-of after the last day of the publication month (S4 decision 18). The month, not the
        day: the extractor reads a cover date "March 2026" as 2026-03-01, and a day test would
        turn the actuals of that deck into plans.
        """
        as_of, published = self.as_of_date, self.published_date
        return (as_of.year, as_of.month) > (published.year, published.month)


class Metric(_Frozen):
    """A node in the metric dictionary."""

    metric_id: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]*$")]
    canonical_name: str
    aliases: tuple[str, ...] = ()
    dimension: Dimension
    stock_or_flow: StockOrFlow
    definition_note: str = ""
    expected_for: tuple[str, ...] = ()


class Identity(_Frozen):
    """A relation between metrics. One unknown term: a derivation. All terms observed: a check."""

    identity_id: Id
    equation: str
    terms: tuple[Id, ...] = Field(min_length=2)
    validity_conditions: tuple[str, ...] = ()
    tolerance_policy: TolerancePolicy


class UndefinedMetric(_Frozen):
    """A metric id used by an observation but not in the dictionary.

    Computed, never stored: a new dictionary entry removes the id from the next result.
    """

    metric_id: str
    observation_ids: tuple[str, ...]
    entity_ids: tuple[str, ...]
    stated_labels: tuple[str, ...]
    suggested_metric_ids: tuple[str, ...]


class Dictionary(_Frozen):
    """The metric dictionary and identity catalogue (architecture doc section 2.2)."""

    metrics: tuple[Metric, ...]
    identities: tuple[Identity, ...]

    @model_validator(mode="after")
    def _check_invariants(self) -> Self:
        metric_ids = [metric.metric_id for metric in self.metrics]
        if len(metric_ids) != len(set(metric_ids)):
            dupes = sorted({m for m in metric_ids if metric_ids.count(m) > 1})
            msg = f"duplicate metric_id: {', '.join(dupes)}"
            raise ValueError(msg)

        identity_ids = [identity.identity_id for identity in self.identities]
        if len(identity_ids) != len(set(identity_ids)):
            dupes = sorted({i for i in identity_ids if identity_ids.count(i) > 1})
            msg = f"duplicate identity_id: {', '.join(dupes)}"
            raise ValueError(msg)

        owner_by_alias: dict[str, str] = {}
        for metric in self.metrics:
            for alias in metric.aliases:
                key = alias.casefold()
                owner = owner_by_alias.get(key)
                if owner is not None and owner != metric.metric_id:
                    msg = f"alias {alias!r} is under both {owner!r} and {metric.metric_id!r}"
                    raise ValueError(msg)
                owner_by_alias[key] = metric.metric_id

        known_metric_ids = set(metric_ids)
        for identity in self.identities:
            for term in identity.terms:
                if term not in known_metric_ids:
                    msg = f"identity {identity.identity_id!r} has term {term!r}, not a metric id"
                    raise ValueError(msg)
                if term.endswith("_unspecified"):
                    msg = (
                        f"identity {identity.identity_id!r} uses umbrella id {term!r}: "
                        "umbrella ids are never used in a check or a derivation"
                    )
                    raise ValueError(msg)
        return self

    @property
    def metric_ids(self) -> frozenset[str]:
        return frozenset(metric.metric_id for metric in self.metrics)

    @property
    def identity_ids(self) -> frozenset[str]:
        return frozenset(identity.identity_id for identity in self.identities)

    def alias_owner(self, label: str) -> str | None:
        key = label.casefold()
        for metric in self.metrics:
            if key in {alias.casefold() for alias in metric.aliases}:
                return metric.metric_id
        return None

    def undefined_metrics(self, observations: Iterable[Observation]) -> list[UndefinedMetric]:
        """Metric ids used by ``observations`` but not in ``metric_ids``.

        Usage is ``metric_id`` or any ``candidate_metric_ids`` entry. Nothing is stored: this
        is a comparison against the current dictionary, run again on every call.
        """
        known = self.metric_ids
        observation_ids: dict[str, list[str]] = {}
        entity_ids: dict[str, set[str]] = {}
        stated_labels: dict[str, set[str]] = {}
        for observation in observations:
            for used in {observation.metric_id, *observation.candidate_metric_ids}:
                if used in known:
                    continue
                observation_ids.setdefault(used, []).append(observation.observation_id)
                entity_ids.setdefault(used, set()).add(observation.entity_id)
                stated_labels.setdefault(used, set()).add(observation.stated_label)

        results = []
        for metric_id in sorted(observation_ids):
            labels = tuple(sorted(stated_labels[metric_id]))
            suggestions = {
                owner for label in labels if (owner := self.alias_owner(label)) is not None
            }
            results.append(
                UndefinedMetric(
                    metric_id=metric_id,
                    observation_ids=tuple(observation_ids[metric_id]),
                    entity_ids=tuple(sorted(entity_ids[metric_id])),
                    stated_labels=labels,
                    suggested_metric_ids=tuple(sorted(suggestions)),
                )
            )
        return results
