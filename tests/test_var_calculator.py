"""Tests for core/var_calculator.py (v2.45 Item 7)."""
import os
import sqlite3
import tempfile
from datetime import date, timedelta
import pytest
from core.var_calculator import VaRResult, compute_var, format_var_summary


def _make_db(daily_pnls: list[float], days_back: int = 30) -> str:
    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    f.close()
    conn = sqlite3.connect(f.name)
    conn.execute("""
        CREATE TABLE trades (
            id INTEGER PRIMARY KEY,
            ts TEXT,
            net_pnl REAL
        )
    """)
    today = date.today()
    for i, pnl in enumerate(daily_pnls):
        day = (today - timedelta(days=len(daily_pnls) - i - 1)).isoformat()
        conn.execute("INSERT INTO trades (ts, net_pnl) VALUES (?, ?)", (day + "T10:00:00", pnl))
    conn.commit()
    conn.close()
    return f.name


# ── disabled ──────────────────────────────────────────────────────────────────

def test_disabled_returns_zero():
    result = compute_var(100000, cfg={"var_enabled": False})
    assert result.var_95 == 0.0
    assert result.var_99 == 0.0
    assert result.n_days == 0


def test_zero_capital_returns_zero():
    result = compute_var(0.0)
    assert result.var_95 == 0.0


# ── formula ───────────────────────────────────────────────────────────────────

def test_var_95_less_than_var_99():
    pnls = [100.0, -500.0, 300.0, -200.0, 800.0, -400.0, 200.0,
            -300.0, 100.0, -600.0, 400.0, -100.0, 250.0, -350.0, 150.0]
    db = _make_db(pnls)
    try:
        result = compute_var(100000, db_path=db, cfg={"var_enabled": True, "var_lookback_days": 30})
        assert result.var_95 < result.var_99
    finally:
        os.unlink(db)


def test_var_positive():
    pnls = [500.0, -300.0, 200.0, -400.0, 100.0, -200.0, 300.0,
            -100.0, 400.0, -500.0, 150.0, -250.0, 350.0, -150.0, 200.0]
    db = _make_db(pnls)
    try:
        result = compute_var(100000, db_path=db, cfg={"var_enabled": True})
        assert result.var_95 >= 0
        assert result.var_99 >= 0
    finally:
        os.unlink(db)


def test_var_pct_matches_absolute():
    pnls = [200.0, -100.0, 300.0, -150.0, 250.0, -200.0, 100.0,
            -300.0, 400.0, -250.0, 150.0, -180.0, 220.0, -130.0, 280.0]
    db = _make_db(pnls)
    capital = 100000.0
    try:
        result = compute_var(capital, db_path=db, cfg={"var_enabled": True})
        if result.var_95 > 0:
            expected_pct = result.var_95 / capital * 100
            assert abs(result.var_95_pct - expected_pct) < 0.01
    finally:
        os.unlink(db)


def test_no_positions_returns_zero():
    db = _make_db([])
    try:
        result = compute_var(100000, db_path=db, cfg={"var_enabled": True})
        assert result.var_95 == 0.0
        assert result.n_days == 0
    finally:
        os.unlink(db)


def test_single_day_returns_zero():
    db = _make_db([500.0])
    try:
        result = compute_var(100000, db_path=db, cfg={"var_enabled": True})
        # Need >= 2 days for std
        assert result.var_95 == 0.0
    finally:
        os.unlink(db)


# ── alert ─────────────────────────────────────────────────────────────────────

def test_alert_fires_when_var_exceeds_threshold():
    # Large losses → high vol → VaR should exceed 5% threshold
    pnls = [100.0, -9000.0, 200.0, -8500.0, 100.0, -9000.0, 200.0,
            -8000.0, 150.0, -9500.0, 100.0, -8200.0, 300.0, -8800.0, 200.0]
    db = _make_db(pnls)
    try:
        result = compute_var(100000, db_path=db, cfg={"var_enabled": True, "max_var_pct": 5.0})
        if result.var_95_pct > 5.0:
            assert result.alert is True
    finally:
        os.unlink(db)


def test_missing_db_returns_zero():
    result = compute_var(100000, db_path="nonexistent.db", cfg={"var_enabled": True})
    assert result.var_95 == 0.0


# ── format ────────────────────────────────────────────────────────────────────

def test_format_var_summary_string():
    result = VaRResult(var_95=5000, var_99=7000, var_95_pct=5.0, var_99_pct=7.0,
                       daily_vol=3.0, n_days=20, alert=False, alert_message="")
    s = format_var_summary(result)
    assert isinstance(s, str)
    assert "VaR" in s


def test_format_insufficient_history():
    result = VaRResult(var_95=0, var_99=0, var_95_pct=0, var_99_pct=0,
                       daily_vol=0, n_days=1, alert=False, alert_message="")
    s = format_var_summary(result)
    assert "insufficient" in s.lower()
