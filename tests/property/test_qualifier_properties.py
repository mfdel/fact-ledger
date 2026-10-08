"""S3-12, criterion 3. A row that states no
segment, no region and no basis is a group row on the reported basis: every S1, S2 and S3 row
today. ``qualifier_of`` must give it ``Qualifier()``, the same key those rows have today,
whatever its metric, value or period. This is what keeps every existing fixture's report
unchanged ("Steps 1 to 4 change no expected result").

This property test proves ``qualifier_of`` returns the default ``Qualifier()`` for any metric,
value and period when the row states no segment, region or basis.
"""

from datetime import date
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from fact_ledger.domain.models import Observation, Qualifier
from fact_ledger.domain.paths import qualifier_of
from tests.factories import valid_observation_fields

pytestmark = pytest.mark.property

_METRIC_IDS = ("arr", "mrr", "revenue_recognised", "gross_profit")
_VALUES = st.decimals(
    min_value=Decimal("0.01"),
    max_value=Decimal(10**9),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)
_DATES = st.dates(min_value=date(1990, 1, 1), max_value=date(2040, 12, 31))


@given(metric_id=st.sampled_from(_METRIC_IDS), value=_VALUES, period_end=_DATES)
def test_a_row_with_no_stated_qualifier_gives_the_default_qualifier(
    metric_id: str, value: Decimal, period_end: date
) -> None:
    fields = {
        **valid_observation_fields(),
        "metric_id": metric_id,
        "value": value,
        "period_start": period_end,
        "period_end": period_end,
        "as_of_date": period_end,
    }
    observation = Observation(**fields)

    assert qualifier_of(observation) == Qualifier()
