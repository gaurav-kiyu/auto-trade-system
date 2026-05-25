"""
Daily Session Report (Phase 3).

Generates end-of-day trading summary with:
- P&L breakdown
- Trade statistics
- Risk metrics
- Performance indicators
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from datetime import time as dt_time
from typing import Any

from core.datetime_ist import now_ist

log = logging.getLogger(__name__)


@dataclass
class TradeSummary:
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    total_volume: float = 0.0
    total_premium: float = 0.0


@dataclass
class PnLBreakdown:
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    total_pnl: float = 0.0
    commissions: float = 0.0
    net_pnl: float = 0.0


@dataclass
class RiskMetrics:
    max_drawdown: float = 0.0
    max_position_size: int = 0
    largest_loss: float = 0.0
    largest_win: float = 0.0


@dataclass
class SessionReport:
    date: str
    session: str
    started_at: datetime
    ended_at: datetime | None = None
    duration_minutes: float = 0.0
    trades: TradeSummary = field(default_factory=TradeSummary)
    pnl: PnLBreakdown = field(default_factory=PnLBreakdown)
    risk: RiskMetrics = field(default_factory=RiskMetrics)
    win_rate: float = 0.0
    profit_factor: float = 0.0
    sharpe_ratio: float = 0.0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class DailySessionReporter:
    """
    Generates end-of-day session reports.

    Runs at:
    - 3:30 PM IST (pre-market close)
    - Manual trigger via CLI
    """

    REPORT_TIME = dt_time(15, 30)
    REPORT_FILE_PREFIX = "session_report"

    def __init__(
        self,
        db_path: str = "trades.db",
        send_fn: Any = None,
    ):
        self._db_path = db_path
        self._send_fn = send_fn or (lambda x: None)

    def generate_report(self, date: datetime | None = None) -> SessionReport:
        """Generate session report for given date."""
        if date is None:
            date = now_ist()

        date_str = date.strftime("%Y-%m-%d")
        report = SessionReport(
            date=date_str,
            session="REGULAR",
            started_at=date.replace(hour=9, minute=15),
        )

        try:
            self._load_trade_data(report, date_str)
            self._calculate_pnl(report, date_str)
            self._calculate_risk_metrics(report)
            self._calculate_performance(report)
            report.ended_at = now_ist()
            report.duration_minutes = (report.ended_at - report.started_at).total_seconds() / 60
        except Exception as e:
            log.error(f"Failed to generate session report: {e}")
            report.errors.append(str(e))

        return report

    def _load_trade_data(self, report: SessionReport, date_str: str) -> None:
        """Load trade data from database."""
        try:
            import sqlite3
            conn = sqlite3.connect(self._db_path)
            conn.row_factory = sqlite3.Row

            cursor = conn.execute(
                """
                SELECT direction, qty, entry_price, exit_price, pnl
                FROM trades
                WHERE date(entry_time) = ?
                """,
                (date_str,)
            )

            trades = list(cursor.fetchall())
            conn.close()

            report.trades.total_trades = len(trades)

            for trade in trades:
                qty = int(trade["qty"])
                pnl = float(trade.get("pnl", 0) or 0)
                entry_price = float(trade["entry_price"] or 0)
                premium = entry_price * qty

                report.trades.total_volume += qty
                report.trades.total_premium += premium

                if pnl > 0:
                    report.trades.winning_trades += 1
                    if pnl > report.risk.largest_win:
                        report.risk.largest_win = pnl
                elif pnl < 0:
                    report.trades.losing_trades += 1
                    if pnl < report.risk.largest_loss:
                        report.risk.largest_loss = pnl

        except Exception as e:
            log.warning(f"Could not load trade data: {e}")
            report.warnings.append(f"Trade data unavailable: {e}")

    def _calculate_pnl(self, report: SessionReport, date_str: str) -> None:
        """Calculate P&L breakdown."""
        try:
            import sqlite3
            conn = sqlite3.connect(self._db_path)

            cursor = conn.execute(
                "SELECT SUM(pnl) as realized FROM trades WHERE date(entry_time) = ? AND status = 'CLOSED'",
                (date_str,)
            )
            row = cursor.fetchone()
            report.pnl.realized_pnl = float(row[0] or 0) if row else 0

            cursor = conn.execute(
                "SELECT SUM(pnl) as unrealized FROM trades WHERE date(entry_time) = ? AND status = 'OPEN'",
                (date_str,)
            )
            row = cursor.fetchone()
            report.pnl.unrealized_pnl = float(row[0] or 0) if row else 0

            conn.close()

            report.pnl.total_pnl = report.pnl.realized_pnl + report.pnl.unrealized_pnl
            report.pnl.net_pnl = report.pnl.total_pnl - report.pnl.commissions

        except Exception as e:
            log.warning(f"Could not calculate P&L: {e}")

    def _calculate_risk_metrics(self, report: SessionReport) -> None:
        """Calculate risk metrics."""
        report.risk.max_drawdown = abs(report.risk.largest_loss) if report.trades.losing_trades > 0 else 0

    def _calculate_performance(self, report: SessionReport) -> None:
        """Calculate performance indicators."""
        if report.trades.total_trades > 0:
            report.win_rate = (report.trades.winning_trades / report.trades.total_trades) * 100

        if report.trades.losing_trades > 0 and abs(report.risk.largest_loss) > 0:
            gross_profit = report.risk.largest_win * max(1, report.trades.winning_trades)
            gross_loss = abs(report.risk.largest_loss) * max(1, report.trades.losing_trades)
            report.profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0

    def format_telegram_message(self, report: SessionReport) -> str:
        """Format report as Telegram message."""
        lines = [
            f"📊 Daily Session Report - {report.date}",
            "=" * 40,
            f"⏱ Duration: {report.duration_minutes:.0f} min",
            "",
            f"📈 Trades: {report.trades.total_trades} ({report.trades.winning_trades}W / {report.trades.losing_trades}L)",
            f"   Win Rate: {report.win_rate:.1f}%",
            f"   Profit Factor: {report.profit_factor:.2f}",
            "",
            f"💰 P&L: ₹{report.pnl.total_pnl:,.2f}",
            f"   Realized: ₹{report.pnl.realized_pnl:,.2f}",
            f"   Unrealized: ₹{report.pnl.unrealized_pnl:,.2f}",
            "",
            f"⚠️ Risk: Max DD ₹{report.risk.max_drawdown:,.2f}",
            f"   Largest Win: ₹{report.risk.largest_win:,.2f}",
            f"   Largest Loss: ₹{report.risk.largest_loss:,.2f}",
        ]

        if report.warnings:
            lines.append("")
            lines.append("⚡ Warnings:")
            for w in report.warnings[:3]:
                lines.append(f"   - {w}")

        if report.errors:
            lines.append("")
            lines.append("❌ Errors:")
            for e in report.errors[:3]:
                lines.append(f"   - {e}")

        return "\n".join(lines)

    def send_report(self, report: SessionReport | None = None, date: datetime | None = None) -> SessionReport:
        """Generate and send report."""
        if report is None:
            report = self.generate_report(date)

        message = self.format_telegram_message(report)
        self._send_fn(message)

        return report

    def save_report(self, report: SessionReport, output_dir: str = "reports") -> str:
        """Save report to file."""
        import json
        from pathlib import Path

        output_path = Path(output_dir)
        output_path.mkdir(exist_ok=True)

        filename = output_path / f"{self.REPORT_FILE_PREFIX}_{report.date}.json"
        with open(filename, "w") as f:
            json.dump(
                {
                    "date": report.date,
                    "trades": {
                        "total": report.trades.total_trades,
                        "winning": report.trades.winning_trades,
                        "losing": report.trades.losing_trades,
                    },
                    "pnl": {
                        "realized": report.pnl.realized_pnl,
                        "unrealized": report.pnl.unrealized_pnl,
                        "total": report.pnl.total_pnl,
                    },
                    "metrics": {
                        "win_rate": report.win_rate,
                        "profit_factor": report.profit_factor,
                        "max_drawdown": report.risk.max_drawdown,
                    },
                },
                f,
                indent=2,
            )

        return str(filename)


def create_session_reporter(
    db_path: str = "trades.db",
    send_fn: Any = None,
) -> DailySessionReporter:
    """Factory function to create session reporter."""
    return DailySessionReporter(db_path=db_path, send_fn=send_fn)
