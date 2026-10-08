"""``write_transcript`` writes what ``read_transcript`` reads back, unedited: the
"``facts load`` with no edit" criterion (S1-06 precedent, S3-01 criterion 6).
"""

from datetime import date
from pathlib import Path

import pytest

from fact_ledger.domain import DefinitionStatus, Observation
from fact_ledger.store.yaml_files import read_transcript, write_transcript
from tests.factories import valid_observation_fields

pytestmark = pytest.mark.unit

_DEFAULTS = {
    "entity_id": "acme",
    "origin_id": "acme-management",
    "document_id": "deck-2025",
    "source_type": "deck",
    "reliability": 4,
    "published_date": date(2025, 3, 1),
}


def test_a_resolved_and_an_ambiguous_row_round_trip_to_equal_observations(tmp_path: Path) -> None:
    fields = valid_observation_fields()
    # One date object in two fields, as extract_deck sets it: no YAML anchor may tie them.
    resolved = Observation(**fields | {"as_of_date": fields["period_end"]})
    ambiguous = Observation(
        **(
            valid_observation_fields()
            | {
                "observation_id": "obs-2",
                "metric_id": "revenue_unspecified",
                "stated_label": "Revenue",
                "definition_status": DefinitionStatus.AMBIGUOUS,
                "candidate_metric_ids": ("revenue_recognised", "arr"),
            }
        )
    )
    path = tmp_path / "transcript.yaml"

    write_transcript(
        path,
        "deck.pdf, extract_deck_v7.md. Not reviewed.",
        _DEFAULTS,
        [(resolved, "~€8m"), (ambiguous, "€4.7m")],
    )

    assert read_transcript(path) == [resolved, ambiguous]
    assert "&" not in path.read_text(encoding="utf-8")


def test_the_header_is_written_as_leading_comment_lines(tmp_path: Path) -> None:
    path = tmp_path / "transcript.yaml"
    resolved = Observation(**valid_observation_fields())

    write_transcript(
        path,
        "nimbus-pdf-2025.pdf, extract_deck_v7.md. Not reviewed.",
        _DEFAULTS,
        [(resolved, "~€8m")],
    )

    lines = path.read_text().splitlines()
    header_lines = [line for line in lines if line.startswith("#")]
    assert any("nimbus-pdf-2025.pdf" in line for line in header_lines)
    assert any("Not reviewed" in line for line in header_lines)
