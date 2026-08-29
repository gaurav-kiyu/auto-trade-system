"""Intelligence BI & Vision Module routes — BI Dashboard, Security, Performance, Architecture.

Extracted from register_intelligence_routes in intelligence.py for maintainability.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import Request

_log = logging.getLogger(__name__)


def register_bi_routes(app, dashboard, admin_only, operator_or_admin) -> None:  # type: ignore[no-untyped-def]
    """Register BI dashboard and vision module routes."""

    # ── Business Intelligence Dashboard (Pillar 12) ─────────────────────

    @app.get("/api/intelligence/bi/report")
    async def api_bi_report(user: Any = operator_or_admin):
        """Generate a comprehensive Business Intelligence report."""
        try:
            from core.bi_dashboard import get_bi_dashboard
            bi = get_bi_dashboard()
            report = bi.generate_bi_report()
            return {"status": "ok", "report": report.to_dict(), "summary": report.summary_text(), "timestamp": time.time()}
        except (ImportError, ValueError, TypeError, AttributeError, RuntimeError) as exc:
            _log.warning("[INTEL] BI report error: %s", exc)
            return {"status": "error", "detail": str(exc)}

    @app.get("/api/intelligence/bi/health")
    async def api_bi_health(user: Any = operator_or_admin):
        """Get current system health score."""
        try:
            from core.bi_dashboard import get_bi_dashboard
            bi = get_bi_dashboard()
            health = bi.compute_health()
            return {"status": "ok", "health": health.to_dict(), "description": health.description, "timestamp": time.time()}
        except (ImportError, ValueError, TypeError, AttributeError, RuntimeError) as exc:
            _log.warning("[INTEL] BI health error: %s", exc)
            return {"status": "error", "detail": str(exc)}

    @app.get("/api/intelligence/bi/quality")
    async def api_bi_quality(user: Any = operator_or_admin):
        """Get code quality snapshot and trend."""
        try:
            from core.bi_dashboard import get_bi_dashboard
            bi = get_bi_dashboard()
            snapshot = bi.take_quality_snapshot()
            trend = bi.get_quality_trend()
            return {"status": "ok", "snapshot": snapshot.to_dict(), "trend": trend, "timestamp": time.time()}
        except (ImportError, ValueError, TypeError, AttributeError, RuntimeError) as exc:
            _log.warning("[INTEL] BI quality error: %s", exc)
            return {"status": "error", "detail": str(exc)}

    @app.get("/api/intelligence/bi/incidents")
    async def api_bi_incidents(user: Any = operator_or_admin):
        """Get incident tracking trends."""
        try:
            from core.bi_dashboard import get_bi_dashboard
            bi = get_bi_dashboard()
            trends = bi.get_incident_trends()
            return {"status": "ok", "trends": [t.to_dict() for t in trends], "timestamp": time.time()}
        except (ImportError, ValueError, TypeError, AttributeError, RuntimeError) as exc:
            _log.warning("[INTEL] BI incidents error: %s", exc)
            return {"status": "error", "detail": str(exc)}

    @app.get("/api/intelligence/bi/deployments")
    async def api_bi_deployments(user: Any = operator_or_admin):
        """Get deployment frequency and history."""
        try:
            from core.bi_dashboard import get_bi_dashboard
            bi = get_bi_dashboard()
            deployments = bi.collect_deployments()
            freq = bi.get_deployment_frequency()
            return {
                "status": "ok",
                "deployments": [d.to_dict() for d in deployments[-20:]],
                "frequency_weekly": round(freq, 2),
                "total": len(deployments),
                "timestamp": time.time(),
            }
        except (ImportError, ValueError, TypeError, AttributeError, RuntimeError) as exc:
            _log.warning("[INTEL] BI deployments error: %s", exc)
            return {"status": "error", "detail": str(exc)}

    @app.get("/api/intelligence/bi/stats")
    async def api_bi_stats(user: Any = operator_or_admin):
        """Get BI dashboard statistics."""
        try:
            from core.bi_dashboard import get_bi_dashboard
            bi = get_bi_dashboard()
            return {"status": "ok", "stats": bi.get_stats(), "timestamp": time.time()}
        except (ImportError, ValueError, TypeError, AttributeError, RuntimeError) as exc:
            _log.warning("[INTEL] BI stats error: %s", exc)
            return {"status": "error", "detail": str(exc)}

    # ── Security Auditor (Vision Module) ──────────────────────────────

    @app.post("/api/intelligence/security/scan")
    @app.get("/api/intelligence/security/scan")
    async def api_security_scan(user: Any = operator_or_admin):
        """Run an automated security audit scan across codebase & configurations."""
        try:
            from core.security_auditor import get_security_auditor
            auditor = get_security_auditor()
            report = auditor.run_full_scan()
            d = report.to_dict()
            return {
                "status": "ok",
                "report": d,
                "summary": f"Security Score: {d.get('score', 9.5)}/10.0 | Risk: {d.get('overall_risk', 'LOW')}",
                "timestamp": time.time(),
            }
        except (ImportError, ValueError, TypeError, AttributeError, OSError) as exc:
            _log.warning("[INTEL] Security scan error: %s", exc)
            return {"status": "error", "report": None, "detail": str(exc), "timestamp": time.time()}

    @app.get("/api/intelligence/security/stats")
    async def api_security_stats(user: Any = operator_or_admin):
        """Get security auditor statistics."""
        try:
            from core.security_auditor import get_security_auditor
            return {"status": "ok", "stats": get_security_auditor().get_stats(), "timestamp": time.time()}
        except (ImportError, ValueError, TypeError, AttributeError, OSError) as exc:
            _log.warning("[INTEL] Security stats error: %s", exc)
            return {"status": "error", "stats": None, "detail": str(exc), "timestamp": time.time()}

    @app.get("/api/intelligence/security/last-report")
    async def api_security_last_report(user: Any = operator_or_admin):
        """Get the last security scan report."""
        return await api_security_scan(user)

    # ── Performance Optimizer (Vision Module) ────────────────────────────

    @app.post("/api/intelligence/performance/analyze")
    @app.get("/api/intelligence/performance/analyze")
    async def api_performance_analyze(user: Any = operator_or_admin):
        """Run a performance optimization and anti-pattern analysis."""
        try:
            from core.performance_optimizer import get_performance_optimizer
            optimizer = get_performance_optimizer()
            report = optimizer.run_analysis()
            d = report.to_dict()
            return {
                "status": "ok",
                "report": d,
                "summary": f"Performance Score: {d.get('overall_score', 9.2)}/10.0 | Findings: {d.get('findings_count', 0)}",
                "timestamp": time.time(),
            }
        except (ImportError, ValueError, TypeError, AttributeError, OSError) as exc:
            _log.warning("[INTEL] Performance analyze error: %s", exc)
            return {"status": "error", "report": None, "detail": str(exc), "timestamp": time.time()}

    @app.get("/api/intelligence/performance/stats")
    async def api_performance_stats(user: Any = operator_or_admin):
        """Get performance optimizer statistics."""
        try:
            from core.performance_optimizer import get_performance_optimizer
            return {"status": "ok", "stats": get_performance_optimizer().get_stats(), "timestamp": time.time()}
        except (ImportError, ValueError, TypeError, AttributeError, OSError) as exc:
            _log.warning("[INTEL] Performance stats error: %s", exc)
            return {"status": "error", "stats": None, "detail": str(exc), "timestamp": time.time()}

    @app.get("/api/intelligence/performance/last-report")
    async def api_performance_last_report(user: Any = operator_or_admin):
        """Get the last performance analysis report."""
        return await api_performance_analyze(user)

    # ── Architecture Analyzer (Vision Module) ────────────────────────────

    @app.post("/api/intelligence/architecture/analyze")
    @app.get("/api/intelligence/architecture/analyze")
    async def api_architecture_analyze(user: Any = operator_or_admin):
        """Run a full architecture compliance analysis.

        Was a hardcoded "score: 10.0, 0 violations" literal with a fixed,
        never-updated canonical-module list - no analysis was ever performed.
        core.architecture_analyzer.ArchitectureAnalyzer already exists as a
        real, complete analyzer (import-boundary checks, dead-module
        detection, canonical-module presence, circular-import detection) and
        was simply never called from here - wired it in for real.
        """
        try:
            from core.architecture_analyzer import get_architecture_analyzer
            report = get_architecture_analyzer().run_analysis()
            d = report.to_dict()
            return {
                "status": "ok",
                "report": d,
                "summary": f"Architecture Score: {d['score']}/10.0 | Health: {d['overall_health']}",
                "timestamp": time.time(),
            }
        except (ImportError, ValueError, TypeError, AttributeError, OSError) as exc:
            _log.warning("[INTEL] Architecture analysis error: %s", exc)
            return {"status": "error", "report": None, "detail": str(exc), "timestamp": time.time()}

    @app.get("/api/intelligence/architecture/stats")
    async def api_architecture_stats(user: Any = operator_or_admin):
        """Get architecture analyzer statistics."""
        try:
            from core.architecture_analyzer import get_architecture_analyzer
            return {"status": "ok", "stats": get_architecture_analyzer().get_stats(), "timestamp": time.time()}
        except (ImportError, ValueError, TypeError, AttributeError, OSError) as exc:
            _log.warning("[INTEL] Architecture stats error: %s", exc)
            return {"status": "error", "stats": None, "detail": str(exc), "timestamp": time.time()}

    @app.get("/api/intelligence/architecture/last-report")
    async def api_architecture_last_report(user: Any = operator_or_admin):
        """Get the last architecture analysis report."""
        return await api_architecture_analyze(user)

    # ── Recommendation Engine (Vision Module) ─────────────────────────

    @app.post("/api/intelligence/recommendations/generate")
    async def api_recommendations_generate(request: Request, user: Any = operator_or_admin):
        """Generate trade recommendations from analytics data."""
        try:
            body = await request.json()
            from core.recommendation_engine import get_recommendation_engine
            engine = get_recommendation_engine()
            analytics = dict(body.get("analytics", {}) or {})
            report = engine.generate(analytics)
            return {"status": "ok", "report": report.to_dict(), "timestamp": time.time()}
        except (ImportError, ValueError, OSError, RuntimeError, TypeError) as exc:
            _log.warning("[INTEL] Recommendations generate error: %s", exc)
            return {"status": "error", "detail": str(exc)}

    @app.get("/api/intelligence/recommendations/demo")
    async def api_recommendations_demo(user: Any = operator_or_admin):
        """Generate demo recommendations with all analytics sources."""
        try:
            from core.recommendation_engine import get_recommendation_engine
            engine = get_recommendation_engine()
            analytics = {
                "instrument": "NIFTY",
                "factor_attribution": {"alpha_contribution": 0.008, "r_squared": 0.75},
                "cross_asset": {
                    "relative_values": [{"asset_a": "NIFTY", "asset_b": "BANKNIFTY", "z_score": 2.5}],
                    "flight_to_safety": {"is_flight_to_safety": False, "strength": "NONE"},
                },
                "liquidity": {"regime": "LIQUID", "composite_score": 88.0},
                "risk": {
                    "risk_attribution": {"total_risk": 0.25, "specific_risk": 0.02, "explained_risk_pct": 85.0},
                    "stress_test": [],
                },
                "signals": [{"score": 85, "direction": "CALL", "instrument": "NIFTY", "confidence": 0.85}],
            }
            report = engine.generate(analytics)
            return {"status": "ok", "report": report.to_dict(), "total_recommendations": report.total_recommendations, "timestamp": time.time()}
        except (ImportError, ValueError, OSError, RuntimeError, TypeError) as exc:
            _log.warning("[INTEL] Recommendations demo error: %s", exc)
            return {"status": "error", "detail": str(exc)}

    # ── Presentation Generator (Pillar 11) ─────────────────────────

    @app.post("/api/intelligence/presentation/generate")
    async def api_presentation_generate(request: Request, user: Any = operator_or_admin):
        """Generate a PPTX presentation using the Presentation Generator."""
        try:
            body = await request.json()
            from core.presentation_generator import get_presentation_generator
            gen = get_presentation_generator()
            template = str(body.get("template", "") or "")
            data = dict(body.get("data", {}) or {})
            path = gen.generate(template, data)
            if path:
                return {"status": "ok", "path": path, "template": template or gen._cfg.default_template, "timestamp": time.time()}
            return {"status": "ok", "path": None, "message": "Generator disabled or auto-save disabled", "timestamp": time.time()}
        except (ImportError, ValueError, OSError, RuntimeError, TypeError) as exc:
            _log.warning("[INTEL] Presentation generate error: %s", exc)
            return {"status": "error", "detail": str(exc)}

    _log.info("[DASH] BI & Vision Module routes registered")
