"""Tests for core/wal/journal.py - Write-Ahead Intent Journal.

Covers:
- IntentStatus constants
- Intent dataclass defaults
- WriteAheadJournal init with db init
- append() with async and fallback sync
- commit(), fail(), settle() lifecycle
- get_intent(), get_pending(), get_unsettled()
- get_by_correlation(), count_by_status()
- cleanup(), flush(), close()
- health_check()
"""
from __future__ import annotations

import sqlite3
import threading
from unittest.mock import MagicMock, call, patch

import pytest

from core.wal.journal import (
    Intent,
    IntentStatus,
    WriteAheadJournal,
)


class TestIntentStatus:
    """IntentStatus constants."""

    def test_constants(self):
        assert IntentStatus.PENDING == "PENDING"
        assert IntentStatus.COMMITTED == "COMMITTED"
        assert IntentStatus.SETTLED == "SETTLED"
        assert IntentStatus.FAILED == "FAILED"


class TestIntent:
    """Intent dataclass defaults."""

    def test_defaults(self):
        intent = Intent(
            intent_id="intent-1",
            action="BUY",
            params={"qty": 50, "symbol": "NIFTY"},
        )
        assert intent.intent_id == "intent-1"
        assert intent.action == "BUY"
        assert intent.params == {"qty": 50, "symbol": "NIFTY"}
        assert intent.risk_verdict is None
        assert intent.config_snapshot_hash == ""
        assert intent.correlation_id == ""
        assert intent.status == IntentStatus.PENDING
        assert intent.created_at == ""
        assert intent.committed_at is None
        assert intent.failed_at is None
        assert intent.error_message == ""


class TestWriteAheadJournalInit:
    """WriteAheadJournal construction."""

    @patch("core.wal.journal.get_connection")
    def test_init_creates_db(self, mock_get_conn):
        mock_conn = MagicMock()
        mock_get_conn.return_value = mock_conn
        journal = WriteAheadJournal(db_path=":memory:")
        assert journal._lock is not None

    @patch("core.wal.journal.get_connection")
    def test_init_runs_ddl(self, mock_get_conn):
        mock_conn = MagicMock()
        mock_get_conn.return_value = mock_conn
        journal = WriteAheadJournal(db_path=":memory:")
        mock_conn.executescript.assert_called_once()
        assert "CREATE TABLE IF NOT EXISTS intents" in mock_conn.executescript.call_args[0][0]


class TestAppend:
    """append() method."""

    @patch("core.wal.journal.get_connection")
    @patch("core.wal.journal.now_ist")
    def test_append_sets_created_at(self, mock_now, mock_get_conn):
        mock_now.return_value.__str__.return_value = "2026-01-15T09:15:00"
        mock_conn = MagicMock()
        mock_get_conn.return_value = mock_conn

        journal = WriteAheadJournal(db_path=":memory:")
        intent = Intent(intent_id="intent-1", action="BUY", params={"qty": 50})
        with patch.object(journal, "_get_async_writer") as mock_writer:
            mock_writer.return_value.submit.return_value = True
            journal.append(intent)

        assert intent.created_at == "2026-01-15T09:15:00"
        assert intent.correlation_id != ""  # auto-generated UUID

    @patch("core.wal.journal.get_connection")
    @patch("core.wal.journal.now_ist")
    def test_append_falls_back_to_sync_when_queue_full(self, mock_now, mock_get_conn):
        mock_now.return_value.__str__.return_value = "2026-01-15T10:00:00"
        mock_conn = MagicMock()
        mock_get_conn.return_value = mock_conn

        journal = WriteAheadJournal(db_path=":memory:")
        intent = Intent(intent_id="intent-2", action="SELL", params={"qty": 25})
        with patch.object(journal, "_get_async_writer") as mock_writer:
            mock_writer.return_value.submit.return_value = False  # queue full
            journal.append(intent)

        # Falls back to sync execute
        assert mock_conn.execute.call_count >= 1
        assert mock_conn.commit.call_count >= 1

    @patch("core.wal.journal.get_connection")
    @patch("core.wal.journal.now_ist")
    def test_append_preserves_existing_created_at(self, mock_now, mock_get_conn):
        mock_now.return_value.__str__.return_value = "2026-01-15T11:00:00"
        mock_conn = MagicMock()
        mock_get_conn.return_value = mock_conn

        journal = WriteAheadJournal(db_path=":memory:")
        intent = Intent(
            intent_id="intent-3", action="BUY", params={},
            created_at="2026-01-14T09:00:00",
        )
        with patch.object(journal, "_get_async_writer") as mock_writer:
            mock_writer.return_value.submit.return_value = True
            journal.append(intent)

        assert intent.created_at == "2026-01-14T09:00:00"  # preserved


class TestLifecycle:
    """commit, fail, settle lifecycle."""

    @patch("core.wal.journal.get_connection")
    @patch("core.wal.journal.now_ist")
    def test_commit_sets_status(self, mock_now, mock_get_conn):
        mock_now.return_value.__str__.return_value = "2026-01-15T12:00:00"
        mock_conn = MagicMock()
        mock_get_conn.return_value = mock_conn

        journal = WriteAheadJournal(db_path=":memory:")
        with patch.object(journal, "_get_async_writer") as mock_writer:
            mock_writer.return_value.submit.return_value = True
            journal.commit("intent-1")

        # Verify the correct SQL was submitted
        mock_writer.return_value.submit.assert_called_with(
            "UPDATE intents SET status = ?, committed_at = ? WHERE intent_id = ?",
            ("COMMITTED", "2026-01-15T12:00:00", "intent-1"),
        )

    @patch("core.wal.journal.get_connection")
    @patch("core.wal.journal.now_ist")
    def test_fail_sets_status(self, mock_now, mock_get_conn):
        mock_now.return_value.__str__.return_value = "2026-01-15T13:00:00"
        mock_conn = MagicMock()
        mock_get_conn.return_value = mock_conn

        journal = WriteAheadJournal(db_path=":memory:")
        with patch.object(journal, "_get_async_writer") as mock_writer:
            mock_writer.return_value.submit.return_value = True
            journal.fail("intent-1", error="Timeout")

        mock_writer.return_value.submit.assert_called_with(
            "UPDATE intents SET status = ?, failed_at = ?, error_message = ? WHERE intent_id = ?",
            ("FAILED", "2026-01-15T13:00:00", "Timeout", "intent-1"),
        )

    @patch("core.wal.journal.get_connection")
    @patch("core.wal.journal.now_ist")
    def test_settle_requires_committed(self, mock_now, mock_get_conn):
        mock_now.return_value.__str__.return_value = "2026-01-15T14:00:00"
        mock_conn = MagicMock()
        mock_get_conn.return_value = mock_conn

        journal = WriteAheadJournal(db_path=":memory:")
        with patch.object(journal, "_get_async_writer") as mock_writer:
            mock_writer.return_value.submit.return_value = True
            journal.settle("intent-1")

        mock_writer.return_value.submit.assert_called_with(
            "UPDATE intents SET status = ? WHERE intent_id = ? AND status = ?",
            ("SETTLED", "intent-1", "COMMITTED"),
        )

    @patch("core.wal.journal.get_connection")
    @patch("core.wal.journal.now_ist")
    def test_commit_falls_back_to_sync(self, mock_now, mock_get_conn):
        mock_now.return_value.__str__.return_value = "2026-01-15T15:00:00"
        mock_conn = MagicMock()
        mock_get_conn.return_value = mock_conn

        journal = WriteAheadJournal(db_path=":memory:")
        with patch.object(journal, "_get_async_writer") as mock_writer:
            mock_writer.return_value.submit.return_value = False
            journal.commit("intent-1")

        # Falls back to sync execution
        assert mock_conn.execute.call_count >= 1


class TestQueryMethods:
    """get_intent, get_pending, get_unsettled, etc."""

    @patch("core.wal.journal.get_connection")
    def test_get_intent_found(self, mock_get_conn):
        mock_conn = MagicMock()
        # Build a mock row that works with dict() and [] access
        row_data = {
            "intent_id": "intent-1",
            "action": "BUY",
            "params_json": '{"qty": 50}',
            "risk_verdict_json": None,
            "config_snapshot_hash": "",
            "correlation_id": "",
            "status": "PENDING",
            "created_at": "T1",
            "committed_at": None,
            "failed_at": None,
            "error_message": "",
        }
        mock_rows = [row_data]
        mock_conn.execute.return_value.fetchall.return_value = mock_rows
        mock_get_conn.return_value = mock_conn

        journal = WriteAheadJournal(db_path=":memory:")
        journal._async_writer = None
        journal._conn = mock_conn
        intent = journal.get_intent("intent-1")
        assert intent is not None
        assert intent.intent_id == "intent-1"
        assert intent.action == "BUY"
        assert intent.params == {"qty": 50}

    @patch("core.wal.journal.get_connection")
    def test_get_intent_not_found(self, mock_get_conn):
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = []
        mock_get_conn.return_value = mock_conn
        journal = WriteAheadJournal(db_path=":memory:")
        journal._async_writer = None
        journal._conn = mock_conn
        assert journal.get_intent("nonexistent") is None

    @patch("core.wal.journal.get_connection")
    def test_get_pending_empty(self, mock_get_conn):
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = []
        mock_get_conn.return_value = mock_conn
        journal = WriteAheadJournal(db_path=":memory:")
        journal._async_writer = None
        journal._conn = mock_conn
        assert len(journal.get_pending()) == 0

    @patch("core.wal.journal.get_connection")
    def test_get_unsettled(self, mock_get_conn):
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = []
        mock_get_conn.return_value = mock_conn
        journal = WriteAheadJournal(db_path=":memory:")
        journal._async_writer = None
        journal._conn = mock_conn
        assert len(journal.get_unsettled()) == 0

    @patch("core.wal.journal.get_connection")
    def test_count_by_status(self, mock_get_conn):
        mock_conn = MagicMock()
        mock_conn.row_factory = sqlite3.Row
        mock_row1 = ("PENDING", 5)
        mock_row2 = ("COMMITTED", 3)
        mock_conn.execute.return_value.fetchall.return_value = [mock_row1, mock_row2]
        mock_get_conn.return_value = mock_conn
        journal = WriteAheadJournal(db_path=":memory:")
        journal._async_writer = None
        journal._conn = mock_conn
        counts = journal.count_by_status()
        assert counts == {"PENDING": 5, "COMMITTED": 3}


class TestCleanup:
    """cleanup() method."""

    @patch("core.wal.journal.get_connection")
    @patch("core.wal.journal.now_ist")
    def test_cleanup_deletes_old_settled(self, mock_now, mock_get_conn):
        from datetime import timedelta
        mock_now_inst = MagicMock()
        mock_now_inst.__sub__.return_value.__str__.return_value = "2026-01-01T00:00:00"
        mock_now.return_value = mock_now_inst
        mock_conn = MagicMock()
        mock_conn.total_changes = 3
        mock_get_conn.return_value = mock_conn

        journal = WriteAheadJournal(db_path=":memory:")
        journal._async_writer = None
        journal._conn = mock_conn
        deleted = journal.cleanup(max_age_hours=168)
        assert isinstance(deleted, int)


class TestFlushAndClose:
    """flush() and close()."""

    @patch("core.wal.journal.get_connection")
    @patch("core.wal.journal.time")
    def test_flush_polls_until_empty(self, mock_time, mock_get_conn):
        mock_conn = MagicMock()
        mock_get_conn.return_value = mock_conn
        mock_time.time.return_value = 100.0

        journal = WriteAheadJournal(db_path=":memory:")
        mock_writer = MagicMock()
        mock_writer.stats = {"queue_size": 0}
        journal._async_writer = mock_writer
        journal._conn = mock_conn
        journal.flush()
        # Should return immediately since queue is empty

    @patch("core.wal.journal.get_connection")
    @patch("core.wal.journal.time")
    def test_flush_timed_out(self, mock_time, mock_get_conn):
        mock_conn = MagicMock()
        mock_get_conn.return_value = mock_conn
        mock_time.time.side_effect = [0.0, 0.1, 6.0]  # First check, wait, timeout

        journal = WriteAheadJournal(db_path=":memory:")
        mock_writer = MagicMock()
        mock_writer.stats = {"queue_size": 5}  # Never drains
        journal._async_writer = mock_writer
        journal._conn = mock_conn
        # Should timeout after 5s without raising
        journal.flush()

    @patch("core.wal.journal.get_connection")
    def test_close_stops_async_writer(self, mock_get_conn):
        mock_conn = MagicMock()
        mock_get_conn.return_value = mock_conn

        journal = WriteAheadJournal(db_path=":memory:")
        mock_writer = MagicMock()
        journal._async_writer = mock_writer
        journal._conn = mock_conn
        journal.close()
        mock_writer.stop.assert_called_once_with(block=True, timeout=5.0)
        assert journal._async_writer is None

    @patch("core.wal.journal.get_connection")
    def test_close_closes_connection(self, mock_get_conn):
        mock_conn = MagicMock()
        mock_get_conn.return_value = mock_conn

        journal = WriteAheadJournal(db_path=":memory:")
        journal._async_writer = None
        journal._conn = mock_conn
        journal.close()
        mock_conn.close.assert_called_once()
        assert journal._conn is None

    @patch("core.wal.journal.get_connection")
    def test_health_check(self, mock_get_conn):
        mock_conn = MagicMock()
        mock_conn.row_factory = None
        mock_row1 = ("PENDING", 2)
        mock_row2 = ("COMMITTED", 1)
        mock_conn.execute.return_value.fetchall.return_value = [mock_row1, mock_row2]
        mock_get_conn.return_value = mock_conn

        journal = WriteAheadJournal(db_path="test_wal.db")
        mock_writer = MagicMock()
        mock_writer.stats = {"queue_size": 0, "written": 10, "errors": 0}
        journal._async_writer = mock_writer
        journal._conn = mock_conn
        health = journal.health_check()
        assert "db_path" in health
        assert "by_status" in health
        assert "async_writer" in health
        assert health["async_writer"]["written"] == 10
