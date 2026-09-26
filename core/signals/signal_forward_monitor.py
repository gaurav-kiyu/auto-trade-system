"""OPB v2.60 — Phase D Operational Monitoring & Reporting Service.

Authority:
Mandatory Agent Governance & Engineering Constitution (OPB-FINAL-PHASE-GOVERNANCE-001)

Program:
Signal Quality / Predictive Validation Roadmap

Role:
Deterministic, read-only operational monitoring and reporting layer for Phase D.

Guarantees:
- 100% Read-Only: Zero mutations on analytical datasets (snapshots, outcomes, forward observations).
- Zero Live Trading: Safety invariants verified; live trading remains unconditionally locked out.
- Canonical Score Buckets: Exactly 4 canonical buckets (70-74, 75-79, 80-84, 85+).
- Out-of-Range Anomaly Quarantine: Scores < 70 treated as data-quality anomalies, not canonical buckets.
- Authority Delegation: Consumes Phase-D and Phase-B semantics without redefinition.
"""

from __future__ import annotations

import datetime
import logging
import sqlite3
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from core.datetime_ist import now_ist
from core.signals.signal_outcome_dataset import parse_timestamp

_log = logging.getLogger("SIGNAL_FORWARD_MONITOR")
_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_DB_PATH = _ROOT / "db" / "signals_history.db"

MONITOR_REPORT_VERSION = "FORWARD_MONITOR_V1"
DEFAULT_FORWARD_CUTOFF_ISO = "2026-09-26T00:00:00+05:30"
FORWARD_CUTOFF_VERSION = "PHASE_D_V1_20260926"

# Canonical Phase-D Score Buckets (strictly 4)
CANONICAL_SCORE_BUCKETS = ["70-74", "75-79", "80-84", "85+"]

# Calibration Readiness Gate Thresholds
GATE_MIN_RESOLVED_PER_ACTIVE_BUCKET = 100  # Gate 1
GATE_MIN_TOTAL_RESOLVED = 300              # Gate 2
GATE_MIN_DISTINCT_MONTHS = 2               # Gate 3
GATE_MIN_RESOLVED_PER_MONTH = 30           # Gate 3
GATE_MAX_DATA_QUALITY_ERROR_RATE = 0.05     # Gate 4
GATE_MAX_STALE_RATE = 0.02                 # Gate 4
STALE_THRESHOLD_HOURS = 48


def _normalize_dt(dt: datetime.datetime | None) -> datetime.datetime | None:
    """Normalize datetime to timezone-naive UTC for offset-safe comparisons."""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone(datetime.timezone.utc).replace(tzinfo=None)
    return dt


# ============================================================================
# 1. Dataclasses
# ============================================================================

@dataclass
class BucketReportItem:
    bucket: str
    total_registered: int
    total_resolved: int
    eligible_resolved: int
    unresolved: int
    stale_unresolved: int
    target_first: int
    sl_first: int
    timeout: int
    ambiguous: int
    no_data: int
    invalidated: int
    data_quality_errors: int
    status: str  # "INACTIVE_BUCKET", "INSUFFICIENT_SAMPLE", "COLLECTING", "SAMPLE_TARGET_MET"
    gate_n_resolved: int
    is_active: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MonthlyReportItem:
    cohort_id: str
    calendar_month: str
    registered: int
    resolved: int
    eligible_resolved: int
    data_quality_errors: int
    stale_unresolved: int
    qualifies_for_monthly_gate: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DataQualityReport:
    total_observations: int
    valid_data_count: int
    ambiguous_count: int
    no_data_count: int
    invalidated_count: int
    out_of_range_score_count: int
    total_error_count: int
    data_quality_error_rate: float
    stale_unresolved_count: int
    stale_unresolved_rate: float
    max_permitted_error_rate: float
    max_permitted_stale_rate: float
    dq_gate_passed: bool
    stale_gate_passed: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class GateStatusItem:
    gate_id: str
    gate_name: str
    passed: bool
    actual: Any
    required: Any
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ForwardSummary:
    report_version: str
    generated_at: str
    forward_cutoff_version: str
    current_market_date: str
    current_cohort_id: str
    total_registered: int
    total_resolved: int
    total_observing: int
    total_timeout: int
    total_ambiguous: int
    total_no_data: int
    total_invalidated: int
    total_unresolved: int
    stale_unresolved_count: int
    stale_unresolved_rate: float
    data_quality_error_count: int
    data_quality_error_rate: float
    overall_readiness: str
    blocking_gates: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ============================================================================
# 2. Operational Monitoring Service (100% Read-Only)
# ============================================================================

class SignalForwardMonitorService:
    """Deterministic read-only operational monitoring and reporting service for Phase D."""

    _instance: SignalForwardMonitorService | None = None
    _lock = threading.Lock()

    def __init__(self, db_path: Path | str | None = None) -> None:
        self._db_path = Path(db_path) if db_path else _DEFAULT_DB_PATH
        self._io_lock = threading.Lock()

    @classmethod
    def get_instance(cls, db_path: Path | str | None = None) -> SignalForwardMonitorService:
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

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path), timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def _load_observations(self, cohort_id: str | None = None) -> list[dict[str, Any]]:
        """Fetch forward observations read-only."""
        if not self._db_path.exists():
            return []

        with self._io_lock:
            conn = self._get_conn()
            try:
                cur = conn.cursor()
                # Verify table exists
                cur.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='signal_forward_observations'"
                )
                if not cur.fetchone():
                    return []

                if cohort_id:
                    cur.execute(
                        "SELECT * FROM signal_forward_observations WHERE cohort_id = ? ORDER BY registered_at ASC, forward_id ASC",
                        (cohort_id,),
                    )
                else:
                    cur.execute(
                        "SELECT * FROM signal_forward_observations ORDER BY registered_at ASC, forward_id ASC"
                    )
                return [dict(r) for r in cur.fetchall()]
            finally:
                conn.close()

    # ------------------------------------------------------------------------
    # Public Reporting APIs
    # ------------------------------------------------------------------------

    def get_forward_summary(self, cohort_id: str | None = None) -> dict[str, Any]:
        """Answer core population questions: total, resolved, observing, DQ, readiness."""
        all_obs = self._load_observations(cohort_id=cohort_id)
        now_dt_iso = now_ist().isoformat()
        current_date = now_ist().date().isoformat()
        resolved_cohort = cohort_id or f"FWD_{current_date[:7]}"

        total_registered = len(all_obs)
        total_resolved = sum(1 for r in all_obs if r.get("is_resolved") == 1)
        total_observing = sum(1 for r in all_obs if r.get("observation_status") == "OBSERVING")
        total_timeout = sum(1 for r in all_obs if r.get("observation_status") == "TIMEOUT")
        total_ambiguous = sum(1 for r in all_obs if r.get("observation_status") == "AMBIGUOUS")
        total_no_data = sum(1 for r in all_obs if r.get("observation_status") == "NO_DATA")
        total_invalidated = sum(1 for r in all_obs if r.get("observation_status") == "INVALIDATED")
        total_unresolved = sum(
            1 for r in all_obs
            if r.get("is_resolved") == 0 and r.get("observation_status") not in ("AMBIGUOUS", "NO_DATA", "INVALIDATED")
        )

        # Stale observations check (> 48 hours in OBSERVING state)
        stale_count = 0
        now_dt = _normalize_dt(parse_timestamp(now_dt_iso))
        for r in all_obs:
            if r.get("observation_status") == "OBSERVING" and now_dt:
                reg_dt = _normalize_dt(parse_timestamp(r.get("registered_at")))
                if reg_dt and (now_dt - reg_dt).total_seconds() > STALE_THRESHOLD_HOURS * 3600:
                    stale_count += 1
        stale_rate = round(stale_count / total_registered, 4) if total_registered > 0 else 0.0

        # Data quality errors (reusing Phase-D / Phase-B status semantics)
        dq_errors = sum(
            1 for r in all_obs
            if r.get("observation_status") in ("AMBIGUOUS", "NO_DATA", "INVALIDATED")
            or r.get("data_quality_status") not in ("VALID_DATA", None, "")
        )
        dq_error_rate = round(dq_errors / total_registered, 4) if total_registered > 0 else 0.0

        readiness_info = self.get_readiness_status(cohort_id=cohort_id)

        summary = ForwardSummary(
            report_version=MONITOR_REPORT_VERSION,
            generated_at=now_dt_iso,
            forward_cutoff_version=FORWARD_CUTOFF_VERSION,
            current_market_date=current_date,
            current_cohort_id=resolved_cohort,
            total_registered=total_registered,
            total_resolved=total_resolved,
            total_observing=total_observing,
            total_timeout=total_timeout,
            total_ambiguous=total_ambiguous,
            total_no_data=total_no_data,
            total_invalidated=total_invalidated,
            total_unresolved=total_unresolved,
            stale_unresolved_count=stale_count,
            stale_unresolved_rate=stale_rate,
            data_quality_error_count=dq_errors,
            data_quality_error_rate=dq_error_rate,
            overall_readiness=readiness_info["status"],
            blocking_gates=readiness_info["blocking_gates"],
        )
        return summary.to_dict()

    def get_bucket_summary(self, cohort_id: str | None = None) -> list[dict[str, Any]]:
        """Return canonical score buckets sorted strictly numerically with separate maturity status."""
        all_obs = self._load_observations(cohort_id=cohort_id)
        now_dt = _normalize_dt(parse_timestamp(now_ist().isoformat()))

        # Canonical buckets: strictly ["70-74", "75-79", "80-84", "85+"]
        bucket_items: list[dict[str, Any]] = []

        for b_name in CANONICAL_SCORE_BUCKETS:
            b_obs = [r for r in all_obs if r.get("score_bucket") == b_name]
            total_reg = len(b_obs)
            resolved = sum(1 for r in b_obs if r.get("is_resolved") == 1)
            target_first = sum(1 for r in b_obs if r.get("terminal_outcome") == "TARGET_FIRST")
            sl_first = sum(1 for r in b_obs if r.get("terminal_outcome") == "SL_FIRST")
            timeout = sum(1 for r in b_obs if r.get("observation_status") == "TIMEOUT" or r.get("terminal_outcome") == "TIMEOUT")
            ambiguous = sum(1 for r in b_obs if r.get("observation_status") == "AMBIGUOUS")
            no_data = sum(1 for r in b_obs if r.get("observation_status") == "NO_DATA")
            invalidated = sum(1 for r in b_obs if r.get("observation_status") == "INVALIDATED")
            unresolved = sum(
                1 for r in b_obs
                if r.get("is_resolved") == 0 and r.get("observation_status") not in ("AMBIGUOUS", "NO_DATA", "INVALIDATED")
            )

            # Stale count
            stale_count = 0
            for r in b_obs:
                if r.get("observation_status") == "OBSERVING" and now_dt:
                    reg_dt = _normalize_dt(parse_timestamp(r.get("registered_at")))
                    if reg_dt and (now_dt - reg_dt).total_seconds() > STALE_THRESHOLD_HOURS * 3600:
                        stale_count += 1

            dq_errors = ambiguous + no_data + invalidated

            # Maturity progress (distinct from overall system READY_FOR_REVIEW)
            is_active = total_reg > 0
            if total_reg == 0:
                b_status = "INACTIVE_BUCKET"
            elif total_reg < 10:
                b_status = "INSUFFICIENT_SAMPLE"
            elif resolved < GATE_MIN_RESOLVED_PER_ACTIVE_BUCKET:
                b_status = "COLLECTING"
            else:
                b_status = "SAMPLE_TARGET_MET"

            item = BucketReportItem(
                bucket=b_name,
                total_registered=total_reg,
                total_resolved=resolved,
                eligible_resolved=resolved,
                unresolved=unresolved,
                stale_unresolved=stale_count,
                target_first=target_first,
                sl_first=sl_first,
                timeout=timeout,
                ambiguous=ambiguous,
                no_data=no_data,
                invalidated=invalidated,
                data_quality_errors=dq_errors,
                status=b_status,
                gate_n_resolved=GATE_MIN_RESOLVED_PER_ACTIVE_BUCKET,
                is_active=is_active,
            )
            bucket_items.append(item.to_dict())

        return bucket_items

    def get_monthly_summary(self) -> list[dict[str, Any]]:
        """Return observed FWD_YYYY-MM cohorts sorted chronologically with strict resolved counts."""
        all_obs = self._load_observations()
        now_dt = _normalize_dt(parse_timestamp(now_ist().isoformat()))

        # Collect distinct cohorts
        cohort_groups: dict[str, list[dict[str, Any]]] = {}
        for r in all_obs:
            c_id = str(r.get("cohort_id") or "")
            if not c_id:
                m_date = str(r.get("market_date") or "")
                c_id = f"FWD_{m_date[:7]}" if len(m_date) >= 7 else "FWD_UNKNOWN"
            cohort_groups.setdefault(c_id, []).append(r)

        # Sort chronologically by cohort_id key
        sorted_cohort_ids = sorted(cohort_groups.keys())
        monthly_items: list[dict[str, Any]] = []

        for c_id in sorted_cohort_ids:
            c_obs = cohort_groups[c_id]
            cal_month = c_id.replace("FWD_", "") if c_id.startswith("FWD_") else c_id
            reg = len(c_obs)
            # Gate 3 STRICT: Count only genuinely resolved observations (is_resolved == 1)
            resolved = sum(1 for r in c_obs if r.get("is_resolved") == 1)
            dq_errors = sum(
                1 for r in c_obs
                if r.get("observation_status") in ("AMBIGUOUS", "NO_DATA", "INVALIDATED")
                or r.get("data_quality_status") not in ("VALID_DATA", None, "")
            )

            stale_count = 0
            for r in c_obs:
                if r.get("observation_status") == "OBSERVING" and now_dt:
                    reg_dt = _normalize_dt(parse_timestamp(r.get("registered_at")))
                    if reg_dt and (now_dt - reg_dt).total_seconds() > STALE_THRESHOLD_HOURS * 3600:
                        stale_count += 1

            qualifies = resolved >= GATE_MIN_RESOLVED_PER_MONTH

            item = MonthlyReportItem(
                cohort_id=c_id,
                calendar_month=cal_month,
                registered=reg,
                resolved=resolved,
                eligible_resolved=resolved,
                data_quality_errors=dq_errors,
                stale_unresolved=stale_count,
                qualifies_for_monthly_gate=qualifies,
            )
            monthly_items.append(item.to_dict())

        return monthly_items

    def get_data_quality_summary(self, cohort_id: str | None = None) -> dict[str, Any]:
        """Return comprehensive data-quality summary reusing Phase-D / Phase-B recorded semantics."""
        all_obs = self._load_observations(cohort_id=cohort_id)
        now_dt = _normalize_dt(parse_timestamp(now_ist().isoformat()))

        total_obs = len(all_obs)
        valid_data = sum(
            1 for r in all_obs
            if r.get("data_quality_status") in ("VALID_DATA", None, "")
            and r.get("observation_status") not in ("AMBIGUOUS", "NO_DATA", "INVALIDATED")
        )
        ambiguous = sum(1 for r in all_obs if r.get("observation_status") == "AMBIGUOUS" or r.get("data_quality_status") == "AMBIGUOUS_DATA")
        no_data = sum(1 for r in all_obs if r.get("observation_status") == "NO_DATA" or r.get("data_quality_status") == "NO_DATA")
        invalidated = sum(1 for r in all_obs if r.get("observation_status") == "INVALIDATED" or r.get("data_quality_status") == "INVALID_DATA")

        # Anomaly check: scores outside canonical score buckets (< 70 or unmapped)
        out_of_range = sum(1 for r in all_obs if r.get("score_bucket") not in CANONICAL_SCORE_BUCKETS)

        total_errors = sum(
            1 for r in all_obs
            if r.get("observation_status") in ("AMBIGUOUS", "NO_DATA", "INVALIDATED")
            or r.get("data_quality_status") not in ("VALID_DATA", None, "")
            or r.get("score_bucket") not in CANONICAL_SCORE_BUCKETS
        )
        dq_error_rate = round(total_errors / total_obs, 4) if total_obs > 0 else 0.0

        stale_count = 0
        for r in all_obs:
            if r.get("observation_status") == "OBSERVING" and now_dt:
                reg_dt = _normalize_dt(parse_timestamp(r.get("registered_at")))
                if reg_dt and (now_dt - reg_dt).total_seconds() > STALE_THRESHOLD_HOURS * 3600:
                    stale_count += 1
        stale_rate = round(stale_count / total_obs, 4) if total_obs > 0 else 0.0

        dq_gate_passed = dq_error_rate <= GATE_MAX_DATA_QUALITY_ERROR_RATE
        stale_gate_passed = stale_rate <= GATE_MAX_STALE_RATE

        rep = DataQualityReport(
            total_observations=total_obs,
            valid_data_count=valid_data,
            ambiguous_count=ambiguous,
            no_data_count=no_data,
            invalidated_count=invalidated,
            out_of_range_score_count=out_of_range,
            total_error_count=total_errors,
            data_quality_error_rate=dq_error_rate,
            stale_unresolved_count=stale_count,
            stale_unresolved_rate=stale_rate,
            max_permitted_error_rate=GATE_MAX_DATA_QUALITY_ERROR_RATE,
            max_permitted_stale_rate=GATE_MAX_STALE_RATE,
            dq_gate_passed=dq_gate_passed,
            stale_gate_passed=stale_gate_passed,
        )
        return rep.to_dict()

    def get_readiness_gate_status(self, cohort_id: str | None = None) -> dict[str, Any]:
        """Return explicit structured pass/fail results for G1, G2, G3, G4, and Overall."""
        all_obs = self._load_observations(cohort_id=cohort_id)
        bucket_items = self.get_bucket_summary(cohort_id=cohort_id)
        monthly_items = self.get_monthly_summary()
        dq_summary = self.get_data_quality_summary(cohort_id=cohort_id)

        # Gate 1: Each ACTIVE canonical score bucket must have n_resolved >= 100
        active_buckets = [b for b in bucket_items if b["is_active"]]
        if not active_buckets:
            g1_passed = False
            g1_actual = {b["bucket"]: b["total_resolved"] for b in bucket_items}
            g1_reason = "No active canonical score buckets have accumulated forward observations."
        else:
            unmet_buckets = [b["bucket"] for b in active_buckets if b["total_resolved"] < GATE_MIN_RESOLVED_PER_ACTIVE_BUCKET]
            g1_passed = len(unmet_buckets) == 0
            g1_actual = {b["bucket"]: b["total_resolved"] for b in active_buckets}
            if g1_passed:
                g1_reason = f"All active buckets meet threshold of >= {GATE_MIN_RESOLVED_PER_ACTIVE_BUCKET} resolved observations."
            else:
                g1_reason = f"Active buckets {unmet_buckets} have fewer than {GATE_MIN_RESOLVED_PER_ACTIVE_BUCKET} resolved observations."

        # Gate 2: Overall N_resolved >= 300
        total_resolved = sum(1 for r in all_obs if r.get("is_resolved") == 1)
        g2_passed = total_resolved >= GATE_MIN_TOTAL_RESOLVED
        g2_reason = (
            f"Total resolved observations ({total_resolved}) >= {GATE_MIN_TOTAL_RESOLVED} requirement."
            if g2_passed else
            f"Total resolved observations ({total_resolved}) < {GATE_MIN_TOTAL_RESOLVED} requirement."
        )

        # Gate 3: >= 2 distinct calendar months with >= 30 resolved each
        qualifying_months = [m for m in monthly_items if m["qualifies_for_monthly_gate"]]
        g3_passed = len(qualifying_months) >= GATE_MIN_DISTINCT_MONTHS
        g3_reason = (
            f"Qualifying calendar months with >= {GATE_MIN_RESOLVED_PER_MONTH} resolved ({len(qualifying_months)}) meets >= {GATE_MIN_DISTINCT_MONTHS} requirement."
            if g3_passed else
            f"Qualifying calendar months with >= {GATE_MIN_RESOLVED_PER_MONTH} resolved ({len(qualifying_months)}) < {GATE_MIN_DISTINCT_MONTHS} requirement."
        )

        # Gate 4: DQ error rate <= 5% and stale rate <= 2%
        g4_passed = dq_summary["dq_gate_passed"] and dq_summary["stale_gate_passed"]
        g4_actual = {
            "dq_error_rate": dq_summary["data_quality_error_rate"],
            "stale_rate": dq_summary["stale_unresolved_rate"],
        }
        g4_required = {
            "max_dq_error_rate": GATE_MAX_DATA_QUALITY_ERROR_RATE,
            "max_stale_rate": GATE_MAX_STALE_RATE,
        }
        if g4_passed:
            g4_reason = "Data quality error rate and stale rate within permissible boundaries."
        else:
            g4_reason = (
                f"Data quality error rate ({dq_summary['data_quality_error_rate']:.1%}) or stale rate "
                f"({dq_summary['stale_unresolved_rate']:.1%}) exceeds thresholds."
            )

        # Determine overall readiness & blocking gates
        blocking_gates: list[str] = []
        if not g1_passed:
            blocking_gates.append("G1")
        if not g2_passed:
            blocking_gates.append("G2")
        if not g3_passed:
            blocking_gates.append("G3")
        if not g4_passed:
            blocking_gates.append("G4")

        total_obs_count = len(all_obs)
        if total_obs_count == 0:
            overall_status = "INSUFFICIENT_SAMPLE"
            explanation = "Zero forward observations registered. Collecting forward cohort data. Live trading remains locked out."
        elif not g4_passed:
            overall_status = "DATA_QUALITY_BLOCKED"
            explanation = f"Blocked by Gate 4: {g4_reason}"
        elif len(blocking_gates) > 0:
            overall_status = "COLLECTING"
            explanation = f"Forward accumulation active. Pending gates: {blocking_gates}."
        else:
            overall_status = "READY_FOR_REVIEW"
            explanation = (
                "All 4 Phase-D calibration readiness gates (G1-G4) pass. "
                "The dataset has reached evidence maturity for a future human-reviewed calibration study (Phase E). "
                "Live trading remains locked out."
            )

        return {
            "G1": GateStatusItem(
                gate_id="G1",
                gate_name="Active Bucket Sample Maturity (n_resolved >= 100)",
                passed=g1_passed,
                actual=g1_actual,
                required=GATE_MIN_RESOLVED_PER_ACTIVE_BUCKET,
                reason=g1_reason,
            ).to_dict(),
            "G2": GateStatusItem(
                gate_id="G2",
                gate_name="Overall System Sample Size (N_resolved >= 300)",
                passed=g2_passed,
                actual=total_resolved,
                required=GATE_MIN_TOTAL_RESOLVED,
                reason=g2_reason,
            ).to_dict(),
            "G3": GateStatusItem(
                gate_id="G3",
                gate_name="Multi-Period Longitudinal Coverage (>= 2 months with >= 30 resolved)",
                passed=g3_passed,
                actual=len(qualifying_months),
                required=GATE_MIN_DISTINCT_MONTHS,
                reason=g3_reason,
            ).to_dict(),
            "G4": GateStatusItem(
                gate_id="G4",
                gate_name="Data Quality & Stale Backlog Hygiene (DQ <= 5%, Stale <= 2%)",
                passed=g4_passed,
                actual=g4_actual,
                required=g4_required,
                reason=g4_reason,
            ).to_dict(),
            "overall": {
                "status": overall_status,
                "blocking_gates": blocking_gates,
                "explanation": explanation,
                "is_ready_for_review": (overall_status == "READY_FOR_REVIEW"),
            },
        }

    def get_readiness_status(self, cohort_id: str | None = None) -> dict[str, Any]:
        """Convenience method returning overall readiness status and explanation."""
        gate_status = self.get_readiness_gate_status(cohort_id=cohort_id)
        return gate_status["overall"]

    def build_daily_report(self, market_date: str | None = None, cohort_id: str | None = None) -> str:
        """Build deterministic human-readable report suitable for terminal/CI output."""
        rep_date = market_date or now_ist().date().isoformat()
        resolved_cohort = cohort_id or f"FWD_{rep_date[:7]}"

        summary = self.get_forward_summary(cohort_id=cohort_id)
        gate_status = self.get_readiness_gate_status(cohort_id=cohort_id)
        bucket_items = self.get_bucket_summary(cohort_id=cohort_id)
        monthly_items = self.get_monthly_summary()
        safety = self.verify_safety_invariants()

        g1 = gate_status["G1"]
        g2 = gate_status["G2"]
        g3 = gate_status["G3"]
        g4 = gate_status["G4"]
        overall = gate_status["overall"]

        lines = [
            "PHASE D FORWARD OBSERVATION REPORT",
            "==================================",
            "",
            f"Report version: {MONITOR_REPORT_VERSION}",
            f"Generated at: {summary['generated_at']}",
            f"Forward cutoff: {DEFAULT_FORWARD_CUTOFF_ISO} ({FORWARD_CUTOFF_VERSION})",
            f"Current cohort: {resolved_cohort}",
            "",
            "OVERALL",
            "-------",
            f"Registered:       {summary['total_registered']}",
            f"Resolved:         {summary['total_resolved']}",
            f"Observing:        {summary['total_observing']}",
            f"Timeout:          {summary['total_timeout']}",
            f"Ambiguous:        {summary['total_ambiguous']}",
            f"No data:          {summary['total_no_data']}",
            f"Invalidated:      {summary['total_invalidated']}",
            f"Stale unresolved: {summary['stale_unresolved_count']} ({summary['stale_unresolved_rate']:.1%})",
            f"DQ error rate:    {summary['data_quality_error_rate']:.1%}",
            "",
            "READINESS",
            "---------",
            f"G1 (Bucket maturity >= 100):  {'PASS' if g1['passed'] else 'FAIL'} -- {g1['reason']}",
            f"G2 (Total resolved >= 300):   {'PASS' if g2['passed'] else 'FAIL'} -- {g2['reason']}",
            f"G3 (Multi-period >= 2 mos):   {'PASS' if g3['passed'] else 'FAIL'} -- {g3['reason']}",
            f"G4 (DQ <= 5%, Stale <= 2%):   {'PASS' if g4['passed'] else 'FAIL'} -- {g4['reason']}",
            "",
            f"Overall:        {overall['status']}",
            f"Blocking gates: {', '.join(overall['blocking_gates']) if overall['blocking_gates'] else 'NONE'}",
            f"Explanation:    {overall['explanation']}",
            "",
            "BUCKETS",
            "-------",
        ]

        for b in bucket_items:
            lines.append(
                f"{b['bucket']:<6}: Registered={b['total_registered']:<3} Resolved={b['total_resolved']:<3} "
                f"Target={b['target_first']:<3} SL={b['sl_first']:<3} Timeout={b['timeout']:<3} "
                f"Status={b['status']}"
            )

        lines.extend([
            "",
            "MONTHLY COVERAGE",
            "----------------",
        ])

        if not monthly_items:
            lines.append("None (zero forward cohorts registered yet)")
        else:
            for m in monthly_items:
                lines.append(
                    f"{m['cohort_id']:<12}: Registered={m['registered']:<3} Resolved={m['resolved']:<3} "
                    f"Qualifies_G3={'YES' if m['qualifies_for_monthly_gate'] else 'NO'}"
                )

        lines.extend([
            "",
            "SAFETY",
            "------",
            f"SIGNAL_ONLY:          {'PASS' if safety['invariants'].get('EXECUTION_MODE') == 'SIGNAL_ONLY' else 'FAIL'}",
            f"LIVE_TRADING_LOCKOUT: {'PASS' if safety['invariants'].get('LIVE_TRADING_LOCKOUT') is True else 'FAIL'}",
            f"full_auto_allowed:    {'PASS' if safety['invariants'].get('full_auto_allowed') is False else 'FAIL'}",
            f"Broker execution:     {'LOCKED OUT' if safety['safe'] else 'VIOLATION'}",
            "",
            "PHASE E STATUS",
            "--------------",
            f"{'READY FOR HUMAN REVIEW' if overall['is_ready_for_review'] else 'DO NOT START'}",
            f"Reason:                  {overall['explanation']}",
            f"Required remaining gates: {', '.join(overall['blocking_gates']) if overall['blocking_gates'] else 'NONE'}",
        ])

        return "\n".join(lines)

    def verify_safety_invariants(self) -> dict[str, Any]:
        """Verify strict live-trading lockout and frozen configuration invariants."""
        try:
            from core.config_bootstrap import get_effective_config
            cfg = get_effective_config()
        except Exception as exc:
            _log.warning("Could not load config_bootstrap: %s", exc)
            cfg = {}

        mode = str(cfg.get("EXECUTION_MODE") or "SIGNAL_ONLY").upper()
        lockout = bool(cfg.get("LIVE_TRADING_LOCKOUT", True))
        auto = bool(cfg.get("full_auto_allowed", False))
        capital = float(cfg.get("BASE_CAPITAL", 3000))
        sl_pct = float(cfg.get("SL_PCT", 0.88))

        violations: list[str] = []
        if mode != "SIGNAL_ONLY":
            violations.append(f"EXECUTION_MODE must be SIGNAL_ONLY, got {mode}")
        if not lockout:
            violations.append("LIVE_TRADING_LOCKOUT must be True")
        if auto:
            violations.append("full_auto_allowed must be False")
        if capital != 3000:
            violations.append(f"BASE_CAPITAL must be 3000, got {capital}")
        if sl_pct != 0.88:
            violations.append(f"SL_PCT must be 0.88, got {sl_pct}")

        is_safe = len(violations) == 0
        return {
            "safe": is_safe,
            "invariants": {
                "EXECUTION_MODE": mode,
                "SIGNAL_ONLY": mode == "SIGNAL_ONLY",
                "LIVE_TRADING_LOCKOUT": lockout,
                "full_auto_allowed": auto,
                "BASE_CAPITAL": capital,
                "SL_PCT": sl_pct,
            },
            "violations": violations,
        }
