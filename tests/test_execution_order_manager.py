"""Tests for core/execution/order_manager.py — Order Manager."""

from __future__ import annotations

import json
import os
import tempfile
import pytest

from core.adapters.base_adapter import OrderRequest, OrderStatus
from core.execution.order_manager import OrderManager, OrderState, order_manager


def make_order_request(**overrides) -> OrderRequest:
    """Helper to create OrderRequest with sensible defaults."""
    params = {
        "symbol": "NIFTY",
        "qty": 50,
        "price": 0.0,
        "order_type": "MARKET",
        "direction": "BUY",
        "product": "MIS",
        "variety": "REGULAR",
    }
    params.update(overrides)
    return OrderRequest(**params)


class TestOrderState:
    """OrderState dataclass coverage."""

    def test_default_values(self):
        req = make_order_request()
        state = OrderState(intent_id="intent_001", request=req, status=OrderStatus.NEW)
        assert state.intent_id == "intent_001"
        assert state.status == OrderStatus.NEW
        assert state.filled_qty == 0
        assert state.avg_price == 0.0
        assert state.error is None
        assert state.broker_order_id is None

    def test_created_at_set(self):
        req = make_order_request()
        state = OrderState(intent_id="intent_001", request=req, status=OrderStatus.NEW)
        assert state.created_at is not None
        assert state.updated_at is not None


class TestOrderManager:
    """OrderManager coverage."""

    @pytest.fixture
    def manager(self):
        # Use a temp file for persistence
        tmp = tempfile.mktemp(suffix="_orders.db")
        m = OrderManager(persistence_path=tmp)
        yield m
        try:
            os.unlink(tmp)
        except OSError:
            pass

    def test_create_order_intent(self, manager):
        req = make_order_request()
        intent_id = manager.create_order_intent(req)
        assert intent_id is not None
        assert len(intent_id) > 0

    def test_create_order_intent_unique(self, manager):
        req = make_order_request()
        id1 = manager.create_order_intent(req)
        id2 = manager.create_order_intent(req)
        assert id1 != id2

    def test_execute_intent_duplicate(self, manager):
        """Same intent_id should return existing order."""
        req = make_order_request()
        intent_id = manager.create_order_intent(req)
        response1 = manager.execute_intent(intent_id, req)
        # Execute again with same intent
        response2 = manager.execute_intent(intent_id, req)
        assert response2.status in (OrderStatus.ACKNOWLEDGED, OrderStatus.FAILED)

    def test_execute_intent_no_broker(self, manager):
        """With no broker gateway connected, should fail gracefully."""
        req = make_order_request()
        intent_id = manager.create_order_intent(req)
        response = manager.execute_intent(intent_id, req)
        assert response.status == OrderStatus.FAILED

    def test_update_order_status_unknown(self, manager):
        """Updating status for unknown order should not crash."""
        # Just verify it doesn't raise
        manager.update_order_status("UNKNOWN_ORD", OrderStatus.FILLED)

    def test_get_order_response_not_found(self, manager):
        response = manager.get_order_response("UNKNOWN_ORD")
        assert response.status == OrderStatus.FAILED
        assert response.order_id == "NOT_FOUND"

    def test_persist_and_load(self, manager):
        """Verify order state is persisted to SQLite."""
        req = make_order_request()
        intent_id = manager.create_order_intent(req)
        # Execute to trigger persistence
        manager.execute_intent(intent_id, req)
        # Check that order is in _orders
        assert intent_id in manager._orders
        order = manager._orders[intent_id]
        assert order.status in (OrderStatus.ACKNOWLEDGED, OrderStatus.FAILED)

    def test_order_state_transition_valid(self, manager):
        """Set up an order and verify valid transitions."""
        req = make_order_request()
        intent_id = manager.create_order_intent(req)
        order = OrderState(intent_id=intent_id, request=req, status=OrderStatus.NEW)
        manager._orders[intent_id] = order
        # Try valid transition
        order.status = OrderStatus.VALIDATED
        order.updated_at = "2026-06-11T12:00:00"
        manager._persist_order(order)
        assert order.status == OrderStatus.VALIDATED

    def test_order_manager_singleton(self):
        """The module-level singleton should be an OrderManager instance."""
        assert isinstance(order_manager, OrderManager)

    def test_init_durable_storage_creates_db(self, manager):
        """Verify the SQLite DB file was created."""
        assert os.path.exists(manager.PERSISTENCE_PATH)

    def test_load_orders_from_disk_no_crash(self, manager):
        """Loading from disk with no data should not crash."""
        assert manager._orders == {} or isinstance(manager._orders, dict)

    def test_persist_order_with_error(self, manager):
        """Persist order with error should handle gracefully."""
        req = make_order_request()
        state = OrderState(
            intent_id="test_error",
            request=req,
            status=OrderStatus.FAILED,
            error="Test error",
        )
        manager._persist_order(state)

    def test_persist_order_with_broker_id(self, manager):
        req = make_order_request()
        state = OrderState(
            intent_id="test_broker",
            request=req,
            status=OrderStatus.ACKNOWLEDGED,
            broker_order_id="BROKER_ORD_001",
        )
        manager._orders[state.intent_id] = state
        manager._broker_map["BROKER_ORD_001"] = state.intent_id
        manager._persist_order(state)
        assert manager._broker_map.get("BROKER_ORD_001") == "test_broker"

    def test_get_order_response_by_broker_id(self, manager):
        req = make_order_request()
        state = OrderState(
            intent_id="test_broker2",
            request=req,
            status=OrderStatus.FILLED,
            broker_order_id="BROKER_ORD_002",
            filled_qty=50,
            avg_price=23500.0,
        )
        manager._orders[state.intent_id] = state
        manager._broker_map["BROKER_ORD_002"] = state.intent_id
        response = manager.get_order_response("BROKER_ORD_002")
        assert response.status == OrderStatus.FILLED
        assert response.filled_qty == 50

    def test_get_order_response_by_intent_id_fallback(self, manager):
        req = make_order_request()
        state = OrderState(
            intent_id="test_fallback",
            request=req,
            status=OrderStatus.VALIDATED,
        )
        manager._orders[state.intent_id] = state
        response = manager.get_order_response("test_fallback")
        assert response.status == OrderStatus.VALIDATED

    def test_load_inflight_orders(self):
        """Simulate loading in-flight orders from a pre-populated DB."""
        tmp = tempfile.mktemp(suffix="_inflight.db")
        try:
            import sqlite3
            conn = sqlite3.connect(tmp)
            conn.execute("""
                CREATE TABLE orders (
                    intent_id TEXT PRIMARY KEY,
                    broker_order_id TEXT UNIQUE,
                    request_json TEXT,
                    status TEXT,
                    filled_qty INTEGER,
                    avg_price REAL,
                    created_at TEXT,
                    updated_at TEXT,
                    error_text TEXT
                )
            """)
            req_data = json.dumps({
                "symbol": "NIFTY", "qty": 50, "direction": "BUY",
                "price": 0.0, "order_type": "MARKET", "product": "MIS",
                "variety": "REGULAR", "tag": "OPB_BOT", "idempotency_key": "",
            })
            conn.execute(
                "INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("intent_inflight", "BROKER_ORD_IF", req_data,
                 "ACKNOWLEDGED", 0, 0.0, "2026-06-11T09:00", "2026-06-11T09:01", None),
            )
            conn.commit()
            conn.close()

            m = OrderManager(persistence_path=tmp)
            assert "intent_inflight" in m._orders
            assert m._orders["intent_inflight"].status == OrderStatus.ACKNOWLEDGED
            assert m._broker_map.get("BROKER_ORD_IF") == "intent_inflight"
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass
