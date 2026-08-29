"""Integration 2: CQRS -> Event Sourcing.

Wires the CQRS Command Bus into the Event Store so every command execution
is automatically recorded as an event. This enables deterministic replay,
audit trails, and state recovery from command history.

Usage:
    from core.integrations import wire_cqrs_to_event_sourcing
    wire_cqrs_to_event_sourcing()
"""

from __future__ import annotations

import logging

_log = logging.getLogger(__name__)


def wire_cqrs_to_event_sourcing() -> bool:
    """Wire CQRS Command Bus executions into the Event Store.

    Adds middleware to the Command Bus that automatically records every
    command execution as an event in the Event Store.

    Returns:
        True if wired successfully, False if dependencies missing.
    """
    try:
        from core.event_sourcing import get_event_store

        store = get_event_store()
        bus = get_command_bus()

        def event_sourcing_middleware(ctx, cmd_bus):
            """Middleware: Record command execution as event."""
            try:
                store.append(
                    event_type=f"cqrs.{ctx.command_type}",
                    stream="cqrs",
                    data={
                        "command_type": ctx.command_type,
                        "command_data": ctx.command.to_dict() if hasattr(ctx.command, "to_dict") else {},
                    },
                    metadata={"source": "cqrs_middleware"},
                )
            except Exception as exc:
                _log.debug("[INTEGRATION] CQRS->ES event recording failed: %s", exc)
            return None  # Continue middleware pipeline

        bus.use(event_sourcing_middleware)
        _log.info("[INTEGRATION] CQRS -> Event Sourcing: WIRED")
        return True

    except (ImportError, AttributeError) as exc:
        _log.warning("[INTEGRATION] CQRS -> Event Sourcing: FAILED (%s)", exc)
        return False
    except Exception as exc:
        _log.warning("[INTEGRATION] CQRS -> Event Sourcing: ERROR (%s)", exc)
        return False


_command_bus_instance = None


def get_command_bus():
    """Get or create the CQRS Command Bus singleton."""
    global _command_bus_instance
    if _command_bus_instance is not None:
        return _command_bus_instance

    try:
        from core.cqrs.command_bus import CommandBus
        # Try resolving from DI container first
        try:
            from core.di_container import container
            bus = container.try_resolve(CommandBus)
            if bus is not None:
                _command_bus_instance = bus
                return bus
        except (ImportError, AttributeError):
            pass
        # Fallback: create new instance and cache as singleton
        bus = CommandBus()
        _command_bus_instance = bus
        return bus
    except ImportError:
        raise


__all__ = ["wire_cqrs_to_event_sourcing", "get_command_bus"]
