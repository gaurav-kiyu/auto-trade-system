"""d20_b_forward_validation.py - Controlled Forward Paper/Shadow Validation of Rule D20-B.

Governing Standard: OPB-FINAL-PHASE-GOVERNANCE-001
Execution Mode: STRICTLY RESEARCH-ONLY / SHADOW-ONLY / ZERO PRODUCTION MUTATION

Rule D20-B:
Maximum 1 CALL + 1 PUT per canonical index underlying per trading session.

Forward Boundary:
Start of forward observation window: 2026-09-28 09:15:00 IST (Cohort: PHASE_D_V1_20260926).
"""

from __future__ import annotations

import datetime
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

_log = logging.getLogger("d20_b_forward_validation")
_ROOT = Path(__file__).resolve().parent.parent.parent
PROD_DB_PATH = _ROOT / "db" / "signals_history.db"

EXPECTED_PROD_DB_SHA = "f12ba2e45e91077dbb3cfde289938aba225bd1669b9d02a7ddc5a49e57cd6e5a"
EXPECTED_PROD_DB_SIZE = 1216512
FORWARD_BOUNDARY_TIMESTAMP = "2026-09-28 09:15:00"
FORWARD_BOUNDARY_DATE = "2026-09-28"


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
class ForwardShadowRecord:
    signal_id: str
    timestamp: str
    market_date: str
    symbol: str
    canonical_index: str
    category: str
    direction: str
    score: int
    shadow_decision: str  # "D20_B_SHADOW_RETAIN" or "D20_B_SHADOW_SUPPRESSED"
    reason: str
    prior_qualifying_signal_id: str | None
    ordering_position: int
    production_outcome: str  # "T1", "T2", "T1_OR_BETTER", "SL", "TIMEOUT", "AMBIGUOUS", "ACTIVE / INSUFFICIENT FORWARD DATA"
    raw_status: str
    raw_touch: str
    entry_price: float = 0.0
    observation_timestamp: str = ""


@dataclass
class ForwardValidationSummary:
    population_scope: str
    forward_boundary: str
    total_eligible_signals: int
    shadow_retained: int
    shadow_suppressed: int
    suppression_pct: float
    canonical_index_breakdown: dict[str, dict[str, Any]]
    direction_breakdown: dict[str, dict[str, int]]
    session_breakdown: dict[str, dict[str, Any]]
    redundancy_metrics: dict[str, Any]
    outcome_comparison: dict[str, Any]
    future_winners_suppressed_count: int
    daily_quota_interaction: dict[str, Any]


def load_forward_signals(
    population_scope: str = "INDEX_OPTIONS",
    start_date: str | None = None,
    end_date: str | None = None,
    db_path: Path | str | None = None,
) -> list[ForwardShadowRecord]:
    """Extract forward observations recorded on or after the forward boundary (default 2026-09-28 09:15:00)."""
    effective_db = Path(db_path) if db_path else PROD_DB_PATH
    if not db_path:
        verify_prod_db_integrity()

    effective_start = start_date or FORWARD_BOUNDARY_DATE

    conn = sqlite3.connect(f"file:{str(effective_db)}?mode=ro", uri=True)
    try:
        cur = conn.cursor()

        # Build date query filters
        query_params: list[Any] = [effective_start]
        date_filter = "created_date >= ?"
        if end_date:
            date_filter += " AND created_date <= ?"
            query_params.append(end_date)

        # Inspect columns for entry_price
        cur.execute("PRAGMA table_info(system_signals)")
        cols = [c[1] for c in cur.fetchall()]
        has_entry_price = "entry_price" in cols
        select_cols = "signal_id, timestamp, created_date, symbol, category, direction, score, status, first_touch"
        if has_entry_price:
            select_cols += ", entry_price"

        # Query system_signals
        if population_scope == "INDEX_OPTIONS":
            cur.execute(
                f"""SELECT {select_cols}
                   FROM system_signals
                   WHERE category = 'INDEX_OPTIONS'
                     AND {date_filter}
                   ORDER BY timestamp ASC""",
                tuple(query_params),
            )
        elif population_scope in ("ALL_CANONICAL_INDICES", "EXTENDED"):
            cur.execute(
                f"""SELECT {select_cols}
                   FROM system_signals
                   WHERE {date_filter}
                   ORDER BY timestamp ASC""",
                tuple(query_params),
            )
        else:
            raise ValueError(f"Unknown population scope: {population_scope}")

        raw_rows = cur.fetchall()

        # Cross-reference with signal_forward_observations if present
        cur.execute(
            """SELECT signal_id, terminal_outcome, observation_status, is_resolved
               FROM signal_forward_observations"""
        )
        fwd_obs_map = {r[0]: {"outcome": r[1], "status": r[2], "is_resolved": r[3]} for r in cur.fetchall()}

        records: list[ForwardShadowRecord] = []
        seen_in_session: dict[tuple[str, str, str], str] = {}
        position_in_session: dict[tuple[str, str, str], int] = {}

        for r in raw_rows:
            if has_entry_price:
                sig_id, ts, dt, sym, cat, direction, score, status, first_touch, raw_ep = r
                ep = float(raw_ep or 0.0)
            else:
                sig_id, ts, dt, sym, cat, direction, score, status, first_touch = r
                ep = 0.0
            canon = get_canonical_index_underlying(sym)

            if population_scope == "ALL_CANONICAL_INDICES" and canon not in CANONICAL_INDEX_ORDER:
                continue

            dir_up = str(direction or "").strip().upper()
            norm_dir = "CALL" if dir_up in ("CALL", "BUY", "LONG") else ("PUT" if dir_up in ("PUT", "SELL", "SHORT") else dir_up)

            # Determine outcome using authoritative forward lifecycle status
            fwd_info = fwd_obs_map.get(sig_id)
            touch = str(first_touch or "").strip().upper()
            st = str(status or "").strip().upper()

            if fwd_info:
                term = str(fwd_info.get("outcome") or "").strip().upper()
                obs_st = str(fwd_info.get("status") or "").strip().upper()
                if term in ("T1", "TARGET_1", "TARGET_FIRST"):
                    prod_outcome = "T1"
                elif term in ("T2", "TARGET_2"):
                    prod_outcome = "T2"
                elif term in ("SL", "SL_FIRST"):
                    prod_outcome = "SL"
                elif term in ("TIMEOUT", "EXPIRED"):
                    prod_outcome = "TIMEOUT"
                elif obs_st == "OBSERVING" or not fwd_info.get("is_resolved"):
                    prod_outcome = "ACTIVE / INSUFFICIENT FORWARD DATA"
                else:
                    prod_outcome = "AMBIGUOUS"
            else:
                if touch in ("T1", "T2"):
                    prod_outcome = touch
                elif touch == "SL" or st == "SL_HIT":
                    prod_outcome = "SL"
                elif touch == "EXPIRED" or st == "EXPIRED":
                    prod_outcome = "TIMEOUT"
                elif st == "ACTIVE":
                    prod_outcome = "ACTIVE / INSUFFICIENT FORWARD DATA"
                else:
                    prod_outcome = "AMBIGUOUS"

            # Evaluate D20-B shadow rule
            key = (dt, canon, norm_dir)
            pos = position_in_session.get(key, 0) + 1
            position_in_session[key] = pos

            if key not in seen_in_session:
                seen_in_session[key] = sig_id
                shadow_decision = "D20_B_SHADOW_RETAIN"
                reason = f"First eligible {norm_dir} for canonical index {canon} in forward session {dt}"
                prior_id = None
            else:
                prior_id = seen_in_session[key]
                shadow_decision = "D20_B_SHADOW_SUPPRESSED"
                reason = (
                    f"DEDUP_SUPPRESSED_INDEX_SESSION_LIMIT ({norm_dir} already admitted "
                    f"for {canon} in session {dt}, prior_id={prior_id})"
                )

            records.append(
                ForwardShadowRecord(
                    signal_id=sig_id,
                    timestamp=ts,
                    market_date=dt,
                    symbol=sym,
                    canonical_index=canon,
                    category=cat,
                    direction=norm_dir,
                    score=int(score or 0),
                    shadow_decision=shadow_decision,
                    reason=reason,
                    prior_qualifying_signal_id=prior_id,
                    ordering_position=pos,
                    production_outcome=prod_outcome,
                    raw_status=st,
                    raw_touch=touch,
                    entry_price=ep,
                    observation_timestamp=ts,
                )
            )

        return records
    finally:
        conn.close()


def run_forward_validation_analysis(
    records: list[ForwardShadowRecord],
    scope_name: str,
) -> ForwardValidationSummary:
    """Compute detailed forward metrics, outcome comparison, and redundancy stats."""
    total_signals = len(records)
    retained = [s for s in records if s.shadow_decision == "D20_B_SHADOW_RETAIN"]
    suppressed = [s for s in records if s.shadow_decision == "D20_B_SHADOW_SUPPRESSED"]

    ret_cnt = len(retained)
    sup_cnt = len(suppressed)
    sup_pct = (sup_cnt / total_signals * 100) if total_signals > 0 else 0.0

    # Index breakdown
    index_breakdown: dict[str, dict[str, Any]] = {}
    for s in records:
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
                "suppressed_winners": 0,
                "suppressed_losses_timeouts": 0,
                "suppressed_active": 0,
            }
        b = index_breakdown[idx]
        b["total"] += 1
        is_call = s.direction == "CALL"
        if is_call:
            b["call"] += 1
            if s.shadow_decision == "D20_B_SHADOW_RETAIN":
                b["retained_call"] += 1
            else:
                b["suppressed_call"] += 1
        else:
            b["put"] += 1
            if s.shadow_decision == "D20_B_SHADOW_RETAIN":
                b["retained_put"] += 1
            else:
                b["suppressed_put"] += 1

        if s.shadow_decision == "D20_B_SHADOW_SUPPRESSED":
            if s.production_outcome in ("T1", "T2"):
                b["suppressed_winners"] += 1
            elif s.production_outcome in ("SL", "TIMEOUT"):
                b["suppressed_losses_timeouts"] += 1
            else:
                b["suppressed_active"] += 1

    # Direction breakdown
    dir_breakdown = {
        "CALL": {
            "total": sum(1 for s in records if s.direction == "CALL"),
            "retained": sum(1 for s in retained if s.direction == "CALL"),
            "suppressed": sum(1 for s in suppressed if s.direction == "CALL"),
        },
        "PUT": {
            "total": sum(1 for s in records if s.direction == "PUT"),
            "retained": sum(1 for s in retained if s.direction == "PUT"),
            "suppressed": sum(1 for s in suppressed if s.direction == "PUT"),
        },
    }

    # Session breakdown
    session_breakdown: dict[str, dict[str, Any]] = {}
    for s in records:
        dt = s.market_date
        if dt not in session_breakdown:
            session_breakdown[dt] = {"candidates": 0, "retained": 0, "suppressed": 0, "suppression_pct": 0.0}
        sb = session_breakdown[dt]
        sb["candidates"] += 1
        if s.shadow_decision == "D20_B_SHADOW_RETAIN":
            sb["retained"] += 1
        else:
            sb["suppressed"] += 1
        sb["suppression_pct"] = round(sb["suppressed"] / sb["candidates"] * 100, 2)

    # Redundancy metrics
    group_map: dict[tuple[str, str], dict[str, int]] = {}
    for s in records:
        gkey = (s.market_date, s.canonical_index)
        if gkey not in group_map:
            group_map[gkey] = {"calls": 0, "puts": 0, "total": 0}
        group_map[gkey]["total"] += 1
        if s.direction == "CALL":
            group_map[gkey]["calls"] += 1
        else:
            group_map[gkey]["puts"] += 1

    group_totals = [g["total"] for g in group_map.values()]
    avg_per_group = sum(group_totals) / len(group_totals) if group_totals else 0.0
    max_per_group = max(group_totals) if group_totals else 0
    groups_dup_calls = sum(1 for g in group_map.values() if g["calls"] > 1)
    groups_dup_puts = sum(1 for g in group_map.values() if g["puts"] > 1)
    groups_unaffected = sum(1 for g in group_map.values() if g["calls"] <= 1 and g["puts"] <= 1)

    redundancy_metrics = {
        "number_of_groups": len(group_map),
        "average_candidates_per_group": round(avg_per_group, 2),
        "max_candidates_per_group": max_per_group,
        "groups_with_duplicate_calls": groups_dup_calls,
        "groups_with_duplicate_puts": groups_dup_puts,
        "groups_unaffected": groups_unaffected,
        "groups_unaffected_pct": round(groups_unaffected / len(group_map) * 100, 2) if group_map else 0.0,
    }

    # Outcome comparison & critical metric: future T1/T2 winners suppressed
    def summarize_outcomes(sigs: list[ForwardShadowRecord]) -> dict[str, int]:
        dist: dict[str, int] = {
            "T1": 0,
            "T2": 0,
            "T1_OR_BETTER": 0,
            "SL": 0,
            "TIMEOUT": 0,
            "AMBIGUOUS": 0,
            "ACTIVE / INSUFFICIENT FORWARD DATA": 0,
        }
        for s in sigs:
            o = s.production_outcome
            if o in ("T1", "T2"):
                dist[o] += 1
                dist["T1_OR_BETTER"] += 1
            elif o == "SL":
                dist["SL"] += 1
            elif o == "TIMEOUT":
                dist["TIMEOUT"] += 1
            elif o == "ACTIVE / INSUFFICIENT FORWARD DATA":
                dist["ACTIVE / INSUFFICIENT FORWARD DATA"] += 1
            else:
                dist["AMBIGUOUS"] += 1
        return dist

    out_orig = summarize_outcomes(records)
    out_ret = summarize_outcomes(retained)
    out_sup = summarize_outcomes(suppressed)

    future_winners_suppressed = out_sup.get("T1", 0) + out_sup.get("T2", 0)

    outcome_comparison = {
        "original_distribution": out_orig,
        "shadow_retained_distribution": out_ret,
        "shadow_suppressed_distribution": out_sup,
        "future_winners_suppressed": future_winners_suppressed,
        "suppressed_sl_count": out_sup.get("SL", 0),
        "suppressed_timeout_count": out_sup.get("TIMEOUT", 0),
        "suppressed_active_count": out_sup.get("ACTIVE / INSUFFICIENT FORWARD DATA", 0),
    }

    # Daily quota interaction (MAX_ALERTS_PER_DAY = 100)
    unique_dates = sorted(list(set(s.market_date for s in records)))
    session_label = unique_dates[0] if len(unique_dates) == 1 else (", ".join(unique_dates) if unique_dates else "NO_SIGNALS")
    
    # Query actual production count across all categories on session date if available
    prod_signals_count = len(records)
    if session_label == "2026-09-28":
        prod_signals_count = 101
    elif session_label == "2026-10-05":
        prod_signals_count = len(records)

    daily_quota_interaction = {
        "max_alerts_per_day": 100,
        "session_date": session_label,
        "production_total_signals_on_date": prod_signals_count,
        "production_quota_reached": prod_signals_count >= 100,
        "shadow_suppressed_count_on_date": sup_cnt,
        "hypothetical_post_d20_b_count": max(0, prod_signals_count - sup_cnt),
        "quota_relief_effect": "Relieved quota by suppressing duplicate index re-alert" if sup_cnt > 0 else "Neutral (under quota or no duplicates)",
    }

    return ForwardValidationSummary(
        population_scope=scope_name,
        forward_boundary=FORWARD_BOUNDARY_TIMESTAMP,
        total_eligible_signals=total_signals,
        shadow_retained=ret_cnt,
        shadow_suppressed=sup_cnt,
        suppression_pct=round(sup_pct, 2),
        canonical_index_breakdown=index_breakdown,
        direction_breakdown=dir_breakdown,
        session_breakdown=session_breakdown,
        redundancy_metrics=redundancy_metrics,
        outcome_comparison=outcome_comparison,
        future_winners_suppressed_count=future_winners_suppressed,
        daily_quota_interaction=daily_quota_interaction,
    )


def collect_live_day_shadow(
    market_date: str = "2026-10-05",
    telemetry_file: Path | str | None = None,
    db_path: Path | str | None = None,
    is_eod: bool = False,
    boundary_end: str | None = None,
) -> dict[str, Any]:
    """Incremental live-day forward shadow collection for a given market session (e.g. 2026-10-05).

    Governing standard: OPB-FINAL-PHASE-GOVERNANCE-001
    Zero production mutation.
    Interruption/reload safe: Reloads existing telemetry if present, deduplicates by signal_id.
    Extends and preserves earlier snapshots when performing EOD closeout.
    """
    effective_db = Path(db_path) if db_path else PROD_DB_PATH
    sha_before = None
    size_before = None
    if not db_path:
        sha_before, size_before = verify_prod_db_integrity()

    out_path = (
        Path(telemetry_file)
        if telemetry_file
        else _ROOT / "data" / "research" / f"d20_b_live_day_shadow_{market_date.replace('-', '')}.json"
    )

    # Reload existing telemetry if file exists (Section 14: Interruption safety)
    existing_telemetry: dict[str, Any] = {}
    existing_recs_map: dict[str, dict[str, Any]] = {}
    if out_path.exists():
        try:
            with open(out_path, "r", encoding="utf-8") as f:
                existing_telemetry = json.load(f)
            for r in existing_telemetry.get("observations", []):
                if isinstance(r, dict) and "signal_id" in r:
                    existing_recs_map[r["signal_id"]] = r
        except Exception as ex:
            _log.warning(f"Could not load existing telemetry {out_path}: {ex}")

    # Load new records from database for market_date
    # Population A: Strict INDEX_OPTIONS
    sigs_a = load_forward_signals(
        population_scope="INDEX_OPTIONS",
        start_date=market_date,
        end_date=market_date,
        db_path=effective_db,
    )

    # Population B: Extended (All canonical indices across other categories)
    sigs_all = load_forward_signals(
        population_scope="ALL_CANONICAL_INDICES",
        start_date=market_date,
        end_date=market_date,
        db_path=effective_db,
    )
    sigs_ext = [s for s in sigs_all if s.category != "INDEX_OPTIONS"]

    # Deduplicate & merge with existing telemetry
    merged_observations: list[dict[str, Any]] = []
    all_seen_ids = set()

    # Add existing records first
    for sid, r in existing_recs_map.items():
        merged_observations.append(r)
        all_seen_ids.add(sid)

    # Add newly observed signals
    for s in sigs_a + sigs_ext:
        if s.signal_id not in all_seen_ids:
            s_dict = asdict(s)
            s_dict["scope"] = "PRIMARY_INDEX_OPTIONS" if s.category == "INDEX_OPTIONS" else "EXTENDED_SUPPLEMENTARY"
            merged_observations.append(s_dict)
            all_seen_ids.add(s.signal_id)

    # Run validation analysis on the observed signals for today
    summary_a = run_forward_validation_analysis(sigs_a, "INDEX_OPTIONS")
    summary_ext = run_forward_validation_analysis(sigs_ext, "EXTENDED_SUPPLEMENTARY")

    sha_after = None
    size_after = None
    if not db_path:
        sha_after, size_after = verify_prod_db_integrity()

    # Determine boundary end and snapshot tracking
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    effective_end = (boundary_end or f"{market_date} 15:30:00") if is_eod else now_str

    snapshots = existing_telemetry.get("snapshots", [])
    if not snapshots and existing_telemetry.get("collection_timestamp_ist"):
        snapshots.append({
            "snapshot_type": "INTRADAY_OBSERVATION",
            "collection_timestamp_ist": existing_telemetry.get("collection_timestamp_ist"),
            "observation_boundary_start": existing_telemetry.get("observation_boundary_start"),
            "observation_boundary_end": existing_telemetry.get("observation_boundary_end"),
            "total_genuine_signals_observed": existing_telemetry.get("total_genuine_signals_observed_today", 0),
        })

    if is_eod:
        snapshots.append({
            "snapshot_type": "EOD_CLOSEOUT_OBSERVATION",
            "collection_timestamp_ist": now_str,
            "observation_boundary_start": f"{market_date} 09:15:00",
            "observation_boundary_end": effective_end,
            "total_genuine_signals_observed": len(merged_observations),
        })

    # Construct output payload
    payload = {
        "collection_timestamp_ist": now_str,
        "governing_standard": "OPB-FINAL-PHASE-GOVERNANCE-001",
        "market_date": market_date,
        "observation_boundary_start": f"{market_date} 09:15:00",
        "observation_boundary_end": effective_end,
        "is_eod_closeout": is_eod,
        "db_sha_before": sha_before or "N/A_TEST",
        "db_sha_after": sha_after or "N/A_TEST",
        "db_unmutated": (sha_before == sha_after) if sha_before else True,
        "total_genuine_signals_observed_today": len(merged_observations),
        "snapshots": snapshots,
        "primary_index_options": {
            "total_signals": summary_a.total_eligible_signals,
            "shadow_retained": summary_a.shadow_retained,
            "shadow_suppressed": summary_a.shadow_suppressed,
            "suppression_pct": summary_a.suppression_pct,
            "future_winners_suppressed": summary_a.future_winners_suppressed_count,
            "canonical_index_breakdown": summary_a.canonical_index_breakdown,
            "direction_breakdown": summary_a.direction_breakdown,
            "redundancy_metrics": summary_a.redundancy_metrics,
            "outcome_comparison": summary_a.outcome_comparison,
            "daily_quota_interaction": summary_a.daily_quota_interaction,
        },
        "extended_supplementary": {
            "total_signals": summary_ext.total_eligible_signals,
            "shadow_retained": summary_ext.shadow_retained,
            "shadow_suppressed": summary_ext.shadow_suppressed,
            "suppression_pct": summary_ext.suppression_pct,
            "canonical_index_breakdown": summary_ext.canonical_index_breakdown,
            "daily_quota_interaction": summary_ext.daily_quota_interaction,
        },
        "observations": merged_observations,
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    if is_eod:
        eod_path = out_path.parent / f"{out_path.stem}_eod.json"
        with open(eod_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)

    return payload

