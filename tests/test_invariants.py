"""
Tests for the invariants engine and standard invariant checks.
"""

from __future__ import annotations

import threading

from core.invariants.engine import (
    InvariantResult,
    InvariantSeverity,
    InvariantViolation,
    check_all,
    get_state,
    get_violations,
    is_check_enabled,
    register_halt_callback,
    register_invariant,
    resolve_violation,
    toggle_check,
)


def _passing_check() -> tuple[bool, str]:
    return True, "All good"


def _failing_check() -> tuple[bool, str]:
    return False, "Something went wrong"


def _error_check() -> tuple[bool, str]:
    raise RuntimeError("Unexpected error")


class TestInvariantEngine:
    """Tests for core.invariants.engine module."""

    def setup_method(self):
        """Reset global state between tests."""
        # Toggle any disabled checks back on
        toggle_check("test_check")
        # Clear violations by resolving them all
        for v in get_violations():
            resolve_violation(v.check_name)

    def test_register_and_run_passing(self):
        """Register a passing check and verify it runs cleanly."""
        register_invariant(
            "test_pass",
            "A check that always passes",
            InvariantSeverity.WARN,
            _passing_check,
        )
        results = check_all()
        matches = [r for r in results if r.name == "test_pass"]
        assert len(matches) == 1
        assert matches[0].last_result == InvariantResult.PASS
        assert matches[0].last_message == "All good"

    def test_register_and_run_failing(self):
        """Register a failing check and verify it produces a violation."""
        register_invariant(
            "test_fail",
            "A check that always fails",
            InvariantSeverity.WARN,
            _failing_check,
        )
        results = check_all()
        matches = [r for r in results if r.name == "test_fail"]
        assert len(matches) == 1
        assert matches[0].last_result == InvariantResult.FAIL
        assert matches[0].last_message == "Something went wrong"

    def test_failing_check_creates_violation(self):
        """Verify failing checks produce violations in the violation list."""
        name = "test_violation_create"
        register_invariant(name, "Violation test", InvariantSeverity.WARN, _failing_check)
        before = len(get_violations())
        check_all()
        after = len(get_violations())
        assert after > before

    def test_error_check_sets_error_result(self):
        """Verify a check that raises an exception gets ERROR result."""
        register_invariant(
            "test_error",
            "A check that errors",
            InvariantSeverity.HALT,
            _error_check,
        )
        results = check_all()
        matches = [r for r in results if r.name == "test_error"]
        assert len(matches) == 1
        assert matches[0].last_result == InvariantResult.ERROR
        assert "Unexpected error" in matches[0].last_message

    def test_severity_halt_triggers_callback(self):
        """Verify HALT severity invokes the registered halt callback."""
        callback_triggered = threading.Event()
        callback_message = [""]

        def halt_cb(msg: str) -> None:
            callback_message[0] = msg
            callback_triggered.set()

        register_halt_callback(halt_cb)
        register_invariant(
            "test_halt_cb",
            "Triggers halt callback",
            InvariantSeverity.HALT,
            _failing_check,
        )
        check_all()
        assert callback_triggered.wait(timeout=2.0)
        assert "test_halt_cb" in callback_message[0]

    def test_toggle_check_disable(self):
        """Verify disabling a check prevents it from running."""
        name = "test_toggle_disable"
        register_invariant(name, "Toggle test", InvariantSeverity.WARN, _failing_check)
        assert is_check_enabled(name)
        toggle_check(name)
        assert not is_check_enabled(name)

    def test_toggle_check_enable(self):
        """Verify re-enabling a check allows it to run again."""
        name = "test_toggle_enable"
        register_invariant(name, "Toggle enable", InvariantSeverity.WARN, _failing_check)
        toggle_check(name)  # disable
        toggle_check(name)  # re-enable
        assert is_check_enabled(name)
        results = check_all()
        matches = [r for r in results if r.name == name]
        assert len(matches) == 1
        assert matches[0].last_result == InvariantResult.FAIL

    def test_resolve_violation(self):
        """Verify resolving a violation marks it as resolved."""
        name = "test_resolve"
        register_invariant(name, "Resolve test", InvariantSeverity.WARN, _failing_check)
        check_all()
        violations_before = get_violations(unresolved_only=True)
        assert any(v.check_name == name for v in violations_before)

        resolve_violation(name)
        violations_after = get_violations(unresolved_only=True)
        assert not any(v.check_name == name for v in violations_after)

    def test_get_state_contains_expected_keys(self):
        """Verify get_state returns the expected structure."""
        state = get_state()
        assert "checks" in state
        assert "violations" in state
        assert "violation_count" in state
        assert "disabled_checks" in state
        assert isinstance(state["checks"], list)
        assert isinstance(state["violations"], list)
        assert isinstance(state["violation_count"], int)
        assert isinstance(state["disabled_checks"], list)

    def test_unresolved_only_filter(self):
        """Verify unresolved_only filter works correctly."""
        name = "test_unresolved"
        register_invariant(name, "Unresolved test", InvariantSeverity.WARN, _failing_check)
        check_all()
        unres = get_violations(unresolved_only=True)
        assert any(v.check_name == name for v in unres)
        resolve_violation(name)
        unres_after = get_violations(unresolved_only=True)
        assert not any(v.check_name == name for v in unres_after)

    def test_register_updates_existing(self):
        """Verify registering a check with an existing name updates it."""
        name = "test_update"
        register_invariant(name, "Original", InvariantSeverity.WARN, _passing_check)
        results1 = check_all()
        m1 = [r for r in results1 if r.name == name][0]
        assert m1.last_result == InvariantResult.PASS

        # Update with failing check
        register_invariant(name, "Updated", InvariantSeverity.HALT, _failing_check)
        results2 = check_all()
        m2 = [r for r in results2 if r.name == name][0]
        assert m2.last_result == InvariantResult.FAIL
        assert m2.severity == InvariantSeverity.HALT


class TestStandardChecks:
    """Tests for core.invariants.checks standard invariants."""

    def test_register_all_runs_without_error(self):
        """Verify register_all() does not raise."""
        from core.invariants.checks import register_all
        register_all()

    def test_standard_checks_are_registered(self):
        """Verify standard checks are present after registration."""
        from core.invariants.checks import register_all
        register_all()
        state = get_state()
        check_names = {c["name"] for c in state["checks"]}
        assert "broker_positions_match_local" in check_names
        assert "single_risk_engine" in check_names
        assert "no_stale_data_trading" in check_names
        assert "operating_mode_gate" in check_names
        assert "no_duplicate_submissions" in check_names
        assert "hard_halt_operational" in check_names
        assert "consecutive_loss_threshold" in check_names
        assert "intraday_pnl_monitor" in check_names

    def test_checks_run_without_exception(self):
        """Verify running all standard checks doesn't crash."""
        from core.invariants.checks import register_all
        register_all()
        results = check_all()
        # Should have at least 8 standard checks
        assert len(results) >= 8
        # All should return either PASS, FAIL, or ERROR (not None)
        for r in results:
            assert r.last_result in (
                InvariantResult.PASS,
                InvariantResult.FAIL,
                InvariantResult.ERROR,
            )


class TestInvariantViolation:
    """Tests for the InvariantViolation dataclass."""

    def test_violation_defaults(self):
        """Verify default values for InvariantViolation."""
        from datetime import datetime
        v = InvariantViolation(
            timestamp=datetime.now(),
            check_name="test",
            severity=InvariantSeverity.WARN,
            message="test message",
        )
        assert not v.resolved
        assert v.resolved_at is None

    def test_violation_resolved(self):
        """Verify resolved state works."""
        from datetime import datetime
        v = InvariantViolation(
            timestamp=datetime.now(),
            check_name="test",
            severity=InvariantSeverity.WARN,
            message="test",
            resolved=True,
            resolved_at=datetime.now(),
        )
        assert v.resolved
        assert v.resolved_at is not None
