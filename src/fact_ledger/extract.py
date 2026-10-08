"""Turn a PDF deck or a saved text file into transcript rows (S3-01, S5-02).
The LLM reads one page, or one whole text; this module turns each response into an ``Observation``
with the pure rules of ``domain.extraction``, and leaves out a value it cannot trust, naming
the page or paragraph and the printed text (S3-05).
"""

import re
from collections.abc import Callable, Iterator, Mapping
from datetime import date
from functools import partial
from importlib import resources
from json import loads
from pathlib import Path
from string import Template
from typing import Any, Literal, NamedTuple

from pydantic import BaseModel
from pypdf import PdfReader

from fact_ledger.domain import Basis, Dictionary, Dimension, Metric, Observation, PeriodType
from fact_ledger.domain.extraction import (
    currency_for,
    is_cost_label,
    map_label,
    parse_figure,
    prints_period,
)
from fact_ledger.domain.paths import metric_of
from fact_ledger.domain.rules import (
    COST_LINE_WORD,
    GENERIC_MARGIN_LABELS,
    OUTFLOW_METRICS,
    SIGNED_METRICS,
)

PROMPT = "extract_deck_v7.md"
TEXT_PROMPT = "extract_text_v1.md"

_BASIS_VALUES = frozenset(basis.value for basis in Basis)


class ExtractedValue(BaseModel):
    stated_label: str
    printed: str  # the figure as printed, for example "~€8m" or "7,450"
    scale: Literal["", "k", "m", "bn"]
    unit: str  # a currency symbol or ISO code, or "percent", "ratio", "count"
    period_type: PeriodType
    period_start: date | None
    period_end: date | None
    candidate_metric_ids: list[str]
    # "" is "not stated": ``_row`` maps it to None, or to reported for basis.
    segment: str
    region: str
    basis: str


class PageExtraction(BaseModel):
    cover_date: date | None  # read from page 1 only
    values: list[ExtractedValue]


class TextValue(ExtractedValue):
    paragraph: int  # the N of the [para N] marker that holds the label and the figure


class TextExtraction(BaseModel):
    values: list[TextValue]  # no cover_date: the LLM never reads a published date


# The default keeps a bare ``Complete`` the deck's type.
type Complete[M: BaseModel = PageExtraction] = Callable[[str, str, type[M]], M]


class Extraction(NamedTuple):
    defaults: dict[str, object]
    rows: list[tuple[Observation, str]]
    pages: int
    left_out: list[str]
    sign_changed: list[str]  # S3-18: a row whose printed sign the cost rule flipped


# S3-07: a label beside a neighbour tile reaches only over that tile's unit, period and delta
# lines, and layout mode can put a few blank lines between them.
_MAX_LINES_BELOW_SHARED_LABEL = 4
# S3-16: a label prints just after its own figure, never far below it.
_MAX_TEXT_LINES_ABOVE = 2
# S3-16: a lone label reaches one line further, to a chart's bars under its unit, period and
# growth lines.
_MAX_LINES_BELOW_LONE_LABEL = 5
_MAX_BLANK_RUN = 3


def _lines_below(lines: list[str], index: int, max_lines: int) -> Iterator[str]:
    """The next ``max_lines`` text lines after ``lines[index]``. A run of more than
    ``_MAX_BLANK_RUN`` blank lines ends the search.
    """
    blank_run = 0
    text_lines = 0
    for text in lines[index + 1 :]:
        if not text.strip():
            blank_run += 1
            if blank_run > _MAX_BLANK_RUN:
                return
            continue
        blank_run = 0
        yield text
        text_lines += 1
        if text_lines == max_lines:
            return


def _needle(text: str) -> str:
    return r"\s+".join(re.escape(token) for token in text.split())


def _label_pattern(label: str) -> str:
    return rf"(?<!\w){_needle(label)}(?!\w)"


def _figure_re(printed: str) -> re.Pattern[str]:
    """The whole figure, never a piece of a longer one ("8" of "€8.4m")."""
    return re.compile(rf"(?<!\w)(?<!\d[.,]){_needle(printed)}(?![\w%]|[.,]\d)")


def _lines_above(lines: list[str], index: int, max_lines: int) -> Iterator[str]:
    """The ``max_lines`` text lines before ``lines[index]``, nearest first. A run of more
    than ``_MAX_BLANK_RUN`` blank lines ends the search.
    """
    blank_run = 0
    text_lines = 0
    for text in reversed(lines[:index]):
        if not text.strip():
            blank_run += 1
            if blank_run > _MAX_BLANK_RUN:
                return
            continue
        blank_run = 0
        yield text
        text_lines += 1
        if text_lines == max_lines:
            return


def _overlaps(spans: list[tuple[int, int]], start: int, end: int) -> bool:
    return any(start < span_end and span_start < end for span_start, span_end in spans)


_TOKEN_RE = re.compile(r"\S+")
_DIGIT_RE = re.compile(r"\d")


def _blocked_by(lines: list[str], start: int, end: int) -> bool:
    """A no-digit token over ``(start, end)`` on one of ``lines`` is another tile's title,
    not the figure's own tile, and blocks a lone label from claiming a figure in another
    column.
    """
    return any(
        _overlaps([token.span()], start, end) and not _DIGIT_RE.search(token.group())
        for text in lines
        for token in _TOKEN_RE.finditer(text)
    )


def _figure_above(lines: list[str], index: int, spans: list[tuple[int, int]]) -> bool:
    """A number prints in ``spans``' column, within ``_MAX_TEXT_LINES_ABOVE`` lines above
    ``lines[index]``. That figure already pairs with the label through criterion 1. A lone
    label must not also take criterion 2's wide reach below it.
    """
    return any(
        _DIGIT_RE.search(token.group()) and _overlaps(spans, *token.span())
        for above in _lines_above(lines, index, _MAX_TEXT_LINES_ABOVE)
        for token in _TOKEN_RE.finditer(above)
    )


def _pairs_with_figure(label: str, printed: str, page_text: str) -> bool:
    """S1 V3, S3-07 and S3-16. A label
    that shares its raw line with other text pairs only with a figure in its own column.
    That figure is on the same line, or on the next ``_MAX_LINES_BELOW_SHARED_LABEL`` text
    lines. A label alone on its raw line pairs with a figure in any column, on the next
    ``_MAX_LINES_BELOW_LONE_LABEL`` text lines. A no-digit token between them, over the
    figure's column, blocks the pair. That token is another tile's title on its own baseline,
    not this figure's. A lone label with a figure above it, in its own
    column, skips this wide reach. A label below its own figure pairs in the
    same column, ``_MAX_TEXT_LINES_ABOVE`` up. A piece of a longer figure ("8" of "€8.4m")
    does not count, and a label wrapped over two lines matches on neither line. Every label
    and figure match counts, because two tiles can print the same label.
    """
    label_re = re.compile(_label_pattern(label))
    figure_re = _figure_re(printed)
    lines = page_text.splitlines()

    for index, line in enumerate(lines):
        label_spans = [match.span() for match in label_re.finditer(line)]
        if label_spans:
            if figure_re.search(line):
                return True
            label_alone = len(label_spans) == 1 and not label_re.sub("", line).strip()
            if not (label_alone and _figure_above(lines, index, label_spans)):
                reach = (
                    _MAX_LINES_BELOW_LONE_LABEL if label_alone else _MAX_LINES_BELOW_SHARED_LABEL
                )
                between: list[str] = []
                for below in _lines_below(lines, index, reach):
                    for figure in figure_re.finditer(below):
                        if _overlaps(label_spans, *figure.span()):
                            return True
                        if label_alone and not _blocked_by(between, *figure.span()):
                            return True
                    between.append(below)
        figure_spans = [match.span() for match in figure_re.finditer(line)]
        if figure_spans:
            for above in _lines_below(lines, index, _MAX_TEXT_LINES_ABOVE):
                for match in label_re.finditer(above):
                    if _overlaps(figure_spans, *match.span()):
                        return True
    return False


def _names_the_row_above(label: str, printed: str, page_text: str) -> bool:
    """S3-17: a generic margin row prints "% Margin" beside its figure and the
    metric on the row above, so the combined label is nowhere on the page. Accept it when one
    line holds the figure and a ``GENERIC_MARGIN_LABELS`` label of its own, not a "%" unit
    marker in brackets or the figure's own "%" suffix (S3-13), and the complete
    row above, not a part of it, opens the nearest text line above that line, so a second copy
    of the figure elsewhere cannot pair with another row. A label two or more rows above is out
    of scope.
    """
    figure_re = _figure_re(printed)
    label_re = re.compile(_label_pattern(label))
    generic_re = re.compile(
        "|".join(_label_pattern(generic) for generic in GENERIC_MARGIN_LABELS), re.IGNORECASE
    )
    lines = page_text.splitlines()
    for index, line in enumerate(lines):
        figure = figure_re.search(line)
        if figure is None:
            continue
        rest = line[: figure.start()] + re.sub(r"^\s?%(?!\w)", "", line[figure.end() :])
        rest = re.sub(r"\([^)]*\)", "", rest)
        if generic_re.search(rest):
            above = next((text for text in reversed(lines[:index]) if text.strip()), "")
            if label_re.match(above.lstrip()):
                return True
    return False


def _label_pairs_with_figure(label: str, printed: str, page_text: str, unit: str) -> bool:
    """S3-15, S3-17 and S3-20: the prompt builds two labels
    from two places, so the page prints neither in full. Inside a cost block it adds
    ``COST_LINE_WORD`` ("Sales" gives "Sales expenses"). On a generic margin row it adds
    "margin", "%" or the generic label as printed to the label of the row above ("% Margin"
    under "Gross profit" gives "Gross profit margin"), or to the label of its own row or column
    ("EBITDA   60.0   30.0%" gives "EBITDA margin" for the percent). Each added part is a
    ``GENERIC_MARGIN_LABELS`` label. The check drops the added part; the rest of the label must
    still pair with the figure, or name the row above, or (a percent value only, so a currency
    value can never drop the added part) pair with the figure itself, on its own row or column.
    """
    if _pairs_with_figure(label, printed, page_text):
        return True
    on_page, _, last = label.rpartition(" ")
    if on_page and last.casefold() == COST_LINE_WORD:
        return _pairs_with_figure(on_page, printed, page_text)
    folded = label.casefold()
    for added in GENERIC_MARGIN_LABELS:
        if not folded.endswith(f" {added}"):
            continue
        rest = label[: -len(added) - 1]
        if _names_the_row_above(rest, printed, page_text) or (
            unit == "percent" and _pairs_with_figure(rest, printed, page_text)
        ):
            return True
    return False


def _prints_year(page_text: str, day: date) -> bool:
    """D1, D2: the page prints the year of ``day`` in 4 digits."""
    return re.search(rf"(?<!\d){day.year}(?!\d)", page_text) is not None


def _dictionary_line(metric: Metric) -> str:
    aliases = ", ".join(metric.aliases)
    line = f"- {metric.metric_id}: {metric.canonical_name} ({metric.stock_or_flow}). "
    return f"{line}Aliases: {aliases}. {metric.definition_note}".rstrip()


def _system_prompt(dictionary: Dictionary, prompt: str = PROMPT) -> str:
    """Fill the ``$dictionary`` placeholder: one line per metric."""
    text = resources.files("fact_ledger").joinpath("prompts", prompt).read_text("utf-8")
    lines = "\n".join(_dictionary_line(metric) for metric in dictionary.metrics)
    return Template(text).substitute(dictionary=lines)


def replay[M: BaseModel](path: Path) -> Complete[M]:
    """A ``Complete`` that gives the next recorded page of ``path``."""
    pages = iter(loads(path.read_text("utf-8"))["pages"])

    def complete(system: str, user: str, schema: type[M]) -> M:
        del system, user
        try:
            page = next(pages)
        except StopIteration as exc:
            msg = f"{path}: no recorded page left to replay"
            raise ValueError(msg) from exc
        return schema.model_validate(page)

    return complete


def _reject(locator: str, printed: str, reason: str) -> ValueError:
    return ValueError(f"{locator}: {printed!r}: {reason}")


def _row(
    number: int,
    locator: str,
    value: ExtractedValue,
    page_text: str,
    *,
    dictionary: Dictionary,
    context: Mapping[str, object],
    sign_changed: list[str],
    label_pairs_with_figure: Callable[[str, str, str], bool],
) -> tuple[Observation, str]:
    if value.stated_label.casefold() in GENERIC_MARGIN_LABELS:
        raise _reject(locator, value.printed, "a generic margin label names no metric")
    if not label_pairs_with_figure(value.stated_label, value.printed, page_text):
        msg = "stated_label and printed are not on one line or in one column"
        raise _reject(locator, value.printed, msg)
    if value.period_start is None or value.period_end is None:
        raise _reject(locator, value.printed, "no usable printed period")
    # S3-06: a hyphen token ("H1-26") also proves the year, next to a quarter column with none.
    if not _prints_year(page_text, value.period_end) and not prints_period(
        page_text, value.period_start, value.period_end
    ):
        raise _reject(locator, value.printed, "the page does not print the year of period_end")
    # A basis word outside the closed list is left out and named, never guessed.
    if value.basis and value.basis not in _BASIS_VALUES:
        msg = f"basis {value.basis!r} is not reported, pro_forma or constant_currency"
        raise _reject(locator, value.printed, msg)

    try:
        parsed_value, precision = parse_figure(value.printed, value.scale, value.unit)
        currency = currency_for(value.unit)
        metric_id, status, candidates = map_label(
            value.stated_label, value.candidate_metric_ids, dictionary
        )
        # S3-18: a cost line, a dictionary outflow or a slug with a cost word, is a positive amount.
        is_slug = metric_id not in dictionary.metric_ids
        is_cost = metric_id in OUTFLOW_METRICS or (is_slug and is_cost_label(value.stated_label))
        flipped = parsed_value < 0 and is_cost
        if flipped:
            parsed_value = -parsed_value
        # S3-08: a negative on a dictionary metric is a sign or label error, unless it can fall.
        is_unsigned_metric = metric_id in dictionary.metric_ids and metric_id not in SIGNED_METRICS
        if parsed_value < 0 and is_unsigned_metric:
            msg = f"{metric_id} cannot be negative"
            raise ValueError(msg)
        # S3-20: a percent is a rate, never an amount or a count. A slug has no dimension.
        if value.unit == "percent" and metric_id in dictionary.metric_ids:
            dimension = metric_of(dictionary, metric_id).dimension
            if dimension is not Dimension.PERCENT:
                msg = f"a percent value cannot carry a {dimension.value} metric"
                raise ValueError(msg)
        fields: dict[str, Any] = {
            **context,
            "observation_id": f"{context['document_id']}-{number:02d}",
            "metric_id": metric_id,
            "value": parsed_value,
            "unit": currency if currency is not None else value.unit,
            "currency": currency,
            "stated_precision": precision,
            "period_start": value.period_start,
            "period_end": value.period_end,
            "period_type": value.period_type,
            "as_of_date": value.period_end,  # D2, D4: the code sets it, never the LLM
            "locator": locator,
            "stated_label": value.stated_label,
            "definition_status": status,
            "candidate_metric_ids": candidates,
            "segment": value.segment or None,
            "region": value.region or None,
            "basis": value.basis or Basis.REPORTED,
        }
        observation = Observation(**fields)
    except ValueError as exc:
        raise _reject(locator, value.printed, str(exc)) from exc
    if flipped:
        sign_changed.append(
            f"{locator}: {value.printed!r}: stored as the positive amount of a cost"
        )
    return observation, value.printed


def extract_deck(
    pdf: Path,
    dictionary: Dictionary,
    source: Mapping[str, object],
    complete: Complete,
) -> Extraction:
    """One ``complete`` call per page with text, in page order. A
    blank or whitespace-only page gets no call. A value that fails a check is left out: its
    message goes into ``Extraction.left_out`` and the run continues. A response that fails
    the schema raises ``ValueError`` with the page number. Page 1 with no cover date, or
    without its year, raises ``ValueError`` with the file name (D1). A row whose printed sign
    the cost rule flips is kept, and named in ``Extraction.sign_changed`` (S3-18).
    """
    reader = PdfReader(pdf)
    system = _system_prompt(dictionary)
    published_date: date | None = None
    rows: list[tuple[Observation, str]] = []
    left_out: list[str] = []
    sign_changed: list[str] = []

    for page_index, page in enumerate(reader.pages, start=1):
        page_text = page.extract_text(extraction_mode="layout")
        if not page_text.strip():
            if page_index == 1:
                msg = f"{pdf.name}: no cover date on page 1"
                raise ValueError(msg)
            continue
        try:
            extraction = complete(system, page_text, PageExtraction)
        except ValueError as exc:  # a response that fails the schema
            msg = f"p{page_index}: {exc}"
            raise ValueError(msg) from exc

        if page_index == 1:
            if extraction.cover_date is None:
                msg = f"{pdf.name}: no cover date on page 1"
                raise ValueError(msg)
            if not _prints_year(page_text, extraction.cover_date):
                msg = f"{pdf.name}: page 1 does not print the year of cover_date"
                raise ValueError(msg)
            published_date = extraction.cover_date

        context = {**source, "source_type": "deck", "published_date": published_date}
        for value in extraction.values:
            try:
                rows.append(
                    _row(
                        len(rows) + 1,
                        f"p{page_index}",
                        value,
                        page_text,
                        dictionary=dictionary,
                        context=context,
                        sign_changed=sign_changed,
                        label_pairs_with_figure=partial(_label_pairs_with_figure, unit=value.unit),
                    )
                )
            except ValueError as exc:
                left_out.append(str(exc))

    defaults: dict[str, object] = {
        **source,
        "source_type": "deck",
        "published_date": published_date,
    }
    return Extraction(
        defaults=defaults,
        rows=rows,
        pages=len(reader.pages),
        left_out=left_out,
        sign_changed=sign_changed,
    )


_PARAGRAPH_BREAK = re.compile(r"\n\s*\n")


def extract_text(
    path: Path,
    dictionary: Dictionary,
    source: Mapping[str, object],
    complete: Complete[TextExtraction],
) -> Extraction:
    """One ``complete`` call for the whole file, every paragraph under a ``[para N]`` marker.
    A paragraph is folded to one line, so the deck checks of
    ``_row`` read it unchanged: the figure and the year must be in the paragraph of the
    value. The label check is strict (``_pairs_with_figure``, never ``_label_pairs_with_figure``):
    the whole label, as the response prints it, must be in the paragraph. A deck rewrite that
    drops an added cost or margin word would pass a paragraph that never prints that word. A
    value that fails a check, or names no paragraph, is left out and named.
    ``source`` holds the published date and the source type. A file with no paragraph, or a
    response that fails the schema, raises ``ValueError``.
    """
    blocks = (" ".join(block.split()) for block in _PARAGRAPH_BREAK.split(path.read_text("utf-8")))
    paragraphs = [block for block in blocks if block]
    if not paragraphs:
        msg = f"{path.name}: no paragraph"
        raise ValueError(msg)
    user = "\n\n".join(f"[para {n}]\n{text}" for n, text in enumerate(paragraphs, start=1))
    extraction = complete(_system_prompt(dictionary, TEXT_PROMPT), user, TextExtraction)

    rows: list[tuple[Observation, str]] = []
    left_out: list[str] = []
    sign_changed: list[str] = []
    for value in extraction.values:
        locator = f"para {value.paragraph}"
        if not 1 <= value.paragraph <= len(paragraphs):
            left_out.append(str(_reject(locator, value.printed, "no such paragraph")))
            continue
        try:
            rows.append(
                _row(
                    len(rows) + 1,
                    locator,
                    value,
                    paragraphs[value.paragraph - 1],
                    dictionary=dictionary,
                    context=source,
                    sign_changed=sign_changed,
                    label_pairs_with_figure=_pairs_with_figure,
                )
            )
        except ValueError as exc:
            left_out.append(str(exc))
    return Extraction(dict(source), rows, len(paragraphs), left_out, sign_changed)
