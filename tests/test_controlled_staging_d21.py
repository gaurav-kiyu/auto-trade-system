"""OPB Phase D21: Controlled Staging Preparation Verification Test Suite.

Authority: OPB-FINAL-PHASE-GOVERNANCE-001 / Phase D21 Specification.

Verifies:
D20-A (Tests 1-10): Category-Aware Options Quality Gate
D20-B (Tests 11-16): Canonical Index Session Deduplication
D20-C (Tests 17-18): Hard Isolation of Experimental Target Models from Production Path
Integration (Tests 19-22): Pre-Persistence, Pre-Dispatch, and Zero Broker Mutation Guarantees
"""

import math
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from core.signals.signal_quality_gate import (
    validate_options_quality_gate,
    check_index_session_dedup,
    get_canonical_index_underlying,
    calculate_experimental_target_levels,
)
from core.signals.signal_tracker import SignalTracker
from core.all_nse_scanner import AllNSEScanner, ScannedStockSignal
from core.signal_utils import calculate_directional_levels


@pytest.fixture
def temp_db(tmp_path: Path):
    """Isolated temporary SQLite database for signal tracker."""
    db_file = tmp_path / "test_d21_signals.db"
    SignalTracker.reset_instance()
    tracker = SignalTracker.get_instance(db_path=db_file)
    yield tracker, db_file
    SignalTracker.reset_instance()


# =============================================================================
# D20-A TESTS: CATEGORY-AWARE OPTIONS QUALITY GATE (1–10)
# =============================================================================

def test_01_stock_option_breakout_and_volume_allowed():
    """1. Stock Option + breakout > 0 + volume > 0 -> allowed."""
    payload = {
        "category": "STOCK_OPTIONS",
        "symbol": "RELIANCE",
        "score_components": {"breakout": 8, "volume": 12},
    }
    ok, reason = validate_options_quality_gate(payload)
    assert ok is True
    assert "ELIGIBLE" in reason


def test_02_stock_option_missing_breakout_rejected():
    """2. Stock Option missing breakout -> rejected."""
    payload = {
        "category": "STOCK_OPTIONS",
        "symbol": "RELIANCE",
        "score_components": {"volume": 12},
    }
    ok, reason = validate_options_quality_gate(payload)
    assert ok is False
    assert "MISSING_BREAKOUT" in reason


def test_03_stock_option_missing_volume_rejected():
    """3. Stock Option missing volume -> rejected."""
    payload = {
        "category": "STOCK_OPTIONS",
        "symbol": "RELIANCE",
        "score_components": {"breakout": 8},
    }
    ok, reason = validate_options_quality_gate(payload)
    assert ok is False
    assert "MISSING_VOLUME" in reason


def test_04_stock_option_nan_breakout_rejected():
    """4. Stock Option NaN breakout -> rejected."""
    payload = {
        "category": "STOCK_OPTIONS",
        "symbol": "RELIANCE",
        "score_components": {"breakout": float("nan"), "volume": 10},
    }
    ok, reason = validate_options_quality_gate(payload)
    assert ok is False
    assert "NAN_BREAKOUT" in reason


def test_05_stock_option_nan_volume_rejected():
    """5. Stock Option NaN volume -> rejected."""
    payload = {
        "category": "STOCK_OPTIONS",
        "symbol": "RELIANCE",
        "score_components": {"breakout": 10, "volume": float("nan")},
    }
    ok, reason = validate_options_quality_gate(payload)
    assert ok is False
    assert "NAN_VOLUME" in reason


def test_06_index_option_breakout_and_volume_allowed():
    """6. Index Option + breakout > 0 + volume > 0 -> allowed."""
    payload = {
        "category": "INDEX_OPTIONS",
        "symbol": "NIFTY",
        "score_components": {"breakout": 5, "volume": 8},
    }
    ok, reason = validate_options_quality_gate(payload)
    assert ok is True
    assert "ELIGIBLE" in reason


def test_07_index_option_missing_breakout_rejected():
    """7. Index Option missing breakout -> rejected."""
    payload = {
        "category": "INDEX_OPTIONS",
        "symbol": "BANKNIFTY",
        "score_components": {"volume": 8},
    }
    ok, reason = validate_options_quality_gate(payload)
    assert ok is False
    assert "MISSING_BREAKOUT" in reason


def test_08_index_option_missing_volume_rejected():
    """8. Index Option missing volume -> rejected."""
    payload = {
        "category": "INDEX_OPTIONS",
        "symbol": "FINNIFTY",
        "score_components": {"breakout": 5},
    }
    ok, reason = validate_options_quality_gate(payload)
    assert ok is False
    assert "MISSING_VOLUME" in reason


def test_09_equity_swing_normal_components_unchanged():
    """9. Equity Swing with normal components -> behavior unchanged."""
    payload = {
        "category": "EQUITY_SWING_DELIVERY",
        "symbol": "TCS",
        "score_components": {"breakout": 0, "volume": 0, "trend": 15},
    }
    ok, reason = validate_options_quality_gate(payload)
    assert ok is True
    assert "NOT_APPLICABLE_NON_OPTION" in reason


def test_10_equity_swing_missing_option_components_not_rejected():
    """10. Equity Swing missing option-specific components -> NOT rejected."""
    payload = {
        "category": "EQUITY_SWING_DELIVERY",
        "symbol": "INFY",
        "score_components": {},
    }
    ok, reason = validate_options_quality_gate(payload)
    assert ok is True
    assert "NOT_APPLICABLE_NON_OPTION" in reason


# =============================================================================
# D20-B TESTS: CANONICAL INDEX SESSION DEDUPLICATION (11–16)
# =============================================================================

def test_11_first_call_for_index_session_allowed(temp_db):
    """11. First CALL for index/session -> allowed."""
    tracker, db_file = temp_db
    conn = tracker._get_conn()
    try:
        ok, reason = check_index_session_dedup(conn, "NIFTY", "INDEX_OPTIONS", "CALL", "2026-09-29")
        assert ok is True
        assert "ELIGIBLE" in reason
    finally:
        conn.close()


def test_12_second_call_same_index_session_rejected(temp_db):
    """12. Second CALL same index/session -> rejected."""
    tracker, db_file = temp_db
    # Record first CALL
    sig1_id = tracker.record_generated_signal({
        "symbol": "NIFTY",
        "category": "INDEX_OPTIONS",
        "direction": "CALL",
        "price": 24500.0,
        "score": 85,
        "score_components": {"breakout": 8, "volume": 10},
        "options_quality_gate_enabled": True,
        "index_session_dedup_enabled": True,
    })
    assert bool(sig1_id) is True

    conn = tracker._get_conn()
    cur = conn.cursor()
    ok, reason = check_index_session_dedup(cur, "NIFTY 24500 CE", "INDEX_OPTIONS", "CALL", "2026-09-29")
    conn.close()

    assert ok is False
    assert "DEDUP_SUPPRESSED" in reason


def test_13_first_put_same_index_session_allowed(temp_db):
    """13. First PUT same index/session (coexisting with CALL) -> allowed."""
    tracker, db_file = temp_db
    # Record first CALL
    sig1_id = tracker.record_generated_signal({
        "symbol": "NIFTY",
        "category": "INDEX_OPTIONS",
        "direction": "CALL",
        "price": 24500.0,
        "score": 85,
        "score_components": {"breakout": 8, "volume": 10},
        "options_quality_gate_enabled": True,
        "index_session_dedup_enabled": True,
    })
    assert bool(sig1_id) is True

    conn = tracker._get_conn()
    cur = conn.cursor()
    # First PUT should be accepted even though CALL exists
    ok, reason = check_index_session_dedup(cur, "NIFTY 24500 PE", "INDEX_OPTIONS", "PUT", "2026-09-29")
    conn.close()

    assert ok is True
    assert "ELIGIBLE" in reason


def test_14_second_put_same_index_session_rejected(temp_db):
    """14. Second PUT same index/session -> rejected."""
    tracker, db_file = temp_db
    # Record first PUT
    sig1_id = tracker.record_generated_signal({
        "symbol": "NIFTY",
        "category": "INDEX_OPTIONS",
        "direction": "PUT",
        "price": 24500.0,
        "score": 85,
        "score_components": {"breakout": 8, "volume": 10},
        "options_quality_gate_enabled": True,
        "index_session_dedup_enabled": True,
    })
    assert bool(sig1_id) is True

    conn = tracker._get_conn()
    cur = conn.cursor()
    ok, reason = check_index_session_dedup(cur, "NIFTY 24400 PE", "INDEX_OPTIONS", "PUT", "2026-09-29")
    conn.close()

    assert ok is False
    assert "DEDUP_SUPPRESSED" in reason


def test_15_next_session_call_allowed(temp_db):
    """15. Next session CALL -> allowed (session rollover resets quota)."""
    tracker, db_file = temp_db
    conn = tracker._get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO system_signals (signal_id, timestamp, created_date, created_week, created_month, created_year,
            symbol, company_name, category, direction, score, tier, entry_price, stop_loss, target_1, target_2,
            current_price, status, pnl_pct)
        VALUES ('SIG-NIFTY-CALL-D1', '2026-09-28 09:20:00', '2026-09-28', 'W39', '09', '2026',
            'NIFTY', 'Nifty Index', 'INDEX_OPTIONS', 'CALL', 85, 'STRONG', 24500.0, 23765.0, 25480.0, 26460.0,
            24500.0, 'ACTIVE', 0.0)
    """)
    conn.commit()

    # Querying next session date 2026-09-29
    ok, reason = check_index_session_dedup(cur, "NIFTY", "INDEX_OPTIONS", "CALL", "2026-09-29")
    conn.close()

    assert ok is True
    assert "ELIGIBLE" in reason


def test_16_different_canonical_index_independently_allowed(temp_db):
    """16. Different canonical index -> independently allowed."""
    tracker, db_file = temp_db
    # Record NIFTY CALL
    sig1_id = tracker.record_generated_signal({
        "symbol": "NIFTY",
        "category": "INDEX_OPTIONS",
        "direction": "CALL",
        "price": 24500.0,
        "score": 85,
        "score_components": {"breakout": 8, "volume": 10},
        "options_quality_gate_enabled": True,
        "index_session_dedup_enabled": True,
    })
    assert bool(sig1_id) is True

    conn = tracker._get_conn()
    cur = conn.cursor()
    # BANKNIFTY is independent of NIFTY
    ok, reason = check_index_session_dedup(cur, "BANKNIFTY 52000 CE", "INDEX_OPTIONS", "CALL", "2026-09-29")
    conn.close()

    assert ok is True
    assert "ELIGIBLE" in reason


# =============================================================================
# D20-C TESTS: HARD DISABLE FROM PRODUCTION PATH (17–18)
# =============================================================================

def test_17_production_configuration_still_4_8_minus_3():
    """17. Production configuration still calculates canonical +4.0% T1, +8.0% T2, -3.0% SL."""
    entry = 1000.0
    sl, t1, t2 = calculate_directional_levels(entry_price=entry, direction="CALL")
    assert sl == 970.0   # -3.0%
    assert t1 == 1040.0  # +4.0%
    assert t2 == 1080.0  # +8.0%

    sl_put, t1_put, t2_put = calculate_directional_levels(entry_price=entry, direction="PUT")
    assert sl_put == 1030.0  # +3.0%
    assert t1_put == 960.0   # -4.0%
    assert t2_put == 920.0   # -8.0%


def test_18_experimental_targets_not_used_in_production_path():
    """18. Experimental +1.2%/+2.4%/-1.0% target model is not used in production path."""
    entry = 1000.0
    # In production mode (mode="PRODUCTION" or unspecified), calculate_experimental_target_levels returns production defaults
    sl, t1, t2 = calculate_experimental_target_levels(
        entry_price=entry,
        direction="CALL",
        category="STOCK_OPTIONS",
        mode="PRODUCTION",
    )
    assert sl == 970.0
    assert t1 == 1040.0
    assert t2 == 1080.0

    # Also for cash equity swing, regardless of mode, production levels must always return
    sl_eq, t1_eq, t2_eq = calculate_experimental_target_levels(
        entry_price=entry,
        direction="CALL",
        category="EQUITY_SWING_DELIVERY",
        mode="CANDIDATE_1_2_PCT",
    )
    assert sl_eq == 970.0
    assert t1_eq == 1040.0
    assert t2_eq == 1080.0


# =============================================================================
# INTEGRATION TESTS: PRE-PERSISTENCE, PRE-DISPATCH & BROKER SAFETY (19–22)
# =============================================================================

def test_19_d20_a_rejection_occurs_before_persistence(temp_db):
    """19. D20-A rejection occurs before persistence in tracker.record_generated_signal."""
    tracker, db_file = temp_db
    signal_dict = {
        "symbol": "TEST_RELIANCE_D21_UNIQUE",
        "category": "STOCK_OPTIONS",
        "direction": "CALL",
        "price": 2500.0,
        "score": 85,
        "score_components": {"breakout": 0, "volume": 10},  # Fails breakout > 0
        "options_quality_gate_enabled": True,
    }
    sig_id = tracker.record_generated_signal(signal_dict)
    assert sig_id == ""  # Rejected, not recorded

    conn = tracker._get_conn()
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM system_signals WHERE symbol = 'TEST_RELIANCE_D21_UNIQUE'")
    count = cur.fetchone()[0]
    conn.close()
    assert count == 0


def test_20_d20_a_rejection_occurs_before_dispatch(temp_db):
    """20. D20-A rejection occurs before dispatch in AllNSEScanner._dispatch_alert_if_eligible."""
    cfg = {
        "EXECUTION_MODE": "SIGNAL_ONLY",
        "D20_OPTIONS_QUALITY_GATE_ENABLED": True,
        "ALLOW_AFTER_HOURS_SCANNING": True,
    }
    with patch.object(AllNSEScanner, "_reload_config_credentials", lambda self: None):
        scanner = AllNSEScanner(cfg=cfg)
        scanner._bot_token = ""
        scanner._email_enabled = False

        stock_signal = ScannedStockSignal(
            symbol="RELIANCE24AUG2500CE",
            company_name="Reliance Options",
            series="OPT",
            direction="CALL",
            score=85,
            raw_score=85,
            tier="STRONG",
            regime="BULLISH",
            price=2500.0,
            rsi=55.0,
            adx=25.0,
            vwap=2490.0,
            score_components={"breakout": 0, "volume": 10},  # Rejected by options gate
        )

        with patch("core.fno_universe.classify_instrument_market", return_value="STOCK_OPTIONS"), \
             patch.object(scanner, "_record_evaluation_state") as mock_record, \
             patch.object(SignalTracker, "record_generated_signal") as mock_tracker_record:

            scanner._dispatch_alert_if_eligible(stock_signal)
            # Must record as FILTERED and return BEFORE dispatch or tracker persistence
            assert mock_record.call_count >= 1
            call_args = mock_record.call_args[0]
            assert call_args[1] == "FILTERED"
            assert mock_tracker_record.call_count == 0


def test_21_d20_b_rejection_occurs_before_persistence_and_dispatch(temp_db):
    """21. D20-B rejection occurs before persistence and dispatch."""
    tracker, db_file = temp_db
    # Record first NIFTY CALL
    sig1_id = tracker.record_generated_signal({
        "symbol": "NIFTY",
        "category": "INDEX_OPTIONS",
        "direction": "CALL",
        "price": 24500.0,
        "score": 85,
        "score_components": {"breakout": 8, "volume": 10},
        "options_quality_gate_enabled": True,
        "index_session_dedup_enabled": True,
    })
    assert bool(sig1_id) is True

    cfg = {
        "EXECUTION_MODE": "SIGNAL_ONLY",
        "D20_INDEX_SESSION_DEDUP_ENABLED": True,
        "ALLOW_AFTER_HOURS_SCANNING": True,
    }
    with patch.object(AllNSEScanner, "_reload_config_credentials", lambda self: None):
        scanner = AllNSEScanner(cfg=cfg)
        stock_signal = ScannedStockSignal(
            symbol="NIFTY24AUG24500CE",
            company_name="Nifty Index Call",
            series="OPT",
            direction="CALL",
            score=85,
            raw_score=85,
            tier="STRONG",
            regime="BULLISH",
            price=24500.0,
            rsi=55.0,
            adx=25.0,
            vwap=24490.0,
            score_components={"breakout": 10, "volume": 10},
        )

        with patch("core.fno_universe.classify_instrument_market", return_value="INDEX_OPTIONS"), \
             patch.object(scanner, "_record_evaluation_state") as mock_record, \
             patch.object(SignalTracker, "record_generated_signal") as mock_tracker_record:

            scanner._dispatch_alert_if_eligible(stock_signal)
            # Must record as DEDUP_SUPPRESSED and return BEFORE dispatch
            assert mock_record.call_count >= 1
            call_args = mock_record.call_args[0]
            assert call_args[1] == "DEDUP_SUPPRESSED"
            assert mock_tracker_record.call_count == 0


def test_22_no_broker_order_call_occurs(temp_db):
    """22. Verifies that no broker execution or order placement calls occur in SIGNAL_ONLY mode."""
    cfg = {
        "EXECUTION_MODE": "SIGNAL_ONLY",
        "D20_OPTIONS_QUALITY_GATE_ENABLED": True,
        "D20_INDEX_SESSION_DEDUP_ENABLED": True,
    }
    with patch.object(AllNSEScanner, "_reload_config_credentials", lambda self: None):
        scanner = AllNSEScanner(cfg=cfg)
        # Verify that broker auto routing is strictly disabled and broker client is not instantiated
        assert scanner._cfg.get("EXECUTION_MODE") == "SIGNAL_ONLY"
        assert not hasattr(scanner, "_broker_adapter") or scanner._broker_adapter is None
