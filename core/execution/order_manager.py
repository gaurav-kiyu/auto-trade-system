import json
import logging
import sqlite3
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from core.adapters.base_adapter import OrderRequest, OrderResponse, OrderStatus
from core.execution.broker_gateway import broker_gateway
from core.time_provider import time_provider

log = logging.getLogger("order_manager")

@dataclass
class OrderState:
    """Tracks the full lifecycle of a single order."""
    intent_id: str           # Unique ID for the trade intent (prevents duplicates)
    request: OrderRequest
    status: OrderStatus
    broker_order_id: str | None = None
    filled_qty: int = 0
    avg_price: float = 0.0
    created_at: str = field(default_factory=lambda: time_provider.format_ts())
    updated_at: str = field(default_factory=lambda: time_provider.format_ts())
    error: str | None = None

class OrderManager:
    """
    Deterministic Order Lifecycle Manager with Durable Persistence.

    Ensures orders follow a strict state transition:
    NEW -> VALIDATED -> SUBMITTED -> ACKNOWLEDGED -> FILLED

    Phase 0 Fix: Orders are persisted to SQLite for crash recovery.
    """
    PERSISTENCE_PATH = "order_state.db"

    def __init__(self, persistence_path: str | Path | None = None):
        self._orders: dict[str, OrderState] = {}  # intent_id -> OrderState
        self._broker_map: dict[str, str] = {}     # broker_order_id -> intent_id
        self._intent_map: dict[str, str] = {}     # intent_id -> broker_order_id
        self._intent_events: dict[str, threading.Event] = {}
        self._lock = __import__('threading').Lock()
        if persistence_path:
            self.PERSISTENCE_PATH = str(persistence_path)
        self._init_durable_storage()
        self._load_orders_from_disk()  # Recover in-flight orders on restart

    def _init_durable_storage(self) -> None:
        """Initialize SQLite persistence for orders (Phase 0 fix)."""
        try:
            with sqlite3.connect(self.PERSISTENCE_PATH, timeout=10) as conn:
                table_info = list(conn.execute("PRAGMA table_info(orders)"))
                if table_info:
                    broker_pk = next((row for row in table_info if row[1] == "broker_order_id"), None)
                    intent_pk = next((row for row in table_info if row[1] == "intent_id"), None)
                    if broker_pk and broker_pk[5] == 1 and (not intent_pk or intent_pk[5] != 1):
                        conn.execute("""
                            CREATE TABLE IF NOT EXISTS orders_new (
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
                        conn.execute("""
                            INSERT OR REPLACE INTO orders_new
                            (intent_id, broker_order_id, request_json, status, filled_qty, avg_price, created_at, updated_at, error_text)
                            SELECT intent_id, broker_order_id, request_json, status, filled_qty, avg_price, created_at, updated_at, error_text
                            FROM orders
                        """)
                        conn.execute("DROP TABLE orders")
                        conn.execute("ALTER TABLE orders_new RENAME TO orders")
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS orders (
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
                conn.execute("CREATE INDEX IF NOT EXISTS idx_intent ON orders(intent_id)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_broker_order_id ON orders(broker_order_id)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_status ON orders(status)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_updated_at ON orders(updated_at)")
                conn.commit()
            log.info("OrderManager: Durable storage initialized")
        except Exception as e:
            log.error(f"OrderManager: Failed to init durable storage: {e}")

    def _persist_order(self, order: OrderState) -> None:
        """Persist order state to SQLite."""
        try:
            req_json = json.dumps({
                "symbol": order.request.symbol,
                "qty": order.request.qty,
                "direction": order.request.direction,
                "price": order.request.price,
                "order_type": order.request.order_type,
                "product": order.request.product,
                "variety": order.request.variety,
                "tag": order.request.tag,
                "idempotency_key": order.request.idempotency_key,
            }, default=str)
            with sqlite3.connect(self.PERSISTENCE_PATH, timeout=10) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO orders
                    (intent_id, broker_order_id, request_json, status, filled_qty, avg_price, created_at, updated_at, error_text)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    order.intent_id,
                    order.broker_order_id,
                    req_json,
                    order.status.name,
                    order.filled_qty,
                    order.avg_price,
                    order.created_at,
                    order.updated_at,
                    order.error,
                ))
                conn.commit()
        except Exception as e:
            log.warning(f"OrderManager: Failed to persist order: {e}")

    def _load_orders_from_disk(self) -> None:
        """Load in-flight orders from disk on startup."""
        try:
            with sqlite3.connect(self.PERSISTENCE_PATH, timeout=10) as conn:
                cursor = conn.execute("""
                    SELECT broker_order_id, intent_id, request_json, status, filled_qty, avg_price, created_at, updated_at, error_text
                    FROM orders
                    WHERE status NOT IN ('FILLED', 'REJECTED', 'CANCELLED', 'FAILED')
                """)
                for row in cursor:
                    broker_order_id, intent_id, request_json, status, filled_qty, avg_price, created_at, updated_at, error_text = row
                    try:
                        request_data = json.loads(request_json or "{}")
                    except Exception:
                        request_data = {}

                    request = OrderRequest(
                        symbol=request_data.get("symbol", ""),
                        qty=int(request_data.get("qty", 0)),
                        price=float(request_data.get("price", 0.0)),
                        order_type=request_data.get("order_type", "MARKET"),
                        direction=request_data.get("direction", "BUY"),
                        product=request_data.get("product", "MIS"),
                        variety=request_data.get("variety", "REGULAR"),
                        tag=request_data.get("tag", "OPB_BOT"),
                        idempotency_key=request_data.get("idempotency_key", ""),
                    )
                    status_obj = OrderStatus.UNKNOWN
                    if isinstance(status, str) and status in OrderStatus.__members__:
                        status_obj = OrderStatus[status]
                    order = OrderState(
                        intent_id=intent_id or str(uuid.uuid4()),
                        request=request,
                        status=status_obj,
                        broker_order_id=broker_order_id,
                        filled_qty=int(filled_qty or 0),
                        avg_price=float(avg_price or 0.0),
                        created_at=created_at,
                        updated_at=updated_at,
                        error=error_text,
                    )
                    self._orders[order.intent_id] = order
                    if broker_order_id:
                        self._broker_map[broker_order_id] = order.intent_id
                    if order.intent_id:
                        self._intent_map[order.intent_id] = broker_order_id or ""
                    log.warning(f"OrderManager: Loaded in-flight order {order.intent_id} from previous session (broker_order_id={broker_order_id})")
        except Exception as e:
            log.warning(f"OrderManager: Failed to load orders: {e}")

    def _validate_transition(self, current: OrderStatus, next_status: OrderStatus) -> bool:
        """Enforces the deterministic state machine."""
        transitions = {
            OrderStatus.NEW: [OrderStatus.VALIDATED, OrderStatus.FAILED],
            OrderStatus.VALIDATED: [OrderStatus.SUBMITTED, OrderStatus.ACKNOWLEDGED, OrderStatus.FAILED],
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
        Implements 3-phase submit to prevent orphan orders:
        Phase 1: PRE_SUBMIT (intent created, NOT sent to broker yet)
        Phase 2: Wait for broker ACK with timeout
        Phase 3: CONFIRMED (broker acknowledged) or query for order status

        Implements idempotency: if intent_id already exists, it returns the existing order.
        """
        event: threading.Event | None = None
        with self._lock:
            if intent_id in self._orders:
                log.warning(f"Duplicate intent detected: {intent_id}. Returning existing order.")
                broker_id = self._intent_map.get(intent_id)
                event = self._intent_events.get(intent_id)
                if broker_id:
                    return self.get_order_response(broker_id)
                if not event:
                    existing_order = self._orders[intent_id]
                    return OrderResponse(
                        order_id=existing_order.broker_order_id or "",
                        status=existing_order.status,
                        filled_qty=existing_order.filled_qty,
                        avg_price=existing_order.avg_price,
                        error=existing_order.error,
                    )

        if event:
            event.wait(timeout=20)
            with self._lock:
                broker_id = self._intent_map.get(intent_id)
                if broker_id:
                    return self.get_order_response(broker_id)
                existing_order = self._orders[intent_id]
                return OrderResponse(
                    order_id=existing_order.broker_order_id or "",
                    status=existing_order.status,
                    filled_qty=existing_order.filled_qty,
                    avg_price=existing_order.avg_price,
                    error=existing_order.error,
                )

        # Phase 1: PRE_SUBMIT — create intent, stay in VALIDATED until broker confirms
        order = OrderState(intent_id=intent_id, request=request, status=OrderStatus.VALIDATED)
        self._orders[intent_id] = order
        self._intent_events[intent_id] = threading.Event()
        self._intent_map[intent_id] = ""
        self._persist_order(order)

        # Phase 2: Call Broker Gateway — order is still VALIDATED, NOT SUBMITTED
        # If broker receives order but connection drops, we stay in VALIDATED
        # and startup reconciliation will query broker for status
        response = broker_gateway.place_order(request)

        if response.status == OrderStatus.FAILED:
            # Broker explicitly rejected or connection failed before broker received
            order.status = OrderStatus.FAILED
            order.error = response.error
            order.updated_at = time_provider.format_ts()
            self._persist_order(order)
            event = self._intent_events.get(intent_id)
            if event:
                event.set()
            return response

        # Phase 3: CONFIRMED — broker returned a valid order_id
        # Now safely transition to ACKNOWLEDGED (not SUBMITTED — we have confirmation)
        order.broker_order_id = response.order_id
        order.status = OrderStatus.ACKNOWLEDGED
        order.filled_qty = response.filled_qty
        order.avg_price = response.avg_price
        order.updated_at = time_provider.format_ts()

        with self._lock:
            if response.order_id:
                self._broker_map[response.order_id] = intent_id
                self._intent_map[intent_id] = response.order_id
            self._persist_order(order)
            event = self._intent_events.get(intent_id)
            if event:
                event.set()

        log.info(f"Order {response.order_id}: VALIDATED -> ACKNOWLEDGED (3-phase submit)")
        return response

    def update_order_status(self, broker_order_id: str, new_status: OrderStatus,
                            filled_qty: int = 0, avg_price: float = 0.0):
        """Updates order state while enforcing transition rules."""
        intent_id = self._broker_map.get(broker_order_id)
        if not intent_id or intent_id not in self._orders:
            log.error(f"Order {broker_order_id} not found in manager.")
            return

        order = self._orders[intent_id]
        if not self._validate_transition(order.status, new_status):
            log.error(f"Invalid transition: {order.status} -> {new_status} for {broker_order_id}")
            return

        with self._lock:
            order.status = new_status
            order.filled_qty = filled_qty
            order.avg_price = avg_price
            order.updated_at = time_provider.format_ts()
            self._persist_order(order)

    def get_order_response(self, broker_order_id: str) -> OrderResponse:
        """Converts internal OrderState back to a Broker OrderResponse."""
        intent_id = self._broker_map.get(broker_order_id)
        if intent_id and intent_id in self._orders:
            order = self._orders[intent_id]
        else:
            # Fall back to treat the input as an intent_id if no broker mapping exists
            order = self._orders.get(broker_order_id)

        if not order:
            return OrderResponse(order_id="NOT_FOUND", status=OrderStatus.FAILED, error="Order not found")

        return OrderResponse(
            order_id=order.broker_order_id or broker_order_id,
            status=order.status,
            filled_qty=order.filled_qty,
            avg_price=order.avg_price,
            error=order.error
        )

# Singleton instance
order_manager = OrderManager()
