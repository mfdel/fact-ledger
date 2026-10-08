"""Drift guard: the observations table and the Observation model must list the same fields.

Mapping by column name has one risk: the table and the model
drift apart. This test would fail the day someone adds a field to one and not the other.
"""

import pytest

from fact_ledger.domain import Observation
from fact_ledger.store.facts import observations

pytestmark = pytest.mark.unit


def test_table_columns_match_observation_fields_exactly() -> None:
    assert set(Observation.model_fields) == set(observations.c.keys())
