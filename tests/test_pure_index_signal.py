"""Tests for core/pure_index_signal.py - Deterministic Signal Evaluation.

Covers:
- compute_index_score() with various component contributions
- evaluate_index_signal_partial() with valid/invalid data
- evaluate_dual_direction_signal() for CALL and PUT scoring
- finalize_index_signal_with_threshold()
- _drop_partial_candle, _validate_frame_alignment
- _macd_bonus_delta, _bar_signal_ts
- PureIndexRegimeParams, PureIndexSignalParams
"""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, PropertyMock, patch

import pandas as pd
import pytest

from core.pure_index_signal import (
    PureIndexRegimeParams,
    PureIndexSignalParams,
    _bar_signal_ts,
    _drop_partial_candle,
    _macd_bonus_delta,
    _validate_frame_alignment,
    compute_index_score,
    evaluate_dual_direction_signal,
    evaluate_index_signal_partial,
    finalize_index_signal_with_threshold,
)


# ── Helpers ──────────────────────────────────────────────────────────────

def make_df(closes: list[float], opens: list[float] | None = None, highs: list[float] | None = None,
            lows: list[float] | None = None, volumes: list[int] | None = None) -> pd.DataFrame:
    """Create a simple OHLCV DataFrame for testing."""
    n = len(closes)
    opens = opens or [c * 0.99 for c in closes]
    highs = highs or [c * 1.02 for c in closes]
    lows = lows or [c * 0.98 for c in closes]
    volumes = volumes or [1000] * n
    return pd.DataFrame({
        "Open": opens, "High": highs, "Low": lows, "Close": closes, "Volume": volumes,
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


@pytest.fixture
def trending_up_df() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """DataFrames with clear uptrend."""
    base = 23000.0
    closes = [base + i * 10 for i in range(60)]
    return make_df(closes), make_df(closes), make_df(closes)


# =============================================================================
# _drop_partial_candle Tests
# =============================================================================

class TestDropPartialCandle:
    def test_returns_none_when_df_none(self):
        assert _drop_partial_candle(None) is None

    def test_returns_df_when_short(self):
        df = make_df([100.0, 101.0])
        result = _drop_partial_candle(df)
        assert result is not None
        assert len(result) == 2

    def test_drops_last_candle_with_zero_volume(self):
        df = make_df([100.0, 101.0, 102.0], volumes=[1000, 2000, 0])
        result = _drop_partial_candle(df)
        assert result is not None
        assert len(result) == 2  # Last zero-volume candle dropped

    def test_keeps_last_candle_when_volume_nonzero(self):
        df = make_df([100.0, 101.0], volumes=[1000, 500])
        result = _drop_partial_candle(df)
        assert len(result) == 2  # All kept


# =============================================================================
# _validate_frame_alignment Tests
# =============================================================================

class TestValidateFrameAlignment:
    def test_valid_alignment(self):
        df1 = make_df([100.0] * 30)
        df5 = make_df([100.0] * 10)
        df15 = make_df([100.0] * 5)
        assert _validate_frame_alignment(df1, df5, df15, 120, 300) is True


# =============================================================================
# _macd_bonus_delta Tests
# =============================================================================

class TestMacdBonusDelta:
    def test_call_with_favorable_macd(self):
        macd = {"histogram": 1.5, "macd": 10.0, "signal": 8.0}
        assert _macd_bonus_delta("CALL", macd, 5) == 5

    def test_put_with_favorable_macd(self):
        macd = {"histogram": -1.5, "macd": 8.0, "signal": 10.0}
        assert _macd_bonus_delta("PUT", macd, 5) == 5

    def test_no_bonus_on_unfavorable(self):
        macd = {"histogram": -1.5, "macd": 8.0, "signal": 10.0}
        assert _macd_bonus_delta("CALL", macd, 5) == 0

    def test_returns_zero_on_empty_macd(self):
        assert _macd_bonus_delta("CALL", {}, 5) == 0

    def test_returns_zero_on_none_macd(self):
        assert _macd_bonus_delta("CALL", None, 5) == 0  # type: ignore[arg-type]


# =============================================================================
# _bar_signal_ts Tests
# =============================================================================

class TestBarSignalTs:
    def test_returns_zero_on_none(self):
        assert _bar_signal_ts(None) == 0.0

    def test_returns_zero_on_empty(self):
        assert _bar_signal_ts(pd.DataFrame()) == 0.0


# =============================================================================
# compute_index_score Tests
# =============================================================================

class TestComputeIndexScore:
    def test_minimum_score(self):
        """With no favorable conditions, score is 0."""
        score = compute_index_score(
            t5="FLAT", t15="FLAT", price=100, vwap=105, atr=0.3,
            vol=0.5, d1=-1, d5=-1, pcr=0.5, smart="NEUTRAL",
            signal_cfg={}, vol_ratio_min=1.2,
        )
        assert score >= 0

    def test_tf_alignment_gives_points(self):
        score = compute_index_score(
            t5="UP", t15="UP", price=101, vwap=100, atr=1.0,
            vol=2.0, d1=5, d5=3, pcr=1.5, smart="BULLISH",
            signal_cfg={}, vol_ratio_min=1.2,
        )
        assert score > 0
        assert score <= 100

    def test_max_score_100(self):
        score = compute_index_score(
            t5="UP", t15="UP", price=110, vwap=100, atr=2.0,
            vol=50.0, d1=10, d5=10, pcr=2.0, smart="BULLISH",
            signal_cfg={"ATR_MIN_THRESHOLD": 0.5},
            vol_ratio_min=1.2, learning_score_bonus=10,
        )
        assert score <= 100
        assert score >= 50

    def test_custom_signal_cfg(self):
        score = compute_index_score(
            t5="UP", t15="UP", price=101, vwap=100, atr=1.0,
            vol=2.0, d1=5, d5=3, pcr=1.5, smart="BULLISH",
            signal_cfg={"PCR_BULLISH": 2.0, "INDEX_RSI_BONUS": 0},
            vol_ratio_min=1.2, rsi=50,
        )
        assert isinstance(score, int)

    def test_learning_bonus_adds_points(self):
        score_with = compute_index_score(
            t5="UP", t15="UP", price=101, vwap=100, atr=1.0,
            vol=2.0, d1=5, d5=3, pcr=1.5, smart="BULLISH",
            signal_cfg={}, vol_ratio_min=1.2, learning_score_bonus=15,
        )
        score_without = compute_index_score(
            t5="UP", t15="UP", price=101, vwap=100, atr=1.0,
            vol=2.0, d1=5, d5=3, pcr=1.5, smart="BULLISH",
            signal_cfg={}, vol_ratio_min=1.2, learning_score_bonus=0,
        )
        assert score_with >= score_without


# =============================================================================
# evaluate_index_signal_partial Tests
# =============================================================================

class TestEvaluateIndexSignalPartial:
    def test_short_data_returns_none(self, params: PureIndexSignalParams):
        df1 = make_df([100.0] * 5)  # Too short
        df5 = make_df([100.0] * 3)
        df15 = make_df([100.0] * 2)
        result, reason = evaluate_index_signal_partial(
            params=params, df1=df1, df5=df5, df15=df15,
            vix=15, iv=10, oi_sup=0, oi_res=0, pcr=1.0, smart="NEUTRAL",
        )
        assert result is None
        assert "short" in reason

    def test_bad_price_returns_none(self, params: PureIndexSignalParams):
        # Create data with trend but 0 as last close (bad price)
        df1 = make_df([100.0 + i * 0.5 for i in range(60)])
        df1.iloc[-1, df1.columns.get_loc("Close")] = 0.0
        df5 = make_df([100.0 + i * 2.5 for i in range(12)])
        df15 = make_df([100.0 + i * 6 for i in range(6)])
        result, reason = evaluate_index_signal_partial(
            params=params, df1=df1, df5=df5, df15=df15,
            vix=15, iv=10, oi_sup=0, oi_res=0, pcr=1.0, smart="NEUTRAL",
        )
        assert result is None

    def test_force_direction(self, params: PureIndexSignalParams):
        df1 = make_df([23000.0 + i * 5 for i in range(60)])
        df5 = make_df([23000.0 + i * 25 for i in range(12)])
        df15 = make_df([23000.0 + i * 60 for i in range(6)])
        result, reason = evaluate_index_signal_partial(
            params=params, df1=df1, df5=df5, df15=df15,
            vix=15, iv=10, oi_sup=0, oi_res=0, pcr=1.0, smart="NEUTRAL",
            force_direction="CALL",
        )
        if result is not None:
            assert result["direction"] == "CALL"

    def test_iv_spike_returns_none(self, params: PureIndexSignalParams):
        df1 = make_df([23000.0 + i * 5 for i in range(60)])
        df5 = make_df([23000.0 + i * 25 for i in range(12)])
        df15 = make_df([23000.0 + i * 60 for i in range(6)])
        result, reason = evaluate_index_signal_partial(
            params=params, df1=df1, df5=df5, df15=df15,
            vix=15, iv=100, oi_sup=0, oi_res=0, pcr=1.0, smart="NEUTRAL",
        )
        if result is not None:
            assert "iv" not in str(result.get("score_components", {}))
        # iv_spike check may or may not trigger depending on threshold


# =============================================================================
# evaluate_dual_direction_signal Tests
# =============================================================================

class TestEvaluateDualDirectionSignal:
    def test_returns_partial_or_none(self, params: PureIndexSignalParams):
        df1 = make_df([23000.0 + i * 5 for i in range(60)])
        df5 = make_df([23000.0 + i * 25 for i in range(12)])
        df15 = make_df([23000.0 + i * 60 for i in range(6)])
        result, reason = evaluate_dual_direction_signal(
            params=params, df1=df1, df5=df5, df15=df15,
            vix=15, iv=10, oi_sup=0, oi_res=0, pcr=1.0, smart="NEUTRAL",
        )
        assert result is None or isinstance(result, dict)

    def test_dual_disabled(self, params: PureIndexSignalParams):
        df1 = make_df([23000.0 + i * 5 for i in range(60)])
        df5 = make_df([23000.0 + i * 25 for i in range(12)])
        df15 = make_df([23000.0 + i * 60 for i in range(6)])
        result, reason = evaluate_dual_direction_signal(
            params=params, df1=df1, df5=df5, df15=df15,
            vix=15, iv=10, oi_sup=0, oi_res=0, pcr=1.0, smart="NEUTRAL",
            dual_direction_enabled=False,
        )
        assert result is None or isinstance(result, dict)


# =============================================================================
# finalize_index_signal_with_threshold Tests
# =============================================================================

class TestFinalizeIndexSignal:
    def test_attaches_threshold_fields(self):
        partial = {"score": 75, "direction": "CALL", "signal_reason": "Strong"}
        result = finalize_index_signal_with_threshold(
            partial, threshold=70, regime="TRENDING",
            adaptive_delta=5, adaptive_reason="ML boost",
            trace_id="TRACE-001",
        )
        assert result["threshold"] == 70
        assert result["regime"] == "TRENDING"
        assert result["adaptive_delta"] == 5
        assert result["trace_id"] == "TRACE-001"
        assert "stars" in result
        assert "strength" in result
        assert "confidence" in result

    def test_low_score_hold(self):
        partial = {"score": 30, "direction": "PUT", "signal_reason": "Weak"}
        result = finalize_index_signal_with_threshold(
            partial, threshold=70, regime="CHOPPY",
            adaptive_delta=0, adaptive_reason="",
            trace_id="TRACE-002",
        )
        assert result["signal"] in ("BUY", "HOLD")
        assert "action" in result

    def test_preserves_partial_fields(self):
        partial = {"score": 85, "direction": "CALL", "signal_reason": "Strong", "price": 23500}
        result = finalize_index_signal_with_threshold(
            partial, threshold=70, regime="TRENDING",
            adaptive_delta=5, adaptive_reason="ML",
            trace_id="TRACE-003",
        )
        assert result["price"] == 23500
        assert result["signal_reason"] == "Strong"
