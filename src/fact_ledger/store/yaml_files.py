"""Read the dictionary and transcript YAML files (ruamel.yaml is the only
YAML library in ``src/``). The plain loaders use ``typ="safe"``: transcripts and reads of
the dictionary are read-only, so round-trip mode (comments, quote style) is not needed.
Writes to the dictionary (``add_aliases``, ``add_metric``) use round-trip mode, so a CLI
write keeps the domain-expert's comments, key order, flow lists and quotes.
"""

from collections.abc import Mapping, Sequence
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from pydantic_core import PydanticUndefined
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.error import YAMLError
from ruamel.yaml.scalarstring import DoubleQuotedScalarString

from fact_ledger.domain import Dictionary, Identity, Metric, Observation

_yaml = YAML(typ="safe")

_yaml_rt = YAML()
_yaml_rt.indent(mapping=2, sequence=4, offset=2)
_yaml_rt.width = 4096  # large on purpose: never re-wrap the long alias lines
_yaml_rt.preserve_quotes = True
# One date object in two fields would become an anchor and an alias, and an edit to one
# field in review would change the other unseen. The dictionary has no anchors to keep.
_yaml_rt.representer.ignore_aliases = lambda _data: True

# A YAML float drops trailing zeros ("8.30" -> 8.3), which would silently change a
# stated value or its precision. Only a quoted string or an integer is accepted.
_DECIMAL_FIELDS = ("value", "stated_precision")


def load_dictionary(directory: Path) -> Dictionary:
    """Build a ``Dictionary`` from ``metrics.yaml`` and ``identities.yaml`` in ``directory``."""
    metrics_data = _yaml.load(directory / "metrics.yaml")
    identities_data = _yaml.load(directory / "identities.yaml")
    metrics = tuple(Metric(**item) for item in metrics_data["metrics"])
    identities = tuple(Identity(**item) for item in identities_data["identities"])
    return Dictionary(metrics=metrics, identities=identities)


def read_transcript(path: Path) -> list[Observation]:
    """Read a transcribed deck into observations.

    Each row is ``{**defaults, **row}``: one deck states its shared fields once, so a
    wrong value does not have to be caught on every one of its repeats. Every row is
    validated; every row error is collected and raised together in one ``ValueError``,
    so one run names every mistake instead of only the first.
    """
    try:
        data = _yaml.load(path)
    except (OSError, YAMLError) as exc:
        msg = f"cannot read {path}: {exc}"
        raise ValueError(msg) from exc
    if not (
        isinstance(data, dict)
        and isinstance(data.get("defaults"), dict)
        and isinstance(data.get("observations"), list)
    ):
        msg = f"{path}: a transcript needs a 'defaults' map and an 'observations' list"
        raise ValueError(msg)
    defaults: dict[str, Any] = data["defaults"]
    errors: list[str] = []
    observations: list[Observation] = []
    for index, row in enumerate(data["observations"], start=1):
        if not isinstance(row, dict):
            errors.append(f"row {index}: a row must be a map of Observation fields")
            continue
        merged: dict[str, Any] = {**defaults, **row}
        label = f"row {index}"
        observation_id = merged.get("observation_id")
        if observation_id:
            label += f" ({observation_id})"

        float_fields = [f for f in _DECIMAL_FIELDS if isinstance(merged.get(f), float)]
        for field in float_fields:
            errors.append(f"{label}: {field}: a float is not allowed, use a quoted string")
        if float_fields:
            continue  # a coerced float would hide as a valid Decimal below

        try:
            observations.append(Observation(**merged))
        except ValidationError as exc:
            for error in exc.errors():
                field = ".".join(str(part) for part in error["loc"]) or "<row>"
                errors.append(f"{label}: {field}: {error['msg']}")

    if errors:
        raise ValueError("\n".join(errors))
    return observations


def _flow_list(values: Sequence[str]) -> CommentedSeq:
    """A ``[a, b, c]`` inline list, the style every ``aliases`` and ``expected_for`` uses."""
    seq = CommentedSeq(values)
    seq.fa.set_flow_style()
    return seq


def _flow_map(data: Mapping[str, object]) -> CommentedMap:
    """A ``{a: 1, b: 2}`` inline map, the style ``defaults`` uses in a transcript."""
    node = CommentedMap(data)
    node.fa.set_flow_style()
    return node


def _validate_and_write(directory: Path, metrics_data: CommentedMap) -> None:
    """Build a ``Dictionary`` from the changed metrics node before writing it:
    an alias conflict or a duplicate id then fails with the file untouched.
    """
    identities_data = _yaml.load(directory / "identities.yaml")
    metrics = tuple(Metric(**item) for item in metrics_data["metrics"])
    identities = tuple(Identity(**item) for item in identities_data["identities"])
    Dictionary(metrics=metrics, identities=identities)  # raises ValueError on conflict

    path = directory / "metrics.yaml"
    tmp_path = path.with_name(path.name + ".tmp")
    with tmp_path.open("wb") as handle:
        _yaml_rt.dump(metrics_data, handle)
    tmp_path.replace(path)  # atomic: a crash cannot leave half a file


def add_aliases(directory: Path, metric_id: str, labels: Sequence[str]) -> None:
    """Append ``labels`` missing (casefold compare) from ``metric_id``'s aliases.
    Raises ``ValueError`` and leaves the file unchanged if ``metric_id`` is not
    in the dictionary, or if a label is already an alias of a different metric.
    """
    data = _yaml_rt.load(directory / "metrics.yaml")
    node = next((m for m in data["metrics"] if m["metric_id"] == metric_id), None)
    if node is None:
        msg = f"metric_id {metric_id!r} is not in the dictionary"
        raise ValueError(msg)

    aliases = node.setdefault("aliases", _flow_list([]))
    existing = {alias.casefold() for alias in aliases}
    for label in labels:
        if label.casefold() not in existing:
            aliases.append(label)
            existing.add(label.casefold())

    _validate_and_write(directory, data)


def _row_scalar(name: str, value: object) -> object:
    if name in _DECIMAL_FIELDS:
        return DoubleQuotedScalarString(str(value))
    if isinstance(value, tuple):
        return _flow_list(list(value))
    if isinstance(value, Enum):
        return str(value)
    return value


def _row_node(observation: Observation, defaults: Mapping[str, object]) -> CommentedMap:
    """One row: every ``Observation`` field except a value equal to ``defaults`` or to the
    model's own default (the ``synthetic_deck.yaml`` layout).
    """
    node = CommentedMap()
    for name, field in Observation.model_fields.items():
        value = getattr(observation, name)
        if name in defaults and value == defaults[name]:
            continue
        if field.default is not PydanticUndefined and value == field.default:
            continue
        node[name] = _row_scalar(name, value)
    node.fa.set_flow_style()
    return node


def write_transcript(
    path: Path,
    header: str,
    defaults: Mapping[str, object],
    rows: Sequence[tuple[Observation, str]],
) -> None:
    """Write ``defaults`` once and each row as a flow map, so ``read_transcript`` loads the
    file with no edit. ``printed`` is an end-of-line comment,
    the only place it is kept: ``Observation`` has no field for it.
    """
    doc = CommentedMap()
    doc.yaml_set_start_comment(header)
    doc["defaults"] = _flow_map(defaults)
    observations = CommentedSeq()
    for observation, printed in rows:
        observations.append(_row_node(observation, defaults))
        observations.yaml_add_eol_comment(f'printed "{printed}"', len(observations) - 1)
    doc["observations"] = observations

    with path.open("wb") as handle:
        _yaml_rt.dump(doc, handle)


def add_metric(directory: Path, metric: Metric) -> None:
    """Append ``metric`` to ``metrics.yaml``, aliases as a flow list.
    Raises ``ValueError`` and leaves the file unchanged if ``metric_id`` is
    already in the dictionary.
    """
    data = _yaml_rt.load(directory / "metrics.yaml")
    node = CommentedMap()
    node["metric_id"] = metric.metric_id
    node["canonical_name"] = metric.canonical_name
    node["aliases"] = _flow_list(metric.aliases)
    node["dimension"] = metric.dimension.value
    node["stock_or_flow"] = metric.stock_or_flow.value
    if metric.definition_note:
        node["definition_note"] = metric.definition_note
    if metric.expected_for:
        node["expected_for"] = _flow_list(metric.expected_for)
    data["metrics"].append(node)

    _validate_and_write(directory, data)
