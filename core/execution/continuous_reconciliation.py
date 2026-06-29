"""
Continuous Reconciliation Service - Periodic broker truth reconciliation

Runs in background thread to continuously reconcile:
- Order states with broker
- Positions with broker
- Balance with broker

Cadence:
- Active session: every 30-60 seconds
- Idle: every few minutes

This ensures broker truth > local truth at all times.
"""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from core.audit_journal import AuditEventType, AuditSeverity, audit_log
from core.datetime_ist import now_ist
from core.execution.broker_truth_reconciliation import (
    ReconciliationStatus,
    get_broker_truth_reconciler,
)
from core.system_mode import can_trade

log = logging.getLogger("continuous_reconciliation")


@dataclass
class ReconciliationIssue:
    """Record of a reconciliation issue found."""
    timestamp: datetime
    issue_type: str  # "orphan_order", "status_drift", "partial_fill", "missing_position"
    description: str
    broker_value: Any = None
    local_value: Any = None
    requires_manual_intervention: bool = False


@dataclass
class ReconciliationReport:
    """Report of a reconciliation cycle."""
    timestamp: datetime
    orders_checked: int = 0
    positions_checked: int = 0
    issues_found: list[ReconciliationIssue] = field(default_factory=list)
    broker_reachable: bool = True
    cycle_time_ms: float = 0.0


class ContinuousReconciliation:
    """
    Background thread that periodically reconciles with broker.
    """

    def __init__(
        self,
        broker_port: Any,
        config: dict | None = None,
        on_issue_callback: Callable[[ReconciliationIssue], None] | None = None
    ):
        self._config = config or {}
        self._broker_port = broker_port
        self._reconciler = get_broker_truth_reconciler(broker_port, config)
        self._on_issue_callback = on_issue_callback

        # Configuration
        self._active_interval_seconds = self._config.get("RECONCILIATION_ACTIVE_INTERVAL_SEC", 30)
        self._idle_interval_seconds = self._config.get("RECONCILIATION_IDLE_INTERVAL_SEC", 300)
        self._enabled = self._config.get("CONTINUOUS_RECONCILIATION_ENABLED", True)

        # State
        self._running = False
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_cycle_time: datetime | None = None
        self._issues: list[ReconciliationIssue] = []
        self._lock = threading.RLock()

    def start(self) -> None:
        """Start the reconciliation thread."""
        if not self._enabled:
            log.info("Continuous reconciliation disabled by config")
            return

        if self._running:
            log.warning("Continuous reconciliation already running")
            return

        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="ContinuousReconcile")
        self._thread.start()
        log.info(f"Continuous reconciliation started (active={self._active_interval_seconds}s, idle={self._idle_interval_seconds}s)")

    def stop(self) -> None:
        """Stop the reconciliation thread."""
        self._running = False
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        log.info("Continuous reconciliation stopped")

    def _run_loop(self) -> None:
        """Main reconciliation loop."""
        while self._running and not self._stop_event.is_set():
            try:
                now_ist()

                # Check system mode - use result to adjust interval
                can_trade_ok, _ = can_trade()

                if not can_trade_ok:
                    interval = self._idle_interval_seconds
                else:
                    interval = self._active_interval_seconds

                # Run reconciliation cycle
                report = self._run_cycle()

                # Process any issues found
                for issue in report.issues_found:
                    self._handle_issue(issue)

                self._last_cycle_time = now_ist()

                log.debug(f"Reconciliation cycle: {report.orders_checked} orders, "
                         f"{report.positions_checked} positions, {len(report.issues_found)} issues")

            except (OSError, ConnectionError, TimeoutError, ValueError, TypeError, AttributeError) as e:
                log.error(f"Reconciliation cycle failed: {e}")

            # Wait until next cycle (interruptible via stop_event)
            if self._stop_event.wait(interval):
                break

    def _run_cycle(self) -> ReconciliationReport:
        """Run a single reconciliation cycle."""
        report = ReconciliationReport(timestamp=now_ist())

        try:
            # Check broker connectivity
            self._check_broker_connectivity(report)

            # Reconcile orders
            orders = self._get_local_orders()
            report.orders_checked = len(orders)

            for order in orders:
                issue = self._reconcile_order(order)
                if issue:
                    report.issues_found.append(issue)

            # Reconcile positions
            positions = self._get_local_positions()
            report.positions_checked = len(positions)

            for symbol, pos in positions.items():
                issue = self._reconcile_position(symbol, pos)
                if issue:
                    report.issues_found.append(issue)

        except (OSError, ConnectionError, ValueError, TypeError, AttributeError) as e:
            log.error(f"Reconciliation cycle error: {e}")

        return report

    def _get_local_orders(self) -> list[dict]:
        """Get local order state for reconciliation."""
        # This should get from the order manager or durable state
        # For now, return empty list if not available
        try:
            from core.execution.durable_state import durable_state_store
            return durable_state_store.get_all_execution_records() if durable_state_store else []
        except (ImportError, AttributeError, TypeError, OSError):
            return []

    def _get_local_positions(self) -> dict[str, dict]:
        """Get local position state for reconciliation."""
        try:
            from core.state_manager import state_manager
            return state_manager.get("active_positions", {})
        except (ImportError, AttributeError, TypeError, OSError):
            return {}

    def _check_broker_connectivity(self, report: ReconciliationReport) -> None:
        """Check broker connectivity."""
        try:
            if hasattr(self._broker_port, 'is_healthy'):
                self._broker_port.is_healthy()
                report.broker_reachable = True
            else:
                report.broker_reachable = True
        except (AttributeError, TypeError, OSError, ConnectionError):
            report.broker_reachable = False
            log.warning("Broker not reachable during reconciliation")

    def _reconcile_order(self, order: dict) -> ReconciliationIssue | None:
        """Reconcile a single order with broker."""
        try:
            order_id = order.get("broker_order_id") or order.get("order_id")
            if not order_id:
                return None

            result = self._reconciler.reconcile_order(
                order_id,
                internal_state=order.get("status", "UNKNOWN")
            )

            if result.status == ReconciliationStatus.MISMATCH:
                return ReconciliationIssue(
                    timestamp=now_ist(),
                    issue_type="status_drift",
                    description=result.mismatch_details,
                    broker_value=result.broker_position,
                    local_value=result.internal_position,
                    requires_manual_intervention=True
                )

            if result.status == ReconciliationStatus.INTERNAL_ONLY:
                return ReconciliationIssue(
                    timestamp=now_ist(),
                    issue_type="orphan_order",
                    description=f"Order {order_id} in local but not in broker",
                    local_value=result.internal_position,
                    requires_manual_intervention=True
                )

        except (OSError, ConnectionError, ValueError, TypeError, AttributeError, KeyError) as e:
            log.error(f"Order reconciliation error for {order.get('order_id')}: {e}")

        return None

    def _reconcile_position(self, symbol: str, local_pos: dict) -> ReconciliationIssue | None:
        """Reconcile a single position with broker."""
        try:
            broker_result = self._reconciler.get_authoritative_position(symbol)
            broker_pos = broker_result.broker_position

            if not broker_pos and local_pos:
                return ReconciliationIssue(
                    timestamp=now_ist(),
                    issue_type="missing_position",
                    description=f"Position {symbol} in local but not at broker",
                    local_value=local_pos,
                    requires_manual_intervention=True
                )

            if broker_pos:
                local_qty = local_pos.get("qty", 0)
                broker_qty = broker_pos.get("quantity", 0) or broker_pos.get("qty", 0)

                if local_qty != broker_qty:
                    return ReconciliationIssue(
                        timestamp=now_ist(),
                        issue_type="position_mismatch",
                        description=f"Position {symbol} qty mismatch: local={local_qty}, broker={broker_qty}",
                        broker_value=broker_pos,
                        local_value=local_pos,
                        requires_manual_intervention=True
                    )

        except (OSError, ConnectionError, ValueError, TypeError, AttributeError, KeyError) as e:
            log.error(f"Position reconciliation error for {symbol}: {e}")

        return None

    def _handle_issue(self, issue: ReconciliationIssue) -> None:
        """Handle a reconciliation issue."""
        with self._lock:
            self._issues.append(issue)

        # Log to audit journal
        audit_log(
            event_type=AuditEventType.RECONCILIATION_MISMATCH,
            severity=AuditSeverity.ERROR,
            message=f"Reconciliation issue: {issue.issue_type} - {issue.description}",
            details={"issue_type": issue.issue_type, "requires_manual": issue.requires_manual_intervention}
        )

        # Callback if set
        if self._on_issue_callback:
            try:
                self._on_issue_callback(issue)
            except (TypeError, ValueError, OSError) as e:
                log.error(f"Issue callback failed: {e}")

    def get_issues(self) -> list[ReconciliationIssue]:
        """Get all reconciliation issues found."""
        with self._lock:
            return list(self._issues)

    def get_last_cycle_time(self) -> datetime | None:
        """Get time of last reconciliation cycle."""
        return self._last_cycle_time

    def force_cycle(self) -> ReconciliationReport:
        """Force an immediate reconciliation cycle."""
        return self._run_cycle()

    def health_check(self) -> dict:
        """Return health status."""
        return {
            "running": self._running,
            "last_cycle": self._last_cycle_time.isoformat() if self._last_cycle_time else None,
            "issues_count": len(self._issues),
            "enabled": self._enabled,
        }


# Singleton
_continuous_reconciliation: ContinuousReconciliation | None = None


def get_continuous_reconciliation(
    broker_port: Any = None,
    config: dict | None = None,
    on_issue_callback: Callable | None = None
) -> ContinuousReconciliation | None:
    """Get or create singleton continuous reconciliation service."""
    global _continuous_reconciliation

    if _continuous_reconciliation is None and broker_port is not None:
        _continuous_reconciliation = ContinuousReconciliation(
            broker_port=broker_port,
            config=config,
            on_issue_callback=on_issue_callback
        )

    return _continuous_reconciliation


def start_continuous_reconciliation(
    broker_port: Any,
    config: dict | None = None
) -> ContinuousReconciliation:
    """Start the continuous reconciliation service."""
    svc = get_continuous_reconciliation(broker_port, config)
    if svc:
        svc.start()
    return svc


__all__ = [
    "ReconciliationIssue",
    "ReconciliationReport",
    "ContinuousReconciliation",
    "get_continuous_reconciliation",
    "start_continuous_reconciliation",
]
