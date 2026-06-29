# =============================================================================
# RECONCILIATION CONTROLLER
# Extracted from index_app/index_trader.py for modularity (GAP-07).
# Responsibility: periodic reconciliation of internal state vs broker,
#                 ACK watchdog for stuck orders, live position reconciliation.
# =============================================================================

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

__all__ = [
    "ReconciliationController",
    "log",
]

log = logging.getLogger(__name__)


class ReconciliationController:
    """Manages periodic reconciliation of internal state with broker.

    Encapsulates:
    - Live position reconciliation (qty mismatch → hard halt)
    - Periodic ACK watchdog for stuck orders
    - Pending order reconciliation
    """

    def __init__(
        self,
        broker_api_enabled: bool,
        reconcile_halt_on_qty_mismatch: bool,
        broker_truth_reconciler: Any | None,
        legacy_broker: Any,
        positions: dict[str, Any],
        pos_lock: Any,
        trip_hard_halt_fn: Callable[[str], None],
        execution_service: Any = None,
    ) -> None:
        self._broker_api_enabled = broker_api_enabled
        self._reconcile_halt_on_qty_mismatch = reconcile_halt_on_qty_mismatch
        self._broker_truth_reconciler = broker_truth_reconciler
        self._legacy_broker = legacy_broker
        self._positions = positions
        self._pos_lock = pos_lock
        self._trip_hard_halt_fn = trip_hard_halt_fn
        self._execution_service = execution_service

    # ── public wiring setter (called after DI init) ──────────────────────

    def set_execution_service(self, execution_service: Any) -> None:
        """Set execution service reference after DI container init."""
        self._execution_service = execution_service

    def set_broker_truth_reconciler(self, reconciler: Any) -> None:
        """Set broker truth reconciler after broker init."""
        self._broker_truth_reconciler = reconciler

    # ── public API ──────────────────────────────────────────────────────

    def reconcile_live_positions(self) -> None:
        """Compare internal position quantities with broker truth.

        If both sides have positive qty and they differ, trips hard halt.
        """
        if not (self._broker_api_enabled and self._reconcile_halt_on_qty_mismatch):
            return

        if self._broker_truth_reconciler is not None:
            self._reconcile_via_broker_truth()
        else:
            self._reconcile_via_legacy_broker()

    def periodic_reconcile(self) -> None:
        """Periodic reconciliation: ACK watchdog + pending order check.

        Safe to call even if execution_service is not yet wired.
        """
        if self._execution_service is None:
            return
        try:
            ack_result = self._execution_service.run_ack_watchdog(
                max_ack_age_seconds=30.0
            )
            if ack_result.get("acknowledged", 0) > 0:
                log.info(
                    "[RECONCILE] Recovered %d stuck orders via ACK watchdog",
                    ack_result["acknowledged"],
                )
            if ack_result.get("errors", 0) > 0:
                log.warning(
                    "[RECONCILE] ACK watchdog errors: %d", ack_result["errors"]
                )

            if hasattr(self._execution_service, "reconcile_pending_orders"):
                recon_result = self._execution_service.reconcile_pending_orders()
                if not recon_result.get("is_clean", True):
                    log.warning(
                        "[RECONCILE] Pending order reconciliation found %d issues",
                        recon_result.get("issues_count", 0),
                    )
        except (ValueError, TypeError, KeyError, OSError) as exc:
            log.warning(
                "[RECONCILE] Error during reconciliation: %s", exc, exc_info=True
            )

    # ── private helpers ─────────────────────────────────────────────────

    def _reconcile_via_broker_truth(self) -> None:
        """Use broker truth reconciler for authoritative position comparison."""
        try:
            broker_positions = (
                self._broker_truth_reconciler.get_all_authoritative_positions()
            )
            with self._pos_lock:
                for name, pos in list(self._positions.items()):
                    local_qty = pos.get("qty", 0)
                    broker_pos = broker_positions.get(name)
                    broker_qty = broker_pos.get("qty", 0) if broker_pos else 0
                    if broker_qty != local_qty and broker_qty > 0 and local_qty > 0:
                        reason = (
                            f"qty mismatch: broker={broker_qty} vs "
                            f"local={local_qty} for {name}"
                        )
                        self._trip_hard_halt_fn(reason)
                        return
        except (ValueError, TypeError, KeyError, AttributeError, IndexError, OSError) as e:
            log.error("Broker truth reconciliation failed: %s", e)

    def _reconcile_via_legacy_broker(self) -> None:
        """Fallback to legacy broker shim for position comparison."""
        with self._pos_lock:
            for name, pos in list(self._positions.items()):
                broker_qty = 0
                try:
                    broker_qty = self._legacy_broker.get_position_qty(
                        name, pos.get("signal", ""), pos.get("strike", 0)
                    )
                except (
                    ValueError,
                    TypeError,
                    KeyError,
                    AttributeError,
                    IndexError,
                    OSError,
                ):
                    log.debug("Legacy broker position fetch failed for %s", name)
                local_qty = pos.get("qty", 0)
                if broker_qty != local_qty and broker_qty > 0 and local_qty > 0:
                    reason = (
                        f"qty mismatch: broker={broker_qty} vs "
                        f"local={local_qty} for {name}"
                    )
                    self._trip_hard_halt_fn(reason)
                    return
