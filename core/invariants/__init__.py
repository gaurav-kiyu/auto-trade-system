"""Domain invariant engine — runtime checks for system health and safety invariants."""

from core.invariants.checks import register_all
from core.invariants.engine import (
    InvariantCheck,
    InvariantResult,
    InvariantSeverity,
    InvariantViolation,
    check_all,
    get_violations,
    is_check_enabled,
    register_halt_callback,
    register_invariant,
    toggle_check,
)

__all__ = [
    "InvariantCheck",
    "InvariantResult",
    "InvariantSeverity",
    "InvariantViolation",
    "check_all",
    "get_violations",
    "is_check_enabled",
    "register_all",
    "register_halt_callback",
    "register_invariant",
    "toggle_check",
]
