"""Validator constants. Owner: domain-expert.

A diff to this file is a domain review. A diff to ``validator.py`` is a code review.

- ``RELATIVE_TOLERANCE`` (D1.2): the ``inequality`` policy has no value of its own. It uses the
  policy of the terms' dimension, applied to the size of the violation.
- ``POLICY_BY_DIMENSION`` (D1.3): a count is an amount built from records, with the same cut-off
  noise as currency. Durations derive from rates, so they take the rate policy.
- ``MIN_RELIABILITY`` (D2.4, D2.6): a reliability-1 source cannot contest a deck, and cannot tell
  what a deck label means.
- ``SIGNED_METRICS`` (S3-08; S3-19; S3-24): the dictionary
  metrics that a deck can print negative. Every other dictionary metric is a magnitude, so a
  negative on it is a sign or label error.
- ``OUTFLOW_METRICS`` (S3-19): a deck can print an amount of cash or
  cost used as a negative. The dictionary defines it as a positive amount, so the extractor
  stores the amount.
- ``COST_WORDS`` (S3-18): a whole word, case-insensitive, that covers a slug label
  with no dictionary alias. A slug whose label holds one of these words stores its amount as a
  positive cost, the convention ``OUTFLOW_METRICS`` sets for a dictionary metric.
- ``COST_LINE_WORD`` (S3-15): the one word the prompt tells the model to add after a
  bare cost-line label inside a cost block ("Sales" gives "Sales expenses"). The label check
  accepts a label without this last word, and no other rewrite, so the page text still has to
  print the rest of the label.
- ``GENERIC_MARGIN_LABELS`` (S3-17): the row labels that name no metric of their own,
  casefolded, so the check reads them in any case. A row that keeps such a label alone maps to
  nothing, so the prompt writes the label of the row above and then "margin", "%" (after a
  label that ends with "margin") or, under a cost line, the generic label as printed. Each
  added part is in this set, so the label check drops it.
- ``STOCK_CANDIDATE_PERIOD_TYPES`` (S3-25): the annualised stock candidates, with
  the period types of a row that can equal them. A year of revenue can equal a year-end ARR. A
  quarter of revenue is a flow, so it is never compared with an ARR.
"""

from decimal import Decimal

from fact_ledger.domain.enums import (
    Dimension,
    DivergenceClass,
    FindingKind,
    PeriodType,
    TolerancePolicy,
)

RELATIVE_TOLERANCE: dict[TolerancePolicy, Decimal] = {
    TolerancePolicy.CURRENCY_DEFAULT: Decimal("0.01"),
    TolerancePolicy.PERCENT_DEFAULT: Decimal("0.005"),
}

POLICY_BY_DIMENSION: dict[Dimension, TolerancePolicy] = {
    Dimension.CURRENCY: TolerancePolicy.CURRENCY_DEFAULT,
    Dimension.COUNT: TolerancePolicy.CURRENCY_DEFAULT,
    Dimension.PERCENT: TolerancePolicy.PERCENT_DEFAULT,
    Dimension.RATIO: TolerancePolicy.PERCENT_DEFAULT,
    Dimension.MONTHS: TolerancePolicy.PERCENT_DEFAULT,
    Dimension.DAYS: TolerancePolicy.PERCENT_DEFAULT,
}

MIN_RELIABILITY = 2

# S3-01: U1 currency symbols and scale, V2 no-currency units
# and the unit that a figure suffix prints, P1 markers that do not change the stated precision.
CURRENCY_SYMBOLS: dict[str, str] = {"€": "EUR", "£": "GBP"}

SUFFIX_UNITS: dict[str, str] = {"%": "percent", "x": "ratio"}

SCALE_MULTIPLIERS: dict[str, Decimal] = {
    "": Decimal(1),
    "k": Decimal(1000),
    "m": Decimal(1000000),
    "bn": Decimal(1000000000),
}

NO_CURRENCY_UNITS: frozenset[str] = frozenset({"percent", "ratio", "count"})

APPROXIMATION_MARKERS: tuple[str, ...] = ("~", "c.", "approx.")

SIGNED_METRICS: frozenset[str] = frozenset(
    {
        "net_new_arr",
        "gross_profit",
        "ebitda",
        "ebitda_adjusted",
        "ebit",
        "net_income",
        "ebt",
        "gross_margin",
        "ebitda_margin",
        "ebitda_adjusted_margin",
        "ebit_margin",
        "net_margin",
        "margin_unspecified",
    }
)

OUTFLOW_METRICS: frozenset[str] = frozenset(
    {"burn_gross", "burn_net", "cost_of_sales", "d_and_a", "income_tax_expense"}
)

COST_WORDS: frozenset[str] = frozenset(
    {
        "cost",
        "costs",
        "expense",
        "expenses",
        "expenditure",
        "tax",
        "taxes",
        "depreciation",
        "amortisation",
        "amortization",
        "impairment",
    }
)

COST_LINE_WORD = "expenses"

GENERIC_MARGIN_LABELS: frozenset[str] = frozenset(
    {
        "margin",
        "% margin",
        "margin %",
        "%",
        "in %",
        "% of revenue",
        "% of sales",
        "as % of revenue",
    }
)

# D6.3. T6's {used} cites the paths only a validity condition used (S2-06).
QUESTION_TEMPLATES: dict[tuple[FindingKind, DivergenceClass | None], str] = {
    (FindingKind.DIVERGENCE, DivergenceClass.INCONSISTENT): (
        "{metric} {period} is {path_s} and {path_c}.{also} Which value is correct, and what "
        "explains the difference of {gap}?{reading}"
    ),
    (FindingKind.DIVERGENCE, DivergenceClass.DEFINITIONAL): (
        '{metric} {period} is {path_s} and {path_c}.{also} Do "{label_s}" and "{label_c}" use '
        "the same definition? If not, what does each one include?"
    ),
    (FindingKind.DIVERGENCE, DivergenceClass.CONTESTED): (
        "{metric} {period} is {path_s} and {path_c}.{also} The two values come from different "
        "sources. Which value is correct, and what explains the difference of {gap}?{reading}"
    ),
    (FindingKind.DIVERGENCE, DivergenceClass.UNRESOLVABLE): (
        "{metric} {period} is {path_s} and {path_c}.{also} The validator cannot judge this "
        "difference: {reason}. Can you confirm the correct value?{reading}"
    ),
    (FindingKind.AMBIGUITY, DivergenceClass.DEFINITIONAL): (
        '"{label}" {period} is {value} on {locator}. It differs from each candidate metric: '
        '{candidates}. Which metric does "{label}" mean, and how is it defined?'
    ),
    (FindingKind.INVARIANT, None): (
        "{metric_a} {period} is {path_a}, {above_or_below} {metric_b} {path_b}. The rule "
        "{identity_id} ({equation}) does not allow this.{used}{assumption} Which value is wrong, "
        "or do the two use a different scope or definition?"
    ),
    (FindingKind.BRIDGE, None): (
        "The MRR bridge {period} does not close. Opening MRR {t_1} plus new {new}, expansion "
        "{exp} and reactivation {react}, minus contraction {contr} and churned {churn}, gives "
        "{computed}. The stated closing MRR is {t}. The bridge {overstates_or_understates} the "
        "closing MRR by {abs_residual}. Which bridge line or which closing value is wrong?"
    ),
    (FindingKind.PROJECTION, None): (
        "{metric} {period} is planned at {path_p}, growth of {implied} a year from {path_last}. "
        "Before that, from {path_first}, {metric} grew {realized} a year. What causes the "
        "planned growth to be higher than the realized growth?"
    ),
    (FindingKind.LABEL_CONFLICT, DivergenceClass.DEFINITIONAL): (
        'The values of "{label}" in {document_id} match more than one metric: {matches}. Does '
        '"{label}" have one definition in this document? If not, which definition applies to '
        "each period?"
    ),
    (FindingKind.BASIS_GAP, DivergenceClass.DEFINITIONAL): (
        "The reported {metric} {period} is {path_r}. The {basis} value is {path_o}.{also} What "
        "change of scope or exchange rates explains the difference of {gap}?"
    ),
}

# S4-02: ARR is a stock, so two year-end actuals and a year-end plan give two rates with no
# period mismatch. A plan row labeled "Revenue" stays ambiguous, so the check could not read it.
PROJECTION_METRICS: frozenset[str] = frozenset({"arr"})

# S4-02: percentage points. A ratio has no meaning when the realized rate is zero or negative.
# No corpus tunes the size. Change it when an analyst reads a flag as noise.
PROJECTION_MARGIN = Decimal(10)

ABSENCE_QUESTION = (
    "{metric} is not in the pack, and the pack does not give the values to calculate it. "
    "What is {metric} for each period that the pack reports, and how do you define it?"
)

# D5.2, keyed by "the residual is negative".
BRIDGE_DIRECTION: dict[bool, str] = {True: "overstates", False: "understates"}

PERIOD_NAMES: dict[PeriodType, str] = {
    PeriodType.FY: "fiscal year",
    PeriodType.TTM: "twelve months",
    PeriodType.QUARTER: "quarter",
    PeriodType.MONTH: "month",
    PeriodType.YTD: "year to date",
    PeriodType.HALF: "half year",
}

# S3-06: keys to (first month, last month) of the financial year. "FY" alone is (1, 12).
PERIOD_TOKENS: dict[str, tuple[int, int]] = {
    "q1": (1, 3),
    "q2": (4, 6),
    "q3": (7, 9),
    "q4": (10, 12),
    "h1": (1, 6),
    "h2": (7, 12),
    "6m": (1, 6),
    "9m": (1, 9),
}

STOCK_CANDIDATE_PERIOD_TYPES: dict[str, frozenset[PeriodType]] = {
    "arr": frozenset({PeriodType.FY, PeriodType.TTM, PeriodType.POINT_IN_TIME}),
    "arr_run_rate": frozenset({PeriodType.FY, PeriodType.TTM, PeriodType.POINT_IN_TIME}),
}
