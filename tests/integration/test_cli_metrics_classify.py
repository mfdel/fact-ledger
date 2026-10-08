"""Acceptance tests for ``fact-ledger metrics map`` and ``metrics add`` (S1-07).

``run_rate_revenue`` is undefined in ``data/dictionary/metrics.yaml``; ``arr``, ``arr_run_rate``
and the umbrella ``revenue_unspecified`` already exist there.
"""

from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from fact_ledger.cli import app
from fact_ledger.domain import Observation
from fact_ledger.store.facts import FactStore
from fact_ledger.store.yaml_files import load_dictionary
from tests.factories import valid_observation_fields

pytestmark = pytest.mark.integration


def _observation(**overrides: Any) -> Observation:
    return Observation(**{**valid_observation_fields(), **overrides})


def _metrics_bytes(cli_env: Path) -> bytes:
    return (cli_env / "metrics.yaml").read_bytes()


# ---------------------------------------------------------------- metrics map


def test_map_moves_observations_keeps_their_fields_and_adds_the_aliases(
    cli_env: Path, store: FactStore
) -> None:
    moved = [
        _observation(
            observation_id="rr-1",
            metric_id="run_rate_revenue",
            stated_label="Run rate (deck)",
            value=Decimal(1000000),
            origin_id="acme-management",
            locator="p10",
        ),
        _observation(
            observation_id="rr-2",
            metric_id="run_rate_revenue",
            stated_label="Run rate (deck)",
            value=Decimal(2000000),
            locator="p11",
        ),
        _observation(
            observation_id="rr-3",
            metric_id="run_rate_revenue",
            stated_label="LTM x12 revenue",
            value=Decimal(3000000),
            locator="p12",
        ),
    ]
    store.add_many(moved)

    result = CliRunner().invoke(app, ["metrics", "map", "run_rate_revenue", "--to", "arr_run_rate"])

    assert result.exit_code == 0
    for original in moved:
        loaded = store.get(original.observation_id)
        assert loaded is not None
        assert loaded.metric_id == "arr_run_rate"
        assert loaded.stated_label == original.stated_label
        assert loaded.value == original.value
        assert loaded.origin_id == original.origin_id
        assert loaded.locator == original.locator

    dictionary = load_dictionary(cli_env)
    arr_run_rate = next(m for m in dictionary.metrics if m.metric_id == "arr_run_rate")
    assert "Run rate (deck)" in arr_run_rate.aliases
    assert "LTM x12 revenue" in arr_run_rate.aliases


def test_map_target_not_a_dictionary_metric_fails_and_changes_nothing(
    cli_env: Path, store: FactStore
) -> None:
    observation = _observation(metric_id="run_rate_revenue")
    store.add_many([observation])
    before = _metrics_bytes(cli_env)

    result = CliRunner().invoke(
        app, ["metrics", "map", "run_rate_revenue", "--to", "not_a_real_metric"]
    )

    assert result.exit_code == 1
    assert "not_a_real_metric" in result.stderr
    loaded = store.get(observation.observation_id)
    assert loaded is not None
    assert loaded.metric_id == "run_rate_revenue"
    assert _metrics_bytes(cli_env) == before


def test_map_source_that_is_already_a_dictionary_metric_fails_and_changes_nothing(
    cli_env: Path, store: FactStore
) -> None:
    observation = _observation(metric_id="arr")
    store.add_many([observation])
    before = _metrics_bytes(cli_env)

    result = CliRunner().invoke(app, ["metrics", "map", "arr", "--to", "arr_run_rate"])

    assert result.exit_code == 1
    assert "arr" in result.stderr
    loaded = store.get(observation.observation_id)
    assert loaded is not None
    assert loaded.metric_id == "arr"
    assert _metrics_bytes(cli_env) == before


def test_map_label_already_owned_by_a_different_metric_fails_and_names_both_ids(
    cli_env: Path, store: FactStore
) -> None:
    # "ARR" is already an alias of "arr" (data/dictionary/metrics.yaml).
    observation = _observation(metric_id="run_rate_revenue", stated_label="ARR")
    store.add_many([observation])
    before = _metrics_bytes(cli_env)

    result = CliRunner().invoke(app, ["metrics", "map", "run_rate_revenue", "--to", "arr_run_rate"])

    assert result.exit_code == 1
    assert "arr" in result.stderr
    assert "arr_run_rate" in result.stderr
    loaded = store.get(observation.observation_id)
    assert loaded is not None
    assert loaded.metric_id == "run_rate_revenue"
    assert _metrics_bytes(cli_env) == before


def test_map_into_an_umbrella_id_keeps_the_row_ambiguous(cli_env: Path, store: FactStore) -> None:
    ambiguous = _observation(
        metric_id="run_rate_revenue",
        stated_label="revenue",
        definition_status="ambiguous",
        candidate_metric_ids=("arr",),
    )
    store.add_many([ambiguous])

    result = CliRunner().invoke(
        app, ["metrics", "map", "run_rate_revenue", "--to", "revenue_unspecified"]
    )

    assert result.exit_code == 0
    loaded = store.get(ambiguous.observation_id)
    assert loaded is not None
    assert loaded.metric_id == "revenue_unspecified"
    assert loaded.definition_status == "ambiguous"  # mapping never resolves an ambiguity
    assert loaded.candidate_metric_ids == ("arr",)


def test_map_target_already_a_candidate_fails_names_the_row_and_changes_nothing(
    cli_env: Path, store: FactStore
) -> None:
    ambiguous = _observation(
        observation_id="obs-conflict",
        metric_id="run_rate_revenue",
        stated_label="revenue",
        definition_status="ambiguous",
        candidate_metric_ids=("arr_run_rate", "mrr"),
    )
    store.add_many([ambiguous])
    before = _metrics_bytes(cli_env)

    result = CliRunner().invoke(app, ["metrics", "map", "run_rate_revenue", "--to", "arr_run_rate"])

    # Validate every remapped row in memory before the
    # YAML write, so this failure changes neither file nor database.
    assert result.exit_code == 1
    assert "obs-conflict" in result.stderr
    assert store.get("obs-conflict") == ambiguous
    assert _metrics_bytes(cli_env) == before


def test_map_moves_a_candidate_only_row_but_takes_no_alias_from_it(
    cli_env: Path, store: FactStore
) -> None:
    resolved = _observation(
        observation_id="rr-1", metric_id="run_rate_revenue", stated_label="Run rate (deck)"
    )
    candidate_only = _observation(
        observation_id="amb-1",
        metric_id="revenue_unspecified",
        stated_label="Q4 booked amount",
        definition_status="ambiguous",
        candidate_metric_ids=("run_rate_revenue", "arr"),
    )
    store.add_many([resolved, candidate_only])

    result = CliRunner().invoke(app, ["metrics", "map", "run_rate_revenue", "--to", "arr_run_rate"])

    assert result.exit_code == 0
    moved = store.get("amb-1")
    assert moved is not None
    assert moved.candidate_metric_ids == ("arr_run_rate", "arr")
    assert moved.definition_status == "ambiguous"
    dictionary = load_dictionary(cli_env)
    assert dictionary.alias_owner("Run rate (deck)") == "arr_run_rate"
    assert dictionary.alias_owner("Q4 booked amount") is None


# ---------------------------------------------------------------- metrics add


def test_add_creates_a_metric_from_stored_labels_and_removes_it_from_undefined(
    cli_env: Path, store: FactStore
) -> None:
    store.add_many(
        [
            _observation(
                observation_id="pc-1",
                metric_id="pipeline_coverage",
                stated_label="Pipeline coverage",
            ),
            _observation(
                observation_id="pc-2",
                entity_id="beta",
                metric_id="pipeline_coverage",
                stated_label="Pipeline coverage",
            ),
            _observation(
                observation_id="pc-3",
                metric_id="pipeline_coverage",
                stated_label="Pipeline coverage ratio",
            ),
        ]
    )
    before_undefined = CliRunner().invoke(app, ["metrics", "undefined"])
    assert "pipeline_coverage" in before_undefined.stdout

    result = CliRunner().invoke(
        app,
        [
            "metrics",
            "add",
            "pipeline_coverage",
            "--name",
            "Pipeline coverage",
            "--dimension",
            "ratio",
            "--stock-or-flow",
            "stock",
        ],
    )

    assert result.exit_code == 0
    dictionary = load_dictionary(cli_env)
    added = next(m for m in dictionary.metrics if m.metric_id == "pipeline_coverage")
    assert added.canonical_name == "Pipeline coverage"
    assert added.dimension == "ratio"
    assert added.stock_or_flow == "stock"
    assert set(added.aliases) == {"Pipeline coverage", "Pipeline coverage ratio"}

    after_undefined = CliRunner().invoke(app, ["metrics", "undefined"])
    assert "pipeline_coverage" not in after_undefined.stdout
    kept = store.get("pc-1")
    assert kept is not None
    assert kept.metric_id == "pipeline_coverage"  # the database does not change


def test_add_takes_no_alias_from_an_ambiguous_row(cli_env: Path, store: FactStore) -> None:
    store.add_many(
        [
            _observation(
                observation_id="pc-1", metric_id="pipeline_coverage", stated_label="Pipeline cover"
            ),
            _observation(
                observation_id="amb-1",
                metric_id="revenue_unspecified",
                stated_label="Q4 booked amount",
                definition_status="ambiguous",
                candidate_metric_ids=("pipeline_coverage", "arr"),
            ),
        ]
    )

    result = CliRunner().invoke(
        app,
        [
            "metrics",
            "add",
            "pipeline_coverage",
            "--name",
            "Pipeline coverage",
            "--dimension",
            "ratio",
            "--stock-or-flow",
            "stock",
        ],
    )

    assert result.exit_code == 0
    dictionary = load_dictionary(cli_env)
    added = next(m for m in dictionary.metrics if m.metric_id == "pipeline_coverage")
    assert added.aliases == ("Pipeline cover",)


def test_add_fails_when_the_id_is_already_a_dictionary_metric(cli_env: Path) -> None:
    before = _metrics_bytes(cli_env)

    result = CliRunner().invoke(
        app,
        [
            "metrics",
            "add",
            "arr",
            "--name",
            "x",
            "--dimension",
            "currency",
            "--stock-or-flow",
            "stock",
        ],
    )

    assert result.exit_code == 1
    assert "arr" in result.stderr
    assert _metrics_bytes(cli_env) == before


def test_add_with_an_invalid_metric_id_fails_without_a_traceback(cli_env: Path) -> None:
    before = _metrics_bytes(cli_env)

    result = CliRunner().invoke(
        app,
        [
            "metrics",
            "add",
            "Bad-Id",
            "--name",
            "x",
            "--dimension",
            "ratio",
            "--stock-or-flow",
            "stock",
        ],
    )

    assert result.exit_code == 1
    assert "metric_id" in result.stderr
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert _metrics_bytes(cli_env) == before


def test_add_with_no_stored_observations_creates_a_metric_with_no_aliases(
    cli_env: Path,
) -> None:
    result = CliRunner().invoke(
        app,
        [
            "metrics",
            "add",
            "widget_count",
            "--name",
            "Widget count",
            "--dimension",
            "count",
            "--stock-or-flow",
            "stock",
        ],
    )

    assert result.exit_code == 0
    dictionary = load_dictionary(cli_env)
    added = next(m for m in dictionary.metrics if m.metric_id == "widget_count")
    assert added.aliases == ()
