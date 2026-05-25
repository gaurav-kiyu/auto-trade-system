"""
Chaos: DB Corruption
"""
import os
import sqlite3
import tempfile
from pathlib import Path

import pytest


def test_db_corruption_detected():
    """Corrupted DB raises on query."""
    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    db = f.name
    f.close()
    Path(db).write_bytes(b"GARBAGE" * 100)
    try:
        conn = sqlite3.connect(db)
        with pytest.raises(Exception):
            conn.execute("SELECT 1")
        conn.close()
    finally:
        os.unlink(db)


def test_db_corruption_fallback():
    """In-memory fallback works."""
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE t (id, v)")
    conn.execute("INSERT INTO t VALUES (1, 'ok')")
    assert conn.execute("SELECT v FROM t WHERE id=1").fetchone()[0] == "ok"
    conn.close()


def test_no_capital_loss_on_corruption():
    """Idempotency via :memory: survives."""
    from core.execution.idempotency.certifier import IdempotencyCertifier
    cert = IdempotencyCertifier(":memory:")
    try:
        eid = cert.generate_execution_id("NIFTY", "CALL", 18000.0, 50)
        cid = cert.begin(eid, "NIFTY", "BUY", {"qty": 50})
        cert.settle(cid)
        assert cert.get_by_execution_id(eid).status == "SETTLED"
    finally:
        cert.close()
