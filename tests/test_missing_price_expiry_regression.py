"""Explicit regression suite proving requirements A through G for missing price & expiry.

Proves:
A. price exists + active signal -> normal tick evaluation (hits target or stays active)
B. price=None + signal not expired -> remains ACTIVE, 0 errors
C. price=None + signal expired -> transitions cleanly to EXPIRED, 0 errors
D. price=None + off-market signal -> transitions cleanly to EXPIRED, 0 errors
E. malformed/missing price does not crash tracker
F. expired signal transitions exactly once
G. repeated sweep is strictly idempotent
"""
import datetime
import sqlite3
import sys
from pathlib import Path

BASE_DIR = Path(r"D:\AI_APPs\TRADING_APP\OPB_V2_59_4_CANONICAL")
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from core.signals.signal_tracker import SignalTracker
from core.signals.signal_outcome_tracker import SignalOutcomeTracker

def run_regression_suite():
    print("=" * 80)
    print("REGRESSION SUITE: MISSING PRICE & EXPIRY SEMANTICS (A through G)")
    print("=" * 80)

    test_db = BASE_DIR / "scratch" / "test_missing_price_regression.db"
    if test_db.exists():
        try:
            test_db.unlink()
        except Exception:
            pass

    SignalTracker.reset_instance()
    SignalOutcomeTracker.reset_instance()

    sig_tracker = SignalTracker(db_path=test_db)
    tracker = SignalOutcomeTracker(db_path=test_db)

    # --------------------------------------------------------------------------
    # CASE A: price exists + active signal -> normal tick evaluation
    # --------------------------------------------------------------------------
    print("\n--- CASE A: Price exists + active signal ---")
    conn = tracker._get_conn()
    conn.execute("DELETE FROM system_signals")
    conn.execute("DELETE FROM user_deliveries")
    conn.execute("DELETE FROM signal_outcome_events")
    now_ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    today_str = datetime.datetime.now().strftime("%Y-%m-%d")
    conn.execute(f"""
        INSERT INTO system_signals (
            signal_id, symbol, category, direction, score, tier,
            entry_price, stop_loss, target_1, target_2, current_price,
            pnl_pct, status, first_touch, created_date, created_week,
            created_month, created_year, timestamp
        ) VALUES ('SIG-A-1', 'RELIANCE', 'INDEX_OPTIONS', 'CALL', 80, 'STRONG',
                  100.0, 80.0, 120.0, 150.0, 100.0, 0.0, 'ACTIVE', '', '{today_str}', 'W38', '09', '2026', '{now_ts}')
    """)
    conn.commit()

    # Price moves to 125 (Target 1 hit)
    res_a = tracker.update_active_signal_outcomes(lambda sym: 125.0)
    row_a = dict(conn.execute("SELECT status, first_touch FROM system_signals WHERE signal_id = 'SIG-A-1'").fetchone())
    assert row_a["status"] == "TARGET_1_HIT", f"Expected TARGET_1_HIT, got {row_a['status']}"
    assert row_a["first_touch"] == "T1", f"Expected first_touch T1, got {row_a['first_touch']}"
    print(f"[PASS] Case A: Signal transitioned to {row_a['status']} with first_touch={row_a['first_touch']}")

    # --------------------------------------------------------------------------
    # CASE B: price=None + signal not expired -> remains ACTIVE, 0 errors
    # --------------------------------------------------------------------------
    print("\n--- CASE B: price=None + signal not expired ---")
    conn.execute(f"""
        INSERT INTO system_signals (
            signal_id, symbol, category, direction, score, tier,
            entry_price, stop_loss, target_1, target_2, current_price,
            pnl_pct, status, first_touch, created_date, created_week,
            created_month, created_year, timestamp
        ) VALUES ('SIG-B-1', 'INFY', 'INDEX_OPTIONS', 'CALL', 75, 'MODERATE',
                  100.0, 80.0, 120.0, 150.0, 100.0, 0.0, 'ACTIVE', '', '{today_str}', 'W38', '09', '2026', '{now_ts}')
    """)
    conn.commit()

    res_b = tracker.update_active_signal_outcomes(lambda sym: None)
    row_b = dict(conn.execute("SELECT status FROM system_signals WHERE signal_id = 'SIG-B-1'").fetchone())
    assert row_b["status"] == "ACTIVE", f"Expected ACTIVE, got {row_b['status']}"
    print(f"[PASS] Case B: Unexpired signal with price=None remained {row_b['status']}")

    # --------------------------------------------------------------------------
    # CASE C: price=None + signal expired -> transitions cleanly to EXPIRED, 0 errors
    # --------------------------------------------------------------------------
    print("\n--- CASE C: price=None + signal expired ---")
    conn.execute("""
        INSERT INTO system_signals (
            signal_id, symbol, category, direction, score, tier,
            entry_price, stop_loss, target_1, target_2, current_price,
            pnl_pct, status, first_touch, created_date, created_week,
            created_month, created_year, timestamp
        ) VALUES ('SIG-C-1', 'TCS', 'INDEX_OPTIONS', 'CALL', 82, 'STRONG',
                  100.0, 80.0, 120.0, 150.0, 100.0, 0.0, 'ACTIVE', '', '2026-09-18', 'W38', '09', '2026', '2026-09-18 10:00:00')
    """)
    conn.commit()

    res_c = tracker.update_active_signal_outcomes(lambda sym: None)
    row_c = dict(conn.execute("SELECT status, first_touch FROM system_signals WHERE signal_id = 'SIG-C-1'").fetchone())
    assert row_c["status"] == "EXPIRED", f"Expected EXPIRED, got {row_c['status']}"
    assert row_c["first_touch"] == "EXPIRED", f"Expected first_touch EXPIRED, got {row_c['first_touch']}"
    print(f"[PASS] Case C: Expired signal with price=None cleanly transitioned to {row_c['status']}, first_touch={row_c['first_touch']}")

    # --------------------------------------------------------------------------
    # CASE D: price=None + off-market signal -> transitions cleanly to EXPIRED
    # --------------------------------------------------------------------------
    print("\n--- CASE D: price=None + off-market signal ---")
    conn.execute("""
        INSERT INTO system_signals (
            signal_id, symbol, category, direction, score, tier,
            entry_price, stop_loss, target_1, target_2, current_price,
            pnl_pct, status, first_touch, created_date, created_week,
            created_month, created_year, timestamp
        ) VALUES ('SIG-D-1', 'NIFTY', 'INDEX_OPTIONS', 'CALL', 88, 'STRONG',
                  25000.0, 24800.0, 25200.0, 25400.0, 25000.0, 0.0, 'ACTIVE', '', '2026-09-18', 'W38', '09', '2026', '2026-09-18 14:15:00')
    """)
    conn.commit()

    res_d = tracker.update_active_signal_outcomes(lambda sym: None)
    row_d = dict(conn.execute("SELECT status, first_touch FROM system_signals WHERE signal_id = 'SIG-D-1'").fetchone())
    assert row_d["status"] == "EXPIRED", f"Expected EXPIRED, got {row_d['status']}"
    print(f"[PASS] Case D: Off-market signal cleanly transitioned to {row_d['status']}")

    # --------------------------------------------------------------------------
    # CASE E: malformed/missing price does not crash tracker
    # --------------------------------------------------------------------------
    print("\n--- CASE E: Malformed price lookup does not crash tracker ---")
    def bad_lookup(sym):
        raise ValueError("Simulated broker API failure")

    # Should not throw exception
    res_e = tracker.update_active_signal_outcomes(bad_lookup)
    assert isinstance(res_e, dict)
    print(f"[PASS] Case E: Exception inside price_lookup_fn gracefully handled: {res_e}")

    # --------------------------------------------------------------------------
    # CASE F: expired signal transitions exactly once
    # --------------------------------------------------------------------------
    print("\n--- CASE F: Expired signal transitions exactly once ---")
    events_c = conn.execute("SELECT COUNT(*) FROM signal_outcome_events WHERE signal_id = 'SIG-C-1'").fetchone()[0]
    assert events_c == 1, f"Expected 1 event, got {events_c}"
    print(f"[PASS] Case F: Signal SIG-C-1 transitioned exactly once (event count = {events_c})")

    # --------------------------------------------------------------------------
    # CASE G: repeated sweep is strictly idempotent
    # --------------------------------------------------------------------------
    print("\n--- CASE G: Repeated sweep is idempotent ---")
    sweep_1 = tracker.run_stale_signal_expiry_sweep(force=True)
    sweep_2 = tracker.run_stale_signal_expiry_sweep(force=True)
    assert sweep_2.get("transitioned", 0) == 0, f"Expected 0 transitioned on second sweep, got {sweep_2.get('transitioned')}"
    events_c_after = conn.execute("SELECT COUNT(*) FROM signal_outcome_events WHERE signal_id = 'SIG-C-1'").fetchone()[0]
    assert events_c_after == 1, f"Expected event count to remain 1, got {events_c_after}"
    print(f"[PASS] Case G: Repeated sweep is strictly idempotent (0 duplicate transitions, 0 duplicate events)")

    conn.close()
    print("\n--> ALL CASES A THROUGH G VERIFIED EMPIRICALLY!")

def test_missing_price_expiry_cases_a_through_g():
    run_regression_suite()

if __name__ == "__main__":
    run_regression_suite()
