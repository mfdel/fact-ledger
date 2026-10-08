"""Acceptance tests for ``fact-ledger facts load`` (S1-06).

AC 4 (the ambiguous row stays ambiguous after load) relies on ``facts show`` (S1-05).
"""

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner

from fact_ledger.cli import app
from fact_ledger.domain import Period, PeriodType
from fact_ledger.store.facts import FactStore

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[2]
FIXTURES_DIR = ROOT / "tests" / "fixtures" / "transcripts"
SYNTHETIC_DECK = FIXTURES_DIR / "synthetic_deck.yaml"
SYNTHETIC_DECK_UNDEFINED = FIXTURES_DIR / "synthetic_deck_undefined.yaml"


def _row(observation_id: str, **overrides: Any) -> dict[str, Any]:
    """A row dict in transcript (YAML) form: values are strings, ints or dates, never floats."""
    base = {
        "observation_id": observation_id,
        "metric_id": "arr",
        "value": "1000000",
        "period_start": date(2024, 12, 31),
        "period_end": date(2024, 12, 31),
        "period_type": "point_in_time",
        "as_of_date": date(2024, 12, 31),
        "locator": "p1",
        "stated_label": "ARR",
    }
    return {**base, **overrides}


def _defaults(**overrides: Any) -> dict[str, Any]:
    base = {
        "entity_id": "acme",
        "origin_id": "acme-management",
        "document_id": "acme-deck-2025",
        "source_type": "deck",
        "reliability": 4,
        "bias_direction": "up",
        "published_date": date(2025, 1, 1),
        "unit": "EUR",
        "currency": "EUR",
    }
    return {**base, **overrides}


def _write_transcript(path: Path, defaults: dict[str, Any], rows: list[dict[str, Any]]) -> Path:
    path.write_text(yaml.safe_dump({"defaults": defaults, "observations": rows}, sort_keys=False))
    return path


def test_loading_the_synthetic_deck_saves_every_row_retrievable_by_find(store: FactStore) -> None:
    result = CliRunner().invoke(app, ["facts", "load", str(SYNTHETIC_DECK)])

    assert result.exit_code == 0
    all_rows = store.find(entity_id="nimbus")
    assert len(all_rows) == 20

    arr_2023 = store.find(
        entity_id="nimbus",
        metric_id="arr",
        period=Period(date(2023, 12, 31), date(2023, 12, 31), PeriodType.POINT_IN_TIME),
    )
    assert {o.observation_id for o in arr_2023} == {"nimbus-01"}

    # PLANTED disagreement: both rows for the same entity, metric and period are kept.
    arr_2024 = store.find(
        entity_id="nimbus",
        metric_id="arr",
        period=Period(date(2024, 12, 31), date(2024, 12, 31), PeriodType.POINT_IN_TIME),
    )
    by_id = {o.observation_id: o for o in arr_2024}
    assert {"nimbus-02", "nimbus-03", "nimbus-04"} <= by_id.keys()
    assert by_id["nimbus-02"].value == Decimal(8064000)
    assert by_id["nimbus-04"].value == Decimal(7450000)


def test_undefined_metric_ids_all_save_and_are_named_with_their_row_numbers(
    store: FactStore,
) -> None:
    result = CliRunner().invoke(app, ["facts", "load", str(SYNTHETIC_DECK_UNDEFINED)])

    assert result.exit_code == 0
    rows = store.find(entity_id="nimbus")
    assert {o.observation_id for o in rows} == {"nimbus-u01", "nimbus-u02", "nimbus-u03"}

    pipeline_line = next(line for line in result.stderr.splitlines() if "pipeline_coverage" in line)
    assert "2" in pipeline_line.split()
    net_new_line = next(
        line for line in result.stderr.splitlines() if "net_new_arr_per_rep" in line
    )
    assert "3" in net_new_line.split()


def test_duplicate_observation_id_fails_and_keeps_nothing_from_the_file(
    tmp_path: Path, store: FactStore
) -> None:
    transcript = _write_transcript(
        tmp_path / "duplicate.yaml",
        _defaults(),
        [
            _row("dup-1", metric_id="arr"),
            _row(
                "dup-1",
                metric_id="mrr",
                period_start=date(2024, 6, 30),
                period_end=date(2024, 6, 30),
            ),
        ],
    )

    result = CliRunner().invoke(app, ["facts", "load", str(transcript)])

    assert result.exit_code == 1
    assert "dup-1" in result.stderr
    assert store.find() == []


def test_missing_required_field_fails_and_keeps_nothing_from_the_file(
    tmp_path: Path, store: FactStore
) -> None:
    row = _row("acme-1")
    del row["locator"]  # required Observation field, absent from the row and from defaults
    transcript = _write_transcript(tmp_path / "missing_field.yaml", _defaults(), [row])

    result = CliRunner().invoke(app, ["facts", "load", str(transcript)])

    assert result.exit_code == 1
    assert "row 1" in result.stderr
    assert "locator" in result.stderr
    assert store.find() == []


def test_a_float_value_is_a_row_error_and_keeps_nothing_from_the_file(
    tmp_path: Path, store: FactStore
) -> None:
    transcript = tmp_path / "float_value.yaml"
    transcript.write_text(
        yaml.safe_dump(
            {
                "defaults": _defaults(),
                "observations": [{**_row("acme-1"), "value": 8.3}],
            },
            sort_keys=False,
        )
    )

    result = CliRunner().invoke(app, ["facts", "load", str(transcript)])

    assert result.exit_code == 1
    assert "row 1" in result.stderr
    assert "value" in result.stderr
    assert store.find() == []


@pytest.mark.parametrize(
    ("name", "content", "expected"),
    [
        ("missing.yaml", None, "missing.yaml"),
        ("invalid.yaml", "defaults: {entity_id: [unclosed\n", "invalid.yaml"),
        ("no_defaults.yaml", "observations: []\n", "no_defaults.yaml"),
        ("no_observations.yaml", "defaults: {}\n", "no_observations.yaml"),
        ("empty.yaml", "", "empty.yaml"),
        ("text_row.yaml", "defaults: {}\nobservations: [just text]\n", "row 1"),
    ],
)
def test_a_malformed_transcript_is_a_clear_error_not_a_traceback(
    tmp_path: Path, store: FactStore, name: str, content: str | None, expected: str
) -> None:
    transcript = tmp_path / name
    if content is not None:
        transcript.write_text(content)

    result = CliRunner().invoke(app, ["facts", "load", str(transcript)])

    assert result.exit_code == 1
    assert isinstance(result.exception, SystemExit)
    assert expected in result.stderr
    assert store.find() == []


def test_ambiguous_row_stays_ambiguous_after_load_and_after_facts_show(store: FactStore) -> None:
    load_result = CliRunner().invoke(app, ["facts", "load", str(SYNTHETIC_DECK)])
    assert load_result.exit_code == 0

    show_result = CliRunner().invoke(app, ["facts", "show", "nimbus"])
    assert show_result.exit_code == 0

    (line,) = (
        row for row in show_result.stdout.splitlines()[1:] if row.split("\t")[0] == "nimbus-12"
    )
    columns = line.split("\t")
    assert columns[1] == "revenue_unspecified"  # never silently resolved to one metric
    assert columns[9] == "ambiguous"
    assert "revenue_recognised" in columns[10]
    assert "arr" in columns[10]


def test_a_segment_row_round_trips_through_facts_load_and_find(
    tmp_path: Path, store: FactStore
) -> None:
    """S3-12, criterion 6. A segment row round-trips through ``facts load`` and
    ``FactStore.find``.
    """
    transcript = _write_transcript(
        tmp_path / "segment.yaml",
        _defaults(),
        [_row("acme-emea", segment="EMEA"), _row("acme-group", stated_label="Group revenue")],
    )

    result = CliRunner().invoke(app, ["facts", "load", str(transcript)])

    assert result.exit_code == 0, result.stderr
    rows = {o.observation_id: o for o in store.find(entity_id="acme")}
    assert rows["acme-emea"].segment == "EMEA"
    assert rows["acme-group"].segment is None


def test_a_cited_origin_round_trips_through_facts_load_and_find(
    tmp_path: Path, store: FactStore
) -> None:
    """S5-01, criterion 3. A row with a cited origin reads back with both origins.
    A row without one reads back with none.
    """
    transcript = _write_transcript(
        tmp_path / "cited.yaml",
        _defaults(),
        [
            _row("acme-press", origin_id="techdaily", cited_origin_id="acme-management"),
            _row("acme-deck"),
        ],
    )

    result = CliRunner().invoke(app, ["facts", "load", str(transcript)])

    assert result.exit_code == 0, result.stderr
    rows = {o.observation_id: o for o in store.find(entity_id="acme")}
    assert (rows["acme-press"].origin_id, rows["acme-press"].cited_origin_id) == (
        "techdaily",
        "acme-management",
    )
    assert rows["acme-deck"].cited_origin_id is None
