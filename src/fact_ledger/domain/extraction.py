"""Pure rules from an LLM response to a transcript row (S3-01).
No IO: ``extract.py`` supplies the page text and calls these on each value.
"""

import calendar
import re
import unicodedata
from collections.abc import Iterator, Sequence
from datetime import date
from decimal import Decimal

from fact_ledger.domain.enums import DefinitionStatus
from fact_ledger.domain.models import Dictionary
from fact_ledger.domain.paths import metric_of
from fact_ledger.domain.rules import (
    APPROXIMATION_MARKERS,
    COST_WORDS,
    CURRENCY_SYMBOLS,
    NO_CURRENCY_UNITS,
    PERIOD_TOKENS,
    SCALE_MULTIPLIERS,
    SUFFIX_UNITS,
)

_APPROX = f"(?:{'|'.join(re.escape(marker) + r'\s*' for marker in APPROXIMATION_MARKERS)})?"
# S3-08: an en dash or other dash is a nil or range mark, never a sign. The Unicode minus
# (U+2212) is a sign. It can come before or after the currency symbol ("-€4.2m", "€-4.2m").
_MINUS = "-\u2212"
# A currency symbol ("Sc") or ISO code, never a bound sign (">100"). S3-13: one space can follow.
_SYMBOL = r"(?:(?P<symbol>[$\u00a2-\u00a5\u20a0-\u20cf]|[A-Z]{3}) ?)?"
_SIGN = rf"(?P<sign>[{_MINUS}])?{_SYMBOL}(?P<sign_after_symbol>[{_MINUS}])?"
_NUMBER = r"(?P<int>\d{1,3}(?:,\d{3})*|\d+)(?:\.(?P<frac>\d+))?"
_SCALE = r"(?: ?(?P<scale>k|m|bn))?"
_UNIT_SUFFIX = r"(?: ?(?=%))?(?P<suffix>[%x])?"
_FIGURE = re.compile(f"^{_APPROX}{_SIGN}{_NUMBER}{_SCALE}{_UNIT_SUFFIX}$")
_THOUSANDS_GROUP_LENGTH = 3


def parse_figure(printed: str, scale: str, unit: str) -> tuple[Decimal, Decimal | None]:
    """V1, P1: one point figure read with no doubt, scaled by ``scale`` (the figure's own
    scale letter, or the scale of its table or axis header). Raises for a bound, a range, a
    scale letter that disagrees with ``scale``, a currency symbol, "%" or "x" that disagrees
    with ``unit`` (V2, U1), or an unclear thousands mark. A minus sign before or after the
    currency symbol, or one pair of round brackets around the figure or its number ("(12.3)",
    "€(12.3)m"), gives a negative value. Two signs raise. Zero has no sign, and
    ``stated_precision`` (P1) stays positive (S3-08).
    """
    open_at, close_at = printed.find("("), printed.rfind(")")
    outside = printed[:open_at] + printed[close_at + 1 :]
    bracketed = (
        printed.count("(") == printed.count(")") == 1
        and open_at < close_at
        and not any(character.isdigit() for character in outside)
    )
    text = printed.replace("(", "").replace(")", "") if bracketed else printed
    match = _FIGURE.fullmatch(text)
    if match is None:
        msg = f"{printed!r} is not one point figure"
        raise ValueError(msg)
    signs = [bracketed, match["sign"] is not None, match["sign_after_symbol"] is not None]
    if sum(signs) > 1:
        msg = f"{printed!r} prints more than one sign"
        raise ValueError(msg)
    negative = any(signs)

    printed_scale = match["scale"]
    if printed_scale and printed_scale != scale:
        msg = f"{printed!r} prints scale {printed_scale!r}, which disagrees with {scale!r}"
        raise ValueError(msg)

    # A unit that the figure contradicts can drop its currency and hide a real finding.
    printed_unit = match["symbol"] or SUFFIX_UNITS.get(match["suffix"] or "")
    # A symbol and its ISO code name one currency in either position.
    if printed_unit and CURRENCY_SYMBOLS.get(printed_unit, printed_unit) != CURRENCY_SYMBOLS.get(
        unit, unit
    ):
        msg = f"{printed!r} prints {printed_unit!r}, which disagrees with unit {unit!r}"
        raise ValueError(msg)

    frac = match["frac"]
    # A dot before exactly 3 digits, with no comma, scale letter, "%" or "x" to anchor the
    # reading, is a European thousands mark as often as it is a fraction.
    ambiguous_frac = frac is not None and len(frac) == _THOUSANDS_GROUP_LENGTH
    if ambiguous_frac and not (printed_scale or match["suffix"] or "," in printed):
        msg = f"{printed!r}: a dot before exactly 3 digits with no comma is ambiguous"
        raise ValueError(msg)

    digits = match["int"].replace(",", "") + (f".{frac}" if frac else "")
    multiplier = SCALE_MULTIPLIERS[scale]
    value = _plain(Decimal(digits) * multiplier)
    if negative and value:
        value = -value

    decimals = len(frac) if frac else 0
    if decimals == 0 and not scale:
        return value, None
    return value, _plain(Decimal(1).scaleb(-decimals) / 2 * multiplier)


def _plain(number: Decimal) -> Decimal:
    """Drop the zeros that a scale adds ("8.4" x 1m is "8400000.0"), so the transcript and the
    fact store show 8400000, as a hand transcript does. ``stated_precision`` keeps the rounding.
    """
    if number == number.to_integral_value():
        return number.quantize(Decimal(1))
    return number.normalize()


def currency_for(unit: str) -> str | None:
    """U1: '€' and '£' map to their ISO code, an ISO code maps to itself, and percent, ratio
    and count carry no currency. Any other symbol is ambiguous and stops the run.
    """
    if unit in CURRENCY_SYMBOLS:
        return CURRENCY_SYMBOLS[unit]
    if unit in NO_CURRENCY_UNITS:
        return None
    if re.fullmatch(r"[A-Z]{3}", unit):
        return unit
    msg = f"{unit!r} is not a currency this code can resolve"
    raise ValueError(msg)


def _slug(label: str, dictionary: Dictionary) -> str:
    """M3: NFKD to ASCII, casefold, each run outside [a-z0-9] becomes '_', a leading digit
    gets an 'm_' prefix. A slug that collides with a dictionary id gets the '_undefined'
    suffix, so the collision does not resolve a row silently.
    """
    ascii_text = unicodedata.normalize("NFKD", label).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "_", ascii_text.casefold()).strip("_")
    if slug[:1].isdigit():
        slug = f"m_{slug}"
    if slug in dictionary.metric_ids:
        slug += "_undefined"
    return slug


_COST_WORD = re.compile(
    rf"(?<!\w)(?:{'|'.join(re.escape(word) for word in COST_WORDS)})(?!\w)", re.IGNORECASE
)


def is_cost_label(label: str) -> bool:
    """S3-18: a slug's label holds a whole ``COST_WORDS`` word, case-insensitive, so "Taxes
    on income" matches "taxes" and "Taxonomy revenue" does not match "tax".
    """
    return _COST_WORD.search(label) is not None


def map_label(
    stated_label: str, candidates: Sequence[str], dictionary: Dictionary
) -> tuple[str, DefinitionStatus, tuple[str, ...]]:
    """M1 to M3: a resolved alias maps with no candidates, an umbrella alias stays ambiguous
    with its checked candidates, and anything else becomes the fixed slug of the label.
    """
    owner = dictionary.alias_owner(stated_label)

    if owner is None:
        if candidates:
            msg = f"{stated_label!r} is undefined: it takes no candidate_metric_ids"
            raise ValueError(msg)
        return _slug(stated_label, dictionary), DefinitionStatus.RESOLVED, ()

    if not owner.endswith("_unspecified"):
        if candidates:
            msg = f"{stated_label!r} resolves to {owner!r}: it takes no candidate_metric_ids"
            raise ValueError(msg)
        return owner, DefinitionStatus.RESOLVED, ()

    if not candidates:
        msg = f"{stated_label!r} is ambiguous ({owner!r}): it needs at least one candidate"
        raise ValueError(msg)
    # M2: the prompt gives the LLM the same note, so both read one list of usual candidates.
    note = metric_of(dictionary, owner).definition_note.partition("Usual candidates:")[2]
    usual = set(re.findall(r"[a-z][a-z0-9_]*", note)) & dictionary.metric_ids
    for candidate in candidates:
        if candidate not in usual:
            msg = f"{candidate!r} for {stated_label!r} is not a usual candidate of {owner!r}"
            raise ValueError(msg)
    return owner, DefinitionStatus.AMBIGUOUS, tuple(candidates)


_TOKENS = "|".join(PERIOD_TOKENS)
_SEPARATOR = r"(?:-|\s?['\u2019]|\s)"
# "(?!\w)" rejects a forecast suffix ("Q2-26E") and the first digits of a 4-digit year ("Q2 2026").
_YY = r"(?P<yy>\d{2})(?!\w)"
_CALENDAR_TOKEN = re.compile(rf"(?<!\w)(?P<token>{_TOKENS}){_SEPARATOR}{_YY}", re.IGNORECASE)
_FISCAL_TOKEN = re.compile(
    rf"(?<!\w)(?:(?P<token>{_TOKENS})[\s-])?FY{_SEPARATOR}?{_YY}", re.IGNORECASE
)
_YTD_MONTH = re.compile(
    rf"(?<!\w)YTD\s+(?P<month>[a-z]{{3}})[a-z]*\.?{_SEPARATOR}{_YY}", re.IGNORECASE
)
_MONTHS = {name.lower(): number for number, name in enumerate(calendar.month_abbr) if name}
_YEAR_END_MONTHS = range(1, 13)


def _window(first: int, last: int) -> tuple[date, date]:
    """First day of month index ``first`` to last day of month index ``last``, where a month
    index is ``year * 12 + month - 1``.
    """
    start_year, start_month = divmod(first, 12)
    end_year, end_month = divmod(last, 12)
    last_day = calendar.monthrange(end_year, end_month + 1)[1]
    return date(start_year, start_month + 1, 1), date(end_year, end_month + 1, last_day)


def _fiscal_window(year: int, year_end_month: int, months: tuple[int, int]) -> tuple[date, date]:
    """A financial year takes the name of the calendar year in which it ends."""
    first_month = year * 12 + year_end_month - 12
    return _window(first_month + months[0] - 1, first_month + months[1] - 1)


def _token_windows(page_text: str) -> Iterator[tuple[date, date]]:
    for match in _CALENDAR_TOKEN.finditer(page_text):
        months = PERIOD_TOKENS[match["token"].lower()]
        yield _fiscal_window(2000 + int(match["yy"]), 12, months)
    # "FY" names a financial year that can end in any month, and the page need not say which.
    for match in _FISCAL_TOKEN.finditer(page_text):
        months = PERIOD_TOKENS[match["token"].lower()] if match["token"] else (1, 12)
        for year_end_month in _YEAR_END_MONTHS:
            yield _fiscal_window(2000 + int(match["yy"]), year_end_month, months)
    for match in _YTD_MONTH.finditer(page_text):
        month = _MONTHS.get(match["month"].lower())
        if month is None:
            continue
        last = (2000 + int(match["yy"])) * 12 + month - 1
        for length in _YEAR_END_MONTHS:
            yield _window(last - length + 1, last)


def prints_period(page_text: str, start: date, end: date) -> bool:
    """S3-06, domain rules 3 and 4: the page prints a two-digit-year token whose window is
    ``(start, end)``, or, for a stock value (``start == end``), whose window ends on ``end``.
    ``YY`` gives ``2000 + YY``. The forms: ``Q2-26``, ``H2 26``, ``Q2'26`` (calendar year),
    ``FY26``, ``H1 FY26`` (a financial year that ends in any month) and ``YTD Sep 24``.
    """
    return any(
        window == (start, end) or (start == end and window[1] == end)
        for window in _token_windows(page_text)
    )
