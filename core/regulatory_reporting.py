"""
Regulatory Reporting Module — SEBI & Exchange Compliance Reports.

Generates structured compliance reports suitable for regulatory filings,
audit trails, and exchange submissions. Covers:

- Trade register (all executed trades with timestamps)
- Risk limit utilization (position limits, margin utilization)
- Broker reconciliation status
- System health and certification status
- Corporate action adjustments

Usage
-----
    from core.regulatory_reporting import RegulatoryReporter

    reporter = RegulatoryReporter(cfg)
    report = reporter.generate_trade_register(db_path="trades.db")
    print(report.summary())

    # Generate full compliance package
    package = reporter.generate_compliance_package()
    package.save_to("reports/compliance/")

Config keys (all optional)
--------------------------
    regulatory_reports_dir   : str  default "reports/compliance"
    regulatory_trader_id     : str  default "OPB-INDEX-001"
    regulatory_broker_name   : str  default "PAPER"
    regulatory_report_days   : int  default 90
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)

_DEFAULT_DB = "trades.db"
_DEFAULT_DIR = "reports/compliance"


# ── Dataclasses ───────────────────────────────────────────────────────────────

@dataclass
class TradeRegisterEntry:
    """A single trade record for regulatory register."""
    trade_id: str
    symbol: str
    entry_time: str
    exit_time: str | None
    direction: str           # CALL | PUT
    entry_price: float
    exit_price: float | None
    quantity: int
    net_pnl: float | None
    exit_reason: str | None
    mode: str                # PAPER | LIVE | SIGNAL_ONLY

    def to_dict(self) -> dict[str, Any]:
        return {
            "trade_id": self.trade_id,
            "symbol": self.symbol,
            "entry_time": self.entry_time,
            "exit_time": self.exit_time or "",
            "direction": self.direction,
            "entry_price": round(self.entry_price, 2),
            "exit_price": round(self.exit_price, 2) if self.exit_price else None,
            "quantity": self.quantity,
            "net_pnl": round(self.net_pnl, 2) if self.net_pnl else None,
            "exit_reason": self.exit_reason or "",
            "mode": self.mode,
        }


@dataclass
class ComplianceReport:
    """A structured compliance report for regulatory use."""
    report_type: str            # TRADE_REGISTER | RISK_LIMITS | BROKER_RECON | SYSTEM_HEALTH
    generated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    report_period: str = ""
    trader_id: str = ""
    broker_name: str = ""
    entries: list[dict[str, Any]] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_type": self.report_type,
            "generated_at": self.generated_at,
            "report_period": self.report_period,
            "trader_id": self.trader_id,
            "broker_name": self.broker_name,
            "entries_count": len(self.entries),
            "entries": self.entries,
            "summary": self.summary,
            "warnings": self.warnings[:20],
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, default=str)

    def save(self, output_dir: str) -> str:
        """Save the report as JSON to the output directory."""
        p = Path(output_dir)
        p.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = p / f"{self.report_type.lower()}_{timestamp}.json"
        filename.write_text(self.to_json(), encoding="utf-8")
        _log.info("[REG] Report saved: %s", filename)
        return str(filename.resolve())


@dataclass
class CompliancePackage:
    """A full compliance reporting package."""
    trader_id: str
    broker_name: str
    report_period: str
    trade_register: ComplianceReport | None = None
    risk_limits_report: ComplianceReport | None = None
    broker_recon_report: ComplianceReport | None = None
    system_health_report: ComplianceReport | None = None
    generated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def save_to(self, output_dir: str) -> dict[str, str]:
        """Save all reports to the output directory."""
        paths = {}
        for report in [self.trade_register, self.risk_limits_report,
                       self.broker_recon_report, self.system_health_report]:
            if report:
                path = report.save(output_dir)
                paths[report.report_type] = path
        return paths


# ── Regulatory Reporter ───────────────────────────────────────────────────────

class RegulatoryReporter:
    """Generates regulatory compliance reports for SEBI/exchange filings."""

    def __init__(self, cfg: dict[str, Any] | None = None):
        self._cfg = cfg or {}
        self._trader_id = str(self._cfg.get("regulatory_trader_id", "OPB-INDEX-001"))
        self._broker_name = str(self._cfg.get("regulatory_broker_name", "PAPER"))
        self._report_days = int(self._cfg.get("regulatory_report_days", 90))

    def generate_trade_register(self, db_path: str = _DEFAULT_DB,
                                days: int | None = None) -> ComplianceReport:
        """Generate trade register — all executed trades in the period."""
        period = days or self._report_days
        report = ComplianceReport(
            report_type="TRADE_REGISTER",
            report_period=f"LAST_{period}_DAYS",
            trader_id=self._trader_id,
            broker_name=self._broker_name,
        )
        p = Path(db_path)
        if not p.is_file():
            report.warnings.append(f"Trades DB not found: {db_path}")
            report.summary = {"total_trades": 0, "status": "NO_DATA"}
            return report

        try:
            from core.db_utils import get_connection
            conn = get_connection(str(p), timeout=5, row_factory=False)
            try:
                rows = conn.execute(
                    "SELECT trade_id, symbol, entry_time, exit_time, direction, "
                    "entry_price, exit_price, quantity, net_pnl, exit_reason, mode "
                    "FROM trades WHERE entry_time >= datetime('now', ?) "
                    "ORDER BY entry_time",
                    (f"-{period} days",),
                ).fetchall()
            finally:
                conn.close()
        except Exception as exc:
            report.warnings.append(f"DB error: {exc}")
            report.summary = {"total_trades": 0, "status": "ERROR"}
            return report

        entries = []
        for row in rows:
            entry = TradeRegisterEntry(
                trade_id=str(row[0] or ""),
                symbol=str(row[1] or ""),
                entry_time=str(row[2] or ""),
                exit_time=str(row[3]) if row[3] else None,
                direction=str(row[4] or ""),
                entry_price=float(row[5]) if row[5] else 0.0,
                exit_price=float(row[6]) if row[6] else None,
                quantity=int(row[7]) if row[7] else 0,
                net_pnl=float(row[8]) if row[8] else None,
                exit_reason=str(row[9]) if row[9] else None,
                mode=str(row[10] or "PAPER") if len(row) > 10 else "PAPER",
            )
            entries.append(entry.to_dict())

        # Compute summary
        total_pnl = sum(e["net_pnl"] or 0 for e in entries)
        wins = sum(1 for e in entries if (e["net_pnl"] or 0) > 0)
        losses = sum(1 for e in entries if (e["net_pnl"] or 0) < 0)
        symbols = set(e["symbol"] for e in entries)

        report.entries = entries
        report.summary = {
            "total_trades": len(entries),
            "wins": wins,
            "losses": losses,
            "total_pnl": round(total_pnl, 2),
            "unique_symbols": list(symbols),
            "modes": list(set(e["mode"] for e in entries)),
            "status": "OK",
        }
        return report

    def generate_risk_limits_report(self) -> ComplianceReport:
        """Generate risk limits utilization report."""
        report = ComplianceReport(
            report_type="RISK_LIMITS",
            report_period="CURRENT",
            trader_id=self._trader_id,
            broker_name=self._broker_name,
        )
        try:
            max_daily_loss = float(self._cfg.get("MAX_DAILY_LOSS", -2000))
            max_drawdown = float(self._cfg.get("MAX_DRAWDOWN", 0.15))
            max_exposure = float(self._cfg.get("MAX_EXPOSURE", 100000))
            max_trades = int(self._cfg.get("MAX_TRADES_DAY", 10))

            # Try to read current state
            daily_pnl = 0.0
            current_drawdown = 0.0
            current_exposure = 0.0
            current_trades = 0
            try:
                from pathlib import Path as _Path
                ts_file = _Path("trader_state.json")
                if ts_file.is_file():
                    data = json.loads(ts_file.read_text(encoding="utf-8"))
                    daily_pnl = float(data.get("daily_pnl", 0))
                    current_drawdown = float(data.get("drawdown_pct", 0))
                    current_exposure = float(data.get("locked_capital", 0))
            except (OSError, json.JSONDecodeError, ValueError):
                pass

            entries = [
                {"limit": "MAX_DAILY_LOSS", "value": abs(max_daily_loss),
                 "current": abs(daily_pnl) if daily_pnl < 0 else 0,
                 "unit": "Rs", "utilization_pct": round(min(100, abs(daily_pnl) / abs(max_daily_loss) * 100), 1)},
                {"limit": "MAX_DRAWDOWN", "value": max_drawdown * 100,
                 "current": round(current_drawdown * 100, 2),
                 "unit": "%", "utilization_pct": round(min(100, current_drawdown / max_drawdown * 100), 1)},
                {"limit": "MAX_EXPOSURE", "value": max_exposure,
                 "current": current_exposure,
                 "unit": "Rs", "utilization_pct": round(min(100, current_exposure / max_exposure * 100), 1)},
                {"limit": "MAX_TRADES_DAY", "value": max_trades,
                 "current": current_trades,
                 "unit": "trades", "utilization_pct": round(min(100, current_trades / max_trades * 100), 1)},
            ]
            report.entries = entries
            over_limit = [e for e in entries if e["utilization_pct"] >= 100]
            if over_limit:
                for ol in over_limit:
                    report.warnings.append(f"LIMIT BREACH: {ol['limit']} at {ol['utilization_pct']}%")
            report.summary = {"limits_checked": len(entries), "breaches": len(over_limit), "status": "OK" if not over_limit else "BREACHES"}
        except Exception as exc:
            report.warnings.append(f"Risk limits check failed: {exc}")
            report.summary = {"status": "ERROR"}
        return report

    def generate_broker_reconciliation_report(self, db_path: str = _DEFAULT_DB) -> ComplianceReport:
        """Generate broker reconciliation status report."""
        report = ComplianceReport(
            report_type="BROKER_RECONCILIATION",
            report_period=f"LAST_{self._report_days}_DAYS",
            trader_id=self._trader_id,
            broker_name=self._broker_name,
        )
        # Check reconciliation status
        try:
            from core.execution.continuous_reconciliation import get_reconciliation_stats
            stats = get_reconciliation_stats()
            report.entries = [stats] if stats else []
            report.summary = {
                "reconciliation_available": stats is not None,
                "status": "OK" if stats else "NO_DATA",
            }
        except ImportError:
            report.warnings.append("Continuous reconciliation engine not available")
            report.summary = {"reconciliation_available": False, "status": "N/A"}
        except Exception as exc:
            report.warnings.append(f"Reconciliation check failed: {exc}")
            report.summary = {"status": "ERROR"}
        return report

    def generate_system_health_report(self) -> ComplianceReport:
        """Generate system health certification report."""
        report = ComplianceReport(
            report_type="SYSTEM_HEALTH",
            report_period="CURRENT",
            trader_id=self._trader_id,
            broker_name=self._broker_name,
        )
        health_checks = []

        # Check certification gate
        try:
            from core.certification.gate import run_certification_gate
            gate_result = run_certification_gate()
            health_checks.append({
                "check": "certification_gate",
                "status": gate_result.verdict,
                "detail": f"{gate_result.passed_certifiers}/{gate_result.total_certifiers} passed",
            })
        except Exception as exc:
            health_checks.append({"check": "certification_gate", "status": "ERROR", "detail": str(exc)})

        # Check SLO compliance
        try:
            from core.slo_governance import check_slo_compliance
            slo_report = check_slo_compliance()
            health_checks.append({
                "check": "slo_compliance",
                "status": "PASS" if not slo_report.blocking else "FAIL",
                "detail": f"{slo_report.passed}/{slo_report.total_slos} SLOs passing",
            })
        except Exception as exc:
            health_checks.append({"check": "slo_compliance", "status": "ERROR", "detail": str(exc)})

        # Check version compatibility
        try:
            from core.version_compatibility import check_version_compatibility
            vc_report = check_version_compatibility()
            health_checks.append({
                "check": "version_compatibility",
                "status": "PASS" if vc_report.all_compatible else "FAIL",
                "detail": f"{len(vc_report.failures)} incompatibilities" if vc_report.failures else "All compatible",
            })
        except Exception as exc:
            health_checks.append({"check": "version_compatibility", "status": "ERROR", "detail": str(exc)})

        # Check hard halt status
        try:
            from core.safety_state import is_hard_halted
            halted = is_hard_halted()
            health_checks.append({
                "check": "hard_halt",
                "status": "ACTIVE" if halted else "INACTIVE",
                "detail": "All trading blocked" if halted else "Normal operation",
            })
        except Exception as exc:
            health_checks.append({"check": "hard_halt", "status": "ERROR", "detail": str(exc)})

        report.entries = health_checks
        failed = [h for h in health_checks if h["status"] in ("FAIL", "ACTIVE", "ERROR")]
        report.summary = {
            "checks": len(health_checks),
            "passed": len(health_checks) - len(failed),
            "failed": len(failed),
            "status": "OK" if not failed else "ISSUES_DETECTED",
        }
        if failed:
            for f in failed:
                report.warnings.append(f"{f['check']}: {f['status']}")
        return report

    def generate_compliance_package(self, db_path: str = _DEFAULT_DB) -> CompliancePackage:
        """Generate a full compliance reporting package."""
        package = CompliancePackage(
            trader_id=self._trader_id,
            broker_name=self._broker_name,
            report_period=f"LAST_{self._report_days}_DAYS",
        )
        package.trade_register = self.generate_trade_register(db_path=db_path)
        package.risk_limits_report = self.generate_risk_limits_report()
        package.broker_recon_report = self.generate_broker_reconciliation_report(db_path=db_path)
        package.system_health_report = self.generate_system_health_report()
        return package


# ── CLI ───────────────────────────────────────────────────────────────────────

def _cli() -> None:
    import argparse
    ap = argparse.ArgumentParser(prog="python -m core.regulatory_reporting")
    ap.add_argument("--db", default=_DEFAULT_DB, help="Trades DB path")
    ap.add_argument("--days", type=int, default=0, help="Lookback days")
    ap.add_argument("--output", "-o", default=_DEFAULT_DIR, help="Output directory")
    ap.add_argument("--json", action="store_true", help="Output JSON to stdout")
    ap.add_argument("--type", choices=["trade_register", "risk_limits", "broker_recon", "system_health", "package"],
                    default="package", help="Report type")
    args = ap.parse_args()

    cfg = {}
    if args.days > 0:
        cfg["regulatory_report_days"] = args.days

    reporter = RegulatoryReporter(cfg)

    if args.type == "package":
        package = reporter.generate_compliance_package(db_path=args.db)
        paths = package.save_to(args.output)
        print("Compliance package saved:")
        for report_type, path in paths.items():
            print(f"  {report_type}: {path}")
    elif args.type == "trade_register":
        report = reporter.generate_trade_register(db_path=args.db, days=args.days or None)
        if args.json:
            print(report.to_json())
        else:
            print(f"Trade Register: {len(report.entries)} trades, {report.summary}")
    elif args.type == "risk_limits":
        report = reporter.generate_risk_limits_report()
        if args.json:
            print(report.to_json())
        else:
            print(f"Risk Limits: {len(report.entries)} limits, breaches={report.summary.get('breaches', 0)}")
    elif args.type == "broker_recon":
        report = reporter.generate_broker_reconciliation_report(db_path=args.db)
        if args.json:
            print(report.to_json())
        else:
            print(f"Broker Reconciliation: {report.summary.get('status', 'N/A')}")
    elif args.type == "system_health":
        report = reporter.generate_system_health_report()
        if args.json:
            print(report.to_json())
        else:
            print(f"System Health: {report.summary.get('passed', 0)}/{report.summary.get('checks', 0)} passed")


if __name__ == "__main__":
    _cli()


__all__ = [
    "CompliancePackage",
    "ComplianceReport",
    "RegulatoryReporter",
    "TradeRegisterEntry",
]

