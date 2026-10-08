"""Closed vocabularies used by the data model."""

from enum import StrEnum


class PeriodType(StrEnum):
    FY = "fy"
    QUARTER = "quarter"
    MONTH = "month"
    TTM = "ttm"
    POINT_IN_TIME = "point_in_time"
    YTD = "ytd"
    HALF = "half"


class SourceType(StrEnum):
    DECK = "deck"
    FILING = "filing"
    INTERVIEW = "interview"
    PRESS = "press"
    WEB = "web"
    RUMOUR = "rumour"


class BiasDirection(StrEnum):
    UP = "up"
    DOWN = "down"
    NEUTRAL = "neutral"
    UNKNOWN = "unknown"


class Basis(StrEnum):
    """The reporting basis of a stated value. Closed: the validator branches on
    it, so a word outside these three is a domain question, not a silent guess.
    """

    REPORTED = "reported"
    PRO_FORMA = "pro_forma"
    CONSTANT_CURRENCY = "constant_currency"


class DefinitionStatus(StrEnum):
    RESOLVED = "resolved"
    AMBIGUOUS = "ambiguous"


class Dimension(StrEnum):
    CURRENCY = "currency"
    COUNT = "count"
    RATIO = "ratio"
    PERCENT = "percent"
    MONTHS = "months"
    DAYS = "days"


class StockOrFlow(StrEnum):
    STOCK = "stock"
    FLOW = "flow"


class TolerancePolicy(StrEnum):
    """The policy names in ``identities.yaml`` (D1.2)."""

    CURRENCY_DEFAULT = "currency_default"
    PERCENT_DEFAULT = "percent_default"
    INEQUALITY = "inequality"


class DivergenceClass(StrEnum):
    """Architecture doc section 4, with the Inconsistent row of S2 decision 5."""

    CORROBORATED = "corroborated"
    CONSISTENT = "consistent"
    INCONSISTENT = "inconsistent"
    DEFINITIONAL = "definitional"
    CONTESTED = "contested"
    UNRESOLVABLE = "unresolvable"


class FindingKind(StrEnum):
    DIVERGENCE = "divergence"
    INVARIANT = "invariant"
    BRIDGE = "bridge"
    AMBIGUITY = "ambiguity"
    LABEL_CONFLICT = "label_conflict"
    PROJECTION = "projection"
    BASIS_GAP = "basis_gap"


class CheckStatus(StrEnum):
    """A skip is never a pass (S2-04)."""

    HELD = "held"
    VIOLATED = "violated"
    NOT_CHECKED = "not_checked"
