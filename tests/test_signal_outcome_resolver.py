"""Tests for Historical Signal Outcome Resolver Service (Phase D.2).

Validates:
1. Symbol formatting for Indian equity & index providers.
2. Chronological bar playback without lookahead bias.
3. First-touch immutability across multi-day bars.
4. Same-bar ambiguity quarantining.
5. End-to-end integration: active signals resolved, events logged, and forward observations synchronized.

Governance Authority: OPB-FINAL-PHASE-GOVERNANCE-001
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest
from core.signals.signal_forward_observation import SignalForwardObservationService
from core.signals.signal_outcome_dataset import SignalOutcomeDatasetService
from core.signals.signal_outcome_resolver import HistoricalOutcomeResolverService
from core.signals.signal_outcome_tracker import SignalBar, SignalOutcomeTracker
from core.signals.signal_score_discrimination import SignalScoreDiscriminationService
from core.signals.signal_tracker import SignalTracker


@pytest.fixture(autouse=True)
def _reset_singletons():
    SignalTracker.reset_instance()
    SignalOutcomeTracker.reset_instance()
    SignalOutcomeDatasetService.reset_instance()
    SignalScoreDiscriminationService.reset_instance()
    SignalForwardObservationService.reset_instance()
    HistoricalOutcomeResolverService.reset_instance()
    yield
    SignalTracker.reset_instance()
    SignalOutcomeTracker.reset_instance()
    SignalOutcomeDatasetService.reset_instance()
    SignalScoreDiscriminationService.reset_instance()
    SignalForwardObservationService.reset_instance()
    HistoricalOutcomeResolverService.reset_instance()


@pytest.fixture
def temp_db(tmp_path: Path) -> Path:
    """Create a temporary test database with full canonical schema."""
    db_file = tmp_path / "test_signals_history.db"
    conn = sqlite3.connect(str(db_file))
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE system_signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            signal_id TEXT UNIQUE NOT NULL,
            symbol TEXT NOT NULL,
            category TEXT NOT NULL,
            direction TEXT NOT NULL,
            score INTEGER NOT NULL DEFAULT 80,
            tier TEXT NOT NULL DEFAULT 'TIER_1',
            status TEXT NOT NULL DEFAULT 'ACTIVE',
            entry_price REAL NOT NULL,
            stop_loss REAL NOT NULL,
            target_1 REAL NOT NULL,
            target_2 REAL NOT NULL,
            current_price REAL,
            pnl_pct REAL DEFAULT 0.0,
            first_touch TEXT,
            first_touch_at TEXT,
            first_touch_price REAL,
            outcome_confidence TEXT DEFAULT 'UNKNOWN',
            raw_data TEXT DEFAULT '{}',
            timestamp TEXT NOT NULL,
            created_date TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE user_deliveries (
            delivery_id INTEGER PRIMARY KEY AUTOINCREMENT,
            signal_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            status TEXT NOT NULL,
            current_price REAL,
            pnl_pct REAL
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
        CREATE TABLE signal_outcome_events (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT,
            signal_id TEXT NOT NULL,
            observed_at TEXT NOT NULL,
            observed_price REAL NOT NULL,
            hit_sl INTEGER NOT NULL DEFAULT 0,
            hit_t1 INTEGER NOT NULL DEFAULT 0,
            hit_t2 INTEGER NOT NULL DEFAULT 0,
            transition_note TEXT DEFAULT '',
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

    cur.execute("""
        CREATE TABLE signal_forward_observations (
            forward_id TEXT PRIMARY KEY,
            signal_id TEXT UNIQUE NOT NULL,
            cohort_id TEXT NOT NULL,
            observation_source TEXT NOT NULL DEFAULT 'FORWARD_LIVE_SCAN',
            forward_cutoff_version TEXT NOT NULL DEFAULT 'PHASE_D_V1_20260926',
            registered_at TEXT NOT NULL,
            market_date TEXT NOT NULL,
            session_name TEXT DEFAULT '',
            score INTEGER NOT NULL,
            score_bucket TEXT NOT NULL,
            direction TEXT NOT NULL,
            symbol TEXT NOT NULL,
            category TEXT NOT NULL,
            entry_price REAL NOT NULL,
            stop_loss REAL NOT NULL,
            target_1 REAL NOT NULL,
            target_2 REAL NOT NULL,
            prediction_hash TEXT NOT NULL,
            snapshot_captured_at TEXT NOT NULL,
            observation_status TEXT NOT NULL,
            terminal_outcome TEXT,
            is_resolved INTEGER NOT NULL DEFAULT 0,
            resolution_timestamp TEXT,
            mfe_r REAL,
            mae_r REAL,
            realized_r REAL,
            data_quality_status TEXT NOT NULL DEFAULT 'VALID_DATA',
            observation_version TEXT NOT NULL DEFAULT 'FORWARD_OBSERVATION_V1',
            last_updated_at TEXT NOT NULL,
            FOREIGN KEY (signal_id) REFERENCES signal_prediction_snapshots(signal_id)
        )
    """)

    conn.commit()
    conn.close()
    return db_file


def _insert_test_signal(
    db_file: Path,
    signal_id: str,
    symbol: str = "TEST_SYM",
    category: str = "EQUITY_SWING_DELIVERY",
    direction: str = "CALL",
    score: int = 82,
    entry_price: float = 100.0,
    stop_loss: float = 95.0,
    target_1: float = 105.0,
    target_2: float = 110.0,
    created_date: str = "2026-10-12",
    timestamp: str = "2026-10-12T10:00:00+05:30",
    status: str = "ACTIVE",
) -> None:
    conn = sqlite3.connect(str(db_file))
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO signal_prediction_snapshots (
            signal_id, captured_at, symbol, category, direction, score, tier,
            entry_price, stop_loss, target_1, target_2, snapshot_hash, source,
            raw_signal_json, created_at
        ) VALUES (
            ?, ?, ?, ?, ?, ?, 'TIER_1',
            ?, ?, ?, ?, 'hash_test', 'GENERATION', '{}', ?
        )
    """, (
        signal_id, timestamp, symbol, category, direction, score,
        entry_price, stop_loss, target_1, target_2, timestamp,
    ))
    cur.execute("""
        INSERT OR REPLACE INTO system_signals (
            signal_id, symbol, category, direction, score, tier, status,
            entry_price, stop_loss, target_1, target_2, current_price, pnl_pct, timestamp, created_date
        ) VALUES (
            ?, ?, ?, ?, ?, 'TIER_1', ?,
            ?, ?, ?, ?, ?, 0.0, ?, ?
        )
    """, (
        signal_id, symbol, category, direction, score, status,
        entry_price, stop_loss, target_1, target_2, entry_price, timestamp, created_date,
    ))
    cur.execute("INSERT INTO user_deliveries (signal_id, user_id, status) VALUES (?, 'USER_TEST', ?)", (signal_id, status))
    conn.commit()
    conn.close()


class TestHistoricalOutcomeResolver:
    """Test suite for HistoricalOutcomeResolverService."""

    def test_01_format_yf_symbol(self, temp_db: Path):
        svc = HistoricalOutcomeResolverService.get_instance(db_path=temp_db)
        assert svc.format_yf_symbol("SBIFUNDS") == "SBIFUNDS.NS"
        assert svc.format_yf_symbol("RELIANCE.NS") == "RELIANCE.NS"
        assert svc.format_yf_symbol("NIFTY") == "^NSEI"
        assert svc.format_yf_symbol("BANKNIFTY") == "^NSEBANK"
        assert svc.format_yf_symbol("SENSEX") == "^BSESN"
        assert svc.format_yf_symbol("GBPINR") == "GBPINR=X"
        assert svc.format_yf_symbol("USDINR") == "USDINR=X"

    def test_02_chronological_bar_replay_sl_hit(self, temp_db: Path):
        svc = HistoricalOutcomeResolverService.get_instance(db_path=temp_db)
        sig = {
            "signal_id": "SIG-SWING-1",
            "symbol": "TESTSYM",
            "direction": "CALL",
            "category": "EQUITY_SWING_DELIVERY",
            "entry_price": 100.0,
            "stop_loss": 95.0,
            "target_1": 105.0,
            "target_2": 110.0,
            "status": "ACTIVE",
            "created_date": "2026-10-12",
            "timestamp": "2026-10-12T10:00:00+05:30",
        }

        bars = [
            SignalBar(open=100, high=102, low=98, close=101, timestamp="2026-10-12"),
            SignalBar(open=101, high=103, low=94, close=96, timestamp="2026-10-13"),  # Hits SL 94 <= 95
            SignalBar(open=96, high=112, low=95, close=110, timestamp="2026-10-14"),  # Would hit T1/T2, but halted!
        ]

        eval_res, bar_ts = svc.evaluate_signal_against_bars(sig, bars)
        assert eval_res is not None
        assert eval_res.new_status == "SL_HIT"
        assert eval_res.first_touch == "SL"
        assert eval_res.hit_sl is True
        assert eval_res.is_terminal is True
        assert str(bar_ts).startswith("2026-10-13")

    def test_03_chronological_bar_replay_target_1_then_target_2(self, temp_db: Path):
        svc = HistoricalOutcomeResolverService.get_instance(db_path=temp_db)
        sig = {
            "signal_id": "SIG-SWING-2",
            "symbol": "TESTSYM",
            "direction": "CALL",
            "category": "EQUITY_SWING_DELIVERY",
            "entry_price": 100.0,
            "stop_loss": 95.0,
            "target_1": 105.0,
            "target_2": 110.0,
            "status": "ACTIVE",
            "created_date": "2026-10-12",
            "timestamp": "2026-10-12T10:00:00+05:30",
        }

        # Day 1: Hits T1 (high 106 >= 105)
        # Day 2: Hits T2 (high 111 >= 110)
        bars = [
            SignalBar(open=100, high=106, low=99, close=104, timestamp="2026-10-12"),
            SignalBar(open=104, high=111, low=103, close=109, timestamp="2026-10-13"),
        ]

        eval_res, bar_ts = svc.evaluate_signal_against_bars(sig, bars)
        assert eval_res is not None
        assert eval_res.new_status == "TARGET_2_HIT"
        assert eval_res.first_touch == "T1"
        assert eval_res.hit_t2 is True
        assert eval_res.is_terminal is True
        assert str(bar_ts).startswith("2026-10-13")

    def test_04_same_bar_ambiguity_quarantined(self, temp_db: Path):
        svc = HistoricalOutcomeResolverService.get_instance(db_path=temp_db)
        sig = {
            "signal_id": "SIG-SWING-3",
            "symbol": "TESTSYM",
            "direction": "CALL",
            "category": "EQUITY_SWING_DELIVERY",
            "entry_price": 100.0,
            "stop_loss": 95.0,
            "target_1": 105.0,
            "target_2": 110.0,
            "status": "ACTIVE",
            "created_date": "2026-10-12",
            "timestamp": "2026-10-12T10:00:00+05:30",
        }

        # Single bar touches both SL (94 <= 95) and T1 (106 >= 105)
        bars = [
            SignalBar(open=100, high=106, low=94, close=102, timestamp="2026-10-12"),
        ]

        eval_res, bar_ts = svc.evaluate_signal_against_bars(sig, bars)
        assert eval_res is not None
        assert eval_res.new_status in ("AMBIGUOUS", "AMBIGUOUS_SAME_BAR")
        assert eval_res.first_touch is None  # Quarantined: no first touch attributed
        assert eval_res.is_terminal is True

    def test_05_resolve_all_pending_end_to_end(self, temp_db: Path):
        """End-to-end test verifying DB update, event emission, and forward observation resolution."""
        t0 = "2026-10-12T10:00:00+05:30"
        _insert_test_signal(temp_db, "SIG-E2E-1", symbol="ALPHA", entry_price=100, stop_loss=95, target_1=105, target_2=110, created_date="2026-10-12", timestamp=t0)
        _insert_test_signal(temp_db, "SIG-E2E-2", symbol="BETA", entry_price=200, stop_loss=190, target_1=210, target_2=220, created_date="2026-10-12", timestamp=t0)

        # Register forward observations
        fwd_svc = SignalForwardObservationService(db_path=temp_db)
        fwd_svc.register_forward_signal("SIG-E2E-1", cutoff_iso="2026-10-12T00:00:00+05:30")
        fwd_svc.register_forward_signal("SIG-E2E-2", cutoff_iso="2026-10-12T00:00:00+05:30")

        # Verify initial forward state is OBSERVING
        conn = sqlite3.connect(str(temp_db))
        unres_cnt = conn.execute("SELECT count(*) FROM signal_forward_observations WHERE observation_status = 'OBSERVING'").fetchone()[0]
        assert unres_cnt == 2
        conn.close()

        svc = HistoricalOutcomeResolverService.get_instance(db_path=temp_db)

        # Mock fetch_daily_bars: ALPHA hits SL on day 2; BETA hits T1 on day 1 and T2 on day 2
        def mock_fetch(symbol: str, category: str = "", start_date: str | None = None) -> list[SignalBar]:
            if symbol == "ALPHA":
                return [
                    SignalBar(open=100, high=101, low=98, close=99, timestamp="2026-10-12"),
                    SignalBar(open=99, high=100, low=93, close=94, timestamp="2026-10-13"),  # Low 93 <= 95 (SL hit)
                ]
            elif symbol == "BETA":
                return [
                    SignalBar(open=200, high=212, low=198, close=208, timestamp="2026-10-12"),  # High 212 >= 210 (T1 hit)
                    SignalBar(open=208, high=225, low=206, close=222, timestamp="2026-10-13"),  # High 225 >= 220 (T2 hit)
                ]
            return []

        with patch.object(svc, "fetch_daily_bars", side_effect=mock_fetch):
            res = svc.resolve_all_pending(dry_run=False)

        assert res["status"] == "success"
        assert res["total_pending"] == 2
        assert res["resolved_barriers"] == 2

        # Verify system_signals updated
        conn = sqlite3.connect(str(temp_db))
        r1 = conn.execute("SELECT status, first_touch FROM system_signals WHERE signal_id = 'SIG-E2E-1'").fetchone()
        r2 = conn.execute("SELECT status, first_touch FROM system_signals WHERE signal_id = 'SIG-E2E-2'").fetchone()
        assert r1[0] == "SL_HIT"
        assert r1[1] == "SL"
        assert r2[0] == "TARGET_2_HIT"
        assert r2[1] == "T1"

        # Verify events logged
        events_cnt = conn.execute("SELECT count(*) FROM signal_outcome_events").fetchone()[0]
        assert events_cnt >= 2

        # Verify signal_forward_observations synchronized to RESOLVED
        obs1 = conn.execute("SELECT observation_status, terminal_outcome, is_resolved FROM signal_forward_observations WHERE signal_id = 'SIG-E2E-1'").fetchone()
        obs2 = conn.execute("SELECT observation_status, terminal_outcome, is_resolved FROM signal_forward_observations WHERE signal_id = 'SIG-E2E-2'").fetchone()
        conn.close()

        assert obs1[0] == "RESOLVED"
        assert obs1[1] == "SL_FIRST"
        assert obs1[2] == 1

        assert obs2[0] == "RESOLVED"
        assert obs2[1] == "TARGET_FIRST"
        assert obs2[2] == 1
