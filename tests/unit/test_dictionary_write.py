"""Acceptance tests for dictionary writes (S1-07): ``add_aliases`` and ``add_metric``.

Every test copies ``data/dictionary`` to ``tmp_path`` first;
the real files are never opened for writing.
"""

import shutil
from pathlib import Path

import pytest

from fact_ledger.domain import Dimension, Metric, StockOrFlow
from fact_ledger.store.yaml_files import add_aliases, add_metric, load_dictionary

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]
REAL_DICTIONARY_DIR = ROOT / "data" / "dictionary"


@pytest.fixture
def dictionary_dir(tmp_path: Path) -> Path:
    target = tmp_path / "dictionary"
    shutil.copytree(REAL_DICTIONARY_DIR, target)
    return target


def test_add_aliases_appends_a_new_label_and_skips_one_already_present(
    dictionary_dir: Path,
) -> None:
    add_aliases(dictionary_dir, "billings", ["Amounts billed", "Billings"])

    dictionary = load_dictionary(dictionary_dir)
    billings = next(m for m in dictionary.metrics if m.metric_id == "billings")
    assert "Amounts billed" in billings.aliases
    casefolded = [alias.casefold() for alias in billings.aliases]
    assert casefolded.count("billings") == 1  # "Billings" already present as "billings"


def test_add_aliases_with_a_label_owned_by_another_metric_fails_and_changes_nothing(
    dictionary_dir: Path,
) -> None:
    metrics_file = dictionary_dir / "metrics.yaml"
    before = metrics_file.read_bytes()

    with pytest.raises(ValueError, match="arr"):
        add_aliases(dictionary_dir, "mrr", ["ARR"])  # "ARR" is already an alias of "arr"

    assert metrics_file.read_bytes() == before


def test_add_metric_appends_a_new_metric_with_its_aliases(dictionary_dir: Path) -> None:
    metric = Metric(
        metric_id="pipeline_coverage",
        canonical_name="Pipeline coverage",
        aliases=("Pipeline coverage",),
        dimension=Dimension.RATIO,
        stock_or_flow=StockOrFlow.STOCK,
    )
    add_metric(dictionary_dir, metric)

    dictionary = load_dictionary(dictionary_dir)
    assert "pipeline_coverage" in dictionary.metric_ids
    added = next(m for m in dictionary.metrics if m.metric_id == "pipeline_coverage")
    assert added.aliases == ("Pipeline coverage",)


def test_add_metric_with_a_duplicate_id_fails_and_changes_nothing(dictionary_dir: Path) -> None:
    metrics_file = dictionary_dir / "metrics.yaml"
    before = metrics_file.read_bytes()
    metric = Metric(
        metric_id="arr",
        canonical_name="Duplicate",
        dimension=Dimension.CURRENCY,
        stock_or_flow=StockOrFlow.STOCK,
    )

    with pytest.raises(ValueError, match="arr"):
        add_metric(dictionary_dir, metric)

    assert metrics_file.read_bytes() == before


def test_add_metric_leaves_no_temporary_file_behind(dictionary_dir: Path) -> None:
    metric = Metric(
        metric_id="widget_count",
        canonical_name="Widget count",
        dimension=Dimension.COUNT,
        stock_or_flow=StockOrFlow.STOCK,
    )
    add_metric(dictionary_dir, metric)

    assert sorted(p.name for p in dictionary_dir.iterdir()) == ["identities.yaml", "metrics.yaml"]
