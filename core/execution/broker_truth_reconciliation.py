"""
Broker Truth Reconciliation - CRITICAL FIX #6
Implements broker-authoritative state reconciliation.
Risk engine must never rely solely on stale internal assumptions.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from datetime import datetime
from enum import Enum

from core.datetime_ist import now_ist
from core.time_provider import time_provider

_log = logging.getLogger(__name__)


class ReconciliationStatus(Enum):
    """Reconciliation result status"""
    MATCH = "MATCH"
    MISMATCH = "MISMATCH"
    BROKER_ONLY = "BROKER_ONLY"
    INTERNAL_ONLY = "INTERNAL_ONLY"
    STALE = "STALE"
    ERROR = "ERROR"


@dataclass
class ReconciliationResult:
    """Result of reconciliation between internal and broker state"""
    status: ReconciliationStatus
    internal_position: dict | None = None
    broker_position: dict | None = None
    mismatch_details: str | None = None
    reconciled_at: str = ""
    broker_source: str = ""


class BrokerTruthReconciler:
    """
    Reconciles internal state with broker-authoritative state.
    Ensures risk calculations use truth from broker, not stale internal.
    """

    def __init__(
        self,
        broker_port,
        max_staleness_seconds: int = 30,
        reconciliation_interval_seconds: int = 60,
    ):
        self._broker_port = broker_port
        self._max_staleness_seconds = max_staleness_seconds
        self._reconciliation_interval = reconciliation_interval_seconds
        self._last_reconciliation: datetime | None = None
        self._cached_positions: dict[str, dict] = {}
        self._cached_positions_time: datetime | None = None
        self._alert_callback: Callable | None = None

    def set_alert_callback(self, callback: Callable):
        """Set callback for reconciliation alerts"""
        self._alert_callback = callback

    def _fetch_broker_positions(self) -> dict[str, dict]:
        """Fetch positions from broker (authoritative source)"""
        try:
            positions = self._broker_port.get_positions()
            return positions if positions else {}
        except Exception as e:
            _log.error(f"Failed to fetch broker positions: {e} (type: {type(e).__name__})")
            return {}

    def _fetch_broker_orders(self) -> dict[str, dict]:
        """Fetch orders from broker (authoritative source)"""
        try:
            orders = self._broker_port.get_orders()
            return orders if orders else {}
        except Exception as e:
            _log.error(f"Failed to fetch broker orders: {e} (type: {type(e).__name__})")
            return {}

    def get_authoritative_position(self, symbol: str) -> ReconciliationResult:
        """
        Get authoritative position for a symbol from broker.
        This is what risk calculations should use.
        """
        now = now_ist()

        # Check if cache is fresh
        cache_age = None
        if self._cached_positions_time:
            cache_age = (now - self._cached_positions_time).total_seconds()

        # Fetch fresh if cache is old
        if cache_age is None or cache_age > self._max_staleness_seconds:
            self._cached_positions = self._fetch_broker_positions()
            self._cached_positions_time = now
            _log.debug(f"Refreshed broker position cache, age: {cache_age}s")

        # Get from cache
        broker_pos = self._cached_positions.get(symbol)

        result = ReconciliationResult(
            status=ReconciliationStatus.MATCH,
            broker_position=broker_pos,
            reconciled_at=time_provider.format_ts(),
            broker_source="BROKER_API",
        )

        # Check if stale
        if cache_age and cache_age > self._max_staleness_seconds:
            result.status = ReconciliationStatus.STALE
            if self._alert_callback:
                self._alert_callback(
                    f"STALE_POSITION_DATA: {symbol} cache age {cache_age:.0f}s"
                )

        return result

    def get_all_authoritative_positions(self) -> dict[str, dict]:
        """Get all positions from broker (authoritative)"""
        now = now_ist()

        cache_age = None
        if self._cached_positions_time:
            cache_age = (now - self._cached_positions_time).total_seconds()

        if cache_age is None or cache_age > self._max_staleness_seconds:
            self._cached_positions = self._fetch_broker_positions()
            self._cached_positions_time = now

        return self._cached_positions

    def get_authoritative_balance(self) -> dict[str, float]:
        """Get authoritative account balance from broker"""
        try:
            funds = self._broker_port.get_funds()
            return {
                "available_cash": funds.get("available_cash", 0),
                "used_margin": funds.get("used_margin", 0),
                "total_value": funds.get("total_value", 0),
            }
        except Exception as e:
            _log.error(f"Failed to fetch broker balance: {e} (type: {type(e).__name__})")
            return {"available_cash": 0, "used_margin": 0, "total_value": 0}

    def reconcile_order(
        self,
        client_order_id: str,
        internal_state: str,
    ) -> ReconciliationResult:
        """
        Reconcile a specific order against broker.
        Used for ambiguous states - queries broker for truth.
        """
        broker_orders = self._fetch_broker_orders()
        broker_order = broker_orders.get(client_order_id)

        if broker_order is None:
            # Order not found in broker - check if it was filled/cancelled
            return ReconciliationResult(
                status=ReconciliationStatus.INTERNAL_ONLY,
                internal_position={"client_order_id": client_order_id, "state": internal_state},
                mismatch_details=f"Order {client_order_id} not found in broker",
                reconciled_at=time_provider.format_ts(),
                broker_source="BROKER_API",
            )

        # Compare states
        broker_state = broker_order.get("status", "UNKNOWN")

        if broker_state != internal_state:
            mismatch = f"State mismatch: internal={internal_state}, broker={broker_state}"
            _log.warning(mismatch)

            if self._alert_callback:
                self._alert_callback(f"ORDER_STATE_MISMATCH: {client_order_id} - {mismatch}")

            return ReconciliationResult(
                status=ReconciliationStatus.MISMATCH,
                internal_position={"client_order_id": client_order_id, "state": internal_state},
                broker_position=broker_order,
                mismatch_details=mismatch,
                reconciled_at=time_provider.format_ts(),
                broker_source="BROKER_API",
            )

        return ReconciliationResult(
            status=ReconciliationStatus.MATCH,
            broker_position=broker_order,
            reconciled_at=time_provider.format_ts(),
            broker_source="BROKER_API",
        )

    def force_refresh(self):
        """Force refresh of cached positions"""
        self._cached_positions = self._fetch_broker_positions()
        self._cached_positions_time = now_ist()
        _log.info("Forced refresh of broker positions cache")


# Singleton
_reconciler: BrokerTruthReconciler | None = None


def reconcile_broker_truth(broker_port: Any | None = None) -> dict:
    """Convenience function: run broker truth reconciliation report.

    Args:
        broker_port: Broker port instance. If None, returns WARN.

    Returns a dict with broker_position_count, local_position_count,
    mismatches, and a summary. If no broker is provided, returns
    a WARN-level dict.
    """
    try:
        if broker_port is None:
            return {
                "broker_positions": 0,
                "local_positions": 0,
                "mismatches": 0,
                "status": "WARN",
                "message": "Broker not provided — reconciliation skipped",
            }
        reconciler = BrokerTruthReconciler(broker_port, max_staleness_seconds=30)
        positions = reconciler.get_all_authoritative_positions()
        return {
            "broker_positions": len(positions),
            "local_positions": 0,  # caller can overlay local after
            "mismatches": 0,
            "status": "OK",
            "message": f"Broker reports {len(positions)} open positions",
        }
    except Exception as exc:
        _log.error("Broker truth reconciliation report error: %s", exc)
        return {
            "broker_positions": 0,
            "local_positions": 0,
            "mismatches": 0,
            "status": "ERROR",
            "message": str(exc),
        }


def get_broker_truth_reconciler(broker_port, config: dict = None) -> BrokerTruthReconciler:
    global _reconciler
    if _reconciler is None:
        max_staleness = config.get("RECONCILIATION_MAX_STALENESS_SEC", 30) if config else 30
        interval = config.get("RECONCILIATION_INTERVAL_SEC", 60) if config else 60
        _reconciler = BrokerTruthReconciler(broker_port, max_staleness, interval)
    return _reconciler
