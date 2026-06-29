"""Idempotency Engine - extracted from ExecutionService (god object).

Provides idempotency key generation, LRU caching, and duplicate detection
for order execution. Delegates to IdempotencyManager for persistence and
maintains a local fallback cache for backward compatibility.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from collections import OrderedDict
from datetime import timedelta
from core.datetime_ist import now_ist
from core.execution.idempotency.manager import IdempotencyManager
from core.ports.execution.execution_port import (
    ExecutionContext,
    OrderRequest,
    OrderResult,
)

_log = logging.getLogger(__name__)

__all__ = [
    "IdempotencyEngine",
]


class IdempotencyEngine:
    """Idempotency key management for order execution.

    Generates deterministic idempotency keys from order requests, stores
    results in an LRU cache with expiry, and provides duplicate detection.

    Thread-safe via internal RLock.
    """

    def __init__(
        self,
        cache_size: int = 1000,
        expiry_hours: int = 24,
        persistence_path: str | None = None,
    ) -> None:
        self._cache_size = cache_size
        self._expiry_hours = expiry_hours
        self._idempotency_cache: OrderedDict[str, tuple] = OrderedDict()
        self._lock = threading.RLock()

        # Delegate to IdempotencyManager for persistent storage
        self._manager = IdempotencyManager(
            cache_size=cache_size,
            expiry_hours=expiry_hours,
            persistence_path=persistence_path,
        )

    # ── Public API ──────────────────────────────────────────────────────────

    def is_duplicate(self, idempotency_key: str) -> bool:
        """Check if an order with the given key has already been processed.

        Args:
            idempotency_key: Unique key to check for duplication.

        Returns:
            True if order is duplicate, False otherwise.
        """
        try:
            return bool(self._manager.is_duplicate(idempotency_key))
        except (KeyError, ValueError, TypeError):
            with self._lock:
                self._cleanup()
                return idempotency_key in self._idempotency_cache

    def generate_key(
        self,
        order_request: OrderRequest,
        execution_context: ExecutionContext,
    ) -> str:
        """Generate a deterministic idempotency key from an order request."""
        key_data = {
            "symbol": order_request.symbol,
            "direction": order_request.direction,
            "strike_price": order_request.strike_price,
            "lot_size": order_request.lot_size,
            "order_type": (
                order_request.order_type.value
                if hasattr(order_request.order_type, 'value')
                else str(order_request.order_type)
            ),
            "price": order_request.price,
            "stop_loss": order_request.stop_loss,
            "target": order_request.target,
            "strategy_id": order_request.strategy_id,
            "signal_id": execution_context.signal_id,
            "timestamp": (
                execution_context.signal_timestamp.isoformat()
                if execution_context.signal_timestamp
                else None
            ),
        }
        # Remove None values for deterministic key
        key_data = {k: v for k, v in key_data.items() if v is not None}
        key_string = "&".join(
            f"{k}={v}" for k, v in sorted(key_data.items())
        )
        return hashlib.sha256(key_string.encode()).hexdigest()[:32]

    def store_result(self, key: str, order_result: OrderResult) -> None:
        """Store an idempotency result in the cache.

        Args:
            key: The idempotency key.
            order_result: The result to associate with the key.
        """
        # Prefer persistent storage
        try:
            self._manager.store_result(key, order_result)
        except (KeyError, OSError, ValueError):
            _log.exception("Failed to persist idempotency key %s", key)

        # Local LRU cache fallback
        with self._lock:
            self._idempotency_cache[key] = (now_ist(), order_result)
            self._idempotency_cache.move_to_end(key, last=False)
            while len(self._idempotency_cache) > self._cache_size:
                self._idempotency_cache.popitem(last=True)

    def get_result(self, key: str) -> OrderResult | None:
        """Retrieve a cached order result by idempotency key.

        Args:
            key: The idempotency key to look up.

        Returns:
            Cached OrderResult if found and not expired, else None.
        """
        try:
            return self._manager.get_result(key)
        except (KeyError, ValueError, TypeError):
            with self._lock:
                self._cleanup()
                entry = self._idempotency_cache.get(key)
                return entry[1] if entry else None

    def mark_in_flight(self, key: str) -> None:
        """Mark an idempotency key as in-flight (prevents dupes)."""
        self._manager.mark_in_flight(key)

    def confirm_execution(self, key: str, order_result: OrderResult) -> None:
        """Confirm an in-flight execution, storing the result."""
        self._manager.confirm_execution(key, order_result)

    def clear_in_flight(self, key: str) -> None:
        """Clear an in-flight marker (e.g. on execution failure)."""
        self._manager.clear_in_flight(key)

    # ── Internal helpers ────────────────────────────────────────────────────

    def _cleanup(self) -> None:
        """Remove expired entries from the local fallback cache."""
        try:
            self._manager._cleanup()  # noqa: SLF001
            return
        except (AttributeError, KeyError, ValueError):
            with self._lock:
                expiry = now_ist() - timedelta(hours=self._expiry_hours)
                expired = [
                    key
                    for key, (ts, _) in self._idempotency_cache.items()
                    if ts < expiry
                ]
                for key in expired:
                    del self._idempotency_cache[key]
                if expired:
                    _log.debug(
                        "Cleaned up %d expired keys (fallback)",
                        len(expired),
                    )
