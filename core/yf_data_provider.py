"""
yf_data_provider.py - Standalone yfinance data provider.

Provides a single-source yfinance data layer extracted from the
trading brain to reduce index_trader.py file size and eliminate
duplicate code between signal and execution modules. Offers a
single source of truth for:

- fetch_intraday_data()        - 1m/5m/15m OHLCV for an index
- fetch_intraday_data_cached() - cached variant with TTL
- fetch_last_close_summary()   - last close price by index
- fetch_vix()                  - India VIX snapshot
- get_vix()                    - VIX from intraday data (1m bar)

Thread-safe: module-level caches are protected by threading.RLock.
Intended to be imported by index_trader.py and other consumers.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

import yfinance as yf

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level caches (thread-safe)
# ---------------------------------------------------------------------------
_yf_data_cache: dict[str, tuple] = {}
_yf_data_cache_lock = threading.RLock()
_yf_data_cache_ts: float = 0.0
_YF_CACHE_TTL: float = 60.0  # seconds before refresh

_last_close_cache: dict[str, dict[str, Any]] = {}
_last_close_cache_lock = threading.RLock()
_last_close_cache_ts: float = 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def fetch_intraday_data(yf_sym: str) -> tuple:
    """Fetch intraday OHLCV data (1m, 5m, 15m) for an index via yfinance.

    Args:
        yf_sym: Yahoo Finance symbol (e.g. "^NSEI", "^NSEBANK").

    Returns:
        Tuple of (df1m, df5m, df15m) - each may be None on failure.
    """
    if not yf_sym:
        return None, None, None
    try:
        df1m = yf.download(yf_sym, period="2d", interval="1m", progress=False)
        df5m = yf.download(yf_sym, period="5d", interval="5m", progress=False)
        df15m = yf.download(yf_sym, period="15d", interval="15m", progress=False)
        return (
            df1m if not df1m.empty else None,
            df5m if not df5m.empty else None,
            df15m if not df15m.empty else None,
        )
    except (ValueError, TypeError, KeyError, AttributeError, IndexError, ConnectionError, TimeoutError, OSError) as exc:
        _log.warning("yfinance intraday fetch failed for %s: %s", yf_sym, exc)
        return None, None, None
    except Exception as exc:
        _log.warning("yfinance intraday fetch failed for %s (unexpected: %s): %s", yf_sym, type(exc).__name__, exc)
        return None, None, None


def fetch_intraday_data_cached(yf_sym: str) -> tuple:
    """Fetch intraday data with cross-cycle caching to avoid yfinance rate limits."""
    global _yf_data_cache, _yf_data_cache_ts
    now = time.time()
    with _yf_data_cache_lock:
        if yf_sym in _yf_data_cache and now - _yf_data_cache_ts < _YF_CACHE_TTL:
            return _yf_data_cache[yf_sym]
    result = fetch_intraday_data(yf_sym)
    with _yf_data_cache_lock:
        _yf_data_cache[yf_sym] = result
        _yf_data_cache_ts = now
    return result


def fetch_last_close_summary(index_map: dict[str, dict[str, str]]) -> dict[str, dict[str, Any]]:
    """Fetch last close price and change % for each index.

    Args:
        index_map: Mapping of index name → {"yf": "<YF symbol>"}.

    Returns:
        Dict of index name → {"close": float, "change": float, "pct": float, "date": str}.
    """
    global _last_close_cache, _last_close_cache_ts
    result: dict[str, dict[str, Any]] = {}
    now = time.time()

    for name, info in index_map.items():
        yf_sym = info.get("yf", "")
        if not yf_sym:
            continue
        try:
            with _last_close_cache_lock:
                if yf_sym in _last_close_cache:
                    result[name] = _last_close_cache[yf_sym]
                    continue
            ticker = yf.Ticker(yf_sym)
            h = ticker.history(period="5d", interval="1d")
            if h.empty:
                continue
            last = h.iloc[-1]
            prev = h.iloc[-2] if len(h) > 1 else last
            change = float(last["Close"]) - float(prev["Close"])
            pct = round(change / float(prev["Close"]) * 100, 2) if prev["Close"] else 0.0
            last_date = h.index[-1]
            date_str = last_date.strftime("%d-%b-%Y")
            entry = {
                "close": float(last["Close"]),
                "change": round(change, 2),
                "pct": pct,
                "date": date_str,
            }
            with _last_close_cache_lock:
                _last_close_cache[yf_sym] = entry
            result[name] = entry
        except (ValueError, TypeError, KeyError, AttributeError, IndexError, ConnectionError, TimeoutError, OSError) as exc:
            _log.warning("yfinance last close fetch failed for %s (%s): %s", name, yf_sym, exc)
            continue
        except Exception as exc:
            _log.warning("yfinance last close fetch failed for %s (%s) (unexpected: %s): %s", name, yf_sym, type(exc).__name__, exc)
            continue

    with _last_close_cache_lock:
        _last_close_cache_ts = now
    return result


def fetch_vix() -> float:
    """Fetch India VIX directly via yfinance.

    Returns:
        Latest VIX close value, or 0.0 on failure.
    """
    try:
        vix_df = yf.download("^INDIAVIX", period="5d", interval="1d", progress=False)
        if vix_df is not None and not vix_df.empty:
            close_val = vix_df["Close"].iloc[-1]
            # Handle MultiIndex columns (yfinance >= 0.2.30)
            if hasattr(close_val, 'iloc'):
                close_val = close_val.iloc[0]
            return float(close_val)
    except (ValueError, TypeError, KeyError, AttributeError, IndexError, ConnectionError, TimeoutError, OSError) as exc:
        _log.warning("VIX fetch failed: %s", exc)
        return 0.0
    except Exception as exc:
        _log.warning("VIX fetch failed (unexpected: %s): %s", type(exc).__name__, exc)
    return 0.0


def get_vix_from_intraday() -> float:
    """Fetch India VIX from intraday data (1m bar).

    Returns:
        Latest VIX close value, or 0.0 on failure.
    """
    try:
        vix_data = yf.download("^INDIAVIX", period="1d", interval="1m", progress=False)
        if not vix_data.empty:
            close_val = vix_data["Close"].iloc[-1]
            # Handle MultiIndex columns (yfinance >= 0.2.30)
            if hasattr(close_val, 'iloc'):
                close_val = close_val.iloc[0]
            return float(close_val)
    except (ValueError, TypeError, KeyError, AttributeError, IndexError, ConnectionError, TimeoutError, OSError) as exc:
        _log.warning("VIX intraday fetch failed: %s", exc)
        return 0.0
    except Exception as exc:
        _log.warning("VIX intraday fetch failed (unexpected: %s): %s", type(exc).__name__, exc)
    return 0.0


# ---------------------------------------------------------------------------
# Invalidation helpers
# ---------------------------------------------------------------------------


def invalidate_cache() -> None:
    """Force cache refresh on next fetch."""
    global _yf_data_cache_ts, _last_close_cache_ts
    with _yf_data_cache_lock:
        _yf_data_cache_ts = 0.0
        _yf_data_cache.clear()
    with _last_close_cache_lock:
        _last_close_cache_ts = 0.0
        _last_close_cache.clear()
