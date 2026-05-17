from __future__ import annotations

import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pytest

from core.adapters.base_adapter import OrderRequest, OrderResponse, OrderStatus
from core.execution.order_manager import OrderManager


class MockBrokerGateway:
    def __init__(self, latency_ms: int = 0):
        self._latency_ms = latency_ms
        self._order_count = 0
        self._lock = threading.Lock()

    @property
    def placed_orders(self) -> int:
        return self._order_count

    def place_order(self, request: OrderRequest) -> OrderResponse:
        time.sleep(self._latency_ms / 1000.0)
        with self._lock:
            self._order_count += 1
            order_id = f"MOCK_{self._order_count}_{int(time.time() * 1000)}"

        return OrderResponse(
            order_id=order_id,
            status=OrderStatus.ACKNOWLEDGED,
            filled_qty=request.qty,
            avg_price=100.0,
            error=None,
        )


def make_order_request(symbol: str = "NIFTY", qty: int = 1, price: float = 100.0) -> OrderRequest:
    return OrderRequest(
        symbol=symbol,
        qty=qty,
        price=price,
        order_type="MARKET",
        direction="BUY",
        product="MIS",
        variety="REGULAR",
        tag="OPB_BOT",
        idempotency_key=str(uuid.uuid4()),
    )


def test_concurrent_order_intents(tmp_path):
    manager = OrderManager(persistence_path=tmp_path / "order_state.db")
    gateway = MockBrokerGateway(latency_ms=5)

    with patch("core.execution.order_manager.broker_gateway", gateway):
        intent_ids = [str(uuid.uuid4()) for _ in range(50)]
        requests = [make_order_request(price=100.0 + i) for i in range(50)]

        with ThreadPoolExecutor(max_workers=20) as executor:
            futures = [
                executor.submit(manager.execute_intent, intent_id, request)
                for intent_id, request in zip(intent_ids, requests)
            ]
            responses = [future.result(timeout=10) for future in futures]

    assert len(responses) == 50
    assert all(resp.status == OrderStatus.ACKNOWLEDGED for resp in responses)
    assert len({resp.order_id for resp in responses}) == 50
    assert gateway.placed_orders == 50

    recovered_manager = OrderManager(persistence_path=tmp_path / "order_state.db")
    assert len(recovered_manager._orders) == 50
    assert all(
        response.order_id == recovered_manager._orders[intent_id].broker_order_id
        for intent_id, response in zip(intent_ids, responses)
    )


def test_duplicate_intent_prevention(tmp_path):
    manager = OrderManager(persistence_path=tmp_path / "order_state.db")
    gateway = MockBrokerGateway(latency_ms=5)

    with patch("core.execution.order_manager.broker_gateway", gateway):
        intent_id = str(uuid.uuid4())
        request = make_order_request()

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(manager.execute_intent, intent_id, request) for _ in range(10)]
            responses = [future.result(timeout=10) for future in futures]

    assert len(responses) == 10
    assert len({resp.order_id for resp in responses}) == 1
    assert gateway.placed_orders == 1
    assert all(resp.status == OrderStatus.ACKNOWLEDGED for resp in responses)


def test_inflight_orders_are_recovered(tmp_path):
    gateway = MockBrokerGateway(latency_ms=0)
    intent_id = str(uuid.uuid4())
    request = make_order_request()

    with patch("core.execution.order_manager.broker_gateway", gateway):
        manager = OrderManager(persistence_path=tmp_path / "order_state.db")
        response = manager.execute_intent(intent_id, request)

    assert response.status == OrderStatus.ACKNOWLEDGED
    assert response.order_id != ""
    assert gateway.placed_orders == 1

    recovered = OrderManager(persistence_path=tmp_path / "order_state.db")
    assert intent_id in recovered._orders
    recovered_order = recovered._orders[intent_id]
    assert recovered_order.status == OrderStatus.ACKNOWLEDGED
    assert recovered_order.broker_order_id == response.order_id
    assert recovered._broker_map[response.order_id] == intent_id
