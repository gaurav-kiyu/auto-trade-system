"""
Idempotency Manager for Order Execution.

Prevents duplicate order submission by tracking unique request keys.
"""

from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, Tuple, Optional
import threading
import hashlib

@dataclass
class IdempotencyRecord:
    timestamp: datetime
    result: Any

class IdempotencyManager:
    def __init__(self, cache_size: int = 1000, expiry_hours: int = 24):
        self._cache: Dict[str, Tuple[datetime, Any]] = {}
        self._cache_size = cache_size
        self._expiry_hours = expiry_hours
        self._lock = threading.Lock()

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
            self._cache[key] = (datetime.now(), result)
            if len(self._cache) > self._cache_size:
                # Remove oldest entry
                oldest_key = next(iter(self._cache))
                del self._cache[oldest_key]

    def _cleanup(self):
        expiry_time = datetime.now() - timedelta(hours=self._expiry_hours)
        expired_keys = [k for k, (t, _) in self._cache.items() if t < expiry_time]
        for k in expired_keys:
            del self._cache[k]
