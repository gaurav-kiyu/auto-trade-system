import sys
sys.path.insert(0, ".")
import sqlite3
import json
import os
from core.signals.signal_tracker import SignalTracker
from core.signals.audit_db_safety import get_readonly_audit_connection, create_isolated_audit_db_copy

# Safe read-only immutable connection
conn = get_readonly_audit_connection("db/signals_history.db")
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# Safe isolated temporary copy for SignalTracker APIs
isolated_temp_db = create_isolated_audit_db_copy("db/signals_history.db")
tracker = SignalTracker(db_path=isolated_temp_db)

admin_data = tracker.get_admin_signal_analytics(timeframe="all", include_seed_samples=True)
signals_list = admin_data.get("signals", [])
print(f"Total signals in admin list: {len(signals_list)}")

mismatches = []
t2_mismatches = []
t1_mismatches = []
sl_mismatches = []
pnl_mismatches = []
ft_mismatches = []

for s in signals_list:
    sig_id = s["signal_id"]
    explanation = tracker.get_signal_explanation(sig_id)
    if not explanation:
        continue
    
    exc = explanation.get("excursion") or {}
    lc = explanation.get("lifecycle") or {}
    
    # List view fields:
    list_status = s["status"]
    list_pnl = s["pnl_pct"]
    
    # Detail / Explainability fields:
    detail_status = explanation.get("outcome_status") or lc.get("outcome_status")
    detail_t1_hit = exc.get("target_1_hit")
    detail_t2_hit = exc.get("target_2_hit")
    detail_sl_hit = exc.get("stop_loss_hit")
    detail_exit_p = lc.get("exit_price")
    detail_realized_r = exc.get("realized_r")
    detail_first_touch = lc.get("first_touch")
    
    # Check 1: list says TARGET_2_HIT but detail says T2 NO
    if list_status == "TARGET_2_HIT" and not detail_t2_hit:
        t2_mismatches.append({
            "signal_id": sig_id, "symbol": s["symbol"], "entry": s["entry_price"],
            "t1": s["target_1"], "t2": s["target_2"], "sl": s["stop_loss"],
            "list_status": list_status, "detail_t2_hit": detail_t2_hit,
            "detail_t1_hit": detail_t1_hit, "detail_status": detail_status,
            "list_pnl": list_pnl, "realized_r": detail_realized_r, "exit_price": detail_exit_p,
            "first_touch": s.get("first_touch")
        })

    # Check 2: list says TARGET_1_HIT but detail says T1 NO
    if list_status == "TARGET_1_HIT" and not detail_t1_hit:
        t1_mismatches.append(sig_id)
        
    # Check 3: list says SL_HIT but detail says SL NO
    if list_status == "SL_HIT" and not detail_sl_hit:
        sl_mismatches.append(sig_id)

    # Check 5: list outcome differs from first_touch
    if s.get("first_touch") and list_status != s.get("first_touch"):
        ft_mismatches.append((sig_id, list_status, s.get("first_touch")))

print(f"\n--- DISCREPANCY COUNTS ---")
print(f"Total signals with explanation: {sum(1 for s in signals_list if tracker.get_signal_explanation(s['signal_id']))}")
print(f"1. list says TARGET_2 but detail says T2 NO: {len(t2_mismatches)}")
print(f"2. list says TARGET_1 but detail says T1 NO: {len(t1_mismatches)}")
print(f"3. list says SL but detail says SL NO: {len(sl_mismatches)}")
print(f"5. list status differs from first_touch: {len(ft_mismatches)}")

if t2_mismatches:
    print(f"\n=== REPRESENTATIVE T2 MISMATCHES ({len(t2_mismatches)}) ===")
    for m in t2_mismatches[:10]:
        print(json.dumps(m, indent=2))

conn.close()
if os.path.exists(isolated_temp_db):
    try:
        os.remove(isolated_temp_db)
    except Exception:
        pass
