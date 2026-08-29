"""Intelligence Pipeline routes — Continuous Intelligence Pipeline.

Extracted from register_intelligence_routes in intelligence.py for maintainability.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import Request

_log = logging.getLogger(__name__)


def register_pipeline_routes(app, dashboard, admin_only, operator_or_admin) -> None:  # type: ignore[no-untyped-def]
    """Register pipeline and supporting routes."""

    # ── Test Generator (Pillar 8) ─────────────────────────────────────────

    @app.post("/api/intelligence/test-generator/analyze")
    async def api_test_analyze(request: Request, user: Any = operator_or_admin):
        """Analyze a change and determine what tests are needed."""
        try:
            body = await request.json()
            from core.intelligent_test_generator import get_test_generator
            gen = get_test_generator()
            plan = gen.analyze_change(
                module_path=body.get("module_path", ""),
                change_type=body.get("change_type", "MODIFY"),
            )
            return {"status": "ok", "plan": plan.to_dict(), "summary": plan.summary, "timestamp": time.time()}
        except (ImportError, ValueError, TypeError, AttributeError, RuntimeError) as exc:
            _log.warning("[INTEL] Test analyze error: %s", exc)
            return {"status": "error", "detail": str(exc)}

    @app.get("/api/intelligence/test-generator/stats")
    async def api_test_stats(user: Any = operator_or_admin):
        """Get test generator statistics."""
        try:
            from core.intelligent_test_generator import get_test_generator
            gen = get_test_generator()
            return {"status": "ok", "stats": gen.get_test_generation_stats(), "timestamp": time.time()}
        except (ImportError, ValueError, TypeError, AttributeError, RuntimeError) as exc:
            _log.warning("[INTEL] Test stats error: %s", exc)
            return {"status": "error", "detail": str(exc)}

    # ── Living Documentation (Pillar 10) ──────────────────────────────────

    @app.post("/api/intelligence/docs/generate")
    async def api_docs_generate(user: Any = operator_or_admin):
        """Generate all living documentation."""
        try:
            from core.living_documentation import get_doc_generator
            doc_gen = get_doc_generator()
            pkg = doc_gen.generate_all()
            return {"status": "ok", "docs": pkg.to_dict(), "timestamp": time.time()}
        except (ImportError, ValueError, TypeError, AttributeError, RuntimeError) as exc:
            _log.warning("[INTEL] Docs generate error: %s", exc)
            return {"status": "error", "detail": str(exc)}

    @app.get("/api/intelligence/docs/stats")
    async def api_docs_stats(user: Any = operator_or_admin):
        """Get documentation generation statistics."""
        try:
            from core.living_documentation import get_doc_generator
            doc_gen = get_doc_generator()
            return {"status": "ok", "stats": doc_gen.get_stats(), "timestamp": time.time()}
        except (ImportError, ValueError, TypeError, AttributeError, RuntimeError) as exc:
            _log.warning("[INTEL] Docs stats error: %s", exc)
            return {"status": "error", "detail": str(exc)}

    # ── Continuous Intelligence Pipeline ────────────────────────────

    @app.get("/api/intelligence/pipeline/stats")
    async def api_pipeline_stats(user: Any = operator_or_admin):
        """Get Continuous Intelligence Pipeline statistics."""
        try:
            from core.continuous_intelligence import get_intelligence_pipeline
            pipeline = get_intelligence_pipeline()
            return {"status": "ok", "stats": pipeline.get_stats(), "timestamp": time.time()}
        except (ImportError, ValueError, TypeError, AttributeError, RuntimeError) as exc:
            _log.warning("[INTEL] Pipeline stats error: %s", exc)
            return {"status": "error", "detail": str(exc)}

    @app.post("/api/intelligence/pipeline/run")
    async def api_pipeline_run(user: Any = operator_or_admin):
        """Trigger a single pipeline check cycle."""
        try:
            from core.continuous_intelligence import get_intelligence_pipeline
            pipeline = get_intelligence_pipeline()
            result = pipeline.run_once()
            return {"status": "ok", "result": result.to_dict(), "summary": result.summary_text(), "timestamp": time.time()}
        except (ImportError, ValueError, TypeError, AttributeError, RuntimeError) as exc:
            _log.warning("[INTEL] Pipeline run error: %s", exc)
            return {"status": "error", "detail": str(exc)}

    @app.get("/api/intelligence/pipeline/history")
    async def api_pipeline_history(limit: int = 10, user: Any = operator_or_admin):
        """Get pipeline check history."""
        try:
            from core.continuous_intelligence import get_intelligence_pipeline
            pipeline = get_intelligence_pipeline()
            history = pipeline.get_history(limit=max(1, min(100, limit)))
            return {"status": "ok", "history": history, "count": len(history), "timestamp": time.time()}
        except (ImportError, ValueError, TypeError, AttributeError, RuntimeError) as exc:
            _log.warning("[INTEL] Pipeline history error: %s", exc)
            return {"status": "error", "detail": str(exc)}

    _log.info("[DASH] Pipeline & Support routes registered")
