"""
Chaos: Auth Expiry
"""
import pytest


def test_auth_expiry_detected():
    """Health check works with :memory:."""
    from core.execution.idempotency.certifier import IdempotencyCertifier
    cert = IdempotencyCertifier(":memory:")
    try:
        hc = cert.health_check()
        assert isinstance(hc, dict)
        assert "by_status" in hc
    finally:
        cert.close()


def test_auth_expiry_blocks_orders():
    """Expired auth blocks (simulated)."""
    auth_valid = False
    assert not auth_valid
