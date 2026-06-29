"""
Tests for core/execution/idempotency/manager.py - IdempotencyManager.

Covers:
  - IdempotencyRecord dataclass
  - Initialization (in-memory, with persistence path)
  - generate_key (deterministic, excludes timestamp)
  - is_duplicate (in cache, in-flight, unknown)
  - mark_in_flight / clear_in_flight
  - confirm_execution (moves from in-flight to cache, eviction)
  - get_result / store_result
  - _cleanup (expired entries, stale in-flight)
  - SQLite persistence (save/load confirmed, cleanup old in-flight)
"""

from __future__ import annotations

import os
import tempfile
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from core.execution.idempotency.manager import IdempotencyManager, IdempotencyRecord


def _cleanup_db(db_path: str) -> None:
    """
    Safely remove a SQLite DB file on Windows.
    Retries with backoff because WAL/SHM companion files may hold locks momentarily.
    """
    import time as _time
    # Remove companion WAL/SHM files first
    for suffix in ("-wal", "-shm"):
        companion = db_path + suffix
        if os.path.exists(companion):
            try:
                os.unlink(companion)
            except PermissionError:
                pass
    for attempt in range(5):
        try:
            if os.path.exists(db_path):
                os.unlink(db_path)
            return
        except PermissionError:
            _time.sleep(0.1 * (attempt + 1))


# ═══════════════════════════════════════════════════════════════════════
#  IdempotencyRecord
# ═══════════════════════════════════════════════════════════════════════


class TestIdempotencyRecord:
    def test_fields(self):
        now = datetime(2026, 1, 1, 12, 0, 0)
        rec = IdempotencyRecord(timestamp=now, result={"status": "FILLED"})
        assert rec.timestamp == now
        assert rec.result == {"status": "FILLED"}


# ═══════════════════════════════════════════════════════════════════════
#  Initialization
# ═══════════════════════════════════════════════════════════════════════


class TestInitialization:
    def test_in_memory_defaults(self):
        mgr = IdempotencyManager()
        assert mgr._cache == {}
        assert mgr._in_flight == {}
        assert mgr._cache_size == 1000
        assert mgr._expiry_hours == 24

    def test_custom_config(self):
        mgr = IdempotencyManager(cache_size=50, expiry_hours=12)
        assert mgr._cache_size == 50
        assert mgr._expiry_hours == 12

    def test_with_persistence_path(self):
        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            IdempotencyManager(persistence_path=db_path)
            # Table should be created
            import sqlite3
            conn = sqlite3.connect(db_path)
            try:
                tables = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            finally:
                conn.close()
            table_names = [t[0] for t in tables]
            assert "idempotency_keys" in table_names
        finally:
            _cleanup_db(db_path)


# ═══════════════════════════════════════════════════════════════════════
#  generate_key
# ═══════════════════════════════════════════════════════════════════════


class TestGenerateKey:
    def test_deterministic(self):
        mgr = IdempotencyManager()
        req = MagicMock(symbol="NIFTY", direction="BUY", strike="23500", qty=50)
        ctx = MagicMock(signal_id="sig-001")
        key1 = mgr.generate_key(req, ctx)
        key2 = mgr.generate_key(req, ctx)
        assert key1 == key2

    def test_different_inputs_different_keys(self):
        mgr = IdempotencyManager()
        req1 = MagicMock(symbol="NIFTY", direction="BUY", strike="23500", qty=50)
        req2 = MagicMock(symbol="BANKNIFTY", direction="SELL", strike="50000", qty=25)
        ctx = MagicMock(signal_id="sig-001")
        key1 = mgr.generate_key(req1, ctx)
        key2 = mgr.generate_key(req2, ctx)
        assert key1 != key2

    def test_does_not_include_timestamp(self):
        """Timestamp must NOT be included to ensure same signal produces same key."""
        mgr = IdempotencyManager()
        req = MagicMock(symbol="NIFTY", direction="BUY", strike="23500", qty=50)
        ctx1 = MagicMock(signal_id="sig-001")
        ctx2 = MagicMock(signal_id="sig-001")
        # Even with different contexts (same signal_id), key should be same
        key1 = mgr.generate_key(req, ctx1)
        key2 = mgr.generate_key(req, ctx2)
        assert key1 == key2


# ═══════════════════════════════════════════════════════════════════════
#  is_duplicate
# ═══════════════════════════════════════════════════════════════════════


class TestIsDuplicate:
    def test_unknown_key_returns_false(self):
        mgr = IdempotencyManager()
        assert mgr.is_duplicate("unknown-key") is False

    def test_key_in_cache_returns_true(self):
        mgr = IdempotencyManager()
        mgr._cache["existing-key"] = (datetime.now(), {"status": "FILLED"})
        assert mgr.is_duplicate("existing-key") is True

    def test_key_in_flight_returns_true(self):
        mgr = IdempotencyManager()
        mgr._in_flight["in-flight-key"] = datetime.now()
        assert mgr.is_duplicate("in-flight-key") is True


# ═══════════════════════════════════════════════════════════════════════
#  mark_in_flight / clear_in_flight
# ═══════════════════════════════════════════════════════════════════════


class TestMarkInFlight:
    def test_marks_key(self):
        mgr = IdempotencyManager()
        mgr.mark_in_flight("test-key")
        assert "test-key" in mgr._in_flight

    def test_is_duplicate_after_mark(self):
        mgr = IdempotencyManager()
        mgr.mark_in_flight("test-key")
        assert mgr.is_duplicate("test-key") is True


class TestClearInFlight:
    def test_clears_marked_key(self):
        mgr = IdempotencyManager()
        mgr.mark_in_flight("test-key")
        mgr.clear_in_flight("test-key")
        assert "test-key" not in mgr._in_flight
        assert mgr.is_duplicate("test-key") is False

    def test_clear_unknown_key_does_nothing(self):
        mgr = IdempotencyManager()
        mgr.clear_in_flight("unknown")
        # Should not raise


# ═══════════════════════════════════════════════════════════════════════
#  confirm_execution
# ═══════════════════════════════════════════════════════════════════════


class TestConfirmExecution:
    def test_moves_from_in_flight_to_cache(self):
        mgr = IdempotencyManager()
        mgr.mark_in_flight("test-key")
        mgr.confirm_execution("test-key", {"status": "FILLED"})
        assert "test-key" not in mgr._in_flight
        assert "test-key" in mgr._cache
        assert mgr._cache["test-key"][1] == {"status": "FILLED"}

    def test_is_duplicate_after_confirm(self):
        mgr = IdempotencyManager()
        mgr.confirm_execution("test-key", {"order_id": "ORD-001"})
        assert mgr.is_duplicate("test-key") is True

    def test_evicts_oldest_when_full(self):
        mgr = IdempotencyManager(cache_size=2)
        mgr.confirm_execution("key-1", "result-1")
        mgr.confirm_execution("key-2", "result-2")
        mgr.confirm_execution("key-3", "result-3")
        assert "key-1" not in mgr._cache
        assert len(mgr._cache) == 2


# ═══════════════════════════════════════════════════════════════════════
#  get_result / store_result
# ═══════════════════════════════════════════════════════════════════════


class TestGetResult:
    def test_known_key_returns_result(self):
        mgr = IdempotencyManager()
        mgr.confirm_execution("test-key", {"order_id": "ORD-001"})
        result = mgr.get_result("test-key")
        assert result == {"order_id": "ORD-001"}

    def test_unknown_key_returns_none(self):
        mgr = IdempotencyManager()
        result = mgr.get_result("unknown")
        assert result is None


class TestStoreResult:
    def test_delegates_to_confirm_execution(self):
        mgr = IdempotencyManager()
        mgr.store_result("test-key", {"order_id": "ORD-002"})
        assert "test-key" in mgr._cache
        assert mgr._cache["test-key"][1] == {"order_id": "ORD-002"}


# ═══════════════════════════════════════════════════════════════════════
#  _cleanup
# ═══════════════════════════════════════════════════════════════════════


class TestCleanup:
    def test_removes_expired_cache_entries(self):
        mgr = IdempotencyManager(expiry_hours=1)
        expired_time = datetime.now() - timedelta(hours=2)
        mgr._cache["expired-key"] = (expired_time, "old-result")
        with patch("core.execution.idempotency.manager.now_ist", return_value=datetime.now()):
            mgr._cleanup()
        assert "expired-key" not in mgr._cache

    def test_keeps_fresh_cache_entries(self):
        mgr = IdempotencyManager(expiry_hours=24)
        fresh_time = datetime.now() - timedelta(hours=1)
        mgr._cache["fresh-key"] = (fresh_time, "result")
        mgr._cleanup()
        assert "fresh-key" in mgr._cache

    def test_removes_stale_in_flight_entries(self):
        mgr = IdempotencyManager()
        stale_time = datetime.now() - timedelta(hours=2)
        mgr._in_flight["stale-key"] = stale_time
        with patch("core.execution.idempotency.manager.now_ist", return_value=datetime.now()):
            mgr._cleanup()
        assert "stale-key" not in mgr._in_flight

    def test_keeps_recent_in_flight_entries(self):
        mgr = IdempotencyManager()
        recent_time = datetime.now() - timedelta(minutes=30)
        mgr._in_flight["recent-key"] = recent_time
        mgr._cleanup()
        assert "recent-key" in mgr._in_flight


# ═══════════════════════════════════════════════════════════════════════
#  SQLite Persistence Integration
# ═══════════════════════════════════════════════════════════════════════


class TestPersistence:
    def test_confirm_execution_persists_to_db(self):
        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            mgr = IdempotencyManager(persistence_path=db_path)
            mgr.confirm_execution("persist-key", {"order_id": "ORD-001"})

            import sqlite3
            conn = sqlite3.connect(db_path)
            try:
                rows = conn.execute(
                    "SELECT key, status FROM idempotency_keys"
                ).fetchall()
            finally:
                conn.close()
            assert ("persist-key", "confirmed") in rows
        finally:
            _cleanup_db(db_path)

    def test_mark_in_flight_persists_to_db(self):
        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            mgr = IdempotencyManager(persistence_path=db_path)
            mgr.mark_in_flight("flight-key")

            import sqlite3
            conn = sqlite3.connect(db_path)
            try:
                rows = conn.execute(
                    "SELECT key, status FROM idempotency_keys"
                ).fetchall()
            finally:
                conn.close()
            assert ("flight-key", "in_flight") in rows
        finally:
            _cleanup_db(db_path)

    def test_clear_in_flight_removes_from_db(self):
        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            mgr = IdempotencyManager(persistence_path=db_path)
            mgr.mark_in_flight("clear-key")
            mgr.clear_in_flight("clear-key")

            import sqlite3
            conn = sqlite3.connect(db_path)
            try:
                rows = conn.execute(
                    "SELECT key, status FROM idempotency_keys WHERE key = ?",
                    ("clear-key",),
                ).fetchall()
            finally:
                conn.close()
            assert len(rows) == 0
        finally:
            _cleanup_db(db_path)

    def test_loads_existing_keys_on_init(self):
        """Keys persisted in a previous session should be loaded on init."""
        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            # First session: persist a key
            mgr1 = IdempotencyManager(persistence_path=db_path)
            mgr1.confirm_execution("survive-key", {"order_id": "ORD-001"})
            mgr1._cache.clear()  # Simulate restart

            # Second session: should load from DB
            mgr2 = IdempotencyManager(persistence_path=db_path)
            assert mgr2.is_duplicate("survive-key") is True
        finally:
            _cleanup_db(db_path)
