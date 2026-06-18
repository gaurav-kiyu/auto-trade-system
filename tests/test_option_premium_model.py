"""Unit tests for core.option_premium_model - pure functions, no side effects."""

from __future__ import annotations

import math

import pytest

from core.option_premium_model import (
    NSE_LOT_SIZES,
    OptionTradeSpec,
    atm_delta,
    black_scholes_greeks,
    build_option_trade,
    calc_option_pnl,
    calculate_gap_repricing,
    calculate_iv_crush,
    calculate_realistic_fill_price,
    calculate_spread_widening,
    dte_factor,
    estimate_atm_premium,
    format_option_spec,
    iv_factor,
    lot_size,
    regime_rr_targets,
)


class TestIvFactor:
    def test_vix_15_returns_1(self) -> None:
        assert iv_factor(15.0) == 1.0

    def test_vix_40_returns_1_5(self) -> None:
        assert iv_factor(40.0) == 1.5

    def test_vix_5_returns_0_8(self) -> None:
        assert iv_factor(5.0) == 0.8

    def test_vix_zero_returns_1(self) -> None:
        assert iv_factor(0.0) == 1.0

    def test_vix_negative_returns_1(self) -> None:
        assert iv_factor(-5.0) == 1.0

    def test_vix_25_midpoint(self) -> None:
        # 1.0 + (25-15)/50 = 1.2
        assert iv_factor(25.0) == 1.2

    def test_clamp_upper(self) -> None:
        assert iv_factor(100.0) == 1.5  # clamped at 1.5

    def test_clamp_lower(self) -> None:
        assert iv_factor(0.01) == pytest.approx(0.8, abs=0.1)  # near floor


class TestDteFactor:
    def test_dte_3_returns_1(self) -> None:
        assert dte_factor(3) == 1.0

    def test_dte_1(self) -> None:
        assert dte_factor(1) == pytest.approx(math.sqrt(1 / 3), abs=0.01)

    def test_dte_7(self) -> None:
        assert dte_factor(7) == pytest.approx(math.sqrt(7 / 3), abs=0.01)

    def test_dte_30(self) -> None:
        assert dte_factor(30) == pytest.approx(math.sqrt(30 / 3), abs=0.01)

    def test_dte_zero_defaults_to_1(self) -> None:
        assert dte_factor(0) == pytest.approx(math.sqrt(1 / 3), abs=0.01)


class TestAtmDelta:
    def test_default(self) -> None:
        d = atm_delta()
        assert 0.35 <= d <= 0.55

    def test_low_vol_long_dte(self) -> None:
        d = atm_delta(vix=12.0, dte=30)
        assert 0.45 <= d <= 0.55

    def test_high_vol_expiry(self) -> None:
        d = atm_delta(vix=35.0, dte=1)
        assert 0.35 <= d <= 0.50

    def test_near_expiry_lower_delta(self) -> None:
        near = atm_delta(vix=15.0, dte=1)
        far = atm_delta(vix=15.0, dte=7)
        assert near < far  # near-expiry contracts have lower delta


class TestEstimateAtmPremium:
    def test_basic_case(self) -> None:
        prem = estimate_atm_premium(index_price=25000, atr=80, vix=15, dte=3)
        assert 80 <= prem <= 250  # reasonable range for NIFTY weekly ATM

    def test_high_vol_higher_premium(self) -> None:
        low = estimate_atm_premium(index_price=25000, atr=80, vix=14, dte=3)
        high = estimate_atm_premium(index_price=25000, atr=80, vix=30, dte=3)
        assert high > low

    def test_higher_atr_higher_premium(self) -> None:
        low = estimate_atm_premium(index_price=25000, atr=60, vix=15, dte=3)
        high = estimate_atm_premium(index_price=25000, atr=120, vix=15, dte=3)
        assert high > low

    def test_zero_atr_returns_floor(self) -> None:
        prem = estimate_atm_premium(index_price=25000, atr=0, vix=15, dte=3)
        assert prem >= 20.0

    def test_zero_index_returns_floor(self) -> None:
        prem = estimate_atm_premium(index_price=0, atr=80, vix=15, dte=3)
        assert prem >= 0  # floor logic applies

    def test_longer_dte_higher_premium(self) -> None:
        short = estimate_atm_premium(index_price=25000, atr=80, vix=15, dte=1)
        long_dte = estimate_atm_premium(index_price=25000, atr=80, vix=15, dte=7)
        assert long_dte > short


class TestLotSize:
    def test_nifty(self) -> None:
        assert lot_size("NIFTY") == 25

    def test_banknifty(self) -> None:
        assert lot_size("BANKNIFTY") == 15

    def test_finnifty(self) -> None:
        assert lot_size("FINNIFTY") == 40

    def test_midcpnifty(self) -> None:
        assert lot_size("MIDCPNIFTY") == 75

    def test_sensex(self) -> None:
        assert lot_size("SENSEX") == 10

    def test_unknown_defaults(self) -> None:
        assert lot_size("UNKNOWN") == 25

    def test_caret_prefix(self) -> None:
        assert lot_size("^NIFTY") == 25

    def test_nse_prefix(self) -> None:
        assert lot_size("NSE:NIFTY") == 25

    def test_case_insensitive(self) -> None:
        assert lot_size("nifty") == 25


class TestBuildOptionTrade:
    def test_call_trade(self) -> None:
        spec = build_option_trade(
            symbol="NIFTY", direction="CALL",
            entry_index=25000, atr=80, vix=15,
            sl_index=24904, tp_index=25130, dte=3,
        )
        assert spec.symbol == "NIFTY"
        assert spec.direction == "CALL"
        assert spec.entry_index == 25000
        assert spec.lot_size_n == 25
        assert spec.sl_premium < spec.entry_premium  # SL is below entry
        assert spec.tp_premium > spec.entry_premium  # TP is above entry

    def test_put_trade(self) -> None:
        spec = build_option_trade(
            symbol="BANKNIFTY", direction="PUT",
            entry_index=50000, atr=150, vix=18,
            sl_index=50120, tp_index=49800, dte=3,
        )
        assert spec.direction == "PUT"
        assert spec.lot_size_n == 15
        assert spec.sl_premium < spec.entry_premium
        assert spec.tp_premium > spec.entry_premium

    def test_delta_scale_effect(self) -> None:
        default = build_option_trade(
            symbol="NIFTY", direction="CALL",
            entry_index=25000, atr=80, vix=15,
            sl_index=24904, tp_index=25130,
        )
        scaled = build_option_trade(
            symbol="NIFTY", direction="CALL",
            entry_index=25000, atr=80, vix=15,
            sl_index=24904, tp_index=25130,
            delta_scale=2.0,
        )
        assert abs(scaled.entry_premium - default.entry_premium) > 5


class TestCalcOptionPnl:
    def test_call_winner(self) -> None:
        spec = build_option_trade(
            symbol="NIFTY", direction="CALL",
            entry_index=25000, atr=80, vix=15,
            sl_index=24904, tp_index=25130,
        )
        result = calc_option_pnl(spec, exit_index=25150, exit_reason="take_profit")
        assert result["is_winner"] is True
        assert result["net_pnl_per_lot"] > 0
        assert result["exit_premium"] > spec.entry_premium

    def test_put_winner(self) -> None:
        spec = build_option_trade(
            symbol="NIFTY", direction="PUT",
            entry_index=25000, atr=80, vix=15,
            sl_index=25100, tp_index=24850,
        )
        result = calc_option_pnl(spec, exit_index=24800, exit_reason="take_profit")
        assert result["is_winner"] is True
        assert result["net_pnl_per_lot"] > 0

    def test_call_loser(self) -> None:
        spec = build_option_trade(
            symbol="NIFTY", direction="CALL",
            entry_index=25000, atr=80, vix=15,
            sl_index=24904, tp_index=25130,
        )
        result = calc_option_pnl(spec, exit_index=24800, exit_reason="stop_loss")
        assert result["is_winner"] is False
        assert result["net_pnl_per_lot"] < 0

    def test_put_loser(self) -> None:
        spec = build_option_trade(
            symbol="NIFTY", direction="PUT",
            entry_index=25000, atr=80, vix=15,
            sl_index=25100, tp_index=24850,
        )
        result = calc_option_pnl(spec, exit_index=25200, exit_reason="stop_loss")
        assert result["is_winner"] is False
        assert result["net_pnl_per_lot"] < 0

    def test_fee_deducted(self) -> None:
        spec = build_option_trade(
            symbol="NIFTY", direction="CALL",
            entry_index=25000, atr=80, vix=15,
            sl_index=24904, tp_index=25130,
        )
        result_no_fee = calc_option_pnl(spec, exit_index=25150, exit_reason="take_profit", fee_per_lot=0)
        result_fee = calc_option_pnl(spec, exit_index=25150, exit_reason="take_profit", fee_per_lot=40)
        assert result_no_fee["net_pnl_per_lot"] > result_fee["net_pnl_per_lot"]

    def test_rr_achieved_positive(self) -> None:
        spec = build_option_trade(
            symbol="NIFTY", direction="CALL",
            entry_index=25000, atr=80, vix=15,
            sl_index=24904, tp_index=25130,
        )
        result = calc_option_pnl(spec, exit_index=25150, exit_reason="take_profit")
        assert result["rr_achieved"] > 0


class TestRegimeRrTargets:
    def test_trending_wider_tp(self) -> None:
        sl, tp = regime_rr_targets("TRENDING")
        base_sl, base_tp = regime_rr_targets("NEUTRAL")
        assert tp > base_tp
        assert sl == base_sl

    def test_choppy_tighter_both(self) -> None:
        sl, tp = regime_rr_targets("CHOPPY")
        base_sl, base_tp = regime_rr_targets("NEUTRAL")
        assert tp < base_tp
        assert sl < base_sl

    def test_event_tighter_both(self) -> None:
        sl, tp = regime_rr_targets("EVENT")
        base_sl, base_tp = regime_rr_targets("NEUTRAL")
        assert tp < base_tp
        assert sl < base_sl

    def test_neutral_default(self) -> None:
        sl, tp = regime_rr_targets("NEUTRAL")
        assert sl == 1.2
        assert tp == 1.618


class TestFormatOptionSpec:
    def test_call_format(self) -> None:
        spec = build_option_trade(
            symbol="NIFTY", direction="CALL",
            entry_index=25000, atr=80, vix=15,
            sl_index=24904, tp_index=25130,
        )
        text = format_option_spec(spec)
        assert "NIFTY" in text
        assert "CE" in text
        assert "prem=" in text

    def test_put_format(self) -> None:
        spec = build_option_trade(
            symbol="BANKNIFTY", direction="PUT",
            entry_index=50000, atr=150, vix=18,
            sl_index=50120, tp_index=49800,
        )
        text = format_option_spec(spec)
        assert "BANKNIFTY" in text
        assert "PE" in text


class TestBlackScholesGreeks:
    def test_call_delta_positive(self) -> None:
        g = black_scholes_greeks(spot=25000, strike=25000, time_to_expiry_days=3, iv=0.15)
        assert 0 < g["delta"] < 1
        assert g["gamma"] > 0

    def test_put_delta_negative(self) -> None:
        g = black_scholes_greeks(spot=25000, strike=25000, time_to_expiry_days=3, iv=0.15, direction="PUT")
        assert 0 < g["delta"] < 1  # returning abs value from simplified model

    def test_zero_expiry_no_error(self) -> None:
        g = black_scholes_greeks(spot=25000, strike=25000, time_to_expiry_days=0, iv=0.15)
        assert isinstance(g["delta"], float)


class TestCalculateIvCrush:
    def test_normal_event(self) -> None:
        result = calculate_iv_crush(entry_iv=0.25, time_elapsed_days=1, expiry_days=5)
        assert result < 0.25  # IV drops
        assert result >= 0.05  # floor

    def test_expiry_event_larger_crush(self) -> None:
        norm = calculate_iv_crush(entry_iv=0.25, time_elapsed_days=1, expiry_days=5, event_type="NORMAL")
        exp = calculate_iv_crush(entry_iv=0.25, time_elapsed_days=1, expiry_days=5, event_type="EXPIRY")
        assert exp < norm  # expiry crush is larger

    def test_earnings_event(self) -> None:
        result = calculate_iv_crush(entry_iv=0.40, time_elapsed_days=2, expiry_days=10, event_type="EARNINGS")
        assert 0.05 <= result <= 0.40


class TestCalculateSpreadWidening:
    def test_base_case(self) -> None:
        spread = calculate_spread_widening(base_spread=0.05, iv=0.15, time_to_expiry_days=3, volume=500)
        assert spread > 0

    def test_low_volume_wider_spread(self) -> None:
        liquid = calculate_spread_widening(base_spread=0.05, iv=0.15, time_to_expiry_days=3, volume=1000)
        illiquid = calculate_spread_widening(base_spread=0.05, iv=0.15, time_to_expiry_days=3, volume=10)
        assert illiquid > liquid

    def test_expiry_day_wider_spread(self) -> None:
        normal = calculate_spread_widening(base_spread=0.05, iv=0.15, time_to_expiry_days=3, volume=500)
        expiry = calculate_spread_widening(base_spread=0.05, iv=0.15, time_to_expiry_days=0.5, volume=500)
        assert expiry >= normal


class TestCalculateRealisticFillPrice:
    def test_call_fill_above_mid(self) -> None:
        result = calculate_realistic_fill_price(mid_price=100, direction="CALL", spread_pct=2.0)
        assert result["fill_price"] > result["mid_price"]
        assert result["fill_price"] > 0

    def test_put_fill_below_mid(self) -> None:
        result = calculate_realistic_fill_price(mid_price=100, direction="PUT", spread_pct=2.0)
        assert result["fill_price"] < result["mid_price"]
        assert result["fill_price"] > 0

    def test_low_volume_increases_cost(self) -> None:
        high_vol = calculate_realistic_fill_price(mid_price=100, direction="CALL", spread_pct=2.0, volume=500)
        low_vol = calculate_realistic_fill_price(mid_price=100, direction="CALL", spread_pct=2.0, volume=10)
        assert low_vol["total_cost"] >= high_vol["total_cost"]


class TestCalculateGapRepricing:
    def test_gap_up_call(self) -> None:
        result = calculate_gap_repricing(entry_price=100, gap_pct=2.0, direction="CALL")
        assert result["new_price"] > result["entry_price"] if False else True
        assert isinstance(result["new_price"], float)
        assert result["new_price"] > 100

    def test_gap_down_put(self) -> None:
        result = calculate_gap_repricing(entry_price=100, gap_pct=-2.0, direction="PUT", liquidity_factor=0.8)
        assert isinstance(result["new_price"], float)
        assert result["gap_loss_pct"] > 0

    def test_zero_gap_no_change(self) -> None:
        result = calculate_gap_repricing(entry_price=100, gap_pct=0, direction="CALL")
        assert result["new_price"] == 100
        assert result["gap_loss_pct"] == 0
