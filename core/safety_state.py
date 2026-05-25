"""
Global Safety State — Single source of truth for process-wide safety events.

This module is the ONLY place where _HARD_HALT and _shutdown are defined.
All risk checks, broker adapters, and execution paths import from here.

CRITICAL RULE:
Never import _HARD_HALT from any other module. Always import from this module.
All _trip_hard_halt() calls must come through here.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Final

_log = logging.getLogger(__name__)

# ── Process-wide kill switches ────────────────────────────────────
# _HARD_HALT: tripped when capital breach or critical risk threshold is hit.
#             Blocks ALL new entries. Never auto-reset during session.
#             Must be manually cleared after investigation.
_HARD_HALT: Final[threading.Event] = threading.Event()

# _shutdown: graceful stop signal. Allows position monitoring to continue.
#           Set by SIGTERM/SIGINT handler or kill file detection.
_shutdown: Final[threading.Event] = threading.Event()

# ── Hard halt guardrails ─────────────────────────────────────────
# clear_hard_halt() audit trail: records who cleared it and when.
_clear_halt_history: list[dict] = []
_clear_halt_lock: threading.Lock = threading.Lock()
_LAST_CLEAR_TIME: float = 0.0  # monotonic time of last clear
_HALT_CLEAR_COOLDOWN: float = 60.0  # minimum seconds between clears

# ── Background kill file watcher ──────────────────────────────────
_KILL_FILE_POLL_INTERVAL: float = 1.0  # Check every 1 second
_kill_watcher_started: bool = False
_kill_watcher_lock: threading.Lock = threading.Lock()


def _kill_file_watcher() -> None:
    """Background thread that polls for STOP_TRADING file every second."""
    while not _shutdown.is_set():
        try:
            if is_kill_file_present():
                # Log BEFORE tripping halt — daemon thread may be killed on exit
                _log.critical("[KILL_WATCHER] STOP_TRADING file DETECTED in project root — halting immediately")
                trip_hard_halt("STOP_TRADING file found in project root", source="kill_file_watcher")
                break
        except Exception:
            pass
        _shutdown.wait(_KILL_FILE_POLL_INTERVAL)


def start_kill_file_watcher() -> None:
    """Start the background kill file polling thread (idempotent)."""
    global _kill_watcher_started
    with _kill_watcher_lock:
        if _kill_watcher_started:
            return
        _kill_watcher_started = True
        # Log fires synchronously inside _kill_file_watcher BEFORE trip_hard_halt(),
        # so even though this is a daemon thread (doesn't block main exit),
        # the halt reason is always captured in logs.
        t = threading.Thread(target=_kill_file_watcher, name="kill-file-watcher", daemon=True)
        t.start()
        _log.info("[KILL_WATCHER] Background kill file watcher started (interval=%ss)", _KILL_FILE_POLL_INTERVAL)

# Human-readable reason for the most recent hard halt trip.
_hard_halt_reason: str = ""


def is_hard_halted() -> bool:
    """Return True if hard halt is active."""
    return _HARD_HALT.is_set()


def is_shutting_down() -> bool:
    """Return True if graceful shutdown is in progress."""
    return _shutdown.is_set()


def trip_hard_halt(reason: str, *, source: str = "") -> None:
    """
    CRITICAL: Trip the hard halt kill-switch.

    Blocks ALL new trade entries across all threads.
    Must only be called from risk denial paths.
    Log the reason before tripping.

    Args:
        reason: Human-readable explanation for the halt.
        source: Module/function name that triggered the halt.
    """
    global _hard_halt_reason
    if _HARD_HALT.is_set():
        return  # Already halted — no double-trip
    _hard_halt_reason = f"[{source}] {reason}" if source else reason
    _HARD_HALT.set()
    # NOTE: logging here would cause circular import in some contexts.
    # Caller is responsible for logging before calling this function.


# ── Centralized consecutive loss counter ────────────────────────────
# Multiple risk engines track consecutive losses independently.
# This is the single source of truth.
_consecutive_losses: int = 0
_consecutive_losses_lock = threading.Lock()


def get_consecutive_losses() -> int:
    """Return the centralized consecutive loss count."""
    with _consecutive_losses_lock:
        return _consecutive_losses


def record_trade_outcome(was_profit: bool) -> int:
    """
    Record a trade outcome and update the centralized consecutive loss counter.

    Args:
        was_profit: True if the trade was profitable, False otherwise.

    Returns:
        The updated consecutive loss count.
    """
    global _consecutive_losses
    with _consecutive_losses_lock:
        if was_profit:
            _consecutive_losses = 0
        else:
            _consecutive_losses += 1
        return _consecutive_losses


def reset_consecutive_losses() -> None:
    """Reset the consecutive loss counter (e.g. at session start)."""
    global _consecutive_losses
    with _consecutive_losses_lock:
        _consecutive_losses = 0


# ── Intraday P&L monitoring ────────────────────────────────────────
# Running P&L tracked throughout the session. Used to trip hard halt
# when intraday loss limit is breached (before MAX_DAILY_LOSS).
_intraday_pnl: float = 0.0
_intraday_pnl_lock = threading.Lock()
_intraday_loss_limit: float = -float("inf")  # set via set_intraday_loss_limit()


def set_intraday_pnl(pnl: float) -> None:
    """Update the running intraday P&L."""
    global _intraday_pnl
    with _intraday_pnl_lock:
        _intraday_pnl = pnl


def get_intraday_pnl() -> float:
    """Return the current intraday P&L."""
    with _intraday_pnl_lock:
        return _intraday_pnl


def set_intraday_loss_limit(limit: float) -> None:
    """Set the intraday loss limit (negative number)."""
    global _intraday_loss_limit
    _intraday_loss_limit = -abs(limit)


def get_intraday_loss_limit() -> float:
    """Return the intraday loss limit."""
    return _intraday_loss_limit


def check_intraday_pnl_and_halt(*, source: str = "intraday_pnl_monitor") -> bool:
    """
    Check if intraday P&L has breached the loss limit.
    Trips hard halt if breached.

    Returns:
        True if hard halt was tripped, False otherwise.
    """
    if is_hard_halted():
        return True
    limit = _intraday_loss_limit
    if limit == -float("inf"):
        return False  # no limit configured
    pnl = get_intraday_pnl()
    if pnl < limit:
        trip_hard_halt(
            f"Intraday loss limit breached: P&L={pnl:.0f} < limit={limit:.0f}",
            source=source,
        )
        return True
    return False


def reset_intraday_pnl() -> None:
    """Reset intraday P&L at session start."""
    global _intraday_pnl
    with _intraday_pnl_lock:
        _intraday_pnl = 0.0


def clear_hard_halt(*, source: str = "operator", reason: str = "manual clear") -> None:
    """
    Clear the hard halt (manual intervention required).

    SECURITY: Requires explicit source and reason.
    Audit trail: records who cleared it and when.
    Cooldown: minimum {_HALT_CLEAR_COOLDOWN}s between clears.

    Must only be called by the operator after reviewing the halt reason.

    Args:
        source: Who/what cleared the halt (e.g. "operator", "web_dashboard", "admin_api")
        reason: Why the halt was cleared
    """
    global _hard_halt_reason, _LAST_CLEAR_TIME
    with _clear_halt_lock:
        now = time.monotonic()
        if now - _LAST_CLEAR_TIME < _HALT_CLEAR_COOLDOWN:
            remaining = _HALT_CLEAR_COOLDOWN - (now - _LAST_CLEAR_TIME)
            _log.warning(
                "[SAFETY] clear_hard_halt blocked by cooldown: %.0fs remaining (source=%s)",
                remaining, source,
            )
            return
        previous_reason = _hard_halt_reason
        _HARD_HALT.clear()
        _hard_halt_reason = ""
        _LAST_CLEAR_TIME = now
        _clear_halt_history.append({
            "timestamp": time.time(),
            "source": source,
            "reason": reason,
            "previous_halt_reason": previous_reason,
        })
        # Keep only last 100 entries
        if len(_clear_halt_history) > 100:
            _clear_halt_history.pop(0)
        _log.warning(
            "[SAFETY] Hard halt CLEARED by %s (reason: %s). Previous halt: %s",
            source, reason, previous_reason,
        )


def request_shutdown(reason: str = "User requested shutdown") -> None:
    """
    Signal graceful shutdown. Positions are allowed to be monitored/closed.

    Shutdown sequence:
      1. Set _shutdown event (blocks new entries)
      2. Execute all registered shutdown callbacks (drain queues, flush state,
         cancel pending orders, close DB connections)

    Args:
        reason: Why shutdown was requested.
    """
    if _shutdown.is_set():
        return
    _shutdown.set()
    # Execute registered shutdown callbacks from python_runtime
    try:
        from core.python_runtime import execute_shutdown
        execute_shutdown()
    except Exception as exc:
        _log.warning("[SHUTDOWN] Error during callback execution: %s", exc)


def hard_halt_reason() -> str:
    """Return the current hard halt reason."""
    return _hard_halt_reason


# ── Kill-file checker (for emergency stop) ─────────────────────────
def is_kill_file_present() -> bool:
    """Check if STOP_TRADING file exists in project root."""
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    return (root / "STOP_TRADING").exists()


def check_kill_file_and_halt() -> None:
    """If kill file is present, trip hard halt."""
    if is_kill_file_present():
        trip_hard_halt("STOP_TRADING file found in project root", source="kill_file_check")
