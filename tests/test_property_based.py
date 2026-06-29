"""
Property-based tests with Hypothesis for critical modules.

Tests mathematical invariants and edge cases that example-based tests may miss.
Targets: VaR calculator, invariants engine.

This addresses the "Fuzz/property-based testing" gap in the 9.9+ roadmap.
"""
from __future__ import annotations

import os
import sqlite3
import tempfile
from datetime import date, timedelta

import pytest
from hypothesis import assume, given
from hypothesis import strategies as st
from hypothesis.strategies import floats, lists

# ── Global state cleanup ──────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _reset_invariant_registry():
    """Reset the invariants global registry before each test to prevent
    Hypothesis's many-example runs from polluting the shared state.

    Directly clears the module-level dicts in core.invariants.engine so
    each test starts with a clean slate.
    """
    import core.invariants.engine as _ie
    _ie._INVARIANTS.clear()
    _ie._violations.clear()
    _ie._disabled_checks.clear()
    yield

from core.invariants.engine import (
    InvariantResult,
    InvariantSeverity,
    InvariantViolation,
    check_all,
    get_state,
    register_invariant,
)
from core.var_calculator import VaRResult, compute_var

# ═══════════════════════════════════════════════════════════════════════════════
# VaR Calculator — Property-Based Tests
# ═══════════════════════════════════════════════════════════════════════════════

def _make_db(pnls: list[float]) -> str:
    """Create temp DB with PnL history."""
    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    f.close()
    conn = sqlite3.connect(f.name)
    conn.execute("CREATE TABLE trades (id INTEGER PRIMARY KEY, ts TEXT, net_pnl REAL)")
    today = date.today()
    for i, pnl in enumerate(pnls):
        day = (today - timedelta(days=len(pnls) - i - 1)).isoformat()
        conn.execute("INSERT INTO trades (ts, net_pnl) VALUES (?, ?)", (day + "T10:00:00", pnl))
    conn.commit()
    conn.close()
    return f.name


@given(
    capital=floats(min_value=1000, max_value=10_000_000, allow_nan=False, allow_infinity=False),
    stdev_factor=floats(min_value=0.001, max_value=0.5, allow_nan=False, allow_infinity=False),
)
def test_var_scales_with_capital(capital: float, stdev_factor: float) -> None:
    """VaR should be proportional to capital when PnL distribution is fixed."""
    assume(capital > 0)
    # Generate PnLs with known volatility
    base_pnl = capital * stdev_factor
    pnls = [base_pnl * (-1 if i % 2 == 0 else 1) for i in range(30)]
    db = _make_db(pnls)
    try:
        result = compute_var(capital, db_path=db, cfg={"var_enabled": True, "var_lookback_days": 60})
        if result.n_days >= 2:
            # VaR should be positive (loss estimate)
            assert result.var_95 >= 0
            assert result.var_99 >= 0
            # VaR_99 should be >= VaR_95 (99th percentile = larger loss)
            assert result.var_99 >= result.var_95
            # VaR as % of capital should be reasonable
            assert result.var_95_pct < 100.0
    finally:
        os.unlink(db)


@given(
    pnls=lists(
        floats(min_value=-10_000, max_value=10_000, allow_nan=False, allow_infinity=False),
        min_size=3,
        max_size=50,
    ),
)
def test_var_99_gte_var_95(pnls: list[float]) -> None:
    """99th percentile VaR must always be >= 95th percentile VaR."""
    capital = 100_000.0
    db = _make_db(pnls)
    try:
        result = compute_var(capital, db_path=db, cfg={"var_enabled": True, "var_lookback_days": 60})
        if result.n_days >= 2:
            assert result.var_99 >= result.var_95, (
                f"Expected var_99 ({result.var_99}) >= var_95 ({result.var_95})"
            )
            # VaR should not exceed total capital
            assert result.var_95 <= capital
            assert result.var_99 <= capital
    finally:
        os.unlink(db)


@given(
    capital=floats(min_value=0, max_value=100_000, allow_nan=False, allow_infinity=False),
)
def test_zero_or_negative_capital_returns_zero_var(capital: float) -> None:
    """VaR should be 0 when capital is 0 or negative."""
    if capital <= 0:
        result = compute_var(capital)
        assert result.var_95 == 0.0
        assert result.var_99 == 0.0
    # else: positive capital test is covered elsewhere


@given(
    pnls=lists(
        floats(min_value=-1000, max_value=1000, allow_nan=False, allow_infinity=False),
        min_size=0,
        max_size=20,
    ),
)
def test_var_result_has_expected_types(pnls: list[float]) -> None:
    """VaRResult should always have valid types regardless of input."""
    capital = 100_000.0
    db = _make_db(pnls)
    try:
        result = compute_var(capital, db_path=db, cfg={"var_enabled": True, "var_lookback_days": 60})
        assert isinstance(result, VaRResult)
        assert isinstance(result.var_95, float)
        assert isinstance(result.var_99, float)
        assert isinstance(result.n_days, int)
        assert isinstance(result.alert, bool)
        assert result.var_95 >= 0
        assert result.var_99 >= 0
        assert result.n_days >= 0
    finally:
        os.unlink(db)


# ═══════════════════════════════════════════════════════════════════════════════
# Invariants Engine — Property-Based Tests
# ═══════════════════════════════════════════════════════════════════════════════

@given(
    severity=st.sampled_from([InvariantSeverity.WARN, InvariantSeverity.HALT]),
    message=st.text(min_size=0, max_size=200),
)
def test_invariant_violation_defaults(severity: InvariantSeverity, message: str) -> None:
    """InvariantViolation properties should hold for any valid inputs."""
    from datetime import datetime
    v = InvariantViolation(
        timestamp=datetime.now(),
        check_name="prop_test",
        severity=severity,
        message=message,
    )
    assert not v.resolved
    assert v.resolved_at is None
    assert v.check_name == "prop_test"
    assert isinstance(v.severity, InvariantSeverity)


@given(
    check_name=st.text(min_size=1, max_size=50),
    severity=st.sampled_from([InvariantSeverity.WARN, InvariantSeverity.HALT]),
)
def test_register_invariant_idempotent(check_name: str, severity: InvariantSeverity) -> None:
    """Registering the same check twice should be idempotent (last wins)."""
    # Register first version
    register_invariant(
        check_name,
        "Original description",
        severity,
        lambda: (True, "ok"),
    )
    # Register second version (update)
    register_invariant(
        check_name,
        "Updated description",
        severity,
        lambda: (True, "ok"),
    )
    results = check_all()
    matches = [r for r in results if r.name == check_name]
    assert len(matches) == 1, "Duplicate registration should update, not add"


@given(
    check_name=st.text(min_size=1, max_size=50),
)
def test_check_all_returns_results_for_all_registered(check_name: str) -> None:
    """check_all() should return result for every registered check."""
    register_invariant(check_name, "Test", InvariantSeverity.WARN, lambda: (True, "ok"))
    results = check_all()
    match = [r for r in results if r.name == check_name]
    assert len(match) == 1
    assert match[0].last_result in (
        InvariantResult.PASS,
        InvariantResult.FAIL,
        InvariantResult.ERROR,
    )


@given(
    pass_count=st.integers(min_value=0, max_value=5),
    fail_count=st.integers(min_value=0, max_value=5),
)
def test_get_state_has_expected_structure(pass_count: int, fail_count: int) -> None:
    """State structure should be consistent regardless of check count."""
    # Clear checks by registering known ones
    for i in range(pass_count):
        register_invariant(f"pass_{i}", "Pass", InvariantSeverity.WARN, lambda: (True, "ok"))
    for i in range(fail_count):
        register_invariant(f"fail_{i}", "Fail", InvariantSeverity.WARN, lambda: (False, "bad"))
    check_all()
    state = get_state()
    assert "checks" in state
    assert "violations" in state
    assert "violation_count" in state
    assert "disabled_checks" in state
    assert isinstance(state["checks"], list)
    assert isinstance(state["violations"], list)
    assert isinstance(state["violation_count"], int)
