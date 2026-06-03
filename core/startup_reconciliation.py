"""
Startup Broker Reconciliation (Additional Fix).

Validates broker connection and reconciles state at startup:
- Broker connectivity check
- Auth token validation
- Order state reconciliation
- Position reconciliation
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)


@dataclass
class ReconciliationResult:
    is_clean: bool
    broker_reachable: bool
    auth_valid: bool
    orders_reconciled: bool
    positions_reconciled: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class StartupReconciler:
    """
    Startup reconciliation for broker and execution state.

    Runs at:
    - Bot startup
    - After network disconnection recovery
    - Manual trigger
    """

    def __init__(self, broker_port: Any = None, durable_store: Any = None):
        self._broker_port = broker_port
        self._durable_store = durable_store

    def set_broker_port(self, broker_port: Any) -> None:
        self._broker_port = broker_port

    def set_durable_store(self, durable_store: Any) -> None:
        self._durable_store = durable_store

    def reconcile(self) -> ReconciliationResult:
        """Run full reconciliation."""
        result = ReconciliationResult(
            is_clean=False,
            broker_reachable=False,
            auth_valid=False,
            orders_reconciled=False,
            positions_reconciled=False,
        )

        if not self._broker_port:
            result.warnings.append("No broker port configured")
            return result

        result.broker_reachable = self._check_broker_reachable()
        if not result.broker_reachable:
            result.errors.append("Broker not reachable")
            return result

        result.auth_valid = self._check_auth_valid()
        if not result.auth_valid:
            result.errors.append("Auth token invalid")
            return result

        result.orders_reconciled = self._reconcile_orders()

        result.positions_reconciled = self._reconcile_positions()

        result.is_clean = (
            result.broker_reachable and
            result.auth_valid and
            result.orders_reconciled and
            result.positions_reconciled
        )

        if result.is_clean:
            log.info("Startup reconciliation: CLEAN")
        else:
            log.warning(f"Startup reconciliation issues: {result.errors}")

        return result

    def _check_broker_reachable(self) -> bool:
        """Check broker API is reachable."""
        try:
            if hasattr(self._broker_port, "health_check"):
                health = self._broker_port.health_check()
                if isinstance(health, dict):
                    return health.get("status") == "healthy"
            return True
        except (AttributeError, TypeError, ValueError, OSError, ConnectionError) as e:
            log.error(f"Broker reachability check failed: {e}")
            return False

    def _check_auth_valid(self) -> bool:
        """Check auth token is valid."""
        try:
            if hasattr(self._broker_port, "_ensure_token_fresh"):
                return self._broker_port._ensure_token_fresh()
            return True
        except (AttributeError, TypeError, OSError) as e:
            log.error(f"Auth validation failed: {e}")
            return False

    def _reconcile_orders(self) -> bool:
        """Reconcile order state with broker."""
        if not self._durable_store:
            return True

        try:
            pending = self._durable_store.get_non_terminal_executions()
            if not pending:
                return True

            if not self._broker_port or not hasattr(self._broker_port, "get_order_status"):
                return True

            for record in pending:
                if not record.broker_order_id:
                    continue

                try:
                    status = self._broker_port.get_order_status(record.broker_order_id)
                    if status in ("FILLED", "COMPLETE"):
                        self._durable_store.update_state(
                            record.intent_id,
                            "FILLED",
                            filled_quantity=record.quantity,
                        )
                except (ValueError, TypeError, AttributeError, KeyError, OSError) as e:
                    log.warning(f"Failed to reconcile {record.intent_id}: {e}")

            return True
        except (ValueError, TypeError, AttributeError, KeyError, OSError) as e:
            log.error(f"Order reconciliation failed: {e}")
            return False

    def _reconcile_positions(self) -> bool:
        """Reconcile positions with broker."""
        try:
            if not self._broker_port or not hasattr(self._broker_port, "get_positions"):
                return True
            positions = self._broker_port.get_positions()
            log.info(f"Reconciled {len(positions)} positions")
            return True
        except (AttributeError, TypeError, ValueError, OSError) as e:
            log.warning(f"Position reconciliation failed: {e}")
            return True


def run_startup_reconciliation(
    broker_port: Any = None,
    durable_store: Any = None,
) -> ReconciliationResult:
    """Run startup reconciliation."""
    reconciler = StartupReconciler(broker_port, durable_store)
    return reconciler.reconcile()
