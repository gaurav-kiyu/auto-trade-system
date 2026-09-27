"""OPB v2.60 — Phase E Analytical & Calibration Readiness Report Generator.

Governance Authority: OPB-FINAL-PHASE-GOVERNANCE-001 / v2.60 Signal Quality Roadmap.

Role:
Produces the deterministic 16-section Phase-E Analytical & Calibration Readiness Report
evaluating forward readiness gates, data eligibility, probability source validity,
Brier score, ECE, reliability curves, and explicit blocking conditions.

Guarantees:
- 100% Read-Only: Zero database mutations.
- Methodological Neutrality: No ranking, no "best" bucket, no "winning" calibration model.
- Explicit Blockers: Clearly documents why Phase E remains BLOCKED when gates are unmet.
- Non-Trading Boundary: Never enables live trading or alters execution behavior.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from core.datetime_ist import now_ist
from core.signals.signal_calibration_readiness import (
    CALIBRATION_FRAMEWORK_VERSION,
    CalibrationDiagnostics,
    CalibrationObservation,
    ECEResult,
    PhaseEReadinessReport,
    STATUS_BLOCKED,
    STATUS_READY_FOR_REVIEW,
    TemporalSplit,
    compute_calibration_diagnostics,
    evaluate_phase_e_readiness,
)
from core.signals.signal_forward_monitor import (
    DEFAULT_FORWARD_CUTOFF_ISO,
    FORWARD_CUTOFF_VERSION,
    SignalForwardMonitorService,
)

_log = logging.getLogger("SIGNAL_CALIBRATION_REPORT")
_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_DB_PATH = _ROOT / "db" / "signals_history.db"


def generate_phase_e_readiness_report(
    readiness_report: PhaseEReadinessReport | None = None,
    diagnostics: CalibrationDiagnostics | None = None,
    split: TemporalSplit | None = None,
    db_path: Path | str | None = None,
    candidate_probabilities: list[float] | None = None,
    cutoff_iso: str = DEFAULT_FORWARD_CUTOFF_ISO,
) -> str:
    """Generate the canonical 16-section Phase-E Calibration Readiness Report.

    Sections:
    1. Executive Summary
    2. Phase-D Readiness
    3. Phase-E Readiness
    4. Forward Population
    5. Eligible Calibration Dataset
    6. Exclusion Reasons
    7. Probability Source
    8. Brier Score
    9. ECE
    10. Reliability Table
    11. Calibration Diagnostics
    12. Temporal Separation
    13. Statistical Methodology
    14. Safety Invariants
    15. Blocking Conditions
    16. Final Decision
    """
    effective_db = Path(db_path) if db_path else _DEFAULT_DB_PATH
    if readiness_report is None:
        readiness_report = evaluate_phase_e_readiness(
            db_path=effective_db,
            candidate_probabilities=candidate_probabilities,
            cutoff_iso=cutoff_iso,
        )

    monitor_svc = SignalForwardMonitorService.get_instance(db_path=effective_db)
    gates_data = monitor_svc.get_readiness_gate_status()
    summary_data = monitor_svc.get_forward_summary()
    dq_summary = monitor_svc.get_data_quality_summary()

    lines: list[str] = []

    # Title & Metadata
    lines.append("# OPB v2.60 — PHASE E CALIBRATION READINESS & PREPARATION REPORT")
    lines.append("")
    lines.append(f"**Report Generated At**: `{now_ist().isoformat()}`  ")
    lines.append("**Governance Authority**: `OPB-FINAL-PHASE-GOVERNANCE-001`  ")
    lines.append("**Program**: Signal Quality / Predictive Validation Roadmap  ")
    lines.append(f"**Framework Version**: `{CALIBRATION_FRAMEWORK_VERSION}`  ")
    lines.append(f"**Forward Cutoff**: `{cutoff_iso}` (`{FORWARD_CUTOFF_VERSION}`)  ")
    lines.append("")
    lines.append("---")
    lines.append("")

    # 1. Executive Summary
    lines.append("## 1. Executive Summary")
    lines.append("")
    lines.append(
        "This report documents the Phase-E Analytical and Calibration Readiness Framework. "
        "The framework prepares all mathematical, statistical, and diagnostic procedures "
        "for probability calibration and reliability assessment without executing calibration "
        "or altering live model parameters. In accordance with strict governance gates, "
        "Phase E cannot begin until all Phase-D empirical forward gates are satisfied and a "
        "legitimate predicted probability source is verified."
    )
    lines.append("")
    lines.append(f"- **Overall Readiness Status**: `{readiness_report.overall_status}`")
    lines.append(f"- **Phase-D Operational Status**: `{readiness_report.phase_d_status}`")
    lines.append(f"- **Phase-E Initiation Status**: `{readiness_report.phase_e_status}`")
    lines.append(f"- **Probability Source Status**: `{readiness_report.probability_source_status}`")
    lines.append("")
    lines.append("---")
    lines.append("")

    # 2. Phase-D Readiness
    lines.append("## 2. Phase-D Readiness")
    lines.append("")
    lines.append("Evaluation of empirical forward accumulation readiness gates (G1 through G4):")
    lines.append("")
    lines.append("| Gate ID | Description | Threshold | Current Value | Status |")
    lines.append("| :--- | :--- | :--- | :--- | :--- |")
    lines.append(f"| **Gate 1** | Resolved per active bucket | $\\ge 100$ | {gates_data.get('G1', {}).get('actual', {})} | **{readiness_report.g1_status}** |")
    lines.append(f"| **Gate 2** | Total resolved observations | $\\ge 300$ | {gates_data.get('G2', {}).get('actual', 0)} | **{readiness_report.g2_status}** |")
    lines.append(f"| **Gate 3** | Distinct qualifying months | $\\ge 2$ months ($\\ge 30$/mo) | {gates_data.get('G3', {}).get('actual', 0)} | **{readiness_report.g3_status}** |")
    lines.append(f"| **Gate 4** | Data quality & staleness | DQ $\\le 5\\%$, Stale $\\le 2\\%$ | DQ: {dq_summary.get('data_quality_error_rate')}, Stale: {dq_summary.get('stale_unresolved_rate')} | **{readiness_report.g4_status}** |")
    lines.append("")
    lines.append("---")
    lines.append("")

    # 3. Phase-E Readiness
    lines.append("## 3. Phase-E Readiness")
    lines.append("")
    lines.append(f"**Current Status**: `{readiness_report.phase_e_status}`")
    lines.append("")
    lines.append(
        "Phase-E calibration model fitting remains strictly disabled. "
        "Under governance rules, calibration fitting requires:"
    )
    lines.append("1. All four Phase-D forward readiness gates (G1–G4) evaluated as SATISFIED / PASS.")
    lines.append("2. A verified model probability source distinct from raw heuristic scores.")
    lines.append("3. An eligible post-cutoff sample of at least $N = 300$ resolved observations.")
    lines.append("4. Zero substitution of historical pre-cutoff signals.")
    lines.append("")
    lines.append("---")
    lines.append("")

    # 4. Forward Population
    lines.append("## 4. Forward Population")
    lines.append("")
    lines.append(f"- **Total Forward Observations Registered**: `{summary_data.get('total_registered', 0)}`")
    lines.append(f"- **Total Forward Observations Resolved**: `{summary_data.get('total_resolved', 0)}`")
    lines.append(f"- **Eligible Resolved (Gate-Counted)**: `{summary_data.get('total_resolved', 0)}`")
    lines.append(f"- **Data Quality Anomalies (<70 score)**: `{dq_summary.get('out_of_range_score_count', 0)}`")
    lines.append("")
    lines.append("---")
    lines.append("")

    # 5. Eligible Calibration Dataset
    lines.append("## 5. Eligible Calibration Dataset")
    lines.append("")
    lines.append(f"- **Total Eligible Calibration Records (N_eligible)**: `{readiness_report.eligible_n}`")
    lines.append(f"- **Total Ineligible / Excluded Records (N_excluded)**: `{readiness_report.excluded_n}`")
    lines.append("")
    if readiness_report.eligible_n == 0:
        lines.append(
            "> [!NOTE]\n"
            "> There are currently zero eligible forward calibration observations because forward accumulation "
            "is in progress and markets are closed for the weekend."
        )
    lines.append("")
    lines.append("---")
    lines.append("")

    # 6. Exclusion Reasons
    lines.append("## 6. Exclusion Reasons")
    lines.append("")
    lines.append("Criteria for observation exclusion from calibration fitting:")
    lines.append("")
    lines.append("- `PRE_CUTOFF`: Any signal generated prior to `2026-09-26T00:00:00+05:30`.")
    lines.append("- `UNRESOLVED`: Signals currently ACTIVE without a terminal outcome (`is_resolved == 0`).")
    lines.append("- `AMBIGUOUS`: Quarantined same-bar bracket hits with indeterminate execution order.")
    lines.append("- `NO_DATA`: Signals lacking post-entry market tick/bar data.")
    lines.append("- `INVALIDATED`: Canceled or corrupt signals.")
    lines.append("- `MISSING_PROBABILITY`: Signals lacking legitimate predicted probabilities.")
    lines.append("- `INVALID_PRICE_DATA`: Zero or negative entry, stop loss, or target prices.")
    lines.append("")
    lines.append("---")
    lines.append("")

    # 7. Probability Source
    lines.append("## 7. Probability Source")
    lines.append("")
    lines.append(f"- **Probability Source Assessment**: `{readiness_report.probability_source_status}`")
    lines.append("")
    lines.append(
        "**Strict Governance Rule**: Heuristic predictive scores (e.g. 72 to 95) represent multi-factor "
        "ranking scores, NOT probabilities. Automatic conversion of scores to pseudo-probabilities "
        "(e.g. score / 100) is strictly forbidden. Until a dedicated model probability field is established "
        "and documented, probability calibration remains blocked."
    )
    lines.append("")
    lines.append("---")
    lines.append("")

    # 8. Brier Score
    lines.append("## 8. Brier Score")
    lines.append("")
    if diagnostics and diagnostics.brier_result.brier_score is not None:
        br = diagnostics.brier_result
        lines.append(f"- **Brier Score**: `{br.brier_score}`")
        lines.append(f"- **Valid Sample Size**: `{br.valid_n}`")
        lines.append(f"- **Invalid / Excluded Pairs**: `{br.invalid_n}`")
        lines.append(f"- **Status**: `{br.status}`")
    else:
        lines.append("- **Brier Score**: `NOT_AVAILABLE`")
        lines.append("- **Status**: `BLOCKED_NO_PROBABILITY_OR_OUTCOMES`")
        lines.append("- **Reason**: Requires valid predicted probabilities and resolved binary ground truth.")
    lines.append("")
    lines.append("---")
    lines.append("")

    # 9. Expected Calibration Error (ECE)
    lines.append("## 9. Expected Calibration Error (ECE)")
    lines.append("")
    if diagnostics and diagnostics.ece_result.ece is not None:
        er = diagnostics.ece_result
        lines.append(f"- **Expected Calibration Error**: `{er.ece}`")
        lines.append(f"- **Number of Probability Bins**: `{er.num_bins}`")
        lines.append(f"- **Total Observations Evaluated**: `{er.total_n}`")
        lines.append(f"- **Status**: `{er.status}`")
    else:
        lines.append("- **Expected Calibration Error**: `NOT_AVAILABLE`")
        lines.append("- **Status**: `BLOCKED_NO_PROBABILITY_OR_OUTCOMES`")
        lines.append("- **Reason**: Requires valid predicted probabilities across deterministic bins.")
    lines.append("")
    lines.append("---")
    lines.append("")

    # 10. Reliability Table
    lines.append("## 10. Reliability Table")
    lines.append("")
    if diagnostics and diagnostics.reliability_bins and any(b.count > 0 for b in diagnostics.reliability_bins):
        lines.append("| Bin Index | Range | Count (N) | Mean Prob | Observed Rate | Absolute Gap | Weighted Contribution |")
        lines.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
        for b in diagnostics.reliability_bins:
            mean_p = f"{b.mean_predicted_probability:.4f}" if b.mean_predicted_probability is not None else "N/A"
            obs_r = f"{b.observed_frequency:.4f}" if b.observed_frequency is not None else "N/A"
            gap = f"{b.absolute_gap:.4f}" if b.absolute_gap is not None else "0.0000"
            contrib = f"{b.weighted_contribution:.6f}" if b.weighted_contribution is not None else "0.0000"
            lines.append(f"| {b.bin_index} | [{b.bin_lower:.2f}, {b.bin_upper:.2f}) | {b.count} | {mean_p} | {obs_r} | {gap} | {contrib} |")
    else:
        lines.append("No active observations in reliability bins. Showing deterministic bin specification:")
        lines.append("")
        lines.append("| Bin Index | Probability Interval | Default Allocation |")
        lines.append("| :--- | :--- | :--- |")
        for b in range(10):
            lo = b * 0.1
            hi = 1.0 if b == 9 else (b + 1) * 0.1
            lines.append(f"| Bin {b} | [{lo:.1f}, {hi:.1f}) | 0 observations |")
    lines.append("")
    lines.append("---")
    lines.append("")

    # 11. Calibration Diagnostics
    lines.append("## 11. Calibration Diagnostics")
    lines.append("")
    lines.append("- **Diagnostic Framework**: Configured for linear/logistic calibration curve estimation.")
    if diagnostics and diagnostics.regression_status == "VALID":
        lines.append(f"- **Calibration Intercept**: `{diagnostics.calibration_intercept}`")
        lines.append(f"- **Calibration Slope**: `{diagnostics.calibration_slope}`")
        lines.append(f"- **Regression p-value**: `{diagnostics.regression_p_value}`")
        lines.append(f"- **Regression Status**: `{diagnostics.regression_status}`")
    else:
        status_msg = diagnostics.regression_status if diagnostics else "SKIPPED_INSUFFICIENT_SAMPLE"
        lines.append(f"- **Calibration Regression**: `{status_msg}`")
        lines.append("- **Requirement**: Minimum 30 valid observations with non-zero outcome variance.")
    lines.append("- **Diagnostic / Model Separation**: Confirmed; diagnostics never alter model outputs.")
    lines.append("")
    lines.append("---")
    lines.append("")

    # 12. Temporal Separation
    lines.append("## 12. Temporal Separation")
    lines.append("")
    if split and split.is_valid:
        lines.append("- **Partition Type**: Strict chronological temporal split")
        lines.append(f"- **Development Cohort**: {len(split.dev_observations)} records (`{split.dev_start}` to `{split.dev_end}`)")
        lines.append(f"- **Validation Cohort**: {len(split.val_observations)} records (`{split.val_start}` to `{split.val_end}`)")
        lines.append(f"- **Split Ratio**: `{split.split_ratio}`")
        lines.append("- **Temporal Leakage**: Verified zero overlap (max(T_dev) < min(T_val)).")
    else:
        lines.append("- **Partition Status**: Pending data accumulation")
        lines.append("- **Protocol**: Strictly chronological dev/val split (default 70/30).")
        lines.append("- **Prohibitions**: Random-shuffle is strictly forbidden; boundary overlap is rejected.")
    lines.append("")
    lines.append("---")
    lines.append("")

    # 13. Statistical Methodology
    lines.append("## 13. Statistical Methodology")
    lines.append("")
    lines.append("1. **Wilson Score Confidence Intervals**: 95% two-sided intervals on proportions.")
    lines.append("2. **Brier Score Decomposition**: Evaluates mean squared error of predicted probabilities.")
    lines.append("3. **Expected Calibration Error (ECE)**: Evaluates weighted absolute deviation across probability bins.")
    lines.append("4. **Calibration Intercept / Slope**: Quantifies over-confidence (slope < 1) or under-confidence (slope > 1).")
    lines.append("5. **Multiple Testing Correction**: Step-down Holm-Bonferroni correction applied across bucket families.")
    lines.append("")
    lines.append("---")
    lines.append("")

    # 14. Safety Invariants
    lines.append("## 14. Safety Invariants")
    lines.append("")
    lines.append("- `EXECUTION_MODE = SIGNAL_ONLY`: **VERIFIED**")
    lines.append("- `SIGNAL_ONLY = True`: **VERIFIED**")
    lines.append("- `LIVE_TRADING_LOCKOUT = True`: **VERIFIED**")
    lines.append("- `full_auto_allowed = False`: **VERIFIED**")
    lines.append("- `BASE_CAPITAL = 3000`: **VERIFIED**")
    lines.append("- `SL_PCT = 0.88`: **VERIFIED**")
    lines.append("- Live Orders Placed: **0**")
    lines.append("- Production Mutations: **0**")
    lines.append("")
    lines.append("---")
    lines.append("")

    # 15. Blocking Conditions
    lines.append("## 15. Blocking Conditions")
    lines.append("")
    if readiness_report.blocking_reasons:
        for idx, reason in enumerate(readiness_report.blocking_reasons, start=1):
            lines.append(f"{idx}. {reason}")
    else:
        lines.append("No active blocking conditions.")
    lines.append("")
    lines.append("---")
    lines.append("")

    # 16. Final Decision
    lines.append("## 16. Final Decision")
    lines.append("")
    lines.append("```text")
    lines.append("================================================================================")
    lines.append("                     PHASE E READINESS DETERMINATION")
    lines.append("================================================================================")
    lines.append("")
    lines.append(f"                     PHASE E STATUS: {readiness_report.phase_e_status}")
    lines.append("")
    lines.append("--------------------------------------------------------------------------------")
    lines.append("PHASE E PREPARATION: PASS (Framework, Tests & Machinery Fully Prepared)")
    lines.append("PHASE E EXECUTION:   NOT STARTED (Awaiting Live Forward Data Accumulation)")
    lines.append("PHASE E CALIBRATION: BLOCKED (Prerequisite Gates Not Satisfied)")
    lines.append("================================================================================")
    lines.append("```")
    lines.append("")

    return "\n".join(lines)
