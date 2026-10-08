import pytest
from typer.testing import CliRunner

from fact_ledger import __version__
from fact_ledger.cli import app

pytestmark = pytest.mark.unit


def test_version_command_prints_version() -> None:
    result = CliRunner().invoke(app, ["version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == __version__
