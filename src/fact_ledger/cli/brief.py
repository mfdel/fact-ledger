"""The analyst brief: ``fact-ledger brief`` (architecture doc section 6; S3-02, S4-03,
S5-03).
"""

from typing import Annotated

import typer

from fact_ledger.cli import _fail, _print_row, app
from fact_ledger.cli.facts import (
    _period_fields,
    _print_findings,
    _qualifier_text,
    facts_show,
    validate_entity,
)
from fact_ledger.domain import DivergenceClass, Observation, Period
from fact_ledger.domain.models import Qualifier
from fact_ledger.domain.paths import Report, metric_of
from fact_ledger.domain.patterns import expected_metrics, patterns
from fact_ledger.domain.questions import absence_question, question
from fact_ledger.settings import get_settings
from fact_ledger.store.yaml_files import load_dictionary

_CORROBORATION_HEADER = (
    "metric_id",
    "period_start",
    "period_end",
    "period_type",
    "qualifier",
    "count",
    "documents",
)


def _corroborated_facts(report: Report) -> dict[tuple[str, Period, Qualifier], list[Observation]]:
    """Group the Corroborated comparisons by fact. The rows of a
    Contested comparison of the same fact stay out: the Inconsistencies section shows them.
    """
    facts: dict[tuple[str, Period, Qualifier], dict[str, Observation]] = {}
    for comparison in report.comparisons:
        if comparison.divergence is not DivergenceClass.CORROBORATED:
            continue
        a = comparison.a
        rows = facts.setdefault((a.metric_id, a.period, a.qualifier), {})
        for row in (*a.observations, *comparison.b.observations):
            rows.setdefault(row.observation_id, row)
    return {fact: list(rows.values()) for fact, rows in facts.items()}


def _document_text(row: Observation) -> str:
    # The cited origin shows where an echo lowers the origin count, so a typo in it is visible.
    cites = f", cites {row.cited_origin_id}" if row.cited_origin_id else ""
    return f"{row.document_id} ({row.origin_id}{cites})"


def _print_corroboration(report: Report, entity_id: str) -> None:
    facts = _corroborated_facts(report)
    if not facts:
        typer.echo(f"No corroborated facts for {entity_id}.")
        return
    _print_row(_CORROBORATION_HEADER)
    for (metric_id, period, qualifier), rows in sorted(
        facts.items(), key=lambda item: (item[0][0], item[0][1], _qualifier_text(item[0][2]))
    ):
        # Sorted by document id, then by origin: the order of the comparisons follows the
        # rank of the paths, which is no order an analyst can predict. Keyed by document and
        # effective origin, not document alone, because one document can cite two origins
        # across its rows, and each must show next to the document.
        texts: dict[tuple[str, str], str] = {}
        for row in rows:
            texts.setdefault((row.document_id, row.effective_origin_id), _document_text(row))
        documents = {row.document_id for row in rows}
        origins = {row.effective_origin_id for row in rows}
        _print_row(
            (
                metric_id,
                *_period_fields(period),
                _qualifier_text(qualifier),
                f"{len(documents)} documents, {len(origins)} origins",
                "; ".join(texts[key] for key in sorted(texts)),
            )
        )


@app.command()
def brief(
    entity_id: str,
    sector: Annotated[
        str | None, typer.Option(help="Sector code. Without it the absence check does not run.")
    ] = None,
) -> None:
    """Print the analyst brief: fact table, inconsistencies, corroboration, conspicuous
    absences, patterns, management questions (architecture doc section 6, items 1 to 4 and
    6; S3-02, S4-03, S5-03).

    Calls ``facts_show`` and ``validate_entity`` directly, so each section is the stdout
    (and, for ``validate_entity``, the stderr notes) of its own command, not a copy of it
    (S2 decision 1: no new table, the brief composes the same calls on demand).
    """
    if sector is not None:
        # A bad code stops here, before any output: an empty expected set hides every absence.
        try:
            expected_metrics(load_dictionary(get_settings().dictionary_dir), sector)
        except ValueError as error:
            _fail(str(error))
    typer.echo("## Fact table")
    facts_show(entity_id)
    typer.echo()
    typer.echo("## Inconsistencies")
    report, dictionary, rows = validate_entity(entity_id)
    typer.echo()
    typer.echo("## Corroboration")
    _print_corroboration(report, entity_id)
    absences, found = patterns(rows, dictionary, sector)
    typer.echo()
    typer.echo("## Conspicuous absences")
    if sector is None:
        typer.echo("No sector given, so the absence check did not run.")
    elif not rows:
        typer.echo(f"No facts for {entity_id}, so the absence check did not run.")
    elif absences:
        _print_row(("metric_id", "name"))
        for absence in absences:
            _print_row((absence.metric_id, metric_of(dictionary, absence.metric_id).canonical_name))
    else:
        typer.echo(f"No conspicuous absences for {entity_id}.")
    typer.echo()
    typer.echo("## Patterns")
    if found:
        _print_findings(found, dictionary)
    else:
        typer.echo(f"No patterns for {entity_id}.")
    typer.echo()
    typer.echo("## Management questions")
    questions = [
        *(question(f, dictionary) for f in report.findings),
        *(absence_question(a, dictionary) for a in absences),
        *(question(f, dictionary) for f in found),
    ]
    for number, text in enumerate(questions, start=1):
        typer.echo(f"{number}. {text}")
    if not questions:
        typer.echo(f"No questions for {entity_id}.")
