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

    def test_flattens_multiindex_columns(self, mock_ohlcv_df):
        """yfinance >= 0.2.30 returns MultiIndex columns - must be flattened."""
        import numpy as np

        mi = pd.MultiIndex.from_tuples(
            [(c, "^NSEI") for c in ("Close", "High", "Low", "Open", "Volume")]
        )
        multi_df = pd.DataFrame(mock_ohlcv_df.values, columns=mi, index=mock_ohlcv_df.index)
        with patch("core.yf_data_provider.yf.download", return_value=multi_df):
            result = fetch_intraday_data("^NSEI")
            assert result[0] is not None
            assert result[0].columns.nlevels == 1
            assert "Close" in result[0].columns
            # FeatureEngine-style access must return a Series (not DataFrame),
            # and its last value must be a plain numeric scalar
            assert isinstance(result[0]["Close"], pd.Series)
            assert isinstance(result[0]["Close"].iloc[-1], (int, float, np.floating))

    def test_flat_columns_unchanged(self, mock_ohlcv_df):
        """Single-level columns must pass through untouched."""
        with patch("core.yf_data_provider.yf.download", return_value=mock_ohlcv_df):
            result = fetch_intraday_data("^NSEI")
            assert result[0] is not None
            assert result[0].columns.nlevels == 1
            assert list(result[0].columns) == list(mock_ohlcv_df.columns)


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

# =============================================================================
# Exponential Backoff Tests (v2.54)
# =============================================================================

class TestYfBackoff:
    """Tests for the exponential backoff mechanism in yf_data_provider."""

    def test_no_backoff_on_first_call(self):
        """A fresh symbol has zero failures, so delay is 0."""
        from core.yf_data_provider import _get_backoff_delay, _record_success
        # Ensure clean state
        _record_success("TEST_SYM")
        delay = _get_backoff_delay("TEST_SYM")
        assert delay == 0.0

    def test_backoff_increases_with_failures(self):
        """Each failure increases the backoff delay exponentially."""
        from core.yf_data_provider import _get_backoff_delay, _record_failure, _record_success
        _record_success("TEST_BACKOFF")  # reset
        delay0 = _get_backoff_delay("TEST_BACKOFF")
        assert delay0 == 0.0
        _record_failure("TEST_BACKOFF")
        delay1 = _get_backoff_delay("TEST_BACKOFF")
        assert delay1 >= 3.0  # 5s base * 0.75 jitter min
        _record_failure("TEST_BACKOFF")
        delay2 = _get_backoff_delay("TEST_BACKOFF")
        assert delay2 >= delay1 * 0.75  # should be larger

    def test_success_resets_backoff(self):
        """After a success, the failure count is reset to 0."""
        from core.yf_data_provider import _get_backoff_delay, _record_failure, _record_success
        _record_success("TEST_RESET")
        _record_failure("TEST_RESET")
        _record_failure("TEST_RESET")
        delay_before = _get_backoff_delay("TEST_RESET")
        assert delay_before > 0
        _record_success("TEST_RESET")
        delay_after = _get_backoff_delay("TEST_RESET")
        assert delay_after == 0.0

    def test_max_backoff_capped(self):
        """Backoff does not exceed _YF_MAX_BACKOFF (300s) with jitter."""
        from core.yf_data_provider import _get_backoff_delay, _record_failure, _record_success
        _record_success("TEST_MAX")
        for _ in range(20):
            _record_failure("TEST_MAX")
        delay = _get_backoff_delay("TEST_MAX")
        # Base delay = min(5*2^19, 300) = 300. With 1.25x jitter max = 375.
        assert delay <= 380  # 300s max * 1.25 jitter + tolerance

    def test_backoff_applied_before_yfinance_call(self):
        """When fetch_intraday_data is called with a failing symbol, failure counter increments."""
        from unittest.mock import patch

        from core.yf_data_provider import _get_backoff_delay, _record_success, fetch_intraday_data
        _record_success("^NSEI_TEST")
        with patch("core.yf_data_provider.yf.download", side_effect=Exception("API error")):
            result = fetch_intraday_data("^NSEI_TEST")
        assert result == (None, None, None)
        # One failure recorded
        delay = _get_backoff_delay("^NSEI_TEST")
        assert delay > 0


# =============================================================================
# Coverage Edge Cases (v2.55)
# =============================================================================

class TestYfBackoffSleepPath:
    """Tests for the backoff-delay sleep path in fetch_intraday_data (lines 121-122)."""

    def test_backoff_trigger_sleep(self) -> None:
        """When backoff delay > 0, _sleep_or_shutdown is called."""
        from core.yf_data_provider import _record_failure, _record_success, fetch_intraday_data
        _record_success("^SLEEP_TEST")
        _record_failure("^SLEEP_TEST")

        with (
            patch("core.yf_data_provider._sleep_or_shutdown") as mock_sleep,
            patch("core.yf_data_provider.yf.download", return_value=None),
        ):
            fetch_intraday_data("^SLEEP_TEST")
            mock_sleep.assert_called_once()


class TestVixBackoffPath:
    """Tests for the backoff-delay path in fetch_vix (lines 210-211)."""

    def test_vix_backoff_triggered(self) -> None:
        """When VIX fetch has repeated failures, backoff delay is applied."""
        from core.yf_data_provider import _record_failure, fetch_vix
        _record_failure("^INDIAVIX")
        _record_failure("^INDIAVIX")
        with patch("core.yf_data_provider.yf.download", return_value=None):
            result = fetch_vix()
            assert result == 0.0

    def test_vix_unexpected_exception(self) -> None:
        """An unexpected exception in fetch_vix is caught and returns 0.0."""
        from core.yf_data_provider import _record_success, fetch_vix
        _record_success("^INDIAVIX")
        with patch("core.yf_data_provider.yf.download", side_effect=RuntimeError("unexpected")):
            result = fetch_vix()
            assert result == 0.0


class TestGetVixFromIntradayEdgeCases:
    """Tests for edge cases in get_vix_from_intraday."""

    def test_backoff_path(self) -> None:
        """Backoff delay path in get_vix_from_intraday (line 249)."""
        from core.yf_data_provider import _record_failure, get_vix_from_intraday
        _record_failure("^INDIAVIX")
        with patch("core.yf_data_provider.yf.download", return_value=None):
            result = get_vix_from_intraday()
            assert result == 0.0

    def test_unexpected_exception(self) -> None:
        """Unexpected exception path (lines 253-255)."""
        from core.yf_data_provider import _record_success, get_vix_from_intraday
        _record_success("^INDIAVIX")
        with patch("core.yf_data_provider.yf.download", side_effect=RuntimeError("unexpected")):
            result = get_vix_from_intraday()
            assert result == 0.0


class TestSleepOrShutdown:
    """Tests for _sleep_or_shutdown fallback path (lines 302-303)."""

    def test_normal_path(self) -> None:
        """Normal path calls _shutdown.wait()."""
        from core.yf_data_provider import _sleep_or_shutdown
        with patch("core.safety_state._shutdown.wait") as mock_wait:
            _sleep_or_shutdown(0.001)
            mock_wait.assert_called_once_with(0.001)

    def test_fallback_when_shutdown_raises(self) -> None:
        """When _shutdown.wait() raises AttributeError, falls back to time.sleep."""

        from core.yf_data_provider import _sleep_or_shutdown
        with patch("core.yf_data_provider.time.sleep") as mock_sleep:
            with patch("core.safety_state._shutdown") as mock_shutdown:
                mock_shutdown.wait.side_effect = AttributeError("no wait method")
                _sleep_or_shutdown(0.001)
                mock_sleep.assert_called_once_with(0.001)


class TestFetchLastCloseSummaryCache:
    """Tests for last-close-summary cache hit path (lines 165-166, 186-191)."""

    def test_cache_hit(self, mock_ohlcv_df) -> None:
        """Second identical call returns cached result without yfinance call."""
        with patch("core.yf_data_provider.yf.Ticker") as mock_ticker:
            mock_ticker.return_value.history.return_value = mock_ohlcv_df
            r1 = fetch_last_close_summary({"NIFTY": {"yf": "^NSEI"}})
            assert len(r1) == 1
            r2 = fetch_last_close_summary({"NIFTY": {"yf": "^NSEI"}})
            assert r2.get("NIFTY") == r1.get("NIFTY")

    def test_cache_key_miss(self, mock_ohlcv_df) -> None:
        """Different symbol bypasses cache and triggers new fetch."""
        with patch("core.yf_data_provider.yf.Ticker") as mock_ticker:
            mock_ticker.return_value.history.return_value = mock_ohlcv_df
            fetch_last_close_summary({"NIFTY": {"yf": "^NSEI"}})
            r2 = fetch_last_close_summary({"BANKNIFTY": {"yf": "^NSEBANK"}})
            assert len(r2) == 1
            assert "BANKNIFTY" in r2

    def test_handles_yfinance_unexpected_exception(self) -> None:
        """Unexpected exception in ticker.history is caught gracefully."""
        from core.yf_data_provider import fetch_last_close_summary

        def throw_error(*args, **kwargs):
            raise RuntimeError("unexpected")

        mock_ticker = type("MockTicker", (), {"history": throw_error})()
        with patch("core.yf_data_provider.yf.Ticker", return_value=mock_ticker):
            result = fetch_last_close_summary({"NIFTY": {"yf": "^NSEI"}})
            assert result == {}

    def test_single_row_dataframe(self) -> None:
        """A DataFrame with only 1 row should still work (uses same row for prev)."""
        df = pd.DataFrame({
            "Close": [23100.0],
            "Open": [23000.0],
            "High": [23150.0],
            "Low": [23050.0],
            "Volume": [100000],
        }, index=pd.date_range("2026-06-01", periods=1, freq="D"))
        with patch("core.yf_data_provider.yf.Ticker") as mock_ticker:
            mock_ticker.return_value.history.return_value = df
            result = fetch_last_close_summary({"NIFTY": {"yf": "^NSEI"}})
            assert len(result) == 1
            assert result["NIFTY"]["pct"] == 0.0
