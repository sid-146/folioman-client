"""Shared errors for NAV/price feed adapters."""

from __future__ import annotations


class NAVFetchError(RuntimeError):
    """A NAV feed returned an error, or the response was unusable."""


class PriceFetchError(RuntimeError):
    """An equity/crypto/bond price feed returned an error or unparseable response."""
