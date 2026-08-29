"""Webhook and options chain route registration for the Enterprise Dashboard.

Handles: /signals/inject, /chain/{index_name}.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from fastapi import Depends, Request

_log = logging.getLogger(__name__)


def _route_signal_via_dispatcher(body: dict[str, Any], dashboard: Any = None) -> dict[str, Any]:
    """Route an incoming signal through the Multi-Asset Strategy Dispatcher.

    Attempts to resolve the dispatcher from the DI container and route the
    signal. If unavailable, falls back to advisory queuing.

    Args:
        body: Signal dict with keys: symbol, direction, score, price, etc.
        dashboard: Unused — kept for API consistency with other route helpers.

    Returns:
        Routing result dict with status and action details.
    """
    symbol = str(body.get("symbol", ""))
    if not symbol:
        return {"status": "skipped", "reason": "no_symbol", "ts": time.time()}

    # Try to resolve dispatcher from DI container
    try:
        from core.di_container import get_container
        from core.strategy.multi_asset_dispatcher import MultiAssetStrategyDispatcher
        container = get_container()
        dispatcher = container.try_resolve(MultiAssetStrategyDispatcher)
        if dispatcher is not None:
            result = dispatcher.route(symbol=symbol, signal=body)
            _log.info("[WEBHOOK] Routed %s -> %s (action=%s engine=%s)",
                      symbol, result.asset_class, result.action, result.engine)
            return {
                "status": "routed",
                "symbol": symbol,
                "asset_class": result.asset_class,
                "action": result.action,
                "engine": result.engine,
                "message": result.message,
                "ts": time.time(),
            }
    except (ImportError, ValueError, TypeError, AttributeError, RuntimeError) as exc:
        _log.debug("[WEBHOOK] Dispatcher routing unavailable: %s", exc)

    return {"status": "queued", "ts": time.time()}


def register_webhook_routes(app, dashboard, admin_only, operator_or_admin) -> None:  # type: ignore[no-untyped-def]
    """Register webhook and options chain visualization routes.

    Args:
        app: FastAPI application instance.
        dashboard: EnterpriseDashboard instance.
        admin_only: FastAPI Depends for admin role.
        operator_or_admin: FastAPI Depends for operator or admin role.

    """

    @app.post("/signals/inject")
    async def signal_webhook(request: Request):  # type: ignore[no-untyped-def]
        """Receive a trading signal via webhook POST."""
        if not dashboard._cfg.get("webhook_enabled", False):
            return {"status": "disabled"}

        if dashboard._rate_limiter is not None:
            try:
                allowed = dashboard._rate_limiter.check("webhook")
                if not allowed:
                    return {"status": "rate_limited", "retry_after": 60}
            except (ValueError, AttributeError, TypeError, RuntimeError) as exc:
                _log.warning("[DASH] Webhook rate limiter error: %s", exc)

        try:
            body = await request.json()
        except (json.JSONDecodeError, ValueError) as exc:
            _log.warning("[DASH] Webhook JSON decode error: %s", exc)
            return {"status": "queued", "ts": time.time()}

        # Route signal through multi-asset dispatcher for active routing
        route_result = _route_signal_via_dispatcher(body, dashboard)

        # Also queue for legacy consumers
        if dashboard._signal_queue is not None:
            try:
                dashboard._signal_queue.put(body)
            except (ValueError, AttributeError, TypeError, RuntimeError) as exc:
                _log.warning("[DASH] Webhook signal queue error: %s", exc)

        if dashboard._signal_log is not None:
            try:
                dashboard._signal_log.append(body)
            except (ValueError, AttributeError, TypeError) as exc:
                _log.warning("[DASH] Webhook signal log error: %s", exc)

        return route_result

    @app.get("/chain/{index_name}")
    async def options_chain_viz(index_name: str, user: Any = Depends(dashboard._auth_deps.require_auth_optional)):  # type: ignore[no-untyped-def]
        """Get options chain data for a given index."""
        if not dashboard._cfg.get("chain_viz_enabled", False):
            return {"status": "disabled"}

        chain_data = {"index": index_name.upper()}

        market_data = dashboard._bot_refs.get("market_data")
        if market_data is not None:
            try:
                oc = market_data.get_option_chain(index_name.upper())
                if oc:
                    chain_data["option_chain"] = oc
            except (ValueError, TypeError, AttributeError, RuntimeError) as exc:
                _log.warning("[DASH] Option chain fetch error: %s", exc)

        chain_data["symbol"] = index_name.upper()
        chain_data["spot_price"] = dashboard._bot_refs.get(f"ltp_{index_name.upper()}", 0)
        return chain_data
