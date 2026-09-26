"""Phase B Test Suite: Signal Outcome Measurement Dataset & Analytical Validation.

Governance Authority: OPB-FINAL-PHASE-GOVERNANCE-001 / v2.60 Phase B Roadmap.

Verifies all mandatory Phase-B requirements:
1. CALL favorable movement produces positive MFE.
2. PUT favorable movement produces positive MFE.
3. CALL adverse movement produces positive MAE magnitude.
4. PUT adverse movement produces positive MAE magnitude.
5. MFE_R calculation is correct.
6. MAE_R calculation is correct.
7. T1 first-touch is preserved.
8. SL first-touch is preserved.
9. T1 and SL same-bar ambiguity is preserved.
10. T1 -> T2 progression is preserved.
11. T1 -> SL after T1 does not rewrite first-touch.
12. Missing price produces NO_DATA.
13. Invalid price does not enter calculations.
14. Time-to-event uses prediction timestamp.
15. Missing event timestamp produces NULL.
16. Realized R for CALL is correct.
17. Realized R for PUT is correct.
18. Invalid/zero initial risk does not produce division-by-zero or fabricated R.
19. Historical calculation is deterministic.
20. Re-running dataset construction is idempotent.
21. Prediction snapshot remains byte/value-for-value unchanged after outcome measurement.
22. No look-ahead: observations before T0 are ignored.
"""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import Any

import pytest

from core.datetime_ist import now_ist
from core.signals.signal_outcome_dataset import (
    CALCULATION_VERSION,
    SignalOutcomeDatasetService,
    calculate_directional_mfe_mae,
    calculate_realized_r,
    normalize_outcome_state,
    parse_timestamp,
)
from core.signals.signal_outcome_tracker import SignalOutcomeTracker
from core.signals.signal_tracker import SignalTracker


@pytest.fixture(autouse=True)
def _reset_singletons():
    SignalTracker.reset_instance()
    SignalOutcomeTracker.reset_instance()
    SignalOutcomeDatasetService.reset_instance()
    yield
    SignalTracker.reset_instance()
    SignalOutcomeTracker.reset_instance()
    SignalOutcomeDatasetService.reset_instance()


@pytest.fixture
def isolated_db(tmp_path: Path):
    db_file = tmp_path / "test_phase_b_dataset.db"
    tracker = SignalTracker(db_path=db_file)
    outcome_tracker = SignalOutcomeTracker(db_path=db_file)
    dataset_svc = SignalOutcomeDatasetService(db_path=db_file)

    conn = tracker._get_conn()
    conn.execute("DELETE FROM system_signals")
    conn.execute("DELETE FROM user_deliveries")
    conn.execute("DELETE FROM signal_outcome_events")
    conn.execute("DELETE FROM signal_prediction_snapshots")
    conn.execute("DELETE FROM signal_outcome_measurements")
    conn.commit()
    conn.close()

    return tracker, outcome_tracker, dataset_svc


class TestSignalOutcomeDataset:
    """Test suite for Phase B analytical outcome measurement dataset."""

    def test_01_call_favorable_movement_positive_mfe(self):
        """Req 1: CALL favorable movement produces positive MFE."""
        entry = 100.0
        prices = [98.0, 103.0, 105.5, 101.0]
        mfe, mae, mfe_pct, mae_pct = calculate_directional_mfe_mae("CALL", entry, prices)
        assert mfe == 5.5
        assert mfe_pct == 5.5

    def test_02_put_favorable_movement_positive_mfe(self):
        """Req 2: PUT favorable movement produces positive MFE."""
        entry = 200.0
        prices = [204.0, 192.0, 185.0, 195.0]
        mfe, mae, mfe_pct, mae_pct = calculate_directional_mfe_mae("PUT", entry, prices)
        # Favorable is entry - price = 200 - 185 = 15.0
        assert mfe == 15.0
        assert mfe_pct == 7.5

    def test_03_call_adverse_movement_positive_mae_magnitude(self):
        """Req 3: CALL adverse movement produces positive MAE magnitude."""
        entry = 100.0
        prices = [98.0, 96.5, 103.0]
        mfe, mae, mfe_pct, mae_pct = calculate_directional_mfe_mae("CALL", entry, prices)
        # Adverse is entry - price = 100 - 96.5 = 3.5
        assert mae == 3.5
        assert mae_pct == 3.5

    def test_04_put_adverse_movement_positive_mae_magnitude(self):
        """Req 4: PUT adverse movement produces positive MAE magnitude."""
        entry = 200.0
        prices = [206.0, 195.0, 190.0]
        mfe, mae, mfe_pct, mae_pct = calculate_directional_mfe_mae("PUT", entry, prices)
        # Adverse is price - entry = 206 - 200 = 6.0
        assert mae == 6.0
        assert mae_pct == 3.0

    def test_05_mfe_r_calculation_correctness(self, isolated_db):
        """Req 5: MFE_R calculation is correct (MFE / initial_risk)."""
        tracker, _, dataset_svc = isolated_db
        # Entry 1000, SL 950 (Risk 50), Target 1100
        sig_id = tracker.record_generated_signal({
            "symbol": "STOCK_A",
            "direction": "CALL",
            "price": 1000.0,
            "stop_loss": 950.0,
            "target_1": 1100.0,
            "target_2": 1150.0,
            "score": 85,
        })
        # Add event with price 1075 strictly after T0 (favorable 75.0 -> MFE_R = 75/50 = 1.5)
        post_t0 = (now_ist() + datetime.timedelta(minutes=5)).isoformat()
        conn = tracker._get_conn()
        conn.execute(
            "INSERT INTO signal_outcome_events (signal_id, observed_at, observed_price, hit_sl, hit_t1, hit_t2) "
            "VALUES (?, ?, 1075.0, 0, 0, 0)",
            (sig_id, post_t0),
        )
        conn.commit()
        conn.close()

        meas = dataset_svc.build_signal_outcome_measurement(sig_id)
        assert meas is not None
        assert meas["mfe"] == 75.0
        assert meas["initial_risk"] == 50.0
        assert meas["mfe_r"] == 1.5

    def test_06_mae_r_calculation_correctness(self, isolated_db):
        """Req 6: MAE_R calculation is correct (MAE / initial_risk)."""
        tracker, _, dataset_svc = isolated_db
        # Entry 1000, SL 950 (Risk 50)
        sig_id = tracker.record_generated_signal({
            "symbol": "STOCK_B",
            "direction": "CALL",
            "price": 1000.0,
            "stop_loss": 950.0,
            "target_1": 1100.0,
            "target_2": 1150.0,
            "score": 85,
        })
        # Add event with price 970 strictly after T0 (adverse 30.0 -> MAE_R = 30/50 = 0.6)
        post_t0 = (now_ist() + datetime.timedelta(minutes=5)).isoformat()
        conn = tracker._get_conn()
        conn.execute(
            "INSERT INTO signal_outcome_events (signal_id, observed_at, observed_price, hit_sl, hit_t1, hit_t2) "
            "VALUES (?, ?, 970.0, 0, 0, 0)",
            (sig_id, post_t0),
        )
        conn.commit()
        conn.close()

        meas = dataset_svc.build_signal_outcome_measurement(sig_id)
        assert meas is not None
        assert meas["mae"] == 30.0
        assert meas["initial_risk"] == 50.0
        assert meas["mae_r"] == 0.6

    def test_07_t1_first_touch_preserved(self, isolated_db):
        """Req 7: T1 first-touch produces TARGET_FIRST outcome."""
        tracker, outcome_tracker, dataset_svc = isolated_db
        sig_id = tracker.record_generated_signal({
            "symbol": "STOCK_C",
            "direction": "CALL",
            "price": 500.0,
            "stop_loss": 480.0,
            "target_1": 530.0,
            "target_2": 560.0,
            "score": 88,
        })
        outcome_tracker.update_active_signal_outcomes(lambda sym: 535.0)

        meas = dataset_svc.build_signal_outcome_measurement(sig_id)
        assert meas is not None
        assert meas["outcome"] == "TARGET_FIRST"
        assert meas["first_touch"] == "T1"
        assert meas["target_1_hit"] == 1
        assert meas["realized_r"] is not None
        assert meas["realized_r"] >= 1.5

    def test_08_sl_first_touch_preserved(self, isolated_db):
        """Req 8: SL first-touch produces SL_FIRST outcome."""
        tracker, outcome_tracker, dataset_svc = isolated_db
        sig_id = tracker.record_generated_signal({
            "symbol": "STOCK_D",
            "direction": "CALL",
            "price": 500.0,
            "stop_loss": 480.0,
            "target_1": 530.0,
            "target_2": 560.0,
            "score": 88,
        })
        # Hit SL exactly at 480.0
        outcome_tracker.update_active_signal_outcomes(lambda sym: 480.0)

        meas = dataset_svc.build_signal_outcome_measurement(sig_id)
        assert meas is not None
        assert meas["outcome"] == "SL_FIRST"
        assert meas["first_touch"] == "SL"
        assert meas["stop_loss_hit"] == 1
        assert meas["realized_r"] == -1.0

    def test_09_t1_and_sl_same_bar_ambiguity_preserved(self, isolated_db):
        """Req 9: T1 and SL hit on same bar is quarantined as AMBIGUOUS."""
        tracker, outcome_tracker, dataset_svc = isolated_db
        sig_id = tracker.record_generated_signal({
            "symbol": "STOCK_E",
            "direction": "CALL",
            "price": 100.0,
            "stop_loss": 90.0,
            "target_1": 110.0,
            "target_2": 120.0,
            "score": 85,
        })
        # Evaluate against a bar where High >= T1 and Low <= SL
        from core.signals.signal_outcome_tracker import SignalBar
        ambig_bar = SignalBar(open=100.0, high=115.0, low=85.0, close=102.0, timestamp="2026-09-26T10:15:00")
        conn = tracker._get_conn()
        cur = conn.cursor()
        cur.execute("SELECT * FROM system_signals WHERE signal_id = ?", (sig_id,))
        row = dict(cur.fetchone())
        conn.close()

        res = outcome_tracker.evaluate_bar(row, ambig_bar)
        assert res.new_status == "AMBIGUOUS"
        assert res.first_touch == "AMBIGUOUS_SAME_BAR"

        # Apply state to DB
        conn = tracker._get_conn()
        conn.execute(
            "UPDATE system_signals SET status = ?, first_touch = ?, outcome_confidence = ? WHERE signal_id = ?",
            (res.new_status, res.first_touch, res.outcome_confidence, sig_id),
        )
        conn.commit()
        conn.close()

        meas = dataset_svc.build_signal_outcome_measurement(sig_id)
        assert meas is not None
        assert meas["outcome"] == "AMBIGUOUS"
        assert meas["raw_lifecycle_state"] == "AMBIGUOUS"
        assert meas["data_quality_status"] == "AMBIGUOUS_DATA"
        assert meas["realized_r"] is None  # Never fabricated for ambiguous outcomes

    def test_10_t1_to_t2_progression_preserved(self, isolated_db):
        """Req 10: T1 -> T2 progression is preserved and recorded."""
        tracker, outcome_tracker, dataset_svc = isolated_db
        sig_id = tracker.record_generated_signal({
            "symbol": "STOCK_F",
            "direction": "CALL",
            "price": 200.0,
            "stop_loss": 190.0,
            "target_1": 210.0,
            "target_2": 220.0,
            "score": 90,
        })
        # Hit T1
        outcome_tracker.update_active_signal_outcomes(lambda sym: 212.0)
        # Continue to T2
        outcome_tracker.update_active_signal_outcomes(lambda sym: 225.0)

        meas = dataset_svc.build_signal_outcome_measurement(sig_id)
        assert meas is not None
        assert meas["outcome"] == "TARGET_FIRST"
        assert meas["first_touch"] == "T1"
        assert meas["target_1_hit"] == 1
        assert meas["target_2_hit"] == 1
        assert meas["raw_lifecycle_state"] == "TARGET_2_HIT"

    def test_11_t1_then_sl_after_t1_does_not_rewrite_first_touch(self, isolated_db):
        """Req 11: A later SL touch following T1 preserves first_touch='T1'."""
        tracker, outcome_tracker, dataset_svc = isolated_db
        sig_id = tracker.record_generated_signal({
            "symbol": "STOCK_G",
            "direction": "CALL",
            "price": 300.0,
            "stop_loss": 285.0,
            "target_1": 315.0,
            "target_2": 330.0,
            "score": 85,
        })
        # First hit T1
        outcome_tracker.update_active_signal_outcomes(lambda sym: 318.0)
        # Later market turns and hits SL
        outcome_tracker.update_active_signal_outcomes(lambda sym: 280.0)

        meas = dataset_svc.build_signal_outcome_measurement(sig_id)
        assert meas is not None
        assert meas["first_touch"] == "T1"
        assert meas["outcome"] == "TARGET_FIRST"
        assert meas["target_1_hit"] == 1
        assert meas["stop_loss_hit"] == 1

    def test_12_missing_price_produces_no_data(self, isolated_db):
        """Req 12: Zero observations after T0 results in NO_DATA status."""
        tracker, _, dataset_svc = isolated_db
        sig_id = tracker.record_generated_signal({
            "symbol": "STOCK_H",
            "direction": "CALL",
            "price": 100.0,
            "stop_loss": 90.0,
            "target_1": 120.0,
            "target_2": 140.0,
            "score": 80,
        })
        # Clear out current_price update to simulate strictly zero post-T0 observations
        conn = tracker._get_conn()
        conn.execute("UPDATE system_signals SET current_price = 0, first_touch_price = 0 WHERE signal_id = ?", (sig_id,))
        conn.commit()
        conn.close()

        meas = dataset_svc.build_signal_outcome_measurement(sig_id)
        assert meas is not None
        assert meas["outcome"] == "NO_DATA"
        assert meas["data_quality_status"] == "NO_DATA"
        assert meas["mfe"] is None or meas["mfe"] == 0.0

    def test_13_invalid_prices_do_not_enter_calculations(self):
        """Req 13: Non-positive / invalid prices are excluded from MFE/MAE."""
        entry = 100.0
        prices = [-50.0, 0.0, 105.0, -10.0]
        mfe, mae, mfe_pct, mae_pct = calculate_directional_mfe_mae("CALL", entry, prices)
        assert mfe == 5.0
        assert mae == 0.0

    def test_14_time_to_event_uses_prediction_timestamp(self, isolated_db):
        """Req 14: Elapsed seconds are calculated from prediction timestamp T0."""
        tracker, _, dataset_svc = isolated_db
        t0 = "2026-09-26T10:00:00"
        sig_id = tracker.record_generated_signal({
            "symbol": "STOCK_I",
            "direction": "CALL",
            "price": 100.0,
            "stop_loss": 95.0,
            "target_1": 105.0,
            "target_2": 110.0,
            "score": 80,
        })
        # Set T0 explicitly in snapshot and system_signals
        conn = tracker._get_conn()
        conn.execute("UPDATE signal_prediction_snapshots SET captured_at = ? WHERE signal_id = ?", (t0, sig_id))
        conn.execute("UPDATE system_signals SET timestamp = ?, first_touch_at = '2026-09-26T10:15:30', first_touch = 'T1' WHERE signal_id = ?", (t0, sig_id))
        # Insert T1 event at 10:15:30 (15m 30s = 930 seconds)
        conn.execute(
            "INSERT INTO signal_outcome_events (signal_id, observed_at, observed_price, hit_sl, hit_t1, hit_t2) "
            "VALUES (?, '2026-09-26T10:15:30', 106.0, 0, 1, 0)",
            (sig_id,),
        )
        conn.commit()
        conn.close()

        meas = dataset_svc.build_signal_outcome_measurement(sig_id)
        assert meas is not None
        assert meas["time_to_first_event_seconds"] == 930.0
        assert meas["time_to_t1_seconds"] == 930.0

    def test_15_missing_event_timestamp_produces_null(self, isolated_db):
        """Req 15: If an event never occurred, its time_to_event is NULL (None), not 0."""
        tracker, _, dataset_svc = isolated_db
        sig_id = tracker.record_generated_signal({
            "symbol": "STOCK_J",
            "direction": "CALL",
            "price": 100.0,
            "stop_loss": 95.0,
            "target_1": 105.0,
            "target_2": 110.0,
            "score": 80,
        })
        meas = dataset_svc.build_signal_outcome_measurement(sig_id)
        assert meas is not None
        assert meas["time_to_t1_seconds"] is None
        assert meas["time_to_t2_seconds"] is None
        assert meas["time_to_sl_seconds"] is None

    def test_16_realized_r_for_call_is_correct(self):
        """Req 16: Realized R for CALL = (exit - entry) / initial_risk."""
        entry = 100.0
        sl = 95.0
        risk = entry - sl  # 5.0
        # Win at 110.0
        assert calculate_realized_r("CALL", entry, 110.0, risk) == 2.0
        # Loss at 95.0
        assert calculate_realized_r("CALL", entry, 95.0, risk) == -1.0

    def test_17_realized_r_for_put_is_correct(self):
        """Req 17: Realized R for PUT = (entry - exit) / initial_risk."""
        entry = 200.0
        sl = 210.0
        risk = sl - entry  # 10.0
        # Win at 180.0
        assert calculate_realized_r("PUT", entry, 180.0, risk) == 2.0
        # Loss at 210.0
        assert calculate_realized_r("PUT", entry, 210.0, risk) == -1.0

    def test_18_zero_or_invalid_initial_risk_prevents_division_by_zero(self):
        """Req 18: Zero or invalid initial risk produces None without error."""
        assert calculate_realized_r("CALL", 100.0, 105.0, 0.0) is None
        assert calculate_realized_r("CALL", 100.0, 105.0, -5.0) is None
        assert calculate_realized_r("CALL", 0.0, 105.0, 5.0) is None

    def test_19_historical_calculation_is_deterministic(self, isolated_db):
        """Req 19: Repeated measurement calculation yields identical results."""
        tracker, _, dataset_svc = isolated_db
        sig_id = tracker.record_generated_signal({
            "symbol": "STOCK_K",
            "direction": "CALL",
            "price": 1000.0,
            "stop_loss": 950.0,
            "target_1": 1080.0,
            "target_2": 1120.0,
            "score": 85,
        })
        conn = tracker._get_conn()
        conn.execute(
            "INSERT INTO signal_outcome_events (signal_id, observed_at, observed_price, hit_sl, hit_t1, hit_t2) "
            "VALUES (?, '2026-09-26T10:10:00', 1040.0, 0, 0, 0)",
            (sig_id,),
        )
        conn.execute(
            "INSERT INTO signal_outcome_events (signal_id, observed_at, observed_price, hit_sl, hit_t1, hit_t2) "
            "VALUES (?, '2026-09-26T10:20:00', 1090.0, 0, 1, 0)",
            (sig_id,),
        )
        conn.commit()
        conn.close()

        meas1 = dataset_svc.build_signal_outcome_measurement(sig_id)
        meas2 = dataset_svc.build_signal_outcome_measurement(sig_id)
        assert meas1 is not None and meas2 is not None
        # Remove volatile calculated_at timestamp for comparison
        meas1_clean = {k: v for k, v in meas1.items() if k != "calculated_at"}
        meas2_clean = {k: v for k, v in meas2.items() if k != "calculated_at"}
        assert meas1_clean == meas2_clean

    def test_20_rerunning_dataset_construction_is_idempotent(self, isolated_db):
        """Req 20: Re-running dataset construction updates rows idempotently without duplication."""
        tracker, _, dataset_svc = isolated_db
        for sym in ("SYM_X", "SYM_Y"):
            tracker.record_generated_signal({
                "symbol": sym,
                "direction": "CALL",
                "price": 100.0,
                "stop_loss": 90.0,
                "target_1": 120.0,
                "target_2": 140.0,
                "score": 80,
            })

        # Run twice
        res1 = dataset_svc.build_signal_outcome_dataset()
        res2 = dataset_svc.build_signal_outcome_dataset()
        assert len(res1) == 2
        assert len(res2) == 2

        # Check table row count
        conn = tracker._get_conn()
        cnt = conn.execute("SELECT COUNT(*) as cnt FROM signal_outcome_measurements").fetchone()["cnt"]
        assert cnt == 2
        conn.close()

    def test_21_prediction_snapshot_remains_unmutated_after_measurement(self, isolated_db):
        """Req 21: Prediction snapshot is 100% byte-for-byte unmutated by outcome measurement."""
        tracker, _, dataset_svc = isolated_db
        sig_id = tracker.record_generated_signal({
            "symbol": "STOCK_IMMUTABLE",
            "direction": "CALL",
            "price": 2500.0,
            "stop_loss": 2425.0,
            "target_1": 2650.0,
            "target_2": 2750.0,
            "score": 92,
            "raw_score": 98.5,
            "features": {"f1": 1, "f2": 2},
        })
        snap_before = tracker.get_prediction_snapshot(sig_id)
        assert snap_before is not None

        # Build outcome measurement
        dataset_svc.build_signal_outcome_measurement(sig_id)

        snap_after = tracker.get_prediction_snapshot(sig_id)
        assert snap_after == snap_before
        assert snap_after["snapshot_hash"] == snap_before["snapshot_hash"]

    def test_22_no_look_ahead_observations_before_t0_ignored(self, isolated_db):
        """Req 22: Strict No Look-Ahead: observations timestamped before T0 are completely ignored."""
        tracker, _, dataset_svc = isolated_db
        t0 = "2026-09-26T10:00:00"
        sig_id = tracker.record_generated_signal({
            "symbol": "STOCK_LOOKAHEAD",
            "direction": "CALL",
            "price": 100.0,
            "stop_loss": 90.0,
            "target_1": 120.0,
            "target_2": 140.0,
            "score": 85,
        })
        conn = tracker._get_conn()
        conn.execute("UPDATE signal_prediction_snapshots SET captured_at = ? WHERE signal_id = ?", (t0, sig_id))
        conn.execute("UPDATE system_signals SET timestamp = ? WHERE signal_id = ?", (t0, sig_id))

        # Event BEFORE T0 at 09:55:00 with price 150.0 (would be MFE 50 if admitted)
        conn.execute(
            "INSERT INTO signal_outcome_events (signal_id, observed_at, observed_price, hit_sl, hit_t1, hit_t2) "
            "VALUES (?, '2026-09-26T09:55:00', 150.0, 0, 1, 0)",
            (sig_id,),
        )
        # Event AFTER T0 at 10:05:00 with price 105.0 (legitimate MFE 5.0)
        conn.execute(
            "INSERT INTO signal_outcome_events (signal_id, observed_at, observed_price, hit_sl, hit_t1, hit_t2) "
            "VALUES (?, '2026-09-26T10:05:00', 105.0, 0, 0, 0)",
            (sig_id,),
        )
        conn.commit()
        conn.close()

        meas = dataset_svc.build_signal_outcome_measurement(sig_id)
        assert meas is not None
        # Pre-T0 price 150.0 MUST NOT be included in MFE
        assert meas["mfe"] == 5.0
        assert meas["target_1_hit"] == 0  # Pre-T0 T1 hit MUST NOT be admitted
        assert meas["observation_count"] == 1  # Only post-T0 observation counted
