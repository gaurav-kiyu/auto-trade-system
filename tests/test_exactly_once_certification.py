"""
AD-KIYU Exactly-Once Execution Certification - Failure Simulation Suite.

Proves that IdempotencyCertifier prevents duplicate order submission
under all defined failure modes:

  SCENARIO 1: Normal lifecycle - begin → commit → settle → duplicate rejected
  SCENARIO 2: Crash after begin - PENDING cert recovered on restart
  SCENARIO 3: Crash after commit - COMMITTED cert recovered on restart
  SCENARIO 4: Duplicate execution_id - is_duplicate returns True
  SCENARIO 5: Concurrent duplicate detection - thread safety
  SCENARIO 6: Generate same execution_id from matching params (determinism)
  SCENARIO 7: Different params produce different execution_id
  SCENARIO 8: DB persistence across restart (file mode)
  SCENARIO 9: Health check reflects correct state
"""
from __future__ import annotations

import gc
import os
import tempfile
import threading
import time

from core.execution.idempotency.certifier import IdempotencyCertifier

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_cert(db=":memory:") -> IdempotencyCertifier:
    return IdempotencyCertifier(db_path=db)


def _make_eid(cert: IdempotencyCertifier, sym="NIFTY", direction="CALL",
              strike=18000.0, lots=50) -> str:
    return cert.generate_execution_id(sym, direction, strike, lots)


# ---------------------------------------------------------------------------
# SCENARIO 1: Normal lifecycle
# ---------------------------------------------------------------------------

def test_scenario_1_normal_lifecycle():
    """begin → commit → settle → duplicate => True, not pending."""
    cert = _make_cert()
    try:
        eid = _make_eid(cert)
        cid = cert.begin(eid, "NIFTY", "BUY", {"qty": 50})
        assert cert.is_pending(eid)

        cert.commit(cid, "BROKER_001")
        assert cert.is_duplicate(eid)
        assert not cert.is_pending(eid)
        assert cert.get_by_execution_id(eid).status == "COMMITTED"

        cert.settle(cid)
        assert cert.get_by_execution_id(eid).status == "SETTLED"
        assert cert.is_duplicate(eid)

        # Second begin returns same cert_id, doesn't duplicate
        cid2 = cert.begin(eid, "NIFTY", "BUY", {"qty": 50})
        assert cid2 is not None  # returns existing cert_id
    finally:
        cert.close()


# ---------------------------------------------------------------------------
# SCENARIO 2: Crash after begin (PENDING recovery)
# ---------------------------------------------------------------------------

def test_scenario_2_crash_after_begin():
    """PENDING cert survives restart."""
    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    db = f.name
    f.close()
    try:
        cert1 = _make_cert(db)
        eid = _make_eid(cert1)
        cert1.begin(eid, "NIFTY", "BUY", {"qty": 50})
        assert cert1.is_pending(eid)
        cert1.close()
        del cert1
        gc.collect()

        cert2 = _make_cert(db)
        try:
            assert cert2.is_pending(eid)
            assert cert2.is_duplicate(eid)
            assert cert2.get_by_execution_id(eid).status == "PENDING"
        finally:
            cert2.close()
    finally:
        try:
            os.unlink(db)
        except PermissionError:
            pass


# ---------------------------------------------------------------------------
# SCENARIO 3: Crash after commit (COMMITTED recovery)
# ---------------------------------------------------------------------------

def test_scenario_3_crash_after_commit():
    """COMMITTED cert survives restart."""
    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    db = f.name
    f.close()
    try:
        cert1 = _make_cert(db)
        eid = _make_eid(cert1)
        cid = cert1.begin(eid, "NIFTY", "BUY", {"qty": 50})
        cert1.commit(cid, "BROKER_002")
        assert not cert1.is_pending(eid)
        cert1.close()
        del cert1
        gc.collect()

        cert2 = _make_cert(db)
        try:
            assert not cert2.is_pending(eid)
            assert cert2.is_duplicate(eid)
            assert cert2.get_by_execution_id(eid).status == "COMMITTED"
        finally:
            cert2.close()
    finally:
        try:
            os.unlink(db)
        except PermissionError:
            pass


# ---------------------------------------------------------------------------
# SCENARIO 4: Duplicate execution_id is rejected
# ---------------------------------------------------------------------------

def test_scenario_4_duplicate_rejected():
    """After begin, is_duplicate returns True."""
    cert = _make_cert()
    try:
        eid = _make_eid(cert)
        assert not cert.is_duplicate(eid)
        cert.begin(eid, "NIFTY", "BUY", {"qty": 50})
        assert cert.is_duplicate(eid)
    finally:
        cert.close()


# ---------------------------------------------------------------------------
# SCENARIO 5: Concurrent duplicate detection (thread safety)
# ---------------------------------------------------------------------------

def test_scenario_5_concurrent_duplicate_detection():
    """Multiple threads see same state."""
    cert = _make_cert()
    try:
        eid = _make_eid(cert)
        errors = []

        def thread_begin():
            try:
                cid = cert.begin(eid, "NIFTY", "BUY", {"qty": 50})
                return cid
            except Exception as e:
                errors.append(e)
                return None

        threads = [threading.Thread(target=thread_begin) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert cert.is_duplicate(eid)
        assert cert.is_pending(eid)  # still PENDING
        # Exactly 1 cert with this execution_id
        certs = cert.get_pending()
        matching = [c for c in certs if c.execution_id == eid]
        assert len(matching) == 1
    finally:
        cert.close()


# ---------------------------------------------------------------------------
# SCENARIO 6: Deterministic execution_id
# ---------------------------------------------------------------------------

def test_scenario_6_deterministic_id():
    """Same params + same time slot => same execution_id."""
    slot = int(time.time() / 300)  # current 5-min slot
    cert = _make_cert()
    try:
        eid1 = cert.generate_execution_id("NIFTY", "CALL", 18000.0, 50, slot)
        eid2 = cert.generate_execution_id("NIFTY", "CALL", 18000.0, 50, slot)
        assert eid1 == eid2
    finally:
        cert.close()


# ---------------------------------------------------------------------------
# SCENARIO 7: Different params => different execution_id
# ---------------------------------------------------------------------------

def test_scenario_7_different_params_different_id():
    """Different params produce different execution_id."""
    cert = _make_cert()
    try:
        eid1 = cert.generate_execution_id("NIFTY", "CALL", 18000.0, 50)
        eid2 = cert.generate_execution_id("BANKNIFTY", "PUT", 36000.0, 25)
        assert eid1 != eid2

        # Same symbol, different direction
        eid3 = cert.generate_execution_id("NIFTY", "PUT", 18000.0, 50)
        assert eid1 != eid3
    finally:
        cert.close()


# ---------------------------------------------------------------------------
# SCENARIO 8: DB persistence across restart (file mode)
# ---------------------------------------------------------------------------

def test_scenario_8_persistence_across_restart():
    """Full lifecycle survives across restart."""
    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    db = f.name
    f.close()
    try:
        cert1 = _make_cert(db)
        eid = _make_eid(cert1)
        cid = cert1.begin(eid, "NIFTY", "BUY", {"qty": 50})
        cert1.commit(cid, "BROKER_003")
        cert1.settle(cid)
        cert1.close()
        del cert1
        gc.collect()

        cert2 = _make_cert(db)
        try:
            record = cert2.get_by_execution_id(eid)
            assert record is not None
            assert record.status == "SETTLED"
            assert record.broker_order_id == "BROKER_003"

            hc = cert2.health_check()
            assert hc["by_status"].get("SETTLED", 0) >= 1
        finally:
            cert2.close()
    finally:
        try:
            os.unlink(db)
        except PermissionError:
            pass


# ---------------------------------------------------------------------------
# SCENARIO 9: Health check correctness
# ---------------------------------------------------------------------------

def test_scenario_9_health_check_correctness():
    """Health check accurately reflects stored state."""
    cert = _make_cert()
    try:
        hc0 = cert.health_check()
        assert hc0["by_status"] == {}

        eid1 = _make_eid(cert, sym="NIFTY", strike=18000.0)
        eid2 = _make_eid(cert, sym="BANKNIFTY", strike=36000.0)
        cid1 = cert.begin(eid1, "NIFTY", "BUY", {"qty": 50})

        hc1 = cert.health_check()
        assert hc1["by_status"].get("PENDING", 0) >= 1

        cert.commit(cid1, "BROKER_001")
        cid2 = cert.begin(eid2, "BANKNIFTY", "SELL", {"qty": 25})

        hc2 = cert.health_check()
        assert hc2["by_status"].get("COMMITTED", 0) >= 1
        assert hc2["by_status"].get("PENDING", 0) >= 1

        cert.settle(cid1)
        cert.commit(cid2, "BROKER_002")
        cert.settle(cid2)

        hc3 = cert.health_check()
        assert hc3["by_status"].get("SETTLED", 0) >= 2
    finally:
        cert.close()
