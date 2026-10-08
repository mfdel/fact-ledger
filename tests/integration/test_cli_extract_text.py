"""Acceptance tests for ``fact-ledger extract-text`` (S5-02).
The recording ``nimbus-press-2025.responses.json`` is hand-written, not from a
live model: it is the answer a model would give for ``nimbus-press-2025.txt``. The prompt was
not run live.
"""

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from typer.testing import CliRunner

import fact_ledger.llm as llm_module
from fact_ledger.cli import app
from fact_ledger.extract import replay
from fact_ledger.store.facts import FactStore
from fact_ledger.store.yaml_files import read_transcript

pytestmark = pytest.mark.integration

TEXTS_DIR = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "texts"
NIMBUS_TEXT = TEXTS_DIR / "nimbus-press-2025.txt"
NIMBUS_RESPONSES = TEXTS_DIR / "nimbus-press-2025.responses.json"

_ARGS = [
    str(NIMBUS_TEXT),
    "--entity",
    "nimbus",
    "--origin",
    "techdaily",
    "--document",
    "techdaily-2025-02-10",
    "--reliability",
    "3",
    "--source-type",
    "press",
    "--published",
    "2025-02-10",
    "--cites",
    "nimbus-management",
]


def test_extract_text_writes_a_transcript_that_facts_load_then_loads(
    store: FactStore, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(llm_module, "complete", replay(NIMBUS_RESPONSES))
    out = tmp_path / "techdaily-2025-02-10.yaml"

    result = CliRunner().invoke(app, ["extract-text", *_ARGS, "--out", str(out)])

    assert result.exit_code == 0
    [row] = read_transcript(out)
    assert (row.value, row.stated_precision, row.stated_label) == (
        Decimal(8100000),
        Decimal(50000),
        "annual recurring revenue",
    )
    assert (row.source_type, row.published_date, row.as_of_date) == (
        "press",
        date(2025, 2, 10),
        date(2024, 12, 31),
    )
    assert (row.locator, row.entity_id, row.origin_id, row.document_id) == (
        "para 2",
        "nimbus",
        "techdaily",
        "techdaily-2025-02-10",
    )
    assert (row.reliability, row.cited_origin_id) == (3, "nimbus-management")
    assert store.get(row.observation_id) is None  # the command never opens the fact store

    assert CliRunner().invoke(app, ["facts", "load", str(out)]).exit_code == 0
    assert store.get(row.observation_id) is not None


def test_a_value_with_its_label_or_year_in_another_paragraph_is_left_out_and_the_rest_is_written(
    cli_env: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def value(label: str, printed: str, year: int, paragraph: int) -> dict[str, object]:
        return {
            **recording["pages"][0]["values"][0],
            "stated_label": label,
            "printed": printed,
            "period_start": f"{year}-12-31",
            "period_end": f"{year}-12-31",
            "paragraph": paragraph,
        }

    recording = json.loads(NIMBUS_RESPONSES.read_text(encoding="utf-8"))
    # Replace the null-period values of the recording with two that print a year.
    recording["pages"][0]["values"][1:] = [
        value("MRR", "€675k", 2024, 3),  # the label is in para 3, the figure in para 4
        value("Revenue", "€4.7", 2023, 5),  # para 1 prints 2023, para 5 does not
    ]
    modified = tmp_path / "responses.json"
    modified.write_text(json.dumps(recording), encoding="utf-8")
    monkeypatch.setattr(llm_module, "complete", replay(modified))
    out = tmp_path / "techdaily-2025-02-10.yaml"

    result = CliRunner().invoke(app, ["extract-text", *_ARGS, "--out", str(out)])

    assert result.exit_code == 0
    assert [row.locator for row in read_transcript(out)] == ["para 2"]
    left_out = [line for line in result.stderr.splitlines() if line.startswith("Left out ")]
    assert len(left_out) == 2
    assert left_out[0].startswith("Left out para 3: '€675k': ")
    assert left_out[1].startswith("Left out para 5: '€4.7': ")
