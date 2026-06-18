"""Tests for core/signal_independence.py - pillar-based signal validation."""

from __future__ import annotations

from core.signal_independence import (
    SignalIndependenceValidator,
    create_signal_validator,
)

# ── Initial state ─────────────────────────────────────────────────────────────

class TestInitialState:
    def test_no_pillars_initially(self) -> None:
        v = SignalIndependenceValidator()
        valid, reason, count = v.validate_independence()
        assert valid is False
        assert count == 0

    def test_summary_empty_initially(self) -> None:
        v = SignalIndependenceValidator()
        s = v.get_summary()
        assert s["num_pillars"] == 0
        assert s["valid"] is False

    def test_consensus_none_initially(self) -> None:
        v = SignalIndependenceValidator()
        assert v.get_consensus_direction() is None


# ── Single pillar ─────────────────────────────────────────────────────────────

class TestSinglePillar:
    def test_one_pillar_insufficient(self) -> None:
        v = SignalIndependenceValidator()
        v.set_price_momentum_signal(rsi=60.0, macd="BULLISH", adx=25.0)
        valid, _, count = v.validate_independence()
        assert valid is False
        assert count == 1


# ── Two pillars agreement ─────────────────────────────────────────────────────

class TestTwoPillarAgreement:
    def test_price_and_options_bullish(self) -> None:
        v = SignalIndependenceValidator()
        v.set_price_momentum_signal(rsi=60.0, macd="BULLISH", adx=25.0)
        v.set_options_market_signal(iv_rank=40.0, oi_change_pct=5.0, pcr=0.8)
        valid, reason, count = v.validate_independence()
        assert valid is True
        assert count == 2
        assert "Bullish" in reason

    def test_options_and_flow_bearish(self) -> None:
        v = SignalIndependenceValidator()
        v.set_options_market_signal(iv_rank=50.0, oi_change_pct=-10.0, pcr=1.5)
        v.set_institutional_flow_signal(fii_net=-5000000.0, dii_net=-2000000.0, gex=-100.0)
        valid, reason, _ = v.validate_independence()
        assert valid is True
        assert "Bearish" in reason

    def test_structural_and_price_mixed(self) -> None:
        v = SignalIndependenceValidator()
        v.set_price_momentum_signal(rsi=40.0, macd="BEARISH", adx=30.0)
        v.set_structural_signal(session_score=70.0, time_context="morning", event_clear=True)
        valid, _, _ = v.validate_independence()
        assert valid is False  # Bullish vs Bearish = no consensus


# ── Three pillars ─────────────────────────────────────────────────────────────

class TestThreePillars:
    def test_three_pillars_all_bullish(self) -> None:
        v = SignalIndependenceValidator()
        v.set_price_momentum_signal(rsi=65.0, macd="BULLISH", adx=30.0)
        v.set_options_market_signal(iv_rank=40.0, oi_change_pct=5.0, pcr=0.8)
        v.set_institutional_flow_signal(fii_net=10000000.0, dii_net=5000000.0, gex=50.0)
        valid, _, count = v.validate_independence()
        assert valid is True
        assert count == 3

    def test_two_bullish_one_bearish_allows(self) -> None:
        v = SignalIndependenceValidator()
        v.set_price_momentum_signal(rsi=60.0, macd="BULLISH", adx=25.0)
        v.set_options_market_signal(iv_rank=40.0, oi_change_pct=5.0, pcr=0.8)
        v.set_institutional_flow_signal(fii_net=-5000000.0, dii_net=-2000000.0, gex=-50.0)
        valid, _, _ = v.validate_independence()
        assert valid is True  # 2 bullish, 1 bearish → consensus


# ── Pillar directions ─────────────────────────────────────────────────────────

class TestDirectionLogic:
    def test_rsi_over_55_bullish(self) -> None:
        v = SignalIndependenceValidator()
        v.set_price_momentum_signal(rsi=60.0, macd="BULLISH", adx=25.0)
        v.set_options_market_signal(iv_rank=30.0, oi_change_pct=0.0, pcr=0.9)
        _, _, count = v.validate_independence()
        assert count == 2

    def test_rsi_below_45_bearish(self) -> None:
        v = SignalIndependenceValidator()
        v.set_price_momentum_signal(rsi=40.0, macd="BEARISH", adx=25.0)
        assert v._pillars["price_momentum"].direction == "BEARISH"

    def test_rsi_neutral_uses_macd(self) -> None:
        v = SignalIndependenceValidator()
        v.set_price_momentum_signal(rsi=50.0, macd="BULLISH", adx=25.0)
        assert v._pillars["price_momentum"].direction == "BULLISH"

    def test_rsi_neutral_macd_neutral(self) -> None:
        v = SignalIndependenceValidator()
        v.set_price_momentum_signal(rsi=50.0, macd="NEUTRAL", adx=25.0)
        assert v._pillars["price_momentum"].direction == "NEUTRAL"

    def test_pcr_below_1_bullish(self) -> None:
        v = SignalIndependenceValidator()
        v.set_options_market_signal(iv_rank=30.0, oi_change_pct=0.0, pcr=0.8)
        assert v._pillars["options_market"].direction == "BULLISH"

    def test_pcr_above_1_point_2_bearish(self) -> None:
        v = SignalIndependenceValidator()
        v.set_options_market_signal(iv_rank=30.0, oi_change_pct=0.0, pcr=1.5)
        assert v._pillars["options_market"].direction == "BEARISH"

    def test_pcr_between_neutral(self) -> None:
        v = SignalIndependenceValidator()
        v.set_options_market_signal(iv_rank=30.0, oi_change_pct=0.0, pcr=1.1)
        assert v._pillars["options_market"].direction == "NEUTRAL"

    def test_institutional_flow_positive_bullish(self) -> None:
        v = SignalIndependenceValidator()
        v.set_institutional_flow_signal(fii_net=5000000.0, dii_net=3000000.0, gex=100.0)
        assert v._pillars["institutional_flow"].direction == "BULLISH"

    def test_institutional_flow_negative_bearish(self) -> None:
        v = SignalIndependenceValidator()
        v.set_institutional_flow_signal(fii_net=-5000000.0, dii_net=-3000000.0, gex=-100.0)
        assert v._pillars["institutional_flow"].direction == "BEARISH"

    def test_structural_above_60_bullish(self) -> None:
        v = SignalIndependenceValidator()
        v.set_structural_signal(session_score=70.0, time_context="morning", event_clear=True)
        assert v._pillars["structural"].direction == "BULLISH"

    def test_structural_below_40_bearish(self) -> None:
        v = SignalIndependenceValidator()
        v.set_structural_signal(session_score=30.0, time_context="afternoon", event_clear=False)
        assert v._pillars["structural"].direction == "BEARISH"

    def test_structural_neutral(self) -> None:
        v = SignalIndependenceValidator()
        v.set_structural_signal(session_score=50.0, time_context="morning", event_clear=True)
        assert v._pillars["structural"].direction == "NEUTRAL"


# ── Getters ───────────────────────────────────────────────────────────────────

class TestGetters:
    def test_get_aligned_pillars(self) -> None:
        v = SignalIndependenceValidator()
        v.set_price_momentum_signal(rsi=60.0, macd="BULLISH", adx=25.0)
        v.set_options_market_signal(iv_rank=40.0, oi_change_pct=5.0, pcr=0.8)
        aligned = v.get_aligned_pillars()
        assert len(aligned) == 2

    def test_get_aligned_no_consensus(self) -> None:
        v = SignalIndependenceValidator()
        v.set_price_momentum_signal(rsi=60.0, macd="BULLISH", adx=25.0)
        v.set_structural_signal(session_score=30.0, time_context="afternoon", event_clear=True)
        aligned = v.get_aligned_pillars()
        assert aligned == []

    def test_consensus_direction(self) -> None:
        v = SignalIndependenceValidator()
        v.set_price_momentum_signal(rsi=60.0, macd="BULLISH", adx=25.0)
        v.set_options_market_signal(iv_rank=40.0, oi_change_pct=5.0, pcr=0.8)
        assert v.get_consensus_direction() == "BULLISH"

    def test_get_summary(self) -> None:
        v = SignalIndependenceValidator()
        v.set_price_momentum_signal(rsi=60.0, macd="BULLISH", adx=25.0)
        s = v.get_summary()
        assert "price_momentum" in s["pillars"]
        assert s["num_pillars"] == 1
        assert s["valid"] is False


# ── Reset ─────────────────────────────────────────────────────────────────────

class TestReset:
    def test_reset_clears_pillars(self) -> None:
        v = SignalIndependenceValidator()
        v.set_price_momentum_signal(rsi=60.0, macd="BULLISH", adx=25.0)
        v.reset()
        assert v.get_summary()["num_pillars"] == 0

    def test_reset_allows_new_eval(self) -> None:
        v = SignalIndependenceValidator()
        v.set_price_momentum_signal(rsi=60.0, macd="BULLISH", adx=25.0)
        v.reset()
        v.set_options_market_signal(iv_rank=40.0, oi_change_pct=5.0, pcr=0.8)
        valid, _, count = v.validate_independence()
        assert valid is False  # only 1 pillar after reset
        assert count == 1


# ── Factory ───────────────────────────────────────────────────────────────────

class TestFactory:
    def test_create_validator(self) -> None:
        v = create_signal_validator()
        assert isinstance(v, SignalIndependenceValidator)
        assert v.get_summary()["num_pillars"] == 0
