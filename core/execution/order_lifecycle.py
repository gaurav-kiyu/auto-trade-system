"""Order Lifecycle Management — Stale Order Handler & ACK Watchdog.

Extracted from core.services.execution_service.ExecutionService for SRP compliance.
Provides standalone functions for managing order lifecycle:
- Cancel orders stuck in non-terminal states (zombie prevention)
- Detect orders stuck in SUBMITTED without broker ACK (ACK timeout watchdog)

Usage:
    from core.execution.order_lifecycle import run_stale_order_timeout, run_ack_watchdog
"""

from __future__ import annotations

import logging
from datetime import datetime

from core.datetime_ist import now_ist
from core.execution.deterministic_state_machine import ExecutionState, get_execution_state_manager

_log = logging.getLogger(__name__)


def run_stale_order_timeout(
    broker_port: object,
    logger: logging.Logger | None = None,
    max_stale_seconds: float = 300.0,
) -> dict:
    """Cancel orders stuck in non-terminal states beyond the stale threshold.

    Scans all state machines for orders that have been in a non-terminal,
    non-progressing state (SUBMITTED, ACKNOWLEDGED, CANCEL_PENDING,
    PENDING_SUBMISSION) for longer than max_stale_seconds, then attempts
    to cancel them via the broker and transitions the machine to FAILED.

    This prevents "zombie orders" from blocking capacity and consuming
    risk capital indefinitely.

    Args:
        broker_port: Broker port with cancel_order method.
        logger: Optional logger instance. Falls back to module-level logger.
        max_stale_seconds: Maximum time (in seconds) an order can remain
                           in a non-terminal state before being cancelled.
                           Default 300 (5 minutes).

    Returns:
        dict with keys: checked, cancelled, already_terminal, errors

    """
    _logger_inst = logger or _log
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

                _logger_inst.warning(
                    "Stale order detected: client_order_id=%s, state=%s, "
                    "age=%.1fs, broker_order_id=%s",
                    machine.client_order_id,
                    stale_state.value,
                    age_seconds,
                    broker_order_id or "N/A",
                )

                # Attempt to cancel via broker if we have a broker order ID
                if broker_order_id and hasattr(broker_port, "cancel_order"):
                    try:
                        cancel_success = broker_port.cancel_order(broker_order_id)
                        if cancel_success:
                            _logger_inst.info(
                                "Stale order cancelled via broker: %s", broker_order_id,
                            )
                    except (ValueError, OSError, ConnectionError) as ex:
                        _logger_inst.warning(
                            "Failed to cancel stale order via broker: %s - %s",
                            broker_order_id, ex,
                        )

            # Use record_failure OUTSIDE the lock to avoid deadlock
            # with persistence callbacks. record_failure sets error_message
            # BEFORE the transition, ensuring the callback sees the correct reason.
            machine.record_failure(
                f"Stale order timeout ({age_seconds:.0f}s in {stale_state.value})",
            )
            result["cancelled"] += 1

    except (ValueError, OSError, AttributeError) as e:
        _logger_inst.error(f"Error in stale order timeout run: {e}", exc_info=True)
        result["errors"] += 1

    if result["cancelled"] > 0:
        _logger_inst.warning(
            "Stale order timeout: cancelled %d of %d checked orders",
            result["cancelled"],
            result["checked"],
        )
    return result


def run_ack_watchdog(
    broker_port: object,
    logger: logging.Logger | None = None,
    max_ack_age_seconds: float = 30.0,
) -> dict:
    """Find orders stuck in SUBMITTED state without broker ACK.

    Queries the broker for current order status. If the order has been
    acknowledged/rejected/filled by the broker, updates the state machine.
    If still pending, logs a warning.

    Args:
        broker_port: Broker port with get_order_status method.
        logger: Optional logger instance. Falls back to module-level logger.
        max_ack_age_seconds: Maximum time to wait for broker ACK.

    Returns:
        dict with keys: checked, acknowledged, still_pending, errors

    """
    # logger parameter is accepted for signature compatibility; module-level _log is used
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
            status = broker_port.get_order_status(broker_id)
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


__all__ = [
    "run_stale_order_timeout",
    "run_ack_watchdog",
]
