"""
Tests for Phase 8 — Multi-Instrument Correlation Guard (core/correlation_guard.py).

Covers:
  - pearson_r: correct values, edge cases (< 5 pts, zero variance)
  - are_correlated_pair: known pairs and unknown pairs
  - update_closes / get_closes: rolling cache behaviour
  - check_portfolio_correlation:
      - disabled guard → always allowed
      - non-correlated pair → allowed
      - correlated pair opposite directions → allowed
      - correlated pair same direction, r < warn_thresh → allowed
      - correlated pair same direction, r >= warn_thresh → allowed (but logged)
      - correlated pair same direction, r >= threshold → blocked
      - insufficient price history → allowed (skip check)
  - correlation_summary: correct keys
"""
from __future__ import annotations

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

# ── Helpers ────────────────────────────────────────────────────────────────────

def _inject_closes(name: str, values: list[float]) -> None:
    """Directly inject closes into the module-level cache for testing."""
    _closes_cache.clear()
    update_closes(name, values)


def _inject_two(n1: str, v1: list[float], n2: str, v2: list[float]) -> None:
    _closes_cache.clear()
    update_closes(n1, v1)
    update_closes(n2, v2)


def _perfect_corr(n: int = 25) -> tuple[list[float], list[float]]:
    """Two perfectly correlated series."""
    x = [100.0 + i for i in range(n)]
    y = [200.0 + 2 * i for i in range(n)]
    return x, y


def _zero_corr(n: int = 25) -> tuple[list[float], list[float]]:
    """Uncorrelated series: x rises linearly, y is constant (zero variance → r=0)."""
    x = [100.0 + i for i in range(n)]
    y = [200.0] * n
    return x, y


# ── pearson_r ──────────────────────────────────────────────────────────────────

class TestPearsonR:
    def test_perfect_positive_correlation(self):
        x, y = _perfect_corr(20)
        r = pearson_r(x, y)
        assert abs(r - 1.0) < 1e-4

    def test_perfect_negative_correlation(self):
        x = [float(i) for i in range(20)]
        y = [float(20 - i) for i in range(20)]
        r = pearson_r(x, y)
        assert abs(r + 1.0) < 1e-4

    def test_zero_correlation(self):
        x, y = _zero_corr(26)
        r = pearson_r(x, y)
        assert r == 0.0  # y is constant → zero variance → pearson_r returns 0.0

    def test_returns_zero_with_fewer_than_5_points(self):
        assert pearson_r([1, 2, 3, 4], [1, 2, 3, 4]) == 0.0

    def test_returns_zero_with_zero_variance(self):
        x = [100.0] * 10
        y = [200.0 + i for i in range(10)]
        assert pearson_r(x, y) == 0.0

    def test_result_in_bounds(self):
        import random
        random.seed(42)
        x = [random.random() for _ in range(30)]
        y = [random.random() for _ in range(30)]
        r = pearson_r(x, y)
        assert -1.0 <= r <= 1.0

    def test_uses_shorter_series(self):
        x = [float(i) for i in range(30)]
        y = [float(i) for i in range(20)]  # shorter
        r = pearson_r(x, y)
        assert r == pytest.approx(1.0, abs=1e-4)


# ── are_correlated_pair ────────────────────────────────────────────────────────

class TestAreCorrelatedPair:
    def test_nifty_banknifty(self):
        assert are_correlated_pair("NIFTY", "BANKNIFTY") is True

    def test_banknifty_nifty_reversed(self):
        assert are_correlated_pair("BANKNIFTY", "NIFTY") is True

    def test_nifty_finnifty(self):
        assert are_correlated_pair("NIFTY", "FINNIFTY") is True

    def test_banknifty_finnifty(self):
        assert are_correlated_pair("BANKNIFTY", "FINNIFTY") is True

    def test_unknown_pair_false(self):
        assert are_correlated_pair("NIFTY", "SENSEX") is False

    def test_same_name_false(self):
        assert are_correlated_pair("NIFTY", "NIFTY") is False


# ── update_closes / get_closes ─────────────────────────────────────────────────

class TestClosesCache:
    def setup_method(self):
        _closes_cache.clear()

    def test_get_closes_empty_returns_empty(self):
        assert get_closes("NIFTY", 10) == []

    def test_update_and_get(self):
        update_closes("NIFTY", [100.0, 101.0, 102.0])
        assert get_closes("NIFTY", 3) == [100.0, 101.0, 102.0]

    def test_get_clips_to_n(self):
        update_closes("NIFTY", [float(i) for i in range(30)])
        result = get_closes("NIFTY", 5)
        assert len(result) == 5
        assert result == [25.0, 26.0, 27.0, 28.0, 29.0]

    def test_filters_zero_and_negative(self):
        update_closes("NIFTY", [0.0, -1.0, 100.0, 101.0])
        result = get_closes("NIFTY", 10)
        assert 0.0 not in result
        assert all(v > 0 for v in result)

    def test_rolling_max_length(self):
        from core.correlation_guard import _CACHE_MAX
        update_closes("NIFTY", [float(i) for i in range(_CACHE_MAX + 20)])
        result = get_closes("NIFTY", _CACHE_MAX + 20)
        assert len(result) <= _CACHE_MAX

    def test_incremental_updates_append(self):
        update_closes("NIFTY", [1.0, 2.0, 3.0])
        update_closes("NIFTY", [4.0, 5.0])
        result = get_closes("NIFTY", 10)
        assert result[-2:] == [4.0, 5.0]


# ── check_portfolio_correlation ────────────────────────────────────────────────

class TestCheckPortfolioCorrelation:
    def setup_method(self):
        _closes_cache.clear()

    def _cfg(self, **kwargs):
        base = {
            "correlation_guard_enabled": True,
            "correlation_threshold": 0.85,
            "correlation_warn_threshold": 0.70,
            "correlation_lookback_bars": 20,
        }
        base.update(kwargs)
        return base

    def test_disabled_guard_always_allowed(self):
        cfg = self._cfg(correlation_guard_enabled=False)
        ok, reason = check_portfolio_correlation(
            "BANKNIFTY", "CALL", {"NIFTY": {"signal": "CALL"}}, cfg
        )
        assert ok is True
        assert reason == ""

    def test_no_open_positions_allowed(self):
        ok, _ = check_portfolio_correlation("NIFTY", "CALL", {}, self._cfg())
        assert ok is True

    def test_same_name_in_positions_skipped(self):
        ok, _ = check_portfolio_correlation(
            "NIFTY", "CALL", {"NIFTY": {"signal": "CALL"}}, self._cfg()
        )
        assert ok is True

    def test_non_correlated_pair_allowed(self):
        ok, _ = check_portfolio_correlation(
            "NIFTY", "CALL", {"SENSEX": {"signal": "CALL"}}, self._cfg()
        )
        assert ok is True

    def test_opposite_directions_allowed(self):
        x, y = _perfect_corr(25)
        _inject_two("NIFTY", x, "BANKNIFTY", y)
        ok, _ = check_portfolio_correlation(
            "BANKNIFTY", "PUT",
            {"NIFTY": {"signal": "CALL"}},
            self._cfg(),
        )
        assert ok is True

    def test_high_correlation_same_direction_blocked(self):
        x, y = _perfect_corr(25)
        _inject_two("BANKNIFTY", x, "NIFTY", y)
        ok, reason = check_portfolio_correlation(
            "BANKNIFTY", "CALL",
            {"NIFTY": {"signal": "CALL"}},
            self._cfg(correlation_threshold=0.85),
        )
        assert ok is False
        assert "BANKNIFTY" in reason or "NIFTY" in reason
        assert "blocked" in reason.lower()

    def test_low_correlation_same_direction_allowed(self):
        x, y = _zero_corr(26)
        _inject_two("BANKNIFTY", x, "NIFTY", y)
        ok, _ = check_portfolio_correlation(
            "BANKNIFTY", "CALL",
            {"NIFTY": {"signal": "CALL"}},
            self._cfg(),
        )
        assert ok is True

    def test_insufficient_history_skips_check(self):
        # Only 3 bars — < 5 required → skip check, allow
        _closes_cache.clear()
        update_closes("BANKNIFTY", [100.0, 101.0, 102.0])
        update_closes("NIFTY", [200.0, 201.0, 202.0])
        ok, _ = check_portfolio_correlation(
            "BANKNIFTY", "CALL",
            {"NIFTY": {"signal": "CALL"}},
            self._cfg(),
        )
        assert ok is True

    def test_no_closes_in_cache_skips_check(self):
        _closes_cache.clear()
        ok, _ = check_portfolio_correlation(
            "BANKNIFTY", "CALL",
            {"NIFTY": {"signal": "CALL"}},
            self._cfg(),
        )
        assert ok is True

    def test_threshold_at_boundary(self):
        # r≈1.0 with threshold=0.99 → blocked; with threshold=1.01 → allowed
        x, y = _perfect_corr(25)
        _inject_two("BANKNIFTY", x, "NIFTY", y)
        ok_blocked, _ = check_portfolio_correlation(
            "BANKNIFTY", "CALL",
            {"NIFTY": {"signal": "CALL"}},
            self._cfg(correlation_threshold=0.99),
        )
        assert ok_blocked is False  # r≈1.0 >= 0.99 → blocked
        ok_allowed, _ = check_portfolio_correlation(
            "BANKNIFTY", "CALL",
            {"NIFTY": {"signal": "CALL"}},
            self._cfg(correlation_threshold=1.01),
        )
        assert ok_allowed is True  # r≈1.0 < 1.01 → allowed

    def test_finnifty_banknifty_pair_checked(self):
        x, y = _perfect_corr(25)
        _inject_two("FINNIFTY", x, "BANKNIFTY", y)
        ok, reason = check_portfolio_correlation(
            "FINNIFTY", "PUT",
            {"BANKNIFTY": {"signal": "PUT"}},
            self._cfg(correlation_threshold=0.85),
        )
        assert ok is False

    def test_signal_field_case_insensitive(self):
        x, y = _perfect_corr(25)
        _inject_two("BANKNIFTY", x, "NIFTY", y)
        ok, _ = check_portfolio_correlation(
            "BANKNIFTY", "call",
            {"NIFTY": {"signal": "Call"}},
            self._cfg(),
        )
        assert ok is False  # both normalise to CALL → blocked


# ── correlation_summary ────────────────────────────────────────────────────────

class TestCorrelationSummary:
    def setup_method(self):
        _closes_cache.clear()

    def test_summary_has_required_keys(self):
        s = correlation_summary()
        assert "enabled" in s
        assert "threshold" in s
        assert "pairs" in s

    def test_summary_empty_when_no_cache(self):
        s = correlation_summary()
        assert s["pairs"] == {}

    def test_summary_contains_pair_when_two_symbols_cached(self):
        x, y = _perfect_corr(25)
        update_closes("NIFTY", x)
        update_closes("BANKNIFTY", y)
        s = correlation_summary()
        pair_keys = list(s["pairs"].keys())
        assert len(pair_keys) == 1
        assert "NIFTY" in pair_keys[0] or "BANKNIFTY" in pair_keys[0]

    def test_summary_respects_enabled_flag(self):
        s = correlation_summary({"correlation_guard_enabled": False})
        assert s["enabled"] is False

    def test_summary_r_value_near_1_for_perfect_corr(self):
        x, y = _perfect_corr(25)
        update_closes("NIFTY", x)
        update_closes("BANKNIFTY", y)
        s = correlation_summary({"correlation_lookback_bars": 20})
        r_vals = list(s["pairs"].values())
        assert len(r_vals) == 1
        assert abs(r_vals[0] - 1.0) < 1e-3
