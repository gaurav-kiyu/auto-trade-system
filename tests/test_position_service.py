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


@pytest.fixture(autouse=True)
def _force_no_auction_window():
    """Force the NSE auction gate OFF for time-of-day test independence.

    ``PositionService.enter_trade`` calls ``core.datetime_ist.is_in_auction_session``
    (imported locally inside the method), which returns True during the NSE
    pre-open (09:00-09:15) and post-close (15:30-15:45) auction windows.
    A full-suite run that crosses 15:30 IST therefore makes every entry test
    fail with ``AUCTION_BLOCK`` unless the gate is pinned off here.

    ``test_auction_block`` explicitly patches the gate to True inside the
    test body, so it still exercises the blocking path.
    """
    with patch("core.datetime_ist.is_in_auction_session", return_value=False):
        yield


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
# Time-of-day filter wiring (config key TIME_OF_DAY_FILTER_ENABLED via
# time_of_day_hard_block_enabled, opt-in, default OFF — core/time_of_day_filter.py)
# =============================================================================

class TestTimeOfDayFilterWiring:
    def test_disabled_by_default_filter_not_consulted(self, service: PositionService):
        with patch("core.time_of_day_filter.create_time_of_day_filter") as mock_create, \
             patch("core.safety_state.is_hard_halted", return_value=False), \
             patch("core.safety_state.check_intraday_pnl_and_halt", return_value=False), \
             patch("core.safety_state.check_kill_file_and_halt"), \
             patch("core.position_service.time.time", return_value=100.0):
            service.enter_trade("NIFTY", {"direction": "CALL", "price": 23500.0, "score": 75, "signal_ts": 99.0})
            mock_create.assert_not_called()
            assert "Executed" in service._decision_log.get("NIFTY", {}).get("msg", "")

    def test_enabled_blocks_entry_with_real_reason(self, service: PositionService):
        service._cfg["time_of_day_hard_block_enabled"] = True
        mock_filter = MagicMock()
        mock_filter.should_allow_entry.return_value = (False, "Blocked trading hours: 14-15 IST")
        with patch("core.time_of_day_filter.create_time_of_day_filter", return_value=mock_filter), \
             patch("core.safety_state.is_hard_halted", return_value=False), \
             patch("core.safety_state.check_intraday_pnl_and_halt", return_value=False), \
             patch("core.safety_state.check_kill_file_and_halt"), \
             patch("core.position_service.time.time", return_value=100.0):
            service.enter_trade("NIFTY", {"direction": "CALL", "price": 23500.0, "score": 75, "signal_ts": 99.0, "regime": "SIDEWAYS"})
            mock_filter.should_allow_entry.assert_called_once_with(regime="SIDEWAYS")
            msg = service._decision_log.get("NIFTY", {}).get("msg", "")
            assert "TIME_OF_DAY_BLOCK" in msg
            assert "NIFTY" not in service._positions

    def test_enabled_allows_entry_when_filter_passes(self, service: PositionService):
        service._cfg["time_of_day_hard_block_enabled"] = True
        mock_filter = MagicMock()
        mock_filter.should_allow_entry.return_value = (True, "")
        with patch("core.time_of_day_filter.create_time_of_day_filter", return_value=mock_filter), \
             patch("core.safety_state.is_hard_halted", return_value=False), \
             patch("core.safety_state.check_intraday_pnl_and_halt", return_value=False), \
             patch("core.safety_state.check_kill_file_and_halt"), \
             patch("core.position_service.time.time", return_value=100.0):
            service.enter_trade("NIFTY", {"direction": "CALL", "price": 23500.0, "score": 75, "signal_ts": 99.0})
            assert "Executed" in service._decision_log.get("NIFTY", {}).get("msg", "")


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

    def test_successful_entry_records_trade_with_risk_service(self, service: PositionService, mock_risk: MagicMock):
        """A successful fill must feed RiskService's daily trade-count tracker,
        or MAX_TRADES_DAY is threaded through config but never enforced."""
        with patch("core.safety_state.is_hard_halted", return_value=False), \
             patch("core.safety_state.check_intraday_pnl_and_halt", return_value=False), \
             patch("core.safety_state.check_kill_file_and_halt"), \
             patch("core.position_service.time.time", return_value=100.0):
            service.enter_trade("NIFTY", {"direction": "CALL", "price": 23500.0, "score": 75, "signal_ts": 99.0})
            mock_risk.record_trade_entry.assert_called_once_with("NIFTY")

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

    def test_liquidity_block_with_failing_quote_data(self, service: PositionService):
        """When the signal carries real bid/ask/oi/volume that fail the
        liquidity_guard.py thresholds, entry is blocked with LIQUIDITY_BLOCK.
        """
        with patch("core.safety_state.is_hard_halted", return_value=False), \
             patch("core.safety_state.check_intraday_pnl_and_halt", return_value=False), \
             patch("core.safety_state.check_kill_file_and_halt"), \
             patch("core.position_service.time.time", return_value=100.0):
            service.enter_trade("NIFTY", {
                "direction": "CALL", "price": 23500.0, "score": 75, "signal_ts": 99.0,
                "bid": 100.0, "ask": 102.0, "oi": 50, "volume": 5,  # oi below default min_entry_oi=100
            })
            msg = service._decision_log.get("NIFTY", {}).get("msg", "")
            assert "LIQUIDITY_BLOCK" in msg

    def test_liquidity_fails_open_without_quote_data(self, service: PositionService):
        """Regression guard: today's real signals carry no bid/ask (no live
        option-quote feed exists yet) — the liquidity gate must fail open and
        leave entry behavior completely unchanged.
        """
        with patch("core.safety_state.is_hard_halted", return_value=False), \
             patch("core.safety_state.check_intraday_pnl_and_halt", return_value=False), \
             patch("core.safety_state.check_kill_file_and_halt"), \
             patch("core.position_service.time.time", return_value=100.0):
            service.enter_trade("NIFTY", {"direction": "CALL", "price": 23500.0, "score": 75, "signal_ts": 99.0})
            assert "Executed" in service._decision_log.get("NIFTY", {}).get("msg", "")


# =============================================================================
# Manual-signal notification message content (previously bare-bones:
# "[MANUAL SIGNAL] {name} {direction} @ {price} RR={rr}" - score/tier/regime/
# VIX/SL/target already existed on `sig` unused; this is the ONLY thing a
# manual-mode user sees per signal, so it matters for a fast, confident call)
# =============================================================================

class TestManualSignalMessageContent:
    def test_includes_score_tier_and_computed_sl_target_for_call(self, service: PositionService):
        msg = service._build_manual_signal_message(
            "NIFTY",
            {"direction": "CALL", "score": 85, "tier": "STRONG", "regime": "TRENDING", "vix": 15.2},
            price=100.0, rr=1.5,
        )
        assert "STRONG" in msg
        assert "85" in msg
        assert "TRENDING" in msg
        assert "15.2" in msg
        # SL_PCT=0.92, TARGET_PCT=1.3 from the fixture cfg -> SL=92.00, Target=130.00
        assert "92.00" in msg
        assert "130.00" in msg
        assert "RR=1.5" in msg

    def test_put_direction_mirrors_sl_target_around_price(self, service: PositionService):
        msg = service._build_manual_signal_message(
            "NIFTY", {"direction": "PUT", "score": 80, "tier": "MODERATE"}, price=100.0, rr=1.2,
        )
        # PUT: SL = price*(2-0.92)=108.00, Target = price*(2-1.3)=70.00
        assert "108.00" in msg
        assert "70.00" in msg

    def test_includes_soft_blocks_as_a_caution_line(self, service: PositionService):
        msg = service._build_manual_signal_message(
            "NIFTY", {"direction": "CALL", "soft_blocks": ["tf_mismatch", "choppy_regime"]}, price=100.0, rr=1.0,
        )
        assert "Caution" in msg
        assert "tf_mismatch" in msg
        assert "choppy_regime" in msg

    def test_missing_optional_fields_does_not_crash_or_add_empty_sections(self, service: PositionService):
        msg = service._build_manual_signal_message("NIFTY", {"direction": "CALL"}, price=100.0, rr=0.0)
        assert "Tier" not in msg  # header's (Tier: ..., Score: ...) suffix omitted entirely when neither is present
        assert "RR=0.0" in msg

    def test_bad_config_values_fail_open_to_no_levels_line(self, service: PositionService):
        service._cfg["SL_PCT"] = "not-a-number"
        msg = service._build_manual_signal_message("NIFTY", {"direction": "CALL"}, price=100.0, rr=1.0)  # must not raise
        assert "SL:" not in msg

    def test_enter_trade_manual_mode_sends_enriched_message(self, service: PositionService):
        service._manual_signals_only = True
        with patch("core.safety_state.is_hard_halted", return_value=False), \
             patch("core.safety_state.check_intraday_pnl_and_halt", return_value=False), \
             patch("core.safety_state.check_kill_file_and_halt"), \
             patch("core.position_service.time.time", return_value=100.0):
            service.enter_trade("NIFTY", {
                "direction": "CALL", "price": 23500.0, "score": 88, "tier": "STRONG",
                "regime": "TRENDING", "vix": 14.5, "signal_ts": 99.0,
            })
        msg = service._decision_log.get("NIFTY", {}).get("msg", "")
        assert "STRONG" in msg
        assert "88" in msg
        assert "TRENDING" in msg


# =============================================================================
# Capital-manager equity scaling wiring (opt-in — RiskService.scale_position /
# record_trade_result, backed by core.capital_manager.CapitalManager, default OFF)
# =============================================================================

class TestCapitalManagerEquityScalingWiring:
    def test_disabled_by_default_entry_qty_unchanged(self, service: PositionService, mock_risk: MagicMock):
        """Regression guard: with capital_manager_equity_scaling_enabled left at
        its default (False), scale_position must never be called and entry qty
        (here 1, since no mandate_service is wired in the test fixture) is
        completely unchanged."""
        with patch("core.safety_state.is_hard_halted", return_value=False), \
             patch("core.safety_state.check_intraday_pnl_and_halt", return_value=False), \
             patch("core.safety_state.check_kill_file_and_halt"), \
             patch("core.position_service.time.time", return_value=100.0):
            service.enter_trade("NIFTY", {"direction": "CALL", "price": 23500.0, "score": 75, "signal_ts": 99.0})
            mock_risk.scale_position.assert_not_called()
            assert service._positions["NIFTY"]["qty"] == 1

    def test_enabled_scales_entry_qty(self, service: PositionService, mock_risk: MagicMock):
        """With the flag on, scale_position()'s scaled_lots becomes the real
        stored qty — proving this is wired with real effect, not advisory."""
        service._cfg["capital_manager_equity_scaling_enabled"] = True
        service._cfg["VIX_SIZE_SCALE"] = False  # isolate from the separate always-on VIX-sizing block
        scale_result = MagicMock(scaled_lots=3)
        mock_risk.scale_position.return_value = scale_result
        with patch("core.safety_state.is_hard_halted", return_value=False), \
             patch("core.safety_state.check_intraday_pnl_and_halt", return_value=False), \
             patch("core.safety_state.check_kill_file_and_halt"), \
             patch("core.position_service.time.time", return_value=100.0):
            service.enter_trade("NIFTY", {"direction": "CALL", "price": 23500.0, "score": 75, "signal_ts": 99.0})
            mock_risk.scale_position.assert_called_once_with(base_lots=1, max_lots=1)
            assert service._positions["NIFTY"]["qty"] == 3

    def test_disabled_by_default_no_trade_result_recorded_on_exit(self, service: PositionService, mock_risk: MagicMock, mock_execution: MagicMock):
        filled_result = MagicMock(status=_OrderStatus.FILLED, order_id="ORD-003", reject_reason="", average_price=24000.0)
        mock_execution.execute_order.return_value = filled_result
        service._positions["NIFTY"] = {
            "direction": "CALL", "qty": 1, "entry_price": 100,
            "underlying_entry_price": 23500, "entry_time": 0,
            "entry_order_direction": "BUY",
        }
        with patch.object(service, "_get_underlying_ltp", return_value=24000.0):
            service.exit_position("NIFTY", "TARGET_HIT")
        mock_risk.record_trade_result.assert_not_called()

    def test_enabled_records_trade_result_on_exit(self, service: PositionService, mock_risk: MagicMock, mock_execution: MagicMock):
        service._cfg["capital_manager_equity_scaling_enabled"] = True
        filled_result = MagicMock(status=_OrderStatus.FILLED, order_id="ORD-004", reject_reason="", average_price=24000.0)
        mock_execution.execute_order.return_value = filled_result
        service._positions["NIFTY"] = {
            "direction": "CALL", "qty": 1, "entry_price": 100,
            "underlying_entry_price": 23500, "entry_time": 0,
            "entry_order_direction": "BUY",
        }
        with patch.object(service, "_get_underlying_ltp", return_value=24000.0):
            service.exit_position("NIFTY", "TARGET_HIT")
        mock_risk.record_trade_result.assert_called_once_with(net_pnl=(24000.0 - 100) * 1, is_winner=True)


# =============================================================================
# Intraday performance monitor wiring (opt-in — core.intraday_performance_monitor,
# get_intraday_monitor() singleton, default OFF)
# =============================================================================

class TestIntradayPerformanceMonitorWiring:
    def test_disabled_by_default_monitor_not_consulted(self, service: PositionService):
        """Regression guard: with intraday_performance_monitor_enabled left at
        its default (False), get_intraday_monitor() must never even be called,
        and entry qty (here 1, no mandate_service in the test fixture) is
        completely unchanged."""
        with patch("core.intraday_performance_monitor.get_intraday_monitor") as mock_get, \
             patch("core.safety_state.is_hard_halted", return_value=False), \
             patch("core.safety_state.check_intraday_pnl_and_halt", return_value=False), \
             patch("core.safety_state.check_kill_file_and_halt"), \
             patch("core.position_service.time.time", return_value=100.0):
            service.enter_trade("NIFTY", {"direction": "CALL", "price": 23500.0, "score": 75, "signal_ts": 99.0})
            mock_get.assert_not_called()
            assert service._positions["NIFTY"]["qty"] == 1

    def test_enabled_applies_position_size_multiplier(self, service: PositionService):
        """With the flag on, get_current_params().position_size_mult becomes
        the real stored qty multiplier — proving this is wired with real
        effect, not just an unread display field."""
        from core.intraday_performance_monitor import AdaptationParams

        service._cfg["intraday_performance_monitor_enabled"] = True
        service._cfg["VIX_SIZE_SCALE"] = False  # isolate from the separate always-on VIX-sizing block
        mock_monitor = MagicMock()
        mock_monitor.get_current_params.return_value = AdaptationParams(
            score_threshold_boost=0, position_size_mult=3.0, reason="test", level="NORMAL",
        )
        with patch("core.intraday_performance_monitor.get_intraday_monitor", return_value=mock_monitor), \
             patch("core.safety_state.is_hard_halted", return_value=False), \
             patch("core.safety_state.check_intraday_pnl_and_halt", return_value=False), \
             patch("core.safety_state.check_kill_file_and_halt"), \
             patch("core.position_service.time.time", return_value=100.0):
            service.enter_trade("NIFTY", {"direction": "CALL", "price": 23500.0, "score": 75, "signal_ts": 99.0})
            assert service._positions["NIFTY"]["qty"] == 3

    def test_disabled_by_default_no_record_trade_close_on_exit(self, service: PositionService, mock_execution: MagicMock):
        filled_result = MagicMock(status=_OrderStatus.FILLED, order_id="ORD-005", reject_reason="", average_price=24000.0)
        mock_execution.execute_order.return_value = filled_result
        service._positions["NIFTY"] = {
            "direction": "CALL", "qty": 1, "entry_price": 100,
            "underlying_entry_price": 23500, "entry_time": 0,
            "entry_order_direction": "BUY",
        }
        with patch("core.intraday_performance_monitor.get_intraday_monitor") as mock_get, \
             patch.object(service, "_get_underlying_ltp", return_value=24000.0):
            service.exit_position("NIFTY", "TARGET_HIT")
        mock_get.assert_not_called()

    def test_enabled_records_trade_close_on_exit(self, service: PositionService, mock_execution: MagicMock):
        service._cfg["intraday_performance_monitor_enabled"] = True
        mock_monitor = MagicMock()
        filled_result = MagicMock(status=_OrderStatus.FILLED, order_id="ORD-006", reject_reason="", average_price=24000.0)
        mock_execution.execute_order.return_value = filled_result
        service._positions["NIFTY"] = {
            "direction": "CALL", "qty": 1, "entry_price": 100,
            "underlying_entry_price": 23500, "entry_time": 0,
            "entry_order_direction": "BUY",
        }
        with patch("core.intraday_performance_monitor.get_intraday_monitor", return_value=mock_monitor), \
             patch.object(service, "_get_underlying_ltp", return_value=24000.0):
            service.exit_position("NIFTY", "TARGET_HIT")
        mock_monitor.record_trade_close.assert_called_once_with(pnl=(24000.0 - 100) * 1, was_winner=True)


# =============================================================================
# VIX-based sizing wiring (config key VIX_SIZE_SCALE, default ON — this key
# already existed at that default, so unlike the opt-in flags above, this
# one is live by default and every other test above relies on RiskService's
# mock (an unconfigured MagicMock) failing open here transparently)
# =============================================================================

class TestVixBasedSizingWiring:
    def test_disabled_multiplier_not_consulted(self, service: PositionService, mock_risk: MagicMock):
        service._cfg["VIX_SIZE_SCALE"] = False
        with patch("core.safety_state.is_hard_halted", return_value=False), \
             patch("core.safety_state.check_intraday_pnl_and_halt", return_value=False), \
             patch("core.safety_state.check_kill_file_and_halt"), \
             patch("core.position_service.time.time", return_value=100.0):
            service.enter_trade("NIFTY", {"direction": "CALL", "price": 23500.0, "score": 75, "signal_ts": 99.0})
            mock_risk.get_vix_size_multiplier.assert_not_called()
            assert service._positions["NIFTY"]["qty"] == 1

    def test_enabled_by_default_applies_real_multiplier(self, service: PositionService, mock_risk: MagicMock):
        """Default config (no VIX_SIZE_SCALE override) must actually apply
        get_vix_size_multiplier()'s result to qty — proving this is a real
        effect, not just a passthrough."""
        mock_risk.get_vix_size_multiplier.return_value = 3.0
        with patch("core.safety_state.is_hard_halted", return_value=False), \
             patch("core.safety_state.check_intraday_pnl_and_halt", return_value=False), \
             patch("core.safety_state.check_kill_file_and_halt"), \
             patch("core.position_service.time.time", return_value=100.0):
            service.enter_trade("NIFTY", {"direction": "CALL", "price": 23500.0, "score": 75, "signal_ts": 99.0, "vix": 20.0})
            mock_risk.get_vix_size_multiplier.assert_called_once_with(20.0)
            assert service._positions["NIFTY"]["qty"] == 3

    def test_missing_vix_on_signal_defaults_to_15(self, service: PositionService, mock_risk: MagicMock):
        mock_risk.get_vix_size_multiplier.return_value = 1.0
        with patch("core.safety_state.is_hard_halted", return_value=False), \
             patch("core.safety_state.check_intraday_pnl_and_halt", return_value=False), \
             patch("core.safety_state.check_kill_file_and_halt"), \
             patch("core.position_service.time.time", return_value=100.0):
            service.enter_trade("NIFTY", {"direction": "CALL", "price": 23500.0, "score": 75, "signal_ts": 99.0})
            mock_risk.get_vix_size_multiplier.assert_called_once_with(15.0)


# =============================================================================
# VIX soft-warning notification wiring (config key VIX_HALT_THRESHOLD via
# RiskService.is_vix_soft_warning() — non-blocking, informational only)
# =============================================================================

class TestVixSoftWarningNotificationWiring:
    def test_sends_notification_when_soft_threshold_crossed(self, service: PositionService, mock_risk: MagicMock):
        mock_risk.is_vix_soft_warning.return_value = True
        mock_notify = MagicMock()
        service._notification_service = mock_notify
        with patch("core.safety_state.is_hard_halted", return_value=False), \
             patch("core.safety_state.check_intraday_pnl_and_halt", return_value=False), \
             patch("core.safety_state.check_kill_file_and_halt"), \
             patch("core.position_service.time.time", return_value=100.0):
            service.enter_trade("NIFTY", {"direction": "CALL", "price": 23500.0, "score": 75, "signal_ts": 99.0, "vix": 32.0})
            mock_risk.is_vix_soft_warning.assert_called_once_with(32.0)
            mock_notify.send.assert_called_once()
            assert "VIX_SOFT_WARNING" in mock_notify.send.call_args[0][0]
            # Purely informational: trade still executes, qty unaffected by this check.
            assert "Executed" in service._decision_log.get("NIFTY", {}).get("msg", "")

    def test_no_notification_when_below_soft_threshold(self, service: PositionService, mock_risk: MagicMock):
        mock_risk.is_vix_soft_warning.return_value = False
        mock_notify = MagicMock()
        service._notification_service = mock_notify
        with patch("core.safety_state.is_hard_halted", return_value=False), \
             patch("core.safety_state.check_intraday_pnl_and_halt", return_value=False), \
             patch("core.safety_state.check_kill_file_and_halt"), \
             patch("core.position_service.time.time", return_value=100.0):
            service.enter_trade("NIFTY", {"direction": "CALL", "price": 23500.0, "score": 75, "signal_ts": 99.0, "vix": 12.0})
            mock_notify.send.assert_not_called()


# =============================================================================
# Per-trade SL-risk cap wiring (config key MAX_SINGLE_TRADE_LOSS_PCT via
# max_single_trade_loss_pct_enabled, opt-in, default OFF)
# =============================================================================

class TestPerTradeSlRiskCapWiring:
    def test_disabled_by_default_cap_not_consulted(self, service: PositionService, mock_risk: MagicMock):
        service._cfg["VIX_SIZE_SCALE"] = False  # isolate from the always-on VIX block
        with patch("core.safety_state.is_hard_halted", return_value=False), \
             patch("core.safety_state.check_intraday_pnl_and_halt", return_value=False), \
             patch("core.safety_state.check_kill_file_and_halt"), \
             patch("core.position_service.time.time", return_value=100.0):
            service.enter_trade("NIFTY", {"direction": "CALL", "price": 23500.0, "score": 75, "signal_ts": 99.0})
            mock_risk.get_single_trade_loss_cap_lots.assert_not_called()
            assert service._positions["NIFTY"]["qty"] == 1

    def test_enabled_caps_qty_downward_with_real_effect(self, service: PositionService, mock_risk: MagicMock):
        service._cfg["VIX_SIZE_SCALE"] = False
        service._cfg["max_single_trade_loss_pct_enabled"] = True
        mock_risk.get_single_trade_loss_cap_lots.return_value = 0
        with patch("core.safety_state.is_hard_halted", return_value=False), \
             patch("core.safety_state.check_intraday_pnl_and_halt", return_value=False), \
             patch("core.safety_state.check_kill_file_and_halt"), \
             patch("core.position_service.time.time", return_value=100.0):
            service.enter_trade("NIFTY", {"direction": "CALL", "price": 23500.0, "score": 75, "signal_ts": 99.0})
            # SL_PCT=0.92 from the fixture cfg -> price_diff = 23500 * 0.08
            mock_risk.get_single_trade_loss_cap_lots.assert_called_once_with(
                capital_available=100000.0, price_diff=pytest.approx(1880.0), lot_size=1,
            )
            assert service._positions["NIFTY"]["qty"] == 0

    def test_enabled_leaves_qty_unchanged_when_cap_not_binding(self, service: PositionService, mock_risk: MagicMock):
        service._cfg["VIX_SIZE_SCALE"] = False
        service._cfg["max_single_trade_loss_pct_enabled"] = True
        mock_risk.get_single_trade_loss_cap_lots.return_value = 50  # far above qty=1, not binding
        with patch("core.safety_state.is_hard_halted", return_value=False), \
             patch("core.safety_state.check_intraday_pnl_and_halt", return_value=False), \
             patch("core.safety_state.check_kill_file_and_halt"), \
             patch("core.position_service.time.time", return_value=100.0):
            service.enter_trade("NIFTY", {"direction": "CALL", "price": 23500.0, "score": 75, "signal_ts": 99.0})
            assert service._positions["NIFTY"]["qty"] == 1


# =============================================================================
# Portfolio-wide SL-risk cap wiring (config key PORTFOLIO_MAX_SL_RISK_PCT via
# portfolio_max_sl_risk_pct_enabled, opt-in, default OFF). Unlike the
# per-trade cap above, this one can block the entry outright rather than
# resize it.
# =============================================================================

class TestPortfolioSlRiskCapWiring:
    def test_disabled_by_default_check_not_consulted(self, service: PositionService, mock_risk: MagicMock):
        service._cfg["VIX_SIZE_SCALE"] = False
        with patch("core.safety_state.is_hard_halted", return_value=False), \
             patch("core.safety_state.check_intraday_pnl_and_halt", return_value=False), \
             patch("core.safety_state.check_kill_file_and_halt"), \
             patch("core.position_service.time.time", return_value=100.0):
            service.enter_trade("NIFTY", {"direction": "CALL", "price": 23500.0, "score": 75, "signal_ts": 99.0})
            mock_risk.check_portfolio_sl_risk.assert_not_called()
            assert "Executed" in service._decision_log.get("NIFTY", {}).get("msg", "")

    def test_enabled_blocks_entry_over_cap_using_real_open_position_risk(self, service: PositionService, mock_risk: MagicMock):
        """Proves the wiring aggregates real open-position SL-risk, not just
        a stub boolean: pre-seed one open NIFTY-style position and verify
        check_portfolio_sl_risk() is called with the actual computed
        open/new risk amounts before the block takes effect."""
        service._cfg["VIX_SIZE_SCALE"] = False
        service._cfg["portfolio_max_sl_risk_pct_enabled"] = True
        service._positions["BANKNIFTY"] = {"underlying_entry_price": 23000.0, "qty": 2}
        mock_risk.check_portfolio_sl_risk.return_value = False
        with patch("core.safety_state.is_hard_halted", return_value=False), \
             patch("core.safety_state.check_intraday_pnl_and_halt", return_value=False), \
             patch("core.safety_state.check_kill_file_and_halt"), \
             patch("core.position_service.time.time", return_value=100.0):
            service.enter_trade("NIFTY", {"direction": "CALL", "price": 23500.0, "score": 75, "signal_ts": 99.0})
            # open_risk = |23000 - 23000*0.92| * 2 = 3680.0; new_trade_risk = |23500 - 23500*0.92| * 1 = 1880.0
            mock_risk.check_portfolio_sl_risk.assert_called_once_with(
                pytest.approx(3680.0), 100000.0, pytest.approx(1880.0),
            )
            assert "PORTFOLIO_SL_RISK_BLOCK" in service._decision_log.get("NIFTY", {}).get("msg", "")
            assert "NIFTY" not in service._positions

    def test_enabled_allows_entry_within_cap_without_resizing(self, service: PositionService, mock_risk: MagicMock):
        service._cfg["VIX_SIZE_SCALE"] = False
        service._cfg["portfolio_max_sl_risk_pct_enabled"] = True
        mock_risk.check_portfolio_sl_risk.return_value = True
        with patch("core.safety_state.is_hard_halted", return_value=False), \
             patch("core.safety_state.check_intraday_pnl_and_halt", return_value=False), \
             patch("core.safety_state.check_kill_file_and_halt"), \
             patch("core.position_service.time.time", return_value=100.0):
            service.enter_trade("NIFTY", {"direction": "CALL", "price": 23500.0, "score": 75, "signal_ts": 99.0})
            assert "Executed" in service._decision_log.get("NIFTY", {}).get("msg", "")
            assert service._positions["NIFTY"]["qty"] == 1


# =============================================================================
# Expiry-day trade count cap wiring (config key EXPIRY_MAX_TRADES via
# expiry_max_trades_enabled, opt-in, default OFF)
# =============================================================================

class TestExpiryMaxTradesWiring:
    def test_disabled_by_default_not_consulted(self, service: PositionService, mock_risk: MagicMock):
        expiry = MagicMock()
        expiry.can_enter_position.return_value = MagicMock(allowed=True)
        expiry.is_expiry_day.return_value = True
        service._expiry_controller = expiry
        service._cfg["VIX_SIZE_SCALE"] = False
        with patch("core.safety_state.is_hard_halted", return_value=False), \
             patch("core.safety_state.check_intraday_pnl_and_halt", return_value=False), \
             patch("core.safety_state.check_kill_file_and_halt"), \
             patch("core.position_service.time.time", return_value=100.0):
            service.enter_trade("NIFTY", {"direction": "CALL", "price": 23500.0, "score": 75, "signal_ts": 99.0})
            mock_risk.get_trades_today.assert_not_called()
            assert "Executed" in service._decision_log.get("NIFTY", {}).get("msg", "")

    def test_enabled_blocks_once_cap_reached_on_expiry_day(self, service: PositionService, mock_risk: MagicMock):
        expiry = MagicMock()
        expiry.can_enter_position.return_value = MagicMock(allowed=True)
        expiry.is_expiry_day.return_value = True
        service._expiry_controller = expiry
        service._cfg["VIX_SIZE_SCALE"] = False
        service._cfg["expiry_max_trades_enabled"] = True
        service._cfg["EXPIRY_MAX_TRADES"] = 2
        mock_risk.get_trades_today.return_value = 2
        with patch("core.safety_state.is_hard_halted", return_value=False), \
             patch("core.safety_state.check_intraday_pnl_and_halt", return_value=False), \
             patch("core.safety_state.check_kill_file_and_halt"), \
             patch("core.position_service.time.time", return_value=100.0):
            service.enter_trade("NIFTY", {"direction": "CALL", "price": 23500.0, "score": 75, "signal_ts": 99.0})
            expiry.is_expiry_day.assert_called_once_with(index_name="NIFTY")
            assert "EXPIRY_MAX_TRADES_BLOCK" in service._decision_log.get("NIFTY", {}).get("msg", "")
            assert "NIFTY" not in service._positions

    def test_enabled_allows_entry_below_cap(self, service: PositionService, mock_risk: MagicMock):
        expiry = MagicMock()
        expiry.can_enter_position.return_value = MagicMock(allowed=True)
        expiry.is_expiry_day.return_value = True
        service._expiry_controller = expiry
        service._cfg["VIX_SIZE_SCALE"] = False
        service._cfg["expiry_max_trades_enabled"] = True
        service._cfg["EXPIRY_MAX_TRADES"] = 2
        mock_risk.get_trades_today.return_value = 1
        with patch("core.safety_state.is_hard_halted", return_value=False), \
             patch("core.safety_state.check_intraday_pnl_and_halt", return_value=False), \
             patch("core.safety_state.check_kill_file_and_halt"), \
             patch("core.position_service.time.time", return_value=100.0):
            service.enter_trade("NIFTY", {"direction": "CALL", "price": 23500.0, "score": 75, "signal_ts": 99.0})
            assert "Executed" in service._decision_log.get("NIFTY", {}).get("msg", "")

    def test_enabled_not_expiry_day_unaffected(self, service: PositionService, mock_risk: MagicMock):
        expiry = MagicMock()
        expiry.can_enter_position.return_value = MagicMock(allowed=True)
        expiry.is_expiry_day.return_value = False
        service._expiry_controller = expiry
        service._cfg["VIX_SIZE_SCALE"] = False
        service._cfg["expiry_max_trades_enabled"] = True
        mock_risk.get_trades_today.return_value = 99  # would block if today were expiry day
        with patch("core.safety_state.is_hard_halted", return_value=False), \
             patch("core.safety_state.check_intraday_pnl_and_halt", return_value=False), \
             patch("core.safety_state.check_kill_file_and_halt"), \
             patch("core.position_service.time.time", return_value=100.0):
            service.enter_trade("NIFTY", {"direction": "CALL", "price": 23500.0, "score": 75, "signal_ts": 99.0})
            assert "Executed" in service._decision_log.get("NIFTY", {}).get("msg", "")


# =============================================================================
# General per-index entry cooldown wiring (config key COOLDOWN via
# general_cooldown_enabled, opt-in, default OFF)
# =============================================================================

class TestGeneralCooldownWiring:
    def test_disabled_by_default_rapid_reentry_allowed(self, service: PositionService):
        service._cfg["VIX_SIZE_SCALE"] = False
        with patch("core.safety_state.is_hard_halted", return_value=False), \
             patch("core.safety_state.check_intraday_pnl_and_halt", return_value=False), \
             patch("core.safety_state.check_kill_file_and_halt"), \
             patch("core.position_service.time.time", return_value=100.0):
            service.enter_trade("NIFTY", {"direction": "CALL", "price": 23500.0, "score": 75, "signal_ts": 99.0})
            service.exit_position("NIFTY", "MANUAL")
            service.enter_trade("NIFTY", {"direction": "CALL", "price": 23500.0, "score": 75, "signal_ts": 99.0})
            assert "Executed" in service._decision_log.get("NIFTY", {}).get("msg", "")

    def test_enabled_blocks_reentry_within_cooldown_window(self, service: PositionService):
        service._cfg["VIX_SIZE_SCALE"] = False
        service._cfg["general_cooldown_enabled"] = True
        service._cfg["COOLDOWN"] = 300
        with patch("core.safety_state.is_hard_halted", return_value=False), \
             patch("core.safety_state.check_intraday_pnl_and_halt", return_value=False), \
             patch("core.safety_state.check_kill_file_and_halt"):
            with patch("core.position_service.time.time", return_value=100.0):
                service.enter_trade("NIFTY", {"direction": "CALL", "price": 23500.0, "score": 75, "signal_ts": 99.0})
                assert "Executed" in service._decision_log.get("NIFTY", {}).get("msg", "")
            with patch("core.position_service.time.time", return_value=250.0):  # only 150s later, < 300s cooldown
                service.enter_trade("NIFTY", {"direction": "CALL", "price": 23500.0, "score": 75, "signal_ts": 249.0})
                assert "COOLDOWN_BLOCK" in service._decision_log.get("NIFTY", {}).get("msg", "")

    def test_enabled_allows_reentry_after_cooldown_elapses(self, service: PositionService):
        service._cfg["VIX_SIZE_SCALE"] = False
        service._cfg["general_cooldown_enabled"] = True
        service._cfg["COOLDOWN"] = 300
        with patch("core.safety_state.is_hard_halted", return_value=False), \
             patch("core.safety_state.check_intraday_pnl_and_halt", return_value=False), \
             patch("core.safety_state.check_kill_file_and_halt"):
            with patch("core.position_service.time.time", return_value=100.0):
                service.enter_trade("NIFTY", {"direction": "CALL", "price": 23500.0, "score": 75, "signal_ts": 99.0})
            with patch("core.position_service.time.time", return_value=500.0):  # 400s later, >= 300s cooldown
                service.enter_trade("NIFTY", {"direction": "CALL", "price": 23500.0, "score": 75, "signal_ts": 499.0})
                assert "Executed" in service._decision_log.get("NIFTY", {}).get("msg", "")


# =============================================================================
# Breakout confirmation staleness wiring (config key BREAKOUT_TIMEOUT via
# breakout_timeout_enabled, opt-in, default OFF)
# =============================================================================

class TestBreakoutTimeoutWiring:
    def test_disabled_by_default_uses_signal_max_age(self, service: PositionService):
        """Regression guard: with breakout_timeout_enabled left at its
        default (False), a confirmed_ts older than SIGNAL_MAX_AGE (but well
        within BREAKOUT_TIMEOUT's much longer default) must still be
        rejected as stale - unchanged from today's real behavior."""
        service._breakout_state["NIFTY"] = {"confirmed_ts": 0.0}
        with patch("core.safety_state.is_hard_halted", return_value=False), \
             patch("core.safety_state.check_intraday_pnl_and_halt", return_value=False), \
             patch("core.safety_state.check_kill_file_and_halt"), \
             patch("core.position_service.time.time", return_value=100.0):
            # service._signal_max_age default is 90 (see PositionService.__init__)
            service.enter_trade("NIFTY", {"direction": "CALL", "price": 23500.0, "score": 75, "signal_ts": 99.0})
            assert "stale" in service._decision_log.get("NIFTY", {}).get("msg", "")

    def test_enabled_allows_older_confirmed_ts_within_breakout_timeout(self, service: PositionService):
        """With breakout_timeout_enabled=True and BREAKOUT_TIMEOUT=1800,
        the same confirmed_ts age that was stale above must now pass."""
        service._cfg["breakout_timeout_enabled"] = True
        service._cfg["BREAKOUT_TIMEOUT"] = 1800
        service._breakout_state["NIFTY"] = {"confirmed_ts": 0.0}
        with patch("core.safety_state.is_hard_halted", return_value=False), \
             patch("core.safety_state.check_intraday_pnl_and_halt", return_value=False), \
             patch("core.safety_state.check_kill_file_and_halt"), \
             patch("core.position_service.time.time", return_value=100.0):
            service.enter_trade("NIFTY", {"direction": "CALL", "price": 23500.0, "score": 75, "signal_ts": 99.0})
            msg = service._decision_log.get("NIFTY", {}).get("msg", "")
            assert "stale - confirmed_ts" not in msg


# =============================================================================
# Force pre-trade reconciliation wiring (config key FORCE_PRE_TRADE_RECON via
# force_pre_trade_recon_enabled, opt-in, default OFF)
# =============================================================================

class TestForcePreTradeReconWiring:
    def test_disabled_by_default_watchdog_not_consulted(self, service: PositionService, mock_execution: MagicMock):
        service._cfg["VIX_SIZE_SCALE"] = False
        with patch("core.safety_state.is_hard_halted", return_value=False), \
             patch("core.safety_state.check_intraday_pnl_and_halt", return_value=False), \
             patch("core.safety_state.check_kill_file_and_halt"), \
             patch("core.position_service.time.time", return_value=100.0):
            service.enter_trade("NIFTY", {"direction": "CALL", "price": 23500.0, "score": 75, "signal_ts": 99.0})
            mock_execution.run_ack_watchdog.assert_not_called()
            assert "Executed" in service._decision_log.get("NIFTY", {}).get("msg", "")

    def test_enabled_blocks_entry_when_orders_still_unacknowledged(self, service: PositionService, mock_execution: MagicMock):
        service._cfg["VIX_SIZE_SCALE"] = False
        service._cfg["force_pre_trade_recon_enabled"] = True
        mock_execution.run_ack_watchdog.return_value = {"checked": 2, "acknowledged": 0, "still_pending": 2, "errors": 0}
        with patch("core.safety_state.is_hard_halted", return_value=False), \
             patch("core.safety_state.check_intraday_pnl_and_halt", return_value=False), \
             patch("core.safety_state.check_kill_file_and_halt"), \
             patch("core.position_service.time.time", return_value=100.0):
            service.enter_trade("NIFTY", {"direction": "CALL", "price": 23500.0, "score": 75, "signal_ts": 99.0})
            mock_execution.run_ack_watchdog.assert_called_once()
            assert "PRE_TRADE_RECON_BLOCK" in service._decision_log.get("NIFTY", {}).get("msg", "")
            assert "NIFTY" not in service._positions

    def test_enabled_allows_entry_when_nothing_pending(self, service: PositionService, mock_execution: MagicMock):
        service._cfg["VIX_SIZE_SCALE"] = False
        service._cfg["force_pre_trade_recon_enabled"] = True
        mock_execution.run_ack_watchdog.return_value = {"checked": 2, "acknowledged": 2, "still_pending": 0, "errors": 0}
        with patch("core.safety_state.is_hard_halted", return_value=False), \
             patch("core.safety_state.check_intraday_pnl_and_halt", return_value=False), \
             patch("core.safety_state.check_kill_file_and_halt"), \
             patch("core.position_service.time.time", return_value=100.0):
            service.enter_trade("NIFTY", {"direction": "CALL", "price": 23500.0, "score": 75, "signal_ts": 99.0})
            assert "Executed" in service._decision_log.get("NIFTY", {}).get("msg", "")


# =============================================================================
# Strike selector wiring (opt-in — core/strike_selector.py, default OFF)
# =============================================================================

class TestStrikeSelectorWiring:
    def test_disabled_by_default_legacy_behavior_unchanged(self, service: PositionService):
        """Regression guard: with strike_selector_enabled left at its default
        (False), sig['strike'] must never be set — legacy behavior (raw price
        used as strike) is completely unchanged.
        """
        sig = {"direction": "CALL", "price": 23517.35, "score": 75, "signal_ts": 99.0}
        with patch("core.safety_state.is_hard_halted", return_value=False), \
             patch("core.safety_state.check_intraday_pnl_and_halt", return_value=False), \
             patch("core.safety_state.check_kill_file_and_halt"), \
             patch("core.position_service.time.time", return_value=100.0):
            service.enter_trade("NIFTY", sig)
        assert "strike" not in sig
        assert "Executed" in service._decision_log.get("NIFTY", {}).get("msg", "")

    def test_enabled_atm_mode_stores_rounded_strike(self, service: PositionService):
        """With the flag on and default ATM mode, sig['strike'] becomes the
        real rounded ATM strike (nearest 50 for NIFTY), not the raw price.
        """
        service._cfg["strike_selector_enabled"] = True
        sig = {"direction": "CALL", "price": 23517.35, "score": 75, "signal_ts": 99.0, "tier": "STRONG", "vix": 15.0}
        with patch("core.safety_state.is_hard_halted", return_value=False), \
             patch("core.safety_state.check_intraday_pnl_and_halt", return_value=False), \
             patch("core.safety_state.check_kill_file_and_halt"), \
             patch("core.position_service.time.time", return_value=100.0), \
             patch.object(service, "_resolve_dte", return_value=2):
            service.enter_trade("NIFTY", sig)
        assert sig["strike"] == 23500  # round(23517.35 / 50) * 50
        assert "Executed" in service._decision_log.get("NIFTY", {}).get("msg", "")

    def test_enabled_dte_below_minimum_blocks_entry(self, service: PositionService):
        """With the flag on, an expiring-too-soon DTE hard-blocks entry via
        dte_entry_check() (default min_dte_for_entry=1)."""
        service._cfg["strike_selector_enabled"] = True
        sig = {"direction": "CALL", "price": 23500.0, "score": 75, "signal_ts": 99.0}
        with patch("core.safety_state.is_hard_halted", return_value=False), \
             patch("core.safety_state.check_intraday_pnl_and_halt", return_value=False), \
             patch("core.safety_state.check_kill_file_and_halt"), \
             patch("core.position_service.time.time", return_value=100.0), \
             patch.object(service, "_resolve_dte", return_value=0):
            service.enter_trade("NIFTY", sig)
        msg = service._decision_log.get("NIFTY", {}).get("msg", "")
        assert "STRIKE_BLOCK" in msg
        assert "strike" not in sig

    def test_enabled_otm_mode_offsets_from_atm(self, service: PositionService):
        """With OTM mode, the stored strike differs from the ATM strike for a
        STRONG-tier signal (otm_step_offset_strong defaults to 1 step)."""
        service._cfg["strike_selector_enabled"] = True
        service._cfg["strike_selection_mode"] = "OTM"
        sig = {"direction": "CALL", "price": 23500.0, "score": 90, "signal_ts": 99.0, "tier": "STRONG", "vix": 15.0}
        with patch("core.safety_state.is_hard_halted", return_value=False), \
             patch("core.safety_state.check_intraday_pnl_and_halt", return_value=False), \
             patch("core.safety_state.check_kill_file_and_halt"), \
             patch("core.position_service.time.time", return_value=100.0), \
             patch.object(service, "_resolve_dte", return_value=2):
            service.enter_trade("NIFTY", sig)
        assert sig["strike"] != 23500
        assert "Executed" in service._decision_log.get("NIFTY", {}).get("msg", "")


# =============================================================================
# Live option quote feed wiring (config key live_option_quotes_enabled,
# opt-in, default OFF — core/live_option_quotes.py). Only meaningful once
# strike_selector_enabled has also produced a real strike.
# =============================================================================

class TestLiveOptionQuotesWiring:
    def _sig(self):
        return {"direction": "CALL", "price": 23500.0, "score": 75, "signal_ts": 99.0, "tier": "STRONG", "vix": 15.0}

    def test_disabled_by_default_not_consulted(self, service: PositionService):
        service._cfg["strike_selector_enabled"] = True
        sig = self._sig()
        with patch("core.live_option_quotes.fetch_live_option_quote") as mock_fetch, \
             patch("core.safety_state.is_hard_halted", return_value=False), \
             patch("core.safety_state.check_intraday_pnl_and_halt", return_value=False), \
             patch("core.safety_state.check_kill_file_and_halt"), \
             patch("core.position_service.time.time", return_value=100.0), \
             patch.object(service, "_resolve_dte", return_value=2):
            service.enter_trade("NIFTY", sig)
        mock_fetch.assert_not_called()
        assert "bid" not in sig

    def test_disabled_when_strike_selector_off_even_if_quotes_enabled(self, service: PositionService):
        service._cfg["live_option_quotes_enabled"] = True  # strike_selector_enabled stays default False
        sig = self._sig()
        with patch("core.live_option_quotes.fetch_live_option_quote") as mock_fetch, \
             patch("core.safety_state.is_hard_halted", return_value=False), \
             patch("core.safety_state.check_intraday_pnl_and_halt", return_value=False), \
             patch("core.safety_state.check_kill_file_and_halt"), \
             patch("core.position_service.time.time", return_value=100.0):
            service.enter_trade("NIFTY", sig)
        mock_fetch.assert_not_called()
        assert "bid" not in sig

    def test_enabled_populates_real_quote_fields(self, service: PositionService):
        service._cfg["strike_selector_enabled"] = True
        service._cfg["live_option_quotes_enabled"] = True
        sig = self._sig()
        with patch(
            "core.live_option_quotes.fetch_live_option_quote",
            return_value={"symbol": "NIFTY24DEC23500CE", "bid": 150.0, "ask": 151.0, "last": 150.5, "volume": 5000, "oi": 200000},
        ) as mock_fetch, \
             patch("core.safety_state.is_hard_halted", return_value=False), \
             patch("core.safety_state.check_intraday_pnl_and_halt", return_value=False), \
             patch("core.safety_state.check_kill_file_and_halt"), \
             patch("core.position_service.time.time", return_value=100.0), \
             patch.object(service, "_resolve_dte", return_value=2):
            service.enter_trade("NIFTY", sig)
        mock_fetch.assert_called_once()
        assert sig["bid"] == 150.0
        assert sig["ask"] == 151.0
        assert sig["oi"] == 200000
        assert sig["volume"] == 5000
        assert sig["option_symbol"] == "NIFTY24DEC23500CE"

    def test_enabled_fetch_returning_none_fails_open(self, service: PositionService):
        service._cfg["strike_selector_enabled"] = True
        service._cfg["live_option_quotes_enabled"] = True
        sig = self._sig()
        with patch("core.live_option_quotes.fetch_live_option_quote", return_value=None), \
             patch("core.safety_state.is_hard_halted", return_value=False), \
             patch("core.safety_state.check_intraday_pnl_and_halt", return_value=False), \
             patch("core.safety_state.check_kill_file_and_halt"), \
             patch("core.position_service.time.time", return_value=100.0), \
             patch.object(service, "_resolve_dte", return_value=2):
            service.enter_trade("NIFTY", sig)
        assert "bid" not in sig
        assert "Executed" in service._decision_log.get("NIFTY", {}).get("msg", "")

    def test_enabled_fetch_raising_fails_open(self, service: PositionService):
        service._cfg["strike_selector_enabled"] = True
        service._cfg["live_option_quotes_enabled"] = True
        sig = self._sig()
        with patch("core.live_option_quotes.fetch_live_option_quote", side_effect=ValueError("boom")), \
             patch("core.safety_state.is_hard_halted", return_value=False), \
             patch("core.safety_state.check_intraday_pnl_and_halt", return_value=False), \
             patch("core.safety_state.check_kill_file_and_halt"), \
             patch("core.position_service.time.time", return_value=100.0), \
             patch.object(service, "_resolve_dte", return_value=2):
            service.enter_trade("NIFTY", sig)  # must not raise
        assert "Executed" in service._decision_log.get("NIFTY", {}).get("msg", "")


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

    def test_take_profit_and_stop_disabled_skips_target_hit(self, service: PositionService):
        """config key TAKE_PROFIT_AND_STOP: false must skip the fixed
        TARGET_HIT exit, letting the position continue (rely on trailing
        stop instead) — the SL leg is never the one this key disables."""
        service._cfg["TAKE_PROFIT_AND_STOP"] = False
        service._positions["NIFTY"] = {
            "direction": "CALL", "underlying_entry_price": 23500,
            "qty": 1, "entry_price": 100, "entry_time": 0,
        }
        with patch.object(service, "_get_underlying_ltp", return_value=31000.0):
            with patch.object(service, "exit_position") as mock_exit:
                service.monitor_positions()
                mock_exit.assert_not_called()
                assert "NIFTY" in service._positions

    def test_take_profit_and_stop_disabled_sl_still_enforced(self, service: PositionService):
        """The SL leg must remain active even with TAKE_PROFIT_AND_STOP=false."""
        service._cfg["TAKE_PROFIT_AND_STOP"] = False
        service._positions["NIFTY"] = {
            "direction": "CALL", "underlying_entry_price": 23500,
            "qty": 1, "entry_price": 100, "entry_time": 0,
        }
        with patch.object(service, "_get_underlying_ltp", return_value=20000.0):
            with patch.object(service, "exit_position") as mock_exit:
                service.monitor_positions()
                mock_exit.assert_called_once_with("NIFTY", "SL_HIT")

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

    def test_failed_exit_retries_default_of_3_before_giving_up(self, service: PositionService, mock_execution: MagicMock):
        """config key EXIT_ORDER_RETRIES (default 3): a failed exit order
        must be retried (position kept, retry count incremented) up to 3
        times before the position is given up on and dropped."""
        rejected_result = MagicMock(status=_OrderStatus.REJECTED, order_id="", reject_reason="no liquidity", average_price=0.0)
        mock_execution.execute_order.return_value = rejected_result
        service._positions["NIFTY"] = {
            "direction": "CALL", "qty": 1, "entry_price": 100,
            "underlying_entry_price": 23500, "entry_time": 0,
            "entry_order_direction": "BUY",
        }
        with patch.object(service, "_get_underlying_ltp", return_value=23500.0):
            for expected_retries in (1, 2, 3):
                service.exit_position("NIFTY", "SL_HIT")
                if expected_retries < 3:
                    assert service._positions["NIFTY"]["exit_retries"] == expected_retries
                else:
                    assert "NIFTY" not in service._positions  # gave up after the 3rd failure

    def test_custom_exit_order_retries_gives_up_sooner(self, service: PositionService, mock_execution: MagicMock):
        """A lower EXIT_ORDER_RETRIES must genuinely shorten the give-up
        point, proving this is a real effect and not an unread value."""
        service._cfg["EXIT_ORDER_RETRIES"] = 1
        rejected_result = MagicMock(status=_OrderStatus.REJECTED, order_id="", reject_reason="no liquidity", average_price=0.0)
        mock_execution.execute_order.return_value = rejected_result
        service._positions["NIFTY"] = {
            "direction": "CALL", "qty": 1, "entry_price": 100,
            "underlying_entry_price": 23500, "entry_time": 0,
            "entry_order_direction": "BUY",
        }
        with patch.object(service, "_get_underlying_ltp", return_value=23500.0):
            service.exit_position("NIFTY", "SL_HIT")
        assert "NIFTY" not in service._positions  # gave up after just 1 failure, not 3


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
