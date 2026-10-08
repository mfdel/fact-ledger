"""CLI-level regression lock for ``Dictionary.undefined_metrics`` label handling.

Moved from ``tests/unit/test_undefined_metrics_labels.py`` (S1-06
fixture cleanup): this test is DB-backed, so it belongs with the other
``facts``/``metrics`` CLI integration tests, not in ``tests/unit``.
"""

from typing import Any

import pytest
from typer.testing import CliRunner

from fact_ledger.cli import app
from fact_ledger.domain import Observation
from fact_ledger.store.facts import FactStore
from tests.factories import valid_observation_fields

pytestmark = pytest.mark.integration


def _observation(**overrides: Any) -> Observation:
    return Observation(**{**valid_observation_fields(), **overrides})


def test_cli_output_joins_multiple_entity_ids_with_comma_space(store: FactStore) -> None:
    store.add_many(
        [
            _observation(observation_id="o1", entity_id="acme", metric_id="pipeline_coverage"),
            _observation(observation_id="o2", entity_id="beta", metric_id="pipeline_coverage"),
        ]
    )

    result = CliRunner().invoke(app, ["metrics", "undefined"])

    assert result.exit_code == 0
    (line,) = (
        row for row in result.stdout.splitlines()[1:] if row.split("\t")[0] == "pipeline_coverage"
    )
    assert line.split("\t")[2] == "acme, beta"
