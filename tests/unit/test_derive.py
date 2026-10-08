"""S4-01: derivation fills the target term of an equality."""

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from fact_ledger.domain import Observation, Period, PeriodType
from fact_ledger.domain.checks import build_index, derive
from fact_ledger.domain.models import Qualifier
from fact_ledger.domain.paths import ComputationPath, direct_path
from fact_ledger.store.yaml_files import load_dictionary, read_transcript

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]
DICTIONARY = load_dictionary(ROOT / "data" / "dictionary")
CLEAN = {
    o.observation_id: o for o in read_transcript(ROOT / "evals/corpus/clean-nimbus/transcript.yaml")
}
FY2024 = Period(date(2024, 1, 1), date(2024, 12, 31), PeriodType.FY)


def _row(base: str, row_id: str, **fields: Any) -> Observation:
    return Observation(**(CLEAN[base].model_dump() | fields | {"observation_id": row_id}))


def _fills(*extra: Observation, without: tuple[str, ...] = ()) -> list[ComputationPath]:
    rows = {k: v for k, v in CLEAN.items() if k not in without}
    rows |= {o.observation_id: o for o in extra}
    paths = {i: direct_path(r, DICTIONARY) for i, r in rows.items()}
    index = build_index(rows.values(), paths, DICTIONARY)[Qualifier()]
    return derive(index, DICTIONARY)


def _of(fills: list[ComputationPath], metric_id: str) -> list[ComputationPath]:
    return [p for p in fills if p.metric_id == metric_id]


def _ids(path: ComputationPath) -> set[str]:
    return {o.observation_id for o in path.observations}


def test_clean_nimbus_derives_one_arr_and_two_net_new_arr_paths() -> None:
    fills = _fills()
    assert sorted(p.metric_id for p in fills) == ["arr", "net_new_arr", "net_new_arr"]


def test_an_arr_fill_is_twelve_times_mrr_and_keeps_its_input_and_precision() -> None:
    (fill,) = _of(_fills(), "arr")
    assert (fill.identity_id, _ids(fill), fill.value, fill.precision) == (
        "arr_from_mrr",
        {"nimbus-07"},
        Decimal(7176000),
        Decimal(6000),
    )


def test_net_new_arr_is_filled_for_the_twelve_months_that_end_on_each_arr_date() -> None:
    fills = _of(_fills(), "net_new_arr")
    assert {p.period for p in fills} == {FY2024}
    by_value = {p.value: _ids(p) for p in fills}
    assert by_value == {
        Decimal(2664000): {"nimbus-02", "nimbus-01"},
        Decimal(2600000): {"nimbus-03", "nimbus-01"},
    }


def test_a_net_new_arr_row_for_the_period_stops_its_fill() -> None:
    stated = _row(
        "nimbus-01",
        "nnarr-fy",
        metric_id="net_new_arr",
        value=Decimal(2500000),
        period_start=FY2024.start,
        period_end=FY2024.end,
        period_type=FY2024.type,
    )
    assert _of(_fills(stated), "net_new_arr") == []


def test_a_filled_value_has_the_reliability_of_its_weakest_input() -> None:
    weak = _row("nimbus-01", "nimbus-01", reliability=2)
    assert {p.reliability for p in _of(_fills(weak), "net_new_arr")} == {2}


def test_a_bridge_over_one_quarter_fills_neither_nrr_nor_grr() -> None:
    fills = _fills(without=("nimbus-19", "nimbus-20"))
    assert _of(fills, "nrr") == _of(fills, "grr") == []


def test_a_bridge_over_twelve_months_fills_grr() -> None:
    year = {"period_start": date(2024, 1, 1), "period_end": date(2024, 12, 31), "period_type": "fy"}
    rows = [
        _row("nimbus-34", "contraction-fy", **year),
        _row("nimbus-35", "churned-fy", **year),
    ]
    (fill,) = _of(_fills(*rows, without=("nimbus-20",)), "grr")
    # arr 5,400,000 at 2023-12-31, and 12 x (4,000 + 5,000) of MRR lost
    assert (fill.identity_id, fill.value) == ("grr_from_bridge", Decimal(98))


def test_a_target_with_a_resolved_row_is_not_filled() -> None:
    stated = _row("nimbus-07", "arr-sep", metric_id="arr", value=Decimal(7100000))
    assert _of(_fills(stated), "arr") == []
    assert _of(_fills(), "churn_logo_annual") == []


def test_a_missing_term_gives_no_fill() -> None:
    assert _of(_fills(without=("nimbus-07",)), "arr") == []
    assert _of(_fills(without=("nimbus-01",)), "net_new_arr") == []


def test_a_term_in_another_currency_gives_no_fill() -> None:
    usd = _row("nimbus-01", "nimbus-01", unit="USD", currency="USD")
    assert _of(_fills(usd), "net_new_arr") == []


def test_a_derived_value_is_not_the_input_of_another_derivation() -> None:
    # mrr at 2024-09-30 fills arr there. A net_new_arr for the 12 months to that date would
    # need that derived arr as its end term.
    day = date(2023, 9, 30)
    start = _row("nimbus-01", "arr-2023-09", period_start=day, period_end=day, as_of_date=day)
    fills = _fills(start, without=("nimbus-01", "nimbus-02", "nimbus-03"))
    assert [p.metric_id for p in fills if p.period.end == date(2024, 9, 30)] == ["arr"]
    assert _of(fills, "net_new_arr") == []
