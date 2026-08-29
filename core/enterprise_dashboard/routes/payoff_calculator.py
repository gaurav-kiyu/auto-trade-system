"""Option Strategy Payoff Calculator API route for the Enterprise Dashboard.

Read-only decision-support visualization — the multi-leg payoff-curve
feature Sensibull/uTrade Algos are known for (see
docs/COMPETITIVE_ANALYSIS.md) that this project's dashboard didn't expose
anywhere, even though the underlying math already existed in
core/trading/option_strategy_builder.py.

Deliberately uses only that module's generic add_leg()/calculate_payoff_
profile() primitives - never its build_straddle()/build_iron_condor() preset
methods, which the module's own docstring flags as exact duplicates of the
real, live strategy engines (core/straddle_strategy.py,
core/iron_condor_strategy.py; docs/duplicate_code_register.md DUP-182/
DUP-116). This endpoint never places, sizes, or influences a real order -
it only computes a P&L curve for legs the user types in, for the same
before-you-trade "what does this look like" purpose Sensibull's payoff
diagram serves.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import Depends, Request

_log = logging.getLogger(__name__)

_MAX_LEGS = 8


def _parse_leg(raw: dict[str, Any]) -> dict[str, Any]:
    strike = float(raw["strike"])
    option_type = str(raw["option_type"]).upper()
    action = str(raw["action"]).upper()
    quantity = int(raw["quantity"])
    premium = float(raw["premium"])

    if strike <= 0:
        raise ValueError("strike must be positive")
    if option_type not in ("CE", "PE"):
        raise ValueError(f"option_type must be CE or PE, got {option_type!r}")
    if action not in ("BUY", "SELL"):
        raise ValueError(f"action must be BUY or SELL, got {action!r}")
    if quantity <= 0 or quantity > 10_000:
        raise ValueError("quantity must be between 1 and 10,000")
    if premium < 0:
        raise ValueError("premium cannot be negative")

    return {
        "strike": strike, "option_type": option_type, "action": action,
        "quantity": quantity, "premium": premium,
    }


def register_payoff_calculator_routes(app, dashboard, admin_only, operator_or_admin) -> None:  # type: ignore[no-untyped-def]
    """Register the payoff-calculator compute API.

    Args:
        app: FastAPI application instance.
        dashboard: EnterpriseDashboard instance.
        admin_only: FastAPI Depends for admin role (unused here, kept for the
            same registration signature every routes/*.py module follows).
        operator_or_admin: FastAPI Depends for operator or admin role (unused
            here, same reason).

    """

    @app.post("/api/payoff-calculator/compute", tags=["PayoffCalculator"])
    async def api_payoff_calculator_compute(
        request: Request,
        user: Any = Depends(dashboard._auth_deps.require_auth_optional),
    ):
        try:
            body = await request.json()
            spot_price = float(body["spot_price"])
            if spot_price <= 0:
                return {"status": "error", "detail": "spot_price must be positive."}
            price_range_pct = float(body.get("price_range_pct", 0.20))
            if not (0 < price_range_pct <= 1.0):
                return {"status": "error", "detail": "price_range_pct must be between 0 and 1."}

            raw_legs = body.get("legs") or []
            if not raw_legs:
                return {"status": "error", "detail": "At least one leg is required."}
            if len(raw_legs) > _MAX_LEGS:
                return {"status": "error", "detail": f"At most {_MAX_LEGS} legs are supported."}
            legs = [_parse_leg(leg) for leg in raw_legs]
        except (KeyError, ValueError, TypeError) as exc:
            return {"status": "error", "detail": str(exc)}

        try:
            from core.trading.option_strategy_builder import OptionStrategyBuilder

            builder = OptionStrategyBuilder(spot_price)
            for leg in legs:
                builder.add_leg(**leg)
            profile = builder.calculate_payoff_profile(price_range_pct=price_range_pct)
        except (ImportError, ValueError, TypeError, ZeroDivisionError) as exc:
            _log.warning("[DASH] Payoff calculation failed: %s", exc)
            return {"status": "error", "detail": str(exc)}

        return {
            "status": "ok",
            "max_profit": profile.max_profit,
            "max_loss": profile.max_loss,
            "break_evens": profile.break_evens,
            "net_premium": profile.net_premium,
            "payoff_curve": profile.payoff_curve,
        }
