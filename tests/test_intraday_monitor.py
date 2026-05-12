"""Tests for core/intraday_performance_monitor.py (v2.44 Item 9)."""
import pytest
from core.intraday_performance_monitor import (
    AdaptationParams,
    IntradayPerformanceMonitor,
    IntradayStats,
)

CFG = {
    "intraday_monitor_enabled": True,
    "intraday_min_trades_to_adapt": 3,
    "intraday_defensive_win_rate": 0.25,
    "intraday_cautious_win_rate": 0.40,
    "intraday_defensive_size_mult": 0.50,
    "intraday_cautious_size_mult": 0.75,
    "intraday_defensive_score_boost": 10,
    "intraday_cautious_score_boost": 5,
}


def make_monitor():
    return IntradayPerformanceMonitor(cfg=CFG)


# ── Initial state ─────────────────────────────────────────────────────────────

def test_initial_params_normal():
    m = make_monitor()
    p = m.get_current_params()
    assert p.level == "NORMAL"
    assert p.score_threshold_boost == 0
    assert p.position_size_mult == pytest.approx(1.0)


def test_initial_stats_zeros():
    m = make_monitor()
    s = m.get_stats()
    assert s.trades_today == 0
    assert s.wins_today == 0
    assert s.losses_today == 0


# ── Level transitions ─────────────────────────────────────────────────────────

def test_becomes_defensive_on_low_win_rate():
    m = make_monitor()
    # 1 win, 3 losses → win_rate = 0.25 but ≥ 0.25 → CAUTIOUS, need < 0.25 → DEFENSIVE
    m.record_trade_close(pnl=-100, was_winner=False)
    m.record_trade_close(pnl=-100, was_winner=False)
    m.record_trade_close(pnl=-100, was_winner=False)
    m.record_trade_close(pnl=-100, was_winner=False)
    # 0/4 = 0.0 < 0.25 → DEFENSIVE
    p = m.get_current_params()
    assert p.level == "DEFENSIVE"


def test_becomes_cautious_on_medium_win_rate():
    m = make_monitor()
    m.record_trade_close(pnl=100, was_winner=True)
    m.record_trade_close(pnl=-100, was_winner=False)
    m.record_trade_close(pnl=-100, was_winner=False)
    # 1/3 = 0.33 → between 0.25 and 0.40 → CAUTIOUS
    p = m.get_current_params()
    assert p.level == "CAUTIOUS"


def test_stays_normal_on_good_win_rate():
    m = make_monitor()
    m.record_trade_close(pnl=100, was_winner=True)
    m.record_trade_close(pnl=100, was_winner=True)
    m.record_trade_close(pnl=-100, was_winner=False)
    # 2/3 = 0.67 → NORMAL
    p = m.get_current_params()
    assert p.level == "NORMAL"


def test_no_adaptation_below_min_trades():
    m = make_monitor()
    m.record_trade_close(pnl=-100, was_winner=False)
    m.record_trade_close(pnl=-100, was_winner=False)
    # Only 2 trades, min=3 → still NORMAL
    p = m.get_current_params()
    assert p.level == "NORMAL"


# ── Adaptation params values ──────────────────────────────────────────────────

def test_defensive_boost_value():
    m = make_monitor()
    for _ in range(4):
        m.record_trade_close(-100, False)
    p = m.get_current_params()
    assert p.score_threshold_boost == CFG["intraday_defensive_score_boost"]


def test_defensive_size_mult_value():
    m = make_monitor()
    for _ in range(4):
        m.record_trade_close(-100, False)
    p = m.get_current_params()
    assert p.position_size_mult == pytest.approx(CFG["intraday_defensive_size_mult"])


def test_cautious_boost_value():
    m = make_monitor()
    m.record_trade_close(100, True)
    m.record_trade_close(-100, False)
    m.record_trade_close(-100, False)
    p = m.get_current_params()
    assert p.score_threshold_boost == CFG["intraday_cautious_score_boost"]


def test_cautious_size_mult_value():
    m = make_monitor()
    m.record_trade_close(100, True)
    m.record_trade_close(-100, False)
    m.record_trade_close(-100, False)
    p = m.get_current_params()
    assert p.position_size_mult == pytest.approx(CFG["intraday_cautious_size_mult"])


# ── Recovery from defensive ───────────────────────────────────────────────────

def test_recovery_after_consecutive_wins():
    m = make_monitor()
    for _ in range(4):
        m.record_trade_close(-100, False)
    assert m.get_current_params().level == "DEFENSIVE"
    # 3 consecutive wins → relax one level
    m.record_trade_close(100, True)
    m.record_trade_close(100, True)
    m.record_trade_close(100, True)
    p = m.get_current_params()
    # Should relax from DEFENSIVE → CAUTIOUS
    assert p.level in ("CAUTIOUS", "NORMAL")


# ── Disabled feature ─────────────────────────────────────────────────────────

def test_disabled_always_returns_normal():
    cfg = dict(CFG, intraday_monitor_enabled=False)
    m = IntradayPerformanceMonitor(cfg=cfg)
    for _ in range(5):
        m.record_trade_close(-100, False)
    p = m.get_current_params()
    assert p.level == "NORMAL"
    assert p.score_threshold_boost == 0
    assert p.position_size_mult == pytest.approx(1.0)


# ── Reset daily ──────────────────────────────────────────────────────────────

def test_reset_daily_clears_trades():
    m = make_monitor()
    m.record_trade_close(-100, False)
    m.record_trade_close(-100, False)
    m.record_trade_close(-100, False)
    m.reset_daily()
    s = m.get_stats()
    assert s.trades_today == 0


def test_reset_daily_resets_level():
    m = make_monitor()
    for _ in range(4):
        m.record_trade_close(-100, False)
    m.reset_daily()
    p = m.get_current_params()
    assert p.level == "NORMAL"


# ── Stats ─────────────────────────────────────────────────────────────────────

def test_stats_tracks_wins_losses():
    m = make_monitor()
    m.record_trade_close(100, True)
    m.record_trade_close(-100, False)
    s = m.get_stats()
    assert s.wins_today == 1
    assert s.losses_today == 1
    assert s.trades_today == 2


def test_stats_win_rate():
    m = make_monitor()
    m.record_trade_close(100, True)
    m.record_trade_close(100, True)
    m.record_trade_close(-100, False)
    s = m.get_stats()
    assert s.session_win_rate == pytest.approx(2 / 3, abs=0.001)


def test_stats_has_level():
    m = make_monitor()
    s = m.get_stats()
    assert hasattr(s, "adaptation_level")


def test_adaptation_returns_params():
    m = make_monitor()
    result = m.record_trade_close(-100, False)
    assert isinstance(result, AdaptationParams)
