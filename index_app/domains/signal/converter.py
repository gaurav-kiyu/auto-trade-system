"""Adaptive Signal Converter — converts ``AdaptiveSignal`` dataclass to a
signal-consumer-friendly dict compatible with ``index_trader.py``.

Extracted from ``core.signal_service._evaluate_v2_signal()`` to separate
the serialisation concern from evaluation orchestration.
"""

from __future__ import annotations

import logging
from typing import Any

from core.adaptive_signal import AdaptiveSignal

_log = logging.getLogger(__name__)


class AdaptiveSignalConverter:
    """Convert ``AdaptiveSignal`` dataclass instances to signal dicts.

    Parameters
    ----------
    cfg:
        Config dict (used for threshold values).
    """

    def __init__(self, cfg: dict[str, Any]) -> None:
        self._cfg = cfg

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def to_dict(
        self,
        result: AdaptiveSignal,
        name: str,
        vix: float = 0.0,
    ) -> dict[str, Any]:
        """Convert an ``AdaptiveSignal`` to the dict format expected by consumers.

        Parameters
        ----------
        result:
            The ``AdaptiveSignal`` instance to convert.
        name:
            Index symbol (e.g. ``"NIFTY"``).
        vix:
            Current VIX value (included for traceability in the output dict).

        Returns
        -------
        Dict with keys: ``symbol``, ``name``, ``signal``, ``score``,
        ``raw_score``, ``direction``, ``regime``, ``strength``, ``tier``,
        ``confidence``, ``threshold``, ``vix``, ``price``, ``atr``, ``rsi``,
        ``adx``, ``vwap``, ``vol_ratio``, ``breakout_ok``, ``soft_blocks``,
        ``reasons``, ``score_components``, ``features``, ``risk``,
        ``signal_engine_v2``.
        """
        sc = dict(self._cfg)
        threshold = int(sc.get("AI_THRESHOLD", 60))

        if result.score >= threshold:
            sig_signal = "BUY" if result.direction == "CALL" else "SELL"
        else:
            sig_signal = "HOLD"

        strength = (
            "STRONG"
            if result.score >= int(sc.get("STRONG_THRESHOLD", 85))
            else "MODERATE"
            if result.score >= int(sc.get("MODERATE_THRESHOLD", 70))
            else "WEAK"
            if result.score >= threshold
            else "NONE"
        )

        _log.info(
            "SIGNAL PATH: V2 adaptive_signal for %s score=%d dir=%s tier=%s",
            name,
            result.score,
            result.direction,
            result.tier,
        )

        return {
            "symbol": name,
            "name": name,
            "signal": sig_signal,
            "score": result.score,
            "raw_score": result.raw_score,
            "direction": result.direction,
            "regime": result.regime,
            "strength": strength,
            "tier": result.tier,
            "confidence": float(result.confidence * 100),
            "threshold": threshold,
            "vix": round(vix, 1),
            "price": result.price,
            "atr": result.atr,
            "rsi": result.rsi,
            "adx": result.adx,
            "vwap": result.vwap,
            "vol_ratio": result.vol_ratio,
            "breakout_ok": "tf_mismatch" not in result.soft_blocks,
            "soft_blocks": list(result.soft_blocks),
            "reasons": list(result.reasons),
            "score_components": dict(result.score_components),
            "features": list(result.features),
            "risk": dict(result.risk),
            "signal_engine_v2": True,
        }


__all__ = [
    "AdaptiveSignalConverter",
]
