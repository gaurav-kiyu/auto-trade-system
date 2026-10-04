"""OPB v2.60 — E5 Replay Execution Script.

Governing Standard: OPB-FINAL-PHASE-GOVERNANCE-001
Authorization: OPB v2.60 — E5 Offline Historical Candle Replay & Barrier Evaluation Authorization

Executes offline counterfactual replay across eligible Point-A candidate snapshots
under the pre-authorized 6 barrier models (M1–M6) and 6 discrete horizons.
Writes results exclusively to db/e5_research_results.db.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import logging
import sqlite3
import statistics
from pathlib import Path
import sys

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.research.e5_replay_engine import (
    CATEGORY_AUTHORIZED_HORIZONS,
    DEFAULT_E5_DB_PATH,
    E5_TELEMETRY_POPULATION,
    PRE_AUTHORIZED_HORIZONS,
    PRE_AUTHORIZED_MODELS,
    BarrierModel,
    E5DatabaseManager,
    E5ReplayEngine,
    HorizonSpec,
    ReplayCandle,
    ReplayEvaluationResult,
    classify_score_bucket,
    generate_candidate_obs_id,
    validate_e5_db_path,
)

_log = logging.getLogger("EXECUTE_E5_REPLAY")
_ROOT = Path(__file__).resolve().parent.parent
PROD_DB_PATH = _ROOT / "db" / "signals_history.db"


def run_e5_offline_replay() -> dict[str, Any]:
    """Execute complete E5 offline replay and produce structured analysis."""
    # 1. Verify production database immutability before execution
    prod_sha_before = hashlib.sha256(PROD_DB_PATH.read_bytes()).hexdigest()
    prod_size_before = PROD_DB_PATH.stat().st_size

    e5_db_path = DEFAULT_E5_DB_PATH
    db_mgr = E5DatabaseManager(db_path=e5_db_path)
    engine = E5ReplayEngine(db_manager=db_mgr)

    # 2. Extract setup-qualified candidate snapshots from local database (Read-Only)
    conn_ro = sqlite3.connect(f"file:{str(PROD_DB_PATH)}?mode=ro", uri=True)
    conn_ro.row_factory = sqlite3.Row
    try:
        cur_ro = conn_ro.cursor()
        cur_ro.execute("""
            SELECT
                s.signal_id,
                s.symbol,
                s.category,
                s.direction,
                s.score,
                s.entry_price,
                s.captured_at,
                s.features_json,
                s.score_components_json,
                s.market_regime,
                s.snapshot_hash
            FROM signal_prediction_snapshots s
            ORDER BY s.captured_at ASC
        """)
        raw_snapshots = [dict(r) for r in cur_ro.fetchall()]

        # Also load outcome measurements if present for contemporaneous MFE/MAE excursion verification
        cur_ro.execute("""
            SELECT
                m.signal_id,
                m.mfe,
                m.mae,
                m.mfe_pct,
                m.mae_pct,
                m.time_to_first_event_seconds,
                m.time_to_t1_seconds,
                m.time_to_sl_seconds,
                m.outcome
            FROM signal_outcome_measurements m
        """)
        measurements_map = {r["signal_id"]: dict(r) for r in cur_ro.fetchall()}

        # Load candle/tick event checkpoints from signal_outcome_events if available
        cur_ro.execute("""
            SELECT
                event_id,
                signal_id,
                observed_at,
                observed_price,
                hit_sl,
                hit_t1,
                hit_t2,
                transition_note
            FROM signal_outcome_events
            ORDER BY observed_at ASC
        """)
        events_by_signal: dict[str, list[dict[str, Any]]] = {}
        for ev in cur_ro.fetchall():
            s_id = ev["signal_id"]
            if s_id not in events_by_signal:
                events_by_signal[s_id] = []
            events_by_signal[s_id].append(dict(ev))
    finally:
        conn_ro.close()

    # 3. Filter and freeze candidate snapshots with valid ATR & entry price
    eligible_candidates: list[dict[str, Any]] = []
    excluded_candidates: list[dict[str, Any]] = []

    for snap in raw_snapshots:
        s_id = snap["signal_id"]
        sym = snap["symbol"]
        cat = snap["category"]
        direction = snap["direction"]
        score = int(snap["score"])
        entry = float(snap["entry_price"])
        cap_at = str(snap["captured_at"])
        mkt_date = cap_at[:10]
        cyc_id = f"CYC-{cap_at.replace('-', '').replace(':', '')[:15]}"

        atr_val: float | None = None
        if snap.get("features_json"):
            try:
                feat = json.loads(snap["features_json"])
                if feat.get("atr") and float(feat["atr"]) > 0:
                    atr_val = float(feat["atr"])
            except Exception:
                pass

        # Deterministic Point-A observation ID (E4.2.2 specification)
        obs_id = generate_candidate_obs_id(
            market_date=mkt_date,
            cycle_id=cyc_id,
            symbol=sym,
            direction=direction,
            candidate_timestamp=cap_at,
            entry_price=entry,
        )

        cand_record = {
            "candidate_obs_id": obs_id,
            "signal_id": s_id,
            "market_date": mkt_date,
            "cycle_id": cyc_id,
            "symbol": sym,
            "direction": direction,
            "category": cat,
            "score": score,
            "entry_price": entry,
            "atr": atr_val,
            "candidate_timestamp": cap_at,
            "snapshot_hash": snap["snapshot_hash"],
            "features_json": snap["features_json"],
            "score_components_json": snap["score_components_json"],
            "market_regime": snap["market_regime"],
        }

        if atr_val is not None and atr_val > 0 and entry > 0:
            eligible_candidates.append(cand_record)
        else:
            excluded_candidates.append({**cand_record, "exclusion_reason": "MISSING_OR_ZERO_ATR"})

    # 4. Construct candle maps from available historical price checkpoint observations
    # Rule 5: Use ONLY genuine market data. If 1m completed candles are missing,
    # evaluate available checkpoints or classify as INSUFFICIENT_FORWARD_DATA.
    symbol_candles_map: dict[str, list[ReplayCandle]] = {}
    for cand in eligible_candidates:
        s_id = cand["signal_id"]
        sym = cand["symbol"]
        ev_list = events_by_signal.get(s_id, [])
        if ev_list:
            c_list = []
            for ev in ev_list:
                p = float(ev["observed_price"])
                c_list.append(ReplayCandle(
                    timestamp=ev["observed_at"],
                    open=p,
                    high=p,
                    low=p,
                    close=p,
                    volume=0.0,
                ))
            symbol_candles_map[sym] = c_list

    # 5. Clear old results and execute replay matrix across authorized category horizons
    db_mgr.clear_results()
    models = list(PRE_AUTHORIZED_MODELS.values())
    horizons = list(PRE_AUTHORIZED_HORIZONS.values())
    evaluation_results = engine.execute_replay_matrix(
        candidates=eligible_candidates,
        symbol_candles_map=symbol_candles_map,
        models=models,
        horizons=horizons,
        enforce_category_horizons=True,
    )
    aggregations = engine.compute_aggregations()

    # 7. Verify production database immutability after execution
    prod_sha_after = hashlib.sha256(PROD_DB_PATH.read_bytes()).hexdigest()
    prod_size_after = PROD_DB_PATH.stat().st_size
    assert prod_sha_before == prod_sha_after, "FATAL: Production DB altered during E5 execution!"
    assert prod_size_before == prod_size_after, "FATAL: Production DB size changed!"

    return {
        "production_db_sha_before": prod_sha_before,
        "production_db_sha_after": prod_sha_after,
        "production_db_size_before": prod_size_before,
        "production_db_size_after": prod_size_after,
        "total_snapshots_examined": len(raw_snapshots),
        "eligible_candidates_count": len(eligible_candidates),
        "excluded_candidates_count": len(excluded_candidates),
        "total_evaluations_recorded": len(evaluation_results),
        "aggregations": aggregations,
        "category_counts": {
            cat: sum(1 for c in eligible_candidates if c["category"] == cat)
            for cat in set(c["category"] for c in eligible_candidates)
        },
    }


if __name__ == "__main__":
    results = run_e5_offline_replay()
    print("E5 Replay Execution Summary:")
    print(f"Total Eligible Candidates: {results['eligible_candidates_count']}")
    print(f"Total Excluded Candidates: {results['excluded_candidates_count']}")
    print(f"Total Evaluations Recorded: {results['total_evaluations_recorded']}")
    print(f"Production DB SHA-256 Before: {results['production_db_sha_before']}")
    print(f"Production DB SHA-256 After:  {results['production_db_sha_after']}")
    print("All Invariants Verified Pristine.")
