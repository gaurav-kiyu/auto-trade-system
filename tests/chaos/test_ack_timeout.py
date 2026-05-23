"""
Chaos: ACK Timeout
"""
import pytest


def test_ack_timeout_detected():
    """Timeout: PENDING -> FAILED."""
    from core.execution.idempotency.certifier import IdempotencyCertifier
    cert = IdempotencyCertifier(":memory:")
    eid = cert.generate_execution_id("NIFTY", "CALL", 18000.0, 50)
    cid = cert.begin(eid, "NIFTY", "BUY", {"qty": 50})
    assert cert.get_by_execution_id(eid).status == "PENDING"
    cert.fail(cid, error="TIMEOUT")
    assert not cert.is_pending(eid)


def test_ack_timeout_no_double_submit():
    """Failed cert is not pending."""
    from core.execution.idempotency.certifier import IdempotencyCertifier
    cert = IdempotencyCertifier(":memory:")
    eid = cert.generate_execution_id("NIFTY", "CALL", 18000.0, 50)
    cid = cert.begin(eid, "NIFTY", "BUY", {"qty": 50})
    cert.fail(cid, error="TIMEOUT")
    assert not cert.is_pending(eid)
    assert cert.is_duplicate(eid)
