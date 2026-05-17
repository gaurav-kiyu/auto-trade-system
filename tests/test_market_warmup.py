"""Tests for core/market_warmup.py."""

from __future__ import annotations

import time
from datetime import date, datetime, timedelta
from unittest.mock import patch

import pytest

from core.market_warmup import MarketWarmup


# ── Constructor ──────────────────────────────────────────────────────────

def test_constructor_defaults():
    m = MarketWarmup()
    assert m._enabled is True
    assert m._duration_mins == 15
    assert m._size_mult == 0.5
    assert m._score_boost == 10
    assert m._max_trades == 2


def test_constructor_with_cfg():
    m = MarketWarmup(cfg={
        "warmup_enabled": False,
        "warmup_duration_mins": 30,
        "warmup_size_mult": 0.75,
        "warmup_score_boost": 5,
        "warmup_max_trades": 3,
    })
    assert m._enabled is False
    assert m._duration_mins == 30
    assert m._size_mult == 0.75
    assert m._score_boost == 5
    assert m._max_trades == 3


# ── is_warmup_active ────────────────────────────────────────────────────

def test_warmup_inactive_when_disabled():
    m = MarketWarmup(cfg={"warmup_enabled": False})
    assert m.is_warmup_active() is False


def test_warmup_inactive_when_no_market_open():
    """Weekend or non-trading day should have no warm-up."""
    m = MarketWarmup()
    m.reset_day()
    with patch.object(m, "_market_open_today", return_value=None):
        assert m.is_warmup_active() is False


def test_warmup_active_during_period():
    m = MarketWarmup(cfg={"warmup_duration_mins": 60})
    m.reset_day()
    # Simulate market open 5 minutes ago
    five_min_ago = datetime.now().replace(hour=9, minute=15, second=0, microsecond=0)
    m._warmup_end = five_min_ago + timedelta(minutes=60)
    m._current_day = date.today()
    # Current time is within 60 mins of 9:15
    with patch("core.market_warmup.datetime") as mock_dt:
        mock_dt.now.return_value = datetime.now().replace(hour=9, minute=20)
        assert m.is_warmup_active() is True


def test_warmup_inactive_after_period():
    m = MarketWarmup(cfg={"warmup_duration_mins": 15})
    m.reset_day()
    now = datetime.now()
    # Simulate warm-up ended 1 hour ago
    m._warmup_end = now - timedelta(hours=1)
    m._current_day = date.today()
    assert m.is_warmup_active() is False


# ── market_open_today ───────────────────────────────────────────────────

def test_market_open_weekday_returns_time():
    m = MarketWarmup()
    result = m._market_open_today()
    if result is not None:
        assert result.hour == 9
        assert result.minute == 15


# ── can_enter ───────────────────────────────────────────────────────────

def test_can_enter_when_disabled():
    m = MarketWarmup(cfg={"warmup_enabled": False})
    assert m.can_enter("NIFTY") is True


def test_can_enter_when_not_warmup():
    m = MarketWarmup()
    m.reset_day()
    with patch.object(m, "is_warmup_active", return_value=False):
        assert m.can_enter("NIFTY") is True


def test_can_enter_below_max():
    m = MarketWarmup(cfg={"warmup_max_trades": 2})
    m.reset_day()
    with patch.object(m, "is_warmup_active", return_value=True):
        assert m.can_enter("NIFTY") is True
        assert m.can_enter("BANKNIFTY") is True


def test_can_enter_blocks_after_max():
    m = MarketWarmup(cfg={"warmup_max_trades": 1})
    m.reset_day()
    with patch.object(m, "is_warmup_active", return_value=True):
        assert m.can_enter("NIFTY") is True
        m.try_mark_entry("NIFTY")
        assert m.can_enter("BANKNIFTY") is False


# ── try_mark_entry ──────────────────────────────────────────────────────

def test_try_mark_entry_returns_false_when_blocked():
    m = MarketWarmup(cfg={"warmup_max_trades": 1})
    m.reset_day()
    with patch.object(m, "is_warmup_active", return_value=True):
        assert m.try_mark_entry("NIFTY") is True
        assert m.try_mark_entry("BANKNIFTY") is False


def test_try_mark_entry_always_true_not_warmup():
    m = MarketWarmup()
    m.reset_day()
    with patch.object(m, "is_warmup_active", return_value=False):
        assert m.try_mark_entry("NIFTY") is True
        assert m.try_mark_entry("BANKNIFTY") is True


# ── position_size_mult ──────────────────────────────────────────────────

def test_position_size_mult_normal():
    m = MarketWarmup()
    with patch.object(m, "is_warmup_active", return_value=False):
        assert m.position_size_mult() == 1.0


def test_position_size_mult_warmup():
    m = MarketWarmup(cfg={"warmup_size_mult": 0.5})
    with patch.object(m, "is_warmup_active", return_value=True):
        assert m.position_size_mult() == 0.5


def test_position_size_mult_disabled():
    m = MarketWarmup(cfg={"warmup_enabled": False})
    with patch.object(m, "is_warmup_active", return_value=True):
        assert m.position_size_mult() == 1.0


# ── score_threshold_adjustment ──────────────────────────────────────────

def test_score_adjustment_normal():
    m = MarketWarmup()
    with patch.object(m, "is_warmup_active", return_value=False):
        assert m.score_threshold_adjustment() == 0


def test_score_adjustment_warmup():
    m = MarketWarmup(cfg={"warmup_score_boost": 10})
    with patch.object(m, "is_warmup_active", return_value=True):
        assert m.score_threshold_adjustment() == 10


def test_score_adjustment_disabled():
    m = MarketWarmup(cfg={"warmup_enabled": False})
    with patch.object(m, "is_warmup_active", return_value=True):
        assert m.score_threshold_adjustment() == 0


# ── adjusted_position_size ──────────────────────────────────────────────

def test_adjusted_size_normal():
    m = MarketWarmup()
    with patch.object(m, "is_warmup_active", return_value=False):
        assert m.adjusted_position_size(10) == 10


def test_adjusted_size_warmup():
    m = MarketWarmup(cfg={"warmup_size_mult": 0.5})
    with patch.object(m, "is_warmup_active", return_value=True):
        assert m.adjusted_position_size(10) == 5


def test_adjusted_size_minimum_one():
    m = MarketWarmup(cfg={"warmup_size_mult": 0.25})
    with patch.object(m, "is_warmup_active", return_value=True):
        assert m.adjusted_position_size(1) == 1


def test_adjusted_size_rounded():
    m = MarketWarmup(cfg={"warmup_size_mult": 0.5})
    with patch.object(m, "is_warmup_active", return_value=True):
        assert m.adjusted_position_size(3) == 2  # round(1.5)


# ── reset_day ───────────────────────────────────────────────────────────

def test_reset_day_clears_state():
    m = MarketWarmup()
    m._current_day = date(2026, 1, 1)
    m._warmup_end = datetime(2026, 1, 1, 9, 30)
    m._entries["NIFTY"] = time.time()
    m.reset_day()
    assert m._current_day is None
    assert m._warmup_end is None
    assert len(m._entries) == 0


# ── status ──────────────────────────────────────────────────────────────

def test_status():
    m = MarketWarmup()
    st = m.status()
    assert st["enabled"] is True
    assert st["duration_mins"] == 15
    assert st["size_mult"] == 0.5
    assert st["score_boost"] == 10
    assert st["max_trades"] == 2
    assert "warmup_active" in st
    assert "entries_in_warmup" in st


def test_status_disabled():
    m = MarketWarmup(cfg={"warmup_enabled": False})
    st = m.status()
    assert st["enabled"] is False
    assert st["warmup_active"] is False


def test_status_warmup_active_shows_remaining():
    m = MarketWarmup()
    m.reset_day()
    m._current_day = date.today()
    m._warmup_end = datetime.now() + timedelta(minutes=10)
    st = m.status()
    assert st["warmup_active"] is True
    assert "remaining" in st
