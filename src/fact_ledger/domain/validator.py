"""The A2 validator: readings of ambiguous rows, comparisons and findings.

Pure domain code. ``validate`` gets observations and the dictionary and returns
a ``Report``. It never reads the store, and it never writes a reading back.
"""

from collections import defaultdict
from collections.abc import Iterable
from datetime import date
from itertools import combinations, groupby
from typing import NamedTuple

from fact_ledger.domain.checks import EqualityRun, build_index, equality_checks, run_checks
from fact_ledger.domain.enums import (
    Basis,
    DefinitionStatus,
    Dimension,
    DivergenceClass,
    FindingKind,
)
from fact_ledger.domain.models import Dictionary, Metric, Observation, Period, Qualifier
from fact_ledger.domain.paths import (
    CheckResult,
    Comparison,
    ComputationPath,
    Finding,
    Reading,
    Report,
    aligned_period,
    compare,
    direct_path,
    is_outside,
    metric_of,
    pair_tolerance,
    period_of,
    qualifier_of,
    rank,
    text_key,
)
from fact_ledger.domain.rules import MIN_RELIABILITY, STOCK_CANDIDATE_PERIOD_TYPES

_MATCH, _SEVERAL, _NO_MATCH, _NO_CANDIDATE = "match", "several", "no match", "no candidate"


class _Match(NamedTuple):
    """The direct result of the D2.6 match test for one ambiguous row."""

    result: str
    metric_id: str | None
    basis: tuple[Observation, ...]
    candidates: tuple[Observation, ...]  # best-ranked candidate observation per metric


def _match(
    row: Observation,
    index: dict[tuple[str, Period, Qualifier], list[Observation]],
    dictionary: Dictionary,
) -> _Match:
    """D2.6 steps 1 to 3. The index holds stored resolved rows only, so a match never chains.
    Check index key 2: a candidate is read from the row's own
    qualifier only, so a segment or basis row never matches across a qualifier boundary.
    """
    value = direct_path(row, dictionary)
    qualifier = qualifier_of(row)
    matched: dict[str, tuple[Observation, ...]] = {}
    best: list[Observation] = []
    for metric_id in row.candidate_metric_ids:
        if metric_id not in dictionary.metric_ids:
            continue
        fits = STOCK_CANDIDATE_PERIOD_TYPES.get(metric_id)
        if fits is not None and row.period_type not in fits:
            continue
        metric = metric_of(dictionary, metric_id)
        found = [
            direct_path(c, dictionary)
            for c in index.get((metric_id, aligned_period(row, metric), qualifier), [])
            if c.derivation is None
            and c.reliability >= MIN_RELIABILITY
            and (c.unit, c.currency) == (row.unit, row.currency)
        ]
        if not found:
            continue
        best.append(min(found, key=rank).observations[0])
        inside = [
            p
            for p in found
            if abs(p.value - value.value) <= pair_tolerance(p, value, metric.dimension)
        ]
        if inside:
            matched[metric_id] = tuple(p.observations[0] for p in inside)
    if len(matched) == 1:
        ((metric_id, basis),) = matched.items()
        return _Match(_MATCH, metric_id, basis, tuple(best))
    result = _SEVERAL if matched else _NO_MATCH if best else _NO_CANDIDATE
    return _Match(result, None, (), tuple(best))


def _readings(
    ambiguous: list[Observation], matches: dict[str, _Match]
) -> tuple[dict[str, Reading], list[list[Observation]]]:
    """D2.7: readings per label group, and the matched rows of each label conflict. The
    qualifier is part of the key (check index key 3): without
    it, a group row with no direct match would inherit the reading of a segment row that
    happens to share its label, through ``Reading.sources``.
    """
    groups: defaultdict[tuple[str, str, str, Qualifier], list[Observation]] = defaultdict(list)
    for row in ambiguous:
        key = row.document_id, row.metric_id, text_key(row.stated_label), qualifier_of(row)
        groups[key].append(row)
    readings: dict[str, Reading] = {}
    conflicts: list[list[Observation]] = []
    for rows in groups.values():
        direct = [r for r in rows if matches[r.observation_id].result == _MATCH]
        found = {matches[r.observation_id].metric_id for r in direct}
        for row in rows:
            match = matches[row.observation_id]
            if len(found) > 1:
                readings[row.observation_id] = Reading(
                    observation=row,
                    inferred=False,
                    metric_id=match.metric_id,
                    basis=match.basis,
                    reason="label conflict",
                )
            elif match.result == _MATCH:
                readings[row.observation_id] = Reading(
                    observation=row, inferred=True, metric_id=match.metric_id, basis=match.basis
                )
            elif not found:
                readings[row.observation_id] = Reading(
                    observation=row, inferred=False, reason=match.result
                )
        if len(found) > 1:
            conflicts.append(sorted(direct, key=lambda r: (r.period_end, r.observation_id)))
        elif found:
            (metric_id,) = found
            sources = tuple(readings[r.observation_id] for r in direct)
            for row in rows:
                if row.observation_id in readings:
                    continue
                readings[row.observation_id] = (
                    Reading(observation=row, inferred=True, metric_id=metric_id, sources=sources)
                    if metric_id in row.candidate_metric_ids
                    else Reading(
                        observation=row, inferred=False, reason=f"{metric_id} not a candidate"
                    )
                )
    return readings, conflicts


def _comparison_dimension(path: ComputationPath, metric: Metric) -> Dimension:
    """D1.1: an unresolved ambiguous row's own unit picks its tolerance. ``margin_unspecified``
    can hold a currency amount under its declared percent dimension.
    """
    if metric.dimension is Dimension.PERCENT and path.unit != "percent":
        return Dimension.CURRENCY
    return metric.dimension


def _skip_reason(
    a: ComputationPath, b: ComputationPath, dictionary: Dictionary, dimension: Dimension
) -> str:
    """D2.9: an inferred row never meets its basis, and never restates a gap of its basis."""
    for x, y in ((a, b), (b, a)):
        if x.reading is None or not x.reading.inferred:
            continue
        linked = {o.observation_id for o in x.reading.basis}
        linked |= {s.observation.observation_id for s in x.reading.sources}
        if y.identity_id is None and y.observations[0].observation_id in linked:
            return "basis of the reading"
        if any(
            is_outside(compare(direct_path(o, dictionary), y, dimension)) for o in x.reading.basis
        ):
            return "basis differs from this value"
    return ""


def _subject_findings(entity_id: str, comparisons: list[Comparison]) -> list[Finding]:
    """D2.5: one finding per disagreeing value, not one per pair."""
    paths: dict[tuple[str, tuple[str, ...]], ComputationPath] = {}
    differs: defaultdict[tuple[str, tuple[str, ...]], set[tuple[str, tuple[str, ...]]]]
    differs = defaultdict(set)
    classes: dict[frozenset[tuple[str, tuple[str, ...]]], DivergenceClass] = {}
    for comparison in comparisons:
        if comparison.divergence is None or not is_outside(comparison):
            continue
        a, b = comparison.a, comparison.b
        paths[a.key], paths[b.key] = a, b
        differs[a.key].add(b.key)
        differs[b.key].add(a.key)
        classes[frozenset((a.key, b.key))] = comparison.divergence
    findings = []
    while any(differs.values()):
        subject = paths[
            max(
                differs,
                key=lambda k: (
                    len(differs[k]),
                    -paths[k].reliability,
                    max(o.published_date for o in paths[k].observations),
                    paths[k].identity_id is None,
                    k[1][0],
                ),
            )
        ]
        counterpart, *others = sorted((paths[k] for k in differs[subject.key]), key=rank)
        others.sort(key=lambda p: (p.identity_id is not None, p.key[1]))
        cited = [counterpart, *others]
        for other in cited:
            differs[other.key].discard(subject.key)
        differs[subject.key].clear()
        findings.append(
            Finding(
                kind=FindingKind.DIVERGENCE,
                divergence=classes[frozenset((subject.key, cited[0].key))],
                entity_id=entity_id,
                subject=subject.metric_id,
                period=subject.period,
                left=subject,
                right=tuple(cited),
            )
        )
    return findings


def _dedup_key(finding: Finding) -> tuple[object, ...] | None:
    """D6.6: a backstop to the subject rule. Findings of two kinds never merge. The qualifier
    guards a page that carries more than one segment, region or basis: two violations there can
    share a locator, and without the qualifier in the key one would merge into the other's
    question.
    """
    if finding.kind is FindingKind.DIVERGENCE:
        pair = frozenset((finding.left.locators, finding.right[0].locators))
        return "pair", finding.subject, finding.period, finding.left.qualifier, pair
    if finding.kind in {FindingKind.INVARIANT, FindingKind.BRIDGE}:
        cited = frozenset(loc for p in (finding.left, *finding.right) for loc in p.locators)
        return "check", finding.subject, finding.period, finding.left.qualifier, cited
    return None


def _dedup(findings: list[Finding]) -> list[Finding]:
    """The first finding of a key keeps the question. The paths of a later one join its list."""
    result: list[Finding] = []
    first: dict[tuple[object, ...], int] = {}
    for finding in findings:
        key = _dedup_key(finding)
        if key is None or key not in first:
            if key is not None:
                first[key] = len(result)
            result.append(finding)
            continue
        kept = result[first[key]]
        known = {p.key for p in (kept.left, *kept.right)}
        extra = tuple(p for p in (finding.left, *finding.right) if p.key not in known)
        result[first[key]] = kept.model_copy(update={"right": kept.right + extra})
    return result


def _basis_gaps(
    entity_id: str,
    resolved: dict[tuple[str, Period, Qualifier], list[Observation]],
    dictionary: Dictionary,
) -> list[Finding]:
    """A reported value and the same value on another basis. The key holds the whole
    period, so the pairs are aligned and no ``compare`` call is needed. Stored resolved rows
    only: a computed path restates its input, and a reading never joins a finding.
    """
    findings = []
    for (metric_id, period, qualifier), rows in resolved.items():
        if qualifier.basis is not Basis.REPORTED:
            continue
        dimension = metric_of(dictionary, metric_id).dimension
        others = [
            direct_path(r, dictionary)
            for basis in Basis
            for r in resolved.get((metric_id, period, qualifier._replace(basis=basis)), [])
            if basis is not Basis.REPORTED
        ]
        # The key holds no unit or currency, so one key can hold two reported rows in two
        # currencies. Each (unit, currency) group gets its own reference, or a reported USD
        # row ranked ahead of a reported EUR row would hide the EUR gap.
        by_basis: defaultdict[tuple[str | None, str | None], list[ComputationPath]] = defaultdict(
            list
        )
        for r in rows:
            path = direct_path(r, dictionary)
            by_basis[path.unit, path.currency].append(path)
        for group_key, group_paths in by_basis.items():
            left = min(group_paths, key=rank)
            gaps = [
                p
                for p in others
                if (p.unit, p.currency) == group_key
                and abs(p.value - left.value) > pair_tolerance(left, p, dimension)
            ]
            if gaps:
                findings.append(
                    Finding(
                        kind=FindingKind.BASIS_GAP,
                        divergence=DivergenceClass.DEFINITIONAL,
                        entity_id=entity_id,
                        subject=metric_id,
                        period=left.period,
                        left=left,
                        right=tuple(sorted(gaps, key=rank)),
                    )
                )
    return findings


def _validate_entity(
    entity_id: str, rows: list[Observation], dictionary: Dictionary
) -> tuple[list[Reading], list[Comparison], list[Finding], list[CheckResult]]:
    """D2.12: direct results, then readings, then checks and comparisons. No step reads its
    own results.
    """
    resolved: dict[tuple[str, Period, Qualifier], list[Observation]] = {}
    for row in rows:
        if row.definition_status is DefinitionStatus.RESOLVED:
            resolved.setdefault((row.metric_id, period_of(row), qualifier_of(row)), []).append(row)
    ambiguous = [r for r in rows if r.definition_status is DefinitionStatus.AMBIGUOUS]
    matches = {r.observation_id: _match(r, resolved, dictionary) for r in ambiguous}
    readings, conflicts = _readings(ambiguous, matches)
    paths = {
        r.observation_id: direct_path(r, dictionary, readings.get(r.observation_id)) for r in rows
    }
    # One index per qualifier, checks run once for each, and the
    # qualifier of the index is tagged onto every result the caller gets back.
    checks: list[CheckResult] = []
    findings: list[Finding] = []
    runs: list[EqualityRun] = []
    for qualifier, index in build_index(rows, paths, dictionary).items():
        q_checks, q_findings, q_runs = run_checks(entity_id, index, dictionary)
        checks += [c.model_copy(update={"qualifier": qualifier}) for c in q_checks]
        findings += q_findings
        runs += [run._replace(qualifier=qualifier) for run in q_runs]

    groups: defaultdict[tuple[str, date, bool, Qualifier], list[ComputationPath]] = defaultdict(
        list
    )
    for path in (*paths.values(), *(p for run in runs for p in run.paths)):
        stays_ambiguous = path.reading is not None and not path.inferred
        groups[path.metric_id, path.period.end, stays_ambiguous, path.qualifier].append(path)
    comparisons: list[Comparison] = []
    for key in sorted(groups):
        metric = metric_of(dictionary, key[0])
        group: list[Comparison] = []
        for a, b in combinations(sorted(groups[key], key=lambda p: p.key), 2):
            dimension = _comparison_dimension(a, metric)
            reason = _skip_reason(a, b, dictionary, dimension)
            group.append(
                Comparison(a=a, b=b, tolerance=None, divergence=None, reason=reason)
                if reason
                else compare(a, b, dimension)
            )
        comparisons += group
        findings += _subject_findings(entity_id, group)
    checks += equality_checks(entity_id, runs, comparisons)

    for row in ambiguous:
        match = matches[row.observation_id]
        if match.result == _NO_MATCH and not readings[row.observation_id].inferred:
            findings.append(_ambiguity(entity_id, paths[row.observation_id], match, dictionary))
    for matched in conflicts:
        *others, located = (paths[r.observation_id] for r in matched)
        findings.append(
            Finding(
                kind=FindingKind.LABEL_CONFLICT,
                divergence=DivergenceClass.DEFINITIONAL,
                entity_id=entity_id,
                subject=located.metric_id,
                period=located.period,
                left=located,
                right=tuple(others),
            )
        )
    findings += _basis_gaps(entity_id, resolved, dictionary)
    findings.sort(
        key=lambda f: (f.subject, f.period.end, f.period.start, f.period.type, f.kind, f.left.key)
    )
    checks.sort(key=lambda c: (c.identity_id, c.qualifier, c.period is not None, c.period or ()))
    return [readings[r.observation_id] for r in ambiguous], comparisons, _dedup(findings), checks


def _ambiguity(
    entity_id: str, path: ComputationPath, match: _Match, dictionary: Dictionary
) -> Finding:
    """D2.10 item 1: an ambiguous value that matches no candidate metric."""
    return Finding(
        kind=FindingKind.AMBIGUITY,
        divergence=DivergenceClass.DEFINITIONAL,
        entity_id=entity_id,
        subject=path.metric_id,
        period=path.period,
        left=path,
        right=tuple(direct_path(c, dictionary) for c in match.candidates),
    )


def validate(observations: Iterable[Observation], dictionary: Dictionary) -> Report:
    """Run the validator on every entity.

    A row whose ``metric_id`` is not in the dictionary has no dimension and so no tolerance.
    S1-03 keeps it out of every check. A projection is a plan, not an actual value, so S4
    decision 16 keeps it out too. Rows are sorted first, so the input order never changes the
    report (D2.12).
    """
    rows = sorted(
        (o for o in observations if o.metric_id in dictionary.metric_ids and not o.is_projection),
        key=lambda o: (o.entity_id, o.observation_id),
    )
    readings: list[Reading] = []
    comparisons: list[Comparison] = []
    findings: list[Finding] = []
    checks: list[CheckResult] = []
    for entity_id, entity_rows in groupby(rows, key=lambda o: o.entity_id):
        entity = _validate_entity(entity_id, list(entity_rows), dictionary)
        readings += entity[0]
        comparisons += entity[1]
        findings += entity[2]
        checks += entity[3]
    return Report(
        readings=tuple(readings),
        comparisons=tuple(comparisons),
        findings=tuple(findings),
        checks=tuple(checks),
    )
