"""S2-03 to S2-05: identity checks, invariants and the MRR bridge."""

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, NamedTuple

import pytest

from fact_ledger.domain import (
    CheckStatus,
    DefinitionStatus,
    DivergenceClass,
    FindingKind,
    Identity,
    Observation,
    TolerancePolicy,
)
from fact_ledger.domain.checks import BRIDGE, BRIDGE_ID, EQUALITIES, INEQUALITIES
from fact_ledger.domain.models import Qualifier
from fact_ledger.domain.paths import Report, metric_of
from fact_ledger.domain.rules import POLICY_BY_DIMENSION
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
Q4 = {"period_start": date(2024, 10, 1), "period_end": date(2024, 12, 31), "period_type": "quarter"}


def _run(rows: dict[str, Observation]) -> Report:
    return validate(rows.values(), DICTIONARY)


def _with(**changes: dict[str, Any]) -> dict[str, Observation]:
    """Nimbus with some rows changed. An empty change map removes the row."""
    rows = dict(NIMBUS)
    for observation_id, update in changes.items():
        if update:
            rows[observation_id] = Observation(**(NIMBUS[observation_id].model_dump() | update))
        else:
            del rows[observation_id]
    return rows


def _add(rows: dict[str, Observation], row_id: str, /, **fields: Any) -> None:
    """A nimbus deck row. Fields default to nimbus-08 (mrr at 2024-12-31, p7 chart)."""
    base = NIMBUS["nimbus-08"].model_dump()
    rows[row_id] = Observation(**(base | fields | {"observation_id": row_id}))


def _checks(report: Report, identity_id: str) -> list[tuple[str, CheckStatus, str]]:
    return [
        (str(c.period.end) if c.period else "", c.status, c.reason)
        for c in report.checks
        if c.identity_id == identity_id
    ]


def _bridge(new: str = "52000", **skip: bool) -> dict[str, Observation]:
    """The Q4 2024 bridge of D7.3 on "p12 waterfall". Opening nimbus-07, closing nimbus-08."""
    rows = dict(NIMBUS)
    flows = {
        "mrr_new": new,
        "mrr_expansion": "31000",
        "mrr_reactivation": "0",
        "mrr_contraction": "4000",
        "mrr_churned": "5000",
    }
    for metric_id, value in flows.items():
        if not skip.get(metric_id):
            _add(
                rows,
                f"bridge-{metric_id}",
                metric_id=metric_id,
                value=Decimal(value),
                stated_precision=None if value == "0" else Decimal(500),
                locator="p12 waterfall",
                stated_label="No reactivations" if value == "0" else metric_id,
                **Q4,
            )
    return rows


# ---------------------------------------------------------------- S2-03


def test_identity_table_matches_the_dictionary() -> None:
    evaluated = {*EQUALITIES, *INEQUALITIES, BRIDGE_ID}
    assert evaluated == DICTIONARY.identity_ids
    terms = {i.identity_id: set(i.terms) for i in DICTIONARY.identities}
    for identity_id, rule in EQUALITIES.items():
        assert {rule.target, *(m for m, _ in rule.inputs)} == terms[identity_id]
    for identity_id, inequality in INEQUALITIES.items():
        assert {inequality.lhs, inequality.rhs[0]} == terms[identity_id]
    assert {m for m, _ in BRIDGE.inputs} == terms[BRIDGE_ID]


def test_each_identity_policy_is_the_policy_of_its_target_dimension() -> None:
    """The checks take the tolerance from the dimension (D1.3), so the YAML must agree."""
    for identity in DICTIONARY.identities:
        dimension = metric_of(DICTIONARY, identity.terms[0]).dimension
        expected = (
            TolerancePolicy.INEQUALITY
            if identity.identity_id in INEQUALITIES
            else POLICY_BY_DIMENSION[dimension]
        )
        assert identity.tolerance_policy is expected, identity.identity_id


def test_arr_from_mrr_is_consistent_with_the_stated_arr() -> None:
    report = _run(NIMBUS)
    (computed,) = (
        c
        for c in report.comparisons
        if c.b.identity_id == "arr_from_mrr" and c.a.key[1] == ("nimbus-02",)
    )
    assert (computed.b.value, computed.b.precision) == (Decimal(8064000), Decimal(6000))
    assert computed.divergence == "consistent"
    assert _checks(report, "arr_from_mrr") == [
        ("2023-12-31", CheckStatus.HELD, ""),
        ("2024-12-31", CheckStatus.VIOLATED, ""),
    ]


def test_monthly_churn_compounds_to_the_stated_annual_churn() -> None:
    report = _run(NIMBUS)
    computed = next(c for c in report.comparisons if c.b.metric_id == "churn_logo_annual")
    assert round(computed.b.value, 4) == Decimal("9.1887")
    assert computed.divergence == "consistent"
    assert _checks(report, "churn_logo_annual_from_monthly")[1] == (
        "2024-12-31",
        CheckStatus.HELD,
        "",
    )


def test_the_computed_arr_joins_the_nimbus_04_finding() -> None:
    (finding, _ambiguity) = _run(NIMBUS).findings
    assert finding.left.key == ("", ("nimbus-04",))
    assert [p.key for p in finding.right] == [
        ("", ("nimbus-02",)),
        ("", ("nimbus-03",)),
        ("arr_from_mrr", ("nimbus-08",)),
    ]


def test_net_new_arr_is_not_derived_when_it_is_not_observed() -> None:
    assert _checks(_run(NIMBUS), "net_new_arr_from_arr") == []


def test_net_new_arr_is_checked_when_every_term_is_observed() -> None:
    rows = _with(**{"nimbus-03": {}, "nimbus-04": {}})
    _add(
        rows,
        "nimbus-nna",
        metric_id="net_new_arr",
        value=Decimal(2664000),
        stated_precision=Decimal(500),
        period_start=date(2024, 1, 1),
        period_type="fy",
    )
    assert _checks(_run(rows), "net_new_arr_from_arr") == [("2024-12-31", CheckStatus.HELD, "")]


def test_a_term_in_another_currency_skips_the_check() -> None:
    report = _run(_with(**{"nimbus-08": {"unit": "USD", "currency": "USD"}}))
    assert _checks(report, "arr_from_mrr")[1] == (
        "2024-12-31",
        CheckStatus.NOT_CHECKED,
        "currency differs: EUR and USD",
    )
    computed = [
        c.b.period.end.year for c in report.comparisons if c.b.identity_id == "arr_from_mrr"
    ]
    assert computed == [2023]


def test_a_target_in_another_currency_does_not_hide_the_check() -> None:
    report = _run(_with(**{"nimbus-03": {"unit": "USD", "currency": "USD"}}))
    assert _checks(report, "arr_from_mrr")[1] == ("2024-12-31", CheckStatus.VIOLATED, "")
    computed = {
        c.a.observations[0].observation_id: (c.divergence, c.reason)
        for c in report.comparisons
        if c.b.identity_id == "arr_from_mrr" and c.b.period.end.year == 2024
    }
    assert computed == {
        "nimbus-02": (DivergenceClass.CONSISTENT, ""),
        "nimbus-03": (None, "currency differs"),
        "nimbus-04": (DivergenceClass.INCONSISTENT, ""),
    }


def test_an_ambiguous_row_never_fills_a_term() -> None:
    report = _run(_with(**{"nimbus-10": {}}))
    assert _checks(report, "arr_ge_revenue_recognised")[1] == (
        "2024-12-31",
        CheckStatus.NOT_CHECKED,
        "only an ambiguous value for revenue_recognised: nimbus-12",
    )


def test_an_inferred_row_never_fills_a_term() -> None:
    rows = _with(**{"nimbus-12": {"value": Decimal(6950000)}})
    _add(rows, "nimbus-21", **_revenue(2023, "4650000"))
    _add(rows, "nimbus-22", **_revenue(2022, "3300000"))
    _add(rows, "arr-2022", metric_id="arr", value=Decimal(4000000), **_point(2022))
    assert _checks(_run(rows), "arr_ge_revenue_recognised")[0] == (
        "2022-12-31",
        CheckStatus.NOT_CHECKED,
        "only an inferred value for revenue_recognised: nimbus-22",
    )


def _revenue(year: int, value: str) -> dict[str, Any]:
    return NIMBUS["nimbus-12"].model_dump() | {
        "value": Decimal(value),
        "stated_precision": Decimal(5000),
        "period_start": date(year, 1, 1),
        "period_end": date(year, 12, 31),
        "as_of_date": date(year, 12, 31),
    }


def _point(year: int) -> dict[str, Any]:
    day = date(year, 12, 31)
    return {"period_start": day, "period_end": day, "as_of_date": day, "locator": "p4 chart"}


def test_an_undefined_metric_never_fills_a_term() -> None:
    report = _run(_with(**{"nimbus-08": {"metric_id": "mrr_eop"}}))
    assert _checks(report, "arr_from_mrr")[1] == (
        "2024-12-31",
        CheckStatus.NOT_CHECKED,
        "mrr not observed at 2024-12-31",
    )


def test_a_missing_term_gives_no_computed_path() -> None:
    report = _run(NIMBUS)
    assert _checks(report, "nrr_from_bridge") == [
        (
            "2024-12-31",
            CheckStatus.NOT_CHECKED,
            "mrr_expansion not observed for fy 2024-01-01 to 2024-12-31",
        )
    ]
    assert not any(c.b.identity_id == "nrr_from_bridge" for c in report.comparisons)


def test_a_zero_denominator_is_a_skip() -> None:
    rows = _with(**{"nimbus-01": {"value": Decimal(0)}})
    for metric_id in ("mrr_contraction", "mrr_churned"):
        _add(rows, metric_id, metric_id=metric_id, value=Decimal(1000), **_fy(2024))
    assert _checks(_run(rows), "grr_from_bridge") == [
        ("2024-12-31", CheckStatus.NOT_CHECKED, "zero denominator")
    ]


def _fy(year: int) -> dict[str, Any]:
    return {"period_start": date(year, 1, 1), "period_end": date(year, 12, 31), "period_type": "fy"}


def test_an_identity_with_no_evaluator_is_a_visible_skip() -> None:
    extra = Identity(
        identity_id="made_up",
        equation="arr = mrr",
        terms=("arr", "mrr"),
        tolerance_policy=TolerancePolicy.CURRENCY_DEFAULT,
    )
    dictionary = DICTIONARY.model_copy(update={"identities": (*DICTIONARY.identities, extra)})
    report = validate(NIMBUS.values(), dictionary)
    assert [
        (c.period, c.status, c.reason) for c in report.checks if c.identity_id == "made_up"
    ] == [(None, CheckStatus.NOT_CHECKED, "no evaluator")]


# ---------------------------------------------------------------- S2-04


def test_nimbus_invariants_hold_or_are_not_checked() -> None:
    report = _run(NIMBUS)
    assert report.findings[0].kind is FindingKind.DIVERGENCE
    assert _checks(report, "nrr_ge_grr") == [("2024-12-31", CheckStatus.HELD, "")]
    assert _checks(report, "customers_paying_le_users_registered") == [
        ("2023-12-31", CheckStatus.NOT_CHECKED, "users_registered not observed at 2023-12-31"),
        ("2024-12-31", CheckStatus.HELD, ""),
    ]
    assert _checks(report, "arr_ge_revenue_recognised") == [
        ("2023-12-31", CheckStatus.NOT_CHECKED, "arr not observed at 2022-12-31"),
        (
            "2024-12-31",
            CheckStatus.HELD,
            "revenue_services plus revenue_hardware is below 10% of revenue_recognised",
        ),
    ]


def test_more_paying_customers_than_users_is_a_violation() -> None:
    report = _run(_with(**{"nimbus-17": {"value": Decimal(4120)}}))
    (finding,) = (f for f in report.findings if f.kind is FindingKind.INVARIANT)
    assert finding.subject == "customers_paying_le_users_registered"
    assert [p.value for p in (finding.left, *finding.right)] == [Decimal(4120), Decimal(3950)]
    assert [*finding.left.locators, *finding.right[0].locators] == [
        "nimbus-deck-2025#p6",
        "nimbus-deck-2025#p6",
    ]
    assert _checks(report, "customers_paying_le_users_registered")[1][1] is CheckStatus.VIOLATED


def test_the_inequality_margin_absorbs_rounding_at_the_boundary() -> None:
    changes = {
        "nimbus-19": {"value": Decimal("91.0"), "stated_precision": Decimal("0.05")},
        "nimbus-20": {"value": Decimal("91.05"), "stated_precision": Decimal("0.005")},
    }
    assert _checks(_run(_with(**changes)), "nrr_ge_grr") == [("2024-12-31", CheckStatus.HELD, "")]


def test_arr_growth_of_30_percent_or_less_skips_the_revenue_invariant() -> None:
    report = _run(_with(**{"nimbus-01": {"value": Decimal(7000000)}}))
    assert _checks(report, "arr_ge_revenue_recognised")[1][1:] == (
        CheckStatus.NOT_CHECKED,
        "condition not met: arr grew more than 30% over those 12 months, "
        "arr[t] / arr[t-12m] - 1 > 0.30",
    )


@pytest.mark.parametrize(
    ("services", "hardware", "expected"),
    [
        ("500000", "300000", (CheckStatus.NOT_CHECKED, "condition not met")),
        ("100000", "50000", (CheckStatus.HELD, "")),
    ],
)
def test_the_services_share_is_tested_when_observed(
    services: str, hardware: str, expected: tuple[CheckStatus, str]
) -> None:
    rows = dict(NIMBUS)
    for metric_id, value in (("revenue_services", services), ("revenue_hardware", hardware)):
        _add(rows, metric_id, metric_id=metric_id, value=Decimal(value), **_fy(2024))
    status, reason = _checks(_run(rows), "arr_ge_revenue_recognised")[1][1:]
    assert (status, reason[: len(expected[1])]) == expected


def test_revenue_above_arr_states_the_assumption() -> None:
    report = _run(_with(**{"nimbus-10": {"value": Decimal(9000000)}}))
    invariants = [f for f in report.findings if f.kind is FindingKind.INVARIANT]
    assert [f.left.key[1][0] for f in invariants] == ["nimbus-02", "nimbus-03", "nimbus-04"]
    assert {f.assumption for f in invariants} == {
        "revenue_services plus revenue_hardware is below 10% of revenue_recognised"
    }
    assert [p.key[1][0] for p in invariants[0].right] == ["nimbus-10", "nimbus-01"]


def test_two_violations_with_the_same_locators_give_one_finding() -> None:
    rows = _with(**{"nimbus-17": {"value": Decimal(4120)}})
    _add(rows, "nimbus-17b", **(NIMBUS["nimbus-17"].model_dump() | {"value": Decimal(4200)}))
    (finding,) = (f for f in _run(rows).findings if f.kind is FindingKind.INVARIANT)
    assert [p.key[1][0] for p in (finding.left, *finding.right)] == [
        "nimbus-17",
        "nimbus-18",
        "nimbus-17b",
    ]


# ---------------------------------------------------------------- S2-05


def test_a_bridge_that_closes_holds() -> None:
    report = _run(_bridge())
    assert _checks(report, BRIDGE_ID) == [("2024-12-31", CheckStatus.HELD, "")]
    assert not any(f.kind is FindingKind.BRIDGE for f in report.findings)


def test_a_bridge_that_does_not_close_reports_its_residual() -> None:
    report = _run(_bridge(new="76000"))
    (finding,) = (f for f in report.findings if f.kind is FindingKind.BRIDGE)
    (computed,) = finding.right
    assert finding.left.value - computed.value == Decimal(-24000)
    assert [o.observation_id for o in computed.observations] == [
        "nimbus-07",
        "bridge-mrr_new",
        "bridge-mrr_expansion",
        "bridge-mrr_reactivation",
        "bridge-mrr_contraction",
        "bridge-mrr_churned",
    ]
    assert _checks(report, BRIDGE_ID)[0][1] is CheckStatus.VIOLATED


def test_a_missing_bridge_term_is_never_zero() -> None:
    report = _run(_bridge(mrr_reactivation=True))
    assert _checks(report, BRIDGE_ID) == [
        (
            "2024-12-31",
            CheckStatus.NOT_CHECKED,
            "mrr_reactivation not observed for quarter 2024-10-01 to 2024-12-31",
        )
    ]


def test_an_ambiguous_bridge_term_skips_the_bridge() -> None:
    rows = _bridge(mrr_expansion=True)
    _add(
        rows,
        "bridge-upsell",
        metric_id="bridge_movement_unspecified",
        value=Decimal(31000),
        locator="p12 waterfall",
        stated_label="Upsell",
        definition_status="ambiguous",
        candidate_metric_ids=("mrr_expansion", "mrr_contraction"),
        **Q4,
    )
    assert _checks(_run(rows), BRIDGE_ID)[0][2] == (
        "only an ambiguous value for mrr_expansion: bridge-upsell"
    )


def test_a_retention_rate_that_is_not_twelve_months_is_not_checked() -> None:
    rows = _with(**{"nimbus-19": Q4})
    assert _checks(_run(rows), "nrr_from_bridge") == [
        ("2024-12-31", CheckStatus.NOT_CHECKED, "condition not met: nrr covers 12 months")
    ]


def test_a_percent_term_in_another_unit_is_not_checked() -> None:
    report = _run(_with(**{"nimbus-20": {"unit": "bp", "value": Decimal(9100)}}))
    assert _checks(report, "nrr_ge_grr") == [
        ("2024-12-31", CheckStatus.NOT_CHECKED, "unit differs: bp and percent")
    ]


def test_a_mid_month_date_looks_up_the_same_day_a_year_before() -> None:
    rows = dict(NIMBUS)
    day = date(2024, 6, 15)
    _add(rows, "arr-mid", metric_id="arr", period_start=day, period_end=day, as_of_date=day)
    assert _checks(_run(rows), "arr_ge_revenue_recognised")[1] == (
        "2024-06-15",
        CheckStatus.NOT_CHECKED,
        "revenue_recognised not observed for fy 2023-06-16 to 2024-06-15",
    )


def test_a_bridge_term_in_another_currency_is_not_checked() -> None:
    rows = _bridge()
    rows["bridge-mrr_new"] = Observation(
        **(rows["bridge-mrr_new"].model_dump() | {"unit": "USD", "currency": "USD"})
    )
    assert _checks(_run(rows), BRIDGE_ID)[0][2] == "currency differs: EUR and USD"


# ---------------------------------------------------------------- S3-19


def _ifrs(
    observation_id: str, metric_id: str, value: Decimal, label: str, unit: str = "EUR"
) -> dict[str, Observation]:
    """One synthetic listed-company FY2024 row (S3-19). ``unit`` is "percent" for a
    margin row, since a margin observation carries no currency.
    """
    fields = valid_observation_fields() | {
        "observation_id": observation_id,
        "entity_id": "ifrsco",
        "document_id": "ifrsco-2024",
        "metric_id": metric_id,
        "value": value,
        "unit": unit,
        "currency": None if unit == "percent" else unit,
        "stated_precision": None,
        "period_start": date(2024, 1, 1),
        "period_end": date(2024, 12, 31),
        "period_type": "fy",
        "as_of_date": date(2024, 12, 31),
        "stated_label": label,
    }
    return {observation_id: Observation(**fields)}


class _IfrsCase(NamedTuple):
    """One S3-19 identity: its exact FY2024 values and one planted defect."""

    identity_id: str
    target: str
    label: str
    unit: str
    hold: Decimal
    planted: Decimal
    other: tuple[tuple[str, Decimal, str, str], ...]  # metric_id, value, label, unit


_EBT_PROFIT_CASE = _IfrsCase(
    "net_income_from_ebt",
    "net_income",
    "Net income",
    "EUR",
    Decimal(70),
    Decimal(75),
    (
        ("ebt", Decimal(100), "Profit before tax (EBT)", "EUR"),
        ("income_tax_expense", Decimal(30), "Income tax expense", "EUR"),
        ("ebit", Decimal(90), "EBIT", "EUR"),
    ),
)

_IFRS_CASES: tuple[_IfrsCase, ...] = (
    _IfrsCase(
        "gross_profit_from_revenue",
        "gross_profit",
        "Gross profit",
        "EUR",
        Decimal(120),
        Decimal(110),
        (
            ("revenue_recognised", Decimal(200), "Revenue", "EUR"),
            ("cost_of_sales", Decimal(80), "Cost of sales", "EUR"),
        ),
    ),
    _IfrsCase(
        "ebitda_from_ebit",
        "ebitda",
        "EBITDA",
        "EUR",
        Decimal(60),
        Decimal(66),
        (
            ("ebit", Decimal(50), "EBIT", "EUR"),
            ("d_and_a", Decimal(10), "Depreciation and amortisation", "EUR"),
        ),
    ),
    _IfrsCase(
        "gross_margin_from_revenue",
        "gross_margin",
        "Gross margin",
        "percent",
        Decimal(60),
        Decimal(66),
        (
            ("gross_profit", Decimal(120), "Gross profit", "EUR"),
            ("revenue_recognised", Decimal(200), "Revenue", "EUR"),
        ),
    ),
    # ebitda_adjusted is a decoy: a wrong term reading it instead of ebitda must fail too.
    # Also S3-20 criteria 4 and 5.
    _IfrsCase(
        "ebitda_margin_from_revenue",
        "ebitda_margin",
        "EBITDA margin",
        "percent",
        Decimal(30),
        Decimal(33),
        (
            ("ebitda", Decimal(60), "EBITDA", "EUR"),
            ("revenue_recognised", Decimal(200), "Revenue", "EUR"),
            ("ebitda_adjusted", Decimal(70), "Adjusted EBITDA", "EUR"),
        ),
    ),
    # ebitda is a decoy: a wrong term reading it instead of ebitda_adjusted must fail too.
    _IfrsCase(
        "ebitda_adjusted_margin_from_revenue",
        "ebitda_adjusted_margin",
        "Adjusted EBITDA margin",
        "percent",
        Decimal(35),
        Decimal(39),
        (
            ("ebitda_adjusted", Decimal(70), "Adjusted EBITDA", "EUR"),
            ("revenue_recognised", Decimal(200), "Revenue", "EUR"),
            ("ebitda", Decimal(60), "EBITDA", "EUR"),
        ),
    ),
    # net_income is a decoy: a wrong term reading it instead of ebit must fail too.
    _IfrsCase(
        "ebit_margin_from_revenue",
        "ebit_margin",
        "EBIT margin",
        "percent",
        Decimal(25),
        Decimal(28),
        (
            ("ebit", Decimal(50), "EBIT", "EUR"),
            ("revenue_recognised", Decimal(200), "Revenue", "EUR"),
            ("net_income", Decimal(40), "Net income", "EUR"),
        ),
    ),
    # ebit is a decoy: a wrong term reading it instead of net_income must fail too.
    _IfrsCase(
        "net_margin_from_revenue",
        "net_margin",
        "Net margin",
        "percent",
        Decimal(20),
        Decimal(22),
        (
            ("net_income", Decimal(40), "Net income", "EUR"),
            ("revenue_recognised", Decimal(200), "Revenue", "EUR"),
            ("ebit", Decimal(50), "EBIT", "EUR"),
        ),
    ),
    # S3-24: ebit is a decoy: a wrong term reading it instead of ebt must fail too.
    _EBT_PROFIT_CASE,
    _IfrsCase(
        "net_income_from_ebt",
        "net_income",
        "Net income",
        "EUR",
        Decimal(-12),
        Decimal(-20),
        (
            ("ebt", Decimal(-10), "Profit before tax (EBT)", "EUR"),
            ("income_tax_expense", Decimal(2), "Income tax expense", "EUR"),
            ("ebit", Decimal(-8), "EBIT", "EUR"),
        ),
    ),
)


def _ifrs_rows(case: _IfrsCase, *, planted: bool) -> dict[str, Observation]:
    rows: dict[str, Observation] = {}
    for metric_id, value, label, unit in case.other:
        rows |= _ifrs(f"ifrs-{metric_id}", metric_id, value, label, unit=unit)
    target_value = case.planted if planted else case.hold
    rows |= _ifrs(f"ifrs-{case.target}", case.target, target_value, case.label, unit=case.unit)
    return rows


@pytest.mark.parametrize("case", _IFRS_CASES, ids=lambda c: c.identity_id)
def test_an_s3_19_identity_holds_on_the_printed_values(case: _IfrsCase) -> None:
    report = _run(_ifrs_rows(case, planted=False))
    assert _checks(report, case.identity_id) == [("2024-12-31", CheckStatus.HELD, "")]
    assert not report.findings


@pytest.mark.parametrize("case", _IFRS_CASES, ids=lambda c: c.identity_id)
def test_an_s3_19_identity_raises_one_finding_on_a_planted_defect(case: _IfrsCase) -> None:
    report = _run(_ifrs_rows(case, planted=True))
    assert len(report.findings) == 1
    assert report.findings[0].subject == case.target


def test_a_tax_credit_loss_period_holds_on_the_alternate_sign() -> None:
    """S3-24, criterion 4 (story decision 28). The extractor stores a tax credit as a
    positive income tax expense (2.0). The primary path -10.0 - 2.0 = -12.0 is outside tolerance
    of the printed -8.0, so a held check with no finding proves the alternate path -10.0 + 2.0.
    """
    rows = {
        **_ifrs("s324-ebt", "ebt", Decimal(-10), "Profit before tax (EBT)"),
        **_ifrs("s324-tax", "income_tax_expense", Decimal(2), "Income tax credit"),
        **_ifrs("s324-net", "net_income", Decimal(-8), "Net income"),
    }
    report = _run(rows)
    assert _checks(report, "net_income_from_ebt") == [("2024-12-31", CheckStatus.HELD, "")]
    assert not report.findings


def test_a_planted_net_income_cites_the_printed_value_and_the_subtracted_formula() -> None:
    """S3-24, criterion 5. Net income 75.0 is outside
    tolerance of 70.0 (ebt - tax) and of 130.0 (ebt + tax). The finding cites 70.0, never 130.0.
    """
    case = _EBT_PROFIT_CASE
    rows = {
        key: Observation(**(row.model_dump() | {"locator": f"p{n}"}))
        for n, (key, row) in enumerate(_ifrs_rows(case, planted=True).items(), start=1)
    }
    report = _run(rows)
    assert _checks(report, "net_income_from_ebt")[0][1] is CheckStatus.VIOLATED
    (finding,) = report.findings
    assert finding.subject == "net_income"
    assert finding.left.value == Decimal(75)
    assert finding.left.locators == ("ifrsco-2024#p4",)
    (computed,) = finding.right
    assert computed.value == Decimal(70)
    assert computed.identity_id == "net_income_from_ebt"
    assert [(o.metric_id, o.locator) for o in computed.observations] == [
        ("ebt", "p1"),
        ("income_tax_expense", "p2"),
    ]


# ---------------------------------------------------------------- S3-20


def test_an_ebitda_margin_is_not_checked_when_the_revenue_row_stays_ambiguous() -> None:
    """S3-20, criterion 6 (regression). The revenue line prints only "Revenue", so
    it stays ``revenue_unspecified`` and ambiguous. The check reports NOT_CHECKED
    and names the ambiguous row; it never reads it as the denominator.
    """
    revenue_fields = valid_observation_fields() | {
        "observation_id": "s320-revenue",
        "entity_id": "ifrsco",
        "document_id": "ifrsco-2024",
        "metric_id": "revenue_unspecified",
        "value": Decimal(200),
        "unit": "EUR",
        "currency": "EUR",
        "stated_precision": None,
        "period_start": date(2024, 1, 1),
        "period_end": date(2024, 12, 31),
        "period_type": "fy",
        "as_of_date": date(2024, 12, 31),
        "stated_label": "Revenue",
        "definition_status": DefinitionStatus.AMBIGUOUS,
        "candidate_metric_ids": ("revenue_recognised", "arr"),
    }
    rows = {
        **_ifrs("s320-ebitda", "ebitda", Decimal(60), "EBITDA"),
        **_ifrs("s320-margin", "ebitda_margin", Decimal(30), "EBITDA margin", unit="percent"),
        "s320-revenue": Observation(**revenue_fields),
    }
    assert _checks(_run(rows), "ebitda_margin_from_revenue") == [
        (
            "2024-12-31",
            CheckStatus.NOT_CHECKED,
            "only an ambiguous value for revenue_recognised: s320-revenue",
        )
    ]


# ---------------------------------------------------------------- S3-12, qualifiers

_SEGMENT_FY_2024 = {
    "period_start": date(2024, 1, 1),
    "period_end": date(2024, 12, 31),
    "period_type": "fy",
    "as_of_date": date(2024, 12, 31),
}


def _segment_row(observation_id: str, metric_id: str, value: str, **changes: Any) -> Observation:
    fields = {
        **valid_observation_fields(),
        "observation_id": observation_id,
        "metric_id": metric_id,
        "value": Decimal(value),
        "stated_precision": None,
        **_SEGMENT_FY_2024,
        **changes,
    }
    return Observation(**fields)


def test_an_identity_check_runs_once_per_segment_with_no_term_crossing_a_segment() -> None:
    """S3-12, criterion 7. North holds:
    1,000,000 - 400,000 = 600,000. South's stated gross profit (900,000) matches South's own
    terms (2,000,000 - 1,300,000 = 700,000) only if no term crosses a segment; it is planted to
    violate, so a crossed check (mixing North's revenue with South's cost, or the reverse) would
    give a different status than the one asserted here.
    """
    rows = [
        _segment_row("north-revenue", "revenue_recognised", "1000000", segment="North"),
        _segment_row("north-cost", "cost_of_sales", "400000", segment="North"),
        _segment_row("north-gross", "gross_profit", "600000", segment="North"),
        _segment_row("south-revenue", "revenue_recognised", "2000000", segment="South"),
        _segment_row("south-cost", "cost_of_sales", "1300000", segment="South"),
        _segment_row("south-gross", "gross_profit", "900000", segment="South"),
    ]

    report = validate(rows, DICTIONARY)

    by_qualifier = {
        c.qualifier: c.status for c in report.checks if c.identity_id == "gross_profit_from_revenue"
    }
    assert by_qualifier == {
        Qualifier(segment="north"): CheckStatus.HELD,
        Qualifier(segment="south"): CheckStatus.VIOLATED,
    }

    (finding,) = (f for f in report.findings if f.subject == "gross_profit")
    segments = {o.segment for path in (finding.left, *finding.right) for o in path.observations}
    assert segments == {"South"}


def test_two_segments_violating_one_invariant_on_one_page_give_two_findings() -> None:
    """North and South both violate
    ``customers_paying_le_users_registered`` on the one page every ``_segment_row`` call defaults
    to (same ``locator``). ``_dedup_key`` must key on the qualifier too, or the second finding
    merges into the first and the question cites paths from both segments.
    """
    rows = [
        _segment_row("north-customers", "customers_paying", "1000", segment="North"),
        _segment_row("north-users", "users_registered", "800", segment="North"),
        _segment_row("south-customers", "customers_paying", "2000", segment="South"),
        _segment_row("south-users", "users_registered", "1500", segment="South"),
    ]

    report = validate(rows, DICTIONARY)

    findings = [f for f in report.findings if f.subject == "customers_paying_le_users_registered"]
    assert len(findings) == 2
    for finding in findings:
        segments = {o.segment for path in (finding.left, *finding.right) for o in path.observations}
        assert len(segments) == 1
