"""Unit tests for the 4 Layer 3 Pinnacle Quant Capabilities (v3.0)."""

from core.market.fii_dii_flow_radar import FiiDiiFlowRadar
from core.strategy.expiry_0dte_harvester import Expiry0DTEHarvester
from core.execution.iceberg_sor_engine import IcebergSOREngine
from core.ai.copilot_command_bar import AICopilotEngine


def test_fii_dii_flow_radar():
    data = FiiDiiFlowRadar.get_participant_positioning()
    assert len(data["participants"]) == 4
    assert data["fii_index_fut_long_ratio_pct"] > 0
    assert len(data["smart_money_traps"]) >= 1

    # Verify FII net long and Client net short
    fii = next(p for p in data["participants"] if p["participant_type"] == "FII")
    assert fii["net_bias"] == "BULLISH"
    assert fii["index_fut_net"] > 0


def test_expiry_0dte_harvester():
    status = Expiry0DTEHarvester.get_live_harvest_status("NIFTY", 24520.0)
    assert status["index_symbol"] == "NIFTY"
    assert len(status["legs"]) == 2
    assert status["total_theta_decay_pct"] > 0
    assert status["engine_state"] == "HARVESTING"
    assert abs(status["delta_exposure"]) < 0.1  # Delta neutral


def test_iceberg_sor_engine():
    plan = IcebergSOREngine.slice_and_execute(
        symbol="TCS",
        side="BUY",
        total_quantity=5000,
        benchmark_price=2268.0,
        num_tranches=10,
    )
    assert plan["parent_order_id"].startswith("ICE-")
    assert plan["filled_quantity"] == 5000
    assert len(plan["tranches"]) == 10
    assert abs(plan["total_slippage_pct"]) < 0.1  # Low slippage cross


def test_ai_copilot_engine():
    # 1. Margin query
    q1 = AICopilotEngine.process_query("What is my total available margin?")
    assert q1["intent"] == "QUERY_MARGINS"
    assert "purchasing power" in q1["answer"]

    # 2. Sector query
    q2 = AICopilotEngine.process_query("Which sectors are in the leading quadrant?")
    assert q2["intent"] == "QUERY_SECTOR_RADAR"
    assert "LEADING" in q2["answer"]

    # 3. FII / DII query
    q3 = AICopilotEngine.process_query("What is the current FII smart money positioning?")
    assert q3["intent"] == "QUERY_FII_DII"
    assert "FII" in q3["answer"]

    # 4. 0DTE query
    q4 = AICopilotEngine.process_query("How much 0dte theta decay captured today?")
    assert q4["intent"] == "QUERY_0DTE_EXPIRY"
    assert "Theta decay" in q4["answer"]
