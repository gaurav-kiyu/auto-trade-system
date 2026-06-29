"""Unit tests for core.yf_data_provider.

Tests the 6 exported functions using mocked yfinance responses.
"""

from __future__ import annotations

from unittest.mock import patch

import pandas as pd
import pytest
from core.yf_data_provider import (
    fetch_intraday_data,
    fetch_intraday_data_cached,
    fetch_last_close_summary,
    fetch_vix,
    get_vix_from_intraday,
    invalidate_cache,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def clear_cache():
    """Ensure a clean cache before each test."""
    invalidate_cache()
    yield


@pytest.fixture
def mock_ohlcv_df():
    """Create a realistic OHLCV DataFrame."""
    import numpy as np
    dates = pd.date_range("2026-06-01 09:15", periods=10, freq="1min", tz="Asia/Kolkata")
    return pd.DataFrame({
        "Open": np.linspace(23000, 23100, 10),
        "High": np.linspace(23050, 23150, 10),
        "Low": np.linspace(22950, 23050, 10),
        "Close": np.linspace(23000, 23100, 10),
        "Volume": [100000] * 10,
    }, index=dates)


@pytest.fixture
def mock_empty_df():
    """Empty DataFrame for failure tests."""
    return pd.DataFrame()


# ---------------------------------------------------------------------------
# fetch_intraday_data
# ---------------------------------------------------------------------------

class TestFetchIntradayData:
    def test_returns_tuple(self, mock_ohlcv_df):
        with patch("core.yf_data_provider.yf.download", return_value=mock_ohlcv_df) as mock_dl:
            result = fetch_intraday_data("^NSEI")
            assert isinstance(result, tuple)
            assert len(result) == 3
            assert mock_dl.call_count == 3

    def test_returns_none_for_empty_symbol(self):
        result = fetch_intraday_data("")
        assert result == (None, None, None)

    def test_handles_yfinance_error(self):
        with patch("core.yf_data_provider.yf.download", side_effect=Exception("API error")):
            result = fetch_intraday_data("^NSEI")
            assert result == (None, None, None)

    def test_handles_empty_dataframes(self, mock_empty_df):
        with patch("core.yf_data_provider.yf.download", return_value=mock_empty_df):
            result = fetch_intraday_data("^NSEI")
            assert result == (None, None, None)


# ---------------------------------------------------------------------------
# fetch_intraday_data_cached
# ---------------------------------------------------------------------------

class TestFetchIntradayDataCached:
    def test_caches_result(self, mock_ohlcv_df):
        with patch("core.yf_data_provider.yf.download", return_value=mock_ohlcv_df) as mock_dl:
            # First call - should fetch
            r1 = fetch_intraday_data_cached("^NSEI")
            assert mock_dl.call_count >= 3

            # Second call - should use cache (within TTL)
            calls_before = mock_dl.call_count
            r2 = fetch_intraday_data_cached("^NSEI")
            assert mock_dl.call_count == calls_before  # no new calls
            assert r1 == r2

    def test_cache_expires_after_ttl(self, mock_ohlcv_df):
        with patch("core.yf_data_provider.yf.download", return_value=mock_ohlcv_df) as mock_dl, \
             patch("core.yf_data_provider.time.time") as mock_time:
            # First call at t=0
            mock_time.return_value = 0.0
            fetch_intraday_data_cached("^NSEI")
            calls_after_first = mock_dl.call_count

            # Second call at t=100s (past 60s TTL) - should re-fetch
            mock_time.return_value = 100.0
            fetch_intraday_data_cached("^NSEI")
            assert mock_dl.call_count > calls_after_first

    def test_handles_cache_miss(self, mock_ohlcv_df):
        with patch("core.yf_data_provider.yf.download", return_value=mock_ohlcv_df):
            result = fetch_intraday_data_cached("^NSEI")
            assert result is not None
            assert len(result) == 3


# ---------------------------------------------------------------------------
# fetch_last_close_summary
# ---------------------------------------------------------------------------

class TestFetchLastCloseSummary:
    def test_returns_dict(self, mock_ohlcv_df):
        with patch("core.yf_data_provider.yf.Ticker") as mock_ticker:
            mock_ticker.return_value.history.return_value = mock_ohlcv_df
            result = fetch_last_close_summary({"NIFTY": {"yf": "^NSEI"}})
            assert isinstance(result, dict)
            assert "NIFTY" in result
            assert "close" in result["NIFTY"]
            assert "pct" in result["NIFTY"]
            assert "date" in result["NIFTY"]

    def test_handles_empty_index_map(self):
        result = fetch_last_close_summary({})
        assert result == {}

    def test_skips_missing_yf_symbol(self):
        result = fetch_last_close_summary({"NIFTY": {}})
        assert result == {}

    def test_handles_yfinance_error(self, mock_empty_df):
        with patch("core.yf_data_provider.yf.Ticker") as mock_ticker:
            mock_ticker.return_value.history.return_value = mock_empty_df
            result = fetch_last_close_summary({"NIFTY": {"yf": "^NSEI"}})
            assert result == {}


# ---------------------------------------------------------------------------
# fetch_vix
# ---------------------------------------------------------------------------

class TestFetchVix:
    def test_returns_float(self, mock_ohlcv_df):
        with patch("core.yf_data_provider.yf.download", return_value=mock_ohlcv_df):
            vix = fetch_vix()
            assert isinstance(vix, float)
            assert vix > 0

    def test_returns_zero_on_empty(self, mock_empty_df):
        with patch("core.yf_data_provider.yf.download", return_value=mock_empty_df):
            vix = fetch_vix()
            assert vix == 0.0

    def test_returns_zero_on_error(self):
        with patch("core.yf_data_provider.yf.download", side_effect=Exception("API error")):
            vix = fetch_vix()
            assert vix == 0.0


# ---------------------------------------------------------------------------
# get_vix_from_intraday
# ---------------------------------------------------------------------------

class TestGetVixFromIntraday:
    def test_returns_float(self, mock_ohlcv_df):
        with patch("core.yf_data_provider.yf.download", return_value=mock_ohlcv_df):
            vix = get_vix_from_intraday()
            assert isinstance(vix, float)

    def test_returns_zero_on_empty(self, mock_empty_df):
        with patch("core.yf_data_provider.yf.download", return_value=mock_empty_df):
            vix = get_vix_from_intraday()
            assert vix == 0.0

    def test_returns_zero_on_error(self):
        with patch("core.yf_data_provider.yf.download", side_effect=Exception("API error")):
            vix = get_vix_from_intraday()
            assert vix == 0.0


# ---------------------------------------------------------------------------
# invalidate_cache
# ---------------------------------------------------------------------------

class TestInvalidateCache:
    def test_clears_both_caches(self, mock_ohlcv_df):
        # Populate cache
        with patch("core.yf_data_provider.yf.download", return_value=mock_ohlcv_df), \
             patch("core.yf_data_provider.yf.Ticker") as mock_ticker:
            mock_ticker.return_value.history.return_value = mock_ohlcv_df
            fetch_intraday_data_cached("^NSEI")
            fetch_last_close_summary({"NIFTY": {"yf": "^NSEI"}})

        # Invalidate
        invalidate_cache()

        # Verify cache is cleared - fetching should trigger new yfinance calls
        with patch("core.yf_data_provider.yf.download", return_value=mock_ohlcv_df) as mock_dl, \
             patch("core.yf_data_provider.yf.Ticker") as mock_ticker:
            mock_ticker.return_value.history.return_value = mock_ohlcv_df
            fetch_intraday_data_cached("^NSEI")
            assert mock_dl.call_count >= 3  # fresh fetch after invalidation
