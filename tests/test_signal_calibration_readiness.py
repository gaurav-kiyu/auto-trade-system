"""Tests for Phase E Analytical & Calibration Readiness Framework.

Governance Authority: OPB-FINAL-PHASE-GOVERNANCE-001 / v2.60 Signal Quality Roadmap.

Ensures strict mathematical correctness, governance compliance, data contracts,
probability validation, Brier/ECE computation, temporal isolation, readiness guards,
and safety invariants.
"""

import math
import sqlite3
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from core.signals.signal_calibration_readiness import (
    CALIBRATION_FIT_BLOCKED,
    DEFAULT_ECE_BINS,
    NO_VALID_PROBABILITY_SOURCE,
    STATUS_BLOCKED,
    STATUS_READY_FOR_REVIEW,
    BrierResult,
    CalibrationDiagnostics,
    CalibrationObservation,
    ECEResult,
    PhaseEReadinessReport,
    ReliabilityBin,
    SignalCalibrationReadinessService,
    TemporalSplit,
    calculate_brier_score,
    calculate_expected_calibration_error,
    compute_calibration_diagnostics,
    evaluate_phase_e_readiness,
    filter_calibration_eligibility,
    fit_isotonic_calibration,
    fit_platt_calibration,
    generate_reliability_curve,
    split_chronological_calibration_data,
    validate_calibration_observation_contract,
    validate_probability_source,
)
from core.signals.signal_calibration_report import generate_phase_e_readiness_report


# ============================================================================
# Fixtures & Helpers
# ============================================================================

def make_valid_observation_dict(**overrides) -> dict:
    base = {
        "signal_id": "SIG-TEST-001",
        "prediction_timestamp": "2026-09-26T10:00:00+05:30",
        "market_date": "2026-09-26",
        "score": 85,
        "score_bucket": "85+",
        "direction": "CALL",
        "symbol": "NIFTY26SEP25000CE",
        "category": "INDEX_OPT",
        "entry_price": 120.0,
        "stop_loss": 100.0,
        "target_1": 150.0,
        "target_2": 180.0,
        "terminal_outcome": "TARGET_FIRST",
        "is_resolved": 1,
        "realized_r": 1.5,
        "mfe_r": 1.8,
        "mae_r": 0.2,
        "data_quality_status": "VALID_DATA",
        "cohort_id": "FWD_2026-09",
        "observation_source": "FORWARD_REALTIME",
        "predicted_probability": 0.65,
        "resolution_timestamp": "2026-09-26T11:00:00+05:30",
    }
    base.update(overrides)
    return base


def make_valid_observation(**overrides) -> CalibrationObservation:
    d = make_valid_observation_dict(**overrides)
    _, _, obs = validate_calibration_observation_contract(d)
    assert obs is not None
    return obs


# ============================================================================
# 1. Data Contract Tests
# ============================================================================

def test_data_contract_valid_observation_accepted():
    d = make_valid_observation_dict()
    valid, errors, obs = validate_calibration_observation_contract(d)
    assert valid is True
    assert errors == []
    assert obs is not None
    assert obs.signal_id == "SIG-TEST-001"
    assert obs.score_bucket == "85+"
    assert obs.entry_price == 120.0


def test_data_contract_missing_signal_id_rejected():
    d = make_valid_observation_dict(signal_id="")
    valid, errors, obs = validate_calibration_observation_contract(d)
    assert valid is False
    assert any("signal_id" in err for err in errors)
    assert obs is None


def test_data_contract_invalid_timestamp_rejected():
    d = make_valid_observation_dict(prediction_timestamp="not-a-timestamp")
    valid, errors, obs = validate_calibration_observation_contract(d)
    assert valid is False
    assert any("prediction_timestamp" in err for err in errors)
    assert obs is None


@pytest.mark.parametrize(
    "price_field",
    ["entry_price", "stop_loss", "target_1", "target_2"],
)
def test_data_contract_invalid_price_rejected(price_field):
    # Non-positive values (<= 0) or strings
    d = make_valid_observation_dict(**{price_field: 0.0})
    valid, errors, obs = validate_calibration_observation_contract(d)
    assert valid is False
    assert any(price_field in err for err in errors)

    d_neg = make_valid_observation_dict(**{price_field: -10.0})
    valid_neg, errors_neg, _ = validate_calibration_observation_contract(d_neg)
    assert valid_neg is False
    assert any(price_field in err for err in errors_neg)


# ============================================================================
# 2. Eligibility Filter Tests
# ============================================================================

def test_eligibility_target_first_eligible():
    obs = make_valid_observation(terminal_outcome="TARGET_FIRST", is_resolved=1)
    eligible, reasons = filter_calibration_eligibility(obs)
    assert eligible is True
    assert reasons == []


def test_eligibility_sl_first_eligible():
    obs = make_valid_observation(terminal_outcome="SL_FIRST", is_resolved=1, realized_r=-1.0)
    eligible, reasons = filter_calibration_eligibility(obs)
    assert eligible is True
    assert reasons == []


def test_eligibility_valid_timeout_with_realized_r_eligible():
    obs = make_valid_observation(terminal_outcome="TIMEOUT", is_resolved=1, realized_r=0.25)
    eligible, reasons = filter_calibration_eligibility(obs)
    assert eligible is True
    assert reasons == []


def test_eligibility_timeout_without_realized_r_excluded():
    obs = make_valid_observation(terminal_outcome="TIMEOUT", is_resolved=1, realized_r=None)
    eligible, reasons = filter_calibration_eligibility(obs)
    assert eligible is False
    assert any("INVALID_TIMEOUT" in r for r in reasons)


def test_eligibility_timeout_is_resolved_zero_excluded():
    obs = make_valid_observation(terminal_outcome="TIMEOUT", is_resolved=0, realized_r=0.0)
    eligible, reasons = filter_calibration_eligibility(obs)
    assert eligible is False
    assert any("UNRESOLVED" in r for r in reasons)


def test_eligibility_ambiguous_excluded():
    obs = make_valid_observation(terminal_outcome="AMBIGUOUS", is_resolved=1)
    eligible, reasons = filter_calibration_eligibility(obs)
    assert eligible is False
    assert any("AMBIGUOUS_OUTCOME" in r for r in reasons)


def test_eligibility_no_data_excluded():
    obs = make_valid_observation(terminal_outcome="NO_DATA", is_resolved=0)
    eligible, reasons = filter_calibration_eligibility(obs)
    assert eligible is False
    assert any("NO_DATA" in r or "UNRESOLVED" in r for r in reasons)


def test_eligibility_invalidated_excluded():
    obs = make_valid_observation(terminal_outcome="INVALIDATED", is_resolved=0)
    eligible, reasons = filter_calibration_eligibility(obs)
    assert eligible is False
    assert any("INVALIDATED" in r or "UNRESOLVED" in r for r in reasons)


def test_eligibility_unresolved_excluded():
    obs = make_valid_observation(terminal_outcome="UNRESOLVED", is_resolved=0)
    eligible, reasons = filter_calibration_eligibility(obs)
    assert eligible is False
    assert any("UNRESOLVED" in r for r in reasons)


def test_eligibility_pre_cutoff_excluded():
    obs = make_valid_observation(prediction_timestamp="2026-09-25T15:00:00+05:30")
    eligible, reasons = filter_calibration_eligibility(obs, cutoff_iso="2026-09-26T00:00:00+05:30")
    assert eligible is False
    assert any("PRE_CUTOFF" in r for r in reasons)


def test_eligibility_temporal_lookahead_leakage_excluded():
    # resolution_timestamp is earlier than prediction_timestamp
    obs = make_valid_observation(
        prediction_timestamp="2026-09-26T12:00:00+05:30",
        resolution_timestamp="2026-09-26T11:00:00+05:30",
    )
    eligible, reasons = filter_calibration_eligibility(obs)
    assert eligible is False
    assert any("TEMPORAL_LEAKAGE" in r for r in reasons)


# ============================================================================
# 3. Probability Input Validation & No-Fabrication Tests
# ============================================================================

def test_probability_source_valid_accepted():
    probs = [0.1, 0.5, 0.75, 0.9]
    valid, status, vals, reasons = validate_probability_source(probs)
    assert valid is True
    assert status == "VALID"
    assert vals == probs
    assert reasons == []


def test_probability_source_negative_rejected():
    probs = [0.5, -0.1, 0.8]
    valid, status, _, reasons = validate_probability_source(probs)
    assert valid is False
    assert any("outside [0.0, 1.0]" in r for r in reasons)


def test_probability_source_greater_than_one_rejected():
    probs = [0.5, 1.05, 0.8]
    valid, status, _, reasons = validate_probability_source(probs)
    assert valid is False


def test_probability_source_nan_inf_rejected():
    probs = [0.5, float("nan"), 0.8]
    valid, status, _, reasons = validate_probability_source(probs)
    assert valid is False
    assert any("NaN" in r for r in reasons)


def test_probability_source_empty_or_none_blocked():
    valid, status, _, _ = validate_probability_source([])
    assert valid is False
    assert status == NO_VALID_PROBABILITY_SOURCE

    valid2, status2, _, _ = validate_probability_source(None)
    assert valid2 is False
    assert status2 == NO_VALID_PROBABILITY_SOURCE


def test_probability_source_score_not_treated_as_probability():
    # Passing raw scores (e.g. 75, 85, 90) must be BLOCKED with explicit warning
    scores = [75, 82, 85, 90]
    valid, status, _, reasons = validate_probability_source(scores)
    assert valid is False
    assert status == NO_VALID_PROBABILITY_SOURCE
    assert any("PROBABILITY_FABRICATION_BLOCK" in r for r in reasons)
    assert any("score/100 conversion is strictly prohibited" in r for r in reasons)


# ============================================================================
# 4. Brier Score Tests
# ============================================================================

def test_brier_score_known_calculation():
    # p = [0.8, 0.2, 0.6, 0.1], y = [1, 0, 1, 0]
    # (0.8 - 1)^2 = 0.04
    # (0.2 - 0)^2 = 0.04
    # (0.6 - 1)^2 = 0.16
    # (0.1 - 0)^2 = 0.01
    # Sum = 0.25, Mean = 0.25 / 4 = 0.0625
    probs = [0.8, 0.2, 0.6, 0.1]
    outcomes = [1, 0, 1, 0]
    res = calculate_brier_score(probs, outcomes)
    assert res.status == "VALID"
    assert res.brier_score == pytest.approx(0.0625, abs=1e-5)
    assert res.valid_n == 4
    assert res.invalid_n == 0


def test_brier_score_perfect_prediction():
    probs = [1.0, 0.0, 1.0, 0.0]
    outcomes = [1, 0, 1, 0]
    res = calculate_brier_score(probs, outcomes)
    assert res.brier_score == 0.0


def test_brier_score_worst_prediction():
    probs = [0.0, 1.0]
    outcomes = [1, 0]
    res = calculate_brier_score(probs, outcomes)
    assert res.brier_score == 1.0


def test_brier_score_empty_returns_no_valid_data():
    res = calculate_brier_score([], [])
    assert res.status == "NO_VALID_DATA"
    assert res.brier_score is None


def test_brier_score_invalid_values_rejected_not_clipped():
    probs = [0.8, -0.5, 1.5, 0.2]
    outcomes = [1, 0, 1, 0]
    res = calculate_brier_score(probs, outcomes)
    assert res.valid_n == 2  # Only 0.8 and 0.2 are valid
    assert res.invalid_n == 2
    assert len(res.exclusion_reasons) == 2


def test_brier_score_non_binary_outcome_rejected():
    probs = [0.5, 0.5]
    outcomes = [1, 2]  # 2 is non-binary
    res = calculate_brier_score(probs, outcomes)
    assert res.valid_n == 1
    assert res.invalid_n == 1


# ============================================================================
# 5. Expected Calibration Error (ECE) & Reliability Bins Tests
# ============================================================================

def test_ece_deterministic_bins_count():
    bins = generate_reliability_curve([], [], num_bins=10)
    assert len(bins) == 10
    assert bins[0].bin_lower == 0.0
    assert bins[0].bin_upper == 0.1
    assert bins[-1].bin_upper == 1.0


def test_ece_known_calculation():
    # 2 observations in bin [0.0, 0.5): p = [0.2, 0.4] -> mean_p = 0.3, y = [0, 0] -> obs_rate = 0.0. Gap = 0.3.
    # 2 observations in bin [0.5, 1.0]: p = [0.6, 0.8] -> mean_p = 0.7, y = [1, 1] -> obs_rate = 1.0. Gap = 0.3.
    # Weighted ECE = 0.5 * 0.3 + 0.5 * 0.3 = 0.3.
    probs = [0.2, 0.4, 0.6, 0.8]
    outcomes = [0, 0, 1, 1]
    ece_res = calculate_expected_calibration_error(probs, outcomes, num_bins=2)
    assert ece_res.ece == pytest.approx(0.3, abs=1e-5)
    assert ece_res.total_n == 4


def test_ece_empty_bins_handled_safely():
    probs = [0.25]
    outcomes = [0]
    ece_res = calculate_expected_calibration_error(probs, outcomes, num_bins=10)
    assert ece_res.total_n == 1
    # 9 empty bins have count=0 and contribution=0.0
    empty_bins = [b for b in ece_res.bins if b.count == 0]
    assert len(empty_bins) == 9
    assert all(b.weighted_contribution == 0.0 for b in empty_bins)


def test_ece_all_observations_same_bin():
    probs = [0.82, 0.85, 0.88]
    outcomes = [1, 1, 1]
    ece_res = calculate_expected_calibration_error(probs, outcomes, num_bins=10)
    active_bins = [b for b in ece_res.bins if b.count > 0]
    assert len(active_bins) == 1
    assert active_bins[0].count == 3
    mean_p = (0.82 + 0.85 + 0.88) / 3
    assert active_bins[0].mean_predicted_probability == pytest.approx(mean_p, abs=1e-4)
    assert active_bins[0].observed_frequency == 1.0


# ============================================================================
# 6. Calibration Diagnostics Tests
# ============================================================================

def test_calibration_diagnostics_structure_and_type():
    probs = [0.2] * 20 + [0.8] * 20
    outcomes = [0] * 20 + [1] * 20
    diag = compute_calibration_diagnostics(probs, outcomes, num_bins=5)
    assert isinstance(diag, CalibrationDiagnostics)
    assert diag.diagnostics_type == "DIAGNOSTIC"
    assert diag.brier_result.valid_n == 40
    assert diag.regression_status == "VALID"
    assert diag.calibration_slope is not None
    assert diag.calibration_intercept is not None


def test_calibration_diagnostics_skips_regression_on_small_sample():
    probs = [0.2, 0.8]
    outcomes = [0, 1]
    diag = compute_calibration_diagnostics(probs, outcomes, num_bins=5)
    assert diag.regression_status == "SKIPPED_INSUFFICIENT_SAMPLE"
    assert diag.calibration_slope is None


def test_calibration_diagnostics_skips_regression_on_zero_outcome_variance():
    probs = [0.7] * 35
    outcomes = [1] * 35  # Only 1s, zero variance
    diag = compute_calibration_diagnostics(probs, outcomes, num_bins=5)
    assert diag.regression_status == "ZERO_OUTCOME_VARIANCE"
    assert diag.calibration_slope is None


# ============================================================================
# 7. Temporal Split Tests
# ============================================================================

def test_temporal_split_chronological_valid():
    obs_list = [
        make_valid_observation(signal_id=f"SIG-{i}", prediction_timestamp=f"2026-09-26T10:{i:02d}:00+05:30")
        for i in range(10)
    ]
    split = split_chronological_calibration_data(obs_list, split_ratio=0.7)
    assert split.is_valid is True
    assert len(split.dev_observations) == 7
    assert len(split.val_observations) == 3
    assert split.dev_start == "2026-09-26T10:00:00+05:30"
    assert split.dev_end == "2026-09-26T10:06:00+05:30"
    assert split.val_start == "2026-09-26T10:07:00+05:30"
    assert split.val_end == "2026-09-26T10:09:00+05:30"


def test_temporal_split_rejects_boundary_collision():
    # Observations with identical timestamps spanning the 70% boundary
    obs_list = [
        make_valid_observation(signal_id=f"SIG-{i}", prediction_timestamp="2026-09-26T10:05:00+05:30")
        for i in range(10)
    ]
    split = split_chronological_calibration_data(obs_list, split_ratio=0.7)
    assert split.is_valid is False
    assert "boundary collision" in split.error_message


def test_temporal_split_invalid_ratio_rejected():
    obs_list = [make_valid_observation(signal_id="SIG-1")]
    split = split_chronological_calibration_data(obs_list, split_ratio=0.99)
    assert split.is_valid is False
    assert "split_ratio" in split.error_message


# ============================================================================
# 8. Readiness Evaluation Tests
# ============================================================================

def test_readiness_current_state_returns_blocked():
    report = evaluate_phase_e_readiness()
    assert isinstance(report, PhaseEReadinessReport)
    assert report.overall_status == STATUS_BLOCKED
    assert report.phase_e_status == STATUS_BLOCKED
    assert report.g1_status == "NOT_SATISFIED"
    assert report.g2_status == "NOT_SATISFIED"
    assert report.g3_status == "NOT_SATISFIED"
    assert report.g4_status == "PASS"
    assert report.probability_source_status == NO_VALID_PROBABILITY_SOURCE
    assert report.is_ready_for_calibration is False


def test_readiness_reports_all_required_blocking_reasons():
    report = evaluate_phase_e_readiness()
    blockers = " ".join(report.blocking_reasons)
    assert "Gate 1 not satisfied" in blockers
    assert "Gate 2 not satisfied" in blockers
    assert "Gate 3 not satisfied" in blockers
    assert "Genuine forward observations = 0" in blockers
    assert "Historical data cannot substitute" in blockers
    assert "No valid predicted probability source" in blockers


def test_readiness_all_gates_ready_fixture_returns_ready_for_review():
    mock_gates = {
        "G1": {"passed": True, "actual": {"80-84": 120, "85+": 180}},
        "G2": {"passed": True, "actual": 300},
        "G3": {"passed": True, "actual": 2},
        "G4": {"passed": True, "reason": "clean"},
        "overall": {"status": "READY_FOR_REVIEW", "blocking_gates": []},
    }
    mock_summary = {
        "total_registered": 350,
        "total_resolved": 300,
        "overall_readiness": "READY_FOR_REVIEW",
    }

    with patch(
        "core.signals.signal_forward_monitor.SignalForwardMonitorService.get_readiness_gate_status",
        return_value=mock_gates,
    ), patch(
        "core.signals.signal_forward_monitor.SignalForwardMonitorService.get_forward_summary",
        return_value=mock_summary,
    ):
        probs = [0.5] * 300
        report = evaluate_phase_e_readiness(candidate_probabilities=probs)
        assert report.g1_status == "SATISFIED"
        assert report.g2_status == "SATISFIED"
        assert report.g3_status == "SATISFIED"
        assert report.g4_status == "PASS"
        assert report.probability_source_status == "VALID"
        assert report.overall_status == STATUS_READY_FOR_REVIEW
        assert report.phase_e_status == STATUS_READY_FOR_REVIEW


# ============================================================================
# 9. Guarded Calibration Fitting Tests
# ============================================================================

def test_fit_isotonic_blocked_when_readiness_is_blocked():
    report = evaluate_phase_e_readiness()
    res = fit_isotonic_calibration(report)
    assert res.status == CALIBRATION_FIT_BLOCKED
    assert res.model_fit_attempted is False
    assert any("READINESS_GATE_BLOCK" in r for r in res.blocking_reasons)


def test_fit_platt_blocked_when_readiness_is_blocked():
    report = evaluate_phase_e_readiness()
    res = fit_platt_calibration(report)
    assert res.status == CALIBRATION_FIT_BLOCKED
    assert res.model_fit_attempted is False
    assert any("READINESS_GATE_BLOCK" in r for r in res.blocking_reasons)


# ============================================================================
# 10. Report Generator Tests
# ============================================================================

def test_generate_report_contains_all_16_sections():
    rep = generate_phase_e_readiness_report()
    assert "# OPB v2.60 — PHASE E CALIBRATION READINESS & PREPARATION REPORT" in rep
    for sec_num in range(1, 17):
        assert f"## {sec_num}." in rep
    assert "PHASE E PREPARATION: PASS" in rep
    assert "PHASE E EXECUTION:   NOT STARTED" in rep
    assert "PHASE E CALIBRATION: BLOCKED" in rep


def test_generate_report_no_ranking_or_best_bucket():
    rep = generate_phase_e_readiness_report()
    assert "best bucket" not in rep.lower()
    assert "worst bucket" not in rep.lower()
    assert "winning calibration" not in rep.lower()
    assert "superior model" not in rep.lower()


# ============================================================================
# 11. Safety & Boundary Tests
# ============================================================================

def test_safety_no_execution_imports():
    import core.signals.signal_calibration_readiness as scr
    import core.signals.signal_calibration_report as screp

    # Check imported module names in globals
    for mod in [scr, screp]:
        for k, v in mod.__dict__.items():
            if hasattr(v, "__module__"):
                mod_name = str(getattr(v, "__module__", ""))
                assert not mod_name.startswith("core.execution"), f"Forbidden import of {mod_name} in {mod.__name__}"
                assert not mod_name.startswith("core.broker"), f"Forbidden import of {mod_name} in {mod.__name__}"


def test_service_extract_forward_observations_is_read_only(tmp_path):
    # Verify extraction doesn't mutate or create tables
    db_file = tmp_path / "test_ro.db"
    conn = sqlite3.connect(str(db_file))
    conn.execute(
        """
        CREATE TABLE signal_forward_observations (
            signal_id TEXT, registered_at TEXT, market_date TEXT, score INTEGER,
            score_bucket TEXT, direction TEXT, symbol TEXT, category TEXT,
            entry_price REAL, stop_loss REAL, target_1 REAL, target_2 REAL,
            terminal_outcome TEXT, is_resolved INTEGER, realized_r REAL,
            mfe_r REAL, mae_r REAL, observation_status TEXT, cohort_id TEXT,
            observation_source TEXT, snapshot_captured_at TEXT, resolution_timestamp TEXT
        )
        """
    )
    conn.commit()
    conn.close()

    svc = SignalCalibrationReadinessService.get_instance(db_path=db_file)
    eligible, excluded = svc.extract_calibration_observations()
    assert eligible == []
    assert excluded == []
