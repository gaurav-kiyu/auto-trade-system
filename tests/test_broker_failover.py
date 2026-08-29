"""Tests for core/broker_failover.py (v2.45 Item 20)."""
import time

from core.broker_failover import BrokerFailoverManager


def _mgr(**kw):
    base = {
        "broker_failover_enabled": True,
        "failover_threshold": 3,
        "failover_chain": ["kite", "angel"],
        "failover_recovery_mins": 15,
    }
    base.update(kw)
    return BrokerFailoverManager(base)


# ── basic state ───────────────────────────────────────────────────────────────

def test_initial_active_broker_is_primary():
    mgr = _mgr()
    assert mgr.get_active_broker() == "kite"


def test_record_success_no_failover():
    mgr = _mgr()
    mgr.record_success("kite")
    assert mgr.get_active_broker() == "kite"


def test_record_failure_below_threshold_no_switch():
    mgr = _mgr()
    triggered = mgr.record_failure("kite")
    assert triggered is False
    assert mgr.get_active_broker() == "kite"


# ── failover trigger ──────────────────────────────────────────────────────────

def test_failover_after_threshold():
    mgr = _mgr(failover_threshold=3)
    for _ in range(2):
        assert mgr.record_failure("kite") is False
    assert mgr.record_failure("kite") is True


def test_active_broker_changes_after_failover():
    mgr = _mgr(failover_threshold=2)
    mgr.record_failure("kite")
    mgr.record_failure("kite")
    assert mgr.get_active_broker() == "angel"


def test_failure_on_non_active_broker_no_switch():
    mgr = _mgr(failover_threshold=2)
    # angel is not active - failures should not trigger switch
    for _ in range(5):
        mgr.record_failure("angel")
    assert mgr.get_active_broker() == "kite"


# ── disabled mode ─────────────────────────────────────────────────────────────

def test_disabled_record_failure_returns_false():
    mgr = BrokerFailoverManager({"broker_failover_enabled": False})
    for _ in range(10):
        assert mgr.record_failure("kite") is False


def test_disabled_active_broker_unchanged():
    mgr = BrokerFailoverManager({"broker_failover_enabled": False,
                                  "failover_chain": ["kite", "angel"]})
    for _ in range(10):
        mgr.record_failure("kite")
    assert mgr.get_active_broker() == "kite"


# ── reset ──────────────────────────────────────────────────────────────────────

def test_reset_restores_primary():
    mgr = _mgr(failover_threshold=2)
    mgr.record_failure("kite")
    mgr.record_failure("kite")
    assert mgr.get_active_broker() == "angel"
    mgr.reset()
    assert mgr.get_active_broker() == "kite"


def test_reset_clears_failure_counts():
    mgr = _mgr(failover_threshold=5)
    for _ in range(3):
        mgr.record_failure("kite")
    mgr.reset()
    # After reset, 3 more failures should not trigger (count was cleared)
    for _ in range(2):
        assert mgr.record_failure("kite") is False


# ── status dict ───────────────────────────────────────────────────────────────

def test_status_returns_dict():
    mgr = _mgr()
    s = mgr.status()
    assert isinstance(s, dict)
    assert "active_broker" in s
    assert "enabled" in s


def test_status_active_is_kite_initially():
    mgr = _mgr()
    assert mgr.status()["active_broker"] == "kite"


# ── recovery ──────────────────────────────────────────────────────────────────

def test_no_recovery_when_on_primary():
    mgr = _mgr()
    assert mgr.maybe_recover() is False


def test_recovery_when_elapsed(monkeypatch):
    mgr = _mgr(failover_threshold=1, failover_recovery_mins=0.001)
    mgr.record_failure("kite")
    assert mgr.get_active_broker() == "angel"
    time.sleep(0.1)
    recovered = mgr.maybe_recover()
    assert recovered is True
    assert mgr.get_active_broker() == "kite"
