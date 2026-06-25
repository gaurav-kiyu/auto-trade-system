"""
[DEPRECATED] Capital Manager — use core.services.risk_service.RiskService instead.

This module is retained for backward compatibility. New code should import
from ``core.services.risk_service`` directly (``RiskService`` provides
capital scaling, drawdown tracking, and profit locking).

.. deprecated:: 2.54.0
    Use ``RiskService`` with ``RiskServiceConfig`` instead.

---

Capital Manager - equity-aware position scaling and drawdown control.

Scaling formula:
    scale_factor = capital_growth × drawdown_factor × consec_loss_factor × daily_loss_factor

PositionSizer computes tier/regime lots; CapitalManager multiplies by scale_factor.
Net lots are always clamped to [1, max_lots] so a valid trade never drops to 0 lots
due to scaling (call decide_trade_allowed() first to gate the decision).

Design principles:
  - Stateful (tracks equity curve, daily PnL, consecutive losses)
  - Thread-safe
  - Deterministic (no randomness)
  - Never modifies thresholds or scores - only position size
"""

from __future__ import annotations

import logging
import math
import threading
from dataclasses import dataclass
from typing import Any

from core.safety_state import trip_hard_halt

log = logging.getLogger("capital_manager")


# ── Default scaling constants ──────────────────────────────────────────────
_GROWTH_CAP      = 1.50   # max capital growth multiplier (prevents runaway leverage)
_DD_SCALE_FLOOR  = 0.30   # minimum scale factor during drawdown (never below 30%)
_DD_HARD_BLOCK   = 0.20   # drawdown % above which trading is halted (20% peak-to-trough)
_CONSEC_LOSS_2   = 0.75   # scale after 2 consecutive losses
_CONSEC_LOSS_3   = 0.50   # scale after 3 consecutive losses
_CONSEC_LOSS_4P  = 0.25   # scale after 4+ consecutive losses
_DAILY_WARN_PCT  = 0.60   # fraction of MAX_DAILY_LOSS that triggers size reduction


@dataclass
class CapitalState:
    initial_capital: float
    current_capital: float
    peak_capital: float
    locked_profit: float           # profit extracted to safe account / locked pool
    daily_pnl: float               # PnL today only
    daily_trade_count: int
    consecutive_losses: int
    total_trades: int
    total_wins: int


@dataclass
class ScaleResult:
    scale_factor: float            # [0.0, 1.0]  (1.0 = full size)
    scaled_lots: int               # final lots after scaling
    capital_growth: float
    drawdown_factor: float
    consec_loss_factor: float
    daily_loss_factor: float
    drawdown_pct: float
    reasoning: str


class CapitalManager:
    """
    Thread-safe equity-aware capital scaling engine.

    Usage:
        cm = CapitalManager(initial_capital=100_000, max_daily_loss=-4000)

        # Before every trade
        scale = cm.scale(base_lots=2, max_lots=2)
        actual_lots = scale.scaled_lots

        # After exit
        cm.record_trade(net_pnl=+1200, is_winner=True)

        # Periodically (e.g. EOD)
        extracted = cm.lock_profits(lock_pct=0.50)
    """

    def __init__(
        self,
        initial_capital: float,
        max_daily_loss: float,           # negative number, e.g. -4000
        max_drawdown_pct: float = 0.20,  # halt trading at 20% drawdown
        daily_loss_warn_pct: float = _DAILY_WARN_PCT,
    ):
        if max_daily_loss >= 0:
            raise ValueError("max_daily_loss must be negative")
        self._lock = threading.RLock()
        self._max_daily_loss = max_daily_loss
        self._max_dd = max_drawdown_pct
        self._daily_warn_pct = daily_loss_warn_pct

        self._state = CapitalState(
            initial_capital   = initial_capital,
            current_capital   = initial_capital,
            peak_capital      = initial_capital,
            locked_profit     = 0.0,
            daily_pnl         = 0.0,
            daily_trade_count = 0,
            consecutive_losses= 0,
            total_trades      = 0,
            total_wins        = 0,
        )

    # ── Core scaling ──────────────────────────────────────────────────────

    def scale(self, base_lots: int, max_lots: int = 1) -> ScaleResult:
        """
        Apply all scaling factors to base_lots.

        base_lots: lots recommended by PositionSizer
        max_lots:  configured ceiling
        """
        with self._lock:
            st = self._state

            # 1. Capital growth factor
            growth = st.current_capital / max(st.initial_capital, 1.0)
            capital_growth = round(min(_GROWTH_CAP, max(0.10, growth)), 3)

            # 2. Drawdown factor
            dd_pct = self._drawdown_pct_unlocked(st)
            if dd_pct >= self._max_dd:
                dd_factor = 0.0    # hard block - caller checks decide_trade_allowed()
            elif dd_pct > 0:
                dd_factor = round(
                    max(_DD_SCALE_FLOOR, 1.0 - (dd_pct / self._max_dd)),
                    3
                )
            else:
                dd_factor = 1.0

            # 3. Consecutive loss factor
            cl = st.consecutive_losses
            if cl >= 4:
                consec_factor = _CONSEC_LOSS_4P
            elif cl >= 3:
                consec_factor = _CONSEC_LOSS_3
            elif cl >= 2:
                consec_factor = _CONSEC_LOSS_2
            else:
                consec_factor = 1.0

            # 4. Daily loss factor
            daily_warn_level = self._max_daily_loss * self._daily_warn_pct
            if st.daily_pnl <= daily_warn_level and daily_warn_level < 0:
                fraction_used = st.daily_pnl / self._max_daily_loss
                daily_factor = round(max(0.25, 1.0 - fraction_used * 0.50), 3)
            else:
                daily_factor = 1.0

            # Composite
            scale_factor = round(
                capital_growth * dd_factor * consec_factor * daily_factor, 3
            )
            scale_factor = max(0.0, min(1.0, scale_factor))

            scaled_lots = int(math.floor(base_lots * scale_factor))
            scaled_lots = max(1, min(scaled_lots, max_lots)) if scale_factor > 0 else 0

            parts = [f"growth={capital_growth:.2f}"]
            if dd_factor < 1.0:
                parts.append(f"dd={dd_pct:.1%}→dd_factor={dd_factor:.2f}")
            if consec_factor < 1.0:
                parts.append(f"consec_losses={cl}→factor={consec_factor:.2f}")
            if daily_factor < 1.0:
                parts.append(f"daily_pnl={st.daily_pnl:+.0f}→factor={daily_factor:.2f}")
            reasoning = (
                f"{base_lots} lots × scale={scale_factor:.2f} "
                f"[{', '.join(parts)}] → {scaled_lots} lots"
            )

            return ScaleResult(
                scale_factor=scale_factor,
                scaled_lots=scaled_lots,
                capital_growth=capital_growth,
                drawdown_factor=dd_factor,
                consec_loss_factor=consec_factor,
                daily_loss_factor=daily_factor,
                drawdown_pct=dd_pct,
                reasoning=reasoning,
            )

    # ── Trade recording ───────────────────────────────────────────────────

    def record_trade(self, net_pnl: float, is_winner: bool) -> None:
        """Update equity state after a trade closes."""
        with self._lock:
            st = self._state
            st.current_capital  += net_pnl
            st.daily_pnl        += net_pnl
            st.peak_capital      = max(st.peak_capital, st.current_capital)
            st.daily_trade_count += 1
            st.total_trades      += 1

            if is_winner:
                st.consecutive_losses = 0
                st.total_wins        += 1
            else:
                st.consecutive_losses += 1

    def reset_daily(self) -> None:
        """Call at start of each trading day to reset intraday counters."""
        with self._lock:
            self._state.daily_pnl         = 0.0
            self._state.daily_trade_count = 0

    # ── Profit locking ────────────────────────────────────────────────────

    def lock_profits(self, lock_pct: float = 0.50) -> float:
        """
        Extract `lock_pct` of unrealised profits above initial_capital.
        Locked profit is removed from current_capital (moved to safe account).

        CRITICAL FIX (C11): peak_capital is NOT reduced - it tracks the true equity
        peak. Reducing it would understate drawdown and prevent the hard halt from
        triggering when it should.

        Returns the amount locked.
        """
        with self._lock:
            st = self._state
            profit = st.current_capital - st.initial_capital
            if profit <= 0:
                return 0.0
            amount = round(profit * lock_pct, 2)
            st.current_capital -= amount
            st.locked_profit   += amount
            # CRITICAL FIX: Do NOT reduce peak_capital here. Peak capital is the
            # HIGHEST the portfolio has ever been - locking profits is a cash
            # movement, not a portfolio loss. Reducing peak_capital would
            # understate drawdown and delay the hard halt.
            log.info(
                "Profit lock: extracted Rs%.2f (%.0f%% of profit=Rs%.2f). "
                "Capital: Rs%.2f → Rs%.2f. Total locked: Rs%.2f. "
                "Peak capital preserved: Rs%.2f",
                amount, lock_pct * 100, profit,
                st.current_capital + amount, st.current_capital, st.locked_profit,
                st.peak_capital,
            )
            return amount

    # ── Safety gates ─────────────────────────────────────────────────────

    def decide_trade_allowed(self) -> tuple[bool, str]:
        """
        Hard-stop checks. Call before every potential trade.

        Returns (allowed, reason).
        """
        with self._lock:
            st = self._state

            if st.daily_pnl <= self._max_daily_loss:
                return False, (
                    f"Daily loss limit hit: {st.daily_pnl:+.2f} <= {self._max_daily_loss:+.2f}"
                )

            dd = self._drawdown_pct_unlocked(st)
            if dd >= self._max_dd:
                trip_hard_halt(
                    f"Max drawdown breached: {dd:.1%} >= {self._max_dd:.1%} "
                    f"(peak={st.peak_capital:,.0f}, current={st.current_capital:,.0f})",
                    source="CapitalManager.decide_trade_allowed",
                )
                return False, (
                    f"Max drawdown breached: {dd:.1%} >= {self._max_dd:.1%} "
                    f"(peak={st.peak_capital:,.0f}, current={st.current_capital:,.0f})"
                )

            if st.consecutive_losses >= 5:
                trip_hard_halt(
                    f"Circuit breaker: {st.consecutive_losses} consecutive losses",
                    source="CapitalManager.decide_trade_allowed",
                )
                return False, (
                    f"Circuit breaker: {st.consecutive_losses} consecutive losses"
                )

            return True, "OK"

    # ── Status ────────────────────────────────────────────────────────────

    def get_state(self) -> dict[str, Any]:
        with self._lock:
            st = self._state
            dd = self._drawdown_pct_unlocked(st)
            wr = round(st.total_wins / st.total_trades * 100, 1) if st.total_trades else 0.0
            return {
                "initial_capital":    st.initial_capital,
                "current_capital":    round(st.current_capital, 2),
                "peak_capital":       round(st.peak_capital, 2),
                "locked_profit":      round(st.locked_profit, 2),
                "daily_pnl":          round(st.daily_pnl, 2),
                "drawdown_pct":       round(dd * 100, 2),
                "consecutive_losses": st.consecutive_losses,
                "total_trades":       st.total_trades,
                "win_rate":           wr,
                "capital_return_pct": round(
                    (st.current_capital - st.initial_capital) / max(st.initial_capital, 1.0) * 100, 2
                ),
            }

    # ── Internal ─────────────────────────────────────────────────────────

    @staticmethod
    def _drawdown_pct_unlocked(st: CapitalState) -> float:
        if st.peak_capital <= 0:
            return 0.0
        return max(0.0, (st.peak_capital - st.current_capital) / st.peak_capital)

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
    "log",
]

