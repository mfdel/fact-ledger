"""Acceptance tests for S1-02: persisting an Observation in the fact store."""

from collections.abc import Sequence
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import Connection, Engine

from fact_ledger.domain import Derivation, Observation
from fact_ledger.store.facts import FactStore, FactStoreError
from tests.factories import valid_observation_fields

pytestmark = pytest.mark.integration

IDENTITY_IDS = {"arr_from_mrr"}  # real id from data/dictionary/identities.yaml


def _observation(**overrides: Any) -> Observation:
    return Observation(**{**valid_observation_fields(), **overrides})


def test_saved_observation_round_trips_with_full_provenance(migrated_engine: Engine) -> None:
    store = FactStore(migrated_engine, identity_ids=IDENTITY_IDS)
    observation = _observation(
        stated_precision=Decimal(500000),
        origin_id="acme-management",
        document_id="deck-2025",
        locator="deck.pdf#p4",
        bias_direction="up",
    )
    store.add_many([observation])

    loaded = store.get(observation.observation_id)

    assert loaded == observation
    assert loaded is not None
    assert loaded.stated_precision == observation.stated_precision
    assert loaded.origin_id == observation.origin_id
    assert loaded.document_id == observation.document_id
    assert loaded.locator == observation.locator
    assert loaded.bias_direction == observation.bias_direction


def test_get_of_a_missing_id_returns_none(migrated_engine: Engine) -> None:
    store = FactStore(migrated_engine, identity_ids=IDENTITY_IDS)
    assert store.get("does-not-exist") is None


def test_ambiguous_candidate_metric_ids_round_trip_in_order(migrated_engine: Engine) -> None:
    store = FactStore(migrated_engine, identity_ids=IDENTITY_IDS)
    observation = _observation(
        metric_id="revenue_unspecified",
        stated_label="revenue",
        definition_status="ambiguous",
        candidate_metric_ids=("mrr", "arr", "bookings"),
    )
    store.add_many([observation])

    loaded = store.get(observation.observation_id)

    assert loaded is not None
    assert loaded.candidate_metric_ids == ("mrr", "arr", "bookings")


def test_derivation_round_trips_with_a_real_identity(migrated_engine: Engine) -> None:
    store = FactStore(migrated_engine, identity_ids=IDENTITY_IDS)
    mrr_observation = _observation(observation_id="obs-mrr", metric_id="mrr")
    derived = _observation(
        observation_id="obs-arr",
        derivation=Derivation(identity_id="arr_from_mrr", input_observation_ids=("obs-mrr",)),
    )
    store.add_many([mrr_observation, derived])

    loaded = store.get("obs-arr")

    assert loaded is not None
    assert loaded.derivation == derived.derivation


def test_duplicate_observation_id_already_in_the_store_is_rejected(migrated_engine: Engine) -> None:
    store = FactStore(migrated_engine, identity_ids=IDENTITY_IDS)
    observation = _observation()
    store.add_many([observation])

    with pytest.raises(FactStoreError, match=observation.observation_id):
        store.add_many([observation])

    # atomic: the rejected call left the original row exactly as it was
    assert store.get(observation.observation_id) == observation


def test_duplicate_observation_id_within_one_batch_is_rejected(migrated_engine: Engine) -> None:
    store = FactStore(migrated_engine, identity_ids=IDENTITY_IDS)
    first = _observation()
    second = _observation(metric_id="mrr")  # same observation_id, different content

    with pytest.raises(FactStoreError, match=first.observation_id):
        store.add_many([first, second])

    assert store.get(first.observation_id) is None


def test_add_many_is_atomic_when_one_row_is_a_duplicate(migrated_engine: Engine) -> None:
    store = FactStore(migrated_engine, identity_ids=IDENTITY_IDS)
    existing = _observation(observation_id="obs-existing")
    store.add_many([existing])
    fresh = _observation(observation_id="obs-fresh")

    with pytest.raises(FactStoreError):
        store.add_many([existing, fresh])

    assert store.get("obs-fresh") is None


def test_an_id_used_between_the_check_and_the_insert_is_still_named(
    migrated_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A concurrent writer can use an id after the duplicate check. The primary key then
    rejects the insert, and the error must still be a FactStoreError that names the id."""
    store = FactStore(migrated_engine, identity_ids=IDENTITY_IDS)
    rival = FactStore(migrated_engine, identity_ids=IDENTITY_IDS)
    observation = _observation()
    check = FactStore._reject_duplicates
    raced = False

    def check_then_race(
        self: FactStore, connection: Connection, batch: Sequence[Observation]
    ) -> None:
        nonlocal raced
        check(self, connection, batch)
        if self is store and not raced:
            raced = True
            rival.add_many([observation])

    monkeypatch.setattr(FactStore, "_reject_duplicates", check_then_race)

    with pytest.raises(FactStoreError, match=observation.observation_id):
        store.add_many([observation])


def test_unknown_identity_id_is_rejected_and_named(migrated_engine: Engine) -> None:
    store = FactStore(migrated_engine, identity_ids=IDENTITY_IDS)
    observation = _observation(
        derivation=Derivation(identity_id="not_a_real_identity", input_observation_ids=("obs-mrr",))
    )

    with pytest.raises(FactStoreError, match="not_a_real_identity"):
        store.add_many([observation])

    assert store.get(observation.observation_id) is None


def test_add_many_is_atomic_when_one_row_has_an_unknown_identity(migrated_engine: Engine) -> None:
    store = FactStore(migrated_engine, identity_ids=IDENTITY_IDS)
    good = _observation(observation_id="obs-good")
    unknown_identity = Derivation(
        identity_id="not_a_real_identity", input_observation_ids=("obs-mrr",)
    )
    bad = _observation(observation_id="obs-bad", derivation=unknown_identity)

    with pytest.raises(FactStoreError):
        store.add_many([good, bad])

    assert store.get("obs-good") is None


def test_value_keeps_trailing_zeros_after_a_round_trip(migrated_engine: Engine) -> None:
    """SQLite Numeric goes through float and drops trailing zeros."""
    store = FactStore(migrated_engine, identity_ids=IDENTITY_IDS)
    observation = _observation(value=Decimal("8.30"))
    store.add_many([observation])

    loaded = store.get(observation.observation_id)

    assert loaded is not None
    assert str(loaded.value) == "8.30"


def test_value_keeps_more_than_fifteen_significant_digits(migrated_engine: Engine) -> None:
    store = FactStore(migrated_engine, identity_ids=IDENTITY_IDS)
    exact = Decimal("123456789012345.678")  # 18 significant digits: beyond float precision
    observation = _observation(value=exact)
    store.add_many([observation])

    loaded = store.get(observation.observation_id)

    assert loaded is not None
    assert str(loaded.value) == str(exact)


def test_add_many_of_an_empty_batch_is_a_no_op(migrated_engine: Engine) -> None:
    store = FactStore(migrated_engine, identity_ids=IDENTITY_IDS)
    store.add_many([])  # an empty executemany insert fails in SQLite; the guard skips it
