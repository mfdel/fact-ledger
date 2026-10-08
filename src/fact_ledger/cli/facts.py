"""Fact store and validator commands: ``fact-ledger facts ...``, ``validate``.
``brief`` composes them in ``cli/brief.py``.
"""

from collections.abc import Sequence
from pathlib import Path
from typing import Annotated

import typer

from fact_ledger.cli import _fail, _open, _print_row, app, facts_app
from fact_ledger.domain import Basis, CheckStatus, Dictionary, Observation, Period
from fact_ledger.domain.models import Qualifier
from fact_ledger.domain.paths import Finding, Report
from fact_ledger.domain.questions import path_texts, question
from fact_ledger.domain.validator import validate
from fact_ledger.store.facts import FactStoreError
from fact_ledger.store.yaml_files import read_transcript

_FACTS_HEADER = (
    "observation_id",
    "metric_id",
    "period_start",
    "period_end",
    "period_type",
    "value",
    "unit",
    "origin_id",
    "locator",
    "definition_status",
    "candidate_metric_ids",
)

_FINDINGS_HEADER = (
    "kind",
    "class",
    "subject",
    "period_start",
    "period_end",
    "period_type",
    "left",
    "right",
    "question",
)

_READINGS_HEADER = (
    "observation_id",
    "metric_id",
    "stated_label",
    "period_start",
    "period_end",
    "period_type",
    "status",
    "read_as",
    "how",
    "basis",
    "reason",
)


def _warn_undefined_metrics(dictionary: Dictionary, rows: Sequence[Observation]) -> None:
    """Warn about metric ids not in the dictionary, naming their 1-based row numbers."""
    row_numbers = {
        observation.observation_id: number for number, observation in enumerate(rows, start=1)
    }
    for item in dictionary.undefined_metrics(rows):
        numbers = ", ".join(str(row_numbers[oid]) for oid in item.observation_ids)
        typer.echo(f"undefined metric id {item.metric_id!r}: row(s) {numbers}", err=True)


@facts_app.command("load")
def facts_load(file: Path) -> None:
    """Load a transcribed deck into the fact store."""
    try:
        rows = read_transcript(file)
    except ValueError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(1) from error

    store, dictionary = _open()
    try:
        store.add_many(rows)
    except FactStoreError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(1) from error
    finally:
        store.dispose()
    _warn_undefined_metrics(dictionary, rows)
    typer.echo(f"Loaded {len(rows)} observations from {file}.")


@facts_app.command("show")
def facts_show(entity_id: str) -> None:
    """Print every fact stored for one company."""
    store, _dictionary = _open()
    try:
        facts = store.find(entity_id=entity_id)
    finally:
        store.dispose()
    if not facts:
        typer.echo(f"No facts found for {entity_id}.")
        return
    _print_row(_FACTS_HEADER)
    for observation in facts:
        _print_row(
            (
                observation.observation_id,
                observation.metric_id,
                str(observation.period_start),
                str(observation.period_end),
                str(observation.period_type),
                str(observation.value),
                observation.unit,
                observation.origin_id,
                observation.locator,
                str(observation.definition_status),
                ", ".join(observation.candidate_metric_ids),
            )
        )


def _period_fields(period: Period | None) -> tuple[str, str, str]:
    return (str(period.start), str(period.end), str(period.type)) if period else ("", "", "")


def _print_findings(findings: Sequence[Finding], dictionary: Dictionary) -> None:
    _print_row(_FINDINGS_HEADER)
    for finding in findings:
        left, *right = path_texts(finding, dictionary)
        _print_row(
            (
                str(finding.kind),
                str(finding.divergence or ""),
                finding.subject,
                *_period_fields(finding.period),
                left,
                "; ".join(right),
                question(finding, dictionary),
            )
        )


def _qualifier_text(qualifier: Qualifier) -> str:
    """Blank for the group row on the reported basis: every S1 and S2
    fixture. Only the parts a deck stated print, so an unqualified check keeps its
    unqualified look.
    """
    parts = []
    if qualifier.segment:
        parts.append(f"segment={qualifier.segment}")
    if qualifier.region:
        parts.append(f"region={qualifier.region}")
    if qualifier.basis is not Basis.REPORTED:
        parts.append(f"basis={qualifier.basis}")
    return ", ".join(parts)


def _print_checks(report: Report) -> None:
    _print_row(
        (
            "identity_id",
            "period_start",
            "period_end",
            "period_type",
            "status",
            "reason",
            "qualifier",
        )
    )
    for check in report.checks:
        _print_row(
            (
                check.identity_id,
                *_period_fields(check.period),
                str(check.status),
                check.reason,
                _qualifier_text(check.qualifier),
            )
        )


def _print_readings(report: Report) -> None:
    """The stored ``metric_id`` prints next to the reading, never replaced by it."""
    _print_row(_READINGS_HEADER)
    for reading in report.readings:
        row = reading.observation
        basis = reading.basis or tuple(s.observation for s in reading.sources)
        how = ("inherited" if reading.sources else "direct") if reading.inferred else ""
        _print_row(
            (
                row.observation_id,
                row.metric_id,
                row.stated_label,
                *_period_fields(Period(row.period_start, row.period_end, row.period_type)),
                "inferred" if reading.inferred else "ambiguous",
                (reading.metric_id or "") if reading.inferred else "",
                how,
                ",".join(o.observation_id for o in basis),
                reading.reason,
            )
        )


@app.command("validate")
def validate_entity(
    entity_id: str,
    checks: Annotated[bool, typer.Option("--checks", help="List the checks.")] = False,
    readings: Annotated[bool, typer.Option("--readings", help="List the ambiguous rows.")] = False,
) -> tuple[Report, Dictionary, list[Observation]]:
    """Run the validator on one company and print its findings.

    Findings are computed on demand from the fact store. Nothing is written back. Returns
    the report, dictionary and rows so that ``brief`` can build its questions and pattern
    sections from the same run, without printing it twice.
    """
    if checks and readings:
        _fail("Use --checks or --readings, not both.")
    store, dictionary = _open()
    try:
        rows = store.find(entity_id=entity_id)
    finally:
        store.dispose()
    report = validate(rows, dictionary)
    if checks:
        _print_checks(report)
    elif readings:
        _print_readings(report)
    elif report.findings:
        _print_findings(report.findings, dictionary)
    else:
        typer.echo(f"No findings for {entity_id}.")

    counts = [sum(c.status is status for c in report.checks) for status in CheckStatus]
    typer.echo(
        "Checks: {} held, {} violated, {} not checked. Use --checks to list them.".format(*counts),
        err=True,
    )
    if report.readings:
        inferred = sum(r.inferred for r in report.readings)
        typer.echo(
            f"Ambiguous rows: {inferred} inferred, {len(report.readings) - inferred} still "
            "ambiguous. Use --readings to list them.",
            err=True,
        )
    undefined = sum(len(u.observation_ids) for u in dictionary.undefined_metrics(rows))
    if undefined:
        typer.echo(
            f"{undefined} observation(s) use undefined metric ids and were not validated. "
            "See 'metrics undefined'.",
            err=True,
        )
    return report, dictionary, rows
