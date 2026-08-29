"""Integration 5: Distributed Tracing -> Mediator.

Wires the Distributed Tracer into the Mediator pattern so that every
command and query executed through the Mediator is automatically wrapped
with tracing spans. This enables end-to-end visibility of all operations.

Usage:
    from core.integrations import wire_tracing_to_mediator
    wire_tracing_to_mediator()
"""

from __future__ import annotations

import logging
from typing import Any

_log = logging.getLogger(__name__)


def wire_tracing_to_mediator() -> bool:
    """Wire Distributed Tracing into the Mediator.

    Wraps the Mediator's send() and publish() methods with tracing spans.

    Returns:
        True if wired successfully, False if dependencies missing.
    """
    try:
        from core.distributed_tracing import get_tracer
        from core.patterns.mediator import get_mediator

        tracer = get_tracer()
        mediator = get_mediator()

        # Wrap send() with tracing
        original_send = mediator.send

        async def traced_send(command: Any, **context_kwargs: Any) -> Any:
            command_name = type(command).__name__ if hasattr(command, "__class__") else "UnknownCommand"
            with tracer.trace(f"mediator.send.{command_name}"):
                return await original_send(command, **context_kwargs)

        mediator.send = traced_send  # type: ignore[method-assign]

        # Wrap publish() with tracing
        original_publish = mediator.publish

        async def traced_publish(event: Any) -> None:
            event_name = type(event).__name__ if hasattr(event, "__class__") else "UnknownEvent"
            with tracer.trace(f"mediator.publish.{event_name}"):
                await original_publish(event)

        mediator.publish = traced_publish  # type: ignore[method-assign]

        _log.info("[INTEGRATION] Distributed Tracing -> Mediator: WIRED")
        return True

    except ImportError as exc:
        _log.warning("[INTEGRATION] Distributed Tracing -> Mediator: FAILED (%s)", exc)
        return False
    except Exception as exc:
        _log.warning("[INTEGRATION] Distributed Tracing -> Mediator: ERROR (%s)", exc)
        return False


__all__ = ["wire_tracing_to_mediator"]
