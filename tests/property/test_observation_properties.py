from datetime import date, timedelta
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from fact_ledger.domain import Observation
from tests.factories import valid_observation_fields

pytestmark = pytest.mark.property

dates = st.dates(min_value=date(1990, 1, 1), max_value=date(2040, 12, 31))
lengths = st.integers(min_value=0, max_value=3650)


def _fields(start: date, end: date) -> dict[str, Any]:
    return {
        **valid_observation_fields(),
        "period_type": "fy",
        "period_start": start,
        "period_end": end,
    }


@given(start=dates, length=lengths, published=dates, as_of=dates)
def test_ordered_periods_are_accepted_for_any_publish_and_as_of_dates(
    start: date, length: int, published: date, as_of: date
) -> None:
    fields = _fields(start, start + timedelta(days=length))
    observation = Observation(**fields | {"published_date": published, "as_of_date": as_of})
    assert observation.published_date == published
    assert observation.as_of_date == as_of


@given(start=dates, length=st.integers(min_value=1, max_value=3650))
def test_reversed_periods_are_always_rejected(start: date, length: int) -> None:
    with pytest.raises(ValidationError):
        Observation(**_fields(start + timedelta(days=length), start))
