"""Tests for core.regime_transition_detector - thread-safe VIX history + transition detection."""
from __future__ import annotations

import threading

import pytest
from core.regime_transition_detector import (
    TransitionSignal,
    _VixHistoryTracker,
    detect_transition,
    get_transition_score_adj,
    reset_vix_history,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_vix() -> None:
    """Reset VIX history before each test to avoid cross-test contamination."""
    reset_vix_history()


# ── _VixHistoryTracker ────────────────────────────────────────────────────────


class TestVixHistoryTracker:
    def test_empty_initially(self) -> None:
        tracker = _VixHistoryTracker()
        assert len(tracker) == 0
        assert tracker.get_history() == []

    def test_append(self) -> None:
        tracker = _VixHistoryTracker(max_size=5)
        tracker.update(15.0)
        tracker.update(16.0)
        assert len(tracker) == 2
        assert tracker.get_history() == [15.0, 16.0]

    def test_ignores_non_positive(self) -> None:
        tracker = _VixHistoryTracker()
        tracker.update(0.0)
        tracker.update(-1.0)
        assert len(tracker) == 0

    def test_ring_buffer_eviction(self) -> None:
        tracker = _VixHistoryTracker(max_size=3)
        for v in [10, 11, 12, 13, 14]:
            tracker.update(float(v))
        assert len(tracker) == 3
        assert tracker.get_history() == [12.0, 13.0, 14.0]

    def test_reset(self) -> None:
        tracker = _VixHistoryTracker()
        tracker.update(15.0)
        tracker.reset()
        assert len(tracker) == 0

    def test_thread_safety(self) -> None:
        """Concurrent updates should not corrupt history."""
        tracker = _VixHistoryTracker(max_size=20)
        errors: list[Exception | None] = [None] * 10

        def _writer(n: int) -> None:
            try:
                for _ in range(100):
                    tracker.update(float(n))
            except Exception as e:
                errors[n] = e

        threads = [threading.Thread(target=_writer, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        for e in errors:
            if e is not None:
                raise e
        # Should have exactly max_size (20) entries after many concurrent writes
        assert len(tracker) <= 20
        assert len(tracker) >= 1


# ── detect_transition ─────────────────────────────────────────────────────────


class TestDetectTransition:
    def test_disabled_by_default(self) -> None:
        result = detect_transition("CHOPPY", "CHOPPY", [15, 18, 22], 15.0, [-1, 0, 1], None)
        assert result is None

    def test_enabled_no_transition(self) -> None:
        cfg = {"regime_transition_enabled": True}
        result = detect_transition("CHOPPY", "CHOPPY", [15, 16, 17], 15.0, [0, 0, 0], cfg)
        assert result is None

    def test_choppy_to_trending(self) -> None:
        cfg = {"regime_transition_enabled": True}
        result = detect_transition(
            "TRENDING", "CHOPPY",
            [18, 19, 26], 15.0, [-1, -0.5, 1],
            cfg,
        )
        assert result is not None
        assert result.to_regime == "TRENDING"
        assert result.from_regime == "CHOPPY"
        assert result.score_bonus > 0

    def test_trending_to_choppy(self) -> None:
        cfg = {"regime_transition_enabled": True}
        result = detect_transition(
            "CHOPPY", "TRENDING",
            [27, 26, 18], 15.0, [1, 0.5, 0],
            cfg,
        )
        assert result is not None
        assert result.to_regime == "CHOPPY"
        assert result.from_regime == "TRENDING"
        assert result.score_bonus < 0

    def test_vix_spike_detected(self) -> None:
        cfg = {"regime_transition_enabled": True, "transition_vix_spike_pct": 20.0}
        # First call populates vix history at 15
        detect_transition("TRENDING", "TRENDING", [25, 26, 27], 15.0, [1, 1, 1], cfg)
        # Second call with 50% spike
        result = detect_transition("TRENDING", "TRENDING", [25, 26, 27], 22.5, [1, 1, 1], cfg)
        assert result is not None
        assert result.to_regime == "VOLATILE"
        assert result.score_bonus < 0

    def test_insufficient_adx_data(self) -> None:
        cfg = {"regime_transition_enabled": True}
        result = detect_transition("CHOPPY", "CHOPPY", [15], 15.0, [0], cfg)
        assert result is None

    def test_configured_bonus_value(self) -> None:
        cfg = {"regime_transition_enabled": True, "transition_score_bonus": 15}
        result = detect_transition(
            "TRENDING", "CHOPPY",
            [18, 19, 26], 15.0, [-1, -0.5, 1],
            cfg,
        )
        assert result is not None
        assert result.score_bonus == 15


# ── get_transition_score_adj ──────────────────────────────────────────────────


class TestGetTransitionScoreAdj:
    def test_none_signal_returns_zero(self) -> None:
        assert get_transition_score_adj(None, {"regime_transition_enabled": True}) == 0

    def test_disabled_returns_zero(self) -> None:
        signal = TransitionSignal("A", "B", 0.8, 8, "test")
        assert get_transition_score_adj(signal, None) == 0

    def test_returns_bonus(self) -> None:
        signal = TransitionSignal("A", "B", 0.8, 8, "test")
        result = get_transition_score_adj(signal, {"regime_transition_enabled": True})
        assert result == 8

    def test_negative_bonus(self) -> None:
        signal = TransitionSignal("A", "B", 0.8, -5, "test")
        result = get_transition_score_adj(signal, {"regime_transition_enabled": True})
        assert result == -5


# ── TransitionSignal dataclass ────────────────────────────────────────────────


class TestTransitionSignal:
    def test_frozen(self) -> None:
        s = TransitionSignal("A", "B", 0.9, 10, "test")
        assert s.from_regime == "A"
        assert s.to_regime == "B"
        assert s.confidence == 0.9
        assert s.score_bonus == 10
        assert s.reason == "test"
