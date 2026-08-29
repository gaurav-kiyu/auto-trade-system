"""Tests for CostAccountant - accurate cost-adjusted PnL calculations."""

from __future__ import annotations

from core.cost_accountant import CostAccountant, get_cost_accountant


class TestCostAccountant:
    """CostAccountant - trading cost calculations."""

    def test_default_config_uses_default_rates(self):
        ca = CostAccountant()
        assert ca.STT_PCT == 0.0005
        assert ca.BROKERAGE_PER_ORDER == 20.0

    def test_config_overrides_defaults(self):
        ca = CostAccountant({"MANDATE_COST_STT_PCT": 0.001, "MANDATE_COST_BROKERAGE": 10.0})
        assert ca.STT_PCT == 0.001
        assert ca.BROKERAGE_PER_ORDER == 10.0

    # ── Entry costs ──────────────────────────────────────────────

    def test_calculate_entry_costs_has_all_keys(self):
        ca = CostAccountant()
        costs = ca.calculate_entry_costs(100.0, 1)
        assert "premium" in costs
        assert "brokerage" in costs
        assert "gst" in costs
        assert "stamp_duty" in costs
        assert "total_entry_cost" in costs

    def test_entry_costs_stamp_duty_scales_with_premium(self):
        ca = CostAccountant()
        small = ca.calculate_entry_costs(100.0, 1)
        large = ca.calculate_entry_costs(200.0, 1)
        assert large["stamp_duty"] > small["stamp_duty"]

    def test_entry_premium_reflects_qty(self):
        ca = CostAccountant()
        costs = ca.calculate_entry_costs(100.0, 5)
        assert costs["premium"] == 500.0

    # ── Exit costs ───────────────────────────────────────────────

    def test_calculate_exit_costs_has_all_keys(self):
        ca = CostAccountant()
        costs = ca.calculate_exit_costs(100.0, 1)
        assert "premium" in costs
        assert "brokerage" in costs
        assert "stt" in costs
        assert "stamp_duty" in costs
        assert "gst" in costs
        assert "bid_ask_slippage" in costs
        assert "total_exit_cost" in costs

    def test_exit_stt_on_sell(self):
        ca = CostAccountant()
        sell = ca.calculate_exit_costs(100.0, 1, is_buy=False)
        buy = ca.calculate_exit_costs(100.0, 1, is_buy=True)
        assert sell["stt"] > 0
        assert buy["stt"] == 0

    def test_exit_bid_ask_scales_with_qty(self):
        ca = CostAccountant()
        single = ca.calculate_exit_costs(100.0, 1)
        multi = ca.calculate_exit_costs(100.0, 10)
        assert multi["bid_ask_slippage"] == single["bid_ask_slippage"] * 10

    # ── Net PnL ─────────────────────────────────────────────────

    def test_calculate_net_pnl_profit(self):
        ca = CostAccountant()
        result = ca.calculate_net_pnl(entry_premium=100.0, exit_premium=150.0, qty=1)
        assert result["gross_pnl"] == 50.0
        assert result["net_pnl"] < result["gross_pnl"]
        assert result["total_costs"] > 0

    def test_calculate_net_pnl_loss(self):
        ca = CostAccountant()
        result = ca.calculate_net_pnl(entry_premium=150.0, exit_premium=100.0, qty=1)
        assert result["gross_pnl"] == -50.0
        assert result["net_pnl"] < result["gross_pnl"]

    def test_calculate_net_pnl_has_cost_pct(self):
        ca = CostAccountant()
        result = ca.calculate_net_pnl(100.0, 110.0, 1)
        assert 0 < result["cost_pct_of_trade"] < 1.0

    # ── Expected costs ──────────────────────────────────────────

    def test_calculate_expected_costs_positive(self):
        ca = CostAccountant()
        costs = ca.calculate_expected_costs(100.0, 1)
        assert costs > 0

    def test_calculate_expected_costs_scales_with_qty(self):
        ca = CostAccountant()
        single = ca.calculate_expected_costs(100.0, 1)
        multi = ca.calculate_expected_costs(100.0, 5)
        assert multi > single

    # ── Short expiry STT ────────────────────────────────────────

    def test_short_expiry_stt_call_itm(self):
        ca = CostAccountant()
        stt = ca.calculate_short_expiry_stt("CALL", 23000, 23500, 1, 50)
        # Intrinsic = 23500 - 23000 = 500, qty=1, lot=50 → 500*50=25000, STT=25000*0.001=25
        assert stt == 25.0

    def test_short_expiry_stt_put_itm(self):
        ca = CostAccountant()
        # Use 'PE' direction which is recognized by the source code
        stt = ca.calculate_short_expiry_stt("PE", 23500, 23000, 1, 50)
        # Intrinsic = 23500 - 23000 = 500
        assert stt > 0

    def test_short_expiry_stt_otm_is_zero(self):
        ca = CostAccountant()
        stt = ca.calculate_short_expiry_stt("CALL", 24000, 23500, 1, 50)
        assert stt == 0.0

    def test_short_expiry_stt_long_positions_zero(self):
        ca = CostAccountant()
        # Uses "BUY" direction which is not in SHORT/SELL/CALL/PE set
        stt = ca.calculate_short_expiry_stt("BUY", 23000, 23500, 1, 50)
        assert stt == 0.0

    def test_short_expiry_stt_zero_for_unknown_direction(self):
        ca = CostAccountant()
        stt = ca.calculate_short_expiry_stt("UNKNOWN", 23000, 23500, 1, 50)
        assert stt == 0.0

    # ── Singleton ───────────────────────────────────────────────

    def test_get_cost_accountant_returns_instance(self):
        ca = get_cost_accountant()
        assert isinstance(ca, CostAccountant)

    def test_get_cost_accountant_is_singleton(self):
        ca1 = get_cost_accountant()
        ca2 = get_cost_accountant()
        assert ca1 is ca2
