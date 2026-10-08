"""Acceptance tests for ``fact-ledger facts show`` (S1-05).

AC 5 (ambiguous ``definition_status`` and ``candidate_metric_ids``) is also relied on by
S1-06 AC 4.
"""

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from fact_ledger.cli import app
from fact_ledger.domain import Observation
from fact_ledger.store.facts import FactStore
from tests.factories import valid_observation_fields

pytestmark = pytest.mark.integration

HEADER = [
    "observation_id",
    "metric_id",
    "period_start",
    "period_end",
    "period_type",
    "value",
    "unit",
    "origin_id",
    "locator",
    "definition_status",
    "candidate_metric_ids",
]


def _observation(**overrides: Any) -> Observation:
    return Observation(**{**valid_observation_fields(), **overrides})


def _rows(stdout: str) -> list[list[str]]:
    return [line.split("\t") for line in stdout.splitlines()[1:]]


def _row_for(stdout: str, observation_id: str) -> list[str]:
    (row,) = (row for row in _rows(stdout) if row[0] == observation_id)
    return row


def test_two_metrics_over_two_periods_print_one_row_per_observation(store: FactStore) -> None:
    store.add_many(
        [
            _observation(
                observation_id="o-arr-1",
                metric_id="arr",
                period_start=date(2024, 12, 31),
                period_end=date(2024, 12, 31),
                value=Decimal(8000000),
                origin_id="acme-management",
                locator="deck.pdf#p4",
            ),
            _observation(
                observation_id="o-mrr-1",
                metric_id="mrr",
                period_start=date(2024, 12, 31),
                period_end=date(2024, 12, 31),
                value=Decimal(650000),
                origin_id="acme-management",
                locator="deck.pdf#p5",
            ),
            _observation(
                observation_id="o-arr-2",
                metric_id="arr",
                period_start=date(2025, 3, 31),
                period_end=date(2025, 3, 31),
                value=Decimal(9000000),
                origin_id="acme-management",
                locator="deck.pdf#p6",
            ),
            _observation(
                observation_id="o-mrr-2",
                metric_id="mrr",
                period_start=date(2025, 3, 31),
                period_end=date(2025, 3, 31),
                value=Decimal(720000),
                origin_id="acme-management",
                locator="deck.pdf#p7",
            ),
        ]
    )

    result = CliRunner().invoke(app, ["facts", "show", "acme"])

    assert result.exit_code == 0
    header, *data_rows = result.stdout.splitlines()
    assert header.split("\t") == HEADER
    assert len(data_rows) == 4

    row = _row_for(result.stdout, "o-arr-2")
    assert row[1] == "arr"
    assert row[2] == "2025-03-31"
    assert row[3] == "2025-03-31"
    assert row[4] == "point_in_time"
    assert row[5] == "9000000"
    assert row[6] == "EUR"
    assert row[7] == "acme-management"
    assert row[8] == "deck.pdf#p6"


def test_disagreeing_observations_for_the_same_entity_metric_period_both_print(
    store: FactStore,
) -> None:
    store.add_many(
        [
            _observation(
                observation_id="o-a",
                metric_id="arr",
                origin_id="acme-management",
                value=Decimal(8000000),
            ),
            _observation(
                observation_id="o-b",
                metric_id="arr",
                origin_id="acme-press",
                value=Decimal(7500000),
            ),
        ]
    )

    result = CliRunner().invoke(app, ["facts", "show", "acme"])

    assert result.exit_code == 0
    data_rows = _rows(result.stdout)
    assert len(data_rows) == 2
    values = {row[0]: row[5] for row in data_rows}
    assert values == {"o-a": "8000000", "o-b": "7500000"}


def test_entity_with_no_observations_prints_message_and_exits_zero(cli_env: Path) -> None:
    result = CliRunner().invoke(app, ["facts", "show", "acme"])

    assert result.exit_code == 0
    assert result.stdout.strip() == "No facts found for acme."


def test_never_used_entity_id_matches_the_no_observations_case(store: FactStore) -> None:
    store.add_many([_observation(observation_id="o-beta", entity_id="beta")])

    result = CliRunner().invoke(app, ["facts", "show", "ghost"])

    assert result.exit_code == 0
    assert result.stdout.strip() == "No facts found for ghost."


def test_ambiguous_observation_prints_status_and_candidate_metric_ids(store: FactStore) -> None:
    store.add_many(
        [
            _observation(
                observation_id="o-ambiguous",
                metric_id="revenue_unspecified",
                definition_status="ambiguous",
                candidate_metric_ids=("arr", "mrr"),
            )
        ]
    )

    result = CliRunner().invoke(app, ["facts", "show", "acme"])

    assert result.exit_code == 0
    row = _row_for(result.stdout, "o-ambiguous")
    assert row[9] == "ambiguous"
    assert "arr" in row[10]
    assert "mrr" in row[10]


def test_value_prints_with_its_exact_stated_digits(store: FactStore) -> None:
    store.add_many([_observation(observation_id="o-precise", value=Decimal("8.30"))])

    result = CliRunner().invoke(app, ["facts", "show", "acme"])

    assert result.exit_code == 0
    row = _row_for(result.stdout, "o-precise")
    assert row[5] == "8.30"


def test_observations_of_another_entity_are_not_printed(store: FactStore) -> None:
    store.add_many(
        [
            _observation(observation_id="o-acme", entity_id="acme"),
            _observation(observation_id="o-beta", entity_id="beta"),
        ]
    )

    result = CliRunner().invoke(app, ["facts", "show", "acme"])

    assert result.exit_code == 0
    assert {row[0] for row in _rows(result.stdout)} == {"o-acme"}
