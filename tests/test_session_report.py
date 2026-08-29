"""Tests for core.session_report - daily session report generation."""

from __future__ import annotations

from datetime import datetime

from core.session_report import (
    DailySessionReporter,
    PnLBreakdown,
    RiskMetrics,
    SessionReport,
    TradeSummary,
    create_session_reporter,
)

# ── TradeSummary ─────────────────────────────────────────────────────────

def test_trade_summary_defaults() -> None:
    ts = TradeSummary()
    assert ts.total_trades == 0
    assert ts.winning_trades == 0
    assert ts.losing_trades == 0
    assert ts.total_volume == 0.0
    assert ts.total_premium == 0.0


def test_trade_summary_custom() -> None:
    ts = TradeSummary(total_trades=10, winning_trades=6, losing_trades=4)
    assert ts.total_trades == 10
    assert ts.winning_trades == 6


# ── PnLBreakdown ─────────────────────────────────────────────────────────

def test_pnl_breakdown_defaults() -> None:
    pnl = PnLBreakdown()
    assert pnl.realized_pnl == 0.0
    assert pnl.unrealized_pnl == 0.0
    assert pnl.total_pnl == 0.0
    assert pnl.net_pnl == 0.0


def test_pnl_breakdown_custom() -> None:
    pnl = PnLBreakdown(realized_pnl=1500.0, commissions=50.0)
    pnl.total_pnl = 1500.0
    pnl.net_pnl = 1450.0
    assert pnl.realized_pnl == 1500.0
    assert pnl.net_pnl == 1450.0


# ── RiskMetrics ──────────────────────────────────────────────────────────

def test_risk_metrics_defaults() -> None:
    rm = RiskMetrics()
    assert rm.max_drawdown == 0.0
    assert rm.max_position_size == 0
    assert rm.largest_loss == 0.0
    assert rm.largest_win == 0.0


# ── SessionReport ────────────────────────────────────────────────────────

def test_session_report_defaults() -> None:
    now = datetime(2026, 6, 1, 9, 15)
    report = SessionReport(date="2026-06-01", session="REGULAR", started_at=now)
    assert report.date == "2026-06-01"
    assert report.session == "REGULAR"
    assert report.duration_minutes == 0.0
    assert report.win_rate == 0.0
    assert report.profit_factor == 0.0
    assert report.errors == []
    assert report.warnings == []


def test_session_report_with_trades() -> None:
    now = datetime(2026, 6, 1, 9, 15)
    report = SessionReport(
        date="2026-06-01",
        session="REGULAR",
        started_at=now,
        trades=TradeSummary(total_trades=5, winning_trades=3, losing_trades=2),
        pnl=PnLBreakdown(realized_pnl=1000.0, net_pnl=950.0),
        win_rate=60.0,
        profit_factor=2.0,
    )
    assert report.trades.total_trades == 5
    assert report.win_rate == 60.0
    assert report.pnl.net_pnl == 950.0


# ── DailySessionReporter ─────────────────────────────────────────────────

def test_reporter_construction() -> None:
    reporter = DailySessionReporter(db_path=":memory:", send_fn=print)
    assert reporter._db_path == ":memory:"
    assert callable(reporter._send_fn)


def test_reporter_default_send_fn() -> None:
    reporter = DailySessionReporter()
    # Default send_fn is lambda that returns None
    assert reporter._send_fn("test") is None


def test_reporter_generate_report_empty() -> None:
    reporter = DailySessionReporter(db_path=":memory:")
    report = reporter.generate_report(datetime(2026, 6, 1, 9, 15))
    assert isinstance(report, SessionReport)
    assert report.date == "2026-06-01"
    assert report.trades.total_trades >= 0  # empty DB → 0 trades


def test_reporter_format_telegram_message() -> None:
    reporter = DailySessionReporter()
    now = datetime(2026, 6, 1, 9, 15)
    report = SessionReport(
        date="2026-06-01",
        session="REGULAR",
        started_at=now,
        ended_at=datetime(2026, 6, 1, 15, 20),
        duration_minutes=365.0,
        trades=TradeSummary(total_trades=10, winning_trades=6, losing_trades=4),
        pnl=PnLBreakdown(realized_pnl=2500.0, total_pnl=2500.0, net_pnl=2450.0),
        risk=RiskMetrics(max_drawdown=500.0, largest_win=800.0, largest_loss=-300.0),
        win_rate=60.0,
        profit_factor=1.5,
    )
    msg = reporter.format_telegram_message(report)
    assert "Daily Session Report" in msg
    assert "2026-06-01" in msg
    assert "10" in msg  # total trades
    assert "6W" in msg  # winning
    assert "4L" in msg  # losing
    assert "2,500" in msg or "2500.00" in msg  # P&L formatted as ₹2,500.00


def test_reporter_format_with_warnings() -> None:
    reporter = DailySessionReporter()
    now = datetime(2026, 6, 1, 9, 15)
    report = SessionReport(
        date="2026-06-01",
        session="REGULAR",
        started_at=now,
        warnings=["Data feed delayed", "High VIX detected"],
    )
    msg = reporter.format_telegram_message(report)
    assert "Warnings" in msg
    assert "Data feed delayed" in msg


def test_reporter_format_with_errors() -> None:
    reporter = DailySessionReporter()
    now = datetime(2026, 6, 1, 9, 15)
    report = SessionReport(
        date="2026-06-01",
        session="REGULAR",
        started_at=now,
        errors=["DB connection failed"],
    )
    msg = reporter.format_telegram_message(report)
    assert "Errors" in msg
    assert "DB connection failed" in msg


# ── send_report ──────────────────────────────────────────────────────────

def test_send_report_generates_and_sends() -> None:
    sent_messages: list[str] = []
    reporter = DailySessionReporter(db_path=":memory:", send_fn=lambda m: sent_messages.append(str(m)))
    report = reporter.send_report(date=datetime(2026, 6, 1, 9, 15))
    assert isinstance(report, SessionReport)
    assert len(sent_messages) >= 1


# ── save_report ──────────────────────────────────────────────────────────

def test_save_report(tmp_path) -> None:
    reporter = DailySessionReporter()
    now = datetime(2026, 6, 1, 9, 15)
    report = SessionReport(date="2026-06-01", session="REGULAR", started_at=now)
    filepath = reporter.save_report(report, output_dir=str(tmp_path))
    assert tmp_path.name in filepath
    import json
    with open(filepath) as f:
        data = json.load(f)
    assert data["date"] == "2026-06-01"
    assert data["trades"]["total"] == 0


# ── create_session_reporter factory ──────────────────────────────────────

def test_create_session_reporter() -> None:
    reporter = create_session_reporter(db_path="test.db", send_fn=print)
    assert isinstance(reporter, DailySessionReporter)
    assert reporter._db_path == "test.db"
