"""CQRS Query Bus — Execute queries through handler pipeline with caching support."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

_log = logging.getLogger(__name__)


# ── Query Base ──────────────────────────────────────────────────────────────


class Query:
    """Base class for all queries.

    Subclass and define expected fields:
        class GetTradeQuery(Query):
            def __init__(self, trade_id: str = ""):
                self.trade_id = trade_id
    """

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if not k.startswith("_")}


# ── Data Models ──────────────────────────────────────────────────────────────


@dataclass
class QueryResult:
    """Result of executing a query."""

    success: bool = True
    data: Any = None
    error: str = ""
    duration_ms: float = 0.0
    query_type: str = ""
    cached: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "error": self.error,
            "duration_ms": round(self.duration_ms, 2),
            "query_type": self.query_type,
            "cached": self.cached,
        }


# ── Query Cache Entry ───────────────────────────────────────────────────────


@dataclass
class CacheEntry:
    """A cached query result."""

    result: Any = None
    cached_at: float = 0.0
    ttl_seconds: float = 60.0

    def is_expired(self) -> bool:
        return (time.time() - self.cached_at) > self.ttl_seconds


# ── Query Bus ────────────────────────────────────────────────────────────────


QueryHandlerFn = Callable[[Query], Any]


class QueryBus:
    """Executes queries against registered handlers with optional caching.

    Separates read operations from write operations (CQRS).
    Supports result caching with configurable TTL.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._handlers: dict[str, QueryHandlerFn] = {}
        self._cache: dict[str, CacheEntry] = {}
        self._total_queries: int = 0
        self._cache_hits: int = 0
        self._cache_misses: int = 0

    # ── Handler Registration ──────────────────────────────────────────────

    def register_handler(self, query_type: type[Query],
                         handler: QueryHandlerFn) -> None:
        """Register a handler for a query type.

        Args:
            query_type: The Query subclass to handle.
            handler: Callable receiving a query instance, returning data.
        """
        name = query_type.__name__
        with self._lock:
            self._handlers[name] = handler

    def handler(self, query_type: type[Query]) -> Callable:
        """Decorator to register a handler for a query type.

        Usage:
            @bus.handler(GetTradeQuery)
            def handle(query):
                return trades_db.get(query.trade_id)
        """
        def decorator(fn: QueryHandlerFn) -> QueryHandlerFn:
            self.register_handler(query_type, fn)
            return fn
        return decorator

    def unregister_handler(self, query_type: type[Query]) -> bool:
        """Unregister a handler.

        Returns True if removed, False if not found.
        """
        name = query_type.__name__
        with self._lock:
            return self._handlers.pop(name, None) is not None

    # ── Execution ─────────────────────────────────────────────────────────

    def execute(self, query: Query, use_cache: bool = False,
                cache_ttl: float = 60.0) -> QueryResult:
        """Execute a query against its registered handler.

        Args:
            query: Query instance.
            use_cache: If True, cache the result for subsequent queries.
            cache_ttl: Cache TTL in seconds.

        Returns:
            QueryResult with data.
        """
        t0 = time.time()
        query_type = type(query).__name__
        cache_key = f"{query_type}:{hash(frozenset(query.to_dict().items()))}"

        # Check cache
        if use_cache:
            with self._lock:
                cached = self._cache.get(cache_key)
                if cached and not cached.is_expired():
                    self._total_queries += 1
                    self._cache_hits += 1
                    return QueryResult(
                        success=True,
                        data=cached.result,
                        query_type=query_type,
                        duration_ms=(time.time() - t0) * 1000,
                        cached=True,
                    )

        with self._lock:
            handler = self._handlers.get(query_type)

        if handler is None:
            self._total_queries += 1
            return QueryResult(
                success=False, error=f"No handler for {query_type}",
                query_type=query_type,
                duration_ms=(time.time() - t0) * 1000,
            )

        try:
            result_data = handler(query)
            self._total_queries += 1

            # Cache if enabled
            if use_cache:
                with self._lock:
                    self._cache[cache_key] = CacheEntry(
                        result=result_data,
                        cached_at=time.time(),
                        ttl_seconds=cache_ttl,
                    )
                    self._cache_misses += 1

            return QueryResult(
                success=True, data=result_data,
                query_type=query_type,
                duration_ms=(time.time() - t0) * 1000,
            )
        except Exception as exc:
            _log.warning("[QRYBUS] Handler error for '%s': %s", query_type, exc)
            self._total_queries += 1
            return QueryResult(
                success=False, error=str(exc),
                query_type=query_type,
                duration_ms=(time.time() - t0) * 1000,
            )

    def invalidate_cache(self, query_type: type[Query] | None = None) -> int:
        """Invalidate cache entries.

        Args:
            query_type: Optional query type to invalidate. None = all.

        Returns:
            Number of invalidated entries.
        """
        prefix = query_type.__name__ if query_type else ""
        count = 0
        with self._lock:
            keys = list(self._cache.keys())
            for key in keys:
                if not prefix or key.startswith(prefix):
                    del self._cache[key]
                    count += 1
        return count

    # ── Statistics ────────────────────────────────────────────────────────

    def get_stats(self) -> dict[str, Any]:
        """Get query bus statistics."""
        with self._lock:
            total = self._total_queries
            hits = self._cache_hits
            return {
                "total_queries": total,
                "registered_handlers": len(self._handlers),
                "handler_names": list(self._handlers.keys()),
                "cache_entries": len(self._cache),
                "cache_hits": hits,
                "cache_misses": self._cache_misses,
                "cache_hit_rate": round(hits / max(total, 1) * 100, 1),
            }

    def clear_all(self) -> None:
        """Clear all handlers and cache (for testing)."""
        with self._lock:
            self._handlers.clear()
            self._cache.clear()
            self._total_queries = 0
            self._cache_hits = 0
            self._cache_misses = 0
