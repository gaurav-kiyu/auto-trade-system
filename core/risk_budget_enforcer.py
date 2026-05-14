"""
Risk Budget Enforcer - Non-negotiable risk rules from mandate
PART 3 - Hard stops, circuit breakers, drawdown protection
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional
import logging

_log = logging.getLogger(__name__)


@dataclass
class RiskBudgetConfig:
    daily_hard_stop: float = 0.025
    weekly_circuit_breaker: float = 0.05
    max_drawdown_protection: float = 0.12
    loss_streak_cooldown_hours: float = 2.0
    max_positions: int = 2
    event_cooldown_minutes: int = 30
    loss_streak_threshold: int = 3


class RiskState:
    NORMAL = "NORMAL"
    DAILY_STOP_HIT = "DAILY_STOP_HIT"
    WEEKLY_CIRCUIT = "WEEKLY_CIRCUIT"
    DRAWDOWN_PROTECTION = "DRAWDOWN_PROTECTION"
    LOSS_STREAK_COOLDOWN = "LOSS_STREAK_COOLDOWN"
    EVENT_COOLDOWN = "EVENT_COOLDOWN"
    HARD_HALT = "HARD_HALT"


class RiskBudgetEnforcer:
    def __init__(self, config: dict):
        self.cfg = self._load_config(config)
        self._capital: float = config.get("BASE_CAPITAL", 5000)
        self._equity_peak: float = config.get("BASE_CAPITAL", 5000)
        self._daily_loss: float = 0.0
        self._weekly_loss: float = 0.0
        self._loss_streak: int = 0
        self._last_trade_time: Optional[datetime] = None
        self._last_event_time: Optional[datetime] = None
        self._current_state: str = RiskState.NORMAL
        self._hard_halt_active: bool = False

    def _load_config(self, config: dict) -> RiskBudgetConfig:
        return RiskBudgetConfig(
            daily_hard_stop=config.get("MANDATE_DAILY_HARD_STOP", 0.025),
            weekly_circuit_breaker=config.get("MANDATE_WEEKLY_CIRCUIT_BREAKER", 0.05),
            max_drawdown_protection=config.get("MANDATE_MAX_DRAWDOWN_PROTECTION", 0.12),
            loss_streak_cooldown_hours=config.get("MANDATE_LOSS_STREAK_COOLDOWN_HOURS", 2.0),
            max_positions=config.get("MANDATE_MAX_POSITIONS_SAME_TIME", 2),
            event_cooldown_minutes=config.get("MANDATE_EVENT_COOLDOWN_MINUTES", 30),
            loss_streak_threshold=config.get("MANDATE_LOSS_STREAK_THRESHOLD", 3),
        )

    def update_capital(self, capital: float, daily_pnl: float, weekly_pnl: float):
        self._capital = capital
        self._daily_loss = -daily_pnl if daily_pnl < 0 else 0
        self._weekly_loss = -weekly_pnl if weekly_pnl < 0 else 0

        if capital > self._equity_peak:
            self._equity_peak = capital

    def record_trade_result(self, pnl: float, timestamp: datetime):
        if pnl < 0:
            self._loss_streak += 1
        else:
            self._loss_streak = 0

        if self._loss_streak >= self.cfg.loss_streak_threshold:
            self._trigger_hard_halt(f"Loss streak: {self.cfg.loss_streak_threshold} consecutive losses")

        self._last_trade_time = timestamp

    def _trigger_hard_halt(self, reason: str):
        self._hard_halt_active = True
        self._current_state = RiskState.HARD_HALT
        _log.critical(f"HARD HALT TRIGGERED: {reason}")

    def can_trade(self) -> tuple[bool, str]:
        if self._hard_halt_active:
            return False, f"HARD HALT ACTIVE: {self._current_state}"

        drawdown = (self._equity_peak - self._capital) / self._equity_peak if self._equity_peak > 0 else 0
        if drawdown >= self.cfg.max_drawdown_protection:
            self._current_state = RiskState.DRAWDOWN_PROTECTION
            return False, f"Max drawdown protection triggered: {drawdown:.1%}"

        daily_loss_pct = self._daily_loss / self._capital if self._capital > 0 else 0
        if daily_loss_pct >= self.cfg.daily_hard_stop:
            self._current_state = RiskState.DAILY_STOP_HIT
            return False, f"Daily hard stop hit: {daily_loss_pct:.1%}"

        weekly_loss_pct = self._weekly_loss / self._capital if self._capital > 0 else 0
        if weekly_loss_pct >= self.cfg.weekly_circuit_breaker:
            self._current_state = RiskState.WEEKLY_CIRCUIT
            return False, f"Weekly circuit breaker hit: {weekly_loss_pct:.1%}"

        if self._loss_streak >= self.cfg.loss_streak_threshold:
            if self._last_trade_time:
                cooldown_end = self._last_trade_time + timedelta(hours=self.cfg.loss_streak_cooldown_hours)
                if datetime.utcnow() < cooldown_end:
                    remaining = (cooldown_end - datetime.utcnow()).total_seconds() / 60
                    self._current_state = RiskState.LOSS_STREAK_COOLDOWN
                    return False, f"Loss streak cooldown: {remaining:.0f} min remaining"

        if self._last_event_time:
            event_cooldown_end = self._last_event_time + timedelta(minutes=self.cfg.event_cooldown_minutes)
            if datetime.utcnow() < event_cooldown_end:
                self._current_state = RiskState.EVENT_COOLDOWN
                return False, "High-impact event cooldown active"

        self._current_state = RiskState.NORMAL
        return True, "Risk checks passed"

    def record_event(self, event_type: str, timestamp: datetime = None):
        if timestamp is None:
            timestamp = datetime.utcnow()
        if event_type.upper() in ["RBI", "CPI", "FOMC", "BUDGET", "EXPIRY"]:
            self._last_event_time = timestamp
            _log.info(f"Recorded high-impact event: {event_type}")

    def get_current_state(self) -> str:
        return self._current_state

    def get_risk_metrics(self) -> dict:
        drawdown = (self._equity_peak - self._capital) / self._equity_peak if self._equity_peak > 0 else 0
        daily_loss_pct = self._daily_loss / self._capital if self._capital > 0 else 0
        return {
            "current_capital": self._capital,
            "equity_peak": self._equity_peak,
            "drawdown_pct": drawdown,
            "daily_loss_pct": daily_loss_pct,
            "loss_streak": self._loss_streak,
            "state": self._current_state,
            "hard_halt_active": self._hard_halt_active,
        }

    def reset_daily(self):
        self._daily_loss = 0.0

    def reset_weekly(self):
        self._weekly_loss = 0.0

    def reset_hard_halt(self):
        self._hard_halt_active = False
        self._loss_streak = 0
        self._current_state = RiskState.NORMAL

    def get_max_position_size_pct(self) -> float:
        drawdown = (self._equity_peak - self._capital) / self._equity_peak if self._equity_peak > 0 else 0

        if self._current_state == RiskState.HARD_HALT:
            return 0.0
        if drawdown > 0.08:
            return 0.0
        if self._current_state in [RiskState.DAILY_STOP_HIT, RiskState.WEEKLY_CIRCUIT]:
            return 0.0
        if drawdown > 0.05:
            return 0.5
        if self._loss_streak >= 2:
            return 0.75

        return 1.0


def create_risk_budget_enforcer(config: dict) -> RiskBudgetEnforcer:
    return RiskBudgetEnforcer(config)