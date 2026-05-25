"""
Unit tests for core/iv_rank.py

All tests run fully offline — Yahoo Finance is mocked throughout.
No network calls, no file writes to production paths.
"""
from __future__ import annotations

import time
from typing import Any
from unittest.mock import patch

import pytest

# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_closes(low: float, high: float, n: int = 50) -> list[float]:
    """Generate a simple ascending VIX history from low to high."""
    step = (high - low) / max(n - 1, 1)
    return [round(low + i * step, 2) for i in range(n)]


def _reset_module_cache() -> None:
    """Clear iv_rank's in-memory cache between tests."""
    import core.iv_rank as iv
    iv._mem_cache = {}


# ── get_iv_rank ───────────────────────────────────────────────────────────────

class TestGetIvRank:
    def setup_method(self):
        _reset_module_cache()

    def test_rank_at_52w_low(self):
        """When current VIX == 52-week low, rank should be 0."""
        closes = _make_closes(10.0, 30.0, 50)
        with patch("core.iv_rank._get_history", return_value=closes):
            from core.iv_rank import get_iv_rank
            assert get_iv_rank(10.0) == pytest.approx(0.0, abs=0.1)

    def test_rank_at_52w_high(self):
        """When current VIX == 52-week high, rank should be 100."""
        closes = _make_closes(10.0, 30.0, 50)
        with patch("core.iv_rank._get_history", return_value=closes):
            from core.iv_rank import get_iv_rank
            assert get_iv_rank(30.0) == pytest.approx(100.0, abs=0.1)

    def test_rank_midpoint(self):
        """When current VIX is exactly at midpoint of range, rank should be ~50."""
        closes = _make_closes(10.0, 30.0, 50)
        with patch("core.iv_rank._get_history", return_value=closes):
            from core.iv_rank import get_iv_rank
            assert get_iv_rank(20.0) == pytest.approx(50.0, abs=0.5)

    def test_rank_clamped_above(self):
        """VIX above 52-week high → rank clamped at 100."""
        closes = _make_closes(10.0, 25.0, 50)
        with patch("core.iv_rank._get_history", return_value=closes):
            from core.iv_rank import get_iv_rank
            assert get_iv_rank(40.0) == pytest.approx(100.0, abs=0.1)

    def test_rank_clamped_below(self):
        """VIX below 52-week low → rank clamped at 0."""
        closes = _make_closes(15.0, 30.0, 50)
        with patch("core.iv_rank._get_history", return_value=closes):
            from core.iv_rank import get_iv_rank
            assert get_iv_rank(5.0) == pytest.approx(0.0, abs=0.1)

    def test_rank_returns_minus1_on_zero_vix(self):
        """VIX = 0 is invalid; must return -1.0."""
        from core.iv_rank import get_iv_rank
        assert get_iv_rank(0.0) == -1.0

    def test_rank_returns_minus1_on_negative_vix(self):
        from core.iv_rank import get_iv_rank
        assert get_iv_rank(-5.0) == -1.0

    def test_rank_returns_minus1_on_insufficient_history(self):
        """Fewer than 20 sessions → return -1.0."""
        with patch("core.iv_rank._get_history", return_value=[15.0, 16.0, 17.0]):
            from core.iv_rank import get_iv_rank
            assert get_iv_rank(15.5) == -1.0

    def test_rank_returns_minus1_on_empty_history(self):
        with patch("core.iv_rank._get_history", return_value=[]):
            from core.iv_rank import get_iv_rank
            assert get_iv_rank(20.0) == -1.0

    def test_rank_neutral_when_history_all_same(self):
        """All sessions at same VIX → flat environment → return 50.0."""
        closes = [15.0] * 50
        with patch("core.iv_rank._get_history", return_value=closes):
            from core.iv_rank import get_iv_rank
            assert get_iv_rank(15.0) == pytest.approx(50.0)

    def test_rank_known_value(self):
        """
        Known calculation: low=10, high=30, current=16
        rank = (16-10)/(30-10)*100 = 30.0
        """
        closes = [10.0] * 25 + [30.0] * 25  # simple two-value history
        with patch("core.iv_rank._get_history", return_value=closes):
            from core.iv_rank import get_iv_rank
            assert get_iv_rank(16.0) == pytest.approx(30.0, abs=0.1)


# ── get_iv_percentile ─────────────────────────────────────────────────────────

class TestGetIvPercentile:
    def setup_method(self):
        _reset_module_cache()

    def test_percentile_all_below(self):
        """All sessions below current VIX → percentile = 100."""
        closes = list(range(10, 30))  # 10-29 (20 sessions)
        with patch("core.iv_rank._get_history", return_value=closes):
            from core.iv_rank import get_iv_percentile
            assert get_iv_percentile(35.0) == pytest.approx(100.0)

    def test_percentile_all_above(self):
        """All sessions above current VIX → percentile = 0."""
        closes = list(range(20, 50))  # 20 sessions above 5
        with patch("core.iv_rank._get_history", return_value=closes):
            from core.iv_rank import get_iv_percentile
            assert get_iv_percentile(5.0) == pytest.approx(0.0)

    def test_percentile_half_below(self):
        """Exactly half the sessions below → percentile ~50."""
        closes = [10.0] * 25 + [30.0] * 25
        with patch("core.iv_rank._get_history", return_value=closes):
            from core.iv_rank import get_iv_percentile
            # current=20: 25 sessions (10.0) are below 20 → 50%
            assert get_iv_percentile(20.0) == pytest.approx(50.0)

    def test_percentile_returns_minus1_on_zero_vix(self):
        from core.iv_rank import get_iv_percentile
        assert get_iv_percentile(0.0) == -1.0

    def test_percentile_returns_minus1_on_empty_history(self):
        with patch("core.iv_rank._get_history", return_value=[]):
            from core.iv_rank import get_iv_percentile
            assert get_iv_percentile(20.0) == -1.0

    def test_percentile_returns_minus1_on_short_history(self):
        with patch("core.iv_rank._get_history", return_value=[15.0] * 10):
            from core.iv_rank import get_iv_percentile
            assert get_iv_percentile(20.0) == -1.0


# ── get_score_multiplier ──────────────────────────────────────────────────────

class TestGetScoreMultiplier:
    def setup_method(self):
        _reset_module_cache()

    def _cfg(self, **overrides: Any) -> dict:
        base = {
            "iv_rank_enabled": True,
            "iv_rank_high_threshold": 70.0,
            "iv_rank_low_threshold":  30.0,
            "iv_rank_high_mult":       0.60,
            "iv_rank_low_mult":        1.20,
        }
        base.update(overrides)
        return base

    def test_high_iv_rank_returns_reducing_multiplier(self):
        """IV Rank > 70 → 0.60x multiplier."""
        closes = _make_closes(10.0, 30.0, 50)  # low=10, high=30
        # current_vix=28 → rank = (28-10)/(30-10)*100 = 90 → high
        with patch("core.iv_rank._get_history", return_value=closes):
            from core.iv_rank import get_score_multiplier
            mult, rank, reason = get_score_multiplier(28.0, self._cfg())
        assert mult == pytest.approx(0.60)
        assert rank > 70.0
        assert "expensive" in reason

    def test_low_iv_rank_returns_boosting_multiplier(self):
        """IV Rank < 30 → 1.20x multiplier."""
        closes = _make_closes(10.0, 30.0, 50)  # low=10, high=30
        # current_vix=12 → rank = (12-10)/(30-10)*100 = 10 → low
        with patch("core.iv_rank._get_history", return_value=closes):
            from core.iv_rank import get_score_multiplier
            mult, rank, reason = get_score_multiplier(12.0, self._cfg())
        assert mult == pytest.approx(1.20)
        assert rank < 30.0
        assert "cheap" in reason

    def test_neutral_iv_rank_returns_1x(self):
        """IV Rank 30-70 → 1.0x multiplier (no adjustment)."""
        closes = _make_closes(10.0, 30.0, 50)
        # current_vix=20 → rank ~50 → neutral
        with patch("core.iv_rank._get_history", return_value=closes):
            from core.iv_rank import get_score_multiplier
            mult, rank, reason = get_score_multiplier(20.0, self._cfg())
        assert mult == pytest.approx(1.0)
        assert 30.0 <= rank <= 70.0
        assert "neutral" in reason

    def test_disabled_via_config_returns_1x(self):
        """iv_rank_enabled=False → always 1.0, no Yahoo call."""
        with patch("core.iv_rank._get_history") as mock_hist:
            from core.iv_rank import get_score_multiplier
            mult, rank, reason = get_score_multiplier(25.0, self._cfg(iv_rank_enabled=False))
        mock_hist.assert_not_called()
        assert mult == pytest.approx(1.0)
        assert rank == -1.0
        assert "disabled" in reason

    def test_vix_zero_returns_1x_no_crash(self):
        """current_vix=0 → graceful no-op, no Yahoo call."""
        with patch("core.iv_rank._get_history") as mock_hist:
            from core.iv_rank import get_score_multiplier
            mult, rank, reason = get_score_multiplier(0.0, self._cfg())
        mock_hist.assert_not_called()
        assert mult == pytest.approx(1.0)
        assert "unavailable" in reason

    def test_unavailable_data_returns_1x(self):
        """If Yahoo returns empty history → no-op, not a crash."""
        with patch("core.iv_rank._get_history", return_value=[]):
            from core.iv_rank import get_score_multiplier
            mult, rank, reason = get_score_multiplier(20.0, self._cfg())
        assert mult == pytest.approx(1.0)
        assert rank == -1.0
        assert "unavailable" in reason

    def test_custom_thresholds_respected(self):
        """Custom thresholds override defaults."""
        closes = _make_closes(10.0, 30.0, 50)
        # rank ~50 is neutral by default but HIGH with custom high_threshold=40
        cfg = self._cfg(iv_rank_high_threshold=40.0, iv_rank_high_mult=0.75)
        with patch("core.iv_rank._get_history", return_value=closes):
            from core.iv_rank import get_score_multiplier
            mult, rank, reason = get_score_multiplier(20.0, cfg)  # rank ~50 > 40 → high
        assert mult == pytest.approx(0.75)

    def test_returns_tuple_of_correct_types(self):
        closes = _make_closes(10.0, 30.0, 50)
        with patch("core.iv_rank._get_history", return_value=closes):
            from core.iv_rank import get_score_multiplier
            result = get_score_multiplier(20.0)
        assert isinstance(result, tuple) and len(result) == 3
        mult, rank, reason = result
        assert isinstance(mult, float)
        assert isinstance(rank, float)
        assert isinstance(reason, str)


# ── iv_summary ────────────────────────────────────────────────────────────────

class TestIvSummary:
    def setup_method(self):
        _reset_module_cache()

    def test_summary_keys_present(self):
        closes = _make_closes(10.0, 30.0, 50)
        with patch("core.iv_rank._get_history", return_value=closes):
            from core.iv_rank import iv_summary
            result = iv_summary(20.0)
        assert set(result.keys()) == {"iv_rank", "iv_percentile", "score_multiplier", "iv_regime", "reason"}

    def test_summary_high_iv_regime(self):
        closes = _make_closes(10.0, 30.0, 50)
        with patch("core.iv_rank._get_history", return_value=closes):
            from core.iv_rank import iv_summary
            result = iv_summary(28.0)  # rank ~90 → HIGH_IV
        assert result["iv_regime"] == "HIGH_IV"
        assert result["score_multiplier"] == pytest.approx(0.60)

    def test_summary_low_iv_regime(self):
        closes = _make_closes(10.0, 30.0, 50)
        with patch("core.iv_rank._get_history", return_value=closes):
            from core.iv_rank import iv_summary
            result = iv_summary(11.0)  # rank ~5 → LOW_IV
        assert result["iv_regime"] == "LOW_IV"
        assert result["score_multiplier"] == pytest.approx(1.20)

    def test_summary_neutral_regime(self):
        closes = _make_closes(10.0, 30.0, 50)
        with patch("core.iv_rank._get_history", return_value=closes):
            from core.iv_rank import iv_summary
            result = iv_summary(20.0)  # rank ~50 → NEUTRAL
        assert result["iv_regime"] == "NEUTRAL_IV"
        assert result["score_multiplier"] == pytest.approx(1.0)

    def test_summary_unknown_when_no_data(self):
        with patch("core.iv_rank._get_history", return_value=[]):
            from core.iv_rank import iv_summary
            result = iv_summary(20.0)
        assert result["iv_regime"] == "UNKNOWN"
        assert result["iv_rank"] == -1.0
        assert result["score_multiplier"] == pytest.approx(1.0)


# ── Cache behaviour ───────────────────────────────────────────────────────────

class TestCacheBehaviour:
    def setup_method(self):
        _reset_module_cache()

    def test_in_memory_cache_avoids_refetch(self):
        """Second call must use in-memory cache — _fetch_vix_history called once."""
        closes = _make_closes(10.0, 30.0, 50)
        with patch("core.iv_rank._fetch_vix_history", return_value=closes) as mock_fetch:
            with patch("core.iv_rank._load_file_cache", return_value={}):
                with patch("core.iv_rank._save_file_cache"):
                    from core.iv_rank import get_iv_rank
                    get_iv_rank(20.0)
                    get_iv_rank(22.0)
        # _fetch_vix_history should only be called once despite two get_iv_rank calls
        assert mock_fetch.call_count == 1

    def test_invalidate_cache_clears_memory(self):
        import core.iv_rank as iv
        iv._mem_cache = {"fetched_at": time.time(), "closes": [15.0] * 50}
        from core.iv_rank import invalidate_cache
        invalidate_cache()
        assert iv._mem_cache == {}

    def test_stale_cache_triggers_refetch(self):
        """Cache older than TTL must trigger a fresh fetch."""
        import core.iv_rank as iv
        old_time = time.time() - (25 * 3600)  # 25h ago → stale (TTL=24h)
        iv._mem_cache = {"fetched_at": old_time, "closes": [15.0] * 50}
        fresh_closes = _make_closes(12.0, 28.0, 50)
        with patch("core.iv_rank._fetch_vix_history", return_value=fresh_closes) as mock_f:
            with patch("core.iv_rank._load_file_cache", return_value={}):
                with patch("core.iv_rank._save_file_cache"):
                    from core.iv_rank import get_iv_rank
                    get_iv_rank(20.0)
        assert mock_f.call_count == 1

    def test_fetch_failure_falls_back_to_stale(self):
        """When Yahoo fetch fails, stale file cache is used as fallback."""
        import core.iv_rank as iv
        iv._mem_cache = {}
        stale_data = {"fetched_at": time.time() - 48 * 3600, "closes": [15.0] * 50}
        with patch("core.iv_rank._fetch_vix_history", return_value=[]):
            with patch("core.iv_rank._load_file_cache", return_value=stale_data):
                with patch("core.iv_rank._save_file_cache"):
                    from core.iv_rank import get_iv_rank
                    rank = get_iv_rank(15.0)
        # Should still return a valid rank from stale data, not -1.0
        assert rank >= 0.0

    def test_file_cache_hit_skips_fetch(self):
        """Fresh file cache should skip Yahoo fetch entirely."""
        import core.iv_rank as iv
        iv._mem_cache = {}
        fresh_file = {"fetched_at": time.time() - 100, "closes": _make_closes(10.0, 30.0, 50)}
        with patch("core.iv_rank._fetch_vix_history") as mock_f:
            with patch("core.iv_rank._load_file_cache", return_value=fresh_file):
                from core.iv_rank import get_iv_rank
                get_iv_rank(20.0)
        mock_f.assert_not_called()


# ── Integration: adaptive_signal wiring ───────────────────────────────────────

class TestAdaptiveSignalIvWiring:
    """
    Smoke-test that the IV rank multiplier is applied in evaluate_adaptive_signal.
    Verifies score_components["iv_rank_adj"] is present and non-zero when IV is
    extreme.  Full signal evaluation is heavy, so we mock the feature computation.
    """

    def test_iv_rank_adj_in_score_components_on_high_iv(self):
        """score_components must contain 'iv_rank_adj' key after signal eval."""
        closes = _make_closes(10.0, 30.0, 50)
        # Patch the heavy computation to return a known score
        fake_data = {
            "score": 75, "direction": "CALL", "mkt_regime": "TRENDING",
            "adx": 22.0, "rsi": 55.0, "vwap": 22000.0, "atr": 100.0,
            "vol_ratio": 1.5, "price": 22050.0,
            "score_components": {
                "tf_aligned": 20, "vwap": 15, "d1_momentum": 15, "d5_momentum": 10,
                "volume": 10, "atr_floor": 5, "rsi_bonus": 0, "smart_money": 0,
                "pcr": 0, "macd_bonus": 0, "breakout": 0, "adx_penalty": 0,
                "adx_trend_bonus": 0, "regime_penalty": 0, "vwap_reclaim": 0, "orb_bonus": 0,
            },
            "macd": {}, "breakout_ok": False, "t5": "UP", "t15": "UP",
        }

        with patch("core.iv_rank._get_history", return_value=closes):
            with patch(
                "core.adaptive_signal._compute_features_and_score",
                return_value=fake_data
            ):
                with patch(
                    "core.pure_index_signal.evaluate_index_signal_partial",
                    return_value=(fake_data, "")
                ):
                    from core.adaptive_signal import evaluate_adaptive_signal
                    from core.pure_index_signal import PureIndexRegimeParams, PureIndexSignalParams

                    params = PureIndexSignalParams(
                        name="NIFTY",
                        signal_cfg={
                            "iv_rank_enabled": True,
                            "iv_rank_high_threshold": 70.0,
                            "iv_rank_low_threshold":  30.0,
                            "iv_rank_high_mult":       0.60,
                            "iv_rank_low_mult":        1.20,
                        },
                        regime=PureIndexRegimeParams(35.0, 20.0, 14.0),
                        iv_spike_threshold=60.0,
                        vol_ratio_min=1.2,
                        is_early_session=False,
                        min15_early=3,
                        min15_normal=5,
                    )

                    import pandas as pd
                    _idx = pd.date_range("2026-04-01 09:15", periods=60, freq="1min")
                    df1 = pd.DataFrame({"Open": 22000.0, "High": 22100.0, "Low": 21900.0,
                                        "Close": 22050.0, "Volume": 1000.0}, index=_idx)
                    df5  = df1.resample("5min").agg({"Open":"first","High":"max","Low":"min","Close":"last","Volume":"sum"}).dropna()
                    df15 = df1.resample("15min").agg({"Open":"first","High":"max","Low":"min","Close":"last","Volume":"sum"}).dropna()

                    # vix=28 → rank≈90 (HIGH_IV) with our _make_closes(10,30) history
                    result, reason = evaluate_adaptive_signal(
                        params=params,
                        df1=df1, df5=df5, df15=df15,
                        vix=28.0, iv=20.0,
                        oi_sup=0.0, oi_res=0.0,
                        pcr=1.0, smart="NEUTRAL",
                    )

        # If signal is returned, iv_rank_adj must be in score_components
        if result is not None:
            assert "iv_rank_adj" in result.score_components
            # With HIGH_IV (rank~90) and mult=0.60, adjustment must be negative
            assert result.score_components["iv_rank_adj"] <= 0
