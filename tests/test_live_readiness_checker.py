"""
Tests for core/live_readiness_checker.py - Paper Trading Scorecard.

Covers:
  - CriterionResult and ReadinessReport dataclasses
  - _count_trading_days
  - _compute_drawdown from cumulative P&L
  - check_live_readiness with mocked _load_paper_trades
  - format_readiness_report output
  - should_send_today / mark_sent_today flag management
  - CriterionResult.status property
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch


from core.live_readiness_checker import (
    CriterionResult,
    ReadinessReport,
    _compute_drawdown,
    _count_trading_days,
    _load_paper_trades,
    check_live_readiness,
    format_readiness_report,
    mark_sent_today,
    should_send_today,
)


# ── CriterionResult ─────────────────────────────────────────────────


class TestCriterionResult:
    def test_passing_blocking(self) -> None:
        c = CriterionResult(name="Test", passed=True, blocking=True, actual=50, required=50)
        assert c.status == "PASS"

    def test_failing_blocking(self) -> None:
        c = CriterionResult(name="Test", passed=False, blocking=True, actual=30, required=50)
        assert c.status == "FAIL"

    def test_failing_non_blocking(self) -> None:
        c = CriterionResult(name="Test", passed=False, blocking=False, actual=0.2, required=0.5)
        assert c.status == "WARN"


# ── ReadinessReport ─────────────────────────────────────────────────


class TestReadinessReport:
    def test_ready(self) -> None:
        report = ReadinessReport(
            overall_ready=True, blocking_score=5, readiness_score=0.9,
            criteria=[CriterionResult("T", True, True, 50, 50)],
        )
        assert report.overall_ready
        assert len(report.blocking_criteria) == 1

    def test_not_ready(self) -> None:
        report = ReadinessReport(
            overall_ready=False, blocking_score=2, readiness_score=0.4,
            criteria=[CriterionResult("T", False, True, 10, 50)],
        )
        assert not report.overall_ready

    def test_warning_criteria_separated(self) -> None:
        report = ReadinessReport(
            overall_ready=True, blocking_score=5, readiness_score=0.8,
            criteria=[
                CriterionResult("B1", True, True, 50, 50),
                CriterionResult("W1", True, False, 0.6, 0.5),
                CriterionResult("W2", False, False, 0.3, 0.5),
            ],
        )
        assert len(report.blocking_criteria) == 1
        assert len(report.warning_criteria) == 2


# ── _count_trading_days ─────────────────────────────────────────────


class TestCountTradingDays:
    def test_empty_list(self) -> None:
        assert _count_trading_days([]) == 0

    def test_single_day(self) -> None:
        trades = [{"ts": "2026-06-11T09:30:00"}]
        assert _count_trading_days(trades) == 1

    def test_multiple_days(self) -> None:
        trades = [
            {"ts": "2026-06-10T09:30:00"},
            {"ts": "2026-06-11T09:30:00"},
            {"ts": "2026-06-11T10:00:00"},  # Same day
        ]
        assert _count_trading_days(trades) == 2

    def test_missing_ts(self) -> None:
        trades: list[dict] = [{"ts": ""}, {"ts": "2026-06-11T09:30:00"}]
        assert _count_trading_days(trades) == 1


# ── _compute_drawdown ───────────────────────────────────────────────


class TestComputeDrawdown:
    def test_no_losses(self) -> None:
        assert _compute_drawdown([100, 200, 300]) == 0.0

    def test_simple_drawdown(self) -> None:
        dd = _compute_drawdown([100, -50, -30])
        # Cumulative: 100, 50, 20
        # Peak: 100
        # Max DD: (100-20)/100*100 = 80%
        assert round(dd, 1) == 80.0

    def test_recovery_reduces_dd(self) -> None:
        dd = _compute_drawdown([100, -50, 100])
        # Cumulative: 100, 50, 150
        # Peak: 150, Max DD from peak: recovered
        # Max DD from peak-to-trough: (100-50)/100 = 50%
        assert round(dd, 1) == 50.0

    def test_no_positive_peak(self) -> None:
        dd = _compute_drawdown([-50, -30])
        # Cumulative: -50, -80
        # Peak: 0 (never positive)
        assert dd == 0.0

    def test_large_drawdown(self) -> None:
        dd = _compute_drawdown([100, 50, -200, 100])
        # Cumulative: 100, 150, -50, 50
        # Peak: 150
        # Max DD from peak: (150-(-50))/150*100 = 133.33%
        assert round(dd, 2) == 133.33

    def test_empty_list(self) -> None:
        assert _compute_drawdown([]) == 0.0


# ── _load_paper_trades basic tests ──────────────────────────────────


class TestLoadPaperTrades:
    def test_missing_db(self) -> None:
        assert _load_paper_trades("nonexistent.db", 30) == []

    def test_empty_string_path(self) -> None:
        assert _load_paper_trades("", 30) == []


# ── check_live_readiness (with mocked trades) ───────────────────────


def _make_winning_trades(count: int, days: int = 10) -> list[dict]:
    """Create a list of winning trade dicts."""
    trades = []
    for i in range(count):
        day = 10 + (i // max(1, (count // max(days, 1))))
        trades.append({
            "mode": "PAPER",
            "net_pnl": 100.0,
            "ts": f"2026-06-{day:02d}T09:30:00",
        })
    return trades


class TestCheckLiveReadiness:
    def test_no_trades_returns_not_ready(self) -> None:
        with patch("core.live_readiness_checker._load_paper_trades", return_value=[]):
            report = check_live_readiness("dummy.db", cfg={
                "live_readiness_min_paper_trades": 50,
            })
        assert not report.overall_ready
        assert not report.blocking_criteria[0].passed  # min trades

    def test_ready_with_good_trades(self) -> None:
        trades = _make_winning_trades(100, days=20)
        with patch("core.live_readiness_checker._load_paper_trades", return_value=trades):
            report = check_live_readiness("dummy.db", cfg={
                "live_readiness_min_paper_trades": 50,
                "live_readiness_min_win_rate": 0.50,
                "live_readiness_min_profit_factor": 1.30,
                "live_readiness_max_drawdown_pct": 15.0,
                "live_readiness_min_trading_days": 10,
            })
        assert report.overall_ready

    def test_not_ready_insufficient_trades(self) -> None:
        trades = _make_winning_trades(5)
        with patch("core.live_readiness_checker._load_paper_trades", return_value=trades):
            report = check_live_readiness("dummy.db", cfg={
                "live_readiness_min_paper_trades": 50,
            })
        assert not report.overall_ready
        min_trades_criteria = [c for c in report.blocking_criteria if "paper trades" in c.name.lower()]
        assert len(min_trades_criteria) == 1
        assert not min_trades_criteria[0].passed
        assert min_trades_criteria[0].actual == 5

    def test_not_ready_low_win_rate(self) -> None:
        trades = _make_winning_trades(100)
        # Override 80 trades to be losses
        for i in range(80):
            trades[i]["net_pnl"] = -50.0
        with patch("core.live_readiness_checker._load_paper_trades", return_value=trades):
            report = check_live_readiness("dummy.db", cfg={
                "live_readiness_min_paper_trades": 50,
                "live_readiness_min_win_rate": 0.50,
            })
        assert not report.overall_ready
        wr_criteria = [c for c in report.blocking_criteria if "win rate" in c.name.lower()]
        assert len(wr_criteria) == 1
        assert not wr_criteria[0].passed

    def test_not_ready_high_drawdown(self) -> None:
        # Alternating wins and big losses = high drawdown
        trades = []
        for i in range(60):
            trades.append({
                "mode": "PAPER",
                "net_pnl": 100.0 if i % 2 == 0 else -500.0,
                "ts": f"2026-06-{11 + i // 6}T09:30",
            })
        with patch("core.live_readiness_checker._load_paper_trades", return_value=trades):
            report = check_live_readiness("dummy.db", cfg={
                "live_readiness_min_paper_trades": 50,
                "live_readiness_min_win_rate": 0.0,  # Don't fail on WR
                "live_readiness_min_profit_factor": 0.0,
                "live_readiness_max_drawdown_pct": 10.0,
                "live_readiness_min_trading_days": 3,
            })
        dd_criteria = [c for c in report.blocking_criteria if "drawdown" in c.name.lower()]
        assert len(dd_criteria) == 1
        assert not dd_criteria[0].passed

    def test_readiness_score_computed(self) -> None:
        trades = _make_winning_trades(100)
        with patch("core.live_readiness_checker._load_paper_trades", return_value=trades):
            report = check_live_readiness("dummy.db", cfg={
                "live_readiness_min_paper_trades": 50,
                "live_readiness_min_win_rate": 0.40,
                "live_readiness_min_profit_factor": 1.0,
                "live_readiness_max_drawdown_pct": 50.0,
                "live_readiness_min_trading_days": 5,
            })
        assert 0.0 <= report.readiness_score <= 1.0


# ── format_readiness_report ────────────────────────────────────────


class TestFormatReport:
    def test_contains_summary(self) -> None:
        report = ReadinessReport(
            overall_ready=False, blocking_score=0, readiness_score=0.0,
            criteria=[CriterionResult("Test", False, True, 0, 50)],
            summary="NOT READY",
            recommendation="Keep paper trading",
        )
        output = format_readiness_report(report)
        assert "NOT READY" in output
        assert "Blocking Criteria" in output
        assert "Test" in output

    def test_ready_format(self) -> None:
        report = ReadinessReport(
            overall_ready=True, blocking_score=5, readiness_score=0.9,
            criteria=[CriterionResult("Trades", True, True, 100, 50)],
            summary="READY FOR LIVE",
            recommendation="Ready to go",
        )
        output = format_readiness_report(report)
        assert "READY FOR LIVE" in output
        assert "Readiness score" in output

    def test_shows_all_criteria(self) -> None:
        report = ReadinessReport(
            overall_ready=False, blocking_score=0, readiness_score=0.3,
            criteria=[
                CriterionResult("B1", False, True, 0, 50, message="0 trades"),
                CriterionResult("W1", True, False, 0.6, 0.5, message="OK"),
            ],
            summary="Test",
            recommendation="Keep testing",
        )
        output = format_readiness_report(report)
        assert "Blocking Criteria" in output
        assert "Advisory Criteria" in output


# ── Flag File ───────────────────────────────────────────────────────


class TestFlagFile:
    def test_should_send_default(self, tmp_path: Path) -> None:
        assert should_send_today(str(tmp_path))

    def test_should_send_after_mark(self, tmp_path: Path) -> None:
        mark_sent_today(str(tmp_path))
        assert not should_send_today(str(tmp_path))

    def test_mark_creates_flag_file(self, tmp_path: Path) -> None:
        flag = tmp_path / ".live_readiness_notified"
        assert not flag.exists()
        mark_sent_today(str(tmp_path))
        assert flag.exists()

    def test_flag_contains_today_date(self, tmp_path: Path) -> None:
        import datetime
        mark_sent_today(str(tmp_path))
        flag = tmp_path / ".live_readiness_notified"
        content = flag.read_text().strip()
        assert content == datetime.date.today().isoformat()


# ── check_live_readiness defaults ───────────────────────────────────


class TestCheckLiveReadinessDefaults:
    def test_nonexistent_db_returns_not_ready(self) -> None:
        report = check_live_readiness("nonexistent_file.db", cfg={"live_readiness_min_paper_trades": 50})
        assert not report.overall_ready

    def test_default_config_used(self) -> None:
        """With no config, should use hard-coded defaults."""
        with patch("core.live_readiness_checker._load_paper_trades", return_value=[]):
            report = check_live_readiness("dummy.db")
        assert not report.overall_ready
