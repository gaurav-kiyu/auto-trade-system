"""
Chaos: ACK Timeout
"""
import pytest
import tempfile, os, gc


def test_ack_timeout_detected():
    """Timeout: PENDING → FAILED."""
    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    db = f.name
    f.close()
    try:
        from core.execution.idempotency.certifier import IdempotencyCertifier
        cert = IdempotencyCertifier(db)
        eid = cert.generate_execution_id("NIFTY", "CALL", 18000.0, 50)
        cid = cert.begin(eid, "NIFTY", "BUY", {"qty": 50})
        assert cert.get_by_execution_id(eid).status == "PENDING"
        cert.fail(cid, error="TIMEOUT")
        assert not cert.is_pending(eid)
    finally:
        del cert
        gc.collect()
        try:
            os.unlink(db)
        except PermissionError:
            pass


def test_ack_timeout_no_double_submit():
    """Failed cert is not pending."""
    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    db = f.name
    f.close()
    try:
        from core.execution.idempotency.certifier import IdempotencyCertifier
        cert = IdempotencyCertifier(db)
        eid = cert.generate_execution_id("NIFTY", "CALL", 18000.0, 50)
        cid = cert.begin(eid, "NIFTY", "BUY", {"qty": 50})
        cert.fail(cid, error="TIMEOUT")
        assert not cert.is_pending(eid)
    finally:
        del cert
        gc.collect()
        try:
            os.unlink(db)
        except PermissionError:
            pass
