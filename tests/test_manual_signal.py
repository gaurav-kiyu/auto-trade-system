"""Tests for core/manual_signal.py (v2.46 Sprint 1A)."""
import threading
import time

import pytest
from core.manual_signal import (
    APPROVED,
    CANCELLED,
    EXECUTED,
    EXPIRED,
    PENDING,
    REJECTED,
    ManualSignal,
    ManualSignalQueue,
    _make_signal_id,
    build_signal_queue,
)

# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture
def queue(tmp_path):
    cfg = {"manual_signal_db_path": str(tmp_path / "test_signals.db"),
           "manual_signal_timeout_mins": 30,
           "manual_signal_auto_approve_secs": 0,
           "manual_signal_default_analyst": "TestBot"}
    q = ManualSignalQueue(cfg)
    yield q
    q.close()


# ── ID generation ──────────────────────────────────────────────────────────────

def test_make_signal_id_format():
    sid = _make_signal_id()
    assert sid.startswith("MSQ_")
    parts = sid.split("_")
    assert len(parts) == 3
    assert parts[1].isdigit()
    assert parts[2].isdigit()


def test_make_signal_id_unique():
    ids = {_make_signal_id() for _ in range(50)}
    assert len(ids) == 50


# ── ManualSignal dataclass ─────────────────────────────────────────────────────

def test_manual_signal_to_dict_roundtrip():
    sig = ManualSignal(
        signal_id="MSQ_1_0001", source="TELEGRAM", analyst_name="Bob",
        index_name="NIFTY", direction="CALL", score=80, reason="test",
        submitted_at="2026-01-01T09:30:00",
    )
    d = sig.to_dict()
    sig2 = ManualSignal.from_dict(d)
    assert sig2.signal_id == sig.signal_id
    assert sig2.score == 80
    assert sig2.status == PENDING


def test_manual_signal_is_pending():
    sig = ManualSignal(
        signal_id="MSQ_2_0001", source="CSV", analyst_name="X",
        index_name="BANKNIFTY", direction="PUT", score=70, reason="",
        submitted_at="2026-01-01T09:30:00",
    )
    assert sig.is_pending
    sig.status = APPROVED
    assert not sig.is_pending
    assert sig.is_actionable


def test_manual_signal_is_actionable():
    sig = ManualSignal(
        signal_id="MSQ_3_0001", source="TEXT", analyst_name="X",
        index_name="NIFTY", direction="CALL", score=60, reason="",
        submitted_at="2026-01-01T09:30:00",
    )
    for s in (PENDING, APPROVED):
        sig.status = s
        assert sig.is_actionable
    for s in (REJECTED, EXECUTED, EXPIRED, CANCELLED):
        sig.status = s
        assert not sig.is_actionable


# ── Submit ─────────────────────────────────────────────────────────────────────

def test_submit_returns_signal(queue):
    sig = queue.submit("NIFTY", "CALL", 80, "test reason")
    assert sig.signal_id.startswith("MSQ_")
    assert sig.index_name == "NIFTY"
    assert sig.direction == "CALL"
    assert sig.score == 80
    assert sig.status == PENDING


def test_submit_score_clamped(queue):
    sig = queue.submit("NIFTY", "CALL", 150)
    assert sig.score == 100
    sig2 = queue.submit("NIFTY", "PUT", -50)
    assert sig2.score == 0


def test_submit_uppercase_normalisation(queue):
    sig = queue.submit("nifty", "call", 75)
    assert sig.index_name == "NIFTY"
    assert sig.direction == "CALL"


def test_submit_with_overrides(queue):
    sig = queue.submit(
        "BANKNIFTY", "PUT", 82, "gap fill",
        source="CSV", analyst_name="Alice",
        expiry="2026-02-27", lots_override=3,
        sl_override=45.5, target_override=90.0,
    )
    assert sig.lots_override == 3
    assert sig.sl_override == 45.5
    assert sig.target_override == 90.0
    assert sig.expiry == "2026-02-27"
    assert sig.source == "CSV"
    assert sig.analyst_name == "Alice"


def test_submit_persisted(queue):
    sig = queue.submit("NIFTY", "CALL", 75)
    fetched = queue.get_by_id(sig.signal_id)
    assert fetched is not None
    assert fetched.signal_id == sig.signal_id


# ── Approve / Reject ───────────────────────────────────────────────────────────

def test_approve_pending(queue):
    sig = queue.submit("NIFTY", "CALL", 80)
    result = queue.approve(sig.signal_id, reviewer="Admin")
    assert result is True
    fetched = queue.get_by_id(sig.signal_id)
    assert fetched.status == APPROVED
    assert fetched.reviewed_by == "Admin"


def test_approve_already_approved(queue):
    sig = queue.submit("NIFTY", "CALL", 80)
    queue.approve(sig.signal_id)
    result = queue.approve(sig.signal_id)
    assert result is False


def test_approve_with_overrides(queue):
    sig = queue.submit("NIFTY", "CALL", 80)
    queue.approve(sig.signal_id, reviewer="Admin", lots_override=5, sl_override=30.0)
    fetched = queue.get_by_id(sig.signal_id)
    assert fetched.lots_override == 5
    assert fetched.sl_override == 30.0


def test_reject_pending(queue):
    sig = queue.submit("NIFTY", "PUT", 70)
    result = queue.reject(sig.signal_id, reviewer="Admin", reason="Bad timing")
    assert result is True
    fetched = queue.get_by_id(sig.signal_id)
    assert fetched.status == REJECTED
    assert fetched.reject_reason == "Bad timing"


def test_reject_non_pending(queue):
    sig = queue.submit("NIFTY", "PUT", 70)
    queue.approve(sig.signal_id)
    result = queue.reject(sig.signal_id)
    assert result is False


def test_approve_nonexistent(queue):
    assert queue.approve("MSQ_0_9999") is False


# ── Mark executed / cancel ─────────────────────────────────────────────────────

def test_mark_executed(queue):
    sig = queue.submit("NIFTY", "CALL", 85)
    queue.mark_executed(sig.signal_id, trade_id="T123")
    fetched = queue.get_by_id(sig.signal_id)
    assert fetched.status == EXECUTED
    assert fetched.execution_trade_id == "T123"


def test_cancel(queue):
    sig = queue.submit("NIFTY", "CALL", 75)
    result = queue.cancel(sig.signal_id, reason="Changed mind")
    assert result is True
    fetched = queue.get_by_id(sig.signal_id)
    assert fetched.status == CANCELLED


def test_cancel_executed_returns_false(queue):
    sig = queue.submit("NIFTY", "CALL", 85)
    queue.mark_executed(sig.signal_id, "T999")
    assert queue.cancel(sig.signal_id) is False


# ── Query methods ──────────────────────────────────────────────────────────────

def test_get_pending(queue):
    s1 = queue.submit("NIFTY", "CALL", 80)
    s2 = queue.submit("BANKNIFTY", "PUT", 70)
    queue.approve(s1.signal_id)
    pending = queue.get_pending()
    ids = {s.signal_id for s in pending}
    assert s2.signal_id in ids
    assert s1.signal_id not in ids


def test_get_approved(queue):
    s1 = queue.submit("NIFTY", "CALL", 80)
    queue.approve(s1.signal_id)
    approved = queue.get_approved()
    assert any(s.signal_id == s1.signal_id for s in approved)


def test_get_recent_limit(queue):
    for i in range(5):
        queue.submit("NIFTY", "CALL", 70 + i)
    recent = queue.get_recent(limit=3)
    assert len(recent) == 3


def test_get_by_id_missing(queue):
    assert queue.get_by_id("MSQ_NONEXISTENT") is None


# ── Expiry ─────────────────────────────────────────────────────────────────────

def test_expire_old(tmp_path):
    cfg = {"manual_signal_db_path": str(tmp_path / "exp.db"),
           "manual_signal_timeout_mins": 0}  # expire immediately
    q = ManualSignalQueue(cfg)
    sig = q.submit("NIFTY", "CALL", 80)
    time.sleep(0.05)
    count = q.expire_old()
    assert count >= 1
    fetched = q.get_by_id(sig.signal_id)
    assert fetched.status == EXPIRED
    q.close()


# ── Auto-approve ───────────────────────────────────────────────────────────────

def test_maybe_auto_approve(tmp_path):
    cfg = {"manual_signal_db_path": str(tmp_path / "aa.db"),
           "manual_signal_auto_approve_secs": 1}
    q = ManualSignalQueue(cfg)
    sig = q.submit("NIFTY", "CALL", 80, auto_approve_secs=1)
    time.sleep(1.2)
    approved = q.maybe_auto_approve()
    assert any(s.signal_id == sig.signal_id for s in approved)
    fetched = q.get_by_id(sig.signal_id)
    assert fetched.status == APPROVED
    q.close()


def test_maybe_auto_approve_disabled(queue):
    queue.submit("NIFTY", "CALL", 80)
    approved = queue.maybe_auto_approve()
    assert approved == []


# ── Stats ──────────────────────────────────────────────────────────────────────

def test_get_stats(queue):
    queue.submit("NIFTY", "CALL", 80)
    queue.submit("BANKNIFTY", "PUT", 70)
    stats = queue.get_stats()
    assert stats["total"] >= 2
    assert "by_status" in stats
    assert "by_index" in stats
    assert "by_analyst" in stats


# ── Thread safety ──────────────────────────────────────────────────────────────

def test_concurrent_submits(queue):
    errors = []
    def submit_many():
        try:
            for _ in range(10):
                queue.submit("NIFTY", "CALL", 75)
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=submit_many) for _ in range(5)]
    for t in threads: t.start()
    for t in threads: t.join()
    assert errors == []
    assert queue.get_stats()["total"] == 50


# ── Factory ────────────────────────────────────────────────────────────────────

def test_build_signal_queue_enabled(tmp_path):
    q = build_signal_queue({"manual_signal_enabled": True,
                             "manual_signal_db_path": str(tmp_path / "f.db")})
    assert q is not None
    q.close()


def test_build_signal_queue_disabled():
    q = build_signal_queue({"manual_signal_enabled": False})
    assert q is None
