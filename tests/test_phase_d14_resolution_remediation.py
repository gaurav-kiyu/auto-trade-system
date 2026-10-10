"""Regression & Verification Test Suite for Phase D.14 Resolution-Bypass Remediation.

Governance Authority: OPB-FINAL-PHASE-GOVERNANCE-001
Blocker Remediated: BLK-PHASE-D13-UNRESOLVED-MEASUREMENT-BYPASS

Verifies:
- TEST 1: Existing UNRESOLVED measurement correctly resolves to TARGET_FIRST with MFE/MAE and Realized-R.
- TEST 2: Existing UNRESOLVED measurement correctly resolves to SL_FIRST with Realized-R.
- TEST 3: Existing UNRESOLVED measurement correctly materializes canonical TIMEOUT via Phase B.
- TEST 4: Terminal measurements (TARGET_FIRST, SL_FIRST, TIMEOUT, AMBIGUOUS, NO_DATA, INVALIDATED) remain 100% immutable and unmutated.
- TEST 5: UNRESOLVED measurement without terminal price event safely re-evaluates and remains UNRESOLVED (is_resolved=0).
- TEST 6: system_signals.EXPIRED without valid Phase-B canonical outcome does NOT cause false Phase-D forward resolution.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest
from core.datetime_ist import now_ist
from core.signals.signal_forward_observation import (
    SignalForwardObservationService,
)
from core.signals.signal_outcome_dataset import (
    SignalOutcomeDatasetService,
)
from core.signals.signal_outcome_tracker import SignalOutcomeTracker
from core.signals.signal_tracker import SignalTracker


@pytest.fixture(autouse=True)
def clean_environment():
    """Ensure singleton isolation and clean environment before and after each test."""
    orig_env = dict(os.environ)
    SignalTracker.reset_instance()
    SignalOutcomeTracker.reset_instance()
    SignalOutcomeDatasetService.reset_instance()
    SignalForwardObservationService.reset_instance()
    yield
    SignalTracker.reset_instance()
    SignalOutcomeTracker.reset_instance()
    SignalOutcomeDatasetService.reset_instance()
    SignalForwardObservationService.reset_instance()
    for k in list(os.environ):
        if k not in orig_env:
            del os.environ[k]
        elif os.environ[k] != orig_env[k]:
            os.environ[k] = orig_env[k]


@pytest.fixture
def temp_db(tmp_path: Path) -> Path:
    """Create an isolated test database with all schemas initialized."""
    db_file = tmp_path / "d14_remediation_test.db"
    SignalTracker(db_path=db_file)
    SignalOutcomeTracker(db_path=db_file)
    SignalOutcomeDatasetService(db_path=db_file)
    SignalForwardObservationService(db_path=db_file)
    return db_file


def _create_sample_signal(tracker: SignalTracker, symbol: str = "TCS", price: float = 3500.0, score: int = 82) -> str:
    """Helper to record a valid forward signal."""
    sig_data = {
        "symbol": symbol,
        "company_name": f"{symbol} India Ltd",
        "direction": "CALL",
        "price": price,
        "score": score,
        "raw_score": float(score),
        "tier": "STRONG",
        "category": "LARGE_CAP_EQUITY",
        "regime": "TRENDING_BULLISH",
        "stop_loss": price - 50.0,
        "target_1": price + 100.0,
        "target_2": price + 200.0,
        "features": {"rsi": 62.5, "adx": 28.0, "price": price},
        "observation_source": "FORWARD_LIVE_SCAN",
    }
    return tracker.record_generated_signal(sig_data)


def test_1_unresolved_to_target_first(temp_db: Path):
    """TEST 1: Existing UNRESOLVED measurement resolves to TARGET_FIRST upon target hit."""
    tracker = SignalTracker(db_path=temp_db)
    fwd_service = SignalForwardObservationService(db_path=temp_db)
    phase_b_service = SignalOutcomeDatasetService(db_path=temp_db)

    sig_id = _create_sample_signal(tracker, "INFY", price=1500.0)

    # 1. Populate an existing UNRESOLVED measurement in signal_outcome_measurements
    phase_b_service.build_signal_outcome_measurement(sig_id)
    meas_initial = phase_b_service.get_outcome_measurement(sig_id)
    assert meas_initial is not None
    assert meas_initial["outcome"] == "UNRESOLVED"

    # Forward observation is in-flight
    obs_initial = fwd_service.get_forward_observation(sig_id)
    assert obs_initial is not None
    assert obs_initial["observation_status"] == "OBSERVING"
    assert obs_initial["is_resolved"] == 0

    # 2. Simulate canonical price hit in system_signals with native timestamp
    # Under v2.60 lifecycle semantics (RFC-OPB-V260-LIFECYCLE-001):
    # TARGET_1_HIT is an interim milestone (trade in-flight towards T2, terminal exit pending).
    # TARGET_2_HIT represents canonical terminal target resolution where realized_r is materialized.
    now_str = now_ist().strftime("%Y-%m-%d %H:%M:%S")
    conn = sqlite3.connect(str(temp_db))
    conn.execute("""
        UPDATE system_signals
        SET status = 'TARGET_1_HIT',
            first_touch = 'T1',
            first_touch_at = ?,
            first_touch_price = 1600.0,
            current_price = 1605.0
        WHERE signal_id = ?
    """, (now_str, sig_id))
    conn.commit()
    conn.close()

    # Verify interim milestone state: outcome is TARGET_FIRST, but trade is in-flight (realized_r is None)
    fwd_service.sync_forward_outcomes()
    meas_interim = phase_b_service.get_outcome_measurement(sig_id)
    assert meas_interim is not None
    assert meas_interim["outcome"] == "TARGET_FIRST"
    assert meas_interim["mfe_r"] is not None and meas_interim["mfe_r"] > 0
    assert meas_interim["realized_r"] is None
    obs_interim = fwd_service.get_forward_observation(sig_id)
    assert obs_interim is not None
    assert obs_interim["observation_status"] == "OBSERVING"
    assert obs_interim["is_resolved"] == 0

    # Progress to terminal target (TARGET_2_HIT)
    conn = sqlite3.connect(str(temp_db))
    conn.execute("""
        UPDATE system_signals
        SET status = 'TARGET_2_HIT',
            current_price = 1705.0
        WHERE signal_id = ?
    """, (sig_id,))
    conn.commit()
    conn.close()

    # 3. Call sync_forward_outcomes() for terminal resolution
    updated_cnt = fwd_service.sync_forward_outcomes()
    assert updated_cnt >= 1

    # 4. Verify Phase B materialized TARGET_FIRST
    meas_after = phase_b_service.get_outcome_measurement(sig_id)
    assert meas_after is not None
    assert meas_after["outcome"] == "TARGET_FIRST"
    assert meas_after["mfe_r"] is not None and meas_after["mfe_r"] > 0
    assert meas_after["realized_r"] is not None

    # 5. Verify Forward observation transitioned to RESOLVED
    obs_after = fwd_service.get_forward_observation(sig_id)
    assert obs_after is not None
    assert obs_after["observation_status"] == "RESOLVED"
    assert obs_after["terminal_outcome"] == "TARGET_FIRST"
    assert obs_after["is_resolved"] == 1
    assert obs_after["realized_r"] == meas_after["realized_r"]


def test_2_unresolved_to_sl_first(temp_db: Path):
    """TEST 2: Existing UNRESOLVED measurement resolves to SL_FIRST upon stop-loss hit."""
    tracker = SignalTracker(db_path=temp_db)
    fwd_service = SignalForwardObservationService(db_path=temp_db)
    phase_b_service = SignalOutcomeDatasetService(db_path=temp_db)

    sig_id = _create_sample_signal(tracker, "RELIANCE", price=2500.0)

    # Initial UNRESOLVED measurement
    phase_b_service.build_signal_outcome_measurement(sig_id)
    meas_initial = phase_b_service.get_outcome_measurement(sig_id)
    assert meas_initial["outcome"] == "UNRESOLVED"

    now_str = now_ist().strftime("%Y-%m-%d %H:%M:%S")
    # Simulate canonical SL event in system_signals
    conn = sqlite3.connect(str(temp_db))
    conn.execute("""
        UPDATE system_signals
        SET status = 'SL_HIT',
            first_touch = 'SL',
            first_touch_at = ?,
            first_touch_price = 2450.0,
            current_price = 2448.0
        WHERE signal_id = ?
    """, (now_str, sig_id))
    conn.commit()
    conn.close()

    # Synchronize forward outcomes
    fwd_service.sync_forward_outcomes()

    # Verify measurement is SL_FIRST
    meas_after = phase_b_service.get_outcome_measurement(sig_id)
    assert meas_after["outcome"] == "SL_FIRST"
    assert meas_after["realized_r"] is not None
    assert meas_after["realized_r"] <= 0

    # Verify forward observation is resolved
    obs_after = fwd_service.get_forward_observation(sig_id)
    assert obs_after["observation_status"] == "RESOLVED"
    assert obs_after["terminal_outcome"] == "SL_FIRST"
    assert obs_after["is_resolved"] == 1


def test_3_unresolved_to_timeout(temp_db: Path):
    """TEST 3: Existing UNRESOLVED measurement materializes canonical TIMEOUT via Phase B."""
    tracker = SignalTracker(db_path=temp_db)
    fwd_service = SignalForwardObservationService(db_path=temp_db)
    phase_b_service = SignalOutcomeDatasetService(db_path=temp_db)

    sig_id = _create_sample_signal(tracker, "HDFCBANK", price=1600.0)

    # Initial UNRESOLVED measurement
    phase_b_service.build_signal_outcome_measurement(sig_id)

    now_str = now_ist().strftime("%Y-%m-%d %H:%M:%S")
    # Simulate legitimate holding horizon expiry in system_signals
    conn = sqlite3.connect(str(temp_db))
    conn.execute("""
        UPDATE system_signals
        SET status = 'EXPIRED',
            first_touch = 'EXPIRED',
            first_touch_at = ?,
            first_touch_price = 1610.0,
            current_price = 1610.0
        WHERE signal_id = ?
    """, (now_str, sig_id))
    conn.commit()
    conn.close()

    fwd_service.sync_forward_outcomes()

    # Verify Phase B canonical outcome is TIMEOUT
    meas_after = phase_b_service.get_outcome_measurement(sig_id)
    assert meas_after["outcome"] == "TIMEOUT"
    assert meas_after["realized_r"] is not None

    # Verify forward observation resolved as TIMEOUT
    obs_after = fwd_service.get_forward_observation(sig_id)
    assert obs_after["observation_status"] == "TIMEOUT"
    assert obs_after["terminal_outcome"] == "TIMEOUT"
    assert obs_after["is_resolved"] == 1


def test_4_terminal_immutability(temp_db: Path):
    """TEST 4: Terminal measurements remain 100% immutable and are NOT recomputed."""
    fwd_service = SignalForwardObservationService(db_path=temp_db)
    phase_b_service = SignalOutcomeDatasetService(db_path=temp_db)

    terminals = ["TARGET_FIRST", "SL_FIRST", "TIMEOUT", "AMBIGUOUS", "NO_DATA", "INVALIDATED"]
    sig_ids = []

    conn = sqlite3.connect(str(temp_db))
    now_str = now_ist().strftime("%Y-%m-%d %H:%M:%S")

    for idx, term in enumerate(terminals):
        s_id = f"SIG-TERM-{term}-{idx}"
        sig_ids.append(s_id)
        # Insert prediction snapshot with all required columns
        conn.execute("""
            INSERT INTO signal_prediction_snapshots (
                signal_id, captured_at, snapshot_schema_version, engine_version,
                symbol, category, direction, strategy, score, tier, entry_price, stop_loss, target_1, target_2,
                snapshot_hash, source, created_at
            ) VALUES (?, ?, 'v1.0', '2.60.0', 'TEST_SYM', 'EQUITY', 'CALL', 'test', 80, 'STRONG', 100, 95, 105, 110, 'hash', 'FORWARD_LIVE_SCAN', ?)
        """, (s_id, now_str, now_str))

        conn.commit()
        fwd_service.register_forward_signal(s_id)

        # Update to terminal state
        is_res = 1 if term in ("TARGET_FIRST", "SL_FIRST", "TIMEOUT") else 0
        conn.execute("""
            INSERT OR REPLACE INTO signal_outcome_measurements (
                signal_id, prediction_snapshot_id, symbol, category, direction,
                entry_price, stop_loss, target_1, target_2, observed_from,
                outcome, raw_lifecycle_state, realized_r, calculated_at
            ) VALUES (?, ?, 'TEST_SYM', 'EQUITY', 'CALL', 100, 95, 105, 110, ?, ?, ?, 1.0, '2026-09-28 10:00:00')
        """, (s_id, s_id, now_str, term, term))
        conn.execute("""
            UPDATE signal_forward_observations
            SET observation_status = ?,
                terminal_outcome = ?,
                is_resolved = ?
            WHERE signal_id = ?
        """, (term, term, is_res, s_id))
        conn.commit()

    # Capture measurements state before sync
    measurements_before = {
        s_id: conn.execute("SELECT * FROM signal_outcome_measurements WHERE signal_id = ?", (s_id,)).fetchone()
        for s_id in sig_ids
    }
    conn.close()

    # Patch build_signal_outcome_measurement to detect if it gets called unnecessarily
    with patch.object(phase_b_service, "build_signal_outcome_measurement", wraps=phase_b_service.build_signal_outcome_measurement) as mock_b:
        fwd_service.sync_forward_outcomes()
        # Mock must NOT have been called for any of these terminal measurements
        mock_b.assert_not_called()

    # Verify measurements are bit-for-bit unchanged
    conn = sqlite3.connect(str(temp_db))
    for s_id in sig_ids:
        row_after = conn.execute("SELECT * FROM signal_outcome_measurements WHERE signal_id = ?", (s_id,)).fetchone()
        assert row_after == measurements_before[s_id], f"Terminal measurement {s_id} was mutated!"
    conn.close()


def test_5_unresolved_remains_unresolved_without_event(temp_db: Path):
    """TEST 5: UNRESOLVED measurement without terminal event re-evaluates safely and remains UNRESOLVED."""
    tracker = SignalTracker(db_path=temp_db)
    fwd_service = SignalForwardObservationService(db_path=temp_db)
    phase_b_service = SignalOutcomeDatasetService(db_path=temp_db)

    sig_id = _create_sample_signal(tracker, "SBIN", price=800.0)

    # Initial UNRESOLVED measurement
    phase_b_service.build_signal_outcome_measurement(sig_id)

    # Signal remains ACTIVE with no barrier hit
    fwd_service.sync_forward_outcomes()

    # Measurement must remain UNRESOLVED
    meas = phase_b_service.get_outcome_measurement(sig_id)
    assert meas["outcome"] == "UNRESOLVED"

    # Forward observation must remain in OBSERVING (is_resolved = 0)
    obs = fwd_service.get_forward_observation(sig_id)
    assert obs["observation_status"] == "OBSERVING"
    assert obs["terminal_outcome"] == "UNRESOLVED"
    assert obs["is_resolved"] == 0


def test_6_expired_without_phase_b_timeout_safety(temp_db: Path):
    """TEST 6: system_signals.EXPIRED without valid Phase-B outcome does NOT cause false Phase-D forward resolution."""
    tracker = SignalTracker(db_path=temp_db)
    fwd_service = SignalForwardObservationService(db_path=temp_db)
    phase_b_service = SignalOutcomeDatasetService(db_path=temp_db)

    sig_id = _create_sample_signal(tracker, "WIPRO", price=500.0)
    phase_b_service.build_signal_outcome_measurement(sig_id)

    # Set status = 'EXPIRED' in system_signals, but corrupt prediction snapshot parameters so Phase B classifies as INVALIDATED
    conn = sqlite3.connect(str(temp_db))
    conn.execute("""
        UPDATE signal_prediction_snapshots
        SET entry_price = 0.0,
            stop_loss = 0.0
        WHERE signal_id = ?
    """, (sig_id,))
    conn.execute("""
        UPDATE system_signals
        SET status = 'EXPIRED',
            first_touch = 'EXPIRED'
        WHERE signal_id = ?
    """, (sig_id,))
    conn.commit()
    conn.close()

    fwd_service.sync_forward_outcomes()

    # Phase B classifies invalid parameters as INVALIDATED, NOT TIMEOUT
    meas = phase_b_service.get_outcome_measurement(sig_id)
    assert meas["outcome"] == "INVALIDATED"

    # Forward observation status becomes INVALIDATED with is_resolved = 0 (quarantined, NOT resolved!)
    obs = fwd_service.get_forward_observation(sig_id)
    assert obs["observation_status"] == "INVALIDATED"
    assert obs["is_resolved"] == 0
