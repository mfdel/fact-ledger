"""Acceptance tests for ``fact-ledger validate`` (S2-07)."""

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner, Result

from fact_ledger.cli import app
from fact_ledger.domain import Observation
from fact_ledger.store.facts import FactStore
from fact_ledger.store.yaml_files import read_transcript

pytestmark = pytest.mark.integration

NIMBUS = {
    o.observation_id: o
    for o in read_transcript(
        Path(__file__).resolve().parents[1] / "fixtures/transcripts/synthetic_deck.yaml"
    )
}


def _load(store: FactStore, *extra: Observation, **changes: dict[str, Any]) -> None:
    rows = dict(NIMBUS)
    for row_id, update in changes.items():
        rows[row_id] = Observation(**(NIMBUS[row_id].model_dump() | update))
    rows |= {o.observation_id: o for o in extra}
    store.add_many(list(rows.values()))


def _run(*args: str) -> Result:
    return CliRunner().invoke(app, ["validate", *args])


def _table(result: Result) -> list[dict[str, str]]:
    header, *lines = result.stdout.splitlines()
    return [dict(zip(header.split("\t"), line.split("\t"), strict=True)) for line in lines]


def test_nimbus_prints_one_row_per_finding(store: FactStore) -> None:
    _load(store)
    result = _run("nimbus")
    assert result.exit_code == 0
    first, second = _table(result)
    assert (first["kind"], first["class"], first["subject"]) == (
        "divergence",
        "inconsistent",
        "arr",
    )
    assert (first["period_start"], first["period_end"], first["period_type"]) == (
        "2024-12-31",
        "2024-12-31",
        "point_in_time",
    )
    assert first["left"].startswith("EUR 7,450,000 on p14 appendix table")
    assert first["right"].startswith("EUR 8,064,000 on p4 chart")
    assert first["question"].endswith("what explains the difference of EUR 614,000?")
    assert (second["kind"], second["subject"]) == ("ambiguity", "revenue_unspecified")
    assert "Checks: 5 held, 1 violated, 5 not checked. Use --checks to list them." in result.stderr
    assert "Ambiguous rows: 0 inferred, 1 still ambiguous." in result.stderr


@pytest.mark.parametrize("entity_id", ["nimbus-clean", "never-used"])
def test_no_findings_prints_a_message(store: FactStore, entity_id: str) -> None:
    store.add_many([NIMBUS["nimbus-02"].model_copy(update={"entity_id": "nimbus-clean"})])
    result = _run(entity_id)
    assert (result.exit_code, result.stdout) == (0, f"No findings for {entity_id}.\n")


def test_an_invariant_and_an_inferred_reading_print_without_resolving_the_row(
    store: FactStore,
) -> None:
    exact = Observation(
        **(
            NIMBUS["nimbus-02"].model_dump()
            | {
                "observation_id": "press-arr",
                "value": Decimal(8000000),
                "stated_precision": None,
                "origin_id": "techdaily",
                "document_id": "techdaily-2025-02",
                "source_type": "press",
                "reliability": 2,
                "stated_label": "ARR",
            }
        )
    )
    changes = {"nimbus-12": {"value": Decimal(8100000)}, "nimbus-17": {"value": Decimal(4120)}}
    _load(store, exact, **changes)
    table = _table(_run("nimbus"))
    assert "invariant" in {row["kind"] for row in table}
    (inferred,) = (row for row in table if "read as" in row["right"])
    assert inferred["class"] == "definitional"
    assert '("Revenue", stated for the fiscal year' in inferred["right"]


def test_readings_list_each_ambiguous_row(store: FactStore) -> None:
    _load(store, **{"nimbus-12": {"value": Decimal(6950000)}})
    result = _run("nimbus", "--readings")
    assert _table(result) == [
        {
            "observation_id": "nimbus-12",
            "metric_id": "revenue_unspecified",
            "stated_label": "Revenue",
            "period_start": "2024-01-01",
            "period_end": "2024-12-31",
            "period_type": "fy",
            "status": "inferred",
            "read_as": "revenue_recognised",
            "how": "direct",
            "basis": "nimbus-10",
            "reason": "",
        }
    ]


def test_checks_list_each_status_and_reason(store: FactStore) -> None:
    _load(store)
    rows = _table(_run("nimbus", "--checks"))
    assert {
        "identity_id": "customers_paying_le_users_registered",
        "period_start": "2023-12-31",
        "period_end": "2023-12-31",
        "period_type": "point_in_time",
        "status": "not_checked",
        "reason": "users_registered not observed at 2023-12-31",
        "qualifier": "",
    } in rows
    assert len(rows) == 11


def test_checks_print_the_qualifier_of_a_segment_row(store: FactStore) -> None:
    """S3-12. A segment row's identity check names its segment in the qualifier
    column, the format ``_qualifier_text`` gives it.
    """
    segment_fields = {
        "period_start": date(2024, 1, 1),
        "period_end": date(2024, 12, 31),
        "period_type": "fy",
        "as_of_date": date(2024, 12, 31),
        "stated_precision": None,
        "segment": "North",
    }

    def _segment_row(observation_id: str, metric_id: str, value: Decimal) -> Observation:
        return Observation(
            **(
                NIMBUS["nimbus-02"].model_dump()
                | segment_fields
                | {"observation_id": observation_id, "metric_id": metric_id, "value": value}
            )
        )

    _load(
        store,
        _segment_row("north-revenue", "revenue_recognised", Decimal(1000000)),
        _segment_row("north-cost", "cost_of_sales", Decimal(400000)),
        _segment_row("north-gross", "gross_profit", Decimal(600000)),
    )
    rows = _table(_run("nimbus", "--checks"))
    (north,) = (row for row in rows if row["identity_id"] == "gross_profit_from_revenue")
    assert north["qualifier"] == "segment=north"


def test_two_runs_print_the_same_output(store: FactStore) -> None:
    _load(store)
    assert _run("nimbus").stdout == _run("nimbus").stdout


def test_checks_and_readings_together_are_refused(store: FactStore) -> None:
    result = _run("nimbus", "--checks", "--readings")
    assert result.exit_code == 1
    assert "not both" in result.stderr


def test_rows_with_undefined_metric_ids_are_counted(store: FactStore) -> None:
    odd = NIMBUS["nimbus-02"].model_copy(update={"observation_id": "odd", "metric_id": "arr_x"})
    _load(store, odd)
    assert "1 observation(s) use undefined metric ids" in _run("nimbus").stderr
