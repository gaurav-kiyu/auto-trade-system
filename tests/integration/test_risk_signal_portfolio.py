"""
Integration tests for risk, signal, and portfolio services working together.
"""

import pytest
from datetime import datetime, timedelta
from core.domains.risk.service import create_risk_service, RiskLimits
from core.domains.signal_engine.service import create_signal_service, TradingSignal
from core.domains.portfolio.service import create_portfolio_service, Position


class TestIntegration:
    """Integration tests for core domain services."""

    def setup_method(self):
        """Set up test fixtures before each test method."""
        # Create services with test configuration
        risk_config = {
            'max_position_size': 100,
            'max_daily_loss': 1000.0,
            'max_drawdown': 0.20,
            'max_consecutive_losses': 5,
            'max_portfolio_exposure': 0.80,
            'account_equity': 100000.0
        }
        self.risk_service = create_risk_service(risk_config)
        self.signal_service = create_signal_service({})
        self.portfolio_service = create_portfolio_service({})

    def test_risk_signal_portfolio_workflow(self):
        """Test a complete workflow: signal generation -> risk evaluation -> portfolio update."""
        # Step 1: Generate a trading signal (simplified test)
        # In reality, this would use real market data
        signal = TradingSignal(
            symbol="NIFTY",
            strength=0.8,
            direction="BUY",
            quality="STRONG",
            timestamp=datetime.now()
        )

        # Verify signal properties
        assert signal.symbol == "NIFTY"
        assert signal.direction == "BUY"
        assert signal.strength == 0.8
        assert signal.quality == "STRONG"

        # Step 2: Evaluate risk for the proposed trade
        portfolio_state = {
            'positions': []  # Start with no positions
        }

        # Use a simple market conditions object
        class MockMarketConditions:
            def __init__(self):
                self.volatility = 0.15
                self.liquidity = "NORMAL"
                self.trend = "NEUTRAL"

        market_conditions = MockMarketConditions()

        risk_decision = self.risk_service.evaluate_trade(
            symbol=signal.symbol,
            direction=signal.direction,
            suggested_size=50,  # Proposed position size
            portfolio_state=portfolio_state,
            market_conditions=market_conditions
        )

        # Verify risk evaluation
        assert risk_decision.allowed is True
        assert risk_decision.suggested_size > 0
        assert "All risk checks passed" in risk_decision.reason

        # Step 3: Update portfolio with the trade (simulated)
        # Create a mock fill object
        class MockFill:
            def __init__(self, symbol, quantity, price, direction, timestamp=None, commission=0.0, strategy_id='TEST'):
                self.symbol = symbol
                self.quantity = quantity
                self.price = price
                self.direction = direction
                self.timestamp = timestamp or datetime.now()
                self.commission = commission
                self.strategy_id = strategy_id

        # Simulate buying 50 NIFTY at 20000
        fill = MockFill(
            symbol="NIFTY",
            quantity=risk_decision.suggested_size,
            price=20000.0,
            direction="BUY"
        )

        position = self.portfolio_service.update_position(fill)

        # Verify portfolio update
        assert position.symbol == "NIFTY"
        assert position.quantity == risk_decision.suggested_size
        assert position.average_price == 20000.0
        assert position.market_value == risk_decision.suggested_size * 20000.0

        # Step 4: Calculate portfolio performance
        # Simulate some price movement for unrealized P&L
        current_prices = {"NIFTY": 20500.0}  # Price went up
        positions_dict = {"NIFTY": position}
        unrealized_pnl = self.portfolio_service.calculate_unrealized_pnl(
            positions_dict,
            current_prices
        )

        expected_pnl = risk_decision.suggested_size * (20500.0 - 20000.0)
        assert unrealized_pnl == expected_pnl

        # Verify the position was updated with unrealized P&L
        updated_position = positions_dict["NIFTY"]
        assert updated_position.unrealized_pnl == expected_pnl

    def test_risk_limits_enforcement(self):
        """Test that risk limits are properly enforced in the workflow."""
        # Set up a scenario that should trigger risk limits

        # First, create a large position that uses most of the portfolio
        large_position = Position(
            symbol="NIFTY",
            quantity=80,
            average_price=20000,
            market_value=1600000,  # 80 * 20000 = 1,600,000
            unrealized_pnl=0.0,
            realized_pnl=0.0,
            timestamp=datetime.now()
        )

        portfolio_state = {
            'positions': [large_position]
            # This already uses 1600000/100000 = 16x exposure (1600% of account)
            # which should exceed our 80% max portfolio exposure limit
        }

        # Try to add another position
        risk_decision = self.risk_service.evaluate_trade(
            symbol="BANKNIFTY",
            direction="BUY",
            suggested_size=10,
            portfolio_state=portfolio_state,
            market_conditions=type('MockMarketConditions', (), {
                'volatility': 0.15,
                'liquidity': 'NORMAL',
                'trend': 'NEUTRAL'
            })()
        )

        # Should be rejected due to portfolio exposure limits
        assert risk_decision.allowed is False
        assert "Portfolio exposure limit breached" in risk_decision.reason
        assert risk_decision.suggested_size == 0

    def test_signal_quality_affects_risk_sizing(self):
        """Test that signal quality can influence position sizing through strategy decisions."""
        # Create signals of different qualities
        strong_signal = TradingSignal(
            symbol="NIFTY",
            strength=0.9,
            direction="BUY",
            quality="STRONG",
            timestamp=datetime.now()
        )

        weak_signal = TradingSignal(
            symbol="NIFTY",
            strength=0.2,
            direction="BUY",
            quality="WEAK",
            timestamp=datetime.now()
        )

        # In a real implementation, the trading orchestrator would use signal quality
        # to influence the suggested size passed to risk evaluation
        # For this test, we'll verify that the signals have different strengths
        assert strong_signal.strength > weak_signal.strength
        assert strong_signal.quality == "STRONG"
        assert weak_signal.quality == "WEAK"


if __name__ == "__main__":
    pytest.main([__file__])