"""S2-01 and S2-02: tolerance, divergence classes, readings of ambiguous rows."""

import random
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from fact_ledger.domain import (
    DefinitionStatus,
    Dimension,
    DivergenceClass,
    FindingKind,
    Observation,
    Period,
    PeriodType,
    TolerancePolicy,
)
from fact_ledger.domain.paths import (
    ComputationPath,
    Finding,
    Report,
    compare,
    direct_path,
    pair_tolerance,
)
from fact_ledger.domain.questions import question
from fact_ledger.domain.rules import POLICY_BY_DIMENSION, RELATIVE_TOLERANCE
from fact_ledger.domain.validator import validate
from fact_ledger.store.yaml_files import load_dictionary, read_transcript
from tests.factories import valid_observation_fields

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]
DICTIONARY = load_dictionary(ROOT / "data" / "dictionary")
NIMBUS = {
    o.observation_id: o
    for o in read_transcript(ROOT / "tests/fixtures/transcripts/synthetic_deck.yaml")
}
CURRENCY = Dimension.CURRENCY


def _row(observation_id: str, **changes: Any) -> Observation:
    return Observation(
        **{**valid_observation_fields(), "observation_id": observation_id, **changes}
    )


def _path(row: Observation) -> ComputationPath:
    return direct_path(row, DICTIONARY)


def _nimbus(**nimbus_12: Any) -> dict[str, Observation]:
    rows = dict(NIMBUS)
    rows["nimbus-12"] = NIMBUS["nimbus-12"].model_copy(update=nimbus_12)
    return rows


def _revenue(observation_id: str, year: int, value: str, precision: str) -> Observation:
    """A "Revenue" row on p2 of the nimbus deck (D2.13 d)."""
    return NIMBUS["nimbus-12"].model_copy(
        update={
            "observation_id": observation_id,
            "value": Decimal(value),
            "stated_precision": Decimal(precision),
            "period_start": date(year, 1, 1),
            "period_end": date(year, 12, 31),
            "as_of_date": date(year, 12, 31),
        }
    )


def _net_sales_2022(value: str, **changes: Any) -> Observation:
    """nimbus-23 of D2.13 (d): a press row for recognised revenue FY2022."""
    return NIMBUS["nimbus-10"].model_copy(
        update={
            "observation_id": "nimbus-23",
            "value": Decimal(value),
            "stated_precision": Decimal(50000),
            "period_start": date(2022, 1, 1),
            "period_end": date(2022, 12, 31),
            "as_of_date": date(2022, 12, 31),
            "origin_id": "techdaily",
            "document_id": "techdaily-2025-02",
            "source_type": "press",
            "reliability": 2,
            "locator": "para 5",
            "stated_label": "net sales",
            **changes,
        }
    )


def _example_d(**nimbus_12: Any) -> dict[str, Observation]:
    rows = _nimbus(**({"value": Decimal(6950000)} | nimbus_12))
    rows["nimbus-21"] = _revenue("nimbus-21", 2023, "4650000", "5000")
    rows["nimbus-22"] = _revenue("nimbus-22", 2022, "3300000", "50000")
    return rows


def _run(rows: dict[str, Observation]) -> Report:
    return validate(rows.values(), DICTIONARY)


def _reading(report: Report, observation_id: str) -> tuple[bool, str | None, list[str], str]:
    (reading,) = (r for r in report.readings if r.observation.observation_id == observation_id)
    basis = [o.observation_id for o in reading.basis]
    basis += [s.observation.observation_id for s in reading.sources]
    return reading.inferred, reading.metric_id, basis, reading.reason


def _ids(report: Report) -> list[tuple[str, str, list[str]]]:
    return [(f.kind, f.left.key[1][0], [p.key[1][0] for p in f.right]) for f in report.findings]


def _comparison(report: Report, a: str, b: str) -> tuple[DivergenceClass | None, str]:
    (found,) = (
        c
        for c in report.comparisons
        if {c.a.observations[0].observation_id, c.b.observations[0].observation_id} == {a, b}
    )
    return found.divergence, found.reason


# ---------------------------------------------------------------- S2-01


def test_stated_precisions_absorb_a_rounded_headline_figure() -> None:
    result = compare(_path(NIMBUS["nimbus-03"]), _path(NIMBUS["nimbus-02"]), CURRENCY)
    assert result.tolerance == Decimal(500500)
    assert result.divergence is DivergenceClass.CONSISTENT


def test_without_precision_the_relative_tolerance_applies() -> None:
    low = _row("a", value=Decimal(100), stated_precision=None)
    high = _row("b", value=Decimal(140), stated_precision=None)
    result = compare(_path(low), _path(high), CURRENCY)
    assert result.tolerance == Decimal("1.40")
    assert result.divergence is DivergenceClass.INCONSISTENT


def test_percent_policy_is_tighter_than_currency_policy() -> None:
    assert (
        RELATIVE_TOLERANCE[TolerancePolicy.PERCENT_DEFAULT]
        < RELATIVE_TOLERANCE[TolerancePolicy.CURRENCY_DEFAULT]
    )
    fields = {"metric_id": "nrr", "unit": "percent", "currency": None, "stated_precision": None}
    a, b = (
        _path(_row("a", value=Decimal(100), **fields)),
        _path(_row("b", value=Decimal("100.6"), **fields)),
    )
    assert compare(a, b, Dimension.PERCENT).divergence is DivergenceClass.INCONSISTENT
    assert compare(a, b, CURRENCY).divergence is DivergenceClass.CONSISTENT


def test_every_dimension_has_a_policy_with_a_value() -> None:
    assert set(POLICY_BY_DIMENSION) == set(Dimension)
    assert set(POLICY_BY_DIMENSION.values()) <= set(RELATIVE_TOLERANCE)


def test_the_inequality_margin_uses_the_policy_of_the_terms_dimension() -> None:
    """D1.2: nrr 91.0 against grr 91.05 is rounding, not a violation of nrr >= grr."""
    unrounded = {"stated_precision": None}
    nrr = _path(NIMBUS["nimbus-19"].model_copy(update={"value": Decimal("91.0"), **unrounded}))
    grr = _path(NIMBUS["nimbus-20"].model_copy(update={"value": Decimal("91.05"), **unrounded}))
    margin = pair_tolerance(nrr, grr, Dimension.PERCENT)
    assert margin == RELATIVE_TOLERANCE[TolerancePolicy.PERCENT_DEFAULT] * Decimal("91.05")
    assert nrr.value >= grr.value - margin


def test_fy_and_q4_with_one_period_end_are_not_aligned() -> None:
    result = compare(_path(NIMBUS["nimbus-10"]), _path(NIMBUS["nimbus-11"]), CURRENCY)
    assert (result.tolerance, result.divergence, result.reason) == (
        None,
        None,
        "period not aligned",
    )


def test_two_currencies_are_not_comparable() -> None:
    usd = _row("b", value=Decimal(9000000), unit="USD", currency="USD")
    result = compare(_path(_row("a")), _path(usd), CURRENCY)
    assert (result.tolerance, result.divergence, result.reason) == (None, None, "currency differs")


def test_two_units_are_not_comparable() -> None:
    fields = {"currency": None, "stated_precision": None}
    a, b = _row("a", unit="count", **fields), _row("b", unit="percent", **fields)
    assert compare(_path(a), _path(b), CURRENCY).reason == "unit differs"


def test_an_unresolved_margin_unspecified_currency_row_keeps_currency_tolerance() -> None:
    """``margin_unspecified`` is declared ``percent``, but a deck can print it as
    a currency gross-profit amount (data/dictionary/metrics.yaml). A row that stays ambiguous
    keeps its own unit for tolerance, so a 0.7% gap stays within the 1% currency tolerance
    instead of failing the tighter 0.5% percent tolerance.
    """
    fields = {
        "metric_id": "margin_unspecified",
        "definition_status": DefinitionStatus.AMBIGUOUS,
        "candidate_metric_ids": ("gross_profit",),
        "stated_precision": None,
    }
    a = _row("a", value=Decimal(100000000), **fields)
    b = _row(
        "b",
        value=Decimal(100700000),
        origin_id="techdaily",
        document_id="techdaily-2025-02",
        **fields,
    )
    report = validate([a, b], DICTIONARY)
    assert _comparison(report, "a", "b") == (DivergenceClass.CORROBORATED, "")


# ---------------------------------------------------------------- S2-02, direct pairs


def test_nimbus_gives_one_inconsistent_arr_finding_and_one_ambiguity() -> None:
    report = _run(NIMBUS)
    assert _ids(report) == [
        (FindingKind.DIVERGENCE, "nimbus-04", ["nimbus-02", "nimbus-03", "nimbus-08"]),
        (FindingKind.AMBIGUITY, "nimbus-12", ["nimbus-10", "nimbus-02"]),
    ]
    assert report.findings[0].divergence is DivergenceClass.INCONSISTENT
    assert _comparison(report, "nimbus-02", "nimbus-03")[0] is DivergenceClass.CONSISTENT


def test_a_finding_cites_both_values_never_a_merged_one() -> None:
    finding = _run(NIMBUS).findings[0]
    values = {finding.left.value, *(p.value for p in finding.right)}
    assert values == {Decimal(7450000), Decimal(8064000), Decimal(8000000)}
    assert [finding.left.observations[0].locator, finding.right[0].observations[0].locator] == [
        "p14 appendix table",
        "p4 chart",
    ]


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"stated_label": "Subscription ARR"}, DivergenceClass.DEFINITIONAL),
        ({"origin_id": "techdaily"}, DivergenceClass.CONTESTED),
        ({"origin_id": "techdaily", "reliability": 1}, DivergenceClass.UNRESOLVABLE),
    ],
)
def test_outside_tolerance_classes(changes: dict[str, Any], expected: DivergenceClass) -> None:
    other = _row("b", value=Decimal(9500000), stated_precision=Decimal(500), **changes)
    report = validate([_row("a", stated_precision=Decimal(500)), other], DICTIONARY)
    assert report.comparisons[0].divergence is expected
    assert len(report.findings) == 1


def test_two_origins_within_tolerance_corroborate_with_no_finding() -> None:
    report = validate([_row("a"), _row("b", origin_id="techdaily")], DICTIONARY)
    assert report.comparisons[0].divergence is DivergenceClass.CORROBORATED
    assert report.findings == ()


def test_three_observations_give_three_pairs() -> None:
    rows = [
        _row(i, value=Decimal(v), stated_precision=None) for i, v in (("a", 1), ("b", 2), ("c", 3))
    ]
    assert len(validate(rows, DICTIONARY).comparisons) == 3


def test_one_observation_gives_no_comparison_and_no_finding() -> None:
    report = validate([_row("a")], DICTIONARY)
    assert (report.comparisons, report.findings) == ((), ())


def test_a_row_with_an_undefined_metric_is_not_validated() -> None:
    report = validate([_row("a"), _row("b", metric_id="arr_weird", value=Decimal(1))], DICTIONARY)
    assert (report.comparisons, report.findings) == ((), ())


# ---------------------------------------------------------------- S3-12, qualifiers


def test_three_region_rows_of_one_metric_and_period_are_never_compared() -> None:
    """S3-12, criterion 1. A group row and two region rows of one metric, for one
    period: each keeps its own region, and the validator compares none of the three with
    another.
    """
    group = _row("grp-arr", metric_id="arr", value=Decimal(1000000))
    emea = _row("emea-arr", metric_id="arr", value=Decimal(400000), region="EMEA")
    americas = _row("americas-arr", metric_id="arr", value=Decimal(600000), region="Americas")

    report = validate([group, emea, americas], DICTIONARY)

    assert report.comparisons == ()
    assert report.findings == ()


def test_two_bases_of_one_metric_and_period_are_never_compared() -> None:
    """S3-12, criterion 2, and S4-04. A reported row and a pro forma row of one
    metric, for one period: both carry their basis, and the validator compares neither with
    the other. The gap between them is one basis-gap finding, with the reported row as the
    reference.
    """
    reported = _row("reported-ebitda", metric_id="ebitda_adjusted", value=Decimal(33000000))
    pro_forma = _row(
        "pro-forma-ebitda", metric_id="ebitda_adjusted", value=Decimal(36000000), basis="pro_forma"
    )

    report = validate([reported, pro_forma], DICTIONARY)

    assert report.comparisons == ()
    (finding,) = report.findings
    assert (finding.kind, finding.divergence) == (
        FindingKind.BASIS_GAP,
        DivergenceClass.DEFINITIONAL,
    )
    assert finding.left.observations == (reported,)


# ---------------------------------------------------------------- S4-04, the basis gap


_YEAR_BEFORE = {"period_start": date(2023, 12, 31), "period_end": date(2023, 12, 31)}


def _ebitda(observation_id: str, value: int, **changes: Any) -> Observation:
    fields = {"metric_id": "ebitda_adjusted", "stated_precision": Decimal(50000)} | changes
    return _row(observation_id, value=Decimal(value), **fields)


def _gaps(*rows: Observation) -> list[Finding]:
    return [f for f in validate(rows, DICTIONARY).findings if f.kind is FindingKind.BASIS_GAP]


def test_a_gap_inside_the_tolerance_is_no_finding_and_no_corroboration() -> None:
    """S4-04, criterion 2. The tolerance is the larger of 100,000 and 1% of 33,200,000."""
    report = validate(
        [_ebitda("reported", 33000000), _ebitda("pro-forma", 33200000, basis="pro_forma")],
        DICTIONARY,
    )

    assert report.findings == ()
    assert report.comparisons == ()


def test_a_gap_just_outside_the_tolerance_is_a_finding() -> None:
    assert _gaps(_ebitda("reported", 33000000), _ebitda("pro-forma", 33400000, basis="pro_forma"))


@pytest.mark.parametrize("changes", [{"currency": "USD"}, {"unit": "count"}])
def test_a_row_in_another_unit_or_currency_is_never_a_gap(changes: dict[str, Any]) -> None:
    other = _ebitda("pro-forma", 36000000, basis="pro_forma", **changes)

    assert _gaps(_ebitda("reported", 33000000), other) == []


@pytest.mark.parametrize("basis", ["pro_forma", "constant_currency"])
def test_a_gap_with_no_reported_row_is_no_finding(basis: str) -> None:
    assert _gaps(_ebitda("other", 36000000, basis=basis)) == []
    reported_earlier = _ebitda("reported", 30000000, **_YEAR_BEFORE)

    assert _gaps(_ebitda("other", 36000000, basis=basis), reported_earlier) == []


def test_a_projected_pro_forma_plan_row_is_never_a_gap() -> None:
    """S4-02. ``validate`` drops a plan at its entry, so the basis-gap
    step never sees it. No second filter belongs inside ``_basis_gaps``.
    """
    reported = _ebitda("reported", 33000000)
    plan = _ebitda("pro-forma-plan", 36000000, basis="pro_forma", published_date=date(2024, 6, 1))

    assert _gaps(reported, plan) == []


def test_a_computed_path_on_the_other_basis_is_never_a_gap() -> None:
    """The pro forma mrr of 700,000 computes an arr of 8,400,000 on the pro forma basis. That
    path restates its input (S4-04 Domain rules). The stored pro forma arr is inside the
    tolerance of the reported arr, so the gap has no right-hand path.
    """
    reported = _row(
        "reported-arr", metric_id="arr", value=Decimal(8000000), stated_precision=Decimal(50000)
    )
    pro_forma = {"basis": "pro_forma", "stated_precision": Decimal(50000)}
    stored = _row("pf-arr", metric_id="arr", value=Decimal(8000000), **pro_forma)
    mrr = _row("pf-mrr", metric_id="mrr", value=Decimal(700000), **pro_forma)

    report = validate([reported, stored, mrr], DICTIONARY)

    assert any(p.identity_id for c in report.comparisons for p in (c.a, c.b))
    assert [f for f in report.findings if f.kind is FindingKind.BASIS_GAP] == []


def _unspecified(observation_id: str, value: int) -> Observation:
    return _row(
        observation_id,
        metric_id="revenue_unspecified",
        value=Decimal(value),
        stated_precision=Decimal(50000),
        basis="pro_forma",
        definition_status="ambiguous",
        candidate_metric_ids=("revenue_recognised", "arr"),
    )


def _revenue_row(observation_id: str, value: int, **changes: Any) -> Observation:
    return _ebitda(observation_id, value, metric_id="revenue_recognised", **changes)


def test_an_inferred_row_on_the_other_basis_never_joins_the_finding() -> None:
    """An ambiguous pro forma row that matches the pro forma value is read as revenue_recognised.
    The reading is inferred, so the finding cites the resolved pro forma row only.
    """
    pro_forma = _revenue_row("pro-forma", 36000000, basis="pro_forma")
    rows = [_revenue_row("reported", 33000000), pro_forma, _unspecified("pf-unspecified", 36000000)]

    report = validate(rows, DICTIONARY)

    assert [r.inferred for r in report.readings] == [True]
    (finding,) = (f for f in report.findings if f.kind is FindingKind.BASIS_GAP)
    assert [p.observations for p in finding.right] == [(pro_forma,)]


def test_two_other_bases_give_one_finding_with_the_right_paths_in_rank_order() -> None:
    reported = _ebitda("reported", 33000000)
    pro_forma = _ebitda("pro-forma", 36000000, basis="pro_forma")
    constant = _ebitda(
        "constant", 31000000, basis="constant_currency", stated_precision=Decimal(10000)
    )

    (finding,) = _gaps(reported, pro_forma, constant)

    assert finding.left.observations == (reported,)
    assert [p.observations for p in finding.right] == [(constant,), (pro_forma,)]


def test_a_basis_inside_the_tolerance_stays_out_of_a_finding_of_another_basis() -> None:
    near = _ebitda("constant", 33100000, basis="constant_currency")
    far = _ebitda("pro-forma", 36000000, basis="pro_forma")

    (finding,) = _gaps(_ebitda("reported", 33000000), near, far)

    assert [p.observations[0].observation_id for p in finding.right] == ["pro-forma"]


def test_the_reference_is_the_best_ranked_reported_row() -> None:
    coarse = _ebitda("coarse", 33000000)
    exact = _ebitda("exact", 33000000, stated_precision=Decimal(10000), origin_id="auditor")

    (finding,) = _gaps(coarse, exact, _ebitda("pro-forma", 36000000, basis="pro_forma"))

    assert finding.left.observations == (exact,)


def test_each_currency_group_gets_its_own_reference() -> None:
    """A reported USD row ranked ahead of a reported EUR row must not
    hide the EUR gap: each (unit, currency) group gets its own reference.
    """
    reported_usd = _ebitda(
        "reported-usd", 40000000, currency="USD", unit="USD", stated_precision=Decimal(10000)
    )
    reported_eur = _ebitda("reported-eur", 33000000)
    pro_forma_eur = _ebitda("pro-forma-eur", 36000000, basis="pro_forma")

    (finding,) = _gaps(reported_usd, reported_eur, pro_forma_eur)

    assert finding.left.observations == (reported_eur,)
    assert [p.observations for p in finding.right] == [(pro_forma_eur,)]


def test_each_period_with_a_gap_is_one_finding() -> None:
    rows = [
        _ebitda("reported", 33000000),
        _ebitda("pro-forma", 36000000, basis="pro_forma"),
        _ebitda("reported-before", 28000000, **_YEAR_BEFORE),
        _ebitda("pro-forma-before", 30000000, basis="pro_forma", **_YEAR_BEFORE),
    ]

    assert [f.period.end for f in _gaps(*rows)] == [date(2023, 12, 31), date(2024, 12, 31)]


@pytest.mark.parametrize("axis", ["segment", "region"])
def test_a_gap_is_read_inside_one_segment_or_region(axis: str) -> None:
    group = _ebitda("reported-group", 33000000)
    pro_forma_group = _ebitda("pro-forma-group", 33000000, basis="pro_forma")
    reported_emea = _ebitda("reported-emea", 10000000, **{axis: "EMEA"})
    pro_forma_emea = _ebitda("pro-forma-emea", 14000000, basis="pro_forma", **{axis: "emea"})

    (finding,) = _gaps(group, pro_forma_group, reported_emea, pro_forma_emea)

    assert finding.left.observations == (reported_emea,)
    assert [p.observations for p in finding.right] == [(pro_forma_emea,)]


@pytest.mark.parametrize(
    ("reported", "pro_forma"),
    [
        ({}, {"segment": "EMEA"}),
        ({"region": "EMEA"}, {}),
        ({"segment": "EMEA"}, {"region": "EMEA"}),
    ],
)
def test_two_bases_in_two_qualifier_groups_are_never_a_gap(
    reported: dict[str, str], pro_forma: dict[str, str]
) -> None:
    rows = [
        _ebitda("reported", 33000000, **reported),
        _ebitda("pro-forma", 36000000, basis="pro_forma", **pro_forma),
    ]

    assert _gaps(*rows) == []


def test_an_ambiguous_group_row_never_takes_its_reading_from_a_segment_row() -> None:
    """S3-12, criterion 5 (D2.6, D2.7). A stored resolved row matches a segment row
    that carries the same ambiguous label as a group row, for one period. The group row takes
    no reading from the segment row or from its match. It stays ambiguous.
    """
    resolved_segment = _row(
        "resolved-emea",
        metric_id="revenue_recognised",
        value=Decimal(1000000),
        stated_precision=Decimal(500),
        region="EMEA",
    )
    ambiguous_segment = _row(
        "ambiguous-emea",
        metric_id="revenue_unspecified",
        value=Decimal(1000000),
        stated_precision=Decimal(500),
        region="EMEA",
        definition_status="ambiguous",
        candidate_metric_ids=("revenue_recognised", "arr"),
    )
    ambiguous_group = _row(
        "ambiguous-group",
        metric_id="revenue_unspecified",
        value=Decimal(5000000),
        stated_precision=Decimal(500),
        definition_status="ambiguous",
        candidate_metric_ids=("revenue_recognised", "arr"),
    )

    report = validate([resolved_segment, ambiguous_segment, ambiguous_group], DICTIONARY)

    (group_reading,) = (
        r for r in report.readings if r.observation.observation_id == "ambiguous-group"
    )
    assert group_reading.inferred is False
    assert group_reading.metric_id is None


# ---------------------------------------------------------------- S2-02, ambiguous rows (D2.13)


def test_example_a_nimbus_12_as_is_stays_ambiguous() -> None:
    report = _run(NIMBUS)
    assert _reading(report, "nimbus-12") == (False, None, [], "no match")
    compared = {
        o.observation_id for c in report.comparisons for o in (*c.a.observations, *c.b.observations)
    }
    assert "nimbus-12" not in compared


def test_a_candidate_metric_outside_the_dictionary_is_ignored() -> None:
    candidates = ("revenue_recognised", "arr", "revenue_weird")
    report = _run(_nimbus(candidate_metric_ids=candidates))
    assert _reading(report, "nimbus-12") == (False, None, [], "no match")


def test_example_b_a_unique_match_is_inferred_and_not_compared_with_its_basis() -> None:
    report = _run(_nimbus(value=Decimal(6950000)))
    assert _reading(report, "nimbus-12") == (True, "revenue_recognised", ["nimbus-10"], "")
    assert _comparison(report, "nimbus-12", "nimbus-10") == (None, "basis of the reading")
    assert _ids(report) == [
        (FindingKind.DIVERGENCE, "nimbus-04", ["nimbus-02", "nimbus-03", "nimbus-08"])
    ]


def test_an_inferred_row_does_not_change_the_stored_row() -> None:
    stored = _nimbus(value=Decimal(6950000))["nimbus-12"]
    (reading,) = _run(_nimbus(value=Decimal(6950000))).readings
    assert reading.observation == stored
    assert (stored.metric_id, stored.definition_status) == ("revenue_unspecified", "ambiguous")


def test_example_c_two_matching_metrics_stay_ambiguous_with_no_finding() -> None:
    report = _run(_nimbus(value=Decimal(7000000), stated_precision=Decimal(500000)))
    assert _reading(report, "nimbus-12") == (False, None, [], "several")
    assert len(report.findings) == 1


def test_example_d_inherits_inside_one_document_only() -> None:
    rows = _example_d()
    rows["nimbus-24"] = _revenue("nimbus-24", 2021, "2000000", "50000").model_copy(
        update={"document_id": "nimbus-deck-2024"}
    )
    report = _run(rows)
    assert _reading(report, "nimbus-21") == (True, "revenue_recognised", ["nimbus-09"], "")
    assert _reading(report, "nimbus-22") == (
        True,
        "revenue_recognised",
        ["nimbus-12", "nimbus-21"],
        "",
    )
    assert _reading(report, "nimbus-24") == (False, None, [], "no candidate")
    assert len(report.findings) == 1


def test_example_d_an_inherited_row_meets_a_press_value_as_its_metric() -> None:
    rows = _example_d()
    rows["nimbus-23"] = _net_sales_2022("4100000")
    report = _run(rows)
    assert _reading(report, "nimbus-22")[0] is True
    assert _ids(report)[1] == (FindingKind.DIVERGENCE, "nimbus-23", ["nimbus-22"])
    assert report.findings[1].divergence is DivergenceClass.DEFINITIONAL


def test_an_inferred_row_that_agrees_with_another_origin_is_never_corroborated() -> None:
    rows = _example_d()
    rows["nimbus-23"] = _net_sales_2022("3310000", origin_id="rumour-mill", reliability=1)
    assert _comparison(_run(rows), "nimbus-22", "nimbus-23") == (DivergenceClass.CONSISTENT, "")


def test_example_e_one_label_two_metrics_is_a_label_conflict() -> None:
    report = _run(_example_d(value=Decimal(8064000), stated_precision=Decimal(500)))
    assert [r.inferred for r in report.readings] == [False, False, False]
    assert _reading(report, "nimbus-12") == (
        False,
        "arr",
        ["nimbus-02", "nimbus-03"],
        "label conflict",
    )
    assert _ids(report) == [
        (FindingKind.DIVERGENCE, "nimbus-04", ["nimbus-02", "nimbus-03", "nimbus-08"]),
        (FindingKind.LABEL_CONFLICT, "nimbus-12", ["nimbus-21"]),
    ]


def test_an_inferred_row_does_not_restate_a_gap_of_its_basis() -> None:
    report = _run(_nimbus(value=Decimal(8064000), stated_precision=Decimal(500)))
    assert _reading(report, "nimbus-12")[:2] == (True, "arr")
    assert _comparison(report, "nimbus-12", "nimbus-04") == (None, "basis differs from this value")
    assert len(report.findings) == 1


@pytest.mark.parametrize("nimbus_12", [Decimal(6950000), Decimal(8064000)])
def test_the_report_does_not_depend_on_row_order(nimbus_12: Decimal) -> None:
    rows = list(_example_d(value=nimbus_12, stated_precision=Decimal(500)).values())
    rows.append(_net_sales_2022("4100000"))
    expected = validate(rows, DICTIONARY)
    shuffler = random.Random(20260924)  # noqa: S311
    for _ in range(5):
        shuffler.shuffle(rows)
        assert validate(rows, DICTIONARY) == expected


def test_a_point_in_time_stock_reading_uses_the_period_end() -> None:
    report = _run(_nimbus(value=Decimal(8064000), stated_precision=Decimal(500)))
    inferred = {
        (p.metric_id, p.period) for c in report.comparisons for p in (c.a, c.b) if p.inferred
    }
    end = date(2024, 12, 31)
    assert inferred == {("arr", Period(end, end, PeriodType.POINT_IN_TIME))}


# ---------------------------------------------------------------- S3-25, stock candidate (D2.6)

EIGHT_CANDIDATES = (
    "revenue_recognised",
    "arr",
    "arr_run_rate",
    "billings",
    "revenue_subscription",
    "revenue_gross",
    "revenue_usage",
    "mrr",
)


def _bare_revenue(
    value: int, start: date, end: date, period_type: PeriodType
) -> dict[str, Observation]:
    """A synthetic ambiguous "Revenue" row with the eight candidates."""
    row = _row(
        "rev",
        metric_id="revenue_unspecified",
        value=Decimal(value),
        stated_precision=Decimal(500),
        period_start=start,
        period_end=end,
        period_type=period_type,
        as_of_date=end,
        published_date=date(2026, 1, 31),  # after the period end, so no row is a projection
        stated_label="Revenue",
        definition_status=DefinitionStatus.AMBIGUOUS,
        candidate_metric_ids=EIGHT_CANDIDATES,
    )
    return {"rev": row}


def _with_resolved(
    rows: dict[str, Observation], observation_id: str, metric_id: str, value: int
) -> dict[str, Observation]:
    """Add a resolved row at the period of the "rev" row (a stock row at its period end)."""
    rev = rows["rev"]
    if metric_id.startswith("arr"):
        period = {"period_start": rev.period_end, "period_type": PeriodType.POINT_IN_TIME}
    else:
        period = {"period_start": rev.period_start, "period_type": rev.period_type}
    row = _row(
        observation_id,
        metric_id=metric_id,
        value=Decimal(value),
        stated_precision=Decimal(500),
        period_end=rev.period_end,
        as_of_date=rev.period_end,
        published_date=rev.published_date,
        **period,
    )
    return {**rows, observation_id: row}


@pytest.mark.parametrize(
    ("start", "end", "period_type", "value"),
    [
        (date(2025, 7, 1), date(2025, 9, 30), PeriodType.QUARTER, 25_000_000),
        (date(2025, 1, 1), date(2025, 9, 30), PeriodType.YTD, 75_000_000),
        (date(2025, 1, 1), date(2025, 6, 30), PeriodType.HALF, 50_000_000),
        (date(2025, 9, 1), date(2025, 9, 30), PeriodType.MONTH, 8_000_000),
    ],
)
def test_a_bare_revenue_row_of_a_flow_period_never_meets_an_arr(
    start: date, end: date, period_type: PeriodType, value: int
) -> None:
    """S3-25 criterion 1. A quarter of revenue against a year-end stock is no ambiguity."""
    rows = _with_resolved(_bare_revenue(value, start, end, period_type), "arr", "arr", 100_000_000)
    report = _run(rows)
    assert _reading(report, "rev") == (False, None, [], "no candidate")
    assert report.findings == ()


def test_a_bare_revenue_row_of_a_flow_period_never_meets_an_arr_run_rate() -> None:
    rows = _bare_revenue(25_000_000, date(2025, 7, 1), date(2025, 9, 30), PeriodType.QUARTER)
    rows = _with_resolved(rows, "run", "arr_run_rate", 100_000_000)
    report = _run(rows)
    assert _reading(report, "rev") == (False, None, [], "no candidate")
    assert report.findings == ()


def test_a_bare_fy_revenue_row_still_meets_an_arr_in_one_ambiguity_finding() -> None:
    """S3-25 criterion 2 (regression, D2.13). A year of revenue can equal a year-end ARR."""
    rows = _bare_revenue(100_000_000, date(2024, 1, 1), date(2024, 12, 31), PeriodType.FY)
    rows = _with_resolved(rows, "arr", "arr", 150_000_000)
    report = _run(rows)
    assert _ids(report) == [(FindingKind.AMBIGUITY, "rev", ["arr"])]


def test_a_flow_candidate_at_the_row_period_still_gives_a_finding_without_the_arr() -> None:
    """S3-25 criterion 3. The true ambiguity stays and cites the recognised revenue only."""
    rows = _bare_revenue(25_000_000, date(2025, 7, 1), date(2025, 9, 30), PeriodType.QUARTER)
    rows = _with_resolved(rows, "arr", "arr", 100_000_000)
    rows = _with_resolved(rows, "recognised", "revenue_recognised", 30_000_000)
    report = _run(rows)
    assert _ids(report) == [(FindingKind.AMBIGUITY, "rev", ["recognised"])]


# ---------------------------------------------------------------- S5-01, cited origin


def _press_echo(observation_id: str, **changes: Any) -> Observation:
    """A techdaily row that cites the company as the source of its figure."""
    return _row(
        observation_id,
        origin_id="techdaily",
        cited_origin_id="acme-management",
        document_id="techdaily-2025-02",
        source_type="press",
        reliability=3,
        **changes,
    )


def test_a_press_echo_of_the_deck_within_tolerance_is_consistent_not_corroborated() -> None:
    """S5-01, criterion 1. The article cites the company, so deck and article are
    one origin.
    """
    report = validate([_row("deck"), _press_echo("press")], DICTIONARY)

    assert report.comparisons[0].divergence is DivergenceClass.CONSISTENT
    assert report.findings == ()


def test_a_press_echo_outside_tolerance_is_inconsistent_and_cites_both_documents() -> None:
    """S5-01, criterion 2. The company says two things, not Contested."""
    deck = _row("deck", stated_precision=Decimal(500))
    press = _press_echo("press", value=Decimal(9500000), stated_precision=Decimal(500))

    (finding,) = validate([deck, press], DICTIONARY).findings

    assert finding.divergence is DivergenceClass.INCONSISTENT
    text = question(finding, DICTIONARY)
    assert "deck-2025" in text
    assert "techdaily-2025-02" in text


def test_a_press_echo_that_fills_a_computed_path_stays_one_origin() -> None:
    """The echo is an input of `arr_from_mrr`, so the computed path counts as the company too."""
    deck = _row("deck", stated_precision=Decimal(500))
    press = _press_echo(
        "press-mrr", metric_id="mrr", value=Decimal(672000), stated_precision=Decimal(500)
    )

    (comparison,) = validate([deck, press], DICTIONARY).comparisons
    assert comparison.divergence is DivergenceClass.CONSISTENT

    independent = press.model_copy(update={"cited_origin_id": None})
    (comparison,) = validate([deck, independent], DICTIONARY).comparisons
    assert comparison.divergence is DivergenceClass.CORROBORATED
