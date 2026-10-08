from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fact_ledger import __version__
from fact_ledger.app import create_app
from fact_ledger.settings import Settings

pytestmark = pytest.mark.integration


def test_health_reports_ok(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


def test_health_reports_degraded_when_database_is_unreachable(tmp_path: Path) -> None:
    unreachable = f"sqlite:///{tmp_path / 'missing-dir' / 'db.sqlite'}"
    with TestClient(create_app(Settings(env="test", database_url=unreachable))) as client:
        response = client.get("/health")
    assert response.status_code == 503
    assert response.json() == {"status": "degraded", "database": "unavailable"}


def test_version(client: TestClient) -> None:
    assert client.get("/version").json() == {"version": __version__}


def test_index_page_renders_with_htmx(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "htmx.org" in response.text
    assert 'hx-get="/health"' in response.text
