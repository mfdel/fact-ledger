"""S4-02: a projection discontinuity."""

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from fact_ledger.domain import Derivation, FindingKind, Observation
from fact_ledger.domain.paths import Finding
from fact_ledger.domain.patterns import cagr, patterns
from fact_ledger.domain.questions import question
from fact_ledger.domain.validator import validate
from fact_ledger.store.yaml_files import load_dictionary, read_transcript

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]
DICTIONARY = load_dictionary(ROOT / "data" / "dictionary")
CLEAN = {
    o.observation_id: o for o in read_transcript(ROOT / "evals/corpus/clean-nimbus/transcript.yaml")
}


def _at(year: int) -> dict[str, date]:
    day = date(year, 12, 31)
    return {"period_start": day, "period_end": day, "as_of_date": day}


def _plan(row_id: str = "nimbus-plan", value: str = "14000000", **fields: Any) -> Observation:
    """A plan row of arr on the base of clean-nimbus: published 2025-03-01, as of 2025-12-31."""
    base = CLEAN["nimbus-02"].model_dump()
    defaults = _at(2025) | {
        "value": Decimal(value),
        "stated_precision": Decimal(50000),
        "locator": "p15 plan",
        "stated_label": "ARR",
    }
    return Observation(**base | defaults | fields | {"observation_id": row_id})


def _findings(*extra: Observation, without: tuple[str, ...] = ()) -> list[Finding]:
    rows = {k: v for k, v in CLEAN.items() if k not in without}
    rows |= {o.observation_id: o for o in extra}
    return patterns(rows.values(), DICTIONARY, None)[1]


def _ids(path: Any) -> list[str]:
    return [o.observation_id for o in path.observations]


def test_a_plan_faster_than_the_record_gives_one_projection_finding() -> None:
    (finding,) = _findings(_plan())
    assert finding.kind == FindingKind.PROJECTION
    assert finding.entity_id == "nimbus"
    assert finding.subject == "arr"
    assert _ids(finding.left) == ["nimbus-plan"]
    assert [_ids(p) for p in finding.right] == [["nimbus-01"], ["nimbus-02"]]


def test_the_projection_question_names_both_rates_and_each_locator() -> None:
    (finding,) = _findings(_plan())
    assert question(finding, DICTIONARY) == (
        "Annual recurring revenue at 2025-12-31 is planned at EUR 14,000,000 on p15 plan "
        '("ARR"), growth of 73.6% a year from EUR 8,064,000 on p4 chart ("Annual recurring '
        'revenue (exit)"). Before that, from EUR 5,400,000 on p4 chart ("ARR"), Annual '
        "recurring revenue grew 49.3% a year. What causes the planned growth to be higher "
        "than the realized growth?"
    )


def test_a_plan_within_the_margin_of_the_record_gives_no_finding() -> None:
    assert _findings(_plan(value="12500000")) == []


def _earlier_plan() -> Observation:
    return _plan(
        "nimbus-plan-2024",
        value="9000000",
        document_id="nimbus-deck-2024",
        locator="p14 plan",
        published_date=date(2024, 3, 1),
        period_start=date(2024, 12, 31),
        period_end=date(2024, 12, 31),
        as_of_date=date(2024, 12, 31),
    )


def test_validate_gives_no_finding_that_cites_a_plan_row() -> None:
    report = validate([*CLEAN.values(), _earlier_plan()], DICTIONARY)
    cited = {
        row_id for f in report.findings for path in (f.left, *f.right) for row_id in _ids(path)
    }
    assert "nimbus-plan-2024" not in cited


def test_a_plan_row_is_not_an_end_of_the_realized_rate() -> None:
    # nimbus-plan-2024 has the higher precision. As an actual row it would be `last`, and
    # its rate from nimbus-01 (66.7%) would hide the break of the plan at 2025-12-31.
    precise = _earlier_plan().model_copy(update={"stated_precision": Decimal(1)})
    (finding,) = _findings(_plan(), precise)
    assert [_ids(p) for p in finding.right] == [["nimbus-01"], ["nimbus-02"]]


def test_no_finding_cites_a_plan_row_with_no_actual_pair_before_it() -> None:
    assert _findings(_earlier_plan()) == []


@pytest.mark.parametrize(
    "fields",
    [{"segment": "Enterprise"}, {"basis": "pro_forma"}],
    ids=["segment", "pro_forma"],
)
def test_a_plan_with_a_qualifier_gives_no_finding_however_fast(fields: dict[str, Any]) -> None:
    assert _findings(_plan(value="40000000", **fields)) == []


@pytest.mark.parametrize(
    ("plan_fields", "without"),
    [
        pytest.param(
            {
                "period_start": date(2025, 6, 30),
                "period_end": date(2025, 6, 30),
                "as_of_date": date(2025, 6, 30),
            },
            (),
            id="span-under-12-months",
        ),
        pytest.param({}, ("nimbus-01",), id="no-actual-pair-12-months-apart"),
        pytest.param({"value": Decimal(-5000000)} | _at(2026), (), id="negative-plan"),
    ],
)
def test_a_plan_with_no_valid_anchor_gives_no_finding(
    plan_fields: dict[str, Any], without: tuple[str, ...]
) -> None:
    assert _findings(_plan(**plan_fields), without=without) == []


def test_the_realized_rate_reads_the_latest_pair_not_the_first_or_the_whole_record() -> None:
    # The pair 2022-2023 grows 100%, so a first-pair rate hides the break. The whole record
    # grows 72.8% a year, which hides it too.
    (finding,) = _findings(_plan("nimbus-00", "2700000", **_at(2022)), _plan())
    assert [_ids(p) for p in finding.right] == [["nimbus-01"], ["nimbus-02"]]


@pytest.mark.parametrize(
    ("last_value", "plan_value", "flagged"),
    [("8000000", "9000000", True), ("20000000", "42000000", False), ("20000000", "42500000", True)],
    ids=["shrinking-company-plans-growth", "exactly-10-points", "over-10-points"],
)
def test_the_margin_is_10_points_and_a_shrinking_company_that_plans_growth_is_flagged(
    last_value: str, plan_value: str, flagged: bool
) -> None:
    # 10M to 8M is -20% a year, so the plan of 9M (+12.5%) is 32.5 points above it. 10M to 20M
    # is +100% a year, so a plan of 42M is exactly 110%.
    actuals = [
        _plan("a-1", "10000000", **_at(2023)),
        _plan("a-2", last_value, **_at(2024)),
    ]
    found = _findings(
        *actuals, _plan(value=plan_value), without=("nimbus-01", "nimbus-02", "nimbus-03")
    )
    assert bool(found) is flagged


@pytest.mark.parametrize(
    "fields",
    [
        {
            "derivation": Derivation(
                identity_id="arr_from_mrr", input_observation_ids=("nimbus-02",)
            )
        },
        {"definition_status": "ambiguous", "candidate_metric_ids": ("mrr",)},
        {"segment": "Enterprise"},
    ],
    ids=["derived", "ambiguous", "segment"],
)
def test_only_resolved_direct_group_actual_rows_serve_as_the_realized_ends(
    fields: dict[str, Any],
) -> None:
    # Each decoy has the best precision at its date, so it wins the rank if the filter lets it in.
    decoys = [
        _plan(f"decoy-{year}", "1000000", stated_precision=Decimal(1), **_at(year), **fields)
        for year in (2023, 2024)
    ]
    (finding,) = _findings(_plan(), *decoys)
    assert [_ids(p) for p in finding.right] == [["nimbus-01"], ["nimbus-02"]]


@pytest.mark.parametrize(
    ("end_value", "years", "rate"),
    [("150", 1, 50), ("144", 2, 20)],
    ids=["one-year", "two-years-annualized"],
)
def test_cagr_is_the_yearly_rate_in_points(end_value: str, years: int, rate: int) -> None:
    start = _plan("start", "100", **_at(2023))
    end = _plan("end", end_value, **_at(2023 + years))
    assert cagr(start, end) == pytest.approx(Decimal(rate), abs=Decimal("0.000001"))
