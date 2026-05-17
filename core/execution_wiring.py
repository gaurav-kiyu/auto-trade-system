"""
Execution Safety Wiring (Final Integration).

This module wires all the new execution safety components together
and provides a single integration point for index_trader.py.

Components wired:
- DurableExecutionStore (persistence)
- BrokerAckValidator (ACK validation)
- BrokerStateHandler (unknown state handling)
- BrokerErrorClassifier (retry classification)
- StartupReconciler (startup validation)
- ComponentHealthMonitor (health tracking)
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


class ExecutionSafetyWiring:
    """
    Central wiring for all execution safety components.
    
    Use this class to initialize all safety components together
    and get references to individual components.
    """

    def __init__(
        self,
        db_path: str = "trades.db",
        broker_port: Any = None,
    ):
        self._db_path = db_path
        self._broker_port = broker_port
        self._initialized = False

        self.durable_store = None
        self.ack_validator = None
        self.state_handler = None
        self.error_classifier = None
        self.startup_reconciler = None
        self.health_monitor = None

    def initialize(self) -> None:
        """Initialize all safety components."""
        if self._initialized:
            return

        log.info("Initializing execution safety wiring...")

        from core.execution.durable_state import DurableExecutionStore
        durable_db = self._db_path.replace("trades.db", "execution_state.db")
        self.durable_store = DurableExecutionStore(durable_db)
        log.info("  - DurableExecutionStore initialized")

        from core.execution.broker_ack_validator import BrokerAckValidator
        broker_type = BrokerAckValidator.detect_broker_type(self._broker_port)
        self.ack_validator = BrokerAckValidator(broker_type)
        log.info(f"  - BrokerAckValidator initialized ({broker_type.value})")

        from core.execution.broker_state_handler import create_state_handler
        self.state_handler = create_state_handler(max_retries=3, timeout_seconds=30)
        log.info("  - BrokerStateHandler initialized")

        from core.execution_error_classifier import BrokerErrorClassifier
        self.error_classifier = BrokerErrorClassifier()
        log.info("  - BrokerErrorClassifier initialized")

        from core.startup_reconciliation import StartupReconciler
        self.startup_reconciler = StartupReconciler(
            broker_port=self._broker_port,
            durable_store=self.durable_store,
        )
        log.info("  - StartupReconciler initialized")

        from core.component_health_monitor import get_health_monitor
        self.health_monitor = get_health_monitor()
        self.health_monitor.register("durable_store", self.durable_store)
        if self._broker_port:
            self.health_monitor.register("broker_port", self._broker_port)
        log.info("  - ComponentHealthMonitor initialized")

        self._initialized = True
        log.info("Execution safety wiring complete")

    def run_startup_reconciliation(self) -> dict:
        """Run startup reconciliation and return results."""
        if not self._initialized:
            self.initialize()

        if not self.startup_reconciler:
            return {"error": "Not initialized"}

        result = self.startup_reconciler.reconcile()
        return {
            "is_clean": result.is_clean,
            "broker_reachable": result.broker_reachable,
            "auth_valid": result.auth_valid,
            "orders_reconciled": result.orders_reconciled,
            "positions_reconciled": result.positions_reconciled,
            "errors": result.errors,
            "warnings": result.warnings,
        }

    def get_health_status(self) -> str:
        """Get health status of all components."""
        if not self._initialized:
            self.initialize()

        if not self.health_monitor:
            return "Health monitor not initialized"

        return self.health_monitor.format_status()

    def check_trading_allowed(self) -> tuple[bool, str]:
        """Check if trading is allowed based on all safety components."""
        if not self._initialized:
            self.initialize()

        if not self.durable_store:
            return False, "Durable store not initialized"

        pending = self.durable_store.get_non_terminal_executions()
        if len(pending) > 10:
            return False, f"Too many pending executions: {len(pending)}"

        return True, "Trading allowed"


def create_safety_wiring(
    db_path: str = "trades.db",
    broker_port: Any = None,
) -> ExecutionSafetyWiring:
    """Factory function to create safety wiring."""
    wiring = ExecutionSafetyWiring(db_path=db_path, broker_port=broker_port)
    wiring.initialize()
    return wiring
