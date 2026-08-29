"""Capital Manager — Equity-aware capital scaling engine.

Extracted from core.services.risk_service for SRP compliance.
Provides thread-safe equity tracking, drawdown protection, and
position scaling based on capital growth, drawdown, consecutive losses,
and daily loss limits.

Usage:
    from core.capital_manager import CapitalManager, CapitalState, ScaleResult
"""

from __future__ import annotations

import logging
import math
import threading
from dataclasses import dataclass
from typing import Any

from core.safety_state import trip_hard_halt

# ── Module-level constants ──────────────────────────────────────────────
_GROWTH_CAP = 1.50
_DD_SCALE_FLOOR = 0.30
_DD_HARD_BLOCK = 0.20
_CONSEC_LOSS_2 = 0.75
_CONSEC_LOSS_3 = 0.50
_CONSEC_LOSS_4P = 0.25
_DAILY_WARN_PCT = 0.60


@dataclass
class CapitalState:
    initial_capital: float
    current_capital: float
    peak_capital: float
    locked_profit: float
    daily_pnl: float
    daily_trade_count: int
    consecutive_losses: int
    total_trades: int
    total_wins: int


@dataclass
class ScaleResult:
    scale_factor: float
    scaled_lots: int
    capital_growth: float
    drawdown_factor: float
    consec_loss_factor: float
    daily_loss_factor: float
    drawdown_pct: float
    reasoning: str


class CapitalManager:
    """Thread-safe equity-aware capital scaling engine.

    Consolidated from ``core.capital_manager`` (deprecated).
    """

    def __init__(
        self,
        initial_capital: float,
        max_daily_loss: float,
        max_drawdown_pct: float = 0.20,
        daily_loss_warn_pct: float = _DAILY_WARN_PCT,
        drawdown_scale_enabled: bool = True,
    ):
        if max_daily_loss >= 0:
            raise ValueError("max_daily_loss must be negative")
        self._lock = threading.RLock()
        self._max_daily_loss = max_daily_loss
        self._max_dd = max_drawdown_pct
        self._daily_warn_pct = daily_loss_warn_pct
        # config key DRAWDOWN_SIZE_SCALE - previously this flag existed in
        # config but nothing read it; the drawdown-based dd_factor below ran
        # unconditionally regardless of its value.
        self._drawdown_scale_enabled = drawdown_scale_enabled
        self._state = CapitalState(
            initial_capital=initial_capital,
            current_capital=initial_capital,
            peak_capital=initial_capital,
            locked_profit=0.0,
            daily_pnl=0.0,
            daily_trade_count=0,
            consecutive_losses=0,
            total_trades=0,
            total_wins=0,
        )

    def scale(self, base_lots: int, max_lots: int = 1) -> ScaleResult:
        with self._lock:
            st = self._state
            growth = st.current_capital / max(st.initial_capital, 1.0)
            capital_growth = round(min(_GROWTH_CAP, max(0.10, growth)), 3)
            dd_pct = self._drawdown_pct_unlocked(st)
            if not self._drawdown_scale_enabled:
                dd_factor = 1.0
            elif dd_pct >= self._max_dd:
                dd_factor = 0.0
            elif dd_pct > 0:
                dd_factor = round(max(_DD_SCALE_FLOOR, 1.0 - (dd_pct / self._max_dd)), 3)
            else:
                dd_factor = 1.0
            cl = st.consecutive_losses
            consec_factor = _CONSEC_LOSS_4P if cl >= 4 else (_CONSEC_LOSS_3 if cl >= 3 else (_CONSEC_LOSS_2 if cl >= 2 else 1.0))
            daily_warn_level = self._max_daily_loss * self._daily_warn_pct
            if st.daily_pnl <= daily_warn_level < 0:
                fraction_used = st.daily_pnl / self._max_daily_loss
                daily_factor = round(max(0.25, 1.0 - fraction_used * 0.50), 3)
            else:
                daily_factor = 1.0
            scale_factor = round(capital_growth * dd_factor * consec_factor * daily_factor, 3)
            scale_factor = max(0.0, min(1.0, scale_factor))
            scaled_lots = int(math.floor(base_lots * scale_factor))
            scaled_lots = max(1, min(scaled_lots, max_lots)) if scale_factor > 0 else 0
            parts = [f"growth={capital_growth:.2f}"]
            if dd_factor < 1.0:
                parts.append(f"dd={dd_pct:.1%}\u2192dd_factor={dd_factor:.2f}")
            if consec_factor < 1.0:
                parts.append(f"consec_losses={cl}\u2192factor={consec_factor:.2f}")
            if daily_factor < 1.0:
                parts.append(f"daily_pnl={st.daily_pnl:+.0f}\u2192factor={daily_factor:.2f}")
            reasoning = f"{base_lots} lots \u00d7 scale={scale_factor:.2f} [{', '.join(parts)}] \u2192 {scaled_lots} lots"
            return ScaleResult(scale_factor=scale_factor, scaled_lots=scaled_lots, capital_growth=capital_growth, drawdown_factor=dd_factor, consec_loss_factor=consec_factor, daily_loss_factor=daily_factor, drawdown_pct=dd_pct, reasoning=reasoning)

    def record_trade(self, net_pnl: float, is_winner: bool) -> None:
        with self._lock:
            st = self._state
            st.current_capital += net_pnl
            st.daily_pnl += net_pnl
            st.peak_capital = max(st.peak_capital, st.current_capital)
            st.daily_trade_count += 1
            st.total_trades += 1
            if is_winner:
                st.consecutive_losses = 0
                st.total_wins += 1
            else:
                st.consecutive_losses += 1

    def reset_daily(self) -> None:
        with self._lock:
            self._state.daily_pnl = 0.0
            self._state.daily_trade_count = 0

    def lock_profits(self, lock_pct: float = 0.50) -> float:
        with self._lock:
            st = self._state
            profit = st.current_capital - st.initial_capital
            if profit <= 0:
                return 0.0
            amount = round(profit * lock_pct, 2)
            st.current_capital -= amount
            st.locked_profit += amount
            log = logging.getLogger("capital_manager")
            log.info(
                "Profit lock: extracted Rs%.2f (%.0f%% of profit=Rs%.2f). "
                "Locked total=Rs%.2f, capital=Rs%.2f",
                amount, lock_pct * 100, profit,
                st.locked_profit, st.current_capital,
            )
            return amount

    def decide_trade_allowed(self) -> tuple[bool, str]:
        with self._lock:
            st = self._state
            if st.daily_pnl <= self._max_daily_loss:
                return False, f"Daily loss limit hit: {st.daily_pnl:+.2f} <= {self._max_daily_loss:+.2f}"
            dd = self._drawdown_pct_unlocked(st)
            if dd >= self._max_dd:
                trip_hard_halt(f"Max drawdown breached: {dd:.1%} >= {self._max_dd:.1%}", source="CapitalManager.decide_trade_allowed")
                return False, f"Max drawdown breached: {dd:.1%} >= {self._max_dd:.1%}"
            if st.consecutive_losses >= 5:
                trip_hard_halt(f"Circuit breaker: {st.consecutive_losses} consecutive losses", source="CapitalManager.decide_trade_allowed")
                return False, f"Circuit breaker: {st.consecutive_losses} consecutive losses"
            return True, "OK"

    def get_state(self) -> dict[str, Any]:
        with self._lock:
            st = self._state
            dd = self._drawdown_pct_unlocked(st)
            wr = round(st.total_wins / st.total_trades * 100, 1) if st.total_trades else 0.0
            return {
                "initial_capital": st.initial_capital,
                "current_capital": round(st.current_capital, 2),
                "peak_capital": round(st.peak_capital, 2),
                "locked_profit": round(st.locked_profit, 2),
                "daily_pnl": round(st.daily_pnl, 2),
                "drawdown_pct": round(dd * 100, 2),
                "consecutive_losses": st.consecutive_losses,
                "total_trades": st.total_trades,
                "win_rate": wr,
                "capital_return_pct": round((st.current_capital - st.initial_capital) / max(st.initial_capital, 1.0) * 100, 2),
            }

    @staticmethod
    def _drawdown_pct_unlocked(st: CapitalState) -> float:
        return max(0.0, (st.peak_capital - st.current_capital) / st.peak_capital) if st.peak_capital > 0 else 0.0

    @property
    def drawdown_pct(self) -> float:
        with self._lock:
            return round(self._drawdown_pct_unlocked(self._state) * 100, 2)

    @property
    def current_capital(self) -> float:
        with self._lock:
            return self._state.current_capital


__all__ = [
    "CapitalManager",
    "CapitalState",
    "ScaleResult",
]
