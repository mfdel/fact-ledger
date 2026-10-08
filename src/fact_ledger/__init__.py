"""Fact Ledger: Pre-Valuation Intelligence Layer."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("fact-ledger")
except PackageNotFoundError:  # pragma: no cover - only when run from a source tree without install
    __version__ = "0.0.0"
