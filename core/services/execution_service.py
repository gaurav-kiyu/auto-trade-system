import hashlib
import logging
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

__all__ = [
    "ExecutionServiceConfig",
    "ExecutionService",
]

from core.datetime_ist import now_ist
from core.execution.broker_ack_validator import BrokerAckValidator
from core.execution.broker_state_handler import create_state_handler
from core.execution.deterministic_state_machine import ExecutionState, get_execution_state_manager
from core.execution.durable_state import (
    DurableExecutionRecord,
    DurableExecutionStore,
)
from core.execution.durable_state import (
    ExecutionState as DurableExecState,
)
from core.execution.idempotency.manager import IdempotencyManager
from core.execution.order_submission.manager import OrderSubmissionManager
from core.execution.reconciliation.service import (
    ReconciliationService,
    TradingFreezeReason,
)
from core.execution.retry_policy.manager import RetryPolicy
from core.ports.execution.execution_port import (
    ExecutionAuditTrail,
    ExecutionContext,
    ExecutionMode,
    ExecutionPort,
    OrderRequest,
    OrderResult,
    OrderStatus,
    OrderType,
)


@dataclass
class ExecutionServiceConfig:
    """Configuration for the Execution Service."""
    enable_duplicate_prevention: bool = True
    idempotency_db_path: str | None = None
    idempotency_cache_size: int = 1000
    idempotency_expiry_hours: int = 24
    enable_audit_trail: bool = True
    audit_log_path: str = "logs/execution_audit.jsonl"
    max_retries: int = 3
    base_retry_delay: float = 1.0
    max_retry_delay: float = 10.0
    retry_exponential_base: float = 2.0
    paper_fill_delay_ms: int = 50
    paper_fill_slippage_pct: float = 0.05

class ExecutionService(ExecutionPort):
    """
    Hardened Execution Service.
    Orchestrates the flow from Risk Validation -> Order Management -> Broker Gateway.
    """

    def __init__(
        self,
        portfolio_service=None,
        config=None,
        broker_port=None,
        trade_persistence=None,
        reconciliation_db_path: str = "trades.db",
        wal_journal=None,  # Phase 5B: Write-ahead journal for crash-safe intent logging
    ):
        self.portfolio = portfolio_service

        if config is None:
            config = ExecutionServiceConfig()
        elif isinstance(config, dict):
            config = ExecutionServiceConfig(**config)

        self.config = config
        self.config_obj = config

        self._logger = logging.getLogger("execution_service")

        persistence_path = self.config.idempotency_db_path
        cache_size = self.config.idempotency_cache_size
        expiry_hours = self.config.idempotency_expiry_hours

        self.trade_persistence = trade_persistence

        # Phase 5B: WAL journal for crash-safe intent logging
        self._wal_journal = wal_journal
        if self._wal_journal is not None:
            self._logger.info("WAL journal wired into ExecutionService")

        if broker_port is None:
            from core.adapters.broker_adapters import PaperBrokerAdapter
            broker_port = PaperBrokerAdapter()
        self._broker_port = broker_port
        self.broker_port = broker_port

        self.idempotency = IdempotencyManager(
            cache_size=cache_size,
            expiry_hours=expiry_hours,
            persistence_path=persistence_path,
        )

        # Durable execution store - use fixed path so state survives restarts
        durable_db_path = reconciliation_db_path.replace("trades.db", "execution_state.db")

        self._durable_store = DurableExecutionStore(durable_db_path)
        self._logger.info(f"Durable execution store initialized: {durable_db_path}")

        # CRITICAL FIX: Deterministic state machine for idempotency
        # Wire persistence callback so state transitions persist into durable store
        manager = get_execution_state_manager()
        def _persistence_callback(machine):
            try:
                # Map ExecutionState enum to durable store states where possible
                state_map = {
                    ExecutionState.VALIDATED: DurableExecState.PENDING,
                    ExecutionState.PERSISTED: DurableExecState.PENDING,
                    ExecutionState.SUBMITTED: DurableExecState.SUBMITTED,
                    ExecutionState.ACKNOWLEDGED: DurableExecState.SUBMITTED,
                    ExecutionState.PARTIAL_FILL: DurableExecState.PARTIALLY_FILLED,
                    ExecutionState.FILLED: DurableExecState.FILLED,
                    ExecutionState.REJECTED: DurableExecState.REJECTED,
                    ExecutionState.FAILED: DurableExecState.FAILED,
                    ExecutionState.CANCELLED: DurableExecState.CANCELLED,
                }
                durable_state = state_map.get(machine.state, DurableExecState.UNKNOWN)
                # Persist to durable store
                self._durable_store.update_state(
                    machine.intent_id,
                    durable_state,
                    broker_order_id=machine.broker_order_id,
                    filled_quantity=machine.filled_quantity,
                    average_price=machine.average_price,
                    reject_reason=machine.error_message,
                )
            except (KeyError, AttributeError, ValueError, OSError) as _ex:
                self._logger.error(f"Persistence callback failed for {machine.intent_id}: {_ex}")

        manager._persistence_callback = _persistence_callback
        self._state_machine = manager

        self.retry_policy = RetryPolicy()
        self.submission = OrderSubmissionManager(self._broker_port)

        self._executions: dict[str, Any] = {}
        self._execution_counter = 0
        self._idempotency_cache = OrderedDict()
        self._lock = threading.RLock()

        self._paper_price_cache: dict[str, float] = {}

        self._logger = logging.getLogger("execution_service")

        self._shutdown_event = threading.Event()

        self._reconciliation_service = ReconciliationService(
            db_path=reconciliation_db_path,
            freeze_callback=self._on_reconciliation_freeze,
            enable_auto_repair=True,
        )


        broker_type = BrokerAckValidator.detect_broker_type(broker_port)

        # Phase 1A - Operating mode manager (injected by init code)
        self._operating_mode_manager = None

        self._ack_validator = BrokerAckValidator(broker_type)
        self._logger.info(f"Broker ACK validator initialized for {broker_type.value}")

        self._state_handler = create_state_handler(
            max_retries=config.max_retries if config else 3,
            timeout_seconds=30,
        )
        self._logger.info("Broker state handler initialized")

        # Initialize reconciliation freeze flag before any callbacks fire
        self._is_reconciliation_frozen = False

    def set_operating_mode_manager(self, manager) -> None:
        """Inject operating mode manager for execution gating."""
        self._operating_mode_manager = manager
        if manager is not None:
            mode = manager.current_mode
            self._logger.info("Operating mode set: %s", mode.value if hasattr(mode, 'value') else mode)

    def run_stale_order_timeout(self, max_stale_seconds: float = 300.0) -> dict:
        """
        Cancel orders stuck in non-terminal states beyond the stale threshold.

        Scans all state machines for orders that have been in a non-terminal,
        non-progressing state (SUBMITTED, ACKNOWLEDGED, CANCEL_PENDING,
        PENDING_SUBMISSION) for longer than max_stale_seconds, then attempts
        to cancel them via the broker and transitions the machine to FAILED.

        This prevents "zombie orders" from blocking capacity and consuming
        risk capital indefinitely.

        Args:
            max_stale_seconds: Maximum time (in seconds) an order can remain
                               in a non-terminal state before being cancelled.
                               Default 300 (5 minutes).

        Returns:
            dict with keys: checked, cancelled, already_terminal, errors
        """
        result = {"checked": 0, "cancelled": 0, "already_terminal": 0, "errors": 0}
        try:
            manager = get_execution_state_manager()
            now = now_ist()
            stale_states = {
                ExecutionState.SUBMITTED,
                ExecutionState.ACKNOWLEDGED,
                ExecutionState.CANCEL_PENDING,
                ExecutionState.PENDING_SUBMISSION,
                ExecutionState.VALIDATED,
                ExecutionState.PERSISTED,
            }

            for machine in manager.get_all():
                with machine._lock:
                    if machine.is_terminal():
                        result["already_terminal"] += 1
                        continue

                    if machine.state not in stale_states:
                        continue

                    # Determine age based on which timestamp is relevant
                    if machine.submitted_at:
                        try:
                            last_activity = datetime.fromisoformat(machine.submitted_at)
                        except (ValueError, TypeError):
                            result["errors"] += 1
                            continue
                    else:
                        try:
                            last_activity = datetime.fromisoformat(machine.updated_at)
                        except (ValueError, TypeError):
                            result["errors"] += 1
                            continue

                    age_seconds = (now - last_activity).total_seconds()
                    if age_seconds < max_stale_seconds:
                        continue

                    result["checked"] += 1

                    # Capture stale state INSIDE the lock for the error message
                    stale_state = machine.state
                    broker_order_id = machine.broker_order_id

                    self._logger.warning(
                        "Stale order detected: client_order_id=%s, state=%s, "
                        "age=%.1fs, broker_order_id=%s",
                        machine.client_order_id,
                        stale_state.value,
                        age_seconds,
                        broker_order_id or "N/A",
                    )

                    # Attempt to cancel via broker if we have a broker order ID
                    if broker_order_id and hasattr(self._broker_port, 'cancel_order'):
                        try:
                            cancel_success = self._broker_port.cancel_order(broker_order_id)
                            if cancel_success:
                                self._logger.info(
                                    "Stale order cancelled via broker: %s", broker_order_id
                                )
                        except (ValueError, OSError, ConnectionError) as ex:
                            self._logger.warning(
                                "Failed to cancel stale order via broker: %s - %s",
                                broker_order_id, ex,
                            )

                # Use record_failure OUTSIDE the lock to avoid deadlock
                # with persistence callbacks. record_failure sets error_message
                # BEFORE the transition, ensuring the callback sees the correct reason.
                machine.record_failure(
                    f"Stale order timeout ({age_seconds:.0f}s in {stale_state.value})"
                )
                result["cancelled"] += 1

        except (ValueError, OSError, AttributeError) as e:
            self._logger.error(f"Error in stale order timeout run: {e}", exc_info=True)
            result["errors"] += 1

        if result["cancelled"] > 0:
            self._logger.warning(
                "Stale order timeout: cancelled %d of %d checked orders",
                result["cancelled"],
                result["checked"],
            )
        return result

    def run_ack_watchdog(self, max_ack_age_seconds: float = 30.0) -> dict:
        """
        ACK timeout watchdog: find orders stuck in SUBMITTED state without ACK.

        Queries the broker for current order status. If the order has been
        acknowledged/rejected/filled by the broker, updates the state machine.
        If still pending, logs a warning.

        Args:
            max_ack_age_seconds: Maximum time to wait for broker ACK.

        Returns:
            dict with keys: checked, acknowledged, still_pending, errors
        """
        result = {"checked": 0, "acknowledged": 0, "still_pending": 0, "errors": 0}
        manager = get_execution_state_manager()
        now = now_ist()
        for machine in manager.get_all():
            with machine._lock:
                if machine.state != ExecutionState.SUBMITTED:
                    continue
                if machine.submitted_at is None:
                    continue
                try:
                    submitted_dt = datetime.fromisoformat(machine.submitted_at)
                except (ValueError, TypeError):
                    result["errors"] += 1
                    continue
                age = (now - submitted_dt).total_seconds()
                if age < max_ack_age_seconds:
                    continue
            result["checked"] += 1
            try:
                broker_id = machine.broker_order_id
                if not broker_id:
                    result["errors"] += 1
                    continue
                status = self._broker_port.get_order_status(broker_id)
                if status is None:
                    result["still_pending"] += 1
                    continue
                status_upper = status.upper()
                if status_upper in ("COMPLETE", "FILLED", "EXECUTED"):
                    qty = machine.quantity
                    price = machine.price
                    with machine._lock:
                        machine.record_acknowledgment()
                        machine.record_fill(qty, price)
                    result["acknowledged"] += 1
                elif status_upper in ("REJECTED", "CANCELLED", "EXPIRED"):
                    with machine._lock:
                        machine.try_transition_to(ExecutionState.REJECTED)
                    result["acknowledged"] += 1
                elif status_upper in ("OPEN", "PENDING", "TRIGGER PENDING", "SUBMITTED"):
                    result["still_pending"] += 1
                else:
                    result["still_pending"] += 1
            except (ValueError, OSError, AttributeError):
                result["errors"] += 1
        return result

    def _on_reconciliation_freeze(self, reason: TradingFreezeReason, details: str):
        """Callback when reconciliation detects ambiguous state."""
        self._is_reconciliation_frozen = True
        self._logger.critical(
            f"Trading frozen due to reconciliation: {reason.value} - {details}"
        )

    def is_trading_frozen(self) -> bool:
        """Check if trading is frozen due to reconciliation issues."""
        return self._is_reconciliation_frozen

    def unfreeze_trading(self):
        """Manually unfreeze trading after issue resolution."""
        self._reconciliation_service.unfreeze()
        self._is_reconciliation_frozen = False
        self._logger.warning("Trading manually unfrozen")

    def reconcile_pending_orders(self) -> dict:
        """
        Startup reconciliation: scan for non-terminal orders and update status.
        Uses both legacy reconciliation service and durable store for complete coverage.

        Returns:
            dict with reconciliation results
        """
        self._logger.info("Starting execution reconciliation...")

        result = self._reconciliation_service.reconcile(self._broker_port)

        if not result.is_clean:
            self._logger.warning(
                f"Reconciliation found {len(result.issues)} issues"
            )
            for issue in result.issues:
                self._logger.warning(f"  - {issue.issue_type.value}: {issue.description}")
        else:
            self._logger.info("Reconciliation complete: CLEAN")

        if result.freeze_reason:
            self._is_reconciliation_frozen = True
            self._logger.critical(
                f"Trading frozen: {result.freeze_reason.value}"
            )

        self._logger.info("Starting durable state reconciliation...")
        durable_result = self._durable_store.reconcile_with_broker(self._broker_port)
        self._logger.info(
            f"Durable state: checked={durable_result['checked']}, "
            f"filled={durable_result['filled']}, "
            f"still_pending={durable_result['still_pending']}, "
            f"unknown={durable_result['unknown']}"
        )

        return {
            "is_clean": result.is_clean,
            "issues_count": len(result.issues),
            "repaired_count": result.repaired_count,
            "freeze_reason": result.freeze_reason.value if result.freeze_reason else None,
            "broker_positions": result.broker_positions_count,
            "internal_orders": result.internal_orders_count,
            "durable_state": durable_result,
        }

    def execute_order(
        self,
        order_request: OrderRequest,
        execution_context: ExecutionContext = None
    ) -> OrderResult:
        """
        Execute an order with idempotency and duplicate prevention.
        """
        # ─── Operating Mode Gate (Phase 1A) ─────────────────────────────────
        from core.operating_mode import OperatingModeManager
        _mode_manager: OperatingModeManager | None = getattr(self, '_operating_mode_manager', None)
        if _mode_manager is not None:
            allowed, msg = _mode_manager.allows_execution()
            if not allowed:
                self._logger.warning("Order blocked by operating mode: %s", msg)
                return OrderResult(
                    order_id="blocked",
                    status=OrderStatus.REJECTED,
                    reject_reason=f"BLOCKED_{msg}",
                    timestamp=now_ist()
                )
            if _mode_manager.requires_manual_approval():
                from core.operating_mode import ExecutionAction
                live_allowed, live_msg = _mode_manager.can_perform_live(ExecutionAction.SUBMIT_ORDER)
                if live_allowed:
                    self._logger.info("Manual approval required for order %s", order_request.symbol)
        # ─────────────────────────────────────────────────────────────────────

        # Set default execution context if not provided
        if execution_context is None:
            execution_context = ExecutionContext()

        # Generate idempotency key if not provided
        if not order_request.idempotency_key:
            order_request.idempotency_key = self._generate_idempotency_key(
                order_request, execution_context
            )

        idempotency_key = order_request.idempotency_key

        # CRITICAL FIX: Wrap entire check→execute→store in atomic lock
        # to prevent TOCTOU race condition under concurrent load
        with self._lock:
            # Generate execution ID under lock to prevent counter data race
            execution_id = f"exec_{self._execution_counter}_{int(time.time())}"
            self._execution_counter += 1

            intent_id = f"{order_request.symbol}_{order_request.direction}_{order_request.strike_price}_{order_request.lot_size}"

            # ── Phase 5B: WAL journal intent logging ──────────────────────
            # Append PENDING intent BEFORE any broker call ensures crash recovery.
            if self._wal_journal is not None:
                from core.wal.journal import Intent
                wal_intent = Intent(
                    intent_id=intent_id,
                    action="place_order",
                    params={
                        "symbol": order_request.symbol,
                        "direction": order_request.direction,
                        "qty": order_request.lot_size,
                        "strike": order_request.strike_price,
                        "order_type": order_request.order_type.value if hasattr(order_request.order_type, 'value') else str(order_request.order_type),
                    },
                )
                self._wal_journal.append(wal_intent)
            # ────────────────────────────────────────────────────────────────

            if self.config.enable_duplicate_prevention:
                if self.idempotency.is_duplicate(idempotency_key):
                    self._logger.warning(f"Duplicate order prevented: {idempotency_key}")
                    if self._wal_journal is not None:
                        self._wal_journal.fail(intent_id, "Duplicate order detected")
                    cached_result = self.idempotency.get_result(idempotency_key)
                    if cached_result is not None:
                        return cached_result
                    else:
                        return OrderResult(
                            order_id="duplicate",
                            status=OrderStatus.REJECTED,
                            reject_reason="Duplicate order detected",
                            timestamp=now_ist()
                        )

            durable_record = DurableExecutionRecord(
                intent_id=intent_id,
                client_order_id=execution_id,
                symbol=order_request.symbol,
                direction=order_request.direction,
                quantity=order_request.lot_size,
                strike_price=order_request.strike_price,
                state=DurableExecState.PENDING,
            )
            self._logger.debug("saving durable record for intent %s to %s", intent_id, self._durable_store._db_path)
            self._durable_store.save_execution(durable_record)

            self._logger.debug("marking idempotency in flight for key %s", idempotency_key)
            self.idempotency.mark_in_flight(idempotency_key)

        # Record the execution start
        start_time = time.time()
        audit_trail = ExecutionAuditTrail(
            execution_id=execution_id,
            order_request=order_request,
            execution_context=execution_context
        )

        # CRITICAL FIX: Use try/finally to ensure in-flight marker is cleared
        # even if execution fails or crashes
        try:
            # Execute with retries (still inside atomic lock)
            order_result = self._execute_with_retries(order_request, execution_context)

            # Calculate latency
            latency_ms = int((time.time() - start_time) * 1000)
            audit_trail.latency_ms = latency_ms

            # Handle successful execution
            if order_result.status in [OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED]:
                # ── Phase 5B: WAL journal commit ────────────────────────────
                if self._wal_journal is not None:
                    self._wal_journal.commit(intent_id)
                # ─────────────────────────────────────────────────────────────

                self.idempotency.confirm_execution(idempotency_key, order_result)
                # Persist idempotency result for duplicate detection
                try:
                    self._store_idempotency_key(idempotency_key, order_result)
                except (KeyError, ValueError, OSError):
                    self._logger.exception("Failed to store idempotency result in cache")
                self._durable_store.update_state(
                    intent_id,
                    DurableExecState.FILLED if order_result.status == OrderStatus.FILLED else DurableExecState.PARTIALLY_FILLED,
                    broker_order_id=order_result.broker_order_id,
                    filled_quantity=order_result.filled_quantity,
                    average_price=order_result.average_price,
                )

                if (self.trade_persistence and
                    order_result.filled_quantity > 0 and
                    self.config.enable_audit_trail):
                    self._persist_trade_from_order(order_request, order_result, execution_context)

                if self.config.enable_audit_trail:
                    audit_trail.order_result = order_result
                    self.record_execution_audit(audit_trail)

                self._logger.info(
                    f"Order executed successfully: {order_result.order_id} "
                    f"({order_result.filled_quantity} lots @ {order_result.average_price})"
                )

            else:
                # ── Phase 5B: WAL journal failure ───────────────────────────
                if self._wal_journal is not None:
                    self._wal_journal.fail(intent_id, order_result.reject_reason or "Order rejected")
                # ─────────────────────────────────────────────────────────────

                durable_state = DurableExecState.REJECTED if order_result.status == OrderStatus.REJECTED else DurableExecState.FAILED
                self._durable_store.update_state(
                    intent_id,
                    durable_state,
                    reject_reason=order_result.reject_reason,
                )

                audit_trail.order_result = order_result
                if self.config.enable_audit_trail:
                    self.record_execution_audit(audit_trail)

                self._logger.warning(
                    f"Order execution failed: {order_result.status.value} - "
                    f"{order_result.reject_reason}"
                )

            return order_result

        except (ValueError, OSError, AttributeError, ConnectionError) as e:
            # ── Phase 5B: WAL journal failure ───────────────────────────────
            if self._wal_journal is not None:
                self._wal_journal.fail(intent_id, str(e))
            # ─────────────────────────────────────────────────────────────────

            self.idempotency.clear_in_flight(idempotency_key)
            self._durable_store.clear_in_flight(intent_id)

            latency_ms = int((time.time() - start_time) * 1000)
            audit_trail.latency_ms = latency_ms
            audit_trail.order_result = OrderResult(
                order_id="error",
                status=OrderStatus.REJECTED,
                reject_reason=f"Execution service error: {str(e)}",
                timestamp=now_ist()
            )

            if self.config.enable_audit_trail:
                self.record_execution_audit(audit_trail)

            self._logger.error(f"Unexpected error in order execution: {e}", exc_info=True)
            return audit_trail.order_result

    def modify_order(
        self,
        order_id: str,
        *,
        quantity: int | None = None,
        price: float | None = None,
        trigger_price: float | None = None,
        order_type: OrderType | None = None,
    ) -> OrderResult:
        """
        Modify an existing pending order.

        Allows changing quantity, limit price, trigger price, and/or order type
        for orders that are still in a PENDING or SUBMITTED state.

        Args:
            order_id: The order ID to modify
            quantity: New lot quantity (None = no change)
            price: New limit price (None = no change)
            trigger_price: New trigger price for SL orders (None = no change)
            order_type: New order type (None = no change)

        Returns:
            OrderResult with modification status
        """
        try:
            # Check if order exists and is modifiable
            current_status = self.get_order_status(order_id)
            if current_status in [OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.EXPIRED, OrderStatus.REJECTED]:
                self._logger.warning(f"Cannot modify order {order_id} with terminal status {current_status.value}")
                return OrderResult(
                    order_id=order_id,
                    status=OrderStatus.REJECTED,
                    reject_reason=f"Order {order_id} has terminal status {current_status.value}",
                    timestamp=now_ist(),
                )

            # Attempt modification via broker
            start_time = time.time()
            broker_result = self.broker_port.modify_order(
                order_id,
                qty=quantity,
                price=price,
                trigger_price=trigger_price,
                order_type=order_type.value if order_type else None,
            )
            latency_ms = int((time.time() - start_time) * 1000)

            # Convert broker result to OrderResult
            if isinstance(broker_result, bool):
                if broker_result:
                    self._logger.info(f"Order {order_id} modified successfully in {latency_ms}ms")
                    return OrderResult(
                        order_id=order_id,
                        status=OrderStatus.SUBMITTED,
                        filled_quantity=0,
                        average_price=0.0,
                        timestamp=now_ist(),
                    )
                else:
                    self._logger.warning(f"Failed to modify order {order_id}")
                    # ── Telegram escalation: alert on modification failure ──
                    self._escalate_order_modification_failed(
                        order_id=order_id,
                        reason="Broker rejected modification",
                        details={
                            "quantity": quantity,
                            "price": price,
                            "trigger_price": trigger_price,
                            "order_type": order_type.value if order_type else None,
                            "latency_ms": latency_ms,
                        },
                    )
                    return OrderResult(
                        order_id=order_id,
                        status=OrderStatus.REJECTED,
                        reject_reason="Broker rejected modification",
                        timestamp=now_ist(),
                    )

            # If broker returned an OrderResult directly (e.g. PaperBrokerAdapter returns bool)
            if hasattr(broker_result, 'status'):
                status_val = str(broker_result.status).upper() if hasattr(broker_result.status, 'upper') else str(broker_result.status)
                if status_val in ("REJECTED", "CANCELLED", "FAILED"):
                    # ── Telegram escalation on rejected order result ──
                    self._escalate_order_modification_failed(
                        order_id=order_id,
                        reason=f"Broker returned status: {status_val}",
                        details={
                            "quantity": quantity,
                            "price": price,
                            "reject_reason": getattr(broker_result, 'reject_reason', None),
                        },
                    )
                    self._logger.warning(f"Order {order_id} modification rejected: {broker_result.status}")
                else:
                    self._logger.info(f"Order {order_id} modified: {broker_result.status}")
                return broker_result

            return OrderResult(
                order_id=order_id,
                status=OrderStatus.SUBMITTED,
                timestamp=now_ist(),
            )

        except (ValueError, OSError, ConnectionError, AttributeError) as e:
            self._logger.error(f"Error modifying order {order_id}: {e}", exc_info=True)
            # ── Telegram escalation on exception ──
            self._escalate_order_modification_failed(
                order_id=order_id,
                reason=str(e),
                details={
                    "quantity": quantity,
                    "price": price,
                    "error_type": type(e).__name__,
                },
            )
            return OrderResult(
                order_id=order_id,
                status=OrderStatus.REJECTED,
                reject_reason=str(e),
                timestamp=now_ist(),
            )

    def cancel_order(self, order_id: str) -> bool:
        """
        Cancel an existing order.

        Args:
            order_id: The order ID to cancel

        Returns:
            True if cancellation successful, False otherwise
        """
        try:
            # Check if order exists and is cancellable
            current_status = self.get_order_status(order_id)
            if current_status in [OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.EXPIRED]:
                self._logger.warning(f"Cannot cancel order {order_id} with status {current_status.value}")
                return False

            # Attempt cancellation via broker
            start_time = time.time()
            success = self.broker_port.cancel_order(order_id)
            latency_ms = int((time.time() - start_time) * 1000)

            if success:
                self._logger.info(f"Order {order_id} cancelled successfully in {latency_ms}ms")
            else:
                self._logger.warning(f"Failed to cancel order {order_id}")

            return success

        except (ValueError, OSError, ConnectionError, AttributeError) as e:
            self._logger.error(f"Error cancelling order {order_id}: {e}", exc_info=True)
            return False

    def get_order_status(self, order_id: str) -> OrderStatus:
        """
        Get the current status of an order.

        Args:
            order_id: The order ID to check

        Returns:
            Current order status
        """
        if not order_id or order_id in ["duplicate", "error"]:
            return OrderStatus.REJECTED

        try:
            # Query broker for order status
            # Note: This assumes the broker port has a method to get order status
            # In a real implementation, this might involve querying the broker or checking persistence
            if hasattr(self.broker_port, 'get_order_status'):
                return self.broker_port.get_order_status(order_id)
            else:
                # Fallback: assume submitted orders are still pending unless we have other info
                self._logger.debug(f"No direct order status method available for order {order_id}")
                return OrderStatus.SUBMITTED  # Conservative assumption

        except (ValueError, OSError, AttributeError) as e:
            self._logger.error(f"Error getting order status for {order_id}: {e}")
            return OrderStatus.REJECTED

    def verify_order_fill(
        self,
        order_id: str,
        timeout_seconds: int = 30
    ) -> dict[str, Any]:
        """
        Verify that an order has been filled and get fill details.

        Args:
            order_id: The order ID to verify
            timeout_seconds: Maximum time to wait for fill confirmation

        Returns:
            Dictionary containing fill verification results
        """
        try:
            start_time = time.time()

            # Use broker's wait_for_fill method if available
            if hasattr(self.broker_port, 'wait_for_fill'):
                fill_ok = self.broker_port.wait_for_fill(order_id, timeout=timeout_seconds)
            else:
                # Fallback: poll for fill status
                fill_ok = self._poll_for_fill_status(order_id, timeout_seconds)

            # Get fill details
            filled_quantity = 0
            average_price = 0.0

            if hasattr(self.broker_port, 'get_filled_quantity'):
                filled_quantity = self.broker_port.get_filled_quantity(order_id) or 0

            if hasattr(self.broker_port, 'get_average_price'):
                average_price = self.broker_port.get_average_price(order_id) or 0.0

            # Verify with terminal check if available
            status_verified = True
            if hasattr(self.broker_port, 'verify_terminal_ok'):
                try:
                    status_verified = self.broker_port.verify_terminal_ok(order_id)
                except (ValueError, OSError, AttributeError):
                    status_verified = False

            latency_ms = int((time.time() - start_time) * 1000)

            result = {
                "ok": bool(fill_ok or filled_quantity > 0),
                "filled_quantity": int(filled_quantity),
                "average_price": float(average_price),
                "status_verified": bool(status_verified),
                "latency_ms": latency_ms,
                "order_id": order_id,
                "timestamp": now_ist().isoformat()
            }

            self._logger.debug(f"Fill verification for {order_id}: {result}")
            return result

        except (ValueError, OSError, AttributeError, ConnectionError) as e:
            self._logger.error(f"Error verifying order fill for {order_id}: {e}", exc_info=True)
            return {
                "ok": False,
                "filled_quantity": 0,
                "average_price": 0.0,
                "status_verified": False,
                "latency_ms": int((time.time() - start_time) * 1000) if 'start_time' in locals() else 0,
                "order_id": order_id,
                "error": str(e),
                "timestamp": now_ist().isoformat()
            }

    def is_duplicate_order(self, idempotency_key: str) -> bool:
        """
        Check if an order with the given idempotency key has already been processed.

        Args:
            idempotency_key: Unique key to check for duplication

        Returns:
            True if order is duplicate, False otherwise
        """
        # Delegate to IdempotencyManager for duplicate checks
        try:
            return bool(self.idempotency.is_duplicate(idempotency_key))
        except (KeyError, ValueError, TypeError):
            # Fallback to local cache
            with self._lock:
                self._cleanup_idempotency_cache()
                is_duplicate = idempotency_key in getattr(self, '_idempotency_cache', {})
                if is_duplicate:
                    self._logger.debug(f"Duplicate order detected (fallback): {idempotency_key}")
                return is_duplicate

    def record_execution_audit(
        self,
        audit_trail: ExecutionAuditTrail
    ) -> bool:
        """
        Record an execution audit trail for compliance and debugging.

        Args:
            audit_trail: The execution audit trail to record

        Returns:
            True if recording successful, False otherwise
        """
        try:
            with self._lock:
                self._executions[audit_trail.execution_id] = audit_trail

                # Also persist to trade persistence if available
                if self.trade_persistence:
                    # Convert audit trail to format suitable for persistence
                    trade_data = self._audit_trail_to_trade_data(audit_trail)
                    if trade_data:
                        self.trade_persistence.save_trade(trade_data)

                self._logger.debug(f"Execution audit recorded: {audit_trail.execution_id}")
                return True

        except (KeyError, ValueError, AttributeError, OSError) as e:
            self._logger.error(f"Error recording execution audit: {e}", exc_info=True)
            return False

    def get_execution_audit_trail(
        self,
        execution_id: str
    ) -> ExecutionAuditTrail | None:
        """
        Retrieve an execution audit trail by ID.

        Args:
            execution_id: The execution ID to retrieve

        Returns:
            ExecutionAuditTrail if found, None otherwise
        """
        with self._lock:
            return self._executions.get(execution_id)

    def health_check(self) -> dict[str, Any]:
        """
        Perform a health check on the execution service.

        Returns:
            Dictionary containing health check results
        """
        try:
            with self._lock:
                # Cleanup expired idempotency entries
                self._cleanup_idempotency_cache()

                # Check broker health
                broker_healthy = True  # Assume healthy if no health_check method
                if hasattr(self.broker_port, 'health_check'):
                    broker_health = self.broker_port.health_check()
                    broker_healthy = broker_health.get("status") == "healthy"

                # Check persistence health
                persistence_healthy = True  # Assume healthy if no health_check method
                if hasattr(self.trade_persistence, 'health_check'):
                    persistence_health = self.trade_persistence.health_check()
                    persistence_healthy = persistence_health.get("status") == "healthy"

                # Determine overall status
                overall_status = "healthy" if (broker_healthy and persistence_healthy) else "unhealthy"

                return {
                    "status": overall_status,
                    "service": "ExecutionService",
                    "broker_healthy": broker_healthy,
                    "persistence_healthy": persistence_healthy
                }

        except (KeyError, ValueError, AttributeError, OSError) as e:
            self._logger.error(f"Error in execution service health check: {e}", exc_info=True)
            return {
                "status": "unhealthy",
                "service": "ExecutionService",
                "error": str(e)
            }

    # Private helper methods

    def _generate_idempotency_key(
        self,
        order_request: OrderRequest,
        execution_context: ExecutionContext
    ) -> str:
        """
        Generate a unique idempotency key for an order request.

        Args:
            order_request: The order request
            execution_context: The execution context

        Returns:
            Unique idempotency key string
        """
        # Create a string representation of the order and context
        key_data = {
            "symbol": order_request.symbol,
            "direction": order_request.direction,
            "strike_price": order_request.strike_price,
            "lot_size": order_request.lot_size,
            "order_type": order_request.order_type.value if isinstance(order_request.order_type, OrderType) else str(order_request.order_type),
            "price": order_request.price,
            "stop_loss": order_request.stop_loss,
            "target": order_request.target,
            "strategy_id": order_request.strategy_id,
            "signal_id": execution_context.signal_id,
            "timestamp": execution_context.signal_timestamp.isoformat() if execution_context.signal_timestamp else None
        }

        # Remove None values
        key_data = {k: v for k, v in key_data.items() if v is not None}

        # Create deterministic hash
        key_string = "&".join(f"{k}={v}" for k, v in sorted(key_data.items()))
        return hashlib.sha256(key_string.encode()).hexdigest()[:32]

    def _store_idempotency_key(self, key: str, order_result: OrderResult) -> None:
        """
        Store an idempotency key and its associated order result in the LRU cache.

        Args:
            key: The idempotency key to store
            order_result: The order result to associate with the key
        """
        # Prefer IdempotencyManager for storage, but keep a local fallback cache for backwards compatibility.
        try:
            self.idempotency.store_result(key, order_result)
        except (KeyError, OSError, ValueError):
            self._logger.exception(f"Failed to persist idempotency key {key}")

        with self._lock:
            self._idempotency_cache[key] = (now_ist(), order_result)
            self._idempotency_cache.move_to_end(key, last=False)
            while len(self._idempotency_cache) > self.config.idempotency_cache_size:
                self._idempotency_cache.popitem(last=True)

    def _get_idempotency_result(self, key: str) -> OrderResult | None:
        """
        Get the cached order result for the given idempotency key, if it exists and is not expired.

        Returns:
            The cached OrderResult if found, None otherwise.
        """
        # Delegate to IdempotencyManager
        try:
            return self.idempotency.get_result(key)
        except (KeyError, ValueError, TypeError):
            with self._lock:
                self._cleanup_idempotency_cache()
                if key in self._idempotency_cache:
                    return self._idempotency_cache[key][1]
                return None

    def _cleanup_idempotency_cache(self) -> None:
        """
        Remove expired entries from the idempotency cache.
        """
        # IdempotencyManager handles cleanup; keep local cleanup for fallback cache
        try:
            self.idempotency._cleanup()
            return
        except (AttributeError, KeyError, ValueError):
            with self._lock:
                expiry_time = now_ist() - timedelta(hours=self.config.idempotency_expiry_hours)
                expired_keys = [
                    key for key, (timestamp, _) in self._idempotency_cache.items()
                    if timestamp < expiry_time
                ]
                for key in expired_keys:
                    del self._idempotency_cache[key]
                if expired_keys:
                    self._logger.debug(f"Cleaned up {len(expired_keys)} expired idempotency keys (fallback)")

    def _execute_with_retries(
        self,
        order_request: OrderRequest,
        execution_context: ExecutionContext
    ) -> OrderResult:
        """
        Execute an order with deterministic state machine - NO RETRY after ambiguous states.

        Args:
            order_request: The order to execute
            execution_context: Execution context

        Returns:
            OrderResult from the execution attempt
        """
        # Halt gate - block execution if hard halt active (catches webhook/CLI/API paths)
        from core.safety_state import is_hard_halted
        if is_hard_halted():
            self._logger.critical(f"EXECUTION BLOCKED: Hard halt active for {order_request.symbol}")
            return OrderResult(
                order_id="",
                status=OrderStatus.REJECTED,
                reject_reason="Hard halt active",
                timestamp=now_ist(),
            )

        # CRITICAL FIX: Check idempotency using deterministic state machine BEFORE any attempt
        # Use caller-provided key if available (for cross-layer consistency), else derive locally
        intent_id = order_request.idempotency_key or f"{order_request.symbol}_{order_request.direction}_{order_request.strike_price}_{order_request.lot_size}"
        state_machine, is_new = self._state_machine.create_or_get(
            intent_id=intent_id,
            symbol=order_request.symbol,
            quantity=order_request.lot_size,
            price=order_request.strike_price,
            direction=order_request.direction,
        )

        self._logger.debug("create_or_get returned is_new=%s, state=%s", is_new, state_machine.state)
        # If order already exists in non-terminal state, BLOCK duplicate
        if not is_new and state_machine.state not in [ExecutionState.FILLED, ExecutionState.REJECTED, ExecutionState.CANCELLED, ExecutionState.FAILED]:
            self._logger.warning(f"BLOCKED: Order {intent_id} already in progress (state: {state_machine.state.value})")
            return OrderResult(
                order_id=state_machine.client_order_id,
                status=OrderStatus.REJECTED,
                reject_reason=f"Duplicate order blocked - order already in {state_machine.state.value} state",
                timestamp=now_ist()
            )

        # Mark as validated
        state_machine.try_transition_to(ExecutionState.VALIDATED)
        self._logger.debug("state_machine transitioned to %s", state_machine.state)

        # CRITICAL: Single attempt ONLY - NO RETRY to prevent duplicate orders
        # This is the ONLY execution path - state machine guarantees idempotency
        try:
            # Attempt order execution - ONE TIME ONLY
            result = self._attempt_order_execution(order_request, execution_context)

            # Record state transitions based on result
            if result.status == OrderStatus.FILLED:
                # Advance through intermediate states so record_fill can reach FILLED
                try:
                    self._logger.debug("advancing state machine to PERSISTED/SUBMITTED/ACKNOWLEDGED")
                    state_machine.try_transition_to(ExecutionState.PERSISTED)
                    self._logger.debug("state after PERSISTED attempt: %s", state_machine.state)
                    # Record a submission using the broker/order id if available
                    broker_id = result.broker_order_id or result.order_id or state_machine.client_order_id
                    state_machine.record_submission(str(broker_id))
                    self._logger.debug("state after record_submission: %s", state_machine.state)
                    state_machine.record_acknowledgment()
                    self._logger.debug("state after record_acknowledgment: %s", state_machine.state)
                except (ValueError, TypeError, AttributeError) as ex:
                    # Best effort - continue to record fill
                    self._logger.debug("exception while advancing state machine: %s", ex)

                self._logger.debug("calling record_fill with qty=%s price=%s", order_request.lot_size, order_request.strike_price)
                state_machine.record_fill(order_request.lot_size, order_request.strike_price)
                self._logger.debug("state after record_fill: %s", state_machine.state)
                return result

            elif result.status == OrderStatus.PARTIALLY_FILLED:
                # Record partial fill and return - NO RETRY to prevent duplicates
                state_machine.record_partial_fill(result.filled_quantity or 0, result.average_fill_price or 0)
                return result

            elif result.status == OrderStatus.REJECTED:
                state_machine.try_transition_to(ExecutionState.REJECTED)
                return result

            elif result.status == OrderStatus.SUBMITTED:
                state_machine.record_submission(result.order_id or "unknown")
                return result

            else:
                # Unknown status - fail safe
                state_machine.try_transition_to(ExecutionState.FAILED)
                return result

        except (ValueError, OSError, AttributeError, ConnectionError) as e:
            # Execution failed - record failure
            state_machine.try_transition_to(ExecutionState.FAILED)
            return OrderResult(
                order_id="execution_failed",
                status=OrderStatus.REJECTED,
                reject_reason=f"Execution failed: {str(e)}",
                timestamp=now_ist()
            )

    def _attempt_order_execution(
        self,
        order_request: OrderRequest,
        execution_context: ExecutionContext
    ) -> OrderResult:
        """
        Attempt a single order execution.

        Args:
            order_request: The order to execute
            execution_context: Execution context

        Returns:
            OrderResult from the execution attempt
        """
        try:
            # Handle paper trading mode
            if (execution_context.execution_mode == ExecutionMode.PAPER or
                getattr(self.broker_port, '__class__.__name__', '') == 'PaperBrokerAdapter'):
                return self._execute_paper_order(order_request, execution_context)

            # Execute via broker port
            if hasattr(self.broker_port, 'place_order'):
                # Use broker's place_order method - it expects an Order object
                self._logger.debug("calling broker_port.place_order")
                place_order_result = self.broker_port.place_order(order_request)
                self._logger.debug("broker_port.place_order returned")

                if isinstance(place_order_result, OrderResult):
                    result = place_order_result
                elif isinstance(place_order_result, str):
                    # The broker returned an order ID string (proper interface)
                    order_id = place_order_result

                    # Check if the order was filled immediately by the broker
                    filled_quantity = 0
                    average_price = 0.0
                    if hasattr(self.broker_port, 'get_filled_quantity'):
                        filled_quantity = self.broker_port.get_filled_quantity(order_id) or 0
                    if hasattr(self.broker_port, 'get_average_price'):
                        average_price = self.broker_port.get_average_price(order_id) or 0.0

                    if filled_quantity > 0:
                        # The broker reports that the order was filled
                        result = OrderResult(
                            order_id=str(order_id) if order_id else "",
                            status=OrderStatus.FILLED,
                            filled_quantity=filled_quantity,
                            average_price=average_price,
                            commission=self._get_commission_from_broker(order_id, order_request),
                            timestamp=now_ist(),
                            broker_order_id=str(order_id) if order_id else None,
                            broker_timestamp=now_ist()
                        )
                    else:
                        # The order was placed but not yet filled
                        result = OrderResult(
                            order_id=str(order_id) if order_id else "",
                            status=OrderStatus.SUBMITTED if order_id else OrderStatus.REJECTED,
                            broker_order_id=str(order_id) if order_id else None,
                            timestamp=now_ist()
                        )
                else:
                    # Unexpected return type
                    self._logger.warning(f"Broker place_order returned unexpected type: {type(place_order_result)}")
                    # CRITICAL SAFETY: Never simulate execution for a real broker None response
                    result = OrderResult(
                        order_id="",
                        status=OrderStatus.REJECTED,
                        reject_reason=f"Broker returned unexpected type: {type(place_order_result)}",
                        timestamp=now_ist()
                    )

                res = self._validate_broker_result(result)
                self._logger.debug("_validate_broker_result returned status=%s, order_id=%s", res.status, res.order_id)
                return res
            else:
                # CRITICAL SAFETY: Never simulate execution for real broker
                self._logger.warning("Broker port does not have place_order method, rejecting order")
                return OrderResult(
                    order_id="",
                    status=OrderStatus.REJECTED,
                    reject_reason="Broker port has no place_order method",
                    timestamp=now_ist()
                )

        except (ValueError, OSError, AttributeError, ConnectionError) as e:
            self._logger.error(f"Error during order execution attempt: {e}", exc_info=True)
            return OrderResult(
                order_id="execution_error",
                status=OrderStatus.REJECTED,
                reject_reason=str(e),
                timestamp=now_ist()
            )

    def _validate_broker_result(self, result: OrderResult) -> OrderResult:
        """Validate broker result using ACK validator."""
        validation = self._ack_validator.validate_order_result(result)
        if not validation.is_valid:
            self._logger.error(f"Broker ACK validation failed: {validation.error_message}")
            return OrderResult(
                order_id=result.order_id or "validation_failed",
                status=OrderStatus.REJECTED,
                reject_reason=f"Broker ACK validation failed: {validation.error_message}",
                timestamp=now_ist()
            )
        if validation.warnings:
            for warning in validation.warnings:
                self._logger.warning(f"Broker ACK warning: {warning}")
        return result

    def _get_commission_from_broker(self, order_id: str, order_request) -> float:
        """
        Attempt to retrieve commission from broker order response.
        Falls back to estimated commission (0.05% of notional) if unavailable.
        """
        try:
            if hasattr(self.broker_port, 'get_order_details'):
                details = self.broker_port.get_order_details(order_id)
                if details and isinstance(details, dict):
                    charges = details.get('brokerage') or details.get('charges') or details.get('commission') or 0.0
                    return float(charges)
        except (KeyError, ValueError, TypeError, AttributeError):
            self._logger.debug("[SERVICES.EXECUTION_SERVICE] non-critical keyerror; non-critical valueerror; non-critical typeerror; non-critical attributeerror")
        # Fallback: estimate commission at 0.05% of notional trade value
        try:
            notional = float(order_request.strike_price) * int(order_request.lot_size)
            return round(notional * 0.0005, 2)
        except (ValueError, TypeError, AttributeError):
            return 0.0

    def _execute_paper_order(
        self,
        order_request: OrderRequest,
        execution_context: ExecutionContext
    ) -> OrderResult:
        """
        Execute a paper/simulated order.

        Args:
            order_request: The order to execute
            execution_context: Execution context

        Returns:
            OrderResult from the paper execution
        """
        try:
            # Simulate network delay - interruptible on shutdown
            if self._shutdown_event.wait(self.config.paper_fill_delay_ms / 1000.0):
                return OrderResult(
                    order_id="shutdown",
                    status=OrderStatus.REJECTED,
                    reject_reason="Shutdown requested during paper fill delay",
                    timestamp=now_ist()
                )

            # Generate a fake order ID
            order_id = f"paper_{int(time.time()*1000)}_{hash(order_request.symbol) % 10000}"

            # Determine fill price based on order type and market conditions
            if order_request.order_type == OrderType.MARKET:
                # For market orders, use current price with slippage
                base_price = self._get_current_price_for_symbol(order_request.symbol)
                slippage = base_price * (self.config.paper_fill_slippage_pct / 100.0)

                if order_request.direction.upper() == "BUY":
                    fill_price = base_price + slippage  # Pay more when buying
                else:
                    fill_price = base_price - slippage  # Receive less when selling

            elif order_request.order_type == OrderType.LIMIT:
                # For limit orders, use the limit price if it would execute
                base_price = self._get_current_price_for_symbol(order_request.symbol)
                if order_request.direction.upper() == "BUY" and order_request.price >= base_price:
                    fill_price = order_request.price
                elif order_request.direction.upper() == "SELL" and order_request.price <= base_price:
                    fill_price = order_request.price
                else:
                    # Limit order would not execute immediately
                    return OrderResult(
                        order_id=order_id,
                        status=OrderStatus.PENDING,
                        reject_reason="Limit order not executed - price not reached",
                        timestamp=now_ist()
                    )
            else:
                # For other order types (SL, SL-M), use the trigger price or current price
                fill_price = order_request.price or self._get_current_price_for_symbol(order_request.symbol)

            # Apply some randomness to make it feel realistic
            import random
            price_variation = random.uniform(-0.5, 0.5)  # ±0.5 points variation
            fill_price += price_variation

            # Ensure price is positive
            fill_price = max(0.01, fill_price)

            # Calculate commission (simplified)
            commission = abs(fill_price) * order_request.lot_size * 0.0005  # 0.05% commission

            return OrderResult(
                order_id=order_id,
                status=OrderStatus.FILLED,
                filled_quantity=order_request.lot_size,
                average_price=fill_price,
                commission=commission,
                timestamp=now_ist()
            )

        except (ValueError, OSError, AttributeError, ConnectionError) as e:
            self._logger.error(f"Error in paper order execution: {e}", exc_info=True)
            return OrderResult(
                order_id="paper_error",
                status=OrderStatus.REJECTED,
                reject_reason=str(e),
                timestamp=now_ist()
            )

    def _get_current_price_for_symbol(self, symbol: str) -> float:
        """
        Get current price for a symbol (used for paper trading simulation).

        Args:
            symbol: Trading symbol

        Returns:
            Current price for the symbol
        """
        # Check cache first
        if symbol in self._paper_price_cache:
            return self._paper_price_cache[symbol]

        # In a real implementation, this would come from market data
        # For now, return a reasonable default based on symbol
        default_prices = {
            "NIFTY": 19500.0,
            "BANKNIFTY": 44000.0,
            "FINNIFTY": 18500.0,
            "RELIANCE": 2400.0,
            "TCS": 3200.0,
            "HDFCBANK": 1400.0,
            "INFY": 1450.0,
            "ICICIBANK": 850.0,
            "KOTAKBANK": 1650.0,
            "LT": 2800.0,
            "SBIN": 580.0,
            "BHARTIARTL": 820.0,
            "ASIANPAINT": 2900.0,
            "MARUTI": 8800.0,
            "HINDUNILVR": 2200.0,
            "AXISBANK": 900.0
        }

        price = default_prices.get(symbol, 1000.0)  # Default to 1000 if unknown

        # Cache the price for a short time
        self._paper_price_cache[symbol] = price

        # Clear old cache entries periodically (simple approach)
        if len(self._paper_price_cache) > 50:
            # Remove oldest 10 entries
            keys_to_remove = list(self._paper_price_cache.keys())[:10]
            for key in keys_to_remove:
                del self._paper_price_cache[key]

        return price

    def _persist_trade_from_order(
        self,
        order_request: OrderRequest,
        order_result: OrderResult,
        execution_context: ExecutionContext
    ) -> None:
        """
        Persist a trade record from an executed order.

        Args:
            order_request: The original order request
            order_result: The result of the order execution
            execution_context: Execution context
        """
        try:
            if not self.trade_persistence:
                return

            # Only persist filled orders
            if order_result.filled_quantity <= 0:
                return

            # Convert to trade data format
            trade_data = {
                "symbol": order_request.symbol,
                "direction": order_request.direction.upper(),
                "strike_price": order_request.strike_price,
                "lot_size": order_request.lot_size,
                "entry_price": order_result.average_price,
                "entry_time": order_result.timestamp,
                "exit_price": 0.0,  # Will be updated when position is closed
                "exit_time": None,
                "exit_reason": "OPEN",  # Position is still open
                "gross_pnl": 0.0,  # Will be calculated when position is closed
                "brokerage": order_result.commission,
                "taxes": 0.0,  # Simplified - in reality would calculate based on P&L
                "net_pnl": -order_result.commission,  # Negative due to commissions
                "strategy": order_request.strategy_id or "UNKNOWN",
                "tags": [],  # Empty tags for now
                "regime_at_entry": None,  # Would come from market data/context
                "session_at_entry": None,  # Would come from market data/context
                "created_at": order_result.timestamp
            }

            # Save the trade record
            trade_id = self.trade_persistence.save_trade(trade_data)
            self._logger.debug(f"Trade persisted with ID {trade_id} from order {order_result.order_id}")

        except (ValueError, TypeError, OSError, AttributeError) as e:
            self._logger.error(f"Error persisting trade from order: {e}", exc_info=True)

    def _audit_trail_to_trade_data(
        self,
        audit_trail: ExecutionAuditTrail
    ) -> dict[str, Any] | None:
        """
        Convert an execution audit trail to trade data for persistence.

        Args:
            audit_trail: The execution audit trail to convert

        Returns:
            Trade data dictionary, or None if conversion fails
        """
        try:
            # This is a simplified conversion - in reality would be more complex
            if not audit_trail.order_result or audit_trail.order_result.filled_quantity <= 0:
                return None

            order_req = audit_trail.order_request
            order_res = audit_trail.order_result

            return {
                "symbol": order_req.symbol,
                "direction": order_req.direction.upper(),
                "strike_price": order_req.strike_price,
                "lot_size": order_req.lot_size,
                "entry_price": order_res.average_price,
                "entry_time": order_res.timestamp,
                "exit_price": 0.0,
                "exit_time": None,
                "exit_reason": "OPEN",
                "gross_pnl": 0.0,
                "brokerage": order_res.commission,
                "taxes": 0.0,
                "net_pnl": -order_res.commission,
                "strategy": order_req.strategy_id or "UNKNOWN",
                "tags": [],
                "regime_at_entry": None,
                "session_at_entry": None,
                "created_at": order_res.timestamp
            }
        except (ValueError, TypeError, KeyError, AttributeError) as e:
            self._logger.error(f"Error converting audit trail to trade data: {e}")
            return None

    def _escalate_order_modification_failed(
        self,
        order_id: str,
        reason: str,
        details: dict | None = None,
    ) -> None:
        """Escalate order modification failure via incident alerting (Telegram).

        Thread-safe - reports the incident to the singleton IncidentAlerting
        which dispatches via its registered callback (typically Telegram).
        Cooldown prevents alert storms for repeated failures on the same order.
        """
        try:
            from core.incident_alerting import get_incident_alerting
            alerting = get_incident_alerting()
            alerting.alert_order_modification_failed(
                order_id=order_id,
                reason=reason,
                details=details,
            )
        except (ImportError, AttributeError, OSError, ValueError) as exc:
            self._logger.debug(f"Incident alerting unavailable for order {order_id}: {exc}")

    def _poll_for_fill_status(
        self,
        order_id: str,
        timeout_seconds: int
    ) -> bool:
        """
        Poll for fill status when broker doesn't have wait_for_fill method.

        Args:
            order_id: The order ID to poll
            timeout_seconds: Maximum time to poll

        Returns:
            True if order filled, False if timeout
        """
        start_time = time.time()
        poll_interval = 0.5  # Start with 500ms intervals
        max_poll_interval = 5.0  # Max 5 seconds between polls

        while (time.time() - start_time) < timeout_seconds:
            # Check for shutdown signal
            if self._shutdown_event.is_set():
                self._logger.info("Shutdown requested, aborting fill poll for %s", order_id)
                return False

            try:
                # Check if we have a way to get filled quantity
                if hasattr(self.broker_port, 'get_filled_quantity'):
                    filled_qty = self.broker_port.get_filled_quantity(order_id) or 0
                    if filled_qty > 0:
                        return True
                elif hasattr(self.broker_port, 'get_order_status'):
                    status = self.broker_port.get_order_status(order_id)
                    if status in [OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED]:
                        return True

                # Wait before next poll (with exponential backoff) - interruptible on shutdown
                if self._shutdown_event.wait(min(poll_interval, max_poll_interval)):
                    self._logger.info("Shutdown requested during fill poll backoff for %s", order_id)
                    return False
                poll_interval = min(poll_interval * 1.5, max_poll_interval)  # Exponential backoff

            except (ValueError, OSError, AttributeError) as e:
                self._logger.debug(f"Error polling for fill status: {e}")
                if self._shutdown_event.wait(poll_interval):
                    return False

        return False  # Timeout reached
