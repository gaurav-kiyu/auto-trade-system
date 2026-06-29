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
# Re-exports from options_greeks_engine (needed by risk_service.py)
from core.options_greeks_engine import (
    PositionGreeksInput,
)
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
)

# Legacy adapter (backward compat for orchestrator.py)
from core.risk.legacy_adapter import (
    RiskConfig as LegacyRiskConfig,
)
from core.risk.legacy_adapter import (
    RiskDecision as LegacyRiskDecision,
)
from core.risk.legacy_adapter import (
    RiskPortAdapter,
)

# Limits Manager
from core.risk.limits.manager import (
    LimitConfig,
    RiskLimitsManager,
)

# Margin Validator
from core.risk.margin_validator import (
    MarginValidationResult,
    MarginValidator,
    get_margin_validator,
)

# Sizing Manager
from core.risk.sizing.manager import (
    PositionSizingManager,
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
