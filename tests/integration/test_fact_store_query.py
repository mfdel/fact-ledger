"""Acceptance tests for S1-04: look up facts by metric and period.

``Period`` is a named tuple (start, end, type). ``find`` matches
period_start, period_end and period_type exactly, because FY 2024, TTM to December 2024
and Q4 2024 share the same period_end.

Each row reads as a real fact: ARR (a stock) at one date, recognised revenue (a flow)
over a period.
"""

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import Engine

from fact_ledger.domain import Observation, Period, PeriodType
from fact_ledger.store.facts import FactStore
from tests.factories import valid_observation_fields

pytestmark = pytest.mark.integration

FY_2024 = Period(start=date(2024, 1, 1), end=date(2024, 12, 31), type=PeriodType.FY)
TTM_2024 = Period(start=date(2024, 1, 1), end=date(2024, 12, 31), type=PeriodType.TTM)
Q4_2024 = Period(start=date(2024, 10, 1), end=date(2024, 12, 31), type=PeriodType.QUARTER)
Q1_2024 = Period(start=date(2024, 1, 1), end=date(2024, 3, 31), type=PeriodType.QUARTER)


def _arr(observation_id: str, **overrides: Any) -> Observation:
    """ARR is a stock, so it is stated at one date: EUR 8m at 2024-12-31."""
    return Observation(
        **{**valid_observation_fields(), "observation_id": observation_id, **overrides}
    )


def _revenue(observation_id: str, period: Period, **overrides: Any) -> Observation:
    """Recognised revenue is a flow, so it is stated over a period: EUR 2m in that period."""
    fields = {
        **valid_observation_fields(),
        "observation_id": observation_id,
        "metric_id": "revenue_recognised",
        "stated_label": "Revenue",
        "value": Decimal(2000000),
        "stated_precision": None,
        "period_start": period.start,
        "period_end": period.end,
        "period_type": period.type,
        "as_of_date": period.end,
    }
    return Observation(**{**fields, **overrides})


def _store(engine: Engine) -> FactStore:
    # No derived observations in these tests, so no identity id is ever needed.
    return FactStore(engine, identity_ids=frozenset())


def test_find_by_period_returns_only_the_matching_period(migrated_engine: Engine) -> None:
    store = _store(migrated_engine)
    q1 = _revenue("obs-q1", Q1_2024)
    q4_deck = _revenue("obs-q4-deck", Q4_2024)
    q4_board_pack = _revenue(
        "obs-q4-board-pack", Q4_2024, document_id="board-pack-2025-01", locator="board.pdf#p2"
    )
    store.add_many([q1, q4_deck, q4_board_pack])

    found = store.find(entity_id="acme", metric_id="revenue_recognised", period=Q4_2024)

    assert {obs.observation_id for obs in found} == {"obs-q4-deck", "obs-q4-board-pack"}


def test_conflicting_values_for_the_same_period_are_never_merged(migrated_engine: Engine) -> None:
    """Design rule: never average two conflicting values. Disagreement is the product."""
    store = _store(migrated_engine)
    from_management = _revenue("obs-management", Q4_2024, value=Decimal(2000000))
    from_press = _revenue(
        "obs-press",
        Q4_2024,
        value=Decimal(2400000),
        stated_label="Q4 sales",
        origin_id="techpress",
        document_id="techpress-article-2025-02",
        locator="https://techpress.example/acme-q4",
        source_type="press",
        reliability=2,
        bias_direction="unknown",
    )
    store.add_many([from_management, from_press])

    found = store.find(entity_id="acme", metric_id="revenue_recognised", period=Q4_2024)

    assert len(found) == 2
    assert {obs.value for obs in found} == {from_management.value, from_press.value}


def test_find_by_entity_id_alone_returns_every_observation_of_that_entity(
    migrated_engine: Engine,
) -> None:
    store = _store(migrated_engine)
    acme_arr = _arr("obs-acme-arr")
    acme_revenue = _revenue("obs-acme-revenue", Q1_2024)
    other_entity = _arr("obs-other", entity_id="beta", origin_id="beta-management")
    store.add_many([acme_arr, acme_revenue, other_entity])

    found = store.find(entity_id="acme")

    assert {obs.observation_id for obs in found} == {"obs-acme-arr", "obs-acme-revenue"}


def test_find_with_no_match_returns_an_empty_list_not_an_error(migrated_engine: Engine) -> None:
    store = _store(migrated_engine)
    store.add_many([_revenue("obs-q4", Q4_2024)])

    found = store.find(entity_id="acme", metric_id="revenue_recognised", period=Q1_2024)

    assert found == []


def test_find_with_no_filter_returns_every_observation(migrated_engine: Engine) -> None:
    """S1-03 (undefined-metric detection) reads the whole store this way."""
    store = _store(migrated_engine)
    one = _arr("obs-one")
    two = _arr("obs-two", entity_id="beta", origin_id="beta-management")
    store.add_many([one, two])

    found = store.find()

    assert {obs.observation_id for obs in found} == {"obs-one", "obs-two"}


def test_periods_sharing_an_end_date_are_not_confused(migrated_engine: Engine) -> None:
    """FY 2024, TTM to December 2024 and Q4 2024 all end on
    2024-12-31. FY and TTM also share the start. Only the full period tells them apart."""
    store = _store(migrated_engine)
    fy_row = _revenue("obs-fy", FY_2024, value=Decimal(7000000))
    ttm_row = _revenue("obs-ttm", TTM_2024, value=Decimal(7000000))
    q4_row = _revenue("obs-q4", Q4_2024)
    store.add_many([fy_row, ttm_row, q4_row])

    found = store.find(entity_id="acme", metric_id="revenue_recognised", period=FY_2024)

    assert [obs.observation_id for obs in found] == ["obs-fy"]


def test_find_results_are_ordered_deterministically(migrated_engine: Engine) -> None:
    """Order is entity_id, metric_id, period_end, period_start,
    observation_id. Not a rank by confidence."""
    store = _store(migrated_engine)
    # Inserted out of order on purpose: the store must sort, not echo insert order.
    beta_arr = _arr("obs-beta", entity_id="beta", origin_id="beta-management")
    acme_revenue_q1 = _revenue("obs-acme-revenue-q1", Q1_2024)
    acme_arr_z = _arr("obs-acme-arr-z")
    acme_arr_a = _arr("obs-acme-arr-a")
    store.add_many([beta_arr, acme_revenue_q1, acme_arr_z, acme_arr_a])

    found = store.find()

    assert [obs.observation_id for obs in found] == [
        "obs-acme-arr-a",
        "obs-acme-arr-z",
        "obs-acme-revenue-q1",
        "obs-beta",
    ]
