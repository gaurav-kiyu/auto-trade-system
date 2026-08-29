"""Tests for core/domain_invariants.py — Domain Invariant Validation Engine (Phase 14)."""

from __future__ import annotations

from pathlib import Path

import pytest
from core.domain_invariants import (
    InvariantAction,
    InvariantCheck,
    InvariantCheckResult,
    InvariantEngine,
    InvariantViolation,
    check_invariants,
    get_invariant_engine,
    reset_invariant_engine,
)

# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_engine() -> None:
    """Reset singleton before and after each test."""
    reset_invariant_engine()
    p = Path("json/invariant_violations.json")
    if p.exists():
        p.unlink()
    yield
    reset_invariant_engine()


@pytest.fixture
def engine() -> InvariantEngine:
    return get_invariant_engine()


@pytest.fixture
def healthy_state() -> dict:
    return {
        "capital": 50000,
        "position_qty": 10,
        "risk": 150,
        "max_risk": 5000,
        "fill_qty": 50,
        "order_qty": 50,
        "pnl": 250.5,
        "margin": 1000,
        "drawdown": 0.05,
        "max_drawdown": 0.25,
    }


# ── InvariantCheck Tests ─────────────────────────────────────────────────────


class TestInvariantCheck:
    def test_default_values(self) -> None:
        check = InvariantCheck(name="test_check", description="A test check")
        assert check.name == "test_check"
        assert check.description == "A test check"
        assert check.action == InvariantAction.WARN
        assert check.enabled is True

    def test_halt_action(self) -> None:
        check = InvariantCheck(
            name="critical", description="Critical", action=InvariantAction.HALT
        )
        assert check.action == InvariantAction.HALT

    def test_to_dict(self) -> None:
        check = InvariantCheck(
            name="c1", description="C1",
            action=InvariantAction.HALT, enabled=True,
        )
        d = check.to_dict()
        assert d["name"] == "c1"
        assert d["action"] == "HALT"
        assert d["enabled"] is True


# ── InvariantViolation Tests ─────────────────────────────────────────────────


class TestInvariantViolation:
    def test_default_values(self) -> None:
        v = InvariantViolation(
            invariant_name="capital_check",
            message="Capital is negative",
            action_taken="HALT",
            severity="CRITICAL",
        )
        assert v.invariant_name == "capital_check"
        assert v.resolved is False
        assert v.resolved_at is None

    def test_to_dict(self) -> None:
        v = InvariantViolation(
            invariant_name="risk_check",
            message="Risk exceeded",
            action_taken="HALT",
            severity="HIGH",
            actual_value=6000,
            expected_condition="risk <= 5000",
        )
        d = v.to_dict()
        assert d["invariant_name"] == "risk_check"
        assert d["actual_value"] == 6000
        assert d["expected_condition"] == "risk <= 5000"

    def test_resolved(self) -> None:
        v = InvariantViolation(
            invariant_name="c", message="m",
            action_taken="WARN", severity="LOW",
            resolved=True, resolved_at=123.0,
        )
        assert v.resolved is True
        assert v.resolved_at == 123.0


# ── InvariantCheckResult Tests ───────────────────────────────────────────────


class TestInvariantCheckResult:
    def test_default_values(self) -> None:
        result = InvariantCheckResult()
        assert result.passed is True
        assert result.has_violations is False
        assert result.checks_run == 0
        assert result.halt_triggered is False

    def test_summary_text_pass(self) -> None:
        result = InvariantCheckResult(
            checks_run=7, checks_passed=7, checks_failed=0
        )
        text = result.summary_text()
        assert "ALL PASS" in text

    def test_summary_text_violations(self) -> None:
        v = InvariantViolation("c", "Negative capital", "HALT", "CRITICAL")
        result = InvariantCheckResult(
            has_violations=True, violations=[v],
            checks_run=7, checks_passed=6, checks_failed=1,
        )
        text = result.summary_text()
        assert "VIOLATIONS" in text
        assert "Negative capital" in text

    def test_summary_text_halt(self) -> None:
        v = InvariantViolation("c", "Critical", "HALT", "CRITICAL")
        result = InvariantCheckResult(
            halt_triggered=True, has_violations=True,
            violations=[v], checks_run=5, checks_failed=1,
        )
        text = result.summary_text()
        assert "HALT" in text

    def test_to_dict(self) -> None:
        v = InvariantViolation("c", "m", "WARN", "HIGH")
        result = InvariantCheckResult(
            violations=[v], checks_run=5, checks_failed=1
        )
        d = result.to_dict()
        assert d["checks_run"] == 5
        assert d["has_violations"] is False


# ── InvariantEngine Tests ────────────────────────────────────────────────────


class TestInvariantEngine:
    def test_singleton_consistency(self) -> None:
        e1 = get_invariant_engine()
        e2 = get_invariant_engine()
        assert e1 is e2

    def test_reset(self) -> None:
        e1 = get_invariant_engine()
        reset_invariant_engine()
        e2 = get_invariant_engine()
        assert e1 is not e2

    # ── check_all: Healthy State ──────────────────────────────────────────

    def test_check_all_healthy(
        self, engine: InvariantEngine, healthy_state: dict
    ) -> None:
        result = engine.check_all(healthy_state)
        assert result.passed is True
        assert result.has_violations is False
        assert result.halt_triggered is False
        assert result.checks_run == 7
        assert result.checks_passed == 7
        assert result.checks_failed == 0

    # ── Capital ───────────────────────────────────────────────────────────

    def test_capital_negative_triggers_halt(
        self, engine: InvariantEngine
    ) -> None:
        state = {"capital": -100}
        result = engine.check_all(state)
        assert result.has_violations is True
        assert result.halt_triggered is True
        assert any(
            v.invariant_name == "capital_non_negative"
            for v in result.violations
        )

    def test_capital_zero_passes(self, engine: InvariantEngine) -> None:
        state = {"capital": 0}
        result = engine.check_all(state)
        caps = [
            v for v in result.violations
            if v.invariant_name == "capital_non_negative"
        ]
        assert len(caps) == 0

    # ── Position Quantity ─────────────────────────────────────────────────

    def test_position_qty_negative_triggers_halt(
        self, engine: InvariantEngine
    ) -> None:
        state = {"position_qty": -5}
        result = engine.check_all(state)
        assert result.halt_triggered is True
        assert any(
            v.invariant_name == "position_qty_non_negative"
            for v in result.violations
        )

    def test_position_qty_zero_passes(self, engine: InvariantEngine) -> None:
        state = {"position_qty": 0}
        result = engine.check_all(state)
        assert result.passed is True

    # ── Risk ──────────────────────────────────────────────────────────────

    def test_risk_exceeds_limit_triggers_halt(
        self, engine: InvariantEngine
    ) -> None:
        state = {"risk": 10000, "max_risk": 5000}
        result = engine.check_all(state)
        assert result.halt_triggered is True
        assert any(
            v.invariant_name == "risk_within_limits"
            for v in result.violations
        )

    def test_risk_at_limit_passes(self, engine: InvariantEngine) -> None:
        state = {"risk": 5000, "max_risk": 5000}
        result = engine.check_all(state)
        risks = [
            v for v in result.violations
            if v.invariant_name == "risk_within_limits"
        ]
        assert len(risks) == 0

    # ── Fill Quantity ─────────────────────────────────────────────────────

    def test_fill_exceeds_order_triggers_warn(
        self, engine: InvariantEngine
    ) -> None:
        state = {"fill_qty": 100, "order_qty": 50}
        result = engine.check_all(state)
        assert any(
            v.invariant_name == "fill_qty_valid"
            for v in result.violations
        )

    def test_fill_equals_order_passes(self, engine: InvariantEngine) -> None:
        state = {"fill_qty": 50, "order_qty": 50}
        result = engine.check_all(state)
        fills = [
            v for v in result.violations
            if v.invariant_name == "fill_qty_valid"
        ]
        assert len(fills) == 0

    # ── P&L ───────────────────────────────────────────────────────────────

    def test_pnl_nan_triggers_warn(self, engine: InvariantEngine) -> None:
        state = {"pnl": float("nan")}
        result = engine.check_all(state)
        pnls = [
            v for v in result.violations
            if v.invariant_name == "pnl_not_nan"
        ]
        assert len(pnls) == 1

    def test_pnl_infinite_triggers_warn(self, engine: InvariantEngine) -> None:
        state = {"pnl": float("inf")}
        result = engine.check_all(state)
        pnls = [
            v for v in result.violations
            if v.invariant_name == "pnl_not_nan"
        ]
        assert len(pnls) == 1

    def test_pnl_valid_passes(self, engine: InvariantEngine) -> None:
        state = {"pnl": 250.5}
        result = engine.check_all(state)
        pnls = [
            v for v in result.violations
            if v.invariant_name == "pnl_not_nan"
        ]
        assert len(pnls) == 0

    # ── Margin ────────────────────────────────────────────────────────────

    def test_margin_negative_triggers_halt(
        self, engine: InvariantEngine
    ) -> None:
        state = {"margin": -500}
        result = engine.check_all(state)
        assert result.halt_triggered is True
        assert any(
            v.invariant_name == "margin_non_negative"
            for v in result.violations
        )

    def test_margin_zero_passes(self, engine: InvariantEngine) -> None:
        state = {"margin": 0}
        result = engine.check_all(state)
        assert result.passed is True

    # ── Drawdown ──────────────────────────────────────────────────────────

    def test_drawdown_exceeds_limit_triggers_halt(
        self, engine: InvariantEngine
    ) -> None:
        state = {"drawdown": 0.50, "max_drawdown": 0.25}
        result = engine.check_all(state)
        assert result.halt_triggered is True
        assert any(
            v.invariant_name == "drawdown_within_limit"
            for v in result.violations
        )

    def test_drawdown_within_limit_passes(
        self, engine: InvariantEngine
    ) -> None:
        state = {"drawdown": 0.10, "max_drawdown": 0.25}
        result = engine.check_all(state)
        dds = [
            v for v in result.violations
            if v.invariant_name == "drawdown_within_limit"
        ]
        assert len(dds) == 0

    # ── check_invariant (Single Check) ────────────────────────────────────

    def test_check_invariant_capital(self, engine: InvariantEngine) -> None:
        violation = engine.check_invariant(
            "capital_non_negative", {"capital": -1}
        )
        assert violation is not None
        assert violation.invariant_name == "capital_non_negative"

    def test_check_invariant_nonexistent(
        self, engine: InvariantEngine
    ) -> None:
        result = engine.check_invariant("nonexistent_check", {})
        assert result is None

    def test_check_invariant_healthy(
        self, engine: InvariantEngine, healthy_state: dict
    ) -> None:
        violation = engine.check_invariant(
            "capital_non_negative", healthy_state
        )
        assert violation is None

    # ── Enable / Disable ──────────────────────────────────────────────────

    def test_disable_check(self, engine: InvariantEngine) -> None:
        assert engine.disable_check("capital_non_negative") is True
        result = engine.check_all({"capital": -100})
        assert result.passed is True

    def test_enable_check(self, engine: InvariantEngine) -> None:
        engine.disable_check("capital_non_negative")
        assert engine.enable_check("capital_non_negative") is True
        result = engine.check_all({"capital": -100})
        assert result.has_violations is True

    def test_disable_nonexistent(self, engine: InvariantEngine) -> None:
        assert engine.disable_check("nonexistent") is False

    def test_enable_nonexistent(self, engine: InvariantEngine) -> None:
        assert engine.enable_check("nonexistent") is False

    # ── Resolve Violation ─────────────────────────────────────────────────

    def test_resolve_violation(self, engine: InvariantEngine) -> None:
        engine.check_all({"capital": -100})
        assert engine.resolve_violation(0) is True

    def test_resolve_invalid_index(self, engine: InvariantEngine) -> None:
        assert engine.resolve_violation(-1) is False
        assert engine.resolve_violation(999) is False

    # ── HALT ──────────────────────────────────────────────────────────────

    def test_clear_halt(self, engine: InvariantEngine) -> None:
        engine.check_all({"capital": -100})
        assert engine.is_halted is True
        engine.clear_halt()
        assert engine.is_halted is False

    def test_is_halted_false_by_default(self, engine: InvariantEngine) -> None:
        assert engine.is_halted is False

    # ── Violation History ─────────────────────────────────────────────────

    def test_get_violation_history(self, engine: InvariantEngine) -> None:
        engine.check_all({"capital": -100})
        history = engine.get_violation_history()
        assert len(history) >= 1
        assert any(
            v["invariant_name"] == "capital_non_negative" for v in history
        )

    def test_get_violation_history_unresolved_only(
        self, engine: InvariantEngine
    ) -> None:
        engine.check_all({"capital": -100})
        unresolved = engine.get_violation_history(unresolved_only=True)
        assert len(unresolved) >= 1

    def test_get_violation_history_resolved_excluded(
        self, engine: InvariantEngine
    ) -> None:
        engine.check_all({"capital": -100})
        before = engine.get_violation_history(unresolved_only=False)
        if before:
            engine.resolve_violation(0)
            unresolved = engine.get_violation_history(unresolved_only=True)
            assert len(unresolved) < len(before)

    # ── Stats ─────────────────────────────────────────────────────────────

    def test_get_stats_empty(self, engine: InvariantEngine) -> None:
        stats = engine.get_stats()
        assert stats["total_violations"] == 0
        assert stats["halted"] is False
        assert stats["n_checks"] >= 7

    def test_get_stats_after_violation(self, engine: InvariantEngine) -> None:
        engine.check_all({"capital": -100, "position_qty": -5})
        stats = engine.get_stats()
        assert stats["total_violations"] >= 1
        assert stats["halted"] is True
        assert stats["by_action"].get("HALT", 0) >= 1

    # ── Edge Cases ────────────────────────────────────────────────────────

    def test_check_all_with_empty_state_passes(
        self, engine: InvariantEngine
    ) -> None:
        result = engine.check_all({})
        assert result.checks_run == 7
        assert result.passed is True

    def test_check_all_with_partial_state(
        self, engine: InvariantEngine
    ) -> None:
        result = engine.check_all({"capital": 100, "position_qty": 10})
        assert result.checks_run == 7
        assert result.passed is True

    def test_multiple_violations_in_one_call(
        self, engine: InvariantEngine
    ) -> None:
        state = {
            "capital": -100,
            "position_qty": -10,
            "risk": 10000,
            "max_risk": 5000,
            "margin": -500,
            "drawdown": 0.50,
            "max_drawdown": 0.25,
        }
        result = engine.check_all(state)
        assert result.checks_failed >= 4
        assert result.halt_triggered is True

    def test_halt_persists_across_calls(
        self, engine: InvariantEngine
    ) -> None:
        engine.check_all({"capital": -100})
        assert engine.is_halted is True
        engine.check_all({"capital": 50000})
        assert engine.is_halted is True

    def test_pnl_invalid_type(self, engine: InvariantEngine) -> None:
        result = engine.check_all({"pnl": "not_a_number"})
        assert result.checks_run == 7

    # ── check_invariants convenience function ─────────────────────────────

    def test_convenience_function(self, healthy_state: dict) -> None:
        result = check_invariants(healthy_state)
        assert isinstance(result, InvariantCheckResult)
        assert result.passed is True

    def test_convenience_function_with_violation(self) -> None:
        result = check_invariants({"capital": -100})
        assert result.has_violations is True
