"""Pure extraction rules (S3-01).

``parse_figure`` and ``currency_for`` need no dictionary. ``map_label`` uses the real
dictionary for M1 and M2 (an alias must exist to test them) and a synthetic one, built
with ``tests.factories.make_metric``, for the M3 slug edge cases that need a fixed set of
existing ids.
"""

import re
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from fact_ledger.domain import DefinitionStatus, Dictionary
from fact_ledger.domain.extraction import currency_for, map_label, parse_figure, prints_period
from fact_ledger.store.yaml_files import load_dictionary
from tests.factories import make_metric

pytestmark = pytest.mark.unit

DICTIONARY_DIR = Path(__file__).resolve().parents[2] / "data" / "dictionary"


@pytest.fixture(scope="module")
def dictionary() -> Dictionary:
    return load_dictionary(DICTIONARY_DIR)


@pytest.mark.parametrize(
    ("printed", "scale", "unit", "value", "precision"),
    [
        ("~€8m", "m", "€", Decimal(8000000), Decimal(500000)),
        ("€8.4m", "m", "EUR", Decimal(8400000), Decimal(50000)),
        ("€700k", "k", "€", Decimal(700000), Decimal(500)),
        ("7,450", "k", "€", Decimal(7450000), Decimal(500)),
        ("€1.2bn", "bn", "€", Decimal(1200000000), Decimal(50000000)),
        ("9.2%", "", "percent", Decimal("9.2"), Decimal("0.05")),
        ("3.2x", "", "ratio", Decimal("3.2"), Decimal("0.05")),
        ("186", "", "count", Decimal(186), None),
        # S3-13: a space before "%", an ISO code, a space after the symbol or before the scale
        ("97 %", "", "percent", Decimal(97), None),
        ("EUR 42.5m", "m", "EUR", Decimal(42500000), Decimal(50000)),
        ("EUR42.5m", "m", "EUR", Decimal(42500000), Decimal(50000)),
        ("€ 12.3 bn", "bn", "€", Decimal(12300000000), Decimal(50000000)),
        ("EUR -4.2m", "m", "EUR", Decimal(-4200000), Decimal(50000)),
        # a symbol and its ISO code are the same currency printed in either position
        ("EUR 42.5m", "m", "€", Decimal(42500000), Decimal(50000)),
    ],
)
def test_parse_figure_reads_the_value_and_the_stated_precision(
    printed: str, scale: str, unit: str, value: Decimal, precision: Decimal | None
) -> None:
    parsed_value, parsed_precision = parse_figure(printed, scale, unit)
    assert parsed_value == value
    assert parsed_precision == precision


@pytest.mark.parametrize(
    ("printed", "scale"),
    [
        ("over €8m", "m"),
        ("€8m+", "m"),
        ("up to 5%", ""),
        ("€5m-€8m", "m"),
        ("c. €8m", "k"),
        ("TBD", ""),
        ("€8,4m", "m"),  # a comma not followed by exactly 3 digits
        ("7.450", "k"),  # a dot before exactly 3 digits, no comma, no printed scale letter
        (">100", ""),  # a bound sign is not a currency symbol
        ("7.450", ""),  # no scale, "%" or "x" to anchor the dot
        ("\u201312.3", ""),  # S3-08: an en dash is a nil or range mark, never a sign
        ("-(12.3)", "m"),
        ("-\u20ac-4.2", "m"),
        ("12(3)", ""),
        ("(12.3", "m"),
        ("EUR\t42.5m", "m"),  # S3-13 permits a literal space only, never a tab
        ("EUR\n42.5m", "m"),  # S3-13 permits a literal space only, never a line break
    ],
)
def test_parse_figure_rejects_a_bound_a_range_or_unparseable_text(printed: str, scale: str) -> None:
    with pytest.raises(ValueError):  # noqa: PT011 -- the message format is not part of the contract
        parse_figure(printed, scale, "€")


@pytest.mark.parametrize(
    ("printed", "unit"),
    [("97  %", "percent"), ("3.2 x", "ratio"), ("€  12.3", "€")],
)
def test_parse_figure_rejects_more_than_the_s3_13_spaces(printed: str, unit: str) -> None:
    with pytest.raises(ValueError, match="not one point figure"):
        parse_figure(printed, "", unit)


@pytest.mark.parametrize(
    ("printed", "scale", "unit", "value", "precision"),
    [
        ("-4.2", "m", "EUR", Decimal(-4200000), Decimal(50000)),
        ("(12.3)", "m", "EUR", Decimal(-12300000), Decimal(50000)),
        ("\u22124.2", "m", "EUR", Decimal(-4200000), Decimal(50000)),
        ("\u20ac-4.2m", "m", "\u20ac", Decimal(-4200000), Decimal(50000)),
        ("\u20ac(12.3)m", "m", "\u20ac", Decimal(-12300000), Decimal(50000)),
        ("(12.3)m", "m", "EUR", Decimal(-12300000), Decimal(50000)),
        ("\u20ac(12.3)", "m", "\u20ac", Decimal(-12300000), Decimal(50000)),
        ("(\u20ac12.3m)", "m", "\u20ac", Decimal(-12300000), Decimal(50000)),
        ("(0.0)", "", "EUR", Decimal(0), Decimal("0.05")),
    ],
)
def test_parse_figure_reads_a_hyphen_minus_or_round_brackets_as_negative(
    printed: str, scale: str, unit: str, value: Decimal, precision: Decimal
) -> None:
    parsed_value, parsed_precision = parse_figure(printed, scale, unit)
    assert parsed_value == value
    assert str(parsed_value) == str(value)  # "-0" would compare equal to 0
    assert parsed_precision == precision


@pytest.mark.parametrize(
    ("printed", "scale", "unit"),
    [
        ("€8.4m", "m", "count"),
        ("€8.4m", "m", "£"),
        ("9.2%", "", "ratio"),
        ("3.2x", "", "€"),
        ("EUR 42.5m", "m", "GBP"),
        ("GBP 42.5m", "m", "€"),
    ],
)
def test_parse_figure_rejects_a_unit_that_the_figure_contradicts(
    printed: str, scale: str, unit: str
) -> None:
    with pytest.raises(ValueError, match="disagrees with unit"):
        parse_figure(printed, scale, unit)


@pytest.mark.parametrize(
    ("unit", "currency"),
    [
        ("€", "EUR"),
        ("£", "GBP"),
        ("USD", "USD"),
        ("percent", None),
        ("ratio", None),
        ("count", None),
    ],
)
def test_currency_for_maps_a_symbol_an_iso_code_or_none(unit: str, currency: str | None) -> None:
    assert currency_for(unit) == currency


@pytest.mark.parametrize("unit", ["$", "kr"])
def test_currency_for_rejects_a_symbol_more_than_one_currency_uses(unit: str) -> None:
    with pytest.raises(ValueError, match=re.escape(unit)):
        currency_for(unit)


def test_m1_a_resolved_alias_maps_to_its_metric_id_with_no_candidates(
    dictionary: Dictionary,
) -> None:
    metric_id, status, candidates = map_label("ARR", [], dictionary)
    assert metric_id == "arr"
    assert status is DefinitionStatus.RESOLVED
    assert candidates == ()


def test_m1_a_resolved_alias_rejects_a_given_candidate(dictionary: Dictionary) -> None:
    with pytest.raises(ValueError):  # noqa: PT011 -- the message format is not part of the contract
        map_label("ARR", ["mrr"], dictionary)


@pytest.mark.parametrize("label", ["Revenue", "Revenues"])
def test_m2_an_umbrella_alias_maps_to_the_umbrella_id_with_its_candidates(
    label: str, dictionary: Dictionary
) -> None:
    metric_id, status, candidates = map_label(label, ["revenue_recognised", "arr"], dictionary)
    assert metric_id == "revenue_unspecified"
    assert status is DefinitionStatus.AMBIGUOUS
    assert candidates == ("revenue_recognised", "arr")


def test_m2_an_umbrella_alias_rejects_no_candidates(dictionary: Dictionary) -> None:
    with pytest.raises(ValueError):  # noqa: PT011 -- the message format is not part of the contract
        map_label("Revenue", [], dictionary)


@pytest.mark.parametrize("candidate", ["not_a_real_metric_id", "revenue_unspecified", "nrr"])
def test_m2_an_umbrella_alias_rejects_a_candidate_outside_its_usual_candidates(
    dictionary: Dictionary, candidate: str
) -> None:
    with pytest.raises(ValueError, match="not a usual candidate"):
        map_label("Revenue", [candidate], dictionary)


@pytest.mark.parametrize(
    ("label", "metric_id"),
    [
        ("Cost of sales", "cost_of_sales"),
        ("Gross profit", "gross_profit"),
        ("EBITDA", "ebitda"),
        ("EBIT", "ebit"),
        ("Net income", "net_income"),
        ("Profit before tax (EBT)", "ebt"),
        ("EBT", "ebt"),
        ("Earnings before tax", "ebt"),
        ("Earnings before taxes", "ebt"),
    ],
)
def test_s3_19_a_listed_company_income_statement_line_resolves_to_its_metric_id(
    label: str, metric_id: str, dictionary: Dictionary
) -> None:
    resolved, status, candidates = map_label(label, [], dictionary)
    assert resolved == metric_id
    assert status is DefinitionStatus.RESOLVED
    assert candidates == ()


def test_s3_19_an_operating_expense_line_stays_a_slug(dictionary: Dictionary) -> None:
    metric_id, status, candidates = map_label("Personnel expenses", [], dictionary)
    assert metric_id == "personnel_expenses"
    assert status is DefinitionStatus.RESOLVED
    assert candidates == ()


def test_s3_19_gross_margin_maps_to_the_margin_umbrella(dictionary: Dictionary) -> None:
    metric_id, status, candidates = map_label(
        "Gross margin", ["gross_profit", "gross_margin"], dictionary
    )
    assert metric_id == "margin_unspecified"
    assert status is DefinitionStatus.AMBIGUOUS
    assert candidates == ("gross_profit", "gross_margin")


def test_m3_an_undefined_label_maps_to_its_slug(dictionary: Dictionary) -> None:
    metric_id, status, candidates = map_label("Pipeline coverage", [], dictionary)
    assert metric_id == "pipeline_coverage"
    assert status is DefinitionStatus.RESOLVED
    assert candidates == ()


def test_m3_an_undefined_label_rejects_a_given_candidate(dictionary: Dictionary) -> None:
    with pytest.raises(ValueError):  # noqa: PT011 -- the message format is not part of the contract
        map_label("Pipeline coverage", ["arr"], dictionary)


def test_m4_a_label_with_extra_words_around_an_alias_stays_undefined(
    dictionary: Dictionary,
) -> None:
    # No alias holds these exact words, so M3 applies: never a guess built from a shorter alias.
    metric_id, status, _candidates = map_label("Avg. monthly logo churn", [], dictionary)
    assert metric_id == "avg_monthly_logo_churn"
    assert status is DefinitionStatus.RESOLVED


def test_m3_slug_strips_accents_punctuation_and_collapses_runs(dictionary: Dictionary) -> None:
    metric_id, _status, _candidates = map_label("Café ARR growth!!", [], dictionary)
    assert metric_id == "cafe_arr_growth"


def test_m3_slug_of_a_label_starting_with_a_digit_gets_an_m_prefix(dictionary: Dictionary) -> None:
    metric_id, _status, _candidates = map_label("2024 Bookings", [], dictionary)
    assert metric_id == "m_2024_bookings"


def test_m3_slug_colliding_with_a_dictionary_id_gets_the_undefined_suffix() -> None:
    empty = Dictionary(metrics=(make_metric("widgets"),), identities=())
    metric_id, _status, _candidates = map_label("Widgets", [], empty)
    assert metric_id == "widgets_undefined"


@pytest.mark.parametrize(
    ("printed_token", "start", "end"),
    [
        ("Q1-26", date(2026, 1, 1), date(2026, 3, 31)),
        ("Q2-26", date(2026, 4, 1), date(2026, 6, 30)),
        ("Q3-26", date(2026, 7, 1), date(2026, 9, 30)),
        ("Q4-26", date(2026, 10, 1), date(2026, 12, 31)),
        ("H1-26", date(2026, 1, 1), date(2026, 6, 30)),
        ("6M-26", date(2026, 1, 1), date(2026, 6, 30)),
        ("9M-26", date(2026, 1, 1), date(2026, 9, 30)),
        ("H2-26", date(2026, 7, 1), date(2026, 12, 31)),
        ("Q2 26", date(2026, 4, 1), date(2026, 6, 30)),
        ("Q2'26", date(2026, 4, 1), date(2026, 6, 30)),
        ("Q2\u201926", date(2026, 4, 1), date(2026, 6, 30)),
        ("FY26", date(2026, 1, 1), date(2026, 12, 31)),
        ("FY-26", date(2026, 1, 1), date(2026, 12, 31)),
        ("YTD Sep 24", date(2024, 1, 1), date(2024, 9, 30)),
        # a financial year that ends on 31 March: FY26 is April 2025 to March 2026
        ("FY26", date(2025, 4, 1), date(2026, 3, 31)),
        ("H1 FY26", date(2025, 4, 1), date(2025, 9, 30)),
        ("Q3 FY26", date(2025, 10, 1), date(2025, 12, 31)),
        ("H2-FY26", date(2025, 10, 1), date(2026, 3, 31)),
        ("YTD Sep 25", date(2025, 4, 1), date(2025, 9, 30)),
    ],
)
def test_prints_period_expands_each_token_to_its_year_window(
    printed_token: str, start: date, end: date
) -> None:
    assert prints_period(f"Growth  {printed_token}  metrics", start, end)


def test_prints_period_rejects_a_token_whose_year_disagrees() -> None:
    assert not prints_period("H1-25 metrics", date(2026, 1, 1), date(2026, 6, 30))


@pytest.mark.parametrize("printed_token", ["Q2-26E", "H1-26F", "FY26E", "Q2 2026", "Q2-26x"])
def test_prints_period_rejects_a_token_with_more_characters_after_the_year(
    printed_token: str,
) -> None:
    """A forecast suffix ("Q2-26E") or a 4-digit year ("Q2 2026") is not the
    two-digit token, so it gives no window.
    """
    assert not prints_period(f"Growth {printed_token} metrics", date(2026, 4, 1), date(2026, 6, 30))


def test_prints_period_rejects_a_fiscal_window_of_the_wrong_length() -> None:
    """``H1 FY26`` is six months for every year-end month, never three."""
    assert not prints_period("H1 FY26", date(2025, 4, 1), date(2025, 6, 30))


def test_prints_period_accepts_a_stock_value_on_the_last_day_of_the_token_window() -> None:
    day = date(2026, 6, 30)
    assert prints_period("H1-26 ARR", day, day)
