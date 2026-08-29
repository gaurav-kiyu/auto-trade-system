"""Infrastructure layer — persistence, search engine, external adapters.

Uses in-memory storage by default (hot-swappable with SQLite/Postgres).
"""

from __future__ import annotations

from realestate.infrastructure.repository import (
    InMemoryPropertyRepository,
    PropertyRepository,
    SearchEngine,
)

__all__ = [
    "InMemoryPropertyRepository",
    "PropertyRepository",
    "SearchEngine",
]
