"""``read_transcript`` merge behaviour (S1-06).

CLI-level acceptance tests live in ``tests/integration/test_cli_facts_load.py``.
"""

from pathlib import Path
from typing import Any

import pytest
import yaml

from fact_ledger.domain import Observation
from fact_ledger.store.yaml_files import read_transcript

pytestmark = pytest.mark.unit


def _write(path: Path, defaults: dict[str, Any], rows: list[dict[str, Any]]) -> Path:
    path.write_text(yaml.safe_dump({"defaults": defaults, "observations": rows}, sort_keys=False))
    return path


def test_a_row_field_missing_from_the_row_is_filled_from_defaults(tmp_path: Path) -> None:
    defaults = {
        "entity_id": "acme",
        "origin_id": "acme-management",
        "document_id": "acme-deck-2025",
        "source_type": "deck",
        "reliability": 4,
        "bias_direction": "up",
        "published_date": "2025-01-01",
        "unit": "EUR",
        "currency": "EUR",
    }
    row = {
        "observation_id": "acme-1",
        "metric_id": "arr",
        "value": "1000000",
        "period_start": "2024-12-31",
        "period_end": "2024-12-31",
        "period_type": "point_in_time",
        "as_of_date": "2024-12-31",
        "locator": "p1",
        "stated_label": "ARR",
    }
    transcript = _write(tmp_path / "transcript.yaml", defaults, [row])

    (observation,) = read_transcript(transcript)

    assert isinstance(observation, Observation)
    assert observation.entity_id == "acme"  # taken from defaults
    assert observation.origin_id == "acme-management"  # taken from defaults


def test_a_row_field_present_in_both_row_and_defaults_takes_the_row_value(tmp_path: Path) -> None:
    defaults = {
        "entity_id": "acme",
        "origin_id": "acme-management",
        "document_id": "acme-deck-2025",
        "source_type": "deck",
        "reliability": 3,
        "bias_direction": "up",
        "published_date": "2025-01-01",
        "unit": "EUR",
        "currency": "EUR",
    }
    row = {
        "observation_id": "acme-1",
        "metric_id": "arr",
        "value": "1000000",
        "reliability": 5,  # overrides the defaults value of 3
        "period_start": "2024-12-31",
        "period_end": "2024-12-31",
        "period_type": "point_in_time",
        "as_of_date": "2024-12-31",
        "locator": "p1",
        "stated_label": "ARR",
    }
    transcript = _write(tmp_path / "transcript.yaml", defaults, [row])

    (observation,) = read_transcript(transcript)

    assert observation.reliability == 5


def test_every_row_error_in_a_file_is_reported_together(tmp_path: Path) -> None:
    defaults = {
        "entity_id": "acme",
        "origin_id": "acme-management",
        "document_id": "acme-deck-2025",
        "source_type": "deck",
        "reliability": 4,
        "published_date": "2025-01-01",
        "unit": "EUR",
        "period_start": "2024-12-31",
        "period_end": "2024-12-31",
        "period_type": "point_in_time",
        "as_of_date": "2024-12-31",
        "locator": "p1",
        "stated_label": "ARR",
    }
    rows: list[dict[str, Any]] = [
        {
            "observation_id": "acme-1",
            "metric_id": "arr",
            "value": "1000000",
            "stated_precision": 0.5,
        },
        {"observation_id": "acme-2", "value": "1000000"},
    ]
    transcript = _write(tmp_path / "transcript.yaml", defaults, rows)

    with pytest.raises(ValueError, match="row 1") as excinfo:
        read_transcript(transcript)

    lines = str(excinfo.value).splitlines()
    assert any("row 1" in line and "stated_precision" in line for line in lines)
    assert any("row 2" in line and "metric_id" in line for line in lines)
