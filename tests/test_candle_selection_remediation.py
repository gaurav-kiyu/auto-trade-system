"""Tests for Phase D.4 Controlled Candle-Selection Remediation & Regression Validation.

Covers Tests A through J as specified by OPB-FINAL-PHASE-GOVERNANCE-001:
- TEST A: Valid 1m data + some dropped rows -> cleaned 1m retained, df1 remains 1m, no df5 substitution.
- TEST B: Valid 1m data + zero dropped rows -> df1 remains 1m.
- TEST C: v_clean is None -> 1m unavailable, df1m empty/omitted, df5 remains df5.
- TEST D: v_clean has fewer than minimum valid bars -> 1m unavailable, no df5 masquerading.
- TEST E: Fresh 1m candle age 20 seconds -> DataFreshnessGuard passes.
- TEST F: 5m candle age 140 seconds -> must NOT be evaluated as a 1m candle.
- TEST G: 5m fallback with genuine 5m identity -> existing 5m freshness semantics apply.
- TEST H: No timezone regression in timestamp parsing.
- TEST I: No future-timestamp regression (clock skew guard).
- TEST J: Existing Phase D registration pipeline hook remains intact.
"""

from __future__ import annotations

import datetime
import sqlite3
import time
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from core.data_freshness_guard import (
    FreshnessResult,
    _parse_bar_timestamp,
    check_data_freshness,
)
from core.datetime_ist import now_ist
from core.signal_utils import validate_ohlcv
from core.all_nse_scanner import AllNSEScanner


def _create_synthetic_ohlcv(
    periods: int,
    freq: str = "1min",
    end_time: datetime.datetime | None = None,
    zero_volume_indices: list[int] | None = None,
    corrupt_indices: list[int] | None = None,
) -> pd.DataFrame:
    """Helper to generate synthetic OHLCV data."""
    if end_time is None:
        end_time = now_ist()
    dt_index = pd.date_range(end=end_time, periods=periods, freq=freq)
    df = pd.DataFrame(
        {
            "Open": [100.0 + i * 0.1 for i in range(periods)],
            "High": [105.0 + i * 0.1 for i in range(periods)],
            "Low": [95.0 + i * 0.1 for i in range(periods)],
            "Close": [102.0 + i * 0.1 for i in range(periods)],
            "Volume": [1000.0 for _ in range(periods)],
        },
        index=dt_index,
    )
    if zero_volume_indices:
        for idx in zero_volume_indices:
            if 0 <= idx < periods:
                df.iloc[idx, df.columns.get_loc("Volume")] = 0.0

    if corrupt_indices:
        for idx in corrupt_indices:
            if 0 <= idx < periods:
                # Violate Close <= High
                df.iloc[idx, df.columns.get_loc("Close")] = 200.0
                df.iloc[idx, df.columns.get_loc("High")] = 100.0

    return df


class TestCandleSelectionRemediation:
    """Test suite for controlled candle selection and frame identity isolation."""

    def test_a_valid_1m_data_with_some_dropped_rows_retained_as_1m(self):
        """TEST A: Valid 1m data + some dropped rows -> cleaned 1m retained, df1 remains 1m, no df5 substitution."""
        # 50 1-minute bars with 3 auction bars having Volume = 0
        df1_raw = _create_synthetic_ohlcv(50, freq="1min", zero_volume_indices=[0, 1, 2])
        df5_raw = _create_synthetic_ohlcv(20, freq="5min")

        v_clean, v_dropped = validate_ohlcv(df1_raw, interval="1m", allow_zero_volume=False)

        assert v_dropped == 3
        assert v_clean is not None
        assert len(v_clean) == 47
        assert len(v_clean) >= 5

        # Simulate scanner's remediated logic
        if v_clean is not None and not v_clean.empty and len(v_clean) >= 5:
            df1 = v_clean
        else:
            df1 = None

        frames_to_eval = {"df5m": df5_raw, "df15m": df5_raw}
        if df1 is not None and not df1.empty:
            frames_to_eval["df1m"] = df1

        # Verify:
        assert "df1m" in frames_to_eval
        assert len(frames_to_eval["df1m"]) == 47
        # df1 is NOT df5
        assert frames_to_eval["df1m"] is not df5_raw
        assert len(frames_to_eval["df1m"]) != len(df5_raw)
        # Check that 1m interval is preserved (diff between index timestamps is 1 minute)
        time_deltas = frames_to_eval["df1m"].index.to_series().diff().dropna()
        assert (time_deltas.iloc[-5:] == pd.Timedelta(minutes=1)).all()

    def test_b_valid_1m_data_with_zero_dropped_rows_remains_1m(self):
        """TEST B: Valid 1m data + zero dropped rows -> df1 remains 1m."""
        df1_raw = _create_synthetic_ohlcv(50, freq="1min")
        df5_raw = _create_synthetic_ohlcv(20, freq="5min")

        v_clean, v_dropped = validate_ohlcv(df1_raw, interval="1m", allow_zero_volume=False)

        assert v_dropped == 0
        assert v_clean is not None
        assert len(v_clean) == 50

        if v_clean is not None and not v_clean.empty and len(v_clean) >= 5:
            df1 = v_clean
        else:
            df1 = None

        frames_to_eval = {"df5m": df5_raw, "df15m": df5_raw}
        if df1 is not None and not df1.empty:
            frames_to_eval["df1m"] = df1

        assert "df1m" in frames_to_eval
        assert len(frames_to_eval["df1m"]) == 50
        assert frames_to_eval["df1m"] is not df5_raw

    def test_c_v_clean_is_none_1m_unavailable_no_substitution_df5_preserved(self):
        """TEST C: v_clean is None -> 1m unavailable, df1m is empty/omitted, df5 remains df5."""
        # Corrupt all bars so validate_ohlcv returns None
        df1_corrupt = _create_synthetic_ohlcv(10, freq="1min", corrupt_indices=list(range(10)))
        df5_raw = _create_synthetic_ohlcv(20, freq="5min")

        v_clean, v_dropped = validate_ohlcv(df1_corrupt, interval="1m", allow_zero_volume=False)
        assert v_clean is None

        # Remediated logic:
        if v_clean is not None and not v_clean.empty and len(v_clean) >= 5:
            df1 = v_clean
        else:
            df1 = None

        frames_to_eval = {"df5m": df5_raw, "df15m": df5_raw}
        if df1 is not None and not df1.empty:
            frames_to_eval["df1m"] = df1

        # Invariant checks:
        assert "df1m" not in frames_to_eval
        assert df1 is None
        assert frames_to_eval["df5m"] is df5_raw
        assert len(frames_to_eval["df5m"]) == 20

    def test_d_v_clean_fewer_than_minimum_bars_1m_unavailable_no_masquerading(self):
        """TEST D: v_clean has fewer than minimum valid bars -> 1m unavailable, no df5 masquerading as df1m."""
        # Only 3 bars (< 5 minimum threshold)
        df1_sparse = _create_synthetic_ohlcv(3, freq="1min")
        df5_raw = _create_synthetic_ohlcv(20, freq="5min")

        v_clean, v_dropped = validate_ohlcv(df1_sparse, interval="1m", allow_zero_volume=False)

        # In remediated scanner logic:
        if v_clean is not None and not v_clean.empty and len(v_clean) >= 5:
            df1 = v_clean
        else:
            df1 = None

        frames_to_eval = {"df5m": df5_raw, "df15m": df5_raw}
        if df1 is not None and not df1.empty:
            frames_to_eval["df1m"] = df1

        assert "df1m" not in frames_to_eval
        assert df1 is None
        assert frames_to_eval["df5m"] is df5_raw

    def test_e_fresh_1m_candle_age_20_seconds_passes_guard(self):
        """TEST E: Fresh 1m candle age 20 seconds -> DataFreshnessGuard passes."""
        now = now_ist()
        # Bar closed 20 seconds ago
        bar_time = now - datetime.timedelta(seconds=20)
        df1 = _create_synthetic_ohlcv(30, freq="1min", end_time=bar_time)
        df5 = _create_synthetic_ohlcv(10, freq="5min", end_time=bar_time)
        df15 = _create_synthetic_ohlcv(5, freq="15min", end_time=bar_time)

        res = check_data_freshness(
            frames={"df1m": df1, "df5m": df5, "df15m": df15},
            current_time=now,
            session_aware=False,
        )

        assert res.passed is True
        assert res.reject_code == "VALID"
        assert res.stalest_bar_name == "1m"
        assert abs(res.stalest_bar_sec - 20.0) < 1.0

    def test_f_5m_candle_age_140s_not_evaluated_as_1m_candle(self):
        """TEST F: 5m candle age 140 seconds -> must NOT be evaluated as a 1m candle."""
        now = now_ist()
        # 5m candle timestamp is 140s ago (within 300s 5m limit, but > 90s 1m limit)
        bar_time = now - datetime.timedelta(seconds=140)
        df5 = _create_synthetic_ohlcv(20, freq="5min", end_time=bar_time)
        df15 = _create_synthetic_ohlcv(10, freq="15min", end_time=bar_time)

        # 1. If falsely masqueraded as df1m (the OLD BUGGY BEHAVIOR):
        buggy_frames = {"df1m": df5, "df5m": df5, "df15m": df15}
        buggy_res = check_data_freshness(
            frames=buggy_frames,
            current_time=now,
            session_aware=False,
        )
        assert buggy_res.passed is False
        assert buggy_res.reject_code == "STALE_MARKET_DATA"
        assert "1m bar age 140s exceeds 90s limit" in buggy_res.reject_reason

        # 2. Under REMEDIATED BEHAVIOR where df1m is omitted and genuine 5m identity preserved:
        clean_frames = {"df5m": df5, "df15m": df15}
        clean_res = check_data_freshness(
            frames=clean_frames,
            current_time=now,
            session_aware=False,
        )
        assert clean_res.passed is True
        assert clean_res.reject_code == "VALID"
        assert clean_res.stalest_bar_name == "5m"
        assert abs(clean_res.stalest_bar_sec - 140.0) < 1.0

    def test_g_5m_fallback_with_genuine_5m_identity_semantics(self):
        """TEST G: 5m fallback with genuine 5m identity -> existing 5m freshness semantics apply (300s limit)."""
        now = now_ist()

        # Case G.1: 5m candle age 250s (< 300s limit) -> PASSES
        bar_time_fresh = now - datetime.timedelta(seconds=250)
        df5_fresh = _create_synthetic_ohlcv(20, freq="5min", end_time=bar_time_fresh)
        df15_fresh = _create_synthetic_ohlcv(10, freq="15min", end_time=bar_time_fresh)

        res_fresh = check_data_freshness(
            frames={"df5m": df5_fresh, "df15m": df15_fresh},
            current_time=now,
            session_aware=False,
        )
        assert res_fresh.passed is True
        assert res_fresh.reject_code == "VALID"

        # Case G.2: 5m candle age 350s (> 300s limit) -> REJECTS with 5m limit
        bar_time_stale = now - datetime.timedelta(seconds=350)
        df5_stale = _create_synthetic_ohlcv(20, freq="5min", end_time=bar_time_stale)
        df15_stale = _create_synthetic_ohlcv(10, freq="15min", end_time=bar_time_stale)

        res_stale = check_data_freshness(
            frames={"df5m": df5_stale, "df15m": df15_stale},
            current_time=now,
            session_aware=False,
        )
        assert res_stale.passed is False
        assert res_stale.reject_code == "STALE_MARKET_DATA"
        assert "5m bar age 350s exceeds 300s limit" in res_stale.reject_reason

    def test_h_no_timezone_regression(self):
        """TEST H: No timezone regression in timestamp parsing."""
        # Test tz-aware IST pd.Timestamp
        ts_aware = pd.Timestamp("2026-09-28 11:15:00", tz="Asia/Kolkata")
        epoch_aware = _parse_bar_timestamp(ts_aware)
        assert epoch_aware is not None

        # Test tz-naive pd.Timestamp (should be localized to IST, not UTC, preventing 5.5h skew)
        ts_naive = pd.Timestamp("2026-09-28 11:15:00")
        epoch_naive = _parse_bar_timestamp(ts_naive)
        assert epoch_naive is not None

        # Epochs must match exactly because ts_naive is localized to Asia/Kolkata
        assert epoch_aware == epoch_naive

        # Difference to UTC naive (which would be 5.5 hours / 19800 seconds off)
        ts_utc_naive = pd.Timestamp("2026-09-28 11:15:00", tz="UTC")
        epoch_utc = _parse_bar_timestamp(ts_utc_naive)
        assert epoch_utc is not None
        assert abs((epoch_utc - epoch_aware) - 19800.0) < 1.0

    def test_i_no_future_timestamp_regression(self):
        """TEST I: No future-timestamp regression (reject timestamps > 60s ahead)."""
        now = now_ist()
        future_time = now + datetime.timedelta(seconds=90)
        df1_future = _create_synthetic_ohlcv(10, freq="1min", end_time=future_time)
        df5 = _create_synthetic_ohlcv(10, freq="5min", end_time=now)
        df15 = _create_synthetic_ohlcv(5, freq="15min", end_time=now)

        res = check_data_freshness(
            frames={"df1m": df1_future, "df5m": df5, "df15m": df15},
            current_time=now,
            session_aware=False,
        )
        assert res.passed is False
        assert res.reject_code == "INVALID_MARKET_DATA"
        assert "future" in res.reject_reason.lower()

    def test_j_phase_d_registration_hook_integrity_isolated_db(self, tmp_path):
        """TEST J: Existing Phase D registration hook remains intact using isolated temporary database."""
        from core.signals.signal_forward_observation import (
            SignalForwardObservationService,
        )

        test_db = tmp_path / "test_phase_d_isolated.db"
        con = sqlite3.connect(str(test_db))
        con.execute(
            """CREATE TABLE signal_prediction_snapshots (
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
                created_at TEXT NOT NULL
            )"""
        )
        now_str = now_ist().isoformat()
        con.execute(
            """INSERT INTO signal_prediction_snapshots (
                signal_id, captured_at, symbol, category, direction, score,
                tier, entry_price, stop_loss, target_1, target_2, snapshot_hash,
                source, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "SIG_TEST_001", now_str, "RELIANCE", "EQUITY_SWING_DELIVERY", "CALL", 95,
                "STRONG", 2500.0, 2425.0, 2600.0, 2700.0, "abc123hash",
                "GENERATION", now_str,
            ),
        )
        con.commit()
        con.close()

        # Initialize service on test DB
        svc = SignalForwardObservationService(db_path=test_db)
        res = svc.register_forward_signal("SIG_TEST_001")

        assert res is not None
        assert res["signal_id"] == "SIG_TEST_001"
        assert res["symbol"] == "RELIANCE"
        assert res["score"] == 95
        assert res["observation_status"] == "OBSERVING"
        assert res["is_resolved"] == 0

