"""Tests for core.simulation_engine — deep simulation engine for strategy edge validation."""

from __future__ import annotations

from core.simulation_engine import (
    SIGNAL_EARLY,
    SIGNAL_CONFIRMED,
    SIGNAL_STRONG,
    SimConfig,
    SimulationEngine,
    SimulationResult,
    TradeRecord,
    classify_signal_type,
    score_segment,
    _calc_max_dd,
    _make_seg,
)


# ── Signal type classification ───────────────────────────────────────────

def test_classify_signal_type_strong() -> None:
    assert classify_signal_type(85) == "STRONG"
    assert classify_signal_type(80) == "STRONG"


def test_classify_signal_type_moderate() -> None:
    assert classify_signal_type(75) == "MODERATE"
    assert classify_signal_type(70) == "MODERATE"


def test_classify_signal_type_weak() -> None:
    assert classify_signal_type(65) == "WEAK"
    assert classify_signal_type(60) == "WEAK"


def test_classify_signal_type_sub_minimum() -> None:
    assert classify_signal_type(59) == "WEAK"
    assert classify_signal_type(0) == "WEAK"


# ── Score segment ────────────────────────────────────────────────────────

def test_score_segment_strong() -> None:
    assert score_segment(85) == "Strong (80+)"
    assert score_segment(80) == "Strong (80+)"


def test_score_segment_moderate() -> None:
    assert score_segment(75) == "Moderate (70-79)"
    assert score_segment(70) == "Moderate (70-79)"


def test_score_segment_weak() -> None:
    assert score_segment(65) == "Weak (60-69)"
    assert score_segment(60) == "Weak (60-69)"


# ── Constants ────────────────────────────────────────────────────────────

def test_signal_constants() -> None:
    assert SIGNAL_EARLY == 60
    assert SIGNAL_CONFIRMED == 70
    assert SIGNAL_STRONG == 80


# ── SimConfig ────────────────────────────────────────────────────────────

def test_sim_config_defaults() -> None:
    cfg = SimConfig()
    assert cfg.initial_capital == 100_000.0
    assert cfg.lots_per_trade == 1
    assert cfg.warmup_bars == 35
    assert cfg.score_threshold == 65
    assert cfg.use_tiered is False
    assert cfg.use_option_model is True
    assert cfg.vix == 14.0
    assert cfg.dte == 3


def test_sim_config_custom() -> None:
    cfg = SimConfig(initial_capital=50_000.0, lots_per_trade=2, use_tiered=True, trade_weak=True)
    assert cfg.initial_capital == 50_000.0
    assert cfg.lots_per_trade == 2
    assert cfg.use_tiered is True
    assert cfg.trade_weak is True


def test_sim_config_frozen() -> None:
    cfg = SimConfig()
    import pytest
    with pytest.raises(AttributeError):
        cfg.initial_capital = 999  # type: ignore[misc]


# ── SimulationResult ─────────────────────────────────────────────────────

def test_simulation_result_defaults() -> None:
    result = SimulationResult(records=[], equity_curve=[100_000.0], ending_capital=100_000.0,
                              initial_capital=100_000.0, config=SimConfig())
    assert result.total_trades == 0
    assert result.wins == 0
    assert result.losses == 0
    assert result.win_rate == 0.0
    assert result.ending_capital == 100_000.0


def test_simulation_result_with_records() -> None:
    cfg = SimConfig()
    records = [
        TradeRecord(
            trade_id=1, entry_time="09:30", exit_time="10:00",
            symbol="NIFTY", direction="CALL",
            score=75, threshold=65, signal_type="CONFIRMED", score_segment="Moderate (70-79)",
            score_components={"vwap": 10}, features_triggered=["vwap"],
            entry_index=23000.0, exit_index=23100.0, sl_index=22950.0, tp_index=23200.0,
            entry_premium=100.0, exit_premium=150.0, sl_premium=80.0, tp_premium=200.0,
            peak_premium=160.0, delta=0.4, lot_size_n=50, exit_reason="take_profit",
            bars_held=5, slippage_cost=3.0, gross_pnl=2500.0, net_pnl=2450.0,
            rr_achieved=2.5, pct_pnl=50.0, regime="TRENDING",
            adx=28.0, rsi=62.0, vwap=23050.0, vol_ratio=1.5,
            breakout_ok=True, macd_histogram=12.0, is_winner=True, failure_tags=[],
        )
    ]
    result = SimulationResult(records=records, equity_curve=[100_000.0, 102_450.0],
                              ending_capital=102_450.0, initial_capital=100_000.0, config=cfg)
    assert result.total_trades == 0  # not computed until _compute_analytics called
    assert result.ending_capital == 102_450.0


# ── SegmentStats ─────────────────────────────────────────────────────────

def test_segment_stats_win_rate() -> None:
    seg = _make_seg()
    seg.label = "Test"
    seg.trades = 10
    seg.wins = 7
    assert seg.win_rate == 70.0


def test_segment_stats_zero_trades() -> None:
    seg = _make_seg()
    assert seg.win_rate == 0.0
    assert seg.avg_net == 0.0


def test_segment_stats_expectancy() -> None:
    seg = _make_seg()
    result = seg.expectancy(win_trades_net=[200.0, 300.0], loss_trades_net=[-100.0])
    # 2 wins, 1 loss → wr=0.667, aw=250, al=100 → 0.667*250 - 0.333*100 = 166.75 - 33.33 = 133.42
    assert result > 0


# ── _calc_max_dd ─────────────────────────────────────────────────────────

def test_calc_max_dd_basic() -> None:
    dd = _calc_max_dd([100.0, 110.0, 105.0, 95.0, 100.0])
    # peak=110, trough=95 → dd = 15/110 = 13.636%
    assert dd == 13.6364


def test_calc_max_dd_monotonic_up() -> None:
    dd = _calc_max_dd([100.0, 101.0, 102.0, 103.0])
    assert dd == 0.0


def test_calc_max_dd_empty() -> None:
    assert _calc_max_dd([]) == 0.0


# ── SimulationEngine construction ────────────────────────────────────────

def test_engine_construction() -> None:
    engine = SimulationEngine(
        signal_cfg={"SCORE_THRESHOLD": 65, "MIN_SCORE_FLOOR": 0},
        regime_params=None,  # type: ignore[arg-type]
        iv_spike_threshold=45.0,
        vol_ratio_min=1.2,
        name="NIFTY",
    )
    assert engine._name == "NIFTY"
    assert engine._iv == 45.0
    assert engine._vrm == 1.2
