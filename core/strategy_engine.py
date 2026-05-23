"""
AD-KIYU StrategyEngine — DEPRECATED.

This module is deprecated. New code should use StrategyOrchestrator from
core.strategy.orchestrator.

Preserves the original callback-based StrategyEngine API for backward
compatibility with backtest engine and existing code.

Will be removed in a future release.

Original API:
  StrategyEngine(generate_signal_fn, top_signals_fn, detect_regime_fn, ...)
  .generate_signal(name, frames, vix) -> SignalDict | None
  .get_top_signals(limit) -> list[tuple[str, SignalDict]]
  .detect_regime(*args, **kwargs) -> str
  .detect_regime_and_adx(*args, **kwargs) -> tuple[str, float]
  .snapshot(name, signal) -> StrategySnapshot

See core/strategy/orchestrator.py for the canonical implementation.
"""
from __future__ import annotations

import warnings
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

warnings.warn(
    "core.strategy_engine is DEPRECATED. Use core.strategy.orchestrator.StrategyOrchestrator instead.",
    DeprecationWarning,
    stacklevel=2,
)

import logging

_log = logging.getLogger(__name__)

SignalDict = dict[str, Any]


@dataclass(frozen=True)
class StrategySnapshot:
    name: str
    score: float
    threshold: float
    direction: str
    regime: str
    strength: str


class StrategyEngine:
    """DEPRECATED: Use StrategyOrchestrator from core.strategy.orchestrator."""

    def __init__(
        self,
        *,
        generate_signal_fn: Callable[[str, dict[str, Any], float], SignalDict | None] | None = None,
        top_signals_fn: Callable[[int], list[tuple[str, SignalDict]]] | None = None,
        detect_regime_fn: Callable[..., str] | None = None,
        detect_regime_and_adx_fn: Callable[..., tuple[str, float]] | None = None,
        **kwargs,
    ):
        self._generate_signal_fn = generate_signal_fn
        self._top_signals_fn = top_signals_fn
        self._detect_regime_fn = detect_regime_fn
        self._detect_regime_and_adx_fn = detect_regime_and_adx_fn
        _log.warning("StrategyEngine is DEPRECATED — use StrategyOrchestrator")

    def generate_signal(self, name: str, frames: dict[str, Any], vix: float = 0.0) -> SignalDict | None:
        if self._generate_signal_fn:
            return self._generate_signal_fn(name, frames, vix)
        return None

    def get_top_signals(self, limit: int = 5) -> list[tuple[str, SignalDict]]:
        if not self._top_signals_fn:
            return []
        return list(self._top_signals_fn(limit))

    def detect_regime(self, *args: Any, **kwargs: Any) -> str:
        if not self._detect_regime_fn:
            return "UNKNOWN"
        return str(self._detect_regime_fn(*args, **kwargs))

    def detect_regime_and_adx(self, *args: Any, **kwargs: Any) -> tuple[str, float]:
        if not self._detect_regime_and_adx_fn:
            return ("UNKNOWN", 0.0)
        regime, adx = self._detect_regime_and_adx_fn(*args, **kwargs)
        return str(regime), float(adx or 0.0)

    def snapshot(self, name: str, signal: SignalDict | None) -> StrategySnapshot:
        sig = signal or {}
        return StrategySnapshot(
            name=name,
            score=float(sig.get("score") or 0.0),
            threshold=float(sig.get("threshold") or 0.0),
            direction=str(sig.get("direction") or ""),
            regime=str(sig.get("regime") or sig.get("mkt_regime") or ""),
            strength=str(sig.get("strength") or ""),
        )

    def get_status(self) -> dict:
        return {
            "has_generate_signal_fn": self._generate_signal_fn is not None,
            "has_top_signals_fn": self._top_signals_fn is not None,
        }
