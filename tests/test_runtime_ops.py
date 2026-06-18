"""Tests for core.runtime_ops."""

from __future__ import annotations

import threading
import time

from core.runtime_ops import CircuitBreaker, PerfAccumulator, check_manual_kill_switch


def test_circuit_breaker_trips_and_recovers():
    msgs: list[str] = []

    def log_fn(m: str) -> None:
        msgs.append(m)

    cb = CircuitBreaker(threshold=3, window_sec=300.0, log_fn=log_fn)
    for i in range(3):
        cb.record(f"src{i}")
    assert not cb.ok()
    assert "TRIPPED" in msgs[0]
    # expire failures by advancing time - use tiny window for test
    cb2 = CircuitBreaker(threshold=2, window_sec=0.01, log_fn=log_fn)
    cb2.record("a")
    cb2.record("b")
    assert not cb2.ok()
    time.sleep(0.05)
    assert cb2.ok() is True


def test_perf_accumulator_summary():
    acc = PerfAccumulator(("fetch",))
    acc.record("fetch", 10.0)
    acc.record("fetch", 20.0)
    s = acc.summary()
    assert "fetch" in s
    assert acc.any_stage_len_over(1) is True
    acc.trim_queues_over(1, 1)
    acc.clear_all_stages()
    assert acc.summary() == "No data"


def test_check_manual_kill_switch(tmp_path):
    ev = threading.Event()
    trips: list[str] = []

    def trip(r: str) -> None:
        trips.append(r)
        ev.set()

    kf = tmp_path / "STOP"
    assert check_manual_kill_switch(kf, halt_event=ev, trip=trip) is False
    kf.write_text("x", encoding="utf-8")
    assert check_manual_kill_switch(kf, halt_event=ev, trip=trip) is True
    assert len(trips) == 1
    assert check_manual_kill_switch(kf, halt_event=ev, trip=trip) is True
    assert len(trips) == 1
