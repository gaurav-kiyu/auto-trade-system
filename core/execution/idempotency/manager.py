"""
Idempotency Manager for Order Execution.

Prevents duplicate order submission by tracking unique request keys.

CRITICAL: Thread-safe implementation with in-flight tracking to prevent
duplicates on crash/restart scenarios.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from core.datetime_ist import now_ist

log = logging.getLogger(__name__)
import json
import sqlite3
from pathlib import Path


@dataclass
class IdempotencyRecord:
    timestamp: datetime
    result: Any


class IdempotencyManager:
    """
    Thread-safe idempotency manager with in-flight tracking.

    In-flight tracking prevents duplicates on crash/restart by marking
    an order as "in-flight" BEFORE execution, then confirming or clearing
    after execution completes.
    """

    def __init__(self, cache_size: int = 1000, expiry_hours: int = 24, persistence_path: str | None = None):
        self._cache: dict[str, tuple[datetime, Any]] = {}
        self._in_flight: dict[str, datetime] = {}  # Keys currently being executed
        self._cache_size = cache_size
        self._expiry_hours = expiry_hours
        self._lock = threading.Lock()
        self._persistence_path = Path(persistence_path) if persistence_path else None

        if self._persistence_path:
            self._init_persistence()
            self._load_from_persistence()

    def _init_persistence(self):
        """Initialize SQLite table for idempotency keys (thread-safe)."""
        try:
            with self._lock:
                with sqlite3.connect(self._persistence_path) as conn:
                    conn.execute(
                        "CREATE TABLE IF NOT EXISTS idempotency_keys "
                        "(key TEXT PRIMARY KEY, timestamp DATETIME, result_json TEXT, status TEXT)"
                    )
                    conn.execute(
                        "CREATE INDEX IF NOT EXISTS idx_idempotency_status "
                        "ON idempotency_keys(status)"
                    )
                    conn.commit()
        except Exception as e:
            log.error(f"Failed to initialize idempotency persistence: {e}")

    def _load_from_persistence(self):
        """Load recent keys from SQLite into memory cache (thread-safe)."""
        try:
            with self._lock:
                with sqlite3.connect(self._persistence_path) as conn:
                    # Load confirmed keys only (not in-flight from crashed session)
                    cursor = conn.execute(
                        "SELECT key, timestamp, result_json FROM idempotency_keys "
                        "WHERE status = 'confirmed' AND timestamp > datetime('now', '-24 hours')"
                    )
                    for key, ts_str, res_json in cursor:
                        ts = datetime.fromisoformat(ts_str)
                        res = json.loads(res_json)
                        self._cache[key] = (ts, res)

                    # Clean up old in-flight keys from previous sessions (24h expiry)
                    conn.execute(
                        "DELETE FROM idempotency_keys WHERE status = 'in_flight' "
                        "AND timestamp < datetime('now', '-24 hours')"
                    )
                    conn.commit()
            log.info(f"Loaded {len(self._cache)} idempotency keys from persistence")
        except Exception as e:
            log.error(f"Failed to load idempotency keys: {e}")

    def generate_key(self, order_request: Any, context: Any) -> str:
        """
        Creates a deterministic hash of the order and its context.

        CRITICAL: Does NOT include timestamp to ensure deterministic key
        generation for the same order. This prevents duplicate prevention
        failure when the same signal is processed at different times.
        """
        key_data = {
            "symbol": getattr(order_request, 'symbol', ''),
            "direction": getattr(order_request, 'direction', ''),
            "strike": getattr(order_request, 'strike', ''),
            "qty": getattr(order_request, 'qty', ''),
            # CRITICAL FIX: Removed timestamp - it caused different keys for same signal
            "signal_id": getattr(context, 'signal_id', ''),
        }
        key_string = "&".join(f"{k}={v}" for k, v in sorted(key_data.items()))
        return hashlib.sha256(key_string.encode()).hexdigest()[:32]

    def is_duplicate(self, key: str) -> bool:
        """
        Check if order is duplicate.

        Returns True if:
        - Key is already in confirmed cache, OR
        - Key is currently in-flight (being executed)
        """
        with self._lock:
            self._cleanup()
            return key in self._cache or key in self._in_flight

    def mark_in_flight(self, key: str) -> None:
        """
        Mark order as in-flight BEFORE execution.

        This prevents duplicate submission on crash/restart because
        on next startup, is_duplicate() will detect this key as in-flight
        and handle appropriately.
        """
        with self._lock:
            now = now_ist()
            self._in_flight[key] = now

            # Persist in-flight state (thread-safe)
            if self._persistence_path:
                try:
                    with sqlite3.connect(self._persistence_path) as conn:
                        conn.execute(
                            "INSERT OR REPLACE INTO idempotency_keys "
                            "(key, timestamp, result_json, status) VALUES (?, ?, ?, ?)",
                            (key, now.isoformat(), json.dumps({"status": "in_flight"}), "in_flight")
                        )
                        conn.commit()
                except Exception as e:
                    log.error(f"Failed to persist in-flight key {key}: {e}")

    def confirm_execution(self, key: str, result: Any) -> None:
        """
        Confirm order execution completed successfully.

        Moves key from in-flight to confirmed cache and persists result.
        """
        with self._lock:
            now = now_ist()

            # Remove from in-flight
            if key in self._in_flight:
                del self._in_flight[key]

            # Add to confirmed cache
            self._cache[key] = (now, result)

            # Persist confirmed result (thread-safe)
            if self._persistence_path:
                try:
                    res_json = json.dumps(result, default=str)
                    with sqlite3.connect(self._persistence_path) as conn:
                        conn.execute(
                            "INSERT OR REPLACE INTO idempotency_keys "
                            "(key, timestamp, result_json, status) VALUES (?, ?, ?, ?)",
                            (key, now.isoformat(), res_json, "confirmed")
                        )
                        conn.commit()
                except Exception as e:
                    log.error(f"Failed to persist confirmed key {key}: {e}")

            # Evict oldest if cache too large
            if len(self._cache) > self._cache_size:
                oldest_key = next(iter(self._cache))
                del self._cache[oldest_key]

    def clear_in_flight(self, key: str) -> None:
        """
        Clear in-flight marker after execution failure.

        This allows retry of failed orders.
        """
        with self._lock:
            if key in self._in_flight:
                del self._in_flight[key]

            # Update persistence to reflect failure (thread-safe)
            if self._persistence_path:
                try:
                    with sqlite3.connect(self._persistence_path) as conn:
                        conn.execute(
                            "DELETE FROM idempotency_keys WHERE key = ? AND status = 'in_flight'",
                            (key,)
                        )
                        conn.commit()
                except Exception as e:
                    log.error(f"Failed to clear in-flight key {key}: {e}")

    def get_result(self, key: str) -> Any | None:
        """Get cached result for key if available."""
        with self._lock:
            self._cleanup()
            if key in self._cache:
                return self._cache[key][1]
            return None

    def store_result(self, key: str, result: Any):
        """Legacy method - now calls confirm_execution."""
        self.confirm_execution(key, result)

    def _cleanup(self):
        """Remove expired entries from cache."""
        expiry_time = now_ist() - timedelta(hours=self._expiry_hours)
        expired_keys = [k for k, (t, _) in self._cache.items() if t < expiry_time]
        for k in expired_keys:
            del self._cache[k]

        # Also cleanup in-flight entries older than 1 hour (stale crashes)
        stale_time = now_ist() - timedelta(hours=1)
        stale_keys = [k for k, t in self._in_flight.items() if t < stale_time]
        for k in stale_keys:
            del self._in_flight[k]
