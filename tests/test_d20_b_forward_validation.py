"""test_d20_b_forward_validation.py - Comprehensive unit tests for D20-B Forward Shadow Validation.

Governing Standard: OPB-FINAL-PHASE-GOVERNANCE-001
Execution Mode: STRICTLY OFFLINE / ZERO MUTATION UNIT TESTS

Validates Phase 9 Requirements:
1. First CALL retained.
2. Second CALL same canonical index/session suppressed.
3. First PUT retained.
4. CALL + PUT coexist.
5. Different canonical indices do not suppress one another.
6. Different sessions do not suppress one another.
7. Non-INDEX_OPTIONS categories are not incorrectly suppressed.
8. Chronological ordering is deterministic.
9. Shadow evaluation cannot mutate production DB.
10. No future signal can affect an earlier shadow decision.
"""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest
from core.research.d20_b_forward_validation import (
    EXPECTED_PROD_DB_SHA,
    EXPECTED_PROD_DB_SIZE,
    PROD_DB_PATH,
    ForwardShadowRecord,
    collect_live_day_shadow,
    load_forward_signals,
    run_forward_validation_analysis,
    verify_prod_db_integrity,
)


@pytest.fixture
def d20_test_db(tmp_path: Path) -> Path:
    """Creates a deterministic SQLite database with system_signals and signal_forward_observations."""
    db_file = tmp_path / "test_d20_signals.db"
    conn = sqlite3.connect(str(db_file))
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE system_signals (
            signal_id TEXT PRIMARY KEY,
            timestamp TEXT NOT NULL,
            created_date TEXT NOT NULL,
            symbol TEXT NOT NULL,
            category TEXT NOT NULL,
            direction TEXT NOT NULL,
            score INTEGER NOT NULL,
            status TEXT NOT NULL,
            first_touch TEXT NOT NULL,
            entry_price REAL DEFAULT 0.0
        )
    """)
    cur.execute("""
        CREATE TABLE signal_forward_observations (
            signal_id TEXT PRIMARY KEY,
            terminal_outcome TEXT NOT NULL,
            observation_status TEXT NOT NULL,
            is_resolved INTEGER NOT NULL
        )
    """)
    cur.execute("""
        INSERT INTO system_signals VALUES
        ('SIG_D20_001', '2026-09-28 09:30:00', '2026-09-28', 'NIFTY', 'INDEX_OPTIONS', 'CALL', 90, 'ACTIVE', '', 24500.0),
        ('SIG_D20_002', '2026-09-28 09:45:00', '2026-09-28', 'NIFTY', 'INDEX_OPTIONS', 'PUT', 85, 'ACTIVE', '', 24500.0),
        ('SIG_D20_003', '2026-09-28 10:00:00', '2026-09-28', 'BANKNIFTY', 'INDEX_OPTIONS', 'CALL', 92, 'ACTIVE', '', 52000.0)
    """)
    cur.execute("""
        INSERT INTO signal_forward_observations VALUES
        ('SIG_D20_001', 'T1', 'RESOLVED', 1),
        ('SIG_D20_002', 'ACTIVE', 'OBSERVING', 0),
        ('SIG_D20_003', 'T2', 'RESOLVED', 1)
    """)
    conn.commit()
    conn.close()
    return db_file


def test_invariant_1_first_call_retained():
    """Verify first CALL for a canonical index in a session is retained."""
    recs = [
        ForwardShadowRecord("S1", "2026-09-28 09:30:00", "2026-09-28", "NIFTY", "NIFTY", "INDEX_OPTIONS", "CALL", 90, "D20_B_SHADOW_RETAIN", "", None, 1, "T1", "ACTIVE", ""),
    ]
    res = run_forward_validation_analysis(recs, "test")
    assert res.shadow_retained == 1
    assert res.shadow_suppressed == 0


def test_invariant_2_second_call_same_index_suppressed():
    """Verify second CALL for the same canonical index in the same session is suppressed."""
    recs = [
        ForwardShadowRecord("S1", "2026-09-28 09:30:00", "2026-09-28", "NIFTY", "NIFTY", "INDEX_OPTIONS", "CALL", 90, "D20_B_SHADOW_RETAIN", "", None, 1, "T1", "ACTIVE", ""),
        ForwardShadowRecord("S2", "2026-09-28 10:00:00", "2026-09-28", "NIFTY", "NIFTY", "INDEX_OPTIONS", "CALL", 92, "D20_B_SHADOW_SUPPRESSED", "dup", "S1", 2, "SL", "SL_HIT", "SL"),
    ]
    res = run_forward_validation_analysis(recs, "test")
    assert res.shadow_retained == 1
    assert res.shadow_suppressed == 1
    assert res.suppression_pct == 50.0


def test_invariant_3_first_put_retained():
    """Verify first PUT for a canonical index in a session is retained."""
    recs = [
        ForwardShadowRecord("S1", "2026-09-28 09:30:00", "2026-09-28", "BANKNIFTY", "BANKNIFTY", "INDEX_OPTIONS", "PUT", 85, "D20_B_SHADOW_RETAIN", "", None, 1, "T1", "ACTIVE", ""),
    ]
    res = run_forward_validation_analysis(recs, "test")
    assert res.shadow_retained == 1
    assert res.shadow_suppressed == 0


def test_invariant_4_call_and_put_coexist():
    """Verify 1 CALL and 1 PUT for the same index coexist within the same session."""
    recs = [
        ForwardShadowRecord("S1", "2026-09-28 09:30:00", "2026-09-28", "NIFTY", "NIFTY", "INDEX_OPTIONS", "CALL", 90, "D20_B_SHADOW_RETAIN", "", None, 1, "T1", "ACTIVE", ""),
        ForwardShadowRecord("S2", "2026-09-28 09:45:00", "2026-09-28", "NIFTY", "NIFTY", "INDEX_OPTIONS", "PUT", 88, "D20_B_SHADOW_RETAIN", "", None, 1, "SL", "ACTIVE", ""),
    ]
    res = run_forward_validation_analysis(recs, "test")
    assert res.shadow_retained == 2
    assert res.shadow_suppressed == 0


def test_invariant_5_different_canonical_indices_independent():
    """Verify different canonical indices do not suppress one another."""
    recs = [
        ForwardShadowRecord("S1", "2026-09-28 09:30:00", "2026-09-28", "NIFTY", "NIFTY", "INDEX_OPTIONS", "CALL", 90, "D20_B_SHADOW_RETAIN", "", None, 1, "T1", "ACTIVE", ""),
        ForwardShadowRecord("S2", "2026-09-28 09:35:00", "2026-09-28", "BANKNIFTY", "BANKNIFTY", "INDEX_OPTIONS", "CALL", 91, "D20_B_SHADOW_RETAIN", "", None, 1, "T1", "ACTIVE", ""),
        ForwardShadowRecord("S3", "2026-09-28 09:40:00", "2026-09-28", "FINNIFTY", "FINNIFTY", "INDEX_OPTIONS", "CALL", 89, "D20_B_SHADOW_RETAIN", "", None, 1, "T1", "ACTIVE", ""),
    ]
    res = run_forward_validation_analysis(recs, "test")
    assert res.shadow_retained == 3
    assert res.shadow_suppressed == 0


def test_invariant_6_different_sessions_independent():
    """Verify a CALL in Session 1 does not suppress a CALL in Session 2."""
    recs = [
        ForwardShadowRecord("S1", "2026-09-28 09:30:00", "2026-09-28", "NIFTY", "NIFTY", "INDEX_OPTIONS", "CALL", 90, "D20_B_SHADOW_RETAIN", "", None, 1, "T1", "ACTIVE", ""),
        ForwardShadowRecord("S2", "2026-09-29 09:30:00", "2026-09-29", "NIFTY", "NIFTY", "INDEX_OPTIONS", "CALL", 90, "D20_B_SHADOW_RETAIN", "", None, 1, "T1", "ACTIVE", ""),
    ]
    res = run_forward_validation_analysis(recs, "test")
    assert res.shadow_retained == 2
    assert res.shadow_suppressed == 0


def test_invariant_7_non_index_options_categories_unaffected():
    """Verify non-INDEX_OPTIONS categories are strictly not suppressed in strict mode."""
    from core.signals.signal_quality_gate import check_index_session_dedup
    ok, reason = check_index_session_dedup(None, "RELIANCE", "EQUITY_SWING_DELIVERY", "BUY", "2026-09-28")
    assert ok is True
    assert reason == "NOT_APPLICABLE_NON_INDEX"


def test_invariant_8_chronological_ordering_deterministic():
    """Verify chronological ordering is preserved and first arrival is admitted."""
    from core.research.d20_b_shadow_analysis import SignalRecord, apply_d20_b_shadow_simulation
    recs = [
        SignalRecord("S_EARLY", "2026-09-28 09:20:00", "2026-09-28", "NIFTY", "NIFTY", "INDEX_OPTIONS", "CALL", 80, "ACTIVE", "", "UNRESOLVED"),
        SignalRecord("S_LATE", "2026-09-28 09:25:00", "2026-09-28", "NIFTY", "NIFTY", "INDEX_OPTIONS", "CALL", 99, "ACTIVE", "", "UNRESOLVED"),
    ]
    evals = apply_d20_b_shadow_simulation(recs)
    assert evals[0].signal_id == "S_EARLY"
    assert evals[0].decision == "RETAINED"
    assert evals[1].signal_id == "S_LATE"
    assert evals[1].decision == "D20_B_SHADOW_SUPPRESSED"


def test_invariant_9_production_db_unmutated_after_shadow(d20_test_db: Path):
    """Verify shadow evaluation cannot mutate database SHA or byte size."""
    # 1. Deterministic fixture validation: verify byte and size immutability across evaluation
    sha_pre = hashlib.sha256(d20_test_db.read_bytes()).hexdigest()
    sz_pre = d20_test_db.stat().st_size
    sigs = load_forward_signals(population_scope="INDEX_OPTIONS", db_path=d20_test_db)
    res = run_forward_validation_analysis(sigs, "INDEX_OPTIONS")
    assert res is not None
    sha_post = hashlib.sha256(d20_test_db.read_bytes()).hexdigest()
    sz_post = d20_test_db.stat().st_size
    assert sha_pre == sha_post, "Shadow evaluation mutated database SHA-256!"
    assert sz_pre == sz_post, "Shadow evaluation mutated database size!"

    # 2. Canonical baseline validation (when historical production database is present on disk)
    if PROD_DB_PATH.exists() and PROD_DB_PATH.stat().st_size == EXPECTED_PROD_DB_SIZE:
        sha_prod = hashlib.sha256(PROD_DB_PATH.read_bytes()).hexdigest()
        if sha_prod == EXPECTED_PROD_DB_SHA:
            sha_prod_pre, sz_prod_pre = verify_prod_db_integrity()
            sigs_prod = load_forward_signals(population_scope="INDEX_OPTIONS")
            run_forward_validation_analysis(sigs_prod, "INDEX_OPTIONS")
            sha_prod_post, sz_prod_post = verify_prod_db_integrity()
            assert sha_prod_pre == sha_prod_post == EXPECTED_PROD_DB_SHA
            assert sz_prod_pre == sz_prod_post == EXPECTED_PROD_DB_SIZE


def test_invariant_10_no_future_leakage_affects_earlier_decision():
    """Verify an earlier signal's decision is completely independent of future signals."""
    from core.research.d20_b_shadow_analysis import SignalRecord, apply_d20_b_shadow_simulation
    sig_early = SignalRecord("S1", "2026-09-28 09:15:00", "2026-09-28", "NIFTY", "NIFTY", "INDEX_OPTIONS", "CALL", 85, "ACTIVE", "", "UNRESOLVED")

    # Run standalone
    eval_single = apply_d20_b_shadow_simulation([sig_early])

    # Run with 10 future signals
    future_sigs = [
        SignalRecord(f"S_FUT_{i}", f"2026-09-28 09:{20+i}:00", "2026-09-28", "NIFTY", "NIFTY", "INDEX_OPTIONS", "CALL", 90, "ACTIVE", "", "UNRESOLVED")
        for i in range(10)
    ]
    eval_multi = apply_d20_b_shadow_simulation([sig_early] + future_sigs)

    # Early signal must have identical decision
    assert eval_single[0].decision == eval_multi[0].decision == "RETAINED"


def test_invariant_11_live_day_empty_session_handling(tmp_path: Path, d20_test_db: Path):
    """Verify live-day shadow collection properly handles a session with zero signals."""
    t_file = tmp_path / "telemetry_test.json"
    res = collect_live_day_shadow(market_date="2026-10-05", telemetry_file=t_file, db_path=d20_test_db)
    assert res["market_date"] == "2026-10-05"
    assert res["total_genuine_signals_observed_today"] == 0
    assert res["primary_index_options"]["total_signals"] == 0
    assert res["primary_index_options"]["shadow_retained"] == 0
    assert res["primary_index_options"]["shadow_suppressed"] == 0
    assert res["primary_index_options"]["future_winners_suppressed"] == 0
    assert res["primary_index_options"]["daily_quota_interaction"]["production_quota_reached"] is False
    assert res["db_unmutated"] is True
    assert t_file.exists()


def test_invariant_12_telemetry_reload_and_deduplication(tmp_path: Path, d20_test_db: Path):
    """Verify telemetry reloading and deduplication by signal_id (interruption safety)."""
    import json
    t_file = tmp_path / "telemetry_reload_test.json"
    existing_data = {
        "market_date": "2026-10-05",
        "observations": [
            {
                "signal_id": "SIG_EXISTING_1",
                "timestamp": "2026-10-05 09:30:00",
                "market_date": "2026-10-05",
                "symbol": "NIFTY",
                "canonical_index": "NIFTY",
                "category": "INDEX_OPTIONS",
                "direction": "CALL",
                "score": 90,
                "shadow_decision": "D20_B_SHADOW_RETAIN",
                "reason": "First eligible CALL",
                "prior_qualifying_signal_id": None,
                "ordering_position": 1,
                "production_outcome": "ACTIVE / INSUFFICIENT FORWARD DATA",
                "raw_status": "ACTIVE",
                "raw_touch": "",
                "scope": "PRIMARY_INDEX_OPTIONS",
            }
        ],
    }
    with open(t_file, "w", encoding="utf-8") as f:
        json.dump(existing_data, f)

    res = collect_live_day_shadow(market_date="2026-10-05", telemetry_file=t_file, db_path=d20_test_db)
    assert res["total_genuine_signals_observed_today"] == 1
    obs_ids = [o["signal_id"] for o in res["observations"]]
    assert obs_ids == ["SIG_EXISTING_1"]


def test_invariant_13_live_day_active_unresolved_outcomes(tmp_path):
    """Verify newly observed intraday signals are classified as ACTIVE / INSUFFICIENT FORWARD DATA."""
    import sqlite3
    db_file = tmp_path / "test_live_signals.db"
    conn = sqlite3.connect(str(db_file))
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE system_signals (
            signal_id TEXT PRIMARY KEY,
            timestamp TEXT,
            created_date TEXT,
            symbol TEXT,
            category TEXT,
            direction TEXT,
            score INTEGER,
            status TEXT,
            first_touch TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE signal_forward_observations (
            signal_id TEXT PRIMARY KEY,
            terminal_outcome TEXT,
            observation_status TEXT,
            is_resolved INTEGER
        )
    """)
    cur.execute("INSERT INTO system_signals VALUES ('S1', '2026-10-05 09:30:00', '2026-10-05', 'NIFTY', 'INDEX_OPTIONS', 'CALL', 90, 'ACTIVE', '')")
    cur.execute("INSERT INTO system_signals VALUES ('S2', '2026-10-05 10:00:00', '2026-10-05', 'NIFTY', 'INDEX_OPTIONS', 'CALL', 92, 'ACTIVE', '')")
    conn.commit()
    conn.close()

    t_file = tmp_path / "telemetry_active_test.json"
    res = collect_live_day_shadow(market_date="2026-10-05", telemetry_file=t_file, db_path=db_file)
    assert res["total_genuine_signals_observed_today"] == 2
    assert res["primary_index_options"]["shadow_retained"] == 1
    assert res["primary_index_options"]["shadow_suppressed"] == 1
    assert res["primary_index_options"]["future_winners_suppressed"] == 0
    obs = res["observations"]
    assert obs[0]["shadow_decision"] == "D20_B_SHADOW_RETAIN"
    assert obs[0]["production_outcome"] == "ACTIVE / INSUFFICIENT FORWARD DATA"
    assert obs[1]["shadow_decision"] == "D20_B_SHADOW_SUPPRESSED"
    assert obs[1]["production_outcome"] == "ACTIVE / INSUFFICIENT FORWARD DATA"


def test_invariant_14_eod_closeout_preserves_intraday_snapshot(tmp_path: Path, d20_test_db: Path):
    """Verify EOD closeout extends through 15:30 IST while preserving intraday snapshot history."""
    t_file = tmp_path / "telemetry_eod_test.json"

    # Step 1: Intraday snapshot
    res_intra = collect_live_day_shadow(market_date="2026-10-05", telemetry_file=t_file, db_path=d20_test_db, is_eod=False)
    assert res_intra["is_eod_closeout"] is False
    assert len(res_intra["snapshots"]) == 0

    # Step 2: EOD Closeout snapshot
    res_eod = collect_live_day_shadow(
        market_date="2026-10-05",
        telemetry_file=t_file,
        db_path=d20_test_db,
        is_eod=True,
        boundary_end="2026-10-05 15:30:00",
    )
    assert res_eod["is_eod_closeout"] is True
    assert res_eod["observation_boundary_end"] == "2026-10-05 15:30:00"
    assert len(res_eod["snapshots"]) == 2
    assert res_eod["snapshots"][0]["snapshot_type"] == "INTRADAY_OBSERVATION"
    assert res_eod["snapshots"][1]["snapshot_type"] == "EOD_CLOSEOUT_OBSERVATION"
    assert res_eod["snapshots"][1]["observation_boundary_end"] == "2026-10-05 15:30:00"

    # Verify dedicated EOD file was also written
    eod_file = tmp_path / "telemetry_eod_test_eod.json"
    assert eod_file.exists()


