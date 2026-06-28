"""
Fundamental analysis route registration for the Enterprise Dashboard.

Handles: /api/fundamentals/weights (GET + PUT),
/api/fundamentals/analyze/{symbol}, /api/fundamentals/screen.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from fastapi import Depends, Request

_log = logging.getLogger(__name__)


def register_fundamentals_routes(app, dashboard, admin_only, operator_or_admin):
    """Register fundamental analysis API routes.

    Args:
        app: FastAPI application instance.
        dashboard: EnterpriseDashboard instance.
        admin_only: FastAPI Depends for admin role.
        operator_or_admin: FastAPI Depends for operator or admin role.
    """

    @app.get("/api/fundamentals/weights", tags=["Fundamentals"])
    async def api_fundamentals_weights(
        user: Any = Depends(dashboard._auth_deps.require_auth_optional),
    ):
        """Get current fundamental analysis dimension weights."""
        try:
            from core.fundamental_analyzer import get_fundamental_analyzer
            fa = get_fundamental_analyzer()
            return {
                "weights": fa.current_weights,
                "default_weights": {
                    "value": 0.30,
                    "growth": 0.25,
                    "quality": 0.25,
                    "momentum": 0.20,
                },
                "timestamp": time.time(),
            }
        except (ValueError, TypeError, ImportError, AttributeError) as exc:
            _log.warning("[DASH] Fundamentals weights fetch failed: %s", exc)
            return {"error": str(exc), "weights": {}, "timestamp": time.time()}

    @app.put("/api/fundamentals/weights", tags=["Fundamentals"])
    async def api_fundamentals_weights_update(
        request: Request,
        user: Any = Depends(dashboard._auth_deps.require_auth_optional),
    ):
        """Update fundamental analysis dimension weights at runtime."""
        try:
            body = await request.json()
            weights: dict[str, float] = body.get("weights", {})
            if not weights:
                return {"error": "No weights provided", "success": False}

            from core.fundamental_analyzer import get_fundamental_analyzer
            fa = get_fundamental_analyzer()
            fa.set_weights(weights)

            return {
                "success": True,
                "weights": fa.current_weights,
                "timestamp": time.time(),
            }
        except (ValueError, TypeError, KeyError, ImportError, AttributeError) as exc:
            _log.warning("[DASH] Fundamentals weights update failed: %s", exc)
            return {"error": str(exc), "success": False, "timestamp": time.time()}

    @app.get("/api/fundamentals/analyze/{symbol}", tags=["Fundamentals"])
    async def api_fundamentals_analyze(
        symbol: str,
        request: Request,
        user: Any = Depends(dashboard._auth_deps.require_auth_optional),
    ):
        """Analyze a single symbol's fundamentals."""
        try:
            from core.fundamental_analyzer import get_fundamental_analyzer
            fa = get_fundamental_analyzer()

            force_refresh = request.query_params.get("force_refresh", "false").lower() == "true"
            weights_str = request.query_params.get("weights", "")

            prev_weights = None
            if weights_str:
                try:
                    custom_w = json.loads(weights_str)
                    prev_weights = fa.current_weights
                    fa.set_weights(custom_w)
                except (json.JSONDecodeError, ValueError, TypeError) as exc:
                    _log.warning("[DASH] Invalid weights JSON in analyze: %s", exc)

            result = fa.analyze(symbol, force_refresh=force_refresh)

            if prev_weights is not None:
                try:
                    fa.set_weights(prev_weights)
                except ValueError:
                    pass

            return {
                "symbol": result.symbol,
                "name": result.name,
                "sector": result.sector,
                "current_price": result.current_price,
                "market_cap": result.market_cap,
                "pe_ratio": result.pe_ratio,
                "pb_ratio": result.pb_ratio,
                "dividend_yield": result.dividend_yield,
                "eps_ttm": result.eps_ttm,
                "roe_pct": result.roe_pct,
                "debt_to_equity": result.debt_to_equity,
                "earnings_growth": result.earnings_growth,
                "composite_score": result.composite_score,
                "verdict": result.verdict,
                "dimension_scores": {
                    "value": result.dimension_scores.value,
                    "growth": result.dimension_scores.growth,
                    "quality": result.dimension_scores.quality,
                    "momentum": result.dimension_scores.momentum,
                },
                "details": [
                    {
                        "metric": d.metric,
                        "raw_value": d.raw_value,
                        "score": d.score,
                        "weight": d.weight,
                        "rationale": d.rationale,
                    }
                    for d in result.details
                ],
                "short_summary": result.short_summary,
                "error": result.error,
                "timestamp": time.time(),
            }
        except (ValueError, TypeError, KeyError, ImportError, AttributeError) as exc:
            _log.warning("[DASH] Fundamentals analyze failed: %s", exc)
            return {"error": str(exc), "symbol": symbol, "timestamp": time.time()}

    @app.post("/api/fundamentals/screen", tags=["Fundamentals"])
    async def api_fundamentals_screen(
        request: Request,
        user: Any = Depends(dashboard._auth_deps.require_auth_optional),
    ):
        """Screen multiple symbols by fundamental scores."""
        try:
            body = await request.json()
            symbols: list[str] = body.get("symbols", [])
            min_score: float = float(body.get("min_score", 0.0))
            force_refresh: bool = bool(body.get("force_refresh", False))
            weights: dict[str, float] | None = body.get("weights", None)

            if not symbols:
                return {"error": "No symbols provided", "results": [], "count": 0}
            MAX_SCREEN_SYMBOLS = 50
            if len(symbols) > MAX_SCREEN_SYMBOLS:
                symbols = symbols[:MAX_SCREEN_SYMBOLS]
                _log.warning("[DASH] Fundamentals screen truncated to %d symbols", MAX_SCREEN_SYMBOLS)

            from core.fundamental_analyzer import get_fundamental_analyzer
            fa = get_fundamental_analyzer()

            prev_weights = None
            if weights:
                prev_weights = fa.current_weights
                fa.set_weights(weights)

            results = fa.screen(symbols, min_score=min_score, force_refresh=force_refresh)

            if prev_weights is not None:
                try:
                    fa.set_weights(prev_weights)
                except ValueError:
                    pass

            return {
                "results": [
                    {
                        "symbol": r.symbol,
                        "name": r.name,
                        "sector": r.sector,
                        "current_price": r.current_price,
                        "pe_ratio": r.pe_ratio,
                        "composite_score": r.composite_score,
                        "verdict": r.verdict,
                        "dimension_scores": {
                            "value": r.dimension_scores.value,
                            "growth": r.dimension_scores.growth,
                            "quality": r.dimension_scores.quality,
                            "momentum": r.dimension_scores.momentum,
                        },
                        "short_summary": r.short_summary,
                        "error": r.error,
                    }
                    for r in results
                ],
                "count": len(results),
                "min_score": min_score,
                "timestamp": time.time(),
            }
        except (ValueError, TypeError, KeyError, ImportError, AttributeError) as exc:
            _log.warning("[DASH] Fundamentals screen failed: %s", exc)
            return {"error": str(exc), "results": [], "count": 0, "timestamp": time.time()}
