"""
Risk Service Implementation

Implements a comprehensive risk management service that handles:
- Margin validation using broker APIs
- Volatility-based position sizing
- Portfolio-level risk limits
- Loss streak protection
- Trade quality validation
"""

from __future__ import annotations

import threading

__all__ = [
    "RiskServiceConfig",
    "RiskService",
    "PositionSizer",
    "PositionSpec",
    "CapitalManager",
    "CapitalState",
    "ScaleResult",
]
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

# ── Consolidated re-exports from legacy modules ──
# These are the canonical import targets for tier-based position sizing
# and capital scaling. The legacy modules (core.position_sizer, core.capital_manager)
# remain as deprecated wrappers for backward compatibility.
from core.position_sizer import PositionSizer, PositionSpec  # noqa: F401
from core.capital_manager import CapitalManager, CapitalState, ScaleResult  # noqa: F401

from core.datetime_ist import now_ist
from core.logging import LoggingService
from core.ports.persistence.persistence_port import TradePersistencePort
from core.ports.risk.risk_port import PortfolioRiskMetrics, PositionSizingInput, RiskDecision, RiskEvaluation, RiskPort
from core.risk.limits.manager import LimitConfig, RiskLimitsManager
from core.risk.sizing.manager import PositionSizingManager
from core.risk import (
    OptionType,
    OptionsGreeksEngine,
    PositionGreeksInput,
)
from core.safety_state import (
    get_consecutive_losses,
    reset_consecutive_losses,
    trip_hard_halt,
)
from core.utils_numeric import safe_num as _safe_num


@dataclass
class RiskServiceConfig:
    """Configuration for the risk service."""
    # Position sizing
    default_risk_per_trade: float = 0.02  # 2% of capital per trade
    max_risk_per_trade: float = 0.05      # 5% maximum per trade

    # Daily limits
    max_daily_loss: float = -2000.0       # Maximum daily loss in currency
    max_daily_trades: int = 10            # Maximum trades per day

    # Portfolio limits
    max_open_positions: int = 1           # Maximum concurrent positions (default 1, config via MAX_OPEN)
    max_portfolio_risk: float = 0.25      # 25% of capital at risk

    # Loss protection
    max_consecutive_losses: int = 3       # Stop trading after N consecutive losses
    loss_reset_hours: int = 6             # Hours after which loss counter resets

    # Volatility adjustment
    vix_threshold_low: float = 15.0       # VIX below this = low volatility
    vix_threshold_high: float = 35.0      # VIX above this = high volatility
    vix_size_multiplier_low: float = 1.2  # Increase size in low volatility
    vix_size_multiplier_high: float = 0.6 # Decrease size in high volatility

    # Margin requirements
    margin_safety_factor: float = 0.8     # Only use 80% of available margin

    # Quality checks
    min_volume_ratio: float = 0.5         # Minimum volume ratio for entry
    max_spread_pct: float = 2.0           # Maximum bid-ask spread percentage
    max_slippage_pct: float = 1.0         # Maximum expected slippage percentage


class RiskService(RiskPort):
    """
    Comprehensive risk management service.

    Consolidates functionality from:
    - core/risk_engine.py (removed in v2.54)
    - Various legacy risk checks throughout the codebase
    """

    def __init__(
        self,
        config: RiskServiceConfig | None = None,
        trade_persistence: TradePersistencePort | None = None,
        get_capital_fn: Callable[[], float] | None = None,
        get_open_positions_fn: Callable[[], int] | None = None,
        get_daily_pnl_fn: Callable[[], float] | None = None,
        get_volatility_fn: Callable[[str], float] | None = None,
        get_margin_fn: Callable[[str, int], float] | None = None,
        get_live_vix_fn: Callable[[], float] | None = None
    ):
        self.config = config or RiskServiceConfig()
        self.limits = RiskLimitsManager(LimitConfig(
            max_daily_loss=self.config.max_daily_loss,
            max_daily_trades=self.config.max_daily_trades,
            max_open_positions=self.config.max_open_positions,
            max_portfolio_risk=self.config.max_portfolio_risk,
            max_consecutive_losses=self.config.max_consecutive_losses
        ))
        self.sizing = PositionSizingManager(self.config)

        # Dependency injection for external data
        self._get_capital = get_capital_fn or (lambda: 100000.0)  # Default 1L capital
        self._get_open_positions = get_open_positions_fn or (lambda: 0)
        self._get_daily_pnl = get_daily_pnl_fn or (lambda: 0.0)
        self._get_volatility = get_volatility_fn or (lambda symbol: 20.0)  # Default VIX 20
        self._get_margin = get_margin_fn or (lambda symbol, qty: 0.0)  # Default no margin
        self._get_live_vix = get_live_vix_fn or (lambda: 20.0)  # Live VIX for real-time risk adjustment

        # Persistence for historical data
        self._trade_persistence = trade_persistence

        # Thread safety
        self._lock = threading.RLock()

        # Greeks engine for options risk
        self._greeks_engine: OptionsGreeksEngine | None = None

        # Loss tracking - single source of truth in safety_state
        self._last_loss_reset = now_ist()
        self._recent_losses: list[datetime] = []
        self._peak_pnl = 0.0
        self._max_drawdown = 0.0

        # Position tracking
        self._positions: dict[str, dict[str, Any]] = {}

        # Initialize logger
        self._logger = LoggingService(
            log_dir="logs",
            log_filename_prefix="risk_service_",
            retain_days=30,
            json_log_file="",
            version="UNKNOWN",
            enable_correlation_ids=True,
            enable_contextual_logging=True
        )

        self._logger.info("RiskService initialized")

    def evaluate_trade(
        self,
        symbol: str,
        signal_data: dict[str, Any],
        portfolio_metrics: PortfolioRiskMetrics
    ) -> RiskEvaluation:
        """
        NOTE: Primary evaluate_trade. This is the authoritative implementation.
        Risk decisions route through RiskPort → RiskService per the architecture
        declared in core/risk/__init__.py.

        Args:
            symbol: Trading symbol
            signal_data: Signal information (direction, strength, price, etc.)
            portfolio_metrics: Current portfolio risk metrics

        Returns:
            RiskEvaluation indicating whether the trade is allowed and any constraints
        """
        with self._lock:
            try:
                # Extract signal information
                direction = signal_data.get("direction", "").upper()
                entry_price = _safe_num(signal_data.get("price", 0), 0)
                stop_loss = _safe_num(signal_data.get("stop_loss", 0), 0)
                _safe_num(signal_data.get("target", 0), 0)
                _safe_num(signal_data.get("strength", 0), 0)

                if not direction or entry_price <= 0:
                    return RiskEvaluation(
                        decision=RiskDecision.DENIED,
                        reason="Invalid signal data: missing direction or price",
                        risk_score=0.0
                    )

                # Run all risk checks in order of severity
                checks = [
                    self._check_daily_loss_limit,
                    self._check_consecutive_losses,
                    self._check_portfolio_limits,
                    self._check_greeks_limits,     # Options Greeks Risk Engine
                    self._check_margin_requirements,
                    self._check_trade_quality,
                    self._check_position_sizing_limits
                ]

                for check_func in checks:
                    evaluation = check_func(symbol, signal_data, portfolio_metrics)
                    if evaluation.decision == RiskDecision.DENIED:
                        return evaluation

                # If all checks pass, calculate recommended position size
                sizing_input = PositionSizingInput(
                    symbol=symbol,
                    entry_price=entry_price,
                    stop_loss_price=stop_loss,
                    capital_available=portfolio_metrics.available_capital,
                    risk_per_trade=self.config.default_risk_per_trade,
                    lot_size=self._get_lot_size(symbol),
                    volatility=self._get_volatility(symbol),
                    existing_exposure=portfolio_metrics.symbol_exposure.get(symbol, 0.0)
                )

                recommended_size = self.calculate_position_size(sizing_input)

                return RiskEvaluation(
                    decision=RiskDecision.ALLOWED,
                    reason="All risk checks passed",
                    recommended_position_size=recommended_size,
                    max_allowed_position_size=recommended_size,
                    risk_score=self._calculate_risk_score(symbol, signal_data, portfolio_metrics)
                )

            except (KeyError, TypeError, ValueError, AttributeError) as e:
                self._logger.error(f"Error in risk evaluation for {symbol}: {e}")
                return RiskEvaluation(
                    decision=RiskDecision.DENIED,
                    reason=f"Risk evaluation error: {str(e)}",
                    risk_score=1.0
                )

    def calculate_position_size(
        self,
        sizing_input: PositionSizingInput
    ) -> int:
        """
        Calculate the appropriate position size for a trade.

        Args:
            sizing_input: Input parameters for position sizing

        Returns:
            Number of lots/contracts to trade
        """
        try:
            # Base position sizing using fixed fractional method
            if sizing_input.stop_loss_price <= 0 or sizing_input.entry_price <= 0:
                return 0

            risk_amount = sizing_input.capital_available * sizing_input.risk_per_trade
            price_diff = abs(sizing_input.entry_price - sizing_input.stop_loss_price)
            if price_diff <= 0:
                return 0

            raw_lots = risk_amount / (price_diff * sizing_input.lot_size)
            base_lots = max(1, int(raw_lots))

            # Apply volatility adjustment
            volatility_multiplier = self._get_volatility_multiplier(sizing_input.volatility)
            adjusted_lots = int(base_lots * volatility_multiplier)

            # Apply portfolio risk limits
            max_lots_by_portfolio = self._calculate_max_lots_by_portfolio(
                sizing_input, adjusted_lots
            )
            final_lots = min(adjusted_lots, max_lots_by_portfolio)

            # Apply per-trade limits
            max_lots_per_trade = self._get_max_lots_per_trade(sizing_input.symbol)
            final_lots = min(final_lots, max_lots_per_trade)

            # Ensure we don't exceed available capital/margin
            max_lots_by_capital = self._calculate_max_lots_by_capital(sizing_input)
            final_lots = min(final_lots, max_lots_by_capital)

            return max(0, final_lots)

        except (ZeroDivisionError, TypeError, ValueError, AttributeError) as e:
            self._logger.error(f"Error calculating position size: {e}")
            return 0

    def validate_margin_requirements(
        self,
        symbol: str,
        quantity: int,
        capital_available: float
    ) -> bool:
        """
        Validate that sufficient margin is available for a position.

        Args:
            symbol: Trading symbol
            quantity: Position size in lots
            capital_available: Available capital

        Returns:
            True if margin requirements are satisfied, False otherwise
        """
        try:
            if quantity <= 0:
                return True

            margin_required = self._get_margin(symbol, quantity)
            margin_available = capital_available * self.config.margin_safety_factor

            return margin_required <= margin_available

        except (TypeError, ValueError, AttributeError, OSError) as e:
            self._logger.error(f"Error validating margin requirements: {e}")
            return False  # Fail safe

    def get_portfolio_risk_metrics(self) -> PortfolioRiskMetrics:
        """
        Get current portfolio risk metrics.

        Returns:
            PortfolioRiskMetrics object with current risk statistics
        """
        with self._lock:
            try:
                capital = self._get_capital()
                daily_pnl = self._get_daily_pnl()
                open_positions = self._get_open_positions()

                # Calculate drawdown
                peak_pnl = getattr(self, '_peak_pnl', 0.0)
                if daily_pnl > peak_pnl:
                    self._peak_pnl = daily_pnl
                current_drawdown = peak_pnl - daily_pnl
                max_drawdown = getattr(self, '_max_drawdown', 0.0)
                if current_drawdown > max_drawdown:
                    self._max_drawdown = current_drawdown

                # Get position and sector exposure
                symbol_exposure = {}
                sector_exposure = defaultdict(float)

                total_exposure = 0.0
                for symbol, position in self._positions.items():
                    exposure = position.get('market_value', 0.0)
                    symbol_exposure[symbol] = exposure
                    total_exposure += exposure
                    # Simplified sector mapping - in reality this would come from config
                    sector = self._get_sector_for_symbol(symbol)
                    sector_exposure[sector] += exposure

                return PortfolioRiskMetrics(
                    total_capital=capital,
                    used_capital=total_exposure,
                    available_capital=max(0, capital - total_exposure),
                    daily_pnl=daily_pnl,
                    max_daily_loss=self.config.max_daily_loss,
                    current_drawdown=current_drawdown,
                    max_drawdown=self._max_drawdown,
                    open_positions_count=open_positions,
                    max_open_positions=self.config.max_open_positions,
                    consecutive_losses=get_consecutive_losses(),
                    max_consecutive_losses=self.config.max_consecutive_losses,
                    sector_exposure=dict(sector_exposure),
                    symbol_exposure=symbol_exposure
                )

            except (KeyError, TypeError, ValueError, ZeroDivisionError) as e:
                self._logger.error(f"Error getting portfolio risk metrics: {e}", exc_info=True)
                # Fail-closed: return metrics that will block trading
                return PortfolioRiskMetrics(
                    total_capital=0.0,
                    used_capital=0.0,
                    available_capital=0.0,
                    daily_pnl=-999999.0,
                    max_daily_loss=self.config.max_daily_loss,
                    current_drawdown=1.0,
                    max_drawdown=0.0,
                    open_positions_count=999,
                    max_open_positions=0,
                    consecutive_losses=999,
                    max_consecutive_losses=self.config.max_consecutive_losses,
                    sector_exposure={},
                    symbol_exposure={}
                )

    def update_position(
        self,
        symbol: str,
        quantity: int,
        entry_price: float,
        timestamp: datetime,
        option_type: str = "CE",
        strike: float | None = None,
        iv: float | None = None,
        tte_days: float | None = None,
    ) -> None:
        """
        Update risk tracking with a new or modified position.

        Args:
            symbol: Trading symbol
            quantity: Position size (positive for long, negative for short)
            entry_price: Entry price per share/lot
            timestamp: Time of the position update
            option_type: Option type ("CE" or "PE", default "CE")
            strike: Strike price (defaults to entry_price if None)
            iv: Implied volatility (defaults to 0.15 if None)
            tte_days: Days to expiry (defaults to 3.0 if None)
        """
        with self._lock:
            try:
                market_value = quantity * entry_price * self._get_lot_size(symbol)

                if quantity == 0:
                    # Remove position if quantity is zero
                    self._positions.pop(symbol, None)
                else:
                    # Update or add position with Greeks-relevant metadata
                    self._positions[symbol] = {
                        'quantity': quantity,
                        'entry_price': entry_price,
                        'market_value': market_value,
                        'timestamp': timestamp,
                        'symbol': symbol,
                        'option_type': option_type.upper() if option_type in ("CE", "PE") else "CE",
                        'strike': float(strike) if strike is not None else float(entry_price),
                        'iv': float(iv) if iv is not None else 0.15,
                        'tte_days': float(tte_days) if tte_days is not None else 3.0,
                    }

                self._logger.debug(f"Updated position for {symbol}: {quantity} lots @ {entry_price}")

            except (KeyError, TypeError, ValueError, AttributeError) as e:
                self._logger.error(f"Error updating position for {symbol}: {e}")

    def remove_position(self, symbol: str) -> None:
        """
        Remove a position from risk tracking.

        Args:
            symbol: Trading symbol to remove
        """
        with self._lock:
            self._positions.pop(symbol, None)
            self._logger.debug(f"Removed position for {symbol}")

    def reset_daily_metrics(self) -> None:
        """Reset daily risk metrics (called at start of new trading day)."""
        with self._lock:
            self._peak_pnl = 0.0
            self._max_drawdown = 0.0
            # Reset loss counter if enough time has passed
            hours_since_reset = (now_ist() - self._last_loss_reset).total_seconds() / 3600
            if hours_since_reset >= self.config.loss_reset_hours:
                reset_consecutive_losses()
                self._last_loss_reset = now_ist()
            self._logger.info("Daily risk metrics reset")

    def health_check(self) -> dict[str, Any]:
        """
        Perform a health check on the risk management service.

        Returns:
            Dictionary containing health check results
        """
        try:
            # Check critical components directly to catch errors
            self._get_capital()
            self._get_daily_pnl()
            self._get_open_positions()
            live_vix = self.get_live_vix()

            # If we get here, basic components work, get full metrics
            metrics = self.get_portfolio_risk_metrics()
            return {
                "status": "healthy",
                "service": "RiskService",
                "config": {
                    "max_daily_loss": self.config.max_daily_loss,
                    "max_open_positions": self.config.max_open_positions,
                    "max_consecutive_losses": self.config.max_consecutive_losses,
                    "default_risk_per_trade": self.config.default_risk_per_trade
                },
                "metrics": {
                    "capital": metrics.total_capital,
                    "daily_pnl": metrics.daily_pnl,
                    "open_positions": metrics.open_positions_count,
                    "consecutive_losses": metrics.consecutive_losses,
                    "available_capital": metrics.available_capital,
                    "live_vix": live_vix
                }
            }
        except (KeyError, TypeError, ValueError, AttributeError) as e:
            self._logger.error(f"Risk service health check failed: {e}")
            return {
                "status": "unhealthy",
                "service": "RiskService",
                "error": str(e)
            }

    # Private helper methods

    def _check_daily_loss_limit(
        self,
        symbol: str,
        signal_data: dict[str, Any],
        portfolio_metrics: PortfolioRiskMetrics
    ) -> RiskEvaluation:
        """Check if daily loss limit would be exceeded."""
        if portfolio_metrics.daily_pnl <= self.config.max_daily_loss:
            trip_hard_halt(
                f"Daily loss limit breached: {portfolio_metrics.daily_pnl} <= {self.config.max_daily_loss}",
                source="RiskService._check_daily_loss_limit",
            )
            return RiskEvaluation(
                decision=RiskDecision.DENIED,
                reason=f"Daily loss limit reached: {portfolio_metrics.daily_pnl:.2f} <= {self.config.max_daily_loss:.2f}",
                risk_score=1.0
            )
        return RiskEvaluation(
            decision=RiskDecision.ALLOWED,
            reason="Daily loss limit check passed",
            risk_score=0.0
        )

    def _check_consecutive_losses(
        self,
        symbol: str,
        signal_data: dict[str, Any],
        portfolio_metrics: PortfolioRiskMetrics
    ) -> RiskEvaluation:
        """Check if consecutive loss limit would be exceeded."""
        if portfolio_metrics.consecutive_losses >= self.config.max_consecutive_losses:
            trip_hard_halt(
                f"Consecutive loss limit breached: {portfolio_metrics.consecutive_losses} >= {self.config.max_consecutive_losses}",
                source="RiskService._check_consecutive_losses",
            )
            return RiskEvaluation(
                decision=RiskDecision.DENIED,
                reason=f"Consecutive loss limit reached: {portfolio_metrics.consecutive_losses} >= {self.config.max_consecutive_losses}",
                risk_score=1.0
            )
        return RiskEvaluation(
            decision=RiskDecision.ALLOWED,
            reason="Consecutive loss limit check passed",
            risk_score=0.0
        )

    def _check_portfolio_limits(
        self,
        symbol: str,
        signal_data: dict[str, Any],
        portfolio_metrics: PortfolioRiskMetrics
    ) -> RiskEvaluation:
        """Check portfolio-level limits."""
        if portfolio_metrics.open_positions_count >= self.config.max_open_positions:
            return RiskEvaluation(
                decision=RiskDecision.DENIED,
                reason=f"Maximum open positions reached: {portfolio_metrics.open_positions_count} >= {self.config.max_open_positions}",
                risk_score=0.8
            )

        # Check portfolio risk percentage
        current_risk = self._estimate_portfolio_risk()
        if current_risk > self.config.max_portfolio_risk:
            return RiskEvaluation(
                decision=RiskDecision.DENIED,
                reason=f"Portfolio risk limit reached: {current_risk:.2%} > {self.config.max_portfolio_risk:.2%}",
                risk_score=0.9
            )

        return RiskEvaluation(
            decision=RiskDecision.ALLOWED,
            reason="Portfolio limits check passed",
            risk_score=0.1
        )

    def _check_margin_requirements(
        self,
        symbol: str,
        signal_data: dict[str, Any],
        portfolio_metrics: PortfolioRiskMetrics
    ) -> RiskEvaluation:
        """Check margin requirements using ACTUAL position size, not test_quantity=1."""
        entry_price = _safe_num(signal_data.get("price", 0), 0)
        if entry_price <= 0:
            return RiskEvaluation(
                decision=RiskDecision.DENIED,
                reason="Invalid price for margin check",
                risk_score=0.5
            )

        lot_size = self._get_lot_size(symbol)

        # CRITICAL FIX: Calculate quantity from position sizing (NOT test_quantity=1)
        # Priority: 1) signal_data.quantity, 2) calculate from risk-based sizing, 3) 1 lot minimum
        intended_quantity = _safe_num(signal_data.get("quantity"), None)

        if intended_quantity is None or intended_quantity <= 0:
            # Calculate from position sizing using risk-based approach
            risk_amount = portfolio_metrics.available_capital * self.config.default_risk_per_trade
            stop_loss_pct = _safe_num(signal_data.get("stop_loss_pct"), 0.05)

            if stop_loss_pct > 0 and entry_price > 0:
                # Calculate max quantity based on risk
                max_risk_amount = risk_amount
                risk_per_share = entry_price * stop_loss_pct
                calculated_qty = int(max_risk_amount / risk_per_share) if risk_per_share > 0 else 1
                intended_quantity = max(1, min(calculated_qty, lot_size * 5))  # Cap at 5 lots
            else:
                intended_quantity = 1  # Minimum 1 lot

        # Ensure at least 1 lot
        if intended_quantity <= 0:
            intended_quantity = 1

        # Validate margin with ACTUAL calculated quantity (not test_quantity=1)
        if not self.validate_margin_requirements(symbol, intended_quantity, portfolio_metrics.available_capital):
            return RiskEvaluation(
                decision=RiskDecision.DENIED,
                reason="Insufficient margin for position",
                risk_score=0.7
            )

        return RiskEvaluation(
            decision=RiskDecision.ALLOWED,
            reason="Margin requirements check passed",
            risk_score=0.1
        )

    def _check_trade_quality(
        self,
        symbol: str,
        signal_data: dict[str, Any],
        portfolio_metrics: PortfolioRiskMetrics
    ) -> RiskEvaluation:
        """Check trade quality factors."""
        # Volume ratio check
        volume_ratio = _safe_num(signal_data.get("volume_ratio"), 1.0)
        if volume_ratio < self.config.min_volume_ratio:
            return RiskEvaluation(
                decision=RiskDecision.DENIED,
                reason=f"Insufficient volume ratio: {volume_ratio:.2f} < {self.config.min_volume_ratio:.2f}",
                risk_score=0.6
            )

        # Spread check
        spread_pct = _safe_num(signal_data.get("spread_pct"), 0.0)
        if spread_pct > self.config.max_spread_pct:
            return RiskEvaluation(
                decision=RiskDecision.DENIED,
                reason=f"Excessive bid-ask spread: {spread_pct:.2f}% > {self.config.max_spread_pct:.2f}%",
                risk_score=0.6
            )

        return RiskEvaluation(
            decision=RiskDecision.ALLOWED,
            reason="Trade quality checks passed",
            risk_score=0.1
        )

    def _check_position_sizing_limits(
        self,
        symbol: str,
        signal_data: dict[str, Any],
        portfolio_metrics: PortfolioRiskMetrics
    ) -> RiskEvaluation:
        """Check position sizing limits."""
        # This is more of a informational check - we'll adjust size rather than deny
        entry_price = _safe_num(signal_data.get("price", 0), 0)
        stop_loss = _safe_num(signal_data.get("stop_loss", 0), 0)

        if entry_price > 0 and stop_loss > 0:
            price_diff = abs(entry_price - stop_loss)
            if price_diff < (entry_price * 0.01):  # Less than 1% SL/TP distance
                return RiskEvaluation(
                    decision=RiskDecision.ALLOWED,  # Warn but allow
                    reason=f"Very tight stop loss: {price_diff/entry_price:.2%} price distance",
                    risk_score=0.3,
                    recommended_position_size=1  # Suggest minimal size
                )

        return RiskEvaluation(
            decision=RiskDecision.ALLOWED,
            reason="Position sizing limits check passed",
            risk_score=0.0
        )

    def _check_greeks_limits(
        self,
        symbol: str,
        signal_data: dict[str, Any],
        portfolio_metrics: PortfolioRiskMetrics
    ) -> RiskEvaluation:
        """
        Check Options Greeks limits before allowing a trade.

        Uses OptionsGreeksEngine to validate delta/gamma/theta/vega exposure
        against configured limits. Skips gracefully if signal_data lacks
        required Greeks parameters.
        """
        try:
            # Lazy-init Greeks engine
            if self._greeks_engine is None:
                self._greeks_engine = OptionsGreeksEngine()

            direction = signal_data.get("direction", "").upper()
            entry_price = _safe_num(signal_data.get("price", 0), 0)

            if not direction or entry_price <= 0:
                return RiskEvaluation(
                    decision=RiskDecision.ALLOWED,
                    reason="Greeks check skipped - missing direction or price",
                    risk_score=0.0
                )

            # Determine option type from direction
            if direction in ("CE", "CALL", "LONG"):
                option_type = OptionType.CE
            elif direction in ("PE", "PUT", "SHORT"):
                option_type = OptionType.PE
            else:
                return RiskEvaluation(
                    decision=RiskDecision.ALLOWED,
                    reason="Greeks check skipped - unknown option type",
                    risk_score=0.0
                )

            # Determine trade direction (LONG = buying, SHORT = selling/writing)
            trade_direction = "LONG"
            if direction in ("SHORT", "SELL"):
                trade_direction = "SHORT"

            # Build inputs for Greeks computation
            tte_days = _safe_num(signal_data.get("tte_days"), None)
            iv = _safe_num(signal_data.get("iv"), None)
            strike = _safe_num(signal_data.get("strike"), None)
            quantity_lots = _safe_num(signal_data.get("quantity"), 1)
            quantity_lots = max(1, int(quantity_lots))

            # Use defaults for missing params (Greeks engine handles edge cases)
            tte_days = tte_days if tte_days is not None else 3.0
            iv = iv if iv is not None else 0.15
            strike = strike if strike is not None else entry_price

            proposed = PositionGreeksInput(
                symbol=symbol,
                option_type=option_type,
                direction=trade_direction,
                spot=entry_price,
                strike=strike,
                tte_days=tte_days,
                iv=iv,
                quantity_lots=quantity_lots,
            )

            # Build existing positions from current portfolio with stored attributes
            existing = []
            for sym, pos in self._positions.items():
                pos_dir = "LONG" if pos.get("quantity", 0) >= 0 else "SHORT"
                qty = abs(_safe_num(pos.get("quantity", 0), 0))
                stored_ot = str(pos.get("option_type", "CE")).upper()
                pos_ot = OptionType.CE if stored_ot == "CE" else OptionType.PE
                existing.append(PositionGreeksInput(
                    symbol=sym,
                    option_type=pos_ot,
                    direction=pos_dir,
                    spot=_safe_num(pos.get("entry_price", entry_price), entry_price),
                    strike=_safe_num(pos.get("strike"), entry_price),
                    tte_days=_safe_num(pos.get("tte_days"), tte_days),
                    iv=_safe_num(pos.get("iv"), iv),
                    quantity_lots=max(1, int(qty)),
                ))

            # Run Greeks check
            result = self._greeks_engine.check_pre_trade_greeks(proposed, existing)

            if result.status.value == "BLOCK":
                reasons = "; ".join(result.reasons)
                return RiskEvaluation(
                    decision=RiskDecision.DENIED,
                    reason=f"Greeks limit blocked: {reasons}",
                    risk_score=0.9
                )

            if result.status.value == "WARN":
                reasons = "; ".join(result.reasons)
                return RiskEvaluation(
                    decision=RiskDecision.ALLOWED,
                    reason=f"Greeks limit warning: {reasons}",
                    risk_score=0.4
                )

            return RiskEvaluation(
                decision=RiskDecision.ALLOWED,
                reason="Greeks limits check passed",
                risk_score=0.0
            )

        except (ValueError, TypeError, AttributeError, KeyError, ArithmeticError) as exc:
            self._logger.warning(f"Greeks check failed for {symbol}: {exc}")
            return RiskEvaluation(
                decision=RiskDecision.ALLOWED,
                reason=f"Greeks check errored (non-blocking): {exc}",
                risk_score=0.2
            )

    # ── Tier-Based Position Sizing (consolidated from core.position_sizer) ──
    # Delegates to PositionSizer for tier/regime/score-based sizing.

    def calculate_tier_position_size(
        self,
        score: int,
        tier: str,
        regime: str,
        max_lots: int,
        atr: float = 0.0,
        capital: float = 100_000.0,
    ) -> Any:
        """
        Calculate position size using tier/regime/score-based method.

        This delegates to the legacy PositionSizer for backward compatibility.
        New code should prefer ``calculate_position_size()`` for risk-based sizing.

        Args:
            score:     Final adjusted signal score (0-100)
            tier:      Signal tier (STRONG / MODERATE / WEAK / IGNORE)
            regime:    Market regime string
            max_lots:  Maximum configured lots per trade
            atr:       Current ATR
            capital:   Available capital

        Returns:
            PositionSpec dataclass with effective_pct and lots
        """
        try:
            from core.position_sizer import PositionSizer
            return PositionSizer.calculate(
                score=score, tier=tier, regime=regime,
                max_lots=max_lots, atr=atr, capital=capital,
            )
        except (ImportError, ValueError, TypeError, AttributeError) as e:
            self._logger.warning(f"Tier-based sizing failed (legacy module): {e}")
            # Fallback: return a minimal PositionSpec-compatible result
            from core.position_sizer import PositionSpec
            return PositionSpec(
                tier=tier, regime=regime, score=score,
                tier_base_pct=0.0, regime_adj=0.0, score_adj=0.0,
                effective_pct=0.0, lots=0,
                reasoning=f"Fallback: {e}",
            )

    # ── Capital Scaling (consolidated from core.capital_manager) ──
    # Delegates to CapitalManager for equity-aware position scaling.

    def _get_capital_manager(self):
        """Lazy-init CapitalManager for equity tracking (thread-safe)."""
        if hasattr(self, '_capital_manager') and self._capital_manager is not None:
            return self._capital_manager
        with self._lock:
            if hasattr(self, '_capital_manager') and self._capital_manager is not None:
                return self._capital_manager
            from core.capital_manager import CapitalManager
            capital = self._get_capital()
            self._capital_manager = CapitalManager(
                initial_capital=capital,
                max_daily_loss=self.config.max_daily_loss,
                max_drawdown_pct=0.20,
            )
            return self._capital_manager

    def scale_position(self, base_lots: int, max_lots: int = 1) -> Any:
        """
        Apply equity-aware capital scaling to base_lots.

        Delegates to CapitalManager.scale() which computes:
        scale_factor = capital_growth x drawdown_factor x consec_loss_factor x daily_loss_factor

        Args:
            base_lots:  Lots recommended by position sizing
            max_lots:   Configured ceiling

        Returns:
            ScaleResult dataclass with scale_factor and scaled_lots
        """
        try:
            cm = self._get_capital_manager()
            return cm.scale(base_lots=base_lots, max_lots=max_lots)
        except (ImportError, ValueError, TypeError, AttributeError) as e:
            self._logger.warning(f"Capital scaling failed: {e}")
            from core.capital_manager import ScaleResult
            return ScaleResult(
                scale_factor=1.0, scaled_lots=base_lots,
                capital_growth=1.0, drawdown_factor=1.0,
                consec_loss_factor=1.0, daily_loss_factor=1.0,
                drawdown_pct=0.0, reasoning="Fallback: no scaling",
            )

    def record_trade_result(self, net_pnl: float, is_winner: bool) -> None:
        """
        Record a completed trade result for equity tracking.

        Delegates to CapitalManager.record_trade(). Updates internal equity
        curve, drawdown tracking, and consecutive loss counters.

        Args:
            net_pnl:     Net P&L from the trade (positive = profit)
            is_winner:   True if the trade was profitable
        """
        try:
            cm = self._get_capital_manager()
            cm.record_trade(net_pnl=net_pnl, is_winner=is_winner)
        except (ImportError, ValueError, TypeError, AttributeError) as e:
            self._logger.warning(f"Trade recording failed: {e}")

    def lock_profits(self, lock_pct: float = 0.50) -> float:
        """
        Extract a percentage of profits above initial capital to a locked pool.

        Delegates to CapitalManager.lock_profits(). Locked profit is removed
        from current_capital for safe-keeping.

        Args:
            lock_pct: Fraction of unrealised profits to lock (default 0.50)

        Returns:
            Amount locked (0.0 if no profit to lock)
        """
        try:
            cm = self._get_capital_manager()
            return cm.lock_profits(lock_pct=lock_pct)
        except (ImportError, ValueError, TypeError, AttributeError) as e:
            self._logger.warning(f"Profit locking failed: {e}")
            return 0.0

    def get_capital_state(self) -> dict[str, Any]:
        """
        Get current capital state summary.

        Delegates to CapitalManager.get_state().

        Returns:
            Dict with initial_capital, current_capital, peak_capital,
            locked_profit, daily_pnl, drawdown_pct, consecutive_losses, etc.
        """
        try:
            cm = self._get_capital_manager()
            return cm.get_state()
        except (ImportError, ValueError, TypeError, AttributeError) as e:
            self._logger.warning(f"Capital state fetch failed: {e}")
            return {
                "current_capital": self._get_capital(),
                "daily_pnl": self._get_daily_pnl(),
            }

    # ── Trading Policy Gates (consolidated from ProductionMandateEnforcer v2.53) ──

    def is_in_trading_window(self) -> bool:
        """NSE trading windows: 9:20-11:30 and 13:00-14:45 IST."""
        now = now_ist()
        morning_start = 9 * 60 + 20
        morning_end = 11 * 60 + 30
        afternoon_start = 13 * 60
        afternoon_end = 14 * 60 + 45
        current = now.hour * 60 + now.minute
        return (morning_start <= current <= morning_end) or (afternoon_start <= current <= afternoon_end)

    def should_skip_first_20_min(self) -> bool:
        """Skip first 20 minutes (9:20-9:40) to let market settle."""
        now = now_ist()
        current_mins = now.hour * 60 + now.minute
        market_open_mins = 9 * 60 + 20
        return current_mins < market_open_mins + 20

    def should_skip_last_45_min(self) -> bool:
        """Skip last 45 minutes (14:35-15:20) to avoid EOD volatility."""
        now = now_ist()
        current_mins = now.hour * 60 + now.minute
        market_close_mins = 15 * 60 + 20
        return current_mins > market_close_mins - 45

    def get_min_score_for_regime(self, regime: str) -> int:
        """Minimum signal score required by regime.

        Trending regimes need 68+, Sideways needs 73+, Choppy needs 78+.
        """
        reg = (regime or "").upper()
        if reg in ["TRENDING", "BULLISH"]:
            return 68
        elif reg in ["SIDEWAYS", "NEUTRAL"]:
            return 73
        elif reg in ["RANGE", "CHOPPY"]:
            return 78
        return 73

    def should_block_false_signal(self, score: int, iv_rank: float) -> bool:
        """Block when high score coincides with elevated IV (false signal pattern)."""
        return score >= 75 and iv_rank > 26

    def get_max_trades_per_day(self, vix: float | None = None, consecutive_losses: int = 0) -> int:
        """Maximum trades per day, reduced during high VIX or loss streaks."""
        v = vix if vix is not None else self._get_live_vix()
        if v > 28 or consecutive_losses >= 2:
            return 1
        elif v > 20:
            return 2
        return 4

    def get_live_vix(self) -> float:
        """Get live India VIX for real-time risk adjustment."""
        try:
            return self._get_live_vix()
        except (TypeError, ValueError, KeyError, AttributeError, OSError):
            return 20.0  # Default fallback

    def _lazy_vix_getter(self) -> float:
        """Lazy VIX getter - uses injected get_live_vix_fn with fallback."""
        try:
            vix = self._get_live_vix()
            if vix and vix > 0:
                return vix
        except (TypeError, ValueError, KeyError, AttributeError, OSError) as _ex:
            self._logger.debug(f"Could not fetch live VIX via injected getter: {_ex}")

        # Fallback: try via core.iv_rank
        try:
            from core.iv_rank import get_iv_rank
            rank = get_iv_rank()
            vix = rank._vix if hasattr(rank, '_vix') else None
            if vix and vix > 0:
                return vix
        except (ImportError, AttributeError, TypeError, ValueError, OSError) as _ex:
            self._logger.debug(f"Could not fetch live VIX via iv_rank: {_ex}")

        return 20.0

    def _get_lot_size(self, symbol: str) -> int:
        """Get lot size for a symbol."""
        # In a real implementation, this would come from reference data
        # For now, return common lot sizes
        lot_sizes = {
            "NIFTY": 50,
            "BANKNIFTY": 15,
            "FINNIFTY": 40,
            "SENSEX": 10
        }
        return lot_sizes.get(symbol, 50)  # Default to 50

    def _get_volatility_multiplier(self, volatility: float) -> float:
        """Get position size multiplier based on volatility."""
        if volatility <= self.config.vix_threshold_low:
            return self.config.vix_size_multiplier_low
        elif volatility >= self.config.vix_threshold_high:
            return self.config.vix_size_multiplier_high
        else:
            # Linear interpolation between thresholds
            ratio = (volatility - self.config.vix_threshold_low) / (self.config.vix_threshold_high - self.config.vix_threshold_low)
            ratio = max(0, min(1, ratio))  # Clamp to 0-1
            return self.config.vix_size_multiplier_low + (ratio * (self.config.vix_size_multiplier_high - self.config.vix_size_multiplier_low))

    def _get_max_lots_per_trade(self, symbol: str) -> int:
        """Get maximum lots allowed per trade for a symbol."""
        # Based on risk per trade configuration
        capital = self._get_capital()
        risk_amount = capital * self.config.max_risk_per_trade
        # Assume average SL of 5% of price and lot size of 50
        # This is a simplification - real calculation would be more precise
        approx_max_lots = int(risk_amount / (0.05 * 1000 * 50))  # Very rough estimate
        return max(1, approx_max_lots)

    def _calculate_max_lots_by_portfolio(
        self,
        sizing_input: PositionSizingInput,
        current_lots: int
    ) -> int:
        """Calculate maximum lots based on portfolio risk limits."""
        try:
            max_risk_amount = sizing_input.capital_available * self.config.max_portfolio_risk
            current_risk = sizing_input.capital_available * sizing_input.risk_per_trade

            if current_risk <= 0:
                return current_lots

            # Scale down if we're exceeding portfolio risk limits
            if current_risk > max_risk_amount:
                scale_factor = max_risk_amount / current_risk
                return max(1, int(current_lots * scale_factor))
            return current_lots
        except (TypeError, ValueError, ZeroDivisionError, AttributeError):
            return current_lots

    def _calculate_max_lots_by_capital(
        self,
        sizing_input: PositionSizingInput
    ) -> int:
        """Calculate maximum lots based on available capital."""
        try:
            # Simple capital-based limit: don't risk more than X% of capital on one trade
            max_risk_amount = sizing_input.capital_available * self.config.max_risk_per_trade
            if sizing_input.risk_per_trade <= 0:
                return 0

            # Recalculate lots based on max allowed risk
            price_diff = abs(sizing_input.entry_price - sizing_input.stop_loss_price)
            if price_diff <= 0 or sizing_input.lot_size <= 0:
                return 0

            max_lots = int(max_risk_amount / (price_diff * sizing_input.lot_size * sizing_input.risk_per_trade))
            return max(0, max_lots)
        except (TypeError, ValueError, ZeroDivisionError, AttributeError):
            return 0

    def _estimate_portfolio_risk(self) -> float:
        """Estimate current portfolio risk as a fraction of capital."""
        try:
            # This is a simplified estimation
            # In reality, would calculate VaR or similar metric
            metrics = self.get_portfolio_risk_metrics()
            if metrics.total_capital <= 0:
                return 0.0
            # Rough estimate: used capital / total capital
            return metrics.used_capital / metrics.total_capital
        except (TypeError, ValueError, ZeroDivisionError, AttributeError):
            return 0.0

    def _calculate_risk_score(
        self,
        symbol: str,
        signal_data: dict[str, Any],
        portfolio_metrics: PortfolioRiskMetrics
    ) -> float:
        """Calculate a risk score for the trade (0.0 to 1.0)."""
        try:
            score = 0.0

            # Daily loss utilization (0-0.3)
            if self.config.max_daily_loss < 0:
                loss_used = abs(portfolio_metrics.daily_pnl) / abs(self.config.max_daily_loss) if self.config.max_daily_loss != 0 else 0
                score += min(0.3, loss_used * 0.3)

            # Position concentration (0-0.2)
            total_cap = portfolio_metrics.total_capital
            used_cap = portfolio_metrics.used_capital
            if total_cap > 0:
                concentration = used_cap / total_cap
                score += min(0.2, concentration * 0.2)

            # Volatility factor (0-0.2)
            volatility = self._get_volatility(symbol)
            vol_factor = min(1.0, volatility / 50.0)  # Normalize to 50 VIX as max
            score += vol_factor * 0.2

            # Signal strength inverse (0-0.3) - weaker signals = higher risk
            strength = _safe_num(signal_data.get("strength", 50), 50)  # Assume 0-100 scale
            strength_risk = (100 - strength) / 100.0  # Invert so weak signal = high risk
            score += strength_risk * 0.3

            return min(1.0, max(0.0, score))
        except (TypeError, ValueError, ZeroDivisionError, AttributeError, KeyError):
            return 0.5  # Medium risk if calculation fails

    def _get_sector_for_symbol(self, symbol: str) -> str:
        """Get sector for a symbol (simplified mapping)."""
        sector_map = {
            "NIFTY": "INDEX",
            "BANKNIFTY": "INDEX",
            "FINNIFTY": "INDEX",
            "RELIANCE": "ENERGY",
            "TCS": "IT",
            "HDFCBANK": "FINANCIAL",
            "INFY": "IT",
            "ICICIBANK": "FINANCIAL",
            "KOTAKBANK": "FINANCIAL",
            "LT": "INDUSTRIAL",
            "SBIN": "FINANCIAL",
            "BHARTIARTL": "TELECOM",
            "ASIANPAINT": "CONSUMER",
            "MARUTI": "AUTOMOBILE",
            "HINDUNILVR": "CONSUMER",
            "AXISBANK": "FINANCIAL"
        }
        return sector_map.get(symbol, "OTHER")

    def get_required_margin_per_lot(self, symbol: str, price: float) -> float:
        """
        Get required margin per lot for a symbol.
        This is a simplified estimation - in production, broker API provides actual margin.
        """
        lot_size = self._get_lot_size(symbol)
        margin_percentage = 0.20  # Assume 20% margin requirement
        return price * lot_size * margin_percentage
