"""
Chaos: Restart Mid-Session
"""
import pytest
import tempfile, os, gc
from core.execution.idempotency.certifier import IdempotencyCertifier


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
        del cert2
        gc.collect()
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
        del cert2
        gc.collect()
        try:
            os.unlink(db)
        except PermissionError:
            pass


def test_wal_persistence_via_sqlite():
    """SQLite persistence works across sessions."""
    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    db = f.name
    f.close()
    try:
        import sqlite3
        conn = sqlite3.connect(db)
        conn.execute("CREATE TABLE IF NOT EXISTS wal (k TEXT PRIMARY KEY, v TEXT)")
        conn.execute("INSERT INTO wal VALUES ('test', 'value')")
        conn.commit()
        conn.close()

        conn2 = sqlite3.connect(db)
        row = conn2.execute("SELECT v FROM wal WHERE k='test'").fetchone()
        assert row[0] == "value"
        conn2.close()
    finally:
        os.unlink(db)
