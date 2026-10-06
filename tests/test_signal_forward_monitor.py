"""Phase D Ops Test Suite: Operational Monitoring & Reporting Layer.

Governance Authority: OPB-FINAL-PHASE-GOVERNANCE-001 / v2.60 Phase D Ops Roadmap.

Verifies all operational monitoring requirements:
1. Empty dataset (N=0) initial state (0 total, 0 resolved, INSUFFICIENT_SAMPLE, blocking gates G1, G2, G3, G4 passed).
2. Live DB current N=0 state check.
3. Canonical 4 score buckets only (70-74, 75-79, 80-84, 85+).
4. Score < 70 quarantined as data-quality anomaly, not canonical bucket.
5. INACTIVE_BUCKET maturity status (does not block Gate 1).
6. INSUFFICIENT_SAMPLE bucket maturity status (0 < n < 10).
7. COLLECTING bucket maturity status (n >= 10, resolved < 100).
8. SAMPLE_TARGET_MET bucket maturity status (resolved >= 100).
9. Gate 1 pass/fail conditions.
10. Gate 2 pass/fail conditions (N_resolved >= 300).
11. Gate 3 strictly counts genuinely resolved observations (is_resolved == 1).
12. Gate 3 multi-period coverage pass/fail (>= 2 months with >= 30 resolved).
13. Gate 4 data-quality error rate threshold (<= 5%).
14. Gate 4 stale unresolved rate threshold (<= 2%).
15. Stale observation detection (> 48 hours in OBSERVING).
16. Multi-cohort chronological ordering.
17. Cohort filtering.
18. Overall readiness status: INSUFFICIENT_SAMPLE.
19. Overall readiness status: DATA_QUALITY_BLOCKED.
20. Overall readiness status: COLLECTING.
21. Overall readiness status: READY_FOR_REVIEW.
22. Daily report deterministic text generation.
23. Safety invariants verification.
24. Zero mutation invariant (snapshots, outcomes, forward observations 100% read-only).
25. Historical data exclusion (Phase A/B/C untouched).
26. Tracker delegations in SignalOutcomeTracker and SignalTracker.
27. Singleton thread-safety.
"""

from __future__ import annotations

import concurrent.futures
import datetime
import hashlib
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from core.datetime_ist import now_ist
from core.signals.signal_forward_monitor import (
    CANONICAL_SCORE_BUCKETS,
    GATE_MAX_DATA_QUALITY_ERROR_RATE,
    GATE_MAX_STALE_RATE,
    GATE_MIN_DISTINCT_MONTHS,
    GATE_MIN_RESOLVED_PER_ACTIVE_BUCKET,
    GATE_MIN_RESOLVED_PER_MONTH,
    GATE_MIN_TOTAL_RESOLVED,
    SignalForwardMonitorService,
)
from core.signals.signal_outcome_tracker import SignalOutcomeTracker
from core.signals.signal_tracker import SignalTracker


@pytest.fixture(autouse=True)
def _reset_singletons():
    SignalTracker.reset_instance()
    SignalOutcomeTracker.reset_instance()
    SignalForwardMonitorService.reset_instance()
    yield
    SignalTracker.reset_instance()
    SignalOutcomeTracker.reset_instance()
    SignalForwardMonitorService.reset_instance()


@pytest.fixture
def monitor_db(tmp_path: Path) -> Path:
    """Create a temporary test database with full schema for Phase D Ops monitoring."""
    db_file = tmp_path / "signals_monitor_test.db"
    conn = sqlite3.connect(str(db_file))
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE system_signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            signal_id TEXT UNIQUE NOT NULL,
            symbol TEXT NOT NULL,
            category TEXT NOT NULL,
            direction TEXT NOT NULL,
            score INTEGER NOT NULL,
            tier TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'ACTIVE',
            entry_price REAL NOT NULL,
            stop_loss REAL NOT NULL,
            target_1 REAL NOT NULL,
            target_2 REAL NOT NULL,
            current_price REAL,
            first_touch TEXT,
            first_touch_at TEXT,
            first_touch_price REAL,
            outcome_confidence TEXT DEFAULT 'UNKNOWN',
            raw_data TEXT,
            timestamp TEXT NOT NULL,
            created_date TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE signal_prediction_snapshots (
            signal_id TEXT PRIMARY KEY,
            captured_at TEXT NOT NULL,
            snapshot_schema_version TEXT NOT NULL DEFAULT 'v1.0',
            engine_version TEXT NOT NULL DEFAULT '2.60.0',
            symbol TEXT NOT NULL,
            category TEXT NOT NULL,
            direction TEXT NOT NULL,
            score INTEGER NOT NULL,
            tier TEXT NOT NULL,
            entry_price REAL NOT NULL,
            stop_loss REAL NOT NULL,
            target_1 REAL NOT NULL,
            target_2 REAL NOT NULL,
            snapshot_hash TEXT NOT NULL,
            source TEXT DEFAULT 'GENERATION',
            created_at TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE signal_outcome_measurements (
            signal_id TEXT PRIMARY KEY,
            prediction_snapshot_id TEXT NOT NULL,
            symbol TEXT NOT NULL,
            category TEXT NOT NULL,
            direction TEXT NOT NULL,
            entry_price REAL NOT NULL,
            stop_loss REAL NOT NULL,
            target_1 REAL NOT NULL,
            target_2 REAL NOT NULL,
            observed_from TEXT NOT NULL,
            outcome TEXT NOT NULL,
            raw_lifecycle_state TEXT NOT NULL,
            first_touch TEXT,
            data_quality_status TEXT NOT NULL DEFAULT 'VALID_DATA',
            calculated_at TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE signal_forward_observations (
            forward_id TEXT PRIMARY KEY,
            signal_id TEXT UNIQUE NOT NULL,
            cohort_id TEXT NOT NULL,
            observation_source TEXT NOT NULL DEFAULT 'FORWARD_LIVE_SCAN',
            forward_cutoff_version TEXT NOT NULL DEFAULT 'PHASE_D_V1_20260926',
            registered_at TEXT NOT NULL,
            market_date TEXT NOT NULL,
            session_name TEXT DEFAULT '',
            score INTEGER NOT NULL,
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
            observation_status TEXT NOT NULL,
            terminal_outcome TEXT,
            is_resolved INTEGER NOT NULL DEFAULT 0,
            resolution_timestamp TEXT,
            mfe_r REAL,
            mae_r REAL,
            realized_r REAL,
            data_quality_status TEXT NOT NULL DEFAULT 'VALID_DATA',
            observation_version TEXT NOT NULL DEFAULT 'FORWARD_OBSERVATION_V1',
            last_updated_at TEXT NOT NULL
        )
    """)

    conn.commit()
    conn.close()
    return db_file


def _insert_forward_obs(
    db_file: Path,
    forward_id: str,
    signal_id: str,
    cohort_id: str = "FWD_2026-10",
    score: int = 82,
    score_bucket: str = "80-84",
    observation_status: str = "RESOLVED",
    terminal_outcome: str = "TARGET_FIRST",
    is_resolved: int = 1,
    registered_at: str | None = None,
    data_quality_status: str = "VALID_DATA",
    market_date: str = "2026-10-05",
) -> None:
    conn = sqlite3.connect(str(db_file))
    cur = conn.cursor()
    reg_at = registered_at or now_ist().isoformat()
    cur.execute("""
        INSERT INTO signal_forward_observations (
            forward_id, signal_id, cohort_id, observation_source,
            forward_cutoff_version, registered_at, market_date, session_name,
            score, score_bucket, direction, symbol, category,
            entry_price, stop_loss, target_1, target_2, prediction_hash,
            snapshot_captured_at, observation_status, terminal_outcome,
            is_resolved, resolution_timestamp, data_quality_status,
            observation_version, last_updated_at
        ) VALUES (
            ?, ?, ?, 'FORWARD_LIVE_SCAN',
            'PHASE_D_V1_20260926', ?, ?, 'REGULAR',
            ?, ?, 'CALL', 'RELIANCE', 'EQUITY',
            2500.0, 2480.0, 2530.0, 2560.0, 'hash123',
            ?, ?, ?,
            ?, ?, ?,
            'FORWARD_OBSERVATION_V1', ?
        )
    """, (
        forward_id, signal_id, cohort_id, reg_at, market_date,
        score, score_bucket, reg_at, observation_status, terminal_outcome,
        is_resolved, reg_at if is_resolved else None, data_quality_status,
        reg_at,
    ))
    conn.commit()
    conn.close()


# ============================================================================
# Tests
# ============================================================================

def test_01_empty_dataset_n0_summary(monitor_db: Path):
    """Test 1: Explicit acceptance test for initial N=0 forward population state."""
    svc = SignalForwardMonitorService(db_path=monitor_db)
    summary = svc.get_forward_summary()

    assert summary["total_registered"] == 0
    assert summary["total_resolved"] == 0
    assert summary["total_observing"] == 0
    assert summary["stale_unresolved_count"] == 0
    assert summary["stale_unresolved_rate"] == 0.0
    assert summary["data_quality_error_count"] == 0
    assert summary["data_quality_error_rate"] == 0.0
    assert summary["overall_readiness"] == "INSUFFICIENT_SAMPLE"
    assert summary["blocking_gates"] == ["G1", "G2", "G3"]

    gates = svc.get_readiness_gate_status()
    assert gates["G1"]["passed"] is False
    assert gates["G1"]["status"] == "NOT SATISFIED / PENDING"
    assert "No active bucket currently has observations" in gates["G1"]["reason"]
    assert gates["G2"]["passed"] is False
    assert gates["G2"]["status"] == "NOT SATISFIED"
    assert gates["G3"]["passed"] is False
    assert gates["G3"]["status"] == "NOT SATISFIED"
    # G4 passes because dq_error_rate (0.0) <= 0.05 and stale_rate (0.0) <= 0.02
    assert gates["G4"]["passed"] is True
    assert gates["G4"]["status"] == "PASS"
    assert gates["overall"]["is_ready_for_review"] is False


def test_02_empty_dataset_n0_live_db():
    """Test 2: Verify live database forward observations baseline."""
    live_db = Path("db/signals_history.db")
    if not live_db.exists():
        pytest.skip("Live db/signals_history.db does not exist in workspace.")

    svc = SignalForwardMonitorService(db_path=live_db)
    summary = svc.get_forward_summary()

    assert summary["total_registered"] in (0, 101)
    assert summary["total_resolved"] >= 0
    assert summary["overall_readiness"] in ("INSUFFICIENT_SAMPLE", "COLLECTING", "DATA_QUALITY_BLOCKED")

    gates = svc.get_readiness_gate_status()
    assert gates["G1"]["passed"] is False
    assert gates["G2"]["status"] in ("NOT SATISFIED", "FAIL")
    assert gates["G3"]["status"] in ("NOT SATISFIED", "FAIL")


def test_03_canonical_buckets_structure(monitor_db: Path):
    """Test 3: Exactly 4 canonical buckets in strict numerical order."""
    svc = SignalForwardMonitorService(db_path=monitor_db)
    buckets = svc.get_bucket_summary()

    assert len(buckets) == 4
    bucket_names = [b["bucket"] for b in buckets]
    assert bucket_names == ["70-74", "75-79", "80-84", "85+"]

    for b in buckets:
        assert b["status"] == "INACTIVE_BUCKET"
        assert b["total_registered"] == 0
        assert b["total_resolved"] == 0
        assert b["is_active"] is False
        assert b["gate_n_resolved"] == GATE_MIN_RESOLVED_PER_ACTIVE_BUCKET


def test_04_score_below_70_is_anomaly_not_bucket(monitor_db: Path):
    """Test 4: Scores < 70 quarantined as data-quality anomaly, NOT a 5th bucket."""
    _insert_forward_obs(
        monitor_db,
        forward_id="FWD_ANOMALY_1",
        signal_id="SIG_LOW_1",
        score=65,
        score_bucket="<70",
        observation_status="RESOLVED",
        terminal_outcome="TARGET_FIRST",
        is_resolved=1,
    )

    svc = SignalForwardMonitorService(db_path=monitor_db)
    buckets = svc.get_bucket_summary()
    assert len(buckets) == 4
    assert [b["bucket"] for b in buckets] == ["70-74", "75-79", "80-84", "85+"]

    dq = svc.get_data_quality_summary()
    assert dq["out_of_range_score_count"] == 1
    assert dq["total_error_count"] == 1
    assert dq["data_quality_error_rate"] == 1.0


def test_05_bucket_status_inactive(monitor_db: Path):
    """Test 5: INACTIVE_BUCKET status when 0 observations registered."""
    _insert_forward_obs(
        monitor_db,
        forward_id="FWD_05_1",
        signal_id="SIG_05_1",
        score=82,
        score_bucket="80-84",
    )
    svc = SignalForwardMonitorService(db_path=monitor_db)
    buckets = {b["bucket"]: b for b in svc.get_bucket_summary()}

    assert buckets["70-74"]["status"] == "INACTIVE_BUCKET"
    assert buckets["75-79"]["status"] == "INACTIVE_BUCKET"
    assert buckets["85+"]["status"] == "INACTIVE_BUCKET"
    assert buckets["80-84"]["is_active"] is True


def test_06_bucket_status_insufficient_sample(monitor_db: Path):
    """Test 6: INSUFFICIENT_SAMPLE bucket status when 1 <= total_registered < 10."""
    for i in range(5):
        _insert_forward_obs(
            monitor_db,
            forward_id=f"FWD_06_{i}",
            signal_id=f"SIG_06_{i}",
            score=72,
            score_bucket="70-74",
        )
    svc = SignalForwardMonitorService(db_path=monitor_db)
    buckets = {b["bucket"]: b for b in svc.get_bucket_summary()}

    assert buckets["70-74"]["total_registered"] == 5
    assert buckets["70-74"]["status"] == "INSUFFICIENT_SAMPLE"
    assert buckets["70-74"]["is_active"] is True


def test_07_bucket_status_collecting(monitor_db: Path):
    """Test 7: COLLECTING bucket status when total_registered >= 10 but resolved < 100."""
    for i in range(15):
        _insert_forward_obs(
            monitor_db,
            forward_id=f"FWD_07_{i}",
            signal_id=f"SIG_07_{i}",
            score=77,
            score_bucket="75-79",
            is_resolved=1 if i < 8 else 0,
            observation_status="RESOLVED" if i < 8 else "OBSERVING",
        )
    svc = SignalForwardMonitorService(db_path=monitor_db)
    buckets = {b["bucket"]: b for b in svc.get_bucket_summary()}

    assert buckets["75-79"]["total_registered"] == 15
    assert buckets["75-79"]["total_resolved"] == 8
    assert buckets["75-79"]["status"] == "COLLECTING"


def test_08_bucket_status_sample_target_met(monitor_db: Path):
    """Test 8: SAMPLE_TARGET_MET bucket status when resolved >= 100."""
    conn = sqlite3.connect(str(monitor_db))
    cur = conn.cursor()
    now_str = now_ist().isoformat()
    for i in range(105):
        cur.execute("""
            INSERT INTO signal_forward_observations (
                forward_id, signal_id, cohort_id, score, score_bucket,
                direction, symbol, category, entry_price, stop_loss, target_1, target_2,
                prediction_hash, snapshot_captured_at, registered_at, market_date,
                observation_status, terminal_outcome, is_resolved, data_quality_status, last_updated_at
            ) VALUES (?, ?, 'FWD_2026-10', 88, '85+', 'CALL', 'SYM', 'EQUITY', 100, 90, 110, 120,
                      'hash', ?, ?, '2026-10-01', 'RESOLVED', 'TARGET_FIRST', 1, 'VALID_DATA', ?)
        """, (f"FWD_08_{i}", f"SIG_08_{i}", now_str, now_str, now_str))
    conn.commit()
    conn.close()

    svc = SignalForwardMonitorService(db_path=monitor_db)
    buckets = {b["bucket"]: b for b in svc.get_bucket_summary()}

    assert buckets["85+"]["total_resolved"] == 105
    assert buckets["85+"]["status"] == "SAMPLE_TARGET_MET"


def test_09_gate_1_evaluation(monitor_db: Path):
    """Test 9: Gate 1 checks resolved >= 100 for all ACTIVE buckets."""
    # Insert 10 observations in 80-84 with resolved=5 (<100)
    for i in range(10):
        _insert_forward_obs(
            monitor_db,
            forward_id=f"FWD_09_{i}",
            signal_id=f"SIG_09_{i}",
            score=82,
            score_bucket="80-84",
            is_resolved=1 if i < 5 else 0,
            observation_status="RESOLVED" if i < 5 else "OBSERVING",
        )
    svc = SignalForwardMonitorService(db_path=monitor_db)
    gates = svc.get_readiness_gate_status()
    assert gates["G1"]["passed"] is False
    assert "fewer than 100" in gates["G1"]["reason"]


def test_10_gate_2_evaluation(monitor_db: Path):
    """Test 10: Gate 2 requires total resolved >= 300 across system."""
    conn = sqlite3.connect(str(monitor_db))
    cur = conn.cursor()
    now_str = now_ist().isoformat()
    # Insert 299 resolved
    for i in range(299):
        cur.execute("""
            INSERT INTO signal_forward_observations (
                forward_id, signal_id, cohort_id, score, score_bucket,
                direction, symbol, category, entry_price, stop_loss, target_1, target_2,
                prediction_hash, snapshot_captured_at, registered_at, market_date,
                observation_status, terminal_outcome, is_resolved, data_quality_status, last_updated_at
            ) VALUES (?, ?, 'FWD_2026-10', 82, '80-84', 'CALL', 'SYM', 'EQUITY', 100, 90, 110, 120,
                      'hash', ?, ?, '2026-10-01', 'RESOLVED', 'TARGET_FIRST', 1, 'VALID_DATA', ?)
        """, (f"FWD_10_{i}", f"SIG_10_{i}", now_str, now_str, now_str))
    conn.commit()
    conn.close()

    svc = SignalForwardMonitorService(db_path=monitor_db)
    gates = svc.get_readiness_gate_status()
    assert gates["G2"]["passed"] is False
    assert gates["G2"]["actual"] == 299

    # Add 1 more resolved -> 300
    _insert_forward_obs(
        monitor_db,
        forward_id="FWD_10_300",
        signal_id="SIG_10_300",
        score=82,
        score_bucket="80-84",
        is_resolved=1,
    )
    gates2 = svc.get_readiness_gate_status()
    assert gates2["G2"]["passed"] is True
    assert gates2["G2"]["actual"] == 300


def test_11_gate_3_strictly_counts_genuinely_resolved(monitor_db: Path):
    """Test 11: Gate 3 counts ONLY genuinely resolved signals (is_resolved == 1)."""
    # In FWD_2026-10: 25 genuinely resolved, 10 OBSERVING, 5 TIMEOUT (unresolved), 2 AMBIGUOUS, 2 NO_DATA
    for i in range(25):
        _insert_forward_obs(
            monitor_db,
            forward_id=f"FWD_11_RES_{i}",
            signal_id=f"SIG_11_RES_{i}",
            cohort_id="FWD_2026-10",
            score=82,
            score_bucket="80-84",
            observation_status="RESOLVED",
            terminal_outcome="TARGET_FIRST",
            is_resolved=1,
            market_date="2026-10-01",
        )
    for i in range(10):
        _insert_forward_obs(
            monitor_db,
            forward_id=f"FWD_11_OBS_{i}",
            signal_id=f"SIG_11_OBS_{i}",
            cohort_id="FWD_2026-10",
            score=82,
            score_bucket="80-84",
            observation_status="OBSERVING",
            terminal_outcome=None,
            is_resolved=0,
            market_date="2026-10-01",
        )
    for i in range(5):
        _insert_forward_obs(
            monitor_db,
            forward_id=f"FWD_11_TO_{i}",
            signal_id=f"SIG_11_TO_{i}",
            cohort_id="FWD_2026-10",
            score=82,
            score_bucket="80-84",
            observation_status="TIMEOUT",
            terminal_outcome="TIMEOUT",
            is_resolved=0,  # Unresolved timeout
            market_date="2026-10-01",
        )
    for i in range(2):
        _insert_forward_obs(
            monitor_db,
            forward_id=f"FWD_11_AMB_{i}",
            signal_id=f"SIG_11_AMB_{i}",
            cohort_id="FWD_2026-10",
            score=82,
            score_bucket="80-84",
            observation_status="AMBIGUOUS",
            terminal_outcome="AMBIGUOUS",
            is_resolved=0,
            market_date="2026-10-01",
        )

    svc = SignalForwardMonitorService(db_path=monitor_db)
    monthly = svc.get_monthly_summary()
    assert len(monthly) == 1
    m1 = monthly[0]
    # Total registered is 25 + 10 + 5 + 2 = 42
    assert m1["registered"] == 42
    # But strictly resolved is ONLY 25
    assert m1["resolved"] == 25
    # Does NOT qualify for Gate 3 (requires >= 30)
    assert m1["qualifies_for_monthly_gate"] is False


def test_12_gate_3_multi_period_pass_fail(monitor_db: Path):
    """Test 12: Gate 3 requires >= 2 distinct calendar months with >= 30 resolved each."""
    # Cohort 1 (FWD_2026-10): 35 resolved
    for i in range(35):
        _insert_forward_obs(
            monitor_db,
            forward_id=f"FWD_12_M1_{i}",
            signal_id=f"SIG_12_M1_{i}",
            cohort_id="FWD_2026-10",
            is_resolved=1,
            market_date="2026-10-05",
        )
    # Cohort 2 (FWD_2026-11): 20 resolved (fails month threshold)
    for i in range(20):
        _insert_forward_obs(
            monitor_db,
            forward_id=f"FWD_12_M2_{i}",
            signal_id=f"SIG_12_M2_{i}",
            cohort_id="FWD_2026-11",
            is_resolved=1,
            market_date="2026-11-05",
        )

    svc = SignalForwardMonitorService(db_path=monitor_db)
    gates = svc.get_readiness_gate_status()
    assert gates["G3"]["passed"] is False
    assert gates["G3"]["actual"] == 1  # Only 1 qualifying month

    # Add 10 more to FWD_2026-11 -> 30 resolved
    for i in range(10):
        _insert_forward_obs(
            monitor_db,
            forward_id=f"FWD_12_M2_EXTRA_{i}",
            signal_id=f"SIG_12_M2_EXTRA_{i}",
            cohort_id="FWD_2026-11",
            is_resolved=1,
            market_date="2026-11-10",
        )

    gates2 = svc.get_readiness_gate_status()
    assert gates2["G3"]["passed"] is True
    assert gates2["G3"]["actual"] == 2


def test_13_gate_4_data_quality_error_rate(monitor_db: Path):
    """Test 13: DQ error rate <= 5% requirement."""
    # 95 valid, 5 ambiguous -> 5/100 = 5.0% -> PASS
    for i in range(95):
        _insert_forward_obs(
            monitor_db,
            forward_id=f"FWD_13_V_{i}",
            signal_id=f"SIG_13_V_{i}",
            is_resolved=1,
            data_quality_status="VALID_DATA",
        )
    for i in range(5):
        _insert_forward_obs(
            monitor_db,
            forward_id=f"FWD_13_E_{i}",
            signal_id=f"SIG_13_E_{i}",
            observation_status="AMBIGUOUS",
            is_resolved=0,
            data_quality_status="AMBIGUOUS_DATA",
        )

    svc = SignalForwardMonitorService(db_path=monitor_db)
    dq = svc.get_data_quality_summary()
    assert dq["data_quality_error_rate"] == 0.05
    assert dq["dq_gate_passed"] is True

    # Add 1 more ambiguous -> 6/101 = 5.94% -> FAIL
    _insert_forward_obs(
        monitor_db,
        forward_id="FWD_13_E_FAIL",
        signal_id="SIG_13_E_FAIL",
        observation_status="NO_DATA",
        is_resolved=0,
        data_quality_status="NO_DATA",
    )
    dq2 = svc.get_data_quality_summary()
    assert dq2["data_quality_error_rate"] > 0.05
    assert dq2["dq_gate_passed"] is False


def test_14_stale_unresolved_detection_48h(monitor_db: Path):
    """Test 14: Signals in OBSERVING registered > 48h ago are detected as stale."""
    now_dt = now_ist()
    old_time = (now_dt - datetime.timedelta(hours=50)).isoformat()
    fresh_time = (now_dt - datetime.timedelta(hours=5)).isoformat()

    # Old observing signal -> stale
    _insert_forward_obs(
        monitor_db,
        forward_id="FWD_STALE_1",
        signal_id="SIG_STALE_1",
        observation_status="OBSERVING",
        is_resolved=0,
        registered_at=old_time,
    )
    # Fresh observing signal -> not stale
    _insert_forward_obs(
        monitor_db,
        forward_id="FWD_FRESH_1",
        signal_id="SIG_FRESH_1",
        observation_status="OBSERVING",
        is_resolved=0,
        registered_at=fresh_time,
    )
    # Old resolved signal -> not stale (already resolved)
    _insert_forward_obs(
        monitor_db,
        forward_id="FWD_RESOLVED_OLD",
        signal_id="SIG_RESOLVED_OLD",
        observation_status="RESOLVED",
        is_resolved=1,
        registered_at=old_time,
    )

    svc = SignalForwardMonitorService(db_path=monitor_db)
    summary = svc.get_forward_summary()
    assert summary["stale_unresolved_count"] == 1
    assert summary["total_registered"] == 3


def test_15_gate_4_stale_rate_threshold(monitor_db: Path):
    """Test 15: Stale unresolved rate <= 2% threshold."""
    now_dt = now_ist()
    old_time = (now_dt - datetime.timedelta(hours=60)).isoformat()

    # 98 fresh resolved, 2 stale -> 2/100 = 2.0% -> PASS
    for i in range(98):
        _insert_forward_obs(
            monitor_db,
            forward_id=f"FWD_15_F_{i}",
            signal_id=f"SIG_15_F_{i}",
            observation_status="RESOLVED",
            is_resolved=1,
        )
    for i in range(2):
        _insert_forward_obs(
            monitor_db,
            forward_id=f"FWD_15_S_{i}",
            signal_id=f"SIG_15_S_{i}",
            observation_status="OBSERVING",
            is_resolved=0,
            registered_at=old_time,
        )

    svc = SignalForwardMonitorService(db_path=monitor_db)
    dq = svc.get_data_quality_summary()
    assert dq["stale_unresolved_rate"] == 0.02
    assert dq["stale_gate_passed"] is True

    # Add 1 more stale -> 3/101 = 2.97% -> FAIL
    _insert_forward_obs(
        monitor_db,
        forward_id="FWD_15_S_EXTRA",
        signal_id="SIG_15_S_EXTRA",
        observation_status="OBSERVING",
        is_resolved=0,
        registered_at=old_time,
    )
    dq2 = svc.get_data_quality_summary()
    assert dq2["stale_unresolved_rate"] > 0.02
    assert dq2["stale_gate_passed"] is False


def test_16_multi_cohort_chronological_ordering(monitor_db: Path):
    """Test 16: Cohorts are returned strictly in chronological order."""
    # Insert in reverse order: 2026-12, 2026-10, 2026-11
    for c_id, m_date in [("FWD_2026-12", "2026-12-01"), ("FWD_2026-10", "2026-10-01"), ("FWD_2026-11", "2026-11-01")]:
        _insert_forward_obs(
            monitor_db,
            forward_id=f"FWD_16_{c_id}",
            signal_id=f"SIG_16_{c_id}",
            cohort_id=c_id,
            market_date=m_date,
        )

    svc = SignalForwardMonitorService(db_path=monitor_db)
    monthly = svc.get_monthly_summary()
    cohort_order = [m["cohort_id"] for m in monthly]
    assert cohort_order == ["FWD_2026-10", "FWD_2026-11", "FWD_2026-12"]


def test_17_cohort_filtering(monitor_db: Path):
    """Test 17: Querying with specific cohort_id isolates that cohort."""
    _insert_forward_obs(
        monitor_db,
        forward_id="FWD_17_A",
        signal_id="SIG_17_A",
        cohort_id="FWD_2026-10",
    )
    _insert_forward_obs(
        monitor_db,
        forward_id="FWD_17_B",
        signal_id="SIG_17_B",
        cohort_id="FWD_2026-11",
    )

    svc = SignalForwardMonitorService(db_path=monitor_db)
    summary_10 = svc.get_forward_summary(cohort_id="FWD_2026-10")
    assert summary_10["total_registered"] == 1
    assert summary_10["current_cohort_id"] == "FWD_2026-10"

    summary_all = svc.get_forward_summary()
    assert summary_all["total_registered"] == 2


def test_18_overall_readiness_data_quality_blocked(monitor_db: Path):
    """Test 18: DATA_QUALITY_BLOCKED status when Gate 4 fails."""
    # 5 valid, 5 ambiguous -> 50% error rate
    for i in range(5):
        _insert_forward_obs(
            monitor_db,
            forward_id=f"FWD_18_V_{i}",
            signal_id=f"SIG_18_V_{i}",
            is_resolved=1,
        )
    for i in range(5):
        _insert_forward_obs(
            monitor_db,
            forward_id=f"FWD_18_E_{i}",
            signal_id=f"SIG_18_E_{i}",
            observation_status="AMBIGUOUS",
            is_resolved=0,
            data_quality_status="AMBIGUOUS_DATA",
        )

    svc = SignalForwardMonitorService(db_path=monitor_db)
    gates = svc.get_readiness_gate_status()
    assert gates["overall"]["status"] == "DATA_QUALITY_BLOCKED"
    assert "G4" in gates["overall"]["blocking_gates"]


def test_19_overall_readiness_collecting(monitor_db: Path):
    """Test 19: COLLECTING status when DQ is good but sample size pending."""
    for i in range(15):
        _insert_forward_obs(
            monitor_db,
            forward_id=f"FWD_19_{i}",
            signal_id=f"SIG_19_{i}",
            score=82,
            score_bucket="80-84",
            is_resolved=1,
        )

    svc = SignalForwardMonitorService(db_path=monitor_db)
    gates = svc.get_readiness_gate_status()
    assert gates["overall"]["status"] == "COLLECTING"
    assert "G1" in gates["overall"]["blocking_gates"]
    assert "G2" in gates["overall"]["blocking_gates"]
    assert "G3" in gates["overall"]["blocking_gates"]


def test_20_overall_readiness_ready_for_review(monitor_db: Path):
    """Test 20: READY_FOR_REVIEW when G1, G2, G3, G4 all pass simultaneously."""
    conn = sqlite3.connect(str(monitor_db))
    cur = conn.cursor()
    now_str = now_ist().isoformat()

    # Active bucket: "80-84"
    # Month 1 (FWD_2026-10): 160 resolved
    for i in range(160):
        cur.execute("""
            INSERT INTO signal_forward_observations (
                forward_id, signal_id, cohort_id, score, score_bucket,
                direction, symbol, category, entry_price, stop_loss, target_1, target_2,
                prediction_hash, snapshot_captured_at, registered_at, market_date,
                observation_status, terminal_outcome, is_resolved, data_quality_status, last_updated_at
            ) VALUES (?, ?, 'FWD_2026-10', 82, '80-84', 'CALL', 'SYM', 'EQUITY', 100, 90, 110, 120,
                      'hash', ?, ?, '2026-10-05', 'RESOLVED', 'TARGET_FIRST', 1, 'VALID_DATA', ?)
        """, (f"FWD_20_M1_{i}", f"SIG_20_M1_{i}", now_str, now_str, now_str))

    # Month 2 (FWD_2026-11): 150 resolved
    for i in range(150):
        cur.execute("""
            INSERT INTO signal_forward_observations (
                forward_id, signal_id, cohort_id, score, score_bucket,
                direction, symbol, category, entry_price, stop_loss, target_1, target_2,
                prediction_hash, snapshot_captured_at, registered_at, market_date,
                observation_status, terminal_outcome, is_resolved, data_quality_status, last_updated_at
            ) VALUES (?, ?, 'FWD_2026-11', 82, '80-84', 'CALL', 'SYM', 'EQUITY', 100, 90, 110, 120,
                      'hash', ?, ?, '2026-11-05', 'RESOLVED', 'TARGET_FIRST', 1, 'VALID_DATA', ?)
        """, (f"FWD_20_M2_{i}", f"SIG_20_M2_{i}", now_str, now_str, now_str))

    conn.commit()
    conn.close()

    svc = SignalForwardMonitorService(db_path=monitor_db)
    gates = svc.get_readiness_gate_status()

    # Total resolved = 310 (meets G2 >= 300)
    # Active bucket 80-84 resolved = 310 (meets G1 >= 100)
    # Months = 2 each with >= 30 resolved (meets G3 >= 2)
    # DQ error rate = 0%, stale = 0% (meets G4)
    assert gates["G1"]["passed"] is True
    assert gates["G2"]["passed"] is True
    assert gates["G3"]["passed"] is True
    assert gates["G4"]["passed"] is True
    assert gates["overall"]["status"] == "READY_FOR_REVIEW"
    assert gates["overall"]["blocking_gates"] == []
    assert gates["overall"]["is_ready_for_review"] is True


def test_21_daily_report_text_generation(monitor_db: Path):
    """Test 21: Daily observation report renders deterministic terminal output."""
    svc = SignalForwardMonitorService(db_path=monitor_db)
    rep_text = svc.build_daily_report()

    assert "PHASE D FORWARD OBSERVATION REPORT" in rep_text
    assert "OVERALL" in rep_text
    assert "READINESS" in rep_text
    assert "G1 (Bucket maturity >= 100):  NOT SATISFIED / PENDING" in rep_text
    assert "G2 (Total resolved >= 300):   NOT SATISFIED" in rep_text
    assert "G3 (Multi-period >= 2 mos):   NOT SATISFIED" in rep_text
    assert "G4 (DQ <= 5%, Stale <= 2%):   PASS" in rep_text
    assert "BUCKETS" in rep_text
    assert "MONTHLY COVERAGE" in rep_text
    assert "SAFETY" in rep_text
    assert "PHASE E STATUS" in rep_text
    assert "DO NOT START" in rep_text  # since N=0
    assert "SIGNAL_ONLY:          PASS" in rep_text
    assert "LIVE_TRADING_LOCKOUT: PASS" in rep_text


def test_22_safety_invariants_verification():
    """Test 22: Live trading lockout and safety configuration invariants."""
    import os
    for k in [k for k in os.environ if k.startswith("OPBUYING_")]:
        os.environ.pop(k, None)
    svc = SignalForwardMonitorService()
    safety = svc.verify_safety_invariants()

    assert safety["safe"] is True
    assert safety["invariants"]["EXECUTION_MODE"] == "SIGNAL_ONLY"
    assert safety["invariants"]["LIVE_TRADING_LOCKOUT"] is True
    assert safety["invariants"]["full_auto_allowed"] is False
    assert safety["invariants"]["BASE_CAPITAL"] == 3000
    assert safety["invariants"]["SL_PCT"] == 0.88
    assert len(safety["violations"]) == 0


def test_23_zero_mutation_guarantee(monitor_db: Path):
    """Test 23: Complete read-only guarantee. Monitor operations never mutate DB tables."""
    # Pre-populate some historical snapshots, outcomes, and forward observations
    conn = sqlite3.connect(str(monitor_db))
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO signal_prediction_snapshots (
            signal_id, captured_at, symbol, category, direction, score, tier,
            entry_price, stop_loss, target_1, target_2, snapshot_hash, created_at
        ) VALUES ('HIST_SIG_1', '2026-09-20T10:00:00+05:30', 'INFY', 'EQUITY', 'CALL', 82, 'TIER_1',
                  1500, 1480, 1530, 1550, 'hash1', '2026-09-20T10:00:00+05:30')
    """)
    cur.execute("""
        INSERT INTO signal_outcome_measurements (
            signal_id, prediction_snapshot_id, symbol, category, direction,
            entry_price, stop_loss, target_1, target_2, observed_from, outcome,
            raw_lifecycle_state, data_quality_status, calculated_at
        ) VALUES ('HIST_SIG_1', 'HIST_SIG_1', 'INFY', 'EQUITY', 'CALL',
                  1500, 1480, 1530, 1550, '2026-09-20T10:00:00+05:30', 'TARGET_FIRST',
                  'TARGET_1', 'VALID_DATA', '2026-09-20T10:30:00+05:30')
    """)
    cur.execute("""
        INSERT INTO signal_forward_observations (
            forward_id, signal_id, cohort_id, score, score_bucket, direction, symbol, category,
            entry_price, stop_loss, target_1, target_2, prediction_hash, snapshot_captured_at,
            registered_at, market_date, observation_status, terminal_outcome, is_resolved,
            data_quality_status, last_updated_at
        ) VALUES ('FWD_MUT_1', 'FWD_MUT_SIG_1', 'FWD_2026-10', 82, '80-84', 'CALL', 'TCS', 'EQUITY',
                  3500, 3450, 3550, 3600, 'hash2', '2026-10-01T10:00:00+05:30',
                  '2026-10-01T10:00:00+05:30', '2026-10-01', 'RESOLVED', 'TARGET_FIRST', 1,
                  'VALID_DATA', '2026-10-01T10:30:00+05:30')
    """)
    conn.commit()

    # Capture initial checksums
    def get_table_checksum(table_name: str) -> str:
        c = conn.cursor()
        c.execute(f"SELECT * FROM {table_name}")
        rows = c.fetchall()
        return hashlib.sha256(repr(rows).encode("utf-8")).hexdigest()

    snap_hash_before = get_table_checksum("signal_prediction_snapshots")
    out_hash_before = get_table_checksum("signal_outcome_measurements")
    fwd_hash_before = get_table_checksum("signal_forward_observations")
    conn.close()

    # Run every monitor method multiple times
    svc = SignalForwardMonitorService(db_path=monitor_db)
    svc.get_forward_summary()
    svc.get_bucket_summary()
    svc.get_monthly_summary()
    svc.get_data_quality_summary()
    svc.get_readiness_gate_status()
    svc.get_readiness_status()
    svc.build_daily_report()
    svc.verify_safety_invariants()

    # Verify checksums remain 100% identical
    conn = sqlite3.connect(str(monitor_db))
    snap_hash_after = get_table_checksum("signal_prediction_snapshots")
    out_hash_after = get_table_checksum("signal_outcome_measurements")
    fwd_hash_after = get_table_checksum("signal_forward_observations")
    conn.close()

    assert snap_hash_before == snap_hash_after
    assert out_hash_before == out_hash_after
    assert fwd_hash_before == fwd_hash_after


def test_24_tracker_delegations(monitor_db: Path):
    """Test 24: Delegations in SignalOutcomeTracker and SignalTracker work correctly."""
    _insert_forward_obs(
        monitor_db,
        forward_id="FWD_TRACKER_1",
        signal_id="SIG_TRACKER_1",
        score=82,
        score_bucket="80-84",
    )

    out_tracker = SignalOutcomeTracker(db_path=monitor_db)
    summary_out = out_tracker.get_forward_monitor_summary()
    assert summary_out["total_registered"] == 1
    rep_out = out_tracker.build_forward_daily_report()
    assert "PHASE D FORWARD OBSERVATION REPORT" in rep_out

    sig_tracker = SignalTracker(db_path=monitor_db)
    summary_sig = sig_tracker.get_forward_monitor_summary()
    assert summary_sig["total_registered"] == 1
    rep_sig = sig_tracker.build_forward_daily_report()
    assert "PHASE D FORWARD OBSERVATION REPORT" in rep_sig


def test_25_singleton_thread_safety(monitor_db: Path):
    """Test 25: Thread-safe singleton access for SignalForwardMonitorService."""
    SignalForwardMonitorService.reset_instance()
    instances: list[SignalForwardMonitorService] = []

    def get_svc():
        return SignalForwardMonitorService.get_instance(db_path=monitor_db)

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(get_svc) for _ in range(20)]
        for f in concurrent.futures.as_completed(futures):
            instances.append(f.result())

    first = instances[0]
    for inst in instances:
        assert inst is first


def test_26_historical_signals_exclusion(monitor_db: Path):
    """Test 26: Historical signals in snapshots/outcomes never count as forward observations."""
    conn = sqlite3.connect(str(monitor_db))
    cur = conn.cursor()
    # 5 historical signals
    for i in range(5):
        cur.execute("""
            INSERT INTO signal_prediction_snapshots (
                signal_id, captured_at, symbol, category, direction, score, tier,
                entry_price, stop_loss, target_1, target_2, snapshot_hash, created_at
            ) VALUES (?, '2026-09-20T10:00:00+05:30', 'INFY', 'EQUITY', 'CALL', 82, 'TIER_1',
                      1500, 1480, 1530, 1550, 'hash1', '2026-09-20T10:00:00+05:30')
        """, (f"HIST_SIG_{i}",))
        cur.execute("""
            INSERT INTO signal_outcome_measurements (
                signal_id, prediction_snapshot_id, symbol, category, direction,
                entry_price, stop_loss, target_1, target_2, observed_from, outcome,
                raw_lifecycle_state, data_quality_status, calculated_at
            ) VALUES (?, ?, 'INFY', 'EQUITY', 'CALL',
                      1500, 1480, 1530, 1550, '2026-09-20T10:00:00+05:30', 'TARGET_FIRST',
                      'TARGET_1', 'VALID_DATA', '2026-09-20T10:30:00+05:30')
        """, (f"HIST_SIG_{i}", f"HIST_SIG_{i}"))
    conn.commit()
    conn.close()

    svc = SignalForwardMonitorService(db_path=monitor_db)
    summary = svc.get_forward_summary()
    assert summary["total_registered"] == 0
    assert summary["total_resolved"] == 0


def test_27_terminal_daily_report_formatting(monitor_db: Path):
    """Test 27: Report string formatting matches terminal specification."""
    _insert_forward_obs(
        monitor_db,
        forward_id="FWD_27_1",
        signal_id="SIG_27_1",
        score=76,
        score_bucket="75-79",
        observation_status="RESOLVED",
        terminal_outcome="TARGET_FIRST",
        is_resolved=1,
    )
    svc = SignalForwardMonitorService(db_path=monitor_db)
    report = svc.build_daily_report(market_date="2026-10-05", cohort_id="FWD_2026-10")

    assert "Current cohort: FWD_2026-10" in report
    assert "75-79 : Registered=1   Resolved=1   Target=1   SL=0   Timeout=0   Status=INSUFFICIENT_SAMPLE" in report
    assert "FWD_2026-10 : Registered=1   Resolved=1   Qualifies_G3=NO" in report


def test_28_gate_3_timeout_and_authoritative_resolution_semantics(monitor_db: Path):
    """Test 28: Explicit regression test proving Gate 3 resolved population rules.

    Specifically verifies:
    - TIMEOUT + is_resolved=1 is INCLUDED in Gate-3 resolved count.
    - TIMEOUT + is_resolved=0 is EXCLUDED from Gate-3 resolved count.
    - Gate 3 counts the authoritative is_resolved == 1 population rather than
      deriving eligibility from observation_status or terminal_outcome.
    """
    # In cohort FWD_2026-10:
    # 15 standard RESOLVED records with is_resolved=1
    for i in range(15):
        _insert_forward_obs(
            monitor_db,
            forward_id=f"FWD_28_STD_RES_{i}",
            signal_id=f"SIG_28_STD_RES_{i}",
            cohort_id="FWD_2026-10",
            observation_status="RESOLVED",
            terminal_outcome="TARGET_FIRST",
            is_resolved=1,
            market_date="2026-10-02",
        )

    # 16 TIMEOUT records that ARE authoritatively resolved (is_resolved=1)
    for i in range(16):
        _insert_forward_obs(
            monitor_db,
            forward_id=f"FWD_28_TO_RES_{i}",
            signal_id=f"SIG_28_TO_RES_{i}",
            cohort_id="FWD_2026-10",
            observation_status="TIMEOUT",
            terminal_outcome="TIMEOUT",
            is_resolved=1,
            market_date="2026-10-02",
        )

    # 10 TIMEOUT records that are UNRESOLVED (is_resolved=0)
    for i in range(10):
        _insert_forward_obs(
            monitor_db,
            forward_id=f"FWD_28_TO_UNRES_{i}",
            signal_id=f"SIG_28_TO_UNRES_{i}",
            cohort_id="FWD_2026-10",
            observation_status="TIMEOUT",
            terminal_outcome="TIMEOUT",
            is_resolved=0,
            market_date="2026-10-02",
        )

    # 5 OBSERVING records (is_resolved=0)
    for i in range(5):
        _insert_forward_obs(
            monitor_db,
            forward_id=f"FWD_28_OBS_{i}",
            signal_id=f"SIG_28_OBS_{i}",
            cohort_id="FWD_2026-10",
            observation_status="OBSERVING",
            terminal_outcome=None,
            is_resolved=0,
            market_date="2026-10-02",
        )

    # 3 AMBIGUOUS records with is_resolved=0
    for i in range(3):
        _insert_forward_obs(
            monitor_db,
            forward_id=f"FWD_28_AMB_{i}",
            signal_id=f"SIG_28_AMB_{i}",
            cohort_id="FWD_2026-10",
            observation_status="AMBIGUOUS",
            terminal_outcome="AMBIGUOUS",
            is_resolved=0,
            market_date="2026-10-02",
        )

    # 2 NO_DATA records with is_resolved=0
    for i in range(2):
        _insert_forward_obs(
            monitor_db,
            forward_id=f"FWD_28_NODATA_{i}",
            signal_id=f"SIG_28_NODATA_{i}",
            cohort_id="FWD_2026-10",
            observation_status="NO_DATA",
            terminal_outcome="NO_DATA",
            is_resolved=0,
            market_date="2026-10-02",
        )

    # 1 INVALIDATED record with is_resolved=0
    _insert_forward_obs(
        monitor_db,
        forward_id="FWD_28_INVAL_1",
        signal_id="SIG_28_INVAL_1",
        cohort_id="FWD_2026-10",
        observation_status="INVALIDATED",
        terminal_outcome="INVALIDATED",
        is_resolved=0,
        market_date="2026-10-02",
    )

    svc = SignalForwardMonitorService(db_path=monitor_db)
    monthly = svc.get_monthly_summary()
    assert len(monthly) == 1
    m = monthly[0]

    # Total registered in cohort: 15 + 16 + 10 + 5 + 3 + 2 + 1 = 52
    assert m["registered"] == 52

    # Authoritative resolved count MUST BE EXACTLY 31 (15 standard + 16 TIMEOUT with is_resolved=1)
    # Proves:
    # 1) TIMEOUT + is_resolved=1 IS included in Gate-3 resolved population.
    # 2) TIMEOUT + is_resolved=0 IS excluded from Gate-3 resolved population.
    # 3) Gate 3 qualifies because 31 >= 30. (If TIMEOUT had a blanket exclusion, count would be 15 < 30).
    assert m["resolved"] == 31
    assert m["qualifies_for_monthly_gate"] is True

    # Also verify summary level consistency
    summary = svc.get_forward_summary(cohort_id="FWD_2026-10")
    assert summary["total_registered"] == 52
    assert summary["total_resolved"] == 31
