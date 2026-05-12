import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Optional, List
from core.adapters.base_adapter import OrderRequest, OrderResponse, OrderStatus
from core.execution.broker_gateway import broker_gateway
from core.time_provider import time_provider
from core.state_manager import state_manager

log = logging.getLogger("order_manager")

@dataclass
class OrderState:
    """Tracks the full lifecycle of a single order."""
    intent_id: str           # Unique ID for the trade intent (prevents duplicates)
    request: OrderRequest
    status: OrderStatus
    broker_order_id: Optional[str] = None
    filled_qty: int = 0
    avg_price: float = 0.0
    created_at: str = field(default_factory=lambda: time_provider.format_ts())
    updated_at: str = field(default_factory=lambda: time_provider.format_ts())
    error: Optional[str] = None

class OrderManager:
    """
    Deterministic Order Lifecycle Manager.
    Ensures orders follow a strict state transition:
    NEW -> VALIDATED -> SUBMITTED -> ACKNOWLEDGED -> FILLED
    """
    
    def __init__(self):
        self._orders: Dict[str, OrderState] = {} # broker_order_id -> OrderState
        self._intent_map: Dict[str, str] = {}    # intent_id -> broker_order_id
        self._lock = any # Simplified for this implementation, would use threading.Lock in prod

    def _validate_transition(self, current: OrderStatus, next_status: OrderStatus) -> bool:
        """Enforces the deterministic state machine."""
        transitions = {
            OrderStatus.NEW: [OrderStatus.VALIDATED, OrderStatus.FAILED],
            OrderStatus.VALIDATED: [OrderStatus.SUBMITTED, OrderStatus.FAILED],
            OrderStatus.SUBMITTED: [OrderStatus.ACKNOWLEDGED, OrderStatus.REJECTED, OrderStatus.FAILED],
            OrderStatus.ACKNOWLEDGED: [OrderStatus.PARTIAL_FILL, OrderStatus.FILLED, OrderStatus.CANCEL_PENDING, OrderStatus.FAILED],
            OrderStatus.PARTIAL_FILL: [OrderStatus.PARTIAL_FILL, OrderStatus.FILLED, OrderStatus.CANCEL_PENDING, OrderStatus.FAILED],
            OrderStatus.CANCEL_PENDING: [OrderStatus.CANCELLED, OrderStatus.FILLED, OrderStatus.FAILED],
        }
        return next_status in transitions.get(current, [])

    def create_order_intent(self, request: OrderRequest) -> str:
        """Generates a unique intent ID to prevent duplicate execution."""
        intent_id = str(uuid.uuid4())
        # In a real system, we would persist this intent to the StateManager immediately
        return intent_id

    def execute_intent(self, intent_id: str, request: OrderRequest) -> OrderResponse:
        """
        The primary entry point for order execution.
        Implements idempotency: if intent_id already exists, it returns the existing order.
        """
        if intent_id in self._intent_map:
            log.warning(f"Duplicate intent detected: {intent_id}. Returning existing order.")
            return self.get_order_response(self._intent_map[intent_id])

        # 1. NEW -> VALIDATED
        order = OrderState(intent_id=intent_id, request=request, status=OrderStatus.VALIDATED)
        
        # 2. VALIDATED -> SUBMITTED
        order.status = OrderStatus.SUBMITTED
        
        # 3. Call Broker Gateway
        response = broker_gateway.place_order(request)
        
        if response.status == OrderStatus.FAILED:
            order.status = OrderStatus.FAILED
            order.error = response.error
        else:
            # 4. SUBMITTED -> ACKNOWLEDGED
            order.broker_order_id = response.order_id
            order.status = response.status
            order.filled_qty = response.filled_qty
            order.avg_price = response.avg_price
            
            self._orders[response.order_id] = order
            self._intent_map[intent_id] = response.order_id

        order.updated_at = time_provider.format_ts()
        return response

    def update_order_status(self, broker_order_id: str, new_status: OrderStatus, 
                            filled_qty: int = 0, avg_price: float = 0.0):
        """Updates order state while enforcing transition rules."""
        if broker_order_id not in self._orders:
            log.error(f"Order {broker_order_id} not found in manager.")
            return

        order = self._orders[broker_order_id]
        if not self._validate_transition(order.status, new_status):
            log.error(f"Invalid transition: {order.status} -> {new_status} for {broker_order_id}")
            return

        order.status = new_status
        order.filled_qty = filled_qty
        order.avg_price = avg_price
        order.updated_at = time_provider.format_ts()

    def get_order_response(self, broker_order_id: str) -> OrderResponse:
        """Converts internal OrderState back to a Broker OrderResponse."""
        order = self._orders.get(broker_order_id)
        if not order:
            return OrderResponse(order_id="NOT_FOUND", status=OrderStatus.FAILED, error="Order not found")
        
        return OrderResponse(
            order_id=order.broker_order_id,
            status=order.status,
            filled_qty=order.filled_qty,
            avg_price=order.avg_price,
            error=order.error
        )

# Singleton instance
order_manager = OrderManager()
