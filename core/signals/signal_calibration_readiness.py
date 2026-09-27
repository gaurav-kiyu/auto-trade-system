"""OPB v2.60 — Phase E Analytical & Calibration Readiness Framework.

Governance Authority: OPB-FINAL-PHASE-GOVERNANCE-001 / v2.60 Signal Quality Roadmap.

Role:
Prepares the analytical, diagnostic, and eligibility machinery for Phase-E
calibration studies without actually executing calibration, fitting models,
altering thresholds, modifying signal weights, or enabling live trading.

Strict Governance Invariants:
1. Analytical Only: Absolutely no imports by trading or execution paths.
2. Hard Readiness Guard: Refuses to fit calibration models, produce calibrated
   probabilities, or alter score interpretations when Phase-D readiness gates
   or data prerequisites are not fully satisfied.
3. Zero Probability Fabrication: Scores (e.g. 85) are NEVER converted to
   pseudo-probabilities (0.85 or score/100). If no legitimate predicted probability
   exists, status is strictly NO_VALID_PROBABILITY_SOURCE.
4. Non-Negative Valid Brier & ECE: Mathematically rigorous Brier Score and Expected
   Calibration Error (ECE) with rejection of out-of-bounds probabilities.
5. Strict Temporal Isolation: Chronological dev/val splits; no random shuffling;
   zero temporal overlap or look-ahead leakage.
6. Safe Descriptive Diagnostics: Diagnostics remain descriptive only and do not
   modify underlying predictions or scores.
7. Read-Only Database Access: Pure read-only queries with zero mutations.
"""

from __future__ import annotations

import datetime
import logging
import math
import sqlite3
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from core.datetime_ist import now_ist
from core.signals.signal_forward_monitor import (
    DEFAULT_FORWARD_CUTOFF_ISO,
    FORWARD_CUTOFF_VERSION,
    GATE_MAX_DATA_QUALITY_ERROR_RATE,
    GATE_MAX_STALE_RATE,
    GATE_MIN_DISTINCT_MONTHS,
    GATE_MIN_RESOLVED_PER_ACTIVE_BUCKET,
    GATE_MIN_RESOLVED_PER_MONTH,
    GATE_MIN_TOTAL_RESOLVED,
    SignalForwardMonitorService,
)
from core.signals.signal_outcome_dataset import parse_timestamp
from core.signals.signal_score_discrimination import (
    SCORE_BUCKETS,
    assign_score_bucket,
    calculate_distribution_stats,
    wilson_confidence_interval,
)

_log = logging.getLogger("SIGNAL_CALIBRATION_READINESS")
_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_DB_PATH = _ROOT / "db" / "signals_history.db"

CALIBRATION_FRAMEWORK_VERSION = "PHASE_E_PREPARATION_V1"
DEFAULT_ECE_BINS = 10
MIN_CALIBRATION_SAMPLE_SIZE = 300
MIN_CALIBRATION_DEV_VAL_SIZE = 50

# Governance Status Codes
STATUS_BLOCKED = "BLOCKED"
STATUS_READY_FOR_REVIEW = "READY_FOR_REVIEW"
CALIBRATION_FIT_BLOCKED = "CALIBRATION_FIT_BLOCKED"
NO_VALID_PROBABILITY_SOURCE = "NO_VALID_PROBABILITY_SOURCE"
INSUFFICIENT_SAMPLE = "INSUFFICIENT_SAMPLE"


# ============================================================================
# 1. Data Contracts & Dataclasses
# ============================================================================

@dataclass
class CalibrationObservation:
    """Strict data contract for an individual observation in calibration analysis."""
    signal_id: str
    prediction_timestamp: str
    market_date: str
    score: float | int
    score_bucket: str
    direction: str
    symbol: str
    category: str
    entry_price: float
    stop_loss: float
    target_1: float
    target_2: float
    terminal_outcome: str | None
    is_resolved: int  # 1 if resolved, 0 otherwise
    realized_r: float | None
    mfe_r: float | None
    mae_r: float | None
    data_quality_status: str
    cohort_id: str
    observation_source: str
    predicted_probability: float | None = None
    resolution_timestamp: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BrierResult:
    """Result of Brier Score calculation on binary outcomes."""
    brier_score: float | None
    total_n: int
    valid_n: int
    invalid_n: int
    exclusion_reasons: list[str]
    status: str  # "VALID", "NO_VALID_DATA", "INVALID_INPUT"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ReliabilityBin:
    """Bin specification and empirical metrics for reliability curves and ECE."""
    bin_index: int
    bin_lower: float
    bin_upper: float
    count: int
    mean_predicted_probability: float | None
    observed_frequency: float | None
    absolute_gap: float | None
    weighted_contribution: float | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ECEResult:
    """Expected Calibration Error (ECE) metric and reliability bins."""
    ece: float | None
    num_bins: int
    total_n: int
    bins: list[ReliabilityBin]
    status: str  # "VALID", "INSUFFICIENT_SAMPLE", "NO_VALID_DATA"

    def to_dict(self) -> dict[str, Any]:
        return {
            "ece": self.ece,
            "num_bins": self.num_bins,
            "total_n": self.total_n,
            "bins": [b.to_dict() for b in self.bins],
            "status": self.status,
        }


@dataclass
class CalibrationDiagnostics:
    """Descriptive calibration diagnostic bundle (distinguished from fitted models)."""
    brier_result: BrierResult
    ece_result: ECEResult
    reliability_bins: list[ReliabilityBin]
    calibration_intercept: float | None
    calibration_slope: float | None
    regression_p_value: float | None
    regression_status: str
    diagnostics_status: str
    diagnostics_type: str = "DIAGNOSTIC"

    def to_dict(self) -> dict[str, Any]:
        return {
            "diagnostics_type": self.diagnostics_type,
            "diagnostics_status": self.diagnostics_status,
            "brier_result": self.brier_result.to_dict(),
            "ece_result": self.ece_result.to_dict(),
            "reliability_bins": [b.to_dict() for b in self.reliability_bins],
            "calibration_intercept": self.calibration_intercept,
            "calibration_slope": self.calibration_slope,
            "regression_p_value": self.regression_p_value,
            "regression_status": self.regression_status,
        }


@dataclass
class CalibrationFitResult:
    """Result of a calibration model fitting attempt (refused when not ready)."""
    method: str  # "isotonic", "platt", "logistic"
    status: str  # "CALIBRATION_FIT_BLOCKED", "READY_FOR_REVIEW", etc.
    model_fit_attempted: bool = False
    blocking_reasons: list[str] = field(default_factory=list)
    calibrated_probabilities: list[float] | None = None
    parameters: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TemporalSplit:
    """Strict chronological development and validation data partition."""
    dev_observations: list[CalibrationObservation]
    val_observations: list[CalibrationObservation]
    dev_start: str | None
    dev_end: str | None
    val_start: str | None
    val_end: str | None
    split_ratio: float
    is_valid: bool
    error_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "dev_count": len(self.dev_observations),
            "val_count": len(self.val_observations),
            "dev_start": self.dev_start,
            "dev_end": self.dev_end,
            "val_start": self.val_start,
            "val_end": self.val_end,
            "split_ratio": self.split_ratio,
            "is_valid": self.is_valid,
            "error_message": self.error_message,
        }


@dataclass
class PhaseEReadinessReport:
    """Authoritative Phase-E calibration readiness assessment."""
    overall_status: str  # "BLOCKED" or "READY_FOR_REVIEW"
    phase_d_status: str
    phase_e_status: str  # "BLOCKED" or "READY_FOR_REVIEW"
    g1_status: str       # "SATISFIED" or "NOT_SATISFIED"
    g2_status: str       # "SATISFIED" or "NOT_SATISFIED"
    g3_status: str       # "SATISFIED" or "NOT_SATISFIED"
    g4_status: str       # "PASS" or "FAIL"
    probability_source_status: str  # "VALID" or "NO_VALID_PROBABILITY_SOURCE"
    calibration_sample_status: str  # "SATISFIED" or "NOT_SATISFIED"
    temporal_coverage_status: str   # "SATISFIED" or "NOT_SATISFIED"
    data_quality_status: str        # "PASS" or "FAIL"
    blocking_reasons: list[str]
    eligible_n: int
    excluded_n: int
    generated_at: str

    @property
    def is_ready_for_calibration(self) -> bool:
        return (
            self.overall_status == STATUS_READY_FOR_REVIEW
            and self.phase_e_status == STATUS_READY_FOR_REVIEW
            and len(self.blocking_reasons) == 0
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ============================================================================
# 2. Data Contract Validation & Eligibility Filter
# ============================================================================

def validate_calibration_observation_contract(
    data: dict[str, Any] | CalibrationObservation
) -> tuple[bool, list[str], CalibrationObservation | None]:
    """Validate that raw data satisfies the strict calibration data contract."""
    errors: list[str] = []
    
    if isinstance(data, CalibrationObservation):
        raw = data.to_dict()
    elif isinstance(data, dict):
        raw = dict(data)
    else:
        return False, ["Input must be a dict or CalibrationObservation instance"], None

    # Required identifiers
    sig_id = str(raw.get("signal_id") or "").strip()
    if not sig_id:
        errors.append("Missing required field: signal_id")

    pred_ts = raw.get("prediction_timestamp") or raw.get("captured_at") or raw.get("snapshot_captured_at")
    dt_pred = parse_timestamp(pred_ts)
    if dt_pred is None:
        errors.append(f"Invalid or missing prediction_timestamp: {pred_ts}")

    # Numeric fields
    score = raw.get("score")
    if score is None:
        errors.append("Missing required field: score")
    else:
        try:
            score_val = float(score)
        except (ValueError, TypeError):
            errors.append(f"Invalid numeric score: {score}")
            score_val = 0.0

    bucket = raw.get("score_bucket") or assign_score_bucket(score)
    if not bucket:
        errors.append(f"Could not assign score_bucket for score: {score}")

    direction = str(raw.get("direction") or "").strip().upper()
    if direction not in ("BUY", "SELL", "CALL", "PUT"):
        errors.append(f"Invalid direction: {direction}")

    symbol = str(raw.get("symbol") or "").strip()
    if not symbol:
        errors.append("Missing required field: symbol")

    category = str(raw.get("category") or "").strip()
    if not category:
        errors.append("Missing required field: category")

    # Positive price requirements
    entry_price = raw.get("entry_price")
    try:
        ep_val = float(entry_price)
        if ep_val <= 0:
            errors.append(f"entry_price must be > 0, got {ep_val}")
    except (ValueError, TypeError):
        errors.append(f"Invalid numeric entry_price: {entry_price}")
        ep_val = 0.0

    stop_loss = raw.get("stop_loss")
    try:
        sl_val = float(stop_loss)
        if sl_val <= 0:
            errors.append(f"stop_loss must be > 0, got {sl_val}")
    except (ValueError, TypeError):
        errors.append(f"Invalid numeric stop_loss: {stop_loss}")
        sl_val = 0.0

    target_1 = raw.get("target_1")
    try:
        t1_val = float(target_1)
        if t1_val <= 0:
            errors.append(f"target_1 must be > 0, got {t1_val}")
    except (ValueError, TypeError):
        errors.append(f"Invalid numeric target_1: {target_1}")
        t1_val = 0.0

    target_2 = raw.get("target_2")
    try:
        t2_val = float(target_2)
        if t2_val <= 0:
            errors.append(f"target_2 must be > 0, got {t2_val}")
    except (ValueError, TypeError):
        errors.append(f"Invalid numeric target_2: {target_2}")
        t2_val = 0.0

    # Optional probability
    prob = raw.get("predicted_probability")
    prob_val: float | None = None
    if prob is not None:
        try:
            prob_val = float(prob)
        except (ValueError, TypeError):
            errors.append(f"Invalid predicted_probability: {prob}")

    if errors:
        return False, errors, None

    obs = CalibrationObservation(
        signal_id=sig_id,
        prediction_timestamp=dt_pred.isoformat(),
        market_date=str(raw.get("market_date") or dt_pred.strftime("%Y-%m-%d")),
        score=score_val,
        score_bucket=bucket,
        direction=direction,
        symbol=symbol,
        category=category,
        entry_price=ep_val,
        stop_loss=sl_val,
        target_1=t1_val,
        target_2=t2_val,
        terminal_outcome=str(raw.get("terminal_outcome") or raw.get("outcome") or "").strip() or None,
        is_resolved=int(raw.get("is_resolved", 0)),
        realized_r=float(raw["realized_r"]) if raw.get("realized_r") is not None else None,
        mfe_r=float(raw["mfe_r"]) if raw.get("mfe_r") is not None else None,
        mae_r=float(raw["mae_r"]) if raw.get("mae_r") is not None else None,
        data_quality_status=str(raw.get("data_quality_status") or "VALID_DATA"),
        cohort_id=str(raw.get("cohort_id") or "FWD_DEFAULT"),
        observation_source=str(raw.get("observation_source") or "FORWARD_REALTIME"),
        predicted_probability=prob_val,
        resolution_timestamp=str(raw.get("resolution_timestamp") or "") or None,
    )
    return True, [], obs


def filter_calibration_eligibility(
    obs: CalibrationObservation,
    cutoff_iso: str = DEFAULT_FORWARD_CUTOFF_ISO,
) -> tuple[bool, list[str]]:
    """Determine whether an observation is strictly eligible for calibration analysis.

    Eligible candidates:
    - Post-cutoff forward observation: prediction_timestamp >= cutoff_iso
    - Valid data quality status: not 'INVALID_DATA'
    - Terminal outcome is TARGET_FIRST or SL_FIRST, or valid TIMEOUT with is_resolved=1 and valid realized_r
    - Timestamps valid and resolution_timestamp >= prediction_timestamp (no look-ahead)
    - Valid price geometry (entry, stop, targets > 0)

    Ineligible candidates (with explicit reasons):
    - AMBIGUOUS, NO_DATA, INVALIDATED, UNRESOLVED (is_resolved != 1)
    - Pre-cutoff records
    - Temporal inconsistencies / look-ahead leakage
    """
    reasons: list[str] = []

    # 1. Post-cutoff verification
    dt_pred = parse_timestamp(obs.prediction_timestamp)
    dt_cutoff = parse_timestamp(cutoff_iso)
    if dt_pred and dt_cutoff:
        # Standardize for comparison
        dt_pred_naive = dt_pred.astimezone(datetime.timezone.utc).replace(tzinfo=None) if dt_pred.tzinfo else dt_pred
        dt_cut_naive = dt_cutoff.astimezone(datetime.timezone.utc).replace(tzinfo=None) if dt_cutoff.tzinfo else dt_cutoff
        if dt_pred_naive < dt_cut_naive:
            reasons.append(f"PRE_CUTOFF: timestamp {obs.prediction_timestamp} predates cutoff {cutoff_iso}")

    # 2. Data Quality
    if obs.data_quality_status.upper() in ("INVALID_DATA", "DATA_QUALITY_ERROR", "CORRUPTED"):
        reasons.append(f"INVALID_DATA_QUALITY: status is {obs.data_quality_status}")

    # 3. Price Validity
    if obs.entry_price <= 0 or obs.stop_loss <= 0 or obs.target_1 <= 0 or obs.target_2 <= 0:
        reasons.append("INVALID_PRICE_DATA: one or more price levels <= 0")

    # 4. Resolution Status and Terminal Outcome
    outcome = (obs.terminal_outcome or "").upper()
    if obs.is_resolved != 1:
        reasons.append(f"UNRESOLVED: is_resolved={obs.is_resolved}, outcome={outcome}")
    elif outcome in ("AMBIGUOUS", "AMBIGUOUS_SAME_BAR"):
        reasons.append("AMBIGUOUS_OUTCOME: quarantined, cannot serve as ground truth")
    elif outcome in ("NO_DATA", "MISSING_DATA"):
        reasons.append("NO_DATA: observation window lacks market data")
    elif outcome in ("INVALIDATED", "CANCELLED"):
        reasons.append(f"INVALIDATED_OUTCOME: outcome is {outcome}")
    elif outcome == "UNRESOLVED":
        reasons.append("UNRESOLVED: outcome is marked UNRESOLVED")
    elif outcome not in ("TARGET_FIRST", "SL_FIRST", "TIMEOUT"):
        reasons.append(f"UNRECOGNIZED_OUTCOME: outcome {outcome} is not an authorized terminal state")
    elif outcome == "TIMEOUT":
        if obs.realized_r is None:
            reasons.append("INVALID_TIMEOUT: TIMEOUT record missing realized_r calculation")

    # 5. Temporal Look-Ahead / Consistency Check
    if obs.resolution_timestamp:
        dt_res = parse_timestamp(obs.resolution_timestamp)
        if dt_res and dt_pred:
            res_naive = dt_res.astimezone(datetime.timezone.utc).replace(tzinfo=None) if dt_res.tzinfo else dt_res
            pred_naive = dt_pred.astimezone(datetime.timezone.utc).replace(tzinfo=None) if dt_pred.tzinfo else dt_pred
            if res_naive < pred_naive:
                reasons.append("TEMPORAL_LEAKAGE: resolution_timestamp is earlier than prediction_timestamp")

    is_eligible = len(reasons) == 0
    return is_eligible, reasons


# ============================================================================
# 3. Probability Source Validation & Strict No-Fabrication Rule
# ============================================================================

def validate_probability_source(
    probabilities: list[Any] | None,
) -> tuple[bool, str, list[float], list[str]]:
    """Validate candidate probability inputs under strict governance.

    Absolute Rule:
    - Scores (e.g. 70-95) CANNOT be treated as probabilities.
    - score / 100 conversion is strictly FORBIDDEN.
    - Values must be strictly bounded in [0.0, 1.0].
    - Out-of-bounds values are REJECTED, not silently clipped.

    Returns:
        (is_valid, status, valid_probabilities, rejection_reasons)
    """
    if probabilities is None or len(probabilities) == 0:
        return False, NO_VALID_PROBABILITY_SOURCE, [], ["No probability array provided"]

    rejection_reasons: list[str] = []
    valid_floats: list[float] = []

    # Check for suspected score array
    numeric_candidates: list[float] = []
    for idx, p in enumerate(probabilities):
        if p is None:
            rejection_reasons.append(f"Index {idx}: null probability")
            continue
        try:
            val = float(p)
            if math.isnan(val) or math.isinf(val):
                rejection_reasons.append(f"Index {idx}: NaN or Inf probability")
                continue
            numeric_candidates.append(val)
        except (ValueError, TypeError):
            rejection_reasons.append(f"Index {idx}: non-numeric probability '{p}'")

    if not numeric_candidates:
        return False, NO_VALID_PROBABILITY_SOURCE, [], rejection_reasons

    # Check if this looks like a score distribution (e.g. values > 1.0 or mean > 10.0)
    avg_val = sum(numeric_candidates) / len(numeric_candidates)
    max_val = max(numeric_candidates)
    if max_val > 1.0 or avg_val > 1.0:
        msg = (
            f"PROBABILITY_FABRICATION_BLOCK: detected score-scale inputs "
            f"(max={max_val}, mean={round(avg_val, 2)}). Scores CANNOT be treated as "
            f"probabilities, and score/100 conversion is strictly prohibited."
        )
        _log.warning(msg)
        return False, NO_VALID_PROBABILITY_SOURCE, [], [msg] + rejection_reasons

    # Validate range [0.0, 1.0]
    for idx, val in enumerate(numeric_candidates):
        if val < 0.0 or val > 1.0:
            rejection_reasons.append(f"Index {idx}: probability {val} outside [0.0, 1.0]")
        else:
            valid_floats.append(round(val, 6))

    if rejection_reasons:
        return False, "INVALID_PROBABILITY_VALUES", valid_floats, rejection_reasons

    return True, "VALID", valid_floats, []


# ============================================================================
# 4. Brier Score Calculator
# ============================================================================

def calculate_brier_score(
    probabilities: list[float] | None,
    outcomes: list[int | float] | None,
) -> BrierResult:
    """Calculate the Brier Score for binary outcomes.

    Brier = (1/N) * sum((p_i - y_i)^2)
    where:
        p_i in [0.0, 1.0] (predicted probability)
        y_i in {0, 1}     (observed binary event: 1 = target, 0 = failure/SL)

    Invalid values are rejected rather than silently clipped.
    """
    if probabilities is None or outcomes is None:
        return BrierResult(
            brier_score=None,
            total_n=0,
            valid_n=0,
            invalid_n=0,
            exclusion_reasons=["Probabilities or outcomes array is None"],
            status="NO_VALID_DATA",
        )

    if len(probabilities) != len(outcomes):
        return BrierResult(
            brier_score=None,
            total_n=len(probabilities),
            valid_n=0,
            invalid_n=len(probabilities),
            exclusion_reasons=[f"Length mismatch: {len(probabilities)} probs vs {len(outcomes)} outcomes"],
            status="INVALID_INPUT",
        )

    total_n = len(probabilities)
    if total_n == 0:
        return BrierResult(
            brier_score=None,
            total_n=0,
            valid_n=0,
            invalid_n=0,
            exclusion_reasons=["Empty input dataset"],
            status="NO_VALID_DATA",
        )

    valid_pairs: list[tuple[float, int]] = []
    exclusion_reasons: list[str] = []

    for i in range(total_n):
        p = probabilities[i]
        y = outcomes[i]

        # Validate probability
        if p is None or math.isnan(p) or math.isinf(p) or p < 0.0 or p > 1.0:
            exclusion_reasons.append(f"Pair {i}: invalid probability {p}")
            continue

        # Validate binary outcome
        if y not in (0, 1, 0.0, 1.0):
            exclusion_reasons.append(f"Pair {i}: non-binary outcome {y}")
            continue

        valid_pairs.append((float(p), int(y)))

    valid_n = len(valid_pairs)
    invalid_n = total_n - valid_n

    if valid_n == 0:
        return BrierResult(
            brier_score=None,
            total_n=total_n,
            valid_n=0,
            invalid_n=invalid_n,
            exclusion_reasons=exclusion_reasons,
            status="NO_VALID_DATA",
        )

    squared_errors = [(p - y) ** 2 for p, y in valid_pairs]
    brier = sum(squared_errors) / valid_n

    return BrierResult(
        brier_score=round(brier, 6),
        total_n=total_n,
        valid_n=valid_n,
        invalid_n=invalid_n,
        exclusion_reasons=exclusion_reasons,
        status="VALID",
    )


# ============================================================================
# 5. Expected Calibration Error (ECE) & Reliability Curves
# ============================================================================

def generate_reliability_curve(
    probabilities: list[float] | None,
    outcomes: list[int | float] | None,
    num_bins: int = DEFAULT_ECE_BINS,
) -> list[ReliabilityBin]:
    """Generate deterministic reliability curve bins for calibration inspection.

    Divides [0.0, 1.0] into num_bins equal-width intervals.
    Bin k: [k/B, (k+1)/B) for k < B-1, and [ (B-1)/B, 1.0 ] for the last bin.
    """
    if num_bins <= 0:
        num_bins = DEFAULT_ECE_BINS

    # Initialize empty bins
    bins: list[ReliabilityBin] = []
    step = 1.0 / num_bins
    for b in range(num_bins):
        lower = round(b * step, 4)
        upper = round(1.0 if b == num_bins - 1 else (b + 1) * step, 4)
        bins.append(
            ReliabilityBin(
                bin_index=b,
                bin_lower=lower,
                bin_upper=upper,
                count=0,
                mean_predicted_probability=None,
                observed_frequency=None,
                absolute_gap=None,
                weighted_contribution=None,
            )
        )

    if not probabilities or not outcomes or len(probabilities) != len(outcomes):
        return bins

    # Collect observations per bin
    bin_probs: list[list[float]] = [[] for _ in range(num_bins)]
    bin_events: list[list[int]] = [[] for _ in range(num_bins)]

    for p, y in zip(probabilities, outcomes):
        if p is None or y not in (0, 1, 0.0, 1.0) or p < 0.0 or p > 1.0:
            continue
        p_val = float(p)
        y_val = int(y)

        # Assign to bin
        b_idx = int(p_val * num_bins)
        if b_idx >= num_bins:
            b_idx = num_bins - 1
        bin_probs[b_idx].append(p_val)
        bin_events[b_idx].append(y_val)

    total_valid = sum(len(bp) for bp in bin_probs)

    for b in range(num_bins):
        cnt = len(bin_probs[b])
        bins[b].count = cnt
        if cnt > 0:
            mean_p = sum(bin_probs[b]) / cnt
            obs_rate = sum(bin_events[b]) / cnt
            gap = abs(mean_p - obs_rate)
            contrib = (cnt / total_valid) * gap if total_valid > 0 else 0.0
            bins[b].mean_predicted_probability = round(mean_p, 4)
            bins[b].observed_frequency = round(obs_rate, 4)
            bins[b].absolute_gap = round(gap, 4)
            bins[b].weighted_contribution = round(contrib, 6)
        else:
            bins[b].absolute_gap = 0.0
            bins[b].weighted_contribution = 0.0

    return bins


def calculate_expected_calibration_error(
    probabilities: list[float] | None,
    outcomes: list[int | float] | None,
    num_bins: int = DEFAULT_ECE_BINS,
) -> ECEResult:
    """Calculate the Expected Calibration Error (ECE) across deterministic bins."""
    bins = generate_reliability_curve(probabilities, outcomes, num_bins=num_bins)
    total_n = sum(b.count for b in bins)

    if total_n == 0:
        return ECEResult(
            ece=None,
            num_bins=num_bins,
            total_n=0,
            bins=bins,
            status="NO_VALID_DATA",
        )

    ece_val = sum(b.weighted_contribution for b in bins if b.weighted_contribution is not None)
    status = "VALID" if total_n >= 30 else "INSUFFICIENT_SAMPLE"

    return ECEResult(
        ece=round(ece_val, 6),
        num_bins=num_bins,
        total_n=total_n,
        bins=bins,
        status=status,
    )


# ============================================================================
# 6. Calibration Diagnostics
# ============================================================================

def compute_calibration_diagnostics(
    probabilities: list[float] | None,
    outcomes: list[int | float] | None,
    num_bins: int = DEFAULT_ECE_BINS,
) -> CalibrationDiagnostics:
    """Compute comprehensive descriptive calibration diagnostics.

    Guarantees:
    - Purely diagnostic; does not modify model predictions.
    - Estimates calibration slope and intercept via linear/logistic regression
      only when sample size and variance are statistically sufficient (n >= 30, both classes present).
    """
    brier = calculate_brier_score(probabilities, outcomes)
    ece = calculate_expected_calibration_error(probabilities, outcomes, num_bins=num_bins)
    bins = ece.bins

    intercept: float | None = None
    slope: float | None = None
    p_val: float | None = None
    reg_status = "SKIPPED_INSUFFICIENT_SAMPLE"

    if brier.valid_n >= 30 and outcomes and probabilities:
        # Check variance in outcomes
        unique_y = set(y for y in outcomes if y in (0, 1, 0.0, 1.0))
        if len(unique_y) >= 2:
            try:
                from scipy import stats
                valid_p = [float(p) for p, y in zip(probabilities, outcomes) if p is not None and y in (0, 1)]
                valid_y = [float(y) for p, y in zip(probabilities, outcomes) if p is not None and y in (0, 1)]

                if len(valid_p) >= 30:
                    lin_reg = stats.linregress(valid_p, valid_y)
                    slope = round(float(lin_reg.slope), 4)
                    intercept = round(float(lin_reg.intercept), 4)
                    p_val = round(float(lin_reg.pvalue), 6)
                    reg_status = "VALID"
            except Exception as ex:
                reg_status = f"CALCULATION_ERROR: {ex}"
        else:
            reg_status = "ZERO_OUTCOME_VARIANCE"

    diag_status = "VALID" if brier.status == "VALID" and ece.status == "VALID" else "INSUFFICIENT_DATA"

    return CalibrationDiagnostics(
        brier_result=brier,
        ece_result=ece,
        reliability_bins=bins,
        calibration_intercept=intercept,
        calibration_slope=slope,
        regression_p_value=p_val,
        regression_status=reg_status,
        diagnostics_status=diag_status,
        diagnostics_type="DIAGNOSTIC",
    )


# ============================================================================
# 7. Strict Chronological Temporal Split API
# ============================================================================

def split_chronological_calibration_data(
    observations: list[CalibrationObservation],
    split_ratio: float = 0.70,
) -> TemporalSplit:
    """Split observations strictly chronologically into development and validation cohorts.

    Governance Rules:
    - Never random-shuffle observations.
    - Development cohort strictly precedes validation cohort.
    - Rejects overlapping timestamps at the partition boundary.
    - Future leakage is strictly rejected.
    """
    if not observations:
        return TemporalSplit(
            dev_observations=[],
            val_observations=[],
            dev_start=None,
            dev_end=None,
            val_start=None,
            val_end=None,
            split_ratio=split_ratio,
            is_valid=False,
            error_message="Empty observation list",
        )

    if not (0.1 <= split_ratio <= 0.9):
        return TemporalSplit(
            dev_observations=[],
            val_observations=[],
            dev_start=None,
            dev_end=None,
            val_start=None,
            val_end=None,
            split_ratio=split_ratio,
            is_valid=False,
            error_message=f"Invalid split_ratio: {split_ratio}. Must be in [0.1, 0.9]",
        )

    # Sort strictly chronologically by prediction_timestamp
    def get_sort_key(obs: CalibrationObservation) -> tuple[datetime.datetime, str]:
        dt = parse_timestamp(obs.prediction_timestamp) or datetime.datetime.min
        if dt.tzinfo is not None:
            dt = dt.astimezone(datetime.timezone.utc).replace(tzinfo=None)
        return (dt, obs.signal_id)

    sorted_obs = sorted(observations, key=get_sort_key)
    n_total = len(sorted_obs)

    dev_n = int(math.floor(n_total * split_ratio))
    if dev_n < 1 or (n_total - dev_n) < 1:
        return TemporalSplit(
            dev_observations=[],
            val_observations=[],
            dev_start=None,
            dev_end=None,
            val_start=None,
            val_end=None,
            split_ratio=split_ratio,
            is_valid=False,
            error_message="Insufficient observations to form both dev and val splits",
        )

    dev_cohort = sorted_obs[:dev_n]
    val_cohort = sorted_obs[dev_n:]

    dev_start = dev_cohort[0].prediction_timestamp
    dev_end = dev_cohort[-1].prediction_timestamp
    val_start = val_cohort[0].prediction_timestamp
    val_end = val_cohort[-1].prediction_timestamp

    # Boundary overlap & leakage verification
    dt_dev_end = parse_timestamp(dev_end)
    dt_val_start = parse_timestamp(val_start)

    if dt_dev_end and dt_val_start:
        norm_dev_end = dt_dev_end.astimezone(datetime.timezone.utc).replace(tzinfo=None) if dt_dev_end.tzinfo else dt_dev_end
        norm_val_start = dt_val_start.astimezone(datetime.timezone.utc).replace(tzinfo=None) if dt_val_start.tzinfo else dt_val_start

        if norm_dev_end > norm_val_start:
            return TemporalSplit(
                dev_observations=dev_cohort,
                val_observations=val_cohort,
                dev_start=dev_start,
                dev_end=dev_end,
                val_start=val_start,
                val_end=val_end,
                split_ratio=split_ratio,
                is_valid=False,
                error_message=f"Temporal overlap detected: dev_end ({dev_end}) > val_start ({val_start})",
            )
        elif norm_dev_end == norm_val_start:
            # Check if identical timestamp boundary occurs across dev and val
            return TemporalSplit(
                dev_observations=dev_cohort,
                val_observations=val_cohort,
                dev_start=dev_start,
                dev_end=dev_end,
                val_start=val_start,
                val_end=val_end,
                split_ratio=split_ratio,
                is_valid=False,
                error_message=f"Temporal boundary collision: dev_end equals val_start ({dev_end})",
            )

    return TemporalSplit(
        dev_observations=dev_cohort,
        val_observations=val_cohort,
        dev_start=dev_start,
        dev_end=dev_end,
        val_start=val_start,
        val_end=val_end,
        split_ratio=split_ratio,
        is_valid=True,
        error_message=None,
    )


# ============================================================================
# 8. Guarded Calibration Fitting Interfaces (Isotonic & Platt)
# ============================================================================

def fit_isotonic_calibration(
    readiness_report: PhaseEReadinessReport,
    split: TemporalSplit | None = None,
) -> CalibrationFitResult:
    """Attempt Isotonic Regression calibration with hard readiness guards.

    Refuses to execute if readiness conditions are not satisfied.
    """
    blocking_reasons: list[str] = []

    if not readiness_report.is_ready_for_calibration:
        blocking_reasons.append(
            f"READINESS_GATE_BLOCK: Phase-E status is {readiness_report.phase_e_status} "
            f"(overall: {readiness_report.overall_status})"
        )
        for r in readiness_report.blocking_reasons:
            blocking_reasons.append(f"Prerequisite failure: {r}")

    if split is None or not split.is_valid:
        blocking_reasons.append(
            f"TEMPORAL_SPLIT_BLOCK: Valid chronological split required. "
            f"Details: {split.error_message if split else 'No split provided'}"
        )
    elif len(split.dev_observations) < MIN_CALIBRATION_DEV_VAL_SIZE:
        blocking_reasons.append(
            f"SAMPLE_SIZE_BLOCK: Development split has {len(split.dev_observations)} observations "
            f"(minimum {MIN_CALIBRATION_DEV_VAL_SIZE} required)"
        )

    # Return blocked result unconditionally if any guard fires
    if blocking_reasons:
        _log.info("Isotonic calibration fit blocked: %s", blocking_reasons)
        return CalibrationFitResult(
            method="isotonic",
            status=CALIBRATION_FIT_BLOCKED,
            model_fit_attempted=False,
            blocking_reasons=blocking_reasons,
            calibrated_probabilities=None,
            parameters={},
        )

    # In future Phase E execution (when gates pass), fitting logic will reside here
    return CalibrationFitResult(
        method="isotonic",
        status=STATUS_READY_FOR_REVIEW,
        model_fit_attempted=False,
        blocking_reasons=["Awaiting formal Phase E initiation"],
    )


def fit_platt_calibration(
    readiness_report: PhaseEReadinessReport,
    split: TemporalSplit | None = None,
) -> CalibrationFitResult:
    """Attempt Platt / Logistic calibration with hard readiness guards.

    Refuses to execute if readiness conditions are not satisfied.
    """
    blocking_reasons: list[str] = []

    if not readiness_report.is_ready_for_calibration:
        blocking_reasons.append(
            f"READINESS_GATE_BLOCK: Phase-E status is {readiness_report.phase_e_status} "
            f"(overall: {readiness_report.overall_status})"
        )
        for r in readiness_report.blocking_reasons:
            blocking_reasons.append(f"Prerequisite failure: {r}")

    if split is None or not split.is_valid:
        blocking_reasons.append(
            f"TEMPORAL_SPLIT_BLOCK: Valid chronological split required. "
            f"Details: {split.error_message if split else 'No split provided'}"
        )
    elif len(split.dev_observations) < MIN_CALIBRATION_DEV_VAL_SIZE:
        blocking_reasons.append(
            f"SAMPLE_SIZE_BLOCK: Development split has {len(split.dev_observations)} observations "
            f"(minimum {MIN_CALIBRATION_DEV_VAL_SIZE} required)"
        )

    if blocking_reasons:
        _log.info("Platt calibration fit blocked: %s", blocking_reasons)
        return CalibrationFitResult(
            method="platt",
            status=CALIBRATION_FIT_BLOCKED,
            model_fit_attempted=False,
            blocking_reasons=blocking_reasons,
            calibrated_probabilities=None,
            parameters={},
        )

    return CalibrationFitResult(
        method="platt",
        status=STATUS_READY_FOR_REVIEW,
        model_fit_attempted=False,
        blocking_reasons=["Awaiting formal Phase E initiation"],
    )


# ============================================================================
# 9. Readiness Evaluation Engine
# ============================================================================

def evaluate_phase_e_readiness(
    db_path: Path | str | None = None,
    candidate_probabilities: list[float] | None = None,
    cutoff_iso: str = DEFAULT_FORWARD_CUTOFF_ISO,
) -> PhaseEReadinessReport:
    """Evaluate whether the system satisfies all empirical gates to start Phase E.

    Checks:
    1. Phase-D Gates (G1: >= 100/active bucket, G2: >= 300 total, G3: >= 2 months >= 30/mo, G4: DQ <= 5%, Stale <= 2%)
    2. Genuine forward population count (> 0)
    3. Legitimate predicted probability source existence
    4. Historical holdout prohibition
    """
    effective_db = Path(db_path) if db_path else _DEFAULT_DB_PATH
    monitor_svc = SignalForwardMonitorService.get_instance(db_path=effective_db)
    gates_data = monitor_svc.get_readiness_gate_status()
    summary_data = monitor_svc.get_forward_summary()

    blocking_reasons: list[str] = []

    # 1. Gate 1 Evaluation
    g1 = gates_data.get("G1", {})
    g1_satisfied = bool(g1.get("passed", False))
    g1_status = "SATISFIED" if g1_satisfied else "NOT_SATISFIED"
    if not g1_satisfied:
        blocking_reasons.append(
            f"Forward Gate 1 not satisfied: active buckets require >= {GATE_MIN_RESOLVED_PER_ACTIVE_BUCKET} "
            f"resolved observations (current: {g1.get('actual', {})})"
        )

    # 2. Gate 2 Evaluation
    g2 = gates_data.get("G2", {})
    g2_satisfied = bool(g2.get("passed", False))
    g2_status = "SATISFIED" if g2_satisfied else "NOT_SATISFIED"
    if not g2_satisfied:
        blocking_reasons.append(
            f"Forward Gate 2 not satisfied: {g2.get('actual', 0)} total resolved "
            f"forward observations (minimum {GATE_MIN_TOTAL_RESOLVED} required)"
        )

    # 3. Gate 3 Evaluation
    g3 = gates_data.get("G3", {})
    g3_satisfied = bool(g3.get("passed", False))
    g3_status = "SATISFIED" if g3_satisfied else "NOT_SATISFIED"
    if not g3_satisfied:
        blocking_reasons.append(
            f"Forward Gate 3 not satisfied: {g3.get('actual', 0)} qualifying "
            f"forward months (minimum {GATE_MIN_DISTINCT_MONTHS} months with >= {GATE_MIN_RESOLVED_PER_MONTH} resolved required)"
        )

    # 4. Gate 4 Evaluation
    g4 = gates_data.get("G4", {})
    g4_pass = bool(g4.get("passed", False))
    g4_status = "PASS" if g4_pass else "FAIL"
    if not g4_pass:
        blocking_reasons.append(
            f"Forward Gate 4 failed: data quality error rate or stale rate exceeded thresholds: {g4.get('reason')}"
        )

    # 5. Forward Population Count
    total_forward_registered = summary_data.get("total_registered", 0)
    if total_forward_registered == 0:
        blocking_reasons.append("Genuine forward observations = 0; Phase D forward accumulation is currently active")

    # 6. Historical Data Non-Substitution Rule
    blocking_reasons.append("Historical data cannot substitute for forward observations")

    # 7. Probability Source Validation
    prob_valid, prob_status, _, prob_reasons = validate_probability_source(candidate_probabilities)
    if not prob_valid:
        blocking_reasons.append(
            "No valid predicted probability source exists; converting scores to probabilities is strictly prohibited"
        )

    # Sample size and temporal coverage summaries
    sample_status = "SATISFIED" if (g1_satisfied and g2_satisfied) else "NOT_SATISFIED"
    temporal_status = "SATISFIED" if g3_satisfied else "NOT_SATISFIED"
    dq_status = g4_status

    # Overall and Phase-E statuses
    is_fully_ready = (
        g1_satisfied
        and g2_satisfied
        and g3_satisfied
        and g4_pass
        and total_forward_registered > 0
        and prob_valid
    )

    overall_status = STATUS_READY_FOR_REVIEW if is_fully_ready else STATUS_BLOCKED
    phase_e_status = STATUS_READY_FOR_REVIEW if is_fully_ready else STATUS_BLOCKED

    # Filtered unique blocking reasons
    unique_blockers: list[str] = []
    for b in blocking_reasons:
        if b not in unique_blockers:
            unique_blockers.append(b)

    return PhaseEReadinessReport(
        overall_status=overall_status,
        phase_d_status=str(summary_data.get("overall_readiness") or "INSUFFICIENT_SAMPLE"),
        phase_e_status=phase_e_status,
        g1_status=g1_status,
        g2_status=g2_status,
        g3_status=g3_status,
        g4_status=g4_status,
        probability_source_status="VALID" if prob_valid else NO_VALID_PROBABILITY_SOURCE,
        calibration_sample_status=sample_status,
        temporal_coverage_status=temporal_status,
        data_quality_status=dq_status,
        blocking_reasons=unique_blockers,
        eligible_n=summary_data.get("total_resolved", 0),
        excluded_n=summary_data.get("total_registered", 0) - summary_data.get("total_resolved", 0),
        generated_at=now_ist().isoformat(),
    )


# ============================================================================
# 10. Service Singleton
# ============================================================================

class SignalCalibrationReadinessService:
    """Thread-safe analytical singleton for Phase E preparation and readiness."""

    _instance: SignalCalibrationReadinessService | None = None
    _lock = threading.Lock()

    def __init__(self, db_path: Path | str | None = None) -> None:
        self._db_path = Path(db_path) if db_path else _DEFAULT_DB_PATH
        self._io_lock = threading.Lock()

    @classmethod
    def get_instance(cls, db_path: Path | str | None = None) -> SignalCalibrationReadinessService:
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls(db_path=db_path)
            elif db_path and Path(db_path) != cls._instance._db_path:
                cls._instance = cls(db_path=db_path)
            return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        with cls._lock:
            cls._instance = None

    def evaluate_readiness(
        self,
        candidate_probabilities: list[float] | None = None,
        cutoff_iso: str = DEFAULT_FORWARD_CUTOFF_ISO,
    ) -> PhaseEReadinessReport:
        """Evaluate platform readiness for Phase E calibration."""
        return evaluate_phase_e_readiness(
            db_path=self._db_path,
            candidate_probabilities=candidate_probabilities,
            cutoff_iso=cutoff_iso,
        )

    def extract_calibration_observations(
        self,
        cutoff_iso: str = DEFAULT_FORWARD_CUTOFF_ISO,
    ) -> tuple[list[CalibrationObservation], list[dict[str, Any]]]:
        """Extract and filter forward observations for calibration analysis strictly read-only."""
        if not self._db_path.is_file():
            return [], []

        with self._io_lock:
            try:
                conn = sqlite3.connect(f"file:{self._db_path}?mode=ro", uri=True, timeout=10)
            except Exception:
                conn = sqlite3.connect(str(self._db_path), timeout=10)
            conn.row_factory = sqlite3.Row

            try:
                cur = conn.cursor()
                # Check table exists
                tbl = cur.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='signal_forward_observations'"
                ).fetchone()
                if not tbl:
                    return [], []

                cur.execute(
                    """
                    SELECT
                        signal_id,
                        registered_at,
                        market_date,
                        score,
                        score_bucket,
                        direction,
                        symbol,
                        category,
                        entry_price,
                        stop_loss,
                        target_1,
                        target_2,
                        terminal_outcome,
                        is_resolved,
                        realized_r,
                        mfe_r,
                        mae_r,
                        observation_status,
                        cohort_id,
                        observation_source,
                        snapshot_captured_at,
                        resolution_timestamp
                    FROM signal_forward_observations
                    ORDER BY snapshot_captured_at ASC, signal_id ASC
                    """
                )
                rows = [dict(r) for r in cur.fetchall()]
            finally:
                conn.close()

        eligible: list[CalibrationObservation] = []
        excluded: list[dict[str, Any]] = []

        for r in rows:
            is_valid_contract, contract_errors, obs = validate_calibration_observation_contract(r)
            if not is_valid_contract or obs is None:
                excluded.append({"signal_id": r.get("signal_id"), "reasons": contract_errors})
                continue

            is_eligible, eligibility_reasons = filter_calibration_eligibility(obs, cutoff_iso=cutoff_iso)
            if is_eligible:
                eligible.append(obs)
            else:
                excluded.append({"signal_id": obs.signal_id, "reasons": eligibility_reasons})

        return eligible, excluded
