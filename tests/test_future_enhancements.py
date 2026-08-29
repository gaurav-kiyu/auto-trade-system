"""Unit tests for Future-Proof Institutional Enhancements:

- Market Regime Classifier Engine
- Portfolio Auto-Hedger Engine
- Real-Time Broker Health & Latency Monitor
"""

from __future__ import annotations

from core.adapters.broker_health_monitor import get_broker_health_monitor
from core.ai.market_regime_classifier import get_market_regime_classifier
from core.risk.auto_hedger import get_portfolio_auto_hedger


def test_market_regime_classifier_bull_trend() -> None:
    """Test MarketRegimeClassifier for Bull Trend detection."""
    classifier = get_market_regime_classifier()
    prices = [24000.0 + i * 50.0 for i in range(25)]  # Strong upward slope
    result = classifier.classify_regime(prices, vix_level=14.0)

    assert result.regime == "BULL_TREND"
    assert "BULL TREND" in result.regime_label
    assert result.confidence_score >= 85.0
    assert result.parameter_overrides["PREFER_DIRECTION"] == "CALL"


def test_market_regime_classifier_high_volatility() -> None:
    """Test MarketRegimeClassifier for High Volatility Shock detection."""
    classifier = get_market_regime_classifier()
    prices = [24000.0 + (100.0 if i % 2 == 0 else -100.0) for i in range(25)]
    result = classifier.classify_regime(prices, vix_level=28.5)

    assert result.regime == "HIGH_VOLATILITY"
    assert "HIGH VOLATILITY" in result.regime_label
    assert result.parameter_overrides["LOT_SIZE_MULTIPLIER"] == 0.5


def test_portfolio_auto_hedger() -> None:
    """Test PortfolioAutoHedger tail risk analysis & hedge generation."""
    hedger = get_portfolio_auto_hedger()
    positions = [
        {"symbol": "RELIANCE", "quantity": 100, "current_price": 3000.0, "current_value": 300000.0},
        {"symbol": "HDFCBANK", "quantity": 200, "current_price": 1500.0, "current_value": 300000.0},
    ]

    analysis = hedger.analyze_and_hedge(positions, spot_nifty=24250.0)

    assert analysis.tail_risk_level in ["HIGH", "CRITICAL"]
    assert analysis.max_hedged_drawdown_pct == 4.8
    assert len(analysis.hedge_recommendations) >= 2
    assert "Protective Put" in analysis.hedge_recommendations[0].strategy_name


def test_broker_health_monitor() -> None:
    """Test BrokerHealthMonitor pings across all 14 Indian brokers."""
    monitor = get_broker_health_monitor()
    statuses = monitor.ping_all_brokers()

    assert len(statuses) == 14
    broker_codes = {b.broker_code for b in statuses}
    assert "zerodha" in broker_codes
    assert "mstock" in broker_codes
    assert "angelone" in broker_codes

    # Fastest broker should be first
    assert statuses[0].latency_ms <= statuses[-1].latency_ms
    assert statuses[0].is_active is True

def test_portfolio_auto_hedger_execution_service_injection() -> None:
    """Auto-Hedger factory must retain an explicitly supplied ExecutionService."""
    from unittest.mock import MagicMock

    from core.risk.auto_hedger import get_portfolio_auto_hedger

    execution_service = MagicMock()

    hedger = get_portfolio_auto_hedger(execution_service)

    assert hedger._execution_service is execution_service
