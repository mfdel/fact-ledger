"""``Dictionary.undefined_metrics`` on literal observations.

Ordering and distinctness rules only: the store-backed acceptance tests live in
``tests/integration/test_undefined_metrics.py``.
"""

from typing import Any

import pytest

from fact_ledger.domain import Dictionary, Observation
from tests.factories import make_metric, valid_observation_fields

pytestmark = pytest.mark.unit


def _observation(**overrides: Any) -> Observation:
    return Observation(**{**valid_observation_fields(), **overrides})


# Two defined metrics and one umbrella metric, so an undefined id must be told apart from these.
DICTIONARY = Dictionary(
    metrics=(
        make_metric("arr", aliases=("ARR",)),
        make_metric("mrr"),
        make_metric("revenue_unspecified", aliases=("revenue",)),
    ),
    identities=(),
)


def test_no_undefined_metrics_when_every_id_is_in_the_dictionary() -> None:
    observation = _observation(metric_id="arr")
    assert DICTIONARY.undefined_metrics([observation]) == []


def test_result_is_sorted_by_metric_id() -> None:
    observations = [
        _observation(observation_id="o1", metric_id="zzz_undefined"),
        _observation(observation_id="o2", metric_id="aaa_undefined"),
    ]
    result = DICTIONARY.undefined_metrics(observations)
    assert [item.metric_id for item in result] == ["aaa_undefined", "zzz_undefined"]


def test_a_candidate_metric_id_counts_as_usage_even_when_metric_id_is_defined() -> None:
    # revenue_unspecified is a defined umbrella id, so only the undefined candidate is listed.
    observation = _observation(
        metric_id="revenue_unspecified",
        definition_status="ambiguous",
        candidate_metric_ids=("mrr", "pipeline_coverage"),
    )
    result = DICTIONARY.undefined_metrics([observation])
    assert [item.metric_id for item in result] == ["pipeline_coverage"]


def test_a_repeated_candidate_id_counts_its_observation_once() -> None:
    observation = _observation(
        metric_id="revenue_unspecified",
        definition_status="ambiguous",
        candidate_metric_ids=("pipeline_coverage", "pipeline_coverage"),
    )
    (result,) = DICTIONARY.undefined_metrics([observation])
    assert result.observation_ids == (observation.observation_id,)


def test_an_umbrella_id_that_is_defined_is_never_listed_as_undefined() -> None:
    observation = _observation(
        metric_id="revenue_unspecified",
        definition_status="ambiguous",
        candidate_metric_ids=("mrr",),
    )
    result = DICTIONARY.undefined_metrics([observation])
    assert result == []


def test_observation_ids_keep_store_order_but_entity_ids_and_labels_are_distinct_and_sorted() -> (
    None
):
    observations = [
        _observation(
            observation_id="o3", entity_id="zeta", metric_id="pipeline_coverage", stated_label="X"
        ),
        _observation(
            observation_id="o1", entity_id="acme", metric_id="pipeline_coverage", stated_label="X"
        ),
        _observation(
            observation_id="o2", entity_id="acme", metric_id="pipeline_coverage", stated_label="Y"
        ),
    ]
    (result,) = DICTIONARY.undefined_metrics(observations)
    assert result.observation_ids == ("o3", "o1", "o2")  # input order, not sorted
    assert result.entity_ids == ("acme", "zeta")
    assert result.stated_labels == ("X", "Y")  # both distinct and sorted


def test_suggested_metric_ids_are_the_distinct_alias_owners_of_the_stated_labels() -> None:
    observations = [
        _observation(observation_id="o1", metric_id="pipeline_coverage", stated_label="ARR"),
        _observation(observation_id="o2", metric_id="pipeline_coverage", stated_label="arr"),
        _observation(
            observation_id="o3", metric_id="pipeline_coverage", stated_label="no alias match"
        ),
    ]
    (result,) = DICTIONARY.undefined_metrics(observations)
    assert result.suggested_metric_ids == ("arr",)  # distinct, and a non-match adds nothing
