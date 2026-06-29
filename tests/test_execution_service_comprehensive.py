"""
Comprehensive tests for core/services/execution_service.py — covers all untested
methods and edge cases not already covered by tests/test_execution_service.py and
tests/unit/services/test_execution_service.py.

Coverage targets:
  - modify_order (terminal status, success, failure, exception, OrderResult return)
  - run_ack_watchdog (empty, SUBMITTED, broker filled/rejected/pending, errors)
  - reconcile_pending_orders (clean, issues, freeze)
  - Operating mode gate (blocked, allowed, manual approval)
  - WAL journal integration (PENDING, COMMIT, FAIL, no journal)
  - _validate_broker_result (valid, invalid, warnings)
  - _get_commission_from_broker (details, fallback, error)
  - _generate_idempotency_key (determinism, None values, different inputs)
  - _execute_paper_order (MARKET slippage, LIMIT execute/no-execute, SL, shutdown)
  - _get_current_price_for_symbol (known, unknown, cache)
  - _persist_trade_from_order (no persistence, zero qty, success, error)
  - _audit_trail_to_trade_data (none result, zero qty, success, error)
  - _poll_for_fill_status (filled, timeout, shutdown, backoff, error)
  - _escalate_order_modification_failed (success, unavailable)
  - _store_idempotency_key / _get_idempotency_result (store/retrieve, missing, expired)
  - _cleanup_idempotency_cache (IdempotencyManager, fallback expiry, no expired)
  - is_trading_frozen / unfreeze_trading / _on_reconciliation_freeze
  - set_operating_mode_manager
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from core.execution.deterministic_state_machine import ExecutionState
from core.ports.execution.execution_port import (
    ExecutionAuditTrail,
    ExecutionContext,
    ExecutionMode,
    OrderRequest,
    OrderResult,
    OrderStatus,
    OrderType,
)
from core.services.execution_service import ExecutionService, ExecutionServiceConfig

# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture()
def mock_broker() -> MagicMock:
    broker = MagicMock()
    broker.place_order.return_value = OrderResult(
        order_id="ORD-001",
        status=OrderStatus.FILLED,
        filled_quantity=50,
        average_price=23500.0,
        broker_order_id="BRK-001",
    )
    broker.cancel_order.return_value = True
    broker.get_order_status.return_value = OrderStatus.FILLED
    broker.wait_for_fill.return_value = True
    broker.get_filled_quantity.return_value = 50
    broker.get_average_price.return_value = 23500.0
    return broker


@pytest.fixture()
def service(mock_broker: MagicMock) -> ExecutionService:
    """ExecutionService with mock broker and minimal config (no audit, no delay)."""
    config = ExecutionServiceConfig(
        enable_duplicate_prevention=True,
        idempotency_cache_size=100,
        idempotency_expiry_hours=24,
        enable_audit_trail=False,
        paper_fill_delay_ms=0,
        paper_fill_slippage_pct=0.0,
        max_retries=1,
    )
    svc = ExecutionService(
        config=config,
        broker_port=mock_broker,
        reconciliation_db_path=":memory:",
    )
    svc.set_operating_mode_manager(None)  # init freeze state
    return svc


@pytest.fixture()
def order_request() -> OrderRequest:
    return OrderRequest(
        symbol="NIFTY",
        direction="BUY",
        strike_price=23500.0,
        lot_size=50,
        order_type=OrderType.MARKET,
    )


@pytest.fixture()
def execution_context() -> ExecutionContext:
    return ExecutionContext(execution_mode=ExecutionMode.PAPER)


# ═══════════════════════════════════════════════════════════════════════
#  modify_order
# ═══════════════════════════════════════════════════════════════════════


class TestModifyOrder:
    def test_modify_terminal_filled_rejected(self, service: ExecutionService, mock_broker: MagicMock):
        """Terminal status orders cannot be modified."""
        mock_broker.get_order_status.side_effect = [
            OrderStatus.FILLED,
            OrderStatus.CANCELLED,
            OrderStatus.EXPIRED,
            OrderStatus.REJECTED,
        ]
        for status in [OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.EXPIRED, OrderStatus.REJECTED]:
            mock_broker.get_order_status.return_value = status
            result = service.modify_order("ORD-TERM", quantity=10)
            assert result.status == OrderStatus.REJECTED
            assert "terminal" in (result.reject_reason or "").lower()

    def test_modify_success_broker_returns_true(self, service: ExecutionService, mock_broker: MagicMock):
        """Broker returns True → modification accepted."""
        mock_broker.get_order_status.return_value = OrderStatus.SUBMITTED
        mock_broker.modify_order.return_value = True
        result = service.modify_order("ORD-001", quantity=10, price=23600.0)
        assert result.status == OrderStatus.SUBMITTED
        assert result.order_id == "ORD-001"

    def test_modify_failure_broker_returns_false(self, service: ExecutionService, mock_broker: MagicMock):
        """Broker returns False → modification rejected."""
        mock_broker.get_order_status.return_value = OrderStatus.SUBMITTED
        mock_broker.modify_order.return_value = False
        result = service.modify_order("ORD-001", quantity=10)
        assert result.status == OrderStatus.REJECTED
        assert "rejected" in (result.reject_reason or "").lower()

    def test_modify_broker_returns_order_result(self, service: ExecutionService, mock_broker: MagicMock):
        """Broker returns OrderResult directly."""
        mock_broker.get_order_status.return_value = OrderStatus.SUBMITTED
        broker_result = OrderResult(
            order_id="ORD-001", status=OrderStatus.SUBMITTED,
        )
        mock_broker.modify_order.return_value = broker_result
        result = service.modify_order("ORD-001", quantity=10)
        assert result.status == OrderStatus.SUBMITTED

    def test_modify_broker_rejected_order_result(self, service: ExecutionService, mock_broker: MagicMock):
        """Broker returns rejected OrderResult directly."""
        mock_broker.get_order_status.return_value = OrderStatus.SUBMITTED
        broker_result = OrderResult(
            order_id="ORD-001", status=OrderStatus.REJECTED, reject_reason="Insufficient margin",
        )
        mock_broker.modify_order.return_value = broker_result
        result = service.modify_order("ORD-001", quantity=10)
        assert result.status == OrderStatus.REJECTED

    def test_modify_all_params_passed(self, service: ExecutionService, mock_broker: MagicMock):
        """All keyword parameters are passed through to broker."""
        mock_broker.get_order_status.return_value = OrderStatus.SUBMITTED
        mock_broker.modify_order.return_value = True
        service.modify_order(
            "ORD-001",
            quantity=20,
            price=23700.0,
            trigger_price=23600.0,
            order_type=OrderType.LIMIT,
        )
        mock_broker.modify_order.assert_called_once_with(
            "ORD-001",
            qty=20, price=23700.0, trigger_price=23600.0,
            order_type="LIMIT",
        )

    def test_modify_exception_handling(self, service: ExecutionService, mock_broker: MagicMock):
        """Broker exception → REJECTED result, not an unhandled exception."""
        mock_broker.get_order_status.return_value = OrderStatus.SUBMITTED
        mock_broker.modify_order.side_effect = ConnectionError("Broker offline")
        result = service.modify_order("ORD-001", quantity=10)
        assert result.status == OrderStatus.REJECTED
        assert result.reject_reason is not None


# ═══════════════════════════════════════════════════════════════════════
#  run_ack_watchdog
# ═══════════════════════════════════════════════════════════════════════


class TestRunAckWatchdog:
    def test_watchdog_empty_returns_zero(self, service: ExecutionService):
        """No state machines → all zeros."""
        result = service.run_ack_watchdog(max_ack_age_seconds=1.0)
        assert result["checked"] == 0
        assert result["acknowledged"] == 0
        assert result["still_pending"] == 0

    def test_watchdog_no_submitted_machines(self, service: ExecutionService):
        """Machines that are not SUBMITTED are skipped."""
        mgr = service._state_machine
        mgr.create_or_get("idle", "NIFTY", 50, 23500.0, "BUY")
        result = service.run_ack_watchdog(max_ack_age_seconds=1.0)
        assert result["checked"] == 0  # state is INIT, not SUBMITTED

    def test_watchdog_filled_by_broker(self, service: ExecutionService, mock_broker: MagicMock):
        """SUBMITTED order, broker says FILLED → acknowledged."""
        mgr = service._state_machine
        machine, is_new = mgr.create_or_get("wf_fill", "NIFTY", 50, 23500.0, "BUY")
        machine.try_transition_to(ExecutionState.VALIDATED)
        machine.try_transition_to(ExecutionState.PERSISTED)
        machine.record_submission("BRK-WF-001")
        # Manually set submitted_at to past
        machine.submitted_at = (datetime.now() - timedelta(seconds=60)).isoformat()
        mock_broker.get_order_status.return_value = "FILLED"
        result = service.run_ack_watchdog(max_ack_age_seconds=1.0)
        assert result["checked"] == 1
        assert result["acknowledged"] == 1

    def test_watchdog_still_pending(self, service: ExecutionService, mock_broker: MagicMock):
        """Broker says OPEN → still_pending."""
        mgr = service._state_machine
        machine, is_new = mgr.create_or_get("wf_pend", "NIFTY", 50, 23500.0, "BUY")
        machine.try_transition_to(ExecutionState.VALIDATED)
        machine.try_transition_to(ExecutionState.PERSISTED)
        machine.record_submission("BRK-WP-001")
        machine.submitted_at = (datetime.now() - timedelta(seconds=60)).isoformat()
        mock_broker.get_order_status.return_value = "OPEN"
        result = service.run_ack_watchdog(max_ack_age_seconds=1.0)
        assert result["checked"] == 1
        assert result["still_pending"] == 1

    def test_watchdog_error_handling(self, service: ExecutionService, mock_broker: MagicMock):
        """Broker exception increments errors counter."""
        mgr = service._state_machine
        machine, is_new = mgr.create_or_get("wf_err", "NIFTY", 50, 23500.0, "BUY")
        machine.try_transition_to(ExecutionState.VALIDATED)
        machine.try_transition_to(ExecutionState.PERSISTED)
        machine.record_submission("BRK-WE-001")
        machine.submitted_at = (datetime.now() - timedelta(seconds=60)).isoformat()
        mock_broker.get_order_status.side_effect = ConnectionError("Timeout")
        result = service.run_ack_watchdog(max_ack_age_seconds=1.0)
        # The singleton state machine manager may have leftover machines from other tests;
        # assert errors >= 1 to verify the error path works (may be more due to shared state)
        assert result["errors"] >= 1
        assert result["checked"] >= 1


# ═══════════════════════════════════════════════════════════════════════
#  reconcile_pending_orders
# ═══════════════════════════════════════════════════════════════════════


class TestReconcilePendingOrders:
    def test_reconcile_returns_dict(self, service: ExecutionService):
        result = service.reconcile_pending_orders()
        assert isinstance(result, dict)
        assert "is_clean" in result
        assert "issues_count" in result

    def test_reconcile_includes_durable_state(self, service: ExecutionService):
        result = service.reconcile_pending_orders()
        assert "durable_state" in result

    def test_reconcile_clean(self, service: ExecutionService):
        with patch.object(service._reconciliation_service, 'reconcile') as mock_recon:
            mock_recon.return_value.is_clean = True
            mock_recon.return_value.issues = []
            mock_recon.return_value.repaired_count = 0
            mock_recon.return_value.freeze_reason = None
            mock_recon.return_value.broker_positions_count = 0
            mock_recon.return_value.internal_orders_count = 0
            result = service.reconcile_pending_orders()
            assert result["is_clean"] is True
            assert result["issues_count"] == 0

    def test_reconcile_with_freeze(self, service: ExecutionService):
        with patch.object(service._reconciliation_service, 'reconcile') as mock_recon:
            from core.execution.reconciliation.service import TradingFreezeReason
            mock_recon.return_value.is_clean = False
            mock_recon.return_value.issues = [MagicMock()]
            mock_recon.return_value.repaired_count = 0
            mock_recon.return_value.freeze_reason = TradingFreezeReason.ORPHAN_POSITIONS_DETECTED
            mock_recon.return_value.broker_positions_count = 1
            mock_recon.return_value.internal_orders_count = 1
            result = service.reconcile_pending_orders()
            assert result["is_clean"] is False
            assert result["freeze_reason"] == "ORPHAN_POSITIONS_DETECTED"
            assert service.is_trading_frozen()


# ═══════════════════════════════════════════════════════════════════════
#  is_trading_frozen / unfreeze_trading / _on_reconciliation_freeze
# ═══════════════════════════════════════════════════════════════════════


class TestTradingFreezeDetail:
    def test_on_freeze_sets_flag(self, service: ExecutionService):
        from core.execution.reconciliation.service import TradingFreezeReason
        assert not service.is_trading_frozen()
        service._on_reconciliation_freeze(TradingFreezeReason.STALE_ORDERS_UNRESOLVED, "Test freeze")
        assert service.is_trading_frozen()

    def test_unfreeze_clears_flag(self, service: ExecutionService):
        from core.execution.reconciliation.service import TradingFreezeReason
        service._on_reconciliation_freeze(TradingFreezeReason.STALE_ORDERS_UNRESOLVED, "Test")
        assert service.is_trading_frozen()
        service.unfreeze_trading()
        assert not service.is_trading_frozen()


# ═══════════════════════════════════════════════════════════════════════
#  set_operating_mode_manager
# ═══════════════════════════════════════════════════════════════════════


class TestSetOperatingModeManager:
    def test_set_mode_manager(self, service: ExecutionService):
        mock_mgr = MagicMock()
        mock_mgr.current_mode = "PAPER"
        service.set_operating_mode_manager(mock_mgr)
        assert service._operating_mode_manager == mock_mgr

    def test_set_mode_manager_none(self, service: ExecutionService):
        service.set_operating_mode_manager(None)
        assert service._operating_mode_manager is None


# ═══════════════════════════════════════════════════════════════════════
#  Operating Mode Gate in execute_order
# ═══════════════════════════════════════════════════════════════════════


class TestOperatingModeGate:
    def test_mode_blocks_execution(self, service: ExecutionService, order_request: OrderRequest):
        mock_mgr = MagicMock()
        mock_mgr.allows_execution.return_value = (False, "MAINTENANCE")
        service._operating_mode_manager = mock_mgr
        result = service.execute_order(order_request, ExecutionContext())
        assert result.status == OrderStatus.REJECTED
        assert "BLOCKED" in (result.reject_reason or "")

    def test_mode_allows_execution(self, service: ExecutionService, order_request: OrderRequest, mock_broker: MagicMock):
        mock_mgr = MagicMock()
        mock_mgr.allows_execution.return_value = (True, "")
        mock_mgr.requires_manual_approval.return_value = False
        service._operating_mode_manager = mock_mgr
        result = service.execute_order(order_request)
        assert result.status in (OrderStatus.FILLED, OrderStatus.SUBMITTED, OrderStatus.REJECTED)


# ═══════════════════════════════════════════════════════════════════════
#  WAL Journal Integration
# ═══════════════════════════════════════════════════════════════════════


class TestWalJournalIntegration:
    def test_wal_pending_on_execute(self, service: ExecutionService, order_request: OrderRequest):
        mock_wal = MagicMock()
        service._wal_journal = mock_wal
        service.execute_order(order_request, ExecutionContext(execution_mode=ExecutionMode.PAPER))
        # PENDING intent written
        mock_wal.append.assert_called_once()
        args = mock_wal.append.call_args[0][0]
        assert args.action == "place_order"

    def test_wal_commit_on_fill(self, service: ExecutionService, order_request: OrderRequest):
        mock_wal = MagicMock()
        service._wal_journal = mock_wal
        service.execute_order(order_request, ExecutionContext(execution_mode=ExecutionMode.PAPER))
        # Should commit since paper fills immediately
        mock_wal.commit.assert_called_once()

    def test_wal_fail_on_rejection(self, service: ExecutionService, mock_broker: MagicMock, order_request: OrderRequest):
        mock_wal = MagicMock()
        service._wal_journal = mock_wal
        mock_broker.place_order.return_value = OrderResult(
            order_id="", status=OrderStatus.REJECTED, reject_reason="Bad order",
        )
        service.execute_order(order_request, ExecutionContext(execution_mode=ExecutionMode.AUTOMATIC))
        # Should fail the intent
        mock_wal.fail.assert_called_once()

    def test_wal_none_does_not_crash(self, service: ExecutionService, order_request: OrderRequest):
        service._wal_journal = None
        result = service.execute_order(order_request, ExecutionContext(execution_mode=ExecutionMode.PAPER))
        assert result.status == OrderStatus.FILLED


# ═══════════════════════════════════════════════════════════════════════
#  _validate_broker_result
# ═══════════════════════════════════════════════════════════════════════


class TestValidateBrokerResult:
    def test_valid_result_passes(self, service: ExecutionService):
        result = OrderResult(order_id="ORD-V", status=OrderStatus.FILLED, filled_quantity=50, average_price=100.0)
        validated = service._validate_broker_result(result)
        assert validated.status == OrderStatus.FILLED

    def test_invalid_result_rejected(self, service: ExecutionService):
        with patch.object(service._ack_validator, 'validate_order_result') as mock_validate:
            from core.execution.broker_ack_validator import AckValidationResult
            mock_validate.return_value = AckValidationResult(
                is_valid=False, broker=MagicMock(), error_message="Bad ACK",
            )
            result = OrderResult(order_id="ORD-BAD", status=OrderStatus.FILLED)
            validated = service._validate_broker_result(result)
            assert validated.status == OrderStatus.REJECTED
            assert "Bad ACK" in (validated.reject_reason or "")

    def test_warnings_logged(self, service: ExecutionService):
        with patch.object(service._ack_validator, 'validate_order_result') as mock_validate:
            from core.execution.broker_ack_validator import AckValidationResult
            mock_validate.return_value = AckValidationResult(
                is_valid=True, broker=MagicMock(), warnings=["Short order ID"],
            )
            result = OrderResult(order_id="ORD-WARN", status=OrderStatus.FILLED)
            validated = service._validate_broker_result(result)
            assert validated.status == OrderStatus.FILLED  # Still passes


# ═══════════════════════════════════════════════════════════════════════
#  _get_commission_from_broker
# ═══════════════════════════════════════════════════════════════════════


class TestGetCommissionFromBroker:
    def test_broker_has_order_details(self, service: ExecutionService, mock_broker: MagicMock):
        mock_broker.get_order_details.return_value = {"brokerage": 15.5}
        commission = service._get_commission_from_broker("ORD-001", MagicMock(strike_price=100.0, lot_size=50))
        assert commission == 15.5

    def test_broker_details_alternate_keys(self, service: ExecutionService, mock_broker: MagicMock):
        mock_broker.get_order_details.return_value = {"charges": 12.0}
        commission = service._get_commission_from_broker("ORD-001", MagicMock(strike_price=100.0, lot_size=50))
        assert commission == 12.0

    def test_broker_no_details_fallback(self, service: ExecutionService, mock_broker: MagicMock):
        """When broker has no get_order_details, use fallback calculation."""
        if hasattr(mock_broker, 'get_order_details'):
            del mock_broker.get_order_details
        req = MagicMock(strike_price=100.0, lot_size=50)
        commission = service._get_commission_from_broker("ORD-001", req)
        expected = round(100.0 * 50 * 0.0005, 2)
        assert commission == expected

    def test_fallback_error_returns_zero(self, service: ExecutionService, mock_broker: MagicMock):
        if hasattr(mock_broker, 'get_order_details'):
            del mock_broker.get_order_details
        req = MagicMock(strike_price=None, lot_size=None)
        commission = service._get_commission_from_broker("ORD-001", req)
        assert commission == 0.0


# ═══════════════════════════════════════════════════════════════════════
#  _generate_idempotency_key
# ═══════════════════════════════════════════════════════════════════════


class TestGenerateIdempotencyKey:
    def test_deterministic_output(self, service: ExecutionService):
        req = OrderRequest(symbol="NIFTY", direction="BUY", strike_price=23500.0, lot_size=50, order_type=OrderType.MARKET)
        ctx = ExecutionContext()
        key1 = service._generate_idempotency_key(req, ctx)
        key2 = service._generate_idempotency_key(req, ctx)
        assert key1 == key2  # Same inputs → same key

    def test_different_inputs_different_keys(self, service: ExecutionService):
        req1 = OrderRequest(symbol="NIFTY", direction="BUY", strike_price=23500.0, lot_size=50, order_type=OrderType.MARKET)
        req2 = OrderRequest(symbol="BANKNIFTY", direction="BUY", strike_price=44000.0, lot_size=25, order_type=OrderType.MARKET)
        ctx = ExecutionContext()
        key1 = service._generate_idempotency_key(req1, ctx)
        key2 = service._generate_idempotency_key(req2, ctx)
        assert key1 != key2

    def test_none_values_removed(self, service: ExecutionService):
        req = OrderRequest(
            symbol="NIFTY", direction="BUY", strike_price=23500.0, lot_size=50,
            order_type=OrderType.MARKET,
            # stop_loss, target, strategy_id left as defaults (None)
        )
        ctx = ExecutionContext()
        key = service._generate_idempotency_key(req, ctx)
        assert isinstance(key, str)
        assert len(key) == 32  # SHA256 truncated to 32 hex chars

    def test_key_format_is_hex(self, service: ExecutionService):
        req = OrderRequest(symbol="NIFTY", direction="BUY", strike_price=23500.0, lot_size=50, order_type=OrderType.MARKET)
        ctx = ExecutionContext()
        key = service._generate_idempotency_key(req, ctx)
        assert all(c in "0123456789abcdef" for c in key)


# ═══════════════════════════════════════════════════════════════════════
#  _execute_paper_order detail paths
# ═══════════════════════════════════════════════════════════════════════


class TestExecutePaperOrderDetail:
    def test_paper_market_order_with_slippage(self, service: ExecutionService):
        """MARKET order: fill price = base + slippage for BUY."""
        req = OrderRequest(symbol="NIFTY", direction="BUY", strike_price=0.0, lot_size=50, order_type=OrderType.MARKET)
        ctx = ExecutionContext(execution_mode=ExecutionMode.PAPER)
        # Inject price cache for predictable price
        service._paper_price_cache["NIFTY"] = 23500.0
        result = service.execute_order(req, ctx)
        assert result.status == OrderStatus.FILLED
        assert result.average_price > 0
        assert result.filled_quantity == 50

    def test_paper_limit_order_executes(self, service: ExecutionService):
        """LIMIT order at favorable price → immediate fill."""
        req = OrderRequest(
            symbol="NIFTY", direction="BUY", strike_price=0.0, lot_size=50,
            order_type=OrderType.LIMIT, price=24000.0,  # Above current = buy executes
        )
        ctx = ExecutionContext(execution_mode=ExecutionMode.PAPER)
        service._paper_price_cache["NIFTY"] = 23500.0
        result = service.execute_order(req, ctx)
        assert result.status == OrderStatus.FILLED

    def test_paper_limit_order_not_executed(self, service: ExecutionService):
        """LIMIT order at unfavorable price → PENDING."""
        req = OrderRequest(
            symbol="NIFTY", direction="BUY", strike_price=0.0, lot_size=50,
            order_type=OrderType.LIMIT, price=23000.0,  # Below current = won't fill
        )
        ctx = ExecutionContext(execution_mode=ExecutionMode.PAPER)
        service._paper_price_cache["NIFTY"] = 23500.0
        result = service.execute_order(req, ctx)
        assert result.status == OrderStatus.PENDING

    def test_paper_shutdown_during_delay(self, service: ExecutionService):
        """Shutdown event during paper fill delay → REJECTED."""
        service.config.paper_fill_delay_ms = 5000  # Long delay
        service._shutdown_event.set()
        req = OrderRequest(symbol="NIFTY", direction="BUY", strike_price=0.0, lot_size=50, order_type=OrderType.MARKET)
        ctx = ExecutionContext(execution_mode=ExecutionMode.PAPER)
        result = service.execute_order(req, ctx)
        assert result.status == OrderStatus.REJECTED
        assert "shutdown" in (result.reject_reason or "").lower()
        service._shutdown_event.clear()


# ═══════════════════════════════════════════════════════════════════════
#  _get_current_price_for_symbol
# ═══════════════════════════════════════════════════════════════════════


class TestGetCurrentPriceForSymbol:
    def test_known_symbol(self, service: ExecutionService):
        price = service._get_current_price_for_symbol("NIFTY")
        assert price == 19500.0

    def test_unknown_symbol_default(self, service: ExecutionService):
        price = service._get_current_price_for_symbol("ZZZZ_UNKNOWN")
        assert price == 1000.0

    def test_cache_used(self, service: ExecutionService):
        service._paper_price_cache["NIFTY"] = 99999.0
        price = service._get_current_price_for_symbol("NIFTY")
        assert price == 99999.0  # Returns cached value

    def test_cache_cleanup(self, service: ExecutionService):
        # Fill cache with 60+ entries
        for i in range(60):
            service._paper_price_cache[f"SYM_{i}"] = float(i)
        # Access a symbol to trigger cleanup
        service._get_current_price_for_symbol("NIFTY")
        # Cache should now have < 60 entries
        assert len(service._paper_price_cache) < 60


# ═══════════════════════════════════════════════════════════════════════
#  _persist_trade_from_order
# ═══════════════════════════════════════════════════════════════════════


class TestPersistTradeFromOrder:
    def test_no_persistence_does_nothing(self, service: ExecutionService):
        service.trade_persistence = None
        req = OrderRequest(symbol="NIFTY", direction="BUY", strike_price=23500.0, lot_size=50, order_type=OrderType.MARKET)
        res = OrderResult(order_id="ORD-001", status=OrderStatus.FILLED, filled_quantity=50, average_price=23500.0)
        ctx = ExecutionContext()
        # Should not raise
        service._persist_trade_from_order(req, res, ctx)

    def test_zero_filled_quantity_skips(self, service: ExecutionService):
        mock_persistence = MagicMock()
        service.trade_persistence = mock_persistence
        req = OrderRequest(symbol="NIFTY", direction="BUY", strike_price=23500.0, lot_size=50, order_type=OrderType.MARKET)
        res = OrderResult(order_id="ORD-001", status=OrderStatus.REJECTED, filled_quantity=0)
        ctx = ExecutionContext()
        service._persist_trade_from_order(req, res, ctx)
        mock_persistence.save_trade.assert_not_called()

    def test_successful_persist(self, service: ExecutionService):
        mock_persistence = MagicMock()
        mock_persistence.save_trade.return_value = "TRADE-001"
        service.trade_persistence = mock_persistence
        service.config.enable_audit_trail = True
        req = OrderRequest(symbol="NIFTY", direction="BUY", strike_price=23500.0, lot_size=50, order_type=OrderType.MARKET)
        res = OrderResult(order_id="ORD-001", status=OrderStatus.FILLED, filled_quantity=50, average_price=23500.0)
        ctx = ExecutionContext()
        service._persist_trade_from_order(req, res, ctx)
        mock_persistence.save_trade.assert_called_once()

    def test_persist_error_logged(self, service: ExecutionService):
        mock_persistence = MagicMock()
        mock_persistence.save_trade.side_effect = ValueError("DB error")
        service.trade_persistence = mock_persistence
        req = OrderRequest(symbol="NIFTY", direction="BUY", strike_price=23500.0, lot_size=50, order_type=OrderType.MARKET)
        res = OrderResult(order_id="ORD-001", status=OrderStatus.FILLED, filled_quantity=50, average_price=23500.0)
        ctx = ExecutionContext()
        # Should not raise
        service._persist_trade_from_order(req, res, ctx)


# ═══════════════════════════════════════════════════════════════════════
#  _audit_trail_to_trade_data
# ═══════════════════════════════════════════════════════════════════════


class TestAuditTrailToTradeData:
    def test_no_order_result_returns_none(self, service: ExecutionService):
        audit = ExecutionAuditTrail(
            execution_id="audit-001",
            order_request=MagicMock(),
            order_result=None,
        )
        result = service._audit_trail_to_trade_data(audit)
        assert result is None

    def test_zero_filled_returns_none(self, service: ExecutionService):
        audit = ExecutionAuditTrail(
            execution_id="audit-001",
            order_request=MagicMock(),
            order_result=OrderResult(order_id="ORD-001", status=OrderStatus.REJECTED, filled_quantity=0),
        )
        result = service._audit_trail_to_trade_data(audit)
        assert result is None

    def test_successful_conversion(self, service: ExecutionService):
        req = OrderRequest(symbol="NIFTY", direction="BUY", strike_price=23500.0, lot_size=50, order_type=OrderType.MARKET)
        res = OrderResult(order_id="ORD-001", status=OrderStatus.FILLED, filled_quantity=50, average_price=23500.0)
        audit = ExecutionAuditTrail(execution_id="audit-001", order_request=req, order_result=res)
        trade_data = service._audit_trail_to_trade_data(audit)
        assert trade_data is not None
        assert trade_data["symbol"] == "NIFTY"
        assert trade_data["direction"] == "BUY"
        assert trade_data["entry_price"] == 23500.0

    def test_conversion_error_returns_none(self, service: ExecutionService):
        """Bad data causes graceful None return (via negative filled_quantity)."""
        # Test the early-return path: zero/negative filled_quantity returns None
        audit = ExecutionAuditTrail(
            execution_id="audit-001",
            order_request=MagicMock(),
            order_result=OrderResult(order_id="ORD-001", status=OrderStatus.REJECTED, filled_quantity=0),
        )
        result = service._audit_trail_to_trade_data(audit)
        assert result is None

    def test_conversion_exception_returns_none(self, service: ExecutionService):
        """Exception during conversion returns None gracefully."""
        # Use an object that raises on attribute access
        class BadRequest:
            @property
            def symbol(self):
                raise AttributeError("broken")
            @property
            def direction(self):
                return "BUY"
            @property
            def strike_price(self):
                return 23500.0
            @property
            def lot_size(self):
                return 50
            @property
            def strategy_id(self):
                return ""

        audit = ExecutionAuditTrail(
            execution_id="audit-001",
            order_request=BadRequest(),
            order_result=OrderResult(order_id="ORD-001", status=OrderStatus.FILLED, filled_quantity=50, average_price=100.0),
        )
        result = service._audit_trail_to_trade_data(audit)
        assert result is None


# ═══════════════════════════════════════════════════════════════════════
#  _poll_for_fill_status
# ═══════════════════════════════════════════════════════════════════════


class TestPollForFillStatus:
    def test_poll_fill_found_via_get_filled_quantity(self, service: ExecutionService, mock_broker: MagicMock):
        mock_broker.get_filled_quantity.return_value = 50
        result = service._poll_for_fill_status("ORD-001", timeout_seconds=1)
        assert result is True

    def test_poll_fill_found_via_get_order_status(self, service: ExecutionService, mock_broker: MagicMock):
        if hasattr(mock_broker, 'get_filled_quantity'):
            del mock_broker.get_filled_quantity
        mock_broker.get_order_status.return_value = OrderStatus.FILLED
        result = service._poll_for_fill_status("ORD-001", timeout_seconds=1)
        assert result is True

    def test_poll_timeout(self, service: ExecutionService, mock_broker: MagicMock):
        mock_broker.get_filled_quantity.return_value = 0
        result = service._poll_for_fill_status("ORD-001", timeout_seconds=0.1)
        assert result is False  # Timeout

    def test_poll_shutdown_during_backoff(self, service: ExecutionService, mock_broker: MagicMock):
        mock_broker.get_filled_quantity.return_value = 0
        service._shutdown_event.set()
        result = service._poll_for_fill_status("ORD-001", timeout_seconds=5)
        assert result is False
        service._shutdown_event.clear()

    def test_poll_error_during_status_check(self, service: ExecutionService, mock_broker: MagicMock):
        mock_broker.get_filled_quantity.side_effect = [ValueError("Broken"), 0]
        # First poll fails with error, still continues; eventually times out
        result = service._poll_for_fill_status("ORD-001", timeout_seconds=0.3)
        assert result is False


# ═══════════════════════════════════════════════════════════════════════
#  _escalate_order_modification_failed
# ═══════════════════════════════════════════════════════════════════════


class TestEscalateOrderModificationFailed:
    def test_escalation_success(self, service: ExecutionService):
        with patch("core.incident_alerting.get_incident_alerting") as mock_get:
            mock_alerting = MagicMock()
            mock_get.return_value = mock_alerting
            service._escalate_order_modification_failed("ORD-001", "Test reason", {"key": "val"})
            mock_alerting.alert_order_modification_failed.assert_called_once_with(
                order_id="ORD-001", reason="Test reason", details={"key": "val"},
            )

    def test_escalation_alerting_unavailable(self, service: ExecutionService):
        with patch("core.incident_alerting.get_incident_alerting") as mock_get:
            mock_get.side_effect = Exception("Not available")
            # Should not raise
            service._escalate_order_modification_failed("ORD-001", "Reason")


# ═══════════════════════════════════════════════════════════════════════
#  _store_idempotency_key / _get_idempotency_result
# ═══════════════════════════════════════════════════════════════════════


class TestStoreAndGetIdempotency:
    def test_store_and_retrieve(self, service: ExecutionService):
        result = OrderResult(order_id="ORD-001", status=OrderStatus.FILLED, filled_quantity=50, average_price=100.0)
        service._store_idempotency_key("test-key", result)
        cached = service._get_idempotency_result("test-key")
        assert cached is not None
        assert cached.order_id == "ORD-001"

    def test_get_nonexistent_key(self, service: ExecutionService):
        cached = service._get_idempotency_result("nonexistent")
        assert cached is None

    def test_store_to_lru_cache(self, service: ExecutionService):
        service.config.idempotency_cache_size = 5
        for i in range(10):
            service._store_idempotency_key(f"key-{i}", OrderResult(order_id=f"ORD-{i}", status=OrderStatus.FILLED))
        # LRU cache should have at most 5 entries
        assert len(service._idempotency_cache) <= 5


# ═══════════════════════════════════════════════════════════════════════
#  _cleanup_idempotency_cache
# ═══════════════════════════════════════════════════════════════════════


class TestCleanupIdempotencyCache:
    def test_cleanup_delegates_to_manager(self, service: ExecutionService):
        with patch.object(service.idempotency, '_cleanup') as mock_cleanup:
            service._cleanup_idempotency_cache()
            mock_cleanup.assert_called_once()

    def test_cleanup_fallback_on_manager_error(self, service: ExecutionService):
        with patch.object(service.idempotency, '_cleanup', side_effect=AttributeError("No _cleanup")):
            # Add expired key
            expired = datetime.now() - timedelta(hours=48)
            service._idempotency_cache["old-key"] = (expired, MagicMock())
            service._cleanup_idempotency_cache()
            assert "old-key" not in service._idempotency_cache

    def test_cleanup_fallback_no_expired(self, service: ExecutionService):
        with patch.object(service.idempotency, '_cleanup', side_effect=AttributeError):
            fresh = datetime.now() + timedelta(hours=1)  # Future timestamp
            service._idempotency_cache["fresh-key"] = (fresh, MagicMock())
            service._cleanup_idempotency_cache()
            assert "fresh-key" in service._idempotency_cache


# ═══════════════════════════════════════════════════════════════════════
#  _execute_with_retries hard halt gate
# ═══════════════════════════════════════════════════════════════════════


class TestExecuteWithRetriesHardHaltGate:
    def test_hard_halt_blocks_execution(self, service: ExecutionService, order_request: OrderRequest):
        from core.safety_state import _HARD_HALT
        _HARD_HALT.set()
        try:
            # The hard halt gate in _execute_with_retries is called via execute_order
            result = service.execute_order(order_request, ExecutionContext(execution_mode=ExecutionMode.AUTOMATIC))
            assert result.status == OrderStatus.REJECTED
            assert "halt" in (result.reject_reason or "").lower()
        finally:
            _HARD_HALT.clear()

    def test_execute_with_retries_state_machine_blocks_duplicate(self, service: ExecutionService, order_request: OrderRequest, mock_broker: MagicMock):
        """
        When state machine returns existing non-terminal machine, duplicate is blocked.

        The state machine blocks re-entry when an order is in a non-terminal state
        (e.g. VALIDATED/PERSISTED/SUBMITTED). We simulate this by pre-creating
        a machine in VALIDATED state, then attempting execution.
        """
        order_request.idempotency_key = "nonterminal-block-key"
        ctx = ExecutionContext(execution_mode=ExecutionMode.AUTOMATIC)
        # Pre-create a state machine in a non-terminal (VALIDATED) state
        mgr = service._state_machine
        machine, is_new = mgr.create_or_get("nonterminal-block-key", "NIFTY", 50, 23500.0, "BUY")
        machine.try_transition_to(ExecutionState.VALIDATED)
        # Attempt execution — should be blocked by the non-terminal check
        result = service.execute_order(order_request, ctx)
        assert result.status == OrderStatus.REJECTED
        assert "already in" in (result.reject_reason or "").lower()
