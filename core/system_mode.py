"""
System Mode Manager - Broker Outage / Degraded Mode Handling

Manages system operational states:
- NORMAL: All systems operational, full trading allowed
- DEGRADED: Partial functionality, reduced trading
- BROKER_DOWN: Broker unreachable, only reconciliation allowed
- MARKET_HALTED: Market closed or halted, no trading
- SAFE_MODE: Risk breach or manual intervention, no new entries

CRITICAL: This module is the single source of truth for system mode.
All trading decisions must check system mode before allowing new entries.
"""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto

from core.datetime_ist import now_ist

log = logging.getLogger("system_mode")


class SystemMode(Enum):
    """System operational mode - determines what actions are allowed."""
    NORMAL = auto()       # Full trading allowed
    DEGRADED = auto()     # Partial functionality, reduced trading
    BROKER_DOWN = auto()  # Broker unreachable, reconciliation only
    MARKET_HALTED = auto() # Market closed/halted, no trading
    SAFE_MODE = auto()    # Risk breach or manual intervention


class SystemModeReason(Enum):
    """Reason for current system mode."""
    STARTUP = "system_startup"
    BROKER_CONNECTED = "broker_connected"
    BROKER_UNREACHABLE = "broker_unreachable"
    API_ERROR = "api_error_response"
    MARKET_CLOSED = "market_closed"
    MARKET_HOLIDAY = "market_holiday"
    HARD_HALT = "hard_halt_triggered"
    MANUAL_INTERVENTION = "manual_safe_mode"
    CONSECUTIVE_LOSSES = "consecutive_loss_limit"
    DAILY_LOSS_LIMIT = "daily_loss_limit_reached"
    RECONCILIATION_FAILED = "reconciliation_failure"
    UNKNOWN = "unknown"


@dataclass
class SystemState:
    """Current system state snapshot."""
    mode: SystemMode = SystemMode.NORMAL
    reason: SystemModeReason = SystemModeReason.STARTUP
    reason_detail: str = ""
    entered_at: datetime = field(default_factory=now_ist)
    last_transition: datetime = field(default_factory=now_ist)
    consecutive_failures: int = 0
    broker_reachable: bool = True
    market_open: bool = True


class SystemModeManager:
    """
    Thread-safe system mode manager with state transitions.

    This is the central authority for what operations are allowed
    based on system state.
    """

    def __init__(
        self,
        on_mode_change: Callable[[SystemMode, SystemMode, str], None] | None = None,
        config: dict | None = None
    ):
        self._lock = threading.RLock()
        self._state = SystemState()
        self._mode_change_callback = on_mode_change
        self._config = config or {}

        # Configuration
        self._broker_failure_threshold = self._config.get("BROKER_FAILURE_THRESHOLD", 3)
        self._degraded_timeout_seconds = self._config.get("DEGRADED_TIMEOUT_SECONDS", 300)
        self._last_mode_change = now_ist()

    def get_current_mode(self) -> SystemMode:
        """Get current system mode (thread-safe)."""
        with self._lock:
            return self._state.mode

    def get_state(self) -> SystemState:
        """Get full system state (thread-safe)."""
        with self._lock:
            return SystemState(
                mode=self._state.mode,
                reason=self._state.reason,
                reason_detail=self._state.reason_detail,
                entered_at=self._state.entered_at,
                last_transition=self._state.last_transition,
                consecutive_failures=self._state.consecutive_failures,
                broker_reachable=self._state.broker_reachable,
                market_open=self._state.market_open,
            )

    def can_enter_new_trade(self) -> tuple[bool, str]:
        """
        Check if new trade entries are allowed.
        Returns (allowed, reason_if_not).
        """
        with self._lock:
            mode = self._state.mode

            if mode == SystemMode.NORMAL:
                return True, ""
            elif mode == SystemMode.DEGRADED:
                # Degraded mode allows exits but not new entries
                return False, f"System in DEGRADED mode: {self._state.reason_detail}"
            elif mode == SystemMode.BROKER_DOWN:
                return False, f"Broker unreachable: {self._state.reason_detail}"
            elif mode == SystemMode.MARKET_HALTED:
                return False, f"Market closed/halted: {self._state.reason_detail}"
            elif mode == SystemMode.SAFE_MODE:
                return False, f"SAFE_MODE active: {self._state.reason_detail}"
            else:
                return False, f"Unknown mode: {mode}"

    def can_reconcile(self) -> bool:
        """Check if reconciliation is allowed (always allowed except in SAFE_MODE if manual)."""
        with self._lock:
            # Reconciliation is allowed in all modes except possibly SAFE_MODE
            # depending on the reason
            return self._state.mode in (
                SystemMode.NORMAL,
                SystemMode.DEGRADED,
                SystemMode.BROKER_DOWN,
            )

    def can_exit_position(self) -> tuple[bool, str]:
        """Check if position exits are allowed."""
        with self._lock:
            mode = self._state.mode

            if mode in (SystemMode.NORMAL, SystemMode.DEGRADED):
                return True, ""
            elif mode == SystemMode.BROKER_DOWN:
                # Try to exit, but may fail
                return True, "Attempting exit in BROKER_DOWN mode - may fail"
            elif mode == SystemMode.MARKET_HALTED:
                return False, "Cannot exit - market halted"
            elif mode == SystemMode.SAFE_MODE:
                return True, "Exits allowed in SAFE_MODE"
            else:
                return True, ""

    def set_normal(self, reason: str = "") -> None:
        """Transition to NORMAL mode."""
        self._transition_to(SystemMode.NORMAL, SystemModeReason.BROKER_CONNECTED, reason or "Broker connected")

    def set_degraded(self, reason: str = "") -> None:
        """Transition to DEGRADED mode - partial functionality."""
        self._transition_to(SystemMode.DEGRADED, SystemModeReason.API_ERROR, reason or "Partial API failure")

    def set_broker_down(self, reason: str = "") -> None:
        """Transition to BROKER_DOWN mode - broker unreachable."""
        with self._lock:
            self._state.consecutive_failures += 1

            if self._state.consecutive_failures >= self._broker_failure_threshold:
                self._transition_to(SystemMode.BROKER_DOWN, SystemModeReason.BROKER_UNREACHABLE,
                                   reason or f"Broker unreachable after {self._state.consecutive_failures} failures")
            else:
                # Not yet at threshold - stay in degraded
                log.warning(f"Broker failure {self._state.consecutive_failures}/{self._broker_failure_threshold}")

    def set_market_halted(self, reason: str = "") -> None:
        """Transition to MARKET_HALTED mode - market closed."""
        self._transition_to(SystemMode.MARKET_HALTED, SystemModeReason.MARKET_CLOSED,
                           reason or "Market closed or halted")

    def set_safe_mode(self, reason: str = "", from_hard_halt: bool = False) -> None:
        """Transition to SAFE_MODE - risk breach or manual intervention."""
        if from_hard_halt:
            self._transition_to(SystemMode.SAFE_MODE, SystemModeReason.HARD_HALT, reason or "Hard halt triggered")
        else:
            self._transition_to(SystemMode.SAFE_MODE, SystemModeReason.MANUAL_INTERVENTION,
                               reason or "Manual safe mode intervention")

    def record_broker_success(self) -> None:
        """Record successful broker communication - may transition back to NORMAL."""
        with self._lock:
            if self._state.mode == SystemMode.BROKER_DOWN:
                self._state.consecutive_failures = 0
                self._state.broker_reachable = True
                log.info("Broker communication restored - transitioning to NORMAL")
                self._transition_to(SystemMode.NORMAL, SystemModeReason.BROKER_CONNECTED, "Broker restored")

    def record_broker_failure(self) -> None:
        """Record broker communication failure."""
        with self._lock:
            self._state.broker_reachable = False
            self.set_broker_down()

    def check_market_status(self, is_open: bool) -> None:
        """Update market status and transition if needed."""
        with self._lock:
            self._state.market_open = is_open

            if not is_open and self._state.mode == SystemMode.NORMAL:
                self._transition_to(SystemMode.MARKET_HALTED, SystemModeReason.MARKET_CLOSED, "Market closed")

    def _transition_to(self, new_mode: SystemMode, reason: SystemModeReason, detail: str) -> None:
        """Internal mode transition with callback."""
        with self._lock:
            old_mode = self._state.mode

            if old_mode == new_mode:
                # Same mode, just update detail
                self._state.reason_detail = detail
                return

            self._state.mode = new_mode
            self._state.reason = reason
            self._state.reason_detail = detail
            self._state.last_transition = now_ist()

            if new_mode == SystemMode.NORMAL:
                self._state.consecutive_failures = 0

        log.warning(f"System mode transition: {old_mode.name} -> {new_mode.name}: {detail}")

        # Notify callback
        if self._mode_change_callback:
            try:
                self._mode_change_callback(old_mode, new_mode, detail)
            except Exception as e:
                log.error(f"Mode change callback failed: {e} (type: {type(e).__name__})")

    def health_check(self) -> dict:
        """Return health check data."""
        with self._lock:
            return {
                "mode": self._state.mode.name,
                "reason": self._state.reason.value,
                "reason_detail": self._state.reason_detail,
                "broker_reachable": self._state.broker_reachable,
                "market_open": self._state.market_open,
                "consecutive_failures": self._state.consecutive_failures,
                "uptime_seconds": (now_ist() - self._state.entered_at).total_seconds(),
            }


# Singleton instance
_system_mode_manager: SystemModeManager | None = None


def get_system_mode_manager(
    on_mode_change: Callable | None = None,
    config: dict | None = None
) -> SystemModeManager:
    """Get or create the singleton SystemModeManager."""
    global _system_mode_manager
    if _system_mode_manager is None:
        _system_mode_manager = SystemModeManager(on_mode_change, config)
    return _system_mode_manager


def get_current_mode() -> SystemMode:
    """Quick access to current system mode."""
    if _system_mode_manager is None:
        return SystemMode.NORMAL
    return _system_mode_manager.get_current_mode()


def can_trade() -> tuple[bool, str]:
    """Quick check if trading is allowed."""
    if _system_mode_manager is None:
        return True, ""
    return _system_mode_manager.can_enter_new_trade()


def can_exit() -> tuple[bool, str]:
    """Quick check if exits are allowed."""
    if _system_mode_manager is None:
        return True, ""
    return _system_mode_manager.can_exit_position()


__all__ = [
    "SystemMode",
    "SystemModeManager",
    "SystemModeReason",
    "SystemState",
    "can_exit",
    "can_trade",
    "get_current_mode",
    "get_system_mode_manager",
    "log",
]

