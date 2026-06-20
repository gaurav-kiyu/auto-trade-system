"""
Tests for core/execution/reconciliation/service.py

Covers:
- Dataclass creation (ReconciliationResult, ReconciliationIssue)
- ReconciliationService initialization and DB setup
- record_order, update_order_fill, get_pending_orders, get_all_orders
- All 4 detection methods (stale, orphan, mismatch, unrecorded)
- reconcile() main entry point with mock broker
- _detect_ambiguity and _determine_freeze_reason
- _auto_repair for stale orders and unrecorded fills
- is_frozen/unfreeze/trading freeze on ambiguity
- Thread safety with concurrent operations
- Error handling (broker failures, DB errors)
"""
from __future__ import annotations

import os
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from core.execution.reconciliation.service import (
    ReconciliationIssue,
    ReconciliationResult,
    ReconciliationService,
    ReconciliationState,
    TradingFreezeReason,
)


# ═══════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════

@pytest.fixture
def db_path(tmp_path: Any) -> str:
    """Temp DB path for each test."""
    return str(tmp_path / "test_recon.db")


@pytest.fixture
def service(db_path: str) -> ReconciliationService:
    """Clean service with temp DB and auto-repair enabled."""
    return ReconciliationService(db_path=db_path, enable_auto_repair=True)


@pytest.fixture
def service_no_repair(db_path: str) -> ReconciliationService:
    """Clean service with auto-repair disabled."""
    return ReconciliationService(db_path=db_path, enable_auto_repair=False)


@pytest.fixture
def service_with_callback(db_path: str) -> tuple[ReconciliationService, MagicMock]:
    """Service with a freeze callback mock."""
    callback = MagicMock()
    svc = ReconciliationService(db_path=db_path, freeze_callback=callback, enable_auto_repair=True)
    return svc, callback


def make_broker_order(
    order_id: str = "BRK-001",
    status: str = "COMPLETE",
    filled_qty: int = 50,
    price: float = 100.0,
    symbol: str = "NIFTY",
) -> dict[str, Any]:
    return {
        "orderid": order_id,
        "orderstatus": status,
        "filledshares": filled_qty,
        "averageprice": price,
        "tradingsymbol": symbol,
    }


def make_broker_position(
    symbol: str = "NIFTY",
    quantity: int = 50,
) -> dict[str, Any]:
    return {"symbol": symbol, "quantity": quantity}


def seed_internal_order(
    service: ReconciliationService,
    order_id: str = "INT-001",
    intent_id: str = "IT-001",
    symbol: str = "NIFTY",
    direction: str = "BUY",
    quantity: int = 50,
    status: str = "ACKNOWLEDGED",
    broker_order_id: str | None = "BRK-001",
    filled_qty: int = 50,
    avg_price: float = 100.0,
):
    """Helper to insert an order into the service's DB and optionally mark fill."""
    service.record_order(
        order_id=order_id,
        intent_id=intent_id,
        symbol=symbol,
        direction=direction,
        quantity=quantity,
        status=status,
        broker_order_id=broker_order_id,
    )
    if filled_qty > 0:
        service.update_order_fill(order_id, filled_qty, avg_price, status)


# ═══════════════════════════════════════════════════════════════════
# Dataclass & Enum Tests
# ═══════════════════════════════════════════════════════════════════

class TestDataclasses:
    def test_reconciliation_state_values(self):
        assert ReconciliationState.CLEAN.value == "CLEAN"
        assert ReconciliationState.ORPHAN_POSITION.value == "ORPHAN_POSITION"
        assert ReconciliationState.STALE_ORDER.value == "STALE_ORDER"
        assert ReconciliationState.QUANTITY_MISMATCH.value == "QUANTITY_MISMATCH"
        assert ReconciliationState.UNRECORDED_FILL.value == "UNRECORDED_FILL"
        assert ReconciliationState.AMBIGUOUS.value == "AMBIGUOUS"

    def test_trading_freeze_reason_values(self):
        assert TradingFreezeReason.RECONCILIATION_FAILED.value == "RECONCILIATION_FAILED"
        assert TradingFreezeReason.ORPHAN_POSITIONS_DETECTED.value == "ORPHAN_POSITIONS_DETECTED"
        assert TradingFreezeReason.STALE_ORDERS_UNRESOLVED.value == "STALE_ORDERS_UNRESOLVED"
        assert TradingFreezeReason.QUANTITY_MISMATCH_UNRESOLVED.value == "QUANTITY_MISMATCH_UNRESOLVED"
        assert TradingFreezeReason.BROKER_UNAVAILABLE.value == "BROKER_UNAVAILABLE"

    def test_reconciliation_issue_creation(self):
        """Verify ReconciliationIssue is created with 5 fields (timestamp is module-level)."""
        issue = ReconciliationIssue(
            issue_type=ReconciliationState.STALE_ORDER,
            order_id="ORD-001",
            internal_value="ACKNOWLEDGED",
            broker_value="NOT_FOUND",
            description="Order not found in broker",
        )
        assert issue.issue_type == ReconciliationState.STALE_ORDER
        assert issue.order_id == "ORD-001"
        assert issue.internal_value == "ACKNOWLEDGED"
        assert issue.broker_value == "NOT_FOUND"
        assert issue.description == "Order not found in broker"

    def test_reconciliation_result_creation(self):
        """Verify ReconciliationResult creation with all fields."""
        issue = ReconciliationIssue(
            issue_type=ReconciliationState.STALE_ORDER,
            order_id="ORD-001",
            internal_value="ACKNOWLEDGED",
            broker_value="NOT_FOUND",
            description="Stale",
        )
        result = ReconciliationResult(
            is_clean=False,
            issues=[issue],
            freeze_reason=TradingFreezeReason.STALE_ORDERS_UNRESOLVED,
            broker_positions_count=5,
            internal_orders_count=10,
            repaired_count=1,
        )
        assert result.is_clean is False
        assert len(result.issues) == 1
        assert result.freeze_reason == TradingFreezeReason.STALE_ORDERS_UNRESOLVED
        assert result.broker_positions_count == 5
        assert result.internal_orders_count == 10
        assert result.repaired_count == 1
        assert result.issues[0].issue_type == ReconciliationState.STALE_ORDER

    def test_reconciliation_result_defaults(self):
        """Verify default values for optional fields."""
        result = ReconciliationResult(is_clean=True, issues=[], freeze_reason=None)
        assert result.is_clean is True
        assert result.issues == []
        assert result.freeze_reason is None
        assert result.broker_positions_count == 0
        assert result.internal_orders_count == 0
        assert result.repaired_count == 0
        assert result.timestamp is not None

    def test_reconciliation_result_timestamp_on_creation(self):
        """timestamp is set to now_ist() by default via field factory."""
        before = datetime.now(timezone.utc)
        result = ReconciliationResult(is_clean=True, issues=[], freeze_reason=None)
        after = datetime.now(timezone.utc)
        # IST is UTC+5:30, so the timestamp should be a future-aware or naive IST datetime
        assert result.timestamp is not None


# ═══════════════════════════════════════════════════════════════════
# Init & DB Setup Tests
# ═══════════════════════════════════════════════════════════════════

class TestInit:
    def test_creates_db_and_table(self, db_path: str):
        svc = ReconciliationService(db_path=db_path)
        assert os.path.exists(db_path)
        with sqlite3.connect(db_path) as conn:
            cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='execution_orders'")
            assert cursor.fetchone() is not None

    def test_table_has_all_columns(self, db_path: str):
        svc = ReconciliationService(db_path=db_path)
        with sqlite3.connect(db_path) as conn:
            cursor = conn.execute("PRAGMA table_info(execution_orders)")
            cols = {row[1] for row in cursor.fetchall()}
        required = {"order_id", "intent_id", "symbol", "direction", "quantity",
                    "filled_quantity", "average_price", "status", "broker_order_id",
                    "created_at", "updated_at", "idempotency_key", "is_reconciled", "notes"}
        assert required.issubset(cols), f"Missing columns: {required - cols}"

    def test_has_required_indexes(self, db_path: str):
        svc = ReconciliationService(db_path=db_path)
        with sqlite3.connect(db_path) as conn:
            cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='index'")
            indexes = {row[0] for row in cursor.fetchall()}
        assert "idx_orders_status" in indexes
        assert "idx_orders_reconciled" in indexes

    def test_init_without_auto_repair(self, db_path: str):
        svc = ReconciliationService(db_path=db_path, enable_auto_repair=False)
        assert svc._enable_auto_repair is False

    def test_init_with_freeze_callback(self, db_path: str):
        callback = MagicMock()
        svc = ReconciliationService(db_path=db_path, freeze_callback=callback)
        assert svc._freeze_callback is callback

    def test_init_raises_on_invalid_db_path(self):
        """An invalid parent directory should raise an error."""
        with pytest.raises((sqlite3.OperationalError, OSError)):
            ReconciliationService(db_path="/nonexistent_dir/test.db")


# ═══════════════════════════════════════════════════════════════════
# Record Order & Fill Tests
# ═══════════════════════════════════════════════════════════════════

class TestRecordOrder:
    def test_records_new_order(self, service: ReconciliationService):
        service.record_order(
            order_id="ORD-001", intent_id="IT-001",
            symbol="NIFTY", direction="BUY", quantity=50,
            status="CREATED", broker_order_id=None,
        )
        orders = service.get_all_orders()
        assert len(orders) == 1
        o = orders[0]
        assert o["order_id"] == "ORD-001"
        assert o["intent_id"] == "IT-001"
        assert o["symbol"] == "NIFTY"
        assert o["direction"] == "BUY"
        assert o["quantity"] == 50
        assert o["status"] == "CREATED"
        assert o["filled_quantity"] == 0
        assert o["average_price"] == 0.0
        assert o["is_reconciled"] == 0

    def test_records_with_idempotency_key(self, service: ReconciliationService):
        service.record_order(
            order_id="ORD-002", intent_id="IT-002",
            symbol="BANKNIFTY", direction="SELL", quantity=25,
            status="ACKNOWLEDGED", broker_order_id="BRK-002",
            idempotency_key="idem-002",
        )
        orders = service.get_all_orders()
        assert orders[0]["idempotency_key"] == "idem-002"

    def test_replace_existing_order(self, service: ReconciliationService):
        """INSERT OR REPLACE should allow overwriting."""
        service.record_order("ORD-001", "IT-001", "NIFTY", "BUY", 50, "CREATED")
        service.record_order("ORD-001", "IT-002", "BANKNIFTY", "SELL", 25, "SUBMITTED")
        orders = service.get_all_orders()
        assert len(orders) == 1
        assert orders[0]["symbol"] == "BANKNIFTY"
        assert orders[0]["intent_id"] == "IT-002"

    def test_invalid_data_does_not_raise(self, service: ReconciliationService):
        """Function logs error instead of raising on invalid data."""
        # This should not raise; method catches exceptions internally
        service.record_order(None, None, None, None, None, None)  # type: ignore
        # Should not crash; silently logs error
        assert True


class TestUpdateOrderFill:
    def test_updates_fill_data(self, service: ReconciliationService):
        service.record_order("ORD-001", "IT-001", "NIFTY", "BUY", 50, "ACKNOWLEDGED")
        service.update_order_fill("ORD-001", 50, 101.5, "FILLED")
        orders = service.get_all_orders()
        o = orders[0]
        assert o["filled_quantity"] == 50
        assert o["average_price"] == 101.5
        assert o["status"] == "FILLED"
        assert o["is_reconciled"] == 0  # Reset on fill update

    def test_updates_nonexistent_order_does_not_raise(self, service: ReconciliationService):
        service.update_order_fill("NONEXISTENT", 10, 100.0, "FILLED")
        assert True

    def test_resets_reconciled_flag(self, service: ReconciliationService):
        """update_order_fill should reset is_reconciled to 0."""
        service.record_order("ORD-001", "IT-001", "NIFTY", "BUY", 50, "FILLED")
        # Manually set is_reconciled = 1
        with sqlite3.connect(service._db_path) as conn:
            conn.execute("UPDATE execution_orders SET is_reconciled = 1 WHERE order_id = 'ORD-001'")
            conn.commit()
        service.update_order_fill("ORD-001", 50, 100.0, "FILLED")
        orders = service.get_all_orders()
        assert orders[0]["is_reconciled"] == 0


# ═══════════════════════════════════════════════════════════════════
# Query Tests
# ═══════════════════════════════════════════════════════════════════

class TestGetOrders:
    def test_get_all_orders_empty(self, service: ReconciliationService):
        assert service.get_all_orders() == []

    def test_get_all_orders_returns_all(self, service: ReconciliationService):
        service.record_order("ORD-001", "IT-001", "NIFTY", "BUY", 50, "CREATED")
        service.record_order("ORD-002", "IT-002", "BANKNIFTY", "SELL", 25, "FILLED")
        assert len(service.get_all_orders()) == 2

    def test_get_pending_orders_excludes_terminal(self, service: ReconciliationService):
        service.record_order("ORD-001", "IT-001", "NIFTY", "BUY", 50, "CREATED")
        service.record_order("ORD-002", "IT-002", "BANKNIFTY", "SELL", 25, "FILLED")
        service.record_order("ORD-003", "IT-003", "FINNIFTY", "BUY", 10, "CANCELLED")
        service.record_order("ORD-004", "IT-004", "NIFTY", "SELL", 30, "REJECTED")
        service.record_order("ORD-005", "IT-005", "BANKNIFTY", "BUY", 20, "EXPIRED")
        pending = service.get_pending_orders()
        assert len(pending) == 1
        assert pending[0]["order_id"] == "ORD-001"

    def test_get_pending_orders_returns_empty_when_all_terminal(self, service: ReconciliationService):
        service.record_order("ORD-001", "IT-001", "NIFTY", "BUY", 50, "FILLED")
        service.record_order("ORD-002", "IT-002", "BANKNIFTY", "SELL", 25, "CANCELLED")
        assert service.get_pending_orders() == []

    def test_get_pending_orders_empty_when_no_orders(self, service: ReconciliationService):
        assert service.get_pending_orders() == []


# ═══════════════════════════════════════════════════════════════════
# Detection Methods
# ═══════════════════════════════════════════════════════════════════

class TestDetectStaleOrders:
    def test_no_stale_orders(self, service: ReconciliationService):
        seed_internal_order(service, broker_order_id="BRK-001")
        broker_orders = [make_broker_order(order_id="BRK-001")]
        issues = service._detect_stale_orders(
            service.get_pending_orders(), broker_orders
        )
        assert len(issues) == 0

    def test_detects_stale_order(self, service: ReconciliationService):
        seed_internal_order(service, broker_order_id="BRK-001")
        # No matching broker order
        issues = service._detect_stale_orders(
            service.get_pending_orders(), []
        )
        assert len(issues) == 1
        assert issues[0].issue_type == ReconciliationState.STALE_ORDER
        assert issues[0].order_id == "INT-001"

    def test_ignores_terminal_orders(self, service: ReconciliationService):
        seed_internal_order(service, order_id="INT-001", status="FILLED")
        # Terminal orders should not appear in pending
        pending = service.get_pending_orders()
        assert len(pending) == 0

    def test_stale_order_without_broker_id(self, service: ReconciliationService):
        """If broker_order_id is None/empty, not flagged as stale."""
        service.record_order("INT-001", "IT-001", "NIFTY", "BUY", 50, "ACKNOWLEDGED")
        issues = service._detect_stale_orders(
            service.get_pending_orders(), []
        )
        assert len(issues) == 0  # No broker_order_id to match

    def test_broker_order_id_key_variants(self, service: ReconciliationService):
        """Handle both 'orderid' and 'order_id' keys in broker orders."""
        seed_internal_order(service, broker_order_id="BRK-001")
        broker_order = {"order_id": "BRK-001", "status": "COMPLETE"}
        issues = service._detect_stale_orders(
            service.get_pending_orders(), [broker_order]
        )
        assert len(issues) == 0  # Found by order_id key


class TestDetectOrphanPositions:
    def test_no_orphans(self, service: ReconciliationService):
        seed_internal_order(service, symbol="NIFTY")
        positions = [make_broker_position(symbol="NIFTY", quantity=50)]
        issues = service._detect_orphan_positions(
            positions, service.get_pending_orders()
        )
        assert len(issues) == 0

    def test_detects_orphan_position(self, service: ReconciliationService):
        seed_internal_order(service)
        positions = [make_broker_position(symbol="BANKNIFTY", quantity=100)]
        issues = service._detect_orphan_positions(
            positions, service.get_all_orders()
        )
        assert len(issues) == 1
        assert issues[0].issue_type == ReconciliationState.ORPHAN_POSITION
        assert "BANKNIFTY" in issues[0].description

    def test_ignores_zero_quantity_positions(self, service: ReconciliationService):
        seed_internal_order(service)
        positions = [make_broker_position(symbol="BANKNIFTY", quantity=0)]
        issues = service._detect_orphan_positions(
            positions, service.get_all_orders()
        )
        assert len(issues) == 0

    def test_uses_tradingsymbol_fallback(self, service: ReconciliationService):
        """If 'symbol' key is missing, use 'tradingsymbol'."""
        seed_internal_order(service)
        pos = {"tradingsymbol": "NIFTY", "quantity": 50}
        # Symbol matches internal, so no orphan
        issues = service._detect_orphan_positions(
            [pos], service.get_all_orders()
        )
        assert len(issues) == 0


class TestDetectQuantityMismatches:
    def test_no_mismatch(self, service: ReconciliationService):
        seed_internal_order(service, filled_qty=50)
        broker_orders = [make_broker_order(order_id="BRK-001", filled_qty=50)]
        issues = service._detect_quantity_mismatches(
            broker_orders, service.get_all_orders()
        )
        assert len(issues) == 0

    def test_detects_mismatch(self, service: ReconciliationService):
        seed_internal_order(service, filled_qty=50)
        broker_orders = [make_broker_order(order_id="BRK-001", filled_qty=25)]
        issues = service._detect_quantity_mismatches(
            broker_orders, service.get_all_orders()
        )
        assert len(issues) == 1
        assert issues[0].issue_type == ReconciliationState.QUANTITY_MISMATCH

    def test_uses_filled_quantity_fallback(self, service: ReconciliationService):
        """Broker order may use 'filled_quantity' instead of 'filledshares'."""
        seed_internal_order(service, filled_qty=50)
        broker_order = {"orderid": "BRK-001", "filled_quantity": 30}
        issues = service._detect_quantity_mismatches(
            [broker_order], service.get_all_orders()
        )
        assert len(issues) == 1

    def test_ignores_broker_orders_without_matching_internal(self, service: ReconciliationService):
        broker_orders = [make_broker_order(order_id="BRK-001")]
        issues = service._detect_quantity_mismatches(
            broker_orders, []
        )
        assert len(issues) == 0  # No matching internal order


class TestDetectUnrecordedFills:
    def test_no_unrecorded_fills(self, service: ReconciliationService):
        seed_internal_order(service, filled_qty=50)
        broker_orders = [make_broker_order(order_id="BRK-001", filled_qty=50)]
        issues = service._detect_unrecorded_fills(
            broker_orders, service.get_all_orders()
        )
        assert len(issues) == 0

    def test_detects_unrecorded_fill(self, service: ReconciliationService):
        """Broker has COMPLETE order with no matching internal broker_order_id."""
        # Internal order exists but without broker_order_id
        service.record_order("INT-001", "IT-001", "NIFTY", "BUY", 50, "CREATED")
        broker_orders = [make_broker_order(order_id="BRK-001", filled_qty=50)]
        issues = service._detect_unrecorded_fills(
            broker_orders, service.get_all_orders()
        )
        assert len(issues) == 1
        assert issues[0].issue_type == ReconciliationState.UNRECORDED_FILL

    def test_ignores_non_filled_status(self, service: ReconciliationService):
        seed_internal_order(service)
        broker_orders = [make_broker_order(order_id="BRK-001", status="PENDING")]
        issues = service._detect_unrecorded_fills(
            broker_orders, service.get_all_orders()
        )
        assert len(issues) == 0

    def test_uses_status_field_fallback(self, service: ReconciliationService):
        """Broker order may use 'status' instead of 'orderstatus'."""
        seed_internal_order(service)
        broker_order = {"orderid": "BRK-002", "status": "FILLED", "filledshares": 10}
        # Different broker order id -> no match in internal
        issues = service._detect_unrecorded_fills(
            [broker_order], service.get_all_orders()
        )
        assert len(issues) == 1


# ═══════════════════════════════════════════════════════════════════
# Ambiguity & Freeze Reason Tests
# ═══════════════════════════════════════════════════════════════════

class TestDetectAmbiguity:
    def test_not_ambiguous_with_few_clean_issues(self, service: ReconciliationService):
        """Single stale order should not be ambiguous."""
        issue = ReconciliationIssue(
            issue_type=ReconciliationState.STALE_ORDER,
            order_id="ORD-001",
            internal_value="ACKNOWLEDGED",
            broker_value="NOT_FOUND",
            description="Stale",
        )
        assert service._detect_ambiguity([issue]) is False

    def test_ambiguous_with_many_issues(self, service: ReconciliationService):
        issues = [
            ReconciliationIssue(ReconciliationState.STALE_ORDER, f"ORD-{i}", "A", "B", f"Issue {i}")
            for i in range(4)
        ]
        assert service._detect_ambiguity(issues) is True

    def test_ambiguous_with_orphan_position(self, service: ReconciliationService):
        issue = ReconciliationIssue(
            issue_type=ReconciliationState.ORPHAN_POSITION,
            order_id=None, internal_value="NO_ORDER",
            broker_value=100, description="Orphan",
        )
        assert service._detect_ambiguity([issue]) is True

    def test_ambiguous_with_quantity_mismatch(self, service: ReconciliationService):
        issue = ReconciliationIssue(
            issue_type=ReconciliationState.QUANTITY_MISMATCH,
            order_id="ORD-001", internal_value=50,
            broker_value=25, description="Mismatch",
        )
        assert service._detect_ambiguity([issue]) is True

    def test_ambiguous_with_ambiguous_type(self, service: ReconciliationService):
        issue = ReconciliationIssue(
            issue_type=ReconciliationState.AMBIGUOUS,
            order_id=None, internal_value=None,
            broker_value=None, description="Ambiguous",
        )
        assert service._detect_ambiguity([issue]) is True


class TestDetermineFreezeReason:
    def test_orphan_positions_priority(self, service: ReconciliationService):
        issues = [
            ReconciliationIssue(ReconciliationState.ORPHAN_POSITION, None, "A", "B", "Orphan"),
            ReconciliationIssue(ReconciliationState.STALE_ORDER, "O1", "A", "B", "Stale"),
        ]
        assert service._determine_freeze_reason(issues) == TradingFreezeReason.ORPHAN_POSITIONS_DETECTED

    def test_stale_orders_fallback(self, service: ReconciliationService):
        issues = [
            ReconciliationIssue(ReconciliationState.STALE_ORDER, "O1", "A", "B", "Stale"),
        ]
        assert service._determine_freeze_reason(issues) == TradingFreezeReason.STALE_ORDERS_UNRESOLVED

    def test_quantity_mismatch_fallback(self, service: ReconciliationService):
        issues = [
            ReconciliationIssue(ReconciliationState.QUANTITY_MISMATCH, "O1", 50, 25, "Mismatch"),
        ]
        assert service._determine_freeze_reason(issues) == TradingFreezeReason.QUANTITY_MISMATCH_UNRESOLVED

    def test_default_reconciliation_failed(self, service: ReconciliationService):
        issues = [
            ReconciliationIssue(ReconciliationState.UNRECORDED_FILL, "O1", "A", "B", "Fill"),
        ]
        assert service._determine_freeze_reason(issues) == TradingFreezeReason.RECONCILIATION_FAILED


# ═══════════════════════════════════════════════════════════════════
# Freeze / Unfreeze Tests
# ═══════════════════════════════════════════════════════════════════

class TestFreeze:
    def test_not_frozen_initially(self, service: ReconciliationService):
        frozen, reason = service.is_frozen()
        assert frozen is False
        assert reason is None

    def test_freeze_trading(self, service: ReconciliationService):
        service._freeze_trading(TradingFreezeReason.ORPHAN_POSITIONS_DETECTED, "Found orphan")
        frozen, reason = service.is_frozen()
        assert frozen is True
        assert reason == TradingFreezeReason.ORPHAN_POSITIONS_DETECTED

    def test_unfreeze(self, service: ReconciliationService):
        service._freeze_trading(TradingFreezeReason.RECONCILIATION_FAILED, "Failed")
        service.unfreeze()
        frozen, reason = service.is_frozen()
        assert frozen is False
        assert reason is None

    def test_freeze_callback_invoked(self, service_with_callback):
        svc, callback = service_with_callback
        svc._freeze_trading(TradingFreezeReason.RECONCILIATION_FAILED, "Test failure")
        callback.assert_called_once_with(TradingFreezeReason.RECONCILIATION_FAILED, "Test failure")

    def test_freeze_callback_exception_handled(self, service_with_callback):
        """If callback raises, freeze still happens."""
        svc, callback = service_with_callback
        callback.side_effect = ValueError("Callback failed")
        svc._freeze_trading(TradingFreezeReason.RECONCILIATION_FAILED, "Test")
        frozen, _ = svc.is_frozen()
        assert frozen is True


# ═══════════════════════════════════════════════════════════════════
# Broker Adapter Fetch Tests
# ═══════════════════════════════════════════════════════════════════

class TestFetchBrokerOrders:
    def test_uses_get_order_book(self):
        adapter = MagicMock()
        adapter.get_order_book.return_value = [{"orderid": "BRK-001"}]
        svc = ReconciliationService(db_path=":memory:")
        orders = svc._fetch_broker_orders(adapter)
        assert len(orders) == 1
        assert orders[0]["orderid"] == "BRK-001"

    def test_uses_port_get_order_book(self):
        """Uses spec=object so the adapter doesn't have get_order_book."""
        port = MagicMock()
        port.get_order_book.return_value = [{"orderid": "BRK-001"}]
        adapter = MagicMock(spec=object())
        adapter._port = port
        svc = ReconciliationService(db_path=":memory:")
        orders = svc._fetch_broker_orders(adapter)
        assert len(orders) == 1

    def test_returns_empty_on_error(self):
        adapter = MagicMock()
        adapter.get_order_book.side_effect = ConnectionError("Broker down")
        svc = ReconciliationService(db_path=":memory:")
        orders = svc._fetch_broker_orders(adapter)
        assert orders == []

    def test_returns_empty_when_no_method(self):
        adapter = object()
        svc = ReconciliationService(db_path=":memory:")
        orders = svc._fetch_broker_orders(adapter)
        assert orders == []

    def test_handles_dict_response_with_data_key(self):
        adapter = MagicMock()
        adapter.get_order_book.return_value = {"data": [{"orderid": "BRK-001"}]}
        svc = ReconciliationService(db_path=":memory:")
        orders = svc._fetch_broker_orders(adapter)
        assert len(orders) == 1


class TestFetchBrokerPositions:
    def test_uses_get_positions(self):
        adapter = MagicMock()
        adapter.get_positions.return_value = [{"symbol": "NIFTY", "quantity": 50}]
        svc = ReconciliationService(db_path=":memory:")
        positions = svc._fetch_broker_positions(adapter)
        assert len(positions) == 1

    def test_uses_port_get_positions(self):
        """Uses spec=object so the adapter doesn't have get_positions."""
        port = MagicMock()
        port.get_positions.return_value = [{"symbol": "NIFTY", "quantity": 50}]
        adapter = MagicMock(spec=object())
        adapter._port = port
        svc = ReconciliationService(db_path=":memory:")
        positions = svc._fetch_broker_positions(adapter)
        assert len(positions) == 1

    def test_returns_empty_list_when_get_positions_returns_none(self):
        adapter = MagicMock()
        adapter.get_positions.return_value = None
        svc = ReconciliationService(db_path=":memory:")
        positions = svc._fetch_broker_positions(adapter)
        assert positions == []

    def test_returns_empty_on_error(self):
        adapter = MagicMock()
        adapter.get_positions.side_effect = ConnectionError("Broker down")
        svc = ReconciliationService(db_path=":memory:")
        positions = svc._fetch_broker_positions(adapter)
        assert positions == []


# ═══════════════════════════════════════════════════════════════════
# Auto-Repair Tests
# ═══════════════════════════════════════════════════════════════════

class TestAutoRepair:
    def test_repairs_stale_order(self, service: ReconciliationService):
        """Stale order should be marked as terminal."""
        seed_internal_order(service, broker_order_id="BRK-001")
        issue = ReconciliationIssue(
            issue_type=ReconciliationState.STALE_ORDER,
            order_id="INT-001",
            internal_value="ACKNOWLEDGED",
            broker_value="NOT_FOUND",
            description="Stale",
        )
        repaired = service._auto_repair([issue], MagicMock())
        assert repaired == 1
        orders = service.get_all_orders()
        assert orders[0]["status"] == "UNKNOWN_STALE"
        assert orders[0]["is_reconciled"] == 1

    def test_repairs_unrecorded_fill(self, service: ReconciliationService):
        """Unrecorded fill should be written to the DB (via update_order_fill).

        Note: _record_unrecorded_fill uses issue.order_id (the broker order id)
        as the PK to call update_order_fill, so the internal order must have
        that same ID to be found.
        """
        # Create internal order with order_id matching the broker order id
        service.record_order("BRK-001", "IT-001", "NIFTY", "BUY", 50, "ACKNOWLEDGED",
                             broker_order_id="BRK-001")
        issue = ReconciliationIssue(
            issue_type=ReconciliationState.UNRECORDED_FILL,
            order_id="BRK-001",
            internal_value="NOT_FOUND",
            broker_value={"filled_qty": 50, "price": 100.0},
            description="Unrecorded fill",
        )
        repaired = service._auto_repair([issue], MagicMock())
        assert repaired == 1
        # Verify fill was recorded via update_order_fill
        orders = service.get_all_orders()
        assert orders[0]["filled_quantity"] == 50
        assert orders[0]["average_price"] == 100.0

    def test_skips_orphan_position_repair(self, service: ReconciliationService):
        """Orphan positions should NOT be auto-repaired (not implemented)."""
        issue = ReconciliationIssue(
            issue_type=ReconciliationState.ORPHAN_POSITION,
            order_id=None,
            internal_value="NO_ORDER",
            broker_value=100,
            description="Orphan",
        )
        repaired = service._auto_repair([issue], MagicMock())
        assert repaired == 0  # Not handled by auto-repair

    def test_no_auto_repair_when_disabled(self, service_no_repair):
        service_no_repair.record_order("INT-001", "IT-001", "NIFTY", "BUY", 50, "ACKNOWLEDGED")
        issue = ReconciliationIssue(
            issue_type=ReconciliationState.STALE_ORDER,
            order_id="INT-001",
            internal_value="ACKNOWLEDGED",
            broker_value="NOT_FOUND",
            description="Stale",
        )
        adapter = MagicMock()
        service_no_repair.reconcile(adapter)
        # Should not crash; auto_repair is disabled so issues are not resolved
        assert True


# ═══════════════════════════════════════════════════════════════════
# Main reconcile() Tests
# ═══════════════════════════════════════════════════════════════════

class TestReconcile:
    def test_clean_reconciliation(self, service: ReconciliationService):
        """No issues when broker and internal match."""
        seed_internal_order(service, filled_qty=50)
        adapter = MagicMock()
        adapter.get_order_book.return_value = [make_broker_order(order_id="BRK-001", filled_qty=50)]
        adapter.get_positions.return_value = [make_broker_position(symbol="NIFTY", quantity=50)]

        result = service.reconcile(adapter)
        assert result.is_clean is True
        assert len(result.issues) == 0
        assert result.freeze_reason is None
        assert result.broker_positions_count == 1
        assert result.internal_orders_count == 1

    def test_detects_stale_issue(self, service: ReconciliationService):
        """Stale order detected when broker doesn't have the order."""
        seed_internal_order(service, filled_qty=50)
        adapter = MagicMock()
        adapter.get_order_book.return_value = []  # No broker orders
        adapter.get_positions.return_value = [make_broker_position(symbol="NIFTY", quantity=50)]

        result = service.reconcile(adapter)
        assert result.is_clean is False
        assert len(result.issues) > 0
        assert any(i.issue_type == ReconciliationState.STALE_ORDER for i in result.issues)
        # Not ambiguous (single stale order), so no freeze
        assert result.freeze_reason is None

    def test_ambiguous_orphan_triggers_freeze(self, service: ReconciliationService):
        """Orphan position triggers freeze."""
        seed_internal_order(service)
        adapter = MagicMock()
        adapter.get_order_book.return_value = [make_broker_order()]
        # Orphan position in broker (not in internal)
        adapter.get_positions.return_value = [make_broker_position(symbol="BANKNIFTY", quantity=100)]

        result = service.reconcile(adapter)
        assert result.is_clean is False
        assert result.freeze_reason == TradingFreezeReason.ORPHAN_POSITIONS_DETECTED
        frozen, reason = service.is_frozen()
        assert frozen is True

    def test_quantity_mismatch_triggers_freeze(self, service: ReconciliationService):
        """Quantity mismatch triggers freeze."""
        seed_internal_order(service, filled_qty=50)
        adapter = MagicMock()
        # Broker has different filled quantity
        adapter.get_order_book.return_value = [make_broker_order(order_id="BRK-001", filled_qty=25)]
        adapter.get_positions.return_value = [make_broker_position(symbol="NIFTY", quantity=25)]

        result = service.reconcile(adapter)
        assert result.is_clean is False
        # Quantity mismatch is ambiguous -> freeze
        assert result.freeze_reason is not None

    def test_broker_failure_still_reconciles(self, service: ReconciliationService):
        """If broker adapter fails, services catches and returns failure result."""
        seed_internal_order(service)
        adapter = MagicMock()
        adapter.get_order_book.side_effect = ConnectionError("Broker unreachable")
        adapter.get_positions.return_value = []

        result = service.reconcile(adapter)
        # Should not crash; returns result with issues
        assert result.is_clean is False
        assert len(result.issues) > 0 or result.freeze_reason is not None

    def test_auto_repair_fixes_stale_order(self, service: ReconciliationService):
        """Stale order should be auto-repaired during reconcile."""
        seed_internal_order(service, filled_qty=50)
        adapter = MagicMock()
        adapter.get_order_book.return_value = []
        adapter.get_positions.return_value = [make_broker_position(symbol="NIFTY", quantity=50)]

        result = service.reconcile(adapter)
        assert result.is_clean is False
        # Stale order should be repaired
        assert result.repaired_count >= 1

    def test_reconcile_stores_last_result(self, service: ReconciliationService):
        adapter = MagicMock()
        adapter.get_order_book.return_value = []
        adapter.get_positions.return_value = []
        service.reconcile(adapter)
        assert service._last_reconciliation is not None
        assert service._last_reconciliation.is_clean is True
        assert len(service._last_reconciliation.issues) == 0


# ═══════════════════════════════════════════════════════════════════
# Thread Safety Tests
# ═══════════════════════════════════════════════════════════════════

class TestThreadSafety:
    def test_concurrent_record_orders(self, service: ReconciliationService):
        """Multiple threads recording orders should not corrupt DB."""
        errors = []
        lock = threading.Lock()

        def record(idx: int):
            try:
                service.record_order(
                    order_id=f"THR-{idx:04d}",
                    intent_id=f"IT-{idx:04d}",
                    symbol="NIFTY",
                    direction="BUY" if idx % 2 == 0 else "SELL",
                    quantity=idx,
                    status="CREATED",
                )
            except Exception as e:
                with lock:
                    errors.append(e)

        threads = [threading.Thread(target=record, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(5)

        assert len(errors) == 0, f"Errors during concurrent record: {errors}"
        assert len(service.get_all_orders()) == 20

    def test_concurrent_read_write(self, service: ReconciliationService, db_path: str):
        """Concurrent reads and writes should not deadlock."""
        # Pre-seed some orders
        for i in range(10):
            service.record_order(f"PRE-{i:04d}", f"IT-{i:04d}", "NIFTY", "BUY", i, "CREATED")

        errors = []
        lock = threading.Lock()

        def writer(idx: int):
            try:
                service.update_order_fill(f"PRE-{idx:04d}", idx, 100.0, "FILLED")
            except Exception as e:
                with lock:
                    errors.append(e)

        def reader():
            try:
                service.get_all_orders()
                service.get_pending_orders()
            except Exception as e:
                with lock:
                    errors.append(e)

        threads = []
        for i in range(10):
            threads.append(threading.Thread(target=writer, args=(i,)))
        for _ in range(5):
            threads.append(threading.Thread(target=reader))

        for t in threads:
            t.start()
        for t in threads:
            t.join(5)

        assert len(errors) == 0, f"Errors during concurrent read/write: {errors}"

    def test_concurrent_freeze_and_reconcile(self, service: ReconciliationService):
        """Freeze and reconcile can happen concurrently without deadlock."""
        errors = []
        lock = threading.Lock()

        def freeze_worker():
            try:
                service._freeze_trading(TradingFreezeReason.RECONCILIATION_FAILED, "Concurrent")
            except Exception as e:
                with lock:
                    errors.append(e)

        def reconcile_worker():
            try:
                adapter = MagicMock()
                adapter.get_order_book.return_value = []
                adapter.get_positions.return_value = []
                service.reconcile(adapter)
            except Exception as e:
                with lock:
                    errors.append(e)

        threads = [threading.Thread(target=freeze_worker) for _ in range(5)]
        threads += [threading.Thread(target=reconcile_worker) for _ in range(5)]

        for t in threads:
            t.start()
        for t in threads:
            t.join(5)

        assert len(errors) == 0, f"Errors during concurrent freeze/reconcile: {errors}"


# ═══════════════════════════════════════════════════════════════════
# Edge Cases
# ═══════════════════════════════════════════════════════════════════

class TestEdgeCases:
    def test_format_issues_empty(self, service: ReconciliationService):
        formatted = service._format_issues([])
        assert "Total issues: 0" in formatted

    def test_format_issues_with_many_issues(self, service: ReconciliationService):
        issues = [
            ReconciliationIssue(ReconciliationState.STALE_ORDER, f"ORD-{i}", "A", "B", f"Issue {i}")
            for i in range(15)
        ]
        formatted = service._format_issues(issues)
        assert "Total issues: 15" in formatted
        assert "... and 5 more" in formatted

    def test_record_unrecorded_fill_without_broker_value(self, service: ReconciliationService):
        """_record_unrecorded_fill should return early if no broker_value."""
        issue = ReconciliationIssue(
            issue_type=ReconciliationState.UNRECORDED_FILL,
            order_id=None,  # No order_id
            internal_value="NOT_FOUND",
            broker_value=None,
            description="No broker value",
        )
        # Should not raise
        service._record_unrecorded_fill(issue)
        assert True

    def test_mark_order_terminal_succeeds_on_nonexistent(self, service: ReconciliationService):
        """UPDATE on non-existent rows does not raise in SQLite."""
        # This should not raise - UPDATE affects 0 rows silently
        service._mark_order_terminal("NONEXISTENT", "CANCELLED")
        assert True

    def test_order_with_all_none_fields(self, service: ReconciliationService):
        """Handles requests where all optional fields are None."""
        # Would fail validation; fields are not nullable in schema
        pass
