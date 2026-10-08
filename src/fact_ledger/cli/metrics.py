"""Metric dictionary commands: ``fact-ledger metrics ...``."""

from collections.abc import Iterable
from typing import Annotated

import typer

from fact_ledger.cli import _fail, _open, _print_row, metrics_app
from fact_ledger.domain import DefinitionStatus, Dimension, Metric, Observation, StockOrFlow
from fact_ledger.settings import get_settings
from fact_ledger.store.facts import FactStoreError, remap_observation
from fact_ledger.store.yaml_files import add_aliases, add_metric


@metrics_app.command("undefined")
def metrics_undefined() -> None:
    """List metric ids used by stored observations but not in the dictionary."""
    store, dictionary = _open()
    try:
        undefined = dictionary.undefined_metrics(store.find())
    finally:
        store.dispose()
    if not undefined:
        typer.echo("No undefined metrics.")
        return
    _print_row(("metric_id", "observations", "entity_ids", "stated_labels", "suggested_metric_ids"))
    for item in undefined:
        _print_row(
            (
                item.metric_id,
                str(len(item.observation_ids)),
                ", ".join(item.entity_ids),
                ", ".join(item.stated_labels),
                ", ".join(item.suggested_metric_ids),
            )
        )


def _observations_using(rows: Iterable[Observation], metric_id: str) -> list[Observation]:
    """Rows whose ``metric_id`` or ``candidate_metric_ids`` include ``metric_id``."""
    return [row for row in rows if metric_id in (row.metric_id, *row.candidate_metric_ids)]


def _alias_labels(rows: Iterable[Observation], metric_id: str) -> tuple[str, ...]:
    """Stated labels of resolved rows whose own ``metric_id`` it is.

    An ambiguous label has no single meaning. As an alias it would resolve that label for
    every later deck, so a row that is ambiguous, or uses the id only as a candidate, gives none.
    """
    return tuple(
        sorted(
            {
                row.stated_label
                for row in rows
                if row.metric_id == metric_id and row.definition_status is DefinitionStatus.RESOLVED
            }
        )
    )


@metrics_app.command("map")
def metrics_map(metric_id: str, to: Annotated[str, typer.Option("--to")]) -> None:
    """Move an undefined metric id's observations onto a dictionary metric.
    ``--to`` may be an umbrella id (``*_unspecified``); the rows stay ambiguous.
    """
    store, dictionary = _open()
    try:
        if to not in dictionary.metric_ids:
            _fail(f"{to!r} is not a dictionary metric.")
        if metric_id in dictionary.metric_ids:
            _fail(f"{metric_id!r} is already a dictionary metric; map moves undefined ids only.")

        rows = _observations_using(store.find(), metric_id)
        try:
            for row in rows:
                remap_observation(row, metric_id, to)
        except FactStoreError as error:
            _fail(str(error))

        try:
            add_aliases(get_settings().dictionary_dir, to, _alias_labels(rows, metric_id))
        except ValueError as error:
            _fail(str(error))

        changed = store.remap_metric(metric_id, to)
    finally:
        store.dispose()
    typer.echo(f"Mapped {len(changed)} observation(s) from {metric_id!r} to {to!r}.")


@metrics_app.command("add")
def metrics_add(
    metric_id: str,
    name: Annotated[str, typer.Option("--name")],
    dimension: Annotated[Dimension, typer.Option("--dimension")],
    stock_or_flow: Annotated[StockOrFlow, typer.Option("--stock-or-flow")],
) -> None:
    """Define a new dictionary metric from the stored labels of an undefined id (design
    note S1 section 7). The database does not change; the id leaves ``metrics undefined``
    because the comparison now finds it.
    """
    store, dictionary = _open()
    try:
        if metric_id in dictionary.metric_ids:
            _fail(f"{metric_id!r} is already a dictionary metric.")

        try:
            metric = Metric(
                metric_id=metric_id,
                canonical_name=name,
                aliases=_alias_labels(store.find(), metric_id),
                dimension=dimension,
                stock_or_flow=stock_or_flow,
            )
            add_metric(get_settings().dictionary_dir, metric)
        except ValueError as error:  # includes pydantic's ValidationError for a bad metric id
            _fail(str(error))
    finally:
        store.dispose()
    typer.echo(f"Added {metric_id!r} to the dictionary.")
