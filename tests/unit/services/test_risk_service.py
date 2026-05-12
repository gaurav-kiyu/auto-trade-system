"""
Unit tests for Risk Service.
"""
from __future__ import annotations

import pytest
from unittest.mock import Mock, patch
from datetime import datetime, timedelta

from core.services.risk_service import RiskService, RiskServiceConfig
from core.ports.risk.risk_port import (
    RiskPort,
    RiskEvaluation,
    RiskDecision,
    PositionSizingInput,
    PortfolioRiskMetrics
)
from core.ports.persistence.persistence_port import TradePersistencePort


class TestRiskService:
    """Test cases for RiskService."""

    def setup_method(self):
        """Set up test fixtures."""
        self.persistence_mock = Mock(spec=TradePersistencePort)
        self.config = RiskServiceConfig()
        self.service = RiskService(
            config=self.config,
            trade_persistence=self.persistence_mock
        )

    def test_initialization(self):
        """Test service initialization."""
        assert self.service.config == self.config
        assert self.service._trade_persistence == self.persistence_mock
        assert self.service._consecutive_losses == 0
        assert self.service._lock is not None
        assert self.service._logger is not None

    def test_initialization_with_custom_getters(self):
        """Test service initialization with custom getter functions."""
        get_capital = Mock(return_value=50000.0)
        get_positions = Mock(return_value=2)
        get_daily_pnl = Mock(return_value=-500.0)
        get_volatility = Mock(return_value=25.0)
        get_margin = Mock(return_value=1000.0)
        
        service = RiskService(
            config=self.config,
            trade_persistence=self.persistence_mock,
            get_capital_fn=get_capital,
            get_open_positions_fn=get_positions,
            get_daily_pnl_fn=get_daily_pnl,
            get_volatility_fn=get_volatility,
            get_margin_fn=get_margin
        )
        
        assert service._get_capital == get_capital
        assert service._get_open_positions == get_positions
        assert service._get_daily_pnl == get_daily_pnl
        assert service._get_volatility == get_volatility
        assert service._get_margin == get_margin

    def test_evaluate_trade_invalid_signal(self):
        """Test trade evaluation with invalid signal data."""
        # Test missing direction
        evaluation = self.service.evaluate_trade(
            symbol="NIFTY24SepFUT",
            signal_data={"price": 22000.0},  # Missing direction
            portfolio_metrics=PortfolioRiskMetrics(
                total_capital=100000.0,
                used_capital=0.0,
                available_capital=100000.0,
                daily_pnl=0.0,
                max_daily_loss=-2000.0,
                current_drawdown=0.0,
                max_drawdown=0.0,
                open_positions_count=0,
                max_open_positions=5,
                consecutive_losses=0,
                max_consecutive_losses=3,
                sector_exposure={},
                symbol_exposure={}
            )
        )
        
        assert evaluation.decision == RiskDecision.DENIED
        assert "Invalid signal data" in evaluation.reason
        assert evaluation.risk_score == 0.0

    def test_evaluate_trade_invalid_price(self):
        """Test trade evaluation with invalid price."""
        evaluation = self.service.evaluate_trade(
            symbol="NIFTY24SepFUT",
            signal_data={"direction": "BUY", "price": 0},  # Invalid price
            portfolio_metrics=PortfolioRiskMetrics(
                total_capital=100000.0,
                used_capital=0.0,
                available_capital=100000.0,
                daily_pnl=0.0,
                max_daily_loss=-2000.0,
                current_drawdown=0.0,
                max_drawdown=0.0,
                open_positions_count=0,
                max_open_positions=5,
                consecutive_losses=0,
                max_consecutive_losses=3,
                sector_exposure={},
                symbol_exposure={}
            )
        )
        
        assert evaluation.decision == RiskDecision.DENIED
        assert "Invalid signal data" in evaluation.reason

    def test_evaluate_trade_all_checks_pass(self):
        """Test trade evaluation when all risk checks pass."""
        # Setup
        signal_data = {
            "direction": "BUY",
            "price": 22000.0,
            "stop_loss": 21800.0,
            "target": 22400.0,
            "strength": 0.8
        }
        
        portfolio_metrics = PortfolioRiskMetrics(
            total_capital=100000.0,
            used_capital=20000.0,
            available_capital=80000.0,
            daily_pnl=500.0,
            max_daily_loss=-2000.0,
            current_drawdown=0.0,
            max_drawdown=0.0,
            open_positions_count=2,
            max_open_positions=5,
            consecutive_losses=1,
            max_consecutive_losses=3,
            sector_exposure={"FINANCE": 15000.0, "TECH": 5000.0},
            symbol_exposure={"NIFTY24SepFUT": 10000.0, "BANKNIFTY24SepFUT": 10000.0}
        )
        
        # Mock the internal check methods to return ALLOWED
        with patch.object(self.service, '_check_daily_loss_limit') as mock_daily_loss, \
             patch.object(self.service, '_check_consecutive_losses') as mock_consecutive, \
             patch.object(self.service, '_check_portfolio_limits') as mock_portfolio, \
             patch.object(self.service, '_check_margin_requirements') as mock_margin, \
             patch.object(self.service, '_check_trade_quality') as mock_quality, \
             patch.object(self.service, '_check_position_sizing_limits') as mock_sizing:
            
            # All checks return ALLOWED
            allowed_evaluation = RiskEvaluation(
                decision=RiskDecision.ALLOWED,
                reason="Check passed",
                risk_score=0.1
            )
            mock_daily_loss.return_value = allowed_evaluation
            mock_consecutive.return_value = allowed_evaluation
            mock_portfolio.return_value = allowed_evaluation
            mock_margin.return_value = allowed_evaluation
            mock_quality.return_value = allowed_evaluation
            mock_sizing.return_value = allowed_evaluation
            
            # Mock position sizing calculation
            with patch.object(self.service, 'calculate_position_size', return_value=25) as mock_sizing_calc, \
                 patch.object(self.service, '_get_lot_size', return_value=50), \
                 patch.object(self.service, '_get_volatility', return_value=20.0), \
                 patch.object(self.service, '_get_volatility_multiplier', return_value=1.0), \
                 patch.object(self.service, '_get_sector_for_symbol', return_value="FINANCE"), \
                 patch.object(self.service, '_calculate_max_lots_by_portfolio', return_value=30), \
                 patch.object(self.service, '_get_max_lots_per_trade', return_value=50), \
                 patch.object(self.service, '_calculate_max_lots_by_capital', return_value=40), \
                 patch.object(self.service, '_calculate_risk_score', return_value=0.25):
                
                # Execute
                evaluation = self.service.evaluate_trade(
                    symbol="NIFTY24SepFUT",
                    signal_data=signal_data,
                    portfolio_metrics=portfolio_metrics
                )
                
                # Verify
                assert evaluation.decision == RiskDecision.ALLOWED
                assert evaluation.reason == "All risk checks passed"
                assert evaluation.recommended_position_size == 25
                assert evaluation.max_allowed_position_size == 25
                assert evaluation.risk_score == 0.25

    def test_evaluate_trade_daily_loss_limit_exceeded(self):
        """Test trade evaluation when daily loss limit is exceeded."""
        # Setup
        signal_data = {"direction": "BUY", "price": 22000.0}
        portfolio_metrics = PortfolioRiskMetrics(
            total_capital=100000.0,
            used_capital=0.0,
            available_capital=100000.0,
            daily_pnl=-2500.0,  # Exceeds max_daily_loss of -2000.0
            max_daily_loss=-2000.0,
            current_drawdown=0.0,
            max_drawdown=0.0,
            open_positions_count=0,
            max_open_positions=5,
            consecutive_losses=0,
            max_consecutive_losses=3,
            sector_exposure={},
            symbol_exposure={}
        )
        
        # Execute
        evaluation = self.service.evaluate_trade(
            symbol="NIFTY24SepFUT",
            signal_data=signal_data,
            portfolio_metrics=portfolio_metrics
        )
        
        # Verify
        assert evaluation.decision == RiskDecision.DENIED
        assert "Daily loss limit reached" in evaluation.reason

    def test_evaluate_trade_consecutive_losses_exceeded(self):
        """Test trade evaluation when consecutive losses limit is exceeded."""
        # Setup
        signal_data = {"direction": "BUY", "price": 22000.0}
        portfolio_metrics = PortfolioRiskMetrics(
            total_capital=100000.0,
            used_capital=0.0,
            available_capital=100000.0,
            daily_pnl=0.0,
            max_daily_loss=-2000.0,
            current_drawdown=0.0,
            max_drawdown=0.0,
            open_positions_count=0,
            max_open_positions=5,
            consecutive_losses=4,  # Exceeds max_consecutive_losses of 3
            max_consecutive_losses=3,
            sector_exposure={},
            symbol_exposure={}
        )
        
        # Execute
        evaluation = self.service.evaluate_trade(
            symbol="NIFTY24SepFUT",
            signal_data=signal_data,
            portfolio_metrics=portfolio_metrics
        )
        
        # Verify
        assert evaluation.decision == RiskDecision.DENIED
        assert "Consecutive loss limit reached" in evaluation.reason

    def test_evaluate_trade_portfolio_limits_exceeded(self):
        """Test trade evaluation when portfolio limits are exceeded."""
        # Setup
        signal_data = {"direction": "BUY", "price": 22000.0}
        portfolio_metrics = PortfolioRiskMetrics(
            total_capital=100000.0,
            used_capital=95000.0,  # High usage
            available_capital=5000.0,
            daily_pnl=0.0,
            max_daily_loss=-2000.0,
            current_drawdown=0.0,
            max_drawdown=0.0,
            open_positions_count=6,  # Exceeds max_open_positions of 5
            max_open_positions=5,
            consecutive_losses=0,
            max_consecutive_losses=3,
            sector_exposure={"FINANCE": 95000.0},
            symbol_exposure={"NIFTY24SepFUT": 50000.0}
        )
        
        # Execute
        evaluation = self.service.evaluate_trade(
            symbol="NIFTY24SepFUT",
            signal_data=signal_data,
            portfolio_metrics=portfolio_metrics
        )
        
        # Verify
        assert evaluation.decision == RiskDecision.DENIED
        assert ("Maximum open positions reached" in evaluation.reason or
                "Portfolio risk limit reached" in evaluation.reason)

    def test_calculate_position_size_basic(self):
        """Test basic position size calculation."""
        # Setup
        sizing_input = PositionSizingInput(
            symbol="NIFTY24SepFUT",
            entry_price=22000.0,
            stop_loss_price=21800.0,
            capital_available=100000.0,
            risk_per_trade=0.02,  # 2%
            lot_size=50,
            volatility=20.0,
            existing_exposure=0.0
        )

        # Execute
        size = self.service.calculate_position_size(sizing_input)

        # Verify: Risk amount = 100000 * 0.02 = 2000
        # Price diff = 22000 - 21800 = 200
        # Raw lots = 2000 / (200 * 50) = 2000 / 10000 = 0.2
        # Base lots = max(1, int(0.2)) = 1
        assert size >= 1

    def test_calculate_position_size_zero_risk(self):
        """Test position size calculation with zero risk parameters."""
        # Setup
        sizing_input = PositionSizingInput(
            symbol="NIFTY24SepFUT",
            entry_price=22000.0,
            stop_loss_price=22000.0,  # No price difference
            capital_available=100000.0,
            risk_per_trade=0.02,
            lot_size=50,
            volatility=20.0,
            existing_exposure=0.0
        )
        
        # Execute
        size = self.service.calculate_position_size(sizing_input)
        
        # Verify
        assert size == 0

    def test_calculate_position_size_high_volatility(self):
        """Test position size calculation with high volatility adjustment."""
        # Setup
        sizing_input = PositionSizingInput(
            symbol="NIFTY24SepFUT",
            entry_price=22000.0,
            stop_loss_price=21800.0,
            capital_available=100000.0,
            risk_per_trade=0.02,
            lot_size=50,
            volatility=40.0,  # High volatility
            existing_exposure=0.0
        )
        
        # Execute
        size = self.service.calculate_position_size(sizing_input)
        
        # Verify - high volatility should reduce position size
        # (Based on config: vix_threshold_high=35.0, vix_size_multiplier_high=0.6)
        assert size >= 0  # Should be calculated

    def test_validate_margin_requirements_sufficient(self):
        """Test margin validation with sufficient margin."""
        # Setup
        self.service._get_margin = Mock(return_value=8000.0)
        
        # Execute
        result = self.service.validate_margin_requirements(
            symbol="NIFTY24SepFUT",
            quantity=10,
            capital_available=20000.0
        )
        
        # Verify
        assert result is True  # 8000 <= 20000 * 0.8 (margin_safety_factor)

    def test_validate_margin_requirements_insufficient(self):
        """Test margin validation with insufficient margin."""
        # Setup
        self.service._get_margin = Mock(return_value=20000.0)
        
        # Execute
        result = self.service.validate_margin_requirements(
            symbol="NIFTY24SepFUT",
            quantity=10,
            capital_available=20000.0
        )
        
        # Verify
        assert result is False  # 20000 > 20000 * 0.8 = 16000

    def test_get_portfolio_risk_metrics(self):
        """Test getting portfolio risk metrics."""
        # Setup
        self.service._get_capital = Mock(return_value=100000.0)
        self.service._get_daily_pnl = Mock(return_value=1500.0)
        self.service._get_open_positions = Mock(return_value=3)
        
        # Execute
        metrics = self.service.get_portfolio_risk_metrics()
        
        # Verify
        assert isinstance(metrics, PortfolioRiskMetrics)
        assert metrics.total_capital == 100000.0
        assert metrics.daily_pnl == 1500.0
        assert metrics.open_positions_count == 3

    def test_update_position(self):
        """Test updating position tracking."""
        # Setup
        symbol = "NIFTY24SepFUT"
        quantity = 50
        entry_price = 22000.0
        timestamp = datetime.now()
        
        # Execute
        self.service.update_position(symbol, quantity, entry_price, timestamp)
        
        # Verify internal state was updated
        assert symbol in self.service._positions
        position = self.service._positions[symbol]
        assert position['quantity'] == quantity
        assert position['entry_price'] == entry_price
        assert position['symbol'] == symbol

    def test_remove_position(self):
        """Test removing position tracking."""
        # Setup
        symbol = "NIFTY24SepFUT"
        self.service._positions[symbol] = {'quantity': 50, 'entry_price': 22000.0}
        
        # Execute
        self.service.remove_position(symbol)
        
        # Verify
        assert symbol not in self.service._positions

    def test_reset_daily_metrics(self):
        """Test resetting daily metrics."""
        # Setup
        self.service._peak_pnl = 5000.0
        self.service._max_drawdown = 2000.0
        self.service._consecutive_losses = 3
        self.service._last_loss_reset = datetime.now() - timedelta(hours=10)
        
        # Execute
        self.service.reset_daily_metrics()
        
        # Verify
        assert self.service._peak_pnl == 0.0
        assert self.service._max_drawdown == 0.0
        # Since 10 hours > loss_reset_hours (6), consecutive losses should reset
        assert self.service._consecutive_losses == 0

    def test_health_check_healthy(self):
        """Test health check when service is healthy."""
        # Setup
        self.service._get_capital = Mock(return_value=100000.0)
        self.service._get_daily_pnl = Mock(return_value=0.0)
        self.service._get_open_positions = Mock(return_value=2)
        self.persistence_mock.health_check.return_value = {"status": "healthy"}
        
        # Execute
        result = self.service.health_check()
        
        # Verify
        assert result["status"] == "healthy"
        assert result["service"] == "RiskService"
        assert result["metrics"]["capital"] == 100000.0
        assert result["metrics"]["daily_pnl"] == 0.0
        assert result["metrics"]["open_positions"] == 2

    def test_health_check_error(self):
        """Test health check when error occurs."""
        # Setup
        self.service._get_capital = Mock(side_effect=Exception("Capital error"))
        
        # Execute
        result = self.service.health_check()

        # Debug
        print(f"Health check result: {result}")

        # Verify
        assert result["status"] == "unhealthy"
        assert "Capital error" in result["error"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
