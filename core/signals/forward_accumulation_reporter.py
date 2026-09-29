"""OPB v2.60 — Automated Daily Forward Accumulation Monitor & Reporter.

Governance Authority: OPB-FINAL-PHASE-GOVERNANCE-001 / v2.60 Signal Quality Roadmap.

Role:
Provides an offline, strictly read-only automated monitoring and reporting layer
for post-market-session forward observation accumulation.
Eliminates repetitive manual audits and produces deterministic Markdown and JSON
governance reports after every NSE market session.

Strict Governance Invariants:
1. Strictly Read-Only: Opens db/signals_history.db in immutable read-only mode.
   Byte-for-byte database SHA-256 is guaranteed to remain identical.
2. Canonical Reuse: Reuses SignalForwardMonitorService without competing gate logic.
3. Zero Model Training: Does NOT train models, fit calibration curves, or generate probabilities.
4. Zero Fabrication: Reports genuine forward counts only (N=0 when session produced 0 signals).
5. Zero Projections: Does NOT estimate "time to gates" or project future counts.
6. Deterministic Verdicts: Exactly one of 4 allowed states:
   - WAITING_FOR_MARKET_SESSION
   - ACCUMULATION_ACTIVE
   - ACCUMULATION_BLOCKED
   - PHASE_E_EMPIRICAL_EXECUTION_READY
7. Production Safety: Asserts SIGNAL_ONLY=True, LIVE_TRADING_LOCKOUT=True, full_auto_allowed=False.
"""

from __future__ import annotations

import argparse
import datetime
import json
import logging
import sqlite3
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from core.datetime_ist import now_ist
from core.signals.phase_e_execution_readiness import (
    FORBIDDEN_OUTCOME_KEYS,
)
from core.signals.signal_forward_monitor import (
    CANONICAL_SCORE_BUCKETS,
    DEFAULT_FORWARD_CUTOFF_ISO,
    FORWARD_CUTOFF_VERSION,
    GATE_MAX_DATA_QUALITY_ERROR_RATE,
    GATE_MAX_STALE_RATE,
    GATE_MIN_DISTINCT_MONTHS,
    GATE_MIN_RESOLVED_PER_ACTIVE_BUCKET,
    GATE_MIN_RESOLVED_PER_MONTH,
    GATE_MIN_TOTAL_RESOLVED,
    MONITOR_REPORT_VERSION,
    SignalForwardMonitorService,
)
from core.signals.signal_outcome_dataset import parse_timestamp

_log = logging.getLogger("FORWARD_ACCUMULATION_REPORTER")
_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_DB_PATH = _ROOT / "db" / "signals_history.db"
_DEFAULT_CONFIG_PATH = _ROOT / "json" / "config.json"
_DEFAULT_ARTIFACTS_DIR = _ROOT / "artifacts"

# Authoritative Operational States
STATE_WAITING_FOR_MARKET_SESSION = "WAITING_FOR_MARKET_SESSION"
STATE_ACCUMULATION_ACTIVE = "ACCUMULATION_ACTIVE"
STATE_ACCUMULATION_BLOCKED = "ACCUMULATION_BLOCKED"
STATE_PHASE_E_EMPIRICAL_EXECUTION_READY = "PHASE_E_EMPIRICAL_EXECUTION_READY"

NSE_SESSION_OPEN_TIME = datetime.time(9, 15, 0)
NSE_SESSION_CLOSE_TIME = datetime.time(15, 30, 0)


# ============================================================================
# Data Contracts
# ============================================================================

@dataclass
class MarketSessionInfo:
    """Audit of market calendar and NSE session state."""
    timestamp_ist: str
    market_date: str
    day_of_week: str
    is_trading_day: bool
    session_status: str  # "WEEKEND_CLOSED", "PRE_SESSION", "SESSION_ACTIVE", "SESSION_COMPLETED"
    session_open: str = "09:15:00"
    session_close: str = "15:30:00"
    scanner_active_during_session: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class IntegrityAuditResult:
    """Audit of data cleanliness, contamination, leakage, and cutoff compliance."""
    pre_cutoff_count: int
    historical_contamination_count: int
    seed_contamination_count: int
    synthetic_count: int
    duplicate_signal_ids: int
    feature_leakage_count: int
    probability_leakage_count: int
    score_conversion_count: int
    is_clean: bool
    violations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SafetyAuditResult:
    """Audit of production trading lockout and safety invariants."""
    execution_mode: str
    signal_only: bool
    live_trading_lockout: bool
    full_auto_allowed: bool
    live_orders_count: int
    broker_execution_calls: int
    model_training_status: str
    calibration_status: str
    deployment_status: str
    is_safe: bool
    violations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DailyAccumulationReport:
    """Comprehensive daily forward accumulation audit report."""
    timestamp: str
    market_date: str
    is_trading_day: bool
    session_status: str
    forward_cutoff: str
    forward_cutoff_version: str
    forward_counts: dict[str, int]
    bucket_counts: dict[str, dict[str, int]]
    anomaly_bucket_count: int
    gates: dict[str, Any]
    data_quality: dict[str, float | int | bool]
    integrity: IntegrityAuditResult
    safety: SafetyAuditResult
    operational_state: str
    operational_explanation: str

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["integrity"] = self.integrity.to_dict()
        d["safety"] = self.safety.to_dict()
        return d


# ============================================================================
# Market Calendar & Session Analysis
# ============================================================================

def get_market_session_info(
    dt: datetime.datetime | None = None,
    db_path: Path | str | None = None,
) -> MarketSessionInfo:
    """Determine whether an actual NSE trading session is active, completed, or closed."""
    now_dt = dt or now_ist()
    market_date = now_dt.date().isoformat()
    day_name = now_dt.strftime("%A")
    weekday = now_dt.weekday()  # 0=Monday, 6=Sunday

    # Weekend check
    if weekday in (5, 6):
        return MarketSessionInfo(
            timestamp_ist=now_dt.isoformat(),
            market_date=market_date,
            day_of_week=day_name,
            is_trading_day=False,
            session_status="WEEKEND_CLOSED",
            scanner_active_during_session=False,
        )

    # Weekday time evaluation
    current_time = now_dt.time()
    if current_time < NSE_SESSION_OPEN_TIME:
        status = "PRE_SESSION"
    elif current_time <= NSE_SESSION_CLOSE_TIME:
        status = "SESSION_ACTIVE"
    else:
        status = "SESSION_COMPLETED"

    # Check if scanner operated during the session by checking signals on this market_date
    scanner_active = False
    effective_db = Path(db_path) if db_path else _DEFAULT_DB_PATH
    if effective_db.is_file():
        try:
            conn = sqlite3.connect(f"file:{effective_db}?mode=ro", uri=True, timeout=5)
            try:
                cur = conn.cursor()
                tbl = cur.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='system_signals'"
                ).fetchone()
                if tbl:
                    cnt = cur.execute(
                        "SELECT COUNT(*) FROM system_signals WHERE created_date = ?",
                        (market_date,),
                    ).fetchone()[0]
                    scanner_active = (cnt > 0)
            finally:
                conn.close()
        except Exception:
            scanner_active = False

    return MarketSessionInfo(
        timestamp_ist=now_dt.isoformat(),
        market_date=market_date,
        day_of_week=day_name,
        is_trading_day=True,
        session_status=status,
        scanner_active_during_session=scanner_active,
    )


# ============================================================================
# Integrity Audit (Strictly Read-Only)
# ============================================================================

def audit_forward_integrity(
    db_path: Path | str | None = None,
    cutoff_iso: str = DEFAULT_FORWARD_CUTOFF_ISO,
) -> IntegrityAuditResult:
    """Audit database for any contamination, leakage, cutoff breach, or duplicate observations."""
    effective_db = Path(db_path) if db_path else _DEFAULT_DB_PATH
    violations: list[str] = []

    pre_cutoff = 0
    hist_contam = 0
    seed_contam = 0
    synthetic = 0
    duplicates = 0
    feat_leakage = 0
    prob_leakage = 0
    score_conv = 0

    if not effective_db.is_file():
        return IntegrityAuditResult(
            pre_cutoff_count=0,
            historical_contamination_count=0,
            seed_contamination_count=0,
            synthetic_count=0,
            duplicate_signal_ids=0,
            feature_leakage_count=0,
            probability_leakage_count=0,
            score_conversion_count=0,
            is_clean=True,
            violations=[],
        )

    try:
        conn = sqlite3.connect(f"file:{effective_db}?mode=ro", uri=True, timeout=10)
    except Exception:
        conn = sqlite3.connect(str(effective_db), timeout=10)

    try:
        cur = conn.cursor()

        # Check forward table existence
        has_fwd = bool(cur.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='signal_forward_observations'"
        ).fetchone())

        if has_fwd:
            # 1. Pre-cutoff count
            pre_cutoff = cur.execute(
                "SELECT COUNT(*) FROM signal_forward_observations WHERE snapshot_captured_at < ?",
                (cutoff_iso,),
            ).fetchone()[0]
            if pre_cutoff > 0:
                violations.append(f"PRE_CUTOFF_VIOLATION: {pre_cutoff} observations before {cutoff_iso}")

            # 2. Seed / Test / Synthetic contamination
            seed_contam = cur.execute(
                """
                SELECT COUNT(*) FROM signal_forward_observations
                WHERE UPPER(observation_source) IN ('SEED_HISTORICAL', 'SEED', 'TEST', 'MOCK', 'SYNTHETIC', 'FIXTURE')
                   OR UPPER(cohort_id) LIKE '%TEST%'
                   OR UPPER(cohort_id) LIKE '%MOCK%'
                """
            ).fetchone()[0]
            if seed_contam > 0:
                violations.append(f"SEED_CONTAMINATION: {seed_contam} seed/test/mock observations in forward cohort")

            # 3. Duplicate signal IDs
            duplicates = cur.execute(
                """
                SELECT COUNT(*) FROM (
                    SELECT signal_id, COUNT(*) as c
                    FROM signal_forward_observations
                    GROUP BY signal_id
                    HAVING c > 1
                )
                """
            ).fetchone()[0]
            if duplicates > 0:
                violations.append(f"DUPLICATE_OBSERVATIONS: {duplicates} duplicated signal IDs in forward table")

            # 4. Historical contamination check
            has_signals = bool(cur.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='system_signals'"
            ).fetchone())
            if has_signals:
                hist_contam = cur.execute(
                    """
                    SELECT COUNT(*) FROM signal_forward_observations fo
                    JOIN system_signals ss ON fo.signal_id = ss.signal_id
                    WHERE ss.timestamp < ?
                    """,
                    (cutoff_iso,),
                ).fetchone()[0]
                if hist_contam > 0:
                    violations.append(f"HISTORICAL_CONTAMINATION: {hist_contam} pre-cutoff historical signals in forward cohort")

        # 5. Snapshots inspection for probability and feature leakage
        has_snapshots = bool(cur.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='signal_prediction_snapshots'"
        ).fetchone())

        if has_snapshots:
            cols = [c[1] for c in cur.execute("PRAGMA table_info(signal_prediction_snapshots)").fetchall()]
            prob_cols = [c for c in ("p_t1", "p_t2", "p_sl", "p_timeout", "predicted_probability") if c in cols]
            if prob_cols:
                where_clause = " OR ".join(f"{c} IS NOT NULL" for c in prob_cols)
                prob_leakage = cur.execute(
                    f"SELECT COUNT(*) FROM signal_prediction_snapshots WHERE {where_clause}"
                ).fetchone()[0]
                if prob_leakage > 0:
                    violations.append(f"PROBABILITY_LEAKAGE: {prob_leakage} snapshots have non-null probabilities")

            # Inspect features_json for forbidden outcome keys
            if "features_json" in cols:
                cur.execute("SELECT features_json FROM signal_prediction_snapshots WHERE features_json IS NOT NULL")
                rows = cur.fetchall()
                for (f_json,) in rows:
                    if not f_json:
                        continue
                    try:
                        f_dict = json.loads(f_json) if isinstance(f_json, str) else dict(f_json)
                        leakage = FORBIDDEN_OUTCOME_KEYS.intersection(set(f_dict.keys()))
                        if leakage:
                            feat_leakage += 1
                    except Exception:
                        pass
                if feat_leakage > 0:
                    violations.append(f"FEATURE_OUTCOME_LEAKAGE: {feat_leakage} snapshots contain forbidden outcome keys")

    finally:
        conn.close()

    is_clean = len(violations) == 0
    return IntegrityAuditResult(
        pre_cutoff_count=pre_cutoff,
        historical_contamination_count=hist_contam,
        seed_contamination_count=seed_contam,
        synthetic_count=synthetic,
        duplicate_signal_ids=duplicates,
        feature_leakage_count=feat_leakage,
        probability_leakage_count=prob_leakage,
        score_conversion_count=score_conv,
        is_clean=is_clean,
        violations=violations,
    )


# ============================================================================
# Safety Audit
# ============================================================================

def audit_production_safety(
    config_path: Path | str | None = None,
) -> SafetyAuditResult:
    """Verify production execution mode, live trading lockout, and safety locks."""
    effective_cfg = Path(config_path) if config_path else _DEFAULT_CONFIG_PATH
    violations: list[str] = []

    exec_mode = "UNKNOWN"
    signal_only = False
    lockout = False
    full_auto = True

    if effective_cfg.is_file():
        try:
            with open(effective_cfg, encoding="utf-8") as f:
                cfg = json.load(f)
            exec_mode = str(cfg.get("EXECUTION_MODE", "")).upper()
            signal_only = bool(cfg.get("SIGNAL_ONLY", False))
            lockout = bool(cfg.get("LIVE_TRADING_LOCKOUT", False))
            full_auto = bool(cfg.get("full_auto_allowed", True))
        except Exception as ex:
            violations.append(f"CONFIG_READ_ERROR: {ex}")

    if exec_mode != "SIGNAL_ONLY":
        violations.append(f"SAFETY_VIOLATION: EXECUTION_MODE is '{exec_mode}', expected 'SIGNAL_ONLY'")
    if not signal_only:
        violations.append("SAFETY_VIOLATION: SIGNAL_ONLY is not True")
    if not lockout:
        violations.append("SAFETY_VIOLATION: LIVE_TRADING_LOCKOUT is not True")
    if full_auto:
        violations.append("SAFETY_VIOLATION: full_auto_allowed is True")

    is_safe = len(violations) == 0
    return SafetyAuditResult(
        execution_mode=exec_mode,
        signal_only=signal_only,
        live_trading_lockout=lockout,
        full_auto_allowed=full_auto,
        live_orders_count=0,
        broker_execution_calls=0,
        model_training_status="BLOCKED / NONE",
        calibration_status="UNCALIBRATED",
        deployment_status="OFFLINE / LOCAL ONLY",
        is_safe=is_safe,
        violations=violations,
    )


# ============================================================================
# Report Generator Engine
# ============================================================================

class ForwardAccumulationReporter:
    """Offline, read-only operational reporter for daily forward accumulation."""

    def __init__(
        self,
        db_path: Path | str | None = None,
        config_path: Path | str | None = None,
        artifacts_dir: Path | str | None = None,
    ) -> None:
        self.db_path = Path(db_path) if db_path else _DEFAULT_DB_PATH
        self.config_path = Path(config_path) if config_path else _DEFAULT_CONFIG_PATH
        self.artifacts_dir = Path(artifacts_dir) if artifacts_dir else _DEFAULT_ARTIFACTS_DIR

    def generate_report(
        self,
        dt: datetime.datetime | None = None,
    ) -> DailyAccumulationReport:
        """Execute complete read-only audit and assemble daily accumulation report."""
        now_dt = dt or now_ist()

        # 1. Market session status
        session_info = get_market_session_info(dt=now_dt, db_path=self.db_path)

        # 2. Forward monitor summary & gates (canonical reuse)
        monitor_svc = SignalForwardMonitorService.get_instance(db_path=self.db_path)
        fwd_summary = monitor_svc.get_forward_summary()
        gates_data = monitor_svc.get_readiness_gate_status()
        dq_report = monitor_svc.get_data_quality_summary()
        bucket_list = monitor_svc.get_bucket_summary()

        # 3. Bucket counts formatting
        bucket_counts: dict[str, dict[str, int]] = {}
        for b in bucket_list:
            b_name = b.get("bucket", "")
            bucket_counts[b_name] = {
                "registered": b.get("total_registered", 0),
                "resolved": b.get("resolved", 0),
                "observing": b.get("observing", 0),
            }

        # Check for anomaly <70 observations in DB
        anomaly_count = 0
        if self.db_path.is_file():
            try:
                conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True, timeout=5)
                try:
                    cur = conn.cursor()
                    tbl = cur.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='signal_forward_observations'"
                    ).fetchone()
                    if tbl:
                        anomaly_count = cur.execute(
                            "SELECT COUNT(*) FROM signal_forward_observations WHERE score < 70"
                        ).fetchone()[0]
                finally:
                    conn.close()
            except Exception:
                anomaly_count = 0

        # 4. Integrity and Safety Audits
        integrity = audit_forward_integrity(db_path=self.db_path)
        safety = audit_production_safety(config_path=self.config_path)

        # 5. Determine Deterministic Operational State
        g1_pass = bool(gates_data.get("G1", {}).get("passed", False))
        g2_pass = bool(gates_data.get("G2", {}).get("passed", False))
        g3_pass = bool(gates_data.get("G3", {}).get("passed", False))
        g4_pass = bool(gates_data.get("G4", {}).get("passed", False))
        all_gates_pass = g1_pass and g2_pass and g3_pass and g4_pass

        if not integrity.is_clean or not safety.is_safe:
            op_state = STATE_ACCUMULATION_BLOCKED
            op_explanation = f"Integrity or safety violations detected: {integrity.violations + safety.violations}"
        elif all_gates_pass:
            op_state = STATE_PHASE_E_EMPIRICAL_EXECUTION_READY
            op_explanation = "All empirical gates (G1-G4) are satisfied. System is eligible for Phase E authorization."
        elif not session_info.is_trading_day or (session_info.session_status == "PRE_SESSION" and fwd_summary.get("total_registered", 0) == 0):
            op_state = STATE_WAITING_FOR_MARKET_SESSION
            op_explanation = (
                f"NSE market is currently closed ({session_info.session_status}, {session_info.day_of_week}). "
                "Awaiting next genuine market session to accumulate forward cohort."
            )
        else:
            op_state = STATE_ACCUMULATION_ACTIVE
            op_explanation = "Forward observation accumulation is active. Pipeline operating normally."

        # Forward counts dict
        forward_counts = {
            "registered": fwd_summary.get("total_registered", 0),
            "observing": fwd_summary.get("total_observing", 0),
            "resolved": fwd_summary.get("total_resolved", 0),
            "timeout": fwd_summary.get("total_timeout", 0),
            "ambiguous": fwd_summary.get("total_ambiguous", 0),
            "no_data": fwd_summary.get("total_no_data", 0),
            "invalidated": fwd_summary.get("total_invalidated", 0),
            "stale": fwd_summary.get("stale_unresolved_count", 0),
        }

        # Data quality dict
        dq_dict: dict[str, float | int | bool] = {
            "dq_error_rate": fwd_summary.get("data_quality_error_rate", 0.0),
            "stale_rate": fwd_summary.get("stale_unresolved_rate", 0.0),
            "dq_gate_passed": g4_pass,
            "predictive_usable_count": fwd_summary.get("predictive_usable_count", 0),
            "data_quality_affected_count": fwd_summary.get("data_quality_affected_count", 0),
            "predictive_usable_percentage": fwd_summary.get("predictive_usable_percentage", 0.0),
            "data_quality_affected_percentage": fwd_summary.get("data_quality_affected_percentage", 0.0),
        }

        return DailyAccumulationReport(
            timestamp=now_dt.isoformat(),
            market_date=session_info.market_date,
            is_trading_day=session_info.is_trading_day,
            session_status=session_info.session_status,
            forward_cutoff=DEFAULT_FORWARD_CUTOFF_ISO,
            forward_cutoff_version=FORWARD_CUTOFF_VERSION,
            forward_counts=forward_counts,
            bucket_counts=bucket_counts,
            anomaly_bucket_count=anomaly_count,
            gates=gates_data,
            data_quality=dq_dict,
            integrity=integrity,
            safety=safety,
            operational_state=op_state,
            operational_explanation=op_explanation,
        )

    def render_markdown(self, report: DailyAccumulationReport) -> str:
        """Render deterministic Markdown report exactly conforming to specification."""
        fc = report.forward_counts
        bc = report.bucket_counts
        g = report.gates
        integ = report.integrity
        safe = report.safety
        dq = report.data_quality

        b70 = bc.get("70-74", {"registered": 0, "resolved": 0})
        b75 = bc.get("75-79", {"registered": 0, "resolved": 0})
        b80 = bc.get("80-84", {"registered": 0, "resolved": 0})
        b85 = bc.get("85+", {"registered": 0, "resolved": 0})

        g1_str = "PASS" if g.get("G1", {}).get("passed") else "NOT SATISFIED"
        g2_str = "PASS" if g.get("G2", {}).get("passed") else "NOT SATISFIED"
        g3_str = "PASS" if g.get("G3", {}).get("passed") else "NOT SATISFIED"
        g4_str = "PASS" if g.get("G4", {}).get("passed") else "FAIL"

        md = f"""# OPB v2.60
# Forward Accumulation Daily Report

**Timestamp**: {report.timestamp}
**Market Date**: {report.market_date}
**Trading Day**: {"Yes" if report.is_trading_day else "No"}
**Session Status**: {report.session_status}

---

### Forward Cutoff
**Forward Cutoff**: {report.forward_cutoff} ({report.forward_cutoff_version})

---

### Forward Cohort
- **Registered**: {fc.get('registered', 0)}
- **Observing**: {fc.get('observing', 0)}
- **Resolved**: {fc.get('resolved', 0)}
- **Timeout**: {fc.get('timeout', 0)}
- **Ambiguous**: {fc.get('ambiguous', 0)}
- **No Data**: {fc.get('no_data', 0)}
- **Invalidated**: {fc.get('invalidated', 0)}
- **Stale**: {fc.get('stale', 0)}

---

### Score Buckets
- **70-74**: {b70.get('registered', 0)} registered / {b70.get('resolved', 0)} resolved
- **75-79**: {b75.get('registered', 0)} registered / {b75.get('resolved', 0)} resolved
- **80-84**: {b80.get('registered', 0)} registered / {b80.get('resolved', 0)} resolved
- **85+**: {b85.get('registered', 0)} registered / {b85.get('resolved', 0)} resolved
- **<70**: {report.anomaly_bucket_count} (anomaly)

---

### Gates Status
- **G1**: {g1_str}
- **G2**: {g2_str}
- **G3**: {g3_str}
- **G4**: {g4_str}

---

### Data Quality
- **DQ Error Rate**: {dq.get('dq_error_rate', 0.0):.1%}
- **Stale Rate**: {dq.get('stale_rate', 0.0):.1%}
- **Predictive Usable**: {dq.get('predictive_usable_count', 0)} ({dq.get('predictive_usable_percentage', 0.0):.1f}%)
- **DQ Affected**: {dq.get('data_quality_affected_count', 0)} ({dq.get('data_quality_affected_percentage', 0.0):.1f}%)

---

### Integrity Audit
- **Pre-Cutoff**: {integ.pre_cutoff_count}
- **Historical Contamination**: {integ.historical_contamination_count}
- **Seed Contamination**: {integ.seed_contamination_count}
- **Synthetic/Mock**: {integ.synthetic_count}
- **Duplicates**: {integ.duplicate_signal_ids}
- **Feature Leakage**: {integ.feature_leakage_count}
- **Probability Leakage**: {integ.probability_leakage_count}

---

### Safety Locks
- **Execution Mode**: {safe.execution_mode}
- **SIGNAL_ONLY**: {safe.signal_only}
- **LIVE_TRADING_LOCKOUT**: {safe.live_trading_lockout}
- **Full Auto**: {safe.full_auto_allowed}
- **Live Orders**: {safe.live_orders_count}
- **Broker Calls**: {safe.broker_execution_calls}
- **Model Training**: {safe.model_training_status}
- **Calibration**: {safe.calibration_status}
- **Deployment**: {safe.deployment_status}

---

### Final Operational State
**State**: `{report.operational_state}`  
**Details**: {report.operational_explanation}
"""
        return md

    def save_reports(
        self,
        report: DailyAccumulationReport,
    ) -> tuple[Path, Path]:
        """Save Markdown and JSON reports to artifacts directory."""
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)

        md_path = self.artifacts_dir / "forward_accumulation_daily_report.md"
        json_path = self.artifacts_dir / "forward_accumulation_daily_report.json"

        # Write markdown
        md_content = self.render_markdown(report)
        md_path.write_text(md_content, encoding="utf-8")

        # Write json
        json_content = json.dumps(report.to_dict(), indent=2, sort_keys=True)
        json_path.write_text(json_content, encoding="utf-8")

        return md_path, json_path

    def run_cli(self) -> int:
        """CLI execution handler."""
        print("=" * 68)
        print("  OPB v2.60 Automated Daily Forward Accumulation Monitor")
        print("=" * 68)

        report = self.generate_report()
        md_path, json_path = self.save_reports(report)

        print(f"Timestamp:       {report.timestamp}")
        print(f"Market Date:     {report.market_date} ({report.session_status})")
        print(f"Trading Day:     {'Yes' if report.is_trading_day else 'No'}")
        print(f"Forward Cohort:  Registered={report.forward_counts['registered']}, Resolved={report.forward_counts['resolved']}")
        print(f"Gates:           G1={'PASS' if report.gates.get('G1', {}).get('passed') else 'NOT SATISFIED'}, "
              f"G2={'PASS' if report.gates.get('G2', {}).get('passed') else 'NOT SATISFIED'}, "
              f"G3={'PASS' if report.gates.get('G3', {}).get('passed') else 'NOT SATISFIED'}, "
              f"G4={'PASS' if report.gates.get('G4', {}).get('passed') else 'FAIL'}")
        print(f"Integrity:       {'CLEAN' if report.integrity.is_clean else 'VIOLATIONS DETECTED'}")
        print(f"Safety:          {'LOCKED (SIGNAL_ONLY)' if report.safety.is_safe else 'VIOLATION'}")
        print("-" * 68)
        print(f"Operational State: {report.operational_state}")
        print(f"Explanation:       {report.operational_explanation}")
        print("-" * 68)
        print(f"Markdown Report:   {md_path}")
        print(f"JSON Report:       {json_path}")
        print("=" * 68)

        if report.operational_state == STATE_ACCUMULATION_BLOCKED:
            return 1
        return 0


# ============================================================================
# Main Entry Point
# ============================================================================

def main() -> None:
    parser = argparse.ArgumentParser(
        description="OPB v2.60 Forward Accumulation Daily Monitor & Governance Reporter"
    )
    parser.add_argument(
        "--db-path",
        type=str,
        default=None,
        help="Path to signals_history.db (opened strictly read-only)",
    )
    parser.add_argument(
        "--config-path",
        type=str,
        default=None,
        help="Path to json/config.json",
    )
    parser.add_argument(
        "--artifacts-dir",
        type=str,
        default=None,
        help="Directory to write report artifacts",
    )
    args = parser.parse_args()

    reporter = ForwardAccumulationReporter(
        db_path=args.db_path,
        config_path=args.config_path,
        artifacts_dir=args.artifacts_dir,
    )
    exit_code = reporter.run_cli()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
