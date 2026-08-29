"""Integration 1: Event Bus -> Mediator.

Wires the in-process Event Bus into the Mediator pattern so that all
events published through the Mediator are also broadcast on the Event Bus.
This enables decoupled module communication across the entire platform.

Usage:
    from core.integrations import wire_event_bus_to_mediator
    wire_event_bus_to_mediator()
"""

from __future__ import annotations

import logging
from typing import Any

_log = logging.getLogger(__name__)


def wire_event_bus_to_mediator() -> bool:
    """Wire the Event Bus into the Mediator's event publishing.

    This subscribes to the Mediator's internal event publishing and forwards
    all events to the Event Bus, enabling decoupled cross-module communication.

    Returns:
        True if wired successfully, False if dependencies missing.
    """
    try:
        from core.event_bus import get_event_bus
        from core.patterns.mediator import get_mediator

        bus = get_event_bus()
        mediator = get_mediator()

        # Store original publish method
        original_publish = mediator.publish

        async def bridged_publish(event: Any) -> None:
            """Publish event to both Mediator handlers and Event Bus."""
            # Forward to original Mediator handlers
            await original_publish(event)

            # Also broadcast on Event Bus
            event_name = type(event).__name__ if hasattr(event, "__class__") else str(event)
            event_data = event.__dict__ if hasattr(event, "__dict__") else {"event": str(event)}
            bus.publish(f"mediator.{event_name}", event_data, source="mediator")

        # Replace publish method
        mediator.publish = bridged_publish  # type: ignore[method-assign]

        _log.info("[INTEGRATION] Event Bus -> Mediator: WIRED")
        return True

    except ImportError as exc:
        _log.warning("[INTEGRATION] Event Bus -> Mediator: FAILED (%s)", exc)
        return False
    except Exception as exc:
        _log.warning("[INTEGRATION] Event Bus -> Mediator: ERROR (%s)", exc)
        return False


__all__ = ["wire_event_bus_to_mediator"]
