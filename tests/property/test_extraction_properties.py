"""P1: ``stated_precision`` is half a unit of the last
printed digit, times the scale. An integer with no scale is the one exception: the deck
gives no rounding hint, so the row gets no precision at all.
"""

from decimal import Decimal

import pytest
from hypothesis import assume, given
from hypothesis import strategies as st

from fact_ledger.domain.extraction import parse_figure
from fact_ledger.domain.rules import SCALE_MULTIPLIERS

pytestmark = pytest.mark.property


@given(
    integer=st.integers(min_value=0, max_value=999999),
    decimals=st.integers(min_value=0, max_value=3),
    fraction=st.integers(min_value=0, max_value=999),
    scale=st.sampled_from(("", "k", "m", "bn")),
)
def test_stated_precision_is_half_a_unit_of_the_last_printed_digit(
    integer: int, decimals: int, fraction: int, scale: str
) -> None:
    fraction %= 10**decimals if decimals else 1
    assume(decimals != 3 or scale)  # "7.450" with no scale letter stops: a thousands mark?
    printed = f"{integer}.{fraction:0{decimals}d}{scale}" if decimals else f"{integer}{scale}"

    _value, precision = parse_figure(printed, scale, "count")

    if decimals == 0 and scale == "":
        assert precision is None  # no scale and no decimal point: no rounding hint at all
    else:
        half_a_unit = Decimal(1).scaleb(-decimals) / 2
        assert precision == half_a_unit * SCALE_MULTIPLIERS[scale]
