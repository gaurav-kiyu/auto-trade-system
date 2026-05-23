"""
AD-KIYU Risk Architecture — Single Authoritative Path Declaration.

AUTHORITATIVE RISK ENGINE:
    core.services.risk_service.RiskService (implements core.ports.risk.RiskPort)

ARCHITECTURE RULE:
    All risk decisions MUST route through RiskService.evaluate_trade().
    No direct calls to subsizers, margin validators, or limit checkers.
    No other "risk engine" may be loaded at runtime.

ENFORCEMENT:
    startup_validation.py validates single risk engine before trading begins.
    invariants/checks.py enforces at runtime that no duplicate risk engines are loaded.

DEPRECATED MODULES (do not import):
    - core/risk_engine.py                 → use RiskService via RiskPort
    - core/risk/authoritative_engine.py   → unnecessary wrapper; use RiskService directly
    - core/risk/limits/manager.py         → internal to RiskService only
    - core/risk/sizing/manager.py         → internal to RiskService only
    - core/risk/margin_validator.py       → internal to RiskService only

CALL GRAPH (authorized):
    index_trader.py / orchestrator.py
        → core.ports.risk.RiskPort (abstract contract)
            → core.services.risk_service.RiskService (singleton impl)
                → core.risk.limits.manager.RiskLimitsManager
                → core.risk.sizing.manager.PositionSizingManager
                → core.risk.margin_validator.MarginValidator
                → core.safety_state (trip_hard_halt, get_consecutive_losses)
                → core.capital_manager.CapitalManager (position scaling)

LATERAL ACCESS (authorized, not risk decisions):
    - core.position_sizer          → signal-based lot calculation (pre-risk)
    - core.kelly_sizer             → statistical sizing (advisory only)
    - core.exposure_limits         → concentration limits (post-risk gating)
    - core.capital_manager         → equity-based scaling (post-risk adjustment)
"""
from __future__ import annotations

import logging

_log = logging.getLogger(__name__)

AUTHORITATIVE_RISK_MODULE = "core.services.risk_service"
AUTHORITATIVE_RISK_CLASS = "RiskService"
AUTHORITATIVE_RISK_PORT = "core.ports.risk.RiskPort"

DEPRECATED_RISK_MODULES = {
    "core.risk_engine": "Use core.services.risk_service.RiskService via RiskPort",
    "core.risk.authoritative_engine": "Unnecessary wrapper; use RiskService directly",
    "core.predictive_risk": "Removed",
    "core.trading_risk": "Removed",
    "core.dynamic_risk_sizer": "Removed",
    "core.risk.risk_policy_engine": "Removed",
    "core.risk_engine_v2": "Removed",
}
