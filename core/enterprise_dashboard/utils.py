"""
Utility functions for the Enterprise Dashboard.

Extracted from core/enterprise_dashboard.py for SRP compliance.
Provides error responses, freezing helpers, and provider request tracking.
"""
from __future__ import annotations

import threading
import time
from types import MappingProxyType
from typing import Any

__all__ = [
    "_DEFAULT_HOST",
    "_DEFAULT_PORT",
    "_error_response",
    "_freeze",
    "_get_provider_error_info",
    "_record_provider_request",
]


# -- Default host/port constants -------------------------------------------------

_DEFAULT_HOST = "0.0.0.0"
_DEFAULT_PORT = 8765


# -- Provider request tracking ---------------------------------------------------

_PROVIDER_REQUESTS: list[float] = []
_LOCK = threading.RLock()


def _record_provider_request() -> None:
    """Record a request timestamp for rate/error tracking."""
    global _PROVIDER_REQUESTS
    now = time.time()
    with _LOCK:
        _PROVIDER_REQUESTS.append(now)
        # Keep only last 5 minutes of requests
        _PROVIDER_REQUESTS = [t for t in _PROVIDER_REQUESTS if now - t < 300]


def _get_provider_error_info(details: dict) -> dict:
    """Get error-rate info for each adapter from health details."""
    error_info: dict[str, Any] = {}
    now = time.time()
    for name, detail in details.items():
        if not isinstance(detail, dict):
            continue
        error_rate = detail.get("error_rate", 0.0)
        last_error = detail.get("last_error", None)
        last_error_ts = detail.get("last_error_ts", None)
        error_info[name] = {
            "error_rate": error_rate,
            "last_error": last_error,
            "last_error_ts": last_error_ts,
            "error_age": round(now - last_error_ts, 2) if last_error_ts else None,
        }
    return error_info


# -- Error response helper ------------------------------------------------------


def _error_response(message: str, code: int, **kwargs: Any) -> dict:
    """Standardized error response body for all API endpoints.

    Usage:
        return JSONResponse(_error_response("Not found", 404), status_code=404)
        return JSONResponse(_error_response("Rate limited", 429, retry_after=60), status_code=429)
    """
    resp: dict[str, Any] = {"error": message, "code": code}
    resp.update(kwargs)
    return resp


# -- Config freezing helper -----------------------------------------------------


def _freeze(obj: Any) -> Any:
    """Recursively freeze a dict/list into an immutable form.

    Converts all nested dicts to MappingProxyType (read-only views)
    and all nested lists to tuples. This prevents accidental mutation
    of shared config objects at runtime.
    """
    if isinstance(obj, dict):
        return MappingProxyType({k: _freeze(v) for k, v in obj.items()})
    if isinstance(obj, list):
        return tuple(_freeze(v) for v in obj)
    if isinstance(obj, set):
        return frozenset(_freeze(v) for v in obj)
    return obj
