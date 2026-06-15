"""Signal Service — consolidates signal generation and validation logic.

Extracted from index_trader.py (GAP-05b split). Provides a singleton-backed
SignalService class with methods for signal pillar validation, trading signal
generation, and quality reporting.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

_log = logging.getLogger(__name__)

# ============================================================================
# In-Memory cache for signal results (backed by module-level state)
# ============================================================================
# ============================================================================
# Singleton
# ============================================================================
_signal_service_instance: "SignalService | None" = None
_signal_service_lock = threading.Lock()


def get_signal_service(cfg: dict[str, Any] | None = None) -> "SignalService":
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

    Extracted from index_trader.py — provides pillar validation, trading signal
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
        """Validate signal independence — RSI/MACD/ADX = 1 pillar (NOT 3!).

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
        """Generate a trading signal dict using the (deprecated) signal_engine.

        Args:
            name: Index symbol (e.g., "NIFTY", "BANKNIFTY").
            frames: Dict with df1m, df5m, df15m DataFrames.
            vix: Current VIX value.

        Returns:
            Signal dict as returned by signal_engine.build_full_signal.
        """
        from core.iv_rank import get_iv_rank
        from core.oi_snapshot_store import get_oi_at, get_pcr_at

        _log.warning(
            "SIGNAL PATH: using root-level signal_engine.build_full_signal "
            "(deprecated — split-brain risk with core.adaptive_signal)"
        )
        from signal_engine import build_full_signal

        threshold = int(self._cfg.get("AI_THRESHOLD", 60))
        df1m = frames.get("df1m")
        df5m = frames.get("df5m")
        df15m = frames.get("df15m")

        oi_data: dict[str, Any] | None = None
        try:
            from core.datetime_ist import now_ist

            ts = now_ist().timestamp()
            pcr_val = get_pcr_at(name, ts)
            oi_change_val = get_oi_at(name, ts)
            if pcr_val is not None:
                oi_data = {"pcr": pcr_val, "oi_change": oi_change_val or 0}
        except (ValueError, TypeError, KeyError, AttributeError, IndexError, OSError):
            _log.debug("OI data fetch failed for %s — continuing without OI data", name)

        iv = get_iv_rank(name) if callable(get_iv_rank) else 0.0

        return build_full_signal(
            symbol=name,
            df1m=df1m,
            df5m=df5m,
            df15m=df15m,
            asset_type="index",
            oi_data=oi_data,
            iv=iv,
            vix=vix,
            threshold=threshold,
            config=self._cfg,
        )

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
