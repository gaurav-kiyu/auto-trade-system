"""Tests for Signal Expiry, Holding Horizon Evaluation, and Dry-Run Classification.

Validates:
1. Intraday options expiration on session close and prior calendar dates.
2. Near-close generation 1-session grace period (after 15:15 IST).
3. Swing / Delivery holding horizon (5 exchange trading days).
4. First-touch immutability upon expiry (T1 first touch preserved).
5. Zero-mutation dry-run classification.
6. Idempotent database transition and event logging.
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
    db_file = tmp_path / "test_signals_expiry.db"
    SignalTracker(db_path=db_file)
    tracker = SignalOutcomeTracker(db_path=db_file)
    return tracker, db_file



def _insert_test_signal(
    conn: sqlite3.Connection,
    signal_id: str,
    symbol: str = "RELIANCE",
    category: str = "EQUITY_SWING",
    created_date: str = "2026-09-01",
    timestamp: str = "2026-09-01 10:00:00",
    status: str = "ACTIVE",
    first_touch: str | None = None,
    first_touch_at: str | None = None,
    first_touch_price: float = 0.0,
    entry_price: float = 2500.0,
    sl: float = 2400.0,
    t1: float = 2600.0,
    t2: float = 2700.0,
) -> None:
    conn.execute(
        """INSERT INTO system_signals (
            signal_id, symbol, category, direction, score, tier,
            created_date, created_week, created_month, created_year, timestamp,
            status, first_touch, first_touch_at, first_touch_price,
            entry_price, stop_loss, target_1, target_2, current_price, pnl_pct
        ) VALUES (?, ?, ?, 'CALL', 85, 'TIER_1', ?, '2026-W36', '2026-09', '2026', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0.0)""",
        (
            signal_id, symbol, category, created_date, timestamp,
            status, first_touch, first_touch_at, first_touch_price,
            entry_price, sl, t1, t2, entry_price,
        ),
    )
    conn.commit()



def test_check_signal_expiry_intraday_prior_date(temp_tracker):
    tracker, _ = temp_tracker
    signal = {
        "signal_id": "SIG-OPT-1",
        "symbol": "NIFTY26SEP24500CE",
        "category": "INDEX_OPTIONS",
        "created_date": "2026-09-15",
        "timestamp": "2026-09-15 10:00:00",
        "status": "ACTIVE",
        "first_touch": None,
    }
    # Evaluated on Friday Sep 18, 2026
    current_time = datetime.datetime(2026, 9, 18, 11, 0, 0)
    res = tracker.check_signal_expiry(signal, current_time=current_time)

    assert res["would_expire"] is True
    assert res["classification"] == "WOULD_EXPIRE"
    assert res["holding_horizon"] == "INTRADAY"
    assert res["terminal_state"] == "EXPIRED"
    assert "prior date" in res["reason"]


def test_check_signal_expiry_intraday_same_day_open(temp_tracker):
    tracker, _ = temp_tracker
    signal = {
        "signal_id": "SIG-OPT-2",
        "symbol": "NIFTY26SEP24500CE",
        "category": "INDEX_OPTIONS",
        "created_date": "2026-09-18",
        "timestamp": "2026-09-18 10:00:00",
        "status": "ACTIVE",
        "first_touch": None,
    }
    # Evaluated at 11:30 IST on trading day Sep 18, 2026
    current_time = datetime.datetime(2026, 9, 18, 11, 30, 0)
    res = tracker.check_signal_expiry(signal, current_time=current_time)

    assert res["would_expire"] is False
    assert res["classification"] == "WOULD_REMAIN_ACTIVE"
    assert res["terminal_state"] == "ACTIVE"


def test_check_signal_expiry_intraday_near_close_grace(temp_tracker):
    tracker, _ = temp_tracker
    # Signal generated at 15:20 IST (after 15:15)
    signal = {
        "signal_id": "SIG-OPT-3",
        "symbol": "NIFTY26SEP24500CE",
        "category": "INDEX_OPTIONS",
        "created_date": "2026-09-18",
        "timestamp": "2026-09-18 15:20:00",
        "status": "ACTIVE",
        "first_touch": None,
    }
    # Evaluated at 15:35 IST on the same day
    current_time = datetime.datetime(2026, 9, 18, 15, 35, 0)
    res = tracker.check_signal_expiry(signal, current_time=current_time)

    # Receives 1-session grace period, so it does not expire on same day at 15:35
    assert res["would_expire"] is False
    assert res["classification"] == "WOULD_REMAIN_ACTIVE"
    assert "grace period" in res["reason"]


def test_check_signal_expiry_swing_holding_horizon(temp_tracker):
    tracker, _ = temp_tracker
    # Signal created on Aug 20, 2026 (far more than 5 trading days by Sep 18)
    signal_expired = {
        "signal_id": "SIG-SWING-1",
        "symbol": "INFY",
        "category": "EQUITY_SWING",
        "created_date": "2026-08-20",
        "timestamp": "2026-08-20 10:00:00",
        "status": "ACTIVE",
        "first_touch": None,
    }
    current_time = datetime.datetime(2026, 9, 18, 12, 0, 0)
    res = tracker.check_signal_expiry(signal_expired, current_time=current_time)
    assert res["would_expire"] is True
    assert res["classification"] == "WOULD_EXPIRE"
    assert res["holding_horizon"] == "SWING_5_DAYS"

    # Signal created on Sep 17, 2026 (only 1 trading day by Sep 18)
    signal_valid = {
        "signal_id": "SIG-SWING-2",
        "symbol": "TCS",
        "category": "EQUITY_SWING",
        "created_date": "2026-09-17",
        "timestamp": "2026-09-17 10:00:00",
        "status": "ACTIVE",
        "first_touch": None,
    }
    res_valid = tracker.check_signal_expiry(signal_valid, current_time=current_time)
    assert res_valid["would_expire"] is False
    assert res_valid["classification"] == "WOULD_REMAIN_ACTIVE"


def test_check_signal_expiry_already_terminal(temp_tracker):
    tracker, _ = temp_tracker
    signal_sl = {
        "signal_id": "SIG-TERM-1",
        "symbol": "HDFCBANK",
        "category": "EQUITY_SWING",
        "created_date": "2026-08-20",
        "status": "SL_HIT",
        "first_touch": "SL",
    }
    current_time = datetime.datetime(2026, 9, 18, 12, 0, 0)
    res = tracker.check_signal_expiry(signal_sl, current_time=current_time)
    assert res["would_expire"] is False
    assert res["classification"] == "ALREADY_TERMINAL"
    assert res["terminal_state"] == "SL_HIT"


def test_dry_run_zero_mutation(temp_tracker):
    tracker, db_file = temp_tracker
    conn = sqlite3.connect(str(db_file))
    conn.execute("DELETE FROM system_signals")
    conn.execute("DELETE FROM signal_outcome_events")
    conn.commit()

    # Insert 1 active expired, 1 active valid, 1 terminal
    _insert_test_signal(conn, "1", symbol="SBIN", category="INDEX_OPTIONS", created_date="2026-09-10")
    _insert_test_signal(conn, "2", symbol="ITC", category="EQUITY_SWING", created_date="2026-09-17")
    _insert_test_signal(conn, "3", symbol="LT", category="EQUITY_SWING", created_date="2026-08-10", status="TARGET_2_HIT")

    current_time = datetime.datetime(2026, 9, 18, 12, 0, 0)
    report = tracker.dry_run_signal_expiry(current_time=current_time)

    assert report["summary"]["TOTAL_EVALUATED"] == 3
    assert report["summary"]["WOULD_EXPIRE"] == 1
    assert report["summary"]["WOULD_REMAIN_ACTIVE"] == 1
    assert report["summary"]["ALREADY_TERMINAL"] == 1

    # Verify zero database mutation
    cur = conn.cursor()
    cur.execute("SELECT status FROM system_signals WHERE signal_id = '1'")
    assert cur.fetchone()[0] == "ACTIVE"
    cur.execute("SELECT count(*) FROM signal_outcome_events")
    assert cur.fetchone()[0] == 0
    conn.close()


def test_expire_stale_signals_preserves_first_touch_and_idempotency(temp_tracker):
    tracker, db_file = temp_tracker
    conn = sqlite3.connect(str(db_file))
    conn.execute("DELETE FROM system_signals")
    conn.execute("DELETE FROM signal_outcome_events")
    conn.commit()

    # Signal that already hit T1 on day 1, now 5 trading days elapsed
    _insert_test_signal(

        conn,
        "10",
        symbol="WIPRO",
        category="EQUITY_SWING",
        created_date="2026-08-20",
        status="TARGET_1_HIT",
        first_touch="T1",
        first_touch_at="2026-08-21T11:00:00",
        first_touch_price=550.0,
    )
    # Signal with no barrier hit, now expired
    _insert_test_signal(
        conn,
        "11",
        symbol="TATASTEEL",
        category="EQUITY_SWING",
        created_date="2026-08-20",
        status="ACTIVE",
        first_touch=None,
    )

    current_time = datetime.datetime(2026, 9, 18, 12, 0, 0)

    # 1. Execute expire_stale_signals (mutation pass)
    result = tracker.expire_stale_signals(dry_run=False, current_time=current_time)
    assert result["status"] == "ok"
    assert result["transitioned"] == 2

    # Verify DB state
    cur = conn.cursor()
    # Check signal 10: status is EXPIRED, but first_touch is STILL "T1"
    cur.execute("SELECT status, first_touch, first_touch_at, first_touch_price FROM system_signals WHERE signal_id = '10'")
    row10 = cur.fetchone()
    assert row10[0] == "EXPIRED"
    assert row10[1] == "T1"  # FIRST-TOUCH PRESERVED!
    assert row10[2] == "2026-08-21T11:00:00"
    assert row10[3] == 550.0

    # Check signal 11: status is EXPIRED, and first_touch is "EXPIRED"
    cur.execute("SELECT status, first_touch FROM system_signals WHERE signal_id = '11'")
    row11 = cur.fetchone()
    assert row11[0] == "EXPIRED"
    assert row11[1] == "EXPIRED"

    # Verify audit events were created
    cur.execute("SELECT count(*) FROM signal_outcome_events")
    events_first_run = cur.fetchone()[0]
    assert events_first_run == 2

    # 2. Run AGAIN to verify IDEMPOTENCY
    result_second_run = tracker.expire_stale_signals(dry_run=False, current_time=current_time)
    assert result_second_run["transitioned"] == 0

    # Verify audit events did NOT duplicate
    cur.execute("SELECT count(*) FROM signal_outcome_events")
    events_second_run = cur.fetchone()[0]
    assert events_second_run == events_first_run

    conn.close()
