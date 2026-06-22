"""Tests for liquidity_analytics module."""

from __future__ import annotations

import pytest
from core.liquidity_analytics import (
    LiquidityAnalytics,
    SpreadMetrics,
    VolumeProfile,
    LiquidityScore,
    assess_liquidity,
)


class TestLiquidityAnalyticsBasic:
    """Basic tests for the LiquidityAnalytics engine."""

    def test_empty_initialization(self):
        """New instance should have no samples."""
        la = LiquidityAnalytics()
        assert la.n_samples == 0
        assert la.average_spread() == 0.0

    def test_add_trade_with_bid_ask(self):
        """Adding a trade with bid/ask should compute spread."""
        la = LiquidityAnalytics()
        la.add_trade(price=100.0, volume=1000, bid=99.5, ask=100.5)
        assert la.n_samples == 1
        spread = la.average_spread()
        assert spread > 0.0
        assert spread < 2.0  # ~1% relative spread

    def test_add_trade_without_bid_ask(self):
        """Adding a trade without bid/ask should use synthetic spread."""
        la = LiquidityAnalytics()
        la.add_trade(price=100.0, volume=1000)
        assert la.n_samples == 1
        spread = la.average_spread()
        assert abs(spread - 0.5) < 0.01  # synthetic 0.5%

    def test_add_trade_with_open_interest(self):
        """Adding OI should be tracked separately."""
        la = LiquidityAnalytics()
        la.add_trade(price=100.0, volume=1000, open_interest=500000)
        oi = la.oi_analysis()
        assert oi["status"] == "insufficient"  # need 3+ samples for OI analysis

    def test_clear(self):
        """Clearing should reset all state."""
        la = LiquidityAnalytics()
        la.add_trade(price=100.0, volume=1000, bid=99.5, ask=100.5)
        assert la.n_samples == 1
        la.clear()
        assert la.n_samples == 0
        assert la.average_spread() == 0.0

    def test_multiple_trades(self):
        """Multiple trades should accumulate correctly."""
        la = LiquidityAnalytics()
        for i in range(10):
            la.add_trade(price=100.0 + i, volume=1000 * (i + 1))
        assert la.n_samples == 10


class TestSpreadAnalysis:
    """Tests for spread analysis."""

    def test_average_spread_computation(self):
        """Average spread should be computed correctly."""
        la = LiquidityAnalytics()
        la.add_trade(100.0, 1000, 99.5, 100.5)  # ~1.0% spread
        la.add_trade(101.0, 1000, 100.0, 102.0)  # ~2.0% spread
        avg = la.average_spread()
        assert 1.0 < avg < 2.0

    def test_spread_percentile(self):
        """Spread percentile should return correct value."""
        la = LiquidityAnalytics()
        la.add_trade(100.0, 1000, 99.5, 100.5)  # ~1.0%
        la.add_trade(100.0, 1000, 99.0, 101.0)  # ~2.0%
        la.add_trade(100.0, 1000, 99.8, 100.2)  # ~0.4%
        p50 = la.spread_percentile(50.0)
        p100 = la.spread_percentile(100.0)
        assert p50 <= p100

    def test_empty_spread_percentile(self):
        """Empty spread percentile should return 0.0."""
        la = LiquidityAnalytics()
        assert la.spread_percentile(95.0) == 0.0


class TestVolumeProfile:
    """Tests for volume profile analysis."""

    def test_volume_profile_basic(self):
        """Volume profile should compute basic stats."""
        la = LiquidityAnalytics()
        la.add_trade(100.0, 10000)
        la.add_trade(101.0, 20000)
        la.add_trade(102.0, 30000)
        vp = la.volume_profile()
        assert vp.n_observations == 3
        assert vp.total_volume == 60000
        assert vp.avg_volume == 20000
        assert vp.peak_volume == 30000
        assert vp.vwap > 0

    def test_vwap_computation(self):
        """VWAP should be volume-weighted."""
        la = LiquidityAnalytics()
        la.add_trade(100.0, 100)
        la.add_trade(200.0, 100)
        vp = la.volume_profile()
        assert abs(vp.vwap - 150.0) < 0.01  # (100*100 + 200*100) / 200

    def test_volume_concentration(self):
        """Volume concentration should capture top-heavy distribution."""
        la = LiquidityAnalytics()
        la.add_trade(100.0, 10)
        la.add_trade(101.0, 10)
        la.add_trade(102.0, 10)
        la.add_trade(103.0, 10)
        la.add_trade(104.0, 10)
        la.add_trade(105.0, 10)
        la.add_trade(106.0, 10)
        la.add_trade(107.0, 10)
        la.add_trade(108.0, 10)
        la.add_trade(109.0, 100)  # top 10% has 100 out of 190
        vp = la.volume_profile()
        assert vp.volume_concentration > 0.4  # top 10% likely > 40%

    def test_empty_volume_profile(self):
        """Empty volume profile should return zeros."""
        la = LiquidityAnalytics()
        vp = la.volume_profile()
        assert vp.total_volume == 0.0
        assert vp.n_observations == 0


class TestOIAnalysis:
    """Tests for open interest analysis."""

    def test_oi_basic(self):
        """OI analysis with 3+ samples should compute stats."""
        la = LiquidityAnalytics()
        la.add_trade(100.0, 1000, open_interest=500000)
        la.add_trade(101.0, 1000, open_interest=510000)
        la.add_trade(102.0, 1000, open_interest=520000)
        oi = la.oi_analysis()
        assert oi["status"] == "ok"
        assert oi["avg_oi"] == 510000
        assert oi["oi_growth_rate_pct"] > 0  # positive growth

    def test_oi_negative_trend(self):
        """Declining OI should show negative growth rate."""
        la = LiquidityAnalytics()
        la.add_trade(100.0, 1000, open_interest=500000)
        la.add_trade(101.0, 1000, open_interest=490000)
        la.add_trade(102.0, 1000, open_interest=480000)
        oi = la.oi_analysis()
        assert oi["oi_growth_rate_pct"] < 0

    def test_oi_insufficient_data(self):
        """Less than 3 OI samples should return insufficient."""
        la = LiquidityAnalytics()
        la.add_trade(100.0, 1000, open_interest=500000)
        oi = la.oi_analysis()
        assert oi["status"] == "insufficient"


class TestLiquidityScore:
    """Tests for the composite liquidity score."""

    def test_insufficient_data(self):
        """Fewer than min_samples should return INSUFFICIENT_DATA."""
        la = LiquidityAnalytics(min_samples=10)
        la.add_trade(100.0, 1000)
        la.add_trade(101.0, 1000)
        score = la.liquidity_score()
        assert score.regime == "INSUFFICIENT_DATA"
        assert score.composite_score == 0.0

    def test_liquid_regime(self):
        """Tight spreads and high volume should produce LIQUID regime."""
        la = LiquidityAnalytics(min_samples=10)
        for _ in range(12):
            la.add_trade(
                price=100.0,
                volume=500000,
                bid=99.8,
                ask=100.2,  # 0.4% spread
                open_interest=2000000,
            )
        score = la.liquidity_score()
        assert score.regime in ("LIQUID", "NORMAL")
        assert score.spread_score > 80

    def test_illiquid_regime(self):
        """Wide spreads and low volume should produce ILLIQUID regime."""
        la = LiquidityAnalytics(min_samples=10)
        for _ in range(12):
            la.add_trade(
                price=100.0,
                volume=100,
                bid=95.0,
                ask=105.0,  # ~10% spread
            )
        score = la.liquidity_score()
        assert score.regime in ("ILLIQUID", "EXTREME")
        assert score.spread_score < 30
        assert score.volume_score < 30

    def test_score_range(self):
        """Score should always be in 0-100 range."""
        la = LiquidityAnalytics(min_samples=10)
        for _ in range(15):
            import random
            la.add_trade(
                price=100.0 + random.gauss(0, 1),
                volume=random.randint(100, 1000000),
                bid=99.0,
                ask=101.0,
            )
        score = la.liquidity_score()
        assert 0 <= score.composite_score <= 100
        assert 0 <= score.spread_score <= 100
        assert 0 <= score.volume_score <= 100

    def test_to_dict(self):
        """to_dict should produce serializable output."""
        la = LiquidityAnalytics(min_samples=3)
        la.add_trade(100.0, 100000, 99.5, 100.5)
        la.add_trade(101.0, 200000, 100.0, 102.0)
        la.add_trade(102.0, 150000, 101.0, 103.0)
        score = la.liquidity_score()
        d = score.to_dict()
        assert "composite_score" in d
        assert "regime" in d
        assert "n_samples" in d

    def test_summary(self):
        """Summary should be a non-empty string."""
        la = LiquidityAnalytics(min_samples=3)
        la.add_trade(100.0, 100000, 99.5, 100.5)
        la.add_trade(101.0, 200000, 100.0, 102.0)
        la.add_trade(102.0, 150000, 101.0, 103.0)
        score = la.liquidity_score()
        summary = score.summary()
        assert isinstance(summary, str)
        assert len(summary) > 20

    def test_oi_bonus_in_score(self):
        """Growing OI should boost liquidity score."""
        la_high = LiquidityAnalytics(min_samples=10)
        la_low = LiquidityAnalytics(min_samples=10)
        for i in range(12):
            la_high.add_trade(100.0, 500000, 99.8, 100.2, open_interest=100000 * (10 + i))
            la_low.add_trade(100.0, 500000, 99.8, 100.2, open_interest=100000 * (10 - i))
        score_high = la_high.liquidity_score()
        score_low = la_low.liquidity_score()
        assert score_high.composite_score >= score_low.composite_score


class TestTimeOfDayPattern:
    """Tests for time-of-day pattern detection."""

    def test_no_timestamps(self):
        """No timestamps should return empty list."""
        la = LiquidityAnalytics()
        la.add_trade(100.0, 1000, 99.5, 100.5)
        patterns = la.time_of_day_pattern()
        assert patterns == []

    def test_single_hour(self):
        """Trades in same hour should group together."""
        la = LiquidityAnalytics()
        ts = "2026-06-21T10:00:00"
        la.add_trade(100.0, 1000, 99.5, 100.5, timestamp=ts)
        la.add_trade(101.0, 2000, 100.5, 101.5, timestamp=ts)
        patterns = la.time_of_day_pattern()
        assert len(patterns) >= 1
        assert patterns[0]["hour"] == 10
        assert patterns[0]["n_samples"] == 2

    def test_multiple_hours(self):
        """Trades in different hours should create separate groups."""
        la = LiquidityAnalytics()
        la.add_trade(100.0, 1000, 99.5, 100.5, timestamp="2026-06-21T09:30:00")
        la.add_trade(101.0, 2000, 100.5, 101.5, timestamp="2026-06-21T10:30:00")
        patterns = la.time_of_day_pattern()
        assert len(patterns) >= 2
        hours = [p["hour"] for p in patterns]
        assert 9 in hours or 10 in hours


class TestAssessLiquidity:
    """Tests for the convenience function."""

    def test_basic_function(self):
        """Convenience function should work with list inputs."""
        result = assess_liquidity(
            prices=[100.0, 101.0, 102.0],
            volumes=[1000, 2000, 3000],
        )
        assert "score" in result
        assert "volume_profile" in result
        assert result["score"]["n_samples"] == 3

    def test_with_bid_ask_oi(self):
        """Convenience function should work with all optional inputs."""
        result = assess_liquidity(
            prices=[100.0, 101.0, 102.0],
            volumes=[1000, 2000, 3000],
            bids=[99.5, 100.5, 101.5],
            asks=[100.5, 101.5, 102.5],
            open_interests=[500000, 510000, 520000],
        )
        assert "score" in result
        assert result["score"]["n_samples"] == 3


class TestSpreadMetrics:
    """Tests for the SpreadMetrics dataclass."""

    def test_to_dict(self):
        """to_dict should produce serializable output."""
        sm = SpreadMetrics(
            bid=99.5, ask=100.5, mid=100.0,
            absolute_spread=1.0, relative_spread=1.0,
            effective_spread=1.0, trade_price=100.0,
        )
        d = sm.to_dict()
        assert "bid" in d
        assert "ask" in d
        assert "relative_spread" in d


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
