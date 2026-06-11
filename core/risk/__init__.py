"""
Risk Management Module.

Exports:
  - GreeksEngine / GreeksLimitsConfig — Options Greeks Risk Engine (Phase 5)
  - GreeksCalculator — Portfolio Greeks computation
  - PortfolioGreeks — Aggregated portfolio Greeks data

AUTHORITATIVE: core.services.risk_service.RiskService is the single,
unquestionable authority for all execution risk decisions. No other module
may override or bypass RiskService.

DEPRECATED: Legacy risk modules (risk_engine.py, mandate_enforcer.py) have
been removed. Use RiskService directly for any new risk-related code.
"""

from core.risk.greeks_engine import (
    GreeksCheckLevel,
    GreeksCheckResult,
    GreeksEngine,
    GreeksEntryVerdict,
    GreeksLimitsConfig,
    GreeksLimits,
    GreeksCalculator,
    GreeksStressTester,
    GreeksStressResult,
    PortfolioGreeks,
    PositionGreeks,
    get_greeks_engine,
    reset_greeks_engine,
    LegacyOptionType as OptionType,
    LegacyOptionsGreeksEngine as OptionsGreeksEngine,
    LegacyPositionGreeksInput as PositionGreeksInput,
)

__all__ = [
    "GreeksCheckLevel",
    "GreeksCheckResult",
    "GreeksEngine",
    "GreeksEntryVerdict",
    "GreeksLimitsConfig",
    "GreeksLimits",
    "GreeksCalculator",
    "GreeksStressTester",
    "GreeksStressResult",
    "PortfolioGreeks",
    "PositionGreeks",
    "get_greeks_engine",
    "reset_greeks_engine",
    "OptionsGreeksEngine",
    "OptionType",
    "PositionGreeksInput",
]
