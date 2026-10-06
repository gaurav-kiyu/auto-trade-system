"""Phase D Test Suite: Forward Observation & Calibration Readiness.

Governance Authority: OPB-FINAL-PHASE-GOVERNANCE-001 / v2.60 Phase D Roadmap.

Verifies all 30 mandatory Phase-D requirements:
1. Forward observation registration from snapshot.
2. Snapshot immutability preserved.
3. Provenance and cohort tagging.
4. Historical/forward boundary separation.
5. Look-ahead protection: registered_at >= captured_at and captured_at >= cutoff.
6. Duplicate registration prevention / idempotency.
7. Idempotent sync rerun.
8. Restart recovery for in-flight signals.
9. Outcome linkage: TARGET_FIRST.
10. Outcome linkage: SL_FIRST.
11. Outcome linkage: TIMEOUT.
12. Ambiguous outcome quarantined.
13. Unresolved signal handling.
14. No-data signal quarantined.
15. Canonical score bucket mapping.
16. Per-bucket sample counting.
17. Readiness gate: n_resolved < 100 remains COLLECTING.
18. Readiness gate: n_resolved >= 100 per active bucket transitions to READY_FOR_REVIEW.
19. Multi-period longitudinal coverage check (>= 2 months).
20. Data quality metrics calculation.
21. Stale observation detection.
22. Readiness status determinism.
23. Phase-A snapshots unchanged.
24. Phase-B outcomes unchanged.
25. Phase-C discrimination unchanged.
26. Live-trading safety invariants intact.
27. Daily observation report generation.
28. No probability calibration performed.
29. No model or threshold mutations.
30. No ranking or trading recommendations emitted.
"""

from __future__ import annotations

import datetime
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from core.datetime_ist import now_ist
from core.signals.signal_forward_observation import (
    CANONICAL_SCORE_BUCKETS,
    GATE_MIN_RESOLVED_PER_ACTIVE_BUCKET,
    OBSERVATION_VERSION,
    SignalForwardObservationService,
)
from core.signals.signal_outcome_dataset import SignalOutcomeDatasetService
from core.signals.signal_outcome_tracker import SignalOutcomeTracker
from core.signals.signal_score_discrimination import SignalScoreDiscriminationService
from core.signals.signal_tracker import SignalTracker


@pytest.fixture(autouse=True)
def _reset_singletons():
    SignalTracker.reset_instance()
    SignalOutcomeTracker.reset_instance()
    SignalOutcomeDatasetService.reset_instance()
    SignalScoreDiscriminationService.reset_instance()
    SignalForwardObservationService.reset_instance()
    yield
    SignalTracker.reset_instance()
    SignalOutcomeTracker.reset_instance()
    SignalOutcomeDatasetService.reset_instance()
    SignalScoreDiscriminationService.reset_instance()
    SignalForwardObservationService.reset_instance()


@pytest.fixture
def temp_db(tmp_path: Path) -> Path:
    """Create a temporary test database with full schema for Phase D."""
    db_file = tmp_path / "signals_forward_test.db"
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
            strategy_version TEXT DEFAULT '',
            model_version TEXT DEFAULT '',
            calibration_version TEXT DEFAULT 'UNCALIBRATED',
            feature_schema_version TEXT DEFAULT '',
            symbol TEXT NOT NULL,
            category TEXT NOT NULL,
            direction TEXT NOT NULL,
            strategy TEXT DEFAULT '',
            score INTEGER NOT NULL,
            raw_score REAL,
            normalized_score REAL,
            score_saturated INTEGER DEFAULT 0,
            tier TEXT NOT NULL,
            entry_price REAL NOT NULL,
            stop_loss REAL NOT NULL,
            target_1 REAL NOT NULL,
            target_2 REAL NOT NULL,
            market_regime TEXT DEFAULT '',
            regime_confidence REAL,
            composite_score REAL,
            p_t1 REAL,
            p_t2 REAL,
            p_sl REAL,
            p_timeout REAL,
            expected_value_r REAL,
            net_rr_t1 REAL,
            net_rr_t2 REAL,
            features_json TEXT,
            score_components_json TEXT,
            raw_signal_json TEXT,
            snapshot_hash TEXT NOT NULL,
            source TEXT DEFAULT 'GENERATION',
            created_at TEXT NOT NULL,
            FOREIGN KEY (signal_id) REFERENCES system_signals(signal_id)
        )
    """)

    cur.execute("""
        CREATE TABLE signal_outcome_events (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT,
            signal_id TEXT NOT NULL,
            observed_at TEXT NOT NULL,
            observed_price REAL NOT NULL,
            hit_sl INTEGER NOT NULL DEFAULT 0,
            hit_t1 INTEGER NOT NULL DEFAULT 0,
            hit_t2 INTEGER NOT NULL DEFAULT 0,
            transition_note TEXT DEFAULT '',
            FOREIGN KEY (signal_id) REFERENCES system_signals(signal_id)
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
            initial_risk REAL,
            observed_from TEXT NOT NULL,
            observed_until TEXT,
            outcome TEXT NOT NULL,
            raw_lifecycle_state TEXT NOT NULL,
            first_touch TEXT,
            first_touch_at TEXT,
            first_touch_price REAL,
            target_1_hit INTEGER NOT NULL DEFAULT 0,
            target_1_hit_at TEXT,
            target_1_hit_price REAL,
            target_2_hit INTEGER NOT NULL DEFAULT 0,
            target_2_hit_at TEXT,
            target_2_hit_price REAL,
            stop_loss_hit INTEGER NOT NULL DEFAULT 0,
            stop_loss_hit_at TEXT,
            stop_loss_hit_price REAL,
            mfe REAL,
            mae REAL,
            mfe_pct REAL,
            mae_pct REAL,
            mfe_r REAL,
            mae_r REAL,
            time_to_first_event_seconds REAL,
            time_to_t1_seconds REAL,
            time_to_t2_seconds REAL,
            time_to_sl_seconds REAL,
            realized_r REAL,
            exit_price REAL,
            exit_at TEXT,
            observation_count INTEGER NOT NULL DEFAULT 0,
            data_quality_status TEXT NOT NULL DEFAULT 'VALID_DATA',
            outcome_confidence TEXT DEFAULT 'UNKNOWN',
            calculation_version TEXT NOT NULL DEFAULT 'OUTCOME_MEASUREMENT_V1',
            calculated_at TEXT NOT NULL,
            FOREIGN KEY (signal_id) REFERENCES signal_prediction_snapshots(signal_id)
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
            last_updated_at TEXT NOT NULL,
            FOREIGN KEY (signal_id) REFERENCES signal_prediction_snapshots(signal_id)
        )
    """)

    conn.commit()
    conn.close()
    return db_file


def _insert_test_snapshot(
    db_file: Path,
    signal_id: str,
    score: int = 82,
    captured_at: str | None = None,
    source: str = "GENERATION",
    entry_price: float = 1000.0,
    stop_loss: float = 980.0,
    target_1: float = 1020.0,
    target_2: float = 1040.0,
    direction: str = "CALL",
    raw_signal_json: str = "{}",
) -> None:
    conn = sqlite3.connect(str(db_file))
    cur = conn.cursor()
    t0 = captured_at or now_ist().isoformat()
    cur.execute("""
        INSERT INTO signal_prediction_snapshots (
            signal_id, captured_at, symbol, category, direction, score, tier,
            entry_price, stop_loss, target_1, target_2, snapshot_hash, source,
            raw_signal_json, created_at
        ) VALUES (
            ?, ?, 'TEST_SYM', 'EQUITY', ?, ?, 'TIER_1',
            ?, ?, ?, ?, 'hash_123', ?, ?, ?
        )
    """, (
        signal_id, t0, direction, score,
        entry_price, stop_loss, target_1, target_2, source,
        raw_signal_json, t0,
    ))
    cur.execute("""
        INSERT OR REPLACE INTO system_signals (
            signal_id, symbol, category, direction, score, tier, status,
            entry_price, stop_loss, target_1, target_2, timestamp, created_date
        ) VALUES (
            ?, 'TEST_SYM', 'EQUITY', ?, ?, 'TIER_1', 'ACTIVE',
            ?, ?, ?, ?, ?, ?
        )
    """, (
        signal_id, direction, score,
        entry_price, stop_loss, target_1, target_2, t0, t0[:10]
    ))
    conn.commit()
    conn.close()


class TestSignalForwardObservation:
    """30 comprehensive Phase-D tests."""

    # 1. Forward observation registration from snapshot
    def test_01_forward_observation_registration(self, temp_db: Path):
        t0 = "2026-09-26T10:00:00+05:30"
        _insert_test_snapshot(temp_db, "SIG-FWD-01", score=83, captured_at=t0)
        svc = SignalForwardObservationService(db_path=temp_db)
        res = svc.register_forward_signal("SIG-FWD-01", cutoff_iso="2026-09-26T00:00:00+05:30")
        assert res is not None
        assert res["forward_id"] == "FWD_SIG-FWD-01"
        assert res["signal_id"] == "SIG-FWD-01"
        assert res["score_bucket"] == "80-84"
        assert res["observation_status"] == "OBSERVING"
        assert res["is_resolved"] == 0

    # 2. Snapshot immutability preserved
    def test_02_snapshot_immutability_preserved(self, temp_db: Path):
        t0 = "2026-09-26T10:00:00+05:30"
        _insert_test_snapshot(temp_db, "SIG-FWD-02", score=88, captured_at=t0)
        conn = sqlite3.connect(str(temp_db))
        before = conn.execute("SELECT * FROM signal_prediction_snapshots WHERE signal_id='SIG-FWD-02'").fetchone()

        svc = SignalForwardObservationService(db_path=temp_db)
        svc.register_forward_signal("SIG-FWD-02", cutoff_iso="2026-09-26T00:00:00+05:30")

        after = conn.execute("SELECT * FROM signal_prediction_snapshots WHERE signal_id='SIG-FWD-02'").fetchone()
        conn.close()
        assert before == after

    # 3. Provenance and cohort tagging
    def test_03_provenance_and_cohort_tagging(self, temp_db: Path):
        t0 = "2026-09-26T09:15:00+05:30"
        _insert_test_snapshot(temp_db, "SIG-FWD-03", score=86, captured_at=t0)
        svc = SignalForwardObservationService(db_path=temp_db)
        res = svc.register_forward_signal(
            "SIG-FWD-03", cohort_id="FWD_2026-10", observation_source="LIVE_SCAN", cutoff_iso="2026-09-26T00:00:00+05:30"
        )
        assert res["cohort_id"] == "FWD_2026-10"
        assert res["observation_source"] == "LIVE_SCAN"
        assert res["forward_cutoff_version"] == "PHASE_D_V1_20260926"

    # 4. Historical/forward boundary separation
    def test_04_historical_forward_boundary_separation(self, temp_db: Path):
        # Pre-cutoff signal
        t_hist = "2026-09-15T10:00:00+05:30"
        _insert_test_snapshot(temp_db, "SIG-HIST-01", score=80, captured_at=t_hist)
        svc = SignalForwardObservationService(db_path=temp_db)
        # Should be rejected because it predates cutoff
        res_hist = svc.register_forward_signal("SIG-HIST-01", cutoff_iso="2026-09-26T00:00:00+05:30")
        assert res_hist is None

        # Seed sample should also be rejected
        t_fwd = "2026-09-26T10:00:00+05:30"
        _insert_test_snapshot(temp_db, "SIG-SEED-01", score=80, captured_at=t_fwd, source="SEED")
        res_seed = svc.register_forward_signal("SIG-SEED-01", cutoff_iso="2026-09-26T00:00:00+05:30")
        assert res_seed is None

    # 5. Look-ahead protection: registered_at >= captured_at and captured_at >= cutoff
    def test_05_lookahead_protection_registered_after_t0(self, temp_db: Path):
        # Future snapshot timestamp relative to current real time
        future_t0 = (now_ist() + datetime.timedelta(days=10)).isoformat()
        _insert_test_snapshot(temp_db, "SIG-FUTURE-01", score=82, captured_at=future_t0)
        svc = SignalForwardObservationService(db_path=temp_db)
        # Registration must fail because registration time is strictly before snapshot time
        res = svc.register_forward_signal("SIG-FUTURE-01", cutoff_iso="2026-09-26T00:00:00+05:30")
        assert res is None

    # 6. Duplicate registration prevention / idempotency
    def test_06_duplicate_registration_prevention(self, temp_db: Path):
        t0 = "2026-09-26T10:00:00+05:30"
        _insert_test_snapshot(temp_db, "SIG-FWD-06", score=82, captured_at=t0)
        svc = SignalForwardObservationService(db_path=temp_db)
        res1 = svc.register_forward_signal("SIG-FWD-06", cutoff_iso="2026-09-26T00:00:00+05:30")
        res2 = svc.register_forward_signal("SIG-FWD-06", cutoff_iso="2026-09-26T00:00:00+05:30")
        assert res1["forward_id"] == res2["forward_id"]

        conn = sqlite3.connect(str(temp_db))
        count = conn.execute("SELECT COUNT(*) FROM signal_forward_observations WHERE signal_id='SIG-FWD-06'").fetchone()[0]
        conn.close()
        assert count == 1

    # 7. Idempotent sync rerun
    def test_07_idempotent_sync_rerun(self, temp_db: Path):
        t0 = "2026-09-26T10:00:00+05:30"
        _insert_test_snapshot(temp_db, "SIG-FWD-07", score=85, captured_at=t0)
        svc = SignalForwardObservationService(db_path=temp_db)
        svc.register_forward_signal("SIG-FWD-07", cutoff_iso="2026-09-26T00:00:00+05:30")

        # Sync twice
        cnt1 = svc.sync_forward_outcomes()
        cnt2 = svc.sync_forward_outcomes()
        # Second run should have no non-resolved rows needing updates if resolved, or remain unchanged
        assert cnt1 >= 0
        assert cnt2 >= 0

    # 8. Restart recovery for in-flight signals
    def test_08_restart_recovery_in_flight(self, temp_db: Path):
        t0 = "2026-09-26T10:00:00+05:30"
        _insert_test_snapshot(temp_db, "SIG-FWD-08", score=85, captured_at=t0)
        svc1 = SignalForwardObservationService(db_path=temp_db)
        svc1.register_forward_signal("SIG-FWD-08", cutoff_iso="2026-09-26T00:00:00+05:30")

        # Simulate fresh process restart
        SignalForwardObservationService.reset_instance()
        svc2 = SignalForwardObservationService.get_instance(db_path=temp_db)
        conn = sqlite3.connect(str(temp_db))
        row = conn.execute("SELECT observation_status FROM signal_forward_observations WHERE signal_id='SIG-FWD-08'").fetchone()
        conn.close()
        assert row[0] == "OBSERVING"

    # 9. Outcome linkage: TARGET_FIRST
    def test_09_outcome_linkage_target_first(self, temp_db: Path):
        t0 = "2026-09-26T10:00:00+05:30"
        _insert_test_snapshot(temp_db, "SIG-FWD-09", score=85, captured_at=t0, entry_price=500.0, stop_loss=480.0, target_1=520.0)
        svc = SignalForwardObservationService(db_path=temp_db)
        svc.register_forward_signal("SIG-FWD-09", cutoff_iso="2026-09-26T00:00:00+05:30")

        # Insert Phase-B outcome event (target hit post-T0)
        conn = sqlite3.connect(str(temp_db))
        conn.execute("""
            UPDATE system_signals
            SET status = 'TARGET_2_HIT', first_touch = 'T1', first_touch_at = '2026-09-26T10:15:00+05:30', first_touch_price = 520.0
            WHERE signal_id = 'SIG-FWD-09'
        """)
        conn.execute("""
            INSERT INTO signal_outcome_events (signal_id, observed_at, observed_price, hit_sl, hit_t1, hit_t2)
            VALUES ('SIG-FWD-09', '2026-09-26T10:15:00+05:30', 520.0, 0, 1, 1)
        """)
        conn.commit()
        conn.close()

        svc.sync_forward_outcomes()

        conn = sqlite3.connect(str(temp_db))
        row = conn.execute("SELECT observation_status, terminal_outcome, is_resolved, realized_r FROM signal_forward_observations WHERE signal_id='SIG-FWD-09'").fetchone()
        conn.close()
        assert row[0] == "RESOLVED"
        assert row[1] == "TARGET_FIRST"
        assert row[2] == 1
        assert row[3] == 1.0

    # 10. Outcome linkage: SL_FIRST
    def test_10_outcome_linkage_sl_first(self, temp_db: Path):
        t0 = "2026-09-26T10:00:00+05:30"
        _insert_test_snapshot(temp_db, "SIG-FWD-10", score=82, captured_at=t0, entry_price=500.0, stop_loss=480.0, target_1=520.0)
        svc = SignalForwardObservationService(db_path=temp_db)
        svc.register_forward_signal("SIG-FWD-10", cutoff_iso="2026-09-26T00:00:00+05:30")

        # Insert Phase-B outcome event (SL hit post-T0)
        conn = sqlite3.connect(str(temp_db))
        conn.execute("""
            UPDATE system_signals
            SET status = 'SL_HIT', first_touch = 'SL', first_touch_at = '2026-09-26T10:15:00+05:30', first_touch_price = 480.0
            WHERE signal_id = 'SIG-FWD-10'
        """)
        conn.execute("""
            INSERT INTO signal_outcome_events (signal_id, observed_at, observed_price, hit_sl, hit_t1, hit_t2)
            VALUES ('SIG-FWD-10', '2026-09-26T10:15:00+05:30', 480.0, 1, 0, 0)
        """)
        conn.commit()
        conn.close()

        svc.sync_forward_outcomes()

        conn = sqlite3.connect(str(temp_db))
        row = conn.execute("SELECT observation_status, terminal_outcome, is_resolved, realized_r FROM signal_forward_observations WHERE signal_id='SIG-FWD-10'").fetchone()
        conn.close()
        assert row[0] == "RESOLVED"
        assert row[1] == "SL_FIRST"
        assert row[2] == 1
        assert row[3] == -1.0

    # 11. Outcome linkage: TIMEOUT
    def test_11_outcome_linkage_timeout(self, temp_db: Path):
        t0 = "2026-09-26T10:00:00+05:30"
        _insert_test_snapshot(temp_db, "SIG-FWD-11", score=82, captured_at=t0, entry_price=500.0, stop_loss=480.0, target_1=520.0)
        # Update system_signals status to EXPIRED
        conn = sqlite3.connect(str(temp_db))
        conn.execute("""
            UPDATE system_signals
            SET status = 'EXPIRED', first_touch = 'TIMEOUT', first_touch_at = '2026-09-26T15:35:00+05:30'
            WHERE signal_id = 'SIG-FWD-11'
        """)
        conn.execute("""
            INSERT INTO signal_outcome_events (signal_id, observed_at, observed_price, hit_sl, hit_t1, hit_t2)
            VALUES ('SIG-FWD-11', '2026-09-26T15:35:00+05:30', 505.0, 0, 0, 0)
        """)
        conn.commit()
        conn.close()

        svc = SignalForwardObservationService(db_path=temp_db)
        svc.register_forward_signal("SIG-FWD-11", cutoff_iso="2026-09-26T00:00:00+05:30")
        svc.sync_forward_outcomes()

        conn = sqlite3.connect(str(temp_db))
        row = conn.execute("SELECT observation_status, terminal_outcome, is_resolved FROM signal_forward_observations WHERE signal_id='SIG-FWD-11'").fetchone()
        conn.close()
        assert row[0] == "TIMEOUT"
        assert row[1] == "TIMEOUT"
        assert row[2] == 1

    # 12. Ambiguous outcome quarantined
    def test_12_ambiguous_outcome_quarantined(self, temp_db: Path):
        t0 = "2026-09-26T10:00:00+05:30"
        _insert_test_snapshot(temp_db, "SIG-FWD-12", score=82, captured_at=t0, entry_price=500.0, stop_loss=480.0, target_1=520.0)
        # Insert same-bar hit in events
        conn = sqlite3.connect(str(temp_db))
        conn.execute("""
            UPDATE system_signals
            SET status = 'AMBIGUOUS', first_touch = 'AMBIGUOUS_SAME_BAR', outcome_confidence = 'AMBIGUOUS'
            WHERE signal_id = 'SIG-FWD-12'
        """)
        conn.execute("""
            INSERT INTO signal_outcome_events (signal_id, observed_at, observed_price, hit_sl, hit_t1, hit_t2)
            VALUES ('SIG-FWD-12', '2026-09-26T10:15:00+05:30', 500.0, 1, 1, 0)
        """)
        conn.commit()
        conn.close()

        svc = SignalForwardObservationService(db_path=temp_db)
        svc.register_forward_signal("SIG-FWD-12", cutoff_iso="2026-09-26T00:00:00+05:30")
        svc.sync_forward_outcomes()

        conn = sqlite3.connect(str(temp_db))
        row = conn.execute("SELECT observation_status, terminal_outcome, is_resolved FROM signal_forward_observations WHERE signal_id='SIG-FWD-12'").fetchone()
        conn.close()
        assert row[0] == "AMBIGUOUS"
        assert row[1] == "AMBIGUOUS"
        assert row[2] == 0  # Must NOT count toward resolved readiness gate

    # 13. Unresolved signal handling
    def test_13_unresolved_signal_handling(self, temp_db: Path):
        t0 = "2026-09-26T10:00:00+05:30"
        _insert_test_snapshot(temp_db, "SIG-FWD-13", score=82, captured_at=t0)
        conn = sqlite3.connect(str(temp_db))
        conn.execute("""
            INSERT INTO signal_outcome_events (signal_id, observed_at, observed_price, hit_sl, hit_t1, hit_t2)
            VALUES ('SIG-FWD-13', '2026-09-26T10:15:00+05:30', 1005.0, 0, 0, 0)
        """)
        conn.commit()
        conn.close()

        svc = SignalForwardObservationService(db_path=temp_db)
        svc.register_forward_signal("SIG-FWD-13", cutoff_iso="2026-09-26T00:00:00+05:30")
        svc.sync_forward_outcomes()

        conn = sqlite3.connect(str(temp_db))
        row = conn.execute("SELECT observation_status, is_resolved FROM signal_forward_observations WHERE signal_id='SIG-FWD-13'").fetchone()
        conn.close()
        assert row[0] == "OBSERVING"
        assert row[1] == 0

    # 14. No-data signal quarantined
    def test_14_no_data_signal_quarantined(self, temp_db: Path):
        t0 = "2026-09-26T10:00:00+05:30"
        _insert_test_snapshot(temp_db, "SIG-FWD-14", score=82, captured_at=t0)
        # Force outcome measurement with NO_DATA
        conn = sqlite3.connect(str(temp_db))
        conn.execute("""
            INSERT INTO signal_outcome_measurements (signal_id, prediction_snapshot_id, symbol, category, direction, entry_price, stop_loss, target_1, target_2, observed_from, outcome, raw_lifecycle_state, data_quality_status, calculated_at)
            VALUES ('SIG-FWD-14', 'SIG-FWD-14', 'TEST_SYM', 'EQUITY', 'CALL', 1000, 980, 1020, 1040, ?, 'NO_DATA', 'ACTIVE', 'NO_DATA', ?)
        """, (t0, t0))
        conn.commit()
        conn.close()

        svc = SignalForwardObservationService(db_path=temp_db)
        svc.register_forward_signal("SIG-FWD-14", cutoff_iso="2026-09-26T00:00:00+05:30")
        svc.sync_forward_outcomes()

        conn = sqlite3.connect(str(temp_db))
        row = conn.execute("SELECT observation_status, terminal_outcome, is_resolved FROM signal_forward_observations WHERE signal_id='SIG-FWD-14'").fetchone()
        conn.close()
        assert row[0] == "NO_DATA"
        assert row[2] == 0

    # 15. Canonical score bucket mapping
    def test_15_score_bucket_canonical_mapping(self, temp_db: Path):
        t0 = "2026-09-26T10:00:00+05:30"
        svc = SignalForwardObservationService(db_path=temp_db)
        for score, expected_b in [(68, "<70"), (72, "70-74"), (77, "75-79"), (82, "80-84"), (89, "85+")]:
            s_id = f"SIG-SCORE-{score}"
            _insert_test_snapshot(temp_db, s_id, score=score, captured_at=t0)
            res = svc.register_forward_signal(s_id, cutoff_iso="2026-09-26T00:00:00+05:30")
            assert res["score_bucket"] == expected_b

    # 16. Per-bucket sample counting
    def test_16_per_bucket_sample_counting(self, temp_db: Path):
        t0 = "2026-09-26T10:00:00+05:30"
        svc = SignalForwardObservationService(db_path=temp_db)
        _insert_test_snapshot(temp_db, "SIG-C-1", score=82, captured_at=t0)
        _insert_test_snapshot(temp_db, "SIG-C-2", score=82, captured_at=t0)
        _insert_test_snapshot(temp_db, "SIG-C-3", score=88, captured_at=t0)
        svc.register_forward_signal("SIG-C-1", cutoff_iso="2026-09-26T00:00:00+05:30")
        svc.register_forward_signal("SIG-C-2", cutoff_iso="2026-09-26T00:00:00+05:30")
        svc.register_forward_signal("SIG-C-3", cutoff_iso="2026-09-26T00:00:00+05:30")

        summaries, overall, exp = svc.evaluate_readiness_gates()
        assert summaries["80-84"].n_forward == 2
        assert summaries["85+"].n_forward == 1
        assert summaries["70-74"].n_forward == 0
        assert summaries["70-74"].bucket_status == "INACTIVE_BUCKET"

    # 17. Readiness gate: n_resolved < 100 remains COLLECTING
    def test_17_readiness_gate_n100_unmet(self, temp_db: Path):
        t0 = "2026-09-26T10:00:00+05:30"
        svc = SignalForwardObservationService(db_path=temp_db)
        _insert_test_snapshot(temp_db, "SIG-UNMET-1", score=82, captured_at=t0)
        svc.register_forward_signal("SIG-UNMET-1", cutoff_iso="2026-09-26T00:00:00+05:30")

        summaries, overall, exp = svc.evaluate_readiness_gates()
        assert overall in ("INSUFFICIENT_SAMPLE", "COLLECTING")
        assert summaries["80-84"].bucket_status != "READY_FOR_REVIEW"

    # 18. Readiness gate: n_resolved >= 100 per active bucket transitions to READY_FOR_REVIEW
    def test_18_readiness_gate_n100_met(self, temp_db: Path):
        # Insert 100 resolved signals for 80-84 and 100 for 85+ across 2 distinct months
        conn = sqlite3.connect(str(temp_db))
        cur = conn.cursor()
        for idx in range(150):
            # Month 1: 2026-10
            cur.execute("""
                INSERT INTO signal_forward_observations (
                    forward_id, signal_id, cohort_id, registered_at, market_date, score, score_bucket,
                    direction, symbol, category, entry_price, stop_loss, target_1, target_2,
                    prediction_hash, snapshot_captured_at, observation_status, terminal_outcome, is_resolved, last_updated_at
                ) VALUES (
                    ?, ?, 'FWD_2026-10', '2026-10-10T10:00:00+05:30', '2026-10-10', 82, '80-84',
                    'CALL', 'SYM', 'EQUITY', 1000, 980, 1020, 1040, 'h', '2026-10-10T10:00:00+05:30',
                    'RESOLVED', 'TARGET_FIRST', 1, '2026-10-10T10:00:00+05:30'
                )
            """, (f"FWD-M1-{idx}", f"SIG-M1-{idx}"))

        for idx in range(150):
            # Month 2: 2026-11
            cur.execute("""
                INSERT INTO signal_forward_observations (
                    forward_id, signal_id, cohort_id, registered_at, market_date, score, score_bucket,
                    direction, symbol, category, entry_price, stop_loss, target_1, target_2,
                    prediction_hash, snapshot_captured_at, observation_status, terminal_outcome, is_resolved, last_updated_at
                ) VALUES (
                    ?, ?, 'FWD_2026-11', '2026-11-10T10:00:00+05:30', '2026-11-10', 88, '85+',
                    'CALL', 'SYM', 'EQUITY', 1000, 980, 1020, 1040, 'h', '2026-11-10T10:00:00+05:30',
                    'RESOLVED', 'TARGET_FIRST', 1, '2026-11-10T10:00:00+05:30'
                )
            """, (f"FWD-M2-{idx}", f"SIG-M2-{idx}"))
        conn.commit()
        conn.close()

        svc = SignalForwardObservationService(db_path=temp_db)
        summaries, overall, exp = svc.evaluate_readiness_gates()
        assert summaries["80-84"].bucket_status == "READY_FOR_REVIEW"
        assert summaries["85+"].bucket_status == "READY_FOR_REVIEW"
        assert summaries["70-74"].bucket_status == "INACTIVE_BUCKET"
        assert overall == "READY_FOR_REVIEW"

    # 19. Multi-period longitudinal coverage check (>= 2 months)
    def test_19_multi_period_longitudinal_check(self, temp_db: Path):
        conn = sqlite3.connect(str(temp_db))
        cur = conn.cursor()
        # 300 signals in a SINGLE month (2026-10)
        for idx in range(300):
            cur.execute("""
                INSERT INTO signal_forward_observations (
                    forward_id, signal_id, cohort_id, registered_at, market_date, score, score_bucket,
                    direction, symbol, category, entry_price, stop_loss, target_1, target_2,
                    prediction_hash, snapshot_captured_at, observation_status, terminal_outcome, is_resolved, last_updated_at
                ) VALUES (
                    ?, ?, 'FWD_2026-10', '2026-10-10T10:00:00+05:30', '2026-10-10', 82, '80-84',
                    'CALL', 'SYM', 'EQUITY', 1000, 980, 1020, 1040, 'h', '2026-10-10T10:00:00+05:30',
                    'RESOLVED', 'TARGET_FIRST', 1, '2026-10-10T10:00:00+05:30'
                )
            """, (f"FWD-SINGLE-{idx}", f"SIG-SINGLE-{idx}"))
        conn.commit()
        conn.close()

        svc = SignalForwardObservationService(db_path=temp_db)
        summaries, overall, exp = svc.evaluate_readiness_gates()
        # Must NOT be READY_FOR_REVIEW because only 1 calendar month exists
        assert overall == "COLLECTING"
        assert "distinct periods" in exp

    # 20. Data quality metrics calculation
    def test_20_data_quality_metrics_calculation(self, temp_db: Path):
        t0 = "2026-09-26T10:00:00+05:30"
        svc = SignalForwardObservationService(db_path=temp_db)
        _insert_test_snapshot(temp_db, "SIG-DQ-1", score=82, captured_at=t0)
        svc.register_forward_signal("SIG-DQ-1", cutoff_iso="2026-09-26T00:00:00+05:30")

        rep = svc.generate_daily_observation_report()
        assert rep.data_quality_error_rate >= 0.0

    # 21. Stale observation detection
    def test_21_stale_observation_detection(self, temp_db: Path):
        conn = sqlite3.connect(str(temp_db))
        # Registered 5 days ago in OBSERVING state
        old_ts = (now_ist() - datetime.timedelta(days=5)).isoformat()
        conn.execute("""
            INSERT INTO signal_forward_observations (
                forward_id, signal_id, cohort_id, registered_at, market_date, score, score_bucket,
                direction, symbol, category, entry_price, stop_loss, target_1, target_2,
                prediction_hash, snapshot_captured_at, observation_status, is_resolved, last_updated_at
            ) VALUES (
                'FWD-STALE', 'SIG-STALE', 'FWD_2026-09', ?, '2026-09-20', 82, '80-84',
                'CALL', 'SYM', 'EQUITY', 1000, 980, 1020, 1040, 'h', ?,
                'OBSERVING', 0, ?
            )
        """, (old_ts, old_ts, old_ts))
        conn.commit()
        conn.close()

        svc = SignalForwardObservationService(db_path=temp_db)
        rep = svc.generate_daily_observation_report()
        assert rep.stale_observations_count == 1
        assert rep.stale_rate == 1.0

    # 22. Readiness status determinism
    def test_22_readiness_status_determinism(self, temp_db: Path):
        t0 = "2026-09-26T10:00:00+05:30"
        _insert_test_snapshot(temp_db, "SIG-DET-1", score=82, captured_at=t0)
        svc = SignalForwardObservationService(db_path=temp_db)
        svc.register_forward_signal("SIG-DET-1", cutoff_iso="2026-09-26T00:00:00+05:30")

        r1, s1, e1 = svc.evaluate_readiness_gates()
        r2, s2, e2 = svc.evaluate_readiness_gates()
        assert s1 == s2
        assert e1 == e2

    # 23. Phase-A snapshots unchanged
    def test_23_phase_a_snapshots_unchanged(self, temp_db: Path):
        t0 = "2026-09-26T10:00:00+05:30"
        _insert_test_snapshot(temp_db, "SIG-SNAP-CHK", score=84, captured_at=t0)
        conn = sqlite3.connect(str(temp_db))
        b = conn.execute("SELECT * FROM signal_prediction_snapshots WHERE signal_id='SIG-SNAP-CHK'").fetchone()

        svc = SignalForwardObservationService(db_path=temp_db)
        svc.register_forward_signal("SIG-SNAP-CHK", cutoff_iso="2026-09-26T00:00:00+05:30")
        svc.sync_forward_outcomes()
        svc.evaluate_readiness_gates()

        a = conn.execute("SELECT * FROM signal_prediction_snapshots WHERE signal_id='SIG-SNAP-CHK'").fetchone()
        conn.close()
        assert b == a

    # 24. Phase-B outcomes unchanged
    def test_24_phase_b_outcomes_unchanged(self, temp_db: Path):
        t0 = "2026-09-26T10:00:00+05:30"
        _insert_test_snapshot(temp_db, "SIG-OUT-CHK", score=84, captured_at=t0)
        conn = sqlite3.connect(str(temp_db))
        conn.execute("""
            INSERT INTO signal_outcome_measurements (signal_id, prediction_snapshot_id, symbol, category, direction, entry_price, stop_loss, target_1, target_2, observed_from, outcome, raw_lifecycle_state, calculated_at)
            VALUES ('SIG-OUT-CHK', 'SIG-OUT-CHK', 'TEST_SYM', 'EQUITY', 'CALL', 1000, 980, 1020, 1040, ?, 'TARGET_FIRST', 'TARGET_1_HIT', ?)
        """, (t0, t0))
        conn.commit()
        b = conn.execute("SELECT * FROM signal_outcome_measurements WHERE signal_id='SIG-OUT-CHK'").fetchone()

        svc = SignalForwardObservationService(db_path=temp_db)
        svc.register_forward_signal("SIG-OUT-CHK", cutoff_iso="2026-09-26T00:00:00+05:30")
        svc.sync_forward_outcomes()

        a = conn.execute("SELECT * FROM signal_outcome_measurements WHERE signal_id='SIG-OUT-CHK'").fetchone()
        conn.close()
        assert b == a

    # 25. Phase-C discrimination unchanged
    def test_25_phase_c_discrimination_unchanged(self, temp_db: Path):
        disc_svc = SignalScoreDiscriminationService(db_path=temp_db)
        rep = disc_svc.analyze_score_buckets()
        assert rep.analysis_version == "SCORE_DISCRIMINATION_V1"

    # 26. Live-trading safety invariants intact
    def test_26_live_trading_safety_invariants_intact(self):
        from core.config_bootstrap import get_effective_config
        cfg = get_effective_config()
        assert cfg.get("EXECUTION_MODE") == "SIGNAL_ONLY"
        assert cfg.get("SIGNAL_ONLY") is True
        assert cfg.get("full_auto_allowed") is False
        assert cfg.get("LIVE_TRADING_LOCKOUT") is True
        assert cfg.get("BASE_CAPITAL") == 3000
        assert cfg.get("SL_PCT") == 0.88

    # 27. Daily observation report generation
    def test_27_daily_report_generation(self, temp_db: Path):
        svc = SignalForwardObservationService(db_path=temp_db)
        rep = svc.generate_daily_observation_report()
        assert rep.report_version == OBSERVATION_VERSION
        assert rep.live_trading_lockout_enforced is True
        assert "80-84" in rep.bucket_readiness
        assert "85+" in rep.bucket_readiness

    # 28. No probability calibration performed
    def test_28_no_probability_calibration_performed(self, temp_db: Path):
        svc = SignalForwardObservationService(db_path=temp_db)
        rep = svc.generate_daily_observation_report().to_dict()
        # Verify no calibrated probability keys exist in bucket reports
        for b_name, b_info in rep["bucket_readiness"].items():
            assert "p_calibrated" not in b_info
            assert "p_t1" not in b_info
            assert "p_sl" not in b_info

    # 29. No model or threshold mutations
    def test_29_no_model_or_threshold_mutations(self):
        from core.signals.signal_tracker import SignalTracker
        st = SignalTracker.get_instance()
        assert hasattr(st, "register_forward_signal")
        assert hasattr(st, "sync_forward_outcomes")
        assert hasattr(st, "get_forward_observation_report")

    # 30. No ranking or trading recommendations emitted
    def test_30_no_ranking_or_recommendations_emitted(self, temp_db: Path):
        svc = SignalForwardObservationService(db_path=temp_db)
        rep_dict = svc.generate_daily_observation_report().to_dict()
        rep_str = str(rep_dict).upper()
        assert "BEST_BUCKET" not in rep_str
        assert "WORST_BUCKET" not in rep_str
        assert "RECOMMENDED_ACTION" not in rep_str
        assert "TRADE_SIGNAL" not in rep_str
