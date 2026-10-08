"""S4-01: a conspicuous absence is an expected metric that the pack neither shows nor lets the
analyst compute.
"""

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from fact_ledger.domain import Observation
from fact_ledger.domain.patterns import Absence, expected_metrics, patterns
from fact_ledger.domain.questions import absence_question
from fact_ledger.store.yaml_files import load_dictionary, read_transcript

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]
DICTIONARY = load_dictionary(ROOT / "data" / "dictionary")
CLEAN = {
    o.observation_id: o for o in read_transcript(ROOT / "evals/corpus/clean-nimbus/transcript.yaml")
}
GRR = Absence("nimbus", "grr")
FY2025 = {
    "period_start": date(2025, 1, 1),
    "period_end": date(2025, 12, 31),
    "as_of_date": date(2025, 12, 31),
}


def _row(base: str, row_id: str, **fields: Any) -> Observation:
    return Observation(**(CLEAN[base].model_dump() | fields | {"observation_id": row_id}))


def _absences(*extra: Observation, without: tuple[str, ...] = ()) -> list[Absence]:
    rows = {k: v for k, v in CLEAN.items() if k not in without}
    rows |= {o.observation_id: o for o in extra}
    return patterns(rows.values(), DICTIONARY, "b2b_saas")[0]


def test_clean_nimbus_with_a_sector_has_no_absence() -> None:
    # Present through a fill (net_new_arr) or through split rows only (region, segment).
    assert "net_new_arr" not in {r.metric_id for r in CLEAN.values()}
    assert {CLEAN[i].metric_id for i in ("nimbus-46", "nimbus-47")} == {
        "revenue_by_geography",
        "revenue_by_segment",
    }
    assert _absences() == []


def test_removing_the_only_grr_row_gives_one_absence() -> None:
    assert _absences(without=("nimbus-20",)) == [GRR]


def test_no_sector_means_no_absence_check() -> None:
    rows = [r for r in CLEAN.values() if r.observation_id != "nimbus-20"]
    assert patterns(rows, DICTIONARY, None)[0] == []


def test_a_pack_with_one_row_lacks_every_other_expected_metric_in_sorted_order() -> None:
    absences = patterns([CLEAN["nimbus-02"]], DICTIONARY, "b2b_saas")[0]
    assert [a.metric_id for a in absences] == sorted(
        expected_metrics(DICTIONARY, "b2b_saas") - {"arr"}
    )
    assert {a.entity_id for a in absences} == {"nimbus"}


def test_each_entity_has_its_own_absences() -> None:
    orion = _row("nimbus-02", "orion-02", entity_id="orion")
    absences = _absences(orion)
    assert Absence("orion", "grr") in absences
    assert not [a for a in absences if a.entity_id == "nimbus"]


def test_an_entity_with_only_undefined_metric_rows_gets_every_expected_absence() -> None:
    # Grouped by entity before the undefined-metric filter, so the
    # entity keeps an empty row set instead of dropping out of the check.
    ghost = _row("nimbus-02", "ghost-01", entity_id="ghost", metric_id="not_a_real_metric")
    absences = {a.metric_id for a in _absences(ghost) if a.entity_id == "ghost"}
    assert absences == expected_metrics(DICTIONARY, "b2b_saas")


@pytest.mark.parametrize("fields", [{"segment": "Enterprise"}, {"region": "Nordics"}])
def test_a_segment_or_region_row_alone_makes_its_metric_present(fields: dict[str, Any]) -> None:
    assert GRR not in _absences(_row("nimbus-20", "nimbus-20", **fields))


@pytest.mark.parametrize(
    "fields",
    [
        pytest.param(
            {
                "metric_id": "retention_unspecified",
                "definition_status": "ambiguous",
                "candidate_metric_ids": ("nrr", "grr"),
                "stated_label": "Retention",
            },
            id="ambiguous",
        ),
        pytest.param(
            {
                "metric_id": "retention_unspecified",
                "definition_status": "ambiguous",
                "candidate_metric_ids": ("nrr", "grr"),
                "stated_label": "Retention",
                "value": Decimal(118),
            },
            id="inferred-as-another-candidate",
        ),
        pytest.param(FY2025, id="projection"),
    ],
)
def test_an_ambiguous_inferred_or_projected_row_leaves_the_metric_absent(
    fields: dict[str, Any],
) -> None:
    assert GRR in _absences(_row("nimbus-20", "nimbus-20", **fields))


def _arr_at(row_id: str, day: date, published: date) -> Observation:
    return _row(
        "nimbus-02",
        row_id,
        period_start=day,
        period_end=day,
        as_of_date=day,
        published_date=published,
    )


@pytest.mark.parametrize(
    ("published", "absent"),
    [(date(2027, 3, 1), False), (date(2025, 3, 1), True)],
    ids=["actual-inputs", "projection-inputs"],
)
def test_a_fill_with_a_projection_input_makes_nothing_present(
    published: date, absent: bool
) -> None:
    arr = [
        _arr_at("arr-2025", date(2025, 12, 31), published),
        _arr_at("arr-2026", date(2026, 12, 31), published),
    ]
    absences = _absences(*arr, without=("nimbus-01", "nimbus-02", "nimbus-03"))
    assert (Absence("nimbus", "net_new_arr") in absences) is absent


def test_the_absence_question_names_the_metric_and_asks_for_periods_and_definition() -> None:
    assert absence_question(GRR, DICTIONARY) == (
        "Gross revenue retention is not in the pack, and the pack does not give the values to "
        "calculate it. What is Gross revenue retention for each period that the pack reports, "
        "and how do you define it?"
    )


def test_b2b_saas_expects_53_metrics() -> None:
    assert len(expected_metrics(DICTIONARY, "b2b_saas")) == 53


def test_an_empty_sector_raises_and_does_not_skip_the_check() -> None:
    with pytest.raises(ValueError, match="unknown sector ''"):
        patterns([CLEAN["nimbus-02"]], DICTIONARY, "")


def test_an_unknown_sector_raises_and_lists_the_four_codes_sorted() -> None:
    with pytest.raises(ValueError, match=r"b2b_saas.*b2c_subscription.*dtc_commerce.*marketplace"):
        expected_metrics(DICTIONARY, "b2b_sass")
