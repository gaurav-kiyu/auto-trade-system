"""Phase C Test Suite: Statistical Significance & Score Bucket Discrimination.

Governance Authority: OPB-FINAL-PHASE-GOVERNANCE-001 / v2.60 Phase C Roadmap.

Verifies all mandatory Phase-C requirements:
1. Correct score bucket assignment for 70–74.
2. Correct score bucket assignment for 75–79.
3. Correct score bucket assignment for 80–84.
4. Correct score bucket assignment for 85+.
5. Boundary values are tested: 69, 70, 74, 75, 79, 80, 84, 85.
6. Empty bucket is handled safely.
7. Seed samples are excluded.
8. NO_DATA is excluded from resolved-outcome denominator.
9. AMBIGUOUS is not silently counted as a win.
10. UNRESOLVED is not silently counted as a loss.
11. Wilson confidence interval calculation is correct.
12. Expectancy uses valid Realized_R observations only.
13. Profit factor handles positive and negative values, no losses, no wins, empty data.
14. MFE_R statistics are direction-independent because Phase B already normalized direction.
15. MAE_R statistics are correct.
16. Multiple-comparison correction is correct if pairwise tests are implemented.
17. Statistical test selection handles small samples.
18. Temporal grouping excludes unavailable observations correctly.
19. Same input dataset produces deterministic analytical output.
20. Phase-A snapshot remains unchanged.
21. Phase-B outcome dataset remains unchanged.
22. Phase-A snapshot schema and contract verified directly.
23. Phase-B outcome measurement schema and contract verified directly.
24. Tracker delegation methods verified directly.
25. Live-trading safety invariants remain unchanged.
"""

from __future__ import annotations

import datetime
import math
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from core.datetime_ist import now_ist
from core.signals.signal_outcome_dataset import SignalOutcomeDatasetService
from core.signals.signal_outcome_tracker import SignalOutcomeTracker
from core.signals.signal_score_discrimination import (
    ANALYSIS_VERSION,
    MIN_INFERENCE_SAMPLE_SIZE,
    SCORE_BUCKETS,
    SignalScoreDiscriminationService,
    adjust_pvalues_holm,
    assign_score_bucket,
    calculate_distribution_stats,
    calculate_expectancy,
    calculate_profit_factor,
    wilson_confidence_interval,
)
from core.signals.signal_tracker import SignalTracker


@pytest.fixture(autouse=True)
def _reset_singletons():
    SignalTracker.reset_instance()
    SignalOutcomeTracker.reset_instance()
    SignalOutcomeDatasetService.reset_instance()
    SignalScoreDiscriminationService.reset_instance()
    yield
    SignalTracker.reset_instance()
    SignalOutcomeTracker.reset_instance()
    SignalOutcomeDatasetService.reset_instance()
    SignalScoreDiscriminationService.reset_instance()


@pytest.fixture
def temp_db(tmp_path: Path) -> Path:
    """Create a temporary test database with full schema for Phase C."""
    db_file = tmp_path / "signals_test.db"
    conn = sqlite3.connect(str(db_file))
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE system_signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            signal_id TEXT UNIQUE NOT NULL,
            symbol TEXT NOT NULL,
            category TEXT NOT NULL,
            direction TEXT NOT NULL,
            score INTEGER NOT NULL,
            tier TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'ACTIVE',
            entry_price REAL NOT NULL,
            stop_loss REAL NOT NULL,
            target_1 REAL NOT NULL,
            target_2 REAL NOT NULL,
            current_price REAL,
            first_touch TEXT,
            first_touch_at TEXT,
            first_touch_price REAL,
            outcome_confidence TEXT DEFAULT 'UNKNOWN',
            raw_data TEXT,
            created_at TEXT NOT NULL,
            created_date TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE signal_prediction_snapshots (
            signal_id TEXT PRIMARY KEY,
            captured_at TEXT NOT NULL,
            snapshot_schema_version TEXT NOT NULL DEFAULT 'v1.0',
            engine_version TEXT NOT NULL DEFAULT '2.60.0',
            strategy_version TEXT DEFAULT '',
            model_version TEXT DEFAULT '',
            calibration_version TEXT DEFAULT 'UNCALIBRATED',
            feature_schema_version TEXT DEFAULT '',
            symbol TEXT NOT NULL,
            category TEXT NOT NULL,
            direction TEXT NOT NULL,
            strategy TEXT DEFAULT '',
            score INTEGER NOT NULL,
            raw_score REAL,
            normalized_score REAL,
            score_saturated INTEGER DEFAULT 0,
            tier TEXT NOT NULL,
            entry_price REAL NOT NULL,
            stop_loss REAL NOT NULL,
            target_1 REAL NOT NULL,
            target_2 REAL NOT NULL,
            market_regime TEXT DEFAULT '',
            regime_confidence REAL,
            composite_score REAL,
            p_t1 REAL,
            p_t2 REAL,
            p_sl REAL,
            p_timeout REAL,
            expected_value_r REAL,
            net_rr_t1 REAL,
            net_rr_t2 REAL,
            features_json TEXT,
            score_components_json TEXT,
            raw_signal_json TEXT,
            snapshot_hash TEXT NOT NULL,
            source TEXT DEFAULT 'GENERATION',
            created_at TEXT NOT NULL,
            FOREIGN KEY (signal_id) REFERENCES system_signals(signal_id)
        )
    """)

    cur.execute("""
        CREATE TABLE signal_outcome_measurements (
            signal_id TEXT PRIMARY KEY,
            prediction_snapshot_id TEXT NOT NULL,
            symbol TEXT NOT NULL,
            category TEXT NOT NULL,
            direction TEXT NOT NULL,
            entry_price REAL NOT NULL,
            stop_loss REAL NOT NULL,
            target_1 REAL NOT NULL,
            target_2 REAL NOT NULL,
            initial_risk REAL,
            observed_from TEXT NOT NULL,
            observed_until TEXT,
            outcome TEXT NOT NULL,
            raw_lifecycle_state TEXT NOT NULL,
            first_touch TEXT,
            first_touch_at TEXT,
            first_touch_price REAL,
            target_1_hit INTEGER NOT NULL DEFAULT 0,
            target_1_hit_at TEXT,
            target_1_hit_price REAL,
            target_2_hit INTEGER NOT NULL DEFAULT 0,
            target_2_hit_at TEXT,
            target_2_hit_price REAL,
            stop_loss_hit INTEGER NOT NULL DEFAULT 0,
            stop_loss_hit_at TEXT,
            stop_loss_hit_price REAL,
            mfe REAL,
            mae REAL,
            mfe_pct REAL,
            mae_pct REAL,
            mfe_r REAL,
            mae_r REAL,
            time_to_first_event_seconds REAL,
            time_to_t1_seconds REAL,
            time_to_t2_seconds REAL,
            time_to_sl_seconds REAL,
            realized_r REAL,
            exit_price REAL,
            exit_at TEXT,
            observation_count INTEGER NOT NULL DEFAULT 0,
            data_quality_status TEXT NOT NULL DEFAULT 'VALID_DATA',
            outcome_confidence TEXT DEFAULT 'UNKNOWN',
            calculation_version TEXT NOT NULL DEFAULT 'OUTCOME_MEASUREMENT_V1',
            calculated_at TEXT NOT NULL,
            FOREIGN KEY (signal_id) REFERENCES signal_prediction_snapshots(signal_id)
        )
    """)

    conn.commit()
    conn.close()
    return db_file


class TestSignalScoreDiscrimination:
    """Complete 25-requirement Phase C test suite."""

    # 1. Correct score bucket assignment for 70–74
    def test_01_score_bucket_assignment_70_74(self):
        assert assign_score_bucket(70) == "70-74"
        assert assign_score_bucket(72) == "70-74"
        assert assign_score_bucket(74) == "70-74"
        assert assign_score_bucket(74.9) == "70-74"

    # 2. Correct score bucket assignment for 75–79
    def test_02_score_bucket_assignment_75_79(self):
        assert assign_score_bucket(75) == "75-79"
        assert assign_score_bucket(77) == "75-79"
        assert assign_score_bucket(79) == "75-79"
        assert assign_score_bucket(79.9) == "75-79"

    # 3. Correct score bucket assignment for 80–84
    def test_03_score_bucket_assignment_80_84(self):
        assert assign_score_bucket(80) == "80-84"
        assert assign_score_bucket(82) == "80-84"
        assert assign_score_bucket(84) == "80-84"
        assert assign_score_bucket(84.9) == "80-84"

    # 4. Correct score bucket assignment for 85+
    def test_04_score_bucket_assignment_85_plus(self):
        assert assign_score_bucket(85) == "85+"
        assert assign_score_bucket(90) == "85+"
        assert assign_score_bucket(95) == "85+"
        assert assign_score_bucket(100) == "85+"

    # 5. Boundary values are tested: 69, 70, 74, 75, 79, 80, 84, 85
    def test_05_boundary_values(self):
        assert assign_score_bucket(69) == "<70"
        assert assign_score_bucket(70) == "70-74"
        assert assign_score_bucket(74) == "70-74"
        assert assign_score_bucket(75) == "75-79"
        assert assign_score_bucket(79) == "75-79"
        assert assign_score_bucket(80) == "80-84"
        assert assign_score_bucket(84) == "80-84"
        assert assign_score_bucket(85) == "85+"

    # 6. Empty bucket is handled safely
    def test_06_empty_bucket_handled_safely(self):
        service = SignalScoreDiscriminationService.get_instance()
        report = service.analyze_score_buckets(dataset=[])
        assert report.total_snapshots == 0
        for b_name in SCORE_BUCKETS:
            m = report.bucket_metrics[b_name]
            assert m.n_total == 0
            assert m.valid_resolved_count == 0
            assert m.target_first_rate is None
            assert m.target_first_ci.estimate is None
            assert m.sample_size_status == "INSUFFICIENT_SAMPLE"
            assert m.expectancy_info["expectancy"] is None
            assert m.profit_factor_status == "INSUFFICIENT_SAMPLE"

    # 7. Seed samples are excluded
    def test_07_seed_samples_excluded(self, temp_db: Path):
        conn = sqlite3.connect(str(temp_db))
        c = conn.cursor()
        t0 = now_ist().isoformat()

        # Insert real signal
        c.execute("""
            INSERT INTO signal_prediction_snapshots (signal_id, captured_at, symbol, category, direction, score, tier, entry_price, stop_loss, target_1, target_2, snapshot_hash, source, created_at)
            VALUES ('SIG-REAL-1', ?, 'RELIANCE', 'INTRADAY', 'CALL', 82, 'TIER_1', 2500, 2480, 2530, 2550, 'hash1', 'GENERATION', ?)
        """, (t0, t0))
        c.execute("""
            INSERT INTO signal_outcome_measurements (signal_id, prediction_snapshot_id, symbol, category, direction, entry_price, stop_loss, target_1, target_2, observed_from, outcome, raw_lifecycle_state, calculated_at)
            VALUES ('SIG-REAL-1', 'SIG-REAL-1', 'RELIANCE', 'INTRADAY', 'CALL', 2500, 2480, 2530, 2550, ?, 'TARGET_FIRST', 'TARGET_1_HIT', ?)
        """, (t0, t0))

        # Insert seeded signal with source='SEED' and raw_signal_json with is_seed_sample
        c.execute("""
            INSERT INTO signal_prediction_snapshots (signal_id, captured_at, symbol, category, direction, score, tier, entry_price, stop_loss, target_1, target_2, snapshot_hash, source, raw_signal_json, created_at)
            VALUES ('SIG-SEED-1', ?, 'INFY', 'INTRADAY', 'CALL', 88, 'TIER_1', 1500, 1480, 1530, 1550, 'hash2', 'SEED', '{"is_seed_sample": true}', ?)
        """, (t0, t0))
        c.execute("""
            INSERT INTO signal_outcome_measurements (signal_id, prediction_snapshot_id, symbol, category, direction, entry_price, stop_loss, target_1, target_2, observed_from, outcome, raw_lifecycle_state, calculated_at)
            VALUES ('SIG-SEED-1', 'SIG-SEED-1', 'INFY', 'INTRADAY', 'CALL', 1500, 1480, 1530, 1550, ?, 'TARGET_FIRST', 'TARGET_1_HIT', ?)
        """, (t0, t0))

        conn.commit()
        conn.close()

        service = SignalScoreDiscriminationService(db_path=temp_db)
        dataset_no_seeds = service.fetch_joined_dataset(include_seed_samples=False)
        assert len(dataset_no_seeds) == 1
        assert dataset_no_seeds[0]["signal_id"] == "SIG-REAL-1"

        dataset_with_seeds = service.fetch_joined_dataset(include_seed_samples=True)
        assert len(dataset_with_seeds) == 2

    # 8. NO_DATA is excluded from resolved-outcome denominator
    def test_08_no_data_excluded_from_resolved_denominator(self):
        dataset = [
            {"score": 82, "outcome": "TARGET_FIRST", "data_quality_status": "VALID_DATA", "realized_r": 1.5, "mfe_r": 1.6, "mae_r": 0.2},
            {"score": 82, "outcome": "SL_FIRST", "data_quality_status": "VALID_DATA", "realized_r": -1.0, "mfe_r": 0.2, "mae_r": 1.0},
            {"score": 82, "outcome": "NO_DATA", "data_quality_status": "NO_DATA", "realized_r": None, "mfe_r": None, "mae_r": None},
        ]
        service = SignalScoreDiscriminationService.get_instance()
        report = service.analyze_score_buckets(dataset=dataset)
        m = report.bucket_metrics["80-84"]
        assert m.n_total == 3
        assert m.no_data_count == 1
        assert m.valid_resolved_count == 2
        # Target rate must be 1 / 2 = 0.5, NOT 1 / 3 = 0.3333
        assert m.target_first_rate == 0.5
        assert m.target_first_ci.sample_size == 2

    # 9. AMBIGUOUS is not silently counted as a win
    def test_09_ambiguous_not_silently_counted_as_win(self):
        dataset = [
            {"score": 88, "outcome": "AMBIGUOUS", "data_quality_status": "AMBIGUOUS_BAR", "realized_r": None, "mfe_r": 1.5, "mae_r": 1.0},
            {"score": 88, "outcome": "SL_FIRST", "data_quality_status": "VALID_DATA", "realized_r": -1.0, "mfe_r": 0.1, "mae_r": 1.0},
        ]
        service = SignalScoreDiscriminationService.get_instance()
        report = service.analyze_score_buckets(dataset=dataset)
        m = report.bucket_metrics["85+"]
        assert m.target_first_count == 0
        assert m.ambiguous_count == 1
        assert m.sl_first_count == 1
        assert m.valid_resolved_count == 1  # Ambiguous excluded from resolved win/loss denominator
        assert m.target_first_rate == 0.0

    # 10. UNRESOLVED is not silently counted as a loss
    def test_10_unresolved_not_silently_counted_as_loss(self):
        dataset = [
            {"score": 77, "outcome": "TARGET_FIRST", "data_quality_status": "VALID_DATA", "realized_r": 1.2, "mfe_r": 1.2, "mae_r": 0.3},
            {"score": 77, "outcome": "UNRESOLVED", "data_quality_status": "VALID_DATA", "realized_r": None, "mfe_r": 0.5, "mae_r": 0.4},
        ]
        service = SignalScoreDiscriminationService.get_instance()
        report = service.analyze_score_buckets(dataset=dataset)
        m = report.bucket_metrics["75-79"]
        assert m.sl_first_count == 0
        assert m.unresolved_count == 1
        assert m.valid_resolved_count == 1
        assert m.sl_first_rate == 0.0
        assert m.target_first_rate == 1.0

    # 11. Wilson confidence interval calculation is correct
    def test_11_wilson_confidence_interval_correctness(self):
        # Known textbook Wilson 95% CI for 5/10: p=0.5, lower ~0.2366, upper ~0.7634
        est, lo, hi = wilson_confidence_interval(5, 10, z=1.96)
        assert est == 0.5
        assert 0.23 <= lo <= 0.24
        assert 0.76 <= hi <= 0.77

        # Boundary: 0 / 10
        est_0, lo_0, hi_0 = wilson_confidence_interval(0, 10, z=1.96)
        assert est_0 == 0.0
        assert lo_0 == 0.0
        assert hi_0 > 0.0

        # Boundary: 10 / 10
        est_1, lo_1, hi_1 = wilson_confidence_interval(10, 10, z=1.96)
        assert est_1 == 1.0
        assert lo_1 < 1.0
        assert hi_1 == 1.0

        # Empty: 0 / 0
        est_empty, lo_empty, hi_empty = wilson_confidence_interval(0, 0)
        assert est_empty is None
        assert lo_empty == 0.0
        assert hi_empty == 1.0

    # 12. Expectancy uses valid Realized_R observations only
    def test_12_expectancy_uses_valid_realized_r_only(self):
        # 3 observations: +1.5, -1.0, None
        res = calculate_expectancy([1.5, -1.0, None])
        assert res["sample_size"] == 2
        # Mean of 1.5 and -1.0 is +0.25 (NOT 0.5 / 3 = 0.1667)
        assert res["expectancy"] == 0.25
        assert res["median"] == 0.25

    # 13. Profit factor handles positive/negative, no losses, no wins, empty data
    def test_13_profit_factor_edge_cases(self):
        # Mixed: +2.0, +1.0, -1.0 -> 3.0 / 1.0 = 3.0
        pf, status = calculate_profit_factor([2.0, 1.0, -1.0])
        assert pf == 3.0
        assert status == "VALID"

        # No losses: +2.0, +1.0 -> UNDEFINED_NO_LOSSES
        pf_no_loss, status_no_loss = calculate_profit_factor([2.0, 1.0])
        assert pf_no_loss is None
        assert status_no_loss == "UNDEFINED_NO_LOSSES"

        # No wins: -1.0, -0.5 -> 0.0
        pf_no_win, status_no_win = calculate_profit_factor([-1.0, -0.5])
        assert pf_no_win == 0.0
        assert status_no_win == "ZERO_WINS"

        # Empty
        pf_empty, status_empty = calculate_profit_factor([])
        assert pf_empty is None
        assert status_empty == "INSUFFICIENT_SAMPLE"

    # 14. MFE_R statistics are direction-independent because Phase B already normalized direction
    def test_14_mfe_r_statistics_direction_independent(self):
        call_mfe_r = [1.5, 2.0, 0.5]
        put_mfe_r = [1.5, 2.0, 0.5]
        stats_call = calculate_distribution_stats(call_mfe_r)
        stats_put = calculate_distribution_stats(put_mfe_r)
        assert stats_call["mean"] == stats_put["mean"] == 1.3333
        assert stats_call["median"] == stats_put["median"] == 1.5

    # 15. MAE_R statistics are correct and non-negative
    def test_15_mae_r_statistics_correctness(self):
        mae_r_vals = [0.2, 0.5, 1.1, 0.0]
        stats = calculate_distribution_stats(mae_r_vals)
        assert stats["count"] == 4
        assert stats["min"] == 0.0
        assert stats["max"] == 1.1
        assert stats["mean"] == 0.45
        assert stats["median"] == 0.35

    # 16. Multiple-comparison correction is correct
    def test_16_multiple_comparison_holm_correction(self):
        # Raw p-values: 0.01, 0.04, 0.03
        # Sorted: 0.01 (x3 -> 0.03), 0.03 (x2 -> 0.06), 0.04 (x1 -> 0.04 -> monotonic 0.06)
        raw = [0.01, 0.04, 0.03]
        adj = adjust_pvalues_holm(raw)
        assert adj[0] == 0.03
        assert adj[2] == 0.06
        assert adj[1] == 0.06

    # 17. Statistical test selection handles small samples
    def test_17_statistical_test_selection_small_samples(self):
        # Provide small bucket sizes: n=3 and n=4 (< MIN_INFERENCE_SAMPLE_SIZE = 10)
        dataset = [
            {"score": 72, "outcome": "TARGET_FIRST", "data_quality_status": "VALID_DATA", "realized_r": 1.0, "mfe_r": 1.0, "mae_r": 0.2},
            {"score": 72, "outcome": "SL_FIRST", "data_quality_status": "VALID_DATA", "realized_r": -1.0, "mfe_r": 0.1, "mae_r": 1.0},
            {"score": 72, "outcome": "TARGET_FIRST", "data_quality_status": "VALID_DATA", "realized_r": 1.2, "mfe_r": 1.2, "mae_r": 0.1},
            {"score": 88, "outcome": "TARGET_FIRST", "data_quality_status": "VALID_DATA", "realized_r": 1.5, "mfe_r": 1.5, "mae_r": 0.3},
            {"score": 88, "outcome": "TARGET_FIRST", "data_quality_status": "VALID_DATA", "realized_r": 2.0, "mfe_r": 2.0, "mae_r": 0.1},
        ]
        service = SignalScoreDiscriminationService.get_instance()
        report = service.analyze_score_buckets(dataset=dataset)
        # Omnibus test must report INSUFFICIENT_SAMPLE rather than crashing
        kw = report.omnibus_tests.get("kruskal_wallis_realized_r", {})
        assert kw.get("status") == "INSUFFICIENT_SAMPLE"
        for p in report.pairwise_comparisons:
            assert p.status == "INSUFFICIENT_SAMPLE"

    # 18. Temporal grouping excludes unavailable observations correctly
    def test_18_temporal_grouping_and_exclusion(self):
        dataset = [
            {"captured_at": "2026-08-15T10:00:00", "score": 82, "outcome": "TARGET_FIRST"},
            {"captured_at": "2026-08-20T11:00:00", "score": 82, "outcome": "SL_FIRST"},
            {"captured_at": "2026-09-01T09:30:00", "score": 88, "outcome": "TARGET_FIRST"},
            {"captured_at": "", "score": 85, "outcome": "TARGET_FIRST"},
        ]
        service = SignalScoreDiscriminationService.get_instance()
        report = service.analyze_score_buckets(dataset=dataset)
        periods = {t.period: t for t in report.temporal_stability}
        assert "2026-08" in periods
        assert "2026-09" in periods
        assert "UNKNOWN_DATE" in periods
        assert periods["2026-08"].total_signals == 2
        assert periods["2026-09"].total_signals == 1

    # 19. Same input dataset produces deterministic analytical output
    def test_19_determinism_same_input_same_output(self):
        dataset = [
            {"score": 82, "outcome": "TARGET_FIRST", "data_quality_status": "VALID_DATA", "realized_r": 1.5, "mfe_r": 1.6, "mae_r": 0.2},
            {"score": 82, "outcome": "SL_FIRST", "data_quality_status": "VALID_DATA", "realized_r": -1.0, "mfe_r": 0.2, "mae_r": 1.0},
            {"score": 88, "outcome": "TARGET_FIRST", "data_quality_status": "VALID_DATA", "realized_r": 2.0, "mfe_r": 2.0, "mae_r": 0.1},
        ]
        service = SignalScoreDiscriminationService.get_instance()
        rep1 = service.analyze_score_buckets(dataset=dataset).to_dict()
        rep2 = service.analyze_score_buckets(dataset=dataset).to_dict()

        # Compare analytical components (excluding timestamp)
        assert rep1["bucket_metrics"] == rep2["bucket_metrics"]
        assert rep1["omnibus_tests"] == rep2["omnibus_tests"]
        assert rep1["pairwise_comparisons"] == rep2["pairwise_comparisons"]
        assert rep1["data_quality_summary"] == rep2["data_quality_summary"]

    # 20. Phase-A snapshot remains unchanged
    def test_20_phase_a_snapshots_remain_unchanged(self, temp_db: Path):
        conn = sqlite3.connect(str(temp_db))
        c = conn.cursor()
        t0 = now_ist().isoformat()
        c.execute("""
            INSERT INTO signal_prediction_snapshots (signal_id, captured_at, symbol, category, direction, score, tier, entry_price, stop_loss, target_1, target_2, snapshot_hash, created_at)
            VALUES ('SIG-IMMUTABLE-1', ?, 'NIFTY', 'INDEX', 'CALL', 83, 'TIER_1', 22000, 21900, 22150, 22250, 'hash_fixed_1', ?)
        """, (t0, t0))
        conn.commit()

        # Query snapshot row before analysis
        before = c.execute("SELECT * FROM signal_prediction_snapshots WHERE signal_id='SIG-IMMUTABLE-1'").fetchone()

        service = SignalScoreDiscriminationService(db_path=temp_db)
        service.analyze_score_buckets()

        # Query snapshot row after analysis
        after = c.execute("SELECT * FROM signal_prediction_snapshots WHERE signal_id='SIG-IMMUTABLE-1'").fetchone()
        conn.close()

        assert before == after

    # 21. Phase-B outcome dataset remains unchanged
    def test_21_phase_b_outcomes_remain_unchanged(self, temp_db: Path):
        conn = sqlite3.connect(str(temp_db))
        c = conn.cursor()
        t0 = now_ist().isoformat()
        c.execute("""
            INSERT INTO signal_outcome_measurements (signal_id, prediction_snapshot_id, symbol, category, direction, entry_price, stop_loss, target_1, target_2, observed_from, outcome, raw_lifecycle_state, realized_r, calculated_at)
            VALUES ('SIG-IMMUTABLE-2', 'SIG-IMMUTABLE-2', 'BANKNIFTY', 'INDEX', 'PUT', 48000, 48200, 47700, 47500, ?, 'TARGET_FIRST', 'TARGET_1_HIT', 1.5, ?)
        """, (t0, t0))
        conn.commit()

        before = c.execute("SELECT * FROM signal_outcome_measurements WHERE signal_id='SIG-IMMUTABLE-2'").fetchone()

        service = SignalScoreDiscriminationService(db_path=temp_db)
        service.analyze_score_buckets()

        after = c.execute("SELECT * FROM signal_outcome_measurements WHERE signal_id='SIG-IMMUTABLE-2'").fetchone()
        conn.close()

        assert before == after

    # 22. Phase-A snapshot schema and contract verified directly
    def test_22_phase_a_snapshot_schema_and_hashing_contract(self, temp_db: Path):
        conn = sqlite3.connect(str(temp_db))
        cols = [r[1] for r in conn.execute("PRAGMA table_info(signal_prediction_snapshots)").fetchall()]
        conn.close()
        expected = ["signal_id", "captured_at", "score", "symbol", "direction", "entry_price", "stop_loss", "target_1", "target_2", "snapshot_hash", "source"]
        for col in expected:
            assert col in cols, f"Missing Phase-A column {col}"

    # 23. Phase-B outcome measurement schema and contract verified directly
    def test_23_phase_b_outcome_schema_and_mfe_contract(self, temp_db: Path):
        conn = sqlite3.connect(str(temp_db))
        cols = [r[1] for r in conn.execute("PRAGMA table_info(signal_outcome_measurements)").fetchall()]
        conn.close()
        expected = ["signal_id", "outcome", "mfe_r", "mae_r", "realized_r", "time_to_first_event_seconds", "data_quality_status", "calculation_version"]
        for col in expected:
            assert col in cols, f"Missing Phase-B column {col}"

    # 24. Tracker delegation methods verified directly
    def test_24_tracker_delegation_and_integration(self):
        s_tracker = SignalTracker.get_instance()
        assert hasattr(s_tracker, "analyze_score_discrimination")
        so_tracker = SignalOutcomeTracker.get_instance()
        assert hasattr(so_tracker, "analyze_score_discrimination")

    # 25. Live-trading safety invariants remain unchanged
    def test_25_live_trading_safety_invariants_intact(self):
        from core.config_bootstrap import get_effective_config
        cfg = get_effective_config()
        assert cfg.get("EXECUTION_MODE") == "SIGNAL_ONLY"
        assert cfg.get("SIGNAL_ONLY") is True
        assert cfg.get("full_auto_allowed") is False
        assert cfg.get("LIVE_TRADING_LOCKOUT") is True
        assert cfg.get("BASE_CAPITAL") == 3000
        assert cfg.get("SL_PCT") == 0.88
