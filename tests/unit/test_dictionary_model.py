"""The ``Dictionary`` validator and alias lookup, on small literal dictionaries.

Real content lives in ``data/dictionary/`` and is covered by ``test_dictionary_seed.py``.
These tests isolate one validator rule at a time.
"""

import pytest
from pydantic import ValidationError

from fact_ledger.domain import Dictionary, Identity, TolerancePolicy
from tests.factories import make_metric

pytestmark = pytest.mark.unit


def _identity(identity_id: str, terms: tuple[str, ...]) -> Identity:
    return Identity(
        identity_id=identity_id,
        equation="a = b",
        terms=terms,
        tolerance_policy=TolerancePolicy.CURRENCY_DEFAULT,
    )


def test_duplicate_metric_id_is_rejected() -> None:
    with pytest.raises(ValidationError, match="arr"):
        Dictionary(metrics=(make_metric("arr"), make_metric("arr")), identities=())


def test_duplicate_identity_id_is_rejected() -> None:
    metrics = (make_metric("arr"), make_metric("mrr"))
    identities = (
        _identity("arr_from_mrr", ("arr", "mrr")),
        _identity("arr_from_mrr", ("arr", "mrr")),
    )
    with pytest.raises(ValidationError, match="arr_from_mrr"):
        Dictionary(metrics=metrics, identities=identities)


def test_identity_term_that_is_not_a_metric_is_rejected() -> None:
    metrics = (make_metric("arr"),)
    identities = (_identity("arr_from_mrr", ("arr", "mrr")),)
    with pytest.raises(ValidationError, match="mrr"):
        Dictionary(metrics=metrics, identities=identities)


def test_same_alias_under_two_metrics_is_rejected_case_insensitively() -> None:
    # Same alias, different case, under two different metrics.
    metrics = (make_metric("arr", aliases=("ARR",)), make_metric("arr_run_rate", aliases=("arr",)))
    with pytest.raises(ValidationError) as exc_info:
        Dictionary(metrics=metrics, identities=())
    message = str(exc_info.value)
    assert "arr" in message
    assert "arr_run_rate" in message


def test_identity_term_ending_in_unspecified_is_rejected() -> None:
    # Umbrella ids are never used in a check or a derivation (data/dictionary/metrics.yaml header).
    metrics = (make_metric("arr"), make_metric("revenue_unspecified"))
    identities = (_identity("bad_identity", ("arr", "revenue_unspecified")),)
    with pytest.raises(ValidationError, match="revenue_unspecified"):
        Dictionary(metrics=metrics, identities=identities)


def test_alias_owner_matches_case_insensitively() -> None:
    dictionary = Dictionary(metrics=(make_metric("arr", aliases=("ARR",)),), identities=())
    assert dictionary.alias_owner("arr") == "arr"
    assert dictionary.alias_owner("Arr") == "arr"


def test_alias_owner_returns_none_for_an_unknown_label() -> None:
    dictionary = Dictionary(metrics=(make_metric("arr"),), identities=())
    assert dictionary.alias_owner("mrr") is None


def test_unknown_tolerance_policy_is_rejected() -> None:
    with pytest.raises(ValidationError, match="tolerance_policy"):
        Identity(identity_id="x", equation="a = b", terms=("a", "b"), tolerance_policy="default")  # type: ignore[arg-type]
