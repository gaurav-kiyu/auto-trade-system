"""Tests for core/execution/idempotency/certifier.py — IdempotencyCertifier."""

from __future__ import annotations

import time

import pytest

from core.execution.idempotency.certifier import (
    CertStatus,
    ExecutionCert,
    IdempotencyCertifier,
)


class TestCertStatus:
    """CertStatus constants coverage."""

    def test_has_all_statuses(self):
        assert CertStatus.PENDING == "PENDING"
        assert CertStatus.COMMITTED == "COMMITTED"
        assert CertStatus.SETTLED == "SETTLED"
        assert CertStatus.FAILED == "FAILED"


class TestExecutionCert:
    """ExecutionCert dataclass coverage."""

    def test_default_values(self):
        cert = ExecutionCert(
            cert_id="cert_001",
            execution_id="exec_001",
            symbol="NIFTY",
            action="BUY",
            params_hash="abc123",
        )
        assert cert.status == CertStatus.PENDING
        assert cert.broker_order_id == ""
        assert cert.error == ""
        assert cert.committed_at is None


class TestIdempotencyCertifier:
    """IdempotencyCertifier coverage using :memory: SQLite."""

    @pytest.fixture
    def certifier(self):
        c = IdempotencyCertifier(db_path=":memory:", slot_seconds=300)
        yield c
        c.close()

    def test_generate_execution_id(self, certifier):
        exec_id = certifier.generate_execution_id("NIFTY", "BUY", 23500.0, 50)
        assert exec_id.startswith("exec_")
        assert len(exec_id) > 10

    def test_generate_execution_id_with_custom_slot(self, certifier):
        exec_id = certifier.generate_execution_id("NIFTY", "BUY", 23500.0, 50, timestamp_slot=12345)
        assert "12345" in exec_id

    def test_generate_execution_id_deterministic(self, certifier):
        slot = int(time.time() / 300)
        e1 = certifier.generate_execution_id("NIFTY", "BUY", 23500.0, 50, slot)
        e2 = certifier.generate_execution_id("NIFTY", "BUY", 23500.0, 50, slot)
        assert e1 == e2  # Same params + same slot = same ID

    def test_generate_execution_id_different_slots(self, certifier):
        e1 = certifier.generate_execution_id("NIFTY", "BUY", 23500.0, 50, 100)
        e2 = certifier.generate_execution_id("NIFTY", "BUY", 23500.0, 50, 200)
        assert e1 != e2  # Different slot = different ID

    def test_begin_creates_pending_cert(self, certifier):
        exec_id = certifier.generate_execution_id("NIFTY", "BUY", 23500.0, 50)
        cert_id = certifier.begin(exec_id, "NIFTY", "BUY", {"qty": 50, "price": 23500.0})
        assert cert_id.startswith("cert_")
        assert certifier.is_pending(exec_id) is True

    def test_begin_existing_returns_cert_id(self, certifier):
        exec_id = certifier.generate_execution_id("NIFTY", "BUY", 23500.0, 50)
        cert_id1 = certifier.begin(exec_id, "NIFTY", "BUY", {"qty": 50})
        cert_id2 = certifier.begin(exec_id, "NIFTY", "BUY", {"qty": 50})
        # Returns a cert_id (may differ due to timestamp), but execution_id is already known
        assert certifier.is_duplicate(exec_id) is True

    def test_commit(self, certifier):
        exec_id = certifier.generate_execution_id("NIFTY", "BUY", 23500.0, 50)
        cert_id = certifier.begin(exec_id, "NIFTY", "BUY", {"qty": 50})
        certifier.commit(cert_id, "BROKER_ORD_001")
        cert = certifier.get_by_execution_id(exec_id)
        assert cert.status == CertStatus.COMMITTED
        assert cert.broker_order_id == "BROKER_ORD_001"

    def test_settle(self, certifier):
        exec_id = certifier.generate_execution_id("NIFTY", "BUY", 23500.0, 50)
        cert_id = certifier.begin(exec_id, "NIFTY", "BUY", {"qty": 50})
        certifier.commit(cert_id, "BROKER_ORD_002")
        certifier.settle(cert_id)
        cert = certifier.get_by_execution_id(exec_id)
        assert cert.status == CertStatus.SETTLED

    def test_fail(self, certifier):
        exec_id = certifier.generate_execution_id("NIFTY", "BUY", 23500.0, 50)
        cert_id = certifier.begin(exec_id, "NIFTY", "BUY", {"qty": 50})
        certifier.fail(cert_id, "Insufficient margin")
        cert = certifier.get_by_execution_id(exec_id)
        assert cert.status == CertStatus.FAILED
        assert cert.error == "Insufficient margin"

    def test_is_pending_false_for_committed(self, certifier):
        exec_id = certifier.generate_execution_id("NIFTY", "BUY", 23500.0, 50)
        cert_id = certifier.begin(exec_id, "NIFTY", "BUY", {"qty": 50})
        certifier.commit(cert_id, "BROKER_ORD_003")
        assert certifier.is_pending(exec_id) is False

    def test_is_duplicate_unknown(self, certifier):
        assert certifier.is_duplicate("exec_unknown") is False

    def test_get_pending(self, certifier):
        exec_id = certifier.generate_execution_id("NIFTY", "BUY", 23500.0, 50)
        certifier.begin(exec_id, "NIFTY", "BUY", {"qty": 50})
        pending = certifier.get_pending()
        assert len(pending) == 1
        assert pending[0].status == CertStatus.PENDING
        assert pending[0].symbol == "NIFTY"

    def test_get_pending_empty_after_commit(self, certifier):
        exec_id = certifier.generate_execution_id("NIFTY", "BUY", 23500.0, 50)
        cert_id = certifier.begin(exec_id, "NIFTY", "BUY", {"qty": 50})
        certifier.commit(cert_id, "BROKER_ORD_004")
        pending = certifier.get_pending()
        assert len(pending) == 0

    def test_get_by_execution_id_unknown(self, certifier):
        cert = certifier.get_by_execution_id("exec_unknown")
        assert cert is None

    def test_count_by_status_empty(self, certifier):
        counts = certifier.count_by_status()
        assert counts == {}

    def test_count_by_status_with_certs(self, certifier):
        e1 = certifier.generate_execution_id("NIFTY", "BUY", 23500.0, 50)
        c1 = certifier.begin(e1, "NIFTY", "BUY", {"qty": 50})
        certifier.commit(c1, "BROKER_ORD_005")
        certifier.settle(c1)
        e2 = certifier.generate_execution_id("BANKNIFTY", "SELL", 50000.0, 30)
        c2 = certifier.begin(e2, "BANKNIFTY", "SELL", {"qty": 30})
        counts = certifier.count_by_status()
        assert counts.get(CertStatus.SETTLED) == 1
        assert counts.get(CertStatus.PENDING) == 1

    def test_health_check(self, certifier):
        health = certifier.health_check()
        assert "db_path" in health
        assert "by_status" in health

    def test_full_lifecycle(self, certifier):
        exec_id = certifier.generate_execution_id("NIFTY", "BUY", 23500.0, 50)
        cert_id = certifier.begin(exec_id, "NIFTY", "BUY", {"qty": 50, "price": 23500.0})
        assert certifier.is_pending(exec_id) is True
        certifier.commit(cert_id, "BROKER_ORD_006")
        assert certifier.is_duplicate(exec_id) is True
        assert certifier.is_pending(exec_id) is False
        certifier.settle(cert_id)
        cert = certifier.get_by_execution_id(exec_id)
        assert cert.status == CertStatus.SETTLED
        assert cert.broker_order_id == "BROKER_ORD_006"

    def test_close(self, certifier):
        certifier.close()
        # After close, connection should be None
        assert certifier._conn is None

    def test_begin_duplicate_execution_id(self, certifier):
        """begin with the same execution_id should log a warning but not fail."""
        exec_id = "exec_duplicate_test"
        cert_id1 = certifier.begin(exec_id, "NIFTY", "BUY", {"qty": 50})
        cert_id2 = certifier.begin(exec_id, "NIFTY", "BUY", {"qty": 50})
        # Both calls return a cert_id
        assert cert_id1
        assert cert_id2
