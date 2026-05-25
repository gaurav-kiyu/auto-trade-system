"""
Edge case tests for market data handling.
Tests for NaN, zero values, extreme prices, stale data.
"""
import time

import pandas as pd
from core.data_freshness_guard import check_data_freshness
from core.liquidity_guard import check_entry_liquidity


class TestLiquidityGuardEdgeCases:
    def test_zero_bid_rejected(self):
        result = check_entry_liquidity(
            bid=0.0, ask=100.0, oi=1000, volume=500
        )
        assert result.passed is False
        assert "No bid" in result.reject_reason

    def test_zero_ask_rejected(self):
        result = check_entry_liquidity(
            bid=100.0, ask=0.0, oi=1000, volume=500
        )
        assert result.passed is False

    def test_bid_greater_than_ask_rejected(self):
        result = check_entry_liquidity(
            bid=110.0, ask=100.0, oi=1000, volume=500
        )
        assert result.passed is False

    def test_negative_prices_rejected(self):
        result = check_entry_liquidity(
            bid=-10.0, ask=100.0, oi=1000, volume=500
        )
        assert result.passed is False

    def test_zero_oi_rejected(self):
        result = check_entry_liquidity(
            bid=100.0, ask=101.0, oi=0, volume=500
        )
        assert result.passed is False

    def test_zero_volume_rejected(self):
        result = check_entry_liquidity(
            bid=100.0, ask=101.0, oi=1000, volume=0
        )
        assert result.passed is False

    def test_none_values_handled(self):
        result = check_entry_liquidity(
            bid=None, ask=None, oi=None, volume=None
        )
        assert result.passed is False

    def test_extreme_spread_rejected(self):
        result = check_entry_liquidity(
            bid=50.0, ask=200.0, oi=1000, volume=500, cfg={"max_entry_spread_pct": 10.0}
        )
        assert result.passed is False
        assert "spread" in result.reject_reason.lower()

    def test_below_minimum_premium_rejected(self):
        result = check_entry_liquidity(
            bid=1.0, ask=1.5, oi=1000, volume=500, cfg={"min_option_premium": 5.0}
        )
        assert result.passed is False


class TestDataFreshnessEdgeCases:
    def test_none_frames_rejected(self):
        result = check_data_freshness(frames=None, vix_ts=None)
        assert result.passed is False
        assert "no market data" in result.reject_reason.lower()

    def test_empty_frames_rejected(self):
        result = check_data_freshness(frames={}, vix_ts=None)
        assert result.passed is False
        assert "no market data" in result.reject_reason.lower()

    def test_vix_stale_rejected(self):
        old_vix_ts = time.time() - 400
        result = check_data_freshness(
            frames={"1m": pd.DataFrame({"close": [22000]})},
            vix_ts=old_vix_ts,
            cfg={"data_freshness_vix_max_age_sec": 300}
        )
        assert result.passed is False

    def test_fresh_data_passes(self):
        now_ts = pd.Timestamp.now()
        df = pd.DataFrame({"close": [22000]}, index=[now_ts])
        frames = {"1m": df, "5m": df, "15m": df}
        result = check_data_freshness(
            frames=frames,
            vix_ts=time.time(),
            cfg={
                "data_freshness_max_age_1m_sec": 90,
                "data_freshness_max_age_5m_sec": 300,
                "data_freshness_max_age_15m_sec": 600,
                "data_freshness_vix_max_age_sec": 300
            }
        )
        assert result.passed is True


class TestPriceSanityChecks:
    def test_guard_rejects_zero_bid(self):
        from core.liquidity_guard import check_entry_liquidity
        result = check_entry_liquidity(bid=0, ask=100, oi=100, volume=100)
        assert result.passed is False

    def test_guard_rejects_zero_ask(self):
        from core.liquidity_guard import check_entry_liquidity
        result = check_entry_liquidity(bid=100, ask=0, oi=100, volume=100)
        assert result.passed is False

    def test_guard_rejects_invalid_spread(self):
        from core.liquidity_guard import check_entry_liquidity
        result = check_entry_liquidity(bid=100, ask=50, oi=100, volume=100)
        assert result.passed is False

    def test_freshness_guard_enabled_by_default(self):
        result = check_data_freshness(frames=None, vix_ts=None, cfg={})
        assert result.passed is False

    def test_freshness_guard_cannot_be_disabled(self):
        result = check_data_freshness(
            frames=None,
            vix_ts=None,
            cfg={"data_freshness_guard_enabled": False}
        )
        assert result.passed is False  # Guard is always active — safety invariant
