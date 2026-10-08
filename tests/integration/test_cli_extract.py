"""Acceptance tests for ``fact-ledger extract`` (S3-01).
Success is followed by ``facts load`` on the written file with no edit
(criterion 6). Failure writes no file, so the CLI test needs only one such case: the
domain-level reasons for a failed page are covered in ``tests/unit/test_extract_deck.py``.
"""

import json
from datetime import date
from pathlib import Path

import pytest
from pypdf import PageObject
from typer.testing import CliRunner

import fact_ledger.llm as llm_module
from fact_ledger.cli import app
from fact_ledger.domain import PeriodType
from fact_ledger.extract import ExtractedValue, PageExtraction, replay
from fact_ledger.store.yaml_files import read_transcript

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[2]
DECKS_DIR = ROOT / "tests" / "fixtures" / "decks"
NIMBUS_PDF = DECKS_DIR / "nimbus-pdf-2025.pdf"
NIMBUS_RESPONSES = DECKS_DIR / "nimbus-pdf-2025.responses.json"

_ARGS = [
    str(NIMBUS_PDF),
    "--entity",
    "nimbus",
    "--origin",
    "nimbus-management",
    "--document",
    "nimbus-pdf-2025",
    "--reliability",
    "4",
]


def _fail(system: str, user: str, schema: type[PageExtraction]) -> PageExtraction:
    del system, user, schema
    msg = "a fake failure, independent of the extraction rules"
    raise ValueError(msg)


def test_extract_writes_a_transcript_that_facts_load_then_loads_with_no_edit(
    cli_env: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(llm_module, "complete", replay(NIMBUS_RESPONSES))
    out = tmp_path / "nimbus-pdf-2025.yaml"

    result = CliRunner().invoke(app, ["extract", *_ARGS, "--out", str(out)])

    assert result.exit_code == 0
    assert out.exists()
    assert result.stdout.strip() == (
        f"Wrote 7 rows from 4 pages to {out}. Review it, then run 'fact-ledger facts load {out}'."
    )

    load_result = CliRunner().invoke(app, ["facts", "load", str(out)])
    assert load_result.exit_code == 0


def test_a_value_that_fails_a_check_is_left_out_and_the_rest_is_written(
    cli_env: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    recording = json.loads(NIMBUS_RESPONSES.read_text(encoding="utf-8"))
    recording["pages"][3]["values"][0]["unit"] = "$"  # U1: "$" is not a currency
    modified = tmp_path / "responses.json"
    modified.write_text(json.dumps(recording), encoding="utf-8")
    monkeypatch.setattr(llm_module, "complete", replay(modified))
    out = tmp_path / "nimbus-pdf-2025.yaml"

    result = CliRunner().invoke(app, ["extract", *_ARGS, "--out", str(out)])

    assert result.exit_code == 0
    assert out.exists()
    assert len(read_transcript(out)) == 6
    assert "Left out p4: '7,450': '$' is not a currency this code can resolve" in result.stderr
    assert result.stdout.strip().splitlines()[-1] == (
        f"Wrote 6 rows from 4 pages to {out}. Review it, then run 'fact-ledger facts load {out}'."
    )


def test_a_failed_page_exits_1_and_writes_no_file(
    cli_env: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(llm_module, "complete", _fail)
    out = tmp_path / "nimbus-pdf-2025.yaml"

    result = CliRunner().invoke(app, ["extract", *_ARGS, "--out", str(out)])

    assert result.exit_code == 1
    assert "fake failure" in result.stderr
    assert not out.exists()


def test_a_reliability_outside_1_to_5_fails_before_any_llm_call(
    cli_env: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(llm_module, "complete", _fail)
    out = tmp_path / "nimbus-pdf-2025.yaml"

    result = CliRunner().invoke(app, ["extract", *_ARGS[:-1], "6", "--out", str(out)])

    assert result.exit_code == 2  # a Typer usage error: the fake LLM never ran
    assert not out.exists()


def _cost_value(label: str, printed: str, *, unit: str = "EUR") -> ExtractedValue:
    return ExtractedValue(
        stated_label=label,
        printed=printed,
        scale="m",
        unit=unit,
        period_type=PeriodType.QUARTER,
        period_start=date(2026, 4, 1),
        period_end=date(2026, 6, 30),
        candidate_metric_ids=[],
        segment="",
        region="",
        basis="",
    )


def test_the_command_prints_sign_changed_lines_after_left_out_lines(
    cli_env: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """S3-18. A cost line the extractor stores with a flipped sign is named on
    stderr, after the left-out lines, and the command still exits 0.
    """
    pages = [
        PageExtraction(cover_date=date(2026, 3, 1), values=[]),
        PageExtraction(
            cover_date=None,
            values=[
                _cost_value("Personnel expenses", "(55.0)"),
                _cost_value("Bad currency", "$5", unit="$"),
            ],
        ),
        PageExtraction(cover_date=None, values=[]),
        PageExtraction(cover_date=None, values=[]),
    ]
    texts = iter(
        [
            "Nimbus SaaS \u2014 Board Update, March 2026",
            "Q2 2026 (\u20acm)\nPersonnel expenses (55.0)\nBad currency $5",
            "",
            "",
        ]
    )

    def extract_text(self: PageObject, *args: object, **kwargs: object) -> str:
        del self, args, kwargs
        return next(texts)

    monkeypatch.setattr(PageObject, "extract_text", extract_text)
    recording = tmp_path / "responses.json"
    recording.write_text(json.dumps({"pages": [p.model_dump(mode="json") for p in pages]}))
    monkeypatch.setattr(llm_module, "complete", replay(recording))
    out = tmp_path / "nimbus-pdf-2025.yaml"

    result = CliRunner().invoke(app, ["extract", *_ARGS, "--out", str(out)])

    assert result.exit_code == 0
    assert result.stderr.splitlines() == [
        "Left out p2: '$5': '$' is not a currency this code can resolve",
        "Sign changed p2: '(55.0)': stored as the positive amount of a cost",
    ]
