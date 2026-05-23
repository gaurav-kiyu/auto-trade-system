"""
Chaos: Restart Mid-Session
"""
import pytest
import tempfile, os, gc
from core.execution.idempotency.certifier import IdempotencyCertifier
from core.wal.journal import WriteAheadJournal, Intent


def test_idempotency_survives_restart():
    """Certifier state persists via SQLite file."""
    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    db = f.name
    f.close()
    try:
        cert1 = IdempotencyCertifier(db)
        eid = cert1.generate_execution_id("NIFTY", "CALL", 18000.0, 50)
        cid = cert1.begin(eid, "NIFTY", "BUY", {"qty": 50})
        cert1.settle(cid)
        assert cert1.get_by_execution_id(eid).status == "SETTLED"
        del cert1
        gc.collect()

        cert2 = IdempotencyCertifier(db)
        assert cert2.get_by_execution_id(eid).status == "SETTLED"
    finally:
        try:
            os.unlink(db)
        except PermissionError:
            pass


def test_no_duplicate_orders_after_restart():
    """SETTLED prevents re-execution after restart."""
    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    db = f.name
    f.close()
    try:
        cert = IdempotencyCertifier(db)
        eid = cert.generate_execution_id("NIFTY", "CALL", 18000.0, 50)
        cid = cert.begin(eid, "NIFTY", "BUY", {"qty": 50})
        cert.settle(cid)
        del cert
        gc.collect()

        cert2 = IdempotencyCertifier(db)
        assert not cert2.is_pending(eid)
        assert cert2.get_by_execution_id(eid).status == "SETTLED"
    finally:
        try:
            os.unlink(db)
        except PermissionError:
            pass


def test_wal_persistence():
    """WriteAheadJournal persists via SQLite file."""
    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    db = f.name
    f.close()
    try:
        wal1 = WriteAheadJournal(db)
        intent = Intent(
            intent_id="",
            action="BUY",
            params={"sym": "NIFTY", "qty": 50},
            risk_verdict=None,
            config_snapshot_hash="abc",
            correlation_id="test",
            status="PENDING",
            created_at="",
        )
        wal1.append(intent)
        # find our PENDING intent
        pending = wal1.get_pending()
        matching = [i for i in pending if i.action == "BUY"]
        assert len(matching) >= 1
        iid = matching[-1].intent_id
        wal1.commit(iid)
        del wal1
        gc.collect()

        wal2 = WriteAheadJournal(db)
        settled = wal2.get_intent(iid)
        assert settled is not None
        assert settled.status == "COMMITTED"
    finally:
        try:
            os.unlink(db)
        except PermissionError:
            pass
