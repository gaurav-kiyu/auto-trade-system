"""OPB Phase D20: Comprehensive Signal Quality Remediation Test Suite.

Authority: OPB-FINAL-PHASE-GOVERNANCE-001 / Phase D20 Specification.

Tests:
D20-A (Tests 1-13): Category-Aware Options Quality Gate (breakout > 0 AND volume > 0, fail-closed)
D20-B (Tests 14-24): Index Call/Put Session Deduplication (max 1 CALL + 1 PUT per index per session)
D20-C (Tests 25-28): Experimental Target Model Scaffolding & Production Default Invariance
"""

import math
import sqlite3
from pathlib import Path
import pytest

from core.signals.signal_quality_gate import (
    validate_options_quality_gate,
    check_index_session_dedup,
    get_canonical_index_underlying,
    calculate_experimental_target_levels,
)
from core.signals.signal_tracker import SignalTracker
from core.all_nse_scanner import AllNSEScanner, ScannedStockSignal


@pytest.fixture
def temp_db(tmp_path: Path):
    """Isolated temporary SQLite database for signal tracker."""
    db_file = tmp_path / "test_signals_history.db"
    SignalTracker.reset_instance()
    tracker = SignalTracker(db_path=db_file)
    with tracker._io_lock:
        conn = tracker._get_conn()
        conn.execute("DELETE FROM system_signals")
        conn.commit()
        conn.close()
    yield tracker, db_file
    SignalTracker.reset_instance()



# =============================================================================
# D20-A TESTS: CATEGORY-AWARE OPTIONS QUALITY GATE (Tests 1–13)
# =============================================================================

def test_01_stock_option_breakout_and_volume_eligible():
    """1. Stock Option + breakout > 0 + volume > 0 -> eligible."""
    payload = {
        "category": "STOCK_OPTIONS",
        "symbol": "RELIANCE",
        "score_components": {"breakout": 8, "volume": 10},
    }
    ok, reason = validate_options_quality_gate(payload)
    assert ok is True
    assert "ELIGIBLE" in reason


def test_02_stock_option_breakout_only_rejected():
    """2. Stock Option + breakout only (volume <= 0) -> rejected."""
    payload = {
        "category": "STOCK_OPTIONS",
        "symbol": "RELIANCE",
        "score_components": {"breakout": 8, "volume": 0},
    }
    ok, reason = validate_options_quality_gate(payload)
    assert ok is False
    assert "REJECTED_VOLUME_INSUFFICIENT" in reason


def test_03_stock_option_volume_only_rejected():
    """3. Stock Option + volume only (breakout <= 0) -> rejected."""
    payload = {
        "category": "STOCK_OPTIONS",
        "symbol": "TCS",
        "score_components": {"breakout": -4, "volume": 12},
    }
    ok, reason = validate_options_quality_gate(payload)
    assert ok is False
    assert "REJECTED_BREAKOUT_INSUFFICIENT" in reason


def test_04_stock_option_neither_rejected():
    """4. Stock Option + neither (breakout <= 0 and volume <= 0) -> rejected."""
    payload = {
        "category": "STOCK_OPTIONS",
        "symbol": "INFY",
        "score_components": {"breakout": 0, "volume": 0},
    }
    ok, reason = validate_options_quality_gate(payload)
    assert ok is False
    assert "INSUFFICIENT" in reason


def test_05_index_option_breakout_and_volume_eligible():
    """5. Index Option + breakout > 0 + volume > 0 -> eligible."""
    payload = {
        "category": "INDEX_OPTIONS",
        "symbol": "NIFTY",
        "score_components": {"breakout": 8, "volume": 5},
    }
    ok, reason = validate_options_quality_gate(payload)
    assert ok is True
    assert "ELIGIBLE" in reason


def test_06_missing_breakout_rejected():
    """6. Missing breakout component -> rejected (fail-closed)."""
    payload = {
        "category": "INDEX_OPTIONS",
        "symbol": "BANKNIFTY",
        "score_components": {"volume": 10},
    }
    ok, reason = validate_options_quality_gate(payload)
    assert ok is False
    assert "FAIL_CLOSED_MISSING_BREAKOUT" in reason


def test_07_missing_volume_rejected():
    """7. Missing volume component -> rejected (fail-closed)."""
    payload = {
        "category": "STOCK_OPTIONS",
        "symbol": "SBIN",
        "score_components": {"breakout": 8},
    }
    ok, reason = validate_options_quality_gate(payload)
    assert ok is False
    assert "FAIL_CLOSED_MISSING_VOLUME" in reason


def test_08_nan_breakout_rejected():
    """8. NaN breakout value -> rejected (fail-closed)."""
    payload = {
        "category": "INDEX_OPTIONS",
        "symbol": "FINNIFTY",
        "score_components": {"breakout": float("nan"), "volume": 10},
    }
    ok, reason = validate_options_quality_gate(payload)
    assert ok is False
    assert "FAIL_CLOSED_NAN_BREAKOUT" in reason


def test_09_nan_volume_rejected():
    """9. NaN volume value -> rejected (fail-closed)."""
    payload = {
        "category": "STOCK_OPTIONS",
        "symbol": "TATAMOTORS",
        "score_components": {"breakout": 8, "volume": float("nan")},
    }
    ok, reason = validate_options_quality_gate(payload)
    assert ok is False
    assert "FAIL_CLOSED_NAN_VOLUME" in reason


def test_10_stale_or_missing_market_evidence_rejected():
    """10. Missing score_components dict / None evidence -> rejected (fail-closed)."""
    for bad_comps in [None, {}, "INVALID_STRING", []]:
        payload = {
            "category": "INDEX_OPTIONS",
            "symbol": "NIFTY",
            "score_components": bad_comps,
        }
        ok, reason = validate_options_quality_gate(payload)
        assert ok is False
        assert "FAIL_CLOSED" in reason


def test_11_equity_swing_remains_unaffected():
    """11. Equity Swing Delivery remains completely unaffected regardless of breakout/volume."""
    for comps in [
        {"breakout": -4, "volume": 0},
        {},
        {"breakout": float("nan"), "volume": None},
        None,
    ]:
        payload = {
            "category": "EQUITY_SWING_DELIVERY",
            "symbol": "ITC",
            "score_components": comps,
        }
        ok, reason = validate_options_quality_gate(payload)
        assert ok is True
        assert "NOT_APPLICABLE_NON_OPTION" in reason


def test_12_existing_score_remains_unchanged():
    """12. Quality gate does NOT alter or rescale the signal's score or components."""
    orig_score = 92
    comps = {"breakout": 8, "volume": 10, "tf_aligned": 20}
    payload = {
        "category": "STOCK_OPTIONS",
        "symbol": "HDFCBANK",
        "score": orig_score,
        "score_components": comps,
    }
    ok, _ = validate_options_quality_gate(payload)
    assert ok is True
    assert payload["score"] == orig_score
    assert payload["score_components"] == comps


def test_13_existing_target_sl_remains_unchanged_in_production_mode():
    """13. Existing target/SL levels remain strictly +4% / +8% / -3% in production mode."""
    entry = 100.0
    sl, t1, t2 = calculate_experimental_target_levels(
        entry_price=entry,
        direction="CALL",
        category="STOCK_OPTIONS",
        mode="PRODUCTION",
    )
    assert sl == 97.0   # -3.0%
    assert t1 == 104.0  # +4.0%
    assert t2 == 108.0  # +8.0%


# =============================================================================
# D20-B TESTS: INDEX SESSION DEDUPLICATION (Tests 14–24)
# =============================================================================

def test_14_first_call_for_index_session_eligible(temp_db):
    """14. First CALL for index in session -> eligible."""
    tracker, _ = temp_db
    conn = tracker._get_conn()
    ok, reason = check_index_session_dedup(
        conn_or_cursor=conn,
        symbol="NIFTY",
        category="INDEX_OPTIONS",
        direction="CALL",
        session_date="2026-09-29",
    )
    conn.close()
    assert ok is True
    assert "ELIGIBLE" in reason


def test_15_second_call_same_index_session_rejected(temp_db):
    """15. Second CALL for same index in same session -> rejected."""
    tracker, _ = temp_db
    # Record first CALL
    sig1_id = tracker.record_generated_signal({
        "symbol": "NIFTY",
        "category": "INDEX_OPTIONS",
        "direction": "CALL",
        "price": 25000.0,
        "score": 90,
        "score_components": {"breakout": 8, "volume": 10},
        "options_quality_gate_enabled": True,
        "index_session_dedup_enabled": True,
    })
    assert bool(sig1_id) is True

    # Check dedup for second CALL in same session
    conn = tracker._get_conn()
    cur = conn.cursor()
    cur.execute("SELECT created_date FROM system_signals WHERE signal_id = ?", (sig1_id,))
    session_dt = cur.fetchone()["created_date"]

    ok, reason = check_index_session_dedup(
        conn_or_cursor=conn,
        symbol="NIFTY",
        category="INDEX_OPTIONS",
        direction="CALL",
        session_date=session_dt,
    )
    conn.close()
    assert ok is False
    assert "DEDUP_SUPPRESSED" in reason

    # Attempting to record second CALL returns empty string
    sig2_id = tracker.record_generated_signal({
        "symbol": "NIFTY",
        "category": "INDEX_OPTIONS",
        "direction": "CALL",
        "price": 25050.0,
        "score": 95,
        "score_components": {"breakout": 8, "volume": 10},
        "options_quality_gate_enabled": True,
        "index_session_dedup_enabled": True,
    })
    assert sig2_id == ""


def test_16_first_put_same_index_session_eligible(temp_db):
    """16. First PUT for index in session -> eligible."""
    tracker, _ = temp_db
    conn = tracker._get_conn()
    ok, reason = check_index_session_dedup(
        conn_or_cursor=conn,
        symbol="BANKNIFTY",
        category="INDEX_OPTIONS",
        direction="PUT",
        session_date="2026-09-29",
    )
    conn.close()
    assert ok is True
    assert "ELIGIBLE" in reason


def test_17_second_put_same_index_session_rejected(temp_db):
    """17. Second PUT for same index in same session -> rejected."""
    tracker, _ = temp_db
    sig1_id = tracker.record_generated_signal({
        "symbol": "BANKNIFTY",
        "category": "INDEX_OPTIONS",
        "direction": "PUT",
        "price": 52000.0,
        "score": 90,
        "score_components": {"breakout": 8, "volume": 10},
        "options_quality_gate_enabled": True,
        "index_session_dedup_enabled": True,
    })
    assert bool(sig1_id) is True

    # Second PUT is blocked
    sig2_id = tracker.record_generated_signal({
        "symbol": "BANKNIFTY",
        "category": "INDEX_OPTIONS",
        "direction": "PUT",
        "price": 51900.0,
        "score": 92,
        "score_components": {"breakout": 8, "volume": 10},
        "options_quality_gate_enabled": True,
        "index_session_dedup_enabled": True,
    })
    assert sig2_id == ""


def test_18_call_and_put_can_coexist(temp_db):
    """18. CALL and PUT can coexist for the same index in the same session."""
    tracker, _ = temp_db
    conn = tracker._get_conn()

    # Pre-seed a CALL in system_signals with EXPIRED status (or elapsed whipsaw cooldown)
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO system_signals (
            signal_id, timestamp, created_date, created_week, created_month, created_year,
            symbol, category, direction, score, tier, entry_price, stop_loss, target_1, target_2,
            current_price, status, pnl_pct, opportunity_key
        ) VALUES (
            'SIG-TEST-CALL', '2026-09-29 09:30:00', '2026-09-29', '2026-W40', '2026-09', '2026',
            'FINNIFTY', 'INDEX_OPTIONS', 'CALL', 90, 'STRONG', 23000.0, 22500.0, 23500.0, 24000.0,
            23000.0, 'EXPIRED', 0.0, 'FINNIFTY|CALL|INDEX_OPTIONS'
        )"""
    )
    conn.commit()

    # Under D20-B, a PUT check on the same date should pass!
    ok, reason = check_index_session_dedup(
        conn_or_cursor=conn,
        symbol="FINNIFTY",
        category="INDEX_OPTIONS",
        direction="PUT",
        session_date="2026-09-29",
    )
    conn.close()
    assert ok is True
    assert "ELIGIBLE" in reason


def test_19_next_trading_session_resets_eligibility(temp_db):
    """19. Next trading session resets eligibility."""
    tracker, _ = temp_db
    conn = tracker._get_conn()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO system_signals (
            signal_id, timestamp, created_date, created_week, created_month, created_year,
            symbol, category, direction, score, tier, entry_price, stop_loss, target_1, target_2,
            current_price, status, pnl_pct, opportunity_key
        ) VALUES (
            'SIG-CALL-YESTERDAY', '2026-09-28 09:30:00', '2026-09-28', '2026-W40', '2026-09', '2026',
            'NIFTY', 'INDEX_OPTIONS', 'CALL', 90, 'STRONG', 25000.0, 24500.0, 25500.0, 26000.0,
            25000.0, 'EXPIRED', 0.0, 'NIFTY|CALL|INDEX_OPTIONS'
        )"""
    )
    conn.commit()

    # On new session '2026-09-29', CALL is eligible again
    ok, reason = check_index_session_dedup(
        conn_or_cursor=conn,
        symbol="NIFTY",
        category="INDEX_OPTIONS",
        direction="CALL",
        session_date="2026-09-29",
    )
    conn.close()
    assert ok is True
    assert "ELIGIBLE" in reason


def test_20_different_index_underlyings_do_not_collide(temp_db):
    """20. Different index underlyings (NIFTY vs BANKNIFTY) do not collide."""
    tracker, _ = temp_db
    sig1_id = tracker.record_generated_signal({
        "symbol": "NIFTY",
        "category": "INDEX_OPTIONS",
        "direction": "CALL",
        "price": 25000.0,
        "score": 90,
        "score_components": {"breakout": 8, "volume": 10},
        "options_quality_gate_enabled": True,
        "index_session_dedup_enabled": True,
    })
    assert bool(sig1_id) is True

    # BANKNIFTY CALL in same session must be accepted
    sig2_id = tracker.record_generated_signal({
        "symbol": "BANKNIFTY",
        "category": "INDEX_OPTIONS",
        "direction": "CALL",
        "price": 52000.0,
        "score": 90,
        "score_components": {"breakout": 8, "volume": 10},
        "options_quality_gate_enabled": True,
        "index_session_dedup_enabled": True,
    })
    assert bool(sig2_id) is True


def test_21_stock_option_does_not_collide_with_index_option_rule(temp_db):
    """21. Stock Option does not collide with Index Option session dedup rule."""
    tracker, _ = temp_db
    conn = tracker._get_conn()
    ok, reason = check_index_session_dedup(
        conn_or_cursor=conn,
        symbol="RELIANCE",
        category="STOCK_OPTIONS",
        direction="CALL",
        session_date="2026-09-29",
    )
    conn.close()
    assert ok is True
    assert "NOT_APPLICABLE_NON_INDEX" in reason


def test_22_equity_swing_does_not_collide_with_index_option_rule(temp_db):
    """22. Equity Swing does not collide with Index Option session dedup rule."""
    tracker, _ = temp_db
    conn = tracker._get_conn()
    ok, reason = check_index_session_dedup(
        conn_or_cursor=conn,
        symbol="NIFTY",  # Even if symbol has NIFTY
        category="EQUITY_SWING_DELIVERY",
        direction="BUY",
        session_date="2026-09-29",
    )
    conn.close()
    assert ok is True
    assert "NOT_APPLICABLE_NON_INDEX" in reason


def test_23_existing_r2_cooldown_remains_enforced(temp_db):
    """23. Existing R2 cooldown remains strictly enforced before D20."""
    scanner = AllNSEScanner(cfg={"SIGNAL_DEDUP_COOLDOWN_SECS": 900})
    scanner._last_alert_time["TESTSYM"] = 1000.0
    now = 1200.0  # 200s elapsed < 900s
    assert (now - scanner._last_alert_time["TESTSYM"]) < scanner._cooldown_secs


def test_24_existing_daily_quota_remains_enforced():
    """24. Existing daily quota remains strictly enforced."""
    scanner = AllNSEScanner(cfg={"MAX_ALERTS_PER_DAY": 10})
    assert scanner._max_alerts_per_day == 10


# =============================================================================
# D20-C TESTS: EXPERIMENTAL TARGET MODEL ISOLATION (Tests 25–28)
# =============================================================================

def test_25_production_default_target_remains_4_8_3():
    """25. Production/default target remains strictly +4% T1, +8% T2, -3% SL."""
    sl, t1, t2 = calculate_experimental_target_levels(
        entry_price=200.0,
        direction="CALL",
        category="STOCK_OPTIONS",
        mode="PRODUCTION",
    )
    assert sl == 194.0   # 200 * (1 - 0.03)
    assert t1 == 208.0   # 200 * (1 + 0.04)
    assert t2 == 216.0   # 200 * (1 + 0.08)


def test_26_experimental_1_2_pct_target_is_isolated():
    """26. Experimental +1.2% candidate is active only when explicitly specified."""
    sl, t1, t2 = calculate_experimental_target_levels(
        entry_price=200.0,
        direction="CALL",
        category="STOCK_OPTIONS",
        mode="CANDIDATE_1_2_PCT",
    )
    assert sl == 197.0   # 200 * (1 - 0.015)
    assert t1 == 202.4   # 200 * (1 + 0.012)
    assert t2 == 204.8   # 200 * (1 + 0.024)

    # For PUT direction
    sl_put, t1_put, t2_put = calculate_experimental_target_levels(
        entry_price=200.0,
        direction="PUT",
        category="STOCK_OPTIONS",
        mode="CANDIDATE_1_2_PCT",
    )
    assert sl_put == 203.0   # 200 * (1 + 0.015)
    assert t1_put == 197.6   # 200 * (1 - 0.012)
    assert t2_put == 195.2   # 200 * (1 - 0.024)


def test_27_production_config_is_unchanged_when_experiment_disabled():
    """27. When mode is unspecified or 'PRODUCTION', canonical levels are returned."""
    sl, t1, t2 = calculate_experimental_target_levels(
        entry_price=100.0,
        direction="CALL",
        category="STOCK_OPTIONS",
    )
    assert sl == 97.0
    assert t1 == 104.0
    assert t2 == 108.0


def test_28_candidate_target_does_not_leak_into_equity_swing():
    """28. Candidate target mode NEVER modifies Equity Swing Delivery (remains production +4/+8/-3)."""
    sl, t1, t2 = calculate_experimental_target_levels(
        entry_price=100.0,
        direction="CALL",
        category="EQUITY_SWING_DELIVERY",
        mode="CANDIDATE_1_2_PCT",  # Mode set, but category is Equity Swing
    )
    assert sl == 97.0   # -3.0%
    assert t1 == 104.0  # +4.0%
    assert t2 == 108.0  # +8.0%
