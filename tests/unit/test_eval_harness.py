import json
import shutil
from collections import Counter
from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from evals.harness import (
    CORPUS_DIR,
    DEFECT_TYPES,
    DICTIONARY_DIR,
    ROOT,
    Defect,
    corroboration_flags,
    load_cases,
    regressions,
    run_system,
    score,
)
from fact_ledger.domain import DivergenceClass
from fact_ledger.domain.checks import BRIDGE_ID, INEQUALITIES
from fact_ledger.domain.paths import Comparison, direct_path
from fact_ledger.domain.rules import PROJECTION_METRICS
from fact_ledger.store.yaml_files import load_dictionary, read_transcript

pytestmark = pytest.mark.unit

A = Defect("definitional_switch", "deck.pdf#p11")
B = Defect("arithmetic", "deck.pdf#p4")
NOISE = Defect("arithmetic", "deck.pdf#p9")


def test_score_counts_detections_and_false_positives() -> None:
    scores = score(Counter([A, B]), Counter([A, NOISE]))
    assert (scores.detection_rate, scores.false_positive_rate) == (0.5, 0.5)


def test_two_flags_at_one_location_are_two_flags() -> None:
    scores = score(Counter([B]), Counter([B, B]))
    assert (scores.flagged, scores.detected, scores.false_positives) == (2, 1, 1)


def test_empty_inputs_do_not_divide_by_zero() -> None:
    scores = score(Counter(), Counter())
    assert (scores.detection_rate, scores.false_positive_rate) == (1.0, 0.0)


def test_regression_detected_beyond_margin() -> None:
    scores = score(Counter([A, B]), Counter([A, NOISE]))
    baseline: dict[str, float | None] = {"detection_rate": 1.0, "false_positive_rate": 0.0}
    assert len(regressions(scores, baseline, margin=0.02)) == 2


def test_no_baseline_means_no_regression() -> None:
    baseline: dict[str, float | None] = {"detection_rate": None, "false_positive_rate": None}
    assert regressions(score(Counter([A]), Counter()), baseline, margin=0.02) == []


def test_load_cases_reads_manifests(tmp_path: Path) -> None:
    case = tmp_path / "case-1"
    case.mkdir()
    (case / "manifest.yaml").write_text(
        "defects:\n  - defect_type: arithmetic\n    location: deck.pdf#p4\n", encoding="utf-8"
    )
    (tmp_path / "clean").mkdir()
    (tmp_path / "clean" / "manifest.yaml").write_text("defects: []\n", encoding="utf-8")
    assert load_cases(tmp_path) == {"case-1": Counter([B]), "clean": Counter()}


def test_load_cases_rejects_a_value_without_a_deck(tmp_path: Path) -> None:
    case = tmp_path / "case-1"
    case.mkdir()
    (case / "manifest.yaml").write_text(
        "defects:\n  - defect_type: arithmetic\n    location: deck.pdf#p4\n    value: '7450000'\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="no 'deck'"):
        load_cases(tmp_path)


def test_every_finding_kind_maps_to_one_defect_type() -> None:
    outside = {c for c in DivergenceClass if c not in {"corroborated", "consistent"}}
    assert set(DEFECT_TYPES) == {
        *(("divergence", str(c)) for c in outside),
        ("ambiguity", "definitional"),
        ("label_conflict", "definitional"),
        *(("invariant", i) for i in INEQUALITIES),
        ("bridge", BRIDGE_ID),
        *(("projection", m) for m in PROJECTION_METRICS),
        ("basis_gap", "definitional"),
    }


@pytest.mark.parametrize("case", sorted(load_cases(CORPUS_DIR)))
def test_each_corpus_case_flags_exactly_its_planted_defects(case: str) -> None:
    assert run_system(CORPUS_DIR / case) == load_cases(CORPUS_DIR)[case]


@pytest.mark.parametrize("case", sorted(load_cases(CORPUS_DIR)))
def test_each_corpus_case_is_marked_synthetic(case: str) -> None:
    transcript = CORPUS_DIR / case / "transcript.yaml"
    # A deck case has no transcript, so its manifest carries the mark.
    pack = transcript if transcript.exists() else transcript.with_name("manifest.yaml")
    assert pack.read_text(encoding="utf-8").startswith(
        "# Synthetic corpus case. No real company data."
    )


def test_a_deck_flag_on_the_planted_page_with_another_value_is_not_the_planted_defect(
    tmp_path: Path,
) -> None:
    case = CORPUS_DIR / "deck-pdf-restated-arr"
    manifest = yaml.safe_load((case / "manifest.yaml").read_text(encoding="utf-8"))
    recording = json.loads((ROOT / manifest["deck"]["responses"]).read_text(encoding="utf-8"))
    recording["pages"][3]["values"][0]["scale"] = ""  # "7,450" read without its "(€k)" header
    responses = tmp_path / "responses.json"
    responses.write_text(json.dumps(recording), encoding="utf-8")
    manifest["deck"]["responses"] = str(responses)
    (tmp_path / "manifest.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")

    flags = run_system(tmp_path)

    assert flags == Counter([Defect("arithmetic", "nimbus-pdf-2025#p4", "7450")])
    assert not flags & load_cases(CORPUS_DIR)["deck-pdf-restated-arr"]


REMOVED = Defect("removed_expected_metric", "nimbus#grr")


def test_the_planted_absence_case_flags_the_removed_grr_and_nothing_else() -> None:
    assert run_system(CORPUS_DIR / "absence-grr") == Counter([REMOVED])


def test_only_the_clean_control_and_the_absence_case_name_a_sector() -> None:
    named = {
        m.parent.name
        for m in CORPUS_DIR.glob("*/manifest.yaml")
        if "sector" in yaml.safe_load(m.read_text(encoding="utf-8"))
    }
    assert named == {"clean-nimbus", "absence-grr"}


def test_a_removed_id_that_is_not_in_the_pack_raises(tmp_path: Path) -> None:
    shutil.copytree(CORPUS_DIR / "clean-nimbus", tmp_path / "clean-nimbus")
    case = tmp_path / "case"
    case.mkdir()
    manifest = {
        "base": "clean-nimbus",
        "defects": [],
        "sector": "b2b_saas",
        "remove": ["nimbus-99"],
    }
    (case / "manifest.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
    (case / "transcript.yaml").write_text("defaults: {}\nobservations: []\n", encoding="utf-8")
    with pytest.raises(KeyError, match="nimbus-99"):
        run_system(case)


def test_an_echo_without_its_cited_origin_is_one_false_corroboration(tmp_path: Path) -> None:
    # Decision 24: p4, p1 and MRR x 12 give three Corroborated comparisons with one pair of
    # origins. They are one error, so one flag.
    (tmp_path / "clean-nimbus").symlink_to(CORPUS_DIR / "clean-nimbus")
    case = shutil.copytree(CORPUS_DIR / "decoy-echo-press-arr", tmp_path / "echo")
    transcript = case / "transcript.yaml"
    text = transcript.read_text(encoding="utf-8")
    transcript.write_text(text.replace("cited_origin_id: nimbus-management", ""), encoding="utf-8")

    assert run_system(case) == Counter(
        [Defect("corroboration", "nimbus#arr#2024-12-31#nimbus-management+techdaily")]
    )


def test_an_unplanted_pair_does_not_replace_a_planted_pair_at_one_fact(tmp_path: Path) -> None:
    # The pair is part of the location, so the case scores no detection and one false positive.
    (tmp_path / "clean-nimbus").symlink_to(CORPUS_DIR / "clean-nimbus")
    case = shutil.copytree(CORPUS_DIR / "corroboration-audited-revenue", tmp_path / "echo")
    transcript = case / "transcript.yaml"
    text = transcript.read_text(encoding="utf-8")
    transcript.write_text(text.replace("nimbus-audited-accounts", "techdaily"), encoding="utf-8")

    flags = run_system(case)

    assert flags == Counter(
        [
            Defect(
                "corroboration", "nimbus#revenue_recognised#2024-12-31#nimbus-management+techdaily"
            )
        ]
    )
    assert not flags & load_cases(CORPUS_DIR)["corroboration-audited-revenue"]


def test_a_computed_path_with_two_origins_gives_two_pairs() -> None:
    pack = {
        o.observation_id: o
        for o in read_transcript(CORPUS_DIR / "clean-nimbus" / "transcript.yaml")
    }
    dictionary = load_dictionary(DICTIONARY_DIR)
    mrr_from_a_second_origin = pack["nimbus-06"].model_copy(update={"origin_id": "nimbus-board"})
    computed = direct_path(pack["nimbus-02"], dictionary).model_copy(
        update={
            "identity_id": "arr_from_mrr",
            "observations": (pack["nimbus-08"], mrr_from_a_second_origin),
        }
    )
    press = direct_path(pack["nimbus-03"].model_copy(update={"origin_id": "techdaily"}), dictionary)

    flags = corroboration_flags(
        [
            Comparison(
                a=computed, b=press, tolerance=Decimal(1), divergence=DivergenceClass.CORROBORATED
            )
        ]
    )

    assert flags == Counter(
        [
            Defect("corroboration", "nimbus#arr#2024-12-31#nimbus-board+techdaily"),
            Defect("corroboration", "nimbus#arr#2024-12-31#nimbus-management+techdaily"),
        ]
    )
