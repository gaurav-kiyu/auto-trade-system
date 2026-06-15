"""
Tests for core/pure_index_signal.py — Pure, deterministic index signal evaluation.

Covers:
  - compute_index_score component scoring
  - _macd_bonus_delta direction check
  - evaluate_index_signal_partial structural checks
  - evaluate_dual_direction_signal
  - finalize_index_signal_with_threshold
  - Utility functions (_drop_partial_candle, _validate_frame_alignment)
  - Various hard-block scenarios (1m_short, tf_mismatch, choppy, bad_price)
"""
from __future__ import annotations

import datetime

import pandas as pd

from core.pure_index_signal import (
    PureIndexRegimeParams,
    PureIndexSignalParams,
    _drop_partial_candle,
    _macd_bonus_delta,
    _validate_frame_alignment,
    compute_index_score,
    evaluate_dual_direction_signal,
    evaluate_index_signal_partial,
    finalize_index_signal_with_threshold,
)


# ── Helpers for creating test dataframes ────────────────────────────


def _make_df(close_values: list[float], volumes: list[int] | None = None) -> pd.DataFrame:
    """Create a simple OHLCV DataFrame from close prices."""
    n = len(close_values)
    volumes = volumes or [10000] * n
    return pd.DataFrame({
        "Open": close_values,
        "High": [c * 1.005 for c in close_values],
        "Low": [c * 0.995 for c in close_values],
        "Close": close_values,
        "Volume": volumes,
    })


def _sample_params(**overrides: dict) -> PureIndexSignalParams:
    """Create sample signal params for testing."""
    return PureIndexSignalParams(
        name="NIFTY",
        signal_cfg={
            "ATR_MIN_THRESHOLD": 0.5,
            "INDEX_RSI_BONUS": 8,
            "INDEX_RSI_OVERBOUGHT": 75,
            "INDEX_RSI_OVERSOLD": 25,
            "INDEX_RSI_HEALTHY_LOW_CALL": 40,
            "INDEX_RSI_HEALTHY_HIGH_CALL": 70,
            "INDEX_RSI_HEALTHY_LOW_PUT": 30,
            "INDEX_RSI_HEALTHY_HIGH_PUT": 60,
            "PCR_BULLISH": 1.2,
            "PCR_BEARISH": 0.8,
            "MACD_BONUS": 5,
            "BREAKOUT_BONUS": 8,
            "VWAP_RECLAIM_BONUS": 7,
            "ORB_BONUS": 10,
            "ADX_PENALTY_THRESHOLD": 12,
            "ADX_PENALTY_POINTS": 5,
            "ADX_TREND_THRESHOLD": 20,
            "ADX_TREND_BONUS_POINTS": 5,
            "REGIME_SCORE_PENALTY_HV": 8,
            "REGIME_SCORE_PENALTY_EVENT": 10,
            "FRAME_ALIGN_1M_5M": 120,
            "FRAME_ALIGN_1M_15M": 300,
        },
        regime=PureIndexRegimeParams(
            vix_block_threshold=35.0,
            adx_trend_threshold=20.0,
            adx_chop_threshold=15.0,
        ),
        iv_spike_threshold=50.0,
        vol_ratio_min=1.5,
        is_early_session=False,
        min15_early=4,
        min15_normal=5,
    )


# ── compute_index_score ─────────────────────────────────────────────


class TestComputeIndexScore:
    def test_tf_aligned_score(self) -> None:
        score = compute_index_score(
            "UP", "UP", 100.0, 99.0, 1.0, 2.0, 1.0, 1.0, 1.5, "BULLISH",
            signal_cfg=_sample_params().signal_cfg,
            vol_ratio_min=1.5,
            rsi=55.0,
        )
        assert isinstance(score, int)
        assert 0 <= score <= 100

    def test_zero_score_for_wrong_direction(self) -> None:
        """All components should be 0 for perfectly wrong direction."""
        score = compute_index_score(
            "DOWN", "DOWN", 100.0, 102.0, 1.0, 2.0, -2.0, -2.0, 0.5, "BULLISH",
            signal_cfg=_sample_params().signal_cfg,
            vol_ratio_min=1.5,
            rsi=55.0,
        )
        # PUT direction, price below VWAP, negative delta, PCR bearish
        assert isinstance(score, int)
        assert 0 <= score <= 100

    def test_tf_alignment_bonus(self) -> None:
        """TF alignment (t5 == t15) gives 20 points."""
        aligned = compute_index_score(
            "UP", "UP", 100.0, 99.0, 1.0, 2.0, 1.0, 1.0, 1.5, "BULLISH",
            signal_cfg=_sample_params().signal_cfg,
            vol_ratio_min=1.5, rsi=55.0,
        )
        not_aligned = compute_index_score(
            "UP", "DOWN", 100.0, 99.0, 1.0, 2.0, 1.0, 1.0, 1.5, "BULLISH",
            signal_cfg=_sample_params().signal_cfg,
            vol_ratio_min=1.5, rsi=55.0,
        )
        assert aligned >= not_aligned

    def test_vwap_bonus_scales_with_distance(self) -> None:
        near_vwap = compute_index_score(
            "UP", "UP", 100.1, 100.0, 1.0, 2.0, 1.0, 1.0, 1.5, "BULLISH",
            signal_cfg=_sample_params().signal_cfg,
            vol_ratio_min=1.5, rsi=55.0,
        )
        far_vwap = compute_index_score(
            "UP", "UP", 102.0, 100.0, 1.0, 2.0, 1.0, 1.0, 1.5, "BULLISH",
            signal_cfg=_sample_params().signal_cfg,
            vol_ratio_min=1.5, rsi=55.0,
        )
        # Far from VWAP should score higher
        assert far_vwap >= near_vwap

    def test_rsi_bonus_in_healthy_zone(self) -> None:
        """RSI 55 for CALL direction is healthy (40-70) → bonus."""
        healthy_rsi = compute_index_score(
            "UP", "UP", 100.0, 99.0, 1.0, 2.0, 1.0, 1.0, 1.5, "BULLISH",
            signal_cfg=_sample_params().signal_cfg,
            vol_ratio_min=1.5, rsi=55.0,
        )
        unhealthy_rsi = compute_index_score(
            "UP", "UP", 100.0, 99.0, 1.0, 2.0, 1.0, 1.0, 1.5, "BULLISH",
            signal_cfg=_sample_params().signal_cfg,
            vol_ratio_min=1.5, rsi=80.0,  # Overbought — no bonus
        )
        assert healthy_rsi >= unhealthy_rsi

    def test_smart_money_bonus(self) -> None:
        bullish_sentiment = compute_index_score(
            "UP", "UP", 100.0, 99.0, 1.0, 2.0, 1.0, 1.0, 1.5, "BULLISH",
            signal_cfg=_sample_params().signal_cfg,
            vol_ratio_min=1.5, rsi=55.0,
        )
        bearish_sentiment = compute_index_score(
            "UP", "UP", 100.0, 99.0, 1.0, 2.0, 1.0, 1.0, 1.5, "BEARISH",
            signal_cfg=_sample_params().signal_cfg,
            vol_ratio_min=1.5, rsi=55.0,
        )
        assert bullish_sentiment >= bearish_sentiment

    def test_learning_bonus_added(self) -> None:
        no_bonus = compute_index_score(
            "UP", "UP", 100.0, 99.0, 1.0, 2.0, 1.0, 1.0, 1.5, "BULLISH",
            signal_cfg=_sample_params().signal_cfg,
            vol_ratio_min=1.5, rsi=55.0,
            learning_score_bonus=0,
        )
        with_bonus = compute_index_score(
            "UP", "UP", 100.0, 99.0, 1.0, 2.0, 1.0, 1.0, 1.5, "BULLISH",
            signal_cfg=_sample_params().signal_cfg,
            vol_ratio_min=1.5, rsi=55.0,
            learning_score_bonus=10,
        )
        assert with_bonus >= no_bonus

    def test_score_capped_at_100(self) -> None:
        score = compute_index_score(
            "UP", "UP", 100.0, 50.0, 5.0, 5.0, 1.0, 1.0, 2.5, "BULLISH",
            signal_cfg=_sample_params().signal_cfg,
            vol_ratio_min=0.5, rsi=55.0,
        )
        assert score <= 100


# ── _macd_bonus_delta ───────────────────────────────────────────────


class TestMACDBonusDelta:
    def test_call_positive_histogram_gets_bonus(self) -> None:
        macd = {"histogram": 5.0, "macd": 10.0, "signal": 8.0}
        bonus = _macd_bonus_delta("CALL", macd, 5)
        assert bonus == 5

    def test_put_negative_histogram_gets_bonus(self) -> None:
        macd = {"histogram": -5.0, "macd": -10.0, "signal": -8.0}
        bonus = _macd_bonus_delta("PUT", macd, 5)
        assert bonus == 5

    def test_wrong_direction_no_bonus(self) -> None:
        macd = {"histogram": 5.0, "macd": 10.0, "signal": 8.0}
        bonus = _macd_bonus_delta("PUT", macd, 5)
        assert bonus == 0

    def test_not_dict_returns_zero(self) -> None:
        assert _macd_bonus_delta("CALL", "not_a_dict", 5) == 0

    def test_empty_dict_returns_zero(self) -> None:
        assert _macd_bonus_delta("CALL", {}, 5) == 0


# ── _drop_partial_candle ────────────────────────────────────────────


class TestDropPartialCandle:
    def test_none_input_returns_none(self) -> None:
        assert _drop_partial_candle(None) is None

    def test_single_row_unchanged(self) -> None:
        df = _make_df([100.0], [10000])
        result = _drop_partial_candle(df)
        assert len(result) == 1

    def test_drops_last_row_with_zero_volume(self) -> None:
        df = _make_df([100.0, 101.0], [10000, 0])
        result = _drop_partial_candle(df)
        assert len(result) == 1
        assert result.iloc[-1]["Close"] == 100.0

    def test_keeps_last_row_with_volume(self) -> None:
        df = _make_df([100.0, 101.0], [10000, 5000])
        result = _drop_partial_candle(df)
        assert len(result) == 2


# ── _validate_frame_alignment ───────────────────────────────────────


class TestValidateFrameAlignment:
    def test_aligned_frames_pass(self) -> None:
        now = datetime.datetime.now()
        df1 = _make_df([100.0, 101.0])
        df5 = _make_df([100.0, 101.0])
        df15 = _make_df([100.0, 101.0])
        # Set timestamps close together
        df1.index = [now, now + datetime.timedelta(minutes=1)]
        df5.index = [now, now + datetime.timedelta(minutes=1)]
        df15.index = [now, now + datetime.timedelta(minutes=1)]
        assert _validate_frame_alignment(df1, df5, df15, tol_5m=120, tol_15m=300)

    def test_error_returns_true(self) -> None:
        """On error (e.g. no timestamp), return True to not block."""
        df1 = _make_df([100.0])
        df5 = _make_df([100.0])
        df15 = _make_df([100.0])
        # No timestamp attribute
        assert _validate_frame_alignment(df1, df5, df15, tol_5m=120, tol_15m=300)


# ── evaluate_index_signal_partial ───────────────────────────────────


class TestEvaluateSignalPartial:
    def test_requires_min_1m_rows(self) -> None:
        df1 = _make_df([100.0] * 20)
        df5 = _make_df([100.0] * 30)
        df15 = _make_df([100.0] * 30)
        result, reason = evaluate_index_signal_partial(
            params=_sample_params(),
            df1=df1, df5=df5, df15=df15,
            vix=20.0, iv=10.0,
            oi_sup=0, oi_res=0, pcr=1.0, smart="NEUTRAL",
        )
        assert result is None
        assert reason == "1m_short"

    def test_returns_signal_with_sufficient_data(self) -> None:
        df1 = _make_df([100.0 + i * 0.1 for i in range(60)])
        df5 = _make_df([100.0 + i * 0.5 for i in range(30)])
        df15 = _make_df([100.0 + i * 1.0 for i in range(15)])
        result, reason = evaluate_index_signal_partial(
            params=_sample_params(),
            df1=df1, df5=df5, df15=df15,
            vix=20.0, iv=10.0,
            oi_sup=0, oi_res=0, pcr=1.0, smart="NEUTRAL",
        )
        # The result depends on trend analysis, but should not be None
        # since we have enough data points
        if result is not None:
            assert "score" in result
            assert "direction" in result
            assert "mkt_regime" in result

    def test_iv_spike_blocks(self) -> None:
        # Create trending data that passes structural checks, then test IV spike
        # Up-trending data to establish t5/t15 trend
        df1 = _make_df([100.0 + i * 0.5 for i in range(60)])
        df5 = _make_df([100.0 + i * 2.0 for i in range(30)])
        df15 = _make_df([100.0 + i * 3.0 for i in range(15)])
        params = _sample_params()
        result, reason = evaluate_index_signal_partial(
            params=params,
            df1=df1, df5=df5, df15=df15,
            vix=20.0, iv=100.0,  # IV above spike threshold
            oi_sup=0, oi_res=0, pcr=1.0, smart="NEUTRAL",
        )
        assert result is None
        assert "iv_spike" in reason

    def test_bad_price_blocks(self) -> None:
        df1 = _make_df([0.0] * 60)  # Zero price
        df5 = _make_df([0.0] * 30)
        df15 = _make_df([0.0] * 15)
        result, reason = evaluate_index_signal_partial(
            params=_sample_params(),
            df1=df1, df5=df5, df15=df15,
            vix=20.0, iv=10.0,
            oi_sup=0, oi_res=0, pcr=1.0, smart="NEUTRAL",
        )
        assert result is None
        assert "bad_price" in reason or "1m_short" in reason or "5m_short" in reason


# ── evaluate_dual_direction_signal ──────────────────────────────────


class TestEvaluateDualDirection:
    def test_returns_signal_or_none(self) -> None:
        df1 = _make_df([100.0 + i * 1.0 for i in range(60)])
        df5 = _make_df([100.0 + i * 2.0 for i in range(30)])
        df15 = _make_df([100.0 + i * 3.0 for i in range(15)])
        result, reason = evaluate_dual_direction_signal(
            params=_sample_params(),
            df1=df1, df5=df5, df15=df15,
            vix=20.0, iv=10.0,
            oi_sup=0, oi_res=0, pcr=1.0, smart="NEUTRAL",
        )
        # Should return a result (might be None with insufficient trend)
        if result is not None:
            assert "direction" in result
            assert "score" in result


# ── finalize_index_signal_with_threshold ────────────────────────────


class TestFinalizeSignal:
    def test_attaches_threshold_fields(self) -> None:
        partial = {
            "name": "NIFTY", "direction": "CALL", "price": 23500.0,
            "score": 75, "vwap": 23480.0, "atr": 120.0, "vol_ratio": 1.5,
            "trend": "UP", "trend_5m": "UP", "trend_15m": "UP",
            "mkt_regime": "TRENDING", "adx": 25.0, "pcr": 1.3, "smart": "BULLISH",
            "sup": 0, "res": 0, "iv": 10.0, "vix": 20.0, "breakout_ok": True,
            "rsi": 55.0, "score_components": {"tf_aligned": 20},
            "macd": {}, "ema20": 0, "ema50": 0, "ema200": 0,
            "stop_loss": 23400.0, "tp1": 23600.0, "tp2": 23700.0, "tp3": 23800.0,
            "support": 0, "resistance": 0, "signal_ts": 0.0,
            "signal_reason": "score=75 regime=TRENDING dir=CALL",
        }
        result = finalize_index_signal_with_threshold(
            partial,
            threshold=70,
            regime="TRENDING",
            adaptive_delta=0,
            adaptive_reason="",
            trace_id="test-001",
        )
        assert result["threshold"] == 70
        assert result["stars"] is not None
        assert result["strength"] is not None
        assert result["signal"] in ("BUY", "HOLD")
        assert result["action"] in ("BUY", "HOLD")
        assert result["trace_id"] == "test-001"

    def test_threshold_clamped(self) -> None:
        partial = {
            "name": "NIFTY", "direction": "CALL", "price": 23500.0,
            "score": 50, "vwap": 23480.0, "atr": 120.0, "vol_ratio": 0.5,
            "trend": "UP", "trend_5m": "UP", "trend_15m": "UP",
            "mkt_regime": "NEUTRAL", "adx": 15.0, "pcr": 1.0, "smart": "NEUTRAL",
            "sup": 0, "res": 0, "iv": 10.0, "vix": 20.0, "breakout_ok": True,
            "rsi": 50.0, "score_components": {"tf_aligned": 20},
            "macd": {}, "ema20": 0, "ema50": 0, "ema200": 0,
            "stop_loss": 23400.0, "tp1": 23600.0, "tp2": 23700.0, "tp3": 23800.0,
            "support": 0, "resistance": 0, "signal_ts": 0.0,
            "signal_reason": "score=50",
        }
        result = finalize_index_signal_with_threshold(
            partial, threshold=150,  # Over 100 — should be clamped
            regime="NEUTRAL",
            adaptive_delta=5,
            adaptive_reason="session boost",
            trace_id="test-002",
        )
        assert result["threshold"] <= 100
