"""Tests for core/report_generator.py - PDF Trade Report Generator.

Covers:
- _rl_imports() lazy import with ImportError
- _equity_curve_drawing() with trades and no trades
- _metric_table() structure
- _monte_carlo_table() structure
- _breakdown_table() with/without data
- generate_pdf_report() with trades
- generate_pdf_report() with no trades -> RuntimeError
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from core.report_generator import (
    _breakdown_table,
    _equity_curve_drawing,
    _metric_table,
    _monte_carlo_table,
    _rl_imports,
    generate_pdf_report,
)


class TestRLImports:
    """_rl_imports() lazy import."""

    def test_import_success(self):
        with patch("builtins.__import__") as mock_import:
            # Mock reportlab module
            mock_rl = MagicMock()
            mock_import.return_value = mock_rl
            result = _rl_imports()
            # Should return a tuple of imports
            assert isinstance(result, tuple)

    def test_import_error(self):
        with patch("builtins.__import__", side_effect=ImportError("no reportlab")):
            with pytest.raises(ImportError, match="reportlab is required"):
                _rl_imports()


class TestEquityCurveDrawing:
    """_equity_curve_drawing()."""

    def test_no_trades(self):
        d = _equity_curve_drawing([])
        assert d is not None

    def test_single_trade(self):
        trades = [{"net_pnl": 100.0}]
        d = _equity_curve_drawing(trades)
        assert d is not None

    def test_multiple_trades(self):
        trades = [{"net_pnl": 100.0}, {"net_pnl": -50.0}, {"net_pnl": 200.0}]
        d = _equity_curve_drawing(trades)
        assert d is not None


class TestMetricTable:
    """_metric_table()."""

    def test_returns_table(self):
        metrics = {
            "trades": 10, "win_rate": 60.0, "winners": 6, "losers": 4,
            "avg_win": 200.0, "avg_loss": -100.0, "win_loss_ratio": 2.0,
            "expectancy": 80.0, "profit_factor": 1.5, "total_net_pnl": 800.0,
            "largest_win": 500.0, "largest_loss": -200.0, "sharpe_per_trade": 1.2,
            "max_drawdown": 300.0, "recovery_factor": 2.5,
            "max_consec_wins": 4, "max_consec_losses": 2,
        }
        tbl = _metric_table(metrics, None)
        assert tbl is not None

    def test_zero_metrics(self):
        metrics = {
            "trades": 0, "win_rate": 0.0, "winners": 0, "losers": 0,
            "avg_win": 0.0, "avg_loss": 0.0, "win_loss_ratio": 0.0,
            "expectancy": 0.0, "profit_factor": 0.0, "total_net_pnl": 0.0,
            "largest_win": 0.0, "largest_loss": 0.0, "sharpe_per_trade": 0.0,
            "max_drawdown": 0.0, "recovery_factor": 0.0,
            "max_consec_wins": 0, "max_consec_losses": 0,
        }
        tbl = _metric_table(metrics, None)
        assert tbl is not None


class TestMonteCarloTable:
    """_monte_carlo_table()."""

    def test_returns_table(self):
        mc_result = MagicMock()
        mc_result.n_simulations = 1000
        mc_result.n_trades = 50
        mc_result.p5_final_pnl = -10000.0
        mc_result.median_final_pnl = 15000.0
        mc_result.p95_final_pnl = 50000.0
        mc_result.mean_final_pnl = 18000.0
        mc_result.median_max_drawdown = 5000.0
        mc_result.p95_max_drawdown = 15000.0
        mc_result.prob_of_profit = 0.75
        mc_result.worst_case_streak_p95 = 5
        mc_result.median_sharpe = 1.2
        mc_result.p5_sharpe = 0.5

        tbl = _monte_carlo_table(mc_result)
        assert tbl is not None


class TestBreakdownTable:
    """_breakdown_table()."""

    def test_empty_data_returns_none(self):
        tbl = _breakdown_table({}, "Test Header")
        assert tbl is None

    def test_with_data(self):
        data = {
            "70-79": {"trades": 5, "win_rate": 80.0, "avg_pnl": 200.0, "total_pnl": 1000.0},
            "80-89": {"trades": 3, "win_rate": 66.7, "avg_pnl": 150.0, "total_pnl": 450.0},
        }
        tbl = _breakdown_table(data, "Score Bin Breakdown")
        assert tbl is not None


class TestGeneratePDFReport:
    """generate_pdf_report() tests."""

    @patch("core.report_generator.Path.mkdir")
    def test_no_trades_raises_error(self, mock_mkdir):
        with patch("core.performance_metrics.load_trades") as mock_load:
            mock_load.return_value = []
            with pytest.raises(RuntimeError, match="No trades found"):
                generate_pdf_report("trades.db", days=30, output_path="test.pdf")

    @patch("core.report_generator.Path.mkdir")
    def test_generates_report(self, mock_mkdir):
        with (
            patch("core.performance_metrics.load_trades") as mock_load,
            patch("core.performance_metrics.compute_metrics") as mock_metrics,
            patch("core.report_generator._rl_imports") as mock_rl,
            patch("core.performance_metrics.metrics_by_score_bin", return_value={}),
            patch("core.performance_metrics.metrics_by_index", return_value={}),
            patch("core.performance_metrics.metrics_by_exit_reason", return_value={}),
            patch("core.performance_metrics.metrics_by_regime", return_value={}),
            patch("core.performance_metrics.generate_insights", return_value=[]),
        ):
            mock_load.return_value = [
                {"net_pnl": 100.0, "entry_ts": 1000.0},
                {"net_pnl": -50.0, "entry_ts": 2000.0},
            ]
            mock_metrics.return_value = {
                "trades": 2, "win_rate": 50.0, "winners": 1, "losers": 1,
                "avg_win": 100.0, "avg_loss": -50.0, "win_loss_ratio": 2.0,
                "expectancy": 25.0, "profit_factor": 2.0, "total_net_pnl": 50.0,
                "largest_win": 100.0, "largest_loss": -50.0, "sharpe_per_trade": 0.5,
                "max_drawdown": 50.0, "recovery_factor": 1.0,
                "max_consec_wins": 1, "max_consec_losses": 1,
                "total_return_pct": 0.05, "max_drawdown_pct": 0.02,
            }
            mock_rl.return_value = (
                MagicMock(), MagicMock(), MagicMock(), MagicMock(),
                MagicMock(), MagicMock(), MagicMock(), MagicMock(),
                MagicMock(), MagicMock(), MagicMock(), MagicMock(),
                MagicMock(), MagicMock(), MagicMock(), MagicMock(),
            )
            path = generate_pdf_report("trades.db", days=30, output_path="test_report.pdf")
            assert path is not None
