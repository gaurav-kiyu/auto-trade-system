"""
Kelly Criterion Position Sizer (v2.45 Item 6).

Uses the half-Kelly formula on recent trade history to compute a
statistically-grounded lot recommendation.  The output is a SUGGESTION;
the existing 5-layer risk system (regime/score/intraday multipliers) still
applies on top.

Formula
-------
    kelly_f    = (win_rate × avg_win - loss_rate × avg_loss) / avg_win
    half_kelly = kelly_f × 0.5     (always use half-Kelly for safety)
    kelly_lots = int(capital × half_kelly / risk_per_lot)

Clamps: [kelly_min_lots=1, kelly_max_lots_mult × BASE_LOTS]

Public API
----------
    compute_kelly_lots(capital, base_lots, risk_per_lot, db_path, cfg)
        → KellyResult

Config keys
-----------
    kelly_enabled          : bool  default false
    kelly_window_trades    : int   default 50
    kelly_min_trades       : int   default 20
    kelly_max_lots_mult    : float default 2.0
"""
from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)

_DEFAULT_DB = "trades.db"


# ── Dataclass ─────────────────────────────────────────────────────────────────

@dataclass
class KellyResult:
    kelly_f:       float   # raw Kelly fraction (pre half-Kelly)
    half_kelly:    float   # kelly_f × 0.5
    kelly_lots:    int     # recommended lots (clamped)
    win_rate:      float
    avg_win:       float
    avg_loss:      float
    n_trades:      int
    used_fallback: bool    # True if insufficient history → used base_lots


# ── History loader ────────────────────────────────────────────────────────────

def _load_recent_pnls(db_path: str, window: int) -> list[float]:
    p = Path(db_path)
    if not p.is_file():
        return []
    try:
        conn = sqlite3.connect(str(p), check_same_thread=False, timeout=5)
        try:
            rows = conn.execute(
                "SELECT net_pnl FROM trades "
                "WHERE net_pnl IS NOT NULL "
                "ORDER BY id DESC LIMIT ?",
                (window,),
            ).fetchall()
        finally:
            conn.close()
        return [float(r[0]) for r in rows if r[0] is not None]
    except Exception as exc:
        _log.debug("[KELLY] DB load failed: %s", exc)
        return []


# ── Core computation ──────────────────────────────────────────────────────────

def compute_kelly_lots(
    capital:       float,
    base_lots:     int,
    risk_per_lot:  float,
    db_path:       str = _DEFAULT_DB,
    cfg:           dict[str, Any] | None = None,
) -> KellyResult:
    """
    Compute Kelly-based lot recommendation from recent trade history.

    Args:
        capital      : current trading capital (₹).
        base_lots    : fallback lot count when Kelly is unavailable.
        risk_per_lot : ₹ amount risked per lot (SL_PCT × premium × lot_size).
        db_path      : path to trades.db.
        cfg          : config dict.

    Returns:
        KellyResult (always returns, never raises).
    """
    c = cfg or {}

    _fallback = KellyResult(
        kelly_f=0.0, half_kelly=0.0, kelly_lots=base_lots,
        win_rate=0.0, avg_win=0.0, avg_loss=0.0,
        n_trades=0, used_fallback=True,
    )

    if not c.get("kelly_enabled", False):
        return _fallback

    window    = int(c.get("kelly_window_trades", 50))
    min_n     = int(c.get("kelly_min_trades", 20))
    max_mult  = float(c.get("kelly_max_lots_mult", 2.0))

    pnls = _load_recent_pnls(db_path, window)
    n    = len(pnls)
    if n < min_n:
        _log.debug("[KELLY] insufficient history (%d < %d) → fallback", n, min_n)
        return KellyResult(
            kelly_f=0.0, half_kelly=0.0, kelly_lots=base_lots,
            win_rate=0.0, avg_win=0.0, avg_loss=0.0,
            n_trades=n, used_fallback=True,
        )

    wins   = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    wr     = len(wins) / n
    lr     = 1.0 - wr
    avg_w  = sum(wins)  / len(wins)  if wins   else 0.0
    avg_l  = abs(sum(losses) / len(losses)) if losses else 0.0

    if avg_w <= 0:
        return KellyResult(
            kelly_f=0.0, half_kelly=0.0, kelly_lots=base_lots,
            win_rate=wr, avg_win=avg_w, avg_loss=avg_l,
            n_trades=n, used_fallback=True,
        )

    kelly_f   = (wr * avg_w - lr * avg_l) / avg_w
    half_k    = kelly_f * 0.5

    if half_k <= 0 or risk_per_lot <= 0 or capital <= 0:
        kelly_lots = base_lots
    else:
        kelly_lots = max(1, int(capital * half_k / risk_per_lot))

    # Clamp to [1, base_lots × max_mult]
    max_lots   = max(1, int(base_lots * max_mult))
    kelly_lots = min(kelly_lots, max_lots)
    kelly_lots = max(1, kelly_lots)

    _log.debug(
        "[KELLY] f=%.3f half=%.3f → %d lots (wr=%.1f%% n=%d)",
        kelly_f, half_k, kelly_lots, wr * 100, n,
    )
    return KellyResult(
        kelly_f    = round(kelly_f, 4),
        half_kelly = round(half_k, 4),
        kelly_lots = kelly_lots,
        win_rate   = round(wr, 4),
        avg_win    = round(avg_w, 2),
        avg_loss   = round(avg_l, 2),
        n_trades   = n,
        used_fallback = False,
    )
