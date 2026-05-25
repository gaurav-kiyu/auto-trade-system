"""Tests for core/ws_feed_manager.py."""

from __future__ import annotations

import time
from unittest.mock import MagicMock

from core.ws_feed_manager import WebSocketFeedManager

# ── Helpers ──────────────────────────────────────────────────────────────

class _TestableWS(WebSocketFeedManager):
    """Subclass that overrides _do_connect to be controllable in tests."""

    def __init__(self, cfg=None, connect_result=True, connect_delay=0.0):
        super().__init__(cfg)
        self._connect_result = connect_result
        self._connect_delay = connect_delay
        self._connect_call_count = 0
        self._disconnect_call_count = 0

    def _do_connect(self, on_message=None, on_error=None):
        self._connect_call_count += 1
        if self._connect_delay > 0:
            time.sleep(self._connect_delay)
        return self._connect_result

    def _do_disconnect(self):
        self._disconnect_call_count += 1


# ── Constructor ──────────────────────────────────────────────────────────

def test_constructor_defaults():
    m = WebSocketFeedManager()
    assert m._max_attempts == 10
    assert m._base_delay_s == 1.0
    assert m._max_delay_s == 30.0
    assert m._jitter_pct == 0.25
    assert m._heartbeat_s == 30.0


def test_constructor_with_cfg():
    m = WebSocketFeedManager(cfg={
        "ws_reconnect_max_attempts": 5,
        "ws_reconnect_base_delay_s": 2.0,
        "ws_reconnect_max_delay_s": 60.0,
        "ws_reconnect_jitter_pct": 0.1,
        "ws_heartbeat_interval_s": 10.0,
    })
    assert m._max_attempts == 5
    assert m._base_delay_s == 2.0
    assert m._max_delay_s == 60.0
    assert m._jitter_pct == 0.1
    assert m._heartbeat_s == 10.0


# ── backoff calculation ─────────────────────────────────────────────────

def test_backoff_delay_increases():
    m = WebSocketFeedManager(cfg={"ws_reconnect_base_delay_s": 1.0, "ws_reconnect_jitter_pct": 0})
    d1 = m._backoff_delay(1)
    d2 = m._backoff_delay(2)
    d3 = m._backoff_delay(3)
    assert d1 == 1.0
    assert d2 == 2.0
    assert d3 == 4.0


def test_backoff_delay_capped():
    m = WebSocketFeedManager(cfg={
        "ws_reconnect_base_delay_s": 10.0,
        "ws_reconnect_max_delay_s": 15.0,
        "ws_reconnect_jitter_pct": 0,
    })
    d1 = m._backoff_delay(1)  # 10
    d2 = m._backoff_delay(2)  # 20 -> 15 (capped)
    assert d1 == 10.0
    assert d2 == 15.0


def test_backoff_jitter_produces_variation():
    m = WebSocketFeedManager(cfg={
        "ws_reconnect_base_delay_s": 1.0,
        "ws_reconnect_jitter_pct": 0.5,
    })
    delays = {m._backoff_delay(1) for _ in range(100)}
    assert len(delays) > 1, "Jitter should produce varied delays"


# ── connect / disconnect ────────────────────────────────────────────────

def test_connect_success():
    ws = _TestableWS(connect_result=True)
    assert ws.connect() is True
    assert ws.is_connected() is True
    assert ws._connect_call_count == 1


def test_connect_failure():
    ws = _TestableWS(connect_result=False)
    assert ws.connect() is False
    assert ws.is_connected() is False


def test_disconnect():
    ws = _TestableWS(connect_result=True)
    ws.connect()
    assert ws.is_connected() is True
    ws.disconnect()
    assert ws.is_connected() is False
    assert ws._disconnect_call_count == 1


def test_connect_passes_callbacks():
    on_msg = MagicMock()
    on_err = MagicMock()
    ws = _TestableWS(connect_result=True)
    ws.connect(on_message=on_msg, on_error=on_err)
    assert ws.is_connected() is True


# ── status ──────────────────────────────────────────────────────────────

def test_status():
    ws = _TestableWS()
    st = ws.status()
    assert st["connected"] is False
    assert st["max_attempts"] == 10
    assert st["base_delay_s"] == 1.0
    assert "reconnect_count" in st


def test_status_after_connect():
    ws = _TestableWS(connect_result=True)
    ws.connect()
    st = ws.status()
    assert st["connected"] is True


# ── reconnect loop ──────────────────────────────────────────────────────

def test_reconnect_loop_connects_on_success():
    ws = _TestableWS(connect_result=True, cfg={
        "ws_reconnect_max_attempts": 3,
        "ws_reconnect_base_delay_s": 0.01,
        "ws_reconnect_max_delay_s": 0.1,
        "ws_reconnect_jitter_pct": 0,
    })
    ws.start_reconnect_loop()
    # Wait for the thread to attempt connection
    for _ in range(50):
        if ws.is_connected():
            break
        time.sleep(0.05)
    assert ws.is_connected() is True
    assert ws._connect_call_count >= 1
    ws.disconnect()


def test_reconnect_loop_gives_up_after_max():
    ws = _TestableWS(connect_result=False, cfg={
        "ws_reconnect_max_attempts": 2,
        "ws_reconnect_base_delay_s": 0.01,
        "ws_reconnect_max_delay_s": 0.1,
        "ws_reconnect_jitter_pct": 0,
    })
    ws.start_reconnect_loop()
    time.sleep(1.5)
    assert ws.is_connected() is False
    ws.disconnect()


def test_double_start_reconnect_is_noop():
    ws = _TestableWS(connect_result=True, cfg={
        "ws_reconnect_max_attempts": 3,
        "ws_reconnect_base_delay_s": 0.01,
        "ws_reconnect_max_delay_s": 0.1,
        "ws_reconnect_jitter_pct": 0,
    })
    ws.start_reconnect_loop()
    # Starting again should log warning but not error
    ws.start_reconnect_loop()
    time.sleep(0.5)
    ws.disconnect()


# ── stub _do_connect returns False ─────────────────────────────────────

def test_base_class_connect_returns_false():
    ws = WebSocketFeedManager()
    assert ws.connect() is False
    assert ws.is_connected() is False


# ── is_connected ────────────────────────────────────────────────────────

def test_is_connected_false_initially():
    ws = WebSocketFeedManager()
    assert ws.is_connected() is False
