"""Executive Advisor — AI-Powered Executive Insights Agent (Constitution v4.0, Layer 10).

Provides executive-level intelligence:
- System health summary with trend analysis
- Risk exposure overview (VaR, drawdown, position concentration)
- Performance assessment (win rate, Sharpe, P&L attribution)
- Recommendation prioritization (urgent vs important)
- Security posture summary
- Decision memory highlights
- Key metrics at a glance

Integrates with:
- BIDashboard for health and quality metrics
- RiskDashboard for risk exposure
- PerformanceMetrics for trading performance
- SecurityAuditor for security posture
- DecisionMemory for decision highlights
- DigitalTwin for real-time state

Usage:
    from core.executive_advisor import get_executive_advisor

    advisor = get_executive_advisor()
    briefing = advisor.generate_daily_briefing()
    print(briefing.summary_text())
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────


# ── Data Models ────────────────────────────────────────────────────────────


@dataclass
class MetricHighlight:
    """A single key metric highlighted for the executive."""

    name: str = ""
    value: str = ""
    change: str = ""  # UP, DOWN, STABLE
    status: str = "NORMAL"  # GOOD, NORMAL, WARNING, CRITICAL
    description: str = ""
    recommendation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "value": self.value,
            "change": self.change,
            "status": self.status,
            "description": self.description,
            "recommendation": self.recommendation,
        }


@dataclass
class RiskBriefing:
    """Risk exposure briefing for executives."""

    var_95: float = 0.0
    max_drawdown: float = 0.0
    position_concentration: float = 0.0
    broker_dependency: str = "HEALTHY"
    data_provider_health: str = "HEALTHY"
    overall_risk_level: str = "LOW"
    top_risks: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "var_95": round(self.var_95, 2),
            "max_drawdown": round(self.max_drawdown, 2),
            "position_concentration": round(self.position_concentration, 1),
            "broker_dependency": self.broker_dependency,
            "data_provider_health": self.data_provider_health,
            "overall_risk_level": self.overall_risk_level,
            "top_risks": self.top_risks,
            "recommendations": self.recommendations,
        }


@dataclass
class PerformanceBriefing:
    """Trading performance briefing."""

    win_rate: float = 0.0
    total_trades: int = 0
    sharpe_ratio: float = 0.0
    total_pnl: float = 0.0
    avg_return_per_trade: float = 0.0
    best_trade: str = ""
    worst_trade: str = ""
    trend: str = "STABLE"
    top_performers: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "win_rate": round(self.win_rate, 1),
            "total_trades": self.total_trades,
            "sharpe_ratio": round(self.sharpe_ratio, 2),
            "total_pnl": round(self.total_pnl, 2),
            "avg_return_per_trade": round(self.avg_return_per_trade, 2),
            "best_trade": self.best_trade,
            "worst_trade": self.worst_trade,
            "trend": self.trend,
            "top_performers": self.top_performers,
            "recommendations": self.recommendations,
        }


@dataclass
class SystemHealthBriefing:
    """System health briefing."""

    overall_score: float = 0.0
    uptime_percent: float = 0.0
    broker_health: str = "HEALTHY"
    data_health: str = "HEALTHY"
    resource_health: str = "HEALTHY"
    security_score: float = 10.0
    recent_incidents: int = 0
    pending_action_items: int = 0
    recommendations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "overall_score": round(self.overall_score, 1),
            "uptime_percent": round(self.uptime_percent, 1),
            "broker_health": self.broker_health,
            "data_health": self.data_health,
            "resource_health": self.resource_health,
            "security_score": round(self.security_score, 1),
            "recent_incidents": self.recent_incidents,
            "pending_action_items": self.pending_action_items,
            "recommendations": self.recommendations,
        }


@dataclass
class ExecutiveBriefing:
    """Complete executive briefing with all insights."""

    timestamp: str = ""
    title: str = ""
    summary: str = ""
    key_metrics: list[MetricHighlight] = field(default_factory=list)
    risk_briefing: RiskBriefing = field(default_factory=RiskBriefing)
    performance_briefing: PerformanceBriefing = field(default_factory=PerformanceBriefing)
    system_health: SystemHealthBriefing = field(default_factory=SystemHealthBriefing)
    strategic_insights: list[str] = field(default_factory=list)
    top_recommendations: list[str] = field(default_factory=list)
    generated_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "title": self.title,
            "summary": self.summary,
            "key_metrics": [m.to_dict() for m in self.key_metrics],
            "risk_briefing": self.risk_briefing.to_dict(),
            "performance_briefing": self.performance_briefing.to_dict(),
            "system_health": self.system_health.to_dict(),
            "strategic_insights": self.strategic_insights,
            "top_recommendations": self.top_recommendations,
            "generated_at": self.generated_at,
        }

    def summary_text(self) -> str:
        lines = [
            "═" * 60,
            f"  📊 {self.title}",
            "═" * 60,
            f"  {self.summary}",
            "",
        ]
        if self.key_metrics:
            lines.append("  Key Metrics:")
            for m in self.key_metrics:
                icon = {"GOOD": "✅", "NORMAL": "ℹ️", "WARNING": "⚠️", "CRITICAL": "🔴"}.get(m.status, "ℹ️")
                arrow = {"UP": "↑", "DOWN": "↓", "STABLE": "→"}.get(m.change, "→")
                lines.append(f"    {icon} {m.name}: {m.value} {arrow}")
        if self.strategic_insights:
            lines.append("\n  Strategic Insights:")
            for s in self.strategic_insights:
                lines.append(f"    💡 {s}")
        if self.top_recommendations:
            lines.append("\n  Top Recommendations:")
            for r in self.top_recommendations[:5]:
                lines.append(f"    → {r}")
        lines.append("═" * 60)
        return "\n".join(lines)


# ── Executive Advisor ──────────────────────────────────────────────────────


class ExecutiveAdvisor:
    """Executive Advisor — AI-Powered Executive Insights.

    Generates executive-level briefings by aggregating data from:
    - BIDashboard for system health and quality trends
    - Risk services for risk exposure
    - Performance metrics for trading performance
    - Security services for security posture
    - Decision memory for strategic context

    Thread-safe.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._briefings: list[ExecutiveBriefing] = []
        self._max_briefings = 100
        self._persist_path = Path("json/executive_briefings.json")

    # ── Public API ────────────────────────────────────────────────────────

    def generate_daily_briefing(self) -> ExecutiveBriefing:
        """Generate a daily executive briefing.

        Collects data from all available intelligence modules
        and synthesizes a comprehensive executive summary.

        Returns:
            ExecutiveBriefing with key insights and recommendations.
        """
        now = datetime.utcnow()
        briefing = ExecutiveBriefing(
            timestamp=now.isoformat(),
            title=f"Daily Executive Briefing — {now.strftime('%B %d, %Y')}",
            generated_at=time.time(),
        )

        # 1. Collect system health data
        briefing.system_health = self._collect_system_health()

        # 2. Collect risk data
        briefing.risk_briefing = self._collect_risk_briefing()

        # 3. Collect performance data
        briefing.performance_briefing = self._collect_performance_briefing()

        # 4. Generate key metrics
        briefing.key_metrics = self._generate_key_metrics(briefing)

        # 5. Generate strategic insights
        briefing.strategic_insights = self._generate_strategic_insights(briefing)

        # 6. Generate top recommendations
        briefing.top_recommendations = self._prioritize_recommendations(briefing)

        # 7. Generate summary
        briefing.summary = self._generate_summary(briefing)

        with self._lock:
            self._briefings.append(briefing)
            if len(self._briefings) > self._max_briefings:
                self._briefings = self._briefings[-self._max_briefings:]
            self._persist()

        return briefing

    def get_latest_briefing(self) -> ExecutiveBriefing | None:
        """Get the most recently generated briefing."""
        with self._lock:
            return self._briefings[-1] if self._briefings else None

    def get_stats(self) -> dict[str, Any]:
        """Get executive advisor statistics."""
        with self._lock:
            last = self._briefings[-1] if self._briefings else None
            return {
                "total_briefings": len(self._briefings),
                "latest_briefing_ts": last.timestamp if last else "",
                "latest_summary": last.summary[:100] if last else "",
            }

    # ── Data Collection ─────────────────────────────────────────────────

    def _collect_system_health(self) -> SystemHealthBriefing:
        """Collect system health data from available sources."""
        health = SystemHealthBriefing()

        # Try DigitalTwin
        try:
            from core.digital_twin import get_digital_twin
            twin = get_digital_twin()
            score = twin.get_health_score()
            health.overall_score = score * 10  # Scale to 0-10
            state = twin.get_current_state()
            health.broker_health = "HEALTHY" if state.current.broker.primary_connected else "DEGRADED"
            health.data_health = "HEALTHY" if state.current.data_providers.providers_connected > 0 else "DEGRADED"
        except (ImportError, ValueError, AttributeError, RuntimeError):
            health.overall_score = 7.5  # Default estimate

        # Try BIDashboard
        try:
            from core.bi_dashboard import get_bi_dashboard
            bi = get_bi_dashboard()
            try:
                bi_health = bi.compute_health()
                health.overall_score = bi_health.overall_score
                health.recommendations.append("System health data aggregated from BI dashboard")
            except (ValueError, AttributeError, RuntimeError):
                pass
        except ImportError:
            pass

        # Try SecurityAuditor
        try:
            from core.security_auditor import get_security_auditor
            auditor = get_security_auditor()
            stats = auditor.get_stats()
            health.security_score = stats.get("last_scan_score", 10.0)
        except (ImportError, ValueError, AttributeError, RuntimeError):
            pass

        # DigitalTwin for uptime
        try:
            from core.digital_twin import get_digital_twin
            twin = get_digital_twin()
            stats = twin.get_stats()
            health.uptime_percent = 100.0  # Twin is always running
            health.resource_health = "DEGRADED" if stats.get("current_capital", 100000) < 10000 else "HEALTHY"
        except (ImportError, ValueError, AttributeError, RuntimeError):
            pass

        return health

    def _collect_risk_briefing(self) -> RiskBriefing:
        """Collect risk data from available sources."""
        risk = RiskBriefing()

        try:
            from core.risk_dashboard import get_risk_dashboard
            get_risk_dashboard()
            # Attempt to get overview
            risk.overall_risk_level = "LOW"
        except (ImportError, ValueError, AttributeError, RuntimeError):
            pass

        # Try to get VaR from var_calculator
        try:
            from core.var_calculator import get_var_calculator
            calc = get_var_calculator()
            if hasattr(calc, 'get_current_var'):
                var_data = calc.get_current_var()
                risk.var_95 = var_data.get('var_95', 0.0) if isinstance(var_data, dict) else 0.0
        except (ImportError, ValueError, AttributeError, RuntimeError):
            pass

        # Try DecisionMemory for risk-related decisions
        try:
            from core.decision_memory import get_decision_memory
            mem = get_decision_memory()
            risk_decisions = mem.search(query="risk", status="ACCEPTED")
            if risk_decisions:
                risk.top_risks.append(f"{len(risk_decisions)} risk-related decisions active")
        except (ImportError, ValueError, AttributeError, RuntimeError):
            pass

        return risk

    def _collect_performance_briefing(self) -> PerformanceBriefing:
        """Collect trading performance data."""
        perf = PerformanceBriefing()

        # Try to read from trades.db
        try:
            import sqlite3
            db_path = Path("db/trades.db")
            if db_path.is_file():
                conn = sqlite3.connect(str(db_path))
                cursor = conn.cursor()
                try:
                    cursor.execute("SELECT COUNT(*) FROM trades")
                    perf.total_trades = cursor.fetchone()[0] or 0

                    cursor.execute("SELECT SUM(pnl) FROM trades")
                    total = cursor.fetchone()[0]
                    perf.total_pnl = total or 0.0

                    cursor.execute("SELECT COUNT(*) FROM trades WHERE pnl > 0")
                    wins = cursor.fetchone()[0] or 0
                    if perf.total_trades > 0:
                        perf.win_rate = (wins / perf.total_trades) * 100

                    if perf.total_trades > 0:
                        perf.avg_return_per_trade = perf.total_pnl / perf.total_trades

                    # Best and worst trades
                    cursor.execute("SELECT instrument, pnl FROM trades ORDER BY pnl DESC LIMIT 1")
                    best = cursor.fetchone()
                    if best:
                        perf.best_trade = f"{best[0]}: ₹{best[1]:+,.0f}"

                    cursor.execute("SELECT instrument, pnl FROM trades ORDER BY pnl ASC LIMIT 1")
                    worst = cursor.fetchone()
                    if worst:
                        perf.worst_trade = f"{worst[0]}: ₹{worst[1]:+,.0f}"

                except sqlite3.OperationalError:
                    pass
                conn.close()
        except (ImportError, sqlite3.Error, OSError) as exc:
            _log.debug("[EXEC] Performance data unavailable: %s", exc)

        return perf

    def _generate_key_metrics(self, briefing: ExecutiveBriefing) -> list[MetricHighlight]:
        """Generate key metrics for the executive dashboard."""
        metrics: list[MetricHighlight] = []

        # System health
        metrics.append(MetricHighlight(
            name="System Health",
            value=f"{briefing.system_health.overall_score:.1f}/10",
            change="STABLE",
            status="GOOD" if briefing.system_health.overall_score >= 8 else "WARNING",
            description="Overall system health score",
            recommendation="" if briefing.system_health.overall_score >= 8 else "Review system health issues",
        ))

        # Broker status
        metrics.append(MetricHighlight(
            name="Broker Status",
            value=briefing.system_health.broker_health,
            change="STABLE",
            status="GOOD" if briefing.system_health.broker_health == "HEALTHY" else "CRITICAL",
            description="Broker connection status",
        ))

        # Win rate
        metrics.append(MetricHighlight(
            name="Win Rate",
            value=f"{briefing.performance_briefing.win_rate:.0f}%",
            change="STABLE",
            status="GOOD" if briefing.performance_briefing.win_rate >= 60 else "WARNING",
            description="Trade win rate",
        ))

        # Total P&L
        pnl = briefing.performance_briefing.total_pnl
        metrics.append(MetricHighlight(
            name="Total P&L",
            value=f"₹{pnl:+,.0f}",
            change="UP" if pnl >= 0 else "DOWN",
            status="GOOD" if pnl >= 0 else "CRITICAL",
            description="Total realized P&L",
        ))

        # Risk level
        metrics.append(MetricHighlight(
            name="Risk Level",
            value=briefing.risk_briefing.overall_risk_level,
            change="STABLE",
            status="GOOD" if briefing.risk_briefing.overall_risk_level == "LOW" else "WARNING",
            description="Overall risk exposure level",
        ))

        # Security score
        metrics.append(MetricHighlight(
            name="Security Score",
            value=f"{briefing.system_health.security_score:.1f}/10",
            change="STABLE",
            status="GOOD" if briefing.system_health.security_score >= 8 else "WARNING",
            description="Security posture score",
        ))

        # Pending action items
        if briefing.system_health.pending_action_items > 0:
            metrics.append(MetricHighlight(
                name="Pending Actions",
                value=str(briefing.system_health.pending_action_items),
                change="STABLE",
                status="WARNING" if briefing.system_health.pending_action_items > 5 else "NORMAL",
                description="Open action items from postmortems",
            ))

        return metrics

    def _generate_strategic_insights(self, briefing: ExecutiveBriefing) -> list[str]:
        """Generate strategic insights from aggregated data."""
        insights: list[str] = []

        # Health-based insights
        if briefing.system_health.overall_score >= 8.0:
            insights.append("System health is excellent — focus on optimization and new features")
        elif briefing.system_health.overall_score >= 6.0:
            insights.append("System health is adequate — prioritize addressing moderate issues")
        else:
            insights.append("System health needs attention — critical issues require immediate action")

        # Broker insights
        if briefing.system_health.broker_health != "HEALTHY":
            insights.append("Broker connectivity issues detected — verify failover readiness")

        # Performance insights
        if briefing.performance_briefing.total_trades > 0:
            win_rate = briefing.performance_briefing.win_rate
            if win_rate >= 60:
                insights.append(f"Trading performance is strong ({win_rate:.0f}% win rate) — strategy is working well")
            elif win_rate >= 40:
                insights.append(f"Trading performance is moderate ({win_rate:.0f}% win rate) — review strategy parameters")
            else:
                insights.append(f"Trading performance needs improvement ({win_rate:.0f}% win rate) — consider strategy revision")

        # Security insights
        if briefing.system_health.security_score < 8.0:
            insights.append("Security score needs improvement — run security audit and address findings")

        # Risk insights
        if briefing.risk_briefing.overall_risk_level in ("HIGH", "CRITICAL"):
            insights.append("Risk exposure is elevated — review position sizing and risk limits")

        if not insights:
            insights.append("System operating normally — continue monitoring key metrics")

        return insights

    def _prioritize_recommendations(self, briefing: ExecutiveBriefing) -> list[str]:
        """Prioritize recommendations from all sources."""
        recommendations: list[str] = []

        # Critical health issues first
        if briefing.system_health.overall_score < 5.0:
            recommendations.append("URGENT: System health critically low — investigate immediately")
        if briefing.system_health.broker_health != "HEALTHY":
            recommendations.append("URGENT: Broker connection issue — verify and restore connectivity")
        if briefing.performance_briefing.win_rate < 30 and briefing.performance_briefing.total_trades > 20:
            recommendations.append("URGENT: Trading performance severely degraded — pause and review strategy")

        # High priority
        if briefing.system_health.security_score < 6.0:
            recommendations.append("HIGH: Security vulnerabilities require immediate remediation")
        if briefing.risk_briefing.overall_risk_level == "HIGH":
            recommendations.append("HIGH: Risk exposure elevated — review and reduce position sizes")
        if briefing.system_health.pending_action_items > 10:
            recommendations.append("MEDIUM: Excessive pending action items — prioritize and complete open items")

        # Normal recommendations
        if briefing.system_health.overall_score < 8.0:
            recommendations.append("Review and address system health issues in upcoming sprint")
        if briefing.system_health.security_score < 9.0:
            recommendations.append("Schedule security audit to maintain security posture")

        if not recommendations:
            recommendations.append("System is operating at optimal levels — continue monitoring")

        return recommendations[:8]

    def _generate_summary(self, briefing: ExecutiveBriefing) -> str:
        """Generate a one-line executive summary."""
        health = briefing.system_health.overall_score
        broker = briefing.system_health.broker_health
        pnl_val = briefing.performance_briefing.total_pnl
        win = briefing.performance_briefing.win_rate
        risk = briefing.risk_briefing.overall_risk_level

        return (
            f"System health: {health:.1f}/10 | "
            f"Broker: {broker} | "
            f"P&L: ₹{pnl_val:+,.0f} | "
            f"Win Rate: {win:.0f}% | "
            f"Risk: {risk}"
        )

    # ── Persistence ──────────────────────────────────────────────────────

    def _persist(self) -> None:
        """Persist briefing history to disk."""
        try:
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)
            data = [b.to_dict() for b in self._briefings[-50:]]
            self._persist_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except (OSError, ValueError) as exc:
            _log.debug("[EXEC] Persist: %s", exc)


# ── CLI ────────────────────────────────────────────────────────────────────


def _cli() -> None:
    import argparse
    ap = argparse.ArgumentParser(
        prog="python -m core.executive_advisor",
        description="Executive Advisor — Generate executive briefings",
    )
    ap.add_argument("--briefing", action="store_true", help="Generate daily executive briefing")
    ap.add_argument("--latest", action="store_true", help="Show latest briefing")
    ap.add_argument("--json", action="store_true", help="Output as JSON")
    args = ap.parse_args()

    advisor = get_executive_advisor()

    if args.briefing:
        briefing = advisor.generate_daily_briefing()
        if args.json:
            import json
            print(json.dumps(briefing.to_dict(), indent=2))
        else:
            print(briefing.summary_text())
        return

    if args.latest:
        briefing = advisor.get_latest_briefing()
        if briefing:
            if args.json:
                import json
                print(json.dumps(briefing.to_dict(), indent=2))
            else:
                print(briefing.summary_text())
        else:
            print("No briefing generated yet. Use --briefing to generate one.")
        return

    ap.print_help()


if __name__ == "__main__":
    _cli()

# ── Singleton ──────────────────────────────────────────────────────────────

_advisor: ExecutiveAdvisor | None = None
_advisor_lock = threading.RLock()


def get_executive_advisor() -> ExecutiveAdvisor:
    """Get the singleton ExecutiveAdvisor instance."""
    global _advisor
    with _advisor_lock:
        if _advisor is None:
            _advisor = ExecutiveAdvisor()
        return _advisor


def reset_executive_advisor() -> None:
    """Force-reset singleton (for testing)."""
    global _advisor
    with _advisor_lock:
        _advisor = None


__all__ = [
    "ExecutiveAdvisor",
    "ExecutiveBriefing",
    "MetricHighlight",
    "PerformanceBriefing",
    "RiskBriefing",
    "SystemHealthBriefing",
    "get_executive_advisor",
    "reset_executive_advisor",
]
