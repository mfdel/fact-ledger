"""Acceptance tests for ``fact-ledger metrics undefined`` (S1-03).

A tmp copy of ``data/dictionary`` protects the real files: one test appends a metric to it.
"""

from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner

from fact_ledger.cli import app
from fact_ledger.domain import Observation
from fact_ledger.store.facts import FactStore
from tests.factories import valid_observation_fields

pytestmark = pytest.mark.integration


def _observation(**overrides: Any) -> Observation:
    return Observation(**{**valid_observation_fields(), **overrides})


def _row(stdout: str, metric_id: str) -> list[str]:
    (line,) = (row for row in stdout.splitlines()[1:] if row.split("\t")[0] == metric_id)
    return line.split("\t")


def test_no_undefined_metrics_prints_message_and_exits_zero(cli_env: Path) -> None:
    result = CliRunner().invoke(app, ["metrics", "undefined"])
    assert result.exit_code == 0
    assert result.stdout.strip() == "No undefined metrics."


def test_two_undefined_metric_ids_are_each_listed_once_with_counts_entities_and_labels(
    store: FactStore,
) -> None:
    store.add_many(
        [
            _observation(
                observation_id="o1",
                entity_id="acme",
                metric_id="pipeline_coverage",
                stated_label="Pipeline coverage",
            ),
            _observation(
                observation_id="o2",
                entity_id="beta",
                metric_id="pipeline_coverage",
                stated_label="Pipeline coverage",  # same label: stated_labels stays distinct
            ),
            _observation(
                observation_id="o3",
                entity_id="acme",
                metric_id="net_new_arr_per_rep",
                stated_label="Net new ARR per rep",
            ),
        ]
    )

    result = CliRunner().invoke(app, ["metrics", "undefined"])

    assert result.exit_code == 0
    lines = result.stdout.splitlines()
    assert len(lines) == 3
    header, *data_rows = lines
    assert len(header.split("\t")) == 5
    assert [row.split("\t")[0] for row in data_rows] == [
        "net_new_arr_per_rep",  # sorted before pipeline_coverage
        "pipeline_coverage",
    ]

    pipeline_row = _row(result.stdout, "pipeline_coverage")
    assert pipeline_row[1] == "2"
    assert "acme" in pipeline_row[2]
    assert "beta" in pipeline_row[2]
    assert "Pipeline coverage" in pipeline_row[3]

    single_row = _row(result.stdout, "net_new_arr_per_rep")
    assert single_row[1] == "1"


def test_a_tab_or_line_break_in_a_label_is_escaped_so_each_metric_stays_one_row(
    store: FactStore,
) -> None:
    store.add_many(
        [_observation(metric_id="pipeline_coverage", stated_label="Pipeline\tcoverage\nQ4")]
    )

    result = CliRunner().invoke(app, ["metrics", "undefined"])

    assert result.exit_code == 0
    _header, row = result.stdout.splitlines()
    assert row.split("\t") == ["pipeline_coverage", "1", "acme", "Pipeline\\tcoverage\\nQ4", ""]


def test_a_stated_label_matching_a_dictionary_alias_is_suggested_but_not_applied(
    store: FactStore,
) -> None:
    # "ARR" is a literal alias of the dictionary metric "arr" (data/dictionary/metrics.yaml).
    observation = _observation(metric_id="pipeline_coverage", stated_label="ARR")
    store.add_many([observation])

    result = CliRunner().invoke(app, ["metrics", "undefined"])

    assert result.exit_code == 0
    row = _row(result.stdout, "pipeline_coverage")
    assert "arr" in row[4]
    loaded = store.get(observation.observation_id)
    assert loaded is not None
    assert loaded.metric_id == "pipeline_coverage"  # the suggestion is not applied


def test_adding_the_metric_to_the_dictionary_removes_it_and_leaves_observations_unchanged(
    cli_env: Path, store: FactStore
) -> None:
    observation = _observation(metric_id="pipeline_coverage", stated_label="Pipeline coverage")
    store.add_many([observation])
    before = CliRunner().invoke(app, ["metrics", "undefined"])
    assert "pipeline_coverage" in before.stdout

    metrics_file = cli_env / "metrics.yaml"
    data = yaml.safe_load(metrics_file.read_text())
    data["metrics"].append(
        {
            "metric_id": "pipeline_coverage",
            "canonical_name": "Pipeline coverage ratio",
            "aliases": ["Pipeline coverage"],
            "dimension": "ratio",
            "stock_or_flow": "flow",
        }
    )
    metrics_file.write_text(yaml.safe_dump(data, sort_keys=False))

    after = CliRunner().invoke(app, ["metrics", "undefined"])

    assert after.exit_code == 0
    assert "pipeline_coverage" not in after.stdout
    assert store.get(observation.observation_id) == observation
