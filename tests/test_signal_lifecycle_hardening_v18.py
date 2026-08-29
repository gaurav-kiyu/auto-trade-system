import json
import sqlite3
from pathlib import Path

from core.signals.signal_tracker import SignalTracker


def test_duplicate_opportunity_is_suppressed(tmp_path):
    db = tmp_path / "signals.db"
    tracker = SignalTracker(db)
    con0 = sqlite3.connect(db)
    con0.execute("DELETE FROM system_signals")
    con0.commit(); con0.close()
    base = {
        "symbol": "NIFTY",
        "category": "INDEX_OPTIONS",
        "direction": "CALL",
        "price": 100,
        "stop_loss": 97,
        "target_1": 104,
        "target_2": 108,
        "score": 100,
        "raw_score": 112,
        "tier": "STRONG",
        "regime": "TREND",
        "dedup_cooldown_secs": 900,
    }
    first = tracker.record_generated_signal(base, [])
    second = tracker.record_generated_signal(base, [])
    assert first
    assert second == ""
    con = sqlite3.connect(db)
    assert con.execute("select count(*) from system_signals").fetchone()[0] == 1
    row = con.execute("select raw_score, score_saturated from system_signals").fetchone()
    assert row == (112.0, 1)
    con.close()


def test_scan_cycle_metrics_persist(tmp_path):
    db = tmp_path / "signals.db"
    tracker = SignalTracker(db)
    cid = tracker.record_scan_cycle(
        {"evaluated": 700, "accepted": 42, "delivered_candidates": 40, "errors": 3},
        symbols_scanned=2500,
        timestamp="2026-08-26T10:00:00+05:30",
    )
    assert cid
    con = sqlite3.connect(db)
    row = con.execute("select symbols_scanned,evaluated,accepted,delivered_candidates,errors from scan_cycle_metrics").fetchone()
    assert row == (2500,700,42,40,3)
    con.close()
