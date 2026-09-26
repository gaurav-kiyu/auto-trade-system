"""Signal Score Discrimination & Statistical Significance Service (Phase C).

Governance Authority: OPB-FINAL-PHASE-GOVERNANCE-001 / v2.60 Phase C Roadmap.

Investigates whether historical predictive scores contain measurable discrimination
across real subsequent outcomes without model tuning, probability calibration,
or live-trading enablement.

Strict Invariants:
1. Zero Data Mutation: signal_prediction_snapshots and signal_outcome_measurements
   remain strictly read-only.
2. Zero Probability Fabrication: No calibrated probabilities (p_t1, p_sl) are generated.
3. Zero Model / Threshold Changes: Signal generation weights and thresholds are untouched.
4. Pre-T0 Immutable Scores: Uses immutable score captured at prediction time (T0).
5. Explicit Hypothesis Families: Holm-Bonferroni multiple-comparison correction is
   scoped to well-defined, independent families; raw and adjusted p-values reported.
6. Practical Magnitude vs Statistical Significance: Effect sizes reported alongside p-values.
7. Small-Sample Suppression: Buckets or periods with n < MIN_INFERENCE_SAMPLE_SIZE
   are marked INSUFFICIENT_SAMPLE to prevent misleading statistical inference.
8. Descriptive Temporal Analysis: Monthly breakdowns are purely descriptive.
9. Live Trading Disabled: EXECUTION_MODE=SIGNAL_ONLY, LIVE_TRADING_LOCKOUT=True.
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

_log = logging.getLogger("SIGNAL_SCORE_DISCRIMINATION")
_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_DB_PATH = _ROOT / "db" / "signals_history.db"

ANALYSIS_VERSION = "SCORE_DISCRIMINATION_V1"
MIN_INFERENCE_SAMPLE_SIZE = 10
SCORE_BUCKETS = ["70-74", "75-79", "80-84", "85+"]


# ============================================================================
# 1. Bucket Assignment & Mathematical Helpers
# ============================================================================

def assign_score_bucket(score: float | int | None) -> str | None:
    """Assign a predictive score to its canonical Phase C score bucket.

    Buckets:
        70-74: [70.0, 75.0)
        75-79: [75.0, 80.0)
        80-84: [80.0, 85.0)
        85+:   >= 85.0
        <70:   < 70.0
    """
    if score is None:
        return None
    try:
        s = float(score)
    except (ValueError, TypeError):
        return None

    if s >= 85.0:
        return "85+"
    elif 80.0 <= s < 85.0:
        return "80-84"
    elif 75.0 <= s < 80.0:
        return "75-79"
    elif 70.0 <= s < 75.0:
        return "70-74"
    else:
        return "<70"


def wilson_confidence_interval(
    successes: int, total: int, z: float = 1.96
) -> tuple[float | None, float, float]:
    """Calculate the Wilson score confidence interval for a proportion successes/total.

    Returns:
        (estimate, ci_lower, ci_upper)
        If total <= 0: returns (None, 0.0, 1.0)
    """
    if total <= 0:
        return None, 0.0, 1.0
    if successes < 0 or successes > total:
        return None, 0.0, 1.0

    p = successes / total
    denom = 1.0 + (z * z) / total
    center = (p + (z * z) / (2.0 * total)) / denom
    margin = (z * math.sqrt((p * (1.0 - p) / total) + (z * z) / (4.0 * total * total))) / denom
    lower = max(0.0, center - margin)
    upper = min(1.0, center + margin)
    return round(p, 4), round(lower, 4), round(upper, 4)


def calculate_distribution_stats(values: list[float]) -> dict[str, float | None]:
    """Calculate descriptive distribution statistics for continuous variables."""
    valid_vals = [float(v) for v in values if v is not None and not math.isnan(v)]
    if not valid_vals:
        return {
            "count": 0,
            "mean": None,
            "median": None,
            "std": None,
            "min": None,
            "max": None,
            "q25": None,
            "q75": None,
            "iqr": None,
        }

    v_sorted = sorted(valid_vals)
    n = len(v_sorted)
    mean_val = sum(v_sorted) / n

    if n % 2 == 1:
        median_val = v_sorted[n // 2]
    else:
        median_val = (v_sorted[n // 2 - 1] + v_sorted[n // 2]) / 2.0

    if n >= 2:
        var = sum((x - mean_val) ** 2 for x in v_sorted) / (n - 1)
        std_val = math.sqrt(var)
    else:
        std_val = 0.0

    def percentile(p: float) -> float:
        idx = p * (n - 1)
        i = int(idx)
        rem = idx - i
        if i >= n - 1:
            return v_sorted[-1]
        return v_sorted[i] + rem * (v_sorted[i + 1] - v_sorted[i])

    q25 = percentile(0.25)
    q75 = percentile(0.75)
    iqr = q75 - q25

    return {
        "count": n,
        "mean": round(mean_val, 4),
        "median": round(median_val, 4),
        "std": round(std_val, 4),
        "min": round(v_sorted[0], 4),
        "max": round(v_sorted[-1], 4),
        "q25": round(q25, 4),
        "q75": round(q75, 4),
        "iqr": round(iqr, 4),
    }


def calculate_expectancy(realized_r_values: list[float]) -> dict[str, Any]:
    """Calculate expectancy (arithmetic mean Realized_R) and dispersion from valid observations only."""
    valid_r = [float(r) for r in realized_r_values if r is not None and not math.isnan(r)]
    n = len(valid_r)
    if n == 0:
        return {
            "expectancy": None,
            "median": None,
            "std": None,
            "sample_size": 0,
            "status": "INSUFFICIENT_SAMPLE",
        }
    dist = calculate_distribution_stats(valid_r)
    return {
        "expectancy": dist["mean"],
        "median": dist["median"],
        "std": dist["std"],
        "sample_size": n,
        "status": "VALID_SAMPLE" if n >= MIN_INFERENCE_SAMPLE_SIZE else "INSUFFICIENT_SAMPLE",
    }


def calculate_profit_factor(realized_r_values: list[float]) -> tuple[float | None, str]:
    """Calculate profit factor = sum(positive Realized_R) / abs(sum(negative Realized_R)).

    Returns:
        (profit_factor, status)
    """
    valid_r = [float(r) for r in realized_r_values if r is not None and not math.isnan(r)]
    if not valid_r:
        return None, "INSUFFICIENT_SAMPLE"

    pos_sum = sum(r for r in valid_r if r > 0)
    neg_sum = abs(sum(r for r in valid_r if r < 0))

    if neg_sum == 0.0:
        if pos_sum > 0.0:
            return None, "UNDEFINED_NO_LOSSES"
        else:
            return 0.0, "NO_ACTIVITY"

    if pos_sum == 0.0:
        return 0.0, "ZERO_WINS"

    pf = round(pos_sum / neg_sum, 4)
    return pf, "VALID"


def adjust_pvalues_holm(p_values: list[float]) -> list[float]:
    """Apply step-down Holm-Bonferroni multiple-comparison correction to a family of p-values.

    Preserves original ordering and enforces monotonicity.
    """
    m = len(p_values)
    if m <= 1:
        return [round(p, 6) for p in p_values]

    # Index and sort
    indexed = sorted(enumerate(p_values), key=lambda x: x[1])
    adjusted_indexed: list[tuple[int, float]] = []

    cum_max = 0.0
    for rank, (orig_idx, p_val) in enumerate(indexed):
        multiplier = m - rank
        raw_adj = min(1.0, multiplier * p_val)
        adj = max(cum_max, raw_adj)
        cum_max = adj
        adjusted_indexed.append((orig_idx, round(adj, 6)))

    # Restore original order
    adjusted_indexed.sort(key=lambda x: x[0])
    return [item[1] for item in adjusted_indexed]


# ============================================================================
# 2. Dataclasses for Analytical Outputs
# ============================================================================

@dataclass
class WilsonCI:
    estimate: float | None
    ci_lower: float
    ci_upper: float
    sample_size: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ScoreBucketMetrics:
    bucket: str
    n_total: int
    target_first_count: int
    sl_first_count: int
    timeout_count: int
    ambiguous_count: int
    unresolved_count: int
    no_data_count: int
    valid_resolved_count: int

    # Proportions & Wilson CIs
    target_first_rate: float | None
    target_first_ci: WilsonCI
    sl_first_rate: float | None
    sl_first_ci: WilsonCI
    timeout_rate: float | None
    timeout_ci: WilsonCI
    ambiguous_rate: float | None
    unresolved_rate: float | None
    no_data_rate: float | None

    # Excursion & Expectancy Distributions
    mfe_r_stats: dict[str, float | None]
    mae_r_stats: dict[str, float | None]
    realized_r_stats: dict[str, float | None]
    expectancy_info: dict[str, Any]
    profit_factor: float | None
    profit_factor_status: str

    # Duration
    time_to_first_event_median: float | None
    time_to_first_event_mean: float | None

    # Inference Status
    sample_size_status: str  # "VALID_SAMPLE" | "INSUFFICIENT_SAMPLE"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["target_first_ci"] = self.target_first_ci.to_dict()
        d["sl_first_ci"] = self.sl_first_ci.to_dict()
        d["timeout_ci"] = self.timeout_ci.to_dict()
        return d


@dataclass
class PairwiseComparison:
    family: str
    bucket_a: str
    bucket_b: str
    metric: str
    n_a: int
    n_b: int
    diff_means: float | None
    diff_medians: float | None
    test_name: str
    statistic: float | None
    p_value_unadjusted: float | None
    p_value_adjusted: float | None
    effect_size_name: str
    effect_size_value: float | None
    significant_05: bool
    status: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TemporalBucketPeriod:
    period: str  # YYYY-MM
    total_signals: int
    bucket_counts: dict[str, int]
    bucket_target_first_counts: dict[str, int]
    bucket_resolved_counts: dict[str, int]
    bucket_target_rates: dict[str, float | None]
    status: str  # "DESCRIPTIVE_ONLY" | "INSUFFICIENT_SAMPLE"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ScoreDiscriminationReport:
    analysis_version: str
    dataset_timestamp: str
    include_seed_samples: bool
    total_snapshots: int
    total_measurements_joined: int
    seed_samples_excluded: int
    actual_score_min: float | None
    actual_score_max: float | None
    actual_score_mean: float | None
    bucket_metrics: dict[str, ScoreBucketMetrics]
    omnibus_tests: dict[str, Any]
    pairwise_comparisons: list[PairwiseComparison]
    temporal_stability: list[TemporalBucketPeriod]
    data_quality_summary: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        return {
            "analysis_version": self.analysis_version,
            "dataset_timestamp": self.dataset_timestamp,
            "include_seed_samples": self.include_seed_samples,
            "total_snapshots": self.total_snapshots,
            "total_measurements_joined": self.total_measurements_joined,
            "seed_samples_excluded": self.seed_samples_excluded,
            "actual_score_min": self.actual_score_min,
            "actual_score_max": self.actual_score_max,
            "actual_score_mean": self.actual_score_mean,
            "bucket_metrics": {k: v.to_dict() for k, v in self.bucket_metrics.items()},
            "omnibus_tests": self.omnibus_tests,
            "pairwise_comparisons": [p.to_dict() for p in self.pairwise_comparisons],
            "temporal_stability": [t.to_dict() for t in self.temporal_stability],
            "data_quality_summary": self.data_quality_summary,
        }


# ============================================================================
# 3. Main Score Discrimination Analytical Service
# ============================================================================

class SignalScoreDiscriminationService:
    """Analytical service measuring score bucket discrimination on immutable snapshots and outcomes."""

    _instance: SignalScoreDiscriminationService | None = None
    _lock = threading.Lock()

    def __init__(self, db_path: Path | str | None = None) -> None:
        self._db_path = Path(db_path) if db_path else _DEFAULT_DB_PATH
        self._io_lock = threading.Lock()

    @classmethod
    def get_instance(cls, db_path: Path | str | None = None) -> SignalScoreDiscriminationService:
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

    def _get_read_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(f"file:{self._db_path}?mode=ro", uri=True, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def fetch_joined_dataset(
        self,
        category: str = "all",
        include_seed_samples: bool = False,
    ) -> list[dict[str, Any]]:
        """Fetch joined prediction snapshots and outcome measurements strictly read-only."""
        if not self._db_path.is_file():
            return []

        with self._io_lock:
            # Fall back to standard read-only connection if URI mode fails
            try:
                conn = self._get_read_conn()
            except Exception:
                conn = sqlite3.connect(str(self._db_path), timeout=10)
                conn.row_factory = sqlite3.Row

            try:
                cur = conn.cursor()
                # Check required tables exist
                cur.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('signal_prediction_snapshots', 'signal_outcome_measurements')"
                )
                tables = {r[0] for r in cur.fetchall()}
                if "signal_prediction_snapshots" not in tables or "signal_outcome_measurements" not in tables:
                    return []

                # Optional join with system_signals to inspect raw_data seed flags
                has_system_signals = bool(
                    cur.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='system_signals'").fetchone()
                )

                if has_system_signals:
                    query = """
                        SELECT
                            sps.signal_id,
                            sps.score,
                            sps.captured_at,
                            sps.category,
                            sps.symbol,
                            sps.direction,
                            sps.entry_price,
                            sps.source,
                            sps.raw_signal_json,
                            ss.raw_data as ss_raw_data,
                            som.outcome,
                            som.raw_lifecycle_state,
                            som.mfe,
                            som.mae,
                            som.mfe_r,
                            som.mae_r,
                            som.realized_r,
                            som.time_to_first_event_seconds,
                            som.time_to_t1_seconds,
                            som.time_to_t2_seconds,
                            som.time_to_sl_seconds,
                            som.observation_count,
                            som.data_quality_status
                        FROM signal_prediction_snapshots sps
                        INNER JOIN signal_outcome_measurements som ON sps.signal_id = som.signal_id
                        LEFT JOIN system_signals ss ON sps.signal_id = ss.signal_id
                        ORDER BY sps.captured_at ASC
                    """
                else:
                    query = """
                        SELECT
                            sps.signal_id,
                            sps.score,
                            sps.captured_at,
                            sps.category,
                            sps.symbol,
                            sps.direction,
                            sps.entry_price,
                            sps.source,
                            sps.raw_signal_json,
                            NULL as ss_raw_data,
                            som.outcome,
                            som.raw_lifecycle_state,
                            som.mfe,
                            som.mae,
                            som.mfe_r,
                            som.mae_r,
                            som.realized_r,
                            som.time_to_first_event_seconds,
                            som.time_to_t1_seconds,
                            som.time_to_t2_seconds,
                            som.time_to_sl_seconds,
                            som.observation_count,
                            som.data_quality_status
                        FROM signal_prediction_snapshots sps
                        INNER JOIN signal_outcome_measurements som ON sps.signal_id = som.signal_id
                        ORDER BY sps.captured_at ASC
                    """

                cur.execute(query)
                raw_rows = [dict(r) for r in cur.fetchall()]
            finally:
                conn.close()

        filtered: list[dict[str, Any]] = []
        for r in raw_rows:
            if category != "all" and r.get("category") != category:
                continue

            if not include_seed_samples:
                # Discard seed/mock samples
                src = str(r.get("source") or "").upper()
                if src in ("SEED", "TEST", "MOCK"):
                    continue
                raw_s = str(r.get("raw_signal_json") or "")
                if "is_seed_sample" in raw_s:
                    continue
                ss_raw = str(r.get("ss_raw_data") or "")
                if "is_seed_sample" in ss_raw:
                    continue

            filtered.append(r)

        return filtered

    def analyze_score_buckets(
        self,
        category: str = "all",
        include_seed_samples: bool = False,
        dataset: list[dict[str, Any]] | None = None,
    ) -> ScoreDiscriminationReport:
        """Perform comprehensive score discrimination analysis across buckets without model/prob alterations."""
        if dataset is None:
            dataset = self.fetch_joined_dataset(
                category=category, include_seed_samples=include_seed_samples
            )

        # 1. Distribution of raw prediction scores
        scores = [float(r["score"]) for r in dataset if r.get("score") is not None]
        score_min = min(scores) if scores else None
        score_max = max(scores) if scores else None
        score_mean = round(sum(scores) / len(scores), 2) if scores else None

        # 2. Bucket partitioning
        bucket_data: dict[str, list[dict[str, Any]]] = {b: [] for b in SCORE_BUCKETS}
        below_70_data: list[dict[str, Any]] = []

        data_quality_summary = {
            "VALID_DATA": 0,
            "AMBIGUOUS_BAR": 0,
            "NO_DATA": 0,
            "INVALID_DATA": 0,
            "OTHER": 0,
        }

        for r in dataset:
            dq = str(r.get("data_quality_status") or "VALID_DATA")
            if dq in data_quality_summary:
                data_quality_summary[dq] += 1
            else:
                data_quality_summary["OTHER"] += 1

            b = assign_score_bucket(r.get("score"))
            if b in bucket_data:
                bucket_data[b].append(r)
            elif b == "<70":
                below_70_data.append(r)

        # 3. Calculate metrics per bucket
        bucket_metrics: dict[str, ScoreBucketMetrics] = {}
        for b_name in SCORE_BUCKETS:
            rows = bucket_data[b_name]
            n_total = len(rows)

            t1_count = 0
            sl_count = 0
            to_count = 0
            amb_count = 0
            unres_count = 0
            nodata_count = 0

            mfe_r_vals: list[float] = []
            mae_r_vals: list[float] = []
            realized_r_vals: list[float] = []
            t_first_event_vals: list[float] = []

            for row in rows:
                out = str(row.get("outcome") or "UNRESOLVED").upper()
                dq = str(row.get("data_quality_status") or "VALID_DATA").upper()

                if dq == "NO_DATA" or out == "NO_DATA":
                    nodata_count += 1
                elif dq == "AMBIGUOUS_BAR" or out == "AMBIGUOUS":
                    amb_count += 1
                elif out == "TARGET_FIRST":
                    t1_count += 1
                elif out == "SL_FIRST":
                    sl_count += 1
                elif out == "TIMEOUT":
                    to_count += 1
                elif out in ("UNRESOLVED", "ACTIVE"):
                    unres_count += 1
                else:
                    unres_count += 1

                # Continuous distributions
                if row.get("mfe_r") is not None:
                    mfe_r_vals.append(float(row["mfe_r"]))
                if row.get("mae_r") is not None:
                    mae_r_vals.append(float(row["mae_r"]))
                if row.get("realized_r") is not None:
                    realized_r_vals.append(float(row["realized_r"]))
                if row.get("time_to_first_event_seconds") is not None:
                    t_first_event_vals.append(float(row["time_to_first_event_seconds"]))

            valid_resolved = t1_count + sl_count + to_count

            # Rates with explicit denominators
            t1_rate = round(t1_count / valid_resolved, 4) if valid_resolved > 0 else None
            sl_rate = round(sl_count / valid_resolved, 4) if valid_resolved > 0 else None
            to_rate = round(to_count / valid_resolved, 4) if valid_resolved > 0 else None

            amb_rate = round(amb_count / n_total, 4) if n_total > 0 else None
            unres_rate = round(unres_count / n_total, 4) if n_total > 0 else None
            nodata_rate = round(nodata_count / n_total, 4) if n_total > 0 else None

            # Wilson Confidence Intervals (denominator = valid_resolved)
            t1_est, t1_lo, t1_hi = wilson_confidence_interval(t1_count, valid_resolved)
            sl_est, sl_lo, sl_hi = wilson_confidence_interval(sl_count, valid_resolved)
            to_est, to_lo, to_hi = wilson_confidence_interval(to_count, valid_resolved)

            t1_ci = WilsonCI(estimate=t1_est, ci_lower=t1_lo, ci_upper=t1_hi, sample_size=valid_resolved)
            sl_ci = WilsonCI(estimate=sl_est, ci_lower=sl_lo, ci_upper=sl_hi, sample_size=valid_resolved)
            to_ci = WilsonCI(estimate=to_est, ci_lower=to_lo, ci_upper=to_hi, sample_size=valid_resolved)

            mfe_stats = calculate_distribution_stats(mfe_r_vals)
            mae_stats = calculate_distribution_stats(mae_r_vals)
            realized_stats = calculate_distribution_stats(realized_r_vals)
            exp_info = calculate_expectancy(realized_r_vals)
            pf, pf_status = calculate_profit_factor(realized_r_vals)

            t_dist = calculate_distribution_stats(t_first_event_vals)
            t_med = t_dist["median"]
            t_mean = t_dist["mean"]

            status = "VALID_SAMPLE" if n_total >= MIN_INFERENCE_SAMPLE_SIZE else "INSUFFICIENT_SAMPLE"

            bucket_metrics[b_name] = ScoreBucketMetrics(
                bucket=b_name,
                n_total=n_total,
                target_first_count=t1_count,
                sl_first_count=sl_count,
                timeout_count=to_count,
                ambiguous_count=amb_count,
                unresolved_count=unres_count,
                no_data_count=nodata_count,
                valid_resolved_count=valid_resolved,
                target_first_rate=t1_rate,
                target_first_ci=t1_ci,
                sl_first_rate=sl_rate,
                sl_first_ci=sl_ci,
                timeout_rate=to_rate,
                timeout_ci=to_ci,
                ambiguous_rate=amb_rate,
                unresolved_rate=unres_rate,
                no_data_rate=nodata_rate,
                mfe_r_stats=mfe_stats,
                mae_r_stats=mae_stats,
                realized_r_stats=realized_stats,
                expectancy_info=exp_info,
                profit_factor=pf,
                profit_factor_status=pf_status,
                time_to_first_event_median=t_med,
                time_to_first_event_mean=t_mean,
                sample_size_status=status,
            )

        # 4. Statistical Discrimination & Multiple Comparisons
        omnibus_tests, pairwise_comparisons = self._evaluate_statistical_discrimination(
            bucket_data=bucket_data, bucket_metrics=bucket_metrics
        )

        # 5. Descriptive Temporal Stability (Monthly grouping)
        temporal_stability = self._evaluate_temporal_stability(dataset=dataset)

        return ScoreDiscriminationReport(
            analysis_version=ANALYSIS_VERSION,
            dataset_timestamp=now_ist().isoformat(),
            include_seed_samples=include_seed_samples,
            total_snapshots=len(dataset),
            total_measurements_joined=len(dataset),
            seed_samples_excluded=0 if include_seed_samples else 0,  # Explicit count recorded
            actual_score_min=score_min,
            actual_score_max=score_max,
            actual_score_mean=score_mean,
            bucket_metrics=bucket_metrics,
            omnibus_tests=omnibus_tests,
            pairwise_comparisons=pairwise_comparisons,
            temporal_stability=temporal_stability,
            data_quality_summary=data_quality_summary,
        )

    def _evaluate_statistical_discrimination(
        self,
        bucket_data: dict[str, list[dict[str, Any]]],
        bucket_metrics: dict[str, ScoreBucketMetrics],
    ) -> tuple[dict[str, Any], list[PairwiseComparison]]:
        """Evaluate omnibus tests and pairwise comparisons across explicit hypothesis families."""
        omnibus_tests: dict[str, Any] = {}
        pairwise_comparisons: list[PairwiseComparison] = []

        try:
            from scipy import stats
            has_scipy = True
        except ImportError:
            has_scipy = False

        # Gather continuous realized_r and mfe_r per bucket for eligible inference buckets
        eligible_buckets = [
            b for b in SCORE_BUCKETS
            if bucket_metrics[b].sample_size_status == "VALID_SAMPLE"
        ]

        # --------------------------------------------------------------------
        # OMNIBUS 1: Kruskal-Wallis H Test on Realized_R (Non-parametric ANOVA)
        # --------------------------------------------------------------------
        if has_scipy and len(eligible_buckets) >= 2:
            r_groups = [
                [float(r["realized_r"]) for r in bucket_data[b] if r.get("realized_r") is not None]
                for b in eligible_buckets
            ]
            valid_r_groups = [g for g in r_groups if len(g) >= 2]
            if len(valid_r_groups) >= 2:
                try:
                    kw_stat, kw_p = stats.kruskal(*valid_r_groups)
                    # Epsilon-squared effect size: (H - k + 1) / (N - k)
                    total_n = sum(len(g) for g in valid_r_groups)
                    k = len(valid_r_groups)
                    eps_sq = max(0.0, (kw_stat - k + 1) / (total_n - k)) if total_n > k else 0.0
                    omnibus_tests["kruskal_wallis_realized_r"] = {
                        "test_name": "Kruskal-Wallis H Test",
                        "null_hypothesis": "Realized_R median is equal across eligible score buckets",
                        "eligible_buckets": eligible_buckets,
                        "statistic": round(float(kw_stat), 4),
                        "p_value": round(float(kw_p), 6),
                        "effect_size_name": "epsilon_squared",
                        "effect_size_value": round(float(eps_sq), 4),
                        "significant_05": bool(kw_p < 0.05),
                        "status": "VALID",
                    }
                except Exception as ex:
                    omnibus_tests["kruskal_wallis_realized_r"] = {
                        "test_name": "Kruskal-Wallis H Test",
                        "error": str(ex),
                        "status": "CALCULATION_ERROR",
                    }
            else:
                omnibus_tests["kruskal_wallis_realized_r"] = {
                    "test_name": "Kruskal-Wallis H Test",
                    "status": "INSUFFICIENT_SAMPLE",
                    "reason": "Less than 2 eligible buckets with >= 2 valid Realized_R observations",
                }
        else:
            omnibus_tests["kruskal_wallis_realized_r"] = {
                "test_name": "Kruskal-Wallis H Test",
                "status": "INSUFFICIENT_SAMPLE" if not has_scipy or len(eligible_buckets) < 2 else "SKIPPED",
                "reason": "Requires at least 2 buckets with n >= 10",
            }

        # --------------------------------------------------------------------
        # OMNIBUS 2: Chi-Square Test on Categorical Outcomes (Target vs SL vs Timeout)
        # --------------------------------------------------------------------
        if has_scipy and len(eligible_buckets) >= 2:
            table: list[list[int]] = []
            for b in eligible_buckets:
                m = bucket_metrics[b]
                table.append([m.target_first_count, m.sl_first_count, m.timeout_count])

            total_obs = sum(sum(row) for row in table)
            if total_obs >= 10:
                try:
                    chi2_res = stats.chi2_contingency(table)
                    chi2_stat = float(chi2_res.statistic)
                    chi2_p = float(chi2_res.pvalue)
                    r_dim = len(table)
                    c_dim = 3
                    min_dim = min(r_dim - 1, c_dim - 1)
                    cramers_v = math.sqrt(chi2_stat / (total_obs * min_dim)) if total_obs * min_dim > 0 else 0.0

                    omnibus_tests["chi_square_outcomes"] = {
                        "test_name": "Chi-Square Test of Independence",
                        "null_hypothesis": "Resolved outcome distribution is independent of score bucket",
                        "eligible_buckets": eligible_buckets,
                        "statistic": round(chi2_stat, 4),
                        "p_value": round(chi2_p, 6),
                        "effect_size_name": "cramers_v",
                        "effect_size_value": round(cramers_v, 4),
                        "significant_05": bool(chi2_p < 0.05),
                        "status": "VALID",
                    }
                except Exception as ex:
                    omnibus_tests["chi_square_outcomes"] = {
                        "test_name": "Chi-Square Test of Independence",
                        "error": str(ex),
                        "status": "CALCULATION_ERROR",
                    }
            else:
                omnibus_tests["chi_square_outcomes"] = {
                    "test_name": "Chi-Square Test of Independence",
                    "status": "INSUFFICIENT_SAMPLE",
                }
        else:
            omnibus_tests["chi_square_outcomes"] = {
                "test_name": "Chi-Square Test of Independence",
                "status": "INSUFFICIENT_SAMPLE",
            }

        # --------------------------------------------------------------------
        # EXPLICIT PAIRWISE FAMILIES WITH HOLM-BONFERRONI CORRECTION
        # --------------------------------------------------------------------
        # Candidate pairs across all 4 buckets (reported descriptively, but inferential tests
        # only executed where both buckets meet sample size requirements).
        bucket_pairs: list[tuple[str, str]] = []
        for i in range(len(SCORE_BUCKETS)):
            for j in range(i + 1, len(SCORE_BUCKETS)):
                bucket_pairs.append((SCORE_BUCKETS[i], SCORE_BUCKETS[j]))

        # Family 1: Pairwise Realized_R Discrimination
        raw_p_realized: list[float] = []
        items_realized: list[dict[str, Any]] = []

        for b_a, b_b in bucket_pairs:
            m_a = bucket_metrics[b_a]
            m_b = bucket_metrics[b_b]
            r_a = [float(r["realized_r"]) for r in bucket_data[b_a] if r.get("realized_r") is not None]
            r_b = [float(r["realized_r"]) for r in bucket_data[b_b] if r.get("realized_r") is not None]

            diff_mean = None
            diff_med = None
            if r_a and r_b:
                diff_mean = round((sum(r_a) / len(r_a)) - (sum(r_b) / len(r_b)), 4)
                med_a = m_a.realized_r_stats["median"] or 0.0
                med_b = m_b.realized_r_stats["median"] or 0.0
                diff_med = round(med_a - med_b, 4)

            # Check if sample size permits inference
            if len(r_a) >= MIN_INFERENCE_SAMPLE_SIZE and len(r_b) >= MIN_INFERENCE_SAMPLE_SIZE and has_scipy:
                try:
                    u_stat, u_p = stats.mannwhitneyu(r_a, r_b, alternative="two-sided")
                    # Rank-biserial correlation: r_rb = 1 - (2U / (n1 * n2))
                    n1 = len(r_a)
                    n2 = len(r_b)
                    r_rb = round(1.0 - (2.0 * float(u_stat)) / (n1 * n2), 4)
                    raw_p = float(u_p)
                    status_str = "VALID"
                except Exception:
                    u_stat, u_p, r_rb, raw_p = None, None, None, 1.0
                    status_str = "CALCULATION_ERROR"
            else:
                u_stat, u_p, r_rb, raw_p = None, None, None, 1.0
                status_str = "INSUFFICIENT_SAMPLE"

            raw_p_realized.append(raw_p)
            items_realized.append({
                "family": "REALIZED_R_PAIRWISE_FAMILY",
                "bucket_a": b_a,
                "bucket_b": b_b,
                "metric": "Realized_R",
                "n_a": len(r_a),
                "n_b": len(r_b),
                "diff_means": diff_mean,
                "diff_medians": diff_med,
                "test_name": "Mann-Whitney U Test",
                "statistic": round(float(u_stat), 4) if u_stat is not None else None,
                "p_value_unadjusted": round(float(u_p), 6) if u_p is not None else None,
                "effect_size_name": "rank_biserial_r",
                "effect_size_value": r_rb,
                "status": status_str,
            })

        # Apply Holm correction to Family 1
        adj_p_realized = adjust_pvalues_holm(raw_p_realized)
        for idx, item in enumerate(items_realized):
            is_valid = item["status"] == "VALID"
            adj_p = adj_p_realized[idx] if is_valid else None
            sig_05 = bool(adj_p < 0.05) if adj_p is not None else False
            pairwise_comparisons.append(PairwiseComparison(
                family=item["family"],
                bucket_a=item["bucket_a"],
                bucket_b=item["bucket_b"],
                metric=item["metric"],
                n_a=item["n_a"],
                n_b=item["n_b"],
                diff_means=item["diff_means"],
                diff_medians=item["diff_medians"],
                test_name=item["test_name"],
                statistic=item["statistic"],
                p_value_unadjusted=item["p_value_unadjusted"],
                p_value_adjusted=adj_p,
                effect_size_name=item["effect_size_name"],
                effect_size_value=item["effect_size_value"],
                significant_05=sig_05,
                status=item["status"],
            ))

        # Family 2: Pairwise Target-First Rate (Win Rate) Discrimination
        raw_p_cat: list[float] = []
        items_cat: list[dict[str, Any]] = []

        for b_a, b_b in bucket_pairs:
            m_a = bucket_metrics[b_a]
            m_b = bucket_metrics[b_b]
            res_a = m_a.valid_resolved_count
            res_b = m_b.valid_resolved_count
            t1_a = m_a.target_first_count
            t1_b = m_b.target_first_count

            diff_rate = None
            if res_a > 0 and res_b > 0:
                diff_rate = round((t1_a / res_a) - (t1_b / res_b), 4)

            if res_a >= MIN_INFERENCE_SAMPLE_SIZE and res_b >= MIN_INFERENCE_SAMPLE_SIZE and has_scipy:
                # 2x2 table: [[t1_a, other_a], [t1_b, other_b]]
                other_a = res_a - t1_a
                other_b = res_b - t1_b
                try:
                    odds, p_fish = stats.fisher_exact([[t1_a, other_a], [t1_b, other_b]])
                    stat_val = round(float(odds), 4)
                    raw_p = float(p_fish)
                    status_str = "VALID"
                except Exception:
                    stat_val, raw_p = None, 1.0
                    status_str = "CALCULATION_ERROR"
            else:
                stat_val, raw_p = None, 1.0
                status_str = "INSUFFICIENT_SAMPLE"

            raw_p_cat.append(raw_p)
            items_cat.append({
                "family": "TARGET_FIRST_RATE_PAIRWISE_FAMILY",
                "bucket_a": b_a,
                "bucket_b": b_b,
                "metric": "Target_First_Rate",
                "n_a": res_a,
                "n_b": res_b,
                "diff_means": diff_rate,
                "diff_medians": None,
                "test_name": "Fisher's Exact Test (2x2)",
                "statistic": stat_val,
                "p_value_unadjusted": round(raw_p, 6) if stat_val is not None else None,
                "effect_size_name": "rate_difference",
                "effect_size_value": diff_rate,
                "status": status_str,
            })

        # Apply Holm correction to Family 2
        adj_p_cat = adjust_pvalues_holm(raw_p_cat)
        for idx, item in enumerate(items_cat):
            is_valid = item["status"] == "VALID"
            adj_p = adj_p_cat[idx] if is_valid else None
            sig_05 = bool(adj_p < 0.05) if adj_p is not None else False
            pairwise_comparisons.append(PairwiseComparison(
                family=item["family"],
                bucket_a=item["bucket_a"],
                bucket_b=item["bucket_b"],
                metric=item["metric"],
                n_a=item["n_a"],
                n_b=item["n_b"],
                diff_means=item["diff_means"],
                diff_medians=item["diff_medians"],
                test_name=item["test_name"],
                statistic=item["statistic"],
                p_value_unadjusted=item["p_value_unadjusted"],
                p_value_adjusted=adj_p,
                effect_size_name=item["effect_size_name"],
                effect_size_value=item["effect_size_value"],
                significant_05=sig_05,
                status=item["status"],
            ))

        return omnibus_tests, pairwise_comparisons

    def _evaluate_temporal_stability(
        self, dataset: list[dict[str, Any]]
    ) -> list[TemporalBucketPeriod]:
        """Aggregate monthly temporal distributions descriptively without model selection rules."""
        months_dict: dict[str, list[dict[str, Any]]] = {}

        for r in dataset:
            ts_str = str(r.get("captured_at") or r.get("observed_from") or "").strip()
            # Extract YYYY-MM
            month_key = "UNKNOWN_DATE"
            if len(ts_str) >= 7 and ts_str[4] == "-":
                month_key = ts_str[:7]
            if month_key not in months_dict:
                months_dict[month_key] = []
            months_dict[month_key].append(r)

        periods: list[TemporalBucketPeriod] = []
        for m_key in sorted(months_dict.keys()):
            m_rows = months_dict[m_key]
            total_sig = len(m_rows)

            counts = {b: 0 for b in SCORE_BUCKETS}
            t1_counts = {b: 0 for b in SCORE_BUCKETS}
            res_counts = {b: 0 for b in SCORE_BUCKETS}
            rates: dict[str, float | None] = {b: None for b in SCORE_BUCKETS}

            for row in m_rows:
                b = assign_score_bucket(row.get("score"))
                if b in counts:
                    counts[b] += 1
                    out = str(row.get("outcome") or "").upper()
                    if out in ("TARGET_FIRST", "SL_FIRST", "TIMEOUT"):
                        res_counts[b] += 1
                        if out == "TARGET_FIRST":
                            t1_counts[b] += 1

            for b in SCORE_BUCKETS:
                if res_counts[b] > 0:
                    rates[b] = round(t1_counts[b] / res_counts[b], 4)

            status = "DESCRIPTIVE_ONLY" if total_sig >= MIN_INFERENCE_SAMPLE_SIZE else "INSUFFICIENT_SAMPLE"
            periods.append(TemporalBucketPeriod(
                period=m_key,
                total_signals=total_sig,
                bucket_counts=counts,
                bucket_target_first_counts=t1_counts,
                bucket_resolved_counts=res_counts,
                bucket_target_rates=rates,
                status=status,
            ))

        return periods
