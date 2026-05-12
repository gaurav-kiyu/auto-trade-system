"""Unit tests for yfinance OHLCV normalization and 1m chunked fetch (mocked)."""

from __future__ import annotations

import pandas as pd

from core.yf_bar_fetch import (
    YAHOO_1M_MAX_LOOKBACK_DAYS,
    fetch_1m_bars_chunked_yfinance,
    normalize_yfinance_ohlcv,
)


def test_normalize_yfinance_basic() -> None:
    idx = pd.date_range("2025-01-01 09:15", periods=3, freq="1min", tz="UTC")
    df = pd.DataFrame(
        {"Open": [1, 2, 3], "High": [1.1, 2.1, 3.1], "Low": [0.9, 1.9, 2.9], "Close": [1.0, 2.0, 3.0], "Volume": [10, 20, 30]},
        index=idx,
    )
    out = normalize_yfinance_ohlcv(df)
    assert list(out.columns) == ["Open", "High", "Low", "Close", "Volume"]
    assert out.index.tz is None
    assert len(out) == 3


def test_normalize_dedupes_index() -> None:
    idx = pd.to_datetime(["2025-01-01 09:15:00", "2025-01-01 09:15:00", "2025-01-01 09:16:00"])
    df = pd.DataFrame(
        {
            "Open": [1.0, 9.0, 2.0],
            "High": [1.1, 9.1, 2.1],
            "Low": [0.9, 8.9, 1.9],
            "Close": [1.0, 9.0, 2.0],
            "Volume": [1, 2, 3],
        },
        index=idx,
    )
    out = normalize_yfinance_ohlcv(df)
    assert len(out) == 2
    assert float(out.loc[out.index[0], "Open"]) == 9.0


def test_fetch_stitches_chunks_mock() -> None:
    calls: list[tuple[str | None, str | None]] = []

    def fake_dl(symbol: str, **kwargs):
        calls.append((kwargs.get("start"), kwargs.get("end")))
        s = kwargs["start"]
        ts = pd.Timestamp(f"{s} 09:15:00")
        return pd.DataFrame(
            {
                "Open": [100.0],
                "High": [101.0],
                "Low": [99.0],
                "Close": [100.5],
                "Volume": [1000.0],
            },
            index=[ts],
        )

    out = fetch_1m_bars_chunked_yfinance("^NSEI", calendar_days=14, chunk_days=7, sleep_sec=0, download_fn=fake_dl)
    assert len(calls) >= 2
    assert not out.empty


def test_fetch_clamps_total_span_to_yahoo_lookback_mock() -> None:
    """calendar_days above Yahoo lookback should not explode request count."""
    n_calls = 0

    def fake_dl(symbol: str, **kwargs):
        nonlocal n_calls
        n_calls += 1
        s = kwargs["start"]
        ts = pd.Timestamp(f"{s} 09:15:00")
        return pd.DataFrame(
            {
                "Open": [100.0],
                "High": [101.0],
                "Low": [99.0],
                "Close": [100.5],
                "Volume": [1000.0],
            },
            index=[ts],
        )

    fetch_1m_bars_chunked_yfinance("^NSEI", calendar_days=365, chunk_days=7, sleep_sec=0, download_fn=fake_dl)
    assert n_calls <= YAHOO_1M_MAX_LOOKBACK_DAYS // 7 + 8
