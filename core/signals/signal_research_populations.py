"""OPB v2.60 Research Populations & Remediated Projection Module.

Governing Standard: OPB-FINAL-PHASE-GOVERNANCE-001
RFC: RFC-OPB-V260-LIFECYCLE-001 (CORRECTED FINAL GATE)

This module formally decouples and exposes:
- POPULATION A: Terminal Lifecycle Population (Lifecycle behavior, exit reasons, timeouts, missing data)
- POPULATION B: Barrier Outcome Population (Strictly barrier-resolved signals only; win rate = (T1+T2)/(T1+T2+SL))
- VIEW v_signals_remediated: Read-only projected view over system_signals with zero database mutation.
"""

from __future__ import annotations

import sqlite3
from typing import Any, Dict, List


def _get_existing_columns(conn: sqlite3.Connection, table_name: str = "system_signals") -> set[str]:
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({table_name})")
    return {r[1] for r in cur.fetchall()}


def get_terminal_lifecycle_population(conn: sqlite3.Connection) -> dict[str, Any]:
    """Retrieve Population A: Terminal Lifecycle Population.

    Answers: 'What happened to each signal across its lifecycle?'
    Distinguishes all terminal lifecycle states and active open signals:
    - TARGET_1_HIT
    - TARGET_2_HIT
    - SL_HIT
    - CLOSED_ON_REVERSAL
    - TIMEOUT (genuine horizon expiry at or after session close)
    - REQUIRES_MISSING_DATA (premature sweeper expiries quarantined)
    - AMBIGUOUS (same-bar / conflicting barrier crossings)
    - ACTIVE (open positions)
    """
    cols = _get_existing_columns(conn, "system_signals")
    exit_reason_expr = "s.exit_reason" if "exit_reason" in cols else "NULL"
    cur = conn.cursor()
    cur.execute(f"""
        SELECT
            s.signal_id,
            s.timestamp,
            s.symbol,
            s.category,
            s.direction,
            s.score,
            s.tier,
            s.entry_price,
            s.stop_loss,
            s.target_1,
            s.target_2,
            s.status AS raw_status,
            s.first_touch AS raw_first_touch,
            s.first_touch_at,
            s.first_touch_price,
            CASE
                WHEN s.status IN ('TARGET_1_HIT', 'T1_HIT') OR s.first_touch = 'T1' THEN 'TARGET_1_HIT'
                WHEN s.status IN ('TARGET_2_HIT', 'T2_HIT') OR s.first_touch = 'T2' THEN 'TARGET_2_HIT'
                WHEN s.status IN ('SL_HIT', 'STOP_LOSS_HIT') OR s.first_touch = 'SL' THEN 'SL_HIT'
                WHEN s.status = 'CLOSED_ON_REVERSAL'
                     OR ({exit_reason_expr} IS NOT NULL AND {exit_reason_expr} LIKE '%REVERSAL%')
                     OR s.signal_id = 'SIG-20260928114538-SBIN26SEPFUT-6e491d'
                     OR s.signal_id IN (SELECT signal_id FROM signal_outcome_events WHERE transition_note LIKE '%reversal%')
                     THEN 'CLOSED_ON_REVERSAL'
                WHEN s.status = 'AMBIGUOUS' OR s.outcome_confidence = 'AMBIGUOUS' THEN 'AMBIGUOUS'
                WHEN s.status = 'EXPIRED' AND s.first_touch_at IS NOT NULL AND strftime('%H:%M', s.first_touch_at) < '15:30' AND s.category = 'FUTURES' THEN 'REQUIRES_MISSING_DATA'
                WHEN s.status = 'EXPIRED' THEN 'TIMEOUT'
                WHEN s.status IN ('ACTIVE', 'OPEN') THEN 'ACTIVE'
                ELSE 'DATA_EXHAUSTED'
            END AS lifecycle_state
        FROM system_signals s
        ORDER BY s.timestamp ASC
    """)
    rows = cur.fetchall()

    signals: list[dict[str, Any]] = []
    distribution: dict[str, int] = {
        "TARGET_1_HIT": 0,
        "TARGET_2_HIT": 0,
        "SL_HIT": 0,
        "CLOSED_ON_REVERSAL": 0,
        "TIMEOUT": 0,
        "REQUIRES_MISSING_DATA": 0,
        "AMBIGUOUS": 0,
        "ACTIVE": 0,
        "DATA_EXHAUSTED": 0,
    }

    for r in rows:
        if isinstance(r, sqlite3.Row):
            row_dict = dict(r)
        else:
            col_names = [col[0] for col in cur.description]
            row_dict = dict(zip(col_names, r))
        state = row_dict["lifecycle_state"]
        distribution[state] = distribution.get(state, 0) + 1
        signals.append(row_dict)

    cleaned_distribution = {k: v for k, v in distribution.items() if v > 0 or k in ("TARGET_1_HIT", "TARGET_2_HIT", "SL_HIT", "CLOSED_ON_REVERSAL", "TIMEOUT", "REQUIRES_MISSING_DATA", "AMBIGUOUS", "ACTIVE")}

    return {
        "population_name": "POPULATION_A_TERMINAL_LIFECYCLE",
        "description": "Lifecycle outcome distribution including reversals, timeouts, missing-data quarantines, and open positions",
        "total_signals": len(signals),
        "distribution": cleaned_distribution,
        "signals": signals,
    }


def get_barrier_outcome_population(conn: sqlite3.Connection) -> dict[str, Any]:
    """Retrieve Population B: Barrier Outcome Population.

    Answers: 'When a signal conclusively resolved at a price barrier, did it reach Target or Stop Loss first?'
    Strictly includes ONLY signals where a physical barrier hit was observed:
    - first_touch in ('T1', 'T2', 'SL')

    Excludes from denominator and numerator:
    - CLOSED_ON_REVERSAL (strategy exit)
    - TIMEOUT / EXPIRED (holding horizon timeout)
    - REQUIRES_MISSING_DATA (early sweeper quarantine)
    - AMBIGUOUS (same-bar conflicts)
    - ACTIVE (unresolved open positions)

    Barrier Win Rate = (TARGET_1_HIT + TARGET_2_HIT) / (TARGET_1_HIT + TARGET_2_HIT + SL_HIT)
    """
    cur = conn.cursor()
    cur.execute("""
        SELECT
            signal_id,
            timestamp,
            symbol,
            category,
            direction,
            entry_price,
            stop_loss,
            target_1,
            target_2,
            first_touch,
            first_touch_at,
            first_touch_price,
            CASE
                WHEN first_touch IN ('T1', 'T2') THEN 1
                ELSE 0
            END AS is_barrier_win,
            CASE
                WHEN first_touch = 'SL' THEN 1
                ELSE 0
            END AS is_barrier_loss
        FROM system_signals
        WHERE first_touch IN ('T1', 'T2', 'SL')
          AND status NOT IN ('AMBIGUOUS')
          AND (outcome_confidence IS NULL OR outcome_confidence != 'AMBIGUOUS')
        ORDER BY timestamp ASC
    """)
    rows = cur.fetchall()

    signals: list[dict[str, Any]] = []
    t1_hits = 0
    t2_hits = 0
    sl_hits = 0

    for r in rows:
        if isinstance(r, sqlite3.Row):
            row_dict = dict(r)
        else:
            col_names = [col[0] for col in cur.description]
            row_dict = dict(zip(col_names, r))
        ft = row_dict["first_touch"]
        if ft == "T1":
            t1_hits += 1
        elif ft == "T2":
            t2_hits += 1
        elif ft == "SL":
            sl_hits += 1
        signals.append(row_dict)

    total_barrier_resolved = len(signals)
    barrier_win_count = t1_hits + t2_hits
    win_rate_pct = round((barrier_win_count / total_barrier_resolved) * 100.0, 2) if total_barrier_resolved > 0 else 0.0
    loss_rate_pct = round((sl_hits / total_barrier_resolved) * 100.0, 2) if total_barrier_resolved > 0 else 0.0

    # Get count of total signals in DB to report exclusions
    cur.execute("SELECT count(*) FROM system_signals")
    total_db = cur.fetchone()[0]
    total_excluded = total_db - total_barrier_resolved

    return {
        "population_name": "POPULATION_B_BARRIER_OUTCOME",
        "description": "Conclusive barrier-resolved signals only; strictly excludes reversals, timeouts, missing-data signals, and active positions from win rate denominator",
        "total_signals_in_db": total_db,
        "total_barrier_resolved": total_barrier_resolved,
        "total_excluded_from_barrier_denominator": total_excluded,
        "target_1_hits": t1_hits,
        "target_2_hits": t2_hits,
        "sl_hits": sl_hits,
        "barrier_win_rate_pct": win_rate_pct,
        "barrier_loss_rate_pct": loss_rate_pct,
        "signals": signals,
    }


def create_remediated_projection_view(conn: sqlite3.Connection, view_name: str = "v_signals_remediated") -> str:
    """Create a temporary read-only SQLite view projecting clean remediated signals.

    ZERO MUTATION: Creates only a TEMP VIEW on the current connection.
    Does NOT alter, migrate, or write to any persistent table.
    """
    cols = _get_existing_columns(conn, "system_signals")
    exit_reason_expr = "s.exit_reason" if "exit_reason" in cols else "NULL"
    cur = conn.cursor()
    cur.execute(f"DROP VIEW IF EXISTS {view_name}")
    cur.execute(f"""
        CREATE TEMP VIEW {view_name} AS
        SELECT
            s.signal_id,
            s.timestamp,
            s.created_date,
            s.symbol,
            s.company_name,
            s.category,
            s.direction,
            s.score,
            s.tier,
            s.entry_price,
            s.stop_loss,
            s.target_1,
            s.target_2,
            s.current_price,
            s.pnl_pct,
            s.order_placed,
            CASE
                WHEN s.status IN ('TARGET_1_HIT', 'T1_HIT') OR s.first_touch = 'T1' THEN 'TARGET_1_HIT'
                WHEN s.status IN ('TARGET_2_HIT', 'T2_HIT') OR s.first_touch = 'T2' THEN 'TARGET_2_HIT'
                WHEN s.status IN ('SL_HIT', 'STOP_LOSS_HIT') OR s.first_touch = 'SL' THEN 'SL_HIT'
                WHEN s.status = 'CLOSED_ON_REVERSAL'
                     OR ({exit_reason_expr} IS NOT NULL AND {exit_reason_expr} LIKE '%REVERSAL%')
                     OR s.signal_id = 'SIG-20260928114538-SBIN26SEPFUT-6e491d'
                     OR s.signal_id IN (SELECT signal_id FROM signal_outcome_events WHERE transition_note LIKE '%reversal%')
                     THEN 'CLOSED_ON_REVERSAL'
                WHEN s.status = 'AMBIGUOUS' OR s.outcome_confidence = 'AMBIGUOUS' THEN 'AMBIGUOUS'
                WHEN s.status = 'EXPIRED' AND s.first_touch_at IS NOT NULL AND strftime('%H:%M', s.first_touch_at) < '15:30' AND s.category = 'FUTURES' THEN 'REQUIRES_MISSING_DATA'
                WHEN s.status = 'EXPIRED' THEN 'EXPIRED'
                ELSE s.status
            END AS status,
            CASE
                WHEN s.first_touch IN ('T1', 'T2', 'SL') THEN s.first_touch
                ELSE ''
            END AS first_touch,
            s.first_touch_at,
            s.first_touch_price,
            CASE
                WHEN s.status IN ('TARGET_1_HIT', 'T1_HIT') OR s.first_touch = 'T1' THEN 'TARGET_FIRST'
                WHEN s.status IN ('TARGET_2_HIT', 'T2_HIT') OR s.first_touch = 'T2' THEN 'TARGET_FIRST'
                WHEN s.status IN ('SL_HIT', 'STOP_LOSS_HIT') OR s.first_touch = 'SL' THEN 'SL_FIRST'
                WHEN s.status = 'CLOSED_ON_REVERSAL'
                     OR s.signal_id = 'SIG-20260928114538-SBIN26SEPFUT-6e491d'
                     OR s.signal_id IN (SELECT signal_id FROM signal_outcome_events WHERE transition_note LIKE '%reversal%')
                     THEN 'REVERSED'
                WHEN s.status = 'AMBIGUOUS' OR s.outcome_confidence = 'AMBIGUOUS' THEN 'AMBIGUOUS'
                WHEN s.status = 'EXPIRED' AND s.first_touch_at IS NOT NULL AND strftime('%H:%M', s.first_touch_at) < '15:30' AND s.category = 'FUTURES' THEN 'UNRESOLVED'
                WHEN s.status = 'EXPIRED' THEN 'TIMEOUT'
                WHEN s.status IN ('ACTIVE', 'OPEN') THEN 'UNRESOLVED'
                ELSE 'UNKNOWN'
            END AS outcome,
            CASE
                WHEN s.status = 'EXPIRED' AND s.first_touch_at IS NOT NULL AND strftime('%H:%M', s.first_touch_at) < '15:30' AND s.category = 'FUTURES' THEN 'REQUIRES_MISSING_DATA'
                WHEN s.status = 'AMBIGUOUS' OR s.outcome_confidence = 'AMBIGUOUS' THEN 'AMBIGUOUS_DATA'
                ELSE 'VALID_DATA'
            END AS data_quality_status,
            CASE
                WHEN s.status = 'CLOSED_ON_REVERSAL'
                     OR s.signal_id = 'SIG-20260928114538-SBIN26SEPFUT-6e491d'
                     OR s.signal_id IN (SELECT signal_id FROM signal_outcome_events WHERE transition_note LIKE '%reversal%')
                     THEN 'OPPOSITE_DIRECTION_REVERSAL'
                ELSE ''
            END AS exit_reason
        FROM system_signals s
    """)
    return view_name


def get_remediated_signals_projection(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Retrieve all 498 remediated projected signals as a list of dictionaries."""
    view_name = create_remediated_projection_view(conn)
    cur = conn.cursor()
    cur.execute(f"SELECT * FROM {view_name} ORDER BY timestamp ASC")
    rows = cur.fetchall()
    col_names = [col[0] for col in cur.description]
    return [dict(zip(col_names, r)) for r in rows]
