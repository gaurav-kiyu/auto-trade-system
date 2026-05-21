"""
Chaos: Partial Fill + Disconnect
"""
import pytest
import tempfile, os, gc


def test_partial_fill_after_disconnect():
    """Fill after disconnect: PENDING → SETTLED."""
    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    db = f.name
    f.close()
    try:
        from core.execution.idempotency.certifier import IdempotencyCertifier
        cert = IdempotencyCertifier(db)
        eid = cert.generate_execution_id("NIFTY", "CALL", 18000.0, 50)
        cid = cert.begin(eid, "NIFTY", "BUY", {"qty": 50})
        assert cert.is_pending(eid)
        cert.settle(cid)
        assert not cert.is_pending(eid)
    finally:
        del cert
        gc.collect()
        try:
            os.unlink(db)
        except PermissionError:
            pass


def test_no_position_double_count():
    """Settled cert not pending."""
    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    db = f.name
    f.close()
    try:
        from core.execution.idempotency.certifier import IdempotencyCertifier
        cert = IdempotencyCertifier(db)
        eid = cert.generate_execution_id("NIFTY", "CALL", 18000.0, 50)
        cid = cert.begin(eid, "NIFTY", "BUY", {"qty": 50})
        cert.settle(cid)
        assert not cert.is_pending(eid)
        assert cert.get_by_execution_id(eid).status == "SETTLED"
    finally:
        del cert
        gc.collect()
        try:
            os.unlink(db)
        except PermissionError:
            pass
