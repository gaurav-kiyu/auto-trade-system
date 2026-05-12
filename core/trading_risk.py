"""
Risk helpers: position sizing inputs and SL/TP distance checks (pure, no broker).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class RiskSizingInput:
    capital: float
    risk_per_trade: float
    sl_distance: float
    lot_size: int
    max_lots: int = 50


def lots_from_fixed_risk(inp: RiskSizingInput) -> int:
    """Integer lots from capital × risk% / SL distance (same direction as index sizing)."""
    if inp.sl_distance <= 0 or inp.lot_size <= 0 or inp.capital <= 0:
        return inp.lot_size
    risk_amt = float(inp.capital) * float(inp.risk_per_trade)
    raw = int(risk_amt / (inp.sl_distance * inp.lot_size))
    lots = max(1, min(int(inp.max_lots), raw)) * inp.lot_size
    return lots


def sl_tp_hit_side(
    direction: Literal["CALL", "PUT"],
    high: float,
    low: float,
    stop_loss: float,
    take_profit: float,
) -> tuple[bool, bool]:
    """Returns (stop_hit, target_hit) for one bar using conservative intrabar ordering."""
    if direction == "CALL":
        return low <= stop_loss, high >= take_profit
    return high >= stop_loss, low <= take_profit
