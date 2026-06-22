"""
FinOps & Cost Governance Module (Phase 27).

Tracks and analyzes all costs associated with trading operations:
  - Brokerage fees (per trade/per lot)
  - STT (Securities Transaction Tax)
  - GST on brokerage
  - Stamp duty
  - SEBI turnover fees
  - Exchange transaction charges
  - Infrastructure costs (API subscriptions, data feeds)
  - Cumulative cost analysis
  - Budget alerts with notification callback
  - Cost trend analysis (period-over-period)
  - Prometheus metric exposure via callback

Usage
-----
    from core.finops import CostGovernance

    cg = CostGovernance(cfg)
    report = cg.analyze_costs(db_path="trades.db")
    print(report.summary())

Config keys (all optional — safe defaults built in)
---------------------------------------------------
    finops_brokerage_per_lot      : float  default 20.0   (brokerage per lot)
    finops_brokerage_pct          : float  default 0.0003  (brokerage as % of turnover)
    finops_stt_pct                : float  default 0.0005  (STT as % of turnover)
    finops_gst_pct                : float  default 0.18    (GST on brokerage)
    finops_stamp_duty_pct         : float  default 0.00003 (stamp duty as %)
    finops_sebi_turnover_fee_pct  : float  default 0.000001 (SEBI turnover fee)
    finops_exchange_charges_pct   : float  default 0.00053 (exchange transaction charges)
    finops_report_days            : int    default 30     (lookback for cost analysis)
    finops_mode                   : str   default "ALL"   (filter by mode: PAPER, LIVE, SIGNAL_ONLY, ALL)
    finops_ignore_mode            : bool  default False   (if True, ignore mode filter)
    finops_budget_alert_enabled   : bool  default False   (enable budget alerts)
    finops_budget_monthly_total   : float default 5000.0  (monthly cost budget before alert)
    finops_budget_pct_warn        : float default 80.0    (% of budget that triggers WARN)
    finops_trend_periods          : int   default 3       (periods for trend comparison)
    finops_alert_callback         : callable or None       (notification callback)"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)

_DEFAULT_DB = "trades.db"


# ── Dataclasses ──────────────────────────────────────────────────────────────

@dataclass
class TradeCostBreakdown:
    """Detailed cost breakdown for a single trade or aggregate."""
    brokerage: float = 0.0
    stt: float = 0.0
    gst: float = 0.0
    stamp_duty: float = 0.0
    sebi_fee: float = 0.0
    exchange_charges: float = 0.0
    infrastructure: float = 0.0
    total: float = 0.0

    def to_dict(self) -> dict[str, float]:
        return {
            "brokerage": round(self.brokerage, 2),
            "stt": round(self.stt, 2),
            "gst": round(self.gst, 2),
            "stamp_duty": round(self.stamp_duty, 2),
            "sebi_fee": round(self.sebi_fee, 2),
            "exchange_charges": round(self.exchange_charges, 2),
            "infrastructure": round(self.infrastructure, 2),
            "total": round(self.total, 2),
        }


@dataclass
class CostReport:
    """Complete cost analysis report."""
    period_days: int = 30
    total_trades: int = 0
    total_turnover: float = 0.0
    total_pnl: float = 0.0
    total_costs: TradeCostBreakdown = field(default_factory=TradeCostBreakdown)
    cost_per_trade: TradeCostBreakdown = field(default_factory=TradeCostBreakdown)
    cost_pct_of_turnover: float = 0.0
    cost_pct_of_pnl: float = 0.0
    net_pnl_after_costs: float = 0.0
    status: str = "OK"
    warnings: list[str] = field(default_factory=list)
    # Budget alert fields (new)
    monthly_projected_cost: float = 0.0
    budget_usage_pct: float = 0.0
    budget_status: str = "OK"

    def summary(self) -> str:
        """Return a human-readable summary."""
        R = "Rs"
        lines = [
            "=" * 60,
            "  FinOps & Cost Governance Report",
            "=" * 60,
            f"  Period: Last {self.period_days} days",
            f"  Trades: {self.total_trades}",
            f"  Turnover: {R}{self.total_turnover:,.2f}",
            f"  Gross P&L: {R}{self.total_pnl:+,.2f}",
            f"",
            f"  Total Costs: {R}{self.total_costs.total:,.2f}",
            f"    Brokerage:      {R}{self.total_costs.brokerage:,.2f}",
            f"    STT:            {R}{self.total_costs.stt:,.2f}",
            f"    GST:            {R}{self.total_costs.gst:,.2f}",
            f"    Stamp Duty:     {R}{self.total_costs.stamp_duty:,.2f}",
            f"    SEBI Fee:       {R}{self.total_costs.sebi_fee:,.2f}",
            f"    Exchange Chg:   {R}{self.total_costs.exchange_charges:,.2f}",
            f"    Infrastructure: {R}{self.total_costs.infrastructure:,.2f}",
            f"",
            f"  Cost Metrics:",
            f"    Cost per trade:     {R}{self.cost_per_trade.total:,.2f}",
            f"    Cost as % of turnover: {self.cost_pct_of_turnover:.4f}%",
            f"    Cost as % of P&L:     {self.cost_pct_of_pnl:.2f}%",
            f"    Net P&L after costs:  {R}{self.net_pnl_after_costs:+,.2f}",
        ]
        if self.warnings:
            lines.append("")
            lines.append("  Warnings:")
            for w in self.warnings:
                lines.append(f"    [X] {w}")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "period_days": self.period_days,
            "total_trades": self.total_trades,
            "total_turnover": round(self.total_turnover, 2),
            "total_pnl": round(self.total_pnl, 2),
            "total_costs": self.total_costs.to_dict(),
            "cost_per_trade": self.cost_per_trade.to_dict(),
            "cost_pct_of_turnover": round(self.cost_pct_of_turnover, 4),
            "cost_pct_of_pnl": round(self.cost_pct_of_pnl, 2),
            "net_pnl_after_costs": round(self.net_pnl_after_costs, 2),
            "status": self.status,
            "warnings": self.warnings[:10],
        }


# ── Cost Governance Engine ───────────────────────────────────────────────────

class CostGovernance:
    """Tracks and analyzes all trading costs for FinOps governance."""

    def __init__(self, cfg: dict[str, Any] | None = None):
        self._cfg = cfg or {}
        self._brokerage_per_lot = float(self._cfg.get("finops_brokerage_per_lot", 20.0))
        self._brokerage_pct = float(self._cfg.get("finops_brokerage_pct", 0.0003))
        self._stt_pct = float(self._cfg.get("finops_stt_pct", 0.0005))
        self._gst_pct = float(self._cfg.get("finops_gst_pct", 0.18))
        self._stamp_duty_pct = float(self._cfg.get("finops_stamp_duty_pct", 0.00003))
        self._sebi_fee_pct = float(self._cfg.get("finops_sebi_turnover_fee_pct", 0.000001))
        self._exchange_charges_pct = float(self._cfg.get("finops_exchange_charges_pct", 0.00053))
        self._infrastructure_monthly = float(self._cfg.get("finops_infrastructure_monthly", 500.0))
        self._mode = str(self._cfg.get("finops_mode", "ALL")).upper()
        self._ignore_mode = bool(self._cfg.get("finops_ignore_mode", False))

        # Budget alerts (new)
        self._budget_enabled = bool(self._cfg.get("finops_budget_alert_enabled", False))
        self._budget_monthly = float(self._cfg.get("finops_budget_monthly_total", 5000.0))
        self._budget_warn_pct = float(self._cfg.get("finops_budget_pct_warn", 80.0))
        self._alert_callback = self._cfg.get("finops_alert_callback", None)
        self._trend_periods = int(self._cfg.get("finops_trend_periods", 3))

    @property
    def report_days(self) -> int:
        return int(self._cfg.get("finops_report_days", 30))

    def compute_trade_costs(self, trade_value: float, lots: int = 1) -> TradeCostBreakdown:
        """Compute all costs for a single trade of given value."""
        costs = TradeCostBreakdown()

        # Brokerage (per-lot or percentage)
        if self._brokerage_per_lot > 0:
            costs.brokerage = self._brokerage_per_lot * lots
        elif self._brokerage_pct > 0:
            costs.brokerage = trade_value * self._brokerage_pct

        # STT
        costs.stt = trade_value * self._stt_pct

        # GST on brokerage
        costs.gst = costs.brokerage * self._gst_pct

        # Stamp duty
        costs.stamp_duty = trade_value * self._stamp_duty_pct

        # SEBI turnover fee
        costs.sebi_fee = trade_value * self._sebi_fee_pct

        # Exchange charges
        costs.exchange_charges = trade_value * self._exchange_charges_pct

        costs.total = sum([
            costs.brokerage, costs.stt, costs.gst,
            costs.stamp_duty, costs.sebi_fee, costs.exchange_charges,
        ])
        return costs

    def analyze_costs(self, db_path: str = _DEFAULT_DB) -> CostReport:
        """Analyze all costs from trade data."""
        report = CostReport(period_days=self.report_days)
        p = Path(db_path)

        if not p.is_file():
            report.status = "NO_DATA"
            report.warnings.append(f"Trades DB not found: {db_path}")
            return report

        try:
            from core.db_utils import get_connection
            conn = get_connection(str(p), timeout=5, row_factory=False)
            try:
                # Load trades from past N days, optionally filtered by mode
                if self._ignore_mode or self._mode == "ALL":
                    rows = conn.execute(
                        "SELECT entry_price, quantity, net_pnl, ts FROM trades "
                        "WHERE ts >= datetime('now', ?) AND net_pnl IS NOT NULL "
                        "ORDER BY ts",
                        (f"-{self.report_days} days",),
                    ).fetchall()
                else:
                    # Check if mode column exists
                    has_mode = False
                    try:
                        conn.execute("SELECT mode FROM trades LIMIT 0")
                        has_mode = True
                    except Exception:
                        pass

                    if has_mode:
                        rows = conn.execute(
                            "SELECT entry_price, quantity, net_pnl, ts FROM trades "
                            "WHERE ts >= datetime('now', ?) AND net_pnl IS NOT NULL "
                            "AND UPPER(mode) = ? "
                            "ORDER BY ts",
                            (f"-{self.report_days} days", self._mode),
                        ).fetchall()
                    else:
                        report.warnings.append(
                            f"No mode column in trades DB — cannot filter by mode={self._mode}"
                        )
                        rows = conn.execute(
                            "SELECT entry_price, quantity, net_pnl, ts FROM trades "
                            "WHERE ts >= datetime('now', ?) AND net_pnl IS NOT NULL "
                            "ORDER BY ts",
                            (f"-{self.report_days} days",),
                        ).fetchall()
            finally:
                conn.close()

            # Add mode filter info to report
            if self._mode != "ALL" and not self._ignore_mode:
                report.warnings.insert(0, f"Filtered to {self._mode} mode only")
        except Exception as exc:
            report.status = "ERROR"
            report.warnings.append(f"DB error: {exc}")
            return report

        if not rows:
            report.status = "NO_DATA"
            report.warnings.append(f"No trades in last {self.report_days} days")
            return report

        total_turnover = 0.0
        total_pnl = 0.0
        total_costs = TradeCostBreakdown()
        n_trades = len(rows)

        for row in rows:
            entry_price = float(row[0]) if row[0] else 0.0
            quantity = int(row[1]) if row[1] else 0
            net_pnl = float(row[2]) if row[2] else 0.0

            trade_value = entry_price * abs(quantity)
            total_turnover += trade_value
            total_pnl += net_pnl

            # Estimate lots (assume lot_size from config or default 50)
            lot_size = int(self._cfg.get("lot_size", 50))
            lots = max(1, abs(quantity) // lot_size)

            costs = self.compute_trade_costs(trade_value, lots)
            total_costs.brokerage += costs.brokerage
            total_costs.stt += costs.stt
            total_costs.gst += costs.gst
            total_costs.stamp_duty += costs.stamp_duty
            total_costs.sebi_fee += costs.sebi_fee
            total_costs.exchange_charges += costs.exchange_charges

        total_costs.total = sum([
            total_costs.brokerage, total_costs.stt, total_costs.gst,
            total_costs.stamp_duty, total_costs.sebi_fee,
            total_costs.exchange_charges,
        ])

        # Add infrastructure cost (monthly, pro-rated to report period)
        infra_pro_rata = self._infrastructure_monthly * (self.report_days / 30.0)
        total_costs.infrastructure = infra_pro_rata
        total_costs.total += infra_pro_rata

        report.total_trades = n_trades
        report.total_turnover = total_turnover
        report.total_pnl = total_pnl
        report.total_costs = total_costs

        # Per-trade averages
        if n_trades > 0:
            report.cost_per_trade.brokerage = total_costs.brokerage / n_trades
            report.cost_per_trade.stt = total_costs.stt / n_trades
            report.cost_per_trade.gst = total_costs.gst / n_trades
            report.cost_per_trade.stamp_duty = total_costs.stamp_duty / n_trades
            report.cost_per_trade.sebi_fee = total_costs.sebi_fee / n_trades
            report.cost_per_trade.exchange_charges = total_costs.exchange_charges / n_trades
            report.cost_per_trade.infrastructure = infra_pro_rata / n_trades
            report.cost_per_trade.total = total_costs.total / n_trades

        # Cost as percentage of turnover
        if total_turnover > 0:
            report.cost_pct_of_turnover = (total_costs.total / total_turnover) * 100

        # Cost as percentage of P&L
        if total_pnl > 0:
            report.cost_pct_of_pnl = (total_costs.total / total_pnl) * 100
        elif total_pnl < 0:
            # If losing, costs amplify the loss
            report.cost_pct_of_pnl = abs(total_costs.total / total_pnl) * 100
            if total_costs.total > abs(total_pnl):
                report.warnings.append(
                    f"Costs ({total_costs.total:.2f}) exceed P&L ({total_pnl:.2f})!"
                )

        report.net_pnl_after_costs = total_pnl - total_costs.total

        # Generate warnings
        if report.cost_pct_of_turnover > 0.5:
            report.warnings.append(
                f"Cost-to-turnover ratio {report.cost_pct_of_turnover:.2f}% is high"
            )
        if report.cost_pct_of_pnl > 30 and total_pnl > 0:
            report.warnings.append(
                f"Costs consume {report.cost_pct_of_pnl:.1f}% of gross P&L"
            )
        if total_costs.brokerage > total_costs.stt * 2:
            report.warnings.append(
                "Brokerage exceeds STT — consider flat-fee broker plan"
            )

        # ── Budget alerts (new) ──────────────────────────────────────────────
        if self._budget_enabled:
            self._check_budget_alerts(report)
        # ──────────────────────────────────────────────────────────────────────

        return report

    # ── Budget Alert Methods (new) ────────────────────────────────────────────

    def _check_budget_alerts(self, report: CostReport) -> None:
        """Check cost report against configured budget thresholds."""
        monthly_total = report.total_costs.total
        monthly_projected = monthly_total * (30.0 / max(report.period_days, 1))

        usage_pct = (monthly_projected / self._budget_monthly) * 100
        report.monthly_projected_cost = round(monthly_projected, 2)
        report.budget_usage_pct = round(usage_pct, 1)

        if usage_pct >= 100:
            report.budget_status = "EXCEEDED"
            msg = (
                f"[FINOPS] Budget EXCEEDED: projected monthly cost Rs{monthly_projected:,.0f} "
                f"exceeds budget Rs{self._budget_monthly:,.0f} ({usage_pct:.0f}%)"
            )
            report.warnings.append(msg)
            self._fire_alert(msg, "CRITICAL")
        elif usage_pct >= self._budget_warn_pct:
            report.budget_status = "WARN"
            msg = (
                f"[FINOPS] Budget WARNING: projected monthly cost Rs{monthly_projected:,.0f} "
                f"is {usage_pct:.0f}% of budget Rs{self._budget_monthly:,.0f}"
            )
            report.warnings.append(msg)
            self._fire_alert(msg, "WARN")
        else:
            report.budget_status = "OK"

    def _fire_alert(self, message: str, severity: str = "WARN") -> None:
        """Deliver budget alert via configured callback."""
        _log.log(logging.WARNING if severity == "WARN" else logging.ERROR, "%s", message)
        if self._alert_callback is not None:
            try:
                self._alert_callback(message, severity)
            except Exception as exc:
                _log.warning("[FINOPs] Alert callback failed: %s", exc)

    # ── Cost Trend Analysis (new) ────────────────────────────────────────────

    def analyze_cost_trends(self, db_path: str = _DEFAULT_DB) -> dict[str, Any]:
        """Analyze cost trends over multiple periods.

        Returns a dict with period-by-period cost breakdown and trend direction.
        """
        periods: list[dict[str, Any]] = []
        base_days = self.report_days

        for i in range(self._trend_periods):
            period_cfg = dict(self._cfg)
            period_cfg["finops_report_days"] = base_days * (i + 1)
            cg = CostGovernance(period_cfg)
            report = cg.analyze_costs(db_path=db_path)
            periods.append({
                "period_days": report.period_days,
                "label": f"last_{base_days * (i + 1)}d",
                "total_costs": report.total_costs.total,
                "total_trades": report.total_trades,
                "cost_per_trade": report.cost_per_trade.total,
                "cost_pct_of_turnover": report.cost_pct_of_turnover,
                "cost_pct_of_pnl": report.cost_pct_of_pnl,
                "status": report.status,
            })

        # Determine trend direction
        trend = "stable"
        if len(periods) >= 2:
            costs = [p["total_costs"] for p in periods if p["total_costs"] > 0]
            if len(costs) >= 2:
                if costs[-1] > costs[0] * 1.1:
                    trend = "increasing"
                elif costs[-1] < costs[0] * 0.9:
                    trend = "decreasing"

        return {
            "periods": periods,
            "trend": trend,
            "budget_monthly": self._budget_monthly if self._budget_enabled else None,
        }

    def get_prometheus_metrics(self, db_path: str = _DEFAULT_DB) -> dict[str, float]:
        """Export key cost metrics for Prometheus collection.

        Returns a flat dict of metric_name → value suitable for
        the Prometheus metrics exporter.
        """
        report = self.analyze_costs(db_path=db_path)
        return {
            "finops_total_costs": report.total_costs.total,
            "finops_cost_per_trade": report.cost_per_trade.total,
            "finops_cost_pct_turnover": report.cost_pct_of_turnover,
            "finops_net_pnl_after_costs": report.net_pnl_after_costs,
            "finops_brokerage": report.total_costs.brokerage,
            "finops_stt": report.total_costs.stt,
            "finops_monthly_projected": getattr(report, "monthly_projected_cost", 0.0),
            "finops_budget_usage_pct": getattr(report, "budget_usage_pct", 0.0),
        }


# ── CLI ──────────────────────────────────────────────────────────────────────

def _cli() -> None:
    import argparse
    ap = argparse.ArgumentParser(prog="python -m core.finops")
    ap.add_argument("--db", default=_DEFAULT_DB, help="Trades DB path")
    ap.add_argument("--days", type=int, default=0, help="Lookback days")
    ap.add_argument("--json", action="store_true", help="Output JSON")
    ap.add_argument("--mode", type=str, default="", help="Filter by execution mode (PAPER, LIVE, etc.)")
    args = ap.parse_args()

    cfg = {}
    if args.days > 0:
        cfg["finops_report_days"] = args.days
    if args.mode:
        cfg["finops_mode"] = args.mode.upper()

    cg = CostGovernance(cfg)
    report = cg.analyze_costs(db_path=args.db)

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(report.summary())


if __name__ == "__main__":
    _cli()
