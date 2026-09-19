"""Integration tests for runtime stale signal expiry sweeper.

Validates:
1. Automatic transition of stale non-terminal signals to EXPIRED at runtime.
2. First-touch immutability preservation (first_touch='T1' preserved when transitioning to EXPIRED).
3. Terminal states (SL_HIT, TARGET_2_HIT, AMBIGUOUS) remain untouched.
4. Rate limiting / throttling of background sweep calls.
5. SignalTracker proxy delegation to SignalOutcomeTracker.
"""

from __future__ import annotations

import datetime
import sqlite3
from pathlib import Path
import pytest

from core.signals.signal_tracker import SignalTracker
from core.signals.signal_outcome_tracker import SignalOutcomeTracker


@pytest.fixture
def temp_tracker(tmp_path: Path) -> tuple[SignalOutcomeTracker, Path]:
    db_file = tmp_path / "test_runtime_expiry.db"
    SignalTracker.reset_instance()
    SignalOutcomeTracker.reset_instance()
    SignalTracker(db_path=db_file)
    tracker = SignalOutcomeTracker(db_path=db_file)
    conn = tracker._get_conn()
    conn.execute("DELETE FROM system_signals")
    conn.execute("DELETE FROM user_deliveries")
    conn.execute("DELETE FROM signal_outcome_events")
    conn.commit()
    conn.close()
    return tracker, db_file


def _insert_signal(
    conn: sqlite3.Connection,
    signal_id: str,
    symbol: str = "NIFTY",
    category: str = "INDEX_OPTIONS",
    created_date: str = "2026-09-18",
    timestamp: str = "2026-09-18 14:11:02",
    status: str = "ACTIVE",
    first_touch: str | None = None,
    first_touch_at: str | None = None,
    first_touch_price: float = 0.0,
    entry_price: float = 100.0,
    sl: float = 80.0,
    t1: float = 130.0,
    t2: float = 160.0,
) -> None:
    conn.execute(
        """INSERT INTO system_signals (
            signal_id, symbol, category, direction, score, tier,
            entry_price, stop_loss, target_1, target_2, current_price,
            pnl_pct, status, first_touch, first_touch_at, first_touch_price,
            created_date, created_week, created_month, created_year, timestamp
        ) VALUES (?, ?, ?, 'CALL', 85, 'STRONG', ?, ?, ?, ?, ?, 0.0, ?, ?, ?, ?, ?, '2026-W38', '2026-09', '2026', ?)""",
        (
            signal_id,
            symbol,
            category,
            entry_price,
            sl,
            t1,
            t2,
            entry_price,
            status,
            first_touch or "",
            first_touch_at or "",
            first_touch_price,
            created_date,
            timestamp,
        ),
    )
    conn.execute(
        """INSERT INTO user_deliveries (
            delivery_id, signal_id, username, timestamp, delivery_date, delivery_week,
            delivery_month, delivery_year, symbol, category, direction, score, tier,
            entry_price, stop_loss, target_1, target_2, current_price, pnl_pct, status, channels_sent
        ) VALUES (?, ?, 'admin', ?, ?, 'W38', '09', '2026', ?, ?, 'CALL', 85, 'STRONG',
                  ?, ?, ?, ?, ?, 0.0, ?, 'TELEGRAM,EMAIL')""",
        (
            f"DEL-{signal_id}",
            signal_id,
            timestamp,
            created_date,
            symbol,
            category,
            entry_price,
            sl,
            t1,
            t2,
            entry_price,
            status,
        ),
    )
    conn.commit()


def test_runtime_sweep_expires_stale_intraday_signal(temp_tracker):
    tracker, db_file = temp_tracker
    conn = tracker._get_conn()
    try:
        _insert_signal(
            conn,
            signal_id="SIG-20260918141102-NIFTY-f9a67e",
            created_date="2026-09-18",
            timestamp="2026-09-18 14:11:02",
            status="ACTIVE",
        )
    finally:
        conn.close()

    eval_time = datetime.datetime(2026, 9, 19, 10, 0, 0)
    res = tracker.run_stale_signal_expiry_sweep(force=True, current_time=eval_time)
    assert res.get("transitioned") == 1

    conn = tracker._get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM system_signals WHERE signal_id = ?", ("SIG-20260918141102-NIFTY-f9a67e",))
        row = dict(cur.fetchone())
        assert row["status"] == "EXPIRED"
        assert row["first_touch"] == "EXPIRED"

        cur.execute("SELECT * FROM user_deliveries WHERE signal_id = ?", ("SIG-20260918141102-NIFTY-f9a67e",))
        del_row = dict(cur.fetchone())
        assert del_row["status"] == "EXPIRED"

        cur.execute("SELECT * FROM signal_outcome_events WHERE signal_id = ?", ("SIG-20260918141102-NIFTY-f9a67e",))
        evt = cur.fetchone()
        assert evt is not None
        assert "Holding horizon expired" in evt["transition_note"]
    finally:
        conn.close()


def test_runtime_sweep_preserves_first_touch_t1(temp_tracker):
    tracker, db_file = temp_tracker
    conn = tracker._get_conn()
    try:
        _insert_signal(
            conn,
            signal_id="SIG-HIT-T1-THEN-EXPIRED",
            created_date="2026-09-18",
            timestamp="2026-09-18 13:00:00",
            status="TARGET_1_HIT",
            first_touch="T1",
            first_touch_at="2026-09-18 13:30:00",
            first_touch_price=130.0,
        )
    finally:
        conn.close()

    eval_time = datetime.datetime(2026, 9, 19, 10, 0, 0)
    res = tracker.run_stale_signal_expiry_sweep(force=True, current_time=eval_time)
    assert res.get("transitioned") == 1

    conn = tracker._get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM system_signals WHERE signal_id = ?", ("SIG-HIT-T1-THEN-EXPIRED",))
        row = dict(cur.fetchone())
        assert row["status"] == "EXPIRED"
        assert row["first_touch"] == "T1"
        assert row["first_touch_price"] == 130.0
        assert row["first_touch_at"] == "2026-09-18 13:30:00"
    finally:
        conn.close()


def test_runtime_sweep_skips_terminal_states(temp_tracker):
    tracker, db_file = temp_tracker
    conn = tracker._get_conn()
    try:
        _insert_signal(conn, "SIG-SL", status="SL_HIT", first_touch="SL")
        _insert_signal(conn, "SIG-T2", status="TARGET_2_HIT", first_touch="T1")
        _insert_signal(conn, "SIG-AMB", status="AMBIGUOUS", first_touch="AMBIGUOUS_SAME_BAR")
    finally:
        conn.close()

    eval_time = datetime.datetime(2026, 9, 19, 10, 0, 0)
    res = tracker.run_stale_signal_expiry_sweep(force=True, current_time=eval_time)
    assert res.get("transitioned") == 0

    conn = tracker._get_conn()
    try:
        cur = conn.cursor()
        for sid, expected_status in [("SIG-SL", "SL_HIT"), ("SIG-T2", "TARGET_2_HIT"), ("SIG-AMB", "AMBIGUOUS")]:
            cur.execute("SELECT status FROM system_signals WHERE signal_id = ?", (sid,))
            assert cur.fetchone()["status"] == expected_status
    finally:
        conn.close()


def test_runtime_sweep_rate_limiting(temp_tracker):
    tracker, db_file = temp_tracker
    eval_time = datetime.datetime(2026, 9, 19, 10, 0, 0)

    # First sweep runs
    res1 = tracker.run_stale_signal_expiry_sweep(force=False, current_time=eval_time)
    assert res1.get("status") == "ok"

    # Second sweep immediately after within 60s is throttled
    eval_time_soon = eval_time + datetime.timedelta(seconds=10)
    res2 = tracker.run_stale_signal_expiry_sweep(force=False, current_time=eval_time_soon)
    assert res2.get("status") == "throttled"

    # With force=True, sweep is not throttled
    res3 = tracker.run_stale_signal_expiry_sweep(force=True, current_time=eval_time_soon)
    assert res3.get("status") == "ok"


def test_signal_tracker_proxy_delegation(temp_tracker):
    tracker, db_file = temp_tracker
    conn = tracker._get_conn()
    try:
        _insert_signal(
            conn,
            signal_id="SIG-VIA-SIGNAL-TRACKER",
            created_date="2026-09-18",
            timestamp="2026-09-18 14:00:00",
            status="ACTIVE",
        )
    finally:
        conn.close()

    sig_tracker = SignalTracker.get_instance(db_path=db_file)
    res = sig_tracker.run_stale_signal_expiry_sweep(force=True)
    assert res.get("transitioned") == 1
