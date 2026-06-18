"""
Risk Management Domain Service - Clean Architecture Implementation

This service implements core risk management logic in a pure, testable manner
following Clean Architecture principles. All dependencies are injected through
interfaces, making this service easy to test and maintain.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from core.datetime_ist import now_ist

_log = logging.getLogger(__name__)

# Import domain models and value objects
from core.domains.risk.model import MarketConditions, PortfolioRiskMetrics, Position, RiskDecision, RiskLimits

# Import shared kernels


class RiskService:
    """
    Core risk management service.

    This service implements all risk management logic in a pure, testable manner
    without any external dependencies. All dependencies are injected through
    the constructor or method parameters.
    """

    def __init__(self, risk_limits: RiskLimits):
        self.risk_limits = risk_limits
        self._daily_pnl: float = 0.0
        self._daily_start_equity: float = risk_limits.account_equity
        self._consecutive_losses: int = 0
        self._peak_equity: float = risk_limits.account_equity
        self._risk_lock = threading.RLock()

    def evaluate_trade(
        self,
        symbol: str,
        direction: str,
        suggested_size: int,
        portfolio_state: dict[str, Any],
        market_conditions: MarketConditions
    ) -> RiskDecision:
        """
        Evaluate a proposed trade against all risk limits.

        This is the main entry point for pre-trade risk validation.
        """
        with self._risk_lock:
            # Reset daily tracking if needed (simplified)
            self._reset_daily_tracking()

            # Run all risk checks in sequence
            checks = [
            self._check_position_limits(symbol, suggested_size),
            self._check_daily_loss_limits(),
            self._check_drawdown_limits(),
            self._check_consecutive_losses(),
            self._check_portfolio_exposure(symbol, suggested_size, direction, portfolio_state),
            self._check_volatility_limits(symbol, market_conditions),
            self._check_liquidity_limits(symbol, suggested_size),
            self._check_correlation_risk(symbol, direction, suggested_size, portfolio_state),
            self._check_market_conditions_limits(market_conditions),
            self._check_max_positions_limit(portfolio_state),
        ]

        # If any check fails, return the first failure
        for check_result in checks:
            if not check_result.allowed:
                return check_result

        # All checks passed - calculate final position size
        final_size = self._calculate_final_position_size(
            symbol, suggested_size, direction, portfolio_state, market_conditions
        )

        return RiskDecision(
            allowed=True,
            reason="All risk checks passed",
            suggested_size=final_size,
            risk_metrics=self._calculate_trade_risk_metrics(
                symbol, final_size, direction, portfolio_state, market_conditions
            )
        )

    def _reset_daily_tracking(self):
        """Reset daily tracking at start of new trading day."""
        # Called from within _risk_lock in evaluate_trade() - no separate lock needed
        pass  # Simplified - in reality would check date change

    def _check_position_limits(self, symbol: str, suggested_size: int) -> RiskDecision:
        """Check individual position limits."""
        if suggested_size > self.risk_limits.max_position_size:
            return RiskDecision(
                allowed=False,
                reason=f"Position size {suggested_size} exceeds maximum {self.risk_limits.max_position_size}",
                suggested_size=self.risk_limits.max_position_size
            )
        return RiskDecision(allowed=True, reason="Position size within limits")

    def _check_daily_loss_limits(self) -> RiskDecision:
        """Check daily loss limits."""
        max_daily_loss = self.risk_limits.max_daily_loss
        if self._daily_pnl < -max_daily_loss:
            return RiskDecision(
                allowed=False,
                reason=f"Daily loss limit breached: {self._daily_pnl:.2f} < {-max_daily_loss:.2f}",
                suggested_size=0
            )
        return RiskDecision(allowed=True, reason="Daily loss limit OK")

    def _check_drawdown_limits(self) -> RiskDecision:
        """Check drawdown limits."""
        current_equity = self._get_current_equity()
        drawdown = self._calculate_drawdown(current_equity)
        max_drawdown = self.risk_limits.max_drawdown

        if drawdown > max_drawdown:
            return RiskDecision(
                allowed=False,
                reason=f"Drawdown limit breached: {drawdown:.2%} > {max_drawdown:.2%}",
                suggested_size=0
            )
        return RiskDecision(allowed=True, reason="Drawdown limit OK")

    def _check_consecutive_losses(self) -> RiskDecision:
        """Check consecutive losses limit."""
        max_consecutive = self.risk_limits.max_consecutive_losses
        if self._consecutive_losses >= max_consecutive:
            return RiskDecision(
                allowed=False,
                reason=f"Consecutive losses limit breached: {self._consecutive_losses} >= {max_consecutive}",
                suggested_size=0
            )
        return RiskDecision(allowed=True, reason="Consecutive losses limit OK")

    def _check_portfolio_exposure(
        self,
        symbol: str,
        suggested_size: int,
        direction: str,
        portfolio_state: dict[str, Any]
    ) -> RiskDecision:
        """Check portfolio-level exposure limits."""
        # Calculate new exposure if trade is taken
        current_exposure = self._calculate_current_exposure(portfolio_state)
        new_exposure = self._calculate_new_exposure(
            current_exposure, symbol, suggested_size, direction
        )

        max_exposure = self.risk_limits.max_portfolio_exposure
        if new_exposure > max_exposure:
            return RiskDecision(
                allowed=False,
                reason=f"Portfolio exposure limit breached: {new_exposure:.2%} > {max_exposure:.2%}",
                suggested_size=0
            )
        return RiskDecision(allowed=True, reason="Portfolio exposure within limits")

    def _check_volatility_limits(
        self,
        symbol: str,
        market_conditions: MarketConditions
    ) -> RiskDecision:
        """Check volatility-based limits."""
        current_volatility = market_conditions.volatility
        max_volatility = self.risk_limits.max_volatility

        if current_volatility > max_volatility:
            return RiskDecision(
                allowed=False,
                reason=f"Volatility too high: {current_volatility:.2%} > {max_volatility:.2%}",
                suggested_size=0
            )
        return RiskDecision(allowed=True, reason="Volatility within limits")

    def _check_liquidity_limits(self, symbol: str, suggested_size: int) -> RiskDecision:
        """Check liquidity limits."""
        max_size_for_liquidity = self.risk_limits.max_liquidity_size
        if suggested_size > max_size_for_liquidity:
            return RiskDecision(
                allowed=False,
                reason=f"Order size too large for current liquidity: {suggested_size} > {max_size_for_liquidity}",
                suggested_size=max_size_for_liquidity
            )
        return RiskDecision(allowed=True, reason="Liquidity sufficient")

    def _check_correlation_risk(
        self,
        symbol: str,
        direction: str,
        suggested_size: int,
        portfolio_state: dict[str, Any]
    ) -> RiskDecision:
        """Check correlation risk with existing positions."""
        max_correlation = self.risk_limits.max_correlation

        # Calculate correlation with existing positions
        correlation = self._calculate_max_correlation(symbol, direction, portfolio_state)

        if correlation > max_correlation:
            return RiskDecision(
                allowed=False,
                reason=f"Correlation risk too high: {correlation:.2f} > {max_correlation:.2f}",
                suggested_size=0
            )
        return RiskDecision(allowed=True, reason="Correlation risk acceptable")

    def _check_market_conditions_limits(self, market_conditions: MarketConditions) -> RiskDecision:
        """Check if market conditions allow trading."""
        # Example: don't trade during extreme volatility
        if market_conditions.volatility > self.risk_limits.max_volatility:
            return RiskDecision(
                allowed=False,
                reason=f"Market volatility too high: {market_conditions.volatility:.2%}",
                suggested_size=0
            )
        return RiskDecision(allowed=True, reason="Market conditions acceptable")

    def _check_max_positions_limit(self, portfolio_state: dict[str, Any]) -> RiskDecision:
        """Check maximum number of open positions."""
        current_positions = len(portfolio_state.get('positions', []))
        max_positions = self.risk_limits.max_open_positions

        if current_positions >= max_positions:
            return RiskDecision(
                allowed=False,
                reason=f"Maximum positions limit reached: {current_positions} >= {max_positions}",
                suggested_size=0
            )
        return RiskDecision(allowed=True, reason="Position count within limits")

    def _calculate_final_position_size(
        self,
        symbol: str,
        base_size: int,
        direction: str,
        portfolio_state: dict[str, Any],
        market_conditions: MarketConditions
    ) -> int:
        """Calculate final position size after all risk adjustments."""
        size = base_size
        _log.debug("_calculate_final_position_size: use_kelly_sizing=%s, base_size=%s", self.risk_limits.use_kelly_sizing, base_size)

        # Apply volatility adjustment
        volatility_multiplier = self._calculate_volatility_adjustment(market_conditions)
        size = int(size * volatility_multiplier)
        _log.debug("_calculate_final_position_size: after vol adj, size=%s", size)

        # Apply portfolio heat adjustment
        heat_multiplier = self._calculate_portfolio_heat_adjustment(portfolio_state)
        size = int(size * heat_multiplier)
        _log.debug("_calculate_final_position_size: after heat adj, size=%s", size)

        # Apply Kelly criterion if enabled
        _log.debug("_calculate_final_position_size: checking Kelly condition: %s", self.risk_limits.use_kelly_sizing)
        if self.risk_limits.use_kelly_sizing:
            kelly_size = self._calculate_kelly_size(symbol, direction, portfolio_state)
            _log.debug("_calculate_final_position_size: Kelly size=%s, size before Kelly=%s", kelly_size, size)
            size = min(size, kelly_size)
            _log.debug("_calculate_final_position_size: after Kelly adj, size=%s", size)
        else:
            _log.debug("_calculate_final_position_size: Kelly SKIPPED")

        # Ensure we don't go below minimum
        final_size = max(size, self.risk_limits.min_position_size)
        _log.debug("_calculate_final_position_size: final size=%s", final_size)
        return final_size

    def _calculate_volatility_adjustment(self, market_conditions: MarketConditions) -> float:
        """Calculate position size multiplier based on volatility."""
        # Inverse volatility scaling - reduce size when volatility is high
        current_vol = market_conditions.volatility
        target_vol = self.risk_limits.target_volatility

        if current_vol <= 0:
            return 1.0

        # Scale inversely with volatility
        return target_vol / max(current_vol, 0.001)  # Avoid division by zero

    def _calculate_portfolio_heat_adjustment(self, portfolio_state: dict[str, Any]) -> float:
        """Calculate position size multiplier based on current portfolio heat/risk."""
        current_risk = self._calculate_portfolio_risk_score(portfolio_state)
        max_risk = 0.8  # Default max portfolio risk score

        if current_risk >= max_risk:
            return 0.5  # Significantly reduce size when portfolio is hot
        elif current_risk >= max_risk * 0.8:
            return 0.75  # Moderately reduce size
        else:
            return 1.0  # Full size when portfolio is cool

    def _calculate_kelly_size(self, symbol: str, direction: str, portfolio_state: dict[str, Any]) -> int:
        """Calculate position size using Kelly criterion."""
        # Get historical win rate and average win/loss for this strategy/symbol
        stats = self._get_historical_stats(symbol, direction, portfolio_state)

        if stats['win_rate'] <= 0 or stats['avg_win'] <= 0 or stats['avg_loss'] >= 0:
            return self.risk_limits.max_position_size  # Fallback to max if no data

        # Kelly formula: f = (bp - q) / b
        # where b = odds received (avg_win/avg_loss), p = probability of winning, q = probability of losing
        b = stats['avg_win'] / abs(stats['avg_loss'])  # odds ratio
        p = stats['win_rate']
        q = 1 - p

        kelly_fraction = (b * p - q) / b if b > 0 else 0

        # Apply Kelly fraction to max position size with safety factor
        kelly_size = int(self.risk_limits.max_position_size * kelly_fraction * self.risk_limits.kelly_fraction)

        return max(self.risk_limits.min_position_size, min(kelly_size, self.risk_limits.max_position_size))

    def _get_historical_stats(self, symbol: str, direction: str, portfolio_state: dict[str, Any]) -> dict[str, float]:
        """Get historical statistics for Kelly calculation."""
        # In a real implementation, this would query the trade journal/database
        # For now, return placeholder values that would produce a reasonable Kelly fraction
        return {
            'win_rate': 0.55,
            'avg_win': 0.02,   # 2% average win per trade
            'avg_loss': -0.01  # -1% average loss per trade
        }

    def _calculate_current_exposure(self, portfolio_state: dict[str, Any]) -> float:
        """Calculate current portfolio exposure."""
        positions = portfolio_state.get('positions', [])
        total_exposure = sum(abs(pos.market_value) for pos in positions)
        total_equity = self._get_current_equity()

        return total_exposure / total_equity if total_equity > 0 else 0.0

    def _calculate_new_exposure(
        self,
        current_exposure: float,
        symbol: str,
        suggested_size: int,
        direction: str
    ) -> float:
        """Calculate new portfolio exposure if trade is executed."""
        # Simplified - in reality would need current price for the symbol
        estimated_position_value = suggested_size * 100  # Assume ₹100/share for simplicity
        total_equity = self._get_current_equity()

        new_exposure = current_exposure + (estimated_position_value / total_equity)
        return min(new_exposure, 1.0)  # Cap at 100%

    def _calculate_max_correlation(
        self,
        symbol: str,
        direction: str,
        portfolio_state: dict[str, Any]
    ) -> float:
        """Calculate maximum correlation with existing positions."""
        # Simplified correlation calculation
        # In reality, this would use historical price data
        positions = portfolio_state.get('positions', [])

        if not positions:
            return 0.0

        # Mock correlation calculation - would be replaced with real correlation
        base_correlation = 0.3

        # Adjust for same symbol (high correlation)
        same_symbol_positions = [p for p in positions if p.symbol == symbol]
        if same_symbol_positions:
            base_correlation = max(base_correlation, 0.9)

        # Adjust for same direction (moderate correlation)
        same_direction_positions = [p for p in positions if p.direction == direction]
        if same_direction_positions:
            base_correlation = max(base_correlation, 0.6)

        return min(base_correlation, 1.0)

    def _calculate_portfolio_risk_score(self, portfolio_state: dict[str, Any]) -> float:
        """Calculate overall portfolio risk score (0-1)."""
        # Factors: concentration, leverage, volatility, drawdown
        concentration_risk = self._calculate_concentration_risk(portfolio_state)
        leverage_risk = self._calculate_leverage_risk(portfolio_state)
        var_risk = self._calculate_var_risk(portfolio_state)

        # Weighted average
        return (
            concentration_risk * 0.3 +
            leverage_risk * 0.3 +
            var_risk * 0.4
        )

    def _calculate_concentration_risk(self, portfolio_state: dict[str, Any]) -> float:
        """Calculate concentration risk (Herfindahl-Hirschman Index)."""
        positions = portfolio_state.get('positions', [])
        if not positions:
            return 0.0

        total_value = sum(abs(pos.market_value) for pos in positions)
        if total_value == 0:
            return 0.0

        # Calculate HHI
        hhi = sum(((abs(pos.market_value) / total_value) ** 2) for pos in positions)

        # Normalize to 0-1 scale (1/n <= HHI <= 1)
        n = len(positions)
        min_hhi = 1.0 / n if n > 0 else 0
        normalized_hhi = (hhi - min_hhi) / (1.0 - min_hhi) if min_hhi < 1 else 0

        return min(max(normalized_hhi, 0.0), 1.0)

    def _calculate_leverage_risk(self, portfolio_state: dict[str, Any]) -> float:
        """Calculate leverage risk."""
        total_exposure = self._calculate_current_exposure(portfolio_state)
        # Simple leverage exposure ratio
        return min(total_exposure, 2.0) / 2.0  # Cap at 2x leverage

    def _calculate_var_risk(self, portfolio_state: dict[str, Any]) -> float:
        """Calculate Value-at-Risk based risk."""
        # Simplified VaR calculation
        # In reality, would use historical or parametric VaR
        volatility = self._estimate_portfolio_volatility(portfolio_state)
        # Scale volatility to 0-1 range (assuming 50% annual vol is max)
        return min(volatility / 0.5, 1.0)

    def _estimate_portfolio_volatility(self, portfolio_state: dict[str, Any]) -> float:
        """Estimate portfolio volatility."""
        # Simplified - would use actual position volatilities and correlations
        return 0.15  # 15% annualized volatility as placeholder

    def _calculate_drawdown(self, current_equity: float) -> float:
        """Calculate current drawdown from peak equity."""
        if self._peak_equity == 0:
            self._peak_equity = current_equity

        if current_equity > self._peak_equity:
            self._peak_equity = current_equity
            return 0.0

        return (self._peak_equity - current_equity) / self._peak_equity

    def _calculate_trade_risk_metrics(
        self,
        symbol: str,
        size: int,
        direction: str,
        portfolio_state: dict[str, Any],
        market_conditions: MarketConditions
    ) -> dict[str, Any]:
        """Calculate risk metrics for the proposed trade."""
        return {
            'symbol': symbol,
            'position_size': size,
            'direction': direction,
            'estimated_risk': size * 0.01,  # Simplified - 1% risk per share
            'portfolio_impact': size * 0.005,  # Simplified impact
            'timestamp': now_ist().isoformat()
        }

    def update_portfolio_risk(self, positions: list[Position]) -> PortfolioRiskMetrics:
        """Update and return current portfolio risk metrics."""
        with self._risk_lock:
            # Calculate various risk metrics (all inside lock)
            total_exposure = sum(abs(pos.market_value) for pos in positions)
        total_value = sum(pos.market_value for pos in positions)  # Net value

        # Calculate concentration
        concentration = self._calculate_concentration_risk({'positions': positions})

        # Calculate volatility (simplified)
        portfolio_volatility = self._estimate_portfolio_volatility({'positions': positions})

        # Calculate current drawdown
        current_equity = self._get_current_equity()
        drawdown = self._calculate_drawdown(current_equity)

        # Calculate VaR (simplified)
        var_95 = total_exposure * 0.02 * 1.65  # Simplified parametric VaR

        return PortfolioRiskMetrics(
            total_exposure=total_exposure,
            net_value=total_value,
            concentration_risk=concentration,
            volatility=portfolio_volatility,
            drawdown=drawdown,
            value_at_risk_95=var_95
        )

    def check_daily_limits(self, today_pnl: float) -> bool:
        """Check if daily loss/drawdown limits have been breached."""
        # Use a separate lock from evaluate_trade() to avoid deadlock
        with self._risk_lock:
            self._daily_pnl = today_pnl
        return (
            self._daily_pnl >= -self.risk_limits.max_daily_loss and
            self._calculate_drawdown(self._get_current_equity()) <= self.risk_limits.max_drawdown
        )

    def get_risk_alerts(self) -> list[str]:
        """Get current risk alerts and warnings."""
        alerts = []

        with self._risk_lock:
            # Check for proximity to limits
            if abs(self._daily_pnl) > self.risk_limits.max_daily_loss * 0.8:
                alerts.append(f"Approaching daily loss limit: {self._daily_pnl:.2f}")

        current_drawdown = self._calculate_drawdown(self._get_current_equity())
        if current_drawdown > self.risk_limits.max_drawdown * 0.8:
            alerts.append(f"Approaching drawdown limit: {current_drawdown:.2%}")

        if self._consecutive_losses >= self.risk_limits.max_consecutive_losses - 1:
            alerts.append(f"Approaching consecutive losses limit: {self._consecutive_losses}")

        return alerts

    def _get_current_equity(self) -> float:
        """Get current account equity."""
        # In a real implementation, this would come from the portfolio service
        # For now, return the starting equity adjusted by daily P&L
        return self._daily_start_equity + self._daily_pnl


# Factory function for creating risk service instances
def create_risk_service(config: dict[str, Any]) -> RiskService:
    """Factory function to create a RiskService from configuration."""
    _log.debug("create_risk_service: config received: %s", config)
    _log.debug("create_risk_service: use_kelly_sizing in config: %s", config.get('use_kelly_sizing', 'KEY_NOT_FOUND'))
    risk_limits = RiskLimits(
        max_position_size=config.get('max_position_size', 100),
        max_daily_loss=config.get('max_daily_loss', 1000.0),
        max_drawdown=config.get('max_drawdown', 0.20),
        max_consecutive_losses=config.get('max_consecutive_losses', 5),
        max_portfolio_exposure=config.get('max_portfolio_exposure', 0.80),
        max_volatility=config.get('max_volatility', 0.50),
        max_liquidity_size=config.get('max_liquidity_size', 500),
        max_correlation=config.get('max_correlation', 0.70),
        max_open_positions=config.get('max_open_positions', 10),
        target_volatility=config.get('target_volatility', 0.20),
        use_kelly_sizing=config.get('use_kelly_sizing', True),
        kelly_fraction=config.get('kelly_fraction', 0.5),
        min_position_size=config.get('min_position_size', 1),
        account_equity=config.get('account_equity', 100000.0)
    )
    _log.debug("create_risk_service: risk_limits use_kelly_sizing: %s", risk_limits.use_kelly_sizing)

    return RiskService(risk_limits=risk_limits)


if __name__ == "__main__":
    # Example usage and basic tests
    print("=== Risk Service Demo ===")

    # Create risk service with default configuration
    risk_service = create_risk_service({})

    # Test a simple trade evaluation
    decision = risk_service.evaluate_trade(
        symbol="NIFTY",
        direction="BUY",
        suggested_size=50,
        portfolio_state={'positions': []},
        market_conditions=MarketConditions()
    )

    print(f"Trade evaluation: {'ALLOWED' if decision.allowed else 'REJECTED'}")
    print(f"Reason: {decision.reason}")
    print(f"Suggested size: {decision.suggested_size}")

    # Test risk limits
    print("\\n=== Risk Alerts ===")
    alerts = risk_service.get_risk_alerts()
    if alerts:
        for alert in alerts:
            print(f"⚠️  {alert}")
    else:
        print("✅ No risk alerts")

    print("\\n✅ Risk service working correctly!")
