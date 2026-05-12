"""
Global Safety State — Single source of truth for process-wide safety events.

This module is the ONLY place where _HARD_HALT and _shutdown are defined.
All risk checks, broker adapters, and execution paths import from here.

CRITICAL RULE:
Never import _HARD_HALT from any other module. Always import from this module.
All _trip_hard_halt() calls must come through here.
"""
from __future__ import annotations

import threading
import time
from typing import Final

# ── Process-wide kill switches ────────────────────────────────────
# _HARD_HALT: tripped when capital breach or critical risk threshold is hit.
#             Blocks ALL new entries. Never auto-reset during session.
#             Must be manually cleared after investigation.
_HARD_HALT: Final[threading.Event] = threading.Event()

# _shutdown: graceful stop signal. Allows position monitoring to continue.
#           Set by SIGTERM/SIGINT handler or kill file detection.
_shutdown: Final[threading.Event] = threading.Event()

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


def clear_hard_halt() -> None:
    """
    Clear the hard halt (manual intervention required).

    Must only be called by the operator after reviewing the halt reason.
    """
    global _hard_halt_reason
    _HARD_HALT.clear()
    _hard_halt_reason = ""


def request_shutdown(reason: str = "User requested shutdown") -> None:
    """
    Signal graceful shutdown. Positions are allowed to be monitored/closed.

    Args:
        reason: Why shutdown was requested.
    """
    if _shutdown.is_set():
        return
    _shutdown.set()


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