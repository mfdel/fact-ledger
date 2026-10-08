"""``fact-ledger extract`` and ``extract-text``: turn a PDF deck or a saved text file into a
transcript file (S3-01, S5-02). They never
touch the fact store: the analyst reviews the file, then runs ``facts load``.
"""

from datetime import datetime
from pathlib import Path
from typing import Annotated

import typer

from fact_ledger import llm
from fact_ledger.cli import _fail, app
from fact_ledger.domain import SourceType
from fact_ledger.extract import PROMPT, TEXT_PROMPT, Extraction, extract_deck, extract_text
from fact_ledger.settings import get_settings
from fact_ledger.store.yaml_files import load_dictionary, write_transcript


def _write(extraction: Extraction, out: Path, header: str, unit: str) -> None:
    write_transcript(out, header, extraction.defaults, extraction.rows)
    for message in extraction.left_out:
        typer.echo(f"Left out {message}", err=True)
    for message in extraction.sign_changed:
        typer.echo(f"Sign changed {message}", err=True)
    typer.echo(
        f"Wrote {len(extraction.rows)} rows from {extraction.pages} {unit} to {out}. "
        f"Review it, then run 'fact-ledger facts load {out}'."
    )


@app.command("extract")
def extract(
    deck: Path,
    *,
    out: Annotated[Path, typer.Option("--out")],
    entity: Annotated[str, typer.Option("--entity")],
    origin: Annotated[str, typer.Option("--origin")],
    document: Annotated[str, typer.Option("--document")],
    reliability: Annotated[int, typer.Option("--reliability", min=1, max=5)],
) -> None:
    """Read ``deck`` page by page with the LLM and write a transcript."""
    settings = get_settings()
    dictionary = load_dictionary(settings.dictionary_dir)
    source = {
        "entity_id": entity,
        "origin_id": origin,
        "document_id": document,
        "reliability": reliability,
    }
    try:
        # Looked up at call time, so a test can monkeypatch fact_ledger.llm.complete.
        extraction = extract_deck(deck, dictionary, source, llm.complete)
    except ValueError as error:
        _fail(str(error))

    header = f"{deck.name}, {PROMPT}. Model {settings.llm_model}. Not reviewed."
    _write(extraction, out, header, "pages")


@app.command("extract-text")
def extract_text_command(
    file: Path,
    *,
    out: Annotated[Path, typer.Option("--out")],
    entity: Annotated[str, typer.Option("--entity")],
    origin: Annotated[str, typer.Option("--origin")],
    document: Annotated[str, typer.Option("--document")],
    reliability: Annotated[int, typer.Option("--reliability", min=1, max=5)],
    source_type: Annotated[SourceType, typer.Option("--source-type")],
    published: Annotated[datetime, typer.Option("--published", formats=["%Y-%m-%d"])],
    cites: Annotated[str | None, typer.Option("--cites")] = None,
) -> None:
    """Read the text file ``file`` with the LLM and write a transcript (S5-02)."""
    settings = get_settings()
    dictionary = load_dictionary(settings.dictionary_dir)
    source: dict[str, object] = {
        "entity_id": entity,
        "origin_id": origin,
        "document_id": document,
        "reliability": reliability,
        "source_type": source_type.value,
        "published_date": published.date(),
    }
    if cites is not None:
        source["cited_origin_id"] = cites
    try:
        extraction = extract_text(file, dictionary, source, llm.complete)
    except ValueError as error:
        _fail(str(error))

    header = f"{file.name}, {TEXT_PROMPT}. Model {settings.llm_model}. Not reviewed."
    _write(extraction, out, header, "paragraphs")
