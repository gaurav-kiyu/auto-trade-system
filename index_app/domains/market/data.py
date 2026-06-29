"""Market data fetching — intraday OHLCV, cached data, and VIX resolution.

Extracted from ``index_trader.py`` inline functions (``_fetch_intraday_data``,
``_fetch_intraday_data_cached``, ``_yf_fetch_vix``) to reduce the monolith
and centralise data-fetching logic.
"""

from __future__ import annotations

import logging
from typing import Any

__all__ = [
    "fetch_intraday_data",
    "fetch_intraday_data_cached",
    "fetch_vix",
]

_log = logging.getLogger(__name__)


def fetch_intraday_data(yf_symbol: str) -> tuple[Any, Any, Any]:
    """Fetch intraday OHLCV data (1m, 5m, 15m) for a symbol via yfinance.

    Args:
        yf_symbol: Yahoo Finance symbol (e.g. ``^NSEI``).

    Returns:
        ``(df1m, df5m, df15m)`` — three DataFrames (or ``None`` values).
    """
    from core.yf_data_provider import fetch_intraday_data as _yf_fetch
    return _yf_fetch(yf_symbol)


def fetch_intraday_data_cached(yf_symbol: str) -> tuple[Any, Any, Any]:
    """Fetch intraday data with cross-cycle caching to avoid yfinance rate limits.

    Args:
        yf_symbol: Yahoo Finance symbol (e.g. ``^NSEI``).

    Returns:
        ``(df1m, df5m, df15m)`` — three DataFrames (or ``None`` values).
    """
    from core.yf_data_provider import fetch_intraday_data_cached as _yf_fetch_cached
    return _yf_fetch_cached(yf_symbol)


def fetch_vix() -> float:
    """Fetch India VIX via ``core.yf_data_provider``.

    Returns:
        Current VIX value (float). Returns 0.0 on failure.
    """
    from core.yf_data_provider import get_vix_from_intraday
    return get_vix_from_intraday()
