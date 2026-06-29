"""Unit tests for index_app.domains.signal — SignalEvaluator + AdaptiveSignalConverter.

Tests the extracted signal evaluation domain by verifying correct delegation
to ``evaluate_adaptive_signal()`` and correct conversion of ``AdaptiveSignal``
dataclass instances to consumer-friendly dicts.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from core.adaptive_signal import AdaptiveSignal
from index_app.domains.signal.converter import AdaptiveSignalConverter
from index_app.domains.signal.evaluator import SignalEvaluator

# ==============================================================================
# Fixtures
# ==============================================================================


@pytest.fixture()
def sample_cfg() -> dict:
    return {
        "AI_THRESHOLD": 60,
        "STRONG_THRESHOLD": 85,
        "MODERATE_THRESHOLD": 70,
        "VIX_BLOCK_THRESHOLD": 40.0,
        "ADX_TREND_THRESHOLD": 25.0,
        "ADX_CHOP_THRESHOLD": 20.0,
        "IV_SPIKE_THRESHOLD": 60.0,
        "VOL_RATIO_MIN": 1.2,
        "EARLY_SESSION_MIN_15M": 4,
        "NORMAL_SESSION_MIN_15M": 5,
        "LEARNING_SCORE_ADJ": 0,
        "MAX_LOTS": 1,
        "BASE_CAPITAL": 100_000.0,
        "DUAL_DIRECTION_ENABLED": True,
        "COUNTER_TREND_PENALTY": 10,
        "MEAN_REVERSION_ENABLED": True,
        "TF_DIVERGENCE_FALLBACK": True,
    }


@pytest.fixture()
def strong_signal() -> AdaptiveSignal:
    """A STRONG CALL signal with high confidence."""
    return AdaptiveSignal(
        tier="STRONG",
        score=88,
        raw_score=90,
        confidence=0.95,
        direction="CALL",
        regime="TRENDING",
        soft_blocks=[],
        reasons=["[DUAL] chosen=CALL primary=85 opponent=60 pen=0", "vwap=+12pts"],
        score_components={"tf_aligned": 20, "vwap": 12, "d1_momentum": 15},
        features=["tf_aligned", "vwap", "d1_momentum"],
        atr=125.0,
        rsi=62.0,
        adx=28.0,
        vwap=23480.0,
        vol_ratio=1.8,
        price=23500.0,
        macd={"histogram": 2.5, "macd": 6.0, "signal": 4.5},
        risk={"sl_mult_adj": 0.95, "tp_mult_adj": 1.2, "trail_enabled": True},
        ml_pred_id="sig_test_123",
    )


@pytest.fixture()
def weak_signal() -> AdaptiveSignal:
    """A WEAK PUT signal with soft blocks."""
    return AdaptiveSignal(
        tier="WEAK",
        score=45,
        raw_score=65,
        confidence=0.42,
        direction="PUT",
        regime="CHOPPY",
        soft_blocks=["tf_mismatch", "choppy_regime"],
        reasons=["[TF] tf_mismatch → -20pts", "[SOFT] choppy_regime"],
        score_components={"vwap": 8, "volume": 4},
        features=["vwap"],
        atr=95.0,
        rsi=38.0,
        adx=14.0,
        vwap=23100.0,
        vol_ratio=0.9,
        price=23050.0,
        macd={},
        risk={"sl_mult_adj": 1.0, "tp_mult_adj": 1.0, "trail_enabled": False},
    )


@pytest.fixture()
def converter(sample_cfg: dict) -> AdaptiveSignalConverter:
    return AdaptiveSignalConverter(cfg=sample_cfg)


@pytest.fixture()
def evaluator(sample_cfg: dict) -> SignalEvaluator:
    return SignalEvaluator(cfg=sample_cfg)


# ==============================================================================
# Tests — AdaptiveSignalConverter
# ==============================================================================


class TestAdaptiveSignalConverter:
    """Tests for converting AdaptiveSignal dataclass to consumer dict."""

    def test_strong_signal_converts_to_dict(self, converter: AdaptiveSignalConverter, strong_signal: AdaptiveSignal):
        result = converter.to_dict(result=strong_signal, name="NIFTY", vix=14.5)
        assert isinstance(result, dict)
        assert result["symbol"] == "NIFTY"
        assert result["name"] == "NIFTY"
        assert result["signal"] == "BUY"  # CALL → BUY
        assert result["score"] == 88
        assert result["raw_score"] == 90
        assert result["direction"] == "CALL"
        assert result["regime"] == "TRENDING"
        assert result["strength"] == "STRONG"
        assert result["tier"] == "STRONG"
        assert result["confidence"] == 95.0  # 0.95 * 100
        assert result["threshold"] == 60
        assert result["vix"] == 14.5
        assert result["price"] == 23500.0
        assert result["atr"] == 125.0
        assert result["rsi"] == 62.0
        assert result["adx"] == 28.0
        assert result["breakout_ok"] is True  # no tf_mismatch in soft_blocks
        assert result["signal_engine_v2"] is True

    def test_weak_signal_below_threshold_returns_hold(self, converter: AdaptiveSignalConverter, weak_signal: AdaptiveSignal):
        """Score below AI_THRESHOLD (45 < 60) should produce HOLD signal."""
        result = converter.to_dict(result=weak_signal, name="BANKNIFTY", vix=18.0)
        assert result["signal"] == "HOLD"
        assert result["strength"] == "NONE"

    def test_moderate_signal(self, converter: AdaptiveSignalConverter):
        signal = AdaptiveSignal(
            tier="MODERATE", score=75, raw_score=78,
            confidence=0.8, direction="CALL",
            regime="SIDEWAYS", soft_blocks=[],
            reasons=["score=75"], score_components={"tf_aligned": 20},
            features=["tf_aligned"],
        )
        result = converter.to_dict(result=signal, name="FINNIFTY", vix=12.0)
        assert result["signal"] == "BUY"
        assert result["strength"] == "MODERATE"
        assert result["tier"] == "MODERATE"
        assert result["confidence"] == 80.0

    def test_put_to_sell_conversion(self, converter: AdaptiveSignalConverter):
        """PUT direction should map to SELL signal."""
        signal = AdaptiveSignal(
            tier="STRONG", score=90, raw_score=90,
            confidence=0.9, direction="PUT",
            regime="TRENDING", soft_blocks=[],
            reasons=[], score_components={}, features=[],
        )
        result = converter.to_dict(result=signal, name="NIFTY", vix=20.0)
        assert result["signal"] == "SELL"
        assert result["direction"] == "PUT"

    def test_tf_mismatch_sets_breakout_false(self, converter: AdaptiveSignalConverter, weak_signal: AdaptiveSignal):
        result = converter.to_dict(result=weak_signal, name="NIFTY", vix=15.0)
        assert result["breakout_ok"] is False
        assert "tf_mismatch" in result["soft_blocks"]

    def test_soft_blocks_and_reasons_preserved(self, converter: AdaptiveSignalConverter, weak_signal: AdaptiveSignal):
        result = converter.to_dict(result=weak_signal, name="NIFTY", vix=15.0)
        assert len(result["soft_blocks"]) == 2
        assert result["soft_blocks"] == ["tf_mismatch", "choppy_regime"]
        assert len(result["reasons"]) == 2

    def test_score_components_and_features_preserved(self, converter: AdaptiveSignalConverter, strong_signal: AdaptiveSignal):
        result = converter.to_dict(result=strong_signal, name="NIFTY", vix=14.5)
        assert result["score_components"] == strong_signal.score_components
        assert result["features"] == strong_signal.features

    def test_risk_dict_preserved(self, converter: AdaptiveSignalConverter, strong_signal: AdaptiveSignal):
        result = converter.to_dict(result=strong_signal, name="NIFTY", vix=14.5)
        assert result["risk"] == strong_signal.risk


# ==============================================================================
# Tests — SignalEvaluator
# ==============================================================================


class TestSignalEvaluator:
    """Tests for SignalEvaluator.evaluate() with mocked dependencies."""

    def test_evaluate_returns_none_on_hard_block(self, evaluator: SignalEvaluator, sample_cfg: dict):
        """With None frames, evaluate should return None and a reason."""
        result, reason = evaluator.evaluate(name="NIFTY", frames={}, vix=20.0)
        assert result is None
        assert reason is not None

    def test_evaluate_with_mocked_success(self, evaluator: SignalEvaluator):
        """With mocked dependencies, should return an AdaptiveSignal."""
        mock_signal = AdaptiveSignal(
            tier="STRONG", score=85, raw_score=85,
            confidence=0.9, direction="CALL",
            regime="TRENDING", soft_blocks=[],
            reasons=["test"], score_components={"tf_aligned": 20},
            features=["tf_aligned"],
        )

        # get_iv_rank / get_pcr_at / get_oi_at are imported *inside* evaluate()
        # so we patch them at their original module path, not on the evaluator module.
        with patch("core.iv_rank.get_iv_rank", return_value=0.5), \
             patch("core.oi_snapshot_store.get_pcr_at", return_value=1.2), \
             patch("core.oi_snapshot_store.get_oi_at", return_value=0.05), \
             patch("index_app.domains.signal.evaluator._eval_v2", return_value=(mock_signal, "")):

            result, reason = evaluator.evaluate(
                name="NIFTY",
                frames={"df1m": None, "df5m": None, "df15m": None},
                vix=15.0,
            )

        assert result is mock_signal
        assert reason == ""
        assert result.score == 85
        assert result.direction == "CALL"

    def test_evaluate_passes_correct_kwargs(self, evaluator: SignalEvaluator):
        """Verify that evaluate_adaptive_signal receives all kwargs correctly."""
        mock_signal = AdaptiveSignal(
            tier="MODERATE", score=72, raw_score=75,
            confidence=0.7, direction="PUT",
            regime="SIDEWAYS", soft_blocks=[],
            reasons=[], score_components={}, features=[],
        )

        with patch("core.iv_rank.get_iv_rank", return_value=0.3), \
             patch("core.oi_snapshot_store.get_pcr_at", return_value=0.9), \
             patch("core.oi_snapshot_store.get_oi_at", return_value=-0.1), \
             patch("index_app.domains.signal.evaluator._eval_v2") as mock_eval:

            mock_eval.return_value = (mock_signal, "")
            result, reason = evaluator.evaluate(
                name="BANKNIFTY",
                frames={"df1m": None, "df5m": None, "df15m": None},
                vix=18.0,
            )

        # Verify kwargs passed to _eval_v2
        call_kwargs = mock_eval.call_args[1]
        assert call_kwargs["vix"] == 18.0
        assert call_kwargs["max_lots"] == 1
        assert call_kwargs["capital"] == 100_000.0
        assert call_kwargs["dual_direction_enabled"] is True
        assert call_kwargs["counter_trend_penalty"] == 10
        assert call_kwargs["mean_reversion_enabled"] is True
        assert call_kwargs["tf_divergence_fallback"] is True
        # OI context
        assert call_kwargs["pcr"] == 0.9
        assert call_kwargs["smart"] == "BEARISH"  # oi_change was negative

    def test_evaluate_oi_fetch_failure(self, evaluator: SignalEvaluator):
        """When OI data fetch fails, evaluate should continue with defaults."""
        mock_signal = AdaptiveSignal(
            tier="WEAK", score=55, raw_score=60,
            confidence=0.5, direction="CALL",
            regime="NEUTRAL", soft_blocks=[],
            reasons=[], score_components={}, features=[],
        )

        with patch("core.iv_rank.get_iv_rank", return_value=0.4), \
             patch("core.oi_snapshot_store.get_pcr_at", side_effect=ValueError("no data")), \
             patch("index_app.domains.signal.evaluator._eval_v2") as mock_eval:

            mock_eval.return_value = (mock_signal, "")
            result, reason = evaluator.evaluate(
                name="NIFTY",
                frames={"df1m": None, "df5m": None, "df15m": None},
                vix=12.0,
            )

        assert result is not None
        # OI defaults: pcr=1.0, smart=NEUTRAL
        call_kwargs = mock_eval.call_args[1]
        assert call_kwargs["pcr"] == 1.0
        assert call_kwargs["smart"] == "NEUTRAL"

    def test_evaluate_returns_reason_on_failure(self, evaluator: SignalEvaluator):
        """When evaluate_adaptive_signal returns None, reason should propagate."""
        with patch("core.iv_rank.get_iv_rank", return_value=0.5), \
             patch("core.oi_snapshot_store.get_pcr_at", return_value=1.1), \
             patch("index_app.domains.signal.evaluator._eval_v2", return_value=(None, "bad_price")):

            result, reason = evaluator.evaluate(
                name="NIFTY",
                frames={"df1m": None, "df5m": None, "df15m": None},
                vix=25.0,
            )

        assert result is None
        assert reason == "bad_price"

    def test_evaluate_with_custom_thresholds(self):
        """Custom config thresholds should propagate to PureIndexSignalParams."""
        cfg = {
            "VIX_BLOCK_THRESHOLD": 50.0,
            "ADX_TREND_THRESHOLD": 30.0,
            "ADX_CHOP_THRESHOLD": 22.0,
            "IV_SPIKE_THRESHOLD": 70.0,
            "VOL_RATIO_MIN": 1.5,
            "EARLY_SESSION_MIN_15M": 6,
            "NORMAL_SESSION_MIN_15M": 7,
            "LEARNING_SCORE_ADJ": 5,
            "MAX_LOTS": 2,
            "BASE_CAPITAL": 200_000.0,
            "DUAL_DIRECTION_ENABLED": True,
            "COUNTER_TREND_PENALTY": 15,
            "MEAN_REVERSION_ENABLED": False,
            "TF_DIVERGENCE_FALLBACK": False,
        }
        evaluator = SignalEvaluator(cfg=cfg)

        mock_signal = AdaptiveSignal(
            tier="STRONG", score=90, raw_score=90,
            confidence=0.95, direction="CALL",
            regime="TRENDING", soft_blocks=[],
            reasons=[], score_components={}, features=[],
        )

        with patch("core.iv_rank.get_iv_rank", return_value=0.5), \
             patch("core.oi_snapshot_store.get_pcr_at", return_value=1.1), \
             patch("index_app.domains.signal.evaluator._eval_v2") as mock_eval:

            mock_eval.return_value = (mock_signal, "")
            evaluator.evaluate(
                name="NIFTY",
                frames={"df1m": None, "df5m": None, "df15m": None},
                vix=15.0,
            )

        call_kwargs = mock_eval.call_args[1]
        assert call_kwargs["max_lots"] == 2
        assert call_kwargs["capital"] == 200_000.0
        assert call_kwargs["mean_reversion_enabled"] is False
        assert call_kwargs["tf_divergence_fallback"] is False
