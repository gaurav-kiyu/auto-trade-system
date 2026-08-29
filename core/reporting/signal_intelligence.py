"""Historical signal intelligence, outcome sequencing and config suggestions.

This module deliberately separates *recommendations* from live configuration
mutation. Trading/risk parameters are never changed automatically from a
report. Suggestions carry sample-size and confidence evidence and must pass
the existing privileged configuration workflow before application.
"""
from __future__ import annotations

import json
import math
import sqlite3
from collections import defaultdict
from datetime import timedelta
from pathlib import Path
from typing import Any

from core.datetime_ist import now_ist


def _wilson_lower(successes: int, total: int, z: float = 1.96) -> float:
    if total <= 0:
        return 0.0
    p = successes / total
    den = 1 + z * z / total
    centre = p + z * z / (2 * total)
    margin = z * math.sqrt((p * (1 - p) / total) + z * z / (4 * total * total))
    return max(0.0, (centre - margin) / den)


def _bucket_score(score: int) -> str:
    if score >= 90:
        return "90+"
    if score >= 80:
        return "80-89"
    if score >= 70:
        return "70-79"
    if score >= 60:
        return "60-69"
    return "<60"


def _load_rows(db_path: Path, days: int, category: str, tier: str) -> list[dict[str, Any]]:
    if not db_path.is_file():
        return []
    conn = sqlite3.connect(str(db_path), timeout=5)
    conn.row_factory = sqlite3.Row
    try:
        clauses = ["1=1"]
        params: list[Any] = []
        if days > 0:
            cutoff = (now_ist() - timedelta(days=days)).date().isoformat()
            clauses.append("created_date >= ?")
            params.append(cutoff)
        if category and category != "all":
            clauses.append("category = ?")
            params.append(category)
        if tier and tier != "all":
            clauses.append("tier = ?")
            params.append(tier)
        rows = conn.execute(
            f"SELECT * FROM system_signals WHERE {' AND '.join(clauses)} ORDER BY timestamp ASC",  # nosec B608
            params,
        ).fetchall()
        result = []
        for raw_row in rows:
            row = dict(raw_row)
            try:
                payload = json.loads(row.get("raw_data") or "{}")
                if isinstance(payload, dict):
                    row.setdefault("raw_score", payload.get("raw_score"))
                    row.setdefault("score_saturated", payload.get("score_saturated"))
            except (TypeError, ValueError, json.JSONDecodeError):
                pass
            result.append(row)
        return result
    finally:
        conn.close()



def _canonical_first_touch(row: dict[str, Any]) -> str:
    """Return the canonical first-touch outcome when available.

    Modern tracker records use immutable first_touch:
      T1/T2 -> T1 target family
      SL    -> SL

    Legacy rows without first_touch are intentionally returned as empty
    because their terminal status cannot prove chronological first-hit
    ordering.
    """
    touch = str(row.get("first_touch") or "").strip().upper()

    if touch in {"T1", "T2"}:
        return "T1"

    if touch == "SL":
        return "SL"

    return ""


def _legacy_terminal_outcome(row: dict[str, Any]) -> str:
    """Return the legacy terminal outcome when first_touch is unavailable."""
    if str(row.get("first_touch") or "").strip():
        return ""

    status = str(row.get("status") or "").strip().upper()

    if status in {"TARGET_1_HIT", "TARGET_2_HIT"}:
        return "T1"

    if status == "SL_HIT":
        return "SL"

    return ""


def _is_exact_first_touch(row: dict[str, Any]) -> bool:
    """Return True when chronological first-touch information is explicit."""
    return _canonical_first_touch(row) in {"T1", "SL"}


def _is_legacy_resolved(row: dict[str, Any]) -> bool:
    """Return True for old rows whose terminal outcome is still reportable."""
    return bool(_legacy_terminal_outcome(row))


def _canonical_resolved_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return modern exact rows plus backward-compatible legacy outcomes."""
    return [
        row
        for row in rows
        if _is_exact_first_touch(row) or _is_legacy_resolved(row)
    ]


def _canonical_outcome(row: dict[str, Any]) -> str:
    """Return canonical outcome, falling back only for legacy rows."""
    exact = _canonical_first_touch(row)
    if exact:
        return exact
    return _legacy_terminal_outcome(row)


def _dimension(rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        buckets[str(row.get(key) or "UNKNOWN")].append(row)
    result = []
    for name, items in sorted(buckets.items()):
        resolved = _canonical_resolved_rows(items)
        wins = [r for r in resolved if _canonical_outcome(r) == "T1"]
        losses = [r for r in resolved if _canonical_outcome(r) == "SL"]
        result.append({
            "bucket": name,
            "signals": len(items),
            "resolved": len(resolved),
            "t1_or_better": len(wins),
            "sl_before_t1_recorded": len(losses),
            "t1_rate_pct": round(len(wins) / len(items) * 100, 2) if items else 0.0,
            "resolved_win_rate_pct": round(len(wins) / len(resolved) * 100, 2) if resolved else 0.0,
            "wilson_lower_95_pct": round(_wilson_lower(len(wins), len(resolved)) * 100, 2) if resolved else 0.0,
            "avg_pnl_pct": round(sum(float(r.get("pnl_pct") or 0) for r in items) / len(items), 3) if items else 0.0,
        })
    return result


def build_signal_intelligence_report(
    db_path: str | Path = "db/signals_history.db",
    *,
    days: int = 90,
    category: str = "all",
    tier: str = "all",
    include_seed_samples: bool = True,
) -> dict[str, Any]:
    """Build a decision-support report from generated signal history."""
    rows = _load_rows(Path(db_path), days, category, tier)
    seed_rows = [r for r in rows if "is_seed_sample" in str(r.get("raw_data") or "").lower()]
    if not include_seed_samples:
        rows = [r for r in rows if "is_seed_sample" not in str(r.get("raw_data") or "").lower()]
    total = len(rows)
    # Persisted history represents final signals, not all scanner candidates.
    # Surface that distinction explicitly so "signals/day" cannot be confused
    # with scanner evaluations.
    opportunity_keys = [str(r.get("opportunity_key") or "") for r in rows if r.get("opportunity_key")]
    duplicate_key_count = max(0, len(opportunity_keys) - len(set(opportunity_keys)))
    unique_symbols = len({str(r.get("symbol") or "") for r in rows})
    signal_funnel = {
        "persisted_final_signals": total,
        "unique_opportunity_keys": len(set(opportunity_keys)),
        "duplicate_opportunity_rows": duplicate_key_count,
        "unique_symbols": unique_symbols,
        "seed_samples_excluded": len(seed_rows) if not include_seed_samples else 0,
        "seed_samples_present": len(seed_rows),
        "candidate_evaluations": None,
        "rejected_candidates": None,
        "note": "Candidate/evaluation counts require candidate audit persistence; they are intentionally not inferred from final signal rows."
    }

    resolved = _canonical_resolved_rows(rows)
    t1 = [r for r in rows if _canonical_outcome(r) == "T1"]
    t2 = [r for r in rows if r.get("status") == "TARGET_2_HIT"]
    sl = [r for r in rows if _canonical_outcome(r) == "SL"]
    active = [r for r in rows if r.get("status") == "ACTIVE"]
    expired = [r for r in rows if r.get("status") == "EXPIRED"]
    demo = [r for r in rows if "is_seed_sample" in str(r.get("raw_data") or "")]
    ambiguous = [r for r in rows if r.get("status") == "AMBIGUOUS"]
    exact_first_touch = [r for r in rows if r.get("outcome_confidence") == "EXACT_OBSERVATION"]
    saturated = 0
    raw_score_observations = 0
    for r in rows:
        try:
            raw = float(r.get("raw_score"))
            score = float(r.get("score"))
        except (TypeError, ValueError):
            try:
                raw_data = json.loads(r.get("raw_data") or "{}")
                raw = float(raw_data.get("raw_score"))
                score = float(r.get("score"))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
        raw_score_observations += 1
        if score >= 100 and raw > 100:
            saturated += 1
    saturation_pct = (saturated / raw_score_observations * 100) if raw_score_observations else 0.0

    # "SL before T1" here means the recorded terminal outcome was SL rather
    # than T1/T2. Without intrabar OHLC/event timestamps, the system cannot
    # prove which level was crossed first between polling intervals.
    resolved_rate = (len(t1) / len(resolved) * 100) if resolved else 0.0
    sl_rate = (len(sl) / len(resolved) * 100) if resolved else 0.0
    t1_rate = (len(t1) / total * 100) if total else 0.0
    t2_rate = (len(t2) / total * 100) if total else 0.0

    score_breakdown = _dimension(rows, "score")
    # _dimension expects strings; normalize score buckets separately.
    sbuckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        sbuckets[_bucket_score(int(r.get("score") or 0))].append(r)
    score_breakdown = []
    for bucket in ("<60", "60-69", "70-79", "80-89", "90+"):
        items = sbuckets.get(bucket, [])
        rr = _canonical_resolved_rows(items)
        ww = [x for x in rr if _canonical_outcome(x) == "T1"]
        score_breakdown.append({
            "bucket": bucket,
            "signals": len(items),
            "resolved": len(rr),
            "t1_or_better": len(ww),
            "sl_before_t1_recorded": len(rr) - len(ww),
            "resolved_win_rate_pct": round(len(ww) / len(rr) * 100, 2) if rr else 0.0,
            "wilson_lower_95_pct": round(_wilson_lower(len(ww), len(rr)) * 100, 2) if rr else 0.0,
        })

    cfg_diagnostics = {}
    try:
        cfg_path = Path(__file__).resolve().parents[2] / "json" / "config.json"
        cfg = json.loads(cfg_path.read_text(encoding="utf-8")) if cfg_path.exists() else {}
        cat_thresholds = cfg.get("CATEGORY_SCORE_THRESHOLDS", {}) if isinstance(cfg, dict) else {}
        cfg_diagnostics = {
            "AI_THRESHOLD": cfg.get("AI_THRESHOLD"),
            "TG_ALERT_MIN_SCORE": cfg.get("TG_ALERT_MIN_SCORE"),
            "CATEGORY_SCORE_THRESHOLDS": cat_thresholds,
            "EXECUTION_MODE": cfg.get("EXECUTION_MODE"),
            "AUTO_TUNE_ENABLED": cfg.get("AUTO_TUNE_ENABLED"),
            "AUTO_TUNE_REQUIRE_APPROVAL": cfg.get("AUTO_TUNE_REQUIRE_APPROVAL"),
            "SIGNAL_OUTCOME_TRACKING_ENABLED": cfg.get("signal_outcome_tracking_enabled", False),
        }
        # The generic equity/futures scorer tops out below 100 before any
        # normalization. A raw 100 gate therefore makes those categories
        # unreachable. Surface this explicitly rather than silently changing
        # the user's live policy.
        for cat in ("STOCK_OPTIONS", "EQUITY_SWING_DELIVERY", "LARGE_CAP_EQUITY", "MID_SMALL_CAP", "PENNY_SME", "COMMODITIES", "CURRENCIES", "FUTURES", "ETFS_REITS"):
            if isinstance(cat_thresholds, dict) and int(cat_thresholds.get(cat, 0) or 0) >= 100:
                cfg_diagnostics.setdefault("unreachable_raw_100_categories", []).append(cat)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        cfg_diagnostics = {"error": "Unable to load runtime config diagnostics."}

    recommendations: list[dict[str, Any]] = []
    min_sample = 30
    if len(resolved) < min_sample:
        recommendations.append({
            "severity": "INFO",
            "parameter": None,
            "recommendation": "Collect more resolved signals before changing trading thresholds.",
            "reason": f"Only {len(resolved)} resolved signals are available; minimum evidence threshold is {min_sample}.",
        })
    else:
        # Candidate score gate: only suggest a stricter gate when the higher
        # bucket has meaningful sample size and materially stronger evidence.
        candidates = [x for x in score_breakdown if x["resolved"] >= min_sample]
        best = max(candidates, key=lambda x: x["wilson_lower_95_pct"], default=None)
        if best and best["wilson_lower_95_pct"] >= 55:
            suggested = {"60-69": 70, "70-79": 80, "80-89": 80, "90+": 90}.get(best["bucket"])
            if suggested:
                recommendations.append({
                    "severity": "MEDIUM",
                    "parameter": "AI_THRESHOLD",
                    "suggested_value": suggested,
                    "recommendation": f"Consider raising the signal quality gate toward {suggested}.",
                    "reason": f"Score bucket {best['bucket']} has {best['resolved']} resolved signals and a 95% Wilson lower bound of {best['wilson_lower_95_pct']:.1f}%.",
                    "requires_approval": True,
                })
        if sl_rate >= 55:
            recommendations.append({
                "severity": "HIGH",
                "parameter": "SL_PCT",
                "recommendation": "Review stop-loss calibration and market-regime segmentation before changing SL_PCT.",
                "reason": f"Recorded SL outcomes are {sl_rate:.1f}% of resolved signals ({len(sl)}/{len(resolved)}). This is evidence for review, not an automatic widening/tightening instruction.",
                "requires_approval": True,
            })
        if t1_rate < 35 and len(rows) >= min_sample:
            recommendations.append({
                "severity": "HIGH",
                "parameter": "TARGET_PCT",
                "recommendation": "Review T1 distance versus observed volatility and entry quality; do not automatically move the target.",
                "reason": f"T1-or-better rate is {t1_rate:.1f}% across {total} generated signals.",
                "requires_approval": True,
            })
        if t2_rate >= 35 and t1_rate > 0:
            recommendations.append({
                "severity": "LOW",
                "parameter": "TARGET_PCT",
                "recommendation": "T2 performance is strong enough to review whether the staged exit allocation is leaving upside on the table.",
                "reason": f"T2 hit rate is {t2_rate:.1f}% ({len(t2)}/{total}).",
                "requires_approval": True,
            })

        if saturation_pct >= 10 and raw_score_observations >= min_sample:
            recommendations.append({
                "severity": "HIGH",
                "parameter": "CATEGORY_SCORE_THRESHOLDS",
                "recommendation": "Investigate score saturation before treating 100/100 as a rare high-conviction event.",
                "reason": f"{saturation_pct:.1f}% of rows with raw-score evidence are clamped at 100 while raw score exceeds 100. A capped score is not equivalent to an exact model score of 100.",
                "requires_approval": True,
            })
        if ambiguous:
            recommendations.append({
                "severity": "HIGH",
                "parameter": "SIGNAL_OUTCOME_TRACKING",
                "recommendation": "Use intrabar/event-level price observations before tuning SL/T1; ambiguous polling intervals must not be counted as wins or losses.",
                "reason": f"{len(ambiguous)} signals crossed multiple barriers in one observation and therefore cannot establish first-touch order.",
                "requires_approval": True,
            })

    unreachable = cfg_diagnostics.get("unreachable_raw_100_categories", []) if isinstance(cfg_diagnostics, dict) else []
    if unreachable:
        recommendations.append({
            "severity": "HIGH",
            "parameter": "CATEGORY_SCORE_THRESHOLDS",
            "recommendation": "Do not interpret a raw 100 threshold as category-neutral; normalize or redesign category scoring before enabling those categories.",
            "reason": "The shared equity/futures scoring path has a theoretical maximum below 100, so raw 100 is unreachable for: " + ", ".join(unreachable),
            "requires_approval": True,
        })

    scan_metrics = {"cycles": 0, "symbols_scanned": 0, "evaluated": 0, "accepted": 0, "delivered_candidates": 0, "errors": 0}
    try:
        conn = sqlite3.connect(str(Path(db_path)))
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*), COALESCE(SUM(symbols_scanned),0), COALESCE(SUM(evaluated),0), COALESCE(SUM(accepted),0), COALESCE(SUM(delivered_candidates),0), COALESCE(SUM(errors),0) FROM scan_cycle_metrics WHERE timestamp >= datetime('now', ?)", (f"-{int(days)} days",))
        row = cur.fetchone()
        if row:
            scan_metrics = dict(zip(["cycles","symbols_scanned","evaluated","accepted","delivered_candidates","errors"], row))
        conn.close()
    except (sqlite3.Error, OSError):
        pass

    by_category = _dimension(rows, "category")
    by_tier = _dimension(rows, "tier")
    by_direction = _dimension(rows, "direction")
    report = {
        "report_name": "Signal Historical Intelligence",
        "generated_at": now_ist().isoformat(),
        "lookback_days": days,
        "filters": {"category": category, "tier": tier, "include_seed_samples": include_seed_samples},
        "configuration_diagnostics": cfg_diagnostics,
        "data_quality": {
            "total_signals": total,
            "signal_funnel": {**signal_funnel, "scan_cycle_metrics": scan_metrics},
            "resolved_signals": len(resolved),
            "active_signals": len(active),
            "expired_signals": len(expired),
            "demo_signals": len(demo),
            "ambiguous_signals": len(ambiguous),
            "raw_score_observations": raw_score_observations,
            "score_saturated_above_100": saturated,
            "note": "Modern records use immutable first_touch for chronological outcome classification. Legacy records without first_touch retain their recorded terminal outcome for backward-compatible reporting but are not represented as proven chronological first-touch observations. Current status remains the latest lifecycle state; ambiguous same-observation multi-barrier crossings are excluded from exact first-hit statistics.",
        },
        "summary": {
            "t1_or_better_rate_pct": round(t1_rate, 2),
            "t2_hit_rate_pct": round(t2_rate, 2),
            "recorded_sl_before_t1_pct": round(sl_rate, 2),
            "resolved_win_rate_pct": round(resolved_rate, 2),
            "ambiguous_outcome_count": len(ambiguous),
            "exact_first_touch_count": len(exact_first_touch),
            "score_saturation_pct": round(saturation_pct, 2),
            "average_pnl_pct": round(sum(float(r.get("pnl_pct") or 0) for r in rows) / total, 3) if total else 0.0,
        },
        "score_breakdown": score_breakdown,
        "category_breakdown": by_category,
        "tier_breakdown": by_tier,
        "direction_breakdown": by_direction,
        "recommendations": recommendations,
        "signals": rows,
    }
    return report


def report_to_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, default=str)
