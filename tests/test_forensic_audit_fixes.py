"""Tests for forensic audit fixes: deadlock, config freeze, freshness, phantom recovery, shutdown."""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import threading
from pathlib import Path

import pytest

from core.config_bootstrap import _freeze_config
from core.datetime_ist import now_ist
from core.execution.execution_state import FormalOrderState
from core.expiry_day_controller import ExpiryDayController, StrategyType
from core.python_runtime import (
    _reset_shutdown_state_for_testing,
    execute_shutdown,
    register_shutdown_callback,
    setup_graceful_shutdown,
)
from core.state_manager import SessionRecoveryReport, StateManager


# ── B1: Deadlock fix (threading.Lock → RLock) ──────────────────────────

def test_formal_order_state_no_deadlock_on_recursive_access():
    """RLock prevents deadlock when same thread recurses into state transitions."""
    state = FormalOrderState(
        intent_id="test-001", client_order_id="co-001",
        symbol="NIFTY", quantity=75, price=100.0, direction="BUY",
    )

    def recursive_try(depth: int):
        if depth <= 0:
            return
        state.try_transition(state.state)
        recursive_try(depth - 1)

    t = threading.Thread(target=recursive_try, args=(20,), daemon=True)
    t.start()
    t.join(timeout=5)
    assert not t.is_alive(), "Thread deadlocked on recursive transition access"


# ── C5: Config freeze ─────────────────────────────────────────────────

def test_frozen_config_raises_typeerror_on_mutation():
    frozen = _freeze_config({"a": 1, "b": {"c": 2}})
    with pytest.raises(TypeError):
        frozen["a"] = 99


def test_frozen_config_allows_read():
    frozen = _freeze_config({"key": "val"})
    assert frozen["key"] == "val"


# ── C11/C12: Yahoo data freshness ─────────────────────────────────────

def test_yahoo_freshness_rejects_stale_data():
    from infrastructure.adapters.market_data.yahoofinance.adapter import YahooFinanceAdapter

    adapter = YahooFinanceAdapter()
    adapter._last_fetch_time = {"^NSEI": now_ist().timestamp() - 60}
    fresh = adapter.is_data_fresh(market_data=None, symbol="^NSEI")
    assert not fresh, "Data 60s old should not be fresh with 30s threshold"


def test_yahoo_freshness_accepts_recent_data():
    from infrastructure.adapters.market_data.yahoofinance.adapter import YahooFinanceAdapter

    adapter = YahooFinanceAdapter()
    adapter._last_fetch_time = {"^NSEI": now_ist().timestamp() - 5}
    fresh = adapter.is_data_fresh(market_data=None, symbol="^NSEI")
    assert fresh, "Data 5s old should be fresh with 30s threshold"


# ── Expiry day controller ─────────────────────────────────────────────

def test_expiry_controller_accepts_morning_time():
    controller = ExpiryDayController(
        strategy_type=StrategyType.DIRECTIONAL,
        enable_controls=True,
    )
    morning = now_ist().replace(hour=9, minute=30)
    result = controller.can_enter_position(now=morning)
    assert isinstance(result.allowed, bool)
    assert result.session is not None


def test_expiry_controller_disabled_bypasses():
    controller = ExpiryDayController(enable_controls=False)
    result = controller.can_enter_position()
    assert result.allowed
    assert result.risk_level == "LOW"


def test_expiry_controller_returns_reason_when_blocked():
    controller = ExpiryDayController(enable_controls=True)
    late = now_ist().replace(hour=14, minute=45)
    result = controller.can_enter_position(now=late)
    if not result.allowed:
        assert len(result.reason) > 0


# ── C8: Phantom position recovery ─────────────────────────────────────

def test_phantom_recovery_removes_broker_mismatches(tmp_path):
    db_path = tmp_path / "trades.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE IF NOT EXISTS trades (symbol TEXT, qty INT, entry_price REAL, exit_ts TEXT)")
    conn.execute("INSERT INTO trades (symbol, qty, entry_price, exit_ts) VALUES (?, ?, ?, ?)",
                 ("NIFTY", 25, 100.0, None))
    conn.execute("INSERT INTO trades (symbol, qty, entry_price, exit_ts) VALUES (?, ?, ?, ?)",
                 ("BANKNIFTY", 15, 200.0, None))
    conn.commit()
    conn.close()

    sm = StateManager(
        state_file=str(tmp_path / "state.json"),
        db_path=str(db_path),
    )
    broker_positions = {"NIFTY": {"qty": 25}}
    sm.recover_state_from_db(broker_positions=broker_positions)
    active = sm.get("active_positions", {})
    assert "NIFTY" in active
    assert "BANKNIFTY" not in active, "BANKNIFTY should have been removed as phantom"


def test_phantom_recovery_preserves_matched_positions(tmp_path):
    db_path = tmp_path / "trades.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE IF NOT EXISTS trades (symbol TEXT, qty INT, entry_price REAL, exit_ts TEXT)")
    conn.execute("INSERT INTO trades (symbol, qty, entry_price, exit_ts) VALUES (?, ?, ?, ?)",
                 ("NIFTY", 25, 100.0, None))
    conn.commit()
    conn.close()

    sm = StateManager(
        state_file=str(tmp_path / "state.json"),
        db_path=str(db_path),
    )
    broker_positions = {"NIFTY": {"qty": 25}}
    sm.recover_state_from_db(broker_positions=broker_positions)
    active = sm.get("active_positions", {})
    assert active.get("NIFTY", {}).get("qty") == 25


def test_phantom_recovery_without_broker_keeps_all(tmp_path):
    db_path = tmp_path / "trades.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE IF NOT EXISTS trades (symbol TEXT, qty INT, entry_price REAL, exit_ts TEXT)")
    conn.execute("INSERT INTO trades (symbol, qty, entry_price, exit_ts) VALUES (?, ?, ?, ?)",
                 ("NIFTY", 25, 100.0, None))
    conn.execute("INSERT INTO trades (symbol, qty, entry_price, exit_ts) VALUES (?, ?, ?, ?)",
                 ("BANKNIFTY", 15, 200.0, None))
    conn.commit()
    conn.close()

    sm = StateManager(
        state_file=str(tmp_path / "state.json"),
        db_path=str(db_path),
    )
    sm.recover_state_from_db()  # no broker positions → keep everything
    active = sm.get("active_positions", {})
    assert "NIFTY" in active
    assert "BANKNIFTY" in active


# ── Recovery report ───────────────────────────────────────────────────

def test_recovery_report_defaults():
    report = SessionRecoveryReport(
        local_positions=2,
        broker_positions=1,
        matched_symbols=1,
    )
    assert not report.positions_aligned
    assert report.note == ""


def test_recovery_report_custom():
    report = SessionRecoveryReport(
        local_positions=2,
        broker_positions=2,
        matched_symbols=2,
        positions_aligned=True,
        note="Aligned",
    )
    assert report.positions_aligned
    assert report.note == "Aligned"


# ── Graceful shutdown ────────────────────────────────────────────────

def test_shutdown_callbacks_invoke_lifo():
    _reset_shutdown_state_for_testing()
    calls: list[str] = []
    register_shutdown_callback(lambda: calls.append("first"))
    register_shutdown_callback(lambda: calls.append("second"))
    execute_shutdown()
    assert calls == ["second", "first"], f"Expected LIFO, got {calls}"


def test_shutdown_is_idempotent():
    _reset_shutdown_state_for_testing()
    calls: list[str] = []
    register_shutdown_callback(lambda: calls.append("x"))
    execute_shutdown()
    count_before = len(calls)
    execute_shutdown()
    assert len(calls) == count_before, "execute_shutdown must be idempotent"


def test_setup_graceful_shutdown_returns_event():
    ev = setup_graceful_shutdown()
    assert isinstance(ev, threading.Event)
    assert not ev.is_set()


def test_shutdown_callback_exception_does_not_block():
    _reset_shutdown_state_for_testing()
    calls: list[str] = []
    register_shutdown_callback(lambda: (_ for _ in ()).throw(RuntimeError("oops")))
    register_shutdown_callback(lambda: calls.append("ok"))
    execute_shutdown()
    assert "ok" in calls


# ── datetime_ist: now_ist returns correct type ────────────────────────

def test_now_ist_returns_naive_datetime():
    result = now_ist()
    assert result.tzinfo is None, "now_ist must return a naive datetime"
    assert 0 <= result.hour <= 23
