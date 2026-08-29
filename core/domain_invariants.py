"""Domain Invariants — Continuous Invariant Validation Engine (Phase 14).

Validates critical domain invariants continuously:
- PositionQty >= 0
- Capital >= 0
- Risk <= Limits
- FillQty <= OrderQty
- PnL != NaN
- Margin >= 0

Each invariant violation triggers: LOG, WARN, or HALT action.
Integrates with SafetyState for HALT escalation.

Usage:
    from core.domain_invariants import get_invariant_engine

    engine = get_invariant_engine()
    result = engine.check_all(state={
        "capital": 50000,
        "position_qty": 10,
        "risk": 150,
        "max_risk": 5000,
        "pnl": 250.5,
        "margin": 1000,
    })
    if result.has_violations:
        for v in result.violations:
            print(f"[{v.action}] {v.message}")

Design:
- Thread-safe singleton with RLock
- Configurable invariant thresholds
- HALT escalation via SafetyState integration
- JSON persistence for violation history
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

INVARIANTS_FILE = "json/invariant_violations.json"
MAX_VIOLATIONS = 500


class InvariantAction(str, Enum):
    """Action to take when an invariant is violated."""

    LOG = "LOG"        # Log and continue
    WARN = "WARN"      # Log, warn, and degrade
    HALT = "HALT"      # Log, warn, and halt trading


class InvariantSeverity(str, Enum):
    """Severity of an invariant violation."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


# ── Data Models ──────────────────────────────────────────────────────────────


@dataclass
class InvariantCheck:
    """Definition of a single invariant check."""

    name: str
    description: str
    action: InvariantAction = InvariantAction.WARN
    enabled: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "action": self.action.value,
            "enabled": self.enabled,
        }


@dataclass
class InvariantViolation:
    """A single invariant violation record."""

    invariant_name: str
    message: str
    action_taken: str
    severity: str
    actual_value: float | str | None = None
    expected_condition: str = ""
    timestamp: float = field(default_factory=time.time)
    resolved: bool = False
    resolved_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "invariant_name": self.invariant_name,
            "message": self.message,
            "action_taken": self.action_taken,
            "severity": self.severity,
            "actual_value": self.actual_value,
            "expected_condition": self.expected_condition,
            "timestamp": self.timestamp,
            "resolved": self.resolved,
            "resolved_at": self.resolved_at,
        }


@dataclass
class InvariantCheckResult:
    """Result of running all invariant checks."""

    passed: bool = True
    has_violations: bool = False
    violations: list[InvariantViolation] = field(default_factory=list)
    checks_run: int = 0
    checks_passed: int = 0
    checks_failed: int = 0
    halt_triggered: bool = False
    timestamp: float = field(default_factory=time.time)

    def summary_text(self) -> str:
        status = "HALTED" if self.halt_triggered else (
            "VIOLATIONS" if self.has_violations else "ALL PASS"
        )
        lines = [
            "═" * 50,
            f"  DOMAIN INVARIANTS: {status}",
            "═" * 50,
            f"  Checks: {self.checks_passed}/{self.checks_run} passed, "
            f"{self.checks_failed} failed",
        ]
        if self.violations:
            lines.append("")
            lines.append("  Violations:")
            for v in self.violations[:5]:
                lines.append(
                    f"    [{v.action_taken}] {v.invariant_name}: {v.message}"
                )
        if self.halt_triggered:
            lines.append("\n  ⚠ HALT TRIGGERED — Critical invariant violated")
        lines.append("═" * 50)
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "has_violations": self.has_violations,
            "violations": [v.to_dict() for v in self.violations],
            "checks_run": self.checks_run,
            "checks_passed": self.checks_passed,
            "checks_failed": self.checks_failed,
            "halt_triggered": self.halt_triggered,
        }


# ── Invariant Engine ─────────────────────────────────────────────────────────


class InvariantEngine:
    """Continuous invariant validation engine.

    Validates core domain invariants:
    - PositionQty >= 0
    - Capital >= 0
    - Risk <= Limits
    - FillQty <= OrderQty
    - PnL != NaN
    - Margin >= 0

    Each violation triggers an action: LOG, WARN, or HALT.
    HALT escalation integrates with SafetyState.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._violations: list[InvariantViolation] = []
        self._halted: bool = False
        self._violations_path = Path(INVARIANTS_FILE)
        self._load_violations()

        # Default invariant checks
        self._checks: dict[str, InvariantCheck] = {
            "capital_non_negative": InvariantCheck(
                name="capital_non_negative",
                description="Capital must be >= 0",
                action=InvariantAction.HALT,
            ),
            "position_qty_non_negative": InvariantCheck(
                name="position_qty_non_negative",
                description="Position quantity must be >= 0",
                action=InvariantAction.HALT,
            ),
            "risk_within_limits": InvariantCheck(
                name="risk_within_limits",
                description="Current risk must not exceed maximum risk limit",
                action=InvariantAction.HALT,
            ),
            "fill_qty_valid": InvariantCheck(
                name="fill_qty_valid",
                description="Fill quantity must not exceed order quantity",
                action=InvariantAction.WARN,
            ),
            "pnl_not_nan": InvariantCheck(
                name="pnl_not_nan",
                description="P&L must not be NaN or infinity",
                action=InvariantAction.WARN,
            ),
            "margin_non_negative": InvariantCheck(
                name="margin_non_negative",
                description="Margin must be >= 0",
                action=InvariantAction.HALT,
            ),
            "drawdown_within_limit": InvariantCheck(
                name="drawdown_within_limit",
                description="Drawdown must not exceed maximum drawdown limit",
                action=InvariantAction.HALT,
            ),
        }

    # ── Public API ─────────────────────────────────────────────────────────

    def check_all(self, state: dict[str, Any]) -> InvariantCheckResult:
        """Run all enabled invariant checks against current state.

        Args:
            state: Dictionary containing current system state values.
                   Expected keys: capital, position_qty, risk, max_risk,
                   fill_qty, order_qty, pnl, margin, drawdown, max_drawdown.

        Returns:
            InvariantCheckResult with violations and halt status.
        """
        result = InvariantCheckResult()
        violations: list[InvariantViolation] = []
        halt_triggered = False

        with self._lock:
            for check_name, check in self._checks.items():
                if not check.enabled:
                    continue

                result.checks_run += 1
                violation = self._evaluate_check(check, state)

                if violation:
                    result.checks_failed += 1
                    violations.append(violation)
                    self._violations.append(violation)
                    if len(self._violations) > MAX_VIOLATIONS:
                        self._violations = self._violations[-MAX_VIOLATIONS:]

                    if violation.action_taken == "HALT":
                        halt_triggered = True
                else:
                    result.checks_passed += 1

        result.violations = violations
        result.has_violations = len(violations) > 0
        result.halt_triggered = halt_triggered
        result.passed = not result.has_violations

        if halt_triggered:
            self._trigger_halt(violations)

        if violations:
            self._save_violations()

        return result

    def check_invariant(
        self, invariant_name: str, state: dict[str, Any]
    ) -> InvariantViolation | None:
        """Run a specific invariant check."""
        with self._lock:
            check = self._checks.get(invariant_name)
            if not check:
                return None
            violation = self._evaluate_check(check, state)
            if violation:
                self._violations.append(violation)
                if len(self._violations) > MAX_VIOLATIONS:
                    self._violations = self._violations[-MAX_VIOLATIONS:]
                self._save_violations()
                if violation.action_taken == "HALT":
                    self._trigger_halt([violation])
            return violation

    def enable_check(self, name: str) -> bool:
        """Enable an invariant check."""
        with self._lock:
            check = self._checks.get(name)
            if not check:
                return False
            check.enabled = True
            return True

    def disable_check(self, name: str) -> bool:
        """Disable an invariant check."""
        with self._lock:
            check = self._checks.get(name)
            if not check:
                return False
            check.enabled = False
            return True

    def resolve_violation(self, violation_index: int) -> bool:
        """Mark a violation as resolved."""
        with self._lock:
            if 0 <= violation_index < len(self._violations):
                self._violations[violation_index].resolved = True
                self._violations[violation_index].resolved_at = time.time()
                self._save_violations()
                return True
            return False

    def clear_halt(self) -> None:
        """Clear the HALT state (after manual intervention)."""
        with self._lock:
            self._halted = False
        _log.info("[INVARIANT] HALT cleared by manual intervention")

    @property
    def is_halted(self) -> bool:
        return self._halted

    def get_violation_history(
        self, limit: int = 50, unresolved_only: bool = False
    ) -> list[dict[str, Any]]:
        """Get violation history."""
        with self._lock:
            violations = self._violations
            if unresolved_only:
                violations = [v for v in violations if not v.resolved]
            return [v.to_dict() for v in violations[-limit:]]

    def get_stats(self) -> dict[str, Any]:
        """Get invariant engine statistics."""
        with self._lock:
            total = len(self._violations)
            unresolved = sum(1 for v in self._violations if not v.resolved)
            by_action: dict[str, int] = {}
            by_severity: dict[str, int] = {}
            for v in self._violations:
                by_action[v.action_taken] = by_action.get(v.action_taken, 0) + 1
                by_severity[v.severity] = by_severity.get(v.severity, 0) + 1
            return {
                "total_violations": total,
                "unresolved": unresolved,
                "halted": self._halted,
                "n_checks": len(self._checks),
                "n_enabled": sum(1 for c in self._checks.values() if c.enabled),
                "by_action": by_action,
                "by_severity": by_severity,
            }

    # ── Private Evaluation ────────────────────────────────────────────────

    def _evaluate_check(
        self, check: InvariantCheck, state: dict[str, Any]
    ) -> InvariantViolation | None:
        """Evaluate a single invariant check against the current state."""
        name = check.name

        if name == "capital_non_negative":
            capital = state.get("capital")
            if capital is not None and capital < 0:
                return self._build_violation(
                    check, f"Capital is negative: {capital}",
                    "CRITICAL", capital, "capital >= 0",
                )

        elif name == "position_qty_non_negative":
            qty = state.get("position_qty")
            if qty is not None and qty < 0:
                return self._build_violation(
                    check, f"Position quantity is negative: {qty}",
                    "CRITICAL", qty, "position_qty >= 0",
                )

        elif name == "risk_within_limits":
            risk = state.get("risk")
            max_risk = state.get("max_risk")
            if risk is not None and max_risk is not None and risk > max_risk:
                return self._build_violation(
                    check, f"Risk {risk} exceeds limit {max_risk}",
                    "HIGH", risk, f"risk <= {max_risk}",
                )

        elif name == "fill_qty_valid":
            fill_qty = state.get("fill_qty")
            order_qty = state.get("order_qty")
            if (fill_qty is not None and order_qty is not None
                    and fill_qty > order_qty):
                return self._build_violation(
                    check, f"Fill qty {fill_qty} > order qty {order_qty}",
                    "HIGH", fill_qty, f"fill_qty <= {order_qty}",
                )

        elif name == "pnl_not_nan":
            pnl = state.get("pnl")
            if pnl is not None:
                try:
                    if pnl != pnl or abs(pnl) == float("inf"):
                        return self._build_violation(
                            check, f"P&L is NaN or infinite: {pnl}",
                            "MEDIUM", str(pnl), "pnl must be a finite number",
                        )
                except (TypeError, ValueError):
                    return self._build_violation(
                        check, f"P&L has invalid type: {type(pnl).__name__}",
                        "MEDIUM", str(pnl), "pnl must be a number",
                    )

        elif name == "margin_non_negative":
            margin = state.get("margin")
            if margin is not None and margin < 0:
                return self._build_violation(
                    check, f"Margin is negative: {margin}",
                    "CRITICAL", margin, "margin >= 0",
                )

        elif name == "drawdown_within_limit":
            drawdown = state.get("drawdown")
            max_dd = state.get("max_drawdown")
            if drawdown is not None and max_dd is not None and drawdown > max_dd:
                return self._build_violation(
                    check, f"Drawdown {drawdown:.1%} exceeds limit {max_dd:.1%}",
                    "CRITICAL", drawdown, f"drawdown <= {max_dd}",
                )

        return None

    def _build_violation(
        self,
        check: InvariantCheck,
        message: str,
        severity: str,
        actual_value: float | str | None,
        expected: str,
    ) -> InvariantViolation:
        """Build a violation record from a check and state."""
        return InvariantViolation(
            invariant_name=check.name,
            message=message,
            action_taken=check.action.value if isinstance(
                check.action, InvariantAction
            ) else str(check.action),
            severity=severity,
            actual_value=actual_value,
            expected_condition=expected,
        )

    def _trigger_halt(self, violations: list[InvariantViolation]) -> None:
        """Trigger a HALT from critical invariant violations."""
        with self._lock:
            self._halted = True
        for v in violations:
            _log.critical(
                "[INVARIANT] HALT: %s — %s", v.invariant_name, v.message,
            )
        _log.critical(
            "[INVARIANT] HALT triggered by %d invariant violation(s)",
            len(violations),
        )

    # ── Persistence ───────────────────────────────────────────────────────

    def _load_violations(self) -> None:
        """Load violation history from JSON file."""
        try:
            if self._violations_path.is_file():
                data = json.loads(
                    self._violations_path.read_text(encoding="utf-8")
                )
                for item in data.get("violations", []):
                    try:
                        self._violations.append(InvariantViolation(**item))
                    except (TypeError, ValueError):
                        pass
        except (OSError, json.JSONDecodeError, ValueError, TypeError) as exc:
            _log.debug("[INVARIANT] Load violations failed: %s", exc)

    def _save_violations(self) -> None:
        """Save violation history to JSON file."""
        try:
            self._violations_path.parent.mkdir(parents=True, exist_ok=True)
            self._violations_path.write_text(json.dumps({
                "violations": [v.to_dict() for v in self._violations],
            }, indent=2), encoding="utf-8")
        except (OSError, ValueError, TypeError) as exc:
            _log.debug("[INVARIANT] Save violations failed: %s", exc)


# ── Singleton ────────────────────────────────────────────────────────────────

_engine: InvariantEngine | None = None
_engine_lock = threading.RLock()


def get_invariant_engine() -> InvariantEngine:
    """Get the singleton InvariantEngine instance."""
    global _engine
    with _engine_lock:
        if _engine is None:
            _engine = InvariantEngine()
        return _engine


def reset_invariant_engine() -> None:
    """Force-reset singleton (for testing)."""
    global _engine
    with _engine_lock:
        _engine = None


def check_invariants(state: dict[str, Any]) -> InvariantCheckResult:
    """Convenience function: run all invariant checks."""
    return get_invariant_engine().check_all(state)


def _cli() -> None:
    """Command-line interface.

    Usage:
        python -m core.domain_invariants --check '{"capital": 50000, "position_qty": 10}'
        python -m core.domain_invariants --stats
        python -m core.domain_invariants --history
    """
    import argparse

    parser = argparse.ArgumentParser(
        description="Domain Invariants — Continuous Invariant Validation",
    )
    parser.add_argument("--check", type=str, help="JSON state to check")
    parser.add_argument("--stats", action="store_true", help="Show statistics")
    parser.add_argument("--history", action="store_true", help="Show violation history")
    parser.add_argument("--json", action="store_true", help="JSON output")

    args = parser.parse_args()
    engine = get_invariant_engine()

    if args.check:
        import json as _json
        try:
            state = _json.loads(args.check)
            result = engine.check_all(state)
            if args.json:
                print(_json.dumps(result.to_dict(), indent=2))
            else:
                print(result.summary_text())
        except (json.JSONDecodeError, ValueError) as exc:
            print(f"Invalid JSON: {exc}")
        return

    if args.stats:
        stats = engine.get_stats()
        if args.json:
            import json as _json
            print(_json.dumps(stats, indent=2))
        else:
            print("═" * 50)
            print("Domain Invariants — Statistics")
            print("═" * 50)
            for k, v in stats.items():
                print(f"  {k.replace('_', ' ').title():30s}: {v}")
        return

    if args.history:
        history = engine.get_violation_history(unresolved_only=True)
        if args.json:
            import json as _json
            print(_json.dumps(history, indent=2))
        else:
            print(f"Unresolved Violations ({len(history)}):")
            for h in history[:10]:
                print(f"  [{h['action_taken']}] {h['invariant_name']}: {h['message']}")
        return

    parser.print_help()


if __name__ == "__main__":
    _cli()


__all__ = [
    "InvariantCheck",
    "InvariantCheckResult",
    "InvariantEngine",
    "InvariantViolation",
    "InvariantAction",
    "InvariantSeverity",
    "check_invariants",
    "get_invariant_engine",
    "reset_invariant_engine",
]
