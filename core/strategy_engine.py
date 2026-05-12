from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

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
    """Thin strategy boundary around the existing signal logic."""

    def __init__(
        self,
        *,
        generate_signal_fn: Callable[[str, dict[str, Any], float], SignalDict | None],
        top_signals_fn: Callable[[int], list[tuple[str, SignalDict]]] | None = None,
        detect_regime_fn: Callable[..., str] | None = None,
        detect_regime_and_adx_fn: Callable[..., tuple[str, float]] | None = None,
    ) -> None:
        self._generate_signal_fn = generate_signal_fn
        self._top_signals_fn = top_signals_fn
        self._detect_regime_fn = detect_regime_fn
        self._detect_regime_and_adx_fn = detect_regime_and_adx_fn

    def generate_signal(self, name: str, frames: dict[str, Any], vix: float = 0.0) -> SignalDict | None:
        return self._generate_signal_fn(name, frames, vix)

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
