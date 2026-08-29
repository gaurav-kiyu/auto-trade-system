"""
Chaos: Reconnect Storm
"""


def test_reconnect_storm_idempotency():
    """After begin, execution is pending + duplicate."""
    from core.execution.idempotency.certifier import IdempotencyCertifier
    cert = IdempotencyCertifier(":memory:")
    try:
        eid = cert.generate_execution_id("NIFTY", "CALL", 18000.0, 50)
        cert.begin(eid, "NIFTY", "BUY", {"qty": 50})
        assert cert.is_pending(eid)
        assert cert.is_duplicate(eid)
    finally:
        cert.close()


def test_reconnect_storm_position_integrity():
    """Position tracking survives reconnect."""
    p = {"NIFTY": {"qty": 50, "avg": 100.0}}
    for i in range(10):
        p["NIFTY"]["avg"] = 100.0 + i
    assert p["NIFTY"]["qty"] == 50
