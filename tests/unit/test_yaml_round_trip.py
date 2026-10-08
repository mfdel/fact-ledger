"""The ruamel.yaml round-trip settings must reproduce data/dictionary/ byte for byte.

A CLI write to metrics.yaml or identities.yaml uses these same settings.
A load-then-dump that changes one byte turns every CLI
write into a noisy diff, so this test runs before any write code does.
"""

import io
from pathlib import Path

import pytest

from fact_ledger.store.yaml_files import _yaml_rt

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]
DICTIONARY_DIR = ROOT / "data" / "dictionary"


def _round_trip(path: Path) -> bytes:
    buffer = io.BytesIO()
    _yaml_rt.dump(_yaml_rt.load(path), buffer)
    return buffer.getvalue()


def test_metrics_yaml_round_trips_byte_identical() -> None:
    path = DICTIONARY_DIR / "metrics.yaml"
    assert _round_trip(path) == path.read_bytes()


def test_identities_yaml_round_trips_byte_identical() -> None:
    path = DICTIONARY_DIR / "identities.yaml"
    assert _round_trip(path) == path.read_bytes()
