"""Read-only cross-surface consistency audit across all 498 production signals.

Runs strictly with SQLite URI read-only flag: file:db/signals_history.db?mode=ro
Governance: OPB-FINAL-PHASE-GOVERNANCE-001
"""

import sys
import os
sys.path.insert(0, os.getcwd())

import sqlite3
import json
from pathlib import Path
from core.signals.signal_tracker import SignalTracker

DB_URI = "file:db/signals_history.db?mode=ro"
DB_PATH = Path("db/signals_history.db")

def main():
    conn = sqlite3.connect(DB_URI, uri=True)
    cur = conn.cursor()

    cur.execute("SELECT count(*) FROM system_signals")
    total_signals = cur.fetchone()[0]

    cur.execute("SELECT status, count(*) FROM system_signals GROUP BY status")
    status_counts = dict(cur.fetchall())

    cur.execute("SELECT count(*) FROM signal_outcome_measurements")
    total_meas = cur.fetchone()[0]

    cur.execute("SELECT count(*) FROM signal_outcome_events")
    total_events = cur.fetchone()[0]

    cur.execute("SELECT signal_id, symbol, status, entry_price, stop_loss, target_1, target_2, current_price, pnl_pct, first_touch FROM system_signals")
    all_signals = cur.fetchall()
    conn.close()

    print(f"Total Signals: {total_signals}")
    print(f"Status breakdown: {status_counts}")
    print(f"Total Measurements: {total_meas}")
    print(f"Total Outcome Events: {total_events}")

    st = SignalTracker.get_instance(db_path=DB_PATH)

    # Detailed audit
    inconsistencies = []
    smcglobal_data = None
    historical_sl_audited = 0
    in_flight_t1_t2 = 0

    for row in all_signals:
        sig_id, sym, st_status, entry, sl, t1, t2, curr_p, pnl_pct, ft = row
        expl = st.get_signal_explanation(sig_id)
        if not expl:
            inconsistencies.append((sig_id, "Missing explanation"))
            continue

        lifecycle = expl.get("lifecycle", {})
        excursion = expl.get("excursion", {})
        obs_count = expl.get("forward_observation", {}).get("observation_count", 0)

        # Check SMCGLOBAL specifically
        if "SMC" in sym.upper() or "SMC" in sig_id.upper():
            smcglobal_data = {
                "signal_id": sig_id,
                "symbol": sym,
                "system_signals_status": st_status,
                "system_signals_pnl_pct": pnl_pct,
                "system_signals_first_touch": ft,
                "explanation_outcome_status": lifecycle.get("outcome_status"),
                "explanation_first_touch": lifecycle.get("first_touch"),
                "target_1_hit": excursion.get("target_1_hit"),
                "target_2_hit": excursion.get("target_2_hit"),
                "stop_loss_hit": excursion.get("stop_loss_hit"),
                "obs_count": obs_count,
            }

        # Check for cross-surface contradiction:
        # If system_signals says TARGET_2_HIT, does explanation say Target-2 or have target_2_hit == True?
        # Note: if measurements table is frozen in historical DB, does explanation reflect correctly or can it be reconciled?
        if st_status == "TARGET_2_HIT":
            in_flight_t1_t2 += 1
            # Check what explanation says
            if obs_count > 0 and not excursion.get("target_2_hit"):
                inconsistencies.append((sig_id, sym, "TARGET_2_HIT in system_signals but target_2_hit is False in explanation"))

        # Check historical SL_HIT signals
        if st_status == "SL_HIT" and obs_count == 0:
            historical_sl_audited += 1
            if not excursion.get("stop_loss_hit"):
                inconsistencies.append((sig_id, sym, "Historical SL_HIT has stop_loss_hit False"))
            if lifecycle.get("first_touch") != "SL":
                inconsistencies.append((sig_id, sym, f"Historical SL_HIT first_touch is {lifecycle.get('first_touch')}, expected SL"))

    print(f"\n--- SMCGLOBAL Fixture Audit ---")
    print(json.dumps(smcglobal_data, indent=2))

    print(f"\n--- Historical SL_HIT Signals Audited (obs_count == 0) ---")
    print(f"Total audited: {historical_sl_audited}")

    print(f"\n--- Inconsistencies Found: {len(inconsistencies)} ---")
    for inc in inconsistencies[:10]:
        print(inc)

if __name__ == "__main__":
    main()
