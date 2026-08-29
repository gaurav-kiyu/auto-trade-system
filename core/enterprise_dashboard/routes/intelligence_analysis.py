"""Intelligence Analysis routes — Impact, Root Cause, Knowledge Graph, Risk, Dependencies.

Extracted from register_intelligence_routes in intelligence.py for maintainability.
Registered via register_analysis_routes() called from register_intelligence_routes().
"""

from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import Request

_log = logging.getLogger(__name__)


def register_analysis_routes(app, dashboard, admin_only, operator_or_admin) -> None:  # type: ignore[no-untyped-def]
    """Register analysis/analytics routes."""

    # ── Impact Analysis (Pillar 4) ────────────────────────────────────────

    @app.get("/api/intelligence/impact/{module_path:path}")
    async def api_impact_analysis(module_path: str, user: Any = operator_or_admin):
        """Analyze the impact of changing a module."""
        try:
            from core.impact_analysis_engine import get_impact_engine
            engine = get_impact_engine()
            report = engine.analyze_change(module_path)
            return {
                "status": "ok",
                "module": module_path,
                "impact": report.to_dict(),
                "summary": report.summary,
                "timestamp": time.time(),
            }
        except (ImportError, ValueError, TypeError, AttributeError, RuntimeError) as exc:
            _log.warning("[INTEL] Impact analysis error: %s", exc)
            return {"status": "error", "detail": str(exc)}

    @app.get("/api/intelligence/impact/stats")
    async def api_impact_stats(user: Any = operator_or_admin):
        """Get impact analysis engine statistics."""
        try:
            from core.impact_analysis_engine import get_impact_engine
            engine = get_impact_engine()
            return {"status": "ok", "stats": engine.get_module_stats(), "timestamp": time.time()}
        except (ImportError, ValueError, TypeError, AttributeError, RuntimeError) as exc:
            _log.warning("[INTEL] Impact stats error: %s", exc)
            return {"status": "error", "detail": str(exc)}

    @app.get("/api/intelligence/impact/dependents/{module_path:path}")
    async def api_impact_dependents(module_path: str, user: Any = operator_or_admin):
        """Get modules that depend on the given module."""
        try:
            from core.impact_analysis_engine import get_impact_engine
            engine = get_impact_engine()
            dependents = engine.get_dependents(module_path)
            return {
                "status": "ok",
                "module": module_path,
                "dependents": dependents,
                "count": len(dependents),
                "timestamp": time.time(),
            }
        except (ImportError, ValueError, TypeError, AttributeError, RuntimeError) as exc:
            _log.warning("[INTEL] Impact dependents error: %s", exc)
            return {"status": "error", "detail": str(exc)}

    # ── Root Cause Analysis (Pillar 5) ────────────────────────────────────

    @app.post("/api/intelligence/root-cause/investigate")
    async def api_root_cause_investigate(request: Request, user: Any = operator_or_admin):
        """Investigate an incident and determine root cause."""
        try:
            body = await request.json()
            from core.root_cause_analyzer import get_root_cause_analyzer
            analyzer = get_root_cause_analyzer()
            result = analyzer.investigate(
                error_type=body.get("error_type", "UNKNOWN"),
                error_message=body.get("error_message", ""),
                stack_trace=body.get("stack_trace", ""),
                module=body.get("module", ""),
            )
            return {"status": "ok", "result": result.to_dict(), "timestamp": time.time()}
        except (ImportError, ValueError, TypeError, AttributeError, RuntimeError) as exc:
            _log.warning("[INTEL] Root cause error: %s", exc)
            return {"status": "error", "detail": str(exc)}

    @app.get("/api/intelligence/root-cause/history")
    async def api_root_cause_history(incident_type: str = "", user: Any = operator_or_admin):
        """Get incident investigation history."""
        try:
            from core.root_cause_analyzer import get_root_cause_analyzer
            analyzer = get_root_cause_analyzer()
            history = analyzer.get_incident_history(incident_type=incident_type if incident_type else None)
            stats = analyzer.get_incident_stats()
            return {"status": "ok", "history": history, "stats": stats, "timestamp": time.time()}
        except (ImportError, ValueError, TypeError, AttributeError, RuntimeError) as exc:
            _log.warning("[INTEL] Root cause history error: %s", exc)
            return {"status": "error", "detail": str(exc)}

    @app.get("/api/intelligence/root-cause/patterns")
    async def api_root_cause_patterns(user: Any = operator_or_admin):
        """Get known incident patterns."""
        try:
            from core.root_cause_analyzer import KNOWN_INCIDENT_PATTERNS
            return {
                "status": "ok",
                "patterns": {
                    key: {
                        "description": val["description"],
                        "common_causes": val["common_causes"],
                        "recovery_actions": val["recovery_actions"],
                        "severity": val["severity"],
                    }
                    for key, val in KNOWN_INCIDENT_PATTERNS.items()
                },
                "timestamp": time.time(),
            }
        except ImportError as exc:
            return {"status": "error", "detail": str(exc)}

    # ── Codebase Knowledge Graph (Pillar 2) ──────────────────────────────

    @app.get("/api/intelligence/knowledge-graph/search")
    async def api_knowledge_search(query: str = "", symbol_type: str = "", user: Any = operator_or_admin):
        """Search the codebase knowledge graph for symbols."""
        try:
            from core.codebase_knowledge_graph import get_knowledge_graph
            kg = get_knowledge_graph()
            results = kg.search(query, symbol_type if symbol_type else None)
            return {"status": "ok", "query": query, "results": [s.to_dict() for s in results], "count": len(results), "timestamp": time.time()}
        except (ImportError, ValueError, TypeError, AttributeError, RuntimeError) as exc:
            _log.warning("[INTEL] Knowledge graph search error: %s", exc)
            return {"status": "error", "detail": str(exc)}

    @app.get("/api/intelligence/knowledge-graph/report")
    async def api_knowledge_report(user: Any = operator_or_admin):
        """Get the full knowledge graph report."""
        try:
            from core.codebase_knowledge_graph import get_knowledge_graph
            kg = get_knowledge_graph()
            report = kg.get_report()
            return {"status": "ok", "report": report.to_dict(), "summary": report.summary_text(), "timestamp": time.time()}
        except (ImportError, ValueError, TypeError, AttributeError, RuntimeError) as exc:
            _log.warning("[INTEL] Knowledge graph report error: %s", exc)
            return {"status": "error", "detail": str(exc)}

    @app.get("/api/intelligence/knowledge-graph/hotspots")
    async def api_knowledge_hotspots(user: Any = operator_or_admin):
        """Get predicted maintenance hotspots."""
        try:
            from core.codebase_knowledge_graph import get_knowledge_graph
            kg = get_knowledge_graph()
            hotspots = kg.predict_hotspots(top_n=20)
            return {"status": "ok", "hotspots": [h.to_dict() for h in hotspots], "count": len(hotspots), "timestamp": time.time()}
        except (ImportError, ValueError, TypeError, AttributeError, RuntimeError) as exc:
            _log.warning("[INTEL] Hotspots error: %s", exc)
            return {"status": "error", "detail": str(exc)}

    @app.get("/api/intelligence/knowledge-graph/smells")
    async def api_knowledge_smells(user: Any = operator_or_admin):
        """Get detected design smells."""
        try:
            from core.codebase_knowledge_graph import get_knowledge_graph
            kg = get_knowledge_graph()
            smells = kg.detect_design_smells()
            return {"status": "ok", "smells": [s.to_dict() for s in smells], "count": len(smells), "timestamp": time.time()}
        except (ImportError, ValueError, TypeError, AttributeError, RuntimeError) as exc:
            _log.warning("[INTEL] Smells error: %s", exc)
            return {"status": "error", "detail": str(exc)}

    # ── Change Risk Scorer (Pillar 9) ─────────────────────────────────────

    @app.post("/api/intelligence/risk-score")
    async def api_risk_score(request: Request, user: Any = operator_or_admin):
        """Score the risk of a code change."""
        try:
            body = await request.json()
            from core.change_risk_scorer import get_risk_scorer
            scorer = get_risk_scorer()
            score = scorer.score_change(
                files_changed=body.get("files_changed", []),
                lines_added=body.get("lines_added", 0),
                lines_deleted=body.get("lines_deleted", 0),
                commit_message=body.get("commit_message", ""),
            )
            return {"status": "ok", "risk_score": score.to_dict(), "summary": score.summary_text(), "timestamp": time.time()}
        except (ImportError, ValueError, TypeError, AttributeError, RuntimeError) as exc:
            _log.warning("[INTEL] Risk score error: %s", exc)
            return {"status": "error", "detail": str(exc)}

    @app.get("/api/intelligence/risk-score/module/{module_path:path}")
    async def api_risk_module(module_path: str, user: Any = operator_or_admin):
        """Get the risk profile of a specific module."""
        try:
            from core.change_risk_scorer import get_risk_scorer
            scorer = get_risk_scorer()
            profile = scorer.get_module_risk_profile(module_path)
            return {"status": "ok", "profile": profile, "timestamp": time.time()}
        except (ImportError, ValueError, TypeError, AttributeError, RuntimeError) as exc:
            _log.warning("[INTEL] Risk module error: %s", exc)
            return {"status": "error", "detail": str(exc)}

    # ── Dependency Analyzer (Vision Module) ───────────────────────

    @app.get("/api/intelligence/dependencies/report")
    async def api_dependency_report(user: Any = operator_or_admin):
        """Get full dependency analysis report."""
        try:
            from core.dependency_analyzer import get_dependency_analyzer
            analyzer = get_dependency_analyzer()
            report = analyzer.analyze()
            return {"status": "ok", "report": report.to_dict(), "summary": report.summary_text(), "timestamp": time.time()}
        except (ImportError, ValueError, OSError, RuntimeError, TypeError) as exc:
            _log.warning("[INTEL] Dependency report error: %s", exc)
            return {"status": "error", "detail": str(exc)}

    @app.get("/api/intelligence/dependencies/module/{module_path:path}")
    async def api_dependency_module(module_path: str, user: Any = operator_or_admin):
        """Get dependencies and dependents for a specific module."""
        try:
            from core.dependency_analyzer import get_dependency_analyzer
            analyzer = get_dependency_analyzer()
            deps = analyzer.get_module_dependencies(module_path)
            dependents = analyzer.get_module_dependents(module_path)
            return {"status": "ok", "module": module_path, "dependencies": deps, "dependents": dependents, "timestamp": time.time()}
        except (ImportError, ValueError, OSError, RuntimeError, TypeError) as exc:
            _log.warning("[INTEL] Dependency module error: %s", exc)
            return {"status": "error", "detail": str(exc)}

    _log.info("[DASH] Analysis routes registered")
