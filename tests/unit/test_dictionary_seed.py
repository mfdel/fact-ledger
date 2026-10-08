"""The v0 dictionary content.

``load_dictionary`` builds a ``Dictionary``, whose validator already rejects duplicate ids,
duplicate aliases and a dangling identity term. These tests
check the v0 content itself: the validator's rules are covered on literal data in
``test_dictionary_model.py``.
"""

from pathlib import Path

import pytest

from fact_ledger.domain import Dictionary
from fact_ledger.store.yaml_files import load_dictionary

pytestmark = pytest.mark.unit

DICTIONARY_DIR = Path(__file__).resolve().parents[2] / "data" / "dictionary"

# v0 = sections 1, 3 and 4 of metrics.yaml.
SECTION_1_REVENUE = (
    "revenue_recognised",
    "revenue_gross",
    "arr",
    "arr_run_rate",
    "arr_contracted",
    "mrr",
    "mrr_new",
    "mrr_expansion",
    "mrr_contraction",
    "mrr_churned",
    "mrr_reactivation",
    "net_new_arr",
    "bookings_acv",
    "bookings_tcv",
    "billings",
    "deferred_revenue",
    "backlog_rpo",
    "revenue_subscription",
    "revenue_usage",
    "revenue_services",
    "revenue_hardware",
    "recurring_revenue_share",
    "revenue_concentration_top1",
    "revenue_concentration_top5",
    "revenue_concentration_top10",
    "revenue_by_geography",
    "revenue_by_segment",
    "revenue_by_currency",
    "revenue_seasonality_index",
)
SECTION_3_RETENTION = (
    "churn_logo_monthly",
    "churn_logo_annual",
    "churn_revenue_gross_monthly",
    "grr",
    "nrr",
    "nrr_cohort_12m",
    "renewal_rate",
    "churn_voluntary",
    "churn_involuntary",
    "dunning_recovery_rate",
    "reactivation_rate",
    "cohort_retention_curve",
    "cohort_revenue_curve",
    "customer_lifetime_months",
    "contract_length_avg",
    "contract_annual_share",
    "payment_terms_upfront_share",
    "customer_tenure_median",
)
SECTION_4_CUSTOMERS = (
    "customers_paying",
    "customers_active",
    "logos",
    "seats_licensed",
    "seats_active",
    "seat_utilisation",
    "subscribers_paying",
    "users_registered",
    "customers_new",
    "customers_churned",
    "customers_enterprise_share",
    "arpu",
    "acv_avg",
    "asp",
    "aov",
)
# The metric_id of an ambiguous observation.
UMBRELLA = (
    "revenue_unspecified",
    "bridge_movement_unspecified",
    "deal_value_unspecified",
    "churn_unspecified",
    "retention_unspecified",
    "customers_unspecified",
    "concentration_unspecified",
    "customer_tenure_unspecified",
)
V0_METRIC_IDS = SECTION_1_REVENUE + SECTION_3_RETENTION + SECTION_4_CUSTOMERS + UMBRELLA

# The MRR bridge and invariants 1-6 and 11-12, named in identities.yaml.
V0_IDENTITY_IDS = (
    "arr_from_mrr",
    "net_new_arr_from_arr",
    "mrr_bridge",
    "nrr_from_bridge",
    "grr_from_bridge",
    "nrr_ge_grr",
    "arr_ge_revenue_recognised",
    "customers_paying_le_users_registered",
    "seats_active_le_seats_licensed",
    "churn_logo_annual_from_monthly",
)


@pytest.fixture(scope="module")
def dictionary() -> Dictionary:
    return load_dictionary(DICTIONARY_DIR)


def test_load_dictionary_returns_a_dictionary(dictionary: Dictionary) -> None:
    assert isinstance(dictionary, Dictionary)


def test_every_v0_metric_id_is_present_with_its_fields(dictionary: Dictionary) -> None:
    by_id = {metric.metric_id: metric for metric in dictionary.metrics}
    for metric_id in V0_METRIC_IDS:
        metric = by_id[metric_id]
        assert metric.canonical_name
        assert metric.dimension
        assert metric.stock_or_flow
        assert metric.aliases


def test_arr_and_arr_run_rate_are_distinct_nodes_with_disjoint_aliases(
    dictionary: Dictionary,
) -> None:
    by_id = {metric.metric_id: metric for metric in dictionary.metrics}
    arr, arr_run_rate = by_id["arr"], by_id["arr_run_rate"]
    assert arr.metric_id != arr_run_rate.metric_id
    arr_aliases = {alias.casefold() for alias in arr.aliases}
    arr_run_rate_aliases = {alias.casefold() for alias in arr_run_rate.aliases}
    assert not arr_aliases & arr_run_rate_aliases


def test_every_alias_of_arr_and_arr_run_rate_resolves_to_its_own_metric(
    dictionary: Dictionary,
) -> None:
    by_id = {metric.metric_id: metric for metric in dictionary.metrics}
    for metric_id in ("arr", "arr_run_rate"):
        for alias in by_id[metric_id].aliases:
            assert dictionary.alias_owner(alias) == metric_id


def test_every_v0_identity_term_is_a_metric_id(dictionary: Dictionary) -> None:
    by_id = {identity.identity_id: identity for identity in dictionary.identities}
    for identity_id in V0_IDENTITY_IDS:
        identity = by_id[identity_id]
        assert set(identity.terms) <= dictionary.metric_ids
