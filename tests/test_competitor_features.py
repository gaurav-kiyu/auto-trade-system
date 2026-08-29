"""Unit tests for OptionStrategyBuilder, SmartOrderRouter, and AutomatedTestingBridge."""
from core.testing_suite_bridge import AutomatedTestingBridge
from core.trading.option_strategy_builder import OptionStrategyBuilder
from core.trading.smart_order_router import SmartOrderRouter


def test_option_strategy_builder_straddle():
    builder = OptionStrategyBuilder(spot_price=22000.0)
    builder.build_straddle(strike=22000.0, call_premium=150.0, put_premium=120.0)
    profile = builder.calculate_payoff_profile()

    assert profile.max_profit > 0.0
    assert profile.net_premium == 270.0
    assert len(profile.legs) == 2


def test_option_strategy_builder_iron_condor():
    builder = OptionStrategyBuilder(spot_price=22000.0)
    builder.build_iron_condor(
        sell_put_strike=21800.0,
        buy_put_strike=21600.0,
        sell_call_strike=22200.0,
        buy_call_strike=22400.0,
        put_sell_prem=80.0,
        put_buy_prem=30.0,
        call_sell_prem=85.0,
        call_buy_prem=25.0,
    )
    profile = builder.calculate_payoff_profile()

    assert len(profile.legs) == 4
    assert profile.net_premium == -110.0  # Net Credit of 110


def test_smart_order_router_selection():
    sor = SmartOrderRouter()
    best = sor.select_best_broker("NIFTY26AUG22000CE")
    assert best is not None
    assert best.is_active is True
    assert best.name == "zerodha"  # Lowest latency (12ms)


def test_smart_order_router_failover():
    sor = SmartOrderRouter()

    def mock_execute(broker_name: str, order: dict):
        if broker_name == "zerodha":
            raise ConnectionError("Zerodha network timeout")
        return {"order_id": "12345"}

    res = sor.execute_with_failover({"symbol": "INFY"}, mock_execute)
    assert res["status"] == "SUCCESS"
    assert res["broker"] == "angel_one"
    assert "zerodha" in res["tried"]


def test_automated_testing_bridge():
    bridge = AutomatedTestingBridge()
    comp = bridge.run_hygiene_and_compliance()
    assert comp["hygiene_passed"] is True
    assert comp["architecture_passed"] is True

