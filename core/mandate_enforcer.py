"""
PRODUCTION MANDATE ENFORCER v2.50
Wired directly into execution path - not decorative config
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from core.datetime_ist import now_ist
from core.safety_state import trip_hard_halt as _trip_hard_halt

_log = logging.getLogger(__name__)


@dataclass
class MandateState:
    capital: float = 5000.0
    equity_peak: float = 5000.0
    daily_pnl: float = 0.0
    weekly_pnl: float = 0.0
    loss_streak: int = 0
    last_trade_time: datetime | None = None
    trades_today: int = 0
    last_event_time: datetime | None = None
    vix: float = 20.0
    data_stale_seconds: int = 0
    is_hard_halted: bool = False


class ProductionMandateEnforcer:
    """
    Real enforcement - this is what actually controls trading.
    No decorative config - every check is wired to execution.
    """

    def __init__(self, config: dict):
        self._cfg = config
        self._state = MandateState(
            capital=config.get("BASE_CAPITAL", 5000),
            equity_peak=config.get("BASE_CAPITAL", 5000),
        )

    def update_market(self, vix: float, data_age_seconds: int):
        self._state.vix = vix
        self._state.data_stale_seconds = data_age_seconds

    def update_capital(self, capital: float, daily_pnl: float, weekly_pnl: float):
        self._state.capital = capital
        self._state.daily_pnl = daily_pnl
        self._state.weekly_pnl = weekly_pnl
        if capital > self._state.equity_peak:
            self._state.equity_peak = capital

    def record_trade(self, pnl: float):
        if pnl < 0:
            self._state.loss_streak += 1
            if self._state.loss_streak >= 3:
                self._trigger_hard_halt("3 consecutive losses")
        else:
            self._state.loss_streak = 0
        self._state.last_trade_time = now_ist()
        self._state.trades_today += 1

    def reset_daily(self):
        self._state.trades_today = 0

    def _trigger_hard_halt(self, reason: str):
        self._state.is_hard_halted = True
        _log.critical(f"MANDATE HARD HALT: {reason}")
        _trip_hard_halt(reason, source="ProductionMandateEnforcer")

    # =================================================================
    # ACTUAL ENFORCEMENT METHODS - CALLED FROM EXECUTION PATH
    # =================================================================

    def can_trade(self) -> tuple[bool, str]:
        """Primary gate - called before EVERY potential trade"""
        if self._state.is_hard_halted:
            return False, "HARD_HALT: System halted"

        max_dd = float(self._cfg.get("MANDATE_MAX_DRAWDOWN_PROTECTION", 0.12))
        drawdown = (self._state.equity_peak - self._state.capital) / self._state.equity_peak
        if drawdown >= max_dd:
            self._trigger_hard_halt(f"Max drawdown {max_dd:.0%} reached")
            return False, f"MAX_DRAWDOWN: {max_dd:.0%} protection triggered"

        daily_loss_pct = -self._state.daily_pnl / self._state.capital
        if daily_loss_pct >= 0.025:
            return False, f"DAILY_STOP: 2.5% hit ({daily_loss_pct:.1%})"

        weekly_loss_pct = -self._state.weekly_pnl / self._state.capital
        if weekly_loss_pct >= 0.05:
            self._trigger_hard_halt("Weekly circuit breaker 5% hit")
            return False, "WEEKLY_CIRCUIT: 5% hit - trading halted"

        if self._state.loss_streak >= 3 and self._state.last_trade_time:
            cooldown = self._state.last_trade_time + timedelta(hours=2)
            if now_ist() < cooldown:
                return False, "LOSS_STREAK_COOLDOWN: 2 hours"

        if self._state.vix >= 30:
            return False, f"VIX_HARD_BLOCK: {self._state.vix} >= 30"

        if self._state.data_stale_seconds >= 30:
            return False, f"DATA_STALE: {self._state.data_stale_seconds}s"

        return True, "MANDATE_CHECK_PASSED"

    def get_position_size(
        self,
        entry_price: float,
        regime: str,
        sl_pct: float = 0.12,
    ) -> int:
        """
        Calculate position size based on ACTUAL mandate risk rules.
        NOT hardcoded - uses 1.5% base with regime adjustments.

        CRITICAL: Returns 0 if capital is zero or negative to prevent
        division by zero and NaN propagation.
        """
        # CRITICAL FIX: Guard against zero/negative capital
        if self._state.capital <= 0:
            _log.warning(f"Position sizing blocked: capital = {self._state.capital} <= 0")
            return 0

        base_risk_pct = 0.015  # 1.5% as mandated

        reg = (regime or "").upper()
        if reg in ["TRENDING", "BULLISH"]:
            risk_mult = 1.2
        elif reg in ["SIDEWAYS", "NEUTRAL"]:
            risk_mult = 0.85
        elif reg in ["RANGE", "CHOPPY"]:
            risk_mult = 0.75
        else:
            risk_mult = 0.5  # Unknown regime = reduced

        effective_risk = base_risk_pct * risk_mult
        risk_amount = self._state.capital * effective_risk
        risk_per_lot = entry_price * sl_pct

        if risk_per_lot > 0:
            lots = int(risk_amount / risk_per_lot)
            return max(1, min(lots, 25))  # Cap at 25, minimum 1

        return 1

    def get_max_daily_loss(self) -> float:
        """Daily stop as 2.5% of current capital - NOT fixed"""
        return -self._state.capital * 0.025

    def get_max_trades_today(self) -> int:
        """Operating mode based on VIX and conditions"""
        if self._state.vix > 28 or self._state.loss_streak >= 2:
            return 1
        elif self._state.vix > 20:
            return 2
        return 4

    def should_skip_first_20_min(self) -> bool:
        """Skip first 20 minutes as mandated"""
        now = now_ist()
        current_mins = now.hour * 60 + now.minute
        market_open_mins = 9 * 60 + 20  # 9:20 IST
        return current_mins < market_open_mins + 20

    def should_skip_last_45_min(self) -> bool:
        """Skip last 45 minutes as mandated"""
        now = now_ist()
        current_mins = now.hour * 60 + now.minute
        market_close_mins = 15 * 60 + 20  # 15:20 IST
        return current_mins > market_close_mins - 45

    def is_in_trading_window(self) -> bool:
        """Only 9:20-11:30 and 13:00-14:45 IST"""
        now = now_ist()

        morning_start = 9 * 60 + 20
        morning_end = 11 * 60 + 30
        afternoon_start = 13 * 60
        afternoon_end = 14 * 60 + 45

        current = now.hour * 60 + now.minute
        return (morning_start <= current <= morning_end) or (afternoon_start <= current <= afternoon_end)

    def get_min_score(self, regime: str) -> int:
        """Score thresholds by regime as mandated"""
        reg = (regime or "").upper()
        if reg in ["TRENDING", "BULLISH"]:
            return 68
        elif reg in ["SIDEWAYS", "NEUTRAL"]:
            return 73
        elif reg in ["RANGE", "CHOPPY"]:
            return 78
        return 73

    def should_block_false_signal(self, score: int, iv_rank: float) -> bool:
        """False signal suppression: score >=75 AND IV > 26"""
        return score >= 75 and iv_rank > 26

    def get_status(self) -> dict:
        """For observability - what's the current state?"""
        return {
            "capital": self._state.capital,
            "equity_peak": self._state.equity_peak,
            "drawdown_pct": (self._state.equity_peak - self._state.capital) / self._state.equity_peak,
            "daily_pnl": self._state.daily_pnl,
            "loss_streak": self._state.loss_streak,
            "vix": self._state.vix,
            "hard_halted": self._state.is_hard_halted,
            "trades_today": self._state.trades_today,
        }


_production_enforcer: ProductionMandateEnforcer | None = None


def get_mandate_enforcer(config: dict = None) -> ProductionMandateEnforcer:
    """Singleton - one enforcer for entire system"""
    global _production_enforcer
    if _production_enforcer is None:
        if config is None:
            config = {"BASE_CAPITAL": 5000}
        _production_enforcer = ProductionMandateEnforcer(config)
    return _production_enforcer


def reset_mandate_enforcer():
    """For testing / restart"""
    global _production_enforcer
    _production_enforcer = None
