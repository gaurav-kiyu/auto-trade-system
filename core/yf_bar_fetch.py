"""
Yahoo Finance OHLCV for candle backtests.

1m data:  Yahoo limits to ~30 calendar days lookback, ~7d per request chunk.
5m data:  Yahoo provides ~60 calendar days lookback, ~30d per request chunk.
          Use 5m for longer-window backtests; the simulation resamples to 5m/15m/1h.
"""

from __future__ import annotations

import time
from typing import Any

import pandas as pd

# Policy bounds (Yahoo; adjust if their API messages change).
YAHOO_1M_CHUNK_DAYS = 7
YAHOO_1M_MAX_LOOKBACK_DAYS = 30

YAHOO_5M_CHUNK_DAYS = 30
YAHOO_5M_MAX_LOOKBACK_DAYS = 60


def normalize_yfinance_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    """Return OHLCV columns with a DatetimeIndex (UTC-naive), sorted ascending."""
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy()
    if isinstance(out.columns, pd.MultiIndex):
        out.columns = out.columns.droplevel(1)
    # Normalize column names to Title Case to survive Yahoo API casing changes
    col_lower = {c.lower(): c for c in out.columns}
    need = ("Open", "High", "Low", "Close", "Volume")
    rename_map = {}
    for c in need:
        if c not in out.columns:
            alt = col_lower.get(c.lower())
            if alt:
                rename_map[alt] = c
    if rename_map:
        out = out.rename(columns=rename_map)
    for c in need:
        if c not in out.columns:
            raise ValueError(f"yfinance frame missing column {c!r}; got {list(out.columns)}")
    out = out[list(need)].copy()
    for c in need:
        out[c] = pd.to_numeric(out[c], errors="coerce")
    out["Volume"] = out["Volume"].fillna(0.0)
    out = out.dropna(subset=["Open", "High", "Low", "Close"])
    idx = out.index
    if not isinstance(idx, pd.DatetimeIndex):
        out.index = pd.to_datetime(idx, utc=True)
    if out.index.tz is not None:
        out.index = out.index.tz_convert("UTC").tz_localize(None)
    out = out.sort_index()
    out = out[~out.index.duplicated(keep="last")]
    return out


def fetch_1m_bars_chunked_yfinance(
    symbol: str,
    *,
    calendar_days: int = 92,
    chunk_days: int = 7,
    sleep_sec: float = 0.35,
    download_fn: Any | None = None,
) -> pd.DataFrame:
    """
    Pull up to ``min(calendar_days, YAHOO_1M_MAX_LOOKBACK_DAYS)`` of 1m bars.

    ``download_fn`` defaults to ``yfinance.download``; inject a stub in tests.
    """
    import yfinance as yf

    dl = download_fn or yf.download
    if calendar_days <= 0:
        raise ValueError("calendar_days must be positive")
    span = min(int(calendar_days), YAHOO_1M_MAX_LOOKBACK_DAYS)
    chunk = max(1, min(int(chunk_days), YAHOO_1M_CHUNK_DAYS))
    end = pd.Timestamp.now("UTC").floor("s").tz_localize(None)
    start_limit = end - pd.Timedelta(days=span)
    parts: list[pd.DataFrame] = []
    cursor = end
    max_requests = max(8, span // chunk + 6)
    requests = 0
    while cursor > start_limit and requests < max_requests:
        requests += 1
        chunk_start = max(start_limit, cursor - pd.Timedelta(days=chunk))
        raw = dl(
            symbol,
            interval="1m",
            start=chunk_start.strftime("%Y-%m-%d"),
            end=cursor.strftime("%Y-%m-%d"),
            progress=False,
            auto_adjust=False,
            threads=False,
        )
        if raw is not None and not getattr(raw, "empty", True):
            parts.append(normalize_yfinance_ohlcv(raw))
        cursor = chunk_start
        if sleep_sec > 0 and cursor > start_limit:
            time.sleep(float(sleep_sec))
    if not parts:
        raise RuntimeError(
            f"No 1m data returned for {symbol!r} (tried ~{span}d lookback in {chunk}d chunks). "
            "Check symbol, internet, and Yahoo availability."
        )
    merged = pd.concat(parts, axis=0)
    merged = merged[~merged.index.duplicated(keep="last")].sort_index()
    merged = merged[merged.index >= start_limit]
    if merged.empty:
        raise RuntimeError(f"Merged OHLCV empty for {symbol!r}.")
    return merged


def fetch_5m_bars_chunked_yfinance(
    symbol: str,
    *,
    calendar_days: int = 60,
    chunk_days: int = 30,
    sleep_sec: float = 0.35,
    download_fn: Any | None = None,
) -> pd.DataFrame:
    """
    Pull up to 60 calendar days of 5m bars from Yahoo Finance.

    Yahoo Finance provides 5m data for approximately the last 60 days.
    Use this for longer-window backtests (2× the 1m lookback).
    The returned DataFrame has the same OHLCV schema as fetch_1m_bars_chunked_yfinance.
    """
    import yfinance as yf

    dl = download_fn or yf.download
    if calendar_days <= 0:
        raise ValueError("calendar_days must be positive")
    span  = min(int(calendar_days), YAHOO_5M_MAX_LOOKBACK_DAYS)
    chunk = max(1, min(int(chunk_days), YAHOO_5M_CHUNK_DAYS))
    end   = pd.Timestamp.utcnow().floor("s").tz_localize(None)
    start_limit = end - pd.Timedelta(days=span)
    parts: list[pd.DataFrame] = []
    cursor = end
    max_requests = max(4, span // chunk + 4)
    requests = 0
    while cursor > start_limit and requests < max_requests:
        requests += 1
        chunk_start = max(start_limit, cursor - pd.Timedelta(days=chunk))
        raw = dl(
            symbol,
            interval="5m",
            start=chunk_start.strftime("%Y-%m-%d"),
            end=cursor.strftime("%Y-%m-%d"),
            progress=False,
            auto_adjust=False,
            threads=False,
        )
        if raw is not None and not getattr(raw, "empty", True):
            parts.append(normalize_yfinance_ohlcv(raw))
        cursor = chunk_start
        if sleep_sec > 0 and cursor > start_limit:
            time.sleep(float(sleep_sec))
    if not parts:
        raise RuntimeError(
            f"No 5m data returned for {symbol!r} (tried ~{span}d lookback in {chunk}d chunks). "
            "Check symbol, internet, and Yahoo availability."
        )
    merged = pd.concat(parts, axis=0)
    merged = merged[~merged.index.duplicated(keep="last")].sort_index()
    merged = merged[merged.index >= start_limit]
    if merged.empty:
        raise RuntimeError(f"Merged 5m OHLCV empty for {symbol!r}.")
    return merged


__all__ = [
    "YAHOO_1M_CHUNK_DAYS",
    "YAHOO_1M_MAX_LOOKBACK_DAYS",
    "YAHOO_5M_CHUNK_DAYS",
    "YAHOO_5M_MAX_LOOKBACK_DAYS",
    "fetch_1m_bars_chunked_yfinance",
    "fetch_5m_bars_chunked_yfinance",
    "normalize_yfinance_ohlcv",
]

