"""
Risk Management Module.

Exports from sub-subsystems:
  - GreeksEngine / GreeksLimitsConfig - Options Greeks Risk Engine
  - GreeksCalculator - Portfolio Greeks computation
  - PortfolioGreeks - Aggregated portfolio Greeks data
  - RiskLimitsManager - Daily loss, consecutive loss, portfolio limits
  - PositionSizingManager - Volatility-adjusted position sizing
  - MarginValidator - Pre-trade margin validation

AUTHORITATIVE: core.services.risk_service.RiskService is the single,
unquestionable authority for all execution risk decisions. No other module
may override or bypass RiskService.

DEPRECATED: Legacy risk modules (risk_engine.py, mandate_enforcer.py) have
been removed. Use RiskService directly for any new risk-related code.
"""

# Greeks Engine
from core.risk.greeks_engine import (
    GreeksCalculator,
    GreeksCheckLevel,
    GreeksCheckResult,
    GreeksEngine,
    GreeksEntryVerdict,
    GreeksLimits,
    GreeksLimitsConfig,
    GreeksStressResult,
    GreeksStressTester,
    PortfolioGreeks,
    PositionGreeks,
    get_greeks_engine,
    reset_greeks_engine,
    LegacyOptionType as OptionType,
    LegacyOptionsGreeksEngine as OptionsGreeksEngine,
)

# PositionGreeksInput re-exported from legacy engine for backward compatibility
from core.options_greeks_engine import PositionGreeksInput  # noqa: F811

# Legacy adapter (backward compat for orchestrator.py)
from core.risk.legacy_adapter import (
    RiskConfig as LegacyRiskConfig,
    RiskDecision as LegacyRiskDecision,
    RiskPortAdapter,
)

# Limits Manager
from core.risk.limits.manager import (
    LimitConfig,
    RiskLimitsManager,
)

# Sizing Manager
from core.risk.sizing.manager import (
    PositionSizingManager,
)

# Margin Validator
from core.risk.margin_validator import (
    MarginValidationResult,
    MarginValidator,
    get_margin_validator,
)

__all__ = [
    # Greeks Engine
    "GreeksCalculator",
    "GreeksCheckLevel",
    "GreeksCheckResult",
    "GreeksEngine",
    "GreeksEntryVerdict",
    "GreeksLimits",
    "GreeksLimitsConfig",
    "GreeksStressResult",
    "GreeksStressTester",
    "OptionsGreeksEngine",
    "OptionType",
    "PortfolioGreeks",
    "PositionGreeks",
    "PositionGreeksInput",
    "get_greeks_engine",
    "reset_greeks_engine",
    # Legacy Adapter
    "LegacyRiskConfig",
    "LegacyRiskDecision",
    "RiskPortAdapter",
    # Limits
    "LimitConfig",
    "RiskLimitsManager",
    # Sizing
    "PositionSizingManager",
    # Margin
    "MarginValidationResult",
    "MarginValidator",
    "get_margin_validator",
]
