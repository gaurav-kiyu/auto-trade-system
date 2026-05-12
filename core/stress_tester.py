"""
Stress Test Engine (v2.45 Item 8).

Applies shock scenarios to the current open position portfolio and reports
the P&L impact of each scenario.  Pure math — no IO.  Runs on every scan
cycle; must complete in < 5 ms.

Scenarios
---------
    FLASH_CRASH   : index -3.0%, VIX ×2.0, time +5 min
    SLOW_GRIND    : index -1.5%, VIX ×1.3, time +30 min
    GAP_UP        : index +1.8%, VIX ×0.8, time +1 min
    EXPIRY_CRUSH  : theta ×3.0,  VIX -10%, time +90 min

Greek approximation (Black-Scholes first-order):
    shocked_pnl = delta × index_move + vega × vol_change - theta × time_mins/60

Public API
----------
    run_stress_test(open_positions, capital, cfg) → list[StressResult]
    format_stress_summary(results) → str

Config keys
-----------
    stress_test_enabled     : bool  default true
    max_stress_loss_pct     : float default 10.0
    stress_custom_scenarios : list  default []
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

_log = logging.getLogger(__name__)

# ── Built-in scenarios ────────────────────────────────────────────────────────

_BUILT_IN_SCENARIOS: list[dict[str, Any]] = [
    {"name": "FLASH_CRASH",   "index_move_pct": -3.0,  "vix_mult": 2.0,  "time_mins": 5.0},
    {"name": "SLOW_GRIND",    "index_move_pct": -1.5,  "vix_mult": 1.3,  "time_mins": 30.0},
    {"name": "GAP_UP",        "index_move_pct":  1.8,  "vix_mult": 0.8,  "time_mins": 1.0},
    {"name": "EXPIRY_CRUSH",  "index_move_pct":  0.0,  "vix_mult": 0.9,  "theta_mult": 3.0, "time_mins": 90.0},
]


# ── Dataclass ─────────────────────────────────────────────────────────────────

@dataclass
class StressResult:
    scenario:        str
    total_pnl_shock: float    # ₹
    worst_position:  str      # name/id of worst-affected position
    pct_of_capital:  float    # shock as % of capital
    alert:           bool     # True if shock > max_stress_loss_pct


# ── Core computation ──────────────────────────────────────────────────────────

def _greek_shock(
    position:      dict[str, Any],
    index_move_pct: float,
    vix_mult:       float,
    time_mins:      float,
    theta_mult:     float = 1.0,
) -> float:
    """
    Approximate P&L shock using first-order Greeks.

    Position dict expected keys (all optional, default 0):
        delta   : ₹ PnL per 1% index move
        vega    : ₹ PnL per 1-point VIX change
        theta   : ₹ daily time decay (positive = loss per day)
        vix     : current VIX level
        lots    : multiplier
    """
    delta = float(position.get("delta", 0.0))
    vega  = float(position.get("vega",  0.0))
    theta = float(position.get("theta", 0.0))
    vix   = float(position.get("vix",   15.0))
    lots  = float(position.get("lots",  1.0))

    index_shock  = delta * index_move_pct
    vol_change   = vix * (vix_mult - 1.0)
    vega_shock   = vega * vol_change
    theta_shock  = -(theta * theta_mult) * (time_mins / 60.0 / 6.5)
    return (index_shock + vega_shock + theta_shock) * lots


def run_stress_test(
    open_positions: list[dict[str, Any]],
    capital:        float,
    cfg:            dict[str, Any] | None = None,
) -> list[StressResult]:
    """
    Run all stress scenarios against the current open position portfolio.

    Args:
        open_positions : list of position dicts (each with greek keys).
        capital        : current capital (₹) for pct calculation.
        cfg            : config dict.

    Returns:
        List of StressResult, one per scenario.  Empty list if disabled or
        no open positions.
    """
    c = cfg or {}
    if not c.get("stress_test_enabled", True):
        return []
    if not open_positions or capital <= 0:
        return []

    max_loss_pct = float(c.get("max_stress_loss_pct", 10.0))
    custom       = list(c.get("stress_custom_scenarios", []))
    scenarios    = _BUILT_IN_SCENARIOS + custom

    results: list[StressResult] = []
    for sc in scenarios:
        name          = str(sc.get("name", "CUSTOM"))
        idx_move      = float(sc.get("index_move_pct", 0.0))
        vix_mult      = float(sc.get("vix_mult",  1.0))
        time_mins     = float(sc.get("time_mins", 0.0))
        theta_mult    = float(sc.get("theta_mult", 1.0))

        pos_shocks: list[tuple[str, float]] = []
        for pos in open_positions:
            shock = _greek_shock(pos, idx_move, vix_mult, time_mins, theta_mult)
            label = str(pos.get("name") or pos.get("index_name") or pos.get("id") or "POS")
            pos_shocks.append((label, shock))

        total_shock  = sum(s for _, s in pos_shocks)
        worst_name   = min(pos_shocks, key=lambda x: x[1])[0] if pos_shocks else ""
        pct          = total_shock / capital * 100
        alert        = abs(pct) > max_loss_pct and total_shock < 0

        results.append(StressResult(
            scenario        = name,
            total_pnl_shock = round(total_shock, 0),
            worst_position  = worst_name,
            pct_of_capital  = round(pct, 2),
            alert           = alert,
        ))

    return results


def format_stress_summary(results: list[StressResult]) -> str:
    """Compact one-line summary: "Stress: FC=-₹8.4k | GU=+₹3.1k" """
    if not results:
        return "Stress: no positions"
    R = chr(0x20B9)
    parts = []
    abbr  = {"FLASH_CRASH": "FC", "SLOW_GRIND": "SG", "GAP_UP": "GU", "EXPIRY_CRUSH": "EC"}
    for r in results:
        tag = abbr.get(r.scenario, r.scenario[:4])
        k   = r.total_pnl_shock / 1000
        parts.append(f"{tag}={R}{k:+.1f}k{'!' if r.alert else ''}")
    return "Stress: " + " | ".join(parts)
