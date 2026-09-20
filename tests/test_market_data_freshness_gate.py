"""
Comprehensive test suite for Market Data Freshness Gate (P0 Requirement).
Tests:
- fresh 1-minute candle
- valid 5-minute fallback
- stale candle rejection with STALE_MARKET_DATA
- missing timestamp rejection with INVALID_MARKET_DATA
- malformed timestamp rejection with INVALID_MARKET_DATA
- future timestamp rejection with INVALID_MARKET_DATA
- weekend / off-market handling (no false rejection of closing reference data)
- NSE holiday handling
- market open session vs closed session
- timezone conversion (IST vs UTC vs naive)
- sparse 1m -> valid 5m fallback
- stale 5m fallback rejection
- zero unhandled exceptions on corrupt/malformed data
"""
import datetime
import time
import pytest
import pandas as pd

from core.data_freshness_guard import check_data_freshness, FreshnessResult
from core.exchange_calendar_engine import ExchangeCalendarEngine, ExtendedMarketStatus


class MockCalendarEngine:
    """Mock calendar engine for testing market open / closed / holiday sessions."""

    def __init__(self, status: ExtendedMarketStatus = ExtendedMarketStatus.OPEN):
        self._status = status

    def get_market_status(self, dt=None):
        return self._status

    def is_market_day(self, check_date=None):
        return self._status not in (ExtendedMarketStatus.NON_TRADING,)


class TestMarketDataFreshnessGate:
    def test_fresh_1m_candle_passes(self):
        """During active session, a fresh 1m candle (e.g. 30s old) passes with VALID."""
        now = time.time()
        df1m = pd.DataFrame(
            {"close": [24500.0, 24505.0]},
            index=[pd.Timestamp.fromtimestamp(now - 30, tz="Asia/Kolkata"),
                   pd.Timestamp.fromtimestamp(now - 10, tz="Asia/Kolkata")]
        )
        res = check_data_freshness(
            frames={"1m": df1m},
            current_time=now,
            calendar_engine=MockCalendarEngine(ExtendedMarketStatus.OPEN),
            session_aware=True,
        )
        assert res.passed is True
        assert res.reject_code == "VALID"

    def test_stale_1m_candle_rejected_during_market_open(self):
        """During active session, a 1m candle older than 90s is rejected as STALE_MARKET_DATA."""
        now = time.time()
        df1m = pd.DataFrame(
            {"close": [24500.0]},
            index=[pd.Timestamp.fromtimestamp(now - 200, tz="Asia/Kolkata")]
        )
        res = check_data_freshness(
            frames={"1m": df1m},
            current_time=now,
            calendar_engine=MockCalendarEngine(ExtendedMarketStatus.OPEN),
            session_aware=True,
        )
        assert res.passed is False
        assert res.reject_code == "STALE_MARKET_DATA"
        assert "exceeds" in res.reject_reason

    def test_sparse_1m_falls_back_to_valid_5m(self):
        """When 1m candle is sparse/empty, a fresh 5m candle within limit is accepted."""
        now = time.time()
        df1m = pd.DataFrame()  # Sparse/empty
        df5m = pd.DataFrame(
            {"close": [24500.0, 24510.0]},
            index=[pd.Timestamp.fromtimestamp(now - 300, tz="Asia/Kolkata"),
                   pd.Timestamp.fromtimestamp(now - 120, tz="Asia/Kolkata")]
        )
        res = check_data_freshness(
            frames={"df1m": df1m, "df5m": df5m},
            current_time=now,
            calendar_engine=MockCalendarEngine(ExtendedMarketStatus.OPEN),
            session_aware=True,
        )
        assert res.passed is True
        assert res.reject_code == "VALID"

    def test_stale_5m_fallback_rejected(self):
        """When 1m candle is empty and fallback 5m is older than 300s, it is rejected."""
        now = time.time()
        df5m = pd.DataFrame(
            {"close": [24500.0]},
            index=[pd.Timestamp.fromtimestamp(now - 450, tz="Asia/Kolkata")]
        )
        res = check_data_freshness(
            frames={"df5m": df5m},
            current_time=now,
            calendar_engine=MockCalendarEngine(ExtendedMarketStatus.OPEN),
            session_aware=True,
        )
        assert res.passed is False
        assert res.reject_code == "STALE_MARKET_DATA"

    def test_missing_timestamp_rejected(self):
        """DataFrame with no parseable timestamp is rejected as INVALID_MARKET_DATA."""
        df = pd.DataFrame({"close": [100.0, 101.0]})
        df.index = [pd.NaT, pd.NaT]  # NaT timestamps
        res = check_data_freshness(
            frames={"1m": df},
            calendar_engine=MockCalendarEngine(ExtendedMarketStatus.OPEN),
            session_aware=True,
        )
        assert res.passed is False
        assert res.reject_code == "INVALID_MARKET_DATA"

    def test_malformed_timestamp_rejected(self):
        """DataFrame with corrupt non-date string timestamp is rejected gracefully."""
        df = pd.DataFrame({"timestamp": ["corrupted_garbage"], "close": [100.0]})
        res = check_data_freshness(
            frames={"1m": df},
            calendar_engine=MockCalendarEngine(ExtendedMarketStatus.OPEN),
            session_aware=True,
        )
        assert res.passed is False
        assert res.reject_code == "INVALID_MARKET_DATA"

    def test_future_timestamp_rejected(self):
        """Candles with timestamps far in the future (> 60s ahead) are rejected."""
        now = time.time()
        future_ts = now + 500  # 500s into future
        df = pd.DataFrame(
            {"close": [100.0]},
            index=[pd.Timestamp.fromtimestamp(future_ts, tz="Asia/Kolkata")]
        )
        res = check_data_freshness(
            frames={"1m": df},
            current_time=now,
            calendar_engine=MockCalendarEngine(ExtendedMarketStatus.OPEN),
            session_aware=True,
        )
        assert res.passed is False
        assert res.reject_code == "INVALID_MARKET_DATA"
        assert "future" in res.reject_reason

    def test_weekend_and_holiday_graceful_handling(self):
        """Outside active market hours (weekend/holiday), historical closing data is not rejected as stale."""
        ref_time = time.time()
        # Bar from Friday close (e.g. 24 hours ago)
        df = pd.DataFrame(
            {"close": [100.0]},
            index=[pd.Timestamp.fromtimestamp(ref_time - 86400, tz="Asia/Kolkata")]
        )
        # Test weekend (NON_TRADING)
        res_weekend = check_data_freshness(
            frames={"1m": df},
            current_time=ref_time,
            calendar_engine=MockCalendarEngine(ExtendedMarketStatus.NON_TRADING),
            session_aware=True,
            allow_off_market=True,
        )
        assert res_weekend.passed is True
        assert res_weekend.reject_code == "VALID"

        # Test post-market (POST_MARKET)
        res_post = check_data_freshness(
            frames={"1m": df},
            current_time=ref_time,
            calendar_engine=MockCalendarEngine(ExtendedMarketStatus.POST_MARKET),
            session_aware=True,
            allow_off_market=True,
        )
        assert res_post.passed is True
        assert res_post.reject_code == "VALID"

    def test_timezone_naive_and_aware_parity(self):
        """Tz-naive timestamps in IST local time are parsed identically to tz-aware IST timestamps."""
        now = time.time()
        aware_ts = pd.Timestamp.fromtimestamp(now - 20, tz="Asia/Kolkata")
        naive_ts = aware_ts.tz_localize(None)

        df_aware = pd.DataFrame({"close": [100.0]}, index=[aware_ts])
        df_naive = pd.DataFrame({"close": [100.0]}, index=[naive_ts])

        res_aware = check_data_freshness(
            frames={"1m": df_aware},
            current_time=now,
            calendar_engine=MockCalendarEngine(ExtendedMarketStatus.OPEN),
            session_aware=True,
        )
        res_naive = check_data_freshness(
            frames={"1m": df_naive},
            current_time=now,
            calendar_engine=MockCalendarEngine(ExtendedMarketStatus.OPEN),
            session_aware=True,
        )

        assert res_aware.passed is True
        assert res_naive.passed is True
        assert abs(res_aware.stalest_bar_sec - res_naive.stalest_bar_sec) < 0.5

    def test_no_exception_on_corrupt_data(self):
        """Completely corrupt or unexpected data structure returns FreshnessResult(passed=False) without crashing."""
        corrupt_frames = {
            "1m": "not_even_a_dataframe",
            "5m": None,
        }
        res = check_data_freshness(
            frames=corrupt_frames,
            calendar_engine=MockCalendarEngine(ExtendedMarketStatus.OPEN),
            session_aware=True,
        )
        assert isinstance(res, FreshnessResult)
        assert res.passed is False
        assert res.reject_code == "INVALID_MARKET_DATA"
