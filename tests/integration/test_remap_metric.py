"""Acceptance tests for ``FactStore.remap_metric`` (S1-07).

CLI-level behaviour (``metrics map``, ``metrics add``) is covered by
``test_cli_metrics_classify.py``. These tests exercise the store method directly.
"""

from typing import Any

import pytest
from sqlalchemy import Engine, select

from fact_ledger.domain import Observation
from fact_ledger.store.facts import FactStore, FactStoreError, metric_id_changes
from tests.factories import valid_observation_fields

pytestmark = pytest.mark.integration

IDENTITY_IDS = {"arr_from_mrr"}  # real id from data/dictionary/identities.yaml


def _observation(**overrides: Any) -> Observation:
    return Observation(**{**valid_observation_fields(), **overrides})


def _change_rows(engine: Engine) -> list[tuple[str, str, str]]:
    with engine.connect() as connection:
        rows = connection.execute(
            select(
                metric_id_changes.c.observation_id,
                metric_id_changes.c.old_metric_id,
                metric_id_changes.c.new_metric_id,
            )
        ).all()
    return [(r.observation_id, r.old_metric_id, r.new_metric_id) for r in rows]


def test_remap_updates_metric_id_and_records_one_change_row_per_observation(
    migrated_engine: Engine,
) -> None:
    store = FactStore(migrated_engine, identity_ids=IDENTITY_IDS)
    moved_1 = _observation(observation_id="obs-1", metric_id="run_rate_revenue")
    moved_2 = _observation(observation_id="obs-2", metric_id="run_rate_revenue")
    unrelated = _observation(observation_id="obs-3", metric_id="mrr")
    store.add_many([moved_1, moved_2, unrelated])

    changed = store.remap_metric("run_rate_revenue", "arr_run_rate")

    assert set(changed) == {"obs-1", "obs-2"}
    for observation_id in ("obs-1", "obs-2"):
        loaded = store.get(observation_id)
        assert loaded is not None
        assert loaded.metric_id == "arr_run_rate"
        assert loaded.stated_label == valid_observation_fields()["stated_label"]

    untouched = store.get("obs-3")
    assert untouched is not None
    assert untouched.metric_id == "mrr"

    rows = _change_rows(migrated_engine)
    assert sorted(r[:2] for r in rows if r[2] == "arr_run_rate") == [
        ("obs-1", "run_rate_revenue"),
        ("obs-2", "run_rate_revenue"),
    ]


def test_remap_replaces_a_candidate_id_keeps_order_and_drops_a_repeat(
    migrated_engine: Engine,
) -> None:
    store = FactStore(migrated_engine, identity_ids=IDENTITY_IDS)
    ambiguous = _observation(
        metric_id="revenue_unspecified",
        stated_label="revenue",
        definition_status="ambiguous",
        candidate_metric_ids=("run_rate_revenue", "arr_run_rate", "mrr"),
    )
    store.add_many([ambiguous])

    store.remap_metric("run_rate_revenue", "arr_run_rate")

    loaded = store.get(ambiguous.observation_id)
    assert loaded is not None
    assert loaded.metric_id == "revenue_unspecified"  # metric_id itself was not old_metric_id
    assert loaded.definition_status == "ambiguous"
    assert loaded.candidate_metric_ids == ("arr_run_rate", "mrr")  # repeat dropped, order kept


def test_remap_into_a_rows_own_candidate_fails_and_names_the_row(migrated_engine: Engine) -> None:
    store = FactStore(migrated_engine, identity_ids=IDENTITY_IDS)
    ambiguous = _observation(
        observation_id="obs-conflict",
        metric_id="run_rate_revenue",
        stated_label="revenue",
        definition_status="ambiguous",
        candidate_metric_ids=("arr_run_rate", "mrr"),
    )
    store.add_many([ambiguous])

    with pytest.raises(FactStoreError, match="obs-conflict"):
        store.remap_metric("run_rate_revenue", "arr_run_rate")

    loaded = store.get("obs-conflict")
    assert loaded == ambiguous  # the transaction rolled back: the row is exactly as it was
    assert _change_rows(migrated_engine) == []


def test_remap_of_an_id_no_row_uses_returns_an_empty_list_and_changes_nothing(
    migrated_engine: Engine,
) -> None:
    store = FactStore(migrated_engine, identity_ids=IDENTITY_IDS)
    kept = _observation(metric_id="mrr")
    store.add_many([kept])

    changed = store.remap_metric("no_such_metric_id", "arr_run_rate")

    assert changed == []
    assert store.get(kept.observation_id) == kept
    assert _change_rows(migrated_engine) == []
