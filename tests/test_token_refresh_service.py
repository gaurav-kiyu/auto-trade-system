"""Tests for core/token_refresh_service.py."""

from __future__ import annotations

import threading
import time
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pytest

from core.token_refresh_service import TokenRefreshService


# ── Helper: Simple attribute containers (NOT MagicMock!) ────────────────

class _SimpleLock:
    def __enter__(self): return self
    def __exit__(self, *a): pass


def _make_simple(namespace: dict) -> object:
    """Create a simple object with given attributes set as instance attrs."""
    obj = type("SimpleObj", (), {})()
    for k, v in namespace.items():
        setattr(obj, k, v)
    return obj


_SENTINEL = object()

def kite_adapter(token_date=_SENTINEL, connected=True):
    """Create a plain Kite-like adapter (no MagicMock)."""
    if token_date is _SENTINEL:
        token_date = date.today()
    def _now_fn():
        ctx = type("DateObj", (), {})()
        ctx.date = lambda: date.today()
        return ctx
    return _make_simple({
        "_token_date": token_date,
        "_connected": connected,
        "_kite_lock": _SimpleLock(),
        "_kite": object(),
        "_context": _make_simple({
            "cfg": {},
            "now_fn": _now_fn,
        }),
    })


def angel_adapter(connected=True):
    """Create a plain Angel-like adapter (no MagicMock)."""
    return _make_simple({
        "_connected": connected,
        "_angel": object(),
        "_angel_lock": _SimpleLock(),
        "_context": _make_simple({"cfg": {}, "now_fn": lambda: None}),
    })


# ── Constructor ──────────────────────────────────────────────────────────

def test_constructor_defaults():
    s = TokenRefreshService()
    assert s._enabled is True
    assert s._interval == 60.0
    assert s._grace == 30.0
    assert s._retry == 3


def test_constructor_with_cfg():
    s = TokenRefreshService(cfg={
        "token_refresh_enabled": False,
        "token_refresh_interval_mins": 120,
    })
    assert s._enabled is False
    assert s._interval == 120.0


def test_constructor_zero_interval():
    s = TokenRefreshService(cfg={"token_refresh_interval_mins": 0})
    assert s._interval == 0.0


# ── Duck-type detection ──────────────────────────────────────────────────

def test_adapter_has_kite_token():
    adapter = kite_adapter()
    s = TokenRefreshService()
    assert s._adapter_has_kite_token(adapter) is True


def test_adapter_has_no_kite_token():
    s = TokenRefreshService()
    assert s._adapter_has_kite_token(object()) is False


def test_adapter_has_angel_token():
    adapter = angel_adapter()
    s = TokenRefreshService()
    assert s._adapter_has_angel_token(adapter) is True


def test_adapter_has_no_angel_token():
    s = TokenRefreshService()
    assert s._adapter_has_angel_token(object()) is False


# ── validate_token ───────────────────────────────────────────────────────

def test_validate_token_kite_valid():
    adapter = kite_adapter()
    s = TokenRefreshService()
    assert s.validate_token(adapter) is True


def test_validate_token_kite_expired():
    adapter = kite_adapter(token_date=date.today() - timedelta(days=1))
    s = TokenRefreshService()
    assert s.validate_token(adapter) is False


def test_validate_token_kite_no_date():
    adapter = kite_adapter(token_date=None)
    s = TokenRefreshService()
    assert s.validate_token(adapter) is False


def test_validate_token_angel_valid():
    adapter = angel_adapter()
    s = TokenRefreshService()
    assert s.validate_token(adapter) is True


def test_validate_token_angel_disconnected():
    adapter = angel_adapter(connected=False)
    s = TokenRefreshService()
    assert s.validate_token(adapter) is False


def test_validate_token_unknown_adapter():
    s = TokenRefreshService()
    assert s.validate_token(object()) is False


# ── check_auth ───────────────────────────────────────────────────────────

def test_check_auth_kite():
    adapter = kite_adapter()
    s = TokenRefreshService()
    result = s.check_auth(adapter)
    assert result["valid"] is True
    assert result["broker"] == "kite"


def test_check_auth_angel():
    adapter = angel_adapter()
    s = TokenRefreshService()
    result = s.check_auth(adapter)
    assert result["broker"] == "angel"


def test_check_auth_unknown():
    s = TokenRefreshService()
    result = s.check_auth(object())
    assert result["valid"] is False
    assert result["broker"] == "unknown"


# ── status ───────────────────────────────────────────────────────────────

def test_status():
    s = TokenRefreshService()
    st = s.status()
    assert st["enabled"] is True
    assert st["interval_mins"] == 60.0
    assert st["grace_period_mins"] == 30.0
    assert st["retry_count"] == 3
    assert isinstance(st["last_check"], dict)
    assert isinstance(st["refresh_count"], dict)
    assert isinstance(st["last_error"], dict)


def test_status_disabled():
    s = TokenRefreshService(cfg={"token_refresh_enabled": False})
    st = s.status()
    assert st["enabled"] is False


def test_status_tracks_refresh_count():
    s = TokenRefreshService()
    with s._lock:
        s._refresh_count["kite"] = 2
    st = s.status()
    assert st["refresh_count"]["kite"] == 2


# ── check_and_refresh (disabled) ─────────────────────────────────────────

def test_check_and_refresh_disabled():
    s = TokenRefreshService(cfg={"token_refresh_enabled": False})
    result = s.check_and_refresh({"kite": object()})
    assert result == {"kite": True}


# ── check_and_refresh with valid adapters ────────────────────────────────

def test_check_and_refresh_valid_kite():
    adapter = kite_adapter()
    s = TokenRefreshService(cfg={
        "token_refresh_enabled": True,
        "token_refresh_interval_mins": 0,
    })
    result = s.check_and_refresh({"kite": adapter})
    assert result["kite"] is True


def test_check_and_refresh_valid_angel():
    adapter = angel_adapter()
    s = TokenRefreshService(cfg={
        "token_refresh_enabled": True,
        "token_refresh_interval_mins": 0,
    })
    result = s.check_and_refresh({"angel": adapter})
    assert result["angel"] is True


def test_check_and_refresh_multiple():
    s = TokenRefreshService(cfg={
        "token_refresh_enabled": True,
        "token_refresh_interval_mins": 0,
    })
    result = s.check_and_refresh({
        "kite": kite_adapter(),
        "angel": angel_adapter(),
    })
    assert result["kite"] is True
    assert result["angel"] is True


# ── kite expired: triggers refresh call ──────────────────────────────────

@patch("core.token_refresh_service.TokenRefreshService._kite_refresh", return_value=True)
def test_kite_refresh_called_when_expired(mock_refresh):
    adapter = kite_adapter(token_date=date.today() - timedelta(days=1))
    s = TokenRefreshService(cfg={
        "token_refresh_enabled": True,
        "token_refresh_interval_mins": 0,
        "token_refresh_retry_count": 1,
    })
    result = s.check_and_refresh({"kite": adapter})
    assert result["kite"] is True
    mock_refresh.assert_called_once()


@patch("core.token_refresh_service.TokenRefreshService._kite_refresh", return_value=False)
def test_kite_refresh_failure_reported(mock_refresh):
    adapter = kite_adapter(token_date=date.today() - timedelta(days=1))
    s = TokenRefreshService(cfg={
        "token_refresh_enabled": True,
        "token_refresh_interval_mins": 0,
        "token_refresh_retry_count": 1,
    })
    result = s.check_and_refresh({"kite": adapter})
    assert result["kite"] is False
    mock_refresh.assert_called_once()


# ── angel refresh ────────────────────────────────────────────────────────

@patch("core.token_refresh_service.TokenRefreshService._angel_refresh", return_value=True)
def test_angel_refresh_called_when_disconnected(mock_refresh):
    adapter = angel_adapter(connected=False)
    s = TokenRefreshService(cfg={
        "token_refresh_enabled": True,
        "token_refresh_interval_mins": 0,
        "token_refresh_retry_count": 1,
    })
    result = s.check_and_refresh({"angel": adapter})
    assert result["angel"] is True
    mock_refresh.assert_called_once()


# ── _needs_check ─────────────────────────────────────────────────────────

def test_needs_check_false_within_interval():
    s = TokenRefreshService(cfg={"token_refresh_interval_mins": 60})
    s._last_check["kite"] = time.time()
    assert s._needs_check("kite") is False


def test_needs_check_true_after_interval():
    s = TokenRefreshService(cfg={"token_refresh_interval_mins": 0})
    assert s._needs_check("kite") is True


# ── empty adapters ──────────────────────────────────────────────────────

def test_empty_adapters():
    s = TokenRefreshService(cfg={
        "token_refresh_enabled": True,
        "token_refresh_interval_mins": 0,
    })
    result = s.check_and_refresh({})
    assert result == {}


# ── _kite_token_expired edge cases ──────────────────────────────────────

def test_kite_token_expired_no_context():
    adapter = kite_adapter(token_date=date.today())
    adapter._context = None
    s = TokenRefreshService()
    # Without context, falls back to date.today() — same date → not expired
    assert s._kite_token_expired(adapter) is False


def test_kite_token_expired_null_token():
    adapter = kite_adapter(token_date=None)
    s = TokenRefreshService()
    assert s._kite_token_expired(adapter) is True


# ── _get_secrets edge cases ─────────────────────────────────────────────

def test_get_secrets_no_context():
    s = TokenRefreshService()
    adapter = object()  # no _context at all
    assert s._get_secrets("kite", adapter) == {}


def test_get_secrets_null_cfg():
    s = TokenRefreshService()
    ctx = type("Ctx", (), {})()
    ctx.cfg = None
    adapter = type("A", (), {})()
    adapter._context = ctx
    result = s._get_secrets("kite", adapter)
    assert isinstance(result, dict)


# ── _is_mock detection ──────────────────────────────────────────────────

def test_is_mock_true_for_magicmock():
    assert TokenRefreshService._is_mock(MagicMock()) is True


def test_is_mock_false_for_plain_object():
    assert TokenRefreshService._is_mock(object()) is False
