"""Tests for core.strategy_engine - DEPRECATED strategy engine shim."""

from __future__ import annotations

import warnings


from core.strategy_engine import (
    StrategyEngine,
    StrategySnapshot,
    SignalDict,
)


class TestStrategySnapshot:
    """Tests for StrategySnapshot dataclass."""

    def test_defaults(self) -> None:
        snap = StrategySnapshot(name="NIFTY", score=75.0, threshold=60.0, direction="CALL", regime="NEUTRAL", strength="STRONG")
        assert snap.name == "NIFTY"
        assert snap.score == 75.0
        assert snap.direction == "CALL"
        assert snap.regime == "NEUTRAL"


class TestStrategyEngine:
    """Tests for StrategyEngine (DEPRECATED shim)."""

    def setup_method(self) -> None:
        # Suppress deprecation warning during tests
        warnings.filterwarnings("ignore", message="core.strategy_engine is DEPRECATED")
        self.engine = StrategyEngine()

    def test_init_with_no_fns(self) -> None:
        assert self.engine._generate_signal_fn is None

    def test_generate_signal_with_no_fn_returns_none(self) -> None:
        result = self.engine.generate_signal("NIFTY", {})
        assert result is None

    def test_generate_signal_with_fn(self) -> None:
        def mock_fn(name: str, frames: dict, vix: float = 0.0) -> SignalDict:
            return {"name": name, "score": 75, "direction": "CALL"}
        engine = StrategyEngine(generate_signal_fn=mock_fn)
        result = engine.generate_signal("NIFTY", {})
        assert result is not None
        assert result["name"] == "NIFTY"
        assert result["score"] == 75

    def test_get_top_signals_with_no_fn(self) -> None:
        result = self.engine.get_top_signals(5)
        assert result == []

    def test_get_top_signals_with_fn(self) -> None:
        def mock_fn(limit: int) -> list[tuple[str, SignalDict]]:
            return [("NIFTY", {"score": 85})]
        engine = StrategyEngine(top_signals_fn=mock_fn)
        result = engine.get_top_signals(5)
        assert len(result) == 1
        assert result[0][0] == "NIFTY"

    def test_detect_regime_with_no_fn_returns_unknown(self) -> None:
        result = self.engine.detect_regime()
        assert result == "UNKNOWN"

    def test_detect_regime_with_fn(self) -> None:
        def mock_fn(*args, **kwargs) -> str:
            return "TRENDING"
        engine = StrategyEngine(detect_regime_fn=mock_fn)
        result = engine.detect_regime()
        assert result == "TRENDING"

    def test_detect_regime_and_adx_with_no_fn(self) -> None:
        regime, adx = self.engine.detect_regime_and_adx()
        assert regime == "UNKNOWN"
        assert adx == 0.0

    def test_detect_regime_and_adx_with_fn(self) -> None:
        def mock_fn(*args, **kwargs) -> tuple[str, float]:
            return ("TRENDING", 25.0)
        engine = StrategyEngine(detect_regime_and_adx_fn=mock_fn)
        regime, adx = engine.detect_regime_and_adx()
        assert regime == "TRENDING"
        assert adx == 25.0

    def test_snapshot_empty_signal(self) -> None:
        snap = self.engine.snapshot("NIFTY", None)
        assert snap.name == "NIFTY"
        assert snap.score == 0.0

    def test_snapshot_with_signal(self) -> None:
        snap = self.engine.snapshot("NIFTY", {
            "score": 85, "threshold": 60, "direction": "CALL",
            "regime": "TRENDING", "strength": "STRONG",
        })
        assert snap.score == 85.0
        assert snap.strength == "STRONG"

    def test_get_status_no_fns(self) -> None:
        status = self.engine.get_status()
        assert status["has_generate_signal_fn"] is False

    def test_get_status_with_fns(self) -> None:
        engine = StrategyEngine(generate_signal_fn=lambda n, f, v=0.0: None)
        status = engine.get_status()
        assert status["has_generate_signal_fn"] is True
