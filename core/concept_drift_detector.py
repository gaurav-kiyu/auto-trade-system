"""
Concept Drift Detector (Phase C) - detects when the ML model's feature
distribution has shifted relative to the training distribution.

Two complementary statistics are computed:

  PSI (Population Stability Index)
      Measures the shift in a single feature's distribution between a
      reference window (training era) and a recent window.
      PSI < 0.10 → no drift
      PSI 0.10-0.25 → moderate drift (warn)
      PSI > 0.25 → significant drift (alert)

  KS (Kolmogorov-Smirnov statistic)
      Maximum absolute difference between two empirical CDFs.
      KS > 0.20 → drift warning (p-value not computed - fast path).

The detector reads the ``ml_predictions`` table (written by ml_performance
tracker) and the ``journal`` table (training data) to build reference and
recent windows.  It is entirely read-only and non-blocking.

Public API
----------
    compute_psi(reference, recent, n_bins=10) → float

    compute_ks(reference, recent) → float

    detect_drift(feature_name, *, ref_db, recent_db, ref_days, recent_days,
                 psi_warn, psi_alert, ks_warn) → DriftResult

    detect_all_features(*, ref_db, recent_db, ...) → dict[str, DriftResult]

    format_drift_report(results) → str

Config keys (all optional - safe defaults built in)
---------------------------------------------------
  drift_detector_enabled   : bool  default true
  drift_ref_days           : int   default 90   (training reference window)
  drift_recent_days        : int   default 14   (recent window)
  drift_psi_warn           : float default 0.10
  drift_psi_alert          : float default 0.25
  drift_ks_warn            : float default 0.20
  drift_db_path            : str   default "ml_tracker.db"
  drift_auto_retrain       : bool  default False  (auto-trigger retraining on ALERT)
  drift_retrain_callback   : callable or None     (function to call for retraining)
  drift_sla_max_alert_periods : int default 3     (max consecutive ALERT periods before escalation)
  drift_sla_callback       : callable or None     (function to call for SLA breach)
"""
from __future__ import annotations

import logging
import math
import sqlite3
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.db_utils import get_connection

_log = logging.getLogger(__name__)

_DEFAULT_DB          = "ml_tracker.db"
_DEFAULT_REF_DAYS    = 90
_DEFAULT_RECENT_DAYS = 14
_DEFAULT_PSI_WARN    = 0.10
_DEFAULT_PSI_ALERT   = 0.25
_DEFAULT_KS_WARN     = 0.20
_DEFAULT_SLA_MAX_ALERT_PERIODS = 3


# ── Result dataclass ──────────────────────────────────────────────────────────

@dataclass(frozen=True)
class DriftResult:
    feature:    str
    psi:        float
    ks:         float
    ref_n:      int
    recent_n:   int
    status:     str    # "OK" | "WARN" | "ALERT"
    message:    str


@dataclass
class DriftSLAReport:
    """SLA monitoring report for concept drift."""
    total_features: int = 0
    alert_count: int = 0
    warn_count: int = 0
    ok_count: int = 0
    consecutive_alert_periods: int = 0
    sla_breached: bool = False
    last_retrain_ts: float | None = None
    hours_since_retrain: float = 0.0
    retrain_recommended: bool = False
    summary: str = ""


# ── Core statistics ───────────────────────────────────────────────────────────

def compute_psi(
    reference: list[float],
    recent:    list[float],
    n_bins:    int = 10,
) -> float:
    """
    Compute the Population Stability Index between two numeric samples.

    PSI = Σ (recent_pct − ref_pct) × ln(recent_pct / ref_pct)

    Args:
        reference : Values from the reference (training) window.
        recent    : Values from the recent (monitoring) window.
        n_bins    : Number of equal-width bins built from the reference range.

    Returns:
        PSI value ≥ 0.  Returns 0.0 if either sample is empty.
    """
    if not reference or not recent:
        return 0.0

    lo = min(reference)
    hi = max(reference)
    if hi == lo:
        # Constant feature - count fraction outside single value in recent
        ref_match    = sum(1 for v in reference if v == lo) / len(reference)
        recent_match = sum(1 for v in recent    if v == lo) / len(recent)
        diff = abs(recent_match - ref_match)
        return diff  # simplified PSI for degenerate case

    width = (hi - lo) / n_bins
    ref_n    = len(reference)
    recent_n = len(recent)

    psi = 0.0
    for b in range(n_bins):
        edge_lo = lo + b * width
        edge_hi = lo + (b + 1) * width if b < n_bins - 1 else hi + 1e-9

        ref_cnt    = sum(1 for v in reference if edge_lo <= v < edge_hi)
        recent_cnt = sum(1 for v in recent    if edge_lo <= v < edge_hi)

        # Smooth with ε to avoid log(0)
        ref_pct    = max(ref_cnt    / ref_n,    1e-4)
        recent_pct = max(recent_cnt / recent_n, 1e-4)

        psi += (recent_pct - ref_pct) * math.log(recent_pct / ref_pct)

    return round(max(0.0, psi), 6)


def compute_ks(reference: list[float], recent: list[float]) -> float:
    """
    Compute the two-sample KS statistic (max |CDF_ref − CDF_recent|).

    Args:
        reference : Values from the reference window.
        recent    : Values from the recent window.

    Returns:
        KS statistic in [0, 1].  Returns 0.0 if either sample is empty.
    """
    if not reference or not recent:
        return 0.0

    all_vals = sorted(set(reference + recent))
    ref_n    = len(reference)
    recent_n = len(recent)

    max_diff = 0.0
    for v in all_vals:
        cdf_ref    = sum(1 for x in reference if x <= v) / ref_n
        cdf_recent = sum(1 for x in recent    if x <= v) / recent_n
        max_diff = max(max_diff, abs(cdf_ref - cdf_recent))

    return round(max_diff, 6)


# ── Data loader ───────────────────────────────────────────────────────────────

def _load_feature_values(
    feature: str,
    db_path: str,
    since_ts: float,
    until_ts: float,
) -> list[float]:
    """
    Load per-prediction SHAP-keyed feature values from ml_predictions.shap_json.

    Returns a list of raw float values (one per prediction in the window).
    Falls back to empty list on any error.
    """
    p = Path(db_path)
    if not p.is_file():
        return []
    try:
        import json
        conn = get_connection(p, timeout=5, row_factory=False)
        try:
            rows = conn.execute(
                "SELECT shap_json FROM ml_predictions "
                "WHERE ts >= ? AND ts < ? AND shap_json IS NOT NULL AND shap_json != '{}'",
                (since_ts, until_ts),
            ).fetchall()
        finally:
            conn.close()
        vals: list[float] = []
        for (shap_str,) in rows:
            try:
                d = json.loads(shap_str)
                if feature in d:
                    vals.append(float(d[feature]))
            except (json.JSONDecodeError, ValueError, TypeError, KeyError):
                continue
        return vals
    except (sqlite3.Error, OSError, json.JSONDecodeError) as exc:
        _log.debug("[DRIFT] _load_feature_values failed for %s: %s", feature, exc)
        return []


# ── Public detection API ──────────────────────────────────────────────────────

def detect_drift(
    feature: str,
    *,
    db_path:     str   = _DEFAULT_DB,
    ref_days:    int   = _DEFAULT_REF_DAYS,
    recent_days: int   = _DEFAULT_RECENT_DAYS,
    psi_warn:    float = _DEFAULT_PSI_WARN,
    psi_alert:   float = _DEFAULT_PSI_ALERT,
    ks_warn:     float = _DEFAULT_KS_WARN,
    n_bins:      int   = 10,
    _now:        float | None = None,
) -> DriftResult:
    """
    Run drift detection for a single feature.

    The reference window is the period [now − ref_days, now − recent_days].
    The recent window is [now − recent_days, now].

    Args:
        feature     : Feature name (must match keys in shap_json column).
        db_path     : Path to ml_tracker.db.
        ref_days    : Look-back days for reference distribution.
        recent_days : Look-back days for recent distribution.
        psi_warn    : PSI threshold for WARN status.
        psi_alert   : PSI threshold for ALERT status.
        ks_warn     : KS threshold for WARN status.
        n_bins      : Bins for PSI computation.
        _now        : Override current time (for testing).

    Returns:
        DriftResult with status "OK" | "WARN" | "ALERT".
    """
    now       = _now if _now is not None else time.time()
    ref_start = now - ref_days    * 86400
    ref_end   = now - recent_days * 86400
    rec_start = ref_end
    rec_end   = now

    ref_vals    = _load_feature_values(feature, db_path, ref_start, ref_end)
    recent_vals = _load_feature_values(feature, db_path, rec_start, rec_end)

    if not ref_vals or not recent_vals:
        return DriftResult(
            feature=feature, psi=0.0, ks=0.0,
            ref_n=len(ref_vals), recent_n=len(recent_vals),
            status="OK",
            message=f"Insufficient data (ref={len(ref_vals)}, recent={len(recent_vals)})",
        )

    psi = compute_psi(ref_vals, recent_vals, n_bins=n_bins)
    ks  = compute_ks(ref_vals, recent_vals)

    if psi >= psi_alert:
        status = "ALERT"
        msg = f"PSI={psi:.4f} ≥ {psi_alert} (significant drift)"
    elif psi >= psi_warn or ks >= ks_warn:
        status = "WARN"
        msg = f"PSI={psi:.4f}, KS={ks:.4f} - moderate drift"
    else:
        status = "OK"
        msg = f"PSI={psi:.4f}, KS={ks:.4f} - stable"

    return DriftResult(
        feature=feature, psi=psi, ks=ks,
        ref_n=len(ref_vals), recent_n=len(recent_vals),
        status=status, message=msg,
    )


def detect_all_features(
    features: list[str] | None = None,
    *,
    db_path:     str   = _DEFAULT_DB,
    ref_days:    int   = _DEFAULT_REF_DAYS,
    recent_days: int   = _DEFAULT_RECENT_DAYS,
    psi_warn:    float = _DEFAULT_PSI_WARN,
    psi_alert:   float = _DEFAULT_PSI_ALERT,
    ks_warn:     float = _DEFAULT_KS_WARN,
    _now:        float | None = None,
) -> dict[str, DriftResult]:
    """
    Run drift detection on all specified features (or all FEATURE_COLS by default).

    Returns:
        {feature_name: DriftResult}  - non-empty even if all are "OK".
    """
    if features is None:
        try:
            from core.ml_classifier import FEATURE_COLS
            features = list(FEATURE_COLS)
        except (ValueError, TypeError, KeyError, OSError, sqlite3.Error):
            features = []

    results: dict[str, DriftResult] = {}
    for feat in features:
        try:
            results[feat] = detect_drift(
                feat,
                db_path=db_path,
                ref_days=ref_days,
                recent_days=recent_days,
                psi_warn=psi_warn,
                psi_alert=psi_alert,
                ks_warn=ks_warn,
                _now=_now,
            )
        except (ValueError, TypeError, KeyError, OSError, sqlite3.Error) as exc:
            _log.debug("[DRIFT] detect_drift failed for %s: %s", feat, exc)
            results[feat] = DriftResult(
                feature=feat, psi=0.0, ks=0.0, ref_n=0, recent_n=0,
                status="OK", message=f"Error: {exc}",
            )
    return results


# ── Auto-Retraining & SLA Monitoring (new) ──────────────────────────────────

class DriftMonitor:
    """
    Monitors concept drift over time and triggers auto-retraining when
    drift exceeds thresholds. Tracks consecutive alert periods for SLA
    compliance and provides retraining recommendations.

    Thread-safe background monitor that checks drift on configurable intervals.
    """

    def __init__(
        self,
        cfg: dict[str, Any] | None = None,
        retrain_callback: Callable[[str], None] | None = None,
        sla_callback: Callable[[str], None] | None = None,
    ):
        self._cfg = cfg or {}
        self._retrain_callback = retrain_callback
        self._sla_callback = sla_callback
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._background_thread: threading.Thread | None = None

        self._auto_retrain = bool(self._cfg.get("drift_auto_retrain", False))
        self._sla_max_alert = int(self._cfg.get("drift_sla_max_alert_periods", _DEFAULT_SLA_MAX_ALERT_PERIODS))
        self._db_path = str(self._cfg.get("drift_db_path", _DEFAULT_DB))
        self._ref_days = int(self._cfg.get("drift_ref_days", _DEFAULT_REF_DAYS))
        self._recent_days = int(self._cfg.get("drift_recent_days", _DEFAULT_RECENT_DAYS))
        self._check_interval = int(self._cfg.get("drift_check_interval_sec", 3600))

        # State
        self._consecutive_alert_periods = 0
        self._last_check_ts: float | None = None
        self._last_results: dict[str, DriftResult] | None = None
        self._last_retrain_ts: float | None = self._load_last_retrain_ts()
        self._alert_history: list[dict[str, Any]] = []

    def _load_last_retrain_ts(self) -> float | None:
        """Load last retraining timestamp from DB or config."""
        ts = self._cfg.get("drift_last_retrain_ts", None)
        if ts is not None:
            return float(ts)
        return None

    @property
    def enabled(self) -> bool:
        return bool(self._cfg.get("drift_detector_enabled", True))

    def run_check(self) -> DriftSLAReport:
        """Run a drift detection check and evaluate SLA status."""
        now = time.time()
        self._last_check_ts = now

        results = detect_all_features(
            db_path=self._db_path,
            ref_days=self._ref_days,
            recent_days=self._recent_days,
            _now=now,
        )
        self._last_results = results

        n_alert = sum(1 for r in results.values() if r.status == "ALERT")
        n_warn = sum(1 for r in results.values() if r.status == "WARN")
        n_ok = sum(1 for r in results.values() if r.status == "OK")

        with self._lock:
            if n_alert > 0:
                self._consecutive_alert_periods += 1
            else:
                self._consecutive_alert_periods = 0

        sla_breached = self._consecutive_alert_periods >= self._sla_max_alert

        # Auto-retrain logic
        retrain_needed = n_alert > 0 and self._auto_retrain
        if retrain_needed and self._retrain_callback:
            try:
                alert_features = [f for f, r in results.items() if r.status == "ALERT"]
                self._retrain_callback(",".join(alert_features))
                self._last_retrain_ts = time.time()
                _log.info("[DRIFT-MONITOR] Auto-retrain triggered for features: %s", alert_features)
            except Exception as exc:
                _log.warning("[DRIFT-MONITOR] Auto-retrain callback failed: %s", exc)

        # SLA breach escalation
        if sla_breached and self._sla_callback:
            try:
                msg = (
                    f"[DRIFT-SLA] Drift SLA BREACHED: {n_alert} feature(s) in ALERT "
                    f"for {self._consecutive_alert_periods} consecutive periods "
                    f"(max allowed: {self._sla_max_alert})"
                )
                self._sla_callback(msg)
                # Record SLA breach in history
                self._alert_history.append({
                    "ts": now,
                    "event": "SLA_BREACH",
                    "consecutive_alert_periods": self._consecutive_alert_periods,
                    "alert_features": [f for f, r in results.items() if r.status == "ALERT"],
                })
            except Exception as exc:
                _log.warning("[DRIFT-MONITOR] SLA callback failed: %s", exc)

        hours_since = 0.0
        if self._last_retrain_ts:
            hours_since = (now - self._last_retrain_ts) / 3600

        retrain_recommended = n_alert > 0 or hours_since > 168  # >1 week

        report = DriftSLAReport(
            total_features=len(results),
            alert_count=n_alert,
            warn_count=n_warn,
            ok_count=n_ok,
            consecutive_alert_periods=self._consecutive_alert_periods,
            sla_breached=sla_breached,
            last_retrain_ts=self._last_retrain_ts,
            hours_since_retrain=round(hours_since, 1),
            retrain_recommended=retrain_recommended,
            summary=(
                f"Drift Monitor: {len(results)} features, {n_alert} ALERT, {n_warn} WARN, {n_ok} OK. "
                f"Consecutive ALERTs: {self._consecutive_alert_periods}/{self._sla_max_alert}. "
                f"Retrain: {'RECOMMENDED' if retrain_recommended else 'NOT NEEDED'}"
            ),
        )
        return report

    def get_sla_status(self) -> dict[str, Any]:
        """Get SLA monitoring status snapshot."""
        with self._lock:
            return {
                "enabled": self.enabled,
                "auto_retrain": self._auto_retrain,
                "consecutive_alert_periods": self._consecutive_alert_periods,
                "sla_max_alert_periods": self._sla_max_alert,
                "sla_breached": self._consecutive_alert_periods >= self._sla_max_alert,
                "last_check_ts": self._last_check_ts,
                "last_retrain_ts": self._last_retrain_ts,
                "alert_history_count": len(self._alert_history),
                "check_interval_sec": self._check_interval,
            }

    def start_background_monitor(self) -> threading.Thread:
        """Start background drift monitoring thread."""
        if self._background_thread and self._background_thread.is_alive():
            return self._background_thread

        self._stop_event.clear()

        def _loop():
            _log.info("[DRIFT-MONITOR] Background monitor started (interval=%ds)", self._check_interval)
            while not self._stop_event.is_set():
                try:
                    if self.enabled:
                        report = self.run_check()
                        _log.info("[DRIFT-MONITOR] %s", report.summary)
                except Exception as exc:
                    _log.warning("[DRIFT-MONITOR] Check failed: %s", exc)
                self._stop_event.wait(self._check_interval)

        self._background_thread = threading.Thread(target=_loop, daemon=True,
                                                    name="drift-monitor")
        self._background_thread.start()
        return self._background_thread

    def stop_background_monitor(self) -> None:
        """Stop background monitor."""
        self._stop_event.set()
        _log.info("[DRIFT-MONITOR] Background monitor stopped")


# ── Report formatter ──────────────────────────────────────────────────────────

def format_drift_report(results: dict[str, DriftResult]) -> str:
    """
    Return a compact multi-line drift report suitable for console / Telegram.

    Features with ALERT are listed first, then WARN, then OK.
    """
    if not results:
        return "Concept Drift Detector: no features analysed."

    order = {"ALERT": 0, "WARN": 1, "OK": 2}
    sorted_items = sorted(results.items(), key=lambda kv: order.get(kv[1].status, 3))

    n_alert = sum(1 for r in results.values() if r.status == "ALERT")
    n_warn  = sum(1 for r in results.values() if r.status == "WARN")
    n_ok    = sum(1 for r in results.values() if r.status == "OK")

    lines = [
        f"Concept Drift Report - {len(results)} features "
        f"[ALERT:{n_alert} WARN:{n_warn} OK:{n_ok}]"
    ]
    for feat, r in sorted_items:
        icon = "!!" if r.status == "ALERT" else "~~" if r.status == "WARN" else "OK"
        lines.append(
            f"  [{icon}] {feat:<22} PSI={r.psi:.4f}  KS={r.ks:.4f}  "
            f"ref={r.ref_n}  recent={r.recent_n}"
        )
    return "\n".join(lines)


__all__ = [
    "DriftMonitor",
    "DriftResult",
    "DriftSLAReport",
    "compute_ks",
    "compute_psi",
    "detect_all_features",
    "detect_drift",
    "format_drift_report",
]

