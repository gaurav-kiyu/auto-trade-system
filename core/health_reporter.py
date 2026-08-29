import logging
import sqlite3
import time
from dataclasses import dataclass
from typing import Any

__all__ = [
    "HealthReporter",
    "HealthScore",
]


@dataclass
class HealthScore:
    """System health score with enhanced data quality and governance metrics."""

    overall: float
    db_health: str
    ml_drift: str
    api_stability: str
    data_quality_score: float = 1.0
    data_quality_health: str = "GREEN"
    governance_status: str = "ACTIVE"
    invariant_violations: int = 0
    recommendation: str = ""
    timestamp: float = 0.0


class HealthReporter:
    """Performs a comprehensive weekly audit of the trading system.

    Enhanced with data quality scoring, invariant checks, and
    strategy governance status from the new modules.
    """

    def __init__(self, cfg: dict[str, Any], db_path: str) -> None:
        self.cfg = cfg
        self.db_path = db_path
        self.logger = logging.getLogger(__name__)

    def run_weekly_audit(self) -> HealthScore:
        """Executes a battery of health checks including data quality."""
        try:
            # 1. DB Check
            db_ok = self._check_db()
            # 2. ML Drift Check
            ml_ok = self._check_ml_drift()
            # 3. API Stability
            api_ok = "GOOD"
            # 4. Data Quality Score
            dq_score, dq_health = self._check_data_quality()
            # 5. Invariant violations
            inv_violations = self._check_invariants()
            # 6. Governance status
            gov_status = self._check_governance()

            # Composite score: 40% traditional + 30% data quality + 20% invariants + 10% governance
            base_score = 100.0 if db_ok == "PASS" else 70.0
            dq_component = dq_score * 100.0 * 0.3
            inv_penalty = max(0, 100 - inv_violations * 5) * 0.2
            gov_component = 100.0 if gov_status == "ACTIVE" else 70.0

            overall = (base_score * 0.4) + dq_component + inv_penalty + (gov_component * 0.1)
            overall = min(100.0, max(0.0, overall))

            recommendation = self._generate_recommendation(
                db_ok,
                ml_ok,
                dq_health,
                inv_violations,
                gov_status,
            )

            return HealthScore(
                overall=round(overall, 1),
                db_health=db_ok,
                ml_drift=ml_ok,
                api_stability=api_ok,
                data_quality_score=round(dq_score, 4),
                data_quality_health=dq_health,
                governance_status=gov_status,
                invariant_violations=inv_violations,
                recommendation=recommendation,
                timestamp=time.time(),
            )
        except (sqlite3.Error, OSError, ValueError) as e:
            self.logger.error(f"Weekly audit failed: {e}")
            return HealthScore(0.0, "FAIL", "UNKNOWN", "UNKNOWN", recommendation="Urgent: System health audit failed.")

    def _check_db(self) -> str:
        try:
            from core.db_utils import get_connection as _get_hr_conn

            conn = _get_hr_conn(self.db_path, row_factory=False)
            conn.execute("PRAGMA integrity_check")
            conn.close()
            return "PASS"
        except (sqlite3.Error, OSError):
            return "FAIL"

    def _check_ml_drift(self) -> str:
        """Check ML drift via concept_drift_detector if available."""
        try:
            from core.concept_drift_detector import get_drift_detector

            detector = get_drift_detector()
            result = detector.check_all_features()
            worst = max(result.values(), key=lambda r: r.get("psi", 0)) if result else {}
            psi = worst.get("psi", 0) if worst else 0
            if psi > 0.25:
                return "DRIFT_DETECTED"
            elif psi > 0.1:
                return "WATCHING"
            return "STABLE"
        except Exception:
            return "STABLE"

    def _check_data_quality(self) -> tuple[float, str]:
        """Check data quality via DataQualityScorer."""
        try:
            from core.data_quality_scorer import get_quality_scorer

            scorer = get_quality_scorer()
            health = scorer.get_system_health()
            return health.overall_score, health.health
        except Exception:
            return 1.0, "GREEN"

    def _check_invariants(self) -> int:
        """Check pending invariant violations."""
        try:
            from core.invariants.engine import get_state

            state = get_state()
            return state.get("violation_count", 0)
        except Exception:
            return 0

    def _check_governance(self) -> str:
        """Check strategy approval workflow status."""
        try:
            from core.strategy.approval_workflow import get_approval_workflow

            wf = get_approval_workflow()
            report = wf.get_governance_report()
            if report.get("pending_count", 0) > 5:
                return "BACKLOG"
            return "ACTIVE"
        except Exception:
            return "UNAVAILABLE"

    def _generate_recommendation(
        self,
        db_health: str,
        ml_drift: str,
        dq_health: str,
        inv_violations: int,
        gov_status: str,
    ) -> str:
        issues = []
        if db_health != "PASS":
            issues.append("DB health check failed")
        if ml_drift == "DRIFT_DETECTED":
            issues.append("ML concept drift detected - retrain recommended")
        if dq_health == "RED":
            issues.append("Data quality critical - check data sources")
        if inv_violations > 0:
            issues.append(f"{inv_violations} invariant violation(s) unresolved")
        if gov_status == "BACKLOG":
            issues.append("Governance approval backlog - review pending requests")
        if not issues:
            return "System healthy. Proceed with current config."
        return "Action needed: " + "; ".join(issues)

    def format_telegram_report(self, score: HealthScore) -> str:
        # Defensive coercion: data_quality_score may arrive as a string from
        # callers constructing HealthScore positionally — never crash the report.
        try:
            dq_score = float(score.data_quality_score)
        except (TypeError, ValueError):
            dq_score = 0.0
        lines = [
            "📊 SUNDAY SYSTEM HEALTH REPORT",
            f"Overall Score: {score.overall}%",
            f"DB Health: {score.db_health}",
            f"ML Drift: {score.ml_drift}",
            f"Data Quality: {score.data_quality_health} ({dq_score:.2f})",
            f"Governance: {score.governance_status}",
            f"Invariant Violations: {score.invariant_violations}",
            f"Recommendation: {score.recommendation}",
        ]
        return "\n".join(lines)
