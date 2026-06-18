"""Tests for SignalRefiner - multi-indicator confirmation and false signal filtering."""

from __future__ import annotations


from core.signal_refiner import (
    SignalRefiner,
    SignalRefinerConfig,
    create_signal_refiner,
)


class TestSignalRefinerConfig:
    """SignalRefinerConfig defaults."""

    def test_default_config(self):
        cfg = SignalRefinerConfig()
        assert cfg.enabled is True
        assert cfg.rsi_confirm_threshold == 45.0
        assert cfg.macd_confirm_required is False
        assert cfg.adx_confirm_min == 20.0
        assert cfg.iv_block_threshold == 28.0
        assert cfg.regime_aware_thresholds is True
        assert cfg.threshold_trending_adjust == -2
        assert cfg.threshold_sideways_adjust == 2
        assert cfg.threshold_range_adjust == 3
        assert cfg.false_signal_filter is True
        assert cfg.false_signal_min_score_block == 75
        assert cfg.false_signal_iv_threshold == 26.0


class TestSignalRefiner:
    """SignalRefiner - should_block_signal behavior."""

    def setup_method(self):
        self.refiner = SignalRefiner(SignalRefinerConfig())

    def test_disabled_never_blocks(self):
        refiner = SignalRefiner(SignalRefinerConfig(enabled=False))
        blocked, reason = refiner.should_block_signal(
            score=100, regime="TRENDING", iv_rank=50.0, rsi=55.0
        )
        assert not blocked
        assert reason == ""

    def test_false_signal_blocks_high_score_high_iv_original(self):
        blocked, reason = self.refiner.should_block_signal(
            score=80, regime="TRENDING", iv_rank=30.0
        )
        assert blocked
        assert "High score" in reason

    def test_false_signal_blocks_high_score_high_iv(self):
        # score >= 75 and iv_rank >= 26 -> false signal filter
        blocked, reason = self.refiner.should_block_signal(
            score=80, regime="TRENDING", iv_rank=30.0
        )
        assert blocked
        assert "High score" in reason

    def test_low_score_not_blocked_by_false_signal(self):
        # score < 75 does not trigger false_signal filter
        blocked, reason = self.refiner.should_block_signal(
            score=50, regime="TRENDING", iv_rank=30.0
        )
        # RSI is None -> skip RSI check. ADX is None -> skip. VIX is None -> skip.
        assert not blocked
        assert reason == ""

    def test_rsi_neutral_blocked(self):
        # RSI close to 50 (abs(52-50)=2 < 45) -> blocked
        blocked, reason = self.refiner.should_block_signal(
            score=50, regime="TRENDING", iv_rank=10.0, rsi=52.0
        )
        assert blocked
        assert "RSI" in reason

    def test_rsi_extreme_passes(self):
        # RSI=5: abs(5-50)=45 is NOT < 45 -> RSI check passes
        blocked, reason = self.refiner.should_block_signal(
            score=50, regime="TRENDING", iv_rank=10.0, rsi=5.0, macd="BULLISH",
            adx=30.0
        )
        assert not blocked
        assert reason == ""

    def test_macd_required_blocks_no_confirmation(self):
        cfg = SignalRefinerConfig(macd_confirm_required=True)
        refiner = SignalRefiner(cfg)
        blocked, reason = refiner.should_block_signal(
            score=50, regime="TRENDING", iv_rank=10.0, rsi=5.0, macd="NEUTRAL",
        )
        assert blocked
        assert "MACD" in reason

    def test_macd_bullish_passes(self):
        cfg = SignalRefinerConfig(macd_confirm_required=True)
        refiner = SignalRefiner(cfg)
        blocked, reason = refiner.should_block_signal(
            score=50, regime="TRENDING", iv_rank=10.0, rsi=5.0, macd="BULLISH",
            adx=30.0
        )
        assert not blocked

    def test_adx_below_threshold_blocks(self):
        blocked, reason = self.refiner.should_block_signal(
            score=50, regime="TRENDING", iv_rank=10.0, rsi=5.0, macd="BULLISH",
            adx=15.0
        )
        assert blocked
        assert "ADX" in reason

    def test_adx_above_threshold_passes(self):
        blocked, reason = self.refiner.should_block_signal(
            score=50, regime="TRENDING", iv_rank=10.0, rsi=5.0, macd="BULLISH",
            adx=25.0
        )
        assert not blocked

    def test_vix_above_block_threshold(self):
        blocked, reason = self.refiner.should_block_signal(
            score=50, regime="TRENDING", iv_rank=10.0, rsi=5.0, macd="BULLISH",
            adx=25.0, vix=30.0
        )
        assert blocked
        assert "VIX" in reason

    def test_vix_below_threshold_passes(self):
        blocked, reason = self.refiner.should_block_signal(
            score=50, regime="TRENDING", iv_rank=10.0, rsi=5.0, macd="BULLISH",
            adx=25.0, vix=20.0
        )
        assert not blocked

    def test_regime_adjusted_threshold_trending(self):
        adjusted = self.refiner.get_regime_adjusted_threshold(70, "TRENDING")
        assert adjusted == 68  # 70 + (-2)

    def test_regime_adjusted_threshold_sideways(self):
        adjusted = self.refiner.get_regime_adjusted_threshold(70, "SIDEWAYS")
        assert adjusted == 72  # 70 + 2

    def test_regime_adjusted_threshold_range(self):
        adjusted = self.refiner.get_regime_adjusted_threshold(70, "RANGE")
        assert adjusted == 73  # 70 + 3

    def test_regime_disabled_returns_base(self):
        cfg = SignalRefinerConfig(regime_aware_thresholds=False)
        refiner = SignalRefiner(cfg)
        adjusted = refiner.get_regime_adjusted_threshold(70, "TRENDING")
        assert adjusted == 70

    def test_unknown_regime_returns_base(self):
        adjusted = self.refiner.get_regime_adjusted_threshold(70, "UNKNOWN")
        assert adjusted == 70


class TestCreateSignalRefiner:
    """Factory function create_signal_refiner."""

    def test_create_with_defaults(self):
        refiner = create_signal_refiner({})
        assert isinstance(refiner, SignalRefiner)
        assert refiner.config.enabled is True

    def test_create_with_custom_config(self):
        refiner = create_signal_refiner({
            "VOLATILITY_CONFIRMATION_ENABLED": False,
            "VOLATILITY_RSI_CONFIRM_THRESHOLD": 35.0,
            "VOLATILITY_MACD_CONFIRM_REQUIRED": True,
            "VOLATILITY_IV_BLOCK_THRESHOLD": 32.0,
        })
        assert refiner.config.enabled is False
        assert refiner.config.rsi_confirm_threshold == 35.0
        assert refiner.config.macd_confirm_required is True
        assert refiner.config.iv_block_threshold == 32.0
