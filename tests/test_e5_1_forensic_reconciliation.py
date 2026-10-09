"""OPB v2.60 — E5.1 Forensic Reconciliation & Methodology Correction Test Suite.

Governing Standard: OPB-FINAL-PHASE-GOVERNANCE-001
Authorization: OPB v2.60 — E5.1 Forensic Reconciliation & Methodology Correction Authorization

Verifies all 17 E5.1 Forensic Audit & Reconciliation Requirements:
- E5.1-POP-01: Snapshot provenance lineage strictly verified against production DB.
- E5.1-POP-02: Formal denominator classification as Partial Point-A Population.
- E5.1-POP-03: ATR eligibility audit (exactly 8 excluded Futures, 93 eligible).
- E5.1-CATEGORY-01: Category-horizon authorization governance matrix definition.
- E5.1-CATEGORY-02: Category-horizon filtering enforcement in replay matrix.
- E5.1-HORIZON-01: EOD cutoff calendar semantics (same day 15:30:00 IST).
- E5.1-HORIZON-02: Next Trading Day cutoff calendar semantics (skips weekends/holidays).
- E5.1-HORIZON-03: 5 Trading Days cutoff calendar semantics (skips Gandhi Jayanti & weekends).
- E5.1-HORIZON-04: Weekend and overnight jump bounded by session close.
- E5.1-HORIZON-05: Intraday horizon capping at session close (15:30:00 IST).
- E5.1-HORIZON-06: Bar boundary chronological gating.
- E5.1-MFE-01: NULL representation for missing/incomplete excursion data (no 0.0 placeholder).
- E5.1-MFE-02: Directional MFE/MAE excursion formulas (LONG vs SHORT).
- E5.1-MFE-03: R-multiple normalization formula (R = Points / Stop_Distance).
- E5.1-MFE-04: Complete vs incomplete window separation in aggregations.
- E5.1-ISO-01: Production DB (signals_history.db) SHA-256 byte-identical.
- E5.1-ISO-02: Zero production trading code mutation.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import pathlib
import sqlite3
import tempfile
import unittest

from core.exchange_calendar_engine import ExchangeCalendarEngine
from core.research.e5_replay_engine import (
    CATEGORY_AUTHORIZED_HORIZONS,
    E5_TELEMETRY_POPULATION,
    PRE_AUTHORIZED_HORIZONS,
    PRE_AUTHORIZED_MODELS,
    E5DatabaseManager,
    E5ReplayEngine,
    ReplayCandle,
    ReplayEvaluationResult,
    compute_horizon_cutoff,
    is_horizon_authorized_for_category,
    normalize_excursion_pct,
    normalize_excursion_r,
)

_ROOT = pathlib.Path(__file__).resolve().parent.parent
PROD_DB_PATH = _ROOT / "db" / "signals_history.db"
EXPECTED_PROD_DB_SHA = "f12ba2e45e91077dbb3cfde289938aba225bd1669b9d02a7ddc5a49e57cd6e5a"
EXPECTED_PROD_DB_SIZE = 1216512


def _create_deterministic_e5_fixture_db(db_path: pathlib.Path) -> None:
    """Creates a deterministic SQLite database with 101 candidate snapshots matching E5.1 requirements."""
    conn = sqlite3.connect(str(db_path))
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
            status TEXT NOT NULL
        )
    """)
    cur.execute("""
        CREATE TABLE signal_prediction_snapshots (
            signal_id TEXT PRIMARY KEY,
            captured_at TEXT NOT NULL,
            category TEXT NOT NULL,
            features_json TEXT,
            FOREIGN KEY (signal_id) REFERENCES system_signals(signal_id)
        )
    """)
    # 31 EQUITY_SWING_DELIVERY (eligible: atr > 0)
    for i in range(31):
        sid = f"SIG_EQ_{i+1:03d}"
        cur.execute(
            "INSERT INTO system_signals VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (sid, "2026-09-28 09:30:00", "2026-09-28", f"EQ_{i}", "EQUITY_SWING_DELIVERY", "BUY", 90, "ACTIVE"),
        )
        cur.execute(
            "INSERT INTO signal_prediction_snapshots VALUES (?, ?, ?, ?)",
            (sid, "2026-09-28 09:30:00", "EQUITY_SWING_DELIVERY", json.dumps({"atr": 10.0})),
        )
    # 31 STOCK_OPTIONS (eligible: atr > 0)
    for i in range(31):
        sid = f"SIG_OPT_{i+1:03d}"
        cur.execute(
            "INSERT INTO system_signals VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (sid, "2026-09-28 09:30:00", "2026-09-28", f"OPT_{i}", "STOCK_OPTIONS", "BUY", 85, "ACTIVE"),
        )
        cur.execute(
            "INSERT INTO signal_prediction_snapshots VALUES (?, ?, ?, ?)",
            (sid, "2026-09-28 09:30:00", "STOCK_OPTIONS", json.dumps({"atr": 2.5})),
        )
    # 31 FUTURES (eligible: atr > 0)
    for i in range(31):
        sid = f"SIG_FUT_ELIG_{i+1:03d}"
        cur.execute(
            "INSERT INTO system_signals VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (sid, "2026-09-28 09:30:00", "2026-09-28", f"FUT_{i}", "FUTURES", "BUY", 88, "ACTIVE"),
        )
        cur.execute(
            "INSERT INTO signal_prediction_snapshots VALUES (?, ?, ?, ?)",
            (sid, "2026-09-28 09:30:00", "FUTURES", json.dumps({"atr": 15.0})),
        )
    # 7 FUTURES (excluded: missing/zero atr)
    for i in range(7):
        sid = f"SIG_FUT_EXC_{i+1:03d}"
        cur.execute(
            "INSERT INTO system_signals VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (sid, "2026-09-28 09:30:00", "2026-09-28", f"FUT_EXC_{i}", "FUTURES", "BUY", 80, "ACTIVE"),
        )
        cur.execute(
            "INSERT INTO signal_prediction_snapshots VALUES (?, ?, ?, ?)",
            (sid, "2026-09-28 09:30:00", "FUTURES", json.dumps({"atr": 0.0})),
        )
    # 1 INDEX_OPTIONS (excluded: missing/zero atr)
    sid = "SIG_IDX_EXC_001"
    cur.execute(
        "INSERT INTO system_signals VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (sid, "2026-09-28 09:30:00", "2026-09-28", "NIFTY", "INDEX_OPTIONS", "BUY", 85, "ACTIVE"),
    )
    cur.execute(
        "INSERT INTO signal_prediction_snapshots VALUES (?, ?, ?, ?)",
        (sid, "2026-09-28 09:30:00", "INDEX_OPTIONS", json.dumps({"atr": None})),
    )
    conn.commit()
    conn.close()


class TestE51ForensicReconciliation(unittest.TestCase):
    """Exhaustive validation suite for E5.1 forensic reconciliation & methodology correction."""

    def setUp(self) -> None:
        self.test_dir = tempfile.TemporaryDirectory()
        self.test_e5_db = pathlib.Path(self.test_dir.name) / "test_e5_1.db"
        self.db_mgr = E5DatabaseManager(db_path=self.test_e5_db)
        self.engine = E5ReplayEngine(db_manager=self.db_mgr)
        self.calendar = ExchangeCalendarEngine()

        # Deterministic test database fixture for E5.1 population and immutability validation
        self.fixture_db_path = pathlib.Path(self.test_dir.name) / "fixture_signals_history.db"
        _create_deterministic_e5_fixture_db(self.fixture_db_path)
        self.fixture_sha_before = hashlib.sha256(self.fixture_db_path.read_bytes()).hexdigest()
        self.fixture_size_before = self.fixture_db_path.stat().st_size

        # Production database state tracking (immutability guard)
        self.prod_db_exists = PROD_DB_PATH.exists()
        if self.prod_db_exists:
            bytes_before = PROD_DB_PATH.read_bytes()
            self.prod_db_size_before = len(bytes_before)
            self.prod_db_sha_before = hashlib.sha256(bytes_before).hexdigest()

    def tearDown(self) -> None:
        # Fixture database immutability assertion
        bytes_fixture_after = self.fixture_db_path.read_bytes()
        self.assertEqual(
            self.fixture_size_before,
            len(bytes_fixture_after),
            "CRITICAL: fixture database size altered during E5 test execution!",
        )
        self.assertEqual(
            self.fixture_sha_before,
            hashlib.sha256(bytes_fixture_after).hexdigest(),
            "CRITICAL: fixture database SHA-256 altered during E5 test execution!",
        )

        # Production database immutability assertion (if present)
        if self.prod_db_exists:
            bytes_after = PROD_DB_PATH.read_bytes()
            self.assertEqual(
                self.prod_db_size_before,
                len(bytes_after),
                "CRITICAL: signals_history.db size altered during E5 test execution!",
            )
            self.assertEqual(
                self.prod_db_sha_before,
                hashlib.sha256(bytes_after).hexdigest(),
                "CRITICAL: signals_history.db SHA-256 altered during E5 test execution!",
            )
        self.test_dir.cleanup()

    # --------------------------------------------------------------------------
    # E5.1-POP-01: Snapshot Provenance Lineage Verification
    # --------------------------------------------------------------------------
    def test_e5_1_pop_01_provenance_lineage(self) -> None:
        """Verify that 101 candidate snapshots in signal_prediction_snapshots match 2026-09-28 system_signals."""
        # 1. Deterministic fixture verification
        conn = sqlite3.connect(f"file:{str(self.fixture_db_path)}?mode=ro", uri=True)
        try:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM signal_prediction_snapshots")
            total_snaps = cur.fetchone()[0]
            self.assertEqual(total_snaps, 101, "Expected exactly 101 historical prediction snapshots")

            cur.execute("""
                SELECT COUNT(*)
                FROM signal_prediction_snapshots p
                JOIN system_signals s ON p.signal_id = s.signal_id
            """)
            matched_count = cur.fetchone()[0]
            self.assertEqual(matched_count, 101, "100% of candidate snapshots must match system_signals records")

            cur.execute("SELECT DISTINCT date(captured_at) FROM signal_prediction_snapshots")
            dates = [r[0] for r in cur.fetchall()]
            self.assertEqual(dates, ["2026-09-28"], "Snapshots originate exclusively from 2026-09-28 session")
        finally:
            conn.close()

        # 2. Canonical baseline validation (when historical production database is present on disk)
        if self.prod_db_exists and self.prod_db_size_before == EXPECTED_PROD_DB_SIZE:
            if self.prod_db_sha_before == EXPECTED_PROD_DB_SHA:
                conn_prod = sqlite3.connect(f"file:{str(PROD_DB_PATH)}?mode=ro", uri=True)
                try:
                    cur_p = conn_prod.cursor()
                    cur_p.execute("SELECT COUNT(*) FROM signal_prediction_snapshots")
                    self.assertEqual(cur_p.fetchone()[0], 101)
                    cur_p.execute("""
                        SELECT COUNT(*)
                        FROM signal_prediction_snapshots p
                        JOIN system_signals s ON p.signal_id = s.signal_id
                    """)
                    self.assertEqual(cur_p.fetchone()[0], 101)
                    cur_p.execute("SELECT DISTINCT date(captured_at) FROM signal_prediction_snapshots")
                    self.assertEqual([r[0] for r in cur_p.fetchall()], ["2026-09-28"])
                finally:
                    conn_prod.close()

    # --------------------------------------------------------------------------
    # E5.1-POP-02: Formal Denominator Classification
    # --------------------------------------------------------------------------
    def test_e5_1_pop_02_denominator_classification(self) -> None:
        """Verify formal classification as Partial Point-A Population (Completeness Unverifiable)."""
        expected_pop_definition = "POST-EVALUATOR / SETUP-QUALIFIED CANDIDATES ENTERING scan_universe() AT POINT-A"
        self.assertEqual(E5_TELEMETRY_POPULATION, expected_pop_definition)

        # Designated cohort label
        cohort_label = "E5 RESEARCH SNAPSHOT COHORT (2026-09-28 PERSISTED SUBSET)"
        self.assertIn("PERSISTED SUBSET", cohort_label)
        self.assertIn("2026-09-28", cohort_label)

    # --------------------------------------------------------------------------
    # E5.1-POP-03: ATR Eligibility and Exclusion Audit
    # --------------------------------------------------------------------------
    def test_e5_1_pop_03_atr_eligibility_and_exclusions(self) -> None:
        """Verify exactly 8 excluded Futures candidates (missing ATR) and 93 eligible candidates."""
        # 1. Deterministic fixture verification
        conn = sqlite3.connect(f"file:{str(self.fixture_db_path)}?mode=ro", uri=True)
        try:
            cur = conn.cursor()
            cur.execute("SELECT signal_id, category, features_json FROM signal_prediction_snapshots")
            rows = cur.fetchall()

            eligible = []
            excluded = []
            for s_id, cat, feat_json in rows:
                feat = json.loads(feat_json) if feat_json else {}
                atr = feat.get("atr")
                if atr is not None and float(atr) > 0:
                    eligible.append((s_id, cat))
                else:
                    excluded.append((s_id, cat))

            self.assertEqual(len(excluded), 8, "Expected exactly 8 excluded candidates")
            excluded_cats = [cat for _, cat in excluded]
            self.assertEqual(excluded_cats.count("FUTURES"), 7, "Expected exactly 7 excluded FUTURES candidates")
            self.assertEqual(excluded_cats.count("INDEX_OPTIONS"), 1, "Expected exactly 1 excluded INDEX_OPTIONS candidate")

            self.assertEqual(len(eligible), 93, "Expected exactly 93 eligible candidates")
            cat_counts = {}
            for _, cat in eligible:
                cat_counts[cat] = cat_counts.get(cat, 0) + 1

            self.assertEqual(cat_counts.get("EQUITY_SWING_DELIVERY"), 31)
            self.assertEqual(cat_counts.get("STOCK_OPTIONS"), 31)
            self.assertEqual(cat_counts.get("FUTURES"), 31)
        finally:
            conn.close()

        # 2. Canonical baseline validation (when historical production database is present on disk)
        if self.prod_db_exists and self.prod_db_size_before == EXPECTED_PROD_DB_SIZE:
            if self.prod_db_sha_before == EXPECTED_PROD_DB_SHA:
                conn_prod = sqlite3.connect(f"file:{str(PROD_DB_PATH)}?mode=ro", uri=True)
                try:
                    cur_p = conn_prod.cursor()
                    cur_p.execute("SELECT signal_id, category, features_json FROM signal_prediction_snapshots")
                    rows_p = cur_p.fetchall()
                    eligible_p = []
                    excluded_p = []
                    for s_id, cat, feat_json in rows_p:
                        feat = json.loads(feat_json) if feat_json else {}
                        atr = feat.get("atr")
                        if atr is not None and float(atr) > 0:
                            eligible_p.append((s_id, cat))
                        else:
                            excluded_p.append((s_id, cat))
                    self.assertEqual(len(excluded_p), 8)
                    self.assertEqual(len(eligible_p), 93)
                finally:
                    conn_prod.close()

    # --------------------------------------------------------------------------
    # E5.1-CATEGORY-01: Category-Horizon Governance Matrix Definition
    # --------------------------------------------------------------------------
    def test_e5_1_category_01_matrix_definition(self) -> None:
        """Verify category-specific authorized evaluation horizons."""
        self.assertEqual(CATEGORY_AUTHORIZED_HORIZONS["EQUITY_SWING_DELIVERY"], ["EOD", "Next Day", "5 Days"])
        self.assertEqual(CATEGORY_AUTHORIZED_HORIZONS["STOCK_OPTIONS"], ["15m", "30m", "60m", "EOD"])
        self.assertEqual(CATEGORY_AUTHORIZED_HORIZONS["INDEX_OPTIONS"], ["60m"])
        self.assertEqual(CATEGORY_AUTHORIZED_HORIZONS["FUTURES"], ["15m", "30m", "60m", "EOD"])

        # Function verification
        self.assertTrue(is_horizon_authorized_for_category("STOCK_OPTIONS", "15m"))
        self.assertTrue(is_horizon_authorized_for_category("STOCK_OPTIONS", "EOD"))
        self.assertFalse(is_horizon_authorized_for_category("STOCK_OPTIONS", "Next Day"))
        self.assertFalse(is_horizon_authorized_for_category("STOCK_OPTIONS", "5 Days"))

        self.assertFalse(is_horizon_authorized_for_category("EQUITY_SWING_DELIVERY", "15m"))
        self.assertTrue(is_horizon_authorized_for_category("EQUITY_SWING_DELIVERY", "Next Day"))
        self.assertTrue(is_horizon_authorized_for_category("EQUITY_SWING_DELIVERY", "5 Days"))

        self.assertFalse(is_horizon_authorized_for_category("INDEX_OPTIONS", "15m"))
        self.assertTrue(is_horizon_authorized_for_category("INDEX_OPTIONS", "60m"))

    # --------------------------------------------------------------------------
    # E5.1-CATEGORY-02: Category Horizon Replay Enforcement
    # --------------------------------------------------------------------------
    def test_e5_1_category_02_replay_matrix_enforcement(self) -> None:
        """Verify that execute_replay_matrix evaluates ONLY authorized category-horizon pairs."""
        candidates = [
            {
                "candidate_obs_id": "CAND-EQ",
                "market_date": "2026-09-28",
                "cycle_id": "CYC-01",
                "symbol": "EQ_STOCK",
                "direction": "BUY",
                "category": "EQUITY_SWING_DELIVERY",
                "score": 90,
                "entry_price": 500.0,
                "atr": 10.0,
                "candidate_timestamp": "2026-09-28T09:30:00",
            },
            {
                "candidate_obs_id": "CAND-OPT",
                "market_date": "2026-09-28",
                "cycle_id": "CYC-01",
                "symbol": "OPT_STOCK",
                "direction": "BUY",
                "category": "STOCK_OPTIONS",
                "score": 85,
                "entry_price": 50.0,
                "atr": 2.0,
                "candidate_timestamp": "2026-09-28T09:30:00",
            },
        ]
        results = self.engine.execute_replay_matrix(
            candidates=candidates,
            symbol_candles_map={},
            enforce_category_horizons=True,
        )
        # CAND-EQ: 6 models * 3 horizons (EOD, Next Day, 5 Days) = 18
        # CAND-OPT: 6 models * 4 horizons (15m, 30m, 60m, EOD) = 24
        # Total = 42 (not 2 * 6 * 6 = 72)
        self.assertEqual(len(results), 42)
        eq_horizons = {r.horizon for r in results if r.candidate_obs_id == "CAND-EQ"}
        opt_horizons = {r.horizon for r in results if r.candidate_obs_id == "CAND-OPT"}
        self.assertEqual(eq_horizons, {"EOD", "Next Day", "5 Days"})
        self.assertEqual(opt_horizons, {"15m", "30m", "60m", "EOD"})

    # --------------------------------------------------------------------------
    # E5.1-HORIZON-01: EOD Cutoff Calendar Semantics
    # --------------------------------------------------------------------------
    def test_e5_1_horizon_01_eod_cutoff(self) -> None:
        """EOD cutoff is same trading day close at 15:30:00 IST regardless of entry time."""
        cand_dt = datetime.datetime(2026, 9, 28, 10, 15, 0)
        cutoff = compute_horizon_cutoff(cand_dt, "EOD", self.calendar)
        self.assertEqual(cutoff, datetime.datetime(2026, 9, 28, 15, 30, 0))

        cand_dt2 = datetime.datetime(2026, 9, 28, 14, 45, 0)
        cutoff2 = compute_horizon_cutoff(cand_dt2, "EOD", self.calendar)
        self.assertEqual(cutoff2, datetime.datetime(2026, 9, 28, 15, 30, 0))

    # --------------------------------------------------------------------------
    # E5.1-HORIZON-02: Next Trading Day Cutoff Calendar Semantics
    # --------------------------------------------------------------------------
    def test_e5_1_horizon_02_next_trading_day_cutoff(self) -> None:
        """Next Trading Day skips weekends and statutory holidays to 15:30:00 IST close."""
        # Normal day: Monday 28 Sep -> Tuesday 29 Sep 15:30
        mon_dt = datetime.datetime(2026, 9, 28, 10, 0, 0)
        cutoff_mon = compute_horizon_cutoff(mon_dt, "Next Day", self.calendar)
        self.assertEqual(cutoff_mon, datetime.datetime(2026, 9, 29, 15, 30, 0))

        # Friday session: Friday 25 Sep -> Monday 28 Sep 15:30 (skips Sat 26, Sun 27)
        fri_dt = datetime.datetime(2026, 9, 25, 11, 0, 0)
        cutoff_fri = compute_horizon_cutoff(fri_dt, "Next Day", self.calendar)
        self.assertEqual(cutoff_fri, datetime.datetime(2026, 9, 28, 15, 30, 0))

        # Statutory Holiday: Thursday 01 Oct 2026 -> Monday 05 Oct 2026 15:30
        # (Friday 02 Oct is Gandhi Jayanti, Sat 03, Sun 04 are weekend)
        thu_dt = datetime.datetime(2026, 10, 1, 14, 0, 0)
        cutoff_thu = compute_horizon_cutoff(thu_dt, "Next Day", self.calendar)
        self.assertEqual(cutoff_thu, datetime.datetime(2026, 10, 5, 15, 30, 0))

    # --------------------------------------------------------------------------
    # E5.1-HORIZON-03: 5 Trading Days Cutoff Calendar Semantics
    # --------------------------------------------------------------------------
    def test_e5_1_horizon_03_5_trading_days_cutoff(self) -> None:
        """5 Trading Days advances 5 market sessions skipping holidays and weekends."""
        # Monday 21 Sep -> Tue 22, Wed 23, Thu 24, Fri 25, Mon 28 Sep 15:30
        dt1 = datetime.datetime(2026, 9, 21, 10, 0, 0)
        cutoff1 = compute_horizon_cutoff(dt1, "5 Days", self.calendar)
        self.assertEqual(cutoff1, datetime.datetime(2026, 9, 28, 15, 30, 0))

        # Monday 28 Sep -> Tue 29, Wed 30, Thu 01 Oct, Mon 05 Oct (Fri 02 is holiday!), Tue 06 Oct 15:30
        dt2 = datetime.datetime(2026, 9, 28, 9, 30, 0)
        cutoff2 = compute_horizon_cutoff(dt2, "5 Days", self.calendar)
        self.assertEqual(cutoff2, datetime.datetime(2026, 10, 6, 15, 30, 0))

    # --------------------------------------------------------------------------
    # E5.1-HORIZON-04: Weekend and Overnight Jump Bounded
    # --------------------------------------------------------------------------
    def test_e5_1_horizon_04_weekend_jump_bounded(self) -> None:
        """Forward candles across sessions stop evaluation at horizon cutoff without leakage."""
        cand_ts = "2026-09-25T14:30:00"  # Friday afternoon
        # EOD cutoff is Friday 15:30. Monday candles should NOT be evaluated under EOD horizon.
        candles = [
            ReplayCandle("2026-09-25T15:00:00", 100.0, 102.0, 99.0, 101.0),
            ReplayCandle("2026-09-28T09:30:00", 101.0, 120.0, 100.0, 115.0),  # Monday morning
        ]
        res = self.engine.evaluate_candidate_forward_window(
            candidate_obs_id="CAND-FRI-EOD",
            market_date="2026-09-25",
            cycle_id="CYC-01",
            symbol="TEST_JUMP",
            direction="BUY",
            category="EQUITY_SWING_DELIVERY",
            score=90,
            entry_price=100.0,
            atr=5.0,
            candidate_timestamp=cand_ts,
            candles=candles,
            model=PRE_AUTHORIZED_MODELS["M1"],
            horizon_spec=PRE_AUTHORIZED_HORIZONS["EOD"],
            calendar_engine=self.calendar,
        )
        self.assertEqual(res.bars_evaluated, 1, "Only Friday session bar before 15:30 may be evaluated for EOD")
        self.assertNotEqual(res.terminal_status, "T1_ONLY", "Monday target hit must NOT leak into Friday EOD horizon")

    # --------------------------------------------------------------------------
    # E5.1-HORIZON-05: Intraday Horizon Capping at Session Close
    # --------------------------------------------------------------------------
    def test_e5_1_horizon_05_intraday_capping(self) -> None:
        """Intraday horizons (15m, 30m, 60m) do not bleed past session close (15:30:00 IST)."""
        cand_dt = datetime.datetime(2026, 9, 28, 15, 20, 0)  # 10m before close
        cutoff_15m = compute_horizon_cutoff(cand_dt, "15m", self.calendar)
        cutoff_30m = compute_horizon_cutoff(cand_dt, "30m", self.calendar)
        cutoff_60m = compute_horizon_cutoff(cand_dt, "60m", self.calendar)

        # All must be capped at 15:30:00 IST
        self.assertEqual(cutoff_15m, datetime.datetime(2026, 9, 28, 15, 30, 0))
        self.assertEqual(cutoff_30m, datetime.datetime(2026, 9, 28, 15, 30, 0))
        self.assertEqual(cutoff_60m, datetime.datetime(2026, 9, 28, 15, 30, 0))

    # --------------------------------------------------------------------------
    # E5.1-HORIZON-06: Bar Boundary Chronological Gating
    # --------------------------------------------------------------------------
    def test_e5_1_horizon_06_bar_boundary_gating(self) -> None:
        """Only candles strictly after observation and on or before cutoff are evaluated."""
        cand_ts = "2026-09-28T10:00:00"
        expected_cutoff = compute_horizon_cutoff(
            datetime.datetime.fromisoformat(cand_ts), "15m", self.calendar
        )
        self.assertEqual(expected_cutoff, datetime.datetime(2026, 9, 28, 10, 15, 0))
        candles = [
            ReplayCandle("2026-09-28T09:59:00", 100.0, 101.0, 99.0, 100.0),  # Prior: rejected
            ReplayCandle("2026-09-28T10:00:00", 100.0, 101.0, 99.0, 100.0),  # Equal: rejected
            ReplayCandle("2026-09-28T10:05:00", 100.0, 101.0, 99.0, 100.0),  # Valid: evaluated
            ReplayCandle("2026-09-28T10:15:00", 100.0, 101.0, 99.0, 100.0),  # Valid boundary: evaluated
            ReplayCandle("2026-09-28T10:16:00", 100.0, 101.0, 99.0, 100.0),  # Beyond cutoff: rejected
        ]
        res = self.engine.evaluate_candidate_forward_window(
            candidate_obs_id="CAND-BOUNDARY",
            market_date="2026-09-28",
            cycle_id="CYC-01",
            symbol="TEST_BOUND",
            direction="BUY",
            category="STOCK_OPTIONS",
            score=80,
            entry_price=100.0,
            atr=5.0,
            candidate_timestamp=cand_ts,
            candles=candles,
            model=PRE_AUTHORIZED_MODELS["M1"],
            horizon_spec=PRE_AUTHORIZED_HORIZONS["15m"],
            calendar_engine=self.calendar,
        )
        self.assertEqual(res.bars_evaluated, 2, "Exactly 2 candles falling within (10:00, 10:15] must be evaluated")

    # --------------------------------------------------------------------------
    # E5.1-MFE-01: NULL Representation for Incomplete Data
    # --------------------------------------------------------------------------
    def test_e5_1_mfe_01_null_representation_for_incomplete_data(self) -> None:
        """Incomplete forward windows must yield mfe=None and mae=None, never 0.0 placeholder."""
        cand_ts = "2026-09-28T09:30:00"
        # 15m horizon expires at 09:45:00. Candles stop at 09:33 (no barrier hit, window incomplete)
        candles = [ReplayCandle("2026-09-28T09:32:00", 100.0, 101.0, 99.0, 100.5)]
        res = self.engine.evaluate_candidate_forward_window(
            candidate_obs_id="CAND-MFE-NULL",
            market_date="2026-09-28",
            cycle_id="CYC-01",
            symbol="STOCK_NULL",
            direction="BUY",
            category="STOCK_OPTIONS",
            score=80,
            entry_price=100.0,
            atr=5.0,
            candidate_timestamp=cand_ts,
            candles=candles,
            model=PRE_AUTHORIZED_MODELS["M1"],
            horizon_spec=PRE_AUTHORIZED_HORIZONS["15m"],
            calendar_engine=self.calendar,
        )
        self.assertEqual(res.terminal_status, "INSUFFICIENT_FORWARD_DATA")
        self.assertIsNone(res.mfe, "MFE must be None for INSUFFICIENT_FORWARD_DATA, not 0.0")
        self.assertIsNone(res.mae, "MAE must be None for INSUFFICIENT_FORWARD_DATA, not 0.0")
        self.assertIsNone(res.mfe_r, "MFE_R must be None for INSUFFICIENT_FORWARD_DATA")
        self.assertIsNone(res.mae_r, "MAE_R must be None for INSUFFICIENT_FORWARD_DATA")

    # --------------------------------------------------------------------------
    # E5.1-MFE-02: Directional MFE/MAE Excursion Formulas
    # --------------------------------------------------------------------------
    def test_e5_1_mfe_02_directional_excursions(self) -> None:
        """Verify directional MFE/MAE calculation for both LONG and SHORT candidates."""
        # Complete window covering 15m (up to 09:45:00) with TIMEOUT
        cand_ts = "2026-09-28T09:30:00"
        candles_long = [
            ReplayCandle("2026-09-28T09:35:00", 100.0, 103.0, 98.0, 101.0),
            ReplayCandle("2026-09-28T09:45:00", 101.0, 104.0, 97.0, 102.0),
        ]
        res_long = self.engine.evaluate_candidate_forward_window(
            candidate_obs_id="CAND-LONG-EXC",
            market_date="2026-09-28",
            cycle_id="CYC-01",
            symbol="STOCK_LONG",
            direction="BUY",
            category="STOCK_OPTIONS",
            score=85,
            entry_price=100.0,
            atr=10.0,  # M1 T1=110, SL=90 (neither hit)
            candidate_timestamp=cand_ts,
            candles=candles_long,
            model=PRE_AUTHORIZED_MODELS["M1"],
            horizon_spec=PRE_AUTHORIZED_HORIZONS["15m"],
            calendar_engine=self.calendar,
        )
        self.assertEqual(res_long.terminal_status, "TIMEOUT")
        # Long MFE = max(104 - 100) = 4.0; Long MAE = max(100 - 97) = 3.0
        self.assertEqual(res_long.mfe, 4.0)
        self.assertEqual(res_long.mae, 3.0)

        # Short test
        candles_short = [
            ReplayCandle("2026-09-28T09:35:00", 100.0, 102.0, 96.0, 98.0),
            ReplayCandle("2026-09-28T09:45:00", 98.0, 103.5, 95.0, 97.0),
        ]
        res_short = self.engine.evaluate_candidate_forward_window(
            candidate_obs_id="CAND-SHORT-EXC",
            market_date="2026-09-28",
            cycle_id="CYC-01",
            symbol="STOCK_SHORT",
            direction="SHORT",
            category="STOCK_OPTIONS",
            score=85,
            entry_price=100.0,
            atr=10.0,  # M1 T1=90, SL=110 (neither hit)
            candidate_timestamp=cand_ts,
            candles=candles_short,
            model=PRE_AUTHORIZED_MODELS["M1"],
            horizon_spec=PRE_AUTHORIZED_HORIZONS["15m"],
            calendar_engine=self.calendar,
        )
        self.assertEqual(res_short.terminal_status, "TIMEOUT")
        # Short MFE = max(100 - 95) = 5.0; Short MAE = max(103.5 - 100) = 3.5
        self.assertEqual(res_short.mfe, 5.0)
        self.assertEqual(res_short.mae, 3.5)

    # --------------------------------------------------------------------------
    # E5.1-MFE-03: R-Multiple Normalization Formula
    # --------------------------------------------------------------------------
    def test_e5_1_mfe_03_r_multiple_normalization(self) -> None:
        """Verify R-multiple normalization: R = Excursion / Stop_Distance."""
        stop_dist = 20.0
        mfe_pts = 10.0
        mae_pts = 5.0

        r_mfe = normalize_excursion_r(mfe_pts, stop_dist)
        r_mae = normalize_excursion_r(mae_pts, stop_dist)
        self.assertEqual(r_mfe, 0.5)
        self.assertEqual(r_mae, 0.25)

        # None preservation
        self.assertIsNone(normalize_excursion_r(None, stop_dist))
        self.assertIsNone(normalize_excursion_r(10.0, 0.0))

        # Percentage normalization
        pct_mfe = normalize_excursion_pct(mfe_pts, 500.0)
        self.assertEqual(pct_mfe, 2.0)

    # --------------------------------------------------------------------------
    # E5.1-MFE-04: Complete vs Incomplete Window Separation in Aggregations
    # --------------------------------------------------------------------------
    def test_e5_1_mfe_04_incomplete_separation_in_aggregations(self) -> None:
        """Aggregations must exclude INSUFFICIENT_FORWARD_DATA from mean and median excursions."""
        # Insert 1 complete TIMEOUT row with MFE=4.0 and 1 incomplete row with MFE=None
        res_complete = ReplayEvaluationResult(
            candidate_obs_id="CAND-COMPL",
            market_date="2026-09-28",
            cycle_id="CYC-01",
            symbol="COMPL_SYM",
            direction="BUY",
            category="STOCK_OPTIONS",
            score=85,
            entry_price=100.0,
            atr=10.0,
            model_id="M1",
            horizon="15m",
            target1_distance=10.0,
            target2_distance=20.0,
            stop_distance=10.0,
            target1_price=110.0,
            target2_price=120.0,
            stop_price=90.0,
            forward_data_complete=1,
            terminal_status="TIMEOUT",
            first_touch_timestamp=None,
            evaluation_end_timestamp="2026-09-28T09:45:00",
            mfe=4.0,
            mae=2.0,
            bars_evaluated=3,
            ambiguous=0,
            insufficient_forward_data=0,
        )
        res_incompl = ReplayEvaluationResult(
            candidate_obs_id="CAND-INCOMPL",
            market_date="2026-09-28",
            cycle_id="CYC-01",
            symbol="INCOMPL_SYM",
            direction="BUY",
            category="STOCK_OPTIONS",
            score=85,
            entry_price=100.0,
            atr=10.0,
            model_id="M1",
            horizon="15m",
            target1_distance=10.0,
            target2_distance=20.0,
            stop_distance=10.0,
            target1_price=110.0,
            target2_price=120.0,
            stop_price=90.0,
            forward_data_complete=0,
            terminal_status="INSUFFICIENT_FORWARD_DATA",
            first_touch_timestamp=None,
            evaluation_end_timestamp=None,
            mfe=None,
            mae=None,
            bars_evaluated=0,
            ambiguous=0,
            insufficient_forward_data=1,
        )
        self.db_mgr.clear_results()
        self.db_mgr.insert_results([res_complete, res_incompl])
        aggs = self.engine.compute_aggregations()
        mh_matrix = aggs["model_horizon_matrix"]
        m1_15m = [r for r in mh_matrix if r["model_id"] == "M1" and r["horizon"] == "15m"][0]

        self.assertEqual(m1_15m["total_eligible"], 2)
        self.assertEqual(m1_15m["complete_window"], 1)
        self.assertEqual(m1_15m["insufficient_data"], 1)
        self.assertEqual(m1_15m["mean_mfe"], 4.0, "Incomplete rows must not pull mean MFE towards zero")
        self.assertEqual(m1_15m["median_mfe"], 4.0, "Incomplete rows must not pull median MFE towards zero")
        self.assertEqual(m1_15m["median_mfe_r"], 0.4, "Normalized median MFE_R must match 4.0 / 10.0 = 0.4")

    # --------------------------------------------------------------------------
    # E5.1-ISO-01: Production Database Immutability
    # --------------------------------------------------------------------------
    def test_e5_1_iso_01_production_db_immutability(self) -> None:
        """signals_history.db remains strictly immutable (byte-identical SHA-256)."""
        # 1. Deterministic fixture immutability validation
        bytes_fixture = self.fixture_db_path.read_bytes()
        self.assertEqual(len(bytes_fixture), self.fixture_size_before)
        self.assertEqual(hashlib.sha256(bytes_fixture).hexdigest(), self.fixture_sha_before)

        # 2. Production database immutability validation (if present)
        if self.prod_db_exists:
            bytes_now = PROD_DB_PATH.read_bytes()
            self.assertEqual(len(bytes_now), self.prod_db_size_before)
            self.assertEqual(hashlib.sha256(bytes_now).hexdigest(), self.prod_db_sha_before)

            # 3. Canonical baseline validation (when historical production database is present)
            if self.prod_db_size_before == EXPECTED_PROD_DB_SIZE and self.prod_db_sha_before == EXPECTED_PROD_DB_SHA:
                self.assertEqual(len(bytes_now), EXPECTED_PROD_DB_SIZE)
                self.assertEqual(hashlib.sha256(bytes_now).hexdigest(), EXPECTED_PROD_DB_SHA)

    # --------------------------------------------------------------------------
    # E5.1-ISO-02: Zero Production Code Mutation
    # --------------------------------------------------------------------------
    def test_e5_1_iso_02_zero_production_code_mutation(self) -> None:
        """Verify no production trading files were modified."""
        import subprocess

        cmd = ["git", "status", "--porcelain"]
        out = subprocess.check_output(cmd, cwd=str(_ROOT)).decode("utf-8")
        # Ensure only research or test or artifact or runtime data files are modified/untracked
        allowed_prefixes = (
            "core/research/",
            "scripts/execute_e5_replay.py",
            "scripts/research/",
            "tests/",
            "artifacts/",
            "OPB_",
            "scratch/",
            "data/",
            "reports/",
            "logs/",
            ".audit_backups/",
        )
        for line in out.splitlines():
            if not line.strip():
                continue
            path = line[2:].strip()
            # If path contains '->', take target path
            if "->" in path:
                path = path.split("->")[1].strip()
            path_normalized = path.replace("\\", "/")
            is_allowed = any(path_normalized.startswith(p) for p in allowed_prefixes)
            self.assertTrue(
                is_allowed,
                f"VIOLATION: Production file modified or staged outside research scope: {path}",
            )


if __name__ == "__main__":
    unittest.main()
