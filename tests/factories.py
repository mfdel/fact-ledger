"""Test data builders. Plain functions, so hypothesis tests can call them too."""

from datetime import date
from decimal import Decimal
from typing import Any

from fact_ledger.domain import Dimension, Metric, StockOrFlow


def make_metric(metric_id: str, aliases: tuple[str, ...] = ()) -> Metric:
    """A dictionary Metric with fixed dimension and stock_or_flow. Tests vary id and aliases."""
    return Metric(
        metric_id=metric_id,
        canonical_name=metric_id,
        aliases=aliases,
        dimension=Dimension.CURRENCY,
        stock_or_flow=StockOrFlow.STOCK,
    )


def valid_observation_fields() -> dict[str, Any]:
    """A valid Observation as keyword arguments. Tests override single fields."""
    return {
        "observation_id": "obs-1",
        "entity_id": "acme",
        "metric_id": "arr",
        "value": Decimal(8000000),
        "unit": "EUR",
        "currency": "EUR",
        "stated_precision": Decimal(500000),
        "period_start": date(2024, 12, 31),
        "period_end": date(2024, 12, 31),
        "period_type": "point_in_time",
        "as_of_date": date(2024, 12, 31),
        "published_date": date(2025, 3, 1),
        "origin_id": "acme-management",
        "document_id": "deck-2025",
        "locator": "deck.pdf#p4",
        "source_type": "deck",
        "reliability": 4,
        "bias_direction": "up",
        "stated_label": "ARR",
    }
