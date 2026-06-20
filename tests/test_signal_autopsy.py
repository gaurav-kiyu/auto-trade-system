"""Tests for core/signal_autopsy.py - Post-Trade Signal Autopsy.

Covers:
- AutopsyReport, HeatmapCell, TimeHeatmap dataclasses
- _score_bin() helper
- load_autopsy_data() with various DB states
- compute_feature_breakdown()
- find_failure_patterns()
- compute_edge_decay()
- _generate_insights()
- run_autopsy() full pipeline
- format_autopsy_report()
- compute_time_heatmap() and render_ascii_heatmap()
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from core.signal_autopsy import (
    AutopsyReport,
    HeatmapCell,
    TimeHeatmap,
    _score_bin,
    compute_edge_decay,
    compute_feature_breakdown,
    compute_time_heatmap,
    find_failure_patterns,
    format_autopsy_report,
    load_autopsy_data,
    render_ascii_heatmap,
    run_autopsy,
)


class TestScoreBin:
    """_score_bin() helper."""

    def test_90_plus(self):
        assert _score_bin(95) == "90+"
        assert _score_bin(90) == "90+"

    def test_80_to_89(self):
        assert _score_bin(85) == "80-89"
        assert _score_bin(80) == "80-89"

    def test_70_to_79(self):
        assert _score_bin(75) == "70-79"
        assert _score_bin(70) == "70-79"

    def test_60_to_69(self):
        assert _score_bin(65) == "60-69"
        assert _score_bin(60) == "60-69"

    def test_below_60(self):
        assert _score_bin(50) == "<60"
        assert _score_bin(0) == "<60"
        assert _score_bin(-1) == "<60"


class TestLoadAutopsyData:
    """load_autopsy_data() tests."""

    @patch("core.signal_autopsy.Path.is_file")
    @patch("core.signal_autopsy.get_connection")
    def test_missing_db_returns_empty(self, mock_get_conn, mock_is_file):
        mock_is_file.return_value = False
        result = load_autopsy_data("nonexistent.db", days=30)
        assert result == []

    @patch("core.signal_autopsy.Path.is_file")
    @patch("core.signal_autopsy.get_connection")
    def test_empty_db_returns_empty(self, mock_get_conn, mock_is_file):
        mock_is_file.return_value = True
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = []
        mock_get_conn.return_value = mock_conn
        result = load_autopsy_data("empty.db", days=30)
        assert result == []

    @patch("core.signal_autopsy.Path.is_file")
    @patch("core.signal_autopsy.get_connection")
    def test_loads_trades(self, mock_get_conn, mock_is_file):
        mock_is_file.return_value = True
        mock_conn = MagicMock()
        # Use a dict directly (sqlite3.Row supports both [] and .get())
        mock_row = {
            "ts": "2026-01-15T10:00:00",
            "index_name": "NIFTY",
            "direction": "CALL",
            "score": 75.0,
            "net_pnl": 1500.0,
            "regime": "TRENDING",
            "iv": 15.0,
            "vix": 14.0,
            "mode": "PAPER",
        }
        mock_conn.execute.return_value.fetchall.return_value = [mock_row]
        mock_get_conn.return_value = mock_conn
        result = load_autopsy_data("trades.db", days=30)
        assert len(result) == 1
        assert result[0]["direction"] == "CALL"
        assert result[0]["score"] == 75.0
        assert result[0]["net_pnl"] == 1500.0
        assert result[0]["is_winner"] == 1

    @patch("core.signal_autopsy.Path.is_file")
    @patch("core.signal_autopsy.get_connection")
    def test_mode_filter(self, mock_get_conn, mock_is_file):
        mock_is_file.return_value = True
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = []
        mock_get_conn.return_value = mock_conn
        result = load_autopsy_data("trades.db", days=30, mode="LIVE")
        assert result == []

    @patch("core.signal_autopsy.Path.is_file")
    @patch("core.signal_autopsy.get_connection")
    def test_db_error_returns_empty(self, mock_get_conn, mock_is_file):
        mock_is_file.return_value = True
        mock_get_conn.side_effect = OSError("DB locked")
        result = load_autopsy_data("trades.db", days=30)
        assert result == []


class TestComputeFeatureBreakdown:
    """compute_feature_breakdown()."""

    def _make_trade(self, score=75, direction="CALL", regime="TRENDING", index="NIFTY", pnl=100):
        return {
            "score_bin": _score_bin(score),
            "direction": direction,
            "regime": regime,
            "index_name": index,
            "net_pnl": float(pnl),
            "is_winner": 1 if pnl > 0 else 0,
        }

    def test_empty_trades(self):
        assert compute_feature_breakdown([]) == {}

    def test_single_trade(self):
        trades = [self._make_trade()]
        result = compute_feature_breakdown(trades)
        assert "score_bin" in result
        assert "direction" in result
        assert "70-79" in result["score_bin"]
        assert result["score_bin"]["70-79"]["trades"] == 1
        assert result["score_bin"]["70-79"]["win_rate"] == 100.0

    def test_mixed_winners_losers(self):
        trades = [
            self._make_trade(score=85, pnl=200),
            self._make_trade(score=85, pnl=-100),
            self._make_trade(score=85, pnl=50),
        ]
        result = compute_feature_breakdown(trades)
        assert result["score_bin"]["80-89"]["trades"] == 3
        assert result["score_bin"]["80-89"]["win_rate"] == pytest.approx(66.7, abs=0.1)
        assert result["score_bin"]["80-89"]["avg_pnl"] == pytest.approx(50.0, abs=0.1)

    def test_multiple_directions(self):
        trades = [
            self._make_trade(direction="CALL", pnl=100),
            self._make_trade(direction="PUT", pnl=-50),
            self._make_trade(direction="CALL", pnl=-30),
        ]
        result = compute_feature_breakdown(trades)
        assert result["direction"]["CALL"]["trades"] == 2
        assert result["direction"]["CALL"]["win_rate"] == 50.0
        assert result["direction"]["PUT"]["trades"] == 1
        assert result["direction"]["PUT"]["win_rate"] == 0.0


class TestFindFailurePatterns:
    """find_failure_patterns()."""

    def test_no_losers_returns_empty(self):
        trades = [
            {"is_winner": 1, "direction": "CALL", "regime": "TRENDING", "score_bin": "70-79", "net_pnl": 100},
        ]
        assert find_failure_patterns(trades) == []

    def test_top_failure_pattern(self):
        trades = [
            {"is_winner": 0, "direction": "CALL", "regime": "TRENDING", "score_bin": "70-79", "net_pnl": -100},
            {"is_winner": 0, "direction": "CALL", "regime": "TRENDING", "score_bin": "70-79", "net_pnl": -200},
            {"is_winner": 0, "direction": "PUT", "regime": "CHOPPY", "score_bin": "<60", "net_pnl": -50},
        ]
        patterns = find_failure_patterns(trades, top_n=5)
        assert len(patterns) >= 1
        # Most common pattern should be CALL/TRENDING/70-79
        top = patterns[0]
        assert top["direction"] == "CALL"
        assert top["regime"] == "TRENDING"
        assert top["count"] == 2
        assert top["avg_pnl"] == -150.0
        assert top["pct_of_losses"] == pytest.approx(66.7, abs=0.1)

    def test_empty_trades(self):
        assert find_failure_patterns([], top_n=5) == []


class TestComputeEdgeDecay:
    """compute_edge_decay()."""

    def test_empty_trades(self):
        assert compute_edge_decay([], window=10) == []

    def test_fewer_than_window(self):
        trades = [{"is_winner": 1, "net_pnl": 100}] * 5
        assert compute_edge_decay(trades, window=10) == []

    def test_rolling_win_rate(self):
        trades = [
            {"is_winner": 1, "net_pnl": 100},
            {"is_winner": 1, "net_pnl": 50},
            {"is_winner": 0, "net_pnl": -30},
            {"is_winner": 1, "net_pnl": 200},
            {"is_winner": 0, "net_pnl": -50},
        ]
        decay = compute_edge_decay(trades, window=3)
        assert len(decay) == 3  # indices 2, 3, 4
        # Window 1: [1,1,0] -> 66.7%
        assert decay[0]["trade_index"] == 2
        assert decay[0]["win_rate"] == pytest.approx(66.7, abs=0.1)
        assert decay[0]["trades_in_window"] == 3


class TestGenerateInsights:
    """_generate_insights() via run_autopsy."""

    @patch("core.signal_autopsy.load_autopsy_data")
    def test_no_trades_insight(self, mock_load):
        mock_load.return_value = []
        report = run_autopsy("trades.db", days=30)
        assert "No trades found" in report.insights[0]

    @patch("core.signal_autopsy.load_autopsy_data")
    def test_best_score_bin_insight(self, mock_load):
        mock_load.return_value = [
            {"score_bin": "80-89", "direction": "CALL", "regime": "TRENDING", "index_name": "NIFTY",
             "is_winner": 1, "net_pnl": 200, "ts": "2026-01-15T10:00:00"},
            {"score_bin": "80-89", "direction": "CALL", "regime": "TRENDING", "index_name": "NIFTY",
             "is_winner": 1, "net_pnl": 150, "ts": "2026-01-15T11:00:00"},
        ]
        report = run_autopsy("trades.db", days=30)
        assert report.n_trades == 2
        assert report.overall_win_rate == 100.0
        assert any("Score bin" in ins for ins in report.insights)


class TestFormatAutopsyReport:
    """format_autopsy_report()."""

    def test_empty_report(self):
        report = AutopsyReport(n_trades=0, n_winners=0, n_losers=0, overall_win_rate=0.0)
        text = format_autopsy_report(report)
        assert "0 trades" in text
        assert "Win Rate: 0.0%" in text

    def test_report_with_data(self):
        report = AutopsyReport(
            n_trades=10, n_winners=6, n_losers=4, overall_win_rate=60.0,
            feature_breakdown={
                "score_bin": {
                    "70-79": {"trades": 5, "win_rate": 80.0, "avg_pnl": 200.0},
                },
            },
            failure_patterns=[
                {"direction": "CALL", "regime": "CHOPPY", "score_bin": "<60",
                 "count": 2, "pct_of_losses": 50.0},
            ],
            insights=["Sample insight"],
        )
        text = format_autopsy_report(report)
        assert "10 trades" in text
        assert "Win Rate: 60.0%" in text
        assert "Score Bin Breakdown" in text
        assert "Sample insight" in text


class TestTimeHeatmap:
    """compute_time_heatmap() and render_ascii_heatmap()."""

    def _make_trade(self, ts_string, is_winner=True, pnl=100):
        return {"ts": ts_string, "is_winner": 1 if is_winner else 0, "net_pnl": float(pnl)}

    def test_empty_trades(self):
        hmap = compute_time_heatmap([])
        assert hmap.cells == []
        assert hmap.hours == []
        assert hmap.days == []

    def test_single_trade(self):
        trades = [self._make_trade("2026-01-15T10:30:00")]  # Thursday 10:30
        hmap = compute_time_heatmap(trades, min_cell_trades=3)
        assert len(hmap.cells) == 1
        assert hmap.cells[0].hour == 10
        assert hmap.cells[0].day_of_week == 3  # Thursday
        assert hmap.cells[0].n_trades == 1
        assert hmap.cells[0].win_rate == 1.0

    def test_invalid_ts_skipped(self):
        trades = [self._make_trade("invalid-ts")]
        hmap = compute_time_heatmap(trades)
        assert hmap.cells == []

    def test_render_empty(self):
        hmap = TimeHeatmap()
        text = render_ascii_heatmap(hmap)
        assert "no heatmap data" in text

    def test_render_with_data(self):
        hmap = TimeHeatmap(
            cells=[
                HeatmapCell(hour=10, day_of_week=0, n_trades=5, n_wins=3, win_rate=0.6, avg_pnl=100.0),
                HeatmapCell(hour=11, day_of_week=0, n_trades=3, n_wins=2, win_rate=0.6667, avg_pnl=50.0),
            ],
            hours=[10, 11],
            days=[0],
            min_cell_trades=3,
        )
        text = render_ascii_heatmap(hmap)
        assert "Day\\Hour" in text
        assert "Mon" in text or "0" in text
        assert "60" in text or "67" in text

    def test_sparse_cell_shows_dash(self):
        hmap = TimeHeatmap(
            cells=[
                HeatmapCell(hour=10, day_of_week=0, n_trades=1, n_wins=1, win_rate=1.0, avg_pnl=100.0),
            ],
            hours=[10],
            days=[0],
            min_cell_trades=3,
        )
        text = render_ascii_heatmap(hmap)
        assert "--" in text
