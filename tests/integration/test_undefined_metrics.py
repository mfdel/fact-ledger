"""Acceptance tests for S1-03: keep an observation with an undefined metric.

CLI-level tests (``fact-ledger metrics undefined``) live in
``tests/integration/test_cli_metrics_undefined.py``.
"""

from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine

from fact_ledger.domain import Derivation, Dictionary, Observation
from fact_ledger.store.facts import FactStore, FactStoreError
from fact_ledger.store.yaml_files import load_dictionary
from tests.factories import valid_observation_fields

pytestmark = pytest.mark.integration

DICTIONARY_DIR = Path(__file__).resolve().parents[2] / "data" / "dictionary"


def _observation(**overrides: Any) -> Observation:
    return Observation(**{**valid_observation_fields(), **overrides})


@pytest.fixture(scope="module")
def dictionary() -> Dictionary:
    return load_dictionary(DICTIONARY_DIR)


def test_observation_with_an_undefined_metric_id_saves_and_reloads_unchanged(
    migrated_engine: Engine, dictionary: Dictionary
) -> None:
    store = FactStore(migrated_engine, identity_ids=dictionary.identity_ids)
    observation = _observation(
        metric_id="pipeline_coverage",  # not in data/dictionary/metrics.yaml
        stated_label="Pipeline coverage ratio",
    )

    store.add_many([observation])
    loaded = store.get(observation.observation_id)

    assert loaded == observation
    assert loaded is not None
    assert loaded.metric_id == "pipeline_coverage"
    assert loaded.stated_label == "Pipeline coverage ratio"
    assert [item.metric_id for item in dictionary.undefined_metrics([loaded])] == [
        "pipeline_coverage"
    ]


def test_ambiguous_observation_with_one_undefined_candidate_saves_and_that_id_is_undefined(
    migrated_engine: Engine, dictionary: Dictionary
) -> None:
    store = FactStore(migrated_engine, identity_ids=dictionary.identity_ids)
    observation = _observation(
        metric_id="revenue_unspecified",  # a defined umbrella id
        stated_label="revenue",
        definition_status="ambiguous",
        candidate_metric_ids=("mrr", "net_new_arr_per_rep"),  # the second candidate is undefined
    )

    store.add_many([observation])
    loaded = store.get(observation.observation_id)

    assert loaded is not None
    assert loaded.candidate_metric_ids == ("mrr", "net_new_arr_per_rep")
    undefined_ids = {item.metric_id for item in dictionary.undefined_metrics([loaded])}
    assert undefined_ids == {"net_new_arr_per_rep"}


def test_a_derivation_with_an_identity_id_not_in_identities_yaml_is_rejected_and_named(
    migrated_engine: Engine, dictionary: Dictionary
) -> None:
    # Real identities.yaml content, not a literal placeholder set.
    store = FactStore(migrated_engine, identity_ids=dictionary.identity_ids)
    observation = _observation(
        derivation=Derivation(identity_id="not_a_real_identity", input_observation_ids=("obs-mrr",))
    )

    with pytest.raises(FactStoreError, match="not_a_real_identity"):
        store.add_many([observation])

    assert store.get(observation.observation_id) is None
