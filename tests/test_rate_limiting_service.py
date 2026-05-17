"""Tests for core/services/rate_limiting_service.py."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from core.ports.rate_limiting.rate_limit_port import LimitResult, RateLimitConfig
from core.services.rate_limiting_service import RateLimitingService


# ── Constructor ──────────────────────────────────────────────────────────

def test_constructor():
    rl = RateLimitingService()
    assert rl._counters == {}
    assert rl._sliding_windows == {}
    assert rl._token_buckets == {}


# ── Fixed window algorithm ──────────────────────────────────────────────

def test_fixed_window_allows_up_to_limit():
    rl = RateLimitingService()
    config = RateLimitConfig(limit=3, window=60, algorithm="fixed_window")
    rl.update_config("test", config)

    for i in range(3):
        result = rl.is_allowed("test")
        assert result == LimitResult.ALLOWED, f"Request {i+1} should be allowed"

    result = rl.is_allowed("test")
    assert result == LimitResult.DENIED


def test_fixed_window_resets_after_window():
    rl = RateLimitingService()
    config = RateLimitConfig(limit=1, window=0.05, algorithm="fixed_window")
    rl.update_config("test", config)

    assert rl.is_allowed("test") == LimitResult.ALLOWED
    assert rl.is_allowed("test") == LimitResult.DENIED

    time.sleep(0.1)
    assert rl.is_allowed("test") == LimitResult.ALLOWED


# ── Sliding window algorithm ────────────────────────────────────────────

def test_sliding_window_allows_up_to_limit():
    rl = RateLimitingService()
    config = RateLimitConfig(limit=2, window=60, algorithm="sliding_window")
    rl.update_config("test", config)

    assert rl.is_allowed("test") == LimitResult.ALLOWED
    assert rl.is_allowed("test") == LimitResult.ALLOWED
    assert rl.is_allowed("test") == LimitResult.DENIED


def test_sliding_window_expires_old_entries():
    rl = RateLimitingService()
    config = RateLimitConfig(limit=1, window=0.05, algorithm="sliding_window")
    rl.update_config("test", config)

    assert rl.is_allowed("test") == LimitResult.ALLOWED
    assert rl.is_allowed("test") == LimitResult.DENIED

    time.sleep(0.1)
    assert rl.is_allowed("test") == LimitResult.ALLOWED  # old entry expired


# ── Token bucket algorithm ──────────────────────────────────────────────

def test_token_bucket_allows_initial_burst():
    rl = RateLimitingService()
    config = RateLimitConfig(limit=5, window=60, algorithm="token_bucket")
    rl.update_config("test", config)

    for i in range(5):
        result = rl.is_allowed("test")
        assert result == LimitResult.ALLOWED, f"Burst request {i+1} should be allowed"

    result = rl.is_allowed("test")
    assert result == LimitResult.DENIED


def test_token_bucket_refills():
    rl = RateLimitingService()
    config = RateLimitConfig(limit=3, window=0.1, algorithm="token_bucket")
    rl.update_config("test", config)

    # Exhaust 3 tokens
    for _ in range(3):
        assert rl.is_allowed("test") == LimitResult.ALLOWED
    assert rl.is_allowed("test") == LimitResult.DENIED

    # Wait for refill (3 tokens / 0.1s = 30 tps → ~1 token in 33ms)
    # Window = 0.1s → rate = 3/0.1 = 30 tokens/sec
    # In 0.05s → ~1.5 tokens refilled
    time.sleep(0.06)

    assert rl.is_allowed("test") == LimitResult.ALLOWED


# ── get_status ──────────────────────────────────────────────────────────

def test_get_status():
    rl = RateLimitingService()
    config = RateLimitConfig(limit=10, window=60, algorithm="fixed_window")
    rl.update_config("test", config)

    # Use 3 of 10
    for _ in range(3):
        rl.is_allowed("test")

    status = rl.get_status("test")
    assert status.allowed is True
    assert status.remaining == 7
    assert status.limit == 10
    assert status.window == 60
    assert status.algorithm == "fixed_window"


def test_get_status_exhausted():
    rl = RateLimitingService()
    config = RateLimitConfig(limit=2, window=60, algorithm="fixed_window")
    rl.update_config("test", config)

    for _ in range(2):
        rl.is_allowed("test")

    status = rl.get_status("test")
    assert status.allowed is False
    assert status.remaining == 0


# ── reset ───────────────────────────────────────────────────────────────

def test_reset_clears_counters():
    rl = RateLimitingService()
    config = RateLimitConfig(limit=1, window=60, algorithm="fixed_window")
    rl.update_config("test", config)

    rl.is_allowed("test")
    assert rl._counters["test"].count == 1

    rl.reset("test")
    assert "test" not in rl._counters
    status = rl.get_status("test")
    assert status.remaining > 0


# ── health_check ────────────────────────────────────────────────────────

def test_health_check():
    rl = RateLimitingService()
    config = RateLimitConfig(limit=5, window=60, algorithm="fixed_window")
    rl.update_config("a", config)
    rl.update_config("b", config)

    health = rl.health_check()
    assert isinstance(health, dict)
    assert "fixed_window_counters" in health
    assert "sliding_windows" in health
    assert "token_buckets" in health


def test_health_check_empty():
    rl = RateLimitingService()
    health = rl.health_check()
    assert health["fixed_window_counters"] == 0
    assert health["sliding_windows"] == 0
    assert health["token_buckets"] == 0


# ── get_retry_after ─────────────────────────────────────────────────────

def test_get_retry_after():
    rl = RateLimitingService()
    config = RateLimitConfig(limit=1, window=0.05, algorithm="fixed_window")
    rl.update_config("test", config)

    # Returns 0.0 when not exhausted
    retry = rl.get_retry_after("test")
    assert retry == 0.0

    rl.is_allowed("test")
    rl.is_allowed("test")  # 2nd call, should exhaust

    # After exhaustion, retry_after should be > 0
    retry = rl.get_retry_after("test")
    assert retry is not None
    assert retry > 0


# ── Per-key isolation ───────────────────────────────────────────────────

def test_keys_are_independent():
    rl = RateLimitingService()
    config = RateLimitConfig(limit=1, window=60, algorithm="fixed_window")
    rl.update_config("a", config)
    rl.update_config("b", config)

    assert rl.is_allowed("a") == LimitResult.ALLOWED
    assert rl.is_allowed("a") == LimitResult.DENIED

    # b is still allowed
    assert rl.is_allowed("b") == LimitResult.ALLOWED
    assert rl.is_allowed("b") == LimitResult.DENIED


# ── Default config ──────────────────────────────────────────────────────

def test_default_config():
    rl = RateLimitingService()
    # No update_config — uses default
    result = rl.is_allowed("new_key")
    assert result == LimitResult.ALLOWED
    status = rl.get_status("new_key")
    assert status.limit == 100
    assert status.window == 60
    assert status.algorithm == "fixed_window"


# ── Thread safety ───────────────────────────────────────────────────────

def test_concurrent_access():
    import threading as _t
    rl = RateLimitingService()
    config = RateLimitConfig(limit=1000, window=60, algorithm="fixed_window")
    rl.update_config("test", config)

    results = []

    def worker():
        for _ in range(50):
            results.append(rl.is_allowed("test"))

    threads = [_t.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results) == 500
    assert all(r == LimitResult.ALLOWED for r in results)
