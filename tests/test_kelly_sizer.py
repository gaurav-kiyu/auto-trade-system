"""Tests for core/kelly_sizer.py (v2.45 Item 6)."""
import os
import sqlite3
import tempfile
import pytest
from core.kelly_sizer import KellyResult, compute_kelly_lots, _load_recent_pnls


def _make_db(pnls: list[float]) -> str:
    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    f.close()
    conn = sqlite3.connect(f.name)
    conn.execute("CREATE TABLE trades (id INTEGER PRIMARY KEY, net_pnl REAL)")
    for p in pnls:
        conn.execute("INSERT INTO trades (net_pnl) VALUES (?)", (p,))
    conn.commit()
    conn.close()
    return f.name


# ── disabled ──────────────────────────────────────────────────────────────────

def test_disabled_returns_fallback():
    result = compute_kelly_lots(100000, 1, 1000, db_path="nonexistent.db", cfg={"kelly_enabled": False})
    assert result.used_fallback is True
    assert result.kelly_lots == 1


def test_disabled_kelly_lots_equals_base():
    result = compute_kelly_lots(100000, 3, 1000, cfg={"kelly_enabled": False})
    assert result.kelly_lots == 3


# ── insufficient history ──────────────────────────────────────────────────────

def test_insufficient_history_fallback():
    db = _make_db([500.0, 300.0, -200.0])   # only 3, need 20
    try:
        result = compute_kelly_lots(100000, 2, 1000, db_path=db, cfg={"kelly_enabled": True, "kelly_min_trades": 20})
        assert result.used_fallback is True
        assert result.kelly_lots == 2
    finally:
        os.unlink(db)


def test_missing_db_fallback():
    result = compute_kelly_lots(100000, 1, 1000, db_path="no_such.db", cfg={"kelly_enabled": True})
    assert result.used_fallback is True


# ── formula accuracy ──────────────────────────────────────────────────────────

def test_kelly_formula_wins_increase_lots():
    # All-win history → Kelly recommends more lots
    pnls = [1000.0] * 30
    db = _make_db(pnls)
    try:
        result = compute_kelly_lots(100000, 1, 500, db_path=db, cfg={
            "kelly_enabled": True, "kelly_min_trades": 20, "kelly_max_lots_mult": 5.0
        })
        assert result.used_fallback is False
        assert result.kelly_lots >= 1
        assert result.win_rate == 1.0
    finally:
        os.unlink(db)


def test_kelly_all_loss_history_fallback():
    # All losses → kelly_f negative → fallback to base
    pnls = [-500.0] * 25
    db = _make_db(pnls)
    try:
        result = compute_kelly_lots(100000, 2, 500, db_path=db, cfg={
            "kelly_enabled": True, "kelly_min_trades": 20,
        })
        # avg_win == 0 → used_fallback
        assert result.kelly_lots == 2
    finally:
        os.unlink(db)


def test_kelly_clamp_max():
    # Very high Kelly fraction should be clamped
    pnls = [2000.0] * 50
    db = _make_db(pnls)
    try:
        result = compute_kelly_lots(1000000, 2, 100, db_path=db, cfg={
            "kelly_enabled": True, "kelly_min_trades": 20, "kelly_max_lots_mult": 2.0,
        })
        max_allowed = max(1, int(2 * 2.0))
        assert result.kelly_lots <= max_allowed
    finally:
        os.unlink(db)


def test_kelly_clamp_min_one():
    pnls = [100.0] * 10 + [-5000.0] * 15
    db = _make_db(pnls)
    try:
        result = compute_kelly_lots(10000, 1, 500, db_path=db, cfg={
            "kelly_enabled": True, "kelly_min_trades": 20,
        })
        assert result.kelly_lots >= 1
    finally:
        os.unlink(db)


# ── KellyResult fields ────────────────────────────────────────────────────────

def test_result_fields_present():
    result = compute_kelly_lots(100000, 2, 1000, cfg={"kelly_enabled": False})
    assert hasattr(result, "kelly_f")
    assert hasattr(result, "half_kelly")
    assert hasattr(result, "win_rate")
    assert hasattr(result, "avg_win")
    assert hasattr(result, "avg_loss")
    assert hasattr(result, "n_trades")


def test_half_kelly_half_of_kelly_f():
    pnls = [800.0] * 20 + [-300.0] * 10
    db = _make_db(pnls)
    try:
        result = compute_kelly_lots(100000, 1, 500, db_path=db, cfg={
            "kelly_enabled": True, "kelly_min_trades": 20,
        })
        if not result.used_fallback:
            assert abs(result.half_kelly - result.kelly_f * 0.5) < 0.001
    finally:
        os.unlink(db)


def test_mixed_history_reasonable_lots():
    # 60% win rate
    pnls = [500.0] * 18 + [-200.0] * 12
    db = _make_db(pnls)
    try:
        result = compute_kelly_lots(100000, 2, 500, db_path=db, cfg={
            "kelly_enabled": True, "kelly_min_trades": 20, "kelly_max_lots_mult": 3.0,
        })
        assert result.kelly_lots >= 1
        assert isinstance(result.kelly_lots, int)
    finally:
        os.unlink(db)


def test_load_recent_pnls_missing_db():
    pnls = _load_recent_pnls("nonexistent.db", 50)
    assert pnls == []
