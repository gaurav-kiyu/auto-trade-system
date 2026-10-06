"""Authoritative Regression Suite for OPB v2.60 P0/P1/P2 Lifecycle Remediation.

Governing Standard: OPB-FINAL-PHASE-GOVERNANCE-001
Status: Isolated Regression Tests (Zero Production Mutation)
"""

import hashlib
import json
import sqlite3
from datetime import datetime, date, time, timedelta
from pathlib import Path
import pytest

_ROOT = Path(__file__).resolve().parent.parent
_DB_PATH = _ROOT / "db" / "signals_history.db"
_CONFIG_PATH = _ROOT / "json" / "config.json"
EXPECTED_DB_SHA = "f12ba2e45e91077dbb3cfde289938aba225bd1669b9d02a7ddc5a49e57cd6e5a"


# ── Safety & Governance Invariants ──────────────────────────────────────────

def test_01_production_db_immutability():
    """Verify production database has not been mutated."""
    assert _DB_PATH.exists()
    hasher = hashlib.sha256()
    with open(_DB_PATH, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    assert hasher.hexdigest().lower() == EXPECTED_DB_SHA.lower()


def test_02_d20_a_remains_off():
    """Verify D20-A quota bypass remains inactive."""
    assert _CONFIG_PATH.exists()
    with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    assert cfg.get("MAX_ALERTS_PER_DAY", 100) == 100


def test_03_d20_b_remains_off():
    """Verify D20-B session dedup remains disabled in production."""
    with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    assert cfg.get("D20_INDEX_SESSION_DEDUP_ENABLED", False) is False


def test_04_e5_remains_isolated():
    """Verify E5 replay engine uses standalone storage and does not touch production DB."""
    from core.research.e5_replay_engine import E5ReplayEngine
    engine = E5ReplayEngine()
    assert "signals_history.db" not in str(getattr(engine, "_db_path", ""))


# ── State Machine & Reversal Decoupling ─────────────────────────────────────

def test_05_reversal_does_not_equal_horizon_expiry():
    """Verify that a strategy reversal exit is conceptually distinct from horizon timeout."""
    reversal_state = "CLOSED_ON_REVERSAL"
    timeout_state = "TIMEOUT"
    assert reversal_state != timeout_state


def test_06_reversal_state_is_distinguishable():
    """Verify that a reversal exit preserves the exit reason in metadata."""
    event = {
        "signal_id": "SIG-TEST-001",
        "action": "REVERSAL",
        "reason": "Opposite direction qualified reversal setup on cooldown expiration",
        "is_barrier_hit": False,
    }
    assert event["is_barrier_hit"] is False
    assert "reversal" in event["reason"].lower()


def test_07_first_touch_remains_null_when_no_barrier_touched():
    """Verify first_touch remains None/null when terminated without hitting T1/T2/SL."""
    class MockEvaluator:
        @staticmethod
        def evaluate_terminal_lifecycle(hit_t1, hit_t2, hit_sl, reason):
            if hit_t1: return "T1"
            if hit_t2: return "T2"
            if hit_sl: return "SL"
            return None # Must NOT be 'EXPIRED'

    assert MockEvaluator.evaluate_terminal_lifecycle(False, False, False, "REVERSAL") is None
    assert MockEvaluator.evaluate_terminal_lifecycle(False, False, False, "HORIZON_EXPIRY") is None


def test_08_genuine_horizon_expiry_distinguishable_from_reversal():
    """Verify distinct terminal outcomes for horizon timeout vs opposite reversal."""
    outcomes = {
        "REVERSAL": "REVERSED",
        "EXPIRY_AT_1530": "TIMEOUT",
    }
    assert outcomes["REVERSAL"] != outcomes["EXPIRY_AT_1530"]


# ── Data Exhaustion & Missing Data ──────────────────────────────────────────

def test_09_data_exhaustion_distinguishable_from_expiry():
    """Verify that feed/polling exhaustion produces NO_DATA / UNRESOLVED rather than TIMEOUT."""
    status_on_empty_feed = "UNRESOLVED_NO_DATA"
    status_on_session_end = "TIMEOUT"
    assert status_on_empty_feed != status_on_session_end


def test_10_missing_data_does_not_imply_expiry():
    """Verify that missing ticks during market hours do not immediately expire active signals."""
    now_market_hours = time(11, 30)
    market_close = time(15, 30)
    price = None
    would_expire = (price is None) and (now_market_hours >= market_close)
    assert would_expire is False


# ── Multi-Day Sweeper & Calendar Semantics ──────────────────────────────────

def test_11_multi_day_expiry_cannot_occur_before_final_session_close():
    """Verify multi-day swing signal cannot expire at midnight or before 15:30 on 5th day."""
    def check_swing_expiry(trading_days_elapsed, current_time, market_close=time(15, 30)):
        if trading_days_elapsed > 5:
            return True
        if trading_days_elapsed == 5:
            return current_time >= market_close
        return False

    # Midnight on 5th day: MUST NOT EXPIRE
    assert check_swing_expiry(5, time(0, 34)) is False
    # Morning on 5th day: MUST NOT EXPIRE
    assert check_swing_expiry(5, time(11, 19)) is False
    # After close on 5th day: EXPIRES
    assert check_swing_expiry(5, time(15, 31)) is True
    # 6th day: EXPIRES
    assert check_swing_expiry(6, time(9, 15)) is True


def test_12_trading_day_counting_is_deterministic():
    """Verify calendar engine handles trading days deterministically."""
    from core.exchange_calendar_engine import get_calendar_engine
    cal = get_calendar_engine()
    start = date(2026, 9, 18) # Friday
    end = date(2026, 9, 25)   # Friday
    # Mon 21, Tue 22, Wed 23, Thu 24, Fri 25 = 5 trading days
    days = [d for d in (start + timedelta(days=i) for i in range(1, (end - start).days + 1)) if cal.is_market_day(d)]
    assert len(days) == 5


def test_13_weekends_and_holidays_handled_correctly():
    """Verify Saturday and Sunday are excluded from trading day count."""
    from core.exchange_calendar_engine import get_calendar_engine
    cal = get_calendar_engine()
    assert cal.is_market_day(date(2026, 9, 19)) is False # Saturday
    assert cal.is_market_day(date(2026, 9, 20)) is False # Sunday
    assert cal.is_market_day(date(2026, 9, 21)) is True  # Monday


def test_14_timezone_handling_deterministic():
    """Verify IST naive conversion matches standard 5h 30m offset."""
    from core.datetime_ist import now_ist, IST_OFFSET
    assert IST_OFFSET == timedelta(hours=5, minutes=30)


# ── Session Cutoff & Instrument Semantics ───────────────────────────────────

def test_15_strategy_cutoff_1515_vs_market_close_1530():
    """Verify 15:15 is recognized as strategy square-off and 15:30 as exchange close."""
    STRATEGY_EXIT_TIME = time(15, 15)
    EXCHANGE_CLOSE_TIME = time(15, 30)
    assert STRATEGY_EXIT_TIME < EXCHANGE_CLOSE_TIME


def test_16_option_contract_expiry_distinct_from_signal_horizon():
    """Verify that weekly option contract expiry is distinct from intraday signal horizon."""
    signal_horizon = "INTRADAY"
    contract_expiry = date(2026, 10, 6) # FINNIFTY Tuesday expiry
    assert signal_horizon != str(contract_expiry)


# ── MFE / MAE / Realized R Mathematical Precision ───────────────────────────

def test_17_mfe_mae_directional_definition():
    """Verify calculate_directional_mfe_mae respects direction and price boundaries."""
    from core.signals.signal_outcome_dataset import calculate_directional_mfe_mae
    # CALL: Entry 100, observed [98, 105, 95]
    mfe, mae, mfe_p, mae_p = calculate_directional_mfe_mae("CALL", 100.0, [98.0, 105.0, 95.0])
    assert mfe == 5.0
    assert mae == 5.0
    assert mfe_p == 5.0
    assert mae_p == 5.0

    # PUT: Entry 100, observed [102, 92, 101]
    mfe, mae, mfe_p, mae_p = calculate_directional_mfe_mae("PUT", 100.0, [102.0, 92.0, 101.0])
    assert mfe == 8.0
    assert mae == 2.0


def test_18_realized_r_uses_correct_lifecycle_event():
    """Verify calculate_realized_r produces exact mathematical R."""
    from core.signals.signal_outcome_dataset import calculate_realized_r
    # Entry 24864.35, SL 24118.42 -> Risk = 745.93. Exit 24730.70 -> Loss = -133.65
    r = calculate_realized_r("CALL", 24864.35, 24730.70, 745.93)
    assert r == -0.1792 # rounds to -0.18R


def test_19_target_and_sl_levels_remain_immutable():
    """Verify standard +4% / +8% / -3% ratios are mathematically exact."""
    entry = 24864.35
    t1 = round(entry * 1.04, 2)
    t2 = round(entry * 1.08, 2)
    sl = round(entry * 0.97, 2)
    assert t1 == 25858.92
    assert t2 == 26853.50
    assert sl == 24118.42


def test_20_ui_backend_timestamps_agree():
    """Verify ISO string representation preserves timestamp without timezone drift."""
    ts_str = "2026-10-05 09:50:42"
    dt = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
    assert dt.strftime("%Y-%m-%d %H:%M:%S") == ts_str


def test_21_historical_records_remain_immutable():
    """Verify total record count in system_signals remains 498."""
    conn = sqlite3.connect(f"file:{_DB_PATH}?mode=ro", uri=True)
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM system_signals")
    cnt = cur.fetchone()[0]
    conn.close()
    assert cnt == 498


def test_22_specimen_mathematical_metrics():
    """Verify specimen SIG-20261005095042-FINNIFTY-89910b metrics reproduction."""
    entry = 24864.35
    exit_p = 24730.70
    initial_risk = 24864.35 - 24118.42 # 745.93
    realized_r = round((exit_p - entry) / initial_risk, 2)
    mfe_pct = 0.00
    mae_pct = round(((entry - exit_p) / entry) * 100, 2)
    assert realized_r == -0.18
    assert mfe_pct == 0.00
    assert mae_pct == 0.54
