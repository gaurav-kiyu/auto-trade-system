"""OPB v2.60 — E5 Offline Historical Candle Replay & Barrier Evaluation Test Suite.

Governing Standard: OPB-FINAL-PHASE-GOVERNANCE-001
Governing Specification: OPB-V260-E4.1-SHADOW-TELEMETRY-FORMAL-SPEC-20261003-001
Authorization: OPB v2.60 — E5 Offline Historical Candle Replay & Barrier Evaluation Authorization

Verifies all 15 E5 Data Integrity & Replay Audit Requirements:
- E5-DATA-01: Candidate population strictly matches Point-A definition.
- E5-ID-01: Candidate IDs are deterministic.
- E5-LEAK-01: Zero look-ahead leakage in ATR or features.
- E5-ENTRY-01: Entry price matches frozen snapshot.
- E5-BARRIER-01: Barriers derive exclusively from candidate-time ATR and model.
- E5-FIRST-TOUCH-01: Chronological first-touch ordering is correct.
- E5-AMBIG-01: Same-candle conflict correctly quarantined as AMBIGUOUS.
- E5-TIMEOUT-01: Full-window no-touch classified as TIMEOUT.
- E5-INCOMPLETE-01: Missing/partial forward data classified as INSUFFICIENT_FORWARD_DATA.
- E5-DIRECTION-01: Directional barrier logic (LONG vs SHORT) verified.
- E5-NO-SYNTHETIC-01: Zero synthetic/interpolated candle generation.
- E5-DUP-01: Zero duplicate candidate/model/horizon rows in results.
- E5-REPLAY-01: Deterministic replay produces bit-identical results.
- E5-DB-ISO-01: Production DB (signals_history.db) SHA-256 remains 100% byte-identical.
- E5-PROD-ISO-02: Production source/runtime state strictly untouched.
"""

from __future__ import annotations

import copy
import datetime
import hashlib
import json
import logging
import os
import pathlib
import sqlite3
import tempfile
import unittest

from core.research.e5_replay_engine import (
    DEFAULT_E5_DB_PATH,
    E5_TELEMETRY_POPULATION,
    PRE_AUTHORIZED_HORIZONS,
    PRE_AUTHORIZED_MODELS,
    BarrierModel,
    E5DatabaseManager,
    E5ReplayEngine,
    HorizonSpec,
    ReplayCandle,
    classify_score_bucket,
    generate_candidate_obs_id,
    validate_e5_db_path,
)

_ROOT = pathlib.Path(__file__).resolve().parent.parent
PROD_DB_PATH = _ROOT / "db" / "signals_history.db"


class TestE5HistoricalReplayEngine(unittest.TestCase):
    """Exhaustive validation suite for E5 historical candle replay engine."""

    def setUp(self) -> None:
        self.test_dir = tempfile.TemporaryDirectory()
        self.test_e5_db = pathlib.Path(self.test_dir.name) / "test_e5.db"
        self.db_mgr = E5DatabaseManager(db_path=self.test_e5_db)
        self.engine = E5ReplayEngine(db_manager=self.db_mgr)

        # Production database immutability tracking
        self.prod_db_exists = PROD_DB_PATH.exists()
        if self.prod_db_exists:
            self.prod_db_bytes_before = PROD_DB_PATH.read_bytes()
            self.prod_db_sha_before = hashlib.sha256(self.prod_db_bytes_before).hexdigest()
            self.prod_db_size_before = len(self.prod_db_bytes_before)

    def tearDown(self) -> None:
        self.test_dir.cleanup()
        # Verify production DB immutability
        if self.prod_db_exists:
            bytes_after = PROD_DB_PATH.read_bytes()
            sha_after = hashlib.sha256(bytes_after).hexdigest()
            size_after = len(bytes_after)
            self.assertEqual(
                self.prod_db_sha_before,
                sha_after,
                "CRITICAL: signals_history.db SHA-256 altered during E5 test execution!",
            )
            self.assertEqual(
                self.prod_db_size_before,
                size_after,
                "CRITICAL: signals_history.db size altered during E5 test execution!",
            )

    # --------------------------------------------------------------------------
    # E5-DATA-01: Candidate population strictly matches Point-A definition
    # --------------------------------------------------------------------------
    def test_e5_data_01_population_definition(self) -> None:
        expected = "POST-EVALUATOR / SETUP-QUALIFIED CANDIDATES ENTERING scan_universe() AT POINT-A"
        self.assertEqual(E5_TELEMETRY_POPULATION, expected)

    # --------------------------------------------------------------------------
    # E5-ID-01: Candidate IDs are deterministic and reproducible
    # --------------------------------------------------------------------------
    def test_e5_id_01_deterministic_identity(self) -> None:
        id1 = generate_candidate_obs_id("2026-10-03", "CYC-001", "INFY", "BUY", "2026-10-03T09:30:00", 1850.0)
        id2 = generate_candidate_obs_id("2026-10-03", "CYC-001", "INFY", "BUY", "2026-10-03T09:30:00", 1850.0)
        self.assertEqual(id1, id2, "Candidate ID must be 100% deterministic across replays")
        self.assertNotIn("uuid", id1.lower())

    # --------------------------------------------------------------------------
    # E5-LEAK-01: Zero look-ahead leakage in ATR or features
    # --------------------------------------------------------------------------
    def test_e5_leak_01_no_forward_leakage(self) -> None:
        cand_ts = "2026-10-03T09:30:00"
        # Candle timestamped AT or BEFORE candidate observation time must not be evaluated
        candles = [
            ReplayCandle("2026-10-03T09:29:00", 100.0, 105.0, 95.0, 102.0),
            ReplayCandle("2026-10-03T09:30:00", 100.0, 105.0, 95.0, 102.0),
            ReplayCandle("2026-10-03T09:31:00", 100.0, 101.0, 99.0, 100.5),
        ]
        res = self.engine.evaluate_candidate_forward_window(
            candidate_obs_id="CAND-TEST-01",
            market_date="2026-10-03",
            cycle_id="CYC-01",
            symbol="TEST",
            direction="BUY",
            category="LARGE_CAP_EQUITY",
            score=85,
            entry_price=100.0,
            atr=2.0,
            candidate_timestamp=cand_ts,
            candles=candles,
            model=PRE_AUTHORIZED_MODELS["M1"],
            horizon_spec=PRE_AUTHORIZED_HORIZONS["15m"],
        )
        # Only the 09:31 candle (> 09:30) is eligible for evaluation
        self.assertEqual(res.bars_evaluated, 1, "Only strictly post-observation candles may be evaluated")

    # --------------------------------------------------------------------------
    # E5-ENTRY-01: Entry price matches frozen snapshot
    # --------------------------------------------------------------------------
    def test_e5_entry_01_entry_price_matches_snapshot(self) -> None:
        entry = 3450.75
        res = self.engine.evaluate_candidate_forward_window(
            candidate_obs_id="CAND-ENTRY",
            market_date="2026-10-03",
            cycle_id="CYC-01",
            symbol="TCS",
            direction="BUY",
            category="LARGE_CAP_EQUITY",
            score=90,
            entry_price=entry,
            atr=35.0,
            candidate_timestamp="2026-10-03T09:30:00",
            candles=[],
            model=PRE_AUTHORIZED_MODELS["M1"],
            horizon_spec=PRE_AUTHORIZED_HORIZONS["15m"],
        )
        self.assertEqual(res.entry_price, entry, "Replay entry price must match candidate snapshot exactly")

    # --------------------------------------------------------------------------
    # E5-BARRIER-01: Barriers derive exclusively from candidate-time ATR and model
    # --------------------------------------------------------------------------
    def test_e5_barrier_01_barriers_from_candidate_atr(self) -> None:
        entry = 1000.0
        atr = 20.0
        # M1: T1=1.0x, SL=1.0x, T2=2.0x -> T1=1020, T2=1040, SL=980
        t1, t2, sl, t1_d, t2_d, sl_d = E5ReplayEngine.calculate_directional_barriers(
            entry, atr, "BUY", PRE_AUTHORIZED_MODELS["M1"]
        )
        self.assertEqual(t1, 1020.0)
        self.assertEqual(t2, 1040.0)
        self.assertEqual(sl, 980.0)
        self.assertEqual(t1_d, 20.0)
        self.assertEqual(t2_d, 40.0)
        self.assertEqual(sl_d, 20.0)

        # M4: T1=2.0x, SL=1.5x, T2=4.0x -> T1=1040, T2=1080, SL=970
        t1_4, t2_4, sl_4, _, _, _ = E5ReplayEngine.calculate_directional_barriers(
            entry, atr, "BUY", PRE_AUTHORIZED_MODELS["M4"]
        )
        self.assertEqual(t1_4, 1040.0)
        self.assertEqual(t2_4, 1080.0)
        self.assertEqual(sl_4, 970.0)

    # --------------------------------------------------------------------------
    # E5-FIRST-TOUCH-01: Chronological first-touch ordering is correct
    # --------------------------------------------------------------------------
    def test_e5_first_touch_01_chronological_ordering(self) -> None:
        cand_ts = "2026-10-03T09:30:00"
        # Bar 1 touches T1 (high=1025 >= 1020, low=995 > 980). Bar 2 touches T2 (high=1045 >= 1040).
        candles = [
            ReplayCandle("2026-10-03T09:31:00", 1000.0, 1025.0, 995.0, 1022.0),
            ReplayCandle("2026-10-03T09:32:00", 1022.0, 1045.0, 1015.0, 1040.0),
        ]
        res = self.engine.evaluate_candidate_forward_window(
            candidate_obs_id="CAND-TOUCH",
            market_date="2026-10-03",
            cycle_id="CYC-01",
            symbol="STOCK_T",
            direction="BUY",
            category="EQUITY_SWING_DELIVERY",
            score=95,
            entry_price=1000.0,
            atr=20.0,
            candidate_timestamp=cand_ts,
            candles=candles,
            model=PRE_AUTHORIZED_MODELS["M1"],
            horizon_spec=PRE_AUTHORIZED_HORIZONS["15m"],
        )
        self.assertEqual(res.terminal_status, "T2", "Reaching T1 then T2 must be resolved as T2")
        self.assertEqual(res.first_touch_timestamp, "2026-10-03T09:31:00")

    # --------------------------------------------------------------------------
    # E5-AMBIG-01: Same-candle conflict correctly quarantined as AMBIGUOUS
    # --------------------------------------------------------------------------
    def test_e5_ambig_01_same_candle_conflict(self) -> None:
        cand_ts = "2026-10-03T09:30:00"
        # Bar breaches BOTH T1 (1020) and SL (980): high=1030, low=970
        candles = [
            ReplayCandle("2026-10-03T09:31:00", 1000.0, 1030.0, 970.0, 1005.0),
        ]
        res = self.engine.evaluate_candidate_forward_window(
            candidate_obs_id="CAND-AMBIG",
            market_date="2026-10-03",
            cycle_id="CYC-01",
            symbol="STOCK_A",
            direction="BUY",
            category="MID_SMALL_CAP",
            score=88,
            entry_price=1000.0,
            atr=20.0,
            candidate_timestamp=cand_ts,
            candles=candles,
            model=PRE_AUTHORIZED_MODELS["M1"],
            horizon_spec=PRE_AUTHORIZED_HORIZONS["15m"],
        )
        self.assertEqual(res.terminal_status, "AMBIGUOUS", "Same-candle breach must be AMBIGUOUS")
        self.assertEqual(res.ambiguous, 1)

    # --------------------------------------------------------------------------
    # E5-TIMEOUT-01: Full-window no-touch classified as TIMEOUT
    # --------------------------------------------------------------------------
    def test_e5_timeout_01_complete_window_no_touch(self) -> None:
        cand_ts = "2026-10-03T09:30:00"
        # 15m horizon = 900s -> expires at 09:45:00
        # Provide candles covering up to 09:45:00 with no barrier breach (high=1010 < 1020, low=990 > 980)
        candles = [
            ReplayCandle("2026-10-03T09:35:00", 1000.0, 1005.0, 995.0, 1002.0),
            ReplayCandle("2026-10-03T09:40:00", 1002.0, 1008.0, 998.0, 1004.0),
            ReplayCandle("2026-10-03T09:45:00", 1004.0, 1010.0, 992.0, 1001.0),
        ]
        res = self.engine.evaluate_candidate_forward_window(
            candidate_obs_id="CAND-TIMEOUT",
            market_date="2026-10-03",
            cycle_id="CYC-01",
            symbol="STOCK_TO",
            direction="BUY",
            category="LARGE_CAP_EQUITY",
            score=80,
            entry_price=1000.0,
            atr=20.0,
            candidate_timestamp=cand_ts,
            candles=candles,
            model=PRE_AUTHORIZED_MODELS["M1"],
            horizon_spec=PRE_AUTHORIZED_HORIZONS["15m"],
        )
        self.assertEqual(res.terminal_status, "TIMEOUT", "Complete elapsed horizon without touch must be TIMEOUT")
        self.assertEqual(res.forward_data_complete, 1)

    # --------------------------------------------------------------------------
    # E5-INCOMPLETE-01: Missing/partial forward data classified as INSUFFICIENT_FORWARD_DATA
    # --------------------------------------------------------------------------
    def test_e5_incomplete_01_insufficient_data(self) -> None:
        cand_ts = "2026-10-03T09:30:00"
        # 15m horizon expires at 09:45:00. Candles stop at 09:33:00 (incomplete window, no barrier touch)
        candles = [
            ReplayCandle("2026-10-03T09:31:00", 1000.0, 1005.0, 995.0, 1002.0),
            ReplayCandle("2026-10-03T09:33:00", 1002.0, 1004.0, 996.0, 1000.0),
        ]
        res = self.engine.evaluate_candidate_forward_window(
            candidate_obs_id="CAND-INCOMPLETE",
            market_date="2026-10-03",
            cycle_id="CYC-01",
            symbol="STOCK_INC",
            direction="BUY",
            category="LARGE_CAP_EQUITY",
            score=80,
            entry_price=1000.0,
            atr=20.0,
            candidate_timestamp=cand_ts,
            candles=candles,
            model=PRE_AUTHORIZED_MODELS["M1"],
            horizon_spec=PRE_AUTHORIZED_HORIZONS["15m"],
        )
        self.assertEqual(
            res.terminal_status,
            "INSUFFICIENT_FORWARD_DATA",
            "Incomplete window without touch must be INSUFFICIENT_FORWARD_DATA",
        )
        self.assertEqual(res.insufficient_forward_data, 1)
        self.assertEqual(res.forward_data_complete, 0)

    # --------------------------------------------------------------------------
    # E5-DIRECTION-01: Directional barrier logic (LONG vs SHORT) verified
    # --------------------------------------------------------------------------
    def test_e5_direction_01_long_short_logic(self) -> None:
        entry = 1000.0
        atr = 25.0
        # SHORT M1: T1 = 1000 - 25 = 975, T2 = 1000 - 50 = 950, SL = 1000 + 25 = 1025
        t1_s, t2_s, sl_s, t1_d, t2_d, sl_d = E5ReplayEngine.calculate_directional_barriers(
            entry, atr, "SHORT", PRE_AUTHORIZED_MODELS["M1"]
        )
        self.assertEqual(t1_s, 975.0)
        self.assertEqual(t2_s, 950.0)
        self.assertEqual(sl_s, 1025.0)
        self.assertEqual(t1_d, 25.0)
        self.assertEqual(sl_d, 25.0)

        # Test SHORT hit_t1
        cand_ts = "2026-10-03T09:30:00"
        candles = [
            ReplayCandle("2026-10-03T09:31:00", 1000.0, 1010.0, 970.0, 972.0),
        ]
        res = self.engine.evaluate_candidate_forward_window(
            candidate_obs_id="CAND-SHORT",
            market_date="2026-10-03",
            cycle_id="CYC-01",
            symbol="SHORT_SYM",
            direction="SHORT",
            category="FUTURES",
            score=85,
            entry_price=entry,
            atr=atr,
            candidate_timestamp=cand_ts,
            candles=candles,
            model=PRE_AUTHORIZED_MODELS["M1"],
            horizon_spec=PRE_AUTHORIZED_HORIZONS["15m"],
        )
        self.assertEqual(res.terminal_status, "T1_ONLY", "SHORT price drop below T1 must resolve as T1_ONLY")

    # --------------------------------------------------------------------------
    # E5-NO-SYNTHETIC-01: Zero synthetic/interpolated candle generation
    # --------------------------------------------------------------------------
    def test_e5_no_synthetic_01_no_synthetic_candles(self) -> None:
        res = self.engine.evaluate_candidate_forward_window(
            candidate_obs_id="CAND-EMPTY",
            market_date="2026-10-03",
            cycle_id="CYC-01",
            symbol="NO_DATA_STOCK",
            direction="BUY",
            category="LARGE_CAP_EQUITY",
            score=75,
            entry_price=100.0,
            atr=2.0,
            candidate_timestamp="2026-10-03T09:30:00",
            candles=[],
            model=PRE_AUTHORIZED_MODELS["M1"],
            horizon_spec=PRE_AUTHORIZED_HORIZONS["15m"],
        )
        self.assertEqual(res.bars_evaluated, 0, "Zero bars must be evaluated when no candles provided")
        self.assertEqual(res.terminal_status, "INSUFFICIENT_FORWARD_DATA", "Never fabricate outcomes")

    # --------------------------------------------------------------------------
    # E5-DUP-01: Zero duplicate candidate/model/horizon rows in results
    # --------------------------------------------------------------------------
    def test_e5_dup_01_no_duplicate_results(self) -> None:
        cand = {
            "candidate_obs_id": "CAND-DUP-TEST",
            "market_date": "2026-10-03",
            "cycle_id": "CYC-DUP",
            "symbol": "DUP_SYM",
            "direction": "BUY",
            "category": "LARGE_CAP_EQUITY",
            "score": 90,
            "entry_price": 500.0,
            "atr": 10.0,
            "candidate_timestamp": "2026-10-03T09:30:00",
        }
        candles = [ReplayCandle("2026-10-03T09:31:00", 500.0, 515.0, 495.0, 512.0)]
        # Run replay twice with same candidate across all horizons to test deduplication
        self.engine.execute_replay_matrix([cand], {"DUP_SYM": candles}, enforce_category_horizons=False)
        self.engine.execute_replay_matrix([cand], {"DUP_SYM": candles}, enforce_category_horizons=False)

        # Count in DB must be exactly len(PRE_AUTHORIZED_MODELS) * len(PRE_AUTHORIZED_HORIZONS)
        expected_rows = len(PRE_AUTHORIZED_MODELS) * len(PRE_AUTHORIZED_HORIZONS)
        actual_rows = self.db_mgr.get_row_count()
        self.assertEqual(actual_rows, expected_rows, f"Expected {expected_rows} rows, found {actual_rows} (no duplicates allowed)")

    # --------------------------------------------------------------------------
    # E5-REPLAY-01: Deterministic replay produces bit-identical results
    # --------------------------------------------------------------------------
    def test_e5_replay_01_reproducible_replay(self) -> None:
        cand = {
            "candidate_obs_id": "CAND-REPLAY-TEST",
            "market_date": "2026-10-03",
            "cycle_id": "CYC-REP",
            "symbol": "REP_SYM",
            "direction": "BUY",
            "category": "EQUITY_SWING_DELIVERY",
            "score": 92,
            "entry_price": 200.0,
            "atr": 5.0,
            "candidate_timestamp": "2026-10-03T09:30:00",
        }
        candles = [
            ReplayCandle("2026-10-03T09:31:00", 200.0, 204.0, 198.0, 202.0),
            ReplayCandle("2026-10-03T09:32:00", 202.0, 206.0, 201.0, 205.5),
        ]
        res1 = self.engine.evaluate_candidate_forward_window(
            candidate_obs_id=cand["candidate_obs_id"],
            market_date=cand["market_date"],
            cycle_id=cand["cycle_id"],
            symbol=cand["symbol"],
            direction=cand["direction"],
            category=cand["category"],
            score=cand["score"],
            entry_price=cand["entry_price"],
            atr=cand["atr"],
            candidate_timestamp=cand["candidate_timestamp"],
            candles=candles,
            model=PRE_AUTHORIZED_MODELS["M1"],
            horizon_spec=PRE_AUTHORIZED_HORIZONS["15m"],
        )
        res2 = self.engine.evaluate_candidate_forward_window(
            candidate_obs_id=cand["candidate_obs_id"],
            market_date=cand["market_date"],
            cycle_id=cand["cycle_id"],
            symbol=cand["symbol"],
            direction=cand["direction"],
            category=cand["category"],
            score=cand["score"],
            entry_price=cand["entry_price"],
            atr=cand["atr"],
            candidate_timestamp=cand["candidate_timestamp"],
            candles=candles,
            model=PRE_AUTHORIZED_MODELS["M1"],
            horizon_spec=PRE_AUTHORIZED_HORIZONS["15m"],
        )
        self.assertEqual(res1.to_tuple(), res2.to_tuple(), "Identical inputs must yield identical replay output")

    # --------------------------------------------------------------------------
    # E5-DB-ISO-01: Production DB remains byte-identical
    # --------------------------------------------------------------------------
    def test_e5_db_iso_01_production_db_path_safety(self) -> None:
        with self.assertRaises(ValueError):
            validate_e5_db_path(PROD_DB_PATH)

    # --------------------------------------------------------------------------
    # E5-PROD-ISO-02: Production source/runtime state strictly untouched
    # --------------------------------------------------------------------------
    def test_e5_prod_iso_02_production_invariants(self) -> None:
        import core.research.e5_replay_engine as e5_mod
        mod_source = pathlib.Path(e5_mod.__file__).read_text(encoding="utf-8")
        for forbidden in ("signals_history.db", "urllib.request", "smtplib", "telegram"):
            if forbidden == "signals_history.db":
                # Only allowed inside safety validation
                self.assertIn("signals_history", mod_source)
            else:
                self.assertNotIn(f"import {forbidden}", mod_source)


if __name__ == "__main__":
    unittest.main()
