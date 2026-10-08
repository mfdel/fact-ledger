import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine

from fact_ledger.settings import get_settings
from fact_ledger.store.db import make_engine
from fact_ledger.store.facts import FactStore
from fact_ledger.store.yaml_files import load_dictionary

ROOT = Path(__file__).resolve().parents[2]
REAL_DICTIONARY_DIR = ROOT / "data" / "dictionary"


@pytest.fixture
def migrated_engine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Engine]:
    """A SQLite engine built by the real Alembic migration.

    metadata.create_all would hide a broken migration. Fact-store tests must run against
    the same schema alembic produces in production.
    """
    monkeypatch.setenv("FACT_LEDGER_DATABASE_URL", f"sqlite:///{tmp_path / 'facts.db'}")
    get_settings.cache_clear()
    engine = None
    try:
        command.upgrade(Config(ROOT / "alembic.ini"), "head")
        engine = make_engine(get_settings().database_url)
        yield engine
    finally:
        if engine is not None:
            engine.dispose()
        get_settings.cache_clear()


@pytest.fixture
def cli_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """A CLI environment: a tmp copy of the real dictionary and a migrated tmp database.

    Shared by every ``facts``/``metrics`` CLI test module, so one setup change does not
    have to be repeated in each of them.
    """
    dictionary_dir = tmp_path / "dictionary"
    shutil.copytree(REAL_DICTIONARY_DIR, dictionary_dir)
    monkeypatch.setenv("FACT_LEDGER_DATABASE_URL", f"sqlite:///{tmp_path / 'cli.db'}")
    monkeypatch.setenv("FACT_LEDGER_DICTIONARY_DIR", str(dictionary_dir))
    get_settings.cache_clear()
    try:
        command.upgrade(Config(ROOT / "alembic.ini"), "head")
        yield dictionary_dir
    finally:
        get_settings.cache_clear()


@pytest.fixture
def store(cli_env: Path) -> Iterator[FactStore]:
    """A ``FactStore`` bound to the ``cli_env`` database, for tests to seed or read directly."""
    dictionary = load_dictionary(cli_env)
    engine = make_engine(get_settings().database_url)
    try:
        yield FactStore(engine, identity_ids=dictionary.identity_ids)
    finally:
        engine.dispose()
