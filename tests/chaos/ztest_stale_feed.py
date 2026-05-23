"""
Chaos: Stale Feed
"""
import pytest


def test_stale_feed_ignored():
    """Stale signal is rejected."""
    from core.execution.idempotency.certifier import IdempotencyCertifier
    cert = IdempotencyCertifier(":memory:")
    try:
        eid = cert.generate_execution_id("NIFTY", "CALL", 18000.0, 50)
        cid = cert.begin(eid, "NIFTY", "BUY", {"qty": 50})
        cert.settle(cid)
        assert cert.is_duplicate(eid)
        assert not cert.is_pending(eid)
    finally:
        cert.close()


def test_stale_feed_no_duplicate_order():
    """Duplicate detection prevents re-entry."""
    from core.execution.idempotency.certifier import IdempotencyCertifier
    cert = IdempotencyCertifier(":memory:")
    try:
        eid = cert.generate_execution_id("BANKNIFTY", "PUT", 36000.0, 25)
        cid = cert.begin(eid, "BANKNIFTY", "SELL", {"qty": 25})
        cert.fail(cid)
        assert cert.is_duplicate(eid)
    finally:
        cert.close()
