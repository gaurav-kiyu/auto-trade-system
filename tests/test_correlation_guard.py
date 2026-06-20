"""Tests for core/correlation_guard.py - Multi-Instrument Correlation Guard.

Covers:
- update_closes / get_closes (rolling cache)
- are_correlated_pair (known index pairs)
- pearson_r (correlation calculation)
- check_portfolio_correlation (allowed, blocked, warn, disabled)
- correlation_summary (cached correlations snapshot)
"""
from __future__ import annotations

from typing import Any

import pytest

from core.correlation_guard import (
    _closes_cache,
    are_correlated_pair,
    check_portfolio_correlation,
    correlation_summary,
    get_closes,
    pearson_r,
    update_closes,
)


@pytest.fixture(autouse=True)
def clear_cache():
    """Clear the module-level closes cache before each test."""
    _closes_cache.clear()
    yield
    _closes_cache.clear()


# =============================================================================
# update_closes / get_closes Tests
# =============================================================================

class TestClosesCache:
    def test_updates_closes(self):
        update_closes("NIFTY", [100.0, 101.0, 102.0])
        closes = get_closes("NIFTY", 3)
        assert closes == [100.0, 101.0, 102.0]

    def test_get_closes_returns_empty_for_unknown(self):
        assert get_closes("UNKNOWN", 10) == []

    def test_get_closes_limited_to_n(self):
        update_closes("NIFTY", [100.0, 101.0, 102.0, 103.0, 104.0])
        closes = get_closes("NIFTY", 3)
        assert closes == [102.0, 103.0, 104.0]

    def test_filter_invalid_prices(self):
        update_closes("NIFTY", [100.0, 0.0, -5.0, 102.0])
        closes = get_closes("NIFTY", 10)
        assert 0.0 not in closes
        assert -5.0 not in closes

    def test_cache_max_size_60(self):
        update_closes("NIFTY", list(range(100)))
        closes = get_closes("NIFTY", 100)
        assert len(closes) <= 60

    def test_multiple_symbols_independent(self):
        update_closes("NIFTY", [100.0, 101.0])
        update_closes("BANKNIFTY", [200.0, 201.0])
        assert get_closes("NIFTY", 2) == [100.0, 101.0]
        assert get_closes("BANKNIFTY", 2) == [200.0, 201.0]

    def test_empty_closes_list(self):
        update_closes("NIFTY", [])
        assert get_closes("NIFTY", 5) == []


# =============================================================================
# are_correlated_pair Tests
# =============================================================================

class TestAreCorrelatedPair:
    def test_nifty_banknifty(self):
        assert are_correlated_pair("NIFTY", "BANKNIFTY") is True
        assert are_correlated_pair("BANKNIFTY", "NIFTY") is True

    def test_nifty_finnifty(self):
        assert are_correlated_pair("NIFTY", "FINNIFTY") is True

    def test_banknifty_finnifty(self):
        assert are_correlated_pair("BANKNIFTY", "FINNIFTY") is True

    def test_uncorrelated_pair(self):
        assert are_correlated_pair("NIFTY", "SENSEX") is False

    def test_unknown_symbols(self):
        assert are_correlated_pair("UNKNOWN1", "UNKNOWN2") is False

    def test_same_symbol(self):
        """Same symbol should not be in the correlated pairs set (only cross pairs)."""
        assert are_correlated_pair("NIFTY", "NIFTY") is False


# =============================================================================
# pearson_r Tests
# =============================================================================

class TestPearsonR:
    def test_perfect_positive_correlation(self):
        x = [1.0, 2.0, 3.0, 4.0, 5.0]
        y = [2.0, 4.0, 6.0, 8.0, 10.0]
        r = pearson_r(x, y)
        assert r == pytest.approx(1.0, abs=0.001)

    def test_perfect_negative_correlation(self):
        x = [1.0, 2.0, 3.0, 4.0, 5.0]
        y = [10.0, 8.0, 6.0, 4.0, 2.0]
        r = pearson_r(x, y)
        assert r == pytest.approx(-1.0, abs=0.001)

    def test_no_correlation(self):
        x = [1.0, 2.0, 3.0, 4.0, 5.0]
        y = [5.0, 5.0, 5.0, 5.0, 5.0]
        r = pearson_r(x, y)
        # No variance in y -> denom = 0 -> returns 0.0
        assert r == 0.0

    def test_fewer_than_5_points(self):
        r = pearson_r([1.0, 2.0, 3.0], [4.0, 5.0, 6.0])
        assert r == 0.0

    def test_truncates_to_shortest_length(self):
        x = [1.0, 2.0, 3.0, 4.0, 5.0]
        y = [10.0, 20.0, 30.0]
        r = pearson_r(x, y)
        assert r == 0.0  # Only 3 points after min

    def test_zero_variance_x(self):
        x = [5.0, 5.0, 5.0, 5.0, 5.0]
        y = [1.0, 2.0, 3.0, 4.0, 5.0]
        r = pearson_r(x, y)
        assert r == 0.0

    def test_high_correlation(self):
        x = [100.0, 101.0, 102.0, 103.0, 104.0]
        y = [200.0, 202.0, 204.0, 206.0, 208.0]
        r = pearson_r(x, y)
        assert r > 0.95

    def test_returns_rounded_to_4_decimal(self):
        x = [1.0, 2.0, 3.0, 4.0, 5.0]
        y = [2.0, 4.0, 6.0, 8.0, 10.0]
        r = pearson_r(x, y)
        assert r == 1.0  # Rounded to 4 decimal places


# =============================================================================
# check_portfolio_correlation Tests
# =============================================================================

class TestCheckPortfolioCorrelation:
    def test_disabled_guard_always_allows(self):
        cfg = {"correlation_guard_enabled": False}
        allowed, _ = check_portfolio_correlation(
            "BANKNIFTY", "CALL", {"NIFTY": {"signal": "CALL"}}, cfg,
        )
        assert allowed is True

    def test_no_open_positions_allows(self):
        allowed, _ = check_portfolio_correlation(
            "BANKNIFTY", "CALL", {}, None,
        )
        assert allowed is True

    def test_no_config_uses_defaults(self):
        """When cfg is None, defaults are used (guard enabled, threshold=0.85)."""
        allowed, _ = check_portfolio_correlation(
            "BANKNIFTY", "CALL", {"UNKNOWN": {"signal": "CALL"}}, None,
        )
        assert allowed is True  # Uncoupled pair

    def test_different_directions_allows(self):
        """CALL vs PUT should not be blocked (they hedge)."""
        update_closes("NIFTY", [100.0, 101.0, 102.0, 103.0, 104.0, 105.0])
        update_closes("BANKNIFTY", [200.0, 202.0, 204.0, 206.0, 208.0, 210.0])
        allowed, _ = check_portfolio_correlation(
            "BANKNIFTY", "PUT", {"NIFTY": {"signal": "CALL"}},
            {"correlation_threshold": 0.85, "correlation_lookback_bars": 5},
        )
        assert allowed is True

    def test_blocks_correlated_same_direction(self):
        """Same direction on correlated pair with high r should block."""
        update_closes("NIFTY", [100.0, 101.0, 102.0, 103.0, 104.0, 105.0])
        update_closes("BANKNIFTY", [200.0, 202.0, 204.0, 206.0, 208.0, 210.0])
        allowed, reason = check_portfolio_correlation(
            "BANKNIFTY", "CALL", {"NIFTY": {"signal": "CALL"}},
            {"correlation_threshold": 0.85, "correlation_lookback_bars": 5},
        )
        assert allowed is False
        assert "correlation guard" in reason.lower()

    def test_low_correlation_allows(self):
        """Low r should allow through."""
        update_closes("NIFTY", [100.0, 101.0, 100.0, 101.0, 100.0, 101.0])
        update_closes("BANKNIFTY", [200.0, 205.0, 210.0, 215.0, 220.0, 225.0])
        allowed, _ = check_portfolio_correlation(
            "BANKNIFTY", "CALL", {"NIFTY": {"signal": "CALL"}},
            {"correlation_threshold": 0.95, "correlation_lookback_bars": 5},
        )
        assert allowed is True

    def test_insufficient_history_allows(self):
        """Fewer than 5 data points should skip check."""
        update_closes("NIFTY", [100.0])
        update_closes("BANKNIFTY", [200.0])
        allowed, _ = check_portfolio_correlation(
            "BANKNIFTY", "CALL", {"NIFTY": {"signal": "CALL"}},
            {"correlation_lookback_bars": 20},
        )
        assert allowed is True

    def test_same_symbol_not_checked(self):
        """Same symbol should be skipped (no self-correlation check)."""
        allowed, _ = check_portfolio_correlation(
            "NIFTY", "CALL", {"NIFTY": {"signal": "CALL"}}, None,
        )
        assert allowed is True


# =============================================================================
# correlation_summary Tests
# =============================================================================

class TestCorrelationSummary:
    def test_empty_cache(self):
        result = correlation_summary()
        assert result["enabled"] is True
        assert result["pairs"] == {}

    def test_with_cached_data(self):
        update_closes("NIFTY", [100.0, 101.0, 102.0, 103.0, 104.0, 105.0])
        update_closes("BANKNIFTY", [200.0, 202.0, 204.0, 206.0, 208.0, 210.0])
        result = correlation_summary({"correlation_lookback_bars": 5})
        assert result["enabled"] is True
        assert "NIFTY/BANKNIFTY" in result["pairs"]

    def test_disabled_in_summary(self):
        result = correlation_summary({"correlation_guard_enabled": False})
        assert result["enabled"] is False
