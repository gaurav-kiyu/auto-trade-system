"""Tests for core/execution/idempotency/certifier.py - Exactly-Once Execution.

Covers:
- ExecutionCert dataclass
- IdempotencyCertifier init with in-memory and file DB
- generate_execution_id deterministic hashing
- begin() for new entries and duplicate detection
- commit(), settle(), fail() lifecycle
- is_pending(), is_duplicate()
- get_pending(), get_by_execution_id(), count_by_status()
- health_check(), close()
"""
from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch


from core.execution.idempotency.certifier import (
    CertStatus,
    ExecutionCert,
    IdempotencyCertifier,
)


class TestExecutionCert:
    """ExecutionCert dataclass."""

    def test_default_fields(self):
        cert = ExecutionCert(
            cert_id="cert-1",
            execution_id="exec_100_abc123",
            symbol="NIFTY",
            action="BUY",
            params_hash="abc123",
        )
        assert cert.cert_id == "cert-1"
        assert cert.execution_id == "exec_100_abc123"
        assert cert.symbol == "NIFTY"
        assert cert.action == "BUY"
        assert cert.params_hash == "abc123"
        assert cert.status == CertStatus.PENDING
        assert cert.broker_order_id == ""
        assert cert.created_at == ""
        assert cert.committed_at is None
        assert cert.settled_at is None
        assert cert.error == ""


class TestCertifierInit:
    """IdempotencyCertifier init."""

    @patch("core.execution.idempotency.certifier.get_connection")
    def test_in_memory_init(self, mock_get_conn):
        mock_conn = MagicMock()
        mock_get_conn.return_value = mock_conn
        certifier = IdempotencyCertifier(db_path=":memory:", slot_seconds=300)
        assert certifier._slot_seconds == 300
        assert certifier._is_memory is True
        assert certifier._lock is not None

    @patch("core.execution.idempotency.certifier.get_connection")
    def test_file_init(self, mock_get_conn):
        mock_conn = MagicMock()
        mock_get_conn.return_value = mock_conn
        certifier = IdempotencyCertifier(db_path="test_cert.db", slot_seconds=600)
        assert certifier._slot_seconds == 600
        assert certifier._is_memory is False

    @patch("core.execution.idempotency.certifier.get_connection")
    def test_db_init_creates_tables(self, mock_get_conn):
        mock_conn = MagicMock()
        mock_get_conn.return_value = mock_conn
        certifier = IdempotencyCertifier(db_path=":memory:")
        assert mock_conn.execute.call_count >= 3  # pragma, CREATE TABLE, CREATE INDEX x2


class TestGenerateExecutionId:
    """generate_execution_id()."""

    @patch("core.execution.idempotency.certifier.time")
    def test_deterministic_for_same_params(self, mock_time):
        mock_time.time.return_value = 1000.0
        with patch("core.execution.idempotency.certifier.get_connection"):
            certifier = IdempotencyCertifier(db_path=":memory:", slot_seconds=300)
            eid1 = certifier.generate_execution_id("NIFTY", "BUY", 23500.0, 50, timestamp_slot=100)
            eid2 = certifier.generate_execution_id("NIFTY", "BUY", 23500.0, 50, timestamp_slot=100)
            assert eid1 == eid2  # deterministic
            assert eid1.startswith("exec_100_")

    @patch("core.execution.idempotency.certifier.time")
    def test_different_slot_different_id(self, mock_time):
        mock_time.time.return_value = 500.0
        with patch("core.execution.idempotency.certifier.get_connection"):
            certifier = IdempotencyCertifier(db_path=":memory:", slot_seconds=300)
            eid1 = certifier.generate_execution_id("NIFTY", "BUY", 23500.0, 50, timestamp_slot=100)
            eid2 = certifier.generate_execution_id("NIFTY", "BUY", 23500.0, 50, timestamp_slot=101)
            assert eid1 != eid2

    @patch("core.execution.idempotency.certifier.time")
    def test_default_timestamp_slot(self, mock_time):
        mock_time.time.return_value = 500.0  # slot = 500//300 = 1
        with patch("core.execution.idempotency.certifier.get_connection"):
            certifier = IdempotencyCertifier(db_path=":memory:", slot_seconds=300)
            eid = certifier.generate_execution_id("NIFTY", "BUY", 23500.0, 50)
            assert eid.startswith("exec_1_")

    @patch("core.execution.idempotency.certifier.time")
    def test_diff_symbol_diff_id(self, mock_time):
        mock_time.time.return_value = 600.0
        with patch("core.execution.idempotency.certifier.get_connection"):
            certifier = IdempotencyCertifier(db_path=":memory:")
            eid1 = certifier.generate_execution_id("NIFTY", "BUY", 23500.0, 50, timestamp_slot=200)
            eid2 = certifier.generate_execution_id("BANKNIFTY", "BUY", 50000.0, 25, timestamp_slot=200)
            assert eid1 != eid2


class TestBegin:
    """begin() method."""

    @patch("core.execution.idempotency.certifier.now_ist")
    @patch("core.execution.idempotency.certifier.time")
    def test_begin_new_execution(self, mock_time, mock_now):
        mock_time.time.return_value = 1000.0
        mock_time.time.return_value = 1000.0
        mock_now.return_value.__str__.return_value = "2026-01-15T09:15:00"
        with patch("core.execution.idempotency.certifier.get_connection") as mock_get_conn:
            mock_conn = MagicMock()
            mock_conn.execute.return_value.fetchone.return_value = None
            mock_get_conn.return_value = mock_conn
            certifier = IdempotencyCertifier(db_path=":memory:")
            cert_id = certifier.begin("exec_100_abc", "NIFTY", "BUY", {"qty": 50, "price": 23500})
            assert cert_id.startswith("cert_exec_100_abc_")
            mock_conn.execute.assert_any_call(
                "SELECT status FROM certs WHERE execution_id = ?",
                ("exec_100_abc",),
            )

    @patch("core.execution.idempotency.certifier.now_ist")
    @patch("core.execution.idempotency.certifier.time")
    def test_begin_existing_execution(self, mock_time, mock_now):
        mock_time.time.return_value = 2000.0
        mock_now.return_value.__str__.return_value = "2026-01-15T10:00:00"
        with patch("core.execution.idempotency.certifier.get_connection") as mock_get_conn:
            mock_conn = MagicMock()
            # First call returns None (no existing), second returns PENDING
            mock_conn.execute.return_value.fetchone.side_effect = [None, ("PENDING",)]
            mock_get_conn.return_value = mock_conn
            certifier = IdempotencyCertifier(db_path=":memory:")
            # First begin
            cert_id1 = certifier.begin("exec_dupe", "NIFTY", "BUY", {"qty": 50})
            # mock_conn.execute.call_args[0][0] changes now
            # Reset to test duplicate
            cert_id2 = certifier.begin("exec_dupe", "NIFTY", "BUY", {"qty": 50})
            # Second call logs warning but doesn't raise
            assert cert_id2 is not None


class TestLifecycle:
    """Full commit/settle/fail lifecycle."""

    @patch("core.execution.idempotency.certifier.now_ist")
    @patch("core.execution.idempotency.certifier.time")
    def test_commit(self, mock_time, mock_now):
        mock_time.time.return_value = 3000.0
        mock_now.return_value.__str__.return_value = "2026-01-15T11:00:00"
        with patch("core.execution.idempotency.certifier.get_connection") as mock_get_conn:
            mock_conn = MagicMock()
            mock_conn.execute.return_value.fetchone.return_value = None
            mock_get_conn.return_value = mock_conn
            certifier = IdempotencyCertifier(db_path=":memory:")
            cert_id = certifier.begin("exec_commit", "NIFTY", "BUY", {})
            certifier.commit(cert_id, broker_order_id="broker-123")
            # Verify UPDATE was called
            update_calls = [c for c in mock_conn.execute.call_args_list if "UPDATE certs" in str(c)]
            assert len(update_calls) >= 1

    @patch("core.execution.idempotency.certifier.now_ist")
    @patch("core.execution.idempotency.certifier.time")
    def test_settle(self, mock_time, mock_now):
        mock_time.time.return_value = 4000.0
        mock_now.return_value.__str__.return_value = "2026-01-15T12:00:00"
        with patch("core.execution.idempotency.certifier.get_connection") as mock_get_conn:
            mock_conn = MagicMock()
            mock_conn.execute.return_value.fetchone.return_value = None
            mock_get_conn.return_value = mock_conn
            certifier = IdempotencyCertifier(db_path=":memory:")
            cert_id = certifier.begin("exec_settle", "NIFTY", "BUY", {})
            certifier.settle(cert_id)
            update_calls = [c for c in mock_conn.execute.call_args_list if "SETTLED" in str(c)]
            assert len(update_calls) >= 1

    @patch("core.execution.idempotency.certifier.now_ist")
    @patch("core.execution.idempotency.certifier.time")
    def test_fail(self, mock_time, mock_now):
        mock_time.time.return_value = 5000.0
        mock_now.return_value.__str__.return_value = "2026-01-15T13:00:00"
        with patch("core.execution.idempotency.certifier.get_connection") as mock_get_conn:
            mock_conn = MagicMock()
            mock_conn.execute.return_value.fetchone.return_value = None
            mock_get_conn.return_value = mock_conn
            certifier = IdempotencyCertifier(db_path=":memory:")
            cert_id = certifier.begin("exec_fail", "NIFTY", "BUY", {})
            certifier.fail(cert_id, error="Broker rejected")


class TestQueryMethods:
    """is_pending, is_duplicate, get_pending, etc."""

    @patch("core.execution.idempotency.certifier.get_connection")
    def test_is_pending_true(self, mock_get_conn):
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = ("PENDING",)
        mock_get_conn.return_value = mock_conn
        certifier = IdempotencyCertifier(db_path=":memory:")
        assert certifier.is_pending("exec_xyz") is True

    @patch("core.execution.idempotency.certifier.get_connection")
    def test_is_pending_false_for_committed(self, mock_get_conn):
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = ("COMMITTED",)
        mock_get_conn.return_value = mock_conn
        certifier = IdempotencyCertifier(db_path=":memory:")
        assert certifier.is_pending("exec_xyz") is False

    @patch("core.execution.idempotency.certifier.get_connection")
    def test_is_pending_false_when_missing(self, mock_get_conn):
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = None
        mock_get_conn.return_value = mock_conn
        certifier = IdempotencyCertifier(db_path=":memory:")
        assert certifier.is_pending("exec_xyz") is False

    @patch("core.execution.idempotency.certifier.get_connection")
    def test_is_duplicate_true(self, mock_get_conn):
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = ("PENDING",)
        mock_get_conn.return_value = mock_conn
        certifier = IdempotencyCertifier(db_path=":memory:")
        assert certifier.is_duplicate("exec_xyz") is True

    @patch("core.execution.idempotency.certifier.get_connection")
    def test_is_duplicate_false(self, mock_get_conn):
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = None
        mock_get_conn.return_value = mock_conn
        certifier = IdempotencyCertifier(db_path=":memory:")
        assert certifier.is_duplicate("exec_xyz") is False

    @patch("core.execution.idempotency.certifier.get_connection")
    def test_get_pending_empty(self, mock_get_conn):
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = []
        mock_get_conn.return_value = mock_conn
        certifier = IdempotencyCertifier(db_path=":memory:")
        assert certifier.get_pending() == []

    @patch("core.execution.idempotency.certifier.get_connection")
    def test_count_by_status_empty(self, mock_get_conn):
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = []
        mock_get_conn.return_value = mock_conn
        certifier = IdempotencyCertifier(db_path=":memory:")
        assert certifier.count_by_status() == {}

    @patch("core.execution.idempotency.certifier.get_connection")
    def test_health_check(self, mock_get_conn):
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = [("PENDING", 3), ("COMMITTED", 5)]
        mock_get_conn.return_value = mock_conn
        certifier = IdempotencyCertifier(db_path="test_cert.db")
        health = certifier.health_check()
        assert "db_path" in health
        assert "by_status" in health


class TestClose:
    """close() method."""

    def test_close_calls_conn_close(self):
        with patch("core.execution.idempotency.certifier.get_connection") as mock_get_conn:
            mock_conn = MagicMock()
            mock_get_conn.return_value = mock_conn
            certifier = IdempotencyCertifier(db_path=":memory:")
            certifier.close()
            mock_conn.close.assert_called_once()

    def test_close_safe_when_no_conn(self):
        certifier = IdempotencyCertifier.__new__(IdempotencyCertifier)
        certifier._lock = threading.RLock()
        certifier._conn = None
        certifier.close()  # should not raise
