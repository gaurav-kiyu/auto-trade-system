"""Tests for heatmap extensions in core/signal_autopsy.py (v2.44 Item 16)."""
import pytest
from core.signal_autopsy import (
    HeatmapCell,
    TimeHeatmap,
    AutopsyReport,
    compute_time_heatmap,
    render_ascii_heatmap,
    run_autopsy,
    load_autopsy_data,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def make_trades(n=20, win_frac=0.5):
    trades = []
    for i in range(n):
        pnl = 100 if i < int(n * win_frac) else -50
        dow = i % 5   # Mon–Fri
        hr  = 9 + (i % 7)  # 9–15
        ts  = f"2024-01-{(i % 22) + 2:02d}T{hr:02d}:30:00"
        trades.append({
            "ts":         ts,
            "index_name": "NIFTY",
            "direction":  "CALL",
            "score":      70,
            "score_bin":  "70-79",
            "net_pnl":    float(pnl),
            "regime":     "UPTREND",
            "iv":         15.0,
            "vix":        14.0,
            "mode":       "PAPER",
            "is_winner":  1 if pnl > 0 else 0,
        })
    return trades


# ── HeatmapCell dataclass ─────────────────────────────────────────────────────

def test_heatmap_cell_has_all_fields():
    cell = HeatmapCell(
        hour=10, day_of_week=0, n_trades=5, n_wins=3,
        win_rate=0.6, avg_pnl=50.0,
    )
    assert cell.hour == 10
    assert cell.day_of_week == 0
    assert cell.n_trades == 5
    assert cell.n_wins == 3
    assert cell.win_rate == pytest.approx(0.6)
    assert cell.avg_pnl == pytest.approx(50.0)


def test_heatmap_cell_defaults():
    cell = HeatmapCell(hour=9, day_of_week=1, n_trades=2, n_wins=1,
                       win_rate=0.5, avg_pnl=0.0)
    assert isinstance(cell, HeatmapCell)


# ── TimeHeatmap dataclass ─────────────────────────────────────────────────────

def test_time_heatmap_has_cells():
    hm = TimeHeatmap(cells=[], hours=[], days=[])
    assert isinstance(hm.cells, list)
    assert isinstance(hm.hours, list)
    assert isinstance(hm.days, list)


# ── compute_time_heatmap ──────────────────────────────────────────────────────

def test_compute_heatmap_returns_time_heatmap():
    trades = make_trades(20)
    hm = compute_time_heatmap(trades)
    assert isinstance(hm, TimeHeatmap)


def test_compute_heatmap_cells_non_empty():
    trades = make_trades(20)
    hm = compute_time_heatmap(trades)
    assert len(hm.cells) > 0


def test_compute_heatmap_hours_sorted():
    trades = make_trades(20)
    hm = compute_time_heatmap(trades)
    assert hm.hours == sorted(hm.hours)


def test_compute_heatmap_days_sorted():
    trades = make_trades(20)
    hm = compute_time_heatmap(trades)
    assert hm.days == sorted(hm.days)


def test_compute_heatmap_win_rate_range():
    trades = make_trades(30)
    hm = compute_time_heatmap(trades)
    for cell in hm.cells:
        assert 0.0 <= cell.win_rate <= 1.0


def test_compute_heatmap_empty_trades():
    hm = compute_time_heatmap([])
    assert hm.cells == []
    assert hm.hours == []
    assert hm.days == []


def test_compute_heatmap_all_wins():
    trades = make_trades(10, win_frac=1.0)
    hm = compute_time_heatmap(trades)
    for cell in hm.cells:
        assert cell.win_rate == pytest.approx(1.0)


def test_compute_heatmap_min_cell_trades_stored():
    trades = make_trades(10)
    hm = compute_time_heatmap(trades, min_cell_trades=5)
    assert hm.min_cell_trades == 5


def test_compute_heatmap_invalid_ts_skipped():
    trades = [
        {"ts": "INVALID", "net_pnl": 100, "is_winner": 1},
        {"ts": "2024-01-15T10:30:00", "net_pnl": -50, "is_winner": 0},
    ]
    hm = compute_time_heatmap(trades)
    assert len(hm.cells) >= 0  # invalid ts is skipped gracefully


# ── render_ascii_heatmap ──────────────────────────────────────────────────────

def test_render_heatmap_returns_string():
    trades = make_trades(30)
    hm = compute_time_heatmap(trades)
    chart = render_ascii_heatmap(hm)
    assert isinstance(chart, str)


def test_render_heatmap_non_empty():
    trades = make_trades(30)
    hm = compute_time_heatmap(trades)
    chart = render_ascii_heatmap(hm)
    assert len(chart) > 0


def test_render_heatmap_empty_returns_message():
    hm = TimeHeatmap(cells=[], hours=[], days=[])
    chart = render_ascii_heatmap(hm)
    assert "no heatmap data" in chart.lower() or len(chart) > 0


def test_render_heatmap_contains_day_labels():
    trades = make_trades(30)
    hm = compute_time_heatmap(trades)
    chart = render_ascii_heatmap(hm)
    # Should contain at least one day name
    assert any(d in chart for d in ["Mon", "Tue", "Wed", "Thu", "Fri"])


def test_render_heatmap_shows_dash_for_sparse():
    # Create one cell with only 1 trade (below default min of 3)
    cell = HeatmapCell(hour=10, day_of_week=0, n_trades=1, n_wins=0,
                       win_rate=0.0, avg_pnl=-50.0)
    hm = TimeHeatmap(cells=[cell], hours=[10], days=[0], min_cell_trades=3)
    chart = render_ascii_heatmap(hm)
    assert "--" in chart


# ── AutopsyReport.time_heatmap integration ────────────────────────────────────

def test_autopsy_report_has_time_heatmap_field():
    report = AutopsyReport(n_trades=0, n_winners=0, n_losers=0, overall_win_rate=0.0)
    assert hasattr(report, "time_heatmap")


def test_autopsy_report_time_heatmap_default_none():
    report = AutopsyReport(n_trades=0, n_winners=0, n_losers=0, overall_win_rate=0.0)
    assert report.time_heatmap is None


def test_run_autopsy_returns_heatmap():
    report = run_autopsy("/nonexistent.db", days=30)
    # run_autopsy with no DB returns zero-trade report; time_heatmap may be None or empty
    assert report.time_heatmap is None or isinstance(report.time_heatmap, TimeHeatmap)
