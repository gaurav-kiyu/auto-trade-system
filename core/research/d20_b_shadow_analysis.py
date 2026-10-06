"""d20_b_shadow_analysis.py - Retrospective Shadow Analysis of Rule D20-B.

Governing Standard: OPB-FINAL-PHASE-GOVERNANCE-001
Execution Mode: STRICTLY READ-ONLY / OFFLINE RESEARCH ANALYSIS

Rule D20-B:
For each canonical index / session, allow at most:
- 1 CALL
- 1 PUT

Evaluates D20-B retrospectively against existing authoritative signal population
without modifying any production code, database records, or system behavior.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from core.signals.signal_quality_gate import (
    CANONICAL_INDEX_ORDER,
    get_canonical_index_underlying,
)

_log = logging.getLogger("d20_b_shadow_analysis")
_ROOT = Path(__file__).resolve().parent.parent.parent
PROD_DB_PATH = _ROOT / "db" / "signals_history.db"

EXPECTED_PROD_DB_SHA = "f12ba2e45e91077dbb3cfde289938aba225bd1669b9d02a7ddc5a49e57cd6e5a"
EXPECTED_PROD_DB_SIZE = 1216512


def verify_prod_db_integrity() -> tuple[str, int]:
    """Verify that db/signals_history.db matches the authoritative SHA and size."""
    if not PROD_DB_PATH.exists():
        raise FileNotFoundError(f"Production database missing: {PROD_DB_PATH}")
    size = PROD_DB_PATH.stat().st_size
    sha = hashlib.sha256(PROD_DB_PATH.read_bytes()).hexdigest()
    if sha != EXPECTED_PROD_DB_SHA or size != EXPECTED_PROD_DB_SIZE:
        raise RuntimeError(
            f"FATAL: Production DB integrity mismatch! Expected SHA {EXPECTED_PROD_DB_SHA}, got {sha}. "
            f"Expected size {EXPECTED_PROD_DB_SIZE}, got {size}."
        )
    return sha, size


@dataclass
class SignalRecord:
    signal_id: str
    timestamp: str
    created_date: str
    symbol: str
    canonical_index: str
    category: str
    direction: str
    score: int
    status: str
    first_touch: str
    effective_outcome: str
    decision: str = "RETAINED"
    suppression_reason: str = ""


@dataclass
class PopulationAnalysisSummary:
    population_name: str
    total_signals: int
    retained_signals: int
    suppressed_signals: int
    suppression_pct: float
    outcome_distribution_original: dict[str, int]
    outcome_distribution_retained: dict[str, int]
    outcome_distribution_suppressed: dict[str, int]
    win_rate_original: float  # T1 / (T1 + SL)
    win_rate_retained: float
    win_rate_suppressed: float
    sl_reduction_pct: float
    index_breakdown: dict[str, dict[str, Any]]
    redundancy_metrics: dict[str, Any]
    daily_quota_metrics: dict[str, Any]


def load_signals(population_scope: str = "INDEX_OPTIONS") -> list[SignalRecord]:
    """Load authoritative signals from signals_history.db in strictly chronological order."""
    verify_prod_db_integrity()

    conn = sqlite3.connect(f"file:{str(PROD_DB_PATH)}?mode=ro", uri=True)
    try:
        cur = conn.cursor()
        if population_scope == "INDEX_OPTIONS":
            cur.execute(
                """SELECT signal_id, timestamp, created_date, symbol, category, direction, score, status, first_touch
                   FROM system_signals
                   WHERE category = 'INDEX_OPTIONS'
                   ORDER BY timestamp ASC"""
            )
        elif population_scope == "ALL_CANONICAL_INDICES":
            cur.execute(
                """SELECT signal_id, timestamp, created_date, symbol, category, direction, score, status, first_touch
                   FROM system_signals
                   ORDER BY timestamp ASC"""
            )
        else:
            raise ValueError(f"Unknown population scope: {population_scope}")

        rows = cur.fetchall()
        records: list[SignalRecord] = []
        for r in rows:
            sig_id, ts, dt, sym, cat, direction, score, status, first_touch = r
            canon = get_canonical_index_underlying(sym)

            if population_scope == "ALL_CANONICAL_INDICES" and canon not in CANONICAL_INDEX_ORDER:
                continue

            # Authoritative outcome resolution
            # In OPB, first_touch records T1, SL, EXPIRED. If empty, falls back to status.
            touch = str(first_touch or "").strip().upper()
            st = str(status or "").strip().upper()

            if touch in ("T1", "T2"):
                effective_outcome = touch
            elif touch == "SL" or st == "SL_HIT":
                effective_outcome = "SL"
            elif touch == "EXPIRED" or st == "EXPIRED":
                effective_outcome = "TIMEOUT"
            elif st == "ACTIVE":
                effective_outcome = "UNRESOLVED"
            else:
                effective_outcome = "AMBIGUOUS"

            # Normalize direction
            dir_up = str(direction or "").strip().upper()
            if dir_up in ("CALL", "BUY", "LONG"):
                norm_dir = "CALL"
            elif dir_up in ("PUT", "SELL", "SHORT"):
                norm_dir = "PUT"
            else:
                norm_dir = dir_up

            records.append(
                SignalRecord(
                    signal_id=sig_id,
                    timestamp=ts,
                    created_date=dt,
                    symbol=sym,
                    canonical_index=canon,
                    category=cat,
                    direction=norm_dir,
                    score=int(score or 0),
                    status=st,
                    first_touch=touch,
                    effective_outcome=effective_outcome,
                )
            )
        return records
    finally:
        conn.close()


def apply_d20_b_shadow_simulation(records: list[SignalRecord]) -> list[SignalRecord]:
    """Apply exact D20-B deduplication rule in chronological order.

    Rule:
    For each (created_date, canonical_index), retain at most:
    - 1 CALL
    - 1 PUT
    All subsequent CALL and PUT signals for that index in that session are marked
    D20_B_SHADOW_SUPPRESSED.
    """
    seen_slots: set[tuple[str, str, str]] = set()
    evaluated: list[SignalRecord] = []

    for sig in records:
        key = (sig.created_date, sig.canonical_index, sig.direction)
        if key not in seen_slots:
            seen_slots.add(key)
            sig.decision = "RETAINED"
            sig.suppression_reason = ""
        else:
            sig.decision = "D20_B_SHADOW_SUPPRESSED"
            sig.suppression_reason = (
                f"DEDUP_SUPPRESSED_INDEX_SESSION_LIMIT ({sig.direction} already recorded "
                f"for {sig.canonical_index} in session {sig.created_date})"
            )
        evaluated.append(sig)

    return evaluated


def analyze_population(records: list[SignalRecord], population_name: str) -> PopulationAnalysisSummary:
    """Perform complete statistical and qualitative evaluation of D20-B on a signal population."""
    evaluated = apply_d20_b_shadow_simulation(records)

    total_signals = len(evaluated)
    retained = [s for s in evaluated if s.decision == "RETAINED"]
    suppressed = [s for s in evaluated if s.decision == "D20_B_SHADOW_SUPPRESSED"]

    ret_cnt = len(retained)
    sup_cnt = len(suppressed)
    sup_pct = (sup_cnt / total_signals * 100) if total_signals > 0 else 0.0

    # Outcome distributions
    def count_outcomes(sigs: list[SignalRecord]) -> dict[str, int]:
        dist: dict[str, int] = {"T1": 0, "T2": 0, "SL": 0, "TIMEOUT": 0, "AMBIGUOUS": 0, "UNRESOLVED": 0}
        for s in sigs:
            dist[s.effective_outcome] = dist.get(s.effective_outcome, 0) + 1
        return dist

    out_orig = count_outcomes(evaluated)
    out_ret = count_outcomes(retained)
    out_sup = count_outcomes(suppressed)

    # Win-rate calculations (T1 or better / (T1 or better + SL))
    def calc_win_rate(dist: dict[str, int]) -> float:
        wins = dist.get("T1", 0) + dist.get("T2", 0)
        losses = dist.get("SL", 0)
        if wins + losses == 0:
            return 0.0
        return round((wins / (wins + losses)) * 100, 2)

    win_orig = calc_win_rate(out_orig)
    win_ret = calc_win_rate(out_ret)
    win_sup = calc_win_rate(out_sup)

    # Stop Loss reduction %
    sl_orig = out_orig.get("SL", 0)
    sl_ret = out_ret.get("SL", 0)
    sl_red_pct = ((sl_orig - sl_ret) / sl_orig * 100) if sl_orig > 0 else 0.0

    # Index breakdown
    index_breakdown: dict[str, dict[str, Any]] = {}
    for s in evaluated:
        idx = s.canonical_index
        if idx not in index_breakdown:
            index_breakdown[idx] = {
                "total": 0,
                "call": 0,
                "put": 0,
                "retained_call": 0,
                "retained_put": 0,
                "suppressed_call": 0,
                "suppressed_put": 0,
                "suppressed_successful": 0,
                "suppressed_unsuccessful": 0,
            }
        b = index_breakdown[idx]
        b["total"] += 1
        is_call = s.direction == "CALL"
        if is_call:
            b["call"] += 1
            if s.decision == "RETAINED":
                b["retained_call"] += 1
            else:
                b["suppressed_call"] += 1
        else:
            b["put"] += 1
            if s.decision == "RETAINED":
                b["retained_put"] += 1
            else:
                b["suppressed_put"] += 1

        if s.decision == "D20_B_SHADOW_SUPPRESSED":
            if s.effective_outcome in ("T1", "T2"):
                b["suppressed_successful"] += 1
            else:
                b["suppressed_unsuccessful"] += 1

    # Redundancy analysis
    session_groups: dict[tuple[str, str], dict[str, int]] = {}
    for s in evaluated:
        gkey = (s.created_date, s.canonical_index)
        if gkey not in session_groups:
            session_groups[gkey] = {"calls": 0, "puts": 0, "total": 0}
        session_groups[gkey]["total"] += 1
        if s.direction == "CALL":
            session_groups[gkey]["calls"] += 1
        else:
            session_groups[gkey]["puts"] += 1

    group_counts = [g["total"] for g in session_groups.values()]
    avg_candidates = sum(group_counts) / len(group_counts) if group_counts else 0.0
    max_candidates = max(group_counts) if group_counts else 0
    groups_gt1_call = sum(1 for g in session_groups.values() if g["calls"] > 1)
    groups_gt1_put = sum(1 for g in session_groups.values() if g["puts"] > 1)
    groups_no_effect = sum(1 for g in session_groups.values() if g["calls"] <= 1 and g["puts"] <= 1)
    groups_material_reduction = sum(1 for g in session_groups.values() if g["calls"] > 1 or g["puts"] > 1)

    redundancy_metrics = {
        "total_groups": len(session_groups),
        "average_candidates_per_group": round(avg_candidates, 2),
        "max_candidates_per_group": max_candidates,
        "groups_with_multiple_calls": groups_gt1_call,
        "groups_with_multiple_puts": groups_gt1_put,
        "groups_no_effect_count": groups_no_effect,
        "groups_no_effect_pct": round(groups_no_effect / len(session_groups) * 100, 2) if session_groups else 0.0,
        "groups_material_reduction_count": groups_material_reduction,
        "groups_material_reduction_pct": round(groups_material_reduction / len(session_groups) * 100, 2) if session_groups else 0.0,
    }

    # Daily quota interaction (MAX_ALERTS_PER_DAY = 100)
    # Check daily total signal load across the entire database vs post-D20-B
    daily_orig: dict[str, int] = {}
    daily_post: dict[str, int] = {}
    for s in evaluated:
        dt = s.created_date
        daily_orig[dt] = daily_orig.get(dt, 0) + 1
        if s.decision == "RETAINED":
            daily_post[dt] = daily_post.get(dt, 0) + 1

    quota_metrics = {
        "max_alerts_per_day": 100,
        "days_exceeding_quota_orig": sum(1 for c in daily_orig.values() if c > 100),
        "days_exceeding_quota_post": sum(1 for c in daily_post.values() if c > 100),
        "daily_breakdown": {
            dt: {
                "original": daily_orig[dt],
                "post_d20_b": daily_post.get(dt, 0),
                "suppressed": daily_orig[dt] - daily_post.get(dt, 0),
            }
            for dt in sorted(daily_orig.keys())
        },
    }

    return PopulationAnalysisSummary(
        population_name=population_name,
        total_signals=total_signals,
        retained_signals=ret_cnt,
        suppressed_signals=sup_cnt,
        suppression_pct=round(sup_pct, 2),
        outcome_distribution_original=out_orig,
        outcome_distribution_retained=out_ret,
        outcome_distribution_suppressed=out_sup,
        win_rate_original=win_orig,
        win_rate_retained=win_ret,
        win_rate_suppressed=win_sup,
        sl_reduction_pct=round(sl_red_pct, 2),
        index_breakdown=index_breakdown,
        redundancy_metrics=redundancy_metrics,
        daily_quota_metrics=quota_metrics,
    )
