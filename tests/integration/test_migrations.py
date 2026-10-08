from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, inspect

from fact_ledger.settings import get_settings

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[2]


def test_upgrade_and_downgrade_run_cleanly(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FACT_LEDGER_DATABASE_URL", f"sqlite:///{tmp_path / 'm.db'}")
    get_settings.cache_clear()
    config = Config(ROOT / "alembic.ini")
    try:
        command.upgrade(config, "head")
        command.downgrade(config, "base")
    finally:
        get_settings.cache_clear()


def test_upgrade_creates_the_observations_table_its_index_and_metric_id_changes(
    migrated_engine: Engine,
) -> None:
    inspector = inspect(migrated_engine)
    table_names = set(inspector.get_table_names())

    assert "observations" in table_names
    assert "metric_id_changes" in table_names

    index_names = {index["name"] for index in inspector.get_indexes("observations")}
    assert "ix_observations_entity_metric_period" in index_names
