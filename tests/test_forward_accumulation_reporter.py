"""Tests for OPB v2.60 Automated Daily Forward Accumulation Monitor & Reporter.

Governance Authority: OPB-FINAL-PHASE-GOVERNANCE-001 / v2.60 Signal Quality Roadmap.

Ensures strict compliance with:
- Session & market calendar auditing
- Forward cohort accounting (registered, observing, resolved, timeout, ambiguous, no-data, invalidated, stale)
- Score bucket auditing (70-74, 75-79, 80-84, 85+, and <70 anomaly)
- Gate evaluation (G1, G2, G3, G4)
- Integrity auditing (cutoff violations, historical contamination, seed contamination, duplicates, feature leakage, probability leakage)
- Safety locks auditing (SIGNAL_ONLY, live lockout, full auto false, zero orders)
- Markdown and JSON report generation
- Deterministic operational state / verdict mapping
- Production database read-only immutability
"""

import datetime
import json
import sqlite3
from pathlib import Path

import pytest
from core.datetime_ist import now_ist
from core.signals.forward_accumulation_reporter import (
    STATE_ACCUMULATION_ACTIVE,
    STATE_ACCUMULATION_BLOCKED,
    STATE_PHASE_E_EMPIRICAL_EXECUTION_READY,
    STATE_WAITING_FOR_MARKET_SESSION,
    ForwardAccumulationReporter,
    audit_forward_integrity,
    audit_production_safety,
    get_market_session_info,
)
from core.signals.signal_forward_monitor import (
    DEFAULT_FORWARD_CUTOFF_ISO,
    SignalForwardMonitorService,
)

# ============================================================================
# Helpers & Isolated Database Fixtures
# ============================================================================


@pytest.fixture
def isolated_db(tmp_path: Path) -> Path:
    """Create an isolated test database fixture with standard OPB schema."""
    db_file = tmp_path / "test_forward_monitor.db"
    conn = sqlite3.connect(str(db_file))
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE system_signals (
        signal_id TEXT PRIMARY KEY,
        timestamp TEXT,
        created_date TEXT,
        symbol TEXT,
        direction TEXT,
        score REAL,
        entry_price REAL,
        stop_loss REAL,
        target_1 REAL,
        target_2 REAL,
        status TEXT
    );
    """)

    cur.execute("""
    CREATE TABLE signal_prediction_snapshots (
        signal_id TEXT PRIMARY KEY,
        captured_at TEXT,
        snapshot_hash TEXT,
        score REAL,
        features_json TEXT,
        p_t1 REAL,
        p_t2 REAL,
        p_sl REAL,
        p_timeout REAL,
        calibration_version TEXT DEFAULT 'UNCALIBRATED'
    );
    """)

    cur.execute("""
    CREATE TABLE signal_forward_observations (
        forward_id INTEGER PRIMARY KEY AUTOINCREMENT,
        signal_id TEXT UNIQUE,
        cohort_id TEXT,
        registered_at TEXT,
        market_date TEXT,
        score REAL,
        score_bucket TEXT,
        direction TEXT,
        symbol TEXT,
        category TEXT,
        entry_price REAL,
        stop_loss REAL,
        target_1 REAL,
        target_2 REAL,
        snapshot_captured_at TEXT,
        snapshot_hash TEXT,
        observation_source TEXT,
        observation_status TEXT,
        data_quality_status TEXT,
        is_resolved INTEGER DEFAULT 0,
        terminal_outcome TEXT,
        resolution_timestamp TEXT,
        realized_r REAL,
        mfe_r REAL,
        mae_r REAL
    );
    """)

    conn.commit()
    conn.close()
    return db_file


@pytest.fixture
def isolated_config(tmp_path: Path) -> Path:
    """Create an isolated config.json file."""
    cfg_file = tmp_path / "config.json"
    cfg = {
        "EXECUTION_MODE": "SIGNAL_ONLY",
        "SIGNAL_ONLY": True,
        "LIVE_TRADING_LOCKOUT": True,
        "full_auto_allowed": False,
        "BOT_TOKEN": "test_token",
    }
    cfg_file.write_text(json.dumps(cfg), encoding="utf-8")
    return cfg_file


# ============================================================================
# 1. Market Calendar & Session Analysis Tests (5 tests)
# ============================================================================


def test_session_weekend_detected_closed():
    # Sunday: 2026-09-27 12:00:00 IST
    sunday_dt = datetime.datetime(2026, 9, 27, 12, 0, 0)
    info = get_market_session_info(dt=sunday_dt)
    assert info.is_trading_day is False
    assert info.session_status == "WEEKEND_CLOSED"
    assert info.day_of_week == "Sunday"


def test_session_saturday_detected_closed():
    # Saturday: 2026-09-26 10:00:00 IST
    saturday_dt = datetime.datetime(2026, 9, 26, 10, 0, 0)
    info = get_market_session_info(dt=saturday_dt)
    assert info.is_trading_day is False
    assert info.session_status == "WEEKEND_CLOSED"
    assert info.day_of_week == "Saturday"


def test_session_weekday_pre_session():
    # Monday 08:30:00 IST (before 09:15)
    monday_pre = datetime.datetime(2026, 9, 28, 8, 30, 0)
    info = get_market_session_info(dt=monday_pre)
    assert info.is_trading_day is True
    assert info.session_status == "PRE_SESSION"


def test_session_weekday_active():
    # Monday 11:30:00 IST (between 09:15 and 15:30)
    monday_active = datetime.datetime(2026, 9, 28, 11, 30, 0)
    info = get_market_session_info(dt=monday_active)
    assert info.is_trading_day is True
    assert info.session_status == "SESSION_ACTIVE"


def test_session_weekday_completed():
    # Monday 16:00:00 IST (after 15:30)
    monday_post = datetime.datetime(2026, 9, 28, 16, 0, 0)
    info = get_market_session_info(dt=monday_post)
    assert info.is_trading_day is True
    assert info.session_status == "SESSION_COMPLETED"


# ============================================================================
# 2. Forward Cohort Accounting Tests (5 tests)
# ============================================================================


def test_forward_cohort_zero_state(isolated_db: Path):
    reporter = ForwardAccumulationReporter(db_path=isolated_db)
    report = reporter.generate_report()
    assert report.forward_counts["registered"] == 0
    assert report.forward_counts["observing"] == 0
    assert report.forward_counts["resolved"] == 0
    assert report.forward_counts["stale"] == 0


def test_forward_cohort_observing_and_resolved(isolated_db: Path):
    conn = sqlite3.connect(str(isolated_db))
    cur = conn.cursor()
    # Insert 1 observing, 1 resolved (T1), 1 timeout
    cur.execute("""
    INSERT INTO signal_forward_observations (
        signal_id, cohort_id, registered_at, snapshot_captured_at, score, score_bucket,
        observation_source, observation_status, is_resolved, terminal_outcome
    ) VALUES
    ('SIG-01', 'FWD_2026-09', '2026-09-28T10:00:00+05:30', '2026-09-28T10:00:00+05:30', 82.0, '80-84', 'FORWARD_LIVE_SCAN', 'OBSERVING', 0, NULL),
    ('SIG-02', 'FWD_2026-09', '2026-09-28T10:05:00+05:30', '2026-09-28T10:05:00+05:30', 76.0, '75-79', 'FORWARD_LIVE_SCAN', 'RESOLVED', 1, 'TARGET_FIRST'),
    ('SIG-03', 'FWD_2026-09', '2026-09-28T10:10:00+05:30', '2026-09-28T10:10:00+05:30', 71.0, '70-74', 'FORWARD_LIVE_SCAN', 'TIMEOUT', 1, 'TIMEOUT');
    """)
    conn.commit()
    conn.close()

    reporter = ForwardAccumulationReporter(db_path=isolated_db)
    report = reporter.generate_report()
    assert report.forward_counts["registered"] == 3
    assert report.forward_counts["observing"] == 1
    assert report.forward_counts["resolved"] == 2
    assert report.forward_counts["timeout"] == 1


def test_forward_cohort_ambiguous_and_invalidated(isolated_db: Path):
    conn = sqlite3.connect(str(isolated_db))
    cur = conn.cursor()
    cur.execute("""
    INSERT INTO signal_forward_observations (
        signal_id, cohort_id, registered_at, snapshot_captured_at, score, score_bucket,
        observation_source, observation_status, is_resolved, terminal_outcome
    ) VALUES
    ('SIG-01', 'FWD_2026-09', '2026-09-28T10:00:00+05:30', '2026-09-28T10:00:00+05:30', 82.0, '80-84', 'FORWARD_LIVE_SCAN', 'AMBIGUOUS', 0, 'AMBIGUOUS_SAME_BAR'),
    ('SIG-02', 'FWD_2026-09', '2026-09-28T10:05:00+05:30', '2026-09-28T10:05:00+05:30', 76.0, '75-79', 'FORWARD_LIVE_SCAN', 'INVALIDATED', 0, 'INVALIDATED_GAP');
    """)
    conn.commit()
    conn.close()

    reporter = ForwardAccumulationReporter(db_path=isolated_db)
    report = reporter.generate_report()
    assert report.forward_counts["ambiguous"] == 1
    assert report.forward_counts["invalidated"] == 1


def test_forward_cohort_stale_detection(isolated_db: Path):
    conn = sqlite3.connect(str(isolated_db))
    cur = conn.cursor()
    # Registered 72 hours ago, still OBSERVING
    old_ts = (now_ist() - datetime.timedelta(hours=72)).isoformat()
    cur.execute(
        """
    INSERT INTO signal_forward_observations (
        signal_id, cohort_id, registered_at, snapshot_captured_at, score, score_bucket,
        observation_source, observation_status, is_resolved
    ) VALUES ('SIG-OLD', 'FWD_2026-09', ?, ?, 80.0, '80-84', 'FORWARD_LIVE_SCAN', 'OBSERVING', 0);
    """,
        (old_ts, old_ts),
    )
    conn.commit()
    conn.close()

    reporter = ForwardAccumulationReporter(db_path=isolated_db)
    report = reporter.generate_report()
    assert report.forward_counts["stale"] == 1
    assert report.data_quality["stale_rate"] == 1.0


def test_forward_cohort_no_data_accounting(isolated_db: Path):
    conn = sqlite3.connect(str(isolated_db))
    cur = conn.cursor()
    cur.execute("""
    INSERT INTO signal_forward_observations (
        signal_id, cohort_id, registered_at, snapshot_captured_at, score, score_bucket,
        observation_source, observation_status, is_resolved
    ) VALUES ('SIG-ND', 'FWD_2026-09', '2026-09-28T10:00:00+05:30', '2026-09-28T10:00:00+05:30', 75.0, '75-79', 'FORWARD_LIVE_SCAN', 'NO_DATA', 0);
    """)
    conn.commit()
    conn.close()

    reporter = ForwardAccumulationReporter(db_path=isolated_db)
    report = reporter.generate_report()
    assert report.forward_counts["no_data"] == 1


# ============================================================================
# 3. Score Bucket Auditing Tests (3 tests)
# ============================================================================


def test_canonical_score_buckets_distribution(isolated_db: Path):
    conn = sqlite3.connect(str(isolated_db))
    cur = conn.cursor()
    cur.execute("""
    INSERT INTO signal_forward_observations (
        signal_id, cohort_id, registered_at, snapshot_captured_at, score, score_bucket,
        observation_source, observation_status, is_resolved
    ) VALUES
    ('SIG-70', 'FWD_2026-09', '2026-09-28T10:00:00+05:30', '2026-09-28T10:00:00+05:30', 72.0, '70-74', 'FORWARD_LIVE_SCAN', 'RESOLVED', 1),
    ('SIG-75', 'FWD_2026-09', '2026-09-28T10:05:00+05:30', '2026-09-28T10:05:00+05:30', 77.0, '75-79', 'FORWARD_LIVE_SCAN', 'RESOLVED', 1),
    ('SIG-80', 'FWD_2026-09', '2026-09-28T10:10:00+05:30', '2026-09-28T10:10:00+05:30', 82.0, '80-84', 'FORWARD_LIVE_SCAN', 'RESOLVED', 1),
    ('SIG-85', 'FWD_2026-09', '2026-09-28T10:15:00+05:30', '2026-09-28T10:15:00+05:30', 88.0, '85+', 'FORWARD_LIVE_SCAN', 'RESOLVED', 1);
    """)
    conn.commit()
    conn.close()

    reporter = ForwardAccumulationReporter(db_path=isolated_db)
    report = reporter.generate_report()
    assert report.bucket_counts["70-74"]["registered"] == 1
    assert report.bucket_counts["75-79"]["registered"] == 1
    assert report.bucket_counts["80-84"]["registered"] == 1
    assert report.bucket_counts["85+"]["registered"] == 1


def test_anomaly_bucket_under_70_detected(isolated_db: Path):
    conn = sqlite3.connect(str(isolated_db))
    cur = conn.cursor()
    cur.execute("""
    INSERT INTO signal_forward_observations (
        signal_id, cohort_id, registered_at, snapshot_captured_at, score, score_bucket,
        observation_source, observation_status, is_resolved
    ) VALUES
    ('SIG-SUB70', 'FWD_2026-09', '2026-09-28T10:00:00+05:30', '2026-09-28T10:00:00+05:30', 65.0, '<70', 'FORWARD_LIVE_SCAN', 'OBSERVING', 0);
    """)
    conn.commit()
    conn.close()

    reporter = ForwardAccumulationReporter(db_path=isolated_db)
    report = reporter.generate_report()
    assert report.anomaly_bucket_count == 1


def test_anomaly_bucket_not_counted_toward_g1(isolated_db: Path):
    conn = sqlite3.connect(str(isolated_db))
    cur = conn.cursor()
    cur.execute("""
    INSERT INTO signal_forward_observations (
        signal_id, cohort_id, registered_at, snapshot_captured_at, score, score_bucket,
        observation_source, observation_status, is_resolved
    ) VALUES
    ('SIG-SUB70', 'FWD_2026-09', '2026-09-28T10:00:00+05:30', '2026-09-28T10:00:00+05:30', 65.0, '<70', 'FORWARD_LIVE_SCAN', 'RESOLVED', 1);
    """)
    conn.commit()
    conn.close()

    reporter = ForwardAccumulationReporter(db_path=isolated_db)
    report = reporter.generate_report()
    g1 = report.gates.get("G1", {})
    # Active buckets in G1 are strictly 70-74, 75-79, 80-84, 85+
    assert "<70" not in g1.get("actual", {})
    assert g1.get("passed") is False


# ============================================================================
# 4. Gate Status Evaluation Tests (4 tests)
# ============================================================================


def test_gates_fail_when_sample_size_zero(isolated_db: Path):
    reporter = ForwardAccumulationReporter(db_path=isolated_db)
    report = reporter.generate_report()
    assert report.gates["G1"]["passed"] is False
    assert report.gates["G2"]["passed"] is False
    assert report.gates["G3"]["passed"] is False
    assert report.gates["G4"]["passed"] is True  # 0% error rate passes G4


def test_all_gates_pass_in_controlled_fixture(tmp_path: Path):
    # Create controlled in-memory / temp DB with >= 100 resolved per bucket, >= 300 total, >= 2 months
    db_file = tmp_path / "all_gates_pass.db"
    conn = sqlite3.connect(str(db_file))
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE signal_forward_observations (
        forward_id INTEGER PRIMARY KEY AUTOINCREMENT,
        signal_id TEXT UNIQUE,
        cohort_id TEXT,
        registered_at TEXT,
        market_date TEXT,
        score REAL,
        score_bucket TEXT,
        direction TEXT,
        symbol TEXT,
        category TEXT,
        entry_price REAL,
        stop_loss REAL,
        target_1 REAL,
        target_2 REAL,
        snapshot_captured_at TEXT,
        snapshot_hash TEXT,
        observation_source TEXT,
        observation_status TEXT,
        data_quality_status TEXT,
        is_resolved INTEGER DEFAULT 0,
        terminal_outcome TEXT,
        resolution_timestamp TEXT,
        realized_r REAL,
        mfe_r REAL,
        mae_r REAL
    );
    """)

    # Populate 100 in each of 4 buckets across 2 cohorts: FWD_2026-09 and FWD_2026-10
    buckets = ["70-74", "75-79", "80-84", "85+"]
    sig_idx = 0
    for b in buckets:
        for i in range(100):
            sig_idx += 1
            cohort = "FWD_2026-09" if i < 50 else "FWD_2026-10"
            m_date = "2026-09-28" if i < 50 else "2026-10-15"
            ts = f"{m_date}T10:00:00+05:30"
            cur.execute(
                """
            INSERT INTO signal_forward_observations (
                signal_id, cohort_id, registered_at, snapshot_captured_at, score, score_bucket,
                observation_source, observation_status, data_quality_status, is_resolved, terminal_outcome
            ) VALUES (?, ?, ?, ?, 80.0, ?, 'FORWARD_LIVE_SCAN', 'RESOLVED', 'VALID_DATA', 1, 'TARGET_FIRST')
            """,
                (f"SIG-{sig_idx:04d}", cohort, ts, ts, b),
            )

    conn.commit()
    conn.close()

    # Verify gates evaluate to true
    svc = SignalForwardMonitorService.get_instance(db_path=db_file)
    gates = svc.get_readiness_gate_status()
    assert gates["G1"]["passed"] is True
    assert gates["G2"]["passed"] is True
    assert gates["G3"]["passed"] is True
    assert gates["G4"]["passed"] is True


def test_partial_gates_state_g2_fail_g1_fail(isolated_db: Path):
    conn = sqlite3.connect(str(isolated_db))
    cur = conn.cursor()
    # 50 resolved in 85+ (not enough for 100, and total 50 < 300)
    for i in range(50):
        cur.execute(
            """
        INSERT INTO signal_forward_observations (
            signal_id, cohort_id, registered_at, snapshot_captured_at, score, score_bucket,
            observation_source, observation_status, data_quality_status, is_resolved, terminal_outcome
        ) VALUES (?, 'FWD_2026-09', '2026-09-28T10:00:00+05:30', '2026-09-28T10:00:00+05:30', 88.0, '85+', 'FORWARD_LIVE_SCAN', 'RESOLVED', 'VALID_DATA', 1, 'TARGET_FIRST')
        """,
            (f"SIG-{i}",),
        )
    conn.commit()
    conn.close()

    reporter = ForwardAccumulationReporter(db_path=isolated_db)
    report = reporter.generate_report()
    assert report.gates["G1"]["passed"] is False
    assert report.gates["G2"]["passed"] is False


def test_gate_4_fails_when_dq_error_exceeds_threshold(isolated_db: Path):
    conn = sqlite3.connect(str(isolated_db))
    cur = conn.cursor()
    # 10 observations, 2 are NO_DATA (20% > 5%)
    for i in range(8):
        cur.execute(
            """
        INSERT INTO signal_forward_observations (
            signal_id, cohort_id, registered_at, snapshot_captured_at, score, score_bucket,
            observation_source, observation_status, is_resolved
        ) VALUES (?, 'FWD_2026-09', '2026-09-28T10:00:00+05:30', '2026-09-28T10:00:00+05:30', 80.0, '80-84', 'FORWARD_LIVE_SCAN', 'RESOLVED', 1);
        """,
            (f"SIG-OK-{i}",),
        )
    for i in range(2):
        cur.execute(
            """
        INSERT INTO signal_forward_observations (
            signal_id, cohort_id, registered_at, snapshot_captured_at, score, score_bucket,
            observation_source, observation_status, is_resolved
        ) VALUES (?, 'FWD_2026-09', '2026-09-28T10:00:00+05:30', '2026-09-28T10:00:00+05:30', 80.0, '80-84', 'FORWARD_LIVE_SCAN', 'NO_DATA', 0);
        """,
            (f"SIG-BAD-{i}",),
        )
    conn.commit()
    conn.close()

    reporter = ForwardAccumulationReporter(db_path=isolated_db)
    report = reporter.generate_report()
    assert report.gates["G4"]["passed"] is False


# ============================================================================
# 5. Integrity Audit Tests (6 tests)
# ============================================================================


def test_integrity_clean_when_empty(isolated_db: Path):
    audit = audit_forward_integrity(db_path=isolated_db)
    assert audit.is_clean is True
    assert audit.violations == []


def test_integrity_detects_pre_cutoff_violation(isolated_db: Path):
    conn = sqlite3.connect(str(isolated_db))
    cur = conn.cursor()
    cur.execute("""
    INSERT INTO signal_forward_observations (
        signal_id, cohort_id, registered_at, snapshot_captured_at, score, score_bucket,
        observation_source, observation_status
    ) VALUES ('SIG-OLD', 'FWD_2026-09', '2026-09-25T10:00:00+05:30', '2026-09-25T10:00:00+05:30', 80.0, '80-84', 'FORWARD_LIVE_SCAN', 'OBSERVING');
    """)
    conn.commit()
    conn.close()

    audit = audit_forward_integrity(db_path=isolated_db)
    assert audit.is_clean is False
    assert audit.pre_cutoff_count == 1
    assert any("PRE_CUTOFF_VIOLATION" in v for v in audit.violations)


def test_integrity_detects_seed_contamination(isolated_db: Path):
    conn = sqlite3.connect(str(isolated_db))
    cur = conn.cursor()
    cur.execute("""
    INSERT INTO signal_forward_observations (
        signal_id, cohort_id, registered_at, snapshot_captured_at, score, score_bucket,
        observation_source, observation_status
    ) VALUES ('SIG-SEED', 'FWD_2026-09', '2026-09-28T10:00:00+05:30', '2026-09-28T10:00:00+05:30', 80.0, '80-84', 'SEED_HISTORICAL', 'OBSERVING');
    """)
    conn.commit()
    conn.close()

    audit = audit_forward_integrity(db_path=isolated_db)
    assert audit.is_clean is False
    assert audit.seed_contamination_count == 1
    assert any("SEED_CONTAMINATION" in v for v in audit.violations)


def test_integrity_detects_historical_contamination(isolated_db: Path):
    conn = sqlite3.connect(str(isolated_db))
    cur = conn.cursor()
    # Insert pre-cutoff signal into system_signals
    cur.execute("""
    INSERT INTO system_signals (signal_id, timestamp, score)
    VALUES ('SIG-HIST-01', '2026-09-20T10:00:00+05:30', 85.0);
    """)
    # Insert the same signal into signal_forward_observations
    cur.execute("""
    INSERT INTO signal_forward_observations (
        signal_id, cohort_id, registered_at, snapshot_captured_at, score, score_bucket,
        observation_source, observation_status
    ) VALUES ('SIG-HIST-01', 'FWD_2026-09', '2026-09-28T10:00:00+05:30', '2026-09-28T10:00:00+05:30', 85.0, '85+', 'FORWARD_LIVE_SCAN', 'OBSERVING');
    """)
    conn.commit()
    conn.close()

    audit = audit_forward_integrity(db_path=isolated_db)
    assert audit.is_clean is False
    assert audit.historical_contamination_count == 1
    assert any("HISTORICAL_CONTAMINATION" in v for v in audit.violations)


def test_integrity_detects_forbidden_feature_leakage(isolated_db: Path):
    conn = sqlite3.connect(str(isolated_db))
    cur = conn.cursor()
    bad_features = json.dumps({"rsi": 55.0, "target_1_hit": 1})
    cur.execute(
        """
    INSERT INTO signal_prediction_snapshots (signal_id, captured_at, score, features_json)
    VALUES ('SIG-SNAP-01', '2026-09-28T10:00:00+05:30', 80.0, ?);
    """,
        (bad_features,),
    )
    conn.commit()
    conn.close()

    audit = audit_forward_integrity(db_path=isolated_db)
    assert audit.is_clean is False
    assert audit.feature_leakage_count == 1
    assert any("FEATURE_OUTCOME_LEAKAGE" in v for v in audit.violations)


def test_integrity_detects_probability_leakage(isolated_db: Path):
    conn = sqlite3.connect(str(isolated_db))
    cur = conn.cursor()
    cur.execute("""
    INSERT INTO signal_prediction_snapshots (signal_id, captured_at, score, p_t1)
    VALUES ('SIG-SNAP-01', '2026-09-28T10:00:00+05:30', 80.0, 0.75);
    """)
    conn.commit()
    conn.close()

    audit = audit_forward_integrity(db_path=isolated_db)
    assert audit.is_clean is False
    assert audit.probability_leakage_count == 1
    assert any("PROBABILITY_LEAKAGE" in v for v in audit.violations)


# ============================================================================
# 6. Safety Audit Tests (3 tests)
# ============================================================================


def test_safety_audit_passes_on_compliant_config(isolated_config: Path):
    res = audit_production_safety(config_path=isolated_config)
    assert res.is_safe is True
    assert res.execution_mode == "SIGNAL_ONLY"
    assert res.signal_only is True
    assert res.live_trading_lockout is True
    assert res.full_auto_allowed is False


def test_safety_audit_fails_on_execution_mode_mutation(tmp_path: Path):
    cfg_file = tmp_path / "bad_config.json"
    cfg = {
        "EXECUTION_MODE": "AUTO",
        "SIGNAL_ONLY": True,
        "LIVE_TRADING_LOCKOUT": True,
        "full_auto_allowed": False,
    }
    cfg_file.write_text(json.dumps(cfg), encoding="utf-8")

    res = audit_production_safety(config_path=cfg_file)
    assert res.is_safe is False
    assert any("EXECUTION_MODE" in v for v in res.violations)


def test_safety_audit_fails_on_lockout_disabled(tmp_path: Path):
    cfg_file = tmp_path / "bad_lockout.json"
    cfg = {
        "EXECUTION_MODE": "SIGNAL_ONLY",
        "SIGNAL_ONLY": True,
        "LIVE_TRADING_LOCKOUT": False,
        "full_auto_allowed": False,
    }
    cfg_file.write_text(json.dumps(cfg), encoding="utf-8")

    res = audit_production_safety(config_path=cfg_file)
    assert res.is_safe is False
    assert any("LIVE_TRADING_LOCKOUT" in v for v in res.violations)


# ============================================================================
# 7. Operational State / Verdict Mapping Tests (4 tests)
# ============================================================================


def test_verdict_waiting_for_market_session_on_weekend(isolated_db: Path, isolated_config: Path):
    reporter = ForwardAccumulationReporter(db_path=isolated_db, config_path=isolated_config)
    sunday_dt = datetime.datetime(2026, 9, 27, 12, 0, 0)
    report = reporter.generate_report(dt=sunday_dt)
    assert report.operational_state == STATE_WAITING_FOR_MARKET_SESSION


def test_verdict_accumulation_active_during_weekday_session(isolated_db: Path, isolated_config: Path):
    reporter = ForwardAccumulationReporter(db_path=isolated_db, config_path=isolated_config)
    monday_active = datetime.datetime(2026, 9, 28, 11, 0, 0)
    report = reporter.generate_report(dt=monday_active)
    assert report.operational_state == STATE_ACCUMULATION_ACTIVE


def test_verdict_blocked_on_integrity_violation(isolated_db: Path, isolated_config: Path):
    conn = sqlite3.connect(str(isolated_db))
    cur = conn.cursor()
    # Inject seed contamination
    cur.execute("""
    INSERT INTO signal_forward_observations (
        signal_id, cohort_id, registered_at, snapshot_captured_at, score, score_bucket,
        observation_source, observation_status
    ) VALUES ('SIG-TEST', 'FWD_2026-09', '2026-09-28T10:00:00+05:30', '2026-09-28T10:00:00+05:30', 80.0, '80-84', 'SEED_HISTORICAL', 'OBSERVING');
    """)
    conn.commit()
    conn.close()

    reporter = ForwardAccumulationReporter(db_path=isolated_db, config_path=isolated_config)
    report = reporter.generate_report()
    assert report.operational_state == STATE_ACCUMULATION_BLOCKED


def test_verdict_phase_e_ready_when_all_gates_pass(tmp_path: Path, isolated_config: Path):
    db_file = tmp_path / "all_gates.db"
    conn = sqlite3.connect(str(db_file))
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE signal_forward_observations (
        forward_id INTEGER PRIMARY KEY AUTOINCREMENT,
        signal_id TEXT UNIQUE,
        cohort_id TEXT,
        registered_at TEXT,
        market_date TEXT,
        score REAL,
        score_bucket TEXT,
        direction TEXT,
        symbol TEXT,
        category TEXT,
        entry_price REAL,
        stop_loss REAL,
        target_1 REAL,
        target_2 REAL,
        snapshot_captured_at TEXT,
        snapshot_hash TEXT,
        observation_source TEXT,
        observation_status TEXT,
        data_quality_status TEXT,
        is_resolved INTEGER DEFAULT 0,
        terminal_outcome TEXT,
        resolution_timestamp TEXT,
        realized_r REAL,
        mfe_r REAL,
        mae_r REAL
    );
    """)

    # Populate 100 in each bucket across 2 cohorts
    buckets = ["70-74", "75-79", "80-84", "85+"]
    sig_idx = 0
    for b in buckets:
        for i in range(100):
            sig_idx += 1
            cohort = "FWD_2026-09" if i < 50 else "FWD_2026-10"
            m_date = "2026-09-28" if i < 50 else "2026-10-15"
            ts = f"{m_date}T10:00:00+05:30"
            cur.execute(
                """
            INSERT INTO signal_forward_observations (
                signal_id, cohort_id, registered_at, snapshot_captured_at, score, score_bucket,
                observation_source, observation_status, data_quality_status, is_resolved, terminal_outcome
            ) VALUES (?, ?, ?, ?, 80.0, ?, 'FORWARD_LIVE_SCAN', 'RESOLVED', 'VALID_DATA', 1, 'TARGET_FIRST')
            """,
                (f"SIG-{sig_idx:04d}", cohort, ts, ts, b),
            )

    conn.commit()
    conn.close()

    reporter = ForwardAccumulationReporter(db_path=db_file, config_path=isolated_config)
    report = reporter.generate_report()
    assert report.operational_state == STATE_PHASE_E_EMPIRICAL_EXECUTION_READY


# ============================================================================
# 8. Report Serialization & Artifact Generation Tests (3 tests)
# ============================================================================


def test_markdown_report_rendering(isolated_db: Path, isolated_config: Path):
    reporter = ForwardAccumulationReporter(db_path=isolated_db, config_path=isolated_config)
    report = reporter.generate_report()
    md = reporter.render_markdown(report)
    assert "# OPB v2.60" in md
    assert "Forward Accumulation Daily Report" in md
    assert "Forward Cutoff" in md
    assert "Score Buckets" in md
    assert "Gates Status" in md
    assert "Final Operational State" in md


def test_report_artifact_files_saving(tmp_path: Path, isolated_db: Path, isolated_config: Path):
    art_dir = tmp_path / "artifacts"
    reporter = ForwardAccumulationReporter(
        db_path=isolated_db,
        config_path=isolated_config,
        artifacts_dir=art_dir,
    )
    report = reporter.generate_report()
    md_path, json_path = reporter.save_reports(report)

    assert md_path.is_file()
    assert json_path.is_file()

    loaded_json = json.loads(json_path.read_text(encoding="utf-8"))
    assert loaded_json["forward_cutoff"] == DEFAULT_FORWARD_CUTOFF_ISO
    assert "gates" in loaded_json
    assert "integrity" in loaded_json
    assert "safety" in loaded_json


def test_cli_execution_returns_zero(tmp_path: Path, isolated_db: Path, isolated_config: Path):
    reporter = ForwardAccumulationReporter(
        db_path=isolated_db,
        config_path=isolated_config,
        artifacts_dir=tmp_path,
    )
    code = reporter.run_cli()
    assert code == 0


# ============================================================================
# 9. Production Database Read-Only Integration Test (1 test)
# ============================================================================


def test_production_db_read_only_execution():
    """Verify that the reporter executes against db/signals_history.db strictly read-only."""
    prod_db = Path("db/signals_history.db")
    if not prod_db.is_file():
        pytest.skip("Production database db/signals_history.db not found.")

    import hashlib

    hash_pre = hashlib.sha256(prod_db.read_bytes()).hexdigest()

    conn_pre = sqlite3.connect(str(prod_db))
    cur_pre = conn_pre.cursor()
    cur_pre.execute("SELECT count(*) FROM signal_forward_observations")
    count_pre = cur_pre.fetchone()[0]
    conn_pre.close()

    reporter = ForwardAccumulationReporter(db_path=prod_db)
    report = reporter.generate_report()

    hash_post = hashlib.sha256(prod_db.read_bytes()).hexdigest()
    assert hash_pre == hash_post, "Production database was modified during reporter execution!"

    conn_post = sqlite3.connect(str(prod_db))
    cur_post = conn_post.cursor()
    cur_post.execute("SELECT count(*) FROM signal_forward_observations")
    count_post = cur_post.fetchone()[0]
    conn_post.close()

    assert count_pre == count_post, "Production database row counts modified during reporter execution!"
    assert report.forward_counts["registered"] == count_post
    assert report.forward_counts["registered"] >= 0
    assert report.gates["G1"]["passed"] is False
    assert report.gates["G2"]["passed"] is False
    assert report.gates["G3"]["passed"] is False
    assert report.data_quality["dq_error_rate"] <= 0.05
    assert report.gates["G4"]["status"] in ("PASS", "FAIL")
    assert report.integrity.is_clean is True
    assert report.safety.is_safe is True
    if report.session_status in ("SESSION_ACTIVE", "SESSION_COMPLETED") or (
        report.session_status == "PRE_SESSION" and report.forward_counts["registered"] > 0
    ):
        assert report.operational_state == STATE_ACCUMULATION_ACTIVE
    else:
        assert report.operational_state == STATE_WAITING_FOR_MARKET_SESSION
