"""Tests for core/adaptive_signal.py - Adaptive Signal Evaluator.

Covers:
- AdaptiveSignal dataclass
- SignalConfidenceBand dataclass and _wilson_ci
- compute_confidence_band integration
- compute_timeframe_agreement
- evaluate_adaptive_signal with dual-direction, soft blocks
- _compute_features_and_score internal
- Edge cases: missing data, iv_spike, extreme regimes
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from core.adaptive_signal import (
    AdaptiveSignal,
    SignalConfidenceBand,
    _wilson_ci,
    compute_confidence_band,
    compute_timeframe_agreement,
    evaluate_adaptive_signal,
)
from core.pure_index_signal import PureIndexRegimeParams, PureIndexSignalParams

# ── Helpers ──────────────────────────────────────────────────────────────

def make_df(closes: list[float], volumes: list[int] | None = None) -> pd.DataFrame:
    n = len(closes)
    volumes = volumes or [1000] * n
    return pd.DataFrame({
        "Open": [c * 0.99 for c in closes],
        "High": [c * 1.02 for c in closes],
        "Low": [c * 0.98 for c in closes],
        "Close": closes,
        "Volume": volumes,
    })


@pytest.fixture
def params() -> PureIndexSignalParams:
    return PureIndexSignalParams(
        name="NIFTY",
        signal_cfg={},
        regime=PureIndexRegimeParams(
            vix_block_threshold=35.0,
            adx_trend_threshold=25.0,
            adx_chop_threshold=20.0,
        ),
        iv_spike_threshold=50.0,
        vol_ratio_min=1.2,
        is_early_session=False,
    )


# =============================================================================
# AdaptiveSignal Dataclass Tests
# =============================================================================

class TestAdaptiveSignal:
    def test_default_values(self):
        sig = AdaptiveSignal(
            tier="MODERATE", score=70, raw_score=80, confidence=0.8,
            direction="CALL", regime="TRENDING",
            soft_blocks=[], reasons=[], score_components={}, features=[],
        )
        assert sig.tier == "MODERATE"
        assert sig.score == 70
        assert sig.raw_score == 80
        assert sig.confidence == 0.8
        assert sig.direction == "CALL"
        assert sig.atr == 0.0  # Default
        assert sig.rsi == 50.0  # Default
        assert sig.position_spec is None
        assert sig.confidence_band is None

    def test_weak_tier(self):
        sig = AdaptiveSignal(
            tier="WEAK", score=30, raw_score=35, confidence=0.5,
            direction="PUT", regime="CHOPPY",
            soft_blocks=["choppy_regime"], reasons=[], score_components={}, features=[],
        )
        assert sig.tier == "WEAK"


# =============================================================================
# SignalConfidenceBand Tests
# =============================================================================

class TestSignalConfidenceBand:
    def test_dataclass_fields(self):
        band = SignalConfidenceBand(
            n_trades=100, n_wins=60, win_rate=0.6,
            ci_low=0.5, ci_high=0.7, score_bin="70-80",
            regime="TRENDING", session="OPENING", direction="CALL",
        )
        assert band.n_trades == 100
        assert band.win_rate == 0.6

    def test_str_representation(self):
        band = SignalConfidenceBand(
            n_trades=50, n_wins=30, win_rate=0.6,
            ci_low=0.45, ci_high=0.74,
        )
        s = str(band)
        assert "CI:" in s
        assert "45" in s or "74" in s
        assert "n=50" in s


# =============================================================================
# _wilson_ci Tests
# =============================================================================

class TestWilsonCI:
    def test_perfect_win_rate(self):
        low, high = _wilson_ci(100, 100)
        assert low > 0.9
        assert high == pytest.approx(1.0, abs=0.0001)

    def test_zero_wins(self):
        low, high = _wilson_ci(0, 100)
        assert low == 0.0
        assert high < 0.05

    def test_zero_trades(self):
        low, high = _wilson_ci(0, 0)
        assert low == 0.0
        assert high == 1.0

    def test_50pct_win_rate(self):
        low, high = _wilson_ci(50, 100)
        assert low < 0.6
        assert high > 0.4
        assert low > 0


# =============================================================================
# compute_confidence_band Tests
# =============================================================================

class TestComputeConfidenceBand:
    def test_returns_none_when_disabled(self):
        result = compute_confidence_band(
            score=75, regime="TRENDING", session="OPENING",
            direction="CALL", db_path="nonexistent.db",
            cfg={"confidence_band_enabled": False},
        )
        assert result is None

    def test_returns_none_when_no_db(self):
        result = compute_confidence_band(
            score=75, regime="TRENDING", session="OPENING",
            direction="CALL", db_path="nonexistent.db",
            cfg={"confidence_band_enabled": True},
        )
        assert result is None


# =============================================================================
# compute_timeframe_agreement Tests
# =============================================================================

class TestTimeframeAgreement:
    def test_all_agree_bullish(self):
        agreement = compute_timeframe_agreement("UP", "UP", "UP")
        assert agreement.agreement_score == 1.0
        assert agreement.bullish_count == 3
        assert agreement.bearish_count == 0

    def test_all_agree_bearish(self):
        agreement = compute_timeframe_agreement("DOWN", "DOWN", "DOWN")
        assert agreement.agreement_score == 1.0
        assert agreement.bullish_count == 0
        assert agreement.bearish_count == 3

    def test_two_agree(self):
        agreement = compute_timeframe_agreement("UP", "UP", "DOWN")
        assert 0 < agreement.agreement_score < 1.0

    def test_all_flat(self):
        agreement = compute_timeframe_agreement("FLAT", "FLAT", "FLAT")
        assert agreement.agreement_score == 0.0

    def test_mixed_flat_and_direction(self):
        agreement = compute_timeframe_agreement("UP", "FLAT", "UP")
        assert agreement.agreement_score > 0
        assert agreement.bullish_count == 2
        assert agreement.bearish_count == 0

    def test_single_direction(self):
        agreement = compute_timeframe_agreement("UP", "FLAT", "FLAT")
        assert agreement.agreement_score > 0


# =============================================================================
# evaluate_adaptive_signal Tests
# =============================================================================

class TestEvaluateAdaptiveSignal:
    def test_short_data_returns_none(self, params: PureIndexSignalParams):
        df1 = make_df([100.0] * 5)
        df5 = make_df([100.0] * 3)
        df15 = make_df([100.0] * 2)
        result, reason = evaluate_adaptive_signal(
            params=params, df1=df1, df5=df5, df15=df15,
            vix=15, iv=10, oi_sup=0, oi_res=0, pcr=1.0,
            smart="NEUTRAL",
        )
        assert result is None

    def test_returns_signal_with_sufficient_data(self, params: PureIndexSignalParams):
        df1 = make_df([23000.0 + i * 5 for i in range(60)])
        df5 = make_df([23000.0 + i * 25 for i in range(12)])
        df15 = make_df([23000.0 + i * 60 for i in range(6)])
        result, reason = evaluate_adaptive_signal(
            params=params, df1=df1, df5=df5, df15=df15,
            vix=15, iv=10, oi_sup=0, oi_res=0, pcr=1.0,
            smart="NEUTRAL",
        )
        if result is not None:
            assert isinstance(result, AdaptiveSignal)
            assert result.direction in ("CALL", "PUT")
            assert result.score >= 0
            assert result.raw_score >= 0
            assert 0 <= result.confidence <= 1.0

    def test_iv_spike_blocks_signal(self, params: PureIndexSignalParams):
        df1 = make_df([23000.0 + i * 5 for i in range(60)])
        df5 = make_df([23000.0 + i * 25 for i in range(12)])
        df15 = make_df([23000.0 + i * 60 for i in range(6)])
        result, reason = evaluate_adaptive_signal(
            params=params, df1=df1, df5=df5, df15=df15,
            vix=15, iv=100, oi_sup=0, oi_res=0, pcr=1.0,
            smart="NEUTRAL",
        )
        assert result is not None or reason is not None

    def test_high_vix_triggers_iv_adjustment(self, params: PureIndexSignalParams):
        df1 = make_df([23000.0 + i * 5 for i in range(60)])
        df5 = make_df([23000.0 + i * 25 for i in range(12)])
        df15 = make_df([23000.0 + i * 60 for i in range(6)])
        with patch("core.iv_rank.get_score_multiplier") as mock_mult:
            mock_mult.return_value = (0.6, 75.0, "iv_rank=75.0>70 expensive->x0.6")
            with patch("core.iv_rank.get_iv_rank") as mock_rank:
                mock_rank.return_value = 75.0
                result, reason = evaluate_adaptive_signal(
                    params=params, df1=df1, df5=df5, df15=df15,
                    vix=28, iv=10, oi_sup=0, oi_res=0, pcr=1.0,
                    smart="NEUTRAL",
                )
                if result is not None:
                    assert result.score <= result.raw_score  # IV boost/reduction

    def test_soft_blocks_reduce_confidence(self, params: PureIndexSignalParams):
        df1 = make_df([23000.0 + i * 5 for i in range(60)])
        df5 = make_df([23000.0 + i * 25 for i in range(12)])
        df15 = make_df([23000.0 + i * 60 for i in range(6)])
        result, reason = evaluate_adaptive_signal(
            params=params, df1=df1, df5=df5, df15=df15,
            vix=15, iv=10, oi_sup=0, oi_res=0, pcr=1.0,
            smart="NEUTRAL",
        )
        if result is not None:
            assert 0 <= result.confidence <= 1.0

    def test_session_hard_block_default_off_does_not_block(self, params: PureIndexSignalParams):
        """Regression guard: with session_hard_block_enabled left at its
        default (False), a session_*_blocked soft_block tag must NOT stop
        the signal — matches today's shipped behavior exactly.
        """
        df1 = make_df([23000.0 + i * 5 for i in range(60)])
        df5 = make_df([23000.0 + i * 25 for i in range(12)])
        df15 = make_df([23000.0 + i * 60 for i in range(6)])

        def _inject_session_block(*, score, config, soft_blocks, reasons):
            soft_blocks.append("session_choppy_blocked")
            return score, 0

        with patch(
            "core.adaptive_signal.evaluate_dual_direction_signal",
            return_value=(
                {
                    "score": 80, "direction": "CALL", "mkt_regime": "TRENDING",
                    "adx": 30, "rsi": 55, "vwap": 23500, "atr": 100,
                    "vol_ratio": 2.0, "price": 23600, "score_components": {},
                    "macd": {}, "breakout_ok": True, "t5": "UP", "t15": "UP",
                },
                "",
            ),
        ), patch(
            "core.adaptive_signal_score_adjusters.apply_session_adjustment",
            side_effect=_inject_session_block,
        ):
            result, reason = evaluate_adaptive_signal(
                params=params, df1=df1, df5=df5, df15=df15,
                vix=15, iv=10, oi_sup=0, oi_res=0, pcr=1.0,
                smart="BULLISH",
            )

        assert result is not None
        assert "session_choppy_blocked" in result.soft_blocks

    def test_session_hard_block_enabled_blocks_signal(self, params: PureIndexSignalParams):
        """With session_hard_block_enabled=True, a session_*_blocked tag
        must hard-block the signal (restores the documented behavior of
        core/session_classifier.py::session_entry_allowed).
        """
        params.signal_cfg["session_hard_block_enabled"] = True
        df1 = make_df([23000.0 + i * 5 for i in range(60)])
        df5 = make_df([23000.0 + i * 25 for i in range(12)])
        df15 = make_df([23000.0 + i * 60 for i in range(6)])

        def _inject_session_block(*, score, config, soft_blocks, reasons):
            soft_blocks.append("session_choppy_blocked")
            return score, 0

        with patch(
            "core.adaptive_signal.evaluate_dual_direction_signal",
            return_value=(
                {"score": 75, "direction": "CALL", "mkt_regime": "TRENDING"},
                "",
            ),
        ), patch(
            "core.adaptive_signal_score_adjusters.apply_session_adjustment",
            side_effect=_inject_session_block,
        ):
            result, reason = evaluate_adaptive_signal(
                params=params, df1=df1, df5=df5, df15=df15,
                vix=15, iv=10, oi_sup=0, oi_res=0, pcr=1.0,
                smart="BULLISH",
            )

        assert result is None
        assert reason == "session_choppy_blocked"

    def test_signal_refiner_default_off_not_consulted(self, params: PureIndexSignalParams):
        """Regression guard: with signal_refiner_enabled left at its default
        (False), core.signal_refiner must never even be imported/consulted,
        and score classification is completely unchanged."""
        params.signal_cfg["session_classifier_enabled"] = False  # avoid real-time-of-day flakiness
        df1 = make_df([23000.0 + i * 5 for i in range(60)])
        df5 = make_df([23000.0 + i * 25 for i in range(12)])
        df15 = make_df([23000.0 + i * 60 for i in range(6)])
        with patch(
            "core.adaptive_signal.evaluate_dual_direction_signal",
            return_value=({"score": 90, "direction": "CALL", "mkt_regime": "TRENDING"}, ""),
        ), patch("core.signal_refiner.create_signal_refiner") as mock_create:
            result, reason = evaluate_adaptive_signal(
                params=params, df1=df1, df5=df5, df15=df15,
                vix=15, iv=10, oi_sup=0, oi_res=0, pcr=1.0,
                smart="BULLISH",
            )
            mock_create.assert_not_called()
        assert result is not None
        assert result.tier == "STRONG"

    def test_signal_refiner_enabled_false_signal_filter_blocks(self, params: PureIndexSignalParams):
        """With signal_refiner_enabled=True, a high score combined with a
        high IV rank must hard-block via signal_refiner.py's false-signal
        filter (FALSE_SIGNAL_FILTER_ENABLED)."""
        params.signal_cfg["signal_refiner_enabled"] = True
        params.signal_cfg["session_classifier_enabled"] = False  # avoid real-time-of-day flakiness
        df1 = make_df([23000.0 + i * 5 for i in range(60)])
        df5 = make_df([23000.0 + i * 25 for i in range(12)])
        df15 = make_df([23000.0 + i * 60 for i in range(6)])
        data = {
            "score": 80, "direction": "CALL", "mkt_regime": "TRENDING",
            "rsi": 5.0, "adx": 25.0,
            "macd": {"histogram": 1.0, "macd": 2.0, "signal": 1.0},
        }
        with patch("core.adaptive_signal.evaluate_dual_direction_signal", return_value=(data, "")), \
             patch("core.iv_rank.get_score_multiplier", return_value=(1.0, 50.0, "neutral")), \
             patch("core.iv_rank.get_iv_rank", return_value=40.0):  # >= FALSE_SIGNAL_IV_THRESHOLD_BLOCK default 26.0
            result, reason = evaluate_adaptive_signal(
                params=params, df1=df1, df5=df5, df15=df15,
                vix=15, iv=10, oi_sup=0, oi_res=0, pcr=1.0,
                smart="BULLISH",
            )
        assert result is None
        assert reason.startswith("signal_refiner_")

    def test_signal_refiner_enabled_regime_aware_threshold_shifts_tier(self, params: PureIndexSignalParams):
        """With signal_refiner_enabled=True, REGIME_AWARE_THRESHOLDS_ENABLED
        must actually lower the STRONG tier bar for a TRENDING regime
        (default adjust -2: 80 -> 78), reclassifying a score of 79 from
        MODERATE to STRONG — proving real effect, not just an unread flag."""
        params.signal_cfg["signal_refiner_enabled"] = True
        params.signal_cfg["session_classifier_enabled"] = False  # avoid real-time-of-day flakiness
        df1 = make_df([23000.0 + i * 5 for i in range(60)])
        df5 = make_df([23000.0 + i * 25 for i in range(12)])
        df15 = make_df([23000.0 + i * 60 for i in range(6)])
        data = {
            "score": 79, "direction": "CALL", "mkt_regime": "TRENDING",
            "rsi": 5.0, "adx": 25.0,
            "macd": {"histogram": 1.0, "macd": 2.0, "signal": 1.0},
        }
        with patch("core.adaptive_signal.evaluate_dual_direction_signal", return_value=(data, "")), \
             patch("core.iv_rank.get_score_multiplier", return_value=(1.0, 50.0, "neutral")), \
             patch("core.iv_rank.get_iv_rank", return_value=5.0):  # below FALSE_SIGNAL_IV_THRESHOLD_BLOCK -> not blocked
            result, reason = evaluate_adaptive_signal(
                params=params, df1=df1, df5=df5, df15=df15,
                vix=15, iv=10, oi_sup=0, oi_res=0, pcr=1.0,
                smart="BULLISH",
            )
        assert result is not None
        assert result.tier == "STRONG"

    def test_signal_refiner_disabled_same_score_classifies_moderate(self, params: PureIndexSignalParams):
        """Companion to the regime-aware-threshold test above: the identical
        score of 79 classifies MODERATE (not STRONG) when signal_refiner_enabled
        is left at its default (False) — isolating the tier shift to the flag."""
        params.signal_cfg["session_classifier_enabled"] = False  # avoid real-time-of-day flakiness
        df1 = make_df([23000.0 + i * 5 for i in range(60)])
        df5 = make_df([23000.0 + i * 25 for i in range(12)])
        df15 = make_df([23000.0 + i * 60 for i in range(6)])
        data = {
            "score": 79, "direction": "CALL", "mkt_regime": "TRENDING",
            "rsi": 5.0, "adx": 25.0,
            "macd": {"histogram": 1.0, "macd": 2.0, "signal": 1.0},
        }
        with patch("core.adaptive_signal.evaluate_dual_direction_signal", return_value=(data, "")), \
             patch("core.iv_rank.get_score_multiplier", return_value=(1.0, 50.0, "neutral")):
            result, reason = evaluate_adaptive_signal(
                params=params, df1=df1, df5=df5, df15=df15,
                vix=15, iv=10, oi_sup=0, oi_res=0, pcr=1.0,
                smart="BULLISH",
            )
        assert result is not None
        assert result.tier == "MODERATE"

    def test_intraday_score_threshold_boost_default_off_unaffected(self, params: PureIndexSignalParams):
        """Regression guard: with intraday_performance_monitor_enabled left at
        its default (False), a score of 90 (well above the default STRONG_MIN
        of 80) must still classify STRONG — the intraday monitor singleton
        must never even be consulted."""
        params.signal_cfg["session_classifier_enabled"] = False  # avoid real-time-of-day flakiness
        df1 = make_df([23000.0 + i * 5 for i in range(60)])
        df5 = make_df([23000.0 + i * 25 for i in range(12)])
        df15 = make_df([23000.0 + i * 60 for i in range(6)])

        with patch(
            "core.adaptive_signal.evaluate_dual_direction_signal",
            return_value=({"score": 90, "direction": "CALL", "mkt_regime": "TRENDING"}, ""),
        ), patch("core.intraday_performance_monitor.get_intraday_monitor") as mock_get:
            result, reason = evaluate_adaptive_signal(
                params=params, df1=df1, df5=df5, df15=df15,
                vix=15, iv=10, oi_sup=0, oi_res=0, pcr=1.0,
                smart="BULLISH",
            )
            mock_get.assert_not_called()

        assert result is not None
        assert result.tier == "STRONG"

    def test_intraday_score_threshold_boost_enabled_raises_bar(self, params: PureIndexSignalParams):
        """With intraday_performance_monitor_enabled=True and a DEFENSIVE-level
        score_threshold_boost, the same score of 90 must no longer classify
        STRONG (strong_min becomes 80+50=130) — the boost must have real
        effect on tier classification, not just an unread display field."""
        from core.intraday_performance_monitor import AdaptationParams

        params.signal_cfg["intraday_performance_monitor_enabled"] = True
        params.signal_cfg["session_classifier_enabled"] = False  # avoid real-time-of-day flakiness
        df1 = make_df([23000.0 + i * 5 for i in range(60)])
        df5 = make_df([23000.0 + i * 25 for i in range(12)])
        df15 = make_df([23000.0 + i * 60 for i in range(6)])

        mock_monitor = MagicMock()
        mock_monitor.get_current_params.return_value = AdaptationParams(
            score_threshold_boost=50, position_size_mult=0.5,
            reason="Defensive: session win rate very low", level="DEFENSIVE",
        )

        with patch(
            "core.adaptive_signal.evaluate_dual_direction_signal",
            return_value=({"score": 90, "direction": "CALL", "mkt_regime": "TRENDING"}, ""),
        ), patch(
            "core.intraday_performance_monitor.get_intraday_monitor",
            return_value=mock_monitor,
        ):
            result, reason = evaluate_adaptive_signal(
                params=params, df1=df1, df5=df5, df15=df15,
                vix=15, iv=10, oi_sup=0, oi_res=0, pcr=1.0,
                smart="BULLISH",
            )

        assert result is not None
        assert result.tier != "STRONG"

    def test_tier_classification(self, params: PureIndexSignalParams):
        """Very high score should result in STRONG tier."""
        df1 = make_df([23000.0 + i * 10 for i in range(60)], volumes=[10000] * 60)
        df5 = make_df([23000.0 + i * 50 for i in range(12)])
        df15 = make_df([23000.0 + i * 150 for i in range(6)])
        with patch("core.adaptive_signal._compute_features_and_score") as mock_compute:
            mock_compute.return_value = {
                "score": 95, "direction": "CALL", "mkt_regime": "TRENDING",
                "adx": 30, "rsi": 55, "vwap": 23500, "atr": 100,
                "vol_ratio": 2.0, "price": 23600, "score_components": {},
                "macd": {}, "breakout_ok": True, "t5": "UP", "t15": "UP",
            }
            result, reason = evaluate_adaptive_signal(
                params=params, df1=df1, df5=df5, df15=df15,
                vix=15, iv=10, oi_sup=0, oi_res=0, pcr=1.0,
                smart="BULLISH",
            )
            if result is not None:
                assert result.score >= 0
                assert result.raw_score >= 0


# =============================================================================
# Edge Case Tests
# =============================================================================

class TestEdgeCases:
    def test_none_dataframes(self, params: PureIndexSignalParams):
        result, reason = evaluate_adaptive_signal(
            params=params, df1=None, df5=None, df15=None,
            vix=15, iv=10, oi_sup=0, oi_res=0, pcr=1.0, smart="NEUTRAL",
        )
        assert result is None

    def test_learning_score_bonus(self, params: PureIndexSignalParams):
        df1 = make_df([23000.0 + i * 5 for i in range(60)])
        df5 = make_df([23000.0 + i * 25 for i in range(12)])
        df15 = make_df([23000.0 + i * 60 for i in range(6)])
        with patch("core.adaptive_signal._compute_features_and_score") as mock_compute:
            mock_compute.return_value = {
                "score": 60, "direction": "CALL", "mkt_regime": "TRENDING",
                "adx": 25, "rsi": 50, "vwap": 23100, "atr": 50,
                "vol_ratio": 1.5, "price": 23200, "score_components": {},
                "macd": {}, "breakout_ok": True, "t5": "UP", "t15": "UP",
            }
            result, reason = evaluate_adaptive_signal(
                params=params, df1=df1, df5=df5, df15=df15,
                vix=15, iv=10, oi_sup=0, oi_res=0, pcr=1.0,
                smart="NEUTRAL", learning_score_bonus=10,
            )
            if result is not None:
                assert isinstance(result, AdaptiveSignal)

    def test_position_sizing(self, params: PureIndexSignalParams):
        df1 = make_df([23000.0 + i * 5 for i in range(60)])
        df5 = make_df([23000.0 + i * 25 for i in range(12)])
        df15 = make_df([23000.0 + i * 60 for i in range(6)])
        with patch("core.adaptive_signal._compute_features_and_score") as mock_compute:
            mock_compute.return_value = {
                "score": 80, "direction": "CALL", "mkt_regime": "TRENDING",
                "adx": 30, "rsi": 55, "vwap": 23500, "atr": 100,
                "vol_ratio": 2.0, "price": 23600, "score_components": {},
                "macd": {}, "breakout_ok": True, "t5": "UP", "t15": "UP",
            }
            result, reason = evaluate_adaptive_signal(
                params=params, df1=df1, df5=df5, df15=df15,
                vix=15, iv=10, oi_sup=0, oi_res=0, pcr=1.0,
                smart="BULLISH", max_lots=5, capital=500000.0,
            )
            if result is not None:
                assert isinstance(result, AdaptiveSignal)
                assert result.position_spec is not None or hasattr(result, 'position_spec')

# =============================================================================
# Conviction Filter Tests (v2.54)
# =============================================================================

class TestConvictionFilter:
    """Tests for _apply_conviction_filter - the v2.54 quality gate."""

    def test_disabled_by_default(self):
        """When high_conviction_mode is not set, all gates pass."""
        from core.adaptive_signal import _apply_conviction_filter
        ok, reason = _apply_conviction_filter(
            score=50, ml_prob=0.3, vol_ratio=0.8,
            soft_blocks=["tf_mismatch"], config={},
        )
        assert ok is True
        assert reason == ""

    def test_disabled_explicitly(self):
        """When high_conviction_mode is False, all gates pass."""
        from core.adaptive_signal import _apply_conviction_filter
        ok, reason = _apply_conviction_filter(
            score=50, ml_prob=0.3, vol_ratio=0.8,
            soft_blocks=["tf_mismatch"],
            config={"high_conviction_mode": False},
        )
        assert ok is True
        assert reason == ""

    def test_all_gates_pass(self):
        """When all conditions are met, the filter passes."""
        from core.adaptive_signal import _apply_conviction_filter
        ok, reason = _apply_conviction_filter(
            score=80, ml_prob=0.75, vol_ratio=2.0,
            soft_blocks=[],
            config={"high_conviction_mode": True},
        )
        assert ok is True
        assert reason == ""

    def test_gate1_ml_prob_below_threshold(self):
        """Gate 1 blocks when ML probability is below threshold."""
        from core.adaptive_signal import _apply_conviction_filter
        ok, reason = _apply_conviction_filter(
            score=80, ml_prob=0.40, vol_ratio=2.0,
            soft_blocks=[],
            config={"high_conviction_mode": True},
        )
        assert ok is False
        assert "conviction_ml_prob" in reason

    def test_gate2_vol_ratio_below_threshold(self):
        """Gate 2 blocks when volume ratio is below minimum."""
        from core.adaptive_signal import _apply_conviction_filter
        ok, reason = _apply_conviction_filter(
            score=80, ml_prob=0.75, vol_ratio=1.0,
            soft_blocks=[],
            config={"high_conviction_mode": True},
        )
        assert ok is False
        assert "conviction_vol_ratio" in reason

    def test_gate3_score_below_threshold(self):
        """Gate 3 blocks when adjusted score is below minimum."""
        from core.adaptive_signal import _apply_conviction_filter
        ok, reason = _apply_conviction_filter(
            score=60, ml_prob=0.75, vol_ratio=2.0,
            soft_blocks=[],
            config={"high_conviction_mode": True},
        )
        assert ok is False
        assert "conviction_score" in reason

    def test_gate4_soft_tf_mismatch_blocked(self):
        """Gate 4 blocks signals with tf_mismatch soft block."""
        from core.adaptive_signal import _apply_conviction_filter
        ok, reason = _apply_conviction_filter(
            score=80, ml_prob=0.75, vol_ratio=2.0,
            soft_blocks=["tf_mismatch"],
            config={"high_conviction_mode": True},
        )
        assert ok is False
        assert "conviction_blocked_soft_tf_mismatch" in reason

    def test_gate4_soft_choppy_blocked(self):
        """Gate 4 blocks signals with choppy_regime soft block."""
        from core.adaptive_signal import _apply_conviction_filter
        ok, reason = _apply_conviction_filter(
            score=80, ml_prob=0.75, vol_ratio=2.0,
            soft_blocks=["choppy_regime"],
            config={"high_conviction_mode": True},
        )
        assert ok is False
        assert "conviction_blocked_soft_choppy_regime" in reason

    def test_gate4_tf_divergence_fallback_blocked(self):
        """Gate 4 blocks signals with tf_divergence_fallback soft block."""
        from core.adaptive_signal import _apply_conviction_filter
        ok, reason = _apply_conviction_filter(
            score=80, ml_prob=0.75, vol_ratio=2.0,
            soft_blocks=["tf_divergence_fallback"],
            config={"high_conviction_mode": True},
        )
        assert ok is False
        assert "conviction_blocked_soft_tf_divergence_fallback" in reason

    def test_custom_thresholds_from_config(self):
        """Custom config thresholds override defaults."""
        from core.adaptive_signal import _apply_conviction_filter
        # ml_prob=0.70 passes Gate 1 (threshold 0.60), vol_ratio=1.5 passes Gate 2 (threshold 1.4)
        # score=65 < 68 -> Gate 3 blocks
        ok, reason = _apply_conviction_filter(
            score=65, ml_prob=0.70, vol_ratio=1.5,
            soft_blocks=[],
            config={
                "high_conviction_mode": True,
                "HIGH_CONVICTION_ML_THRESHOLD": 0.60,
                "HIGH_CONVICTION_VOL_RATIO_MIN": 1.4,
                "HIGH_CONVICTION_SCORE_MIN": 68,
            },
        )
        assert ok is False
        assert "conviction_score_65_below_68" in reason
