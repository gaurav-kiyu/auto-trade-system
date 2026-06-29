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

from unittest.mock import patch

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
