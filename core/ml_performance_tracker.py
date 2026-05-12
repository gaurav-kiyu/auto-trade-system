"""
ML Performance Tracker (Phase B) — tracks prediction quality over time.

Records each ML prediction alongside the actual trade outcome, then computes:
  - Brier score (mean squared calibration error)
  - Calibration curve (predicted vs actual win rate per prob bin)
  - Feature SHAP trend (average |SHAP| per feature over the last N trades)

All functions are non-blocking; every path catches exceptions and returns a
safe fallback.  The SQLite DB is created on first write; the module is a no-op
if the DB does not yet exist when reading.

Public API
----------
    record_prediction(trade_id, prob, *, actual, shap_json, db_path)
        → bool

    update_outcome(trade_id, actual_outcome, *, db_path)
        → bool

    compute_brier_score(*, db_path, days) → float | None

    compute_calibration(*, n_bins, db_path) → list[dict]

    get_feature_importance_trend(*, n_last, db_path) → dict[str, float]

    format_tracker_summary(*, db_path) → str

Config keys (all optional — safe defaults built in)
---------------------------------------------------
  ml_tracker_db_path : str  default "ml_tracker.db"
  ml_tracker_enabled : bool default true
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)

_DEFAULT_DB = "ml_tracker.db"

# ── Schema ────────────────────────────────────────────────────────────────────

_DDL = """
CREATE TABLE IF NOT EXISTS ml_predictions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts              REAL    NOT NULL,
    trade_id        TEXT    NOT NULL,
    predicted_prob  REAL    NOT NULL,
    actual_outcome  INTEGER,          -- 1=winner 0=loser NULL=pending
    shap_json       TEXT    DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS ix_mlpred_ts       ON ml_predictions (ts);
CREATE INDEX IF NOT EXISTS ix_mlpred_trade_id ON ml_predictions (trade_id);
"""


def _get_conn(db_path: str) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    for stmt in _DDL.strip().split(";"):
        s = stmt.strip()
        if s:
            conn.execute(s)
    conn.commit()
    return conn


# ── Write API ─────────────────────────────────────────────────────────────────

def record_prediction(
    trade_id: str,
    prob: float,
    *,
    actual: int | None = None,
    shap_json: str = "{}",
    db_path: str = _DEFAULT_DB,
) -> bool:
    """
    Persist a single ML prediction (and optional actual outcome).

    Args:
        trade_id   : Unique trade identifier (from trades.db id or ts string).
        prob       : Predicted win probability [0, 1].
        actual     : 1 = winner, 0 = loser, None = result not yet known.
        shap_json  : JSON string from ``ml_classifier.shap_to_json()``.
        db_path    : Path to ml_tracker.db.

    Returns:
        True if row written, False on error.
    """
    try:
        conn = _get_conn(db_path)
        try:
            conn.execute(
                """
                INSERT INTO ml_predictions
                    (ts, trade_id, predicted_prob, actual_outcome, shap_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (time.time(), str(trade_id), float(prob),
                 int(actual) if actual is not None else None,
                 str(shap_json or "{}")),
            )
            conn.commit()
            return True
        finally:
            conn.close()
    except Exception as exc:
        _log.debug("[MLT] record_prediction failed: %s", exc)
        return False


def update_outcome(
    trade_id: str,
    actual_outcome: int,
    *,
    db_path: str = _DEFAULT_DB,
) -> bool:
    """
    Fill in the actual_outcome for a previously recorded trade_id.

    Idempotent: updates the most recent row for trade_id if multiple exist.

    Returns:
        True if at least one row was updated, False otherwise.
    """
    p = Path(db_path)
    if not p.is_file():
        return False
    try:
        conn = sqlite3.connect(str(p), check_same_thread=False, timeout=10)
        try:
            cur = conn.execute(
                """
                UPDATE ml_predictions
                SET actual_outcome = ?
                WHERE trade_id = ?
                  AND actual_outcome IS NULL
                """,
                (int(actual_outcome), str(trade_id)),
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()
    except Exception as exc:
        _log.debug("[MLT] update_outcome failed: %s", exc)
        return False


# ── Analytics ─────────────────────────────────────────────────────────────────

def compute_brier_score(
    *,
    db_path: str = _DEFAULT_DB,
    days: int = 0,
) -> float | None:
    """
    Compute the Brier score over completed predictions.

    Brier score = mean((prob − actual)²).  Lower is better; 0.25 = coin-flip.

    Args:
        db_path : Path to ml_tracker.db.
        days    : Look-back window (0 = all time).

    Returns:
        Float in [0, 1], or None if no completed predictions exist.
    """
    p = Path(db_path)
    if not p.is_file():
        return None
    try:
        conn = sqlite3.connect(str(p), check_same_thread=False, timeout=5)
        try:
            params: list[Any] = []
            where = "actual_outcome IS NOT NULL"
            if days and days > 0:
                cutoff = time.time() - days * 86400
                where += " AND ts >= ?"
                params.append(cutoff)
            rows = conn.execute(
                f"SELECT predicted_prob, actual_outcome FROM ml_predictions WHERE {where}",
                params,
            ).fetchall()
        finally:
            conn.close()
        if not rows:
            return None
        total = sum((float(r[0]) - float(r[1])) ** 2 for r in rows)
        return round(total / len(rows), 6)
    except Exception as exc:
        _log.debug("[MLT] compute_brier_score failed: %s", exc)
        return None


def compute_calibration(
    *,
    n_bins: int = 10,
    db_path: str = _DEFAULT_DB,
) -> list[dict]:
    """
    Compute a calibration curve: predicted probability vs actual win rate.

    Returns a list of dicts, one per bin:
        {
          "bin_low": float,     # lower edge of prob bin
          "bin_mid": float,     # midpoint
          "predicted_mean": float,  # average predicted prob in bin
          "actual_rate": float,     # fraction that were actual winners
          "count": int,
        }

    Bins with no samples are omitted.
    Returns [] if no completed predictions exist.
    """
    p = Path(db_path)
    if not p.is_file():
        return []
    try:
        conn = sqlite3.connect(str(p), check_same_thread=False, timeout=5)
        try:
            rows = conn.execute(
                "SELECT predicted_prob, actual_outcome FROM ml_predictions "
                "WHERE actual_outcome IS NOT NULL"
            ).fetchall()
        finally:
            conn.close()
        if not rows:
            return []

        bins: list[dict] = []
        bin_width = 1.0 / n_bins
        for b in range(n_bins):
            lo = b * bin_width
            hi = lo + bin_width
            in_bin = [(float(r[0]), int(r[1])) for r in rows if lo <= float(r[0]) < hi]
            if not in_bin:
                continue
            probs, actuals = zip(*in_bin)
            bins.append({
                "bin_low":       round(lo, 4),
                "bin_mid":       round(lo + bin_width / 2, 4),
                "predicted_mean": round(sum(probs) / len(probs), 4),
                "actual_rate":   round(sum(actuals) / len(actuals), 4),
                "count":         len(in_bin),
            })
        return bins
    except Exception as exc:
        _log.debug("[MLT] compute_calibration failed: %s", exc)
        return []


def get_feature_importance_trend(
    *,
    n_last: int = 100,
    db_path: str = _DEFAULT_DB,
) -> dict[str, float]:
    """
    Return the mean absolute SHAP value per feature over the last N predictions.

    This serves as a recency-weighted feature importance signal — features that
    the model has been using heavily for recent decisions rank higher.

    Returns:
        {feature_name: mean_abs_shap}  sorted by value descending.
        Empty dict if no SHAP data exists.
    """
    p = Path(db_path)
    if not p.is_file():
        return {}
    try:
        conn = sqlite3.connect(str(p), check_same_thread=False, timeout=5)
        try:
            rows = conn.execute(
                "SELECT shap_json FROM ml_predictions "
                "WHERE shap_json IS NOT NULL AND shap_json != '{}' "
                "ORDER BY ts DESC LIMIT ?",
                (n_last,),
            ).fetchall()
        finally:
            conn.close()

        if not rows:
            return {}

        acc: dict[str, list[float]] = {}
        for (shap_str,) in rows:
            try:
                vals: dict = json.loads(shap_str)
                for feat, v in vals.items():
                    acc.setdefault(feat, []).append(abs(float(v)))
            except Exception:
                continue

        if not acc:
            return {}

        result = {feat: round(sum(vs) / len(vs), 6) for feat, vs in acc.items()}
        return dict(sorted(result.items(), key=lambda kv: kv[1], reverse=True))
    except Exception as exc:
        _log.debug("[MLT] get_feature_importance_trend failed: %s", exc)
        return {}


# ── Summary formatter ─────────────────────────────────────────────────────────

def format_tracker_summary(*, db_path: str = _DEFAULT_DB) -> str:
    """
    Return a human-readable multi-line summary of ML prediction quality.

    Suitable for console output, Telegram messages, and PDF reports.
    """
    p = Path(db_path)
    if not p.is_file():
        return "ML Tracker: no data (db not found)"

    try:
        conn = sqlite3.connect(str(p), check_same_thread=False, timeout=5)
        conn.row_factory = sqlite3.Row
        try:
            total_row = conn.execute(
                "SELECT COUNT(*) as n, "
                "SUM(CASE WHEN actual_outcome IS NOT NULL THEN 1 ELSE 0 END) as completed "
                "FROM ml_predictions"
            ).fetchone()
            n_total     = int(total_row["n"] or 0)
            n_completed = int(total_row["completed"] or 0)
        finally:
            conn.close()

        brier = compute_brier_score(db_path=db_path)
        cal   = compute_calibration(db_path=db_path)
        trend = get_feature_importance_trend(db_path=db_path)

        lines = [
            f"ML Performance Tracker — {n_total} predictions ({n_completed} completed)",
        ]
        if brier is not None:
            quality = "excellent" if brier < 0.15 else "good" if brier < 0.20 else "fair" if brier < 0.25 else "poor"
            lines.append(f"  Brier Score:  {brier:.4f}  ({quality}; 0.25 = coin-flip baseline)")
        if cal:
            lines.append(f"  Calibration:  {len(cal)} bins with data")
            worst_gap = max(abs(b["predicted_mean"] - b["actual_rate"]) for b in cal)
            lines.append(f"  Worst cal gap: {worst_gap:.3f} (lower = better calibrated)")
        if trend:
            top3 = list(trend.items())[:3]
            parts = ", ".join(f"{f}={v:.4f}" for f, v in top3)
            lines.append(f"  Top features (mean |SHAP|): {parts}")
        return "\n".join(lines)
    except Exception as exc:
        _log.debug("[MLT] format_tracker_summary failed: %s", exc)
        return f"ML Tracker: summary unavailable ({exc})"
