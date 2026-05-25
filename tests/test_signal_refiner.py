"""Tests for core/signal_refiner.py — multi-indicator signal refinement & filtering."""

from __future__ import annotations

from core.signal_refiner import (
    SignalRefiner,
    SignalRefinerConfig,
    create_signal_refiner,
)

# ── SignalRefinerConfig ───────────────────────────────────────────────────────

class TestConfig:
    def test_defaults(self) -> None:
        c = SignalRefinerConfig()
        assert c.enabled is True
        assert c.rsi_confirm_threshold == 45.0
        assert c.adx_confirm_min == 20.0
        assert c.iv_block_threshold == 28.0
        assert c.false_signal_filter is True
        assert c.false_signal_min_score_block == 75
        assert c.regime_aware_thresholds is True


# ── should_block_signal ───────────────────────────────────────────────────────

class TestShouldBlockSignal:
    def test_disabled_does_not_block(self) -> None:
        refiner = SignalRefiner(SignalRefinerConfig(enabled=False))
        blocked, reason = refiner.should_block_signal(80, "TRENDING", 20.0)
        assert blocked is False
        assert reason == ""

    def test_false_signal_filter_blocks_high_score_high_iv(self) -> None:
        refiner = SignalRefiner(SignalRefinerConfig(
            false_signal_filter=True, false_signal_min_score_block=75, false_signal_iv_threshold=26.0,
        ))
        blocked, reason = refiner.should_block_signal(80, "TRENDING", 28.0)
        assert blocked is True
        assert "score (80)" in reason
        assert "IV rank" in reason

    def test_false_signal_filter_passes_low_iv(self) -> None:
        refiner = SignalRefiner(SignalRefinerConfig(
            false_signal_filter=True, false_signal_min_score_block=75, false_signal_iv_threshold=26.0,
        ))
        blocked, _ = refiner.should_block_signal(80, "TRENDING", 20.0)
        assert blocked is False  # IV rank too low for filter

    def test_false_signal_filter_passes_low_score(self) -> None:
        refiner = SignalRefiner(SignalRefinerConfig(
            false_signal_filter=True, false_signal_min_score_block=75, false_signal_iv_threshold=26.0,
        ))
        blocked, _ = refiner.should_block_signal(70, "TRENDING", 28.0)
        assert blocked is False  # score too low for filter

    def test_rsi_too_close_to_neutral_blocks(self) -> None:
        refiner = SignalRefiner(SignalRefinerConfig(rsi_confirm_threshold=45.0))
        # abs(52 - 50) = 2 < 45 → blocked
        blocked, reason = refiner.should_block_signal(80, "TRENDING", 20.0, rsi=52.0)
        assert blocked is True
        assert "RSI" in reason

    def test_rsi_sufficiently_away_passes(self) -> None:
        refiner = SignalRefiner(SignalRefinerConfig(rsi_confirm_threshold=5.0))
        # abs(60 - 50) = 10 >= 5 → passes
        blocked, _ = refiner.should_block_signal(80, "TRENDING", 20.0, rsi=60.0)
        assert blocked is False

    def test_macd_confirm_blocks_when_not_confirming(self) -> None:
        refiner = SignalRefiner(SignalRefinerConfig(macd_confirm_required=True))
        blocked, reason = refiner.should_block_signal(80, "TRENDING", 20.0, macd="NEUTRAL")
        assert blocked is True
        assert "MACD" in reason

    def test_macd_confirm_passes_bullish(self) -> None:
        refiner = SignalRefiner(SignalRefinerConfig(macd_confirm_required=True))
        blocked, _ = refiner.should_block_signal(80, "TRENDING", 20.0, macd="BULLISH")
        assert blocked is False

    def test_adx_below_min_blocks(self) -> None:
        refiner = SignalRefiner(SignalRefinerConfig(adx_confirm_min=20.0))
        blocked, reason = refiner.should_block_signal(80, "TRENDING", 20.0, adx=15.0)
        assert blocked is True
        assert "ADX" in reason

    def test_adx_above_min_passes(self) -> None:
        refiner = SignalRefiner(SignalRefinerConfig(adx_confirm_min=20.0))
        blocked, _ = refiner.should_block_signal(80, "TRENDING", 20.0, adx=25.0)
        assert blocked is False

    def test_vix_above_iv_block_blocks(self) -> None:
        refiner = SignalRefiner(SignalRefinerConfig(iv_block_threshold=28.0))
        blocked, reason = refiner.should_block_signal(80, "TRENDING", 20.0, vix=30.0)
        assert blocked is True
        assert "VIX" in reason

    def test_vix_below_iv_block_passes(self) -> None:
        refiner = SignalRefiner(SignalRefinerConfig(iv_block_threshold=28.0))
        blocked, _ = refiner.should_block_signal(80, "TRENDING", 20.0, vix=25.0)
        assert blocked is False

    def test_multiple_checks_all_pass(self) -> None:
        refiner = SignalRefiner(SignalRefinerConfig(
            rsi_confirm_threshold=5.0, adx_confirm_min=20.0, iv_block_threshold=28.0,
        ))
        blocked, _ = refiner.should_block_signal(
            70, "TRENDING", 20.0, rsi=60.0, macd="BULLISH", adx=25.0, vix=18.0,
        )
        assert blocked is False


# ── get_regime_adjusted_threshold ─────────────────────────────────────────────

class TestRegimeAdjustment:
    def test_disabled_returns_base(self) -> None:
        refiner = SignalRefiner(SignalRefinerConfig(regime_aware_thresholds=False))
        assert refiner.get_regime_adjusted_threshold(70, "TRENDING") == 70

    def test_trending_lowers_threshold(self) -> None:
        refiner = SignalRefiner(SignalRefinerConfig(
            regime_aware_thresholds=True, threshold_trending_adjust=-2,
        ))
        assert refiner.get_regime_adjusted_threshold(70, "TRENDING") == 68

    def test_sideways_raises_threshold(self) -> None:
        refiner = SignalRefiner(SignalRefinerConfig(
            regime_aware_thresholds=True, threshold_sideways_adjust=2,
        ))
        assert refiner.get_regime_adjusted_threshold(70, "SIDEWAYS") == 72

    def test_range_raises_threshold_more(self) -> None:
        refiner = SignalRefiner(SignalRefinerConfig(
            regime_aware_thresholds=True, threshold_range_adjust=3,
        ))
        assert refiner.get_regime_adjusted_threshold(70, "RANGE") == 73

    def test_unknown_regime_returns_base(self) -> None:
        refiner = SignalRefiner(SignalRefinerConfig(regime_aware_thresholds=True))
        assert refiner.get_regime_adjusted_threshold(70, "UNKNOWN") == 70

    def test_empty_regime_returns_base(self) -> None:
        refiner = SignalRefiner(SignalRefinerConfig(regime_aware_thresholds=True))
        assert refiner.get_regime_adjusted_threshold(70, "") == 70


# ── Factory ───────────────────────────────────────────────────────────────────

class TestFactory:
    def test_creates_from_dict(self) -> None:
        refiner = create_signal_refiner({
            "VOLATILITY_CONFIRMATION_ENABLED": False,
            "REGIME_AWARE_THRESHOLDS_ENABLED": False,
        })
        assert isinstance(refiner, SignalRefiner)
        assert refiner.config.enabled is False
        assert refiner.config.regime_aware_thresholds is False

    def test_defaults_for_empty(self) -> None:
        refiner = create_signal_refiner({})
        assert refiner.config.enabled is True
        assert refiner.config.adx_confirm_min == 20.0
