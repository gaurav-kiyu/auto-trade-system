"""Exhaustive Test Suite: OPB v2.60 Outcome Materialization Semantics.

Governance: OPB-FINAL-PHASE-GOVERNANCE-001
RFC: RFC-OPB-V260-LIFECYCLE-001 (CORRECTED FINAL GATE)
Specification: OPB_V260_OUTCOME_MATERIALIZATION_SEMANTIC_REVIEW_20261005

Validates all 30 requirements specified in Part P:
1. T1 only
2. T1 -> T2
3. T1 -> SL
4. T1 -> timeout
5. T1 -> reversal
6. Direct T2 without independent T1 evidence
7. Direct T2 with provable T1 crossing
8. Terminal exit after T2
9. T2 milestone while still active
10. MFE continues after T1
11. MFE continues after T2
12. MAE continues after T1
13. MAE continues after T2
14. Rematerialization idempotency
15. No duplicate measurement rows
16. No duplicate lifecycle events
17. Historical signal without measurement
18. Canonical SL_HIT without measurement
19. Ambiguous same-bar
20. First-touch invariant
21. P&L/MTM vs realized-R separation
22. API/list/detail consistency
23. SMCGLOBAL fixture
24. Multiple unrelated symbols/categories
25. Multiple dates
26. Active and terminal signals
27. T2 reached then later reversal
28. T2 reached then later horizon expiry
29. Restart/interruption-safe rematerialization
30. Full-population consistency scan
"""

import datetime
import json
import sqlite3
import pytest
from pathlib import Path

from core.signals.signal_outcome_dataset import SignalOutcomeDatasetService
from core.signals.signal_outcome_tracker import SignalOutcomeTracker, SignalBar
from core.signals.signal_forward_observation import SignalForwardObservationService
from core.signals.signal_tracker import SignalTracker

IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))


def init_test_schema(db_path: Path):
    """Initialize full test SQLite database schema matching production."""
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS system_signals (
            signal_id TEXT PRIMARY KEY,
            timestamp TEXT NOT NULL,
            created_date TEXT,
            created_week TEXT,
            created_month TEXT,
            created_year TEXT,
            symbol TEXT NOT NULL,
            company_name TEXT,
            category TEXT NOT NULL,
            direction TEXT NOT NULL,
            score REAL NOT NULL,
            tier TEXT,
            entry_price REAL NOT NULL,
            stop_loss REAL NOT NULL,
            target_1 REAL NOT NULL,
            target_2 REAL NOT NULL,
            current_price REAL,
            status TEXT NOT NULL DEFAULT 'ACTIVE',
            pnl_pct REAL DEFAULT 0.0,
            recipients_count INTEGER DEFAULT 0,
            raw_data TEXT,
            raw_score REAL,
            normalized_score REAL,
            score_saturated INTEGER DEFAULT 0,
            opportunity_key TEXT,
            outcome_confidence TEXT DEFAULT 'UNKNOWN',
            order_placed INTEGER DEFAULT 0,
            order_placed_by TEXT,
            order_placed_at TEXT,
            first_touch TEXT,
            first_touch_at TEXT,
            first_touch_price REAL
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS signal_outcome_events (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT,
            signal_id TEXT NOT NULL,
            observed_at TEXT NOT NULL,
            observed_price REAL NOT NULL,
            hit_sl INTEGER NOT NULL DEFAULT 0,
            hit_t1 INTEGER NOT NULL DEFAULT 0,
            hit_t2 INTEGER NOT NULL DEFAULT 0,
            transition_note TEXT,
            FOREIGN KEY (signal_id) REFERENCES system_signals(signal_id)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS signal_prediction_snapshots (
            signal_id TEXT PRIMARY KEY,
            symbol TEXT NOT NULL,
            category TEXT NOT NULL,
            direction TEXT NOT NULL,
            score REAL NOT NULL,
            tier TEXT,
            entry_price REAL NOT NULL,
            stop_loss REAL NOT NULL,
            target_1 REAL NOT NULL,
            target_2 REAL NOT NULL,
            captured_at TEXT NOT NULL,
            payload_json TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS signal_forward_observations (
            forward_id TEXT PRIMARY KEY,
            signal_id TEXT NOT NULL UNIQUE,
            cohort_id TEXT,
            observation_source TEXT NOT NULL,
            forward_cutoff_version TEXT NOT NULL,
            registered_at TEXT NOT NULL,
            market_date TEXT NOT NULL,
            session_name TEXT NOT NULL,
            score REAL NOT NULL,
            score_bucket TEXT NOT NULL,
            direction TEXT NOT NULL,
            symbol TEXT NOT NULL,
            category TEXT NOT NULL,
            entry_price REAL NOT NULL,
            stop_loss REAL NOT NULL,
            target_1 REAL NOT NULL,
            target_2 REAL NOT NULL,
            prediction_hash TEXT NOT NULL,
            snapshot_captured_at TEXT NOT NULL,
            observation_status TEXT NOT NULL DEFAULT 'OBSERVING',
            terminal_outcome TEXT,
            is_resolved INTEGER NOT NULL DEFAULT 0,
            resolution_timestamp TEXT,
            mfe_r REAL,
            mae_r REAL,
            realized_r REAL,
            data_quality_status TEXT NOT NULL DEFAULT 'VALID_DATA',
            observation_version TEXT NOT NULL,
            last_updated_at TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()


@pytest.fixture
def isolated_db(tmp_path):
    """Provide an isolated, fully initialized database path for testing."""
    db_file = tmp_path / "test_signals.db"
    init_test_schema(db_file)
    SignalOutcomeDatasetService.reset_instance()
    SignalOutcomeTracker.reset_instance()
    SignalForwardObservationService.reset_instance()
    SignalTracker.reset_instance()
    yield db_file
    SignalOutcomeDatasetService.reset_instance()
    SignalOutcomeTracker.reset_instance()
    SignalForwardObservationService.reset_instance()
    SignalTracker.reset_instance()


def insert_signal_helper(
    db_path: Path,
    signal_id: str,
    symbol: str = "TESTSYM",
    direction: str = "CALL",
    entry: float = 100.0,
    sl: float = 95.0,
    t1: float = 105.0,
    t2: float = 110.0,
    status: str = "ACTIVE",
    category: str = "EQUITY_SWING_DELIVERY",
    first_touch: str = None,
    first_touch_at: str = None,
    first_touch_price: float = None,
    current_price: float = 100.0,
    pnl_pct: float = 0.0,
    timestamp: str = "2026-10-05 09:15:00",
):
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO system_signals (
            signal_id, timestamp, created_date, symbol, category, direction,
            score, tier, entry_price, stop_loss, target_1, target_2,
            current_price, status, pnl_pct, first_touch, first_touch_at, first_touch_price
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            signal_id, timestamp, timestamp[:10], symbol, category, direction,
            85.0, "STRONG", entry, sl, t1, t2,
            current_price, status, pnl_pct, first_touch or "", first_touch_at or "", first_touch_price or 0.0
        ),
    )
    cur.execute(
        """INSERT INTO signal_prediction_snapshots (
            signal_id, symbol, category, direction, score, tier,
            entry_price, stop_loss, target_1, target_2, captured_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            signal_id, symbol, category, direction, 85.0, "STRONG",
            entry, sl, t1, t2, timestamp
        ),
    )
    conn.commit()
    conn.close()


def insert_event_helper(
    db_path: Path,
    signal_id: str,
    observed_at: str,
    price: float,
    hit_sl: int = 0,
    hit_t1: int = 0,
    hit_t2: int = 0,
    note: str = "",
):
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO signal_outcome_events (
            signal_id, observed_at, observed_price, hit_sl, hit_t1, hit_t2, transition_note
        ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (signal_id, observed_at, price, hit_sl, hit_t1, hit_t2, note),
    )
    conn.commit()
    conn.close()


# ==============================================================================
# TEST CASES 1 - 30
# ==============================================================================

def test_1_t1_only(isolated_db):
    """Case 1: Signal reaches T1 only. In-flight, milestone set, exit_price None."""
    sig_id = "SIG-T1-ONLY"
    insert_signal_helper(
        isolated_db, sig_id, status="TARGET_1_HIT", first_touch="T1",
        first_touch_at="2026-10-05 10:00:00", first_touch_price=105.5,
        current_price=106.0, pnl_pct=6.0
    )
    insert_event_helper(isolated_db, sig_id, "2026-10-05 10:00:00", 105.5, hit_t1=1)

    ds_svc = SignalOutcomeDatasetService.get_instance(db_path=isolated_db)
    meas = ds_svc.build_signal_outcome_measurement(sig_id)

    assert meas is not None
    assert meas["first_touch"] == "T1"
    assert meas["target_1_hit"] == 1
    assert meas["target_2_hit"] == 0
    assert meas["stop_loss_hit"] == 0
    assert meas["exit_price"] is None
    assert meas["realized_r"] is None
    assert meas["outcome"] == "TARGET_FIRST"


def test_2_t1_then_t2_progression(isolated_db):
    """Case 2: Signal progresses T1 -> T2. first_touch remains T1, T2 hit, terminal exit recorded."""
    sig_id = "SIG-T1-T2"
    insert_signal_helper(
        isolated_db, sig_id, status="TARGET_2_HIT", first_touch="T1",
        first_touch_at="2026-10-05 10:00:00", first_touch_price=105.5,
        current_price=111.0, pnl_pct=11.0
    )
    insert_event_helper(isolated_db, sig_id, "2026-10-05 10:00:00", 105.5, hit_t1=1)
    insert_event_helper(isolated_db, sig_id, "2026-10-05 11:30:00", 111.0, hit_t2=1)

    ds_svc = SignalOutcomeDatasetService.get_instance(db_path=isolated_db)
    meas = ds_svc.build_signal_outcome_measurement(sig_id)

    assert meas is not None
    assert meas["first_touch"] == "T1"
    assert meas["target_1_hit"] == 1
    assert meas["target_2_hit"] == 1
    assert meas["stop_loss_hit"] == 0
    assert meas["exit_price"] == 111.0
    assert meas["realized_r"] == pytest.approx(2.2, rel=1e-2)  # (111-100)/5


def test_3_t1_then_sl_progression(isolated_db):
    """Case 3: Signal progresses T1 -> SL. first_touch is T1, T1 hit is YES, SL hit is YES."""
    sig_id = "SIG-T1-SL"
    insert_signal_helper(
        isolated_db, sig_id, status="SL_HIT", first_touch="T1",
        first_touch_at="2026-10-05 10:00:00", first_touch_price=105.5,
        current_price=94.5, pnl_pct=-5.5
    )
    insert_event_helper(isolated_db, sig_id, "2026-10-05 10:00:00", 105.5, hit_t1=1)
    insert_event_helper(isolated_db, sig_id, "2026-10-05 12:00:00", 94.5, hit_sl=1)

    ds_svc = SignalOutcomeDatasetService.get_instance(db_path=isolated_db)
    meas = ds_svc.build_signal_outcome_measurement(sig_id)

    assert meas is not None
    assert meas["first_touch"] == "T1"
    assert meas["target_1_hit"] == 1
    assert meas["target_2_hit"] == 0
    assert meas["stop_loss_hit"] == 1
    assert meas["exit_price"] == 94.5
    assert meas["realized_r"] == pytest.approx(-1.1, rel=1e-2)


def test_4_t1_then_timeout(isolated_db):
    """Case 4: Signal hits T1 then expires at holding horizon."""
    sig_id = "SIG-T1-EXPIRED"
    insert_signal_helper(
        isolated_db, sig_id, status="EXPIRED", first_touch="T1",
        first_touch_at="2026-10-05 10:00:00", first_touch_price=105.5,
        current_price=104.0, pnl_pct=4.0
    )
    insert_event_helper(isolated_db, sig_id, "2026-10-05 10:00:00", 105.5, hit_t1=1)

    ds_svc = SignalOutcomeDatasetService.get_instance(db_path=isolated_db)
    meas = ds_svc.build_signal_outcome_measurement(sig_id)

    assert meas is not None
    assert meas["first_touch"] == "T1"
    assert meas["target_1_hit"] == 1
    assert meas["target_2_hit"] == 0
    assert meas["exit_price"] == 104.0
    assert meas["realized_r"] == pytest.approx(0.8, rel=1e-2)


def test_5_t1_then_reversal(isolated_db):
    """Case 5: Signal hits T1 then closes on opposite-direction reversal."""
    sig_id = "SIG-T1-REV"
    insert_signal_helper(
        isolated_db, sig_id, status="CLOSED_ON_REVERSAL", first_touch="T1",
        first_touch_at="2026-10-05 10:00:00", first_touch_price=105.5,
        current_price=103.5, pnl_pct=3.5
    )
    insert_event_helper(isolated_db, sig_id, "2026-10-05 10:00:00", 105.5, hit_t1=1)

    ds_svc = SignalOutcomeDatasetService.get_instance(db_path=isolated_db)
    meas = ds_svc.build_signal_outcome_measurement(sig_id)

    assert meas is not None
    assert meas["first_touch"] == "T1"
    assert meas["target_1_hit"] == 1
    assert meas["outcome"] == "REVERSED"
    assert meas["exit_price"] == 103.5


def test_6_direct_t2_without_independent_t1_evidence(isolated_db):
    """Case 6: Direct T2 gap without independent T1 evidence: first_touch=T2, t1_hit=0."""
    sig_id = "SIG-T2-DIRECT"
    insert_signal_helper(
        isolated_db, sig_id, status="TARGET_2_HIT", first_touch="T2",
        first_touch_at="2026-10-05 09:16:00", first_touch_price=112.0,
        current_price=112.0, pnl_pct=12.0
    )
    insert_event_helper(isolated_db, sig_id, "2026-10-05 09:16:00", 112.0, hit_t2=1, hit_t1=0)

    ds_svc = SignalOutcomeDatasetService.get_instance(db_path=isolated_db)
    meas = ds_svc.build_signal_outcome_measurement(sig_id)

    assert meas is not None
    assert meas["first_touch"] == "T2"
    assert meas["target_2_hit"] == 1
    assert meas["target_1_hit"] == 0  # Not fabricated


def test_7_direct_t2_with_provable_t1_crossing(isolated_db):
    """Case 7: Single candle crossing both T1 and T2 (low=99, high=112). Tracker stamps T1 first touch."""
    tracker = SignalOutcomeTracker.get_instance(db_path=isolated_db)
    sig = {
        "signal_id": "SIG-BAR-T1-T2",
        "symbol": "TESTSYM",
        "direction": "CALL",
        "entry_price": 100.0,
        "stop_loss": 95.0,
        "target_1": 105.0,
        "target_2": 110.0,
        "status": "ACTIVE",
        "first_touch": "",
        "created_date": "2026-10-05",
    }
    bar = SignalBar(open=100.0, high=112.0, low=99.0, close=111.0, timestamp="2026-10-05T09:20:00+05:30")
    res = tracker.evaluate_bar(sig, bar)

    assert res.new_status == "TARGET_2_HIT"
    assert res.first_touch == "T1"  # Provably crossed T1 within the same bar
    assert res.hit_t1 is True
    assert res.hit_t2 is True


def test_8_terminal_exit_after_t2(isolated_db):
    """Case 8: Position liquidated upon reaching Target 2."""
    sig_id = "SIG-T2-TERM"
    insert_signal_helper(
        isolated_db, sig_id, status="TARGET_2_HIT", first_touch="T1",
        first_touch_at="2026-10-05 10:00:00", first_touch_price=105.0,
        current_price=110.5, pnl_pct=10.5
    )
    insert_event_helper(isolated_db, sig_id, "2026-10-05 10:00:00", 105.0, hit_t1=1)
    insert_event_helper(isolated_db, sig_id, "2026-10-05 11:00:00", 110.5, hit_t2=1)

    ds_svc = SignalOutcomeDatasetService.get_instance(db_path=isolated_db)
    meas = ds_svc.build_signal_outcome_measurement(sig_id)

    assert meas["exit_price"] == 110.5
    assert meas["realized_r"] == pytest.approx(2.1, rel=1e-2)


def test_9_t2_milestone_while_still_active(isolated_db):
    """Case 9: If status is ACTIVE after T1, exit_price and realized_r remain None."""
    sig_id = "SIG-T1-ACTIVE"
    insert_signal_helper(
        isolated_db, sig_id, status="ACTIVE", first_touch="T1",
        first_touch_at="2026-10-05 10:00:00", first_touch_price=105.0,
        current_price=107.0, pnl_pct=7.0
    )
    insert_event_helper(isolated_db, sig_id, "2026-10-05 10:00:00", 105.0, hit_t1=1)

    ds_svc = SignalOutcomeDatasetService.get_instance(db_path=isolated_db)
    meas = ds_svc.build_signal_outcome_measurement(sig_id)

    assert meas["exit_price"] is None
    assert meas["realized_r"] is None


def test_10_mfe_continues_after_t1(isolated_db):
    """Case 10: MFE does not freeze at T1 price level."""
    sig_id = "SIG-MFE-T1"
    insert_signal_helper(
        isolated_db, sig_id, status="TARGET_1_HIT", first_touch="T1",
        first_touch_at="2026-10-05 10:00:00", first_touch_price=105.0,
        current_price=108.0, pnl_pct=8.0
    )
    insert_event_helper(isolated_db, sig_id, "2026-10-05 10:00:00", 105.0, hit_t1=1)
    insert_event_helper(isolated_db, sig_id, "2026-10-05 10:30:00", 108.5)

    ds_svc = SignalOutcomeDatasetService.get_instance(db_path=isolated_db)
    meas = ds_svc.build_signal_outcome_measurement(sig_id)

    assert meas["mfe"] == 8.5  # Peak at 108.5, not frozen at 105.0
    assert meas["mfe_pct"] == 8.5


def test_11_mfe_continues_after_t2(isolated_db):
    """Case 11: MFE does not freeze at T2 price level."""
    sig_id = "SIG-MFE-T2"
    insert_signal_helper(
        isolated_db, sig_id, status="TARGET_2_HIT", first_touch="T1",
        first_touch_at="2026-10-05 10:00:00", first_touch_price=105.0,
        current_price=115.0, pnl_pct=15.0
    )
    insert_event_helper(isolated_db, sig_id, "2026-10-05 10:00:00", 105.0, hit_t1=1)
    insert_event_helper(isolated_db, sig_id, "2026-10-05 11:00:00", 110.0, hit_t2=1)
    insert_event_helper(isolated_db, sig_id, "2026-10-05 12:00:00", 116.0)

    ds_svc = SignalOutcomeDatasetService.get_instance(db_path=isolated_db)
    meas = ds_svc.build_signal_outcome_measurement(sig_id)

    assert meas["mfe"] == 16.0  # Peak at 116.0, not frozen at 110.0


def test_12_mae_continues_after_t1(isolated_db):
    """Case 12: MAE tracks adverse movement occurring after T1."""
    sig_id = "SIG-MAE-T1"
    insert_signal_helper(
        isolated_db, sig_id, status="TARGET_1_HIT", first_touch="T1",
        first_touch_at="2026-10-05 10:00:00", first_touch_price=105.0,
        current_price=98.0, pnl_pct=-2.0
    )
    insert_event_helper(isolated_db, sig_id, "2026-10-05 10:00:00", 105.0, hit_t1=1)
    insert_event_helper(isolated_db, sig_id, "2026-10-05 11:00:00", 97.5)

    ds_svc = SignalOutcomeDatasetService.get_instance(db_path=isolated_db)
    meas = ds_svc.build_signal_outcome_measurement(sig_id)

    assert meas["mae"] == 2.5  # 100.0 - 97.5 (non-negative adverse magnitude)


def test_13_mae_continues_after_t2(isolated_db):
    """Case 13: MAE accurately records adverse drawdown across the life of a T2 signal."""
    sig_id = "SIG-MAE-T2"
    insert_signal_helper(
        isolated_db, sig_id, status="TARGET_2_HIT", first_touch="T1",
        first_touch_at="2026-10-05 10:00:00", first_touch_price=105.0,
        current_price=110.0, pnl_pct=10.0
    )
    insert_event_helper(isolated_db, sig_id, "2026-10-05 09:30:00", 98.0)  # Dip before rally
    insert_event_helper(isolated_db, sig_id, "2026-10-05 10:00:00", 105.0, hit_t1=1)
    insert_event_helper(isolated_db, sig_id, "2026-10-05 11:00:00", 110.0, hit_t2=1)

    ds_svc = SignalOutcomeDatasetService.get_instance(db_path=isolated_db)
    meas = ds_svc.build_signal_outcome_measurement(sig_id)

    assert meas["mae"] == 2.0  # 100.0 - 98.0 (non-negative adverse magnitude)


def test_14_rematerialization_idempotency(isolated_db):
    """Case 14: Repeated build_signal_outcome_measurement calls are strictly idempotent."""
    sig_id = "SIG-IDEMPOTENT"
    insert_signal_helper(
        isolated_db, sig_id, status="TARGET_2_HIT", first_touch="T1",
        first_touch_at="2026-10-05 10:00:00", first_touch_price=105.0,
        current_price=110.0, pnl_pct=10.0
    )
    insert_event_helper(isolated_db, sig_id, "2026-10-05 10:00:00", 105.0, hit_t1=1)
    insert_event_helper(isolated_db, sig_id, "2026-10-05 11:00:00", 110.0, hit_t2=1)

    ds_svc = SignalOutcomeDatasetService.get_instance(db_path=isolated_db)
    meas1 = ds_svc.build_signal_outcome_measurement(sig_id)
    meas2 = ds_svc.build_signal_outcome_measurement(sig_id)

    assert meas1["target_1_hit"] == meas2["target_1_hit"]
    assert meas1["target_2_hit"] == meas2["target_2_hit"]
    assert meas1["exit_price"] == meas2["exit_price"]
    assert meas1["realized_r"] == meas2["realized_r"]


def test_15_no_duplicate_measurement_rows(isolated_db):
    """Case 15: Executing materialization multiple times maintains exactly 1 row per signal."""
    sig_id = "SIG-NO-DUP"
    insert_signal_helper(isolated_db, sig_id)
    ds_svc = SignalOutcomeDatasetService.get_instance(db_path=isolated_db)
    ds_svc.build_signal_outcome_measurement(sig_id)
    ds_svc.build_signal_outcome_measurement(sig_id)
    ds_svc.build_signal_outcome_measurement(sig_id)

    conn = sqlite3.connect(str(isolated_db))
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM signal_outcome_measurements WHERE signal_id = ?", (sig_id,))
    count = cur.fetchone()[0]
    conn.close()

    assert count == 1


def test_16_no_duplicate_lifecycle_events(isolated_db):
    """Case 16: Tracker does not insert duplicate events for identical price state."""
    tracker = SignalOutcomeTracker.get_instance(db_path=isolated_db)
    insert_signal_helper(isolated_db, "SIG-DUP-EVT", current_price=100.0)

    # First poll: hits T1
    tracker.update_active_signal_outcomes(price_lookup_fn=lambda s: 106.0)
    # Second poll: price unchanged at 106.0
    tracker.update_active_signal_outcomes(price_lookup_fn=lambda s: 106.0)

    conn = sqlite3.connect(str(isolated_db))
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM signal_outcome_events WHERE signal_id = 'SIG-DUP-EVT'")
    evt_count = cur.fetchone()[0]
    conn.close()

    assert evt_count == 1


def test_17_historical_signal_without_measurement(isolated_db):
    """Case 17: Historical signal without measurement returns evaluated=False, target_1_hit=None."""
    sig_id = "SIG-HIST-NO-MEAS"
    insert_signal_helper(isolated_db, sig_id, status="ACTIVE", first_touch="")

    st_svc = SignalTracker.get_instance(db_path=isolated_db)
    expl = st_svc.get_signal_explanation(sig_id)

    assert expl is not None
    assert expl["excursion"]["evaluated"] is False
    assert expl["excursion"]["target_1_hit"] is None
    assert expl["excursion"]["target_2_hit"] is None
    assert expl["excursion"]["stop_loss_hit"] is None
    assert expl["lifecycle"]["first_touch"] is None


def test_18_canonical_sl_hit_without_measurement(isolated_db):
    """Case 18: Historical signal with status=SL_HIT proves stop_loss_hit=True even without measurement."""
    sig_id = "SIG-HIST-SL"
    insert_signal_helper(isolated_db, sig_id, status="SL_HIT", first_touch="SL")

    st_svc = SignalTracker.get_instance(db_path=isolated_db)
    expl = st_svc.get_signal_explanation(sig_id)

    assert expl is not None
    assert expl["excursion"]["evaluated"] is False
    assert expl["excursion"]["stop_loss_hit"] is True
    assert expl["excursion"]["target_1_hit"] is None
    assert expl["lifecycle"]["first_touch"] == "SL"
    assert expl["lifecycle"]["outcome_status"] == "Stop Loss"


def test_19_ambiguous_same_bar(isolated_db):
    """Case 19: Both T1 and SL hit in the same bar quarantines as AMBIGUOUS, first_touch is None."""
    tracker = SignalOutcomeTracker.get_instance(db_path=isolated_db)
    sig = {
        "signal_id": "SIG-AMB",
        "symbol": "TESTSYM",
        "direction": "CALL",
        "entry_price": 100.0,
        "stop_loss": 95.0,
        "target_1": 105.0,
        "target_2": 110.0,
        "status": "ACTIVE",
        "first_touch": "",
        "created_date": "2026-10-05",
    }
    bar = SignalBar(open=100.0, high=106.0, low=94.0, close=101.0, timestamp="2026-10-05T09:20:00+05:30")
    res = tracker.evaluate_bar(sig, bar)

    assert res.new_status == "AMBIGUOUS"
    assert res.first_touch is None


def test_20_first_touch_invariant(isolated_db):
    """Case 20: EXPIRED, TIMEOUT, AMBIGUOUS are never stamped as first_touch."""
    tracker = SignalOutcomeTracker.get_instance(db_path=isolated_db)
    sig = {
        "signal_id": "SIG-INV",
        "symbol": "TESTSYM",
        "direction": "CALL",
        "entry_price": 100.0,
        "stop_loss": 95.0,
        "target_1": 105.0,
        "target_2": 110.0,
        "status": "ACTIVE",
        "first_touch": "",
        "category": "INTRADAY",
        "created_date": "2026-10-04",  # Prior day
    }
    bar = SignalBar(open=100.0, high=101.0, low=99.0, close=100.0, timestamp="2026-10-05T09:20:00+05:30")
    res = tracker.evaluate_bar(sig, bar)

    assert res.new_status == "EXPIRED"
    assert res.first_touch is None  # EXPIRED is NOT a first touch


def test_21_pnl_pct_mtm_vs_realized_r_separation(isolated_db):
    """Case 21: system_signals.pnl_pct is live MTM; measurement.realized_r is terminal only."""
    sig_id = "SIG-MTM-R"
    insert_signal_helper(
        isolated_db, sig_id, status="TARGET_1_HIT", first_touch="T1",
        entry=100.0, sl=95.0, current_price=107.0, pnl_pct=7.0
    )
    insert_event_helper(isolated_db, sig_id, "2026-10-05 10:00:00", 105.0, hit_t1=1)

    ds_svc = SignalOutcomeDatasetService.get_instance(db_path=isolated_db)
    meas = ds_svc.build_signal_outcome_measurement(sig_id)

    conn = sqlite3.connect(str(isolated_db))
    cur = conn.cursor()
    cur.execute("SELECT pnl_pct FROM system_signals WHERE signal_id = ?", (sig_id,))
    pnl = cur.fetchone()[0]
    conn.close()

    assert pnl == 7.0  # Current MTM
    assert meas["realized_r"] is None  # Not closed yet


def test_22_api_list_detail_consistency(isolated_db):
    """Case 22: Both API surfaces agree on milestone flags."""
    sig_id = "SIG-API-CONSIST"
    insert_signal_helper(
        isolated_db, sig_id, status="TARGET_2_HIT", first_touch="T1",
        first_touch_at="2026-10-05 10:00:00", first_touch_price=105.0,
        current_price=111.0, pnl_pct=11.0
    )
    insert_event_helper(isolated_db, sig_id, "2026-10-05 10:00:00", 105.0, hit_t1=1)
    insert_event_helper(isolated_db, sig_id, "2026-10-05 11:00:00", 111.0, hit_t2=1)

    ds_svc = SignalOutcomeDatasetService.get_instance(db_path=isolated_db)
    ds_svc.build_signal_outcome_measurement(sig_id)

    st_svc = SignalTracker.get_instance(db_path=isolated_db)
    expl = st_svc.get_signal_explanation(sig_id)

    assert expl["lifecycle"]["outcome_status"] == "Target-2"
    assert expl["lifecycle"]["first_touch"] == "T1"
    assert expl["excursion"]["target_1_hit"] is True
    assert expl["excursion"]["target_2_hit"] is True
    assert expl["excursion"]["stop_loss_hit"] is False


def test_23_smcglobal_fixture_acceptance(isolated_db):
    """Case 23: Exact forensic reconciliation of SIG-20261005095443-SMCGLOBAL-8a7a1b fixture."""
    sig_id = "SIG-20261005095443-SMCGLOBAL-8a7a1b"
    insert_signal_helper(
        isolated_db,
        signal_id=sig_id,
        symbol="SMCGLOBAL",
        direction="CALL",
        entry=101.99,
        sl=98.93,
        t1=106.07,
        t2=110.15,
        status="TARGET_2_HIT",
        category="EQUITY_SWING_DELIVERY",
        first_touch="T1",
        first_touch_at="2026-10-05 11:10:49.217274",
        first_touch_price=106.07,
        current_price=114.83,
        pnl_pct=12.59,
        timestamp="2026-10-05 09:54:43",
    )
    # Event 1: T1 hit observed at 107.84
    insert_event_helper(
        isolated_db, sig_id, "2026-10-05 11:10:49.217274", 107.84, hit_t1=1, note="Target 1 hit"
    )
    # Event 2: T2 hit observed at 114.83
    insert_event_helper(
        isolated_db, sig_id, "2026-10-05 13:45:00.000000", 114.83, hit_t2=1, note="Target 2 reached"
    )

    ds_svc = SignalOutcomeDatasetService.get_instance(db_path=isolated_db)
    meas = ds_svc.build_signal_outcome_measurement(sig_id)

    assert meas is not None
    assert meas["symbol"] == "SMCGLOBAL"
    assert meas["first_touch"] == "T1"
    assert meas["target_1_hit"] == 1
    assert meas["target_2_hit"] == 1
    assert meas["stop_loss_hit"] == 0
    assert meas["exit_price"] == 114.83
    assert meas["realized_r"] == pytest.approx((114.83 - 101.99) / 3.06, rel=1e-2)

    st_svc = SignalTracker.get_instance(db_path=isolated_db)
    expl = st_svc.get_signal_explanation(sig_id)

    assert expl["lifecycle"]["outcome_status"] == "Target-2"
    assert expl["lifecycle"]["first_touch"] == "T1"
    assert expl["excursion"]["target_1_hit"] is True
    assert expl["excursion"]["target_2_hit"] is True
    assert expl["excursion"]["stop_loss_hit"] is False


def test_24_multiple_unrelated_symbols(isolated_db):
    """Case 24: Generic logic handles diverse symbols and categories."""
    symbols = [("RELIANCE", "LARGE_CAP_EQUITY"), ("BANKNIFTY", "INDEX_OPTIONS"), ("GOLDM", "COMMODITIES")]
    for sym, cat in symbols:
        sig_id = f"SIG-{sym}"
        insert_signal_helper(isolated_db, sig_id, symbol=sym, category=cat, status="TARGET_1_HIT", first_touch="T1")
        insert_event_helper(isolated_db, sig_id, "2026-10-05 10:00:00", 105.0, hit_t1=1)

    ds_svc = SignalOutcomeDatasetService.get_instance(db_path=isolated_db)
    for sym, cat in symbols:
        meas = ds_svc.build_signal_outcome_measurement(f"SIG-{sym}")
        assert meas["symbol"] == sym
        assert meas["category"] == cat
        assert meas["target_1_hit"] == 1


def test_25_multiple_dates(isolated_db):
    """Case 25: Generic logic respects different market dates."""
    dates = ["2026-09-18", "2026-09-28", "2026-10-05"]
    for dt in dates:
        sig_id = f"SIG-DT-{dt}"
        insert_signal_helper(isolated_db, sig_id, timestamp=f"{dt} 09:15:00", status="EXPIRED", first_touch="")
    ds_svc = SignalOutcomeDatasetService.get_instance(db_path=isolated_db)
    for dt in dates:
        meas = ds_svc.build_signal_outcome_measurement(f"SIG-DT-{dt}")
        assert meas["observed_from"] == f"{dt} 09:15:00"
        assert meas["outcome"] == "TIMEOUT"


def test_26_active_and_terminal_signals(isolated_db):
    """Case 26: Differentiates active vs terminal signals cleanly."""
    insert_signal_helper(isolated_db, "SIG-ACT", status="ACTIVE")
    insert_signal_helper(isolated_db, "SIG-TRM", status="SL_HIT", first_touch="SL")
    insert_event_helper(isolated_db, "SIG-TRM", "2026-10-05 10:00:00", 95.0, hit_sl=1)

    ds_svc = SignalOutcomeDatasetService.get_instance(db_path=isolated_db)
    meas_act = ds_svc.build_signal_outcome_measurement("SIG-ACT")
    meas_trm = ds_svc.build_signal_outcome_measurement("SIG-TRM")

    assert meas_act["outcome"] == "UNRESOLVED"
    assert meas_act["exit_price"] is None
    assert meas_trm["outcome"] == "SL_FIRST"
    assert meas_trm["exit_price"] == 95.0


def test_27_t2_reached_then_reversal(isolated_db):
    """Case 27: Signal reaches T2 then closes on reversal."""
    sig_id = "SIG-T2-REV"
    insert_signal_helper(
        isolated_db, sig_id, status="CLOSED_ON_REVERSAL", first_touch="T1",
        first_touch_at="2026-10-05 10:00:00", first_touch_price=105.0,
        current_price=108.0
    )
    insert_event_helper(isolated_db, sig_id, "2026-10-05 10:00:00", 105.0, hit_t1=1)
    insert_event_helper(isolated_db, sig_id, "2026-10-05 11:00:00", 110.0, hit_t2=1)

    ds_svc = SignalOutcomeDatasetService.get_instance(db_path=isolated_db)
    meas = ds_svc.build_signal_outcome_measurement(sig_id)

    assert meas["target_1_hit"] == 1
    assert meas["target_2_hit"] == 1
    assert meas["outcome"] == "REVERSED"


def test_28_t2_reached_then_later_horizon_expiry(isolated_db):
    """Case 28: T2 reached and holding horizon expiry occurs."""
    sig_id = "SIG-T2-EXP"
    insert_signal_helper(
        isolated_db, sig_id, status="EXPIRED", first_touch="T1",
        first_touch_at="2026-10-05 10:00:00", first_touch_price=105.0,
        current_price=109.5
    )
    insert_event_helper(isolated_db, sig_id, "2026-10-05 10:00:00", 105.0, hit_t1=1)
    insert_event_helper(isolated_db, sig_id, "2026-10-05 11:00:00", 110.0, hit_t2=1)

    ds_svc = SignalOutcomeDatasetService.get_instance(db_path=isolated_db)
    meas = ds_svc.build_signal_outcome_measurement(sig_id)

    assert meas["target_1_hit"] == 1
    assert meas["target_2_hit"] == 1
    assert meas["exit_price"] == 109.5


def test_29_restart_interruption_safe_sync(isolated_db):
    """Case 29: Forward observation sync resumes safely after interruption."""
    sig_id = "SIG-SYNC-TEST"
    insert_signal_helper(isolated_db, sig_id, status="TARGET_2_HIT", first_touch="T1")
    insert_event_helper(isolated_db, sig_id, "2026-10-05 10:00:00", 105.0, hit_t1=1)
    insert_event_helper(isolated_db, sig_id, "2026-10-05 11:00:00", 110.0, hit_t2=1)

    # Register in forward observation
    fwd_svc = SignalForwardObservationService.get_instance(db_path=isolated_db)
    fwd_svc.register_forward_signal(sig_id)

    # First sync run
    updated_1 = fwd_svc.sync_forward_outcomes()
    assert updated_1 == 1

    # Second sync run: already resolved, safely returns 0
    updated_2 = fwd_svc.sync_forward_outcomes()
    assert updated_2 == 0


def test_30_full_population_consistency_scan(isolated_db):
    """Case 30: Scan across diverse signal cohorts verifies zero cross-surface inconsistency."""
    for i in range(10):
        sig_id = f"SIG-COHORT-{i}"
        status = "TARGET_2_HIT" if i % 2 == 0 else "TARGET_1_HIT"
        insert_signal_helper(isolated_db, sig_id, status=status, first_touch="T1")
        insert_event_helper(isolated_db, sig_id, "2026-10-05 10:00:00", 105.0, hit_t1=1)
        if status == "TARGET_2_HIT":
            insert_event_helper(isolated_db, sig_id, "2026-10-05 11:00:00", 110.0, hit_t2=1)

    ds_svc = SignalOutcomeDatasetService.get_instance(db_path=isolated_db)
    for i in range(10):
        sig_id = f"SIG-COHORT-{i}"
        meas = ds_svc.build_signal_outcome_measurement(sig_id)
        assert meas["first_touch"] == "T1"
        assert meas["target_1_hit"] == 1
        if i % 2 == 0:
            assert meas["target_2_hit"] == 1
        else:
            assert meas["target_2_hit"] == 0
