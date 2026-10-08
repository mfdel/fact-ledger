from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from fact_ledger.app import create_app
from fact_ledger.settings import Settings
from tests.factories import valid_observation_fields


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(env="test", database_url=f"sqlite:///{tmp_path / 'test.db'}")


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as test_client:
        yield test_client


@pytest.fixture
def observation_fields() -> dict[str, Any]:
    return valid_observation_fields()
