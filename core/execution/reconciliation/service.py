"""
Execution Reconciliation Service (v2.46).

Implements true broker-vs-internal state reconciliation to detect:
- Orphan positions (positions in broker but not in internal state)
- Stale orders (orders in internal state but not in broker)
- Quantity mismatches
- Unrecorded fills
- Ambiguous state requiring trading freeze

This module replaces the placeholder "In a real implementation" logic in execution_service.py.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from core.datetime_ist import now_ist
from core.exceptions import BrokerConnectionError, DatabaseError, ReconciliationError

log = logging.getLogger(__name__)


class ReconciliationState(Enum):
    """Possible states of reconciliation."""
    CLEAN = "CLEAN"
    ORPHAN_POSITION = "ORPHAN_POSITION"
    STALE_ORDER = "STALE_ORDER"
    QUANTITY_MISMATCH = "QUANTITY_MISMATCH"
    UNRECORDED_FILL = "UNRECORDED_FILL"
    AMBIGUOUS = "AMBIGUOUS"


class TradingFreezeReason(Enum):
    """Reasons for freezing trading."""
    RECONCILIATION_FAILED = "RECONCILIATION_FAILED"
    ORPHAN_POSITIONS_DETECTED = "ORPHAN_POSITIONS_DETECTED"
    STALE_ORDERS_UNRESOLVED = "STALE_ORDERS_UNRESOLVED"
    QUANTITY_MISMATCH_UNRESOLVED = "QUANTITY_MISMATCH_UNRESOLVED"
    BROKER_UNAVAILABLE = "BROKER_UNAVAILABLE"


@dataclass
class ReconciliationIssue:
    """Single reconciliation issue."""
    issue_type: ReconciliationState
    order_id: str | None
    internal_value: Any
    broker_value: Any
    description: str
timestamp: datetime = field(default_factory=now_ist)


@dataclass
class ReconciliationResult:
    """Result of reconciliation run."""
    is_clean: bool
    issues: list[ReconciliationIssue]
    freeze_reason: TradingFreezeReason | None
    timestamp: datetime = field(default_factory=now_ist)
    broker_positions_count: int = 0
    internal_orders_count: int = 0
    repaired_count: int = 0


class ReconciliationService:
    """
    Reconciles internal order state with broker orders and positions.

    Critical: On ambiguity, freezes trading to prevent double-execution or
    position divergence.
    """

    def __init__(
        self,
        db_path: str = "trades.db",
        freeze_callback: Callable[[TradingFreezeReason, str], None] | None = None,
        enable_auto_repair: bool = True,
    ):
        self._db_path = db_path
        self._freeze_callback = freeze_callback
        self._enable_auto_repair = enable_auto_repair
        self._lock = threading.Lock()
        self._is_frozen = False
        self._freeze_reason: TradingFreezeReason | None = None
        self._last_reconciliation: ReconciliationResult | None = None
        self._init_orders_table()

    def _init_orders_table(self):
        """Initialize orders tracking table if not exists."""
        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA busy_timeout=5000")
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS execution_orders (
                        order_id TEXT PRIMARY KEY,
                        intent_id TEXT,
                        symbol TEXT NOT NULL,
                        direction TEXT NOT NULL,
                        quantity INTEGER NOT NULL,
                        filled_quantity INTEGER DEFAULT 0,
                        average_price REAL DEFAULT 0.0,
                        status TEXT NOT NULL,
                        broker_order_id TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        idempotency_key TEXT,
                        is_reconciled INTEGER DEFAULT 0,
                        notes TEXT
                    )
                """)
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_orders_status
                    ON execution_orders(status)
                """)
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_orders_reconciled
                    ON execution_orders(is_reconciled)
                """)
                conn.commit()
                log.info("Execution orders table initialized")
        except (DatabaseError, sqlite3.Error, OSError) as e:
            log.error(f"Failed to initialize orders table: {e}")
            raise

    def is_frozen(self) -> tuple[bool, TradingFreezeReason | None]:
        """Check if trading is frozen and why."""
        with self._lock:
            return self._is_frozen, self._freeze_reason

    def unfreeze(self):
        """Manually unfreeze trading after issue resolution."""
        with self._lock:
            self._is_frozen = False
            self._freeze_reason = None
            log.warning("Trading manually unfrozen")

    def _freeze_trading(self, reason: TradingFreezeReason, details: str):
        """Freeze trading due to reconciliation failure."""
        with self._lock:
            self._is_frozen = True
            self._freeze_reason = reason
            log.critical(f"TRADING FROZEN: {reason.value} - {details}")
            if self._freeze_callback:
                try:
                    self._freeze_callback(reason, details)
                except (ValueError, TypeError, AttributeError, DatabaseError) as e:
                    log.error(f"Freeze callback failed: {e}")

    def record_order(
        self,
        order_id: str,
        intent_id: str,
        symbol: str,
        direction: str,
        quantity: int,
        status: str,
        broker_order_id: str | None = None,
        idempotency_key: str | None = None,
    ):
        """Record a new order in internal state."""
        now = now_ist().isoformat()
        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO execution_orders
                    (order_id, intent_id, symbol, direction, quantity, filled_quantity,
                     average_price, status, broker_order_id, created_at, updated_at,
                     idempotency_key, is_reconciled)
                    VALUES (?, ?, ?, ?, ?, 0, 0.0, ?, ?, ?, ?, ?, 0)
                """, (order_id, intent_id, symbol, direction, quantity, status,
                      broker_order_id, now, now, idempotency_key))
                conn.commit()
        except (DatabaseError, sqlite3.Error, OSError, ValueError) as e:
            log.error(f"Failed to record order {order_id}: {e}")

    def update_order_fill(
        self,
        order_id: str,
        filled_quantity: int,
        average_price: float,
        status: str,
    ):
        """Update order fill information."""
        now = now_ist().isoformat()
        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.execute("""
                    UPDATE execution_orders
                    SET filled_quantity = ?, average_price = ?,
                        status = ?, updated_at = ?, is_reconciled = 0
                    WHERE order_id = ?
                """, (filled_quantity, average_price, status, now, order_id))
                conn.commit()
        except (DatabaseError, sqlite3.Error, OSError, ValueError) as e:
            log.error(f"Failed to update order fill {order_id}: {e}")

    def get_pending_orders(self) -> list[dict]:
        """Get all orders that are not in terminal state."""
        terminal_states = {"FILLED", "CANCELLED", "REJECTED", "EXPIRED", "COMPLETE"}
        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute("""
                    SELECT * FROM execution_orders
                    WHERE status NOT IN (?, ?, ?, ?, ?)
                    ORDER BY created_at
                """, tuple(terminal_states))
                return [dict(row) for row in cursor.fetchall()]
        except (DatabaseError, sqlite3.Error, OSError) as e:
            log.error(f"Failed to get pending orders: {e}")
            return []

    def get_all_orders(self) -> list[dict]:
        """Get all orders from internal state."""
        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute("SELECT * FROM execution_orders ORDER BY created_at")
                return [dict(row) for row in cursor.fetchall()]
        except (DatabaseError, sqlite3.Error, OSError) as e:
            log.error(f"Failed to get all orders: {e}")
            return []

    def reconcile(
        self,
        broker_adapter: Any,
    ) -> ReconciliationResult:
        """
        Main reconciliation entry point.

        Compares internal order state with broker orders and positions.
        Detects issues and optionally auto-repairs or freezes trading.
        """
        issues: list[ReconciliationIssue] = []
        repaired_count = 0

        log.info("Starting execution reconciliation...")

        try:
            broker_orders = self._fetch_broker_orders(broker_adapter)
            broker_positions = self._fetch_broker_positions(broker_adapter)
            internal_orders = self.get_all_orders()

            log.info(
                f"Reconciliation: {len(broker_orders)} broker orders, "
                f"{len(broker_positions)} broker positions, "
                f"{len(internal_orders)} internal orders"
            )

            pending_internal = self.get_pending_orders()

            stale_orders = self._detect_stale_orders(
                pending_internal, broker_orders
            )
            for issue in stale_orders:
                issues.append(issue)
                log.warning(f"Stale order detected: {issue.description}")

            orphan_positions = self._detect_orphan_positions(
                broker_positions, internal_orders
            )
            for issue in orphan_positions:
                issues.append(issue)
                log.warning(f"Orphan position detected: {issue.description}")

            quantity_mismatches = self._detect_quantity_mismatches(
                broker_orders, internal_orders
            )
            for issue in quantity_mismatches:
                issues.append(issue)
                log.warning(f"Quantity mismatch: {issue.description}")

            unrecorded_fills = self._detect_unrecorded_fills(
                broker_orders, internal_orders
            )
            for issue in unrecorded_fills:
                issues.append(issue)
                log.warning(f"Unrecorded fill: {issue.description}")

            if self._enable_auto_repair:
                repaired_count = self._auto_repair(issues, broker_adapter)

            is_clean = len(issues) == 0

            if not is_clean and self._detect_ambiguity(issues):
                freeze_reason = self._determine_freeze_reason(issues)
                self._freeze_trading(freeze_reason, self._format_issues(issues))
            elif not is_clean:
                log.warning(
                    f"Reconciliation found {len(issues)} issues but not ambiguous"
                )

            result = ReconciliationResult(
                is_clean=is_clean,
                issues=issues,
                freeze_reason=self._freeze_reason if not is_clean else None,
                broker_positions_count=len(broker_positions),
                internal_orders_count=len(internal_orders),
                repaired_count=repaired_count,
            )

            self._last_reconciliation = result
            self._log_reconciliation_result(result)

            return result

        except (ReconciliationError, DatabaseError, sqlite3.Error, OSError, ValueError, KeyError) as e:
            log.exception(f"Reconciliation failed: {e}")
            self._freeze_trading(
                TradingFreezeReason.RECONCILIATION_FAILED,
                str(e)
            )
            return ReconciliationResult(
                is_clean=False,
                issues=[ReconciliationIssue(
                    issue_type=ReconciliationState.AMBIGUOUS,
                    order_id=None,
                    internal_value=None,
                    broker_value=None,
                    description=f"Reconciliation exception: {e}"
                )],
                freeze_reason=TradingFreezeReason.RECONCILIATION_FAILED,
            )

    def _fetch_broker_orders(self, broker_adapter: Any) -> list[dict]:
        """Fetch orders from broker."""
        try:
            if hasattr(broker_adapter, 'get_order_book'):
                book = broker_adapter.get_order_book()
                if isinstance(book, list):
                    return book
                elif isinstance(book, dict):
                    return book.get('data', book.get('orders', []))
            elif hasattr(broker_adapter, '_port') and hasattr(broker_adapter._port, 'get_order_book'):
                book = broker_adapter._port.get_order_book()
                if isinstance(book, list):
                    return book
                elif isinstance(book, dict):
                    return book.get('data', book.get('orders', []))
            return []
        except (BrokerConnectionError, ConnectionError, OSError, ValueError) as e:
            log.error(f"Failed to fetch broker orders: {e}")
            return []

    def _fetch_broker_positions(self, broker_adapter: Any) -> list[dict]:
        """Fetch positions from broker."""
        try:
            if hasattr(broker_adapter, 'get_positions'):
                return broker_adapter.get_positions() or []
            elif hasattr(broker_adapter, '_port') and hasattr(broker_adapter._port, 'get_positions'):
                return broker_adapter._port.get_positions() or []
            return []
        except (BrokerConnectionError, ConnectionError, OSError, ValueError) as e:
            log.error(f"Failed to fetch broker positions: {e}")
            return []

    def _detect_stale_orders(
        self,
        internal_pending: list[dict],
        broker_orders: list[dict],
    ) -> list[ReconciliationIssue]:
        """Detect orders in internal state but not in broker."""
        issues = []
        broker_order_ids = {str(o.get('orderid', o.get('order_id', '')))
                          for o in broker_orders}

        for order in internal_pending:
            internal_id = order.get('order_id', '')
            broker_id = order.get('broker_order_id', '')

            if broker_id and broker_id not in broker_order_ids:
                issues.append(ReconciliationIssue(
                    issue_type=ReconciliationState.STALE_ORDER,
                    order_id=internal_id,
                    internal_value=order.get('status'),
                    broker_value='NOT_FOUND',
                    description=f"Order {internal_id} (broker: {broker_id}) not found in broker"
                ))

        return issues

    def _detect_orphan_positions(
        self,
        broker_positions: list[dict],
        internal_orders: list[dict],
    ) -> list[ReconciliationIssue]:
        """Detect positions in broker but not in internal state."""
        issues = []

        internal_symbols = set()
        for order in internal_orders:
            sym = order.get('symbol', '')
            if sym:
                internal_symbols.add(sym)

        for pos in broker_positions:
            symbol = pos.get('symbol', pos.get('tradingsymbol', ''))
            qty = pos.get('quantity', pos.get('net_quantity', 0))

            if qty != 0 and symbol not in internal_symbols:
                issues.append(ReconciliationIssue(
                    issue_type=ReconciliationState.ORPHAN_POSITION,
                    order_id=None,
                    internal_value='NO_ORDER',
                    broker_value=qty,
                    description=f"Orphan position: {symbol} x {qty} in broker but no internal order"
                ))

        return issues

    def _detect_quantity_mismatches(
        self,
        broker_orders: list[dict],
        internal_orders: list[dict],
    ) -> list[ReconciliationIssue]:
        """Detect quantity mismatches between broker and internal."""
        issues = []

        internal_by_broker_id = {}
        for order in internal_orders:
            bid = order.get('broker_order_id')
            if bid:
                internal_by_broker_id[str(bid)] = order

        for broker_order in broker_orders:
            bid = str(broker_order.get('orderid', broker_order.get('order_id', '')))
            if bid in internal_by_broker_id:
                internal = internal_by_broker_id[bid]
                broker_qty = broker_order.get('filledshares', broker_order.get('filled_quantity', 0))
                internal_qty = internal.get('filled_quantity', 0)

                if int(broker_qty) != int(internal_qty):
                    issues.append(ReconciliationIssue(
                        issue_type=ReconciliationState.QUANTITY_MISMATCH,
                        order_id=internal.get('order_id'),
                        internal_value=internal_qty,
                        broker_value=broker_qty,
                        description=f"Mismatch for {bid}: internal={internal_qty}, broker={broker_qty}"
                    ))

        return issues

    def _detect_unrecorded_fills(
        self,
        broker_orders: list[dict],
        internal_orders: list[dict],
    ) -> list[ReconciliationIssue]:
        """Detect fills in broker that weren't recorded internally."""
        issues = []

        internal_by_broker_id = {}
        for order in internal_orders:
            bid = order.get('broker_order_id')
            if bid:
                internal_by_broker_id[str(bid)] = order

        for broker_order in broker_orders:
            bid = str(broker_order.get('orderid', broker_order.get('order_id', '')))
            status = str(broker_order.get('orderstatus', broker_order.get('status', ''))).upper()

            if 'COMPLETE' in status or 'FILLED' in status:
                if bid not in internal_by_broker_id:
                    qty = broker_order.get('filledshares', broker_order.get('filled_quantity', 0))
                    price = broker_order.get('averageprice', broker_order.get('price', 0))
                    issues.append(ReconciliationIssue(
                        issue_type=ReconciliationState.UNRECORDED_FILL,
                        order_id=bid,
                        internal_value='NOT_FOUND',
                        broker_value={'filled_qty': qty, 'price': price},
                        description=f"Fill in broker not recorded internally: {bid} x {qty} @ {price}"
                    ))

        return issues

    def _detect_ambiguity(self, issues: list[ReconciliationIssue]) -> bool:
        """Determine if issues are ambiguous enough to warrant freeze."""
        if len(issues) > 3:
            return True

        ambiguous_types = {
            ReconciliationState.AMBIGUOUS,
            ReconciliationState.ORPHAN_POSITION,
            ReconciliationState.QUANTITY_MISMATCH,
        }

        ambiguous_count = sum(1 for i in issues if i.issue_type in ambiguous_types)
        if ambiguous_count > 0:
            return True

        return False

    def _determine_freeze_reason(
        self,
        issues: list[ReconciliationIssue],
    ) -> TradingFreezeReason:
        """Determine the primary freeze reason from issues."""
        type_counts: dict[ReconciliationState, int] = {}
        for issue in issues:
            t = issue.issue_type
            type_counts[t] = type_counts.get(t, 0) + 1

        if ReconciliationState.ORPHAN_POSITION in type_counts:
            return TradingFreezeReason.ORPHAN_POSITIONS_DETECTED
        elif ReconciliationState.STALE_ORDER in type_counts:
            return TradingFreezeReason.STALE_ORDERS_UNRESOLVED
        elif ReconciliationState.QUANTITY_MISMATCH in type_counts:
            return TradingFreezeReason.QUANTITY_MISMATCH_UNRESOLVED
        else:
            return TradingFreezeReason.RECONCILIATION_FAILED

    def _auto_repair(
        self,
        issues: list[ReconciliationIssue],
        broker_adapter: Any,
    ) -> int:
        """Attempt to automatically repair certain issues."""
        repaired = 0

        for issue in issues:
            if issue.issue_type == ReconciliationState.STALE_ORDER:
                try:
                    self._mark_order_terminal(issue.order_id, 'UNKNOWN_STALE')
                    repaired += 1
                    log.info(f"Auto-repaired stale order: {issue.order_id}")
                except (DatabaseError, sqlite3.Error, OSError, AttributeError) as e:
                    log.error(f"Failed to repair stale order {issue.order_id}: {e}")

            elif issue.issue_type == ReconciliationState.UNRECORDED_FILL:
                try:
                    self._record_unrecorded_fill(issue)
                    repaired += 1
                    log.info(f"Auto-repaired unrecorded fill: {issue.order_id}")
                except (DatabaseError, sqlite3.Error, OSError, AttributeError) as e:
                    log.error(f"Failed to repair unrecorded fill {issue.order_id}: {e}")

        return repaired

    def _mark_order_terminal(self, order_id: str, status: str):
        """Mark an order as terminal state."""
        now = now_ist().isoformat()
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("""
                UPDATE execution_orders
                SET status = ?, updated_at = ?, is_reconciled = 1
                WHERE order_id = ?
            """, (status, now, order_id))
            conn.commit()

    def _record_unrecorded_fill(self, issue: ReconciliationIssue):
        """Record a fill that wasn't in internal state."""
        if not issue.order_id or not issue.broker_value:
            return

        broker_val = issue.broker_value
        if isinstance(broker_val, dict):
            qty = broker_val.get('filled_qty', 0)
            price = broker_val.get('price', 0.0)
        else:
            qty = 0
            price = 0.0

        self.update_order_fill(
            order_id=issue.order_id,
            filled_quantity=int(qty),
            average_price=float(price),
            status='FILLED'
        )

    def _format_issues(self, issues: list[ReconciliationIssue]) -> str:
        """Format issues for logging/freeze notification."""
        lines = [f"Total issues: {len(issues)}"]
        for i, issue in enumerate(issues[:10], 1):
            lines.append(f"  {i}. {issue.issue_type.value}: {issue.description}")
        if len(issues) > 10:
            lines.append(f"  ... and {len(issues) - 10} more")
        return "\n".join(lines)

    def _log_reconciliation_result(self, result: ReconciliationResult):
        """Log reconciliation result."""
        if result.is_clean:
            log.info(
                f"Reconciliation complete: CLEAN "
                f"(broker pos: {result.broker_positions_count}, "
                f"internal orders: {result.internal_orders_count})"
            )
        else:
            log.warning(
                f"Reconciliation complete: ISSUES FOUND "
                f"(issues: {len(result.issues)}, "
                f"repaired: {result.repaired_count}, "
                f"frozen: {result.freeze_reason is not None})"
            )


from collections.abc import Callable
