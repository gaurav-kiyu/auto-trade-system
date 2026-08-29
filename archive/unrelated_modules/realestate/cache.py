"""Performance Caching Layer — in-memory cache with TTL for the real estate platform.

Provides:
  - TTLCache: generic time-to-live cache with max size and automatic cleanup
  - CachedServiceWrapper: wraps any service method with caching
  - Pre-configured caches for: property listings, neighborhood data, analytics

Usage:
    from realestate.cache import property_cache, cached
    listings = property_cache.get("all") or property_cache.set("all", service.list_all(), ttl=60)
"""

from __future__ import annotations

import logging
import time
from collections import OrderedDict
from collections.abc import Callable
from typing import Any

_log = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# TTLCache — Generic Time-To-Live Cache
# ═══════════════════════════════════════════════════════════════════════════════

class _CacheEntry:
    """A single cache entry with expiry time."""

    __slots__ = ("value", "expires_at")

    def __init__(self, value: Any, ttl: float) -> None:
        self.value = value
        self.expires_at = time.time() + ttl

    @property
    def is_expired(self) -> bool:
        return time.time() > self.expires_at


class TTLCache:
    """Thread-safe (basic) in-memory cache with TTL and LRU eviction.

    Features:
      - Per-key TTL (time-to-live in seconds)
      - Max size with LRU eviction
      - Automatic lazy expiry on get/set
      - Bulk operations: get_many, clear, keys
      - Stats: hits, misses, size
    """

    def __init__(self, max_size: int = 500, default_ttl: float = 60.0) -> None:
        self._max_size = max_size
        self._default_ttl = default_ttl
        self._cache: OrderedDict[str, _CacheEntry] = OrderedDict()
        self._hits = 0
        self._misses = 0

    # ── Properties ───────────────────────────────────────────────────────

    @property
    def max_size(self) -> int:
        return self._max_size

    @property
    def default_ttl(self) -> float:
        return self._default_ttl

    # ── Core Operations ───────────────────────────────────────────────────

    def get(self, key: str) -> Any | None:
        """Get a value from the cache. Returns None if missing or expired."""
        entry = self._cache.get(key)
        if entry is None:
            self._misses += 1
            return None
        if entry.is_expired:
            self._cache.pop(key, None)
            self._misses += 1
            return None
        # Move to end (LRU: most recently used)
        self._cache.move_to_end(key)
        self._hits += 1
        return entry.value

    def set(self, key: str, value: Any, ttl: float | None = None) -> Any:
        """Set a value in the cache with optional TTL. Returns the value."""
        ttl = ttl if ttl is not None else self._default_ttl
        # Evict if at capacity
        if len(self._cache) >= self._max_size:
            self._evict_one()
        self._cache[key] = _CacheEntry(value, ttl)
        self._cache.move_to_end(key)
        return value

    def delete(self, key: str) -> bool:
        """Delete a key from the cache. Returns True if existed."""
        if key in self._cache:
            self._cache.pop(key, None)
            return True
        return False

    def clear(self) -> None:
        """Clear all cached entries."""
        self._cache.clear()
        self._hits = 0
        self._misses = 0
        _log.debug("[CACHE] Cleared")

    # ── Bulk Operations ───────────────────────────────────────────────────

    def get_or_set(self, key: str, factory: Callable[[], Any], ttl: float | None = None) -> Any:
        """Get from cache or compute and store using factory function."""
        value = self.get(key)
        if value is not None:
            return value
        value = factory()
        return self.set(key, value, ttl)

    def get_many(self, keys: list[str]) -> dict[str, Any]:
        """Get multiple keys at once. Returns dict of key->value for hits."""
        result: dict[str, Any] = {}
        for key in keys:
            val = self.get(key)
            if val is not None:
                result[key] = val
        return result

    def keys(self) -> list[str]:
        """Get all cached keys (including expired ones until next access)."""
        return list(self._cache.keys())

    # ── Stats ─────────────────────────────────────────────────────────────

    @property
    def size(self) -> int:
        return len(self._cache)

    @property
    def hits(self) -> int:
        return self._hits

    @property
    def misses(self) -> int:
        return self._misses

    @property
    def hit_rate(self) -> float:
        total = self._hits + self._misses
        return round(self._hits / total * 100, 1) if total > 0 else 0.0

    def stats(self) -> dict[str, Any]:
        """Get cache statistics."""
        return {
            "size": self.size,
            "max_size": self._max_size,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": self.hit_rate,
            "default_ttl": self._default_ttl,
        }

    def expire_all(self) -> int:
        """Force-expire all stale entries. Returns count of expired entries."""
        now = time.time()
        expired_keys = [k for k, v in self._cache.items() if v.expires_at <= now]
        for k in expired_keys:
            self._cache.pop(k, None)
        return len(expired_keys)

    # ── Internals ─────────────────────────────────────────────────────────

    def _evict_one(self) -> None:
        """Evict the least recently used (first) entry."""
        if self._cache:
            try:
                self._cache.popitem(last=False)
            except KeyError:
                pass


# ═══════════════════════════════════════════════════════════════════════════════
# Cached Service Wrapper
# ═══════════════════════════════════════════════════════════════════════════════

class CachedServiceWrapper:
    """Wraps a service to add caching to specific methods.

    Example:
        ps = PropertyService()
        cached_ps = CachedServiceWrapper(ps, ttl=30)
        props = cached_ps.call("list_all")  # cached for 30s
    """

    def __init__(self, service: Any, ttl: float = 30.0, cache: TTLCache | None = None) -> None:
        self._service = service
        self._ttl = ttl
        self._cache = cache or TTLCache(max_size=200, default_ttl=ttl)

    @property
    def cache(self) -> TTLCache:
        return self._cache

    def call(self, method_name: str, *args: Any, cache_key: str | None = None, ttl: float | None = None, **kwargs: Any) -> Any:
        """Call a method, caching its return value if possible.

        Args:
            method_name: Name of the method to call on the service.
            *args: Positional arguments to pass to the method.
            cache_key: Optional cache key. If not provided, auto-generated.
            ttl: Optional per-call TTL override.
            **kwargs: Keyword arguments to pass to the method.

        Returns:
            The method's return value.
        """
        method = getattr(self._service, method_name, None)
        if method is None:
            raise AttributeError(f"Service has no method '{method_name}'")

        # Determine if this method is cacheable (no write operations)
        # Write operations: create, update, delete, add, record, submit
        is_read = not any(w in method_name.lower() for w in ["create", "update", "delete", "add", "record", "submit", "remove", "clear"])

        if is_read:
            # Auto-generate cache key if not provided
            if cache_key is None:
                key_parts = [method_name]
                key_parts.extend(str(a) for a in args)
                key_parts.extend(f"{k}={v}" for k, v in sorted(kwargs.items()))
                cache_key = ":".join(key_parts)

            cached = self._cache.get(cache_key)
            if cached is not None:
                return cached

            result = method(*args, **kwargs)
            self._cache.set(cache_key, result, ttl or self._ttl)
            return result

        # Write operations bypass cache and invalidate related keys
        result = method(*args, **kwargs)
        # Invalidate list_all cache after writes
        self._cache.delete("list_all")
        return result

    def invalidate(self, method_name: str | None = None) -> None:
        """Invalidate cache for a method (or all if None)."""
        if method_name:
            for key in self._cache.keys():
                if key.startswith(method_name):
                    self._cache.delete(key)
        else:
            self._cache.clear()


# ═══════════════════════════════════════════════════════════════════════════════
# Pre-configured Cache Instances
# ═══════════════════════════════════════════════════════════════════════════════

# Property listings cache — 30s TTL, max 100 entries
property_cache = TTLCache(max_size=100, default_ttl=30)

# Neighborhood data cache — 300s TTL (5 min), max 50 entries
neighborhood_cache = TTLCache(max_size=50, default_ttl=300)

# Analytics cache — 60s TTL, max 30 entries (one per dashboard view)
analytics_cache = TTLCache(max_size=30, default_ttl=60)

# Search results cache — 15s TTL, max 200 entries
search_cache = TTLCache(max_size=200, default_ttl=15)


def invalidate_all() -> None:
    """Invalidate all pre-configured caches."""
    property_cache.clear()
    neighborhood_cache.clear()
    analytics_cache.clear()
    search_cache.clear()
    _log.debug("[CACHE] All real estate caches invalidated")


def get_cache_stats() -> dict[str, Any]:
    """Get stats for all pre-configured caches."""
    return {
        "property_cache": property_cache.stats(),
        "neighborhood_cache": neighborhood_cache.stats(),
        "analytics_cache": analytics_cache.stats(),
        "search_cache": search_cache.stats(),
    }
