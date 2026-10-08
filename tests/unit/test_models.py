from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from fact_ledger.domain import DefinitionStatus, Derivation, Observation

pytestmark = pytest.mark.unit


def test_valid_observation_round_trips_through_json(observation_fields: dict[str, Any]) -> None:
    observation = Observation(**observation_fields)
    assert Observation.model_validate_json(observation.model_dump_json()) == observation


def test_value_keeps_decimal_precision(observation_fields: dict[str, Any]) -> None:
    observation = Observation(**{**observation_fields, "value": "8000000.10"})
    assert observation.value == Decimal("8000000.10")


def test_projection_may_be_published_before_its_as_of_date(
    observation_fields: dict[str, Any],
) -> None:
    fields = {**observation_fields, "as_of_date": date(2027, 12, 31)}
    fields |= {"period_start": date(2027, 12, 31), "period_end": date(2027, 12, 31)}
    assert Observation(**fields).published_date < Observation(**fields).as_of_date


def test_period_end_before_start_is_rejected(observation_fields: dict[str, Any]) -> None:
    fields = {**observation_fields, "period_type": "fy", "period_start": date(2024, 12, 31)}
    fields["period_end"] = date(2024, 1, 1)
    with pytest.raises(ValidationError, match="period_end"):
        Observation(**fields)


def test_point_in_time_needs_a_single_date(observation_fields: dict[str, Any]) -> None:
    fields = {**observation_fields, "period_start": date(2024, 1, 1)}
    with pytest.raises(ValidationError, match="point-in-time"):
        Observation(**fields)


def test_ambiguous_definition_is_a_valid_end_state(observation_fields: dict[str, Any]) -> None:
    observation = Observation(
        **{
            **observation_fields,
            "metric_id": "revenue_unspecified",
            "stated_label": "revenue",
            "definition_status": "ambiguous",
            "candidate_metric_ids": ("arr", "revenue_recognised"),
        }
    )
    assert observation.definition_status is DefinitionStatus.AMBIGUOUS


def test_ambiguous_definition_must_name_candidates(observation_fields: dict[str, Any]) -> None:
    with pytest.raises(ValidationError, match="candidate_metric_ids"):
        Observation(**{**observation_fields, "definition_status": "ambiguous"})


def test_candidates_are_only_valid_when_ambiguous(observation_fields: dict[str, Any]) -> None:
    with pytest.raises(ValidationError, match="only valid"):
        Observation(**{**observation_fields, "candidate_metric_ids": ("arr",)})


def test_ambiguous_metric_id_must_not_be_in_its_own_candidates(
    observation_fields: dict[str, Any],
) -> None:
    """Without this, find(metric_id=...) can resolve an ambiguous
    row silently, which architecture doc section 2.1 forbids."""
    with pytest.raises(ValidationError, match="candidate_metric_ids"):
        Observation(
            **{
                **observation_fields,
                "metric_id": "revenue_unspecified",
                "stated_label": "revenue",
                "definition_status": "ambiguous",
                "candidate_metric_ids": ("revenue_unspecified", "arr"),
            }
        )


def test_unspecified_metric_id_must_be_ambiguous(observation_fields: dict[str, Any]) -> None:
    """An umbrella id (suffix ``_unspecified``) names a definition that is not yet resolved,
    so a resolved row carrying it is a contradiction."""
    with pytest.raises(ValidationError, match="ambiguous"):
        Observation(**{**observation_fields, "metric_id": "revenue_unspecified"})


def test_derived_observation_keeps_its_inputs(observation_fields: dict[str, Any]) -> None:
    derivation = Derivation(identity_id="arr_from_mrr", input_observation_ids=("obs-mrr",))
    observation = Observation(**{**observation_fields, "derivation": derivation})
    assert observation.is_derived
    assert not Observation(**observation_fields).is_derived


@pytest.mark.parametrize("field", ["unit", "locator", "stated_label"])
def test_empty_text_fields_are_rejected(observation_fields: dict[str, Any], field: str) -> None:
    with pytest.raises(ValidationError, match=field):
        Observation(**{**observation_fields, field: ""})


@pytest.mark.parametrize("reliability", [0, 6])
def test_reliability_is_one_to_five(observation_fields: dict[str, Any], reliability: int) -> None:
    with pytest.raises(ValidationError):
        Observation(**{**observation_fields, "reliability": reliability})


def test_observation_is_immutable(observation_fields: dict[str, Any]) -> None:
    observation = Observation(**observation_fields)
    with pytest.raises(ValidationError):
        observation.value = Decimal(1)  # type: ignore[misc]


@pytest.mark.parametrize(
    ("published", "as_of", "expected"),
    [
        (date(2026, 3, 1), date(2026, 3, 31), False),  # a cover month read as its first day
        (date(2026, 3, 31), date(2026, 3, 31), False),
        (date(2026, 3, 15), date(2026, 2, 28), False),
        (date(2026, 3, 31), date(2026, 4, 1), True),
        (date(2025, 3, 1), date(2025, 12, 31), True),
        (date(2025, 12, 15), date(2026, 1, 1), True),
    ],
)
def test_projection_is_an_as_of_date_after_the_month_of_publication(
    observation_fields: dict[str, Any], published: date, as_of: date, expected: bool
) -> None:
    fields = {**observation_fields, "published_date": published, "as_of_date": as_of}
    fields |= {"period_start": as_of, "period_end": as_of}
    assert Observation(**fields).is_projection is expected
