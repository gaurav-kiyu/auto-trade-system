"""
Webhook and options chain route registration for the Enterprise Dashboard.

Handles: /signals/inject, /chain/{index_name}.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from fastapi import Depends, Request

_log = logging.getLogger(__name__)


def register_webhook_routes(app, dashboard, admin_only, operator_or_admin):
    """Register webhook and options chain visualization routes.

    Args:
        app: FastAPI application instance.
        dashboard: EnterpriseDashboard instance.
        admin_only: FastAPI Depends for admin role.
        operator_or_admin: FastAPI Depends for operator or admin role.
    """

    @app.post("/signals/inject")
    async def signal_webhook(request: Request):
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

        return {"status": "queued", "ts": time.time()}

    @app.get("/chain/{index_name}")
    async def options_chain_viz(index_name: str, user: Any = Depends(dashboard._auth_deps.require_auth_optional)):
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
