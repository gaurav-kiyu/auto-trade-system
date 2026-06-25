"""
Value at Risk (VaR) Calculator (v2.45 Item 7).

Computes parametric daily VaR at 95% and 99% confidence from recent trade
P&L history.  Used for EOD reporting and web dashboard /health.

Formula
-------
    daily_vol   = std(daily_returns_last_N_days)
    VaR_95 (₹) = portfolio_value × daily_vol × 1.645
    VaR_99 (₹) = portfolio_value × daily_vol × 2.326

Public API
----------
    compute_var(capital, db_path, cfg) → VaRResult

Config keys
-----------
    var_enabled          : bool  default true
    var_lookback_days    : int   default 30
    max_var_pct          : float default 5.0  (alert threshold)
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.db_utils import get_connection

_log = logging.getLogger(__name__)

_DEFAULT_DB = "trades.db"
_Z_95 = 1.645
_Z_99 = 2.326


# ── Dataclass ─────────────────────────────────────────────────────────────────

@dataclass
class VaRResult:
    var_95:         float   # ₹
    var_99:         float   # ₹
    var_95_pct:     float   # % of capital
    var_99_pct:     float   # % of capital
    daily_vol:      float   # daily return std dev
    n_days:         int
    alert:          bool    # True if var_95_pct > max_var_pct
    alert_message:  str


# ── History loader ────────────────────────────────────────────────────────────

def _load_daily_pnls(db_path: str, lookback_days: int) -> list[float]:
    """Return list of daily net PnL aggregates."""
    p = Path(db_path)
    if not p.is_file():
        return []
    try:
        conn = get_connection(p, timeout=5, row_factory=False)
        try:
            rows = conn.execute(
                """
                SELECT DATE(ts) as d, SUM(net_pnl) as daily_pnl
                FROM trades
                WHERE net_pnl IS NOT NULL
                  AND ts >= DATE('now', ?)
                GROUP BY DATE(ts)
                ORDER BY d
                """,
                (f"-{lookback_days} days",),
            ).fetchall()
        finally:
            conn.close()
        return [float(r[1]) for r in rows if r[1] is not None]
    except (ValueError, TypeError, KeyError, AttributeError, IndexError, OSError) as exc:
        _log.warning("[VAR] DB load failed: %s", exc)
        return []
    except Exception as exc:
        _log.warning("[VAR] DB load failed (unexpected: %s): %s", type(exc).__name__, exc)
        return []


# ── Core computation ──────────────────────────────────────────────────────────

def compute_var(
    capital:  float,
    db_path:  str = _DEFAULT_DB,
    cfg:      dict[str, Any] | None = None,
) -> VaRResult:
    """
    Compute parametric VaR from recent daily trade P&L history.

    Args:
        capital  : current capital value (₹) - used as portfolio base.
        db_path  : path to trades.db.
        cfg      : config dict.

    Returns:
        VaRResult (always returns, all zeros when insufficient data).
    """
    c = cfg or {}
    _zero = VaRResult(
        var_95=0.0, var_99=0.0, var_95_pct=0.0, var_99_pct=0.0,
        daily_vol=0.0, n_days=0, alert=False, alert_message="",
    )

    if not c.get("var_enabled", True):
        return _zero
    if capital <= 0:
        return _zero

    lookback   = int(c.get("var_lookback_days", 30))
    max_var    = float(c.get("max_var_pct", 5.0))
    daily_pnls = _load_daily_pnls(db_path, lookback)

    n = len(daily_pnls)
    if n < 2:
        return _zero

    # Return as % of capital
    returns = [p / capital for p in daily_pnls]
    mean_r  = sum(returns) / n
    var_r   = sum((r - mean_r) ** 2 for r in returns) / n
    std_r   = math.sqrt(var_r)

    var_95_pct  = std_r * _Z_95 * 100
    var_99_pct  = std_r * _Z_99 * 100
    var_95_abs  = capital * std_r * _Z_95
    var_99_abs  = capital * std_r * _Z_99

    alert = var_95_pct > max_var
    msg   = (
        f"VaR(95%) = {var_95_pct:.1f}% of capital (>{max_var}% threshold)"
        if alert else ""
    )

    return VaRResult(
        var_95      = round(var_95_abs, 0),
        var_99      = round(var_99_abs, 0),
        var_95_pct  = round(var_95_pct, 2),
        var_99_pct  = round(var_99_pct, 2),
        daily_vol   = round(std_r * 100, 3),
        n_days      = n,
        alert       = alert,
        alert_message = msg,
    )


def format_var_summary(result: VaRResult) -> str:
    """One-line summary for EOD Telegram."""
    R = chr(0x20B9)
    if result.n_days < 2:
        return "VaR: insufficient history"
    return (
        f"VaR(95%): {R}{result.var_95:,.0f} ({result.var_95_pct:.1f}% of capital)"
        f"  |  VaR(99%): {R}{result.var_99:,.0f}"
    )


__all__ = [
    "VaRResult",
    "compute_var",
    "format_var_summary",
]

