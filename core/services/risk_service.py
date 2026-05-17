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
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from core.datetime_ist import now_ist
from typing import Any

from core.logging import LoggingService
from core.ports.persistence.persistence_port import TradePersistencePort
from core.ports.risk.risk_port import PortfolioRiskMetrics, PositionSizingInput, RiskDecision, RiskEvaluation, RiskPort
from core.risk.limits.manager import LimitConfig, RiskLimitsManager
from core.risk.sizing.manager import PositionSizingManager
from core.safety_state import trip_hard_halt
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
    max_open_positions: int = 5           # Maximum concurrent positions
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
    - core/risk_engine.py
    - core/risk_engine_v2.py
    - core/trading_risk.py
    - Various risk checks throughout the codebase
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

        # Loss tracking
        self._consecutive_losses = 0
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
        Evaluate whether a trade should be allowed based on risk parameters.

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
                target = _safe_num(signal_data.get("target", 0), 0)
                signal_strength = _safe_num(signal_data.get("strength", 0), 0)

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

            except Exception as e:
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

        except Exception as e:
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

        except Exception as e:
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
                    consecutive_losses=self._consecutive_losses,
                    max_consecutive_losses=self.config.max_consecutive_losses,
                    sector_exposure=dict(sector_exposure),
                    symbol_exposure=symbol_exposure
                )

            except Exception as e:
                self._logger.error(f"Error getting portfolio risk metrics: {e}")
                # Return safe defaults
                return PortfolioRiskMetrics(
                    total_capital=100000.0,
                    used_capital=0.0,
                    available_capital=100000.0,
                    daily_pnl=0.0,
                    max_daily_loss=self.config.max_daily_loss,
                    current_drawdown=0.0,
                    max_drawdown=0.0,
                    open_positions_count=0,
                    max_open_positions=self.config.max_open_positions,
                    consecutive_losses=0,
                    max_consecutive_losses=self.config.max_consecutive_losses,
                    sector_exposure={},
                    symbol_exposure={}
                )

    def update_position(
        self,
        symbol: str,
        quantity: int,
        entry_price: float,
        timestamp: datetime
    ) -> None:
        """
        Update risk tracking with a new or modified position.

        Args:
            symbol: Trading symbol
            quantity: Position size (positive for long, negative for short)
            entry_price: Entry price per share/lot
            timestamp: Time of the position update
        """
        with self._lock:
            try:
                market_value = quantity * entry_price * self._get_lot_size(symbol)

                if quantity == 0:
                    # Remove position if quantity is zero
                    self._positions.pop(symbol, None)
                else:
                    # Update or add position
                    self._positions[symbol] = {
                        'quantity': quantity,
                        'entry_price': entry_price,
                        'market_value': market_value,
                        'timestamp': timestamp,
                        'symbol': symbol
                    }

                self._logger.debug(f"Updated position for {symbol}: {quantity} lots @ {entry_price}")

            except Exception as e:
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
                self._consecutive_losses = 0
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
            capital = self._get_capital()
            daily_pnl = self._get_daily_pnl()
            open_positions = self._get_open_positions()
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
        except Exception as e:
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

    def get_live_vix(self) -> float:
        """Get live India VIX for real-time risk adjustment (Phase 2)."""
        try:
            return self._get_live_vix()
        except Exception:
            return 20.0  # Default fallback

    def _lazy_vix_getter(self) -> float:
        """Lazy VIX getter that imports from index_trader after it's initialized."""
        try:
            import index_app.index_trader as m
            if m.DATA_ENGINE is not None:
                return m.DATA_ENGINE.get_india_vix()
        except Exception:
            pass
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
        except Exception:
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
        except Exception:
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
        except Exception:
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
        except Exception:
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
