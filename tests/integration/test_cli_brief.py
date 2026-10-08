"""Acceptance tests for ``fact-ledger brief`` (S3-02).

The brief composes ``facts show`` and ``validate`` verbatim, with no new
table. Section bodies must be byte-identical to those commands' own stdout,
so the tests build the expected brief from their real output instead of re-implementing it.
"""

from decimal import Decimal
from pathlib import Path

import pytest
from typer.testing import CliRunner, Result

from fact_ledger.cli import app
from fact_ledger.domain import BiasDirection, Observation, SourceType
from fact_ledger.domain.patterns import patterns
from fact_ledger.domain.questions import absence_question, question
from fact_ledger.store.facts import FactStore
from fact_ledger.store.yaml_files import load_dictionary, read_transcript

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[2]
DICTIONARY = load_dictionary(ROOT / "data" / "dictionary")
NIMBUS = {
    o.observation_id: o
    for o in read_transcript(ROOT / "tests/fixtures/transcripts/synthetic_deck.yaml")
}
CLEAN = read_transcript(ROOT / "evals/corpus/clean-nimbus/transcript.yaml")
NO_SECTOR = "No sector given, so the absence check did not run.\n"
HEADINGS = [
    "## Fact table",
    "## Inconsistencies",
    "## Corroboration",
    "## Conspicuous absences",
    "## Patterns",
    "## Management questions",
]
# ARR 14.0m at 2025-12-31 in a deck published 2025-03-01: a plan that grows far faster than
# nimbus-01 to nimbus-02 (the projection-arr-plan case of the eval corpus).
ARR_PLAN = Observation(
    **(
        NIMBUS["nimbus-02"].model_dump()
        | {
            "observation_id": "nimbus-39",
            "value": "14000000",
            "stated_precision": "50000",
            "period_start": "2025-12-31",
            "period_end": "2025-12-31",
            "as_of_date": "2025-12-31",
            "locator": "p15 plan",
            "stated_label": "ARR",
        }
    )
)


def _load(store: FactStore, *extra: Observation) -> None:
    rows = dict(NIMBUS) | {o.observation_id: o for o in extra}
    store.add_many(list(rows.values()))


def _run_brief(entity_id: str, *options: str) -> Result:
    return CliRunner().invoke(app, ["brief", entity_id, *options])


def _sections(stdout: str) -> dict[str, str]:
    """Each ``## `` heading with its body, in print order."""
    return {
        f"## {part.split(chr(10), 1)[0]}": part.split("\n", 1)[1].rstrip("\n")
        for part in stdout.split("## ")[1:]
    }


def _questions_body(validate_stdout: str, entity_id: str) -> str:
    """The numbered, deduplicated question list the brief must print (S2 section 7:
    one finding, one question).
    """
    lines = validate_stdout.splitlines()
    if lines[0] == f"No findings for {entity_id}.":
        return f"No questions for {entity_id}.\n"
    header, *rows = lines
    column = header.split("\t").index("question")
    seen: dict[str, None] = {}
    for row in rows:
        seen.setdefault(row.split("\t")[column], None)
    return "".join(f"{number}. {text}\n" for number, text in enumerate(seen, start=1))


def _expected_stdout(entity_id: str) -> str:
    """The brief of an entity with no sector, no corroborated fact and no pattern finding."""
    facts = CliRunner().invoke(app, ["facts", "show", entity_id])
    validate = CliRunner().invoke(app, ["validate", entity_id])
    return (
        f"## Fact table\n{facts.stdout}\n"
        f"## Inconsistencies\n{validate.stdout}\n"
        f"## Corroboration\nNo corroborated facts for {entity_id}.\n\n"
        f"## Conspicuous absences\n{NO_SECTOR}\n"
        f"## Patterns\nNo patterns for {entity_id}.\n\n"
        f"## Management questions\n{_questions_body(validate.stdout, entity_id)}"
    )


def test_brief_has_six_sections_matching_facts_show_and_validate(store: FactStore) -> None:
    _load(store)

    result = _run_brief("nimbus")

    assert result.exit_code == 0
    assert result.stdout == _expected_stdout("nimbus")
    headings = [line for line in result.stdout.splitlines() if line.startswith("## ")]
    assert headings == HEADINGS
    assert "\n2. " in result.stdout  # the fixture must exercise more than one finding


def test_management_questions_list_each_finding_question_once(store: FactStore) -> None:
    _load(store)

    result = _run_brief("nimbus")

    validate_stdout = CliRunner().invoke(app, ["validate", "nimbus"]).stdout
    header, *rows = validate_stdout.splitlines()
    column = header.split("\t").index("question")
    findings_questions = [row.split("\t")[column] for row in rows]
    assert len(findings_questions) >= 2  # the fixture must exercise more than one finding

    questions_section = result.stdout.split("## Management questions\n", 1)[1]
    printed = questions_section.splitlines()
    assert printed == [f"{i}. {q}" for i, q in enumerate(dict.fromkeys(findings_questions), 1)]


def test_brief_stderr_matches_validate_notes(store: FactStore) -> None:
    _load(store)

    brief_stderr = _run_brief("nimbus").stderr
    validate_stderr = CliRunner().invoke(app, ["validate", "nimbus"]).stderr

    assert brief_stderr == validate_stderr
    assert "Checks: 5 held, 1 violated, 5 not checked." in brief_stderr
    assert "Ambiguous rows:" in brief_stderr


def test_brief_with_no_findings_prints_no_findings_and_no_questions(store: FactStore) -> None:
    store.add_many([NIMBUS["nimbus-02"].model_copy(update={"entity_id": "nimbus-clean"})])

    result = _run_brief("nimbus-clean")

    assert result.exit_code == 0
    assert result.stdout == _expected_stdout("nimbus-clean")
    assert "## Inconsistencies\nNo findings for nimbus-clean.\n" in result.stdout
    assert "## Management questions\nNo questions for nimbus-clean.\n" in result.stdout


def test_brief_with_a_sector_lists_absences_and_patterns_and_their_questions(
    store: FactStore,
) -> None:
    _load(store, ARR_PLAN)
    rows = store.find(entity_id="nimbus")
    absences, findings = patterns(rows, DICTIONARY, "b2b_saas")
    assert absences
    assert [f.subject for f in findings] == ["arr"]

    result = _run_brief("nimbus", "--sector", "b2b_saas")

    assert result.exit_code == 0
    sections = _sections(result.stdout)
    assert list(sections) == HEADINGS
    names = {m.metric_id: m.canonical_name for m in DICTIONARY.metrics}
    assert sections["## Conspicuous absences"].splitlines() == [
        "metric_id\tname",
        *(f"{a.metric_id}\t{names[a.metric_id]}" for a in absences),
    ]
    header, *pattern_rows = sections["## Patterns"].splitlines()
    cells = [row.split("\t") for row in pattern_rows]
    assert header.startswith("kind\tclass\tsubject\t")
    assert [(c[0], c[2]) for c in cells] == [("projection", "arr")]
    assert cells[0][-1] == question(findings[0], DICTIONARY)

    s2 = CliRunner().invoke(app, ["validate", "nimbus"]).stdout
    s2_questions = _questions_body(s2, "nimbus").splitlines()
    new_questions = [absence_question(a, DICTIONARY) for a in absences] + [
        question(findings[0], DICTIONARY)
    ]
    start = len(s2_questions)
    assert start >= 2  # the S2 questions come first
    printed = sections["## Management questions"].splitlines()
    assert printed[:start] == s2_questions
    assert printed[start:] == [f"{n}. {q}" for n, q in enumerate(new_questions, start + 1)]


def test_brief_without_a_sector_skips_the_absence_check_and_keeps_the_patterns(
    store: FactStore,
) -> None:
    _load(store, ARR_PLAN)

    result = _run_brief("nimbus")

    assert result.exit_code == 0
    sections = _sections(result.stdout)
    assert sections["## Conspicuous absences"] == NO_SECTOR.removesuffix("\n")
    assert [r.split("\t")[2] for r in sections["## Patterns"].splitlines()[1:]] == ["arr"]
    assert "not in the pack" not in sections["## Management questions"]


def test_brief_with_an_unknown_sector_stops_before_printing(store: FactStore) -> None:
    _load(store)

    result = _run_brief("nimbus", "--sector", "nope")

    assert result.exit_code == 1
    assert result.stdout == ""
    for text in ("nope", "b2b_saas", "b2c_subscription", "dtc_commerce", "marketplace"):
        assert text in result.stderr


def test_brief_of_a_clean_company_states_no_absences_and_no_patterns(store: FactStore) -> None:
    store.add_many(CLEAN)

    result = _run_brief("nimbus", "--sector", "b2b_saas")

    assert result.exit_code == 0
    sections = _sections(result.stdout)
    assert sections["## Conspicuous absences"] == "No conspicuous absences for nimbus."
    assert sections["## Patterns"] == "No patterns for nimbus."
    assert sections["## Management questions"] == "No questions for nimbus."


@pytest.mark.usefixtures("store")
def test_brief_of_an_unknown_company_runs_no_absence_check() -> None:
    """A typo in the entity id must not read as a company with no absences."""
    result = _run_brief("ghost", "--sector", "b2b_saas")

    assert result.exit_code == 0
    assert _sections(result.stdout)["## Conspicuous absences"] == (
        "No facts for ghost, so the absence check did not run."
    )


def test_brief_lists_a_corroborated_fact_with_its_documents_and_origins(store: FactStore) -> None:
    """S5-03, criterion 1. Deck, echo press row and audited filing for nimbus
    revenue FY2024: 3 documents, 2 origins. The echo prints the cited origin.
    """
    deck = NIMBUS["nimbus-10"]
    press = deck.model_copy(
        update={
            "observation_id": "press-01",
            "value": Decimal(6900000),
            "stated_precision": Decimal(50000),
            "origin_id": "techdaily",
            "cited_origin_id": "nimbus-management",
            "document_id": "techdaily-2025-02",
            "source_type": SourceType.PRESS,
            "reliability": 3,
        }
    )
    filing = deck.model_copy(
        update={
            "observation_id": "filing-01",
            "value": Decimal(6931000),
            "origin_id": "nimbus-audited-accounts",
            "document_id": "nimbus-accounts-fy2024",
            "source_type": SourceType.FILING,
            "reliability": 5,
            "bias_direction": BiasDirection.NEUTRAL,
            "stated_label": "Net sales",
        }
    )
    _load(store, press, filing)

    stdout = _run_brief("nimbus").stdout

    headings = [line for line in stdout.splitlines() if line.startswith("## ")]
    assert headings == HEADINGS
    section = stdout.split("## Corroboration\n", 1)[1].split("\n## ", 1)[0]
    assert section.splitlines() == [
        "metric_id\tperiod_start\tperiod_end\tperiod_type\tqualifier\tcount\tdocuments",
        "revenue_recognised\t2024-01-01\t2024-12-31\tfy\t\t3 documents, 2 origins\t"
        "nimbus-accounts-fy2024 (nimbus-audited-accounts); "
        "nimbus-deck-2025 (nimbus-management); "
        "techdaily-2025-02 (techdaily, cites nimbus-management)",
    ]


def test_corroboration_leaves_out_the_documents_of_a_contesting_origin(store: FactStore) -> None:
    """S5 decision 26: two origins agree and a third contests. The entry keeps the two."""
    deck = NIMBUS["nimbus-10"]
    filing = deck.model_copy(
        update={
            "observation_id": "filing-01",
            "value": Decimal(6931000),
            "origin_id": "nimbus-audited-accounts",
            "document_id": "nimbus-accounts-fy2024",
            "reliability": 5,
        }
    )
    outlier = filing.model_copy(
        update={
            "observation_id": "press-01",
            "value": Decimal(4000000),
            "origin_id": "techdaily",
            "document_id": "techdaily-2025-02",
            "reliability": 3,
        }
    )
    _load(store, filing, outlier)

    stdout = _run_brief("nimbus").stdout

    section = stdout.split("## Corroboration\n", 1)[1].split("\n## ", 1)[0]
    assert "2 documents, 2 origins" in section
    assert "techdaily" not in section


def test_corroboration_shows_both_cited_origins_of_one_document(store: FactStore) -> None:
    """A citation belongs to the row, not the document. One press article can
    echo two origins in two of its own rows; the brief must print both, next to the one
    document that holds them.
    """
    deck = NIMBUS["nimbus-10"]
    filing = deck.model_copy(
        update={
            "observation_id": "filing-01",
            "value": Decimal(6931000),
            "origin_id": "nimbus-audited-accounts",
            "document_id": "nimbus-accounts-fy2024",
            "reliability": 5,
        }
    )
    press_cites_management = deck.model_copy(
        update={
            "observation_id": "press-01",
            "origin_id": "techdaily",
            "cited_origin_id": "nimbus-management",
            "document_id": "techdaily-2025-02",
            "source_type": SourceType.PRESS,
            "reliability": 3,
        }
    )
    press_cites_filing = filing.model_copy(
        update={
            "observation_id": "press-02",
            "origin_id": "techdaily",
            "cited_origin_id": "nimbus-audited-accounts",
            "document_id": "techdaily-2025-02",
            "source_type": SourceType.PRESS,
            "reliability": 3,
        }
    )
    _load(store, filing, press_cites_management, press_cites_filing)

    stdout = _run_brief("nimbus").stdout

    section = stdout.split("## Corroboration\n", 1)[1].split("\n## ", 1)[0]
    assert "3 documents, 2 origins" in section
    assert "techdaily-2025-02 (techdaily, cites nimbus-management)" in section
    assert "techdaily-2025-02 (techdaily, cites nimbus-audited-accounts)" in section


# A repeated-question test needs a new fixture: every S2-06 template cites a value and a
# locator, so two distinct findings in synthetic_deck.yaml never share a question string.
# Skipped instead of adding a fixture (S3-02 test-writing brief).
