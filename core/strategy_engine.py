"""
[DEPRECATED] Strategy Engine — use core.strategy.orchestrator instead.

This module is a backward-compatibility wrapper. The ``StrategyEngine`` class
is replaced by ``StrategyOrchestrator`` (``core.strategy.orchestrator``).

.. deprecated:: 2.54.0
    Import from ``core.strategy.orchestrator`` (StrategyOrchestrator)
    or ``core.services.use_cases.trading_orchestrator`` (TradingOrchestrator)
    instead.
"""
from __future__ import annotations

import warnings
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

warnings.warn(
    "core.strategy_engine is DEPRECATED. "
    "Use core.strategy.orchestrator (StrategyOrchestrator) instead.",
    DeprecationWarning,
    stacklevel=2,
)

SignalDict = dict[str, Any]


@dataclass
class StrategySnapshot:
    name: str = ""
    score: float = 0.0
    threshold: float = 0.0
    direction: str = ""
    regime: str = ""
    strength: str = ""
    note: str = ""


class StrategyEngine:
    def __init__(
        self,
        *,
        generate_signal_fn: Callable[[str, dict, float], SignalDict | None] | None = None,
        top_signals_fn: Callable[[int], list[tuple[str, SignalDict]]] | None = None,
        detect_regime_fn: Callable[..., str] | None = None,
        detect_regime_and_adx_fn: Callable[..., tuple[str, float]] | None = None,
    ):
        self._generate_signal_fn = generate_signal_fn
        self._top_signals_fn = top_signals_fn
        self._detect_regime_fn = detect_regime_fn
        self._detect_regime_and_adx_fn = detect_regime_and_adx_fn

    def generate_signal(self, name: str, frames: dict, vix: float = 0.0) -> SignalDict | None:
        if self._generate_signal_fn is None:
            return None
        return self._generate_signal_fn(name, frames, vix)

    def get_top_signals(self, limit: int) -> list[tuple[str, SignalDict]]:
        if self._top_signals_fn is None:
            return []
        return self._top_signals_fn(limit)

    def detect_regime(self, *args, **kwargs) -> str:
        if self._detect_regime_fn is None:
            return "UNKNOWN"
        return self._detect_regime_fn(*args, **kwargs)

    def detect_regime_and_adx(self, *args, **kwargs) -> tuple[str, float]:
        if self._detect_regime_and_adx_fn is None:
            return "UNKNOWN", 0.0
        return self._detect_regime_and_adx_fn(*args, **kwargs)

    def snapshot(self, name: str, sig: SignalDict | None) -> StrategySnapshot:
        if sig is None:
            return StrategySnapshot(name=name)
        return StrategySnapshot(
            name=name,
            score=float(sig.get("score", 0)),
            threshold=float(sig.get("threshold", 60)),
            direction=str(sig.get("direction", "")),
            regime=str(sig.get("regime", "NEUTRAL")),
            strength=str(sig.get("strength", "NONE")),
        )

    def get_status(self) -> dict[str, Any]:
        return {
            "has_generate_signal_fn": self._generate_signal_fn is not None,
            "has_top_signals_fn": self._top_signals_fn is not None,
            "has_detect_regime_fn": self._detect_regime_fn is not None,
            "has_detect_regime_and_adx_fn": self._detect_regime_and_adx_fn is not None,
        }


__all__ = [
    "SignalDict",
    "StrategyEngine",
    "StrategySnapshot",
]
