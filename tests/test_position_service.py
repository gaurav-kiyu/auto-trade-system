"""Tests for core/position_service.py - PositionService."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from core.ports.execution.execution_port import OrderStatus
from core.position_service import PositionService, get_position_service, reset_position_service


@pytest.fixture
def service():
    """Create a PositionService with mock dependencies."""
    risk_mock = MagicMock()
    risk_mock.get_portfolio_risk_metrics.return_value = MagicMock(
        open_positions_count=0,
        consecutive_losses=0,
        daily_pnl=100.0,
        max_daily_loss=-2000.0,
        max_consecutive_losses=3,
        available_capital=5000.0,
    )
    risk_mock.evaluate_trade.return_value = MagicMock(
        decision=MagicMock(value="allowed"),
        reason="OK",
        risk_score=0.0,
    )

    execution_mock = MagicMock()
    execution_mock.execute_order.return_value = MagicMock(
        status=OrderStatus.FILLED,
        order_id="test_order_123",
        average_price=105.0,
        reject_reason=None,
    )

    portfolio_mock = MagicMock()
    portfolio_mock.get_available_margin.return_value = 50000.0

    margin_mock = MagicMock()
    margin_mock.validate.return_value = MagicMock(allowed=True, error_message="", warning_message=None)

    warmup_mock = MagicMock()
    warmup_mock.can_enter.return_value = True
    warmup_mock.adjusted_position_size.return_value = 1

    news_mock = MagicMock()
    news_mock.get_current_risk.return_value = MagicMock(risk_level="LOW", headline="")

    expiry_mock = MagicMock()
    expiry_mock.can_enter_position.return_value = MagicMock(allowed=True, reason="", session=MagicMock(value="NORMAL"), risk_level="LOW")

    token_mock = MagicMock()
    token_mock._enabled = False

    audit_mock = MagicMock()

    mandate_mock = MagicMock()
    mandate_mock.get_position_size.return_value = 1

    positions: dict = {}
    decision_log: dict = {}
    manual_sig_last: set = set()
    breakout_state: dict = {}
    reentry_trackers: dict = {}

    from threading import Lock
    bos_lock = Lock()
    state_lock = Lock()
    pos_lock = Lock()

    yield PositionService(
        cfg={"SL_PCT": 0.92, "TARGET_PCT": 1.3, "TRAIL_PCT": 0.93, "TRAIL_ACTIVATE": 1.1, "MAX_POSITION_AGE": 9999},
        risk_service=risk_mock,
        execution_service=execution_mock,
        portfolio_service=portfolio_mock,
        margin_validator=margin_mock,
        warmup_manager=warmup_mock,
        news_sentinel=news_mock,
        expiry_controller=expiry_mock,
        token_refresh_service=token_mock,
        audit_engine=audit_mock,
        reentry_trackers=reentry_trackers,
        positions=positions,
        decision_log=decision_log,
        manual_sig_last=manual_sig_last,
        breakout_state=breakout_state,
        bos_lock=bos_lock,
        state_lock=state_lock,
        pos_lock=pos_lock,
        mandate_service=mandate_mock,
        signal_max_age=90,
        manual_signals_only=False,
        execution_mode="AUTO",
    )


class TestEnterTrade:
    """Tests for PositionService.enter_trade()."""

    def test_successful_entry(self, service):
        """Successful trade entry should store position."""
        import time
        sig = {
            "signal": "BUY", "direction": "CALL", "price": 100.0,
            "score": 85, "signal_ts": time.time(), "rr": 2.0,
        }
        with patch("core.datetime_ist.is_in_auction_session", return_value=False):
            service.enter_trade("NIFTY", sig)
        assert "NIFTY" in service._positions
        assert service._positions["NIFTY"]["qty"] > 0

    def test_blocked_hard_halt(self, service):
        """Hard halt should block entry."""
        with patch("core.safety_state.is_hard_halted", return_value=True):
            with patch("core.datetime_ist.is_in_auction_session", return_value=False):
                service.enter_trade("NIFTY", {"direction": "CALL", "price": 100.0})
        assert "NIFTY" not in service._positions

    def test_blocked_news_high(self, service):
        """HIGH news risk should block entry."""
        service._news_sentinel.get_current_risk.return_value = MagicMock(risk_level="HIGH", headline="Breaking news")
        sig = {"direction": "CALL", "price": 100.0, "score": 85}
        service.enter_trade("NIFTY", sig)
        assert "NIFTY" not in service._positions

    def test_blocked_warmup(self, service):
        """Warm-up block should prevent entry."""
        service._warmup_manager.can_enter.return_value = False
        sig = {"direction": "CALL", "price": 100.0, "score": 85}
        service.enter_trade("NIFTY", sig)
        assert "NIFTY" not in service._positions

    def test_blocked_expiry(self, service):
        """Expiry day block should prevent entry."""
        service._expiry_controller.can_enter_position.return_value = MagicMock(
            allowed=False, reason="Expiry cutoff", session=MagicMock(value="CAUTION"), risk_level="HIGH",
        )
        sig = {"direction": "CALL", "price": 100.0, "score": 85}
        service.enter_trade("NIFTY", sig)
        assert "NIFTY" not in service._positions

    def test_blocked_auction(self, service):
        """Auction session should block entry."""
        with patch("core.datetime_ist.is_in_auction_session", return_value=True):
            sig = {"direction": "CALL", "price": 100.0, "score": 85}
            service.enter_trade("NIFTY", sig)
        assert "NIFTY" not in service._positions

    def test_blocked_risk_eval(self, service):
        """Risk evaluation block should prevent entry."""
        service._risk_service.evaluate_trade.return_value = MagicMock(
            decision=MagicMock(value="denied"), reason="Daily loss limit", risk_score=0.8,
        )
        sig = {"direction": "CALL", "price": 100.0, "score": 85}
        service.enter_trade("NIFTY", sig)
        assert "NIFTY" not in service._positions

    def test_stale_signal(self, service):
        """Stale signal should be blocked."""
        sig = {"direction": "CALL", "price": 100.0, "score": 85, "signal_ts": 0.0}
        service.enter_trade("NIFTY", sig)
        assert "NIFTY" not in service._positions

    def test_manual_mode(self, service):
        """Manual mode should log signal without entering position."""
        service._manual_signals_only = True
        sig = {"direction": "CALL", "price": 100.0, "score": 85, "signal_ts": 1000000.0}
        service.enter_trade("NIFTY", sig)
        # In manual mode, should log decision but not enter position
        assert "NIFTY" not in service._positions


class TestMonitorPositions:
    """Tests for PositionService.monitor_positions()."""

    def test_no_positions(self, service):
        """No positions should be a no-op."""
        service.monitor_positions()  # Should not raise

    def test_sl_hit_call(self, service):
        """CALL position should exit on SL hit."""
        with patch.object(service, "_get_underlying_ltp", return_value=90.0):
            service._positions["NIFTY"] = {
                "direction": "CALL", "qty": 1, "entry_price": 100.0,
                "underlying_entry_price": 100.0, "entry_time": 1000.0,
            }
            with patch.object(service, "exit_position") as mock_exit:
                service.monitor_positions()
                mock_exit.assert_called_with("NIFTY", "SL_HIT")

    def test_target_hit_call(self, service):
        """CALL position should exit on target hit."""
        with patch.object(service, "_get_underlying_ltp", return_value=135.0):
            service._positions["NIFTY"] = {
                "direction": "CALL", "qty": 1, "entry_price": 100.0,
                "underlying_entry_price": 100.0, "entry_time": 1000.0,
            }
            with patch.object(service, "exit_position") as mock_exit:
                service.monitor_positions()
                mock_exit.assert_called_with("NIFTY", "TARGET_HIT")

    def test_sl_hit_put(self, service):
        """PUT position should exit on SL hit (underlying up)."""
        with patch.object(service, "_get_underlying_ltp", return_value=110.0):
            service._positions["NIFTY"] = {
                "direction": "PUT", "qty": 1, "entry_price": 100.0,
                "underlying_entry_price": 100.0, "entry_time": 1000.0,
            }
            with patch.object(service, "exit_position") as mock_exit:
                service.monitor_positions()
                mock_exit.assert_called_with("NIFTY", "SL_HIT")


class TestExitPosition:
    """Tests for PositionService.exit_position()."""

    def test_exit_no_position(self, service):
        """Exiting a non-existent position should be a no-op."""
        service.exit_position("NIFTY", "MANUAL")  # Should not raise

    def test_successful_exit(self, service):
        """Successful exit should remove position."""
        service._positions["NIFTY"] = {
            "direction": "CALL", "qty": 1, "entry_price": 100.0,
            "entry_order_direction": "BUY", "entry_time": 1000.0,
        }
        with patch.object(service, "_get_underlying_ltp", return_value=105.0):
            with patch.object(service, "_send_notification"):
                service.exit_position("NIFTY", "TARGET_HIT")
        assert "NIFTY" not in service._positions

    def test_exit_sends_notification(self, service):
        """Exit should log the exit event."""
        service._positions["NIFTY"] = {
            "direction": "CALL", "qty": 1, "entry_price": 100.0,
            "entry_order_direction": "BUY", "entry_time": 1000.0,
        }
        with patch.object(service, "_get_underlying_ltp", return_value=105.0):
            with patch.object(service, "_send_notification") as mock_send:
                service.exit_position("NIFTY", "TARGET_HIT")
                mock_send.assert_called_once()
                assert "EXIT NIFTY" in mock_send.call_args[0][0]


class TestGetPositionService:
    """Tests for get_position_service singleton factory."""

    def setup_method(self):
        reset_position_service()

    def test_get_instance(self):
        instance = get_position_service()
        assert isinstance(instance, PositionService)

    def test_singleton_behavior(self):
        s1 = get_position_service()
        s2 = get_position_service()
        assert s1 is s2

    def test_reset(self):
        s1 = get_position_service()
        reset_position_service()
        s2 = get_position_service()
        assert s1 is not s2
