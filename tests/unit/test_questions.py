"""S2-06: a question for management per finding (D6 and D2.11)."""

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from fact_ledger.domain import DivergenceClass, FindingKind, Observation
from fact_ledger.domain.paths import Finding
from fact_ledger.domain.questions import question
from fact_ledger.domain.rules import QUESTION_TEMPLATES
from fact_ledger.domain.validator import validate
from fact_ledger.store.yaml_files import load_dictionary, read_transcript

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]
DICTIONARY = load_dictionary(ROOT / "data" / "dictionary")
NIMBUS = {
    o.observation_id: o
    for o in read_transcript(ROOT / "tests/fixtures/transcripts/synthetic_deck.yaml")
}
FY = {"period_start": date(2024, 1, 1), "period_end": date(2024, 12, 31), "period_type": "fy"}


def _row(base: str, row_id: str, **fields: Any) -> Observation:
    return Observation(**(NIMBUS[base].model_dump() | fields | {"observation_id": row_id}))


def _press(row_id: str, base: str = "nimbus-02", **fields: Any) -> Observation:
    fields = {
        "origin_id": "techdaily",
        "document_id": "techdaily-2025-02",
        "source_type": "press",
        "reliability": 2,
        "stated_precision": Decimal(50000),
        **fields,
    }
    return _row(base, row_id, **fields)


def _findings(*extra: Observation, **changes: dict[str, Any]) -> list[Finding]:
    """Findings of nimbus plus ``extra`` rows. An empty change map removes the row."""
    rows = dict(NIMBUS)
    for row_id, update in changes.items():
        if update:
            rows[row_id] = _row(row_id, row_id, **update)
        else:
            del rows[row_id]
    rows |= {o.observation_id: o for o in extra}
    return list(validate(rows.values(), DICTIONARY).findings)


def _revenue(row_id: str, year: int, value: str, precision: str) -> Observation:
    return _row(
        "nimbus-12",
        row_id,
        value=Decimal(value),
        stated_precision=Decimal(precision),
        period_start=date(year, 1, 1),
        period_end=date(year, 12, 31),
        as_of_date=date(year, 12, 31),
    )


def _ask(finding: Finding) -> str:
    return question(finding, DICTIONARY)


# ---------------------------------------------------------------- golden texts


def test_d6_4_inconsistent_arr() -> None:
    assert _ask(_findings()[0]) == (
        "Annual recurring revenue at 2024-12-31 is EUR 7,450,000 on p14 appendix table "
        '("Annual recurring revenue (exit)") and EUR 8,064,000 on p4 chart ("Annual recurring '
        'revenue (exit)"). These values also differ from p14 appendix table: EUR 8,000,000 on '
        'p1 ("ARR"); EUR 8,064,000 computed as arr = mrr * 12 from mrr EUR 672,000 on p7 '
        "chart. Which value is correct, and what explains the difference of EUR 614,000?"
    )


def test_d6_5_ambiguity() -> None:
    assert _ask(_findings()[1]) == (
        '"Revenue" for the fiscal year 2024-01-01 to 2024-12-31 is EUR 7,100,000 on p2 '
        "executive summary. It differs from each candidate metric: Recognised revenue "
        '(IFRS/K3) EUR 6,930,000 on p8 P&L table ("Total revenue"); Annual recurring revenue '
        'at 2024-12-31 EUR 8,064,000 on p4 chart ("Annual recurring revenue (exit)"). Which '
        'metric does "Revenue" mean, and how is it defined?'
    )


def test_d6_5a_label_conflict() -> None:
    findings = _findings(
        _revenue("nimbus-12", 2024, "8064000", "500"),
        _revenue("nimbus-21", 2023, "4650000", "5000"),
        _revenue("nimbus-22", 2022, "3300000", "50000"),
    )
    assert _ask(findings[1]) == (
        'The values of "Revenue" in nimbus-deck-2025 match more than one metric: for the '
        "fiscal year 2023-01-01 to 2023-12-31 EUR 4,650,000 on p2 executive summary matches "
        "Recognised revenue (IFRS/K3) EUR 4,650,000 on p8 P&L table; for the fiscal year "
        "2024-01-01 to 2024-12-31 EUR 8,064,000 on p2 executive summary matches Annual "
        'recurring revenue at 2024-12-31 EUR 8,064,000 on p4 chart. Does "Revenue" have one '
        "definition in this document? If not, which definition applies to each period?"
    )


def test_d2_13_d_inherited_reading_against_a_press_value() -> None:
    net_sales = _press(
        "nimbus-23",
        base="nimbus-10",
        value=Decimal(4100000),
        period_start=date(2022, 1, 1),
        period_end=date(2022, 12, 31),
        as_of_date=date(2022, 12, 31),
        locator="para 5",
        stated_label="net sales",
    )
    findings = _findings(
        _revenue("nimbus-12", 2024, "6950000", "50000"),
        _revenue("nimbus-21", 2023, "4650000", "5000"),
        _revenue("nimbus-22", 2022, "3300000", "50000"),
        net_sales,
    )
    assert _ask(findings[1]) == (
        "Recognised revenue (IFRS/K3) for the fiscal year 2022-01-01 to 2022-12-31 is "
        'EUR 4,100,000 on techdaily-2025-02 para 5 ("net sales") and EUR 3,300,000 on '
        'nimbus-deck-2025 p2 executive summary ("Revenue", read as Recognised revenue '
        '(IFRS/K3): "Revenue" for the fiscal year 2024-01-01 to 2024-12-31 on nimbus-deck-2025 '
        "p2 executive summary matches EUR 6,930,000 on nimbus-deck-2025 p8 P&L table). Do "
        '"net sales" and "Revenue" use the same definition? If not, what does each one include?'
    )


def _ebitda(row_id: str, value: int, basis: str, precision: int = 50000) -> Observation:
    return _row(
        "nimbus-02",
        row_id,
        **FY,
        metric_id="ebitda_adjusted",
        value=Decimal(value),
        stated_precision=Decimal(precision),
        as_of_date=date(2024, 12, 31),
        locator="p7",
        stated_label="Adjusted EBITDA",
        basis=basis,
    )


def _basis_gaps(*rows: Observation) -> list[Finding]:
    findings = validate(rows, DICTIONARY).findings
    return [f for f in findings if f.kind is FindingKind.BASIS_GAP]


# ---------------------------------------------------------------- every template


def test_a_basis_gap_question_names_both_values_and_asks_what_explains_the_gap() -> None:
    (finding,) = _basis_gaps(
        _ebitda("pro-forma", 36000000, "pro_forma"), _ebitda("reported", 33000000, "reported")
    )
    assert _ask(finding) == (
        "The reported Adjusted EBITDA (company definition) for the fiscal year 2024-01-01 to "
        '2024-12-31 is EUR 33,000,000 on p7 ("Adjusted EBITDA"). The pro forma value is '
        'EUR 36,000,000 on p7 ("Adjusted EBITDA"). What change of scope or exchange rates '
        "explains the difference of EUR 3,000,000?"
    )


def test_a_basis_gap_question_names_each_further_basis_and_the_gap_to_the_first() -> None:
    (finding,) = _basis_gaps(
        _ebitda("reported", 33000000, "reported"),
        _ebitda("pro-forma", 36000000, "pro_forma"),
        _ebitda("constant", 31000000, "constant_currency", precision=10000),
    )
    assert _ask(finding) == (
        "The reported Adjusted EBITDA (company definition) for the fiscal year 2024-01-01 to "
        '2024-12-31 is EUR 33,000,000 on p7 ("Adjusted EBITDA"). The constant currency value '
        'is EUR 31,000,000 on p7 ("Adjusted EBITDA"). The pro forma value is EUR 36,000,000 '
        'on p7 ("Adjusted EBITDA"). What change of scope or exchange rates explains the '
        "difference of EUR 2,000,000?"
    )


def test_a_contested_question_names_both_sources() -> None:
    press = _press("press-arr", value=Decimal(9500000), locator="para 3", stated_label="ARR")
    (finding,) = _findings(press, **{"nimbus-02": {"stated_label": "ARR"}, "nimbus-04": {}})[:1]
    assert finding.divergence is DivergenceClass.CONTESTED
    text = _ask(finding)
    assert text.startswith("Annual recurring revenue at 2024-12-31 is EUR 9,500,000 on ")
    assert "techdaily-2025-02 para 3" in text
    assert "The two values come from different sources." in text


def test_an_unresolvable_question_names_the_weak_source() -> None:
    rumour = _press("rumour-arr", value=Decimal(9500000), locator="post 7", reliability=1)
    finding = next(f for f in _findings(rumour) if f.divergence is DivergenceClass.UNRESOLVABLE)
    assert "techdaily-2025-02 post 7 comes from a source with reliability 1" in _ask(finding)


def test_an_inferred_path_states_its_reading_and_asks_about_the_label() -> None:
    same_label = _press(
        "nimbus-23",
        base="nimbus-10",
        value=Decimal(4100000),
        period_start=date(2022, 1, 1),
        period_end=date(2022, 12, 31),
        as_of_date=date(2022, 12, 31),
        locator="para 5",
        stated_label="Revenue",
    )
    finding = _findings(
        _revenue("nimbus-12", 2024, "6950000", "50000"),
        _revenue("nimbus-22", 2022, "3300000", "50000"),
        same_label,
    )[1]
    assert finding.divergence is DivergenceClass.CONTESTED
    assert _ask(finding).endswith(
        ' The question reads "Revenue" as Recognised revenue (IFRS/K3). If this is wrong, '
        'what does "Revenue" mean?'
    )


def test_an_invariant_question_states_the_assumption_and_every_locator() -> None:
    finding = next(
        f for f in _findings(**{"nimbus-10": {"value": Decimal(9000000)}}) if f.kind == "invariant"
    )
    assert _ask(finding) == (
        'Annual recurring revenue at 2024-12-31 is EUR 8,064,000 on p4 chart ("Annual '
        'recurring revenue (exit)"), below Recognised revenue (IFRS/K3) EUR 9,000,000 on p8 '
        'P&L table ("Total revenue"). The rule arr_ge_revenue_recognised (arr >= '
        "revenue_recognised) does not allow this. The check also uses EUR 5,400,000 on p4 chart "
        '("ARR"). This check assumes that revenue_services plus revenue_hardware is below 10% '
        "of revenue_recognised. No value in the fact base tests it. Which value is wrong, or do "
        "the two use a different scope or definition?"
    )


def test_a_bridge_question_states_the_residual_and_its_sign() -> None:
    q4 = {"period_start": date(2024, 10, 1), "period_type": "quarter"}
    flows = [
        _row("nimbus-08", metric_id, metric_id=metric_id, value=Decimal(v), locator="p12", **q4)
        for metric_id, v in (
            ("mrr_new", 76000),
            ("mrr_expansion", 31000),
            ("mrr_reactivation", 0),
            ("mrr_contraction", 4000),
            ("mrr_churned", 5000),
        )
    ]
    finding = next(f for f in _findings(*flows) if f.kind is FindingKind.BRIDGE)
    assert _ask(finding) == (
        "The MRR bridge for the quarter 2024-10-01 to 2024-12-31 does not close. Opening MRR "
        "EUR 598,000 (p7 chart) plus new EUR 76,000 (p12), expansion EUR 31,000 (p12) and "
        "reactivation EUR 0 (p12), minus contraction EUR 4,000 (p12) and churned EUR 5,000 "
        "(p12), gives EUR 696,000. The stated closing MRR is EUR 672,000 (p7 chart). The bridge "
        "overstates the closing MRR by EUR 24,000. Which bridge line or which closing value is "
        "wrong?"
    )


def test_percent_values_print_with_a_percent_sign() -> None:
    changed = _findings(**{"nimbus-14": {"value": Decimal(30)}})
    finding = next(f for f in changed if f.subject == "churn_logo_annual")
    assert "30% on p10" in _ask(finding)
    assert "9.19% computed as" in _ask(finding)


def test_every_finding_kind_and_class_has_a_template() -> None:
    assert set(QUESTION_TEMPLATES) == {
        *(
            (FindingKind.DIVERGENCE, c)
            for c in DivergenceClass
            if c not in {"corroborated", "consistent"}
        ),
        (FindingKind.AMBIGUITY, DivergenceClass.DEFINITIONAL),
        (FindingKind.LABEL_CONFLICT, DivergenceClass.DEFINITIONAL),
        (FindingKind.INVARIANT, None),
        (FindingKind.BRIDGE, None),
        (FindingKind.PROJECTION, None),
        (FindingKind.BASIS_GAP, DivergenceClass.DEFINITIONAL),
    }


# ---------------------------------------------------------------- dedup and determinism


def test_one_disagreement_at_one_pair_of_locators_gives_one_question() -> None:
    twin = _row("nimbus-04", "nimbus-04b")
    arr = [f for f in _findings(twin) if f.subject == "arr"]
    assert len(arr) == 1


def test_the_same_finding_gives_the_same_text_and_never_a_merged_value() -> None:
    first, second = _ask(_findings()[0]), _ask(_findings()[0])
    assert first == second
    assert "7,757,000" not in first  # the average of the two values


def test_a_direct_reading_cites_its_basis_and_the_stated_period() -> None:
    exact = _press("press-arr", value=Decimal(8000000), stated_precision=None, stated_label="ARR")
    changed = _findings(exact, **{"nimbus-12": {"value": Decimal(8100000)}})
    finding = next(f for f in changed if f.right[0].inferred)
    assert (
        'EUR 8,100,000 on nimbus-deck-2025 p2 executive summary ("Revenue", stated for the '
        "fiscal year 2024-01-01 to 2024-12-31, read as Annual recurring revenue: it matches "
        "EUR 8,064,000 on nimbus-deck-2025 p4 chart)"
    ) in _ask(finding)


@pytest.mark.parametrize(
    ("metric_id", "unit", "printed"),
    [
        ("customers_paying", "count", "4,120 on"),
        ("revenue_seasonality_index", "ratio", "4120x on"),
        ("customer_lifetime_months", "months", "4120 months on"),
    ],
)
def test_each_dimension_prints_its_own_unit(metric_id: str, unit: str, printed: str) -> None:
    fields = {"metric_id": metric_id, "unit": unit, "currency": None, "stated_precision": None}
    low = _row("nimbus-02", "low", value=Decimal(100), **fields)
    high = _row("nimbus-02", "high", value=Decimal(4120), locator="p5", **fields)
    finding = next(f for f in _findings(low, high) if f.subject == metric_id)
    assert printed in _ask(finding)
