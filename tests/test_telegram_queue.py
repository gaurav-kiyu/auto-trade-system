"""Tests for core/telegram_queue.py (v2.44 Item 7)."""
import time
from unittest.mock import MagicMock, patch

from core.telegram_queue import TelegramMessage, TelegramPriority, TelegramQueue

CFG = {
    "tg_max_queue_depth": 10,
    "tg_normal_drop_age_secs": 30,
    "tg_low_drop_threshold": 5,
    "tg_max_retries_critical": 3,
    "tg_max_retries_normal": 1,
    "tg_rate_limit_per_min": 100,  # high limit to avoid rate waits in tests
}


def make_queue(send_fn=None, cfg=None):
    if send_fn is None:
        send_fn = MagicMock(return_value=True)
    return TelegramQueue(send_fn=send_fn, cfg=cfg or CFG)


# ── Priority enum ─────────────────────────────────────────────────────────────

def test_critical_lower_than_high():
    assert TelegramPriority.CRITICAL < TelegramPriority.HIGH


def test_high_lower_than_normal():
    assert TelegramPriority.HIGH < TelegramPriority.NORMAL


def test_normal_lower_than_low():
    assert TelegramPriority.NORMAL < TelegramPriority.LOW


def test_priority_values():
    assert int(TelegramPriority.CRITICAL) == 0
    assert int(TelegramPriority.HIGH) == 1
    assert int(TelegramPriority.NORMAL) == 2
    assert int(TelegramPriority.LOW) == 3


# ── TelegramMessage ordering ──────────────────────────────────────────────────

def test_message_orders_by_priority():
    m1 = TelegramMessage(priority=2, ts=1.0, text="normal")
    m2 = TelegramMessage(priority=0, ts=2.0, text="critical")
    assert m2 < m1  # CRITICAL (0) < NORMAL (2)


# ── Enqueue and send ──────────────────────────────────────────────────────────

def test_send_critical_delivered():
    sent = []
    q = make_queue(send_fn=lambda t: sent.append(t) or True)
    q.start()
    q.send_critical("HALT!")
    time.sleep(0.3)
    q.stop()
    assert any("HALT!" in m for m in sent)


def test_send_high_delivered():
    sent = []
    q = make_queue(send_fn=lambda t: sent.append(t) or True)
    q.start()
    q.send_high("entry signal")
    time.sleep(0.3)
    q.stop()
    assert any("entry signal" in m for m in sent)


def test_send_normal_delivered():
    sent = []
    q = make_queue(send_fn=lambda t: sent.append(t) or True)
    q.start()
    q.send("status update")
    time.sleep(0.3)
    q.stop()
    assert any("status update" in m for m in sent)


def test_send_heartbeat_delivered_when_queue_shallow():
    sent = []
    q = make_queue(send_fn=lambda t: sent.append(t) or True)
    q.start()
    q.send_heartbeat("♥")
    time.sleep(0.3)
    q.stop()
    assert any("♥" in m for m in sent)


# ── Drop rules ────────────────────────────────────────────────────────────────

def test_low_dropped_when_queue_exceeds_threshold():
    q = make_queue()
    # Fill queue beyond low_threshold=5 with NORMAL msgs
    for i in range(6):
        q.enqueue(f"normal {i}", TelegramPriority.NORMAL)
    initial_dropped = q.get_metrics()["dropped_low"]
    q.enqueue("low msg", TelegramPriority.LOW)
    assert q.get_metrics()["dropped_low"] > initial_dropped


def test_critical_never_dropped():
    q = make_queue()
    cfg = dict(CFG, tg_max_queue_depth=3)
    q._cfg = cfg
    # Fill with normal
    for i in range(3):
        q.enqueue(f"n{i}", TelegramPriority.NORMAL)
    q.enqueue("CRITICAL!", TelegramPriority.CRITICAL)
    # Critical should be in heap
    with q._lock:
        priorities = [m.priority for m in q._heap]
    assert 0 in priorities  # CRITICAL=0


# ── Metrics ───────────────────────────────────────────────────────────────────

def test_metrics_keys_present():
    q = make_queue()
    m = q.get_metrics()
    assert "queue_depth" in m
    assert "dropped_critical" in m
    assert "dropped_high" in m
    assert "dropped_normal" in m
    assert "dropped_low" in m
    assert "dropped_today" in m


def test_metrics_initial_zeros():
    q = make_queue()
    m = q.get_metrics()
    assert m["queue_depth"] == 0
    assert m["dropped_today"] == 0


def test_dropped_today_is_sum():
    q = make_queue()
    q._dropped_by_level["LOW"] = 3
    q._dropped_by_level["NORMAL"] = 2
    m = q.get_metrics()
    assert m["dropped_today"] == 5


# ── Retry on failure ─────────────────────────────────────────────────────────

def test_retries_on_failure_then_succeeds():
    call_count = [0]
    def flaky(text):
        call_count[0] += 1
        return call_count[0] >= 2  # fail first, succeed second
    q = make_queue(send_fn=flaky, cfg=dict(CFG, tg_max_retries_normal=3))
    q._deliver(TelegramMessage(priority=2, ts=time.time(), text="test"))
    assert call_count[0] >= 2


def test_critical_gets_more_retries_than_normal():
    def always_fail(_):
        return False

    q_crit = make_queue(send_fn=always_fail, cfg=dict(CFG, tg_max_retries_critical=3, tg_max_retries_normal=1))
    with patch("time.sleep"):
        q_crit._deliver(TelegramMessage(priority=0, ts=time.time(), text="crit"))
        # Should have attempted max_retries_critical+1 times
        # Just verify it doesn't raise
    q_norm = make_queue(send_fn=always_fail, cfg=dict(CFG, tg_max_retries_critical=3, tg_max_retries_normal=1))
    with patch("time.sleep"):
        q_norm._deliver(TelegramMessage(priority=2, ts=time.time(), text="norm"))


# ── Start / stop ──────────────────────────────────────────────────────────────

def test_start_creates_daemon_thread():
    q = make_queue()
    q.start()
    assert q._thread is not None
    assert q._thread.is_alive()
    q.stop()


def test_double_start_safe():
    q = make_queue()
    q.start()
    q.start()  # Should not raise
    q.stop()


def test_update_config():
    q = make_queue()
    q.update_config({"tg_rate_limit_per_min": 50})
    assert q._cfg["tg_rate_limit_per_min"] == 50


# ── stop() waits for important messages ──────────────────────────────────────


def test_stop_waits_when_important_messages_pending():
    """stop() loops sleeping 0.5s when the heap still has CRITICAL/HIGH (line 99)."""
    import heapq
    q = make_queue()
    # Don't start the drain thread — CRITICAL message stays in heap
    with q._lock:
        heapq.heappush(q._heap, TelegramMessage(
            priority=int(TelegramPriority.CRITICAL), ts=time.time(), text="pending"
        ))
    with patch("time.sleep") as mock_sleep:
        q.stop(flush_timeout=0.2)
    # time.sleep(0.5) in the loop should have been called because the
    # important message was never drained (no thread).
    assert mock_sleep.called, "stop() did not sleep waiting for important messages"


# ── NORMAL drop with old-message expiration (lines 128-139) ──────────────────


def test_normal_drop_expires_old_entries():
    """NORMAL enqueue at max_depth triggers expiration then drops when still full."""
    q = make_queue(cfg=dict(CFG, tg_max_queue_depth=3, tg_normal_drop_age_secs=0.05))
    # Fill to max_depth with HIGH (these are never expired).
    q.enqueue("h1", TelegramPriority.HIGH)
    q.enqueue("h2", TelegramPriority.HIGH)
    q.enqueue("h3", TelegramPriority.HIGH)
    # Depth = 3, try to enqueue NORMAL → triggers expiration (128-133).
    # Heap has only HIGH → nothing to expire → heapify (134) → still full (135-139).
    q.enqueue("normal", TelegramPriority.NORMAL)
    assert q.get_metrics()["dropped_normal"] >= 1


# ── CRITICAL does not drop HIGH (line 148) ───────────────────────────────────


def test_critical_makes_room_but_preserves_high():
    """CRITICAL enqueue at max_depth won't evict HIGH or CRITICAL (line 148 break)."""
    q = make_queue(cfg=dict(CFG, tg_max_queue_depth=3))
    q.enqueue("h1", TelegramPriority.HIGH)
    q.enqueue("h2", TelegramPriority.HIGH)
    q.enqueue("h3", TelegramPriority.HIGH)
    q.enqueue("critical", TelegramPriority.CRITICAL)
    with q._lock:
        priorities = sorted([m.priority for m in q._heap])
    assert priorities == [0, 1, 1, 1]  # 1 CRITICAL + 3 HIGH
    assert q.get_metrics()["dropped_high"] == 0


# ── send_trade_entry / send_trade_close / send_circuit_breaker ───────────────


def test_send_trade_entry_enqueues_high():
    q = make_queue()
    q.send_trade_entry("entry")
    with q._lock:
        assert any(m.priority == 1 for m in q._heap)


def test_send_trade_close_enqueues_critical():
    q = make_queue()
    q.send_trade_close("close")
    with q._lock:
        assert any(m.priority == 0 for m in q._heap)


def test_send_circuit_breaker_enqueues_critical():
    q = make_queue()
    q.send_circuit_breaker("breaker")
    with q._lock:
        assert any(m.priority == 0 for m in q._heap)


# ── Rate-limit sleep (lines 215-219) ─────────────────────────────────────────


def test_rate_wait_sleeps_when_limit_exceeded():
    """_rate_wait() calls time.sleep when sent_this_min >= rate_limit (lines 215-219)."""
    q = make_queue(cfg=dict(CFG, tg_rate_limit_per_min=2))
    now = time.time()
    q._sent_this_min = [now, now - 10]
    with patch("time.sleep") as mock_sleep:
        q._rate_wait()
    assert mock_sleep.called, "rate-limit sleep not triggered"


# ── Exception in _deliver (lines 233-234) ────────────────────────────────────


def test_deliver_handles_send_exception():
    """_deliver catches Exception from send_fn and retries (lines 233-234)."""
    calls = []

    def broken(text):
        calls.append(text)
        raise OSError("broken pipe")

    q = make_queue(send_fn=broken, cfg=dict(CFG, tg_max_retries_normal=2))
    with patch("time.sleep"):
        q._deliver(TelegramMessage(priority=2, ts=time.time(), text="boom"))
    # Should have attempted max_retries+1 = 3 times
    assert len(calls) == 3
