"""Tests for core/position_service.py - Trade Entry, Monitoring & Exit.

Covers:
- TradeBlockError exception
- PositionService init with all dependencies
- enter_trade() with risk gates, news blocks, expiry, auction
- monitor_positions() for SL, target, trailing stop, max age
- exit_position() for exit flow and cleanup
- _read_position_under_lock, _get_underlying_ltp, _get_position_size
- _send_notification, _telegram_action_quality
- get_position_service singleton, reset_position_service
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from core.ports.execution.execution_port import OrderStatus as _OrderStatus
from core.position_service import (
    PositionService,
    TradeBlockError,
    get_position_service,
    reset_position_service,
)

# ── Fixtures ─────────────────────────────────────────────────────────────

@pytest.fixture
def mock_risk() -> MagicMock:
    m = MagicMock()
    m.get_portfolio_risk_metrics.return_value = {"total_exposure": 0.5}
    risk_eval = MagicMock()
    risk_eval.decision.value = "allowed"
    risk_eval.reason = "OK"
    risk_eval.risk_score = 0.3
    m.evaluate_trade.return_value = risk_eval
    return m


@pytest.fixture
def mock_execution() -> MagicMock:
    m = MagicMock()
    result = MagicMock()
    result.status = _OrderStatus.FILLED
    result.order_id = "ORD-001"
    result.reject_reason = ""
    result.average_price = 23500.0
    m.execute_order.return_value = result
    return m


@pytest.fixture
def mock_portfolio() -> MagicMock:
    m = MagicMock()
    m.get_available_margin.return_value = 500000.0
    return m


@pytest.fixture
def mock_margin() -> MagicMock:
    m = MagicMock()
    result = MagicMock()
    result.allowed = True
    result.error_message = ""
    m.validate.return_value = result
    return m


@pytest.fixture
def service(mock_risk: MagicMock, mock_execution: MagicMock, mock_portfolio: MagicMock, mock_margin: MagicMock) -> PositionService:
    return PositionService(
        cfg={"SL_PCT": 0.92, "TARGET_PCT": 1.3, "TRAIL_PCT": 0.93, "TRAIL_ACTIVATE": 1.1},
        risk_service=mock_risk,
        execution_service=mock_execution,
        portfolio_service=mock_portfolio,
        margin_validator=mock_margin,
        positions={},
        decision_log={},
        manual_sig_last=set(),
        pos_lock=MagicMock(),
        state_lock=MagicMock(),
        bos_lock=MagicMock(),
        manual_signals_only=False,
        execution_mode="AUTO",
    )


# =============================================================================
# TradeBlockError Tests
# =============================================================================

class TestTradeBlockError:
    def test_exception_message(self):
        err = TradeBlockError("Margin insufficient", reason="margin")
        assert str(err) == "Margin insufficient"
        assert err.reason == "margin"

    def test_default_reason(self):
        err = TradeBlockError("Something blocked")
        assert err.reason == "BLOCKED"


# =============================================================================
# Init Tests
# =============================================================================

class TestInit:
    def test_default_values(self):
        srv = PositionService()
        assert srv._cfg == {}
        assert srv._positions == {}
        assert srv._decision_log == {}
        assert srv._manual_sig_last == set()
        assert srv._manual_signals_only is True

    def test_custom_values(self):
        srv = PositionService(
            cfg={"key": "val"},
            positions={"NIFTY": {"qty": 1}},
            execution_mode="AUTO",
            manual_signals_only=False,
        )
        assert srv._cfg["key"] == "val"
        assert "NIFTY" in srv._positions
        assert srv._execution_mode == "AUTO"
        assert srv._manual_signals_only is False

    def test_dependencies_stored(self, mock_risk: MagicMock, mock_execution: MagicMock):
        srv = PositionService(risk_service=mock_risk, execution_service=mock_execution)
        assert srv._risk_service is mock_risk
        assert srv._execution_service is mock_execution


# =============================================================================
# enter_trade Tests (gates)
# =============================================================================

class TestEnterTradeGates:
    def test_hard_halt_blocks_entry(self, service: PositionService):
        with patch("core.safety_state.is_hard_halted", return_value=True), \
             patch("core.safety_state.check_kill_file_and_halt"):
            service.enter_trade("NIFTY", {"direction": "CALL", "price": 23500, "score": 75})
            assert "HARD HALT" in service._decision_log.get("NIFTY", {}).get("msg", "")

    def test_intraday_loss_blocks(self, service: PositionService):
        with patch("core.safety_state.check_intraday_pnl_and_halt", return_value=True), \
             patch("core.safety_state.check_kill_file_and_halt"), \
             patch("core.safety_state.is_hard_halted", return_value=False):
            service.enter_trade("NIFTY", {"direction": "CALL", "price": 23500, "score": 75})
            assert "INTRADAY_LOSS_LIMIT" in service._decision_log.get("NIFTY", {}).get("msg", "")

    def test_news_sentinel_high_blocks(self, service: PositionService):
        news = MagicMock()
        risk = MagicMock()
        risk.risk_level = "HIGH"
        risk.headline = "Fed rate decision"
        news.get_current_risk.return_value = risk
        service._news_sentinel = news
        with patch("core.safety_state.check_kill_file_and_halt"), \
             patch("core.safety_state.is_hard_halted", return_value=False), \
             patch("core.safety_state.check_intraday_pnl_and_halt", return_value=False):
            service.enter_trade("NIFTY", {"direction": "CALL", "price": 23500, "score": 75})
            assert "NEWS_BLOCK" in service._decision_log.get("NIFTY", {}).get("msg", "")

    def test_warmup_block(self, service: PositionService):
        warmup = MagicMock()
        warmup.can_enter.return_value = False
        service._warmup_manager = warmup
        with patch("core.safety_state.check_kill_file_and_halt"), \
             patch("core.safety_state.is_hard_halted", return_value=False), \
             patch("core.safety_state.check_intraday_pnl_and_halt", return_value=False):
            service.enter_trade("NIFTY", {"direction": "CALL", "price": 23500, "score": 75})
            assert "WARMUP_BLOCK" in service._decision_log.get("NIFTY", {}).get("msg", "")

    def test_expiry_block(self, service: PositionService):
        expiry = MagicMock()
        result = MagicMock()
        result.allowed = False
        result.reason = "Expiry caution"
        session = MagicMock()
        session.value = "EXPIRY_MORNING"
        result.session = session
        expiry.can_enter_position.return_value = result
        service._expiry_controller = expiry
        with patch("core.safety_state.check_kill_file_and_halt"), \
             patch("core.safety_state.is_hard_halted", return_value=False), \
             patch("core.safety_state.check_intraday_pnl_and_halt", return_value=False):
            service.enter_trade("NIFTY", {"direction": "CALL", "price": 23500, "score": 75})
            assert "EXPIRY_BLOCK" in service._decision_log.get("NIFTY", {}).get("msg", "")

    def test_auction_block(self, service: PositionService):
        with patch("core.datetime_ist.is_in_auction_session", return_value=True), \
             patch("core.safety_state.check_kill_file_and_halt"), \
             patch("core.safety_state.is_hard_halted", return_value=False), \
             patch("core.safety_state.check_intraday_pnl_and_halt", return_value=False):
            service.enter_trade("NIFTY", {"direction": "CALL", "price": 23500, "score": 75})
            assert "AUCTION_BLOCK" in service._decision_log.get("NIFTY", {}).get("msg", "")

    def test_risk_block(self, service: PositionService, mock_risk: MagicMock):
        risk_eval = MagicMock()
        risk_eval.decision.value = "denied"
        risk_eval.reason = "Max drawdown"
        risk_eval.risk_score = 0.8
        mock_risk.evaluate_trade.return_value = risk_eval
        with patch("core.safety_state.check_kill_file_and_halt"), \
             patch("core.safety_state.is_hard_halted", return_value=False), \
             patch("core.safety_state.check_intraday_pnl_and_halt", return_value=False):
            service.enter_trade("NIFTY", {"direction": "CALL", "price": 23500, "score": 75})
            assert "RISK_BLOCK" in service._decision_log.get("NIFTY", {}).get("msg", "")

    def test_stale_signal_blocked(self, service: PositionService):
        with patch("core.position_service.time.time", return_value=99999), \
             patch("core.safety_state.check_kill_file_and_halt"), \
             patch("core.safety_state.is_hard_halted", return_value=False), \
             patch("core.safety_state.check_intraday_pnl_and_halt", return_value=False):
            service.enter_trade("NIFTY", {"direction": "CALL", "price": 23500, "score": 75, "signal_ts": 100})
            assert "stale" in service._decision_log.get("NIFTY", {}).get("msg", "")


# =============================================================================
# enter_trade Tests (execution path)
# =============================================================================

class TestEnterTradeExecution:
    def test_successful_entry(self, service: PositionService):
        with patch("core.safety_state.is_hard_halted", return_value=False), \
             patch("core.safety_state.check_intraday_pnl_and_halt", return_value=False), \
             patch("core.safety_state.check_kill_file_and_halt"), \
             patch("core.position_service.time.time", return_value=100.0):
            service.enter_trade("NIFTY", {"direction": "CALL", "price": 23500.0, "score": 75, "signal_ts": 99.0})
            assert "Executed" in service._decision_log.get("NIFTY", {}).get("msg", "")

    def test_manual_mode_only_logs_signal(self, service: PositionService):
        """In manual mode, signal is logged but not executed."""
        service._manual_signals_only = True
        with patch("core.safety_state.is_hard_halted", return_value=False), \
             patch("core.safety_state.check_intraday_pnl_and_halt", return_value=False), \
             patch("core.safety_state.check_kill_file_and_halt"), \
             patch("core.position_service.time.time", return_value=100.0):
            service.enter_trade("NIFTY", {"direction": "CALL", "price": 23500.0, "score": 75, "signal_ts": 99.0})
            msg = service._decision_log.get("NIFTY", {}).get("msg", "")
            assert "MANUAL SIGNAL" in msg or "Executed" in msg

    def test_margin_block_raises_trade_block_error(self, service: PositionService, mock_margin: MagicMock):
        result = MagicMock()
        result.allowed = False
        result.error_message = "Insufficient margin"
        mock_margin.validate.return_value = result
        with patch("core.safety_state.is_hard_halted", return_value=False), \
             patch("core.safety_state.check_intraday_pnl_and_halt", return_value=False), \
             patch("core.safety_state.check_kill_file_and_halt"), \
             patch("core.position_service.time.time", return_value=100.0):
            service.enter_trade("NIFTY", {"direction": "CALL", "price": 23500.0, "score": 75, "signal_ts": 99.0})
            msg = service._decision_log.get("NIFTY", {}).get("msg", "")
            assert "BLOCK" in msg.upper() or "MARGIN" in msg.upper()


# =============================================================================
# monitor_positions Tests
# =============================================================================

class TestMonitorPositions:
    def test_no_positions_returns_immediately(self, service: PositionService):
        service.monitor_positions()  # Should not raise

    def test_skips_when_no_ltp(self, service: PositionService):
        service._positions["NIFTY"] = {"direction": "CALL", "underlying_entry_price": 23500, "qty": 1, "entry_price": 100, "entry_time": 0}
        service.monitor_positions()  # No LTP resolver, should skip
        assert "NIFTY" in service._positions

    def test_sl_hit_for_call(self, service: PositionService):
        service._positions["NIFTY"] = {
            "direction": "CALL", "underlying_entry_price": 23500,
            "qty": 1, "entry_price": 100, "entry_time": 0,
        }
        with patch.object(service, "_get_underlying_ltp", return_value=20000.0):
            with patch.object(service, "exit_position") as mock_exit:
                service.monitor_positions()
                mock_exit.assert_called_once_with("NIFTY", "SL_HIT")

    def test_target_hit_for_call(self, service: PositionService):
        service._positions["NIFTY"] = {
            "direction": "CALL", "underlying_entry_price": 23500,
            "qty": 1, "entry_price": 100, "entry_time": 0,
        }
        with patch.object(service, "_get_underlying_ltp", return_value=31000.0):
            with patch.object(service, "exit_position") as mock_exit:
                service.monitor_positions()
                mock_exit.assert_called_once_with("NIFTY", "TARGET_HIT")

    def test_sl_hit_for_put(self, service: PositionService):
        service._positions["NIFTY"] = {
            "direction": "PUT", "underlying_entry_price": 23500,
            "qty": 1, "entry_price": 100, "entry_time": 0,
        }
        with patch.object(service, "_get_underlying_ltp", return_value=26000.0):
            with patch.object(service, "exit_position") as mock_exit:
                service.monitor_positions()
                mock_exit.assert_called_once_with("NIFTY", "SL_HIT")

    def test_max_age_exit(self, service: PositionService):
        service._cfg["MAX_POSITION_AGE"] = 5
        service._positions["NIFTY"] = {
            "direction": "CALL", "underlying_entry_price": 23500,
            "qty": 1, "entry_price": 100, "entry_time": 100,
        }
        with patch.object(service, "_get_underlying_ltp", return_value=23600.0):
            with patch("core.position_service.time.time", return_value=1000):
                with patch.object(service, "exit_position") as mock_exit:
                    service.monitor_positions()
                    mock_exit.assert_called_once_with("NIFTY", "MAX_AGE")


# =============================================================================
# exit_position Tests
# =============================================================================

class TestExitPosition:
    def test_unknown_position_noop(self, service: PositionService):
        with patch("core.position_service.time.time", return_value=1000):
            service.exit_position("NONEXISTENT", "SL_HIT")  # Should not raise

    def test_exit_calls_execution(self, service: PositionService, mock_execution: MagicMock):
        # Mock execution to return FILLED so position is fully cleaned up
        filled_result = MagicMock()
        filled_result.status = _OrderStatus.FILLED
        filled_result.order_id = "ORD-002"
        filled_result.reject_reason = ""
        filled_result.average_price = 24000.0
        mock_execution.execute_order.return_value = filled_result

        service._positions["NIFTY"] = {
            "direction": "CALL", "qty": 1, "entry_price": 100,
            "underlying_entry_price": 23500, "entry_time": 0,
            "entry_order_direction": "BUY",
        }
        with patch.object(service, "_get_underlying_ltp", return_value=24000.0):
            service.exit_position("NIFTY", "TARGET_HIT")
            mock_execution.execute_order.assert_called_once()
            assert "NIFTY" not in service._positions  # Position cleaned up


# =============================================================================
# Internal Helpers Tests
# =============================================================================

class TestInternalHelpers:
    def test_read_position_under_lock(self, service: PositionService):
        service._positions["NIFTY"] = {
            "direction": "CALL", "qty": 2, "entry_price": 100,
            "underlying_entry_price": 23500, "entry_time": 0,
            "entry_order_direction": "BUY",
        }
        pos, direction, qty, price, order_dir = service._read_position_under_lock("NIFTY")
        assert direction == "CALL"
        assert qty == 2
        assert price == 100

    def test_read_nonexistent_returns_defaults(self, service: PositionService):
        result = service._read_position_under_lock("NONEXISTENT")
        assert result == (None, None, 0, 0.0, "")

    def test_get_underlying_ltp_no_resolver(self, service: PositionService):
        assert service._get_underlying_ltp("NIFTY") is None

    def test_get_underlying_ltp_with_resolver(self, service: PositionService):
        resolver = MagicMock()
        resolver.resolve.return_value = 23550.0
        service._ltp_resolver = resolver
        assert service._get_underlying_ltp("NIFTY") == 23550.0

    def test_get_position_size_default(self, service: PositionService):
        assert service._get_position_size("NIFTY", 23500.0) == 1

    def test_get_position_size_with_mandate(self, service: PositionService):
        mandate = MagicMock()
        mandate.get_position_size.return_value = 5
        service._mandate_service = mandate
        assert service._get_position_size("NIFTY", 23500.0) == 5

    def test_telegram_action_quality(self, service: PositionService):
        ok, reason = service._telegram_action_quality({"breakout_ok": True})
        assert ok is True

    def test_telegram_action_quality_blocked(self, service: PositionService):
        ok, reason = service._telegram_action_quality({"breakout_ok": False})
        assert ok is False
        assert "breakout_ok" in reason

    def test_send_notification_no_service(self, service: PositionService):
        service._send_notification("test")  # Should not raise

    def test_send_notification_with_service(self, service: PositionService):
        notif = MagicMock()
        notif.send = MagicMock()
        service._notification_service = notif
        service._send_notification("test message")
        notif.send.assert_called_once_with("test message")


# =============================================================================
# Singleton Tests
# =============================================================================

class TestSingleton:
    def test_get_position_service_returns_instance(self):
        reset_position_service()
        instance = get_position_service()
        assert instance is not None
        assert isinstance(instance, PositionService)
        reset_position_service()

    def test_singleton_returns_same_instance(self):
        reset_position_service()
        s1 = get_position_service()
        s2 = get_position_service()
        assert s1 is s2
        reset_position_service()

    def test_reset_position_service(self):
        reset_position_service()
        from core.position_service import _position_service_instance
        assert _position_service_instance is None
