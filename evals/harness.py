"""Score system flags against planted defects and guard against regressions.

A corpus case is a directory under ``evals/corpus/`` with a synthetic pack and a
``manifest.yaml`` that lists the planted defects. Clean control cases have an empty list.
A manifest can name a ``base`` case: the pack is then the base rows with the case rows on top.
``remove`` drops base rows by id, and ``sector`` runs the absence check (S4-01).
A manifest can name a ``deck`` instead. The rows then come from ``extract_deck`` on a recorded
LLM response (S3-03). So a wrong extraction scores as a flag.
A Corroborated fact scores as a ``corroboration`` flag, so a true one is planted (S5-04).
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from fact_ledger.domain import DivergenceClass, FindingKind
from fact_ledger.domain.paths import Comparison, Finding
from fact_ledger.domain.patterns import patterns
from fact_ledger.domain.validator import validate
from fact_ledger.extract import Complete, extract_deck, replay
from fact_ledger.store.yaml_files import load_dictionary, read_transcript

EVALS_DIR = Path(__file__).resolve().parent
ROOT = EVALS_DIR.parent
CORPUS_DIR = EVALS_DIR / "corpus"
BASELINE_FILE = EVALS_DIR / "baseline.json"
DICTIONARY_DIR = ROOT / "data" / "dictionary"

# D7.1: one defect type per finding kind and class, or per invariant id. A projection finding
# has no class, so its metric is the key. No fallback: an unmapped finding raises, so it is
# never scored silently.
DEFECT_TYPES: dict[tuple[str, str], str] = {
    ("divergence", "inconsistent"): "arithmetic",
    ("divergence", "definitional"): "definitional_switch",
    ("divergence", "contested"): "cross_origin_contradiction",
    ("divergence", "unresolvable"): "unresolvable",
    ("ambiguity", "definitional"): "definitional_switch",
    ("label_conflict", "definitional"): "definitional_switch",
    ("basis_gap", "definitional"): "basis_gap",
    ("invariant", "customers_paying_le_users_registered"): "denominator_drift",
    ("invariant", "seats_active_le_seats_licensed"): "denominator_drift",
    ("invariant", "nrr_ge_grr"): "arithmetic",
    ("invariant", "arr_ge_revenue_recognised"): "definitional_switch",
    ("bridge", "mrr_bridge"): "arithmetic",
    ("projection", "arr"): "projection_break",
}


@dataclass(frozen=True)
class Defect:
    """A planted defect, or a flag raised by the system. Matched on type and location. A deck
    case also matches on the subject value, because one page holds many values.
    """

    defect_type: str
    location: str
    value: str = ""


@dataclass(frozen=True)
class Scores:
    planted: int
    flagged: int
    detected: int
    false_positives: int

    @property
    def detection_rate(self) -> float:
        return self.detected / self.planted if self.planted else 1.0

    @property
    def false_positive_rate(self) -> float:
        return self.false_positives / self.flagged if self.flagged else 0.0


def score(planted: Counter[Defect], flags: Counter[Defect]) -> Scores:
    """Multisets: two findings at one location are two flags, so an extra one is never hidden."""
    return Scores(
        planted=planted.total(),
        flagged=flags.total(),
        detected=(planted & flags).total(),
        false_positives=(flags - planted).total(),
    )


def regressions(scores: Scores, baseline: dict[str, float | None], margin: float) -> list[str]:
    problems: list[str] = []
    base_detection = baseline.get("detection_rate")
    base_fp = baseline.get("false_positive_rate")
    if base_detection is not None and scores.detection_rate < base_detection - margin:
        problems.append(f"detection rate {scores.detection_rate:.3f} < baseline {base_detection}")
    if base_fp is not None and scores.false_positive_rate > base_fp + margin:
        problems.append(
            f"false-positive rate {scores.false_positive_rate:.3f} > baseline {base_fp}"
        )
    return problems


def _manifest(case_dir: Path) -> dict[str, Any]:
    return yaml.safe_load((case_dir / "manifest.yaml").read_text(encoding="utf-8")) or {}


def _defects(case_dir: Path) -> Counter[Defect]:
    manifest = _manifest(case_dir)
    defects = manifest.get("defects", [])
    # Only a deck flag carries a value, so a value here would stop every match without a sign.
    if "deck" not in manifest and any("value" in d for d in defects):
        raise ValueError(f"{case_dir.name}: a defect has 'value', but the manifest has no 'deck'")
    return Counter(
        Defect(str(d["defect_type"]), str(d["location"]), str(d.get("value", ""))) for d in defects
    )


def load_cases(corpus_dir: Path) -> dict[str, Counter[Defect]]:
    return {
        manifest.parent.name: _defects(manifest.parent)
        for manifest in sorted(corpus_dir.glob("*/manifest.yaml"))
    }


def defect_type(finding: Finding) -> str:
    detail = finding.subject if finding.divergence is None else finding.divergence
    return DEFECT_TYPES[finding.kind, detail]


def location(finding: Finding) -> str:
    """D7.2: one ``<document_id>#<locator>`` per flag, from the finding alone.

    A pair gives its subject, a computed subject its first input. An ambiguity, a label
    conflict, an invariant and a projection give ``left``. A bridge gives the locator most of
    its seven values share, and ``mrr[t]`` on a tie.
    """
    if finding.kind is not FindingKind.BRIDGE:
        return finding.left.locators[0]
    closing = finding.left.locators[0]
    counts = Counter((closing, *finding.right[0].locators))
    most = max(counts.values())
    return closing if counts[closing] == most else min(k for k, n in counts.items() if n == most)


def corroboration_flags(comparisons: Iterable[Comparison]) -> Counter[Defect]:
    """One flag for each fact and each pair of effective origins (decision 24).

    One echo meets several paths of one fact, and it is one error. A computed path holds the
    origins of all its inputs, so both sides are expanded into pairs of one origin and one
    origin: without that, one key can cover two different pairs. The pair is part of the
    location, so an unplanted pair never replaces a planted pair at the same fact.
    """
    pairs = {
        (
            c.a.observations[0].entity_id,
            c.a.metric_id,
            c.a.period,
            c.a.qualifier,
            frozenset({first, second}),
        )
        for c in comparisons
        if c.divergence is DivergenceClass.CORROBORATED
        for first in c.a.origin_ids
        for second in c.b.origin_ids
        if first != second
    }
    return Counter(
        Defect("corroboration", f"{e}#{m}#{p.end}#{'+'.join(sorted(o))}") for e, m, p, _, o in pairs
    )


def run_system(case_dir: Path) -> Counter[Defect]:
    manifest = _manifest(case_dir)
    dictionary = load_dictionary(DICTIONARY_DIR)
    if deck := manifest.get("deck"):
        complete: Complete = replay(ROOT / deck["responses"])
        extraction = extract_deck(ROOT / deck["pdf"], dictionary, deck["source"], complete)
        rows = [row for row, _printed in extraction.rows]
    else:
        base = manifest.get("base")
        packs = [case_dir.parent / base, case_dir] if base else [case_dir]
        pack = {o.observation_id: o for p in packs for o in read_transcript(p / "transcript.yaml")}
        for observation_id in manifest.get("remove", []):
            pack.pop(observation_id)  # an unknown id raises, so a typo never scores silently
        rows = list(pack.values())
    report = validate(rows, dictionary)
    absences, projections = patterns(rows, dictionary, manifest.get("sector"))
    findings = [*report.findings, *projections]
    # An absence has no row to cite, so its location names the entity and the metric (S4-01).
    flags = Counter(
        [Defect(defect_type(f), location(f), str(f.left.value) if deck else "") for f in findings]
        + [Defect("removed_expected_metric", f"{a.entity_id}#{a.metric_id}") for a in absences]
    )
    # Corroborated gives no finding, so the comparisons give the rest of the flags.
    flags.update(corroboration_flags(report.comparisons))
    return flags


def main() -> int:
    cases = load_cases(CORPUS_DIR)
    if not cases:
        print("eval: no corpus cases yet, nothing to score")
        return 0
    planted: Counter[Defect] = Counter()
    flags: Counter[Defect] = Counter()
    for name, defects in cases.items():
        planted += Counter(
            Defect(d.defect_type, f"{name}:{d.location}", d.value) for d in defects.elements()
        )
        flags += Counter(
            Defect(f.defect_type, f"{name}:{f.location}", f.value)
            for f in run_system(CORPUS_DIR / name).elements()
        )
    scores = score(planted, flags)
    baseline = json.loads(BASELINE_FILE.read_text(encoding="utf-8"))
    print(
        f"eval: detection {scores.detection_rate:.3f}, "
        f"false positives {scores.false_positive_rate:.3f} over {len(cases)} cases"
    )
    problems = regressions(scores, baseline, float(baseline["margin"]))
    for problem in problems:
        print(f"eval: REGRESSION {problem}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
