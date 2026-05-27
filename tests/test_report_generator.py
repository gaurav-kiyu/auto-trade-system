"""
Tests for Phase 6 — PDF Report Generator (core/report_generator.py).

Covers:
  - generate_pdf_report: creates a valid PDF file when trades are present
  - generate_pdf_report: raises RuntimeError when no trades
  - _equity_curve_drawing: returns a Drawing object
  - _metric_table: returns a Table object
  - _breakdown_table: returns None on empty data; Table on non-empty
  - score_adj integration: output dir created automatically
  - CLI entry point: importable and callable
  - _rl_imports: ImportError path (lines 62-63)
  - _equity_curve_drawing: negative cumulative bars (line 127)
  - Monte Carlo exception handler (lines 411-412)
  - Benchmark timestamp extraction (lines 423-424)
  - Benchmark table with data (lines 464-493)
  - _cli() function (lines 511-518)
  - __name__ == '__main__' block (line 522)
"""
from __future__ import annotations

import datetime
import sqlite3
from pathlib import Path

import pytest
from core.report_generator import (
    _breakdown_table,
    _equity_curve_drawing,
    _metric_table,
    generate_pdf_report,
)

# ── Fixtures ───────────────────────────────────────────────────────────────────

def _make_trades_db(path: Path, n: int = 20, win_frac: float = 0.60) -> None:
    """Create a minimal trades.db compatible with performance_metrics.load_trades."""
    con = sqlite3.connect(str(path))
    con.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY,
            ts TEXT, index_name TEXT, direction TEXT,
            entry REAL, exit_price REAL, qty INTEGER,
            gross_pnl REAL, net_pnl REAL,
            reason TEXT, regime TEXT, score INTEGER,
            iv REAL, vix REAL, ltp_estimated INTEGER,
            partial INTEGER, sl_warned INTEGER,
            mode TEXT, version TEXT
        )
    """)
    base = datetime.datetime(2026, 1, 2, 10, 30, 0)
    for i in range(n):
        is_win = i < round(n * win_frac)
        net = 80.0 + i * 2 if is_win else -(40.0 + i)
        gross = net + 40.0
        con.execute(
            "INSERT INTO trades (ts, index_name, direction, entry, exit_price, qty, "
            "gross_pnl, net_pnl, reason, regime, score, iv, vix, ltp_estimated, "
            "partial, sl_warned, mode, version) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                (base + datetime.timedelta(days=i)).isoformat(),
                ["NIFTY", "BANKNIFTY", "FINNIFTY"][i % 3],
                "CALL" if i % 2 == 0 else "PUT",
                100.0, 110.0 if is_win else 88.0, 50,
                gross, net,
                "take_profit" if is_win else "stop_loss",
                "MID_SESSION", 70 + (i % 15),
                0.0, 15.0, 0, 0, 0, "PAPER", "1.0",
            ),
        )
    con.commit()
    con.close()


# ── generate_pdf_report ────────────────────────────────────────────────────────

class TestGeneratePdfReport:
    def test_creates_pdf_file(self, tmp_path):
        db = tmp_path / "trades.db"
        _make_trades_db(db, n=20)
        out = tmp_path / "reports" / "test.pdf"
        result = generate_pdf_report(str(db), days=0, mode="ALL", output_path=out)
        assert Path(result).is_file()
        assert Path(result).suffix == ".pdf"
        assert Path(result).stat().st_size > 1000  # non-trivial file

    def test_auto_generates_output_path(self, tmp_path):
        db = tmp_path / "trades.db"
        _make_trades_db(db, n=20)
        result = generate_pdf_report(str(db), days=0, mode="ALL",
                                     cfg={"report_output_dir": str(tmp_path / "reports")})
        assert Path(result).is_file()

    def test_raises_on_no_trades(self, tmp_path):
        db = tmp_path / "trades.db"
        _make_trades_db(db, n=0)
        with pytest.raises(RuntimeError, match="No trades"):
            generate_pdf_report(str(db), days=0, mode="ALL",
                                output_path=tmp_path / "out.pdf")

    def test_raises_on_missing_db(self, tmp_path):
        with pytest.raises(Exception):
            generate_pdf_report(str(tmp_path / "missing.db"), days=0,
                                output_path=tmp_path / "out.pdf")

    def test_creates_output_dir_if_missing(self, tmp_path):
        db = tmp_path / "trades.db"
        _make_trades_db(db, n=20)
        out_dir = tmp_path / "nested" / "deeply" / "reports"
        result = generate_pdf_report(str(db), days=0, mode="ALL",
                                     cfg={"report_output_dir": str(out_dir)})
        assert Path(result).is_file()

    def test_mode_filter_paper(self, tmp_path):
        db = tmp_path / "trades.db"
        _make_trades_db(db, n=20)
        out = tmp_path / "out.pdf"
        result = generate_pdf_report(str(db), days=0, mode="PAPER", output_path=out)
        assert Path(result).is_file()

    def test_returns_str(self, tmp_path):
        db = tmp_path / "trades.db"
        _make_trades_db(db, n=20)
        result = generate_pdf_report(str(db), days=0,
                                     cfg={"report_output_dir": str(tmp_path)})
        assert isinstance(result, str)

    def test_days_filter_accepts_zero(self, tmp_path):
        db = tmp_path / "trades.db"
        _make_trades_db(db, n=10)
        result = generate_pdf_report(str(db), days=0,
                                     cfg={"report_output_dir": str(tmp_path)})
        assert Path(result).is_file()


# ── _equity_curve_drawing ─────────────────────────────────────────────────────

class TestEquityCurveDrawing:
    def test_returns_drawing_object(self):
        from reportlab.graphics.shapes import Drawing
        trades = [{"net_pnl": 100.0}, {"net_pnl": -50.0}, {"net_pnl": 80.0}]
        d = _equity_curve_drawing(trades)
        assert isinstance(d, Drawing)

    def test_empty_trades_returns_drawing(self):
        from reportlab.graphics.shapes import Drawing
        d = _equity_curve_drawing([])
        assert isinstance(d, Drawing)

    def test_custom_dimensions(self):
        from reportlab.graphics.shapes import Drawing
        trades = [{"net_pnl": 50.0}]
        d = _equity_curve_drawing(trades, width=300, height=80)
        assert isinstance(d, Drawing)


# ── _metric_table ─────────────────────────────────────────────────────────────

class TestMetricTable:
    def _styles(self):
        from reportlab.lib.styles import getSampleStyleSheet
        return getSampleStyleSheet()

    def test_returns_table(self):
        from reportlab.platypus import Table
        m = {"trades": 10, "win_rate": 60.0, "winners": 6, "losers": 4,
             "avg_win": 80.0, "avg_loss": -40.0, "win_loss_ratio": 2.0,
             "expectancy": 24.0, "profit_factor": 1.8, "total_net_pnl": 240.0,
             "total_gross_pnl": 320.0, "largest_win": 200.0, "largest_loss": -80.0,
             "std_pnl": 55.0, "sharpe_per_trade": 0.44, "max_consec_wins": 4,
             "max_consec_losses": 2, "max_drawdown": 120.0, "current_drawdown": 0.0,
             "recovery_factor": 2.0}
        tbl = _metric_table(m, self._styles())
        assert isinstance(tbl, Table)

    def test_handles_inf_profit_factor(self):
        from reportlab.platypus import Table
        m = {"trades": 5, "win_rate": 100.0, "winners": 5, "losers": 0,
             "avg_win": 50.0, "avg_loss": 0.0, "win_loss_ratio": float("inf"),
             "expectancy": 50.0, "profit_factor": "inf", "total_net_pnl": 250.0,
             "total_gross_pnl": 290.0, "largest_win": 80.0, "largest_loss": 0.0,
             "std_pnl": 10.0, "sharpe_per_trade": 1.2, "max_consec_wins": 5,
             "max_consec_losses": 0, "max_drawdown": 0.0, "current_drawdown": 0.0,
             "recovery_factor": "inf"}
        tbl = _metric_table(m, self._styles())
        assert isinstance(tbl, Table)


# ── _breakdown_table ──────────────────────────────────────────────────────────

class TestBreakdownTable:
    def test_returns_none_on_empty(self):
        assert _breakdown_table({}, "Test") is None

    def test_returns_table_on_data(self):
        from reportlab.platypus import Table
        data = {
            "NIFTY":     {"trades": 5, "win_rate": 60.0, "avg_pnl": 20.0, "total_pnl": 100.0},
            "BANKNIFTY": {"trades": 8, "win_rate": 50.0, "avg_pnl": -5.0, "total_pnl": -40.0},
        }
        tbl = _breakdown_table(data, "Index Breakdown")
        assert isinstance(tbl, Table)


# ── _rl_imports: ImportError path (lines 62-63) ──────────────────────────────

class TestRlImports:
    """Cover the ImportError handler in _rl_imports."""

    def test_raises_import_error_when_reportlab_missing(self):
        import sys, builtins
        saved = {k: sys.modules.pop(k) for k in list(sys.modules) if k.startswith('reportlab')}
        orig_import = builtins.__import__
        def mock_import(name, *args, **kwargs):
            if name == 'reportlab' or name.startswith('reportlab.'):
                raise ImportError(f"No module named {name}")
            return orig_import(name, *args, **kwargs)
        try:
            builtins.__import__ = mock_import
            from core.report_generator import _rl_imports
            with pytest.raises(ImportError, match="reportlab is required"):
                _rl_imports()
        finally:
            builtins.__import__ = orig_import
            sys.modules.update(saved)


# ── _equity_curve_drawing: negative bar branch (line 127) ────────────────────

class TestEquityCurveNegative:
    """Cover the else-branch where bar_h < 0 (negative cumulative PnL)."""

    def test_negative_cumulative_renders_bars_below_baseline(self):
        from reportlab.graphics.shapes import Drawing
        trades = [{"net_pnl": -500.0}, {"net_pnl": -100.0}, {"net_pnl": 200.0}]
        d = _equity_curve_drawing(trades)
        assert isinstance(d, Drawing)


# ── generate_pdf_report: Monte Carlo exception handler (lines 411-412) ───────

class TestMonteCarloFallback:
    """Cover the except block that gracefully skips Monte Carlo."""

    def test_skips_monte_carlo_on_exception(self, tmp_path):
        from unittest.mock import patch
        db = tmp_path / "trades.db"
        _make_trades_db(db, n=20)
        with patch('core.monte_carlo.run_simulation',
                   side_effect=ValueError("simulation error")):
            result = generate_pdf_report(
                str(db), days=0, mode="ALL",
                cfg={"report_output_dir": str(tmp_path)},
                output_path=tmp_path / "mc_exc.pdf",
            )
        assert Path(result).is_file()


# ── generate_pdf_report: benchmark with entry_ts & non-None bm (423-493) ─────

class TestBenchmarkFull:
    """Cover benchmark timestamp extraction (423-424) and table rendering (464-493)."""

    def test_benchmark_with_timestamps_and_data(self, tmp_path):
        from types import SimpleNamespace
        from unittest.mock import patch
        db = tmp_path / "trades.db"
        _make_trades_db(db, n=5)

        # Build trades that have entry_ts so _ts_list is non-empty
        from core.performance_metrics import load_trades
        trades = load_trades(str(db))
        base = datetime.datetime(2026, 1, 2, 10, 30, 0)
        for i, t in enumerate(trades):
            t["entry_ts"] = (base + datetime.timedelta(days=i)).timestamp()

        mock_bm = SimpleNamespace(
            total_return_pct=5.0, max_drawdown_pct=-2.0,
            annualized_return_pct=8.0, sharpe_ratio=0.5,
            volatility_pct=10.0, data_source="yahoo")
        mock_alpha = SimpleNamespace(
            alpha_pct=2.0, information_ratio=0.3, drawdown_ratio=1.5)

        with patch('core.performance_metrics.load_trades', return_value=trades):
            with patch('core.benchmark.fetch_benchmark', return_value=mock_bm):
                with patch('core.benchmark.compute_alpha_metrics',
                           return_value=mock_alpha):
                    result = generate_pdf_report(
                        str(db), days=0, mode="ALL",
                        cfg={"report_output_dir": str(tmp_path)},
                        output_path=tmp_path / "bench.pdf")
        assert Path(result).is_file()

    def test_benchmark_exception_skipped_gracefully(self, tmp_path):
        """Cover the except block that catches benchmark failures (lines 492-493)."""
        from unittest.mock import patch
        db = tmp_path / "trades.db"
        _make_trades_db(db, n=5)
        with patch('core.benchmark.fetch_benchmark',
                   side_effect=ValueError("benchmark fetch failed")):
            result = generate_pdf_report(
                str(db), days=0, mode="ALL",
                cfg={"report_output_dir": str(tmp_path)},
                output_path=tmp_path / "bench_exc.pdf",
            )
        assert Path(result).is_file()


# ── CLI entry point ──────────────────────────────────────────────────────────

class TestCli:
    """Cover the _cli() function (511-518) and __name__ == '__main__' (522)."""

    def test_cli_via_function(self, tmp_path):
        db = tmp_path / "trades.db"
        _make_trades_db(db, n=5)
        out = tmp_path / "cli_report.pdf"
        from unittest.mock import patch
        with patch('sys.argv', ["prog", "--db", str(db), "--days", "0",
                                 "--mode", "ALL", "--out", str(out)]):
            from core.report_generator import _cli
            _cli()
        assert out.is_file()

    def test_cli_via_main_block(self, tmp_path):
        import runpy
        db = tmp_path / "trades.db"
        _make_trades_db(db, n=5)
        out = tmp_path / "main_report.pdf"
        from unittest.mock import patch
        with patch('sys.argv', ["prog", "--db", str(db), "--days", "0",
                                 "--mode", "ALL", "--out", str(out)]):
            runpy.run_module('core.report_generator', run_name='__main__')
        assert out.is_file()
