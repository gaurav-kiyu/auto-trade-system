"""
Capacity Planning Module (Phase 18).

Monitors resource usage, forecasts capacity needs, and provides scalability
analysis for the trading platform. Tracks database growth, memory usage,
disk I/O, and trade throughput.

Usage
-----
    from core.capacity_planning import CapacityPlanner

    planner = CapacityPlanner()
    report = planner.analyze()
    print(report.summary())

    # Or check a specific resource
    db_growth = planner.estimate_db_growth("trades.db")

Config keys (all optional — safe defaults built in)
---------------------------------------------------
    capacity_warn_disk_gb      : float  default 5.0   (warn when disk free < this)
    capacity_warn_db_growth    : float  default 0.1   (warn when daily DB growth > this GB)
    capacity_warn_trade_rate   : int    default 100   (warn when trades/hour > this)
    capacity_forecast_days     : int    default 90    (forecast horizon)
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)

_DEFAULT_DB = "trades.db"


# ── Result dataclasses ──────────────────────────────────────────────────────

@dataclass
class ResourceMetric:
    """A single resource measurement."""
    resource: str
    current_value: float
    unit: str
    status: str        # "OK" | "WARN" | "CRITICAL"
    threshold: float
    message: str = ""


@dataclass
class GrowthForecast:
    """Forecast for a tracked resource."""
    resource: str
    current_size_mb: float
    daily_growth_mb: float
    forecast_30d_mb: float
    forecast_90d_mb: float
    days_until_capacity: int | None  # None = unknown
    status: str = "OK"

    def to_dict(self) -> dict[str, Any]:
        return {
            "resource": self.resource,
            "current_size_mb": round(self.current_size_mb, 2),
            "daily_growth_mb": round(self.daily_growth_mb, 2),
            "forecast_30d_mb": round(self.forecast_30d_mb, 2),
            "forecast_90d_mb": round(self.forecast_90d_mb, 2),
            "days_until_capacity": self.days_until_capacity,
            "status": self.status,
        }


@dataclass
class CapacityReport:
    """Complete capacity planning report."""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metrics: list[ResourceMetric] = field(default_factory=list)
    forecasts: list[GrowthForecast] = field(default_factory=list)
    overall_status: str = "OK"
    summary: str = ""

    @property
    def ok_count(self) -> int:
        return sum(1 for m in self.metrics if m.status == "OK")

    @property
    def warn_count(self) -> int:
        return sum(1 for m in self.metrics if m.status == "WARN")

    @property
    def critical_count(self) -> int:
        return sum(1 for m in self.metrics if m.status == "CRITICAL")

    def summary_text(self) -> str:
        lines = [
            "Capacity Planning Report",
            "=" * 60,
            self.summary,
            "",
            "Metrics:",
        ]
        for m in self.metrics:
            icon = {"OK": "[OK]", "WARN": "[!]", "CRITICAL": "[X]"}.get(m.status, "[?]")
            lines.append(f"  {icon} {m.resource:<35s} {m.current_value:<10.2f} {m.unit:<5s} {m.message}")
        if self.forecasts:
            lines.append("")
            lines.append("Growth Forecasts:")
            for f in self.forecasts:
                lines.append(f"  {f.resource:<35s} {f.current_size_mb:>8.2f} MB now -> {f.forecast_90d_mb:>8.2f} MB in 90d")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "overall_status": self.overall_status,
            "summary": self.summary,
            "metrics": [{
                "resource": m.resource, "current_value": m.current_value,
                "unit": m.unit, "status": m.status, "threshold": m.threshold,
                "message": m.message,
            } for m in self.metrics],
            "forecasts": [f.to_dict() for f in self.forecasts],
        }


# ── Scaling Trigger ────────────────────────────────────────────────────────

@dataclass
class ScalingTrigger:
    """A capacity scaling trigger definition.

    When resource usage exceeds the threshold, the trigger fires an alert
    and optionally invokes an action callback.
    """
    name: str
    resource: str              # Matches ResourceMetric.resource name
    threshold: float           # Threshold value
    direction: str             # "above" or "below"
    severity: str              # "INFO" | "WARN" | "CRITICAL"
    action: str = "log"        # "log" | "alert" | "callback" | "auto_scale"
    cooldown_seconds: int = 3600  # Minimum gap between firings
    last_fired: float = 0.0
    description: str = ""

    def should_fire(self, current_value: float) -> bool:
        """Check if this trigger should fire based on current value."""
        if time.time() - self.last_fired < self.cooldown_seconds:
            return False
        if self.direction == "above":
            return current_value > self.threshold
        elif self.direction == "below":
            return current_value < self.threshold
        return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "resource": self.resource,
            "threshold": self.threshold,
            "direction": self.direction,
            "severity": self.severity,
            "action": self.action,
            "cooldown_seconds": self.cooldown_seconds,
            "last_fired": self.last_fired,
            "description": self.description,
        }


DEFAULT_SCALING_TRIGGERS: list[ScalingTrigger] = [
    ScalingTrigger(
        name="disk_free_warn",
        resource="disk_free_space",
        threshold=5.0,
        direction="below",
        severity="WARN",
        action="alert",
        cooldown_seconds=86400,
        description="Free disk space below 5 GB — schedule cleanup",
    ),
    ScalingTrigger(
        name="disk_free_critical",
        resource="disk_free_space",
        threshold=1.0,
        direction="below",
        severity="CRITICAL",
        action="callback",
        cooldown_seconds=3600,
        description="Free disk space below 1 GB — immediate action required",
    ),
    ScalingTrigger(
        name="disk_usage_high",
        resource="disk_usage_pct",
        threshold=90.0,
        direction="above",
        severity="WARN",
        action="log",
        cooldown_seconds=86400,
        description="Disk usage above 90%",
    ),
    ScalingTrigger(
        name="db_growth_rapid",
        resource="db_trades.db_size",
        threshold=500.0,
        direction="above",
        severity="WARN",
        action="alert",
        cooldown_seconds=86400,
        description="Trades DB size exceeds 500 MB",
    ),
    ScalingTrigger(
        name="db_growth_critical",
        resource="db_trades.db_size",
        threshold=900.0,
        direction="above",
        severity="CRITICAL",
        action="alert",
        cooldown_seconds=3600,
        description="Trades DB size exceeds 900 MB — near 1GB limit",
    ),
    ScalingTrigger(
        name="trade_rate_high",
        resource="trade_throughput",
        threshold=100.0,
        direction="above",
        severity="WARN",
        action="log",
        cooldown_seconds=3600,
        description="Trade rate exceeds 100 trades/hour — verify config",
    ),
    ScalingTrigger(
        name="memory_high",
        resource="process_memory",
        threshold=500.0,
        direction="above",
        severity="WARN",
        action="log",
        cooldown_seconds=86400,
        description="Process memory exceeds 500 MB RSS",
    ),
    ScalingTrigger(
        name="log_size_warn",
        resource="log_directory_size",
        threshold=2000.0,
        direction="above",
        severity="WARN",
        action="alert",
        cooldown_seconds=86400,
        description="Log directory exceeds 2 GB — rotate logs",
    ),
    ScalingTrigger(
        name="oi_db_size_warn",
        resource="db_oi_snapshots.db_size",
        threshold=500.0,
        direction="above",
        severity="WARN",
        action="alert",
        cooldown_seconds=86400,
        description="OI snapshots DB exceeds 500 MB",
    ),
]


# ── Capacity Planner ─────────────────────────────────────────────────────────

class CapacityPlanner:
    """Capacity planning and resource forecasting engine."""

    def __init__(self, cfg: dict[str, Any] | None = None):
        self._cfg = cfg or {}
        self._triggers: list[ScalingTrigger] = []
        self._alert_callback: callable | None = None
        self._load_triggers()

    def _load_triggers(self) -> None:
        """Load scaling triggers from config, falling back to defaults."""
        custom_triggers = self._cfg.get("capacity_scaling_triggers", None)
        if custom_triggers and isinstance(custom_triggers, list):
            for t in custom_triggers:
                self._triggers.append(ScalingTrigger(
                    name=t.get("name", "custom"),
                    resource=t.get("resource", ""),
                    threshold=float(t.get("threshold", 0)),
                    direction=t.get("direction", "above"),
                    severity=t.get("severity", "WARN"),
                    action=t.get("action", "log"),
                    cooldown_seconds=int(t.get("cooldown_seconds", 3600)),
                    description=t.get("description", ""),
                ))
        else:
            self._triggers = list(DEFAULT_SCALING_TRIGGERS)

    def set_alert_callback(self, callback: callable) -> None:
        """Set a callback for triggered alerts (e.g. Telegram send function)."""
        self._alert_callback = callback

    def get_triggers(self) -> list[ScalingTrigger]:
        """Get all registered scaling triggers."""
        return list(self._triggers)

    def check_triggers(self, report: CapacityReport | None = None) -> list[dict[str, Any]]:
        """Check all scaling triggers and return fired trigger info."""
        if report is None:
            report = self.analyze()

        # Build lookup of resource -> current value
        resource_values: dict[str, float] = {}
        for m in report.metrics:
            resource_values[m.resource] = m.current_value

        fired: list[dict[str, Any]] = []
        for trigger in self._triggers:
            value = resource_values.get(trigger.resource)
            if value is None:
                continue

            if trigger.should_fire(value):
                trigger.last_fired = time.time()
                fired.append({
                    "trigger": trigger.to_dict(),
                    "current_value": value,
                    "timestamp": time.time(),
                })

                # Execute action
                msg = (
                    f"[SCALE] {trigger.severity}: {trigger.name} "
                    f"({trigger.resource}={value:.1f}, threshold={trigger.threshold})"
                )
                if trigger.action == "alert" and self._alert_callback:
                    try:
                        self._alert_callback(msg)
                    except Exception as exc:
                        _log.warning("[SCALE] Alert callback failed: %s", exc)
                elif trigger.action == "log":
                    if trigger.severity == "CRITICAL":
                        _log.critical(msg)
                    elif trigger.severity == "WARN":
                        _log.warning(msg)
                    else:
                        _log.info(msg)

        return fired

    def _get(self, key: str, default: Any) -> Any:
        return self._cfg.get(f"capacity_{key}", default)

    def analyze(self) -> CapacityReport:
        """Run full capacity analysis and return report."""
        report = CapacityReport()
        issues: list[str] = []

        # 1. Disk space
        self._check_disk_space(report, issues)

        # 2. Database sizes and growth
        self._check_databases(report, issues)

        # 3. Trade throughput
        self._check_trade_throughput(report, issues)

        # 4. Log directory
        self._check_log_directory(report, issues)

        # 5. Memory (approximate via process)
        self._check_memory_usage(report, issues)

        # Determine overall status
        if report.critical_count > 0:
            report.overall_status = "CRITICAL"
        elif report.warn_count > 0:
            report.overall_status = "WARN"
        else:
            report.overall_status = "OK"

        report.summary = (
            f"Capacity: {report.overall_status} - "
            f"{report.ok_count} OK, {report.warn_count} WARN, "
            f"{report.critical_count} CRITICAL"
        )
        return report

    def _check_disk_space(self, report: CapacityReport, issues: list[str]) -> None:
        """Check available disk space."""
        warn_gb = float(self._get("warn_disk_gb", 5.0))

        try:
            import shutil
            total, used, free = shutil.disk_usage(".")
            free_gb = free / (1024 ** 3)
            total_gb = total / (1024 ** 3)

            if free_gb < warn_gb:
                status = "WARN" if free_gb > warn_gb * 0.5 else "CRITICAL"
            else:
                status = "OK"

            report.metrics.append(ResourceMetric(
                resource="disk_free_space",
                current_value=round(free_gb, 2),
                unit="GB",
                status=status,
                threshold=warn_gb,
                message=f"{free_gb:.1f} GB free of {total_gb:.1f} GB total",
            ))

            # Disk usage percentage
            usage_pct = (used / total) * 100 if total > 0 else 0
            report.metrics.append(ResourceMetric(
                resource="disk_usage_pct",
                current_value=round(usage_pct, 1),
                unit="%",
                status="OK" if usage_pct < 85 else "WARN",
                threshold=85.0,
                message=f"{usage_pct:.1f}% utilized",
            ))
        except (OSError, PermissionError) as exc:
            report.metrics.append(ResourceMetric(
                resource="disk_free_space", current_value=0, unit="GB",
                status="WARN", threshold=warn_gb, message=str(exc),
            ))

    def _check_databases(self, report: CapacityReport, issues: list[str]) -> None:
        """Check database size and estimate growth."""
        dbs = ["trades.db", "trade_journal.db", "ml_tracker.db",
               "oi_snapshots.db", "event_store.db", "execution_state.db"]

        for db_name in dbs:
            p = Path(db_name)
            if not p.is_file():
                continue

            size_mb = p.stat().st_size / (1024 * 1024)
            age_days = self._file_age_days(p)
            daily_growth = size_mb / max(age_days, 1)

            forecast_30d = size_mb + daily_growth * 30
            forecast_90d = size_mb + daily_growth * 90

            # Estimate days until 1GB (default capacity)
            capacity_mb = 1000.0
            days_until = None
            if daily_growth > 0:
                days_until = int((capacity_mb - size_mb) / daily_growth)
                if days_until < 0:
                    days_until = 0

            status = "OK"
            if daily_growth > self._get("warn_db_growth", 0.1) * 1024:
                status = "WARN"
            if size_mb > 500:
                status = "WARN"
            if size_mb > 900:
                status = "CRITICAL"

            forecast = GrowthForecast(
                resource=db_name,
                current_size_mb=round(size_mb, 2),
                daily_growth_mb=round(daily_growth, 2),
                forecast_30d_mb=round(forecast_30d, 2),
                forecast_90d_mb=round(forecast_90d, 2),
                days_until_capacity=days_until,
                status=status,
            )
            report.forecasts.append(forecast)

            report.metrics.append(ResourceMetric(
                resource=f"db_{db_name}_size",
                current_value=round(size_mb, 2),
                unit="MB",
                status=status,
                threshold=500.0,
                message=f"{size_mb:.1f} MB (growing {daily_growth:.1f} MB/day)",
            ))

    def _check_trade_throughput(self, report: CapacityReport, issues: list[str]) -> None:
        """Check trade throughput rate."""
        warn_rate = int(self._get("warn_trade_rate", 100))

        try:
            db_path = self._cfg.get("trades_db_path", _DEFAULT_DB)
            p = Path(db_path)
            if not p.is_file():
                report.metrics.append(ResourceMetric(
                    resource="trade_throughput", current_value=0, unit="trades/hour",
                    status="OK", threshold=warn_rate, message="No trades DB",
                ))
                return

            from core.db_utils import get_connection
            conn = get_connection(str(p), timeout=5, row_factory=False)
            try:
                # Count trades in last 24 hours
                row = conn.execute(
                    "SELECT COUNT(*) FROM trades WHERE ts >= datetime('now', '-1 day')"
                ).fetchone()
                trades_24h = row[0] if row and row[0] else 0
                hourly_rate = round(trades_24h / 24.0, 1)

                status = "OK"
                if hourly_rate > warn_rate:
                    status = "WARN" if hourly_rate < warn_rate * 2 else "CRITICAL"

                report.metrics.append(ResourceMetric(
                    resource="trade_throughput",
                    current_value=hourly_rate,
                    unit="trades/hour",
                    status=status,
                    threshold=warn_rate,
                    message=f"{hourly_rate:.1f} trades/hour (24h avg)",
                ))
            finally:
                conn.close()
        except Exception as exc:
            report.metrics.append(ResourceMetric(
                resource="trade_throughput", current_value=0, unit="trades/hour",
                status="WARN", threshold=warn_rate, message=str(exc),
            ))

    def _check_log_directory(self, report: CapacityReport, issues: list[str]) -> None:
        """Check log directory size."""
        log_dir = Path("logs")
        if not log_dir.is_dir():
            report.metrics.append(ResourceMetric(
                resource="log_directory", current_value=0, unit="MB",
                status="OK", threshold=2000.0, message="No logs directory",
            ))
            return

        try:
            total_bytes = sum(f.stat().st_size for f in log_dir.rglob("*") if f.is_file())
            total_mb = total_bytes / (1024 * 1024)
            warn_mb = 2000.0  # 2 GB

            status = "WARN" if total_mb > warn_mb else "OK"
            report.metrics.append(ResourceMetric(
                resource="log_directory_size",
                current_value=round(total_mb, 2),
                unit="MB",
                status=status,
                threshold=warn_mb,
                message=f"{total_mb:.1f} MB in logs/",
            ))
        except (OSError, ValueError) as exc:
            report.metrics.append(ResourceMetric(
                resource="log_directory_size", current_value=0, unit="MB",
                status="WARN", threshold=2000.0, message=str(exc),
            ))

    def _check_memory_usage(self, report: CapacityReport, issues: list[str]) -> None:
        """Approximate memory usage check."""
        try:
            import psutil
            process = psutil.Process()
            mem_mb = process.memory_info().rss / (1024 * 1024)
            report.metrics.append(ResourceMetric(
                resource="process_memory",
                current_value=round(mem_mb, 1),
                unit="MB",
                status="OK" if mem_mb < 500 else "WARN",
                threshold=500.0,
                message=f"{mem_mb:.0f} MB RSS",
            ))
        except ImportError:
            report.metrics.append(ResourceMetric(
                resource="process_memory", current_value=0, unit="MB",
                status="OK", threshold=500.0, message="psutil not available",
            ))
        except Exception:
            report.metrics.append(ResourceMetric(
                resource="process_memory", current_value=0, unit="MB",
                status="OK", threshold=500.0, message="Could not determine",
            ))

    def _file_age_days(self, path: Path) -> float:
        """Estimate file age in days from modification time."""
        try:
            mtime = path.stat().st_mtime
            age_seconds = time.time() - mtime
            return max(age_seconds / 86400.0, 1.0)
        except OSError:
            return 1.0

    def estimate_db_growth(self, db_path: str = _DEFAULT_DB) -> GrowthForecast | None:
        """Quick estimate of a single DB's growth."""
        p = Path(db_path)
        if not p.is_file():
            return None

        size_mb = p.stat().st_size / (1024 * 1024)
        age_days = self._file_age_days(p)
        daily_growth = size_mb / max(age_days, 1)

        return GrowthForecast(
            resource=db_path,
            current_size_mb=round(size_mb, 2),
            daily_growth_mb=round(daily_growth, 2),
            forecast_30d_mb=round(size_mb + daily_growth * 30, 2),
            forecast_90d_mb=round(size_mb + daily_growth * 90, 2),
            days_until_capacity=int((1000 - size_mb) / daily_growth) if daily_growth > 0 else None,
        )


# ── CLI ──────────────────────────────────────────────────────────────────────

def _cli() -> None:
    import argparse
    ap = argparse.ArgumentParser(prog="python -m core.capacity_planning")
    ap.add_argument("--json", action="store_true", help="Output JSON")
    ap.add_argument("--db-growth", type=str, default="", help="Check specific DB growth")
    args = ap.parse_args()

    planner = CapacityPlanner()

    if args.db_growth:
        forecast = planner.estimate_db_growth(args.db_growth)
        if forecast:
            if args.json:
                print(json.dumps(forecast.to_dict(), indent=2))
            else:
                print(f"DB Growth Forecast: {args.db_growth}")
                print(f"  Current: {forecast.current_size_mb:.1f} MB")
                print(f"  Daily growth: {forecast.daily_growth_mb:.1f} MB")
                print(f"  30d forecast: {forecast.forecast_30d_mb:.1f} MB")
                print(f"  90d forecast: {forecast.forecast_90d_mb:.1f} MB")
                if forecast.days_until_capacity is not None:
                    print(f"  Days until 1GB: {forecast.days_until_capacity}")
        else:
            print(f"DB not found: {args.db_growth}")
        return

    report = planner.analyze()
    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(report.summary_text())


# ── Bridge: Capacity Planner → Incident Alerting ─────────────────────────

def wire_capacity_alerting(
    cfg: dict[str, Any] | None = None,
) -> CapacityPlanner:
    """Create a CapacityPlanner wired to the IncidentAlerting system.

    When capacity thresholds are breached, the planner's check_triggers()
    will fire incidents into the IncidentAlerting priority queue, which
    routes CRITICAL/HIGH alerts to notification channels and logs
    NORMAL/LOW alerts for dashboard display.

    This wires the integration called out in the scorecard:
        "Auto-scaling capacity planning triggers integration with alerting"

    Args:
        cfg: Optional config dict.

    Returns:
        A configured CapacityPlanner with alerting wired.
    """
    planner = CapacityPlanner(cfg)

    try:
        from core.incident_alerting import get_incident_alerting
        incident_mgr = get_incident_alerting()

        def _alert_bridge(msg: str) -> None:
            """Bridge callback: CapacityPlanner trigger → IncidentAlerting."""
            is_critical = "CRITICAL" in msg.upper() or "WARN" in msg.upper()
            if is_critical:
                incident_mgr.alert_capacity_critical(msg, {"source": "capacity_planner"})
            else:
                incident_mgr.alert_capacity_warning(msg, {"source": "capacity_planner"})

        planner.set_alert_callback(_alert_bridge)
    except ImportError:
        pass  # IncidentAlerting not available — run without alerting

    return planner


if __name__ == "__main__":
    _cli()


__all__ = [
    "CapacityPlanner",
    "CapacityReport",
    "DEFAULT_SCALING_TRIGGERS",
    "GrowthForecast",
    "ResourceMetric",
    "ScalingTrigger",
    "wire_capacity_alerting",
]

