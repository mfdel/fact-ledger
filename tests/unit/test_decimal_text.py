"""DecimalText converts Decimal to exact text and back."""

from decimal import Decimal

import pytest
from sqlalchemy.dialects import sqlite

from fact_ledger.store.facts import DecimalText

pytestmark = pytest.mark.unit

_DIALECT = sqlite.dialect()
_COLUMN_TYPE = DecimalText()


def test_bind_keeps_exact_digits() -> None:
    assert _COLUMN_TYPE.process_bind_param(Decimal("8.30"), _DIALECT) == "8.30"


def test_result_restores_the_decimal() -> None:
    assert _COLUMN_TYPE.process_result_value("8.30", _DIALECT) == Decimal("8.30")


def test_none_round_trips_to_none() -> None:
    assert _COLUMN_TYPE.process_bind_param(None, _DIALECT) is None
    assert _COLUMN_TYPE.process_result_value(None, _DIALECT) is None
