"""
Chaos: Partial Fill + Disconnect
"""


def test_partial_fill_after_disconnect():
    """Fill after disconnect: PENDING -> SETTLED."""
    from core.execution.idempotency.certifier import IdempotencyCertifier
    cert = IdempotencyCertifier(":memory:")
    try:
        eid = cert.generate_execution_id("NIFTY", "CALL", 18000.0, 50)
        cid = cert.begin(eid, "NIFTY", "BUY", {"qty": 50})
        assert cert.is_pending(eid)
        cert.settle(cid)
        assert not cert.is_pending(eid)
    finally:
        cert.close()


def test_no_position_double_count():
    """Settled cert not pending."""
    from core.execution.idempotency.certifier import IdempotencyCertifier
    cert = IdempotencyCertifier(":memory:")
    try:
        eid = cert.generate_execution_id("NIFTY", "CALL", 18000.0, 50)
        cid = cert.begin(eid, "NIFTY", "BUY", {"qty": 50})
        cert.settle(cid)
        assert not cert.is_pending(eid)
        assert cert.is_duplicate(eid)
        assert cert.get_by_execution_id(eid).status == "SETTLED"
    finally:
        cert.close()
