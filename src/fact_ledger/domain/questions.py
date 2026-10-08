"""Questions for management (S2-06).

Deterministic template text, no LLM call. The text cites paths and never a merged value.
"""

from collections.abc import Iterable
from decimal import ROUND_HALF_EVEN, Decimal

from fact_ledger.domain.checks import INEQUALITIES
from fact_ledger.domain.enums import Dimension, FindingKind, PeriodType
from fact_ledger.domain.models import Dictionary, Observation, Period
from fact_ledger.domain.paths import (
    ComputationPath,
    Finding,
    direct_path,
    identity_of,
    metric_of,
    period_of,
    rank,
)
from fact_ledger.domain.patterns import Absence, cagr
from fact_ledger.domain.rules import (
    ABSENCE_QUESTION,
    BRIDGE_DIRECTION,
    MIN_RELIABILITY,
    PERIOD_NAMES,
    QUESTION_TEMPLATES,
)


class _Text:
    """Path, value and locator text of one finding (D6.1, D6.2, D2.11)."""

    def __init__(self, finding: Finding, dictionary: Dictionary) -> None:
        self.dictionary = dictionary
        cited = (finding.left, *finding.right)
        documents = {o.document_id for p in cited for o in p.observations}
        self.document = documents.pop() if len(documents) == 1 else None

    def name(self, metric_id: str) -> str:
        return metric_of(self.dictionary, metric_id).canonical_name

    def value(self, path: ComputationPath, value: Decimal | None = None) -> str:
        """The stored value. A computed value or a gap is rounded for display only."""
        dimension = metric_of(self.dictionary, path.metric_id).dimension
        if value is None and path.identity_id is None:
            value = path.value
        else:
            places = Decimal(1) if dimension in _WHOLE else Decimal("0.01")
            value = (path.value if value is None else value).quantize(places, ROUND_HALF_EVEN)
        match dimension:
            case Dimension.CURRENCY:
                return f"{path.currency or path.unit} {value:,f}"
            case Dimension.COUNT:
                return f"{value:,f}"
            case Dimension.PERCENT:
                return f"{value:f}%"
            case Dimension.RATIO:
                return f"{value:f}x"
            case _:
                return f"{value:f} {dimension}"

    def locator(self, row: Observation) -> str:
        if row.document_id == self.document:
            return row.locator
        return f"{row.document_id} {row.locator}"

    def at(self, path: ComputationPath) -> str:
        """``<value> on <locator>``, of a direct path."""
        return f"{self.value(path)} on {self.locator(path.observations[0])}"

    def basis(self, row: Observation) -> str:
        return self.at(direct_path(row, self.dictionary))

    def path(self, path: ComputationPath) -> str:
        if path.identity_id:
            identity = identity_of(self.dictionary, path.identity_id)
            inputs = " and ".join(f"{o.metric_id} {self.basis(o)}" for o in path.observations)
            return f"{self.value(path)} computed as {identity.equation} from {inputs}"
        row = path.observations[0]
        if not path.inferred or path.reading is None:
            return f'{self.at(path)} ("{row.stated_label}")'
        reading = path.reading
        stated = ""
        if path.period != period_of(row):
            stated = f", stated {_period(period_of(row))}"
        if reading.sources:
            source = min(
                reading.sources,
                key=lambda s: (-s.observation.period_end.toordinal(), s.observation.observation_id),
            )
            basis = min(source.basis, key=lambda o: rank(direct_path(o, self.dictionary)))
            why = (
                f'"{source.observation.stated_label}" {_period(period_of(source.observation))} '
                f"on {self.locator(source.observation)} matches {self.basis(basis)}"
            )
        else:
            basis = min(reading.basis, key=lambda o: rank(direct_path(o, self.dictionary)))
            why = f"it matches {self.basis(basis)}"
        return (
            f'{self.at(path)} ("{row.stated_label}"{stated}, read as {self.name(path.metric_id)}: '
            f"{why})"
        )


_WHOLE = frozenset({Dimension.CURRENCY, Dimension.COUNT})


def _period(period: Period) -> str:
    if period.type is PeriodType.POINT_IN_TIME:
        return f"at {period.end}"
    return f"for the {PERIOD_NAMES[period.type]} {period.start} to {period.end}"


def _reading_text(paths: Iterable[ComputationPath], text: _Text) -> str:
    """D2.11 item 2: one sentence per inferred label and metric, in citation order."""
    sentences: dict[str, None] = {}
    for path in paths:
        if path.inferred:
            label = path.observations[0].stated_label
            sentences[
                f' The question reads "{label}" as {text.name(path.metric_id)}. If this is wrong, '
                f'what does "{label}" mean?'
            ] = None
    return "".join(sentences)


def _basis_name(path: ComputationPath) -> str:
    return path.qualifier.basis.replace("_", " ")


def _pair_fields(finding: Finding, text: _Text) -> dict[str, str]:
    subject, counterpart, *others = (finding.left, *finding.right)
    gap = abs(subject.value - counterpart.value)
    weak = next((p for p in (subject, counterpart) if p.reliability < MIN_RELIABILITY), None)
    reason = (
        f"{text.locator(weak.observations[0])} comes from a source with reliability 1"
        if weak
        else "the computed value uses inputs from more than one source"
    )
    also = ""
    if others:
        also = (
            f" These values also differ from {text.locator(subject.observations[0])}: "
            + "; ".join(text.path(p) for p in others)
            + "."
        )
    return {
        "metric": text.name(finding.subject),
        "path_s": text.path(subject),
        "path_c": text.path(counterpart),
        "label_s": subject.observations[0].stated_label,
        "label_c": counterpart.observations[0].stated_label,
        "also": also,
        "gap": text.value(subject, gap),
        "reason": reason,
        "reading": _reading_text((subject, counterpart, *others), text),
    }


def _ambiguity_fields(finding: Finding, text: _Text) -> dict[str, str]:
    row = finding.left.observations[0]
    candidates = []
    for path in finding.right:
        period = "" if path.period == finding.period else f" {_period(path.period)}"
        candidates.append(f"{text.name(path.metric_id)}{period} {text.path(path)}")
    return {
        "label": row.stated_label,
        "value": text.value(finding.left),
        "locator": text.locator(row),
        "candidates": "; ".join(candidates),
    }


def _invariant_fields(finding: Finding, text: _Text) -> dict[str, str]:
    lhs, rhs, *used = (finding.left, *finding.right)
    identity = identity_of(text.dictionary, finding.subject)
    assumption = ""
    if finding.assumption:
        assumption = (
            f" This check assumes that {finding.assumption}. No value in the fact base tests it."
        )
    return {
        "metric_a": text.name(lhs.metric_id),
        "path_a": text.path(lhs),
        "above_or_below": "below" if INEQUALITIES[finding.subject].at_least else "above",
        "metric_b": text.name(rhs.metric_id),
        "path_b": text.path(rhs),
        "identity_id": finding.subject,
        "equation": identity.equation,
        "used": f" The check also uses {'; '.join(text.path(p) for p in used)}." if used else "",
        "assumption": assumption,
    }


def _bridge_fields(finding: Finding, text: _Text) -> dict[str, str]:
    closing, (computed,) = finding.left, finding.right
    terms = [
        f"{text.value(direct_path(o, text.dictionary))} ({text.locator(o)})"
        for o in (*computed.observations, closing.observations[0])
    ]
    residual = closing.value - computed.value
    return dict(
        zip(("t_1", "new", "exp", "react", "contr", "churn", "t"), terms, strict=True),
        computed=text.value(computed),
        overstates_or_understates=BRIDGE_DIRECTION[residual < 0],
        abs_residual=text.value(closing, abs(residual)),
    )


def _conflict_fields(finding: Finding, text: _Text) -> dict[str, str]:
    """T8. The metric a row matches is the metric of its basis rows (D2.6 step 4)."""
    matches = []
    for path in (*finding.right, finding.left):
        rows = path.reading.basis if path.reading else ()
        basis = min((direct_path(o, text.dictionary) for o in rows), key=rank)
        period = "" if basis.period == path.period else f" {_period(basis.period)}"
        matches.append(
            f"{_period(path.period)} {text.at(path)} matches "
            f"{text.name(basis.metric_id)}{period} {text.at(basis)}"
        )
    row = finding.left.observations[0]
    return {
        "label": row.stated_label,
        "document_id": row.document_id,
        "matches": "; ".join(matches),
    }


def _projection_fields(finding: Finding, text: _Text) -> dict[str, str]:
    """The rates are not stored: both are a pure function of the three cited rows."""
    first, last = (p.observations[0] for p in finding.right)
    projection = finding.left.observations[0]
    one_place = Decimal("0.1")
    implied = cagr(last, projection).quantize(one_place, ROUND_HALF_EVEN)
    realized = cagr(first, last).quantize(one_place, ROUND_HALF_EVEN)

    return {
        "metric": text.name(finding.subject),
        "path_p": text.path(finding.left),
        "implied": f"{implied:f}%",
        "path_last": text.path(finding.right[1]),
        "path_first": text.path(finding.right[0]),
        "realized": f"{realized:f}%",
    }


def _basis_fields(finding: Finding, text: _Text) -> dict[str, str]:
    reported, (first, *further) = finding.left, finding.right
    return {
        "metric": text.name(finding.subject),
        "path_r": text.path(reported),
        "path_o": text.path(first),
        "basis": _basis_name(first),
        "also": "".join(f" The {_basis_name(p)} value is {text.path(p)}." for p in further),
        "gap": text.value(reported, abs(reported.value - first.value)),
    }


def question(finding: Finding, dictionary: Dictionary) -> str:
    """The question for management (S2-06). A fixed template: the same finding gives the
    same text on every run, and the text never holds a merged value.
    """
    text = _Text(finding, dictionary)
    fields = {
        FindingKind.DIVERGENCE: _pair_fields,
        FindingKind.AMBIGUITY: _ambiguity_fields,
        FindingKind.INVARIANT: _invariant_fields,
        FindingKind.BRIDGE: _bridge_fields,
        FindingKind.LABEL_CONFLICT: _conflict_fields,
        FindingKind.PROJECTION: _projection_fields,
        FindingKind.BASIS_GAP: _basis_fields,
    }[finding.kind](finding, text)
    return QUESTION_TEMPLATES[finding.kind, finding.divergence].format(
        period=_period(finding.period), **fields
    )


def absence_question(absence: Absence, dictionary: Dictionary) -> str:
    return ABSENCE_QUESTION.format(metric=metric_of(dictionary, absence.metric_id).canonical_name)


def path_texts(finding: Finding, dictionary: Dictionary) -> tuple[str, ...]:
    """The D6.2 text of each cited path, ``left`` first. An inferred row keeps its label."""
    text = _Text(finding, dictionary)
    return tuple(text.path(p) for p in (finding.left, *finding.right))
