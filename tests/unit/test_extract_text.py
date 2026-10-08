"""``extract_text`` edges that the CLI tests do not reach (S5-02).
The happy path is in ``test_cli_extract_text.py``.

The prompt tests pin rules in ``extract_text_v1.md`` that no other test checks, because
``replay`` discards the system prompt: an edit that drops a rule fails here,
not at a live model call.
"""

import json
from datetime import date
from pathlib import Path

import pytest

from fact_ledger import extract as extract_module
from fact_ledger.domain import Dictionary, PeriodType
from fact_ledger.extract import Complete, TextExtraction, TextValue, extract_text, replay
from fact_ledger.store.yaml_files import load_dictionary

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]
NIMBUS_TEXT = ROOT / "tests" / "fixtures" / "texts" / "nimbus-press-2025.txt"
NIMBUS_RESPONSES = ROOT / "tests" / "fixtures" / "texts" / "nimbus-press-2025.responses.json"

SOURCE: dict[str, object] = {
    "entity_id": "nimbus",
    "origin_id": "techdaily",
    "document_id": "techdaily-2025-02-10",
    "reliability": 3,
    "source_type": "press",
    "published_date": date(2025, 2, 10),
}


@pytest.fixture(scope="module")
def dictionary() -> Dictionary:
    return load_dictionary(ROOT / "data" / "dictionary")


def test_a_file_with_no_paragraph_raises_with_its_name(
    dictionary: Dictionary, tmp_path: Path
) -> None:
    empty = tmp_path / "empty.txt"
    empty.write_text(" \n\n \n", encoding="utf-8")

    with pytest.raises(ValueError, match=r"^empty\.txt: no paragraph"):
        extract_text(empty, dictionary, SOURCE, replay(NIMBUS_RESPONSES))


def test_a_paragraph_number_out_of_range_is_left_out_and_named(
    dictionary: Dictionary, tmp_path: Path
) -> None:
    recording = json.loads(NIMBUS_RESPONSES.read_text(encoding="utf-8"))
    recording["pages"][0]["values"][0]["paragraph"] = 9
    changed = tmp_path / "responses.json"
    changed.write_text(json.dumps(recording), encoding="utf-8")

    extraction = extract_text(NIMBUS_TEXT, dictionary, SOURCE, replay(changed))

    assert extraction.rows == []
    assert extraction.pages == 5
    assert extraction.left_out[0] == "para 9: '€8.1': no such paragraph"


def test_every_paragraph_goes_to_the_model_under_its_marker(
    dictionary: Dictionary, tmp_path: Path
) -> None:
    text = tmp_path / "wrapped.txt"
    text.write_text("First line\nwraps here.\n\n\n\nSecond one.\n", encoding="utf-8")
    seen: list[str] = []

    def complete(system: str, user: str, schema: type[TextExtraction]) -> TextExtraction:
        del system
        seen.append(user)
        return schema(values=[])

    extract_text(text, dictionary, SOURCE, complete)

    assert seen == ["[para 1]\nFirst line wraps here.\n\n[para 2]\nSecond one."]


def _value(label: str) -> TextValue:
    return TextValue(
        stated_label=label,
        printed="12.5",
        scale="",
        unit="EUR",
        period_type=PeriodType.FY,
        period_start=date(2024, 1, 1),
        period_end=date(2024, 12, 31),
        candidate_metric_ids=[],
        segment="",
        region="",
        basis="",
        paragraph=1,
    )


def _complete(value: TextValue) -> Complete[TextExtraction]:
    def complete(system: str, user: str, schema: type[TextExtraction]) -> TextExtraction:
        del system, user, schema
        return TextExtraction(values=[value])

    return complete


def test_a_label_with_an_invented_suffix_is_left_out_for_text(
    dictionary: Dictionary, tmp_path: Path
) -> None:
    """S5-02 criterion 2: the whole label, as the response prints it, must
    be in the paragraph. The paragraph prints "Sales", never "Sales expenses". The deck rewrite
    drops the added ``COST_LINE_WORD`` and would accept it
    (``test_extract_deck.py::test_a_cost_label_still_pairs_with_a_revenue_figure_on_a_page_with_no_cost_block``).
    The text path must reject it.
    """
    page_text = "Sales reached 12.5 in 2024, the company said."
    assert extract_module._label_pairs_with_figure("Sales expenses", "12.5", page_text, "EUR")
    assert not extract_module._pairs_with_figure("Sales expenses", "12.5", page_text)
    path = tmp_path / "article.txt"
    path.write_text(page_text, encoding="utf-8")

    extraction = extract_text(path, dictionary, SOURCE, _complete(_value("Sales expenses")))

    assert extraction.rows == []
    assert extraction.left_out == [
        "para 1: '12.5': stated_label and printed are not on one line or in one column"
    ]


def test_the_prompt_tells_the_model_the_paragraph_marker_of_the_figure(
    dictionary: Dictionary,
) -> None:
    """Criterion 1 and 2 are prompt behaviour, and no test calls a live LLM. So the test pins
    the rule in the prompt text: an edit that drops it fails here.
    """
    system = extract_module._system_prompt(dictionary, extract_module.TEXT_PROMPT)

    assert "the N of the `[para N]` marker of the paragraph that prints the figure" in system


def test_the_prompt_tells_the_model_to_keep_a_bound_word_in_printed(dictionary: Dictionary) -> None:
    """Decision 22: a bound word makes a bound, not a point value, and
    stays in ``printed`` so the code leaves the row out and names it.
    """
    system = extract_module._system_prompt(dictionary, extract_module.TEXT_PROMPT)

    assert "A bound word marks a bound, not a point value" in system
    assert "Keep the bound word in `printed`" in system
    assert '"over €8 million" gives `printed` "over €8"' in system


def test_the_prompt_tells_the_model_to_null_a_relative_period(dictionary: Dictionary) -> None:
    """Decision 23: a relative period never resolves from the published
    date.
    """
    system = extract_module._system_prompt(dictionary, extract_module.TEXT_PROMPT)

    assert "Set them to null for a relative period" in system
    assert "Never resolve it from the date of the article" in system


def test_the_prompt_tells_the_model_to_null_a_forecast(dictionary: Dictionary) -> None:
    """Decision 23: a forecast, a plan or a target is not an actual
    value.
    """
    system = extract_module._system_prompt(dictionary, extract_module.TEXT_PROMPT)

    assert "Set them to null for a forecast, a plan or a target" in system
    assert "expects €10m by 2026" in system
