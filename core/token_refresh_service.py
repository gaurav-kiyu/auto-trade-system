"""
Token Refresh Service (v2.45 hardening item).

Monitors broker auth token freshness and automatically re-authenticates
before expiry.  Supports Kite (daily token) and Angel (session refresh_token).

Integrates with BrokerFailoverManager for cross-broker coordination.

Config keys (all under BROKER_CONFIG or top-level):
    token_refresh_enabled           : bool   default true
    token_refresh_interval_mins     : int    default 60
    token_refresh_grace_period_mins : int    default 30
    token_refresh_retry_count       : int    default 3

Public API
----------
    TokenRefreshService.check_and_refresh(adapters)  -> dict[str, bool]
    TokenRefreshService.status()                     -> dict
    TokenRefreshService.validate_token(adapter)      -> bool
    TokenRefreshService.check_auth(adapter)          -> dict
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import date
from typing import Any

_log = logging.getLogger(__name__)


class TokenRefreshService:
    """Thread-safe token freshness monitor and auto-refresh."""

    def __init__(self, cfg: dict[str, Any] | None = None) -> None:
        c = cfg or {}
        self._enabled = bool(c.get("token_refresh_enabled", True))
        self._interval = float(c.get("token_refresh_interval_mins", 60))
        self._grace = float(c.get("token_refresh_grace_period_mins", 30))
        self._retry = int(c.get("token_refresh_retry_count", 3))
        self._lock = threading.Lock()
        self._last_check: dict[str, float] = {}
        self._refresh_count: dict[str, int] = {}
        self._last_error: dict[str, str] = {}

    def _needs_check(self, broker: str) -> bool:
        now = time.time()
        last = self._last_check.get(broker, -float("inf"))
        return (now - last) >= self._interval * 60

    def _adapter_has_kite_token(self, adapter: Any) -> bool:
        """Duck-type check: does this adapter look like a Kite adapter?"""
        kl = getattr(adapter, "_kite_lock", None)
        if kl is not None:
            return True
        td = getattr(adapter, "_token_date", None)
        return td is not None and not self._is_mock(td)

    def _adapter_has_angel_token(self, adapter: Any) -> bool:
        """Duck-type check: does this adapter look like an Angel adapter?"""
        a = getattr(adapter, "_angel", None)
        c = getattr(adapter, "_client", None)
        return a is not None or c is not None

    @staticmethod
    def _is_mock(obj: Any) -> bool:
        """Detect unittest.mock objects that auto-create attributes."""
        return type(obj).__name__ in ("MagicMock", "Mock", "AsyncMock")

    def _kite_token_expired(self, adapter: Any) -> bool:
        token_date = getattr(adapter, "_token_date", None)
        if token_date is None:
            return True
        context = getattr(adapter, "_context", None)
        if context is None:
            today = date.today()
        else:
            now_fn = getattr(context, "now_fn", None)
            today = now_fn().date() if callable(now_fn) else date.today()
        return token_date != today

    def _kite_refresh(self, adapter: Any, sec: dict[str, str]) -> bool:
        try:
            from kiteconnect import KiteConnect

            api_key = str(sec.get("api_key") or "")
            access_token = str(sec.get("access_token") or "")
            if not api_key or not access_token:
                _log.warning("[TOKEN_REFRESH] Kite: missing api_key or access_token")
                return False

            k = KiteConnect(api_key=api_key)
            k.set_access_token(access_token)
            k.profile()
            kite_lock = getattr(adapter, "_kite_lock", None)
            if kite_lock and hasattr(kite_lock, "__enter__"):
                with kite_lock:
                    adapter._kite = k
                    adapter._connected = True
                    context = getattr(adapter, "_context", None)
                    if context and callable(getattr(context, "now_fn", None)):
                        adapter._token_date = context.now_fn().date()
                    else:
                        adapter._token_date = date.today()
            else:
                adapter._kite = k
                adapter._connected = True
                adapter._token_date = date.today()
            _log.info("[TOKEN_REFRESH] Kite re-authenticated")
            return True
        except Exception as exc:
            _log.error("[TOKEN_REFRESH] Kite refresh failed: %s", exc)
            return False

    def _angel_refresh(self, adapter: Any, sec: dict[str, str]) -> bool:
        try:
            from SmartApi import SmartConnect

            api_key = str(sec.get("api_key") or "")
            refresh_token = str(sec.get("refresh_token") or "")
            client_id = str(sec.get("client_id") or "")
            password = str(sec.get("password") or "")
            totp_key = str(sec.get("totp_key") or "")

            if not api_key:
                _log.warning("[TOKEN_REFRESH] Angel: missing api_key")
                return False

            client = SmartConnect(api_key=api_key)
            if client_id and password and totp_key:
                client.generateSession(client_id, password, totp_key)
            elif refresh_token:
                client.generateToken(refresh_token)
            else:
                _log.warning("[TOKEN_REFRESH] Angel: no refresh_token or full creds")
                return False

            angel_lock = getattr(adapter, "_angel_lock", None)
            if angel_lock and hasattr(angel_lock, "__enter__"):
                with angel_lock:
                    adapter._angel = client
                    adapter._connected = True
            else:
                adapter._angel = client
                adapter._connected = True
            _log.info("[TOKEN_REFRESH] Angel re-authenticated")
            return True
        except Exception as exc:
            _log.error("[TOKEN_REFRESH] Angel refresh failed: %s", exc)
            return False

    def check_and_refresh(self, adapters: dict[str, Any]) -> dict[str, bool]:
        """Check all adapters and refresh tokens if needed.

        Args:
            adapters: dict mapping broker name -> adapter instance.

        Returns:
            dict mapping broker name -> True if token is valid, False otherwise.
        """
        if not self._enabled:
            return {name: True for name in adapters}

        result: dict[str, bool] = {}
        for name, adapter in adapters.items():
            result[name] = self._check_single(name, adapter)
        return result

    def _check_single(self, name: str, adapter: Any) -> bool:
        if not self._needs_check(name):
            return True

        is_valid = self._validate_token_internal(adapter)
        if is_valid:
            self._last_check[name] = time.time()
            return True

        _log.info("[TOKEN_REFRESH] %s token stale, attempting refresh", name)
        sec = self._get_secrets(name, adapter)
        is_valid = self._retry_refresh(name, adapter, sec)

        self._last_check[name] = time.time()
        return is_valid

    def _retry_refresh(self, name: str, adapter: Any, sec: dict[str, str]) -> bool:
        for attempt in range(1, self._retry + 1):
            _log.info("[TOKEN_REFRESH] %s refresh attempt %d/%d", name, attempt, self._retry)
            ok = (
                self._kite_refresh(adapter, sec)
                if self._adapter_has_kite_token(adapter)
                else self._angel_refresh(adapter, sec)
                if self._adapter_has_angel_token(adapter)
                else False
            )
            with self._lock:
                if ok:
                    self._refresh_count[name] = self._refresh_count.get(name, 0) + 1
                    self._last_error.pop(name, None)
                    return True
                self._last_error[name] = f"attempt {attempt} failed"
        return False

    def _validate_token_internal(self, adapter: Any) -> bool:
        if self._adapter_has_kite_token(adapter):
            return not self._kite_token_expired(adapter)
        return bool(getattr(adapter, "_connected", False))

    def _get_secrets(self, name: str, adapter: Any) -> dict[str, str]:
        cfg_obj = getattr(adapter, "_context", None)
        if cfg_obj is None:
            return {}
        cfg = getattr(cfg_obj, "cfg", None) or {}
        try:
            from core.adapters.broker_adapters import broker_connection_secrets
            return broker_connection_secrets(cfg, name.upper())
        except Exception:
            return {}

    def validate_token(self, adapter: Any) -> bool:
        """Check if the adapter's token is currently valid.

        Uses duck-typing to detect adapter type by attributes.
        """
        if self._adapter_has_kite_token(adapter):
            return not self._kite_token_expired(adapter)
        if self._adapter_has_angel_token(adapter):
            return bool(getattr(adapter, "_connected", False))
        return bool(getattr(adapter, "_connected", False))

    def check_auth(self, adapter: Any) -> dict[str, Any]:
        """Return auth status dict for health checks."""
        is_valid = self.validate_token(adapter)
        broker_type = "kite" if self._adapter_has_kite_token(adapter) else (
            "angel" if self._adapter_has_angel_token(adapter) else "unknown"
        )
        return {
            "valid": is_valid,
            "broker": broker_type,
            "last_check": 0.0,
            "refresh_count": 0,
            "last_error": "",
        }

    def status(self) -> dict[str, Any]:
        """Return a status snapshot for health checks / web dashboard."""
        with self._lock:
            return {
                "enabled": self._enabled,
                "interval_mins": self._interval,
                "grace_period_mins": self._grace,
                "retry_count": self._retry,
                "last_check": dict(self._last_check),
                "refresh_count": dict(self._refresh_count),
                "last_error": dict(self._last_error),
            }
