"""Trading Reconciliation Service — position reconciliation, daily reset, and periodic checks.

Extracted from ``index_trader.py`` (DEBT-008) to reduce the monolith and
centralise all reconciliation and lifecycle-management logic.

Responsibilities:
1. ``reconcile_positions_live()`` — Compare internal positions with broker truth
2. ``periodic_reconcile()`` — ACK watchdog + pending order reconciliation
3. ``daily_reset()`` — Daily portfolio reset with zombie PnL detection
4. ``check_pending_reconciliation()`` — Zombie PnL check and clear
5. ``check_hard_stops_via_risk()`` — Risk service hard stop check
6. ``reload_config_handler()`` — Hot-reload config from disk + env vars
"""

from __future__ import annotations

import logging
from typing import Any, Callable


__all__ = [
    "check_hard_stops_via_risk",
    "check_pending_reconciliation",
    "daily_reset",
    "periodic_reconcile",
    "reconcile_positions_live",
    "reload_config_handler",
]

_log = logging.getLogger(__name__)


def reconcile_positions_live(
    broker_api_enabled: bool,
    reconcile_halt_on_qty_mismatch: bool,
    broker_truth_reconciler: Any,
    positions: dict[str, Any],
    pos_lock: Any,
    broker: Any,
    trip_halt_fn: Callable[[str], None],
    log_fn: Callable = _log,
) -> None:
    """Compare internal positions with broker truth.

    If quantities differ between broker and local state for the same
    position, trips a hard halt to prevent inconsistent execution.
    """
    if not (broker_api_enabled and reconcile_halt_on_qty_mismatch):
        return

    if broker_truth_reconciler is not None:
        try:
            broker_positions = broker_truth_reconciler.get_all_authoritative_positions()
            with pos_lock:
                for name, pos in list(positions.items()):
                    local_qty = pos.get("qty", 0)
                    broker_pos = broker_positions.get(name)
                    broker_qty = broker_pos.get("qty", 0) if broker_pos else 0
                    if broker_qty != local_qty and broker_qty > 0 and local_qty > 0:
                        reason = f"qty mismatch: broker={broker_qty} vs local={local_qty} for {name}"
                        trip_halt_fn(reason)
                        return
        except (ValueError, TypeError, KeyError, AttributeError, IndexError, OSError) as e:
            log_fn.error("Broker truth reconciliation failed: %s", e)
    else:
        # Fallback to legacy method
        with pos_lock:
            for name, pos in list(positions.items()):
                broker_qty = 0
                try:
                    broker_qty = broker.get_position_qty(
                        name, pos.get("signal", ""), pos.get("strike", 0),
                    )
                except (ValueError, TypeError, KeyError, AttributeError, IndexError, OSError):
                    log_fn.debug("Legacy broker position fetch failed for %s", name)
                local_qty = pos.get("qty", 0)
                if broker_qty != local_qty and broker_qty > 0 and local_qty > 0:
                    reason = f"qty mismatch: broker={broker_qty} vs local={local_qty} for {name}"
                    trip_halt_fn(reason)
                    return


def periodic_reconcile(
    execution_service: Any,
    log_fn: Callable = _log,
) -> None:
    """Periodic reconciliation: ACK watchdog + pending order reconciliation.

    Args:
        execution_service: The ``ExecutionService`` instance (may be None).
        log_fn: Logger.
    """
    if execution_service is None:
        return
    try:
        ack_result = execution_service.run_ack_watchdog(max_ack_age_seconds=30.0)
        if ack_result.get("acknowledged", 0) > 0:
            log_fn.info(
                "[RECONCILE] Recovered %d stuck orders via ACK watchdog",
                ack_result["acknowledged"],
            )
        if ack_result.get("errors", 0) > 0:
            log_fn.warning(
                "[RECONCILE] ACK watchdog errors: %d", ack_result["errors"],
            )

        # Reconcile pending orders with broker positions
        if hasattr(execution_service, "reconcile_pending_orders"):
            recon_result = execution_service.reconcile_pending_orders()
            if not recon_result.get("is_clean", True):
                log_fn.warning(
                    "[RECONCILE] Pending order reconciliation found %d issues",
                    recon_result.get("issues_count", 0),
                )
    except (ValueError, TypeError, KeyError, OSError) as exc:
        log_fn.warning("[RECONCILE] Error during reconciliation: %s", exc, exc_info=True)


def daily_reset(
    portfolio_service: Any,
    reentry_trackers: dict[str, Any],
    send_fn: Callable,
    log_fn: Callable = _log,
) -> None:
    """Perform daily portfolio reset with zombie PnL detection.

    Args:
        portfolio_service: Portfolio service instance.
        reentry_trackers: Dict of reentry tracker instances.
        send_fn: Notification function.
        log_fn: Logger.
    """
    pending_adj = 0.0
    try:
        pending_adj = float(portfolio_service.get_pending_adjustment())
    except (ValueError, TypeError, KeyError, AttributeError, IndexError, OSError):
        pending_adj = 0.0

    if pending_adj != 0.0:
        send_fn(
            f"ZOMBIE PnL detected during reset: {pending_adj}",
            critical=True,
        )

    if portfolio_service.handle_daily_reset():
        log_fn.info("Daily portfolio reset performed successfully.")

    for _rt_name, _rt in list(reentry_trackers.items()):
        try:
            _rt.reset_daily()
        except (ValueError, TypeError, KeyError, AttributeError, IndexError, OSError):
            log_fn.debug("Reentry tracker daily reset failed for %s", _rt_name)


def check_pending_reconciliation(
    portfolio_service: Any,
    state_lock: Any,
    state_manager: Any,
    send_fn: Callable,
) -> None:
    """Check for zombie PnL and clear pending adjustment.

    Args:
        portfolio_service: Portfolio service instance.
        state_lock: Thread lock for state access.
        state_manager: State manager for updating state.
        send_fn: Notification function.
    """
    adj = portfolio_service.get_pending_adjustment()
    if adj != 0:
        send_fn(
            f"ZOMBIE PnL: capital_adj_pending={adj} - requires manual reconciliation",
            critical=True,
        )
        return
    with state_lock:
        state_manager.set("capital_adj_pending", 0.0)


def check_hard_stops_via_risk(mandate_service: Any) -> tuple[bool, str]:
    """Delegate hard stop check to mandate service.

    Args:
        mandate_service: The mandate service instance.

    Returns:
        Tuple of (ok, reason).
    """
    return mandate_service._check_hard_stops_via_risk()


def reload_config_handler() -> dict:
    """Hot-reload configuration from disk + env vars.

    Returns:
        Status dict with ``status`` and ``detail`` keys.
    """
    try:
        from core.config_bootstrap import get_effective_config

        merged = get_effective_config()
        return {"status": "ok", "detail": "Config reloaded via SecureConfig", "keys": len(merged)}
    except (ValueError, TypeError, KeyError, AttributeError, IndexError, OSError) as e:
        _log.exception("Config reload failed")
        return {"status": "error", "detail": str(e)}
