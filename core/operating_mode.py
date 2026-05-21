"""
AD-KIYU Operating Mode Manager v1.0

Defines and enforces the system operating mode:
- SIGNAL_ONLY (default): Generate signals only, never execute trades
- BACKTEST: Run against historical data, no live broker
- PAPER: Paper broker, simulated fills
- SHADOW: Follow live but do not submit real orders
- LIVE_MANUAL_CONFIRM: Live broker, requires human approval per trade
- FULL_AUTO: Fully autonomous execution (requires explicit enable)

Safety rules:
- FULL_AUTO requires --enable-full-auto CLI flag OR ENABLE_FULL_AUTO=true env
- Default mode is SIGNAL_ONLY
- Every execute_order() call MUST pass through mode_manager
- Mode transitions are audited and irreversible for the session
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from core.datetime_ist import now_ist

_log = logging.getLogger(__name__)


class OperatingMode(Enum):
    """Operating modes in order of increasing execution authority."""
    SIGNAL_ONLY = "SIGNAL_ONLY"
    BACKTEST = "BACKTEST"
    PAPER = "PAPER"
    SHADOW = "SHADOW"
    LIVE_MANUAL_CONFIRM = "LIVE_MANUAL_CONFIRM"
    FULL_AUTO = "FULL_AUTO"


# Desired mode-to-authority mapping
_MODE_AUTHORITY: dict[OperatingMode, int] = {
    OperatingMode.SIGNAL_ONLY: 0,
    OperatingMode.BACKTEST: 1,
    OperatingMode.PAPER: 2,
    OperatingMode.SHADOW: 3,
    OperatingMode.LIVE_MANUAL_CONFIRM: 4,
    OperatingMode.FULL_AUTO: 5,
}


class ExecutionAction(Enum):
    """Actions that can be gated by mode."""
    GENERATE_SIGNAL = "GENERATE_SIGNAL"
    EVALUATE_RISK = "EVALUATE_RISK"
    SUBMIT_ORDER = "SUBMIT_ORDER"
    CANCEL_ORDER = "CANCEL_ORDER"
    MODIFY_POSITION = "MODIFY_POSITION"
    CLOSE_ALL = "CLOSE_ALL"


# Minimum modes required for each action
_ACTION_MIN_MODE: dict[ExecutionAction, OperatingMode] = {
    ExecutionAction.GENERATE_SIGNAL: OperatingMode.SIGNAL_ONLY,
    ExecutionAction.EVALUATE_RISK: OperatingMode.SIGNAL_ONLY,
    ExecutionAction.SUBMIT_ORDER: OperatingMode.PAPER,
    ExecutionAction.CANCEL_ORDER: OperatingMode.PAPER,
    ExecutionAction.MODIFY_POSITION: OperatingMode.PAPER,
    ExecutionAction.CLOSE_ALL: OperatingMode.SIGNAL_ONLY,
}

# Minimum modes required for each action to reach a LIVE broker
_ACTION_LIVE_MIN_MODE: dict[ExecutionAction, OperatingMode] = {
    ExecutionAction.SUBMIT_ORDER: OperatingMode.LIVE_MANUAL_CONFIRM,
    ExecutionAction.CANCEL_ORDER: OperatingMode.LIVE_MANUAL_CONFIRM,
}


@dataclass
class ModeTransition:
    timestamp: datetime
    from_mode: OperatingMode
    to_mode: OperatingMode
    reason: str
    authorized_by: str = "system"


class OperatingModeViolationError(Exception):
    """Raised when an action is attempted in a mode that does not allow it."""


class OperatingModeManager:
    """Thread-safe manager for system operating mode with strict transitions."""

    def __init__(
        self,
        initial_mode: OperatingMode = OperatingMode.SIGNAL_ONLY,
        enable_full_auto: bool = False,
        max_history: int = 100,
    ):
        self._lock = threading.RLock()
        self._mode: OperatingMode = initial_mode
        self._enable_full_auto = enable_full_auto
        self._history: list[ModeTransition] = []
        self._max_history = max_history
        self._frozen = False  # Once frozen, mode cannot change

        _log.info("Operating mode initialized to %s (full_auto_allowed=%s)", initial_mode.value, enable_full_auto)

    @property
    def current_mode(self) -> OperatingMode:
        with self._lock:
            return self._mode

    @property
    def is_frozen(self) -> bool:
        with self._lock:
            return self._frozen

    def _record_transition(self, to_mode: OperatingMode, reason: str, authorized_by: str) -> None:
        self._history.append(ModeTransition(
            timestamp=now_ist(),
            from_mode=self._mode,
            to_mode=to_mode,
            reason=reason,
            authorized_by=authorized_by,
        ))
        if len(self._history) > self._max_history:
            self._history.pop(0)

    def set_mode(self, mode: OperatingMode, reason: str = "", authorized_by: str = "system") -> None:
        """Transition to a new operating mode."""
        with self._lock:
            if self._frozen:
                raise OperatingModeViolationError(f"Cannot change mode: manager is frozen at {self._mode.value}")

            if mode == OperatingMode.FULL_AUTO and not self._enable_full_auto:
                raise OperatingModeViolationError(
                    "FULL_AUTO mode requires --enable-full-auto flag or ENABLE_FULL_AUTO=true"
                )

            old_mode = self._mode
            self._mode = mode
            self._record_transition(mode, reason, authorized_by)
            _log.info("Mode transition: %s → %s (reason=%s, by=%s)", old_mode.value, mode.value, reason, authorized_by)

    def requires_live_broker(self) -> bool:
        """Returns True if current mode requires a real broker connection."""
        with self._lock:
            return self._mode in (OperatingMode.LIVE_MANUAL_CONFIRM, OperatingMode.FULL_AUTO)

    def allows_execution(self) -> tuple[bool, str]:
        """Check if order execution is allowed in current mode."""
        with self._lock:
            mode = self._mode
            if mode == OperatingMode.SIGNAL_ONLY:
                return False, "SIGNAL_ONLY: Signal generation only, no execution"
            if mode == OperatingMode.BACKTEST:
                return False, "BACKTEST: Historical simulation, no live execution"
            if mode == OperatingMode.PAPER:
                return True, "PAPER: Paper execution allowed"
            if mode == OperatingMode.SHADOW:
                return True, "SHADOW: Shadow execution allowed (no real orders)"
            if mode == OperatingMode.LIVE_MANUAL_CONFIRM:
                return True, "LIVE_MANUAL_CONFIRM: Requires manual approval"
            if mode == OperatingMode.FULL_AUTO:
                return True, "FULL_AUTO: Full auto execution"
            return False, f"Unknown mode: {mode}"

    def allows_live_execution(self) -> tuple[bool, str]:
        """Check if LIVE broker execution is allowed in current mode."""
        with self._lock:
            mode = self._mode
            if mode == OperatingMode.LIVE_MANUAL_CONFIRM:
                return True, "LIVE_MANUAL_CONFIRM: Live execution with manual approval"
            if mode == OperatingMode.FULL_AUTO:
                return True, "FULL_AUTO: Live auto execution"
            return False, f"{mode.value}: Live execution not allowed in this mode"

    def requires_manual_approval(self) -> bool:
        """Returns True if current mode requires manual approval per trade."""
        with self._lock:
            return self._mode == OperatingMode.LIVE_MANUAL_CONFIRM

    def can_perform(self, action: ExecutionAction) -> tuple[bool, str]:
        """Check if a specific action is allowed in current mode."""
        with self._lock:
            mode = self._mode
            min_mode = _ACTION_MIN_MODE.get(action)
            if min_mode and _MODE_AUTHORITY.get(mode, 0) < _MODE_AUTHORITY.get(min_mode, 0):
                return False, f"{mode.value}: {action.value} requires at least {min_mode.value}"
            return True, ""

    def can_perform_live(self, action: ExecutionAction) -> tuple[bool, str]:
        """Check if a specific action can reach a LIVE broker."""
        with self._lock:
            mode = self._mode
            min_live = _ACTION_LIVE_MIN_MODE.get(action)
            if min_live and _MODE_AUTHORITY.get(mode, 0) < _MODE_AUTHORITY.get(min_live, 0):
                return False, f"{mode.value}: LIVE {action.value} requires at least {min_live.value}"
            return True, ""

    def freeze(self) -> None:
        """Freeze the current mode. No further transitions allowed."""
        with self._lock:
            self._frozen = True
            _log.warning("Operating mode frozen at %s", self._mode.value)

    def get_history(self) -> list[ModeTransition]:
        with self._lock:
            return list(self._history)

    def get_state(self) -> dict:
        with self._lock:
            return {
                "mode": self._mode.value,
                "enable_full_auto": self._enable_full_auto,
                "frozen": self._frozen,
                "requires_live_broker": self._mode in (OperatingMode.LIVE_MANUAL_CONFIRM, OperatingMode.FULL_AUTO),
                "allows_execution": self._mode
                    not in (OperatingMode.SIGNAL_ONLY, OperatingMode.BACKTEST),
                "transition_count": len(self._history),
            }
