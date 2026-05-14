"""
Idempotency Manager for Order Execution.

Prevents duplicate order submission by tracking unique request keys.
"""

from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, Tuple, Optional, Any, List
import threading
import hashlib
import logging

log = logging.getLogger(__name__)
import sqlite3
import json
from pathlib import Path

@dataclass
class IdempotencyRecord:
    timestamp: datetime
    result: Any

class IdempotencyManager:
    def __init__(self, cache_size: int = 1000, expiry_hours: int = 24, persistence_path: Optional[str] = None):
        self._cache: Dict[str, Tuple[datetime, Any]] = {}
        self._cache_size = cache_size
        self._expiry_hours = expiry_hours
        self._lock = threading.Lock()
        self._persistence_path = Path(persistence_path) if persistence_path else None
        
        if self._persistence_path:
            self._init_persistence()
            self._load_from_persistence()

    def _init_persistence(self):
        """Initialize SQLite table for idempotency keys."""
        try:
            with sqlite3.connect(self._persistence_path) as conn:
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS idempotency_keys "
                    "(key TEXT PRIMARY KEY, timestamp DATETIME, result_json TEXT)"
                )
                conn.commit()
        except Exception as e:
            log.error(f"Failed to initialize idempotency persistence: {e}")

    def _load_from_persistence(self):
        """Load recent keys from SQLite into memory cache."""
        try:
            with sqlite3.connect(self._persistence_path) as conn:
                cursor = conn.execute("SELECT key, timestamp, result_json FROM idempotency_keys")
                for key, ts_str, res_json in cursor:
                    ts = datetime.fromisoformat(ts_str)
                    res = json.loads(res_json)
                    self._cache[key] = (ts, res)
            log.info(f"Loaded {len(self._cache)} idempotency keys from persistence")
        except Exception as e:
            log.error(f"Failed to load idempotency keys: {e}")

    def generate_key(self, order_request: Any, context: Any) -> str:
        """Creates a deterministic hash of the order and its context."""
        key_data = {
            "symbol": getattr(order_request, 'symbol', ''),
            "direction": getattr(order_request, 'direction', ''),
            "strike": getattr(order_request, 'strike', ''),
            "qty": getattr(order_request, 'qty', ''),
            "signal_id": getattr(context, 'signal_id', ''),
            "timestamp": getattr(context, 'signal_timestamp', '').isoformat() if hasattr(context, 'signal_timestamp') else ''
        }
        key_string = "&".join(f"{k}={v}" for k, v in sorted(key_data.items()))
        return hashlib.sha256(key_string.encode()).hexdigest()[:32]

    def is_duplicate(self, key: str) -> bool:
        with self._lock:
            self._cleanup()
            return key in self._cache

    def get_result(self, key: str) -> Optional[Any]:
        with self._lock:
            self._cleanup()
            return self._cache.get(key)[1] if key in self._cache else None

    def store_result(self, key: str, result: Any):
        with self._lock:
            now = datetime.now()
            self._cache[key] = (now, result)
            
            if self._persistence_path:
                try:
                    res_json = json.dumps(result, default=str)
                    with sqlite3.connect(self._persistence_path) as conn:
                        conn.execute(
                            "INSERT OR REPLACE INTO idempotency_keys (key, timestamp, result_json) VALUES (?, ?, ?)",
                            (key, now.isoformat(), res_json)
                        )
                        conn.commit()
                except Exception as e:
                    log.error(f"Failed to persist idempotency key {key}: {e}")

            if len(self._cache) > self._cache_size:
                # Remove oldest entry
                oldest_key = next(iter(self._cache))
                del self._cache[oldest_key]

    def _cleanup(self):
        expiry_time = datetime.now() - timedelta(hours=self._expiry_hours)
        expired_keys = [k for k, (t, _) in self._cache.items() if t < expiry_time]
        for k in expired_keys:
            del self._cache[k]
