import logging
import warnings
from dataclasses import dataclass
from typing import Any

from core.state_manager import state_manager

warnings.warn(
    "core/risk/risk_engine.py is DEPRECATED. Use core.risk_engine instead.",
    DeprecationWarning,
    stacklevel=2
)

log = logging.getLogger("risk_engine")

@dataclass
class RiskCheckResult:
    is_allowed: bool
    reason: str = "Passed"
    suggested_qty: int | None = None
    risk_score: float = 0.0

class RiskEngine:
    """
    The Final Gatekeeper. 
    No order reaches the BrokerGateway without passing through the RiskEngine.
    
    Implements:
    - Pre-trade exposure limits
    - Daily loss circuit breakers
    - Position sizing based on volatility (VIX)
    - Portfolio concentration guards
    """

    def __init__(self, config: dict[str, Any]):
        self.config = config
        # Hard-halt flag
        self._hard_halt = False

    def trip_hard_halt(self, reason: str):
        """The nuclear option: blocks all further entries until manual reset."""
        self._hard_halt = True
        log.critical(f"!!! HARD HALT TRIPPED: {reason} !!!")

    def reset_halt(self):
        self._hard_halt = False
        log.info("Hard halt reset by user.")

    def validate_trade_intent(self, symbol: str, qty: int, price: float,
                             direction: str, risk_per_trade: float) -> RiskCheckResult:
        """
        Comprehensive pre-trade risk check.
        Returns RiskCheckResult indicating if the trade is allowed.
        """
        if self._hard_halt:
            return RiskCheckResult(False, "System is in HARD HALT mode")

        # 1. Daily Loss Check
        daily_pnl = state_manager.get("daily_pnl", 0.0)
        max_daily_loss = float(self.config.get("MAX_DAILY_LOSS", -5000))
        if daily_pnl <= max_daily_loss:
            self.trip_hard_halt(f"Daily loss limit breached: {daily_pnl} <= {max_daily_loss}")
            return RiskCheckResult(False, "Daily loss limit breached")

        # 2. Portfolio Exposure Check
        total_capital = float(self.config.get("BASE_CAPITAL", 100000))
        trade_value = qty * price
        max_exposure_pct = float(self.config.get("PORTFOLIO_MAX_SL_RISK_PCT", 0.02)) # 2%

        if (trade_value / total_capital) > max_exposure_pct:
            return RiskCheckResult(False, f"Trade exposure too high: {trade_value} exceeds {max_exposure_pct*100}% of capital")

        # 3. Concentration Guard (Prevent over-exposure to one index)
        active_pos = state_manager.get("active_positions", {})
        if symbol in active_pos:
            return RiskCheckResult(False, f"Position already open for {symbol}. No double-entry allowed.")

        # 4. Volatility-Based Sizing (VIX Scaling)
        vix = float(self.config.get("CURRENT_VIX", 15.0))
        vix_multiplier = 1.0
        if vix > 25: vix_multiplier = 0.5  # Halve size in high vol
        elif vix < 12: vix_multiplier = 1.2 # Increase size in low vol

        suggested_qty = int(qty * vix_multiplier)

        return RiskCheckResult(
            is_allowed=True,
            reason="Risk checks passed",
            suggested_qty=suggested_qty
        )

    def check_in_trade_risk(self, symbol: str, current_price: float, entry_price: float,
                            direction: str) -> tuple[bool, str]:
        """
        Monitors open positions for catastrophic failure.
        Returns (should_exit, reason).
        """
        # Example: Flash Crash Protection
        price_diff = (current_price - entry_price) / entry_price
        if direction == "CALL" and price_diff < -0.10: # 10% drop in underlying
            return True, "Flash crash protection triggered"
        if direction == "PUT" and price_diff > 0.10:
            return True, "Flash crash protection triggered"

        return False, "Stable"

# Singleton instance (initialized with config during startup)
risk_engine: RiskEngine | None = None

def init_risk_engine(config: dict[str, Any]):
    """
    DEPRECATED: Use core.services.risk_service.RiskService instead.
    This module exists for backward compatibility only.
    All new code should use RiskService.
    """
    global risk_engine
    risk_engine = RiskEngine(config)
