"""
AD-KIYU Invariant Engine v1.0

Continuously enforces system invariants at runtime:
- Broker positions == local positions
- Exactly one risk engine active
- Exactly one strategy orchestrator active
- No retry after UNKNOWN state
- No stale data used for trading
- No execution without risk approval
- Mode prevents inappropriate execution
- No duplicate submissions

Violation path: AUDIT_WARN → HARD_HALT escalation
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable

from core.datetime_ist import now_ist

_log = logging.getLogger(__name__)


class InvariantSeverity(Enum):
    WARN = "WARN"
    BLOCK = "BLOCK"
    HALT = "HALT"


class InvariantResult(Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    ERROR = "ERROR"


@dataclass
class InvariantCheck:
    name: str
    description: str
    severity: InvariantSeverity
    last_result: InvariantResult = InvariantResult.PASS
    last_checked: datetime | None = None
    failure_count: int = 0
    last_message: str = ""
    check_fn: Callable[[], tuple[bool, str]] | None = None


@dataclass
class InvariantViolation:
    timestamp: datetime
    check_name: str
    severity: InvariantSeverity
    message: str
    resolved: bool = False
    resolved_at: datetime | None = None


_INVARIANTS: list[InvariantCheck] = []
_lock = threading.Lock()
_violations: list[InvariantViolation] = []
_max_violations = 1000
_halt_callback: Callable[[str], None] | None = None


def register_halt_callback(cb: Callable[[str], None]) -> None:
    global _halt_callback
    _halt_callback = cb


def register_invariant(
    name: str,
    description: str,
    severity: InvariantSeverity,
    check_fn: Callable[[], tuple[bool, str]],
) -> None:
    with _lock:
        for i, inv in enumerate(_INVARIANTS):
            if inv.name == name:
                _INVARIANTS[i] = InvariantCheck(
                    name=name, description=description,
                    severity=severity, check_fn=check_fn,
                )
                return
        _INVARIANTS.append(InvariantCheck(
            name=name, description=description,
            severity=severity, check_fn=check_fn,
        ))


def check_all() -> list[InvariantCheck]:
    """Run all registered invariant checks and return results."""
    global _violations
    results = []
    with _lock:
        for inv in _INVARIANTS:
            try:
                passed, message = inv.check_fn()
                now = now_ist()
                inv.last_checked = now
                inv.last_result = InvariantResult.PASS if passed else InvariantResult.FAIL
                inv.last_message = message

                if not passed:
                    inv.failure_count += 1
                    _violations.append(InvariantViolation(
                        timestamp=now,
                        check_name=inv.name,
                        severity=inv.severity,
                        message=message,
                    ))
                    if len(_violations) > _max_violations:
                        _violations.pop(0)

                    if inv.severity == InvariantSeverity.HALT:
                        _log.critical("INVARIANT HALT: %s — %s", inv.name, message)
                        if _halt_callback:
                            _halt_callback(f"INVARIANT_HALT: {inv.name} — {message}")

                results.append(inv)
            except Exception as e:
                inv.last_result = InvariantResult.ERROR
                inv.last_message = str(e)
                inv.last_checked = now_ist()
                results.append(inv)

    return results


def get_violations(unresolved_only: bool = False) -> list[InvariantViolation]:
    with _lock:
        if unresolved_only:
            return [v for v in _violations if not v.resolved]
        return list(_violations)


def resolve_violation(check_name: str) -> None:
    with _lock:
        for v in _violations:
            if v.check_name == check_name and not v.resolved:
                v.resolved = True
                v.resolved_at = now_ist()


def get_state() -> dict:
    with _lock:
        return {
            "checks": [
                {
                    "name": inv.name,
                    "severity": inv.severity.value,
                    "last_result": inv.last_result.value,
                    "last_message": inv.last_message,
                    "failure_count": inv.failure_count,
                    "last_checked": str(inv.last_checked) if inv.last_checked else None,
                }
                for inv in _INVARIANTS
            ],
            "violations": [
                {
                    "timestamp": str(v.timestamp),
                    "check": v.check_name,
                    "severity": v.severity.value,
                    "message": v.message,
                    "resolved": v.resolved,
                }
                for v in _violations[-50:]
            ],
            "violation_count": len(_violations),
        }
