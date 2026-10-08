"""``extract_deck`` (S3-01).

The happy path replays the hand-written recording onto the real PDF fixture and checks
the seven rows of S3-01 (acceptance criteria 1 to 5). Each stop-the-run case changes one
field of the recording and asserts the reason, so it cannot pass on another check. A bound
cannot be on a fixture page, so ``test_extraction.py`` covers V4.
"""

import json
import re
from collections.abc import Callable, Sequence
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Literal

import pytest
from pypdf import PageObject, PdfWriter

from fact_ledger import extract as extract_module
from fact_ledger.domain import BiasDirection, DefinitionStatus, Dictionary, PeriodType
from fact_ledger.domain.rules import COST_LINE_WORD, GENERIC_MARGIN_LABELS
from fact_ledger.extract import Complete, ExtractedValue, PageExtraction, extract_deck, replay
from fact_ledger.store.yaml_files import load_dictionary

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]
DECKS_DIR = ROOT / "tests" / "fixtures" / "decks"
NIMBUS_PDF = DECKS_DIR / "nimbus-pdf-2025.pdf"
NIMBUS_RESPONSES = DECKS_DIR / "nimbus-pdf-2025.responses.json"

SOURCE: dict[str, object] = {
    "entity_id": "nimbus",
    "origin_id": "nimbus-management",
    "document_id": "nimbus-pdf-2025",
    "reliability": 4,
}


@pytest.fixture(scope="module")
def dictionary() -> Dictionary:
    return load_dictionary(ROOT / "data" / "dictionary")


_DEC_31 = date(2024, 12, 31)
_FY_2023_END = date(2023, 12, 31)
_EUR = ("EUR", "EUR")

# S3-01 nn-01 to nn-07: metric, value, precision, (unit, currency), page, as_of, printed
_EXPECTED = {
    "01": ("arr", Decimal(8000000), Decimal(500000), _EUR, "p1", _DEC_31, "~€8m"),
    "02": ("arr", Decimal(8400000), Decimal(50000), _EUR, "p2", _DEC_31, "€8.4m"),
    "03": ("mrr", Decimal(700000), Decimal(500), _EUR, "p2", _DEC_31, "€700k"),
    "04": (
        "revenue_unspecified",
        Decimal(4700000),
        Decimal(50000),
        _EUR,
        "p3",
        _FY_2023_END,
        "€4.7m",
    ),
    "05": (
        "pipeline_coverage",
        Decimal("3.2"),
        Decimal("0.05"),
        ("ratio", None),
        "p3",
        _DEC_31,
        "3.2x",
    ),
    "06": ("arr", Decimal(7450000), Decimal(500), _EUR, "p4", _DEC_31, "7,450"),
    "07": ("mrr", Decimal(700000), Decimal(500), _EUR, "p4", _DEC_31, "700"),
}


def test_extract_deck_gives_the_seven_expected_rows(dictionary: Dictionary) -> None:
    extraction = extract_deck(NIMBUS_PDF, dictionary, SOURCE, replay(NIMBUS_RESPONSES))

    assert extraction.pages == 4
    published = date(2025, 3, 1)
    assert extraction.defaults == {**SOURCE, "source_type": "deck", "published_date": published}
    rows = {o.observation_id.removeprefix("nimbus-pdf-2025-"): (o, p) for o, p in extraction.rows}
    assert list(rows) == list(_EXPECTED)
    for key, (row, printed) in rows.items():
        actual = (
            row.metric_id,
            row.value,
            row.stated_precision,
            (row.unit, row.currency),
            row.locator,
            row.as_of_date,
            printed,
        )
        assert actual == _EXPECTED[key], key
        assert (row.entity_id, row.origin_id, row.reliability) == ("nimbus", "nimbus-management", 4)
        assert row.published_date == published
        assert row.bias_direction is BiasDirection.UNKNOWN  # S3 scope review: no default

    revenue = rows["04"][0]
    assert (revenue.period_start, revenue.period_type) == (date(2023, 1, 1), PeriodType.FY)
    assert revenue.definition_status is DefinitionStatus.AMBIGUOUS
    assert {"revenue_recognised", "arr"} <= set(revenue.candidate_metric_ids)
    for candidate in revenue.candidate_metric_ids:
        assert candidate in dictionary.metric_ids
        assert not candidate.endswith("_unspecified")


def _recorded() -> list[PageExtraction]:
    pages = json.loads(NIMBUS_RESPONSES.read_text(encoding="utf-8"))["pages"]
    return [PageExtraction.model_validate(page) for page in pages]


def _changed(page: int, value: int, **changes: object) -> list[PageExtraction]:
    pages = _recorded()
    values = list(pages[page].values)
    values[value] = values[value].model_copy(update=changes)
    pages[page] = pages[page].model_copy(update={"values": values})
    return pages


def _fake_complete(pages: Sequence[PageExtraction]) -> Complete:
    remaining = iter(pages)

    def complete(system: str, user: str, schema: type[PageExtraction]) -> PageExtraction:
        del system, user, schema
        return next(remaining)

    return complete


@pytest.mark.parametrize(
    ("pages", "page", "printed", "reason"),
    [
        (_changed(1, 0, printed="€8.5m"), "p2", "€8.5m", "not on one line"),  # V3
        (_changed(1, 0, stated_label="Revenue"), "p2", "€8.4m", "not on one line"),
        (_changed(1, 0, printed="€700k"), "p2", "€700k", "not on one line"),
        (_changed(3, 0, printed="700"), "p4", "700", "not on one line"),
        (_changed(1, 0, printed="8"), "p2", "8", "not on one line"),  # a piece of "€8.4m"
        (_changed(3, 0, unit="$"), "p4", "7,450", "is not a currency"),  # U1
        (_changed(1, 0, unit="count"), "p2", "€8.4m", "disagrees with unit"),  # V2
        (_changed(1, 0, scale="k"), "p2", "€8.4m", "disagrees"),  # V1
        (_changed(2, 1, period_end=None), "p3", "3.2x", "no usable printed period"),  # D2
        (_changed(2, 1, period_start=None), "p3", "3.2x", "no usable printed period"),
        (
            _changed(2, 0, period_start=date(2022, 1, 1), period_end=date(2022, 12, 31)),
            "p3",
            "€4.7m",
            "does not print the year",
        ),
        (_changed(2, 0, candidate_metric_ids=["nrr"]), "p3", "€4.7m", "not a usual candidate"),
    ],
)
def test_a_bad_value_is_left_out_and_named_and_the_other_rows_are_written(
    dictionary: Dictionary, pages: list[PageExtraction], page: str, printed: str, reason: str
) -> None:
    expected = f"^{page}: {re.escape(repr(printed))}: .*{re.escape(reason)}"

    extraction = extract_deck(NIMBUS_PDF, dictionary, SOURCE, _fake_complete(pages))

    assert len(extraction.left_out) == 1
    assert re.match(expected, extraction.left_out[0])
    assert len(extraction.rows) == len(_EXPECTED) - 1
    numbers = [int(o.observation_id.rsplit("-", 1)[-1]) for o, _ in extraction.rows]
    assert numbers == list(range(1, len(extraction.rows) + 1))


def test_no_cover_date_on_page_one_names_the_file_not_a_value(dictionary: Dictionary) -> None:
    pages = _recorded()
    pages[0] = pages[0].model_copy(update={"cover_date": None})

    with pytest.raises(ValueError, match=re.escape(NIMBUS_PDF.name)):
        extract_deck(NIMBUS_PDF, dictionary, SOURCE, _fake_complete(pages))


def test_a_blank_page_one_fails_with_no_cover_date_and_no_llm_call(
    dictionary: Dictionary, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S3-09: page 1 holds the cover date, so a blank page 1 must not skip to the LLM."""
    monkeypatch.setattr(PageObject, "extract_text", _extract_text_or("", page_number=0))
    calls: list[str] = []

    with pytest.raises(ValueError, match=re.escape(NIMBUS_PDF.name)):
        extract_deck(NIMBUS_PDF, dictionary, SOURCE, _recording_complete(calls))

    assert calls == []


def test_a_cover_date_whose_year_page_one_does_not_print_stops_the_run(
    dictionary: Dictionary,
) -> None:
    pages = _recorded()
    pages[0] = pages[0].model_copy(update={"cover_date": date(2023, 3, 1)})

    with pytest.raises(ValueError, match="page 1 does not print the year of cover_date"):
        extract_deck(NIMBUS_PDF, dictionary, SOURCE, _fake_complete(pages))


def test_a_response_that_fails_the_schema_names_its_page(
    dictionary: Dictionary, tmp_path: Path
) -> None:
    recording = json.loads(NIMBUS_RESPONSES.read_text(encoding="utf-8"))
    del recording["pages"][2]["values"][0]["period_end"]
    path = tmp_path / "responses.json"
    path.write_text(json.dumps(recording), encoding="utf-8")

    with pytest.raises(ValueError, match=r"^p3: .*PageExtraction"):
        extract_deck(NIMBUS_PDF, dictionary, SOURCE, replay(path))


def _patch_page_texts(monkeypatch: pytest.MonkeyPatch, texts: Sequence[str]) -> None:
    """S3-06: one synthetic page text per page, in page order, instead of the fixture PDF's
    own text, so a token or a plain year can be set up with no new fixture PDF.
    """
    remaining = iter(texts)

    def extract_text(self: PageObject, *args: object, **kwargs: object) -> str:
        del self, args, kwargs
        return next(remaining)

    monkeypatch.setattr(PageObject, "extract_text", extract_text)


def _widget_value(
    printed: str,
    period_type: PeriodType,
    start: date,
    end: date,
    *,
    label: str = "Widgets shipped",
) -> ExtractedValue:
    return ExtractedValue(
        stated_label=label,
        printed=printed,
        scale="",
        unit="count",
        period_type=period_type,
        period_start=start,
        period_end=end,
        candidate_metric_ids=[],
        segment="",
        region="",
        basis="",
    )


def test_a_year_to_date_value_passes_the_year_check_from_a_plain_year_or_a_token(
    dictionary: Dictionary, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S3-06, criteria 1 to 3. A quarter value and a year-to-date value pass the
    year check from a plain 4-digit year (p2) or from a hyphen two-digit token, when the page
    prints no 4-digit year at all (p3). A value whose page prints neither is left out (p4),
    even next to a bare number that looks like a year ("31 Dec 2024", "42 new logos").
    """
    quarter, ytd, point = PeriodType.QUARTER, PeriodType.YTD, PeriodType.POINT_IN_TIME
    pages = [
        PageExtraction(cover_date=date(2026, 3, 1), values=[]),
        PageExtraction(
            cover_date=None,
            values=[
                _widget_value("120", quarter, date(2026, 4, 1), date(2026, 6, 30)),
                _widget_value("640", ytd, date(2026, 1, 1), date(2026, 6, 30)),
            ],
        ),
        PageExtraction(
            cover_date=None,
            values=[
                _widget_value("150", quarter, date(2026, 4, 1), date(2026, 6, 30)),
                _widget_value("700", ytd, date(2026, 1, 1), date(2026, 6, 30)),
            ],
        ),
        PageExtraction(
            cover_date=None,
            values=[
                _widget_value("90", point, date(2031, 12, 31), date(2031, 12, 31)),
                _widget_value(
                    "55", point, date(2042, 6, 30), date(2042, 6, 30), label="Logo count"
                ),
            ],
        ),
    ]
    _patch_page_texts(
        monkeypatch,
        [
            "Nimbus SaaS \u2014 Board Update, March 2026",
            "Q2 2026     6M 2026\nWidgets shipped 120         640",
            "Q2-26     H1-26\nWidgets shipped 150       700",
            "Founded 31 Dec 2024. We added 42 new logos this quarter.\n"
            "Widgets shipped 90\nLogo count 55",
        ],
    )

    extraction = extract_deck(NIMBUS_PDF, dictionary, SOURCE, _fake_complete(pages))

    rows = [
        (row.period_type, row.period_start, row.period_end, row.value, row.locator)
        for row, _printed in extraction.rows
    ]
    assert rows == [
        (quarter, date(2026, 4, 1), date(2026, 6, 30), Decimal(120), "p2"),
        (ytd, date(2026, 1, 1), date(2026, 6, 30), Decimal(640), "p2"),
        (quarter, date(2026, 4, 1), date(2026, 6, 30), Decimal(150), "p3"),
        (ytd, date(2026, 1, 1), date(2026, 6, 30), Decimal(700), "p3"),
    ]
    assert extraction.left_out == [
        "p4: '90': the page does not print the year of period_end",
        "p4: '55': the page does not print the year of period_end",
    ]


@pytest.mark.parametrize(
    ("label", "printed", "expected"),
    [
        ("ARR", "1,234.5", True),  # its own column
        ("Revenue", "345.6", True),
        ("EBITDA", "98.7", True),
        ("ARR", "345.6", False),  # Revenue's column, not its own
    ],
)
def test_a_kpi_tile_label_pairs_only_with_the_figure_in_its_own_column(
    label: str, printed: str, expected: bool
) -> None:
    """S3-07, criterion 1. A tile's label and its figure sit one text line apart,
    in the same raw-line column. A label paired with another tile's figure, at the same
    distance, does not pair.
    """
    page_text = f"{'ARR':<12}{'Revenue':<12}{'EBITDA'}\n{'1,234.5':<12}{'345.6':<12}{'98.7'}"

    assert extract_module._pairs_with_figure(label, printed, page_text) is expected


@pytest.mark.parametrize(
    ("page_text", "expected"),
    [
        ("ARR\n\n1,234.5", True),  # one blank line
        ("ARR\n\n\n\n1,234.5", True),  # three blank lines
        ("ARR\n\n\n\n\n1,234.5", False),  # four blank lines: too far
        ("ARR\n(\u20acm)\nQ2 2026\n+12% YoY\n1,234.5", True),  # the fourth text line
        # S3-16: "ARR" is alone on its line, so it reaches the fifth text line too.
        ("ARR\n(\u20acm)\nQ2 2026\n+12% YoY\nNote 1\n1,234.5", True),
    ],
)
def test_a_figure_pairs_with_its_label_across_a_few_lines(page_text: str, expected: bool) -> None:
    """S3-07, criterion 3, widened by S3-16.
    "ARR" is alone on its raw line, so the figure can be on any of the next five text lines.
    A unit, period or delta line between the label and the figure counts as one of the five.
    More than three blank lines in a row end the search.
    """
    assert extract_module._pairs_with_figure("ARR", "1,234.5", page_text) is expected


_FIGURE_LINE = "\u20ac 12.4 bn"
_INDENT = " " * 20


@pytest.mark.parametrize(
    ("page_text", "expected"),
    [
        (f"{_FIGURE_LINE}\nPayment volume", True),  # the next line
        (f"{_FIGURE_LINE}\n(\u20acbn)\nPayment volume", True),  # the line after that
        (f"{_FIGURE_LINE}\n(\u20acbn)\nQ2 2026\nPayment volume", False),  # a third line: too far
        (f"{_FIGURE_LINE:<20}\n{_INDENT}Payment volume", False),  # another tile's column
    ],
)
def test_a_label_pairs_with_a_figure_above_it_across_a_line_or_two(
    page_text: str, expected: bool
) -> None:
    """S3-16, criterion 1. A tile prints its figure first and its label on the
    next text line, or the one after, in an overlapping column, the way S3-07 reads a label
    above its figure. A third line is too far, and another tile's column does not count.
    """
    assert extract_module._pairs_with_figure("Payment volume", _FIGURE_LINE, page_text) is expected


_CHART_LABEL = "Payment volume"
_CHART_LINES_BEFORE_VALUES = ["(\u20acm)", "Q2 2026", "+18% YoY"]
_CHART_BAR_INDENT = " " * 20


def test_a_bar_charts_values_pair_with_a_lone_label_further_below() -> None:
    """S3-16, criterion 2. A chart's label sits alone on its own line, then a
    unit, a period and a growth-rate line come before the two bar values, further below than
    a KPI tile's figure (S3-07). Both values pair, in a column that does not overlap the
    label's, because the label's own row holds nothing else.
    """
    page_text = "\n".join(
        [
            _CHART_LABEL,
            *_CHART_LINES_BEFORE_VALUES,
            f"{_CHART_BAR_INDENT}45.2",
            f"{_CHART_BAR_INDENT}52.7",
        ]
    )

    assert extract_module._pairs_with_figure(_CHART_LABEL, "45.2", page_text) is True
    assert extract_module._pairs_with_figure(_CHART_LABEL, "52.7", page_text) is True


def test_a_bar_charts_values_do_not_pair_with_a_label_that_shares_its_row() -> None:
    """The any-column reach needs a lone label. A label beside another tile name keeps its own
    column and four lines, so a wide dashboard row cannot borrow a neighbour tile's bar values.
    """
    labels_line = f"{_CHART_LABEL:<20}Tile Beta"
    page_text = "\n".join(
        [
            labels_line,
            *_CHART_LINES_BEFORE_VALUES,
            f"{_CHART_BAR_INDENT}45.2",
            f"{_CHART_BAR_INDENT}52.7",
        ]
    )

    assert extract_module._pairs_with_figure(_CHART_LABEL, "45.2", page_text) is False


def test_two_tiles_on_two_baselines_do_not_swap_figures() -> None:
    """pypdf layout mode can put two tile titles on two raw
    lines when their baselines differ, so each title is alone on its own line. "Tile Alpha"
    must not take "Tile Beta"'s figure: a no-digit token ("Tile Beta") sits between them, over
    the figure's own column, so the cross-column reach is blocked. Each title still pairs with
    the figure in its own column.
    """
    page_text = "Tile Alpha\n                    Tile Beta\n1,234.5             345.6"

    assert extract_module._pairs_with_figure("Tile Alpha", "345.6", page_text) is False
    assert extract_module._pairs_with_figure("Tile Alpha", "1,234.5", page_text) is True
    assert extract_module._pairs_with_figure("Tile Beta", "345.6", page_text) is True


def test_a_stacked_criterion_one_label_does_not_take_the_next_tiles_figure() -> None:
    """Two KPI tiles stack, each label under its own figure
    (criterion 1). "Net revenue retention" already pairs with "112%" above it. It must not
    also take "87%", the next tile's own figure, through the lone-label wide reach. "Gross
    margin" still pairs with "87%" above it.
    """
    page_text = "\n".join(["112%", "Net revenue retention", "87%", "Gross margin"])

    assert extract_module._pairs_with_figure("Net revenue retention", "87%", page_text) is False
    assert extract_module._pairs_with_figure("Net revenue retention", "112%", page_text) is True
    assert extract_module._pairs_with_figure("Gross margin", "87%", page_text) is True


def test_a_label_printed_twice_pairs_with_the_figure_in_its_second_column() -> None:
    """Two tiles print the same label. The figure under the second label pairs,
    so the check compares every label match with every figure match.
    """
    assert extract_module._pairs_with_figure("ARR", "20", "ARR     ARR\n10      20") is True


def test_a_label_wrapped_over_two_lines_does_not_pair_with_the_figure_below_it() -> None:
    """S3-07, criterion 2. The LLM joins two printed lines into one
    ``stated_label``. That label is on no single raw line, so neither the same-line nor the
    column branch finds a match, and the value stays left out.
    """
    page_text = "Adjusted gross\nmargin              45.6%"

    assert extract_module._pairs_with_figure("Adjusted gross margin", "45.6%", page_text) is False


def test_a_figure_with_a_space_still_pairs_across_a_layout_gap() -> None:
    assert extract_module._pairs_with_figure("ARR", "c. \u20ac8m", "ARR    c.   \u20ac8m") is True


def _tile_value(label: str, printed: str) -> ExtractedValue:
    return ExtractedValue(
        stated_label=label,
        printed=printed,
        scale="",
        unit="count",
        period_type=PeriodType.QUARTER,
        period_start=date(2026, 4, 1),
        period_end=date(2026, 6, 30),
        candidate_metric_ids=[],
        segment="",
        region="",
        basis="",
    )


def test_extract_deck_accepts_kpi_tile_values_and_rejects_a_cross_column_pairing(
    dictionary: Dictionary, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S3-07, criterion 1. Three KPI tiles each print a label above its own
    figure, in its own column. ``extract_deck`` accepts each pair and leaves out a value
    that pairs one tile's label with another tile's figure, named with the new reason.
    """
    values = [
        _tile_value("Tile Alpha", "1,234.5"),
        _tile_value("Tile Beta", "345.6"),
        _tile_value("Tile Gamma", "98.7"),
        _tile_value("Tile Alpha", "345.6"),  # Tile Beta's column, not its own
    ]
    pages = [
        PageExtraction(cover_date=date(2026, 3, 1), values=[]),
        PageExtraction(cover_date=None, values=values),
        PageExtraction(cover_date=None, values=[]),
        PageExtraction(cover_date=None, values=[]),
    ]
    labels_line = f"{'Tile Alpha':<14}{'Tile Beta':<14}{'Tile Gamma'}"
    figures_line = f"{'1,234.5':<14}{'345.6':<14}{'98.7'}"
    _patch_page_texts(
        monkeypatch,
        [
            "Nimbus SaaS \u2014 Board Update, March 2026",
            f"Q2 2026\n{labels_line}\n{figures_line}",
            "",
            "",
        ],
    )

    extraction = extract_deck(NIMBUS_PDF, dictionary, SOURCE, _fake_complete(pages))

    assert [printed for _observation, printed in extraction.rows] == ["1,234.5", "345.6", "98.7"]
    assert extraction.left_out == [
        "p2: '345.6': stated_label and printed are not on one line or in one column"
    ]


def test_extract_deck_accepts_a_bar_charts_two_values_below_a_lone_label(
    dictionary: Dictionary, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S3-16, criterion 2. A bar chart prints its label, then a unit, a period
    and a growth-rate line, then two bar values in their own column. ``extract_deck`` accepts
    both.
    """
    values = [_tile_value("Payment volume", "45.2"), _tile_value("Payment volume", "52.7")]
    pages = [
        PageExtraction(cover_date=date(2026, 3, 1), values=[]),
        PageExtraction(cover_date=None, values=values),
        PageExtraction(cover_date=None, values=[]),
        PageExtraction(cover_date=None, values=[]),
    ]
    chart_text = "\n".join(
        ["Payment volume", "(\u20acm)", "Q2 2026", "+18% YoY", f"{' ' * 20}45.2", f"{' ' * 20}52.7"]
    )
    _patch_page_texts(
        monkeypatch,
        [
            "Nimbus SaaS \u2014 Board Update, March 2026",
            chart_text,
            "",
            "",
        ],
    )

    extraction = extract_deck(NIMBUS_PDF, dictionary, SOURCE, _fake_complete(pages))

    assert [printed for _observation, printed in extraction.rows] == ["45.2", "52.7"]
    assert extraction.left_out == []


def _signed_value(label: str, printed: str) -> ExtractedValue:
    return ExtractedValue(
        stated_label=label,
        printed=printed,
        scale="m",
        unit="EUR",
        period_type=PeriodType.QUARTER,
        period_start=date(2026, 4, 1),
        period_end=date(2026, 6, 30),
        candidate_metric_ids=[],
        segment="",
        region="",
        basis="",
    )


def test_a_negative_value_is_written_unless_its_metric_is_outside_signed_metrics(
    dictionary: Dictionary, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S3-08, criteria 1 and 2. A hyphen-minus or round brackets makes a figure
    negative. An undefined label (a slug, no dictionary id) carries the sign with no check.
    A dictionary metric keeps the sign only if ``SIGNED_METRICS`` holds it. ``net_new_arr``
    keeps it. ``mrr_churned`` does not, so that row is left out and named. A burn metric
    (``OUTFLOW_METRICS``) is stored as a positive amount, and named in
    ``Extraction.sign_changed`` (S3-18). "Total opex" holds no cost word, so it
    keeps its printed sign.
    """
    values = [
        _signed_value("Financial result", "-4.2"),
        _signed_value("Total opex", "(12.3)"),
        _signed_value("Net new ARR", "(1.5)"),  # alias of net_new_arr
        _signed_value("Churned MRR", "(12.3)"),  # alias of mrr_churned
        _signed_value("Cash burn", "(0.4)"),  # alias of burn_net
    ]
    pages = [
        PageExtraction(cover_date=date(2026, 3, 1), values=[]),
        PageExtraction(cover_date=None, values=values),
        PageExtraction(cover_date=None, values=[]),
        PageExtraction(cover_date=None, values=[]),
    ]
    _patch_page_texts(
        monkeypatch,
        [
            "Nimbus SaaS \u2014 Board Update, March 2026",
            "Q2 2026 (\u20acm)\n"
            "Financial result -4.2\n"
            "Total opex (12.3)\n"
            "Net new ARR (1.5)\n"
            "Churned MRR (12.3)\n"
            "Cash burn (0.4)",
            "",
            "",
        ],
    )

    extraction = extract_deck(NIMBUS_PDF, dictionary, SOURCE, _fake_complete(pages))

    rows = {
        row.stated_label: (row.metric_id, row.value, row.stated_precision)
        for row, _printed in extraction.rows
    }
    assert rows["Financial result"] == ("financial_result", Decimal(-4200000), Decimal(50000))
    assert rows["Total opex"] == ("total_opex", Decimal(-12300000), Decimal(50000))
    assert rows["Net new ARR"] == ("net_new_arr", Decimal(-1500000), Decimal(50000))
    assert rows["Cash burn"] == ("burn_net", Decimal(400000), Decimal(50000))
    assert extraction.left_out == ["p2: '(12.3)': mrr_churned cannot be negative"]
    assert extraction.sign_changed == ["p2: '(0.4)': stored as the positive amount of a cost"]


def test_a_slug_cost_line_stores_the_positive_amount_in_both_statements(
    dictionary: Dictionary, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S3-18, criterion 1. An income statement page prints a cost line as a
    positive amount; an expense breakdown page of the same document prints the same line,
    for the same period, as a negative. Both rows keep the slug ``personnel_expenses`` and
    store the positive amount. The run output names only the row whose sign changed.
    """
    pages = [
        PageExtraction(cover_date=date(2026, 3, 1), values=[]),
        PageExtraction(cover_date=None, values=[_signed_value("Personnel expenses", "55.0")]),
        PageExtraction(cover_date=None, values=[_signed_value("Personnel expenses", "(55.0)")]),
        PageExtraction(cover_date=None, values=[]),
    ]
    _patch_page_texts(
        monkeypatch,
        [
            "Nimbus SaaS \u2014 Board Update, March 2026",
            "Q2 2026 (\u20acm)\nPersonnel expenses 55.0",
            "Q2 2026 (\u20acm)\nPersonnel expenses (55.0)",
            "",
        ],
    )

    extraction = extract_deck(NIMBUS_PDF, dictionary, SOURCE, _fake_complete(pages))

    rows = [(row.metric_id, row.value, printed) for row, printed in extraction.rows]
    assert rows == [
        ("personnel_expenses", Decimal(55000000), "55.0"),
        ("personnel_expenses", Decimal(55000000), "(55.0)"),
    ]
    assert extraction.left_out == []
    assert extraction.sign_changed == ["p3: '(55.0)': stored as the positive amount of a cost"]


def test_a_slug_with_no_cost_word_keeps_the_printed_sign(
    dictionary: Dictionary, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S3-18, criterion 2, and the whole-word rule. "Financial result" holds no
    cost word, so a genuine loss keeps its minus. "Taxonomy result" holds "tax" inside a
    longer word, which the whole-word, case-insensitive rule does not match, so it also
    keeps its sign.
    """
    values = [
        _signed_value("Financial result", "-18.0"),
        _signed_value("Taxonomy result", "-3.0"),
    ]
    pages = [
        PageExtraction(cover_date=date(2026, 3, 1), values=[]),
        PageExtraction(cover_date=None, values=values),
        PageExtraction(cover_date=None, values=[]),
        PageExtraction(cover_date=None, values=[]),
    ]
    _patch_page_texts(
        monkeypatch,
        [
            "Nimbus SaaS \u2014 Board Update, March 2026",
            "Q2 2026 (\u20acm)\nFinancial result -18.0\nTaxonomy result -3.0",
            "",
            "",
        ],
    )

    extraction = extract_deck(NIMBUS_PDF, dictionary, SOURCE, _fake_complete(pages))

    rows = {row.stated_label: row.value for row, _printed in extraction.rows}
    assert rows == {"Financial result": Decimal(-18000000), "Taxonomy result": Decimal(-3000000)}
    assert extraction.sign_changed == []


@pytest.mark.parametrize(
    ("label", "printed", "expected"),
    [
        ("Cost of sales", "(4.2)", ("cost_of_sales", Decimal(4200000))),
        ("D&A", "(1.1)", ("d_and_a", Decimal(1100000))),
        ("Income tax expense", "(0.6)", ("income_tax_expense", Decimal(600000))),
        ("Operating profit", "(2.3)", ("ebit", Decimal(-2300000))),
        ("Profit before tax (EBT)", "(12.3)", ("ebt", Decimal(-12300000))),
    ],
)
def test_a_negative_ifrs_outflow_becomes_positive_and_a_negative_signed_profit_stays_negative(
    dictionary: Dictionary,
    monkeypatch: pytest.MonkeyPatch,
    label: str,
    printed: str,
    expected: tuple[str, Decimal],
) -> None:
    """S3-19. ``cost_of_sales``, ``d_and_a`` and
    ``income_tax_expense`` joined ``OUTFLOW_METRICS``: a deck can print each negative, and the
    extractor stores it as a positive amount. ``ebit`` stays in ``SIGNED_METRICS``, so a
    negative operating profit keeps its sign.
    """
    pages = [
        PageExtraction(cover_date=date(2026, 3, 1), values=[]),
        PageExtraction(cover_date=None, values=[_signed_value(label, printed)]),
        PageExtraction(cover_date=None, values=[]),
        PageExtraction(cover_date=None, values=[]),
    ]
    _patch_page_texts(
        monkeypatch,
        [
            "Nimbus SaaS \u2014 Board Update, March 2026",
            f"Q2 2026 (\u20acm)\n{label} {printed}",
            "",
            "",
        ],
    )

    extraction = extract_deck(NIMBUS_PDF, dictionary, SOURCE, _fake_complete(pages))

    assert len(extraction.rows) == 1
    row, _printed = extraction.rows[0]
    assert (row.metric_id, row.value) == expected


def _growth_pages(change: ExtractedValue | None) -> list[PageExtraction]:
    values = [_signed_value("Annual recurring revenue", "210.0")]
    if change is not None:
        values.append(change)
    return [
        PageExtraction(cover_date=date(2026, 3, 1), values=[]),
        PageExtraction(cover_date=None, values=values),
        PageExtraction(cover_date=None, values=[]),
        PageExtraction(cover_date=None, values=[]),
    ]


def _growth_page_texts(change_printed: str) -> list[str]:
    return [
        "Nimbus SaaS \u2014 Board Update, March 2026",
        f"Q2 2026 (\u20acm)\nAnnual recurring revenue 210.0\nARR growth {change_printed}",
        "",
        "",
    ]


def test_the_prompt_tells_the_model_to_give_no_object_for_a_change_figure(
    dictionary: Dictionary,
) -> None:
    """S3-14, criteria 1 and 2 are prompt behaviour, and no test calls a live LLM.
    So the test pins the rule in the prompt text: an edit that drops it fails here.
    """
    system = extract_module._system_prompt(dictionary)

    assert "Give no object for a change figure" in system
    assert "A figure in percentage points" in system
    assert "A metric that compares two periods is still a value" in system
    # Criterion 2: the figure pattern accepts a minus, so this prompt line is the only guard.
    assert 'Skip it with any sign, with "%" or without' in system
    # S3-20 narrows this rule: a "%" column is a share column beside its own period's amount,
    # and a change column only when it follows two or more period columns.
    assert 'A column headed only "%" is a share column' in system


def test_a_change_column_the_model_skipped_leaves_the_period_value_alone(
    dictionary: Dictionary, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S3-14, criteria 1 and 2, on the code path. The page prints a growth row and
    the response follows the prompt rule: it gives the period value and no change value. The
    transcript then holds one row and names nothing.
    """
    _patch_page_texts(monkeypatch, _growth_page_texts("+12.4%"))

    extraction = extract_deck(NIMBUS_PDF, dictionary, SOURCE, _fake_complete(_growth_pages(None)))

    assert [(row.metric_id, row.value) for row, _printed in extraction.rows] == [
        ("arr", Decimal(210000000))
    ]
    assert extraction.left_out == []


@pytest.mark.parametrize(
    ("printed", "rows", "left_out"),
    [
        (
            "+12.4%",
            [("arr", Decimal(210000000))],
            ["p2: '+12.4%': '+12.4%' is not one point figure"],
        ),
        ("-3.0%", [("arr", Decimal(210000000)), ("arr_growth", Decimal("-3.0"))], []),
    ],
    ids=["plus-is-left-out", "minus-passes-the-pattern"],
)
def test_a_change_value_the_model_gives_anyway(
    dictionary: Dictionary,
    monkeypatch: pytest.MonkeyPatch,
    printed: str,
    rows: list[tuple[str, Decimal]],
    left_out: list[str],
) -> None:
    """S3-14, criterion 3. ``_SIGN`` accepts a minus only, so a change value with a
    leading plus is left out and named (S3-05), and the period value of the same table is
    written. A change printed with a minus passes the figure pattern and is written as a slug
    row: for that form the prompt rule is the only guard.
    """
    _patch_page_texts(monkeypatch, _growth_page_texts(printed))
    change = _signed_value("ARR growth", printed).model_copy(
        update={"scale": "", "unit": "percent"}
    )
    pages = _growth_pages(change)

    extraction = extract_deck(NIMBUS_PDF, dictionary, SOURCE, _fake_complete(pages))

    assert [(row.metric_id, row.value) for row, _printed in extraction.rows] == rows
    assert extraction.left_out == left_out


_OPEX_PAGE_TEXT = (
    "Q2 2026 (\u20acm)\n"
    "Operating expenses\n"
    "Sales          (4.2)\n"
    "Marketing      (3.1)\n"
    "R&D            (6.0)\n"
    "G&A            (2.4)"
)


def _opex_pages(values: list[ExtractedValue]) -> list[PageExtraction]:
    return [
        PageExtraction(cover_date=date(2026, 3, 1), values=[]),
        PageExtraction(cover_date=None, values=values),
        PageExtraction(cover_date=None, values=[]),
        PageExtraction(cover_date=None, values=[]),
    ]


def test_a_cost_line_written_in_full_maps_to_its_own_slug_not_to_revenue(
    dictionary: Dictionary, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S3-15, criterion 1. The page prints the bare cost lines of an operating
    expense block and the response follows the prompt rule: each label carries the added word
    "expenses". The label check accepts the printed part, so every row is written, with its
    own slug and the positive amount of a cost (S3-18). "Sales" reaches no revenue metric.
    """
    values = [
        _signed_value("Sales expenses", "(4.2)"),
        _signed_value("Marketing expenses", "(3.1)"),
        _signed_value("R&D expenses", "(6.0)"),
        _signed_value("G&A expenses", "(2.4)"),
    ]
    _patch_page_texts(
        monkeypatch,
        ["Nimbus SaaS \u2014 Board Update, March 2026", _OPEX_PAGE_TEXT, "", ""],
    )

    extraction = extract_deck(NIMBUS_PDF, dictionary, SOURCE, _fake_complete(_opex_pages(values)))

    rows = [(row.stated_label, row.metric_id, row.value) for row, _printed in extraction.rows]
    assert rows == [
        ("Sales expenses", "sales_expenses", Decimal(4200000)),
        ("Marketing expenses", "marketing_expenses", Decimal(3100000)),
        ("R&D expenses", "r_d_expenses", Decimal(6000000)),
        ("G&A expenses", "g_a_expenses", Decimal(2400000)),
    ]
    assert not {metric_id for _label, metric_id, _value in rows} & dictionary.metric_ids
    assert extraction.left_out == []


def test_a_revenue_top_line_named_sales_stays_ambiguous_revenue(
    dictionary: Dictionary, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S3-15, criterion 2. The rule holds inside a cost block only, so the top
    line of a revenue table still maps to the umbrella with its candidates.
    """
    value = _signed_value("Sales", "12.5").model_copy(
        update={"candidate_metric_ids": ["revenue_recognised", "arr"]}
    )
    _patch_page_texts(
        monkeypatch,
        [
            "Nimbus SaaS \u2014 Board Update, March 2026",
            "Q2 2026 (\u20acm)\nSales          12.5\nGross profit    7.1",
            "",
            "",
        ],
    )

    extraction = extract_deck(NIMBUS_PDF, dictionary, SOURCE, _fake_complete(_opex_pages([value])))

    row = extraction.rows[0][0]
    assert (row.metric_id, row.value) == ("revenue_unspecified", Decimal(12500000))
    assert row.definition_status is DefinitionStatus.AMBIGUOUS
    assert row.candidate_metric_ids == ("revenue_recognised", "arr")


def test_a_cost_label_whose_first_word_the_page_never_prints_is_left_out(
    dictionary: Dictionary, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S3-15. The label check drops the added word only. A label the page prints
    nowhere, with or without that word, is still left out and named (S3-05).
    """
    _patch_page_texts(
        monkeypatch,
        ["Nimbus SaaS \u2014 Board Update, March 2026", _OPEX_PAGE_TEXT, "", ""],
    )
    values = [_signed_value("Travel expenses", "(4.2)")]

    extraction = extract_deck(NIMBUS_PDF, dictionary, SOURCE, _fake_complete(_opex_pages(values)))

    assert extraction.rows == []
    assert extraction.left_out == [
        "p2: '(4.2)': stated_label and printed are not on one line or in one column"
    ]


def test_a_cost_label_still_pairs_with_a_revenue_figure_on_a_page_with_no_cost_block() -> None:
    """Known gap, not a wanted feature. ``_label_pairs_with_figure``
    drops the added word for every label that ends with it, with no check for a cost block.
    A revenue page that never prints a cost word still pairs "Sales expenses" with the
    revenue figure of "Sales". A fix that reads the cost block before it drops the word must
    flip this assertion to ``False`` on purpose.
    """
    page_text = "Q2 2026 (EURm)\nRevenue by line\nSales          12.5\nServices        3.1"

    assert (
        extract_module._label_pairs_with_figure("Sales expenses", "12.5", page_text, "EUR") is True
    )


def test_the_prompt_tells_the_model_to_write_a_cost_line_in_full(dictionary: Dictionary) -> None:
    """S3-15, criteria 1 and 2 are prompt behaviour, and no test calls a live LLM.
    So the test pins the rule in the prompt text: an edit that drops it fails here.
    """
    system = extract_module._system_prompt(dictionary)

    assert f'Add the one word "{COST_LINE_WORD}" after a short cost-line label' in system
    assert f'the word "{COST_LINE_WORD}" that the cost-line rule adds' in system


_MARGIN_PAGE_TEXT = (
    "Q2 2026 (\u20acm)\n"
    "Gross profit        45.0\n"
    "% Margin             90%\n"
    "Adjusted EBITDA     20.0\n"
    "% Margin             40%"
)


def _percent_value(label: str, printed: str) -> ExtractedValue:
    return _signed_value(label, printed).model_copy(update={"scale": "", "unit": "percent"})


def _margin_page_texts(page_two: str) -> list[str]:
    return ["Nimbus SaaS \u2014 Board Update, March 2026", page_two, "", ""]


def test_two_generic_margin_rows_take_the_metric_of_the_row_above_each_one(
    dictionary: Dictionary, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S3-17, criterion 1. The page prints "% Margin" on both percent rows, and the
    response follows the prompt rule: each label carries the metric of the row above it. The
    two rows reach two margin metrics, so one quarter's 90% and 40% never collapse into one.
    """
    values = [
        _signed_value("Gross profit", "45.0"),
        _percent_value("Gross profit margin", "90%"),
        _signed_value("Adjusted EBITDA", "20.0"),
        _percent_value("Adjusted EBITDA margin", "40%"),
    ]
    _patch_page_texts(monkeypatch, _margin_page_texts(_MARGIN_PAGE_TEXT))

    extraction = extract_deck(NIMBUS_PDF, dictionary, SOURCE, _fake_complete(_opex_pages(values)))

    assert [(row.metric_id, row.value) for row, _printed in extraction.rows] == [
        ("gross_profit", Decimal(45000000)),
        ("gross_margin", Decimal(90)),
        ("ebitda_adjusted", Decimal(20000000)),
        ("ebitda_adjusted_margin", Decimal(40)),
    ]
    assert extraction.left_out == []


def test_a_generic_margin_label_with_no_row_above_is_left_out_and_named(
    dictionary: Dictionary, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S3-17, criterion 2. The generic row is the first row of the page, so the
    model has nothing to combine and gives the label as printed. It names no metric (S3-05).
    """
    page_text = "% Margin             90%\nGross profit        45.0\nQ2 2026 (\u20acm)"
    _patch_page_texts(monkeypatch, _margin_page_texts(page_text))
    values = [_percent_value("% Margin", "90%")]

    extraction = extract_deck(NIMBUS_PDF, dictionary, SOURCE, _fake_complete(_opex_pages(values)))

    assert extraction.rows == []
    assert extraction.left_out == ["p2: '90%': a generic margin label names no metric"]


@pytest.mark.parametrize(
    ("page_text", "label", "printed"),
    [
        (_MARGIN_PAGE_TEXT, "EBIT margin", "90%"),
        (
            "Q2 2026 (\u20acm)\nGross profit        45.0\nNRR (%)             118",
            "Gross profit margin",
            "118",
        ),
        (
            "Q2 2026\nAdjusted EBITDA     20.0\nMonthly logo churn   2.1 %",
            "Adjusted EBITDA margin",
            "2.1",
        ),
        (
            "Q2 2026\nAdjusted EBITDA     20.0\n% Margin             40%",
            "EBITDA margin",
            "40%",
        ),
    ],
    ids=[
        "other-row-above",
        "percent-unit-in-brackets",
        "figures-own-percent-sign",
        "part-of-row-above",
    ],
)
def test_a_combined_margin_label_whose_first_part_is_not_the_row_above_is_left_out(
    page_text: str,
    label: str,
    printed: str,
    dictionary: Dictionary,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """S3-17. The check reads the nearest text line above the
    figure only. A "%" unit marker in brackets, or a figure's own "%", is not a stand-alone
    generic-row label of its own (S3-13). A combined label whose first part names another row,
    or only part of the row above, is left out and named (S3-05).
    """
    _patch_page_texts(monkeypatch, _margin_page_texts(page_text))
    values = [_percent_value(label, printed)]

    extraction = extract_deck(NIMBUS_PDF, dictionary, SOURCE, _fake_complete(_opex_pages(values)))

    assert extraction.rows == []
    assert extraction.left_out == [
        f"p2: {printed!r}: stated_label and printed are not on one line or in one column"
    ]


@pytest.mark.parametrize(
    ("rows", "label", "metric_id"),
    [
        ("Gross profit (\u20acm)   45.0\n% Margin   90%", "Gross profit margin", "gross_margin"),
        ("Gross margin   45.0\n%   90%", "Gross margin %", "gross_margin"),
        (
            "Sales and marketing expenses   12.0\n% of revenue   90%",
            "Sales and marketing expenses % of revenue",
            "sales_and_marketing_expenses_of_revenue",
        ),
        (
            "Adjusted EBITDA     20.0\n% Margin   90%",
            "Adjusted EBITDA margin",
            "ebitda_adjusted_margin",
        ),
    ],
    ids=["unit-in-brackets", "margin-above", "cost-share", "complete-row-above"],
)
def test_each_added_part_of_a_combined_margin_label_passes_the_label_check(
    rows: str,
    label: str,
    metric_id: str,
    dictionary: Dictionary,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """S3-17. The prompt adds "margin", "%" after a label that ends
    with "margin", or the generic label as printed under a cost line, because a cost share of
    revenue is not a margin.
    """
    page_text = f"Q2 2026\n{rows}"
    _patch_page_texts(monkeypatch, _margin_page_texts(page_text))
    values = [_percent_value(label, "90%")]

    extraction = extract_deck(NIMBUS_PDF, dictionary, SOURCE, _fake_complete(_opex_pages(values)))

    assert [row.metric_id for row, _printed in extraction.rows] == [metric_id]
    assert extraction.left_out == []


def test_a_second_copy_of_the_figure_without_a_generic_label_names_no_row_above(
    dictionary: Dictionary, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S3-17. The generic label and the row above must belong to one
    copy of the figure, so "90%" under "EBIT" never borrows the "% Margin" of another row.
    """
    page_text = "Q2 2026\nGross profit   45.0\n% Margin   90%\nEBIT   10.0\nTarget   90%"
    _patch_page_texts(monkeypatch, _margin_page_texts(page_text))
    values = [_percent_value("EBIT margin", "90%")]

    extraction = extract_deck(NIMBUS_PDF, dictionary, SOURCE, _fake_complete(_opex_pages(values)))

    assert extraction.rows == []
    assert extraction.left_out == [
        "p2: '90%': stated_label and printed are not on one line or in one column"
    ]


def test_the_prompt_tells_the_model_to_combine_a_generic_row_with_the_row_above(
    dictionary: Dictionary,
) -> None:
    """S3-17, criteria 1 and 2 are prompt behaviour, and no test calls a live LLM.
    So the test pins the rule and the label list in the prompt text.
    """
    system = extract_module._system_prompt(dictionary)

    assert 'under an "Adjusted EBITDA" row gives "Adjusted EBITDA margin"' in system
    assert 'A "%" row under a "Gross margin" row gives "Gross margin %"' in system
    assert "a cost share of revenue is not a margin" in system
    assert "the part that the generic-row rule adds" in system
    for label in GENERIC_MARGIN_LABELS:
        assert f'"{label}"' in system.casefold()


def test_the_prompt_tells_the_model_to_label_a_percent_beside_its_amount(
    dictionary: Dictionary,
) -> None:
    """S3-20, criteria 1 and 2 are prompt behaviour, and no test calls a live LLM.
    So the test pins the two readings that S3-17 leaves open.
    """
    system = extract_module._system_prompt(dictionary)

    assert "A percent can also stand in the same row as its amount" in system
    assert "A cell of a column headed with one of the generic labels above" in system
    assert "Both rules need the amount" in system
    assert "It is a change column when the table prints two or more period columns" in system
    assert (
        "Never write the row label alone for a percent that stands beside its own amount" in system
    )


def test_the_prompt_tells_the_model_where_a_qualifier_sits_and_which_bases_are_closed(
    dictionary: Dictionary,
) -> None:
    """S3-12, criteria 1, 2 and 4 are prompt behaviour, and no test calls a live
    LLM. So the test pins the three marker places, the group markers and the closed basis list.
    """
    system = extract_module._system_prompt(dictionary)

    assert "A marker can sit in three places" in system
    assert "A heading that names the kind of split states no marker" in system
    assert "Take the marker out of `stated_label`, as you take a period out" in system
    assert 'A bare "Total" is not a group marker' in system
    for marker in ("Group", "Consolidated", "Consolidated group", "Group total", "Total group"):
        assert f'"{marker}"' in system
    assert '"reported", "pro_forma" and "constant_currency". Write one of the three' in system
    assert 'Do not write "reported" for a figure that prints no basis word' in system
    assert "write that word in `basis` exactly as the page prints it" in system


_MARGIN_ROW_PAGE_TEXT = (
    "Q2 2026 (\u20acm)\nRecognised revenue   200.0\nEBITDA                60.0        30.0%"
)

_MARGIN_COLUMN_PAGE_TEXT = (
    "Q2 2026 (\u20acm)                        % of revenue\n"
    "Recognised revenue   200.0\n"
    "EBITDA                60.0                     30.0%"
)


def test_a_percent_in_the_same_row_as_its_amount_maps_to_the_margin_metric(
    dictionary: Dictionary, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S3-20, criterion 1. The page prints "EBITDA 60.0 30.0%" in one row, with no
    generic label anywhere on the page. The prompt gives the percent value the combined
    label "EBITDA margin" (the S3-17 convention), so it must map to ``ebitda_margin``, never
    to the EBITDA amount's metric_id.
    """
    values = [
        _signed_value("Recognised revenue", "200.0"),
        _signed_value("EBITDA", "60.0"),
        _percent_value("EBITDA margin", "30.0%"),
    ]
    _patch_page_texts(monkeypatch, _margin_page_texts(_MARGIN_ROW_PAGE_TEXT))

    extraction = extract_deck(NIMBUS_PDF, dictionary, SOURCE, _fake_complete(_opex_pages(values)))

    assert [(row.metric_id, row.value) for row, _printed in extraction.rows] == [
        ("revenue_recognised", Decimal(200000000)),
        ("ebitda", Decimal(60000000)),
        ("ebitda_margin", Decimal(30)),
    ]
    assert extraction.left_out == []


def test_a_percent_of_revenue_column_cell_maps_to_the_margin_metric(
    dictionary: Dictionary, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S3-20, criterion 2. The table prints an amount column and a column headed
    "% of revenue". The EBITDA row's own line still carries both figures, so the cell of the
    percent column must map to ``ebitda_margin`` and the cell of the amount column must keep
    the EBITDA amount's metric_id.
    """
    values = [
        _signed_value("Recognised revenue", "200.0"),
        _signed_value("EBITDA", "60.0"),
        _percent_value("EBITDA margin", "30.0%"),
    ]
    _patch_page_texts(monkeypatch, _margin_page_texts(_MARGIN_COLUMN_PAGE_TEXT))

    extraction = extract_deck(NIMBUS_PDF, dictionary, SOURCE, _fake_complete(_opex_pages(values)))

    rows = {row.stated_label: row.metric_id for row, _printed in extraction.rows}
    assert rows == {
        "Recognised revenue": "revenue_recognised",
        "EBITDA": "ebitda",
        "EBITDA margin": "ebitda_margin",
    }
    assert extraction.left_out == []


def test_a_percent_value_labeled_with_a_currency_metric_is_left_out_and_named(
    dictionary: Dictionary, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S3-20, criterion 3. A model reply drops the "margin" suffix and labels
    "30.0%" as plain "EBITDA", so ``map_label`` resolves a currency-dimension metric id
    (``ebitda``) for a percent-unit value. The guard must leave such a row out and name it, so
    no percent value ever carries a currency metric id.
    """
    _patch_page_texts(monkeypatch, _margin_page_texts("Q2 2026 (\u20acm)\nEBITDA   30.0%"))
    values = [_percent_value("EBITDA", "30.0%")]

    extraction = extract_deck(NIMBUS_PDF, dictionary, SOURCE, _fake_complete(_opex_pages(values)))

    assert extraction.rows == []
    assert extraction.left_out == ["p2: '30.0%': a percent value cannot carry a currency metric"]


def test_a_kpi_rate_beside_its_own_percent_still_maps_to_the_rate_metric(
    dictionary: Dictionary, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S3-20, open question. The guard now checks every dictionary metric, not only
    currency, so a percent value must still be written when its own metric's dimension is
    percent. "Monthly logo churn" is an alias of ``churn_logo_monthly`` (dimension percent),
    and the page prints no amount for it: the label states the value of its own row.
    """
    _patch_page_texts(monkeypatch, _margin_page_texts("Q2 2026\nMonthly logo churn   2.1%"))
    values = [_percent_value("Monthly logo churn", "2.1%")]

    extraction = extract_deck(NIMBUS_PDF, dictionary, SOURCE, _fake_complete(_opex_pages(values)))

    assert [(row.metric_id, row.value) for row, _printed in extraction.rows] == [
        ("churn_logo_monthly", Decimal("2.1")),
    ]
    assert extraction.left_out == []


def test_a_basis_outside_the_three_values_is_left_out_and_named(
    dictionary: Dictionary, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S3-12, criterion 4. The page prints a basis marker, "organic", beside an
    amount. "organic" fails the three basis tests of story S3-12: its
    perimeter is a choice each company makes, so it does not restate one closed reporting
    basis. The row is left out and named (S3-05), never written as ``reported``.

    ``basis`` is a required field of ``ExtractedValue``. ``.model_copy(update=...)`` still
    overrides it here, the same technique ``_percent_value`` uses for ``unit`` and ``scale``.
    """
    _patch_page_texts(
        monkeypatch, _margin_page_texts("Q2 2026 (\u20acm)\nAdjusted EBITDA (organic)   20.0")
    )
    values = [_signed_value("Adjusted EBITDA", "20.0").model_copy(update={"basis": "organic"})]

    extraction = extract_deck(NIMBUS_PDF, dictionary, SOURCE, _fake_complete(_opex_pages(values)))

    assert extraction.rows == []
    assert extraction.left_out == [
        "p2: '20.0': basis 'organic' is not reported, pro_forma or constant_currency"
    ]


def test_a_figure_with_a_space_or_an_iso_code_passes_the_same_as_its_compact_form(
    dictionary: Dictionary, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S3-13, criteria 1 to 3."""

    def value(label: str, printed: str, scale: Literal["", "m", "bn"], unit: str) -> ExtractedValue:
        return _signed_value(label, printed).model_copy(update={"scale": scale, "unit": unit})

    spaced = [
        value("Widget retention", "97 %", "", "percent"),
        value("Order intake", "EUR 42.5m", "m", "EUR"),
        value("Payment volume", "\u20ac 12.3 bn", "bn", "\u20ac"),
    ]
    compact = [
        value("Widget retention", "97%", "", "percent"),
        value("Order intake", "\u20ac42.5m", "m", "\u20ac"),
        value("Payment volume", "\u20ac12.3bn", "bn", "\u20ac"),
    ]
    pages = [
        PageExtraction(cover_date=date(2026, 3, 1), values=[]),
        PageExtraction(cover_date=None, values=spaced),
        PageExtraction(cover_date=None, values=compact),
        PageExtraction(cover_date=None, values=[]),
    ]
    _patch_page_texts(
        monkeypatch,
        [
            "Nimbus SaaS \u2014 Board Update, March 2026",
            "Q2 2026\nWidget retention 97 %\nOrder intake EUR 42.5m\nPayment volume \u20ac 12.3 bn",
            "Q2 2026\nWidget retention 97%\nOrder intake \u20ac42.5m\nPayment volume \u20ac12.3bn",
            "",
        ],
    )

    extraction = extract_deck(NIMBUS_PDF, dictionary, SOURCE, _fake_complete(pages))

    assert extraction.left_out == []
    rows = [(row.value, row.stated_precision, row.currency) for row, _printed in extraction.rows]
    assert rows[:3] == rows[3:]


def _extract_text_or(blank_text: str, page_number: int = 4) -> Callable[..., str]:
    """Replace the real text of one page, so pypdf never reads an empty content stream."""
    original: Callable[..., str] = PageObject.extract_text

    def patched(self: PageObject, *args: object, **kwargs: object) -> str:
        return blank_text if self.page_number == page_number else original(self, *args, **kwargs)

    return patched


def _recording_complete(calls: list[str]) -> Complete:
    responses = iter([*_recorded(), PageExtraction(cover_date=None, values=[])])

    def complete(system: str, user: str, schema: type[PageExtraction]) -> PageExtraction:
        del system, schema
        calls.append(user)
        return next(responses)

    return complete


@pytest.mark.parametrize("blank_text", ["", "  \n\t "], ids=["empty", "whitespace-only"])
def test_a_blank_or_whitespace_only_page_gets_no_llm_call(
    dictionary: Dictionary, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, blank_text: str
) -> None:
    """S3-09. The last page of a real deck can have no text. That page must get no
    LLM call. Extraction must still return the rows of the other pages.
    """
    pdf_path = tmp_path / "nimbus-with-blank-last-page.pdf"
    writer = PdfWriter(clone_from=NIMBUS_PDF)
    writer.add_blank_page()
    with pdf_path.open("wb") as handle:
        writer.write(handle)
    monkeypatch.setattr(PageObject, "extract_text", _extract_text_or(blank_text))

    calls: list[str] = []
    extraction = extract_deck(pdf_path, dictionary, SOURCE, _recording_complete(calls))

    assert len(calls) == 4, "a blank or whitespace-only page must get no LLM call"
    assert extraction.pages == 5
    rows = {o.observation_id.removeprefix("nimbus-pdf-2025-"): o for o, _ in extraction.rows}
    assert list(rows) == list(_EXPECTED)
