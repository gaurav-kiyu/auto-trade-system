"""Signal Forward Observation & Calibration Readiness Service (Phase D).

Governance Authority: OPB-FINAL-PHASE-GOVERNANCE-001 / v2.60 Phase D Roadmap.

Accumulates genuinely out-of-sample forward signal observations and synchronizes
with Phase-B outcome measurements to assess empirical calibration readiness.

Strict Governance Invariants:
1. Pure Evidence Accumulation: Phase D observes and accumulates data; it does NOT
   tune models, adjust thresholds, alter score weights, or calibrate probabilities.
2. Strengthened Look-Ahead Boundary: Verified against immutable Phase-A snapshot
   creation timestamp (snapshot_captured_at >= CUTOFF) and registered_at >= snapshot_captured_at.
3. Immutable Prediction Snapshots: signal_prediction_snapshots remains strictly READ-ONLY.
4. Strict Delegation to Phase B: All outcome measurements (TARGET_FIRST, SL_FIRST,
   TIMEOUT, AMBIGUOUS, MFE_R, MAE_R, Realized_R) are computed exclusively by Phase B.
5. Canonical Score Buckets: Preserves '<70', '70-74', '75-79', '80-84', '85+'.
6. Readiness Gate Semantics: Inactive buckets (n=0) do not block readiness. Active
   buckets require n_resolved >= 100, multi-period coverage (>= 2 months), and
   total N_resolved >= 300.
7. Non-Trading Boundary: READY_FOR_REVIEW indicates only readiness for a future
   human-reviewed calibration study (Phase E), NOT readiness for trading execution.
8. Live Trading Lockout: EXECUTION_MODE=SIGNAL_ONLY, LIVE_TRADING_LOCKOUT=True.
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
from core.signals.signal_outcome_dataset import (
    CALCULATION_VERSION,
    SignalOutcomeDatasetService,
    parse_timestamp,
)
from core.signals.signal_score_discrimination import assign_score_bucket

_log = logging.getLogger("SIGNAL_FORWARD_OBSERVATION")
_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_DB_PATH = _ROOT / "db" / "signals_history.db"

OBSERVATION_VERSION = "FORWARD_OBSERVATION_V1"
FORWARD_CUTOFF_VERSION = "PHASE_D_V1_20260926"
DEFAULT_FORWARD_CUTOFF_ISO = "2026-09-26T00:00:00+05:30"

CANONICAL_SCORE_BUCKETS = ["<70", "70-74", "75-79", "80-84", "85+"]
GATE_MIN_RESOLVED_PER_ACTIVE_BUCKET = 100
GATE_MIN_TOTAL_RESOLVED = 300
GATE_MIN_DISTINCT_MONTHS = 2
GATE_MIN_RESOLVED_PER_MONTH = 30
GATE_MAX_DATA_QUALITY_ERROR_RATE = 0.05
GATE_MAX_STALE_RATE = 0.02


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
class ForwardObservationRecord:
    forward_id: str
    signal_id: str
    cohort_id: str
    observation_source: str
    forward_cutoff_version: str
    registered_at: str
    market_date: str
    session_name: str
    score: int
    score_bucket: str
    direction: str
    symbol: str
    category: str
    entry_price: float
    stop_loss: float
    target_1: float
    target_2: float
    prediction_hash: str
    snapshot_captured_at: str
    observation_status: str  # "REGISTERED", "OBSERVING", "RESOLVED", "TIMEOUT", "AMBIGUOUS", "NO_DATA", "INVALIDATED"
    terminal_outcome: str | None
    is_resolved: int  # 1 if resolved, 0 otherwise
    resolution_timestamp: str | None
    mfe_r: float | None
    mae_r: float | None
    realized_r: float | None
    data_quality_status: str
    observation_version: str
    last_updated_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BucketReadinessSummary:
    bucket: str
    n_forward: int
    target_first_count: int
    sl_first_count: int
    timeout_count: int
    ambiguous_count: int
    no_data_count: int
    unresolved_count: int
    n_resolved: int  # target_first + sl_first + timeout
    target_first_rate: float | None
    sl_first_rate: float | None
    required_resolved: int
    remaining_resolved_needed: int
    bucket_status: str  # "INACTIVE_BUCKET", "INSUFFICIENT_SAMPLE", "COLLECTING", "READY_FOR_REVIEW"
    is_active: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DailyObservationReport:
    report_version: str
    market_date: str
    cohort_id: str
    generated_at: str
    total_forward_observations: int
    new_observations_today: int
    total_resolved: int
    total_unresolved: int
    total_ambiguous: int
    total_no_data: int
    distinct_months_count: int
    distinct_months_list: list[str]
    data_quality_error_rate: float
    stale_observations_count: int
    stale_rate: float
    bucket_readiness: dict[str, BucketReadinessSummary]
    overall_readiness_status: str  # "INSUFFICIENT_SAMPLE", "COLLECTING", "DATA_QUALITY_BLOCKED", "READY_FOR_REVIEW"
    calibration_readiness_explanation: str
    live_trading_lockout_enforced: bool

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["bucket_readiness"] = {k: v.to_dict() for k, v in self.bucket_readiness.items()}
        return d


# ============================================================================
# 2. Forward Observation Service
# ============================================================================

class SignalForwardObservationService:
    """Automated service managing out-of-sample forward observations and calibration readiness."""

    _instance: SignalForwardObservationService | None = None
    _lock = threading.Lock()

    def __init__(self, db_path: Path | str | None = None) -> None:
        self._db_path = Path(db_path) if db_path else _DEFAULT_DB_PATH
        self._io_lock = threading.Lock()
        self._init_db()

    @classmethod
    def get_instance(cls, db_path: Path | str | None = None) -> SignalForwardObservationService:
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

    def _init_db(self) -> None:
        """Create signal_forward_observations table if not already present."""
        if not self._db_path.parent.exists():
            self._db_path.parent.mkdir(parents=True, exist_ok=True)

        with self._io_lock:
            conn = self._get_conn()
            try:
                cur = conn.cursor()
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS signal_forward_observations (
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
                cur.execute("CREATE INDEX IF NOT EXISTS idx_fwd_obs_cohort ON signal_forward_observations(cohort_id)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_fwd_obs_bucket ON signal_forward_observations(score_bucket)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_fwd_obs_status ON signal_forward_observations(observation_status)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_fwd_obs_date ON signal_forward_observations(market_date)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_fwd_obs_resolved ON signal_forward_observations(is_resolved)")
                conn.commit()
            except Exception as ex:
                _log.error("Failed to initialize signal_forward_observations table: %s", ex)
            finally:
                conn.close()

    def register_forward_signal(
        self,
        signal_id: str,
        cohort_id: str | None = None,
        observation_source: str = "FORWARD_LIVE_SCAN",
        cutoff_iso: str | None = None,
        session_name: str = "",
        registered_at: str | None = None,
    ) -> dict[str, Any] | None:
        """Register a newly generated signal as a forward out-of-sample observation.

        Enforces:
        - Immutable Phase-A snapshot existence
        - Look-ahead boundary: snapshot_captured_at >= cutoff AND registered_at >= snapshot_captured_at
        - Exclusion of SEED / TEST / MOCK / BACKFILL sources
        - Deterministic cohort identity (e.g. FWD_YYYY-MM)
        - Canonical bucket assignment
        """
        cutoff_str = cutoff_iso or DEFAULT_FORWARD_CUTOFF_ISO
        cutoff_dt = _normalize_dt(parse_timestamp(cutoff_str))
        registered_at_val = registered_at or now_ist().isoformat()
        reg_dt = _normalize_dt(parse_timestamp(registered_at_val))

        with self._io_lock:
            conn = self._get_conn()
            try:
                cur = conn.cursor()
                # 1. Fetch immutable Phase-A snapshot
                cur.execute(
                    "SELECT * FROM signal_prediction_snapshots WHERE signal_id = ?",
                    (signal_id,),
                )
                snap_row = cur.fetchone()
                if not snap_row:
                    _log.warning("Cannot register forward signal: snapshot not found for %s", signal_id)
                    return None

                snap = dict(snap_row)
                snap_captured_at = str(snap.get("captured_at") or "").strip()
                snap_dt = _normalize_dt(parse_timestamp(snap_captured_at))

                # 2. Enforce out-of-sample boundary
                if cutoff_dt and snap_dt and snap_dt < cutoff_dt:
                    _log.warning("Signal %s predates forward cutoff %s; rejected from forward cohort", signal_id, cutoff_str)
                    return None

                if snap_dt and reg_dt and reg_dt < snap_dt:
                    _log.warning("Registration time %s is before snapshot time %s for %s", registered_at_val, snap_captured_at, signal_id)
                    return None

                # 3. Bar mock, seed, and test signals
                source_val = str(snap.get("source") or "").upper()
                if source_val in ("SEED", "TEST", "MOCK", "BACKFILL"):
                    _log.warning("Signal %s has test/seed source %s; rejected", signal_id, source_val)
                    return None

                raw_json = str(snap.get("raw_signal_json") or "")
                if "is_seed_sample" in raw_json:
                    _log.warning("Signal %s has is_seed_sample marker; rejected", signal_id)
                    return None

                # 4. Derive market date and cohort ID
                market_date = snap_captured_at[:10] if len(snap_captured_at) >= 10 else registered_at_val[:10]
                month_str = market_date[:7] if len(market_date) >= 7 else "UNKNOWN"
                resolved_cohort = cohort_id or f"FWD_{month_str}"

                # 5. Score bucket assignment
                score_val = int(snap["score"])
                bucket_val = assign_score_bucket(score_val) or "<70"

                forward_id = f"FWD_{signal_id}"
                prediction_hash = str(snap.get("snapshot_hash") or "")
                entry_price = float(snap.get("entry_price") or 0.0)
                stop_loss = float(snap.get("stop_loss") or 0.0)
                target_1 = float(snap.get("target_1") or 0.0)
                target_2 = float(snap.get("target_2") or 0.0)

                # 6. Check existing record
                cur.execute(
                    "SELECT forward_id, observation_status, is_resolved, terminal_outcome FROM signal_forward_observations WHERE signal_id = ?",
                    (signal_id,),
                )
                existing = cur.fetchone()
                if existing:
                    # Already registered, do not overwrite terminal state
                    return dict(existing)

                observation_status = "OBSERVING"
                cur.execute("""
                    INSERT INTO signal_forward_observations (
                        forward_id, signal_id, cohort_id, observation_source,
                        forward_cutoff_version, registered_at, market_date, session_name,
                        score, score_bucket, direction, symbol, category,
                        entry_price, stop_loss, target_1, target_2, prediction_hash,
                        snapshot_captured_at, observation_status, terminal_outcome,
                        is_resolved, resolution_timestamp, mfe_r, mae_r, realized_r,
                        data_quality_status, observation_version, last_updated_at
                    ) VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                    )
                """, (
                    forward_id, signal_id, resolved_cohort, observation_source,
                    FORWARD_CUTOFF_VERSION, registered_at_val, market_date, session_name,
                    score_val, bucket_val, snap["direction"], snap["symbol"], snap["category"],
                    entry_price, stop_loss, target_1, target_2, prediction_hash,
                    snap_captured_at, observation_status, None,
                    0, None, None, None, None,
                    "VALID_DATA", OBSERVATION_VERSION, registered_at_val,
                ))
                conn.commit()

                cur.execute("SELECT * FROM signal_forward_observations WHERE forward_id = ?", (forward_id,))
                res = dict(cur.fetchone())
                return res
            except Exception as ex:
                _log.error("Failed to register forward signal %s: %s", signal_id, ex)
                return None
            finally:
                conn.close()

    def sync_forward_outcomes(self, cohort_id: str | None = None, limit: int = 1000) -> int:
        """Synchronize in-flight forward observations with Phase-B outcome measurements.

        Consumes Phase-B measurements strictly without competing outcome calculation.
        Updates observation_status, terminal_outcome, and resolution metrics idempotently.
        """
        phase_b_service = SignalOutcomeDatasetService.get_instance(db_path=self._db_path)

        with self._io_lock:
            conn = self._get_conn()
            try:
                cur = conn.cursor()
                if cohort_id:
                    cur.execute(
                        "SELECT signal_id, observation_status FROM signal_forward_observations WHERE cohort_id = ? AND is_resolved = 0 LIMIT ?",
                        (cohort_id, limit),
                    )
                else:
                    cur.execute(
                        "SELECT signal_id, observation_status FROM signal_forward_observations WHERE is_resolved = 0 LIMIT ?",
                        (limit,),
                    )
                in_flight_rows = [dict(r) for r in cur.fetchall()]
            finally:
                conn.close()

        updated_count = 0
        now_ts = now_ist().isoformat()

        for item in in_flight_rows:
            sig_id = item["signal_id"]
            # 1. Consume Phase-B outcome measurement: read existing record first to guarantee read-only immutability
            meas: dict[str, Any] | None = None
            with self._io_lock:
                conn = self._get_conn()
                try:
                    cur = conn.cursor()
                    cur.execute("SELECT * FROM signal_outcome_measurements WHERE signal_id = ?", (sig_id,))
                    row = cur.fetchone()
                    if row:
                        meas = dict(row)
                finally:
                    conn.close()

            if not meas:
                meas = phase_b_service.build_signal_outcome_measurement(sig_id)

            if not meas:
                continue

            outcome_val = str(meas.get("outcome") or "UNRESOLVED").upper()
            dq_val = str(meas.get("data_quality_status") or "VALID_DATA").upper()

            # 2. Map Phase-B outcome to forward observation status
            is_resolved = 0
            res_timestamp = None
            if outcome_val in ("TARGET_FIRST", "SL_FIRST"):
                obs_status = "RESOLVED"
                is_resolved = 1
                res_timestamp = meas.get("exit_at") or meas.get("first_touch_at") or now_ts
            elif outcome_val == "TIMEOUT":
                obs_status = "TIMEOUT"
                is_resolved = 1
                res_timestamp = meas.get("exit_at") or meas.get("first_touch_at") or now_ts
            elif outcome_val == "AMBIGUOUS" or dq_val == "AMBIGUOUS_BAR":
                obs_status = "AMBIGUOUS"
                is_resolved = 0
            elif outcome_val == "NO_DATA" or dq_val == "NO_DATA":
                obs_status = "NO_DATA"
                is_resolved = 0
            elif outcome_val == "INVALIDATED" or dq_val == "INVALID_DATA":
                obs_status = "INVALIDATED"
                is_resolved = 0
            else:
                obs_status = "OBSERVING"
                is_resolved = 0

            mfe_r = meas.get("mfe_r")
            mae_r = meas.get("mae_r")
            realized_r = meas.get("realized_r")

            # 3. Update record idempotently
            with self._io_lock:
                conn = self._get_conn()
                try:
                    cur = conn.cursor()
                    cur.execute("""
                        UPDATE signal_forward_observations
                        SET observation_status = ?,
                            terminal_outcome = ?,
                            is_resolved = ?,
                            resolution_timestamp = ?,
                            mfe_r = ?,
                            mae_r = ?,
                            realized_r = ?,
                            data_quality_status = ?,
                            last_updated_at = ?
                        WHERE signal_id = ?
                    """, (
                        obs_status, outcome_val, is_resolved, res_timestamp,
                        mfe_r, mae_r, realized_r, dq_val, now_ts, sig_id
                    ))
                    conn.commit()
                    updated_count += 1
                finally:
                    conn.close()

        return updated_count

    def evaluate_readiness_gates(
        self, cohort_id: str | None = None
    ) -> tuple[dict[str, BucketReadinessSummary], str, str]:
        """Evaluate Phase-D empirical readiness gates across canonical score buckets.

        Returns:
            (bucket_readiness_map, overall_status, explanation)
        """
        with self._io_lock:
            conn = self._get_conn()
            try:
                cur = conn.cursor()
                if cohort_id:
                    cur.execute(
                        "SELECT * FROM signal_forward_observations WHERE cohort_id = ?",
                        (cohort_id,),
                    )
                else:
                    cur.execute("SELECT * FROM signal_forward_observations")
                all_obs = [dict(r) for r in cur.fetchall()]
            finally:
                conn.close()

        # Partition by bucket
        bucket_data: dict[str, list[dict[str, Any]]] = {b: [] for b in CANONICAL_SCORE_BUCKETS}
        for obs in all_obs:
            b = obs.get("score_bucket")
            if b in bucket_data:
                bucket_data[b].append(obs)
            else:
                bucket_data["<70"].append(obs)

        bucket_summaries: dict[str, BucketReadinessSummary] = {}
        active_buckets: list[str] = []
        all_active_buckets_ready = True
        total_resolved_all = 0

        for b_name in CANONICAL_SCORE_BUCKETS:
            rows = bucket_data[b_name]
            n_fwd = len(rows)

            t1_count = sum(1 for r in rows if r.get("terminal_outcome") == "TARGET_FIRST")
            sl_count = sum(1 for r in rows if r.get("terminal_outcome") == "SL_FIRST")
            to_count = sum(1 for r in rows if r.get("terminal_outcome") == "TIMEOUT")
            amb_count = sum(1 for r in rows if r.get("observation_status") == "AMBIGUOUS")
            nodata_count = sum(1 for r in rows if r.get("observation_status") == "NO_DATA")
            unres_count = sum(1 for r in rows if r.get("is_resolved") == 0 and r.get("observation_status") not in ("AMBIGUOUS", "NO_DATA", "INVALIDATED"))

            n_res = t1_count + sl_count + to_count
            total_resolved_all += n_res

            t1_rate = round(t1_count / n_res, 4) if n_res > 0 else None
            sl_rate = round(sl_count / n_res, 4) if n_res > 0 else None
            req_res = GATE_MIN_RESOLVED_PER_ACTIVE_BUCKET
            rem_needed = max(0, req_res - n_res)

            # Determine bucket activity and readiness status
            if n_fwd == 0:
                is_active = False
                b_status = "INACTIVE_BUCKET"
            elif n_fwd < 10:
                is_active = True
                active_buckets.append(b_name)
                b_status = "INSUFFICIENT_SAMPLE"
                all_active_buckets_ready = False
            elif n_res < req_res:
                is_active = True
                active_buckets.append(b_name)
                b_status = "COLLECTING"
                all_active_buckets_ready = False
            else:
                is_active = True
                active_buckets.append(b_name)
                b_status = "READY_FOR_REVIEW"

            bucket_summaries[b_name] = BucketReadinessSummary(
                bucket=b_name,
                n_forward=n_fwd,
                target_first_count=t1_count,
                sl_first_count=sl_count,
                timeout_count=to_count,
                ambiguous_count=amb_count,
                no_data_count=nodata_count,
                unresolved_count=unres_count,
                n_resolved=n_res,
                target_first_rate=t1_rate,
                sl_first_rate=sl_rate,
                required_resolved=req_res,
                remaining_resolved_needed=rem_needed,
                bucket_status=b_status,
                is_active=is_active,
            )

        # Longitudinal check: distinct calendar months with >= GATE_MIN_RESOLVED_PER_MONTH
        month_resolved_counts: dict[str, int] = {}
        for obs in all_obs:
            if obs.get("is_resolved") == 1:
                m_date = str(obs.get("market_date") or "")
                m_key = m_date[:7] if len(m_date) >= 7 else "UNKNOWN"
                month_resolved_counts[m_key] = month_resolved_counts.get(m_key, 0) + 1

        qualifying_months = [m for m, cnt in month_resolved_counts.items() if cnt >= GATE_MIN_RESOLVED_PER_MONTH]
        has_sufficient_months = len(qualifying_months) >= GATE_MIN_DISTINCT_MONTHS

        # Data quality checks
        total_obs_count = len(all_obs)
        total_errors = sum(1 for r in all_obs if r.get("observation_status") in ("AMBIGUOUS", "NO_DATA", "INVALIDATED"))
        dq_error_rate = round(total_errors / total_obs_count, 4) if total_obs_count > 0 else 0.0
        dq_passed = dq_error_rate <= GATE_MAX_DATA_QUALITY_ERROR_RATE

        # Stale observations check (> 48 hours in OBSERVING state)
        stale_count = 0
        now_dt = _normalize_dt(parse_timestamp(now_ist().isoformat()))
        for r in all_obs:
            if r.get("observation_status") == "OBSERVING" and now_dt:
                reg_dt = _normalize_dt(parse_timestamp(r.get("registered_at")))
                if reg_dt and (now_dt - reg_dt).total_seconds() > 48 * 3600:
                    stale_count += 1
        stale_rate = round(stale_count / total_obs_count, 4) if total_obs_count > 0 else 0.0
        stale_passed = stale_rate <= GATE_MAX_STALE_RATE

        # Final Overall System Determination
        if total_obs_count == 0:
            overall_status = "INSUFFICIENT_SAMPLE"
            explanation = "Zero forward observations registered. Collecting forward cohort data."
        elif not dq_passed:
            overall_status = "DATA_QUALITY_BLOCKED"
            explanation = f"Data quality error rate ({dq_error_rate:.1%}) exceeds maximum threshold ({GATE_MAX_DATA_QUALITY_ERROR_RATE:.1%})."
        elif not stale_passed:
            overall_status = "COLLECTING"
            explanation = f"Stale backlog rate ({stale_rate:.1%}) exceeds 2% threshold. Ongoing resolution required."
        elif not active_buckets:
            overall_status = "INSUFFICIENT_SAMPLE"
            explanation = "No active score buckets have accumulated sufficient forward samples."
        elif not all_active_buckets_ready:
            overall_status = "COLLECTING"
            unmet = [b.bucket for b in bucket_summaries.values() if b.is_active and b.bucket_status != "READY_FOR_REVIEW"]
            explanation = f"Active buckets {unmet} have not yet reached the required {GATE_MIN_RESOLVED_PER_ACTIVE_BUCKET} resolved observations."
        elif total_resolved_all < GATE_MIN_TOTAL_RESOLVED:
            overall_status = "COLLECTING"
            explanation = f"Total resolved observations ({total_resolved_all}) below total readiness gate ({GATE_MIN_TOTAL_RESOLVED})."
        elif not has_sufficient_months:
            overall_status = "COLLECTING"
            explanation = f"Qualifying calendar months ({len(qualifying_months)}) below requirement of >= {GATE_MIN_DISTINCT_MONTHS} distinct periods."
        else:
            overall_status = "READY_FOR_REVIEW"
            explanation = (
                "All active forward score buckets meet n_resolved >= 100 across >= 2 independent calendar periods. "
                "The dataset has reached evidence maturity for a future human-reviewed calibration study (Phase E). "
                "Live trading remains locked out."
            )

        return bucket_summaries, overall_status, explanation

    def generate_daily_observation_report(
        self, market_date: str | None = None, cohort_id: str | None = None
    ) -> DailyObservationReport:
        """Generate deterministic daily forward observation report."""
        rep_date = market_date or now_ist().date().isoformat()
        resolved_cohort = cohort_id or f"FWD_{rep_date[:7]}"

        bucket_summaries, overall_status, explanation = self.evaluate_readiness_gates(cohort_id=cohort_id)

        with self._io_lock:
            conn = self._get_conn()
            try:
                cur = conn.cursor()
                if cohort_id:
                    cur.execute(
                        "SELECT * FROM signal_forward_observations WHERE cohort_id = ?",
                        (cohort_id,),
                    )
                else:
                    cur.execute("SELECT * FROM signal_forward_observations")
                all_obs = [dict(r) for r in cur.fetchall()]
            finally:
                conn.close()

        total_obs = len(all_obs)
        new_today = sum(1 for r in all_obs if str(r.get("market_date") or "").startswith(rep_date))
        total_resolved = sum(1 for r in all_obs if r.get("is_resolved") == 1)
        total_unres = sum(1 for r in all_obs if r.get("is_resolved") == 0 and r.get("observation_status") not in ("AMBIGUOUS", "NO_DATA", "INVALIDATED"))
        total_amb = sum(1 for r in all_obs if r.get("observation_status") == "AMBIGUOUS")
        total_nodata = sum(1 for r in all_obs if r.get("observation_status") == "NO_DATA")

        months_set = {str(r.get("market_date") or "")[:7] for r in all_obs if len(str(r.get("market_date") or "")) >= 7}
        months_list = sorted(list(months_set))

        total_errors = sum(1 for r in all_obs if r.get("observation_status") in ("AMBIGUOUS", "NO_DATA", "INVALIDATED"))
        dq_error_rate = round(total_errors / total_obs, 4) if total_obs > 0 else 0.0

        stale_count = 0
        now_dt = _normalize_dt(parse_timestamp(now_ist().isoformat()))
        for r in all_obs:
            if r.get("observation_status") == "OBSERVING" and now_dt:
                reg_dt = _normalize_dt(parse_timestamp(r.get("registered_at")))
                if reg_dt and (now_dt - reg_dt).total_seconds() > 48 * 3600:
                    stale_count += 1
        stale_rate = round(stale_count / total_obs, 4) if total_obs > 0 else 0.0

        return DailyObservationReport(
            report_version=OBSERVATION_VERSION,
            market_date=rep_date,
            cohort_id=resolved_cohort,
            generated_at=now_ist().isoformat(),
            total_forward_observations=total_obs,
            new_observations_today=new_today,
            total_resolved=total_resolved,
            total_unresolved=total_unres,
            total_ambiguous=total_amb,
            total_no_data=total_nodata,
            distinct_months_count=len(months_list),
            distinct_months_list=months_list,
            data_quality_error_rate=dq_error_rate,
            stale_observations_count=stale_count,
            stale_rate=stale_rate,
            bucket_readiness=bucket_summaries,
            overall_readiness_status=overall_status,
            calibration_readiness_explanation=explanation,
            live_trading_lockout_enforced=True,
        )
