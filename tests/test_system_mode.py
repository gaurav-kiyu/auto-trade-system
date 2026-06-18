"""Tests for SystemModeManager - system operational mode state machine."""

from __future__ import annotations

from unittest.mock import Mock


from core.system_mode import (
    SystemMode,
    SystemModeManager,
    SystemModeReason,
    SystemState,
    can_exit,
    can_trade,
    get_current_mode,
    get_system_mode_manager,
)


class TestSystemModeManager:
    """SystemModeManager - thread-safe system mode state machine."""

    def test_default_mode_is_normal(self):
        mgr = SystemModeManager()
        assert mgr.get_current_mode() == SystemMode.NORMAL

    def test_get_state_returns_snapshot(self):
        mgr = SystemModeManager()
        state = mgr.get_state()
        assert isinstance(state, SystemState)
        assert state.mode == SystemMode.NORMAL

    # ── Normal mode ────────────────────────────────────────────────

    def test_can_enter_new_trade_normal(self):
        mgr = SystemModeManager()
        allowed, _ = mgr.can_enter_new_trade()
        assert allowed is True

    def test_can_exit_normal(self):
        mgr = SystemModeManager()
        allowed, _ = mgr.can_exit_position()
        assert allowed is True

    def test_can_reconcile_normal(self):
        mgr = SystemModeManager()
        assert mgr.can_reconcile() is True

    # ── Degraded mode ──────────────────────────────────────────────

    def test_degraded_blocks_new_trades(self):
        mgr = SystemModeManager()
        mgr.set_degraded("API rate limit")
        allowed, reason = mgr.can_enter_new_trade()
        assert allowed is False
        assert "degraded" in reason.lower()

    def test_degraded_allows_exits(self):
        mgr = SystemModeManager()
        mgr.set_degraded()
        allowed, _ = mgr.can_exit_position()
        assert allowed is True

    def test_degraded_reason_stored(self):
        mgr = SystemModeManager()
        mgr.set_degraded("Broker API timeout")
        state = mgr.get_state()
        assert "timeout" in state.reason_detail.lower()

    # ── Broker down mode ───────────────────────────────────────────

    def test_broker_down_blocks_new_trades(self):
        mgr = SystemModeManager(config={"BROKER_FAILURE_THRESHOLD": 1})
        mgr.set_broker_down("Connection refused")
        allowed, _ = mgr.can_enter_new_trade()
        assert allowed is False

    def test_broker_down_allows_exits(self):
        mgr = SystemModeManager(config={"BROKER_FAILURE_THRESHOLD": 1})
        mgr.set_broker_down()
        allowed, _ = mgr.can_exit_position()
        assert allowed is True

    def test_broker_down_needs_threshold_failures(self):
        mgr = SystemModeManager(config={"BROKER_FAILURE_THRESHOLD": 3})
        # First two failures should stay in current mode
        mgr.set_broker_down("fail 1")
        assert mgr.get_current_mode() == SystemMode.NORMAL
        mgr.set_broker_down("fail 2")
        assert mgr.get_current_mode() == SystemMode.NORMAL
        mgr.set_broker_down("fail 3")
        assert mgr.get_current_mode() == SystemMode.BROKER_DOWN

    # ── Market halted mode ─────────────────────────────────────────

    def test_market_halted_blocks_new_trades(self):
        mgr = SystemModeManager()
        mgr.set_market_halted("Market closed")
        allowed, _ = mgr.can_enter_new_trade()
        assert allowed is False

    def test_market_halted_blocks_exits(self):
        mgr = SystemModeManager()
        mgr.set_market_halted()
        allowed, _ = mgr.can_exit_position()
        assert allowed is False

    # ── Safe mode ──────────────────────────────────────────────────

    def test_safe_mode_blocks_new_trades(self):
        mgr = SystemModeManager()
        mgr.set_safe_mode("Max drawdown hit")
        allowed, _ = mgr.can_enter_new_trade()
        assert allowed is False

    def test_safe_mode_allows_exits(self):
        mgr = SystemModeManager()
        mgr.set_safe_mode()
        allowed, _ = mgr.can_exit_position()
        assert allowed is True

    def test_safe_mode_hard_halt_reason(self):
        mgr = SystemModeManager()
        mgr.set_safe_mode("Hard halt triggered", from_hard_halt=True)
        state = mgr.get_state()
        assert state.reason == SystemModeReason.HARD_HALT

    # ── Mode transitions ───────────────────────────────────────────

    def test_set_normal_transition(self):
        mgr = SystemModeManager()
        mgr.set_degraded("test")
        mgr.set_normal("Broker reconnected")
        assert mgr.get_current_mode() == SystemMode.NORMAL

    def test_set_normal_resets_failures(self):
        mgr = SystemModeManager(config={"BROKER_FAILURE_THRESHOLD": 2})
        mgr.set_broker_down("fail")
        mgr.set_broker_down("fail")
        # Should be in broker down
        assert mgr.get_current_mode() == SystemMode.BROKER_DOWN
        mgr.record_broker_success()
        assert mgr.get_current_mode() == SystemMode.NORMAL
        state = mgr.get_state()
        assert state.consecutive_failures == 0

    def test_transition_triggers_callback(self):
        callback = Mock()
        mgr = SystemModeManager(on_mode_change=callback)
        mgr.set_degraded("API issue")
        callback.assert_called_once()
        args = callback.call_args[0]
        assert args[0] == SystemMode.NORMAL  # old
        assert args[1] == SystemMode.DEGRADED  # new

    def test_same_mode_no_callback(self):
        callback = Mock()
        mgr = SystemModeManager(on_mode_change=callback)
        mgr.set_normal("already normal")
        callback.assert_not_called()

    def test_callback_exception_does_not_crash(self):
        def failing(*args):
            raise RuntimeError("Callback error")

        mgr = SystemModeManager(on_mode_change=failing)
        mgr.set_degraded("test")  # should not raise

    # ── Broker success/failure recording ───────────────────────────

    def test_record_broker_success_transitions_to_normal(self):
        mgr = SystemModeManager(config={"BROKER_FAILURE_THRESHOLD": 1})
        mgr.set_broker_down("down")
        assert mgr.get_current_mode() == SystemMode.BROKER_DOWN
        mgr.record_broker_success()
        assert mgr.get_current_mode() == SystemMode.NORMAL

    def test_record_broker_failure_increments_counter(self):
        mgr = SystemModeManager(config={"BROKER_FAILURE_THRESHOLD": 3})
        mgr.record_broker_failure()
        state = mgr.get_state()
        assert state.consecutive_failures == 1

    # ── Market status ──────────────────────────────────────────────

    def test_check_market_status_closed_transitions(self):
        mgr = SystemModeManager()
        mgr.check_market_status(is_open=False)
        assert mgr.get_current_mode() == SystemMode.MARKET_HALTED

    def test_check_market_status_open_stays_normal(self):
        mgr = SystemModeManager()
        mgr.check_market_status(is_open=True)
        assert mgr.get_current_mode() == SystemMode.NORMAL

    # ── Health check ───────────────────────────────────────────────

    def test_health_check_returns_dict(self):
        mgr = SystemModeManager()
        health = mgr.health_check()
        assert isinstance(health, dict)
        assert "mode" in health
        assert health["mode"] == "NORMAL"

    def test_health_check_reflects_current_state(self):
        mgr = SystemModeManager()
        mgr.set_degraded("test")
        health = mgr.health_check()
        assert health["mode"] == "DEGRADED"
        assert health["broker_reachable"] is True

    # ── Module-level convenience functions ─────────────────────────

    def test_get_current_mode_defaults_normal(self):
        # Before any singleton is created
        assert get_current_mode() == SystemMode.NORMAL

    def test_can_trade_defaults_true(self):
        assert can_trade() == (True, "")

    def test_can_exit_defaults_true(self):
        assert can_exit() == (True, "")

    def test_singleton_persists_state(self):
        mgr = get_system_mode_manager()
        # Should return same instance on second call
        mgr2 = get_system_mode_manager()
        assert mgr is mgr2

    # ── Edge cases ─────────────────────────────────────────────────

    def test_state_snapshot_independent(self):
        mgr = SystemModeManager()
        state1 = mgr.get_state()
        mgr.set_degraded("test")
        state2 = mgr.get_state()
        assert state1.mode != state2.mode
        # Verify original is unmodified
        assert state1.mode == SystemMode.NORMAL
        assert state2.mode == SystemMode.DEGRADED

    def test_can_reconcile_broker_down(self):
        mgr = SystemModeManager(config={"BROKER_FAILURE_THRESHOLD": 1})
        mgr.set_broker_down()
        assert mgr.can_reconcile() is True
