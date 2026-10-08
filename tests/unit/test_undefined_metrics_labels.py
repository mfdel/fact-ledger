"""Regression lock for ``Dictionary.undefined_metrics`` label handling (S1-03).

The CLI-level case moved to
``tests/integration/test_cli_metrics_undefined_labels.py`` (it needs a migrated database).
``tests/unit/test_undefined_metrics.py`` covers the rest of this behavior.
"""

from typing import Any

import pytest

from fact_ledger.domain import Dictionary, Observation
from tests.factories import valid_observation_fields

pytestmark = pytest.mark.unit


def _observation(**overrides: Any) -> Observation:
    return Observation(**{**valid_observation_fields(), **overrides})


def test_stated_labels_differing_only_by_case_are_kept_as_separate_entries() -> None:
    dictionary = Dictionary(metrics=(), identities=())
    observations = [
        _observation(observation_id="o1", metric_id="pipeline_coverage", stated_label="ARR"),
        _observation(observation_id="o2", metric_id="pipeline_coverage", stated_label="arr"),
    ]

    (result,) = dictionary.undefined_metrics(observations)

    assert result.stated_labels == ("ARR", "arr")  # exact-string, not casefold, distinctness
