"""Tests for core/regime_transition_detector.py - Regime Transition Detection.

Covers:
- TransitionSignal frozen dataclass
- _VixHistoryTracker thread-safe ring buffer
- update_vix_history and reset_vix_history
- detect_transition() for VIX spike, CHOPPY->TRENDING, TRENDING->CHOPPY
- detect_transition() returns None for no detection
- get_transition_score_adj()
"""
from __future__ import annotations

import threading

import pytest

from core.regime_transition_detector import (
    TransitionSignal,
    _VixHistoryTracker,
    _vix_tracker,
    detect_transition,
    get_transition_score_adj,
    reset_vix_history,
)


class TestTransitionSignal:
    """TransitionSignal frozen dataclass."""

    def test_fields(self):
        ts = TransitionSignal(
            from_regime="CHOPPY", to_regime="TRENDING",
            confidence=0.8, score_bonus=8, reason="ADX rising + MACD cross",
        )
        assert ts.from_regime == "CHOPPY"
        assert ts.to_regime == "TRENDING"
        assert ts.confidence == 0.8
        assert ts.score_bonus == 8
        assert ts.reason == "ADX rising + MACD cross"

    def test_frozen(self):
        ts = TransitionSignal(from_regime="A", to_regime="B", confidence=0.5, score_bonus=0, reason="test")
        with pytest.raises((AttributeError, TypeError)):
            ts.from_regime = "C"


class TestVixHistoryTracker:
    """_VixHistoryTracker thread-safe ring buffer."""

    def test_empty_initially(self):
        tracker = _VixHistoryTracker(max_size=10)
        assert tracker.get_history() == []
        assert len(tracker) == 0

    def test_update_and_get(self):
        tracker = _VixHistoryTracker(max_size=10)
        tracker.update(15.0)
        tracker.update(16.0)
        assert tracker.get_history() == [15.0, 16.0]
        assert len(tracker) == 2

    def test_reset_clears(self):
        tracker = _VixHistoryTracker(max_size=10)
        tracker.update(15.0)
        tracker.reset()
        assert tracker.get_history() == []
        assert len(tracker) == 0

    def test_ignores_non_positive(self):
        tracker = _VixHistoryTracker(max_size=10)
        tracker.update(0.0)
        tracker.update(-1.0)
        assert tracker.get_history() == []

    def test_ring_buffer_trimming(self):
        tracker = _VixHistoryTracker(max_size=3)
        for i in range(1, 6):
            tracker.update(float(i))
        assert len(tracker) == 3
        assert tracker.get_history() == [3.0, 4.0, 5.0]

    def test_thread_safety(self):
        tracker = _VixHistoryTracker(max_size=100)
        errors = []

        def writer():
            try:
                for i in range(50):
                    tracker.update(float(i))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert len(tracker) <= 100


class TestDetectTransition:
    """detect_transition() tests."""

    def _cfg(self, enabled=True):
        return {
            "regime_transition_enabled": enabled,
            "transition_score_bonus": 8,
            "transition_adx_look_bars": 3,
            "transition_vix_spike_pct": 20.0,
        }

    def test_disabled_returns_none(self):
        result = detect_transition("TRENDING", "CHOPPY", [20, 25], 15, [0, 0], {"regime_transition_enabled": False})
        assert result is None

    def test_insufficient_adx_returns_none(self):
        result = detect_transition("TRENDING", "CHOPPY", [25], 15, [0], self._cfg())
        assert result is None

    def test_vix_spike_detected(self):
        reset_vix_history()
        # Simulate VIX spike
        _vix_tracker.update(15.0)
        result = detect_transition("TRENDING", "CHOPPY", [25, 26], 20.0, [0, 0], self._cfg())
        assert result is not None
        assert result.to_regime == "VOLATILE"
        assert result.score_bonus == -8
        assert "VIX spike" in result.reason

    def test_vix_spike_edge_not_triggered(self):
        reset_vix_history()
        _vix_tracker.update(15.0)
        # VIX goes from 15 to 17.9 -> +19.3% < 20% threshold
        result = detect_transition("TRENDING", "CHOPPY", [25, 26], 17.9, [0, 0], self._cfg())
        assert result is None  # Below 20% spike threshold

    def test_choppy_to_trending(self):
        reset_vix_history()
        _vix_tracker.update(15.0)
        _vix_tracker.update(15.0)
        result = detect_transition(
            "CHOPPY", "CHOPPY", [18, 28], 15.0, [-1, 2], self._cfg(),
        )
        assert result is not None
        assert result.from_regime == "CHOPPY"
        assert result.to_regime == "TRENDING"
        assert result.score_bonus == 8
        assert "ADX" in result.reason

    def test_trending_to_choppy(self):
        reset_vix_history()
        _vix_tracker.update(15.0)
        _vix_tracker.update(15.0)
        result = detect_transition(
            "TRENDING", "TRENDING", [28, 18], 15.0, [0, 0], self._cfg(),
        )
        assert result is not None
        assert result.from_regime == "TRENDING"
        assert result.to_regime == "CHOPPY"
        assert result.score_bonus == -8
        assert "ADX" in result.reason

    def test_no_detection_returns_none(self):
        reset_vix_history()
        _vix_tracker.update(15.0)
        _vix_tracker.update(15.0)
        # No VIX spike, no ADX cross, no ADX fall
        result = detect_transition(
            "TRENDING", "TRENDING", [25, 26], 15.0, [0, 0], self._cfg(),
        )
        assert result is None


class TestGetTransitionScoreAdj:
    """get_transition_score_adj()."""

    def test_disabled_returns_zero(self):
        result = get_transition_score_adj(
            TransitionSignal("A", "B", 0.5, 5, "test"),
            {"regime_transition_enabled": False},
        )
        assert result == 0

    def test_none_signal_returns_zero(self):
        assert get_transition_score_adj(None, {"regime_transition_enabled": True}) == 0

    def test_returns_score_bonus(self):
        signal = TransitionSignal("CHOPPY", "TRENDING", 0.8, 8, "test")
        result = get_transition_score_adj(signal, {"regime_transition_enabled": True})
        assert result == 8


class TestResetVixHistory:
    """reset_vix_history()."""

    def test_resets_module_singleton(self):
        _vix_tracker.update(15.0)
        reset_vix_history()
        assert len(_vix_tracker) == 0
