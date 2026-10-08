"""Command-line entry point: ``fact-ledger``.

The app and its sub-apps live here so that ``cli/facts.py`` and ``cli/metrics.py`` can
register their commands on them by decorator (S3 CLI split).
"""

from collections.abc import Iterable
from typing import NoReturn

import typer
import uvicorn

from fact_ledger import __version__
from fact_ledger.domain import Dictionary
from fact_ledger.settings import get_settings
from fact_ledger.store.db import make_engine
from fact_ledger.store.facts import FactStore
from fact_ledger.store.yaml_files import load_dictionary

app = typer.Typer(help="Fact Ledger command-line tools.", no_args_is_help=True)
metrics_app = typer.Typer(help="Metric dictionary commands.")
facts_app = typer.Typer(help="Fact store commands.")
app.add_typer(metrics_app, name="metrics")
app.add_typer(facts_app, name="facts")

# TSV has no quoting. A tab or a line break in a stated label would split its row, so
# escape them the way Postgres COPY text format does.
_TSV_ESCAPES = str.maketrans({"\\": "\\\\", "\t": "\\t", "\n": "\\n", "\r": "\\r"})


@app.command()
def serve(host: str = "127.0.0.1", port: int = 8000, reload: bool = False) -> None:
    """Run the web service."""
    uvicorn.run("fact_ledger.app:create_app", factory=True, host=host, port=port, reload=reload)


@app.command()
def version() -> None:
    """Print the package version."""
    typer.echo(__version__)


def _open() -> tuple[FactStore, Dictionary]:
    """Build the store and dictionary from settings. Run ``make migrate`` first."""
    settings = get_settings()
    dictionary = load_dictionary(settings.dictionary_dir)
    engine = make_engine(settings.database_url)
    return FactStore(engine, identity_ids=dictionary.identity_ids), dictionary


def _print_row(fields: Iterable[str]) -> None:
    typer.echo("\t".join(field.translate(_TSV_ESCAPES) for field in fields))


def _fail(message: str) -> NoReturn:
    typer.echo(message, err=True)
    raise typer.Exit(1)


# Registers the ``metrics``, ``facts``, ``validate`` and ``brief`` commands as a side
# effect of the import. Must come after the app, sub-apps and shared helpers above,
# which these modules import back from this package.
from fact_ledger.cli import brief as brief  # noqa: E402
from fact_ledger.cli import extract as extract  # noqa: E402
from fact_ledger.cli import facts as facts  # noqa: E402
from fact_ledger.cli import metrics as metrics  # noqa: E402
