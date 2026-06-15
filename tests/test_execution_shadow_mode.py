"""Tests for core/execution/shadow_mode.py — Shadow Mode Engine."""

from __future__ import annotations

import itertools
from unittest.mock import patch

import pytest

from core.execution.shadow_mode import (
    ShadowComparison,
    ShadowModeEngine,
    ShadowSignal,
    get_shadow_engine,
)
from core.time_provider import time_provider


_ts_counter = itertools.count(1000)


def _mock_get_ts():
    return next(_ts_counter)


class TestShadowSignal:
    """ShadowSignal dataclass coverage."""

    def test_defaults(self):
        s = ShadowSignal(
            signal_id="SHADOW-001",
            timestamp="2026-06-11T10:00:00",
            strategy_name="test_strat",
            symbol="NIFTY",
            direction="CALL",
            quantity=50,
            price=23500.0,
            score=85.0,
            reason="Strong signal",
        )
        assert s.metadata == {}


class TestShadowComparison:
    """ShadowComparison dataclass coverage."""

    def test_values(self):
        shadow = ShadowSignal(
            signal_id="S1", timestamp="t1", strategy_name="s", symbol="N",
            direction="CALL", quantity=50, price=23500.0, score=85, reason="r",
        )
        comp = ShadowComparison(
            comparison_id="COMP-001",
            timestamp="t2",
            shadow_signal=shadow,
            real_signal=None,
            match=False,
            divergence_reason="No real signal",
        )
        assert comp.match is False


class TestShadowModeEngine:
    """ShadowModeEngine coverage."""

    @pytest.fixture
    def engine(self):
        with patch.object(time_provider, 'get_ts', create=True, side_effect=_mock_get_ts):
            yield ShadowModeEngine()

    def test_initially_disabled(self, engine):
        assert engine.is_enabled() is False
        assert engine.should_execute() is True

    def test_enable(self, engine):
        engine.enable()
        assert engine.is_enabled() is True
        assert engine.should_execute() is False

    def test_disable(self, engine):
        engine.enable()
        engine.disable()
        assert engine.is_enabled() is False
        assert engine.should_execute() is True

    def test_record_signal_when_disabled(self, engine):
        signal = engine.record_signal(
            "strat1", "NIFTY", "CALL", 50, 23500.0, 85.0, "Strong",
        )
        assert signal is None

    def test_record_signal_when_enabled(self, engine):
        engine.enable()
        signal = engine.record_signal(
            "strat1", "NIFTY", "CALL", 50, 23500.0, 85.0, "Strong",
        )
        assert signal is not None
        assert signal.symbol == "NIFTY"
        assert signal.direction == "CALL"
        assert signal.score == 85.0

    def test_record_signal_with_metadata(self, engine):
        engine.enable()
        signal = engine.record_signal(
            "strat1", "NIFTY", "CALL", 50, 23500.0, 85.0, "Strong",
            metadata={"iv_rank": 75.0, "confidence": "high"},
        )
        assert signal.metadata["iv_rank"] == 75.0

    def test_compare_with_real_match(self, engine):
        engine.enable()
        shadow = engine.record_signal(
            "s1", "NIFTY", "CALL", 50, 23500.0, 85.0, "Strong",
        )
        real = ShadowSignal(
            signal_id="REAL-001", timestamp="t1", strategy_name="s1",
            symbol="NIFTY", direction="CALL", quantity=50, price=23500.0,
            score=85, reason="Strong",
        )
        comparison = engine.compare_with_real(shadow, real)
        assert comparison.match is True
        assert comparison.divergence_reason == ""

    def test_compare_with_real_direction_mismatch(self, engine):
        engine.enable()
        shadow = engine.record_signal(
            "s1", "NIFTY", "CALL", 50, 23500.0, 85.0, "Strong",
        )
        real = ShadowSignal(
            signal_id="REAL-001", timestamp="t1", strategy_name="s1",
            symbol="NIFTY", direction="PUT", quantity=50, price=23500.0,
            score=85, reason="Strong",
        )
        comparison = engine.compare_with_real(shadow, real)
        assert "Direction mismatch" in comparison.divergence_reason

    def test_compare_with_real_price_divergence(self, engine):
        engine.enable()
        shadow = engine.record_signal(
            "s1", "NIFTY", "CALL", 50, 23500.0, 85.0, "Strong",
        )
        real = ShadowSignal(
            signal_id="REAL-001", timestamp="t1", strategy_name="s1",
            symbol="NIFTY", direction="CALL", quantity=50, price=24000.0,
            score=85, reason="Strong",
        )
        comparison = engine.compare_with_real(shadow, real)
        assert "Price divergence" in comparison.divergence_reason

    def test_compare_with_real_quantity_mismatch(self, engine):
        engine.enable()
        shadow = engine.record_signal(
            "s1", "NIFTY", "CALL", 50, 23500.0, 85.0, "Strong",
        )
        real = ShadowSignal(
            signal_id="REAL-001", timestamp="t1", strategy_name="s1",
            symbol="NIFTY", direction="CALL", quantity=75, price=23500.0,
            score=85, reason="Strong",
        )
        comparison = engine.compare_with_real(shadow, real)
        assert "Quantity mismatch" in comparison.divergence_reason

    def test_compare_with_real_no_real_signal(self, engine):
        engine.enable()
        shadow = engine.record_signal(
            "s1", "NIFTY", "CALL", 50, 23500.0, 85.0, "Strong",
        )
        comparison = engine.compare_with_real(shadow)
        assert comparison.match is False
        assert "No real signal" in comparison.divergence_reason

    def test_get_shadow_signals_when_disabled(self, engine):
        signals = engine.get_shadow_signals()
        assert signals == []

    def test_get_shadow_signals_when_enabled(self, engine):
        engine.enable()
        engine.record_signal(
            "s1", "NIFTY", "CALL", 50, 23500.0, 85.0, "Strong",
        )
        engine.record_signal(
            "s1", "BANKNIFTY", "PUT", 30, 50000.0, 75.0, "Moderate",
        )
        signals = engine.get_shadow_signals()
        assert len(signals) == 2

    def test_get_comparisons(self, engine):
        engine.enable()
        shadow = engine.record_signal(
            "s1", "NIFTY", "CALL", 50, 23500.0, 85.0, "Strong",
        )
        engine.compare_with_real(shadow)
        comparisons = engine.get_comparisons()
        assert len(comparisons) == 1

    def test_get_stats(self, engine):
        engine.enable()
        stats = engine.get_stats()
        assert stats["enabled"] is True
        assert stats["shadow_signals"] == 0

    def test_get_stats_after_signals(self, engine):
        engine.enable()
        engine.record_signal(
            "s1", "NIFTY", "CALL", 50, 23500.0, 85.0, "Strong",
        )
        shadow = engine.record_signal(
            "s1", "NIFTY", "PUT", 50, 23500.0, 75.0, "Moderate",
        )
        engine.compare_with_real(shadow)
        stats = engine.get_stats()
        assert stats["shadow_signals"] == 2
        assert stats["comparisons"] == 1
        assert stats["divergences"] == 1

    def test_divergence_rate(self, engine):
        engine.enable()
        stats = engine.get_stats()
        assert stats["divergence_rate"] == 0.0

    def test_clear_history(self, engine):
        engine.enable()
        engine.record_signal(
            "s1", "NIFTY", "CALL", 50, 23500.0, 85.0, "Strong",
        )
        engine.clear_history()
        assert engine.get_shadow_signals() == []

    def test_get_signal_history(self, engine):
        engine.enable()
        engine.record_signal(
            "s1", "NIFTY", "CALL", 50, 23500.0, 85.0, "Strong",
        )
        history = engine.get_signal_history()
        assert isinstance(history, list)


class TestGetShadowEngine:
    """Singleton get_shadow_engine coverage."""

    def test_get_instance(self):
        engine = get_shadow_engine()
        assert isinstance(engine, ShadowModeEngine)

    def test_singleton_behavior(self):
        e1 = get_shadow_engine()
        e2 = get_shadow_engine()
        assert e1 is e2
