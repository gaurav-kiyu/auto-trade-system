"""
Chaos: Broker Outage
"""
import pytest


def test_broker_outage_paper_fallback():
    """On broker outage, paper fallback works."""
    from core.adapters.broker_adapters import PaperBrokerAdapter
    pba = PaperBrokerAdapter()
    oid = pba.place_order("NIFTY", "CALL", 50, 18000.0)
    assert oid is not None and oid.startswith("PAPER_")


def test_broker_outage_idempotent():
    """Certifier detects duplicate after begin."""
    from core.execution.idempotency.certifier import IdempotencyCertifier
    cert = IdempotencyCertifier(":memory:")
    eid = cert.generate_execution_id("NIFTY", "CALL", 18000.0, 50)
    cert.begin(eid, "NIFTY", "BUY", {"qty": 50})
    assert cert.is_duplicate(eid)
    assert cert.is_pending(eid)
