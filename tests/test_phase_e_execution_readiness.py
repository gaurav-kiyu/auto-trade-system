"""Tests for Phase E Execution Readiness Governance Layer.

Governance Authority: OPB-FINAL-PHASE-GOVERNANCE-001 / v2.60 Signal Quality Roadmap.

Ensures strict mathematical correctness, governance compliance, data contracts,
target semantics, leakage prevention, temporal splitting, estimator/calibrator interfaces,
probability contracts, Brier/LogLoss/ROC-AUC/ECE metrics, baseline comparison,
calibration separation, reproducibility manifest, model registry, and production DB evaluation.
"""

import json
import math
import sqlite3
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from core.signals.phase_e_execution_readiness import (
    CALIBRATION_FIT_BLOCKED,
    DEFAULT_FORWARD_CUTOFF,
    FEATURE_PROVENANCE_UNVERIFIED,
    FORBIDDEN_OUTCOME_KEYS,
    METRIC_INFEASIBLE,
    PERMITTED_CONTEMPORANEOUS_FEATURES,
    PHASE_E_SOFTWARE_VERSION,
    REASON_AMBIGUOUS_OUTCOME,
    REASON_INVALID_BARRIER,
    REASON_INVALID_NUMERIC,
    REASON_INVALIDATED_OUTCOME,
    REASON_MISSING_FEATURE,
    REASON_MISSING_SNAPSHOT,
    REASON_MISSING_TARGET,
    REASON_NO_DATA,
    REASON_OUTCOME_LEAKAGE,
    REASON_PRE_CUTOFF,
    REASON_SEED_OR_TEST_SOURCE,
    REASON_UNRESOLVED,
    SCORE_CONVERSION_PROHIBITED,
    SPLIT_INFEASIBLE,
    STATUS_ELIGIBLE,
    STATUS_INELIGIBLE,
    STATUS_QUARANTINED,
    VERDICT_PASS_BLOCKED_BY_SAMPLE,
    BaselineComparator,
    BaselineEstimatorInterface,
    BaselineLogisticRegressionEstimator,
    CalibrationFitBlockedError,
    CalibrationInterface,
    ChronologicalDatasetSplitter,
    GovernanceViolationError,
    IsotonicCalibrationInterface,
    ModelLifecycleState,
    ModelRegistry,
    PhaseEExecutionReadinessReport,
    PhaseEExperimentManifest,
    PlattCalibrationInterface,
    ProbabilityPrediction,
    ReliabilityBinResult,
    compute_brier_score,
    compute_expected_calibration_error,
    compute_log_loss,
    compute_pr_auc,
    compute_reliability_bins,
    compute_roc_auc,
    compute_target_outcome,
    evaluate_phase_e_execution_readiness,
    validate_dataset_eligibility,
    validate_feature_contract,
    validate_probability_value,
    verify_calibration_separation,
)


# ============================================================================
# Helpers & Fixtures
# ============================================================================

def make_valid_observation(**overrides) -> dict:
    base = {
        "signal_id": "SIG-FWD-20260926-001",
        "snapshot_captured_at": "2026-09-26T10:00:00+05:30",
        "captured_at": "2026-09-26T10:00:00+05:30",
        "snapshot_hash": "sha256_mock_hash_valid",
        "market_date": "2026-09-26",
        "direction": "BUY",
        "symbol": "RELIANCE",
        "entry_price": 2500.0,
        "stop_loss": 2450.0,
        "target_1": 2550.0,
        "target_2": 2600.0,
        "terminal_outcome": "TARGET_1_HIT",
        "is_resolved": 1,
        "first_touch": "TARGET_1",
        "observation_source": "FORWARD_LIVE_SCAN",
        "observation_status": "VALID_OBSERVATION",
        "data_quality_status": "VALID_DATA",
        "features": {
            "rsi": 55.4,
            "adx": 28.2,
            "vwap": 2495.0,
            "atr": 18.5,
            "vol_ratio": 1.45,
            "price": 2500.0,
        },
    }
    base.update(overrides)
    return base


# ============================================================================
# 1. Dataset Eligibility Validator Tests (8 tests)
# ============================================================================

def test_eligibility_valid_observation_accepted():
    record = make_valid_observation()
    status, reasons = validate_dataset_eligibility(record)
    assert status == STATUS_ELIGIBLE
    assert reasons == []


def test_eligibility_pre_cutoff_rejected():
    record = make_valid_observation(
        snapshot_captured_at="2026-09-25T23:59:59+05:30",
        captured_at="2026-09-25T23:59:59+05:30",
    )
    status, reasons = validate_dataset_eligibility(record)
    assert status == STATUS_INELIGIBLE
    assert REASON_PRE_CUTOFF in reasons


def test_eligibility_seed_or_test_source_rejected():
    for source in ["SEED_HISTORICAL", "SEED", "TEST", "MOCK", "SYNTHETIC", "FIXTURE"]:
        record = make_valid_observation(observation_source=source)
        status, reasons = validate_dataset_eligibility(record)
        assert status == STATUS_INELIGIBLE
        assert REASON_SEED_OR_TEST_SOURCE in reasons


def test_eligibility_missing_snapshot_rejected():
    record = make_valid_observation(snapshot_captured_at=None, captured_at=None)
    status, reasons = validate_dataset_eligibility(record)
    assert status == STATUS_INELIGIBLE
    assert REASON_MISSING_SNAPSHOT in reasons


def test_eligibility_ambiguous_same_bar_quarantined():
    record = make_valid_observation(terminal_outcome="AMBIGUOUS_SAME_BAR")
    status, reasons = validate_dataset_eligibility(record)
    assert status == STATUS_QUARANTINED
    assert REASON_AMBIGUOUS_OUTCOME in reasons


def test_eligibility_invalidated_outcome_quarantined():
    record = make_valid_observation(terminal_outcome="INVALIDATED_GAP")
    status, reasons = validate_dataset_eligibility(record)
    assert status == STATUS_QUARANTINED
    assert REASON_INVALIDATED_OUTCOME in reasons


def test_eligibility_unresolved_rejected():
    record = make_valid_observation(is_resolved=0, terminal_outcome=None)
    status, reasons = validate_dataset_eligibility(record)
    assert status == STATUS_INELIGIBLE
    assert REASON_UNRESOLVED in reasons


def test_eligibility_invalid_barrier_rejected():
    # Buy signal where SL >= entry
    record = make_valid_observation(direction="BUY", entry_price=100.0, stop_loss=105.0, target_1=110.0)
    status, reasons = validate_dataset_eligibility(record)
    assert status == STATUS_INELIGIBLE
    assert REASON_INVALID_BARRIER in reasons


# ============================================================================
# 2. Target Contract Tests (6 tests)
# ============================================================================

def test_target_contract_target_1_hit_resolves_positive():
    obs = {"is_resolved": 1, "terminal_outcome": "TARGET_1_HIT", "first_touch": "TARGET_1"}
    y, status, reasons = compute_target_outcome(obs)
    assert y == 1
    assert status == STATUS_ELIGIBLE
    assert reasons == []


def test_target_contract_stop_loss_hit_resolves_negative():
    obs = {"is_resolved": 1, "terminal_outcome": "STOP_LOSS_HIT", "first_touch": "STOP_LOSS"}
    y, status, reasons = compute_target_outcome(obs)
    assert y == 0
    assert status == STATUS_ELIGIBLE
    assert reasons == []


def test_target_contract_timeout_expiry_resolves_negative():
    obs = {"is_resolved": 1, "terminal_outcome": "TIMEOUT_EXPIRED", "first_touch": "TIMEOUT"}
    y, status, reasons = compute_target_outcome(obs)
    assert y == 0
    assert status == STATUS_ELIGIBLE
    assert reasons == []


def test_target_contract_ambiguous_quarantined_never_coerced():
    obs = {"is_resolved": 1, "terminal_outcome": "AMBIGUOUS_SAME_BAR"}
    y, status, reasons = compute_target_outcome(obs)
    assert y is None
    assert status == STATUS_QUARANTINED
    assert REASON_AMBIGUOUS_OUTCOME in reasons


def test_target_contract_t2_without_t1_prohibited():
    # T2 hit indicated without Target 1 being hit
    obs = {"is_resolved": 1, "terminal_outcome": "TARGET_2_HIT", "target_1_hit": 0, "first_touch": "TARGET_2"}
    y, status, reasons = compute_target_outcome(obs)
    assert y is None
    assert status == STATUS_QUARANTINED
    assert "T2_WITHOUT_T1_PROHIBITED" in reasons


def test_target_contract_unresolved_ineligible():
    obs = {"is_resolved": 0, "terminal_outcome": None}
    y, status, reasons = compute_target_outcome(obs)
    assert y is None
    assert status == STATUS_INELIGIBLE
    assert REASON_UNRESOLVED in reasons


# ============================================================================
# 3. Feature Contract & Leakage Tests (5 tests)
# ============================================================================

def test_feature_contract_valid_contemporaneous_vector_passes():
    features = {
        "rsi": 58.2,
        "adx": 31.0,
        "vwap": 1500.0,
        "atr": 12.0,
        "vol_ratio": 1.25,
        "price": 1502.0,
    }
    is_valid, errors, cleaned = validate_feature_contract(features)
    assert is_valid is True
    assert errors == []
    assert cleaned is not None
    assert cleaned["rsi"] == 58.2
    assert cleaned["price"] == 1502.0


def test_feature_contract_all_forbidden_outcome_keys_rejected():
    for forbidden_key in FORBIDDEN_OUTCOME_KEYS:
        features = {
            "rsi": 50.0,
            "adx": 25.0,
            "vwap": 100.0,
            "atr": 2.0,
            "vol_ratio": 1.0,
            "price": 100.0,
            forbidden_key: 1.0,
        }
        is_valid, errors, cleaned = validate_feature_contract(features)
        assert is_valid is False
        assert any(REASON_OUTCOME_LEAKAGE in e for e in errors)
        assert cleaned is None


def test_feature_contract_missing_required_feature_fails():
    incomplete = {
        "rsi": 50.0,
        # missing adx
        "vwap": 100.0,
        "atr": 2.0,
        "vol_ratio": 1.0,
        "price": 100.0,
    }
    is_valid, errors, cleaned = validate_feature_contract(incomplete)
    assert is_valid is False
    assert any(REASON_MISSING_FEATURE in e for e in errors)


def test_feature_contract_nan_or_inf_fails():
    bad_features = {
        "rsi": float("nan"),
        "adx": 25.0,
        "vwap": 100.0,
        "atr": 2.0,
        "vol_ratio": 1.0,
        "price": 100.0,
    }
    is_valid, errors, cleaned = validate_feature_contract(bad_features)
    assert is_valid is False
    assert any(REASON_INVALID_NUMERIC in e for e in errors)


def test_feature_contract_pit_provenance_validation():
    features = {"rsi": 50.0, "adx": 25.0, "vwap": 100.0, "atr": 2.0, "vol_ratio": 1.0, "price": 100.0}
    # Missing snapshot timestamp
    is_valid, errors, _ = validate_feature_contract(features, snapshot_info={"snapshot_captured_at": None})
    assert is_valid is False
    assert any(FEATURE_PROVENANCE_UNVERIFIED in e for e in errors)


# ============================================================================
# 4. Chronological Dataset Splitter Tests (4 tests)
# ============================================================================

def test_chronological_split_strict_ordering():
    # 60 records chronologically spaced
    records = []
    for i in range(60):
        records.append({
            "signal_id": f"SIG-{i:03d}",
            "snapshot_captured_at": f"2026-09-26T10:{i:02d}:00+05:30",
            "target_y": 1 if i % 2 == 0 else 0,
        })
    res = ChronologicalDatasetSplitter.split(records, train_ratio=0.6, val_ratio=0.2, holdout_ratio=0.2)
    assert res.is_valid is True
    assert res.status == "SPLIT_VALID"
    assert len(res.train_records) == 36
    assert len(res.val_records) == 12
    assert len(res.holdout_records) == 12

    # Verify no temporal overlap: train_end < val_start and val_end < holdout_start
    assert res.train_end < res.val_start
    assert res.val_end < res.holdout_start


def test_chronological_split_insufficient_sample_fails_closed():
    # Less than MIN_TOTAL_SAMPLES (50)
    records = [{"signal_id": f"SIG-{i}", "snapshot_captured_at": "2026-09-26T10:00:00+05:30", "target_y": 1} for i in range(20)]
    res = ChronologicalDatasetSplitter.split(records)
    assert res.is_valid is False
    assert res.status == SPLIT_INFEASIBLE
    assert any("minimum required" in r for r in res.reasons)


def test_chronological_split_degenerate_class_fails_closed():
    # 60 records, but validation set has only 0s
    records = []
    for i in range(60):
        # Indices 36 to 47 are val_records: make them all 0
        y = 0 if (36 <= i < 48) else (1 if i % 2 == 0 else 0)
        records.append({
            "signal_id": f"SIG-{i:03d}",
            "snapshot_captured_at": f"2026-09-26T10:{i:02d}:00+05:30",
            "target_y": y,
        })
    res = ChronologicalDatasetSplitter.split(records)
    assert res.is_valid is False
    assert res.status == SPLIT_INFEASIBLE
    assert any("degenerate class balance" in r for r in res.reasons)


def test_chronological_split_no_random_shuffle():
    # Records passed in reverse order must be sorted chronologically
    records = []
    for i in reversed(range(60)):
        records.append({
            "signal_id": f"SIG-{i:03d}",
            "snapshot_captured_at": f"2026-09-26T10:{i:02d}:00+05:30",
            "target_y": 1 if i % 2 == 0 else 0,
        })
    res = ChronologicalDatasetSplitter.split(records)
    assert res.is_valid is True
    # First train record must be SIG-000
    assert res.train_records[0]["signal_id"] == "SIG-000"
    assert res.holdout_records[-1]["signal_id"] == "SIG-059"


# ============================================================================
# 5. Baseline Estimator Interface Tests (4 tests)
# ============================================================================

def test_estimator_interface_metadata_attributes():
    est = BaselineLogisticRegressionEstimator(model_version="v1.0-test")
    assert est.model_family == "LOGISTIC_REGRESSION"
    assert est.model_version == "v1.0-test"
    assert est.feature_schema_version == "v1.0-contemporaneous-pit"
    assert est.status == "DESIGNED"
    assert est.is_fitted is False


def test_estimator_fit_fails_closed_in_readiness():
    est = BaselineLogisticRegressionEstimator()
    with pytest.raises(CalibrationFitBlockedError) as exc_info:
        est.fit([[1.0, 2.0]], [1])
    assert CALIBRATION_FIT_BLOCKED in str(exc_info.value)


def test_estimator_predict_proba_on_unfitted_raises():
    est = BaselineLogisticRegressionEstimator()
    with pytest.raises(Exception):
        est.predict_proba([[1.0, 2.0]])


def test_estimator_interface_inheritance_contract():
    class DummyEstimator(BaselineEstimatorInterface):
        pass

    with pytest.raises(TypeError):
        # Cannot instantiate abstract class without implementing abstract methods
        DummyEstimator()


# ============================================================================
# 6. Probability Output Contract Tests (4 tests)
# ============================================================================

def test_probability_contract_out_of_bounds_rejected():
    valid, err = validate_probability_value(-0.01)
    assert valid is False
    assert "out of bounds" in str(err)

    valid, err = validate_probability_value(1.05)
    assert valid is False
    assert "out of bounds" in str(err)


def test_probability_contract_score_conversion_strictly_prohibited():
    # Raw score 85 -> probability 0.85 must be rejected with SCORE_CONVERSION_PROHIBITED
    valid, err = validate_probability_value(0.85, raw_score=85.0)
    assert valid is False
    assert SCORE_CONVERSION_PROHIBITED in str(err)


def test_probability_prediction_bundle_valid():
    bundle = ProbabilityPrediction(
        signal_id="SIG-001",
        predicted_probability=0.62,
        model_version="v1.0",
        calibration_version="UNCALIBRATED",
        feature_schema_version="v1.0-contemporaneous-pit",
        prediction_timestamp="2026-09-26T10:00:00+05:30",
        status="UNCALIBRATED",
    )
    d = bundle.to_dict()
    assert d["predicted_probability"] == 0.62
    assert d["signal_id"] == "SIG-001"


def test_probability_prediction_nan_inf_rejected():
    with pytest.raises(ValueError):
        ProbabilityPrediction(
            signal_id="SIG-001",
            predicted_probability=float("nan"),
            model_version="v1.0",
            calibration_version="UNCALIBRATED",
            feature_schema_version="v1.0",
            prediction_timestamp="2026-09-26T10:00:00+05:30",
            status="UNCALIBRATED",
        )


# ============================================================================
# 7. Calibration Interfaces Tests (4 tests)
# ============================================================================

def test_isotonic_calibration_fit_fails_closed():
    cal = IsotonicCalibrationInterface()
    assert cal.method == "ISOTONIC"
    assert cal.status == "DESIGNED"
    with pytest.raises(CalibrationFitBlockedError) as exc_info:
        cal.fit([0.5, 0.6], [0, 1])
    assert CALIBRATION_FIT_BLOCKED in str(exc_info.value)


def test_platt_calibration_fit_fails_closed():
    cal = PlattCalibrationInterface()
    assert cal.method == "PLATT"
    assert cal.status == "DESIGNED"
    with pytest.raises(CalibrationFitBlockedError) as exc_info:
        cal.fit([0.5, 0.6], [0, 1])
    assert CALIBRATION_FIT_BLOCKED in str(exc_info.value)


def test_isotonic_unfitted_calibrate_raises():
    cal = IsotonicCalibrationInterface()
    with pytest.raises(Exception):
        cal.calibrate([0.5])


def test_platt_unfitted_calibrate_raises():
    cal = PlattCalibrationInterface()
    with pytest.raises(Exception):
        cal.calibrate([0.5])


# ============================================================================
# 8. Evaluation Metrics Mathematical Accuracy Tests (7 tests)
# ============================================================================

def test_metric_roc_auc_perfect_discrimination():
    y_true = [1, 0, 1, 0]
    y_prob = [0.9, 0.1, 0.8, 0.2]
    auc = compute_roc_auc(y_true, y_prob)
    assert auc == 1.0


def test_metric_roc_auc_random_guessing():
    # All predictions tied at 0.5
    y_true = [1, 0]
    y_prob = [0.5, 0.5]
    auc = compute_roc_auc(y_true, y_prob)
    assert auc == 0.5


def test_metric_roc_auc_inverse_discrimination():
    y_true = [1, 0]
    y_prob = [0.1, 0.9]
    auc = compute_roc_auc(y_true, y_prob)
    assert auc == 0.0


def test_metric_roc_auc_single_class_fails_closed():
    assert compute_roc_auc([1, 1, 1], [0.8, 0.7, 0.9]) is None
    assert compute_roc_auc([0, 0], [0.1, 0.2]) is None
    assert compute_roc_auc([], []) is None


def test_metric_brier_score_canonical_values():
    # Perfect
    assert compute_brier_score([1, 0], [1.0, 0.0]) == 0.0

    # Worst
    assert compute_brier_score([1, 0], [0.0, 1.0]) == 1.0

    # Coin-flip on balanced
    assert compute_brier_score([1, 0], [0.5, 0.5]) == 0.25


def test_metric_log_loss_analytical_values_and_clipping():
    # Coin-flip: -ln(0.5) = ln(2) = 0.693147...
    ll = compute_log_loss([1, 0], [0.5, 0.5])
    assert ll is not None
    assert math.isclose(ll, math.log(2), rel_tol=1e-5)

    # Extreme probabilities clipped safely (no math domain error)
    ll_clipped = compute_log_loss([1, 0], [0.0, 1.0])
    assert ll_clipped is not None
    assert ll_clipped > 0.0


def test_metric_ece_and_reliability_bins():
    y_true = [1, 1, 0, 0]
    y_prob = [0.85, 0.85, 0.15, 0.15]
    ece, bins = compute_expected_calibration_error(y_true, y_prob, n_bins=10)
    assert ece is not None
    assert len(bins) == 10
    # Bin [0.8, 0.9) has 2 items, mean_p = 0.85, obs_f = 1.0, gap = 0.15, weighted = (2/4)*0.15 = 0.075
    # Bin [0.1, 0.2) has 2 items, mean_p = 0.15, obs_f = 0.0, gap = 0.15, weighted = (2/4)*0.15 = 0.075
    # Total ECE = 0.15
    assert math.isclose(ece, 0.15, rel_tol=1e-5)


# ============================================================================
# 9. Baseline Comparator & Calibration Separation Tests (4 tests)
# ============================================================================

def test_baseline_comparator_prevalence():
    y_train = [1, 1, 0, 0]
    p_base = BaselineComparator.compute_prevalence_baseline(y_train)
    assert p_base == 0.5


def test_baseline_comparator_candidate_beats_baseline():
    y_val = [1, 0, 1, 0]
    p_base = 0.5
    # Superior candidate
    candidate_prob = [0.9, 0.1, 0.8, 0.2]
    res = BaselineComparator.compare(y_val, candidate_prob, p_base)
    assert res.beats_baseline is True
    assert res.brier_improvement > 0.0
    assert res.log_loss_improvement > 0.0
    assert res.candidate_roc_auc == 1.0


def test_calibration_separation_valid():
    train_records = [{"signal_id": "S1", "snapshot_captured_at": "2026-09-26T10:00:00+05:30"}]
    val_records = [{"signal_id": "S2", "snapshot_captured_at": "2026-09-26T11:00:00+05:30"}]
    holdout_records = [{"signal_id": "S3", "snapshot_captured_at": "2026-09-26T12:00:00+05:30"}]
    is_valid, errors = verify_calibration_separation(train_records, val_records, holdout_records)
    assert is_valid is True
    assert errors == []


def test_calibration_separation_leakage_detected():
    # Overlap between train and val
    train_records = [{"signal_id": "S1", "snapshot_captured_at": "2026-09-26T10:00:00+05:30"}]
    val_records = [{"signal_id": "S1", "snapshot_captured_at": "2026-09-26T11:00:00+05:30"}]
    holdout_records = [{"signal_id": "S3", "snapshot_captured_at": "2026-09-26T12:00:00+05:30"}]
    is_valid, errors = verify_calibration_separation(train_records, val_records, holdout_records)
    assert is_valid is False
    assert any("TRAIN_VALIDATION_LEAKAGE" in e for e in errors)


# ============================================================================
# 10. Model Registry & Reproducibility Manifest Tests (4 tests)
# ============================================================================

def test_model_registry_initial_state_designed():
    registry = ModelRegistry()
    model = registry.register_model("LR-BASE-01", "LOGISTIC_REGRESSION", "v1.0")
    assert model["state"] == ModelLifecycleState.DESIGNED.value


def test_model_registry_approved_transition_prohibited():
    registry = ModelRegistry()
    registry.register_model("LR-BASE-01", "LOGISTIC_REGRESSION", "v1.0")
    with pytest.raises(GovernanceViolationError) as exc_info:
        registry.transition_state("LR-BASE-01", ModelLifecycleState.APPROVED)
    assert "Unauthorized transition" in str(exc_info.value)


def test_model_registry_illegal_transition_rejected():
    registry = ModelRegistry()
    registry.register_model("LR-BASE-01", "LOGISTIC_REGRESSION", "v1.0")
    # Cannot jump from DESIGNED to HOLDOUT_EVALUATED
    with pytest.raises(GovernanceViolationError):
        registry.transition_state("LR-BASE-01", ModelLifecycleState.HOLDOUT_EVALUATED)


def test_reproducibility_manifest_deterministic_serialization(tmp_path):
    manifest = PhaseEExperimentManifest(
        manifest_id="EXP-20260927-001",
        created_at="2026-09-27T12:00:00+05:30",
        git_commit="79d95d52716bf52a0f4a826fc82744e4b6a8d5e7",
        software_version=PHASE_E_SOFTWARE_VERSION,
        feature_schema_version="v1.0-contemporaneous-pit",
        dataset_hash="sha256_mock_dataset_hash",
        model_family="LOGISTIC_REGRESSION",
        model_version="v1.0-unfitted",
        calibration_method="PLATT",
        random_seed=42,
        training_window=("2026-09-26T00:00:00", "2026-10-15T00:00:00"),
        validation_window=("2026-10-15T00:00:00", "2026-10-31T00:00:00"),
        holdout_window=("2026-11-01T00:00:00", "2026-11-15T00:00:00"),
        sample_counts={"train": 0, "val": 0, "holdout": 0},
        execution_readiness_status=VERDICT_PASS_BLOCKED_BY_SAMPLE,
    )
    json_1 = manifest.to_json()
    json_2 = manifest.to_json()
    assert json_1 == json_2
    assert manifest.compute_sha256() == manifest.compute_sha256()

    save_path = tmp_path / "manifest.json"
    manifest.save(save_path)
    assert save_path.exists()
    assert json.loads(save_path.read_text(encoding="utf-8"))["manifest_id"] == "EXP-20260927-001"


# ============================================================================
# 11. Production Database Evaluation & Readiness Integration (4 tests)
# ============================================================================

def test_production_readiness_evaluation_blocked_by_sample():
    # Evaluate actual production DB
    report = evaluate_phase_e_execution_readiness()
    assert report.overall_verdict == VERDICT_PASS_BLOCKED_BY_SAMPLE
    assert report.readiness_architecture_status == "PASS"
    assert report.empirical_execution_status == "BLOCKED_BY_SAMPLE"
    assert report.forward_cohort_size == 0
    assert report.resolved_count == 0
    assert report.gate_1_status == "NOT_SATISFIED"
    assert report.gate_2_status == "NOT_SATISFIED"
    assert report.gate_3_status == "NOT_SATISFIED"
    assert report.gate_4_status == "PASS"
    assert report.probability_source_status == "UNCALIBRATED_NULL"
    assert report.model_fitting_status == "BLOCKED_BY_READINESS_PHASE"
    assert report.calibration_status == "UNCALIBRATED"
    assert any("Genuine forward observations = 0" in r for r in report.blocking_reasons)


def test_production_db_isolation_and_no_probabilities():
    # Ensure production DB connection is read-only and no probabilities exist
    db_file = Path("db/signals_history.db")
    if db_file.exists():
        conn = sqlite3.connect(f"file:{db_file}?mode=ro", uri=True)
        try:
            cur = conn.cursor()
            tbl = cur.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='signal_prediction_snapshots'"
            ).fetchone()
            if tbl:
                cols = [c[1] for c in cur.execute("PRAGMA table_info(signal_prediction_snapshots)").fetchall()]
                prob_cols = [c for c in ("p_t1", "p_t2", "p_sl", "p_timeout", "predicted_probability") if c in cols]
                if prob_cols:
                    where_clause = " OR ".join(f"{c} IS NOT NULL" for c in prob_cols)
                    row = cur.execute(
                        f"SELECT COUNT(*) FROM signal_prediction_snapshots WHERE {where_clause}"
                    ).fetchone()
                    assert row[0] == 0, f"Found {row[0]} non-null probabilities in production snapshots!"
        finally:
            conn.close()


def test_production_safety_locks_intact():
    cfg_path = Path(__file__).resolve().parent.parent / "json" / "config.json"
    with open(cfg_path, encoding="utf-8") as f:
        cfg = json.load(f)

    assert str(cfg.get("EXECUTION_MODE", "")).upper() == "SIGNAL_ONLY"
    assert bool(cfg.get("SIGNAL_ONLY", False)) is True
    assert bool(cfg.get("LIVE_TRADING_LOCKOUT", False)) is True
    assert bool(cfg.get("full_auto_allowed", True)) is False


def test_evaluation_report_serialization():
    report = evaluate_phase_e_execution_readiness()
    d = report.to_dict()
    assert isinstance(d, dict)
    assert d["overall_verdict"] == VERDICT_PASS_BLOCKED_BY_SAMPLE
    assert d["readiness_architecture_status"] == "PASS"
    assert d["empirical_execution_status"] == "BLOCKED_BY_SAMPLE"
