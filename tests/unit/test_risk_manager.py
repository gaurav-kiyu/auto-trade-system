"""
Unit tests for the RiskService domain service.
"""

from datetime import datetime

import pytest
from core.domains.risk.model import MarketConditions, Position
from core.domains.risk.service import create_risk_service


class TestRiskManager:
    """Test cases for the RiskManager domain service."""

    def setup_method(self):
        """Set up test fixtures before each test method."""
        self.config = {
            'max_position_size': 100,
            'max_daily_loss': 1000.0,
            'max_drawdown': 0.20,
            'max_consecutive_losses': 5,
            'max_portfolio_exposure': 0.80,
            'max_volatility': 0.50,
            'max_liquidity_size': 500,
            'max_correlation': 0.70,
            'max_open_positions': 10,
            'target_volatility': 0.20,
            'use_kelly_sizing': True,
            'kelly_fraction': 0.5,
            'min_position_size': 1,
            'account_equity': 100000.0
        }
        self.risk_service = create_risk_service(self.config)

    def test_risk_service_initialization(self):
        """Test that the risk manager initializes correctly."""
        assert self.risk_service is not None
        assert self.risk_service.risk_limits.account_equity == 100000.0
        assert self.risk_service.risk_limits.max_position_size == 100
        assert self.risk_service._daily_pnl == 0.0
        assert self.risk_service._consecutive_losses == 0

    def test_position_size_limit_check(self):
        """Test that position size limits are enforced."""
        # Create config with Kelly sizing disabled for isolated position limit testing
        config_no_kelly = self.config.copy()
        config_no_kelly['use_kelly_sizing'] = False
        risk_service_no_kelly = create_risk_service(config_no_kelly)

        # Test within limits
        decision = risk_service_no_kelly.evaluate_trade(
            symbol="NIFTY",
            direction="BUY",
            suggested_size=50,
            portfolio_state={'positions': []},
            market_conditions=MarketConditions()
        )
        assert decision.allowed is True
        assert decision.suggested_size == 50

        # Test exceeding limits
        decision = risk_service_no_kelly.evaluate_trade(
            symbol="NIFTY",
            direction="BUY",
            suggested_size=150,  # Exceeds max of 100
            portfolio_state={'positions': []},
            market_conditions=MarketConditions()
        )
        assert decision.allowed is False
        assert decision.suggested_size == 100  # Should be capped to max
        assert "exceeds maximum" in decision.reason

    def test_daily_loss_limit_check(self):
        """Test that daily loss limits are enforced."""
        # Set up a scenario where daily loss limit is ALREADY breached
        self.risk_service._daily_pnl = -1100.0  # Already lost 1100, exceeds -1000 limit

        decision = self.risk_service.evaluate_trade(
            symbol="NIFTY",
            direction="BUY",
            suggested_size=50,
            portfolio_state={'positions': []},
            market_conditions=MarketConditions()
        )

        # Since daily loss limit is already breached, trade should be rejected
        assert decision.allowed is False
        assert "Daily loss limit breached" in decision.reason
        assert decision.suggested_size == 0

    def test_drawdown_limit_check(self):
        """Test that drawdown limits are enforced."""
        # Simulate a drawdown situation
        self.risk_service._peak_equity = 100000.0
        # Manually adjust current equity to simulate drawdown
        # We'll test this by setting up the internal state directly for test purposes
        original_get_equity = self.risk_service._get_current_equity
        self.risk_service._get_current_equity = lambda: 70000.0  # 30% drawdown

        try:
            decision = self.risk_service.evaluate_trade(
                symbol="NIFTY",
                direction="BUY",
                suggested_size=50,
                portfolio_state={'positions': []},
                market_conditions=MarketConditions()
            )

            # 30% drawdown exceeds 20% limit
            assert decision.allowed is False
            assert "Drawdown limit breached" in decision.reason
            assert decision.suggested_size == 0
        finally:
            # Restore original method
            self.risk_service._get_current_equity = original_get_equity

    def test_consecutive_losses_limit(self):
        """Test that consecutive losses limits are enforced."""
        # Set up consecutive losses
        self.risk_service._consecutive_losses = 5  # Already at limit

        decision = self.risk_service.evaluate_trade(
            symbol="NIFTY",
            direction="BUY",
            suggested_size=50,
            portfolio_state={'positions': []},
            market_conditions=MarketConditions()
        )

        assert decision.allowed is False
        assert "Consecutive losses limit breached" in decision.reason
        assert decision.suggested_size == 0

        # Test just under limit
        self.risk_service._consecutive_losses = 4
        decision = self.risk_service.evaluate_trade(
            symbol="NIFTY",
            direction="BUY",
            suggested_size=50,
            portfolio_state={'positions': []},
            market_conditions=MarketConditions()
        )

        assert decision.allowed is True  # Should still allow trading

    def test_portfolio_exposure_limit(self):
        """Test that portfolio exposure limits are enforced."""
        # Set up existing position that already uses 75% of portfolio
        existing_position = Position(
            symbol="BANKNIFTY",
            quantity=50,
            average_price=40000,
            market_value=2000000,  # 50 * 40000 = 2,000,000
            unrealized_pnl=0.0,
            realized_pnl=0.0,
            timestamp=datetime.now()
        )

        portfolio_state = {
            'positions': [existing_position]
            # Account equity is 100,000, so 2,000,000 / 100,000 = 20x exposure
            # This already exceeds our 80% limit, so any new trade should be rejected
        }

        decision = self.risk_service.evaluate_trade(
            symbol="NIFTY",
            direction="BUY",
            suggested_size=10,
            portfolio_state=portfolio_state,
            market_conditions=MarketConditions()
        )

        assert decision.allowed is False
        assert "Portfolio exposure limit breached" in decision.reason
        assert decision.suggested_size == 0

    def test_volatility_limit_check(self):
        """Test that volatility limits are enforced."""
        market_conditions = MarketConditions()
        market_conditions.volatility = 0.6  # 60% volatility exceeds 50% limit

        decision = self.risk_service.evaluate_trade(
            symbol="NIFTY",
            direction="BUY",
            suggested_size=50,
            portfolio_state={'positions': []},
            market_conditions=market_conditions
        )

        assert decision.allowed is False
        assert "Volatility too high" in decision.reason
        assert decision.suggested_size == 0

        # Test within volatility limits
        market_conditions.volatility = 0.3  # 30% volatility

        decision = self.risk_service.evaluate_trade(
            symbol="NIFTY",
            direction="BUY",
            suggested_size=50,
            portfolio_state={'positions': []},
            market_conditions=market_conditions
        )

        assert decision.allowed is True

    def test_liquidity_limit_check(self):
        """Test that liquidity limits are enforced."""
        # Create config with adjusted liquidity and position limits for this test
        config = self.config.copy()
        config['max_liquidity_size'] = 50   # Set liquidity limit to 50 for testing
        config['max_position_size'] = 100    # Ensure position limit is above liquidity limit
        config['use_kelly_sizing'] = False  # Disable Kelly for this specific test
        risk_service = create_risk_service(config)

        # Test order exceeding liquidity size
        decision = risk_service.evaluate_trade(
            symbol="NIFTY",
            direction="BUY",
            suggested_size=60,  # Exceeds max liquidity size of 50
            portfolio_state={'positions': []},
            market_conditions=MarketConditions()
        )

        assert decision.allowed is False
        assert "Order size too large for current liquidity" in decision.reason
        assert decision.suggested_size == 50  # Should be capped to max liquidity size

        # Test within liquidity limits
        decision = risk_service.evaluate_trade(
            symbol="NIFTY",
            direction="BUY",
            suggested_size=40,
            portfolio_state={'positions': []},
            market_conditions=MarketConditions()
        )

        assert decision.allowed is True
        assert decision.suggested_size == 40

    def test_kelly_sizing(self):
        """Test that Kelly criterion position sizing works."""
        # Configure for Kelly sizing test
        config = self.config.copy()
        config['use_kelly_sizing'] = True
        config['kelly_fraction'] = 0.5  # Half-Kelly

        risk_service = create_risk_service(config)

        # With our mock historical stats (55% win rate, 2% avg win, 1% avg loss)
        # Kelly formula: f = (bp - q) / b
        # where b = avg_win/avg_loss = 2.0, p = 0.55, q = 0.45
        # f = (2.0 * 0.55 - 0.45) / 2.0 = (1.10 - 0.45) / 2.0 = 0.65 / 2.0 = 0.325
        # Half-Kelly: 0.325 * 0.5 = 0.1625
        # Position size: 100,000 * 0.1625 / (price per share)
        # Assuming roughly 1000 price per share for simplicity: ~16 shares

        decision = risk_service.evaluate_trade(
            symbol="NIFTY",
            direction="BUY",
            suggested_size=100,  # Request large size
            portfolio_state={'positions': []},
            market_conditions=MarketConditions()
        )

        # Should allow trade but reduce size based on Kelly
        assert decision.allowed is True
        assert decision.suggested_size > 0
        assert decision.suggested_size < 100  # Should be reduced from requested size
        # Exact size depends on internal calculations, but should be reasonable

    def test_risk_decision_structure(self):
        """Test that RiskDecision objects have correct structure."""
        decision = self.risk_service.evaluate_trade(
            symbol="NIFTY",
            direction="BUY",
            suggested_size=50,
            portfolio_state={'positions': []},
            market_conditions=MarketConditions()
        )

        assert hasattr(decision, 'allowed')
        assert hasattr(decision, 'reason')
        assert hasattr(decision, 'suggested_size')
        assert hasattr(decision, 'risk_metrics')

        assert isinstance(decision.allowed, bool)
        assert isinstance(decision.reason, str)
        assert isinstance(decision.suggested_size, int)
        assert decision.risk_metrics is None or isinstance(decision.risk_metrics, dict)

    def test_update_portfolio_risk(self):
        """Test portfolio risk update functionality."""
        positions = [
            Position(
                symbol="NIFTY",
                quantity=50,
                average_price=20000,
                market_value=1000000,
                unrealized_pnl=50000,
                realized_pnl=0.0,
                timestamp=datetime.now()
            ),
            Position(
                symbol="BANKNIFTY",
                quantity=25,
                average_price=40000,
                market_value=1000000,
                unrealized_pnl=-25000,
                realized_pnl=0.0,
                timestamp=datetime.now()
            )
        ]

        risk_metrics = self.risk_service.update_portfolio_risk(positions)

        assert risk_metrics is not None
        assert hasattr(risk_metrics, 'total_exposure')
        assert hasattr(risk_metrics, 'net_value')
        assert hasattr(risk_metrics, 'concentration_risk')
        assert hasattr(risk_metrics, 'volatility')
        assert hasattr(risk_metrics, 'drawdown')
        assert hasattr(risk_metrics, 'value_at_risk_95')
        assert hasattr(risk_metrics, 'timestamp')

        # Total exposure should be sum of absolute market values
        expected_exposure = 1000000 + 1000000  # 2,000,000
        assert risk_metrics.total_exposure == expected_exposure

        # Net value should be sum of market values (since quantities are positive)
        expected_net_value = 1000000 + 1000000  # 2,000,000
        assert risk_metrics.net_value == expected_net_value

    def test_check_daily_limits(self):
        """Test daily limits checking."""
        # Test within limits
        within_limits = self.risk_service.check_daily_limits(500.0)  # +500 P&L
        assert within_limits is True

        within_limits = self.risk_service.check_daily_limits(-500.0)  # -500 P&L
        assert within_limits is True

        # Test exceeding daily loss limit
        exceeds_limit = self.risk_service.check_daily_limits(-1500.0)  # -1500 P&L > -1000 limit
        assert exceeds_limit is False

        # Test exact limit
        at_limit = self.risk_service.check_daily_limits(-1000.0)  # Exactly at limit
        assert at_limit is True

    def test_get_risk_alerts(self):
        """Test risk alerts generation."""
        # No alerts initially
        alerts = self.risk_service.get_risk_alerts()
        assert isinstance(alerts, list)
        assert len(alerts) == 0

        # Test approaching daily loss limit
        self.risk_service._daily_pnl = -850.0  # 85% of -1000 limit
        alerts = self.risk_service.get_risk_alerts()
        assert any("Approaching daily loss limit" in alert for alert in alerts)

        # Test approaching drawdown limit
        # Manually set up drawdown condition
        original_get_equity = self.risk_service._get_current_equity
        # Drawdown = (100000 - current) / 100000 = 0.17 = 17%
        # 17% > 16% threshold (0.2 * 0.8), so should trigger alert
        self.risk_service._get_current_equity = lambda: 83000.0  # 17% drawdown from 100k peak
        self.risk_service._peak_equity = 100000.0

        try:
            alerts = self.risk_service.get_risk_alerts()
            assert any("Approaching drawdown limit" in alert for alert in alerts)
        finally:
            self.risk_service._get_current_equity = original_get_equity

        # Test approaching consecutive losses limit
        self.risk_service._consecutive_losses = 4  # One away from limit of 5
        alerts = self.risk_service.get_risk_alerts()
        assert any("Approaching consecutive losses limit" in alert for alert in alerts)


if __name__ == "__main__":
    pytest.main([__file__])
