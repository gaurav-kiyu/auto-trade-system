"""Event Sourcing — Append-Only Event Store (DEPRECATED, use core.event_store).

.. deprecated:: v2.57.0
    This module is deprecated. Use ``core.event_store`` instead, which
    consolidates both JSON-file and SQLite EventStore implementations.

This module now re-exports from ``core.event_store`` for backward compatibility.
New code should import directly from ``core.event_store``.

Usage:
    from core.event_store import get_event_store, EventStore, StoredEvent

    store = get_event_store()
    store.append("trade.executed", stream="NIFTY", data={"qty": 50, "price": 23500})
    events = store.read_stream("NIFTY")
    store.create_snapshot("NIFTY", {"position": 50, "pnl": 250})
"""

# The __future__ import must be at the top (after docstring) for Python 3.14 compat
from __future__ import annotations

import warnings as _warnings

_warnings.warn(
    "core.event_sourcing is deprecated — use core.event_store instead (TD-02)",
    DeprecationWarning,
    stacklevel=2,
)

# Re-export from unified store for backward compatibility
from core.event_store import (
    EventStore,
    Snapshot,
    StoredEvent,
    get_event_store,
    reset_event_store,
)

__all__ = [
    "EventStore",
    "Snapshot",
    "StoredEvent",
    "get_event_store",
    "reset_event_store",
]
