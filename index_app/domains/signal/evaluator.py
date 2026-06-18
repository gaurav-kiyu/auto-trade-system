"""Signal Evaluator — evaluates adaptive signals for a given index.

Extracted from ``core.signal_service._evaluate_v2_signal()``.  Responsible
for building market context (OI, IV rank, session time), constructing
``PureIndexSignalParams``, and calling ``evaluate_adaptive_signal()``.
"""

from __future__ import annotations

import logging
from typing import Any

from core.adaptive_signal import AdaptiveSignal
from core.adaptive_signal import evaluate_adaptive_signal as _eval_v2

_log = logging.getLogger(__name__)


class SignalEvaluator:
    """Evaluate adaptive signals for a given index symbol.

    Parameters
    ----------
    cfg:
        Application configuration dict (used for thresholds, flags, etc.).

    Usage
    -----
    evaluator = SignalEvaluator(cfg)
    adaptive_signal, reason = evaluator.evaluate(
        name="NIFTY",
        frames={"df1m": ..., "df5m": ..., "df15m": ...},
        vix=12.5,
    )
    """

    def __init__(self, cfg: dict[str, Any]) -> None:
        self._cfg = cfg

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate(
        self,
        name: str,
        frames: dict[str, Any],
        vix: float = 0.0,
    ) -> tuple[AdaptiveSignal | None, str]:
        """Build signal params + context and evaluate the adaptive signal.

        Parameters
        ----------
        name:
            Index symbol (e.g. ``"NIFTY"``, ``"BANKNIFTY"``).
        frames:
            Dict with ``df1m``, ``df5m``, ``df15m`` DataFrames.
        vix:
            Current VIX value.

        Returns
        -------
        ``(AdaptiveSignal, "")`` on success, or ``(None, reason_tag)`` on
        hard block (data gap, IV spike, etc.).
        """
        from core.iv_rank import get_iv_rank
        from core.oi_snapshot_store import get_oi_at, get_pcr_at
        from core.pure_index_signal import (
            PureIndexRegimeParams,
            PureIndexSignalParams,
        )

        # ── Frames ────────────────────────────────────────────────────────────
        df1 = frames.get("df1m")
        df5 = frames.get("df5m")
        df15 = frames.get("df15m")

        # ── OI context ───────────────────────────────────────────────────────
        oi_sup: float = 0.0
        oi_res: float = 0.0
        pcr: float = 1.0
        smart: str = "NEUTRAL"
        try:
            from core.datetime_ist import now_ist

            ts = now_ist().timestamp()
            pcr_val = get_pcr_at(name, ts)
            if pcr_val is not None:
                pcr = float(pcr_val)
                oi_change = get_oi_at(name, ts) or 0.0
                smart = "BULLISH" if oi_change > 0 else (
                    "BEARISH" if oi_change < 0 else "NEUTRAL"
                )
        except (ValueError, TypeError, KeyError, AttributeError, IndexError, OSError):
            _log.debug("OI data fetch failed for %s - continuing without OI data", name)

        # ── IV rank ──────────────────────────────────────────────────────────
        iv = float(get_iv_rank(name) if callable(get_iv_rank) else 0.0)

        # ── Session time ─────────────────────────────────────────────────────
        from core.datetime_ist import now_ist as _now_ist

        _now = _now_ist()
        is_early = _now.hour < 10 or (_now.hour == 10 and _now.minute < 30)
        sc = dict(self._cfg)

        # ── Regime / signal params ───────────────────────────────────────────
        regime_params = PureIndexRegimeParams(
            vix_block_threshold=float(sc.get("VIX_BLOCK_THRESHOLD", 40.0)),
            adx_trend_threshold=float(sc.get("ADX_TREND_THRESHOLD", 25.0)),
            adx_chop_threshold=float(sc.get("ADX_CHOP_THRESHOLD", 20.0)),
        )
        params = PureIndexSignalParams(
            name=name,
            signal_cfg=sc,
            regime=regime_params,
            iv_spike_threshold=float(sc.get("IV_SPIKE_THRESHOLD", 60.0)),
            vol_ratio_min=float(sc.get("VOL_RATIO_MIN", 1.2)),
            is_early_session=is_early,
            min15_early=int(sc.get("EARLY_SESSION_MIN_15M", 4)),
            min15_normal=int(sc.get("NORMAL_SESSION_MIN_15M", 5)),
        )

        # ── Evaluate ─────────────────────────────────────────────────────────
        adaptive_result, reason = _eval_v2(
            params=params,
            df1=df1,
            df5=df5,
            df15=df15,
            vix=vix,
            iv=iv,
            oi_sup=oi_sup,
            oi_res=oi_res,
            pcr=pcr,
            smart=smart,
            learning_score_bonus=int(sc.get("LEARNING_SCORE_ADJ", 0)),
            max_lots=int(sc.get("MAX_LOTS", 1)),
            capital=float(sc.get("BASE_CAPITAL", 100_000.0)),
            dual_direction_enabled=bool(sc.get("DUAL_DIRECTION_ENABLED", True)),
            counter_trend_penalty=int(sc.get("COUNTER_TREND_PENALTY", 10)),
            mean_reversion_enabled=bool(sc.get("MEAN_REVERSION_ENABLED", True)),
            tf_divergence_fallback=bool(sc.get("TF_DIVERGENCE_FALLBACK", True)),
        )

        if adaptive_result is None:
            _log.debug("V2 signal path returned None for %s (reason=%s)", name, reason)

        return adaptive_result, reason


__all__ = [
    "SignalEvaluator",
]
