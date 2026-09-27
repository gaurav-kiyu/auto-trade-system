"""Focused Regression & Invariant Test Suite for Phase D.1-D.3 Forward Observation Wiring.

Governance Authority: OPB-FINAL-PHASE-GOVERNANCE-001 / v2.60 Phase D.1-D.3 Roadmap.

Covers all 27 mandatory test items:
D.1 Tests (8 tests):
1. test_post_cutoff_signal_auto_registers_forward_observation
2. test_pre_cutoff_signal_rejected_from_forward_cohort
3. test_seed_signal_rejected_from_forward_cohort
4. test_test_source_rejected_from_forward_cohort
5. test_duplicate_registration_is_idempotent
6. test_snapshot_exists_before_forward_registration
7. test_forward_registration_failure_logged_and_non_fatal
8. test_existing_signal_persistence_remains_intact

D.2 Tests (7 tests):
9. test_scanner_passes_feature_vector_to_tracker
10. test_snapshot_contains_non_empty_features_json
11. test_feature_values_match_source_signal
12. test_feature_serialization_is_deterministic
13. test_missing_feature_remains_explicitly_missing
14. test_no_outcome_fields_enter_feature_json
15. test_snapshot_hash_includes_feature_vector

D.3 Tests (7 tests):
16. test_terminal_t1_synchronizes_to_forward_observation
17. test_terminal_sl_synchronizes_to_forward_observation
18. test_timeout_synchronizes_to_forward_observation
19. test_ambiguous_same_bar_remains_unresolved_and_quarantined
20. test_invalidated_remains_quarantined
21. test_repeated_synchronization_is_idempotent
22. test_historical_outcomes_cannot_enter_forward_cohort

Safety Tests (5 tests):
23. test_probabilities_remain_strictly_null
24. test_calibration_version_remains_uncalibrated
25. test_g1_to_g4_thresholds_unchanged
26. test_cutoff_boundary_unchanged
27. test_no_trade_execution_occurs
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import sqlite3
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from core.all_nse_scanner import AllNSEScanner, ScannedStockSignal
from core.datetime_ist import now_ist
from core.signals.signal_forward_observation import (
    DEFAULT_FORWARD_CUTOFF_ISO,
    FORWARD_CUTOFF_VERSION,
    GATE_MAX_DATA_QUALITY_ERROR_RATE,
    GATE_MAX_STALE_RATE,
    GATE_MIN_DISTINCT_MONTHS,
    GATE_MIN_RESOLVED_PER_ACTIVE_BUCKET,
    GATE_MIN_TOTAL_RESOLVED,
    SignalForwardObservationService,
)
from core.signals.signal_outcome_dataset import SignalOutcomeDatasetService
from core.signals.signal_outcome_tracker import SignalOutcomeTracker
from core.signals.signal_score_discrimination import SignalScoreDiscriminationService
from core.signals.signal_tracker import (
    SignalTracker,
    compute_prediction_snapshot_hash,
)


@pytest.fixture(autouse=True)
def _reset_singletons():
    orig_env = dict(os.environ)
    # Ensure no ambient config overrides exist
    for k in ("OPBUYING_SL_PCT", "OPBUYING_K", "OPBUYING_BASE_CAPITAL", "OPBUYING_EMAIL_USER", "OPBUYING_EMAIL_PASS"):
        os.environ.pop(k, None)
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
    # Restore and clean up
    for k in list(os.environ):
        if k not in orig_env:
            del os.environ[k]
        elif os.environ[k] != orig_env[k]:
            os.environ[k] = orig_env[k]
    for k in ("OPBUYING_SL_PCT", "OPBUYING_K", "OPBUYING_BASE_CAPITAL", "OPBUYING_EMAIL_USER", "OPBUYING_EMAIL_PASS"):
        os.environ.pop(k, None)


@pytest.fixture
def temp_db(tmp_path: Path) -> Path:
    """Create an isolated test database with all schemas initialized."""
    db_file = tmp_path / "signals_wiring_test.db"
    # Initializing each service bootstraps its respective tables
    SignalTracker(db_path=db_file)
    SignalOutcomeTracker(db_path=db_file)
    SignalOutcomeDatasetService(db_path=db_file)
    SignalForwardObservationService(db_path=db_file)
    return db_file


# ============================================================================
# D.1 Tests: Automatic Forward Registration (8 tests)
# ============================================================================


def test_post_cutoff_signal_auto_registers_forward_observation(temp_db: Path):
    """1. Post-cutoff signal automatically registers forward observation in SignalTracker."""
    tracker = SignalTracker(db_path=temp_db)

    sig_data = {
        "symbol": "TCS",
        "company_name": "Tata Consultancy Services",
        "direction": "CALL",
        "price": 3500.0,
        "score": 82,
        "raw_score": 82.0,
        "tier": "STRONG",
        "category": "LARGE_CAP_EQUITY",
        "regime": "TRENDING_BULLISH",
        "stop_loss": 3450.0,
        "target_1": 3600.0,
        "target_2": 3700.0,
        "features": {"rsi": 62.5, "adx": 28.0, "vwap": 3490.0, "price": 3500.0},
        "observation_source": "FORWARD_LIVE_SCAN",
    }

    sig_id = tracker.record_generated_signal(sig_data)
    assert sig_id != ""

    fwd_service = SignalForwardObservationService(db_path=temp_db)
    obs = fwd_service.get_forward_observation(sig_id)
    assert obs is not None
    assert obs["signal_id"] == sig_id
    assert obs["score"] == 82
    assert obs["score_bucket"] == "80-84"
    assert obs["observation_status"] == "OBSERVING"
    assert obs["is_resolved"] == 0
    assert obs["terminal_outcome"] is None


def test_pre_cutoff_signal_rejected_from_forward_cohort(temp_db: Path):
    """2. Pre-cutoff signal is persisted in system_signals and snapshots, but rejected from forward cohort."""
    tracker = SignalTracker(db_path=temp_db)

    # Monkeypatch now_ist during generation to simulate pre-cutoff signal
    pre_cutoff_time = datetime.datetime(2026, 9, 25, 14, 30, tzinfo=datetime.timezone(datetime.timedelta(hours=5, minutes=30)))

    with patch("core.signals.signal_tracker.now_ist", return_value=pre_cutoff_time):
        sig_data = {
            "symbol": "INFY",
            "direction": "CALL",
            "price": 1800.0,
            "score": 75,
            "stop_loss": 1770.0,
            "target_1": 1850.0,
            "target_2": 1900.0,
            "features": {"rsi": 58.0, "adx": 22.0, "vwap": 1795.0, "price": 1800.0},
        }
        sig_id = tracker.record_generated_signal(sig_data)

    assert sig_id != ""

    # Verify persisted in system_signals and snapshots
    conn = sqlite3.connect(str(temp_db))
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM system_signals WHERE signal_id = ?", (sig_id,))
    assert cur.fetchone()[0] == 1
    cur.execute("SELECT count(*) FROM signal_prediction_snapshots WHERE signal_id = ?", (sig_id,))
    assert cur.fetchone()[0] == 1

    # Verify strictly excluded from signal_forward_observations
    cur.execute("SELECT count(*) FROM signal_forward_observations WHERE signal_id = ?", (sig_id,))
    assert cur.fetchone()[0] == 0
    conn.close()


def test_seed_signal_rejected_from_forward_cohort(temp_db: Path):
    """3. Seed signal containing is_seed_sample marker is rejected from forward cohort."""
    tracker = SignalTracker(db_path=temp_db)

    sig_data = {
        "symbol": "RELIANCE",
        "direction": "CALL",
        "price": 2800.0,
        "score": 85,
        "is_seed_sample": True,
        "features": {"rsi": 65.0, "adx": 30.0, "vwap": 2790.0, "price": 2800.0},
    }
    sig_id = tracker.record_generated_signal(sig_data)
    assert sig_id != ""

    fwd_service = SignalForwardObservationService(db_path=temp_db)
    obs = fwd_service.get_forward_observation(sig_id)
    assert obs is None


def test_test_source_rejected_from_forward_cohort(temp_db: Path):
    """4. Signal with source TEST/MOCK/BACKFILL is rejected from forward cohort."""
    tracker = SignalTracker(db_path=temp_db)

    for test_src in ("TEST", "MOCK", "BACKFILL"):
        sig_data = {
            "symbol": f"SBIN_{test_src}",
            "direction": "CALL",
            "price": 600.0,
            "score": 78,
            "source": test_src,
            "features": {"rsi": 55.0, "price": 600.0},
        }
        sig_id = tracker.record_generated_signal(sig_data)
        assert sig_id != ""

        fwd_service = SignalForwardObservationService(db_path=temp_db)
        obs = fwd_service.get_forward_observation(sig_id)
        assert obs is None, f"Source {test_src} should be rejected from forward cohort"


def test_duplicate_registration_is_idempotent(temp_db: Path):
    """5. Duplicate registration calls are idempotent and do not duplicate forward records."""
    tracker = SignalTracker(db_path=temp_db)
    fwd_service = SignalForwardObservationService(db_path=temp_db)

    sig_data = {
        "symbol": "HDFCBANK",
        "direction": "CALL",
        "price": 1600.0,
        "score": 88,
        "stop_loss": 1570.0,
        "target_1": 1650.0,
        "target_2": 1700.0,
        "features": {"rsi": 70.0, "price": 1600.0},
    }
    sig_id = tracker.record_generated_signal(sig_data)
    assert sig_id != ""

    # Call register_forward_signal directly again
    dup_obs = fwd_service.register_forward_signal(sig_id)
    assert dup_obs is not None

    conn = sqlite3.connect(str(temp_db))
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM signal_forward_observations WHERE signal_id = ?", (sig_id,))
    count = cur.fetchone()[0]
    conn.close()
    assert count == 1, "Duplicate registration must not insert multiple rows"


def test_snapshot_exists_before_forward_registration(temp_db: Path):
    """6. Snapshot must exist in database before forward registration can succeed."""
    fwd_service = SignalForwardObservationService(db_path=temp_db)

    # Attempt registration with non-existent snapshot
    res = fwd_service.register_forward_signal("SIG-NONEXISTENT-999")
    assert res is None


def test_forward_registration_failure_logged_and_non_fatal(temp_db: Path, caplog):
    """7. Forward registration failure is logged and non-fatal to signal generation."""
    tracker = SignalTracker(db_path=temp_db)

    sig_data = {
        "symbol": "WIPRO",
        "direction": "CALL",
        "price": 480.0,
        "score": 76,
        "stop_loss": 470.0,
        "target_1": 500.0,
        "target_2": 520.0,
        "features": {"rsi": 52.0, "price": 480.0},
    }

    with caplog.at_level(logging.ERROR):
        with patch.object(SignalForwardObservationService, "register_forward_signal", side_effect=RuntimeError("Simulated registration crash")):
            sig_id = tracker.record_generated_signal(sig_data)

    # Signal generation must NOT fail
    assert sig_id != ""

    # System signal and snapshot must be safely persisted
    conn = sqlite3.connect(str(temp_db))
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM system_signals WHERE signal_id = ?", (sig_id,))
    assert cur.fetchone()[0] == 1
    cur.execute("SELECT count(*) FROM signal_prediction_snapshots WHERE signal_id = ?", (sig_id,))
    assert cur.fetchone()[0] == 1
    conn.close()

    # Error must be logged
    assert any("Forward observation registration failed" in record.message for record in caplog.records)


def test_existing_signal_persistence_remains_intact(temp_db: Path):
    """8. Existing signal persistence fields in system_signals and snapshots remain 100% intact."""
    tracker = SignalTracker(db_path=temp_db)

    sig_data = {
        "symbol": "ICICIBANK",
        "company_name": "ICICI Bank Ltd",
        "direction": "CALL",
        "price": 1150.0,
        "score": 84,
        "raw_score": 84.5,
        "tier": "STRONG",
        "category": "LARGE_CAP_EQUITY",
        "regime": "TRENDING_BULLISH",
        "stop_loss": 1130.0,
        "target_1": 1180.0,
        "target_2": 1210.0,
        "features": {"rsi": 64.0, "adx": 26.0, "vwap": 1145.0, "price": 1150.0},
    }
    sig_id = tracker.record_generated_signal(sig_data)

    conn = sqlite3.connect(str(temp_db))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM system_signals WHERE signal_id = ?", (sig_id,))
    sig_row = dict(cur.fetchone())
    cur.execute("SELECT * FROM signal_prediction_snapshots WHERE signal_id = ?", (sig_id,))
    snap_row = dict(cur.fetchone())
    conn.close()

    assert sig_row["symbol"] == "ICICIBANK"
    assert sig_row["score"] == 84
    assert sig_row["status"] == "ACTIVE"
    assert sig_row["entry_price"] == 1150.0

    assert snap_row["symbol"] == "ICICIBANK"
    assert snap_row["score"] == 84
    assert snap_row["raw_score"] == 84.5
    assert snap_row["snapshot_hash"] != ""


# ============================================================================
# D.2 Tests: Scanner Feature Vector Passthrough (7 tests)
# ============================================================================


def test_scanner_passes_feature_vector_to_tracker(temp_db: Path):
    """9. Scanner passes non-empty feature dictionary to tracker."""
    tracker = SignalTracker(db_path=temp_db)
    with patch.object(AllNSEScanner, "_reload_config_credentials"):
        scanner = AllNSEScanner(cfg={"EXECUTION_MODE": "SIGNAL_ONLY"})

    stock_signal = ScannedStockSignal(
        symbol="LT",
        company_name="Larsen & Toubro",
        series="EQ",
        direction="CALL",
        score=85,
        raw_score=85,
        tier="STRONG",
        regime="TRENDING_BULLISH",
        price=3200.0,
        rsi=66.0,
        adx=31.0,
        vwap=3180.0,
        features={"rsi": 66.0, "adx": 31.0, "vwap": 3180.0, "price": 3200.0, "atr": 45.0, "vol_ratio": 1.5},
    )

    with patch.object(SignalTracker, "get_instance", return_value=tracker):
        with patch.object(scanner, "_daily_signal_limit_allows_dispatch", return_value=True):
            with patch.object(scanner, "_rate_limit_allows_dispatch", return_value=True):
                user_mock = MagicMock(telegram_enabled=True, telegram_chat_id="123456789", email_enabled=False, username="admin")
                with patch("core.auth.user_signal_permissions.UserPermissionManager.get_instance") as perm_mock:
                    perm_mock.return_value.get_eligible_recipients.return_value = [user_mock]
                    scanner._dispatch_alert_if_eligible(stock_signal)

    conn = sqlite3.connect(str(temp_db))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT features_json FROM signal_prediction_snapshots WHERE symbol = 'LT'")
    row = cur.fetchone()
    conn.close()

    assert row is not None
    features = json.loads(row["features_json"])
    assert features["rsi"] == 66.0
    assert features["adx"] == 31.0
    assert features["vwap"] == 3180.0
    assert features["price"] == 3200.0


def test_snapshot_contains_non_empty_features_json(temp_db: Path):
    """10. Prediction snapshot contains non-empty features_json when features are passed."""
    tracker = SignalTracker(db_path=temp_db)

    sig_data = {
        "symbol": "BAJFINANCE",
        "direction": "CALL",
        "price": 6800.0,
        "score": 80,
        "features": {"rsi": 60.5, "adx": 25.0, "vwap": 6780.0, "price": 6800.0},
    }
    sig_id = tracker.record_generated_signal(sig_data)

    conn = sqlite3.connect(str(temp_db))
    cur = conn.cursor()
    cur.execute("SELECT features_json FROM signal_prediction_snapshots WHERE signal_id = ?", (sig_id,))
    raw_json = cur.fetchone()[0]
    conn.close()

    assert raw_json != ""
    assert raw_json != "{}"
    parsed = json.loads(raw_json)
    assert "rsi" in parsed


def test_feature_values_match_source_signal(temp_db: Path):
    """11. Feature values stored in snapshot match source signal indicator values."""
    tracker = SignalTracker(db_path=temp_db)

    sig_data = {
        "symbol": "MARUTI",
        "direction": "CALL",
        "price": 12400.0,
        "score": 83,
        "features": {
            "rsi": 68.25,
            "adx": 34.5,
            "vwap": 12350.75,
            "atr": 150.2,
            "vol_ratio": 2.1,
            "price": 12400.0,
        },
    }
    sig_id = tracker.record_generated_signal(sig_data)

    conn = sqlite3.connect(str(temp_db))
    cur = conn.cursor()
    cur.execute("SELECT features_json FROM signal_prediction_snapshots WHERE signal_id = ?", (sig_id,))
    parsed = json.loads(cur.fetchone()[0])
    conn.close()

    assert parsed["rsi"] == 68.25
    assert parsed["adx"] == 34.5
    assert parsed["vwap"] == 12350.75
    assert parsed["atr"] == 150.2
    assert parsed["vol_ratio"] == 2.1
    assert parsed["price"] == 12400.0


def test_feature_serialization_is_deterministic(temp_db: Path):
    """12. Feature serialization is deterministic across arbitrary insertion order."""
    tracker = SignalTracker(db_path=temp_db)

    # Insert two signals with different dict insertion orders
    sig1 = {
        "symbol": "TECHM1",
        "direction": "CALL",
        "price": 1500.0,
        "score": 75,
        "features": {"b": 2.0, "a": 1.0, "c": 3.0},
    }
    sig2 = {
        "symbol": "TECHM2",
        "direction": "CALL",
        "price": 1500.0,
        "score": 75,
        "features": {"c": 3.0, "b": 2.0, "a": 1.0},
    }

    id1 = tracker.record_generated_signal(sig1)
    id2 = tracker.record_generated_signal(sig2)

    conn = sqlite3.connect(str(temp_db))
    cur = conn.cursor()
    cur.execute("SELECT features_json FROM signal_prediction_snapshots WHERE signal_id = ?", (id1,))
    json1 = cur.fetchone()[0]
    cur.execute("SELECT features_json FROM signal_prediction_snapshots WHERE signal_id = ?", (id2,))
    json2 = cur.fetchone()[0]
    conn.close()

    assert json1 == json2
    assert json1 == '{"a":1.0,"b":2.0,"c":3.0}'


def test_missing_feature_remains_explicitly_missing(temp_db: Path):
    """13. Missing features (e.g. atr not computed) are not faked with default 0.0."""
    tracker = SignalTracker(db_path=temp_db)

    sig_data = {
        "symbol": "HCLTECH",
        "direction": "CALL",
        "price": 1700.0,
        "score": 77,
        "features": {
            "rsi": 57.0,
            "adx": 23.0,
            "vwap": 1695.0,
            "price": 1700.0,
            # 'atr' and 'vol_ratio' are explicitly omitted
        },
    }
    sig_id = tracker.record_generated_signal(sig_data)

    conn = sqlite3.connect(str(temp_db))
    cur = conn.cursor()
    cur.execute("SELECT features_json FROM signal_prediction_snapshots WHERE signal_id = ?", (sig_id,))
    parsed = json.loads(cur.fetchone()[0])
    conn.close()

    assert "atr" not in parsed, "Omitted feature must remain absent rather than defaulted to 0.0"
    assert "vol_ratio" not in parsed


def test_no_outcome_fields_enter_feature_json(temp_db: Path):
    """14. Forbidden outcome fields cannot leak into features_json."""
    tracker = SignalTracker(db_path=temp_db)
    with patch.object(AllNSEScanner, "_reload_config_credentials"):
        scanner = AllNSEScanner(cfg={"EXECUTION_MODE": "SIGNAL_ONLY"})

    # Create signal maliciously containing outcome fields
    stock_signal = ScannedStockSignal(
        symbol="KOTAKBANK",
        company_name="Kotak Mahindra Bank",
        series="EQ",
        direction="CALL",
        score=81,
        raw_score=81,
        tier="STRONG",
        regime="TRENDING_BULLISH",
        price=1800.0,
        rsi=60.0,
        adx=25.0,
        vwap=1790.0,
        features={
            "rsi": 60.0,
            "price": 1800.0,
            "outcome": "TARGET_FIRST",
            "first_touch": "T1",
            "target_1_hit": 1,
            "mfe_r": 2.5,
            "realized_r": 1.5,
            "is_resolved": 1,
        },
    )

    with patch.object(SignalTracker, "get_instance", return_value=tracker):
        with patch.object(scanner, "_daily_signal_limit_allows_dispatch", return_value=True):
            with patch.object(scanner, "_rate_limit_allows_dispatch", return_value=True):
                user_mock = MagicMock(telegram_enabled=True, telegram_chat_id="123456789", email_enabled=False, username="admin")
                with patch("core.auth.user_signal_permissions.UserPermissionManager.get_instance") as perm_mock:
                    perm_mock.return_value.get_eligible_recipients.return_value = [user_mock]
                    scanner._dispatch_alert_if_eligible(stock_signal)

    conn = sqlite3.connect(str(temp_db))
    cur = conn.cursor()
    cur.execute("SELECT features_json FROM signal_prediction_snapshots WHERE symbol = 'KOTAKBANK'")
    row = cur.fetchone()
    conn.close()

    assert row is not None
    features = json.loads(row[0])
    assert "rsi" in features
    assert "price" in features
    assert "outcome" not in features
    assert "first_touch" not in features
    assert "target_1_hit" not in features
    assert "mfe_r" not in features
    assert "realized_r" not in features
    assert "is_resolved" not in features


def test_snapshot_hash_includes_feature_vector(temp_db: Path):
    """15. Modifying feature vector alters the computed snapshot_hash."""
    base_payload = {
        "signal_id": "SIG-TEST-001",
        "captured_at": "2026-09-26T10:00:00+05:30",
        "score": 80,
        "features": {"rsi": 60.0, "price": 100.0},
    }
    hash1 = compute_prediction_snapshot_hash(base_payload)

    altered_payload = dict(base_payload)
    altered_payload["features"] = {"rsi": 65.0, "price": 100.0}
    hash2 = compute_prediction_snapshot_hash(altered_payload)

    assert hash1 != hash2, "Snapshot hash must cover the features dictionary"


# ============================================================================
# D.3 Tests: Automatic Forward Outcome Synchronization (7 tests)
# ============================================================================


def test_terminal_t1_synchronizes_to_forward_observation(temp_db: Path):
    """16. Signal hitting T1 during update_active_signal_outcomes synchronizes forward observation to RESOLVED."""
    tracker = SignalTracker(db_path=temp_db)
    outcome_tracker = SignalOutcomeTracker(db_path=temp_db)

    sig_data = {
        "symbol": "TITAN",
        "direction": "CALL",
        "price": 3200.0,
        "score": 85,
        "stop_loss": 3100.0,
        "target_1": 3300.0,
        "target_2": 3400.0,
        "features": {"rsi": 65.0, "price": 3200.0},
    }
    sig_id = tracker.record_generated_signal(sig_data)
    assert sig_id != ""

    fwd_service = SignalForwardObservationService(db_path=temp_db)
    obs_before = fwd_service.get_forward_observation(sig_id)
    assert obs_before["observation_status"] == "OBSERVING"
    assert obs_before["is_resolved"] == 0

    # Simulate price touching T1 (3350 >= 3300)
    res = outcome_tracker.update_active_signal_outcomes(price_lookup_fn=lambda sym: 3350.0)
    assert res["resolved"] >= 1

    obs_after = fwd_service.get_forward_observation(sig_id)
    assert obs_after["is_resolved"] == 1
    assert obs_after["observation_status"] == "RESOLVED"
    assert obs_after["terminal_outcome"] == "TARGET_FIRST"
    assert obs_after["resolution_timestamp"] is not None


def test_terminal_sl_synchronizes_to_forward_observation(temp_db: Path):
    """17. Signal hitting SL during update_active_signal_outcomes synchronizes forward observation to RESOLVED."""
    tracker = SignalTracker(db_path=temp_db)
    outcome_tracker = SignalOutcomeTracker(db_path=temp_db)

    sig_data = {
        "symbol": "ASIANPAINT",
        "direction": "CALL",
        "price": 2900.0,
        "score": 78,
        "stop_loss": 2800.0,
        "target_1": 3000.0,
        "target_2": 3100.0,
        "features": {"rsi": 54.0, "price": 2900.0},
    }
    sig_id = tracker.record_generated_signal(sig_data)
    assert sig_id != ""

    # Simulate price touching SL (2750 <= 2800)
    res = outcome_tracker.update_active_signal_outcomes(price_lookup_fn=lambda sym: 2750.0)
    assert res["resolved"] >= 1

    fwd_service = SignalForwardObservationService(db_path=temp_db)
    obs_after = fwd_service.get_forward_observation(sig_id)
    assert obs_after["is_resolved"] == 1
    assert obs_after["observation_status"] == "RESOLVED"
    assert obs_after["terminal_outcome"] == "SL_FIRST"


def test_timeout_synchronizes_to_forward_observation(temp_db: Path):
    """18. Signal expiring during expire_stale_signals synchronizes forward observation to TIMEOUT."""
    tracker = SignalTracker(db_path=temp_db)
    outcome_tracker = SignalOutcomeTracker(db_path=temp_db)

    # Register forward signal with creation timestamp on market session after cutoff (e.g. 2026-09-26T10:00:00+05:30)
    post_cutoff_time = datetime.datetime(2026, 9, 26, 10, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=5, minutes=30)))
    with patch("core.signals.signal_tracker.now_ist", return_value=post_cutoff_time):
        sig_data = {
            "symbol": "ULTRACEMCO",
            "direction": "CALL",
            "price": 10500.0,
            "score": 80,
            "stop_loss": 10200.0,
            "target_1": 10800.0,
            "target_2": 11000.0,
            "features": {"rsi": 58.0, "price": 10500.0},
        }
        sig_id = tracker.record_generated_signal(sig_data)

    assert sig_id != ""

    # Expire stale signals at a future time past the 5-day holding horizon
    future_time = datetime.datetime(2026, 10, 10, 16, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=5, minutes=30)))
    res = outcome_tracker.expire_stale_signals(dry_run=False, current_time=future_time)
    assert res["transitioned"] >= 1

    fwd_service = SignalForwardObservationService(db_path=temp_db)
    obs_after = fwd_service.get_forward_observation(sig_id)
    assert obs_after["is_resolved"] == 1
    assert obs_after["observation_status"] == "TIMEOUT"
    assert obs_after["terminal_outcome"] == "TIMEOUT"


def test_ambiguous_same_bar_remains_unresolved_and_quarantined(temp_db: Path):
    """19. Ambiguous same-bar cross transitions to AMBIGUOUS and remains unresolved (is_resolved = 0)."""
    tracker = SignalTracker(db_path=temp_db)
    outcome_tracker = SignalOutcomeTracker(db_path=temp_db)

    sig_data = {
        "symbol": "BAJAJ-AUTO",
        "direction": "CALL",
        "price": 9000.0,
        "score": 82,
        "stop_loss": 8800.0,
        "target_1": 9200.0,
        "target_2": 9400.0,
        "features": {"rsi": 61.0, "price": 9000.0},
    }
    sig_id = tracker.record_generated_signal(sig_data)

    from core.signals.signal_outcome_tracker import SignalBar
    # Ambiguous bar: low crosses SL (8750 <= 8800) AND high crosses T1 (9250 >= 9200)
    bar = SignalBar(open=9000.0, high=9250.0, low=8750.0, close=8950.0, timestamp=now_ist().isoformat())

    outcome_tracker.update_active_signal_outcomes(
        price_lookup_fn=lambda sym: 8950.0,
        bar_lookup_fn=lambda sym: bar,
    )

    fwd_service = SignalForwardObservationService(db_path=temp_db)
    obs = fwd_service.get_forward_observation(sig_id)
    assert obs["observation_status"] == "AMBIGUOUS"
    assert obs["is_resolved"] == 0, "Quarantined ambiguous observation must NOT be marked resolved"


def test_invalidated_remains_quarantined(temp_db: Path):
    """20. Invalidated observation remains quarantined with is_resolved = 0."""
    tracker = SignalTracker(db_path=temp_db)
    outcome_tracker = SignalOutcomeTracker(db_path=temp_db)

    sig_data = {
        "symbol": "NESTLEIND",
        "direction": "CALL",
        "price": 2400.0,
        "score": 79,
        "stop_loss": 2350.0,
        "target_1": 2450.0,
        "target_2": 2500.0,
        "features": {"rsi": 56.0, "price": 2400.0},
    }
    sig_id = tracker.record_generated_signal(sig_data)

    # Force invalidation in measurements table
    fwd_service = SignalForwardObservationService(db_path=temp_db)
    conn = sqlite3.connect(str(temp_db))
    cur = conn.cursor()
    cur.execute("""
        INSERT OR REPLACE INTO signal_outcome_measurements (
            signal_id, prediction_snapshot_id, symbol, category, direction,
            entry_price, stop_loss, target_1, target_2, initial_risk,
            observed_from, observed_until, outcome, raw_lifecycle_state,
            first_touch, first_touch_at, first_touch_price, target_1_hit,
            target_1_hit_at, target_1_hit_price, target_2_hit, target_2_hit_at,
            target_2_hit_price, stop_loss_hit, stop_loss_hit_at, stop_loss_hit_price,
            mfe, mae, mfe_pct, mae_pct, mfe_r, mae_r, time_to_first_event_seconds,
            time_to_t1_seconds, time_to_t2_seconds, time_to_sl_seconds, realized_r,
            exit_price, exit_at, observation_count, data_quality_status,
            outcome_confidence, calculation_version, calculated_at
        ) VALUES (
            ?, ?, 'NESTLEIND', 'LARGE_CAP_EQUITY', 'CALL',
            2400.0, 2350.0, 2450.0, 2500.0, 50.0,
            ?, ?, 'INVALIDATED', 'INVALIDATED',
            'INVALIDATED', ?, 2400.0, 0,
            NULL, NULL, 0, NULL,
            NULL, 0, NULL, NULL,
            NULL, NULL, NULL, NULL, NULL, NULL, NULL,
            NULL, NULL, NULL, NULL,
            NULL, NULL, 0, 'INVALID_DATA',
            'UNRESOLVED', 'OUTCOME_MEASUREMENT_V1', ?
        )
    """, (sig_id, sig_id, now_ist().isoformat(), now_ist().isoformat(), now_ist().isoformat(), now_ist().isoformat()))
    conn.commit()
    conn.close()

    outcome_tracker.sync_forward_outcomes()

    obs = fwd_service.get_forward_observation(sig_id)
    assert obs["observation_status"] == "INVALIDATED"
    assert obs["is_resolved"] == 0


def test_repeated_synchronization_is_idempotent(temp_db: Path):
    """21. Repeated calls to sync_forward_outcomes do not alter resolved state or duplicate rows."""
    tracker = SignalTracker(db_path=temp_db)
    outcome_tracker = SignalOutcomeTracker(db_path=temp_db)

    sig_data = {
        "symbol": "SUNPHARMA",
        "direction": "CALL",
        "price": 1500.0,
        "score": 83,
        "stop_loss": 1460.0,
        "target_1": 1540.0,
        "target_2": 1580.0,
        "features": {"rsi": 63.0, "price": 1500.0},
    }
    sig_id = tracker.record_generated_signal(sig_data)

    # First resolve to T1
    outcome_tracker.update_active_signal_outcomes(price_lookup_fn=lambda sym: 1550.0)

    fwd_service = SignalForwardObservationService(db_path=temp_db)
    obs_1 = fwd_service.get_forward_observation(sig_id)
    assert obs_1["is_resolved"] == 1

    # Call sync 3 times in a row
    for _ in range(3):
        outcome_tracker.sync_forward_outcomes()

    obs_2 = fwd_service.get_forward_observation(sig_id)
    assert obs_2["is_resolved"] == 1
    assert obs_2["terminal_outcome"] == obs_1["terminal_outcome"]
    assert obs_2["resolution_timestamp"] == obs_1["resolution_timestamp"]

    conn = sqlite3.connect(str(temp_db))
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM signal_forward_observations WHERE signal_id = ?", (sig_id,))
    assert cur.fetchone()[0] == 1
    conn.close()


def test_historical_outcomes_cannot_enter_forward_cohort(temp_db: Path):
    """22. Outcomes for pre-cutoff historical signals cannot enter forward observations."""
    tracker = SignalTracker(db_path=temp_db)
    outcome_tracker = SignalOutcomeTracker(db_path=temp_db)

    # Pre-cutoff signal
    past_time = datetime.datetime(2026, 9, 20, 10, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=5, minutes=30)))
    with patch("core.signals.signal_tracker.now_ist", return_value=past_time):
        sig_data = {
            "symbol": "HIST_SIG",
            "direction": "CALL",
            "price": 100.0,
            "score": 75,
            "stop_loss": 95.0,
            "target_1": 105.0,
            "target_2": 110.0,
        }
        sig_id = tracker.record_generated_signal(sig_data)

    # Resolve historical signal
    outcome_tracker.update_active_signal_outcomes(price_lookup_fn=lambda sym: 106.0)

    fwd_service = SignalForwardObservationService(db_path=temp_db)
    obs = fwd_service.get_forward_observation(sig_id)
    assert obs is None, "Historical signal must never appear in forward observations"


# ============================================================================
# Safety & Policy Invariant Tests (5 tests)
# ============================================================================


def test_probabilities_remain_strictly_null(temp_db: Path):
    """23. Probability fields in snapshots remain strictly NULL."""
    tracker = SignalTracker(db_path=temp_db)

    sig_data = {
        "symbol": "NTPC",
        "direction": "CALL",
        "price": 350.0,
        "score": 81,
        "features": {"rsi": 62.0, "price": 350.0},
    }
    sig_id = tracker.record_generated_signal(sig_data)

    conn = sqlite3.connect(str(temp_db))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT p_t1, p_t2, p_sl, p_timeout FROM signal_prediction_snapshots WHERE signal_id = ?", (sig_id,))
    row = dict(cur.fetchone())
    conn.close()

    assert row["p_t1"] is None
    assert row["p_t2"] is None
    assert row["p_sl"] is None
    assert row["p_timeout"] is None


def test_calibration_version_remains_uncalibrated(temp_db: Path):
    """24. Calibration version in snapshots defaults strictly to UNCALIBRATED."""
    tracker = SignalTracker(db_path=temp_db)

    sig_data = {
        "symbol": "POWERGRID",
        "direction": "CALL",
        "price": 300.0,
        "score": 79,
        "features": {"rsi": 59.0, "price": 300.0},
    }
    sig_id = tracker.record_generated_signal(sig_data)

    conn = sqlite3.connect(str(temp_db))
    cur = conn.cursor()
    cur.execute("SELECT calibration_version FROM signal_prediction_snapshots WHERE signal_id = ?", (sig_id,))
    calib = cur.fetchone()[0]
    conn.close()

    assert calib == "UNCALIBRATED"


def test_g1_to_g4_thresholds_unchanged():
    """25. G1 to G4 calibration readiness thresholds remain authoritative and unchanged."""
    assert GATE_MIN_RESOLVED_PER_ACTIVE_BUCKET == 100
    assert GATE_MIN_TOTAL_RESOLVED == 300
    assert GATE_MIN_DISTINCT_MONTHS == 2
    assert GATE_MAX_DATA_QUALITY_ERROR_RATE == 0.05
    assert GATE_MAX_STALE_RATE == 0.02


def test_cutoff_boundary_unchanged():
    """26. Phase-D forward observation cutoff and version remain unchanged."""
    assert DEFAULT_FORWARD_CUTOFF_ISO == "2026-09-26T00:00:00+05:30"
    assert FORWARD_CUTOFF_VERSION == "PHASE_D_V1_20260926"


def test_no_trade_execution_occurs():
    """27. Execution mode is strictly SIGNAL_ONLY with 0 orders."""
    cfg_path = Path(__file__).resolve().parent.parent / "json" / "config.json"
    with open(cfg_path, encoding="utf-8") as f:
        cfg = json.load(f)

    assert str(cfg.get("EXECUTION_MODE", "")).upper() == "SIGNAL_ONLY"
    assert bool(cfg.get("SIGNAL_ONLY", False)) is True
    assert bool(cfg.get("LIVE_TRADING_LOCKOUT", False)) is True
    assert bool(cfg.get("full_auto_allowed", True)) is False
