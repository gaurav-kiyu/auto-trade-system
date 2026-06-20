"""Tests for core/execution/order_manager.py - Order lifecycle manager.

Covers:
- OrderState dataclass creation and defaults
- OrderManager initialization and durable storage
- _validate_transition() state machine rules
- create_order_intent() unique ID generation
- execute_intent() 3-phase submit with broker gateway
- update_order_status() with transition enforcement
- get_order_response() conversion
- Duplicate intent detection (idempotency)
- Crash recovery: _load_orders_from_disk()
- Thread safety with concurrent operations
- Schema migration (broker_order_id PK -> intent_id PK)
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.adapters.base_adapter import OrderRequest, OrderResponse, OrderStatus
from core.execution.order_manager import OrderManager, OrderState, order_manager


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def mock_broker_gateway():
    """Mock broker_gateway to prevent real broker calls."""
    with patch("core.execution.order_manager.broker_gateway") as mock:
        mock.place_order.return_value = OrderResponse(
            order_id="BROKER-001",
            status=OrderStatus.ACKNOWLEDGED,
            filled_qty=50,
            avg_price=150.0,
        )
        yield mock


@pytest.fixture
def mgr(tmp_path) -> OrderManager:
    """OrderManager with isolated temp DB."""
    db_path = str(tmp_path / "test_orders.db")
    return OrderManager(persistence_path=db_path)


@pytest.fixture
def sample_request() -> OrderRequest:
    return OrderRequest(
        symbol="NIFTY",
        qty=50,
        price=0.0,
        order_type="MARKET",
        direction="BUY",
        product="MIS",
        variety="REGULAR",
        tag="OPB_BOT",
        idempotency_key="",
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  OrderState Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestOrderState:
    def test_create_with_validated_status(self, sample_request: OrderRequest):
        state = OrderState(intent_id="intent-1", request=sample_request, status=OrderStatus.VALIDATED)
        assert state.intent_id == "intent-1"
        assert state.status == OrderStatus.VALIDATED
        assert state.broker_order_id is None
        assert state.filled_qty == 0
        assert state.error is None
        assert state.created_at is not None
        assert state.updated_at is not None

    def test_create_with_filled_status(self, sample_request: OrderRequest):
        state = OrderState(
            intent_id="intent-2",
            request=sample_request,
            status=OrderStatus.FILLED,
            broker_order_id="BRK-001",
            filled_qty=50,
            avg_price=150.0,
        )
        assert state.broker_order_id == "BRK-001"
        assert state.filled_qty == 50
        assert state.avg_price == 150.0

    def test_timestamps_on_creation(self, sample_request: OrderRequest):
        state = OrderState(intent_id="i1", request=sample_request, status=OrderStatus.NEW)
        assert state.created_at == state.updated_at


# ═══════════════════════════════════════════════════════════════════════════════
#  Initialization
# ═══════════════════════════════════════════════════════════════════════════════


class TestInit:
    def test_creates_db_file(self, tmp_path: Path):
        db_path = str(tmp_path / "test_orders.db")
        mgr = OrderManager(persistence_path=db_path)
        assert os.path.exists(db_path)

    def test_initializes_empty_orders(self, mgr: OrderManager):
        assert mgr._orders == {}
        assert mgr._broker_map == {}

    def test_has_lock(self, mgr: OrderManager):
        assert hasattr(mgr, "_lock")

    def test_custom_persistence_path(self, tmp_path: Path):
        db_path = str(tmp_path / "custom.db")
        mgr = OrderManager(persistence_path=db_path)
        assert mgr.PERSISTENCE_PATH == db_path


# ═══════════════════════════════════════════════════════════════════════════════
#  State Machine Validation
# ═══════════════════════════════════════════════════════════════════════════════


class TestValidateTransition:
    def setup_method(self):
        self.mgr = OrderManager(persistence_path=":memory:")

    def teardown_method(self):
        self.mgr = None

    def test_new_to_validated(self):
        assert self.mgr._validate_transition(OrderStatus.NEW, OrderStatus.VALIDATED)

    def test_new_to_failed(self):
        assert self.mgr._validate_transition(OrderStatus.NEW, OrderStatus.FAILED)

    def test_new_to_submitted_invalid(self):
        assert not self.mgr._validate_transition(OrderStatus.NEW, OrderStatus.SUBMITTED)

    def test_validated_to_submitted(self):
        assert self.mgr._validate_transition(OrderStatus.VALIDATED, OrderStatus.SUBMITTED)

    def test_validated_to_acknowledged(self):
        assert self.mgr._validate_transition(OrderStatus.VALIDATED, OrderStatus.ACKNOWLEDGED)

    def test_validated_to_failed(self):
        assert self.mgr._validate_transition(OrderStatus.VALIDATED, OrderStatus.FAILED)

    def test_submitted_to_acknowledged(self):
        assert self.mgr._validate_transition(OrderStatus.SUBMITTED, OrderStatus.ACKNOWLEDGED)

    def test_submitted_to_rejected(self):
        assert self.mgr._validate_transition(OrderStatus.SUBMITTED, OrderStatus.REJECTED)

    def test_acknowledged_to_filled(self):
        assert self.mgr._validate_transition(OrderStatus.ACKNOWLEDGED, OrderStatus.FILLED)

    def test_acknowledged_to_partial_fill(self):
        assert self.mgr._validate_transition(OrderStatus.ACKNOWLEDGED, OrderStatus.PARTIAL_FILL)

    def test_acknowledged_to_cancel_pending(self):
        assert self.mgr._validate_transition(OrderStatus.ACKNOWLEDGED, OrderStatus.CANCEL_PENDING)

    def test_partial_fill_to_filled(self):
        assert self.mgr._validate_transition(OrderStatus.PARTIAL_FILL, OrderStatus.FILLED)

    def test_partial_fill_to_more_partial(self):
        assert self.mgr._validate_transition(OrderStatus.PARTIAL_FILL, OrderStatus.PARTIAL_FILL)

    def test_filled_no_transitions(self):
        assert not self.mgr._validate_transition(OrderStatus.FILLED, OrderStatus.CANCELLED)

    def test_cancelled_no_transitions(self):
        assert not self.mgr._validate_transition(OrderStatus.CANCELLED, OrderStatus.FILLED)

    def test_rejected_no_transitions(self):
        assert not self.mgr._validate_transition(OrderStatus.REJECTED, OrderStatus.SUBMITTED)

    def test_failed_no_transitions(self):
        assert not self.mgr._validate_transition(OrderStatus.FAILED, OrderStatus.NEW)

    def test_unknown_status_returns_false(self):
        assert not self.mgr._validate_transition(OrderStatus.UNKNOWN, OrderStatus.FILLED)

    def test_cancel_pending_to_cancelled(self):
        assert self.mgr._validate_transition(OrderStatus.CANCEL_PENDING, OrderStatus.CANCELLED)

    def test_cancel_pending_to_filled(self):
        assert self.mgr._validate_transition(OrderStatus.CANCEL_PENDING, OrderStatus.FILLED)

    def test_cancel_pending_to_failed(self):
        assert self.mgr._validate_transition(OrderStatus.CANCEL_PENDING, OrderStatus.FAILED)


# ═══════════════════════════════════════════════════════════════════════════════
#  create_order_intent
# ═══════════════════════════════════════════════════════════════════════════════


class TestCreateOrderIntent:
    def test_returns_unique_id(self, mgr: OrderManager, sample_request: OrderRequest):
        id1 = mgr.create_order_intent(sample_request)
        id2 = mgr.create_order_intent(sample_request)
        assert id1 != id2

    def test_returns_uuid_string(self, mgr: OrderManager, sample_request: OrderRequest):
        intent_id = mgr.create_order_intent(sample_request)
        assert isinstance(intent_id, str)
        assert len(intent_id) > 10

    def test_does_not_add_to_orders(self, mgr: OrderManager, sample_request: OrderRequest):
        mgr.create_order_intent(sample_request)
        # create_order_intent doesn't add to orders dict directly
        assert len(mgr._orders) == 0


# ═══════════════════════════════════════════════════════════════════════════════
#  execute_intent
# ═══════════════════════════════════════════════════════════════════════════════


class TestExecuteIntent:
    def test_successful_execution(self, mgr: OrderManager, sample_request: OrderRequest,
                                  mock_broker_gateway: MagicMock):
        intent_id = mgr.create_order_intent(sample_request)
        response = mgr.execute_intent(intent_id, sample_request)

        assert response.status == OrderStatus.ACKNOWLEDGED
        assert response.order_id == "BROKER-001"
        assert response.filled_qty == 50
        assert response.avg_price == 150.0

    def test_stores_order_in_memory(self, mgr: OrderManager, sample_request: OrderRequest):
        intent_id = mgr.create_order_intent(sample_request)
        mgr.execute_intent(intent_id, sample_request)

        assert intent_id in mgr._orders
        assert mgr._orders[intent_id].status == OrderStatus.ACKNOWLEDGED

    def test_creates_broker_mapping(self, mgr: OrderManager, sample_request: OrderRequest):
        intent_id = mgr.create_order_intent(sample_request)
        mgr.execute_intent(intent_id, sample_request)

        assert "BROKER-001" in mgr._broker_map
        assert mgr._broker_map["BROKER-001"] == intent_id

    def test_duplicate_intent_returns_existing(self, mgr: OrderManager, sample_request: OrderRequest):
        intent_id = mgr.create_order_intent(sample_request)
        response1 = mgr.execute_intent(intent_id, sample_request)
        response2 = mgr.execute_intent(intent_id, sample_request)

        assert response1.order_id == response2.order_id
        assert response1.status == response2.status

    def test_broker_failure_returns_failed(self, mgr: OrderManager, sample_request: OrderRequest,
                                            mock_broker_gateway: MagicMock):
        mock_broker_gateway.place_order.return_value = OrderResponse(
            order_id="", status=OrderStatus.FAILED, error="Insufficient margin",
        )
        intent_id = mgr.create_order_intent(sample_request)
        response = mgr.execute_intent(intent_id, sample_request)

        assert response.status == OrderStatus.FAILED
        assert "margin" in (response.error or "").lower()

    def test_broker_exception_propagates(self, mgr: OrderManager, sample_request: OrderRequest,
                                          mock_broker_gateway: MagicMock):
        """Broker gateway exceptions should propagate to the caller."""
        mock_broker_gateway.place_order.side_effect = ConnectionError("Broker unreachable")
        intent_id = mgr.create_order_intent(sample_request)
        with pytest.raises(ConnectionError, match="Broker unreachable"):
            mgr.execute_intent(intent_id, sample_request)

    def test_failed_order_updates_status(self, mgr: OrderManager, sample_request: OrderRequest,
                                          mock_broker_gateway: MagicMock):
        mock_broker_gateway.place_order.return_value = OrderResponse(
            order_id="", status=OrderStatus.FAILED, error="Rejected",
        )
        intent_id = mgr.create_order_intent(sample_request)
        mgr.execute_intent(intent_id, sample_request)

        assert mgr._orders[intent_id].status == OrderStatus.FAILED
        assert mgr._orders[intent_id].error == "Rejected"

    def test_sets_event_on_completion(self, mgr: OrderManager, sample_request: OrderRequest):
        intent_id = mgr.create_order_intent(sample_request)
        mgr.execute_intent(intent_id, sample_request)

        event = mgr._intent_events.get(intent_id)
        assert event is not None
        assert event.is_set()

    def test_persists_to_db(self, mgr: OrderManager, sample_request: OrderRequest):
        intent_id = mgr.create_order_intent(sample_request)
        mgr.execute_intent(intent_id, sample_request)

        # Verify it was persisted (use fresh port to avoid caching)
        import sqlite3
        conn = sqlite3.connect(mgr.PERSISTENCE_PATH)
        rows = conn.execute("SELECT * FROM orders WHERE intent_id = ?", (intent_id,)).fetchall()
        conn.close()
        assert len(rows) == 1

    def test_persists_broker_data(self, mgr: OrderManager, sample_request: OrderRequest):
        intent_id = mgr.create_order_intent(sample_request)
        mgr.execute_intent(intent_id, sample_request)

        import sqlite3
        conn = sqlite3.connect(mgr.PERSISTENCE_PATH)
        row = conn.execute(
            "SELECT broker_order_id, status FROM orders WHERE intent_id = ?", (intent_id,)
        ).fetchone()
        conn.close()
        assert row is not None
        assert row[0] == "BROKER-001"
        assert row[1] == "ACKNOWLEDGED"


# ═══════════════════════════════════════════════════════════════════════════════
#  update_order_status
# ═══════════════════════════════════════════════════════════════════════════════


class TestUpdateOrderStatus:
    def test_valid_transition_updated(self, mgr: OrderManager, sample_request: OrderRequest):
        intent_id = mgr.create_order_intent(sample_request)
        mgr.execute_intent(intent_id, sample_request)

        # Valid transition: ACKNOWLEDGED -> FILLED
        mgr.update_order_status("BROKER-001", OrderStatus.FILLED, filled_qty=50, avg_price=150.0)
        assert mgr._orders[intent_id].status == OrderStatus.FILLED

    def test_invalid_transition_ignored(self, mgr: OrderManager, sample_request: OrderRequest):
        intent_id = mgr.create_order_intent(sample_request)
        mgr.execute_intent(intent_id, sample_request)

        # Invalid: ACKNOWLEDGED -> CANCELLED (must go through CANCEL_PENDING first)
        mgr.update_order_status("BROKER-001", OrderStatus.CANCELLED)
        assert mgr._orders[intent_id].status != OrderStatus.CANCELLED

    def test_unknown_broker_id(self, mgr: OrderManager):
        # Should not raise
        mgr.update_order_status("UNKNOWN", OrderStatus.FILLED)

    def test_updates_filled_quantity(self, mgr: OrderManager, sample_request: OrderRequest):
        intent_id = mgr.create_order_intent(sample_request)
        mgr.execute_intent(intent_id, sample_request)

        mgr.update_order_status("BROKER-001", OrderStatus.FILLED, filled_qty=50, avg_price=150.0)
        assert mgr._orders[intent_id].filled_qty == 50
        assert mgr._orders[intent_id].avg_price == 150.0

    def test_multiple_partial_fills(self, mgr: OrderManager, sample_request: OrderRequest):
        intent_id = mgr.create_order_intent(sample_request)
        mgr.execute_intent(intent_id, sample_request)

        mgr.update_order_status("BROKER-001", OrderStatus.PARTIAL_FILL, filled_qty=25, avg_price=150.0)
        mgr.update_order_status("BROKER-001", OrderStatus.PARTIAL_FILL, filled_qty=40, avg_price=151.0)
        mgr.update_order_status("BROKER-001", OrderStatus.FILLED, filled_qty=50, avg_price=150.5)
        assert mgr._orders[intent_id].status == OrderStatus.FILLED


# ═══════════════════════════════════════════════════════════════════════════════
#  get_order_response
# ═══════════════════════════════════════════════════════════════════════════════


class TestGetOrderResponse:
    def test_returns_response_for_known_order(self, mgr: OrderManager, sample_request: OrderRequest):
        intent_id = mgr.create_order_intent(sample_request)
        mgr.execute_intent(intent_id, sample_request)

        response = mgr.get_order_response("BROKER-001")
        assert response.order_id == "BROKER-001"
        assert response.status == OrderStatus.ACKNOWLEDGED

    def test_returns_not_found_for_unknown(self, mgr: OrderManager):
        response = mgr.get_order_response("UNKNOWN")
        assert response.status == OrderStatus.FAILED
        assert "not found" in (response.error or "").lower()

    def test_fallback_to_intent_id(self, mgr: OrderManager, sample_request: OrderRequest):
        """If broker_map lookup fails, try direct intent_id lookup."""
        intent_id = mgr.create_order_intent(sample_request)
        mgr.execute_intent(intent_id, sample_request)

        # Remove from broker_map to test fallback
        mgr._broker_map.clear()
        response = mgr.get_order_response(intent_id)
        assert response is not None


# ═══════════════════════════════════════════════════════════════════════════════
#  Crash Recovery (_load_orders_from_disk)
# ═══════════════════════════════════════════════════════════════════════════════


class TestCrashRecovery:
    def test_loads_in_flight_orders(self, mgr: OrderManager, sample_request: OrderRequest,
                                     tmp_path: Path):
        # Execute an order
        intent_id = mgr.create_order_intent(sample_request)
        mgr.execute_intent(intent_id, sample_request)

        # Create a new manager pointing to the same DB to simulate restart
        db_path = mgr.PERSISTENCE_PATH
        mgr2 = OrderManager(persistence_path=db_path)

        # Should have recovered the in-flight order
        assert intent_id in mgr2._orders
        assert mgr2._orders[intent_id].broker_order_id == "BROKER-001"

    def test_does_not_load_terminal_orders(self, mgr: OrderManager, sample_request: OrderRequest,
                                            tmp_path: Path):
        intent_id = mgr.create_order_intent(sample_request)
        mgr.execute_intent(intent_id, sample_request)

        # Mark as FILLED (terminal)
        mgr.update_order_status("BROKER-001", OrderStatus.FILLED, filled_qty=50, avg_price=150.0)

        # Simulate restart
        db_path = mgr.PERSISTENCE_PATH
        mgr2 = OrderManager(persistence_path=db_path)

        # FILLED orders should NOT be loaded (they're terminal)
        assert intent_id not in mgr2._orders

    def test_creates_broker_mapping_on_recovery(self, mgr: OrderManager, sample_request: OrderRequest,
                                                 tmp_path: Path):
        intent_id = mgr.create_order_intent(sample_request)
        mgr.execute_intent(intent_id, sample_request)

        db_path = mgr.PERSISTENCE_PATH
        mgr2 = OrderManager(persistence_path=db_path)

        assert "BROKER-001" in mgr2._broker_map
        assert mgr2._broker_map["BROKER-001"] == intent_id

    def test_empty_db_no_error(self, tmp_path: Path):
        # Should not raise when loading from empty DB
        db_path = str(tmp_path / "empty.db")
        mgr = OrderManager(persistence_path=db_path)
        assert mgr._orders == {}


# ═══════════════════════════════════════════════════════════════════════════════
#  Schema Migration
# ═══════════════════════════════════════════════════════════════════════════════


class TestSchemaMigration:
    def test_migration_from_old_pk(self, tmp_path: Path, sample_request: OrderRequest):
        """Simulate old schema where broker_order_id is PK, verify migration to intent_id PK."""
        db_path = str(tmp_path / "migrate.db")

        # Create old-style table directly via raw sqlite3
        import sqlite3
        conn = sqlite3.connect(db_path)
        conn.executescript("""
            CREATE TABLE orders (
                broker_order_id TEXT PRIMARY KEY,
                intent_id TEXT,
                request_json TEXT,
                status TEXT,
                filled_qty INTEGER,
                avg_price REAL,
                created_at TEXT,
                updated_at TEXT,
                error_text TEXT
            );
            INSERT INTO orders (broker_order_id, intent_id, request_json, status)
            VALUES ('OLD-001', 'intent-old', '{"symbol": "TEST"}', 'ACKNOWLEDGED');
        """)
        conn.commit()
        conn.close()

        # Initialize OrderManager - should detect old schema and migrate
        mgr = OrderManager(persistence_path=db_path)

        # Verify data was migrated
        assert "intent-old" in mgr._orders
        assert mgr._orders["intent-old"].broker_order_id == "OLD-001"

    def test_repeated_migration_idempotent(self, tmp_path: Path):
        """Running init twice should not cause errors."""
        db_path = str(tmp_path / "dup_migrate.db")

        mgr1 = OrderManager(persistence_path=db_path)
        mgr2 = OrderManager(persistence_path=db_path)

        assert mgr2._orders == {}


# ═══════════════════════════════════════════════════════════════════════════════
#  Thread Safety
# ═══════════════════════════════════════════════════════════════════════════════


class TestThreadSafety:
    def test_concurrent_execute(self, mgr: OrderManager, sample_request: OrderRequest,
                                 mock_broker_gateway: MagicMock):
        """Multiple concurrent execute_intent calls should be safe."""
        errors = []

        def _execute(i: int):
            try:
                intent_id = mgr.create_order_intent(sample_request)
                mgr.execute_intent(intent_id, sample_request)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=_execute, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert len(mgr._orders) == 20

    def test_concurrent_update_status(self, mgr: OrderManager, sample_request: OrderRequest):
        """Concurrent status updates should not corrupt state."""
        intent_id = mgr.create_order_intent(sample_request)
        mgr.execute_intent(intent_id, sample_request)
        errors = []

        def _update():
            try:
                mgr.update_order_status("BROKER-001", OrderStatus.FILLED, filled_qty=50, avg_price=150.0)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=_update) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert mgr._orders[intent_id].status == OrderStatus.FILLED

    def test_concurrent_get_and_update(self, mgr: OrderManager, sample_request: OrderRequest):
        """Concurrent reads and writes should be safe."""
        intent_id = mgr.create_order_intent(sample_request)
        mgr.execute_intent(intent_id, sample_request)
        errors = []
        lock = threading.Lock()

        def _get():
            try:
                for _ in range(20):
                    mgr.get_order_response("BROKER-001")
            except Exception as e:
                with lock:
                    errors.append(e)

        def _update():
            try:
                for i in range(10):
                    mgr.update_order_status("BROKER-001", OrderStatus.PARTIAL_FILL,
                                            filled_qty=10 + i, avg_price=150.0)
            except Exception as e:
                with lock:
                    errors.append(e)

        threads = [threading.Thread(target=_get) for _ in range(5)]
        threads += [threading.Thread(target=_update) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
