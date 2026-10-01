"""Tests for Signal Explainability Data-Contract Remediation.

Governance Authority: OPB-FINAL-PHASE-GOVERNANCE-001
Audits the 15 required lifecycle, observation, excursion, barrier, and expiry scenarios:
1. Swing signal lifecycle
2. Same-created/expiry timestamp cannot be silently accepted as fallback
3. Zero observations
4. Non-zero observations
5. MFE/MAE with observations
6. MFE/MAE without observations
7. Unresolved signal
8. Resolved T1
9. Resolved T2
10. Resolved SL
11. Timeout
12. Ambiguous
13. Exact entry representation
14. Missing Entry By
15. Authoritative expiry

Guarantees:
- Runs in an isolated temporary database.
- Zero mutations to production database.
- Zero modifications to trading engine or scoring logic.
"""

import json
import sqlite3
import tempfile
import gc
from pathlib import Path
import pytest

from core.signals.signal_tracker import SignalTracker


@pytest.fixture
def temp_tracker():
    """Create an isolated SignalTracker with a temporary SQLite database."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_file = Path(tmpdir) / "test_signals.db"
        SignalTracker.reset_instance()
        tracker = SignalTracker(db_path=db_file)

        # Create signal_outcome_measurements table in the test database
        conn = tracker._get_conn()
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS signal_outcome_measurements (
                signal_id TEXT PRIMARY KEY,
                prediction_snapshot_id TEXT,
                symbol TEXT,
                category TEXT,
                direction TEXT,
                entry_price REAL,
                stop_loss REAL,
                target_1 REAL,
                target_2 REAL,
                initial_risk REAL,
                observed_from TEXT,
                observed_until TEXT,
                outcome TEXT,
                raw_lifecycle_state TEXT,
                first_touch TEXT,
                first_touch_at TEXT,
                first_touch_price REAL,
                target_1_hit INTEGER,
                target_1_hit_at TEXT,
                target_1_hit_price REAL,
                target_2_hit INTEGER,
                target_2_hit_at TEXT,
                target_2_hit_price REAL,
                stop_loss_hit INTEGER,
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
                observation_count INTEGER,
                data_quality_status TEXT,
                outcome_confidence TEXT,
                calculation_version TEXT,
                calculated_at TEXT NOT NULL
            )
        """)
        conn.commit()
        conn.close()

        yield tracker
        SignalTracker.reset_instance()
        gc.collect()


def _insert_signal(tracker, signal_id, symbol="IRCTC", category="MID_SMALL_CAP", direction="CALL",
                    entry_price=463.80, stop_loss=449.89, target_1=482.35, target_2=500.90,
                    status="ACTIVE", timestamp="2026-09-30 11:59:47", raw_data=None):
    if raw_data is None:
        raw_data = {
            "symbol": symbol,
            "category": category,
            "direction": direction,
            "price": entry_price,
            "raw_score": 95,
            "normalized_score": 80,
            "score_components": {"tf_aligned": 20, "vwap": 20, "d1_momentum": 15},
        }
    conn = tracker._get_conn()
    c = conn.cursor()
    c.execute("""
        INSERT INTO system_signals (
            signal_id, timestamp, created_date, created_week, created_month, created_year,
            symbol, category, direction, score, tier, entry_price, stop_loss, target_1, target_2,
            current_price, status, pnl_pct, raw_data, raw_score, normalized_score
        ) VALUES (?, ?, '2026-09-30', '2026-W40', '2026-09', 2026,
                  ?, ?, ?, 80, 'STRONG', ?, ?, ?, ?,
                  ?, ?, 0.0, ?, 95.0, 80.0)
    """, (
        signal_id, timestamp, symbol, category, direction,
        entry_price, stop_loss, target_1, target_2,
        entry_price, status, json.dumps(raw_data)
    ))
    conn.commit()
    conn.close()


def _insert_measurements(tracker, signal_id, **kwargs):
    fields = {
        "signal_id": signal_id,
        "prediction_snapshot_id": signal_id,
        "symbol": "IRCTC",
        "category": "MID_SMALL_CAP",
        "direction": "CALL",
        "entry_price": 463.80,
        "stop_loss": 449.89,
        "target_1": 482.35,
        "target_2": 500.90,
        "initial_risk": 13.91,
        "observed_from": "2026-09-30T11:59:47",
        "observed_until": "2026-09-30T11:59:47",
        "outcome": "UNRESOLVED",
        "raw_lifecycle_state": "ACTIVE",
        "first_touch": None,
        "target_1_hit": 0,
        "target_2_hit": 0,
        "stop_loss_hit": 0,
        "mfe": 0.0,
        "mae": 9.0,
        "mfe_pct": 0.0,
        "mae_pct": 1.94,
        "mfe_r": 0.0,
        "mae_r": 0.65,
        "observation_count": 0,
        "data_quality_status": "VALID_DATA",
        "outcome_confidence": "POLLING",
        "calculation_version": "OUTCOME_MEASUREMENT_V1",
        "calculated_at": "2026-09-30T12:00:00",
    }
    fields.update(kwargs)
    cols = ", ".join(fields.keys())
    placeholders = ", ".join("?" * len(fields))
    conn = tracker._get_conn()
    c = conn.cursor()
    c.execute(f"INSERT OR REPLACE INTO signal_outcome_measurements ({cols}) VALUES ({placeholders})", list(fields.values()))
    conn.commit()
    conn.close()


# ── Scenario 1: Swing signal lifecycle ─────────────────────────────────────────
def test_swing_signal_lifecycle(temp_tracker):
    sig_id = "SIG-TEST-001"
    _insert_signal(temp_tracker, sig_id, category="MID_SMALL_CAP")
    exp = temp_tracker.get_signal_explanation(sig_id)
    assert exp is not None
    assert exp["holding_horizon"] == "1–5 Days (Swing)"
    assert exp["lifecycle"]["holding_horizon"] == "1–5 Days (Swing)"


# ── Scenario 2: Same-created/expiry timestamp rejected ────────────────────────
def test_same_created_and_expiry_timestamp_rejected(temp_tracker):
    sig_id = "SIG-TEST-002"
    ts = "2026-09-30T11:59:47"
    raw = {
        "symbol": "IRCTC",
        "expiry_date": ts,  # equals creation timestamp
        "score_components": {"vwap": 10},
    }
    _insert_signal(temp_tracker, sig_id, timestamp=ts, raw_data=raw)
    exp = temp_tracker.get_signal_explanation(sig_id)
    assert exp is not None
    assert exp["exit_by"] is None
    assert exp["lifecycle"]["exit_by"] is None


# ── Scenario 3: Zero observations ─────────────────────────────────────────────
def test_zero_observations(temp_tracker):
    sig_id = "SIG-TEST-003"
    _insert_signal(temp_tracker, sig_id)
    _insert_measurements(temp_tracker, sig_id, observation_count=0)
    exp = temp_tracker.get_signal_explanation(sig_id)
    assert exp["observation_count"] == 0
    assert exp["observation_start"] is None
    assert exp["observation_end"] is None
    assert exp["lifecycle"]["observed_from"] is None
    assert exp["lifecycle"]["observed_until"] is None


# ── Scenario 4: Non-zero observations ─────────────────────────────────────────
def test_nonzero_observations(temp_tracker):
    sig_id = "SIG-TEST-004"
    _insert_signal(temp_tracker, sig_id)
    _insert_measurements(
        temp_tracker, sig_id,
        observation_count=15,
        observed_from="2026-09-30T12:00:00",
        observed_until="2026-09-30T13:15:00",
    )
    exp = temp_tracker.get_signal_explanation(sig_id)
    assert exp["observation_count"] == 15
    assert exp["observation_start"] == "2026-09-30T12:00:00"
    assert exp["observation_end"] == "2026-09-30T13:15:00"


# ── Scenario 5: MFE/MAE with observations ─────────────────────────────────────
def test_mfe_mae_with_observations(temp_tracker):
    sig_id = "SIG-TEST-005"
    _insert_signal(temp_tracker, sig_id)
    _insert_measurements(
        temp_tracker, sig_id,
        observation_count=5,
        mfe=12.50,
        mae=4.20,
        mfe_pct=2.70,
        mae_pct=0.91,
        mfe_r=0.90,
        mae_r=0.30,
    )
    exp = temp_tracker.get_signal_explanation(sig_id)
    assert exp["mfe"] == 12.50
    assert exp["mae"] == 4.20
    assert exp["excursion"]["mfe_pct"] == 2.70
    assert exp["excursion"]["mae_r"] == 0.30
    assert exp["evaluated"] is True


# ── Scenario 6: MFE/MAE without observations ──────────────────────────────────
def test_mfe_mae_without_observations(temp_tracker):
    sig_id = "SIG-TEST-006"
    _insert_signal(temp_tracker, sig_id)
    # Stored measurements has mae=9.0 from current_price fallback, but observation_count=0
    _insert_measurements(temp_tracker, sig_id, observation_count=0, mae=9.0, mfe=0.0)
    exp = temp_tracker.get_signal_explanation(sig_id)
    assert exp["mfe"] is None
    assert exp["mae"] is None
    assert exp["excursion"]["mfe"] is None
    assert exp["excursion"]["mae"] is None
    assert exp["evaluated"] is False


# ── Scenario 7: Unresolved signal ─────────────────────────────────────────────
def test_unresolved_signal(temp_tracker):
    sig_id = "SIG-TEST-007"
    _insert_signal(temp_tracker, sig_id, status="ACTIVE")
    _insert_measurements(temp_tracker, sig_id, outcome="UNRESOLVED", observation_count=0)
    exp = temp_tracker.get_signal_explanation(sig_id)
    assert exp["is_observing"] is True
    assert exp["first_touch"] is None
    assert exp["exit_price"] is None


# ── Scenario 8: Resolved T1 ───────────────────────────────────────────────────
def test_resolved_target_1(temp_tracker):
    sig_id = "SIG-TEST-008"
    _insert_signal(temp_tracker, sig_id, status="TARGET_1_HIT")
    _insert_measurements(
        temp_tracker, sig_id,
        outcome="TARGET_FIRST",
        target_1_hit=1,
        first_touch="T1",
        exit_price=482.35,
        observation_count=20,
    )
    exp = temp_tracker.get_signal_explanation(sig_id)
    assert exp["is_observing"] is False
    assert exp["target_1_hit"] is True
    assert exp["first_touch"] == "T1"
    assert exp["exit_price"] == 482.35
    assert exp["lifecycle"]["outcome"] == "TARGET_1"


# ── Scenario 9: Resolved T2 ───────────────────────────────────────────────────
def test_resolved_target_2(temp_tracker):
    sig_id = "SIG-TEST-009"
    _insert_signal(temp_tracker, sig_id, status="TARGET_2_HIT")
    _insert_measurements(
        temp_tracker, sig_id,
        outcome="TARGET_FIRST",
        target_1_hit=1,
        target_2_hit=1,
        first_touch="T1",
        exit_price=500.90,
        observation_count=35,
    )
    exp = temp_tracker.get_signal_explanation(sig_id)
    assert exp["is_observing"] is False
    assert exp["target_1_hit"] is True
    assert exp["target_2_hit"] is True
    assert exp["lifecycle"]["outcome"] == "TARGET_2"


# ── Scenario 10: Resolved SL ──────────────────────────────────────────────────
def test_resolved_stop_loss(temp_tracker):
    sig_id = "SIG-TEST-010"
    _insert_signal(temp_tracker, sig_id, status="SL_HIT")
    _insert_measurements(
        temp_tracker, sig_id,
        outcome="SL_FIRST",
        stop_loss_hit=1,
        first_touch="SL",
        exit_price=449.89,
        observation_count=10,
    )
    exp = temp_tracker.get_signal_explanation(sig_id)
    assert exp["is_observing"] is False
    assert exp["stop_loss_hit"] is True
    assert exp["first_touch"] == "SL"
    assert exp["exit_price"] == 449.89
    assert exp["lifecycle"]["outcome"] == "STOP_LOSS"


# ── Scenario 11: Timeout ──────────────────────────────────────────────────────
def test_timeout(temp_tracker):
    sig_id = "SIG-TEST-011"
    _insert_signal(temp_tracker, sig_id, status="EXPIRED")
    _insert_measurements(
        temp_tracker, sig_id,
        outcome="TIMEOUT",
        observation_count=50,
        exit_price=460.00,
    )
    exp = temp_tracker.get_signal_explanation(sig_id)
    assert exp["is_observing"] is False
    assert exp["lifecycle"]["outcome"] == "TIMEOUT"


# ── Scenario 12: Ambiguous ────────────────────────────────────────────────────
def test_ambiguous(temp_tracker):
    sig_id = "SIG-TEST-012"
    _insert_signal(temp_tracker, sig_id, status="AMBIGUOUS")
    _insert_measurements(
        temp_tracker, sig_id,
        outcome="AMBIGUOUS",
        observation_count=12,
    )
    exp = temp_tracker.get_signal_explanation(sig_id)
    assert exp["lifecycle"]["outcome"] == "AMBIGUOUS"


# ── Scenario 13: Exact entry representation ───────────────────────────────────
def test_exact_entry_representation(temp_tracker):
    sig_id = "SIG-TEST-013"
    _insert_signal(temp_tracker, sig_id, entry_price=463.80)
    exp = temp_tracker.get_signal_explanation(sig_id)
    assert exp["entry_price"] == 463.80
    assert exp["entry_range"] == "₹463.80"
    assert "NOT PARAMETERIZED" not in str(exp["entry_range"])


# ── Scenario 14: Missing Entry By ─────────────────────────────────────────────
def test_missing_entry_by(temp_tracker):
    sig_id = "SIG-TEST-014"
    _insert_signal(temp_tracker, sig_id)
    exp = temp_tracker.get_signal_explanation(sig_id)
    assert exp["entry_by"] is None
    assert exp["lifecycle"]["entry_by"] is None


# ── Scenario 15: Authoritative expiry ─────────────────────────────────────────
def test_authoritative_expiry(temp_tracker):
    sig_id = "SIG-TEST-015"
    raw = {
        "symbol": "NIFTY",
        "category": "INDEX_OPTIONS",
        "expiry_date": "2026-10-08",
        "score_components": {"pcr": 10},
    }
    _insert_signal(
        temp_tracker, sig_id,
        category="INDEX_OPTIONS",
        timestamp="2026-09-30 09:15:00",
        raw_data=raw,
    )
    exp = temp_tracker.get_signal_explanation(sig_id)
    assert exp["exit_by"] == "2026-10-08"
    assert exp["lifecycle"]["exit_by"] == "2026-10-08"
    assert exp["holding_horizon"] == "Intraday (<15:15 IST)"


# ── Scenario 16: Valid From & IST formatting ──────────────────────────────────
def test_valid_from_and_ist_formatting(temp_tracker):
    sig_id = "SIG-TEST-016"
    _insert_signal(temp_tracker, sig_id, timestamp="2026-10-01 10:30:00")
    exp = temp_tracker.get_signal_explanation(sig_id)
    assert exp["valid_from"] == "2026-10-01 10:30:00 IST"
    assert exp["lifecycle"]["valid_from"] == "2026-10-01 10:30:00 IST"


# ── Scenario 17: Max Exit Time derivation ─────────────────────────────────────
def test_max_exit_time_derivation(temp_tracker):
    # With explicit expiry in raw_data
    sig_id1 = "SIG-TEST-017A"
    raw1 = {
        "symbol": "BANKNIFTY",
        "category": "INDEX_OPTIONS",
        "expiry_date": "2026-10-08 15:30:00",
        "score_components": {"vwap": 20},
    }
    _insert_signal(temp_tracker, sig_id1, category="INDEX_OPTIONS", raw_data=raw1)
    exp1 = temp_tracker.get_signal_explanation(sig_id1)
    assert "2026-10-08" in exp1["max_exit_time"]
    assert exp1["max_exit_time"].endswith("IST")
    assert exp1["lifecycle"]["max_exit_time"] == exp1["max_exit_time"]

    # Without explicit expiry (horizon fallback)
    sig_id2 = "SIG-TEST-017B"
    _insert_signal(temp_tracker, sig_id2, category="INTRADAY_EQUITY", timestamp="2026-10-01 11:00:00")
    exp2 = temp_tracker.get_signal_explanation(sig_id2)
    assert exp2["max_exit_time"] != "Not parameterized"
    assert "IST" in exp2["max_exit_time"]


# ── Scenario 18: Outcome Status explicit human-readable values ────────────────
def test_outcome_status_explicit_values(temp_tracker):
    mappings = [
        ("TARGET_FIRST", 0, "Target-1"),
        ("TARGET_FIRST", 1, "Target-2"),
        ("SL_FIRST", 0, "Stop Loss"),
        ("TIMEOUT", 0, "Expired"),
        ("AMBIGUOUS", 0, "Ambiguous"),
        ("UNRESOLVED", 0, "Unresolved"),
    ]
    for idx, (m_outcome, t2_hit, expected_status) in enumerate(mappings):
        sig_id = f"SIG-TEST-018-{idx}"
        _insert_signal(temp_tracker, sig_id)
        _insert_measurements(
            temp_tracker, sig_id,
            outcome=m_outcome,
            target_2_hit=t2_hit,
            observation_count=5,
        )
        exp = temp_tracker.get_signal_explanation(sig_id)
        assert exp["outcome_status"] == expected_status, f"Failed for outcome {m_outcome} / t2={t2_hit}"
        assert exp["lifecycle"]["outcome_status"] == expected_status

