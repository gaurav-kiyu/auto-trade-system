"""Signal Service - consolidates signal generation and validation logic.


__all__ = [
    "SignalService",
    "get_signal_service",
    "reset_signal_service",
]

Extracted from index_trader.py (GAP-05b split). Provides a singleton-backed
SignalService class with methods for signal pillar validation, trading signal
generation, and quality reporting.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

__all__ = [
    "SignalService",
    "get_signal_service",
    "reset_signal_service",
]

_log = logging.getLogger(__name__)

# ============================================================================
# In-Memory cache for signal results (backed by module-level state)
# ============================================================================
# ============================================================================
# Singleton
# ============================================================================
_signal_service_instance: SignalService | None = None
_signal_service_lock = threading.RLock()


def get_signal_service(cfg: dict[str, Any] | None = None) -> SignalService:
    """Return the process-level SignalService singleton."""
    global _signal_service_instance
    with _signal_service_lock:
        if _signal_service_instance is None:
            _signal_service_instance = SignalService(cfg=cfg)
    return _signal_service_instance


def reset_signal_service() -> None:
    """Reset the singleton (used in tests)."""
    global _signal_service_instance
    with _signal_service_lock:
        _signal_service_instance = None


# ============================================================================
# SignalService
# ============================================================================

class SignalService:
    """Consolidates signal generation and validation logic.

    Extracted from index_trader.py - provides pillar validation, trading signal
    generation, quality reporting, and top-signal selection.
    """

    def __init__(self, cfg: dict[str, Any] | None = None) -> None:
        self._cfg = cfg or {}

    # ------------------------------------------------------------------
    # PILLAR VALIDATION
    # ------------------------------------------------------------------

    def validate_signal_pillars(
        self,
        rsi: float | None = None,
        macd: str | None = None,
        adx: float | None = None,
        iv_rank: float | None = None,
        oi_change: float | None = None,
        pcr: float | None = None,
        fii_net: float | None = None,
        dii_net: float | None = None,
        gex: float | None = None,
        session_score: float | None = None,
    ) -> tuple[bool, str]:
        """Validate signal independence - RSI/MACD/ADX = 1 pillar (NOT 3!).

        Must have consensus from 2 independent pillars for trade.
        """
        from core.signal_independence import SignalIndependenceValidator

        validator = SignalIndependenceValidator()

        # PILLAR 1: Price/Momentum (RSI+MACD+ADX = ONE pillar)
        if rsi is not None and macd is not None and adx is not None:
            validator.set_price_momentum_signal(rsi, macd, adx)

        # PILLAR 2: Options Market (IV+OI+PCR = independent)
        if iv_rank is not None and oi_change is not None and pcr is not None:
            validator.set_options_market_signal(iv_rank, oi_change, pcr)

        # PILLAR 3: Institutional Flow (FII+DII+GEX = independent)
        if fii_net is not None and dii_net is not None:
            validator.set_institutional_flow_signal(fii_net, dii_net, gex or 0)

        # PILLAR 4: Structural (session+time+events = independent)
        if session_score is not None:
            validator.set_structural_signal(session_score, "normal", True)

        # Validate: Need 2 pillars agreeing
        valid, reason, pillars = validator.validate_independence()
        if not valid:
            return False, f"PILLAR_FAIL: {reason} (have {pillars} pillars)"

        direction = validator.get_consensus_direction()
        return True, f"PILLAR_OK: {direction} consensus from {pillars} pillars"

    # ------------------------------------------------------------------
    # TRADING SIGNAL GENERATION
    # ------------------------------------------------------------------

    def generate_trading_signal(
        self,
        name: str,
        frames: dict[str, Any],
        vix: float = 0.0,
    ) -> dict[str, Any]:
        """Generate a trading signal dict.

        Routes to the V2 ``SignalEvaluator`` when config key
        ``SIGNAL_ENGINE_V2`` is ``True``; otherwise falls back to the legacy
        ``LegacySignalEngine`` path for backward compatibility.

        Args:
            name: Index symbol (e.g., "NIFTY", "BANKNIFTY").
            frames: Dict with df1m, df5m, df15m DataFrames.
            vix: Current VIX value.

        Returns:
            Signal dict compatible with ``index_trader.py`` signal consumers.
        """
        # ── Route: V2 adaptive_signal path ────────────────────────────────
        if self._cfg.get("SIGNAL_ENGINE_V2", False):
            return self._evaluate_v2_signal(name=name, frames=frames, vix=vix) or {}

        # ── Route: Legacy signal_engine path (DEBT-011) ──────────────────
        from index_app.domains.signal.legacy import LegacySignalEngine

        engine = LegacySignalEngine(cfg=self._cfg)
        return engine.build_signal(name=name, frames=frames, vix=vix)

    # ------------------------------------------------------------------
    # V2 ADAPTIVE SIGNAL PATH
    # ------------------------------------------------------------------

    def _evaluate_v2_signal(
        self,
        name: str,
        frames: dict[str, Any],
        vix: float = 0.0,
    ) -> dict[str, Any] | None:
        """Evaluate signal using ``index_app.domains.signal.evaluator.SignalEvaluator``.

        Delegates to the extracted ``SignalEvaluator`` (DEBT-010) for the full
        evaluation pipeline, then converts the ``AdaptiveSignal`` result via
        ``AdaptiveSignalConverter`` to a dict compatible with ``index_trader.py``.
        """
        from index_app.domains.signal.converter import AdaptiveSignalConverter
        from index_app.domains.signal.evaluator import SignalEvaluator

        evaluator = SignalEvaluator(cfg=self._cfg)
        adaptive_result, reason = evaluator.evaluate(name=name, frames=frames, vix=vix)

        if adaptive_result is None:
            _log.debug("V2 signal path returned None for %s (reason=%s)", name, reason)
            return None

        converter = AdaptiveSignalConverter(cfg=self._cfg)
        return converter.to_dict(result=adaptive_result, name=name, vix=vix)

    # ------------------------------------------------------------------
    # QUALITY REPORTING
    # ------------------------------------------------------------------

    @staticmethod
    def get_signal_quality_report() -> str:
        """Return a placeholder signal quality report."""
        return "ok"

    @staticmethod
    def get_top_signals(n: int) -> list[dict[str, Any]]:
        """Return a placeholder top-signals list."""
        return []
