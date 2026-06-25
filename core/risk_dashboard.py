"""
Global Risk Dashboard - Consolidated risk monitoring and reporting.

Provides REST API endpoints and CLI for viewing aggregated risk metrics
across all risk domains: position risk, portfolio risk, execution risk,
market risk, and operational risk.

Designed to be mounted into the EnterpriseDashboard FastAPI app, or run
standalone via CLI.

Usage
-----
    # CLI snapshot
    python -m core.risk_dashboard --snapshot

    # CLI JSON output
    python -m core.risk_dashboard --snapshot --json

    # Start dashboard server (standalone)
    python -m core.risk_dashboard --serve --port 8766

Endpoints (when mounted in FastAPI)
------------------------------------
    GET  /api/risk/snapshot      - Full risk snapshot
    GET  /api/risk/positions     - Position risk breakdown
    GET  /api/risk/limits        - Risk limit utilization
    GET  /api/risk/alerts        - Active risk alerts
    GET  /api/risk/history       - Risk metric history
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

_log = logging.getLogger(__name__)

# ── Risk data models ──────────────────────────────────────────────────────────

@dataclass
class RiskMetric:
    """A single risk metric with threshold and status."""
    name: str
    current_value: float
    limit_value: float
    unit: str = ""
    status: str = "OK"       # OK | WARN | CRITICAL
    category: str = "general"
    description: str = ""

    @property
    def utilization_pct(self) -> float:
        if self.limit_value == 0:
            return 0.0
        return min(100.0, (abs(self.current_value) / abs(self.limit_value)) * 100.0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "current_value": round(self.current_value, 4),
            "limit_value": self.limit_value,
            "unit": self.unit,
            "status": self.status,
            "category": self.category,
            "utilization_pct": round(self.utilization_pct, 1),
            "description": self.description,
        }


@dataclass
class RiskAlert:
    """An active risk alert."""
    level: str                 # INFO | WARN | CRITICAL
    source: str                # Which module generated it
    message: str
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    acknowledged: bool = False
    metric_name: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "source": self.source,
            "message": self.message,
            "timestamp": self.timestamp,
            "acknowledged": self.acknowledged,
            "metric_name": self.metric_name,
        }


@dataclass
class RiskSnapshot:
    """Complete risk landscape snapshot."""
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    metrics: list[RiskMetric] = field(default_factory=list)
    alerts: list[RiskAlert] = field(default_factory=list)
    overall_status: str = "OK"
    n_ok: int = 0
    n_warn: int = 0
    n_critical: int = 0

    def summary(self) -> str:
        lines = [
            "=" * 60,
            "  Global Risk Dashboard",
            "=" * 60,
            f"  Status: {self.overall_status}",
            f"  OK:       {self.n_ok}",
            f"  WARN:     {self.n_warn}",
            f"  CRITICAL: {self.n_critical}",
            f"  Alerts:   {len(self.alerts)}",
            "",
            "  Risk Metrics:",
        ]
        for m in self.metrics:
            icon = {"OK": "[OK]", "WARN": "[!]", "CRITICAL": "[X]"}.get(m.status, "[?]")
            lines.append(
                f"    {icon} {m.name:<30s} "
                f"{m.current_value:>10.4f} / {m.limit_value:>10.4f} {m.unit:<5s} "
                f"({m.utilization_pct:.0f}%)"
            )
        if self.alerts:
            lines.append("")
            lines.append("  Active Alerts:")
            for a in self.alerts:
                icon = {"CRITICAL": "[X]", "WARN": "[!]", "INFO": "[i]"}.get(a.level, "[?]")
                lines.append(f"    {icon} [{a.level}] {a.source}: {a.message}")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "overall_status": self.overall_status,
            "n_ok": self.n_ok,
            "n_warn": self.n_warn,
            "n_critical": self.n_critical,
            "metrics": [m.to_dict() for m in self.metrics],
            "alerts": [a.to_dict() for a in self.alerts],
        }


# ── Risk Probe ────────────────────────────────────────────────────────────────

class RiskProbe:
    """Gathers risk metrics from various risk components."""

    def __init__(self, config: dict[str, Any] | None = None):
        self._cfg = config or {}

    def collect_metrics(self) -> list[RiskMetric]:
        """Collect risk metrics from all available sources."""
        metrics: list[RiskMetric] = []

        # 1. Try to get position exposure from risk service
        self._add_from_risk_service(metrics)

        # 2. Try to get capital info from config
        self._add_capital_metrics(metrics)

        # 3. Try to get drawdown info
        self._add_drawdown_metrics(metrics)

        # 4. Try to get trade throughput (recent activity)
        self._add_trade_metrics(metrics)

        return metrics

    def _add_from_risk_service(self, metrics: list[RiskMetric]) -> None:
        """Try to read risk metrics from risk service."""
        try:
            from core.domains.risk.service import RiskService

            # Try to resolve from DI container
            container = None
            try:
                from core.di_container import get_container
                container = get_container()
            except ImportError:
                pass

            risk_service = container.try_resolve(RiskService) if container else None

            if risk_service:
                # Get position exposure
                if hasattr(risk_service, "get_current_exposure"):
                    exposure = risk_service.get_current_exposure()
                    metrics.append(RiskMetric(
                        name="current_exposure",
                        current_value=float(exposure),
                        limit_value=float(self._cfg.get("MAX_EXPOSURE", 100000)),
                        unit="Rs",
                        status=self._status_for(exposure, self._cfg.get("MAX_EXPOSURE", 100000), 0.8),
                        category="position_risk",
                        description="Current total position exposure",
                    ))

                # Get daily P&L
                if hasattr(risk_service, "get_daily_pnl"):
                    pnl = risk_service.get_daily_pnl()
                    max_loss = abs(float(self._cfg.get("MAX_DAILY_LOSS", 5000)))
                    metrics.append(RiskMetric(
                        name="daily_pnl",
                        current_value=float(pnl),
                        limit_value=max_loss,
                        unit="Rs",
                        status="OK" if pnl >= -max_loss else "CRITICAL",
                        category="pnl_risk",
                        description="Current daily P&L",
                    ))
        except ImportError:
            pass
        except Exception as exc:
            _log.debug("[RISK-DASH] Risk service probe failed: %s", exc)

    def _add_capital_metrics(self, metrics: list[RiskMetric]) -> None:
        """Add capital-related risk metrics from config."""
        try:
            total_capital = float(self._cfg.get("TOTAL_CAPITAL", 0)) or float(self._cfg.get("starting_capital", 100000))
            max_risk = float(self._cfg.get("MAX_RISK_PER_TRADE", 0.02)) * total_capital

            # Try to read from trader state
            used_capital = 0.0
            try:
                from pathlib import Path
                ts_path = Path("trader_state.json")
                if ts_path.is_file():
                    import json
                    data = json.loads(ts_path.read_text(encoding="utf-8"))
                    used_capital = float(data.get("locked_capital", 0))
            except (OSError, json.JSONDecodeError, ValueError):
                pass

            metrics.append(RiskMetric(
                name="capital_utilization",
                current_value=used_capital,
                limit_value=total_capital,
                unit="Rs",
                status=self._status_for(used_capital, total_capital, 0.7),
                category="capital_risk",
                description="Locked capital / total capital",
            ))

            metrics.append(RiskMetric(
                name="max_risk_per_trade",
                current_value=0.0,
                limit_value=max_risk,
                unit="Rs",
                status="OK",
                category="capital_risk",
                description="Maximum risk allowed per trade",
            ))
        except (ValueError, TypeError) as exc:
            _log.debug("[RISK-DASH] Capital probe failed: %s", exc)

    def _add_drawdown_metrics(self, metrics: list[RiskMetric]) -> None:
        """Add drawdown risk metrics."""
        try:
            max_dd = float(self._cfg.get("MAX_DRAWDOWN", 0.15))
            # Read current drawdown from trader state or config
            current_dd = 0.0
            try:
                from pathlib import Path
                ts_path = Path("trader_state.json")
                if ts_path.is_file():
                    import json
                    data = json.loads(ts_path.read_text(encoding="utf-8"))
                    peak = float(data.get("peak_capital", 0))
                    current = float(data.get("current_capital", 0))
                    if peak > 0:
                        current_dd = (peak - current) / peak
            except (OSError, json.JSONDecodeError, ValueError):
                pass

            metrics.append(RiskMetric(
                name="drawdown",
                current_value=current_dd * 100,
                limit_value=max_dd * 100,
                unit="%",
                status=self._status_for(current_dd, max_dd, 0.7),
                category="drawdown_risk",
                description="Current drawdown from peak",
            ))
        except (ValueError, TypeError) as exc:
            _log.debug("[RISK-DASH] Drawdown probe failed: %s", exc)

    def _add_trade_metrics(self, metrics: list[RiskMetric]) -> None:
        """Add trade throughput metrics."""
        try:
            from pathlib import Path
            db_path = Path(self._cfg.get("trades_db_path", "trades.db"))
            if db_path.is_file():
                from core.db_utils import get_connection
                conn = get_connection(str(db_path), timeout=5, row_factory=False)
                try:
                    # Trades today
                    row = conn.execute(
                        "SELECT COUNT(*) FROM trades WHERE ts >= datetime('now', '-1 day')"
                    ).fetchone()
                    trades_today = row[0] if row and row[0] else 0
                    max_trades = int(self._cfg.get("MAX_DAILY_TRADES", 20))
                    metrics.append(RiskMetric(
                        name="daily_trade_count",
                        current_value=float(trades_today),
                        limit_value=float(max_trades),
                        unit="trades",
                        status=self._status_for(trades_today, max_trades, 0.7),
                        category="execution_risk",
                        description="Trades executed today",
                    ))
                finally:
                    conn.close()
        except Exception as exc:
            _log.debug("[RISK-DASH] Trade probe failed: %s", exc)

    def collect_alerts(self) -> list[RiskAlert]:
        """Collect active risk alerts from available sources."""
        alerts: list[RiskAlert] = []

        # Check hard halt status
        try:
            from core.safety_state import _HARD_HALT
            if _HARD_HALT.is_set():
                alerts.append(RiskAlert(
                    level="CRITICAL",
                    source="safety_state",
                    message="Hard halt is ACTIVE — all trading blocked",
                    metric_name="hard_halt",
                ))
        except ImportError:
            pass
        except Exception as exc:
            _log.debug("[RISK-DASH] Halt check failed: %s", exc)

        # Check circuit breaker status via DI container
        try:
            from core.services.circuit_breaker_service import CircuitBreakerService
            from core.di_container import get_container
            container = get_container()
            cb = container.try_resolve(CircuitBreakerService)
            if cb is not None and hasattr(cb, "get_state"):
                # Check all known circuit breaker keys
                for cb_key in ("broker", "market_data", "order_execution"):
                    try:
                        state = cb.get_state(cb_key)
                        if hasattr(state, "name") and state.name == "OPEN":
                            alerts.append(RiskAlert(
                                level="CRITICAL",
                                source="circuit_breaker",
                                message=f"Circuit breaker '{cb_key}' is OPEN",
                                metric_name=f"circuit_breaker_{cb_key}",
                            ))
                    except (KeyError, ValueError, TypeError, AttributeError):
                        pass
        except ImportError:
            pass
        except Exception as exc:
            _log.debug("[RISK-DASH] Circuit breaker check failed: %s", exc)

        return alerts

    def _status_for(self, current: float, limit: float, warn_threshold: float) -> str:
        """Determine status based on utilization vs limit."""
        if limit == 0:
            return "OK"
        utilization = abs(current) / abs(limit)
        if utilization >= 1.0:
            return "CRITICAL"
        elif utilization >= warn_threshold:
            return "WARN"
        return "OK"

    @staticmethod
    def _status_for_value(value: float, warn_at: float, crit_at: float) -> str:
        """Determine status for unbounded metrics."""
        abs_v = abs(value)
        if abs_v >= crit_at:
            return "CRITICAL"
        elif abs_v >= warn_at:
            return "WARN"
        return "OK"


# ── Global Risk Dashboard ─────────────────────────────────────────────────────

class RiskDashboard:
    """Consolidated risk monitoring dashboard."""

    def __init__(self, probe: RiskProbe | None = None,
                 config: dict[str, Any] | None = None):
        self._probe = probe or RiskProbe(config)
        self._lock = threading.RLock()
        self._alerts: list[RiskAlert] = []
        self._last_snapshot: RiskSnapshot | None = None

    def get_snapshot(self) -> RiskSnapshot:
        """Get a full risk landscape snapshot."""
        metrics = self._probe.collect_metrics()
        alerts = self._probe.collect_alerts()

        # Merge with stored alerts
        with self._lock:
            all_alerts = list(alerts)
            for a in self._alerts:
                if not a.acknowledged:
                    all_alerts.append(a)
            self._alerts = all_alerts

        snapshot = RiskSnapshot(
            metrics=metrics,
            alerts=all_alerts,
        )

        # Compute overall status
        for m in metrics:
            if m.status == "CRITICAL":
                snapshot.n_critical += 1
            elif m.status == "WARN":
                snapshot.n_warn += 1
            else:
                snapshot.n_ok += 1

        if snapshot.n_critical > 0:
            snapshot.overall_status = "CRITICAL"
        elif snapshot.n_warn > 0:
            snapshot.overall_status = "WARN"
        else:
            snapshot.overall_status = "OK"

        self._last_snapshot = snapshot
        return snapshot

    def add_alert(self, alert: RiskAlert) -> None:
        """Add a risk alert."""
        with self._lock:
            self._alerts.append(alert)

    def acknowledge_alert(self, index: int) -> bool:
        """Acknowledge an alert by index."""
        with self._lock:
            if 0 <= index < len(self._alerts):
                self._alerts[index].acknowledged = True
                return True
            return False

    def get_alerts(self, unacknowledged_only: bool = False) -> list[RiskAlert]:
        """Get all alerts, optionally filtered."""
        with self._lock:
            if unacknowledged_only:
                return [a for a in self._alerts if not a.acknowledged]
            return list(self._alerts)


# ── Singleton ─────────────────────────────────────────────────────────────────

_global_dashboard: RiskDashboard | None = None
_dash_lock = threading.RLock()


def get_risk_dashboard(config: dict[str, Any] | None = None) -> RiskDashboard:
    """Get the global RiskDashboard singleton."""
    global _global_dashboard
    with _dash_lock:
        if _global_dashboard is None:
            _global_dashboard = RiskDashboard(config=config)
        return _global_dashboard


def get_risk_snapshot() -> RiskSnapshot:
    """Convenience: get a full risk snapshot."""
    return get_risk_dashboard().get_snapshot()


# ── CLI ───────────────────────────────────────────────────────────────────────

def _cli() -> None:
    import argparse
    ap = argparse.ArgumentParser(prog="python -m core.risk_dashboard")
    ap.add_argument("--snapshot", action="store_true", help="Show risk snapshot")
    ap.add_argument("--json", action="store_true", help="Output JSON")
    args = ap.parse_args()

    dash = get_risk_dashboard()

    if args.snapshot:
        snap = dash.get_snapshot()
        if args.json:
            print(json.dumps(snap.to_dict(), indent=2))
        else:
            print(snap.summary())
        return

    # Default: show snapshot
    snap = dash.get_snapshot()
    print(snap.summary())


if __name__ == "__main__":
    _cli()


__all__ = [
    "RiskAlert",
    "RiskDashboard",
    "RiskMetric",
    "RiskProbe",
    "RiskSnapshot",
    "get_risk_dashboard",
    "get_risk_snapshot",
]

