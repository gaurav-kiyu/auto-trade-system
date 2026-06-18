"""Legacy Signal Engine — backward-compatible ``build_full_signal`` path.

Extracted from ``core.signal_service.generate_trading_signal()`` (DEBT-011).
Wraps the deprecated ``core.legacy.signal_engine.build_full_signal`` call
with the OI data and IV rank context that was previously inline in
``SignalService``.

This path is **deprecated** in favour of ``SignalEvaluator`` (the V2
adaptive_signal path).  New call sites should use ``SignalEvaluator``
directly.  This module exists solely for backward compatibility with
configurations that have ``SIGNAL_ENGINE_V2: false``.
"""

from __future__ import annotations

import logging
from typing import Any

_log = logging.getLogger(__name__)


class LegacySignalEngine:
    """Evaluate a signal using the legacy ``build_full_signal`` path.

    Parameters
    ----------
    cfg:
        Application configuration dict.
    """

    def __init__(self, cfg: dict[str, Any]) -> None:
        self._cfg = cfg

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build_signal(
        self,
        name: str,
        frames: dict[str, Any],
        vix: float = 0.0,
    ) -> dict[str, Any]:
        """Build a signal via ``core.legacy.signal_engine.build_full_signal``.

        Parameters
        ----------
        name:
            Index symbol (e.g. ``\"NIFTY\"``).
        frames:
            Dict with ``df1m``, ``df5m``, ``df15m`` DataFrames.
        vix:
            Current VIX value.

        Returns
        -------
        Signal dict as returned by ``build_full_signal``.
        """
        from core.datetime_ist import now_ist
        from core.iv_rank import get_iv_rank
        from core.legacy.signal_engine import build_full_signal
        from core.oi_snapshot_store import get_oi_at, get_pcr_at

        _log.warning(
            "SIGNAL PATH: using root-level signal_engine.build_full_signal "
            "(deprecated - set SIGNAL_ENGINE_V2=true to use adaptive_signal)"
        )

        threshold = int(self._cfg.get("AI_THRESHOLD", 60))
        df1m = frames.get("df1m")
        df5m = frames.get("df5m")
        df15m = frames.get("df15m")

        # ── OI data context ───────────────────────────────────────────────
        oi_data: dict[str, Any] | None = None
        try:
            ts = now_ist().timestamp()
            pcr_val = get_pcr_at(name, ts)
            oi_change_val = get_oi_at(name, ts)
            if pcr_val is not None:
                oi_data = {"pcr": pcr_val, "oi_change": oi_change_val or 0}
        except (ValueError, TypeError, KeyError, AttributeError, IndexError, OSError):
            _log.debug("OI data fetch failed for %s - continuing without OI data", name)

        # ── IV rank ──────────────────────────────────────────────────────
        iv = float(get_iv_rank(name) if callable(get_iv_rank) else 0.0)

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


__all__ = [
    "LegacySignalEngine",
]
