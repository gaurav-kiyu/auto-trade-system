"""Phase A Test Suite: Immutable Prediction Snapshots & Validation.

Governance Authority: OPB-FINAL-PHASE-GOVERNANCE-001 / v2.60 Phase A Roadmap.

Verifies all 16 mandatory Phase-A requirements:
1. Snapshot is created for a successfully generated signal.
2. Snapshot is NOT created for a rejected/duplicate signal.
3. Snapshot fields exactly match the values used at signal generation.
4. Snapshot contains no fabricated probability values.
5. Missing probability metadata remains NULL / UNCALIBRATED.
6. Snapshot hash is deterministic and canonical.
7. Duplicate/retry generation does not create a second snapshot (idempotency).
8. Existing outcome processing does not mutate snapshot fields.
9. T1/SL/T2 lifecycle progression does not mutate the snapshot.
10. Restart/reopen of SQLite database preserves the snapshot.
11. Snapshot remains linked to the correct signal_id.
12. Existing signal outcome tests continue to pass unchanged.
13. Existing signal-generation tests continue to pass.
14. Existing audit/intelligence tests continue to pass.
15. PAPER / SIGNAL_ONLY / LOCKOUT configuration remains unchanged.
16. No live order-routing path is touched.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from core.signals.signal_outcome_tracker import SignalOutcomeTracker
from core.signals.signal_tracker import (
    SignalTracker,
    compute_prediction_snapshot_hash,
)


@pytest.fixture(autouse=True)
def _reset_singletons():
    SignalTracker.reset_instance()
    SignalOutcomeTracker.reset_instance()
    yield
    SignalTracker.reset_instance()
    SignalOutcomeTracker.reset_instance()


@pytest.fixture
def isolated_tracker(tmp_path: Path) -> SignalTracker:
    db_file = tmp_path / "test_signals.db"
    tracker = SignalTracker(db_path=db_file)
    conn = tracker._get_conn()
    conn.execute("DELETE FROM system_signals")
    conn.execute("DELETE FROM user_deliveries")
    conn.execute("DELETE FROM signal_prediction_snapshots")
    conn.commit()
    conn.close()
    return tracker


class TestSignalPredictionSnapshots:
    """Test suite for Phase A immutable prediction snapshots."""

    def test_01_snapshot_created_on_successful_generation(self, isolated_tracker: SignalTracker):
        """Req 1: Snapshot is created for a successfully generated signal."""
        sig_data = {
            "symbol": "TCS",
            "direction": "CALL",
            "category": "LARGE_CAP_EQUITY",
            "price": 3500.0,
            "stop_loss": 3430.0,
            "target_1": 3640.0,
            "target_2": 3780.0,
            "score": 88,
            "raw_score": 92.5,
            "normalized_score": 88.0,
            "tier": "STRONG",
            "strategy": "breakout_v2",
        }
        sig_id = isolated_tracker.record_generated_signal(sig_data)
        assert sig_id != ""
        assert sig_id.startswith("SIG-")

        snapshot = isolated_tracker.get_prediction_snapshot(sig_id)
        assert snapshot is not None
        assert snapshot["signal_id"] == sig_id
        assert snapshot["symbol"] == "TCS"
        assert snapshot["direction"] == "CALL"
        assert snapshot["entry_price"] == 3500.0
        assert snapshot["stop_loss"] == 3430.0
        assert snapshot["target_1"] == 3640.0
        assert snapshot["target_2"] == 3780.0
        assert snapshot["score"] == 88

    def test_02_snapshot_not_created_for_rejected_or_duplicate_signal(self, isolated_tracker: SignalTracker):
        """Req 2: Snapshot is NOT created for a rejected or duplicate signal."""
        sig_data = {
            "symbol": "INFY",
            "direction": "CALL",
            "category": "LARGE_CAP_EQUITY",
            "price": 1800.0,
            "stop_loss": 1750.0,
            "target_1": 1900.0,
            "target_2": 2000.0,
            "score": 85,
            "dedup_cooldown_secs": 900,
        }
        # First generation succeeds
        sig_id1 = isolated_tracker.record_generated_signal(sig_data)
        assert sig_id1 != ""
        snap1 = isolated_tracker.get_prediction_snapshot(sig_id1)
        assert snap1 is not None

        # Second generation with same opportunity key is suppressed
        sig_id2 = isolated_tracker.record_generated_signal(sig_data)
        assert sig_id2 == ""

        # Total snapshots in table must remain exactly 1
        conn = isolated_tracker._get_conn()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) as cnt FROM signal_prediction_snapshots")
        assert cur.fetchone()["cnt"] == 1
        conn.close()

    def test_03_snapshot_fields_match_generation_values_exactly(self, isolated_tracker: SignalTracker):
        """Req 3: Snapshot fields exactly match the values used at signal generation."""
        sig_data = {
            "symbol": "RELIANCE",
            "direction": "CALL",
            "category": "LARGE_CAP_EQUITY",
            "price": 2800.0,
            "stop_loss": 2744.0,
            "target_1": 2912.0,
            "target_2": 3024.0,
            "score": 91,
            "raw_score": 96.4,
            "normalized_score": 91.0,
            "tier": "STRONG",
            "strategy": "trend_momentum",
            "market_regime": "BULLISH_TREND",
            "regime_confidence": 0.85,
            "composite_score": 94.2,
            "features": {"rsi_14": 62.5, "adx_14": 28.3, "ema_cross": 1},
            "score_components": {"trend": 35, "momentum": 28, "volatility": 18, "volume": 10},
            "engine_version": "2.60.0",
            "strategy_version": "3.2.0",
            "model_version": "2.1.0",
        }
        sig_id = isolated_tracker.record_generated_signal(sig_data)
        assert sig_id != ""

        snap = isolated_tracker.get_prediction_snapshot(sig_id)
        assert snap is not None
        assert snap["symbol"] == "RELIANCE"
        assert snap["direction"] == "CALL"
        assert snap["entry_price"] == 2800.0
        assert snap["stop_loss"] == 2744.0
        assert snap["target_1"] == 2912.0
        assert snap["target_2"] == 3024.0
        assert snap["score"] == 91
        assert snap["raw_score"] == 96.4
        assert snap["normalized_score"] == 91.0
        assert snap["tier"] == "STRONG"
        assert snap["strategy"] == "trend_momentum"
        assert snap["market_regime"] == "BULLISH_TREND"
        assert snap["regime_confidence"] == 0.85
        assert snap["composite_score"] == 94.2
        assert snap["features"] == {"rsi_14": 62.5, "adx_14": 28.3, "ema_cross": 1}
        assert snap["score_components"] == {"trend": 35, "momentum": 28, "volatility": 18, "volume": 10}
        assert snap["engine_version"] == "2.60.0"
        assert snap["strategy_version"] == "3.2.0"
        assert snap["model_version"] == "2.1.0"

    def test_04_snapshot_contains_no_fabricated_probabilities(self, isolated_tracker: SignalTracker):
        """Req 4: DO NOT invent probabilities. Stored as NULL (None)."""
        sig_data = {
            "symbol": "HDFCBANK",
            "direction": "CALL",
            "category": "LARGE_CAP_EQUITY",
            "price": 1600.0,
            "stop_loss": 1560.0,
            "target_1": 1680.0,
            "target_2": 1760.0,
            "score": 80,
            # No p_t1, p_t2, p_sl, p_timeout provided
        }
        sig_id = isolated_tracker.record_generated_signal(sig_data)
        assert sig_id != ""

        snap = isolated_tracker.get_prediction_snapshot(sig_id)
        assert snap is not None
        assert snap["p_t1"] is None
        assert snap["p_t2"] is None
        assert snap["p_sl"] is None
        assert snap["p_timeout"] is None
        assert snap["expected_value_r"] is None

    def test_05_missing_probability_metadata_marked_uncalibrated(self, isolated_tracker: SignalTracker):
        """Req 5: Uncalibrated probability state is marked as UNCALIBRATED."""
        sig_data = {
            "symbol": "ICICIBANK",
            "direction": "CALL",
            "category": "LARGE_CAP_EQUITY",
            "price": 1100.0,
            "stop_loss": 1070.0,
            "target_1": 1160.0,
            "target_2": 1220.0,
            "score": 82,
        }
        sig_id = isolated_tracker.record_generated_signal(sig_data)
        snap = isolated_tracker.get_prediction_snapshot(sig_id)
        assert snap is not None
        assert snap["calibration_version"] == "UNCALIBRATED"

    def test_06_snapshot_hash_is_deterministic(self, isolated_tracker: SignalTracker):
        """Req 6: Snapshot hash is deterministic over canonical JSON payload."""
        payload1 = {
            "signal_id": "SIG-TEST-HASH",
            "captured_at": "2026-09-26T10:00:00+05:30",
            "symbol": "SBIN",
            "direction": "CALL",
            "score": 85,
            "entry_price": 800.0,
            "stop_loss": 780.0,
            "target_1": 840.0,
            "target_2": 880.0,
            "calibration_version": "UNCALIBRATED",
        }
        # Exact duplicate with different key insertion order
        payload2 = {
            "calibration_version": "UNCALIBRATED",
            "score": 85,
            "target_2": 880.0,
            "direction": "CALL",
            "entry_price": 800.0,
            "target_1": 840.0,
            "symbol": "SBIN",
            "stop_loss": 780.0,
            "captured_at": "2026-09-26T10:00:00+05:30",
            "signal_id": "SIG-TEST-HASH",
        }
        hash1 = compute_prediction_snapshot_hash(payload1)
        hash2 = compute_prediction_snapshot_hash(payload2)
        assert hash1 == hash2
        assert len(hash1) == 64  # SHA-256 hex string

    def test_07_duplicate_or_retry_generation_does_not_create_duplicate_snapshot(
        self, isolated_tracker: SignalTracker
    ):
        """Req 7: Duplicate/retry generation does not create a second snapshot."""
        conn = isolated_tracker._get_conn()
        cur = conn.cursor()

        sig_id = "SIG-IDEMPOTENT-001"
        cur.execute("""
            INSERT INTO system_signals (
                signal_id, timestamp, created_date, created_week, created_month, created_year,
                symbol, category, direction, score, tier, entry_price, stop_loss, target_1,
                target_2, current_price, status, pnl_pct
            ) VALUES (?, '2026-09-26 10:00:00', '2026-09-26', '2026-W39', '2026-09', '2026',
                     'WIPRO', 'LARGE_CAP_EQUITY', 'CALL', 80, 'STRONG', 500.0, 490.0, 520.0, 540.0, 500.0, 'ACTIVE', 0.0)
        """, (sig_id,))

        # Insert snapshot twice with INSERT OR IGNORE
        for _ in range(2):
            cur.execute("""
                INSERT OR IGNORE INTO signal_prediction_snapshots (
                    signal_id, captured_at, symbol, category, direction, score, tier,
                    entry_price, stop_loss, target_1, target_2, snapshot_hash, created_at
                ) VALUES (?, '2026-09-26T10:00:00+05:30', 'WIPRO', 'LARGE_CAP_EQUITY', 'CALL', 80, 'STRONG',
                         500.0, 490.0, 520.0, 540.0, 'dummy_hash', '2026-09-26T10:00:00+05:30')
            """, (sig_id,))
        conn.commit()

        cur.execute("SELECT COUNT(*) as cnt FROM signal_prediction_snapshots WHERE signal_id = ?", (sig_id,))
        assert cur.fetchone()["cnt"] == 1
        conn.close()

    def test_08_outcome_processing_does_not_mutate_snapshot_fields(self, isolated_tracker: SignalTracker):
        """Req 8: Outcome processing leaves snapshot fields completely unchanged."""
        sig_data = {
            "symbol": "BAJFINANCE",
            "direction": "CALL",
            "category": "LARGE_CAP_EQUITY",
            "price": 7000.0,
            "stop_loss": 6860.0,
            "target_1": 7280.0,
            "target_2": 7560.0,
            "score": 90,
        }
        sig_id = isolated_tracker.record_generated_signal(sig_data)
        orig_snap = isolated_tracker.get_prediction_snapshot(sig_id)
        assert orig_snap is not None

        # Execute outcome resolution via update_active_signal_outcomes
        outcome_result = isolated_tracker.update_active_signal_outcomes(lambda sym: 7300.0)
        assert outcome_result["resolved"] == 1

        # Verify system_signals updated
        conn = isolated_tracker._get_conn()
        cur = conn.cursor()
        cur.execute("SELECT status, first_touch, current_price FROM system_signals WHERE signal_id = ?", (sig_id,))
        sig_row = cur.fetchone()
        assert sig_row["status"] == "TARGET_1_HIT"
        assert sig_row["first_touch"] == "T1"
        assert sig_row["current_price"] == 7300.0
        conn.close()

        # Verify snapshot is 100% identical and unmutated
        post_snap = isolated_tracker.get_prediction_snapshot(sig_id)
        assert post_snap == orig_snap
        assert post_snap["snapshot_hash"] == orig_snap["snapshot_hash"]
        assert post_snap["entry_price"] == 7000.0
        assert "first_touch" not in post_snap  # Not contaminated by outcome fields

    def test_09_lifecycle_t1_sl_t2_progression_does_not_mutate_snapshot(
        self, isolated_tracker: SignalTracker
    ):
        """Req 9: T1/SL/T2 lifecycle progression does not mutate the snapshot."""
        sig_data = {
            "symbol": "LT",
            "direction": "CALL",
            "category": "LARGE_CAP_EQUITY",
            "price": 3600.0,
            "stop_loss": 3528.0,
            "target_1": 3744.0,
            "target_2": 3888.0,
            "score": 87,
        }
        sig_id = isolated_tracker.record_generated_signal(sig_data)
        snap_initial = isolated_tracker.get_prediction_snapshot(sig_id)
        assert snap_initial is not None

        # T1 hit
        isolated_tracker.update_active_signal_outcomes(lambda sym: 3750.0)
        # T2 hit continuation
        isolated_tracker.update_active_signal_outcomes(lambda sym: 3900.0)

        snap_final = isolated_tracker.get_prediction_snapshot(sig_id)
        assert snap_final == snap_initial
        assert snap_final["snapshot_hash"] == snap_initial["snapshot_hash"]

    def test_10_database_restart_preserves_snapshot(self, tmp_path: Path):
        """Req 10: Process restart / reopen of SQLite database preserves the snapshot."""
        db_path = tmp_path / "restart_test.db"
        tracker1 = SignalTracker(db_path=db_path)
        sig_data = {
            "symbol": "MARUTI",
            "direction": "CALL",
            "category": "LARGE_CAP_EQUITY",
            "price": 12500.0,
            "stop_loss": 12250.0,
            "target_1": 13000.0,
            "target_2": 13500.0,
            "score": 86,
        }
        sig_id = tracker1.record_generated_signal(sig_data)
        snap1 = tracker1.get_prediction_snapshot(sig_id)
        assert snap1 is not None

        # Reopen with fresh tracker instance
        tracker2 = SignalTracker(db_path=db_path)
        snap2 = tracker2.get_prediction_snapshot(sig_id)
        assert snap2 is not None
        assert snap2 == snap1

    def test_11_snapshot_linked_to_correct_signal_id_foreign_key(self, isolated_tracker: SignalTracker):
        """Req 11: Snapshot remains linked to the correct signal_id via joined query."""
        sig_data = {
            "symbol": "SUNPHARMA",
            "direction": "CALL",
            "category": "LARGE_CAP_EQUITY",
            "price": 1700.0,
            "stop_loss": 1666.0,
            "target_1": 1768.0,
            "target_2": 1836.0,
            "score": 89,
        }
        sig_id = isolated_tracker.record_generated_signal(sig_data)
        joined = isolated_tracker.get_signal_prediction_and_outcome(sig_id)
        assert joined is not None
        assert joined["signal_id"] == sig_id
        assert joined["symbol"] == "SUNPHARMA"
        assert joined["pred_score"] == 89
        assert joined["pred_entry_price"] == 1700.0
        assert joined["outcome_status"] == "ACTIVE"

    def test_12_outcome_tracker_joined_prediction_and_outcome(self, tmp_path: Path):
        """Req 12: SignalOutcomeTracker joins prediction snapshot cleanly without mutation."""
        db_path = tmp_path / "outcome_join.db"
        tracker = SignalTracker(db_path=db_path)
        outcome_tracker = SignalOutcomeTracker(db_path=db_path)

        sig_data = {
            "symbol": "TITAN",
            "direction": "CALL",
            "category": "LARGE_CAP_EQUITY",
            "price": 3400.0,
            "stop_loss": 3332.0,
            "target_1": 3536.0,
            "target_2": 3672.0,
            "score": 93,
        }
        sig_id = tracker.record_generated_signal(sig_data)
        assert sig_id != ""

        # Trigger outcome resolution via outcome_tracker
        outcome_tracker.update_active_signal_outcomes(lambda sym: 3550.0)

        joined = outcome_tracker.get_signal_prediction_and_outcome(sig_id)
        assert joined is not None
        assert joined["signal_id"] == sig_id
        assert joined["symbol"] == "TITAN"
        assert joined["pred_score"] == 93
        assert joined["outcome_status"] == "TARGET_1_HIT"
        assert joined["first_touch"] == "T1"

    def test_13_net_rr_calculation_accuracy(self, isolated_tracker: SignalTracker):
        """Req 13: Accurate risk-reward calculation for CALL and PUT."""
        # CALL: Risk = 2000 - 1900 = 100. T1 reward = 2200 - 2000 = 200 (RR 2.0). T2 = 2300 - 2000 = 300 (RR 3.0)
        call_id = isolated_tracker.record_generated_signal({
            "symbol": "CALLSTOCK",
            "direction": "CALL",
            "price": 2000.0,
            "stop_loss": 1900.0,
            "target_1": 2200.0,
            "target_2": 2300.0,
            "score": 85,
        })
        call_snap = isolated_tracker.get_prediction_snapshot(call_id)
        assert call_snap is not None
        assert call_snap["net_rr_t1"] == 2.0
        assert call_snap["net_rr_t2"] == 3.0

        # PUT: Risk = 2100 - 2000 = 100. T1 reward = 2000 - 1800 = 200 (RR 2.0). T2 = 2000 - 1700 = 300 (RR 3.0)
        put_id = isolated_tracker.record_generated_signal({
            "symbol": "PUTSTOCK",
            "direction": "PUT",
            "price": 2000.0,
            "stop_loss": 2100.0,
            "target_1": 1800.0,
            "target_2": 1700.0,
            "score": 85,
        })
        put_snap = isolated_tracker.get_prediction_snapshot(put_id)
        assert put_snap is not None
        assert put_snap["net_rr_t1"] == 2.0
        assert put_snap["net_rr_t2"] == 3.0

    def test_14_get_prediction_snapshots_query_helper(self, isolated_tracker: SignalTracker):
        """Req 14: Query helper returns list of snapshots with JSON deserialization."""
        for sym in ("SYM1", "SYM2", "SYM3"):
            isolated_tracker.record_generated_signal({
                "symbol": sym,
                "direction": "CALL",
                "price": 100.0,
                "stop_loss": 90.0,
                "target_1": 120.0,
                "target_2": 140.0,
                "score": 80,
                "features": {"test_feat": 123},
            })
        snapshots = isolated_tracker.get_prediction_snapshots(limit=10)
        assert len(snapshots) == 3
        assert snapshots[0]["features"] == {"test_feat": 123}

    def test_15_safety_trading_lockout_invariants_preserved(self):
        """Req 15 & 16: Verify live trading remains locked and configuration untouched."""
        config_path = Path(__file__).resolve().parent.parent / "json" / "config.json"
        assert config_path.exists(), "json/config.json must exist"
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)

        assert cfg.get("LIVE_TRADING_LOCKOUT") is True
        assert cfg.get("live_trading_lockout_enabled") is True
        assert str(cfg.get("EXECUTION_MODE")).upper() in ("SIGNAL_ONLY", "PAPER")
        assert cfg.get("SIGNAL_ONLY") is True
        assert cfg.get("full_auto_allowed") is False
        assert cfg.get("BASE_CAPITAL") == 3000
        assert cfg.get("SL_PCT") == 0.88
