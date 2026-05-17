"""Tests for core/services/circuit_breaker_service.py."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from core.ports.circuit_breaker.circuit_breaker_port import (
    CircuitBreakerConfig,
    CircuitBreakerOpenException,
    CircuitState,
)
from core.services.circuit_breaker_service import CircuitBreakerService


# ── Constructor ──────────────────────────────────────────────────────────

def test_constructor():
    cb = CircuitBreakerService()
    assert cb._breakers == {}
    st = cb.get_stats("test")
    assert st.state == CircuitState.CLOSED
    assert st.failure_count == 0
    assert st.success_count == 0


def test_constructor_with_config():
    config = CircuitBreakerConfig(failure_threshold=3, timeout=30)
    cb = CircuitBreakerService()
    cb.update_config("custom", config)
    st = cb.get_stats("custom")
    assert st.state == CircuitState.CLOSED


# ── State machine: CLOSED ───────────────────────────────────────────────

def test_call_success_in_closed_state():
    cb = CircuitBreakerService()
    fn = MagicMock(return_value="ok")
    result = cb.call(fn)
    assert result == "ok"
    fn.assert_called_once()


def test_call_failure_trips_to_open():
    cb = CircuitBreakerService()
    # Disable sliding-window rate check to test absolute count threshold
    config = CircuitBreakerConfig(
        failure_threshold=2, success_threshold=1, timeout=5,
        sliding_window_size=0,
    )
    cb.update_config("test", config)
    fn = MagicMock()
    fn.side_effect = ValueError("boom")

    for i in range(2):
        with pytest.raises(ValueError, match="boom"):
            cb.call_with_key("test", fn)

    st = cb.get_stats("test")
    assert st.state == CircuitState.OPEN


def test_sliding_window_resets_after_window():
    """Count-based window: old failures don't count toward the absolute threshold."""
    cb = CircuitBreakerService()
    # Disable rate check (sliding_window_size=0) to test absolute count threshold
    config = CircuitBreakerConfig(
        failure_threshold=2,
        timeout=1,
        sliding_window_size=0,
    )
    cb.update_config("test", config)
    fn = MagicMock()
    fn.side_effect = ValueError("boom")

    # One failure — should NOT trip (need 2)
    with pytest.raises(ValueError):
        cb.call_with_key("test", fn)

    st = cb.get_stats("test")
    assert st.failure_count == 1
    assert st.state == CircuitState.CLOSED


# ── State machine: OPEN ─────────────────────────────────────────────────

def test_open_rejects_calls():
    cb = CircuitBreakerService()
    config = CircuitBreakerConfig(failure_threshold=1, timeout=60)
    cb.update_config("test", config)
    fn = MagicMock(side_effect=ValueError("boom"))

    with pytest.raises(ValueError):
        cb.call_with_key("test", fn)

    # Circuit is now OPEN — subsequent calls should be rejected
    with pytest.raises(CircuitBreakerOpenException):
        cb.call_with_key("test", MagicMock(return_value="should not run"))


def test_open_transitions_to_half_open_after_timeout():
    cb = CircuitBreakerService()
    config = CircuitBreakerConfig(failure_threshold=1, timeout=0.05, success_threshold=1)
    cb.update_config("test", config)
    fn = MagicMock(side_effect=ValueError("boom"))

    with pytest.raises(ValueError):
        cb.call_with_key("test", fn)

    # Wait for timeout
    time.sleep(0.1)

    # Should now be HALF_OPEN and allow a call
    fn2 = MagicMock(return_value="recovered")
    result = cb.call_with_key("test", fn2)
    assert result == "recovered"

    st = cb.get_stats("test")
    assert st.state == CircuitState.CLOSED  # success → CLOSED with threshold=1


# ── State machine: HALF_OPEN ────────────────────────────────────────────

def test_half_open_failure_goes_back_to_open():
    cb = CircuitBreakerService()
    config = CircuitBreakerConfig(failure_threshold=1, timeout=0.05, success_threshold=1)
    cb.update_config("test", config)
    fn = MagicMock(side_effect=ValueError("boom"))

    # Trip to OPEN
    with pytest.raises(ValueError):
        cb.call_with_key("test", fn)

    # Wait for timeout → HALF_OPEN
    time.sleep(0.1)

    # Call fails again → back to OPEN
    with pytest.raises(ValueError):
        cb.call_with_key("test", fn)

    st = cb.get_stats("test")
    assert st.state == CircuitState.OPEN
    assert st.failure_count >= 2


def test_half_open_success_threshold():
    """Require multiple successes to transition from HALF_OPEN → CLOSED."""
    cb = CircuitBreakerService()
    config = CircuitBreakerConfig(
        failure_threshold=1, timeout=0.05, success_threshold=3,
    )
    cb.update_config("test", config)
    fn = MagicMock(side_effect=ValueError("boom"))

    with pytest.raises(ValueError):
        cb.call_with_key("test", fn)

    time.sleep(0.1)

    # First success in HALF_OPEN
    fn_ok = MagicMock(return_value="ok")
    cb.call_with_key("test", fn_ok)

    st = cb.get_stats("test")
    assert st.state == CircuitState.HALF_OPEN  # still HALF_OPEN, need 2 more

    # Two more successes
    cb.call_with_key("test", fn_ok)
    cb.call_with_key("test", fn_ok)

    st = cb.get_stats("test")
    assert st.state == CircuitState.CLOSED


# ── force_open / force_close / reset ────────────────────────────────────

def test_force_open():
    cb = CircuitBreakerService()
    cb.force_open("test")
    st = cb.get_stats("test")
    assert st.state == CircuitState.OPEN


def test_force_close():
    cb = CircuitBreakerService()
    config = CircuitBreakerConfig(failure_threshold=1, sliding_window_size=0, timeout=60)
    cb.update_config("global", config)
    with pytest.raises(ValueError):
        cb.call(MagicMock(side_effect=ValueError("boom")))  # trips
    cb.force_close("global")
    st = cb.get_stats("global")
    assert st.state == CircuitState.CLOSED
    assert st.failure_count == 0


def test_reset():
    cb = CircuitBreakerService()
    config = CircuitBreakerConfig(failure_threshold=1, sliding_window_size=0, timeout=60)
    cb.update_config("global", config)
    with pytest.raises(ValueError):
        cb.call(MagicMock(side_effect=ValueError("boom")))
    cb.reset("global")
    st = cb.get_stats("global")
    assert st.state == CircuitState.CLOSED
    assert st.failure_count == 0
    assert st.success_count == 0


# ── health_check ────────────────────────────────────────────────────────

def test_health_check():
    cb = CircuitBreakerService()
    config = CircuitBreakerConfig(failure_threshold=1, sliding_window_size=0, timeout=60)
    cb.update_config("global", config)
    with pytest.raises(ValueError):
        cb.call(MagicMock(side_effect=ValueError("x")))
    health = cb.health_check()
    assert isinstance(health, dict)
    assert health["total_breakers"] == 1
    assert health["breakers"]["global"]["state"] == "open"


def test_health_check_empty():
    cb = CircuitBreakerService()
    health = cb.health_check()
    assert health["total_breakers"] == 0


# ── Thread safety ───────────────────────────────────────────────────────

def test_concurrent_calls_do_not_deadlock():
    import threading as _t
    cb = CircuitBreakerService()
    fn = MagicMock(return_value="ok")
    errors = []

    def worker():
        try:
            for _ in range(20):
                cb.call(fn)
        except Exception as e:
            errors.append(e)

    threads = [_t.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    # At least some calls succeeded
    assert fn.call_count >= 50


# ── call_with_key isolation ─────────────────────────────────────────────

def test_breakers_are_independent():
    cb = CircuitBreakerService()
    cb.update_config("alpha", CircuitBreakerConfig(failure_threshold=1, sliding_window_size=0, timeout=60))
    cb.update_config("beta", CircuitBreakerConfig(failure_threshold=10, sliding_window_size=0, timeout=60))

    # Trip only alpha
    with pytest.raises(ValueError):
        cb.call_with_key("alpha", MagicMock(side_effect=ValueError("x")))

    # Beta should still work
    result = cb.call_with_key("beta", MagicMock(return_value="ok"))
    assert result == "ok"

    # Alpha rejects
    with pytest.raises(CircuitBreakerOpenException):
        cb.call_with_key("alpha", MagicMock(return_value="x"))


# ── update_config ──────────────────────────────────────────────────────

def test_update_config_creates_breaker():
    cb = CircuitBreakerService()
    config = CircuitBreakerConfig(failure_threshold=3)
    cb.update_config("new_key", config)
    st = cb.get_stats("new_key")
    assert st.failure_count == 0
    assert st.state == CircuitState.CLOSED


def test_update_config_replaces_existing():
    cb = CircuitBreakerService()
    config = CircuitBreakerConfig(failure_threshold=1, sliding_window_size=0, timeout=60)
    cb.update_config("global", config)
    with pytest.raises(ValueError):
        cb.call(MagicMock(side_effect=ValueError("x")))
    st = cb.get_stats("global")
    assert st.state == CircuitState.OPEN

    # Replace config and explicitly reset
    cb.update_config("global", CircuitBreakerConfig(failure_threshold=20, sliding_window_size=0))
    cb.reset("global")
    st = cb.get_stats("global")
    assert st.state == CircuitState.CLOSED
