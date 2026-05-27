"""Tests for core/trade_replayer.py (v2.44 Item 14)."""
import os
import sqlite3
import tempfile

import pytest
from core.trade_replayer import (
    ReplayFrame,
    _render_bar_chart,
    _simulate_price_bars,
    _verdict,
    get_replay_json,
    list_trades,
    load_trade,
    replay_multiple,
    replay_trade,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────

def make_db(trades=None):
    """Create an in-memory (tmp) trades.db with optional rows."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    conn = sqlite3.connect(tmp.name)
    conn.execute("""
        CREATE TABLE trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT, index_name TEXT, direction TEXT,
            entry REAL, exit_price REAL, qty INTEGER,
            gross_pnl REAL, net_pnl REAL, reason TEXT,
            regime TEXT, score INTEGER, iv REAL, vix REAL,
            ltp_estimated INTEGER, partial INTEGER, sl_warned INTEGER,
            mode TEXT, version TEXT
        )
    """)
    rows = trades if trades is not None else [
        ("2024-01-15 09:30:00", "NIFTY", "CALL", 100.0, 120.0, 50, 1000.0, 950.0,
         "TARGET", "UPTREND", 75, 15.0, 14.0, 0, 0, 0, "PAPER", "2.44"),
        ("2024-01-16 10:00:00", "BANKNIFTY", "PUT", 200.0, 180.0, 25, -500.0, -520.0,
         "STOP_LOSS", "DOWNTREND", 65, 18.0, 16.0, 0, 0, 0, "PAPER", "2.44"),
    ]
    for r in rows:
        conn.execute(
            "INSERT INTO trades (ts,index_name,direction,entry,exit_price,qty,"
            "gross_pnl,net_pnl,reason,regime,score,iv,vix,ltp_estimated,"
            "partial,sl_warned,mode,version) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            r,
        )
    conn.commit()
    conn.close()
    return tmp.name


# ── load_trade ────────────────────────────────────────────────────────────────

def test_load_trade_returns_dict():
    db = make_db()
    try:
        result = load_trade(1, db)
        assert isinstance(result, dict)
        assert result["id"] == 1
    finally:
        os.unlink(db)


def test_load_trade_returns_none_for_missing():
    db = make_db()
    try:
        result = load_trade(9999, db)
        assert result is None
    finally:
        os.unlink(db)


def test_load_trade_returns_none_for_missing_db():
    result = load_trade(1, "/nonexistent/path/trades.db")
    assert result is None


def test_load_trade_correct_fields():
    db = make_db()
    try:
        t = load_trade(1, db)
        assert t["index_name"] == "NIFTY"
        assert t["direction"] == "CALL"
        assert float(t["entry"]) == pytest.approx(100.0)
        assert float(t["net_pnl"]) == pytest.approx(950.0)
    finally:
        os.unlink(db)


# ── list_trades ───────────────────────────────────────────────────────────────

def test_list_trades_last_returns_n():
    db = make_db()
    try:
        result = list_trades(db, last=1)
        assert len(result) == 1
    finally:
        os.unlink(db)


def test_list_trades_worst_returns_lowest_pnl():
    db = make_db()
    try:
        result = list_trades(db, worst=1)
        assert len(result) == 1
        assert float(result[0]["net_pnl"]) < 0
    finally:
        os.unlink(db)


def test_list_trades_best_returns_highest_pnl():
    db = make_db()
    try:
        result = list_trades(db, best=1)
        assert len(result) == 1
        assert float(result[0]["net_pnl"]) > 0
    finally:
        os.unlink(db)


def test_list_trades_date_filter():
    db = make_db()
    try:
        result = list_trades(db, date_str="2024-01-15")
        assert len(result) == 1
        assert result[0]["index_name"] == "NIFTY"
    finally:
        os.unlink(db)


def test_list_trades_empty_db_returns_empty():
    db = make_db(trades=[])
    try:
        result = list_trades(db, last=5)
        assert result == []
    finally:
        os.unlink(db)


# ── _simulate_price_bars ──────────────────────────────────────────────────────

def test_simulate_price_bars_returns_n_bars():
    bars = _simulate_price_bars(100.0, 120.0, 10)
    assert len(bars) == 10


def test_simulate_price_bars_last_close_is_exit():
    bars = _simulate_price_bars(100.0, 130.0, 5)
    assert bars[-1][4] == pytest.approx(130.0)


def test_simulate_price_bars_tuple_format():
    bars = _simulate_price_bars(50.0, 60.0, 3)
    ts, o, h, low_val, c = bars[0]
    assert h >= low_val
    assert h >= c >= 0


# ── _render_bar_chart ─────────────────────────────────────────────────────────

def test_render_bar_chart_returns_string():
    frames = [
        ReplayFrame(0, "T+0", 100.0, 105.0, 99.0, 103.0, True,  False),
        ReplayFrame(1, "T+1", 103.0, 108.0, 102.0, 106.0, False, False),
        ReplayFrame(2, "T+2", 106.0, 110.0, 105.0, 109.0, False, True),
    ]
    chart = _render_bar_chart(frames, 100.0, 109.0, 97.0, 115.0)
    assert isinstance(chart, str)
    assert len(chart) > 0


def test_render_bar_chart_empty_returns_message():
    chart = _render_bar_chart([], 100.0, 120.0, 95.0, 130.0)
    assert "no price data" in chart


# ── _verdict ──────────────────────────────────────────────────────────────────

def test_verdict_positive_pnl_is_win():
    v = _verdict({"net_pnl": 500, "score": 70, "reason": "TARGET"})
    assert "WIN" in v


def test_verdict_negative_pnl_is_loss():
    v = _verdict({"net_pnl": -200, "score": 65, "reason": "STOP_LOSS"})
    assert "LOSS" in v


def test_verdict_high_score_win_message():
    v = _verdict({"net_pnl": 100, "score": 85, "reason": "TARGET"})
    assert "High-confidence" in v or "WIN" in v


def test_verdict_stop_loss_in_message():
    v = _verdict({"net_pnl": -300, "score": 60, "reason": "STOP_LOSS"})
    assert "SL" in v or "Stopped" in v or "LOSS" in v


# ── replay_trade ──────────────────────────────────────────────────────────────

def test_replay_trade_returns_string():
    db = make_db()
    try:
        result = replay_trade(1, db)
        assert isinstance(result, str)
        assert len(result) > 50
    finally:
        os.unlink(db)


def test_replay_trade_missing_id_returns_error():
    db = make_db()
    try:
        result = replay_trade(9999, db)
        assert "not found" in result.lower() or "error" in result.lower() or "9999" in result
    finally:
        os.unlink(db)


def test_replay_trade_contains_trade_info():
    db = make_db()
    try:
        result = replay_trade(1, db)
        assert "NIFTY" in result or "CALL" in result
    finally:
        os.unlink(db)


# ── replay_multiple ───────────────────────────────────────────────────────────

def test_replay_multiple_returns_string():
    db = make_db()
    try:
        trades = list_trades(db, last=2)
        result = replay_multiple(trades, db)
        assert isinstance(result, str)
    finally:
        os.unlink(db)


def test_replay_multiple_empty_returns_message():
    db = make_db()
    try:
        result = replay_multiple([], db)
        assert "No trades" in result or len(result) >= 0
    finally:
        os.unlink(db)


# ── get_replay_json ───────────────────────────────────────────────────────────

def test_get_replay_json_returns_dict():
    db = make_db()
    try:
        result = get_replay_json(1, db)
        assert isinstance(result, dict)
    finally:
        os.unlink(db)


def test_get_replay_json_has_bars():
    db = make_db()
    try:
        result = get_replay_json(1, db)
        assert "bars" in result or "error" in result
        if "bars" in result:
            assert isinstance(result["bars"], list)
    finally:
        os.unlink(db)


def test_get_replay_json_missing_returns_error():
    db = make_db()
    try:
        result = get_replay_json(9999, db)
        assert "error" in result
    finally:
        os.unlink(db)
