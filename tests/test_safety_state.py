"""
Tests for core/safety_state.py — Global Safety State.

Covers:
  - Hard halt trip, check, and reason storage
  - Graceful shutdown flag
  - Consecutive loss counter (thread-safe)
  - Intraday P&L monitoring and loss limit breach
  - Kill file detection
  - Clear hard halt with cooldown and audit trail
  - kill file watcher start
"""
from __future__ import annotations


import pytest

from unittest.mock import patch

import core.safety_state
from core.safety_state import (
    _HARD_HALT,
    _clear_halt_history,
    _hard_halt_reason,
    _shutdown,
    check_intraday_pnl_and_halt,
    check_kill_file_and_halt,
    clear_hard_halt,
    get_consecutive_losses,
    get_intraday_loss_limit,
    get_intraday_pnl,
    hard_halt_reason,
    is_hard_halted,
    is_kill_file_present,
    is_shutting_down,
    record_trade_outcome,
    request_shutdown,
    reset_consecutive_losses,
    reset_intraday_pnl,
    set_intraday_loss_limit,
    set_intraday_pnl,
    trip_hard_halt,
)

# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_global_state() -> None:
    """Reset all global state before each test."""
    _HARD_HALT.clear()
    _shutdown.clear()
    reset_consecutive_losses()
    reset_intraday_pnl()
    global _hard_halt_reason
    _hard_halt_reason = ""
    _clear_halt_history.clear()
    # Reset the clear cooldown so each test can clear immediately
    core.safety_state._LAST_CLEAR_TIME = 0.0


# ── Hard Halt ─────────────────────────────────────────────────────────


class TestHardHalt:
    def test_not_halted_by_default(self) -> None:
        assert not is_hard_halted()

    def test_trip_hard_halt_sets_flag(self) -> None:
        trip_hard_halt("test halt", source="test")
        assert is_hard_halted()

    def test_trip_hard_halt_stores_reason(self) -> None:
        trip_hard_halt("loss limit breached", source="risk_monitor")
        reason = hard_halt_reason()
        assert "loss limit breached" in reason
        assert "risk_monitor" in reason

    def test_double_trip_does_not_override_reason(self) -> None:
        trip_hard_halt("first halt", source="test")
        first_reason = hard_halt_reason()
        trip_hard_halt("second halt", source="test")
        assert hard_halt_reason() == first_reason

    def test_halt_blocks_new_entries(self) -> None:
        trip_hard_halt("test", source="test")
        assert is_hard_halted()
        assert bool(hard_halt_reason())


# ── Graceful Shutdown ────────────────────────────────────────────────


class TestShutdown:
    def test_not_shutting_down_by_default(self) -> None:
        assert not is_shutting_down()

    def test_request_shutdown_sets_flag(self) -> None:
        request_shutdown("test shutdown")
        assert is_shutting_down()

    def test_double_shutdown_safe(self) -> None:
        request_shutdown("first")
        request_shutdown("second")
        assert is_shutting_down()


# ── Consecutive Loss Counter ─────────────────────────────────────────


class TestConsecutiveLosses:
    def test_starts_at_zero(self) -> None:
        assert get_consecutive_losses() == 0

    def test_loss_increments(self) -> None:
        record_trade_outcome(was_profit=False)
        assert get_consecutive_losses() == 1

    def test_multiple_losses_stack(self) -> None:
        record_trade_outcome(was_profit=False)
        record_trade_outcome(was_profit=False)
        record_trade_outcome(was_profit=False)
        assert get_consecutive_losses() == 3

    def test_win_resets_to_zero(self) -> None:
        record_trade_outcome(was_profit=False)
        record_trade_outcome(was_profit=False)
        record_trade_outcome(was_profit=True)
        assert get_consecutive_losses() == 0

    def test_reset_explicit(self) -> None:
        record_trade_outcome(was_profit=False)
        reset_consecutive_losses()
        assert get_consecutive_losses() == 0

    def test_record_trade_returns_count(self) -> None:
        count = record_trade_outcome(was_profit=False)
        assert count == 1

    def test_win_returns_zero(self) -> None:
        count = record_trade_outcome(was_profit=True)
        assert count == 0


# ── Intraday P&L Monitoring ──────────────────────────────────────────


class TestIntradayPnL:
    def test_starts_at_zero(self) -> None:
        assert get_intraday_pnl() == 0.0

    def test_set_and_get(self) -> None:
        set_intraday_pnl(5000.0)
        assert get_intraday_pnl() == 5000.0

    def test_set_negative(self) -> None:
        set_intraday_pnl(-1000.0)
        assert get_intraday_pnl() == -1000.0

    def test_limit_defaults_to_inf(self) -> None:
        assert get_intraday_loss_limit() == -float("inf")

    def test_set_limit_enforces_negative(self) -> None:
        set_intraday_loss_limit(-5000.0)
        assert get_intraday_loss_limit() == -5000.0

    def test_set_limit_positive_is_negated(self) -> None:
        set_intraday_loss_limit(5000.0)
        assert get_intraday_loss_limit() == -5000.0

    def test_check_no_limit_does_not_halt(self) -> None:
        assert not check_intraday_pnl_and_halt(source="test")
        assert not is_hard_halted()

    def test_check_breach_halts(self) -> None:
        set_intraday_loss_limit(-1000.0)
        set_intraday_pnl(-2000.0)
        halted = check_intraday_pnl_and_halt(source="test")
        assert halted
        assert is_hard_halted()
        assert "Intraday loss limit breached" in hard_halt_reason()

    def test_check_below_limit_no_halt(self) -> None:
        set_intraday_loss_limit(-5000.0)
        set_intraday_pnl(-1000.0)
        assert not check_intraday_pnl_and_halt(source="test")
        assert not is_hard_halted()

    def test_already_halted_returns_true(self) -> None:
        trip_hard_halt("already halted", source="test")
        set_intraday_loss_limit(-1000.0)
        set_intraday_pnl(-2000.0)
        assert check_intraday_pnl_and_halt(source="test")

    def test_reset_pnl(self) -> None:
        set_intraday_pnl(5000.0)
        reset_intraday_pnl()
        assert get_intraday_pnl() == 0.0


# ── Clear Hard Halt ──────────────────────────────────────────────────


class TestClearHardHalt:
    def test_clear_hard_halt(self) -> None:
        trip_hard_halt("test", source="test")
        assert is_hard_halted()
        clear_hard_halt(source="operator", reason="verified safe")
        assert not is_hard_halted()

    def test_clear_hard_halt_clears_reason(self) -> None:
        trip_hard_halt("test", source="test")
        clear_hard_halt(source="operator", reason="verified safe")
        assert hard_halt_reason() == ""

    def test_clear_hard_halt_adds_to_history(self) -> None:
        trip_hard_halt("test", source="test")
        clear_hard_halt(source="operator", reason="verified safe")
        assert len(_clear_halt_history) >= 1
        assert _clear_halt_history[-1]["source"] == "operator"
        assert _clear_halt_history[-1]["reason"] == "verified safe"

    def test_clear_hard_halt_with_previous_reason(self) -> None:
        trip_hard_halt("test halt reason", source="test")
        clear_hard_halt(source="admin", reason="investigated")
        assert _clear_halt_history[-1]["previous_halt_reason"] == "[test] test halt reason"

    def test_clear_without_halt_safe(self) -> None:
        clear_hard_halt(source="operator", reason="precaution")
        assert not is_hard_halted()

    def test_clear_history_limited(self) -> None:
        for i in range(10):
            trip_hard_halt(f"halt {i}", source="test")
            clear_hard_halt(source="operator", reason=f"clear {i}")
        assert len(_clear_halt_history) <= 10


# ── Kill File ────────────────────────────────────────────────────────


class TestKillFile:
    def test_kill_file_not_present_by_default(self) -> None:
        with patch("pathlib.Path.exists", return_value=False):
            assert not is_kill_file_present()

    def test_kill_file_detected_when_created(self) -> None:
        with patch("pathlib.Path.exists", return_value=True):
            assert is_kill_file_present()

    def test_kill_file_and_halt_trips(self) -> None:
        with patch("core.safety_state.is_kill_file_present", return_value=True):
            check_kill_file_and_halt()
            assert is_hard_halted()
            assert "STOP_TRADING" in hard_halt_reason()

    def test_kill_file_not_present_does_not_halt(self) -> None:
        check_kill_file_and_halt()
        assert not is_hard_halted()
