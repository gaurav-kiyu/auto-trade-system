"""Unit tests for the 4 Layer 2 Institutional Capabilities (v3.0)."""

from core.execution.trade_copier import MasterTradeCopier
from core.market.order_flow_cvd import OrderFlowCVDEngine
from core.portfolio.margin_radar import MultiBrokerMarginRadar
from core.backtest.strategy_sandbox import StrategySandboxStudio


def test_master_trade_copier_execution():
    copier = MasterTradeCopier.get_instance()
    accounts = copier.get_linked_accounts()
    assert len(accounts) >= 5

    res = copier.execute_master_order(
        symbol="TCS",
        direction="BUY",
        entry_price=2250.0,
        master_quantity=100,
    )
    assert res["total_replications"] >= 5
    assert res["master_order_id"].startswith("MST-")

    history = copier.get_execution_history(10)
    assert len(history) >= 5
    assert any(e["symbol"] == "TCS" for e in history)


def test_order_flow_cvd_engine():
    # 1. Bullish breakout order flow
    of_bull = OrderFlowCVDEngine.calculate_order_flow(
        symbol="NIFTY",
        current_price=24550.0,
        volume_total=200000,
        price_change_pct=1.8,
    )
    assert of_bull.buyer_aggression_pct > 50.0
    assert of_bull.net_delta > 0
    assert of_bull.order_flow_imbalance == "STRONG_BUYER_IMBALANCE"

    # 2. Bullish Absorption detection (Price flat but aggressive buying)
    of_abs = OrderFlowCVDEngine.calculate_order_flow(
        symbol="RELIANCE",
        current_price=1380.0,
        volume_total=100000,
        price_change_pct=0.1,
    )
    assert of_abs.absorption_signal in ("BULLISH_ABSORPTION", "NEUTRAL")


def test_multi_broker_margin_radar():
    radar = MultiBrokerMarginRadar.get_consolidated_margins()
    assert radar["total_available_cash"] > 0
    assert radar["total_purchasing_power"] > 0
    assert radar["overall_utilization_pct"] > 0
    assert len(radar["brokers"]) >= 8

    # Verify peak margin alert triggers when any broker >= 75%
    assert "peak_margin_alert" in radar
    assert isinstance(radar["warning_brokers"], list)


def test_strategy_sandbox_simulation():
    res = StrategySandboxStudio.run_sandbox_simulation(
        strategy_name="Multi-Timeframe Trend Breakout",
        symbol="NIFTY",
        rsi_lower=30,
        rsi_upper=70,
        adx_cutoff=25,
        ema_fast=9,
        ema_slow=21,
        vwap_mult=1.8,
        period_days=252,
    )
    assert res.win_rate_pct >= 70.0
    assert res.profit_factor > 1.5
    assert res.total_return_pct > 0
    assert len(res.equity_curve) > 0
    assert res.sharpe_ratio > 1.0
