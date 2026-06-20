"""Tests for core.domains.fo - Futures & Options domain models.

Covers:
  - ContractSpec validation and NFO_CONTRACT_SPECS presets
  - FutureContract validation and properties
  - OptionContract validation, moneyness, Greeks
  - FuturePosition, OptionPosition validation
  - SpreadLeg and SpreadPosition validation
  - Edge cases (zero prices, invalid types, empty spreads)
"""

from __future__ import annotations


import pytest

from core.domains.fo import (
    ContractSpec,
    ExpiryType,
    FutureContract,
    FuturePosition,
    NFO_CONTRACT_SPECS,
    OptionContract,
    OptionPosition,
    PositionType,
    SpreadLeg,
    SpreadPosition,
    SpreadType,
    UnderlyingType,
)


class TestContractSpec:
    def test_valid_spec(self):
        spec = ContractSpec("NIFTY", "NFO", UnderlyingType.INDEX, 50, 0.05)
        assert spec.symbol == "NIFTY"
        assert spec.lot_size == 50
        assert spec.tick_size == 0.05

    def test_zero_lot_size_raises(self):
        with pytest.raises(ValueError, match="Lot size must be positive"):
            ContractSpec("NIFTY", "NFO", UnderlyingType.INDEX, 0, 0.05)

    def test_negative_tick_size_raises(self):
        with pytest.raises(ValueError, match="Tick size must be positive"):
            ContractSpec("NIFTY", "NFO", UnderlyingType.INDEX, 50, -0.05)

    def test_negative_price_band_raises(self):
        with pytest.raises(ValueError, match="Price band must be positive"):
            ContractSpec("NIFTY", "NFO", UnderlyingType.INDEX, 50, 0.05, price_band_pct=-1)

    def test_nfo_presets_have_all_indices(self):
        expected = {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX"}
        assert set(NFO_CONTRACT_SPECS.keys()) == expected

    def test_nfo_presets_valid(self):
        for name, spec in NFO_CONTRACT_SPECS.items():
            assert spec.lot_size > 0, f"{name} lot_size invalid"
            assert spec.tick_size > 0, f"{name} tick_size invalid"


class TestFutureContract:
    def test_valid_future(self):
        contract = FutureContract("NIFTY", date(2026, 6, 25), NFO_CONTRACT_SPECS["NIFTY"], last_price=23000)
        assert contract.symbol == "NIFTY"
        assert contract.notional_value > 0

    def test_negative_price_raises(self):
        with pytest.raises(ValueError, match="Last price cannot be negative"):
            FutureContract("NIFTY", date(2026, 6, 25), last_price=-100)

    def test_negative_oi_raises(self):
        with pytest.raises(ValueError, match="Open interest cannot be negative"):
            FutureContract("NIFTY", date(2026, 6, 25), open_interest=-10)

    def test_days_to_expiry(self):
        far = date(2099, 12, 31)
        contract = FutureContract("NIFTY", far)
        assert contract.days_to_expiry > 0

    def test_past_expiry_zero_days(self):
        past = date(2020, 1, 1)
        contract = FutureContract("NIFTY", past)
        assert contract.days_to_expiry == 0

    def test_notional_value_with_spec(self):
        spec = NFO_CONTRACT_SPECS["NIFTY"]
        contract = FutureContract("NIFTY", date(2026, 6, 25), spec, last_price=23000.0)
        assert contract.notional_value == 23000.0 * 50


class TestOptionContract:
    def test_valid_call(self):
        opt = OptionContract("NIFTY", "CE", 23000, date(2026, 6, 25))
        assert opt.is_call is True
        assert opt.is_put is False

    def test_valid_put(self):
        opt = OptionContract("NIFTY", "PE", 23000, date(2026, 6, 25))
        assert opt.is_call is False
        assert opt.is_put is True

    def test_invalid_option_type_raises(self):
        with pytest.raises(ValueError, match="Option type must be 'CE' or 'PE'"):
            OptionContract("NIFTY", "XX", 23000, date(2026, 6, 25))

    def test_zero_strike_raises(self):
        with pytest.raises(ValueError, match="Strike must be positive"):
            OptionContract("NIFTY", "CE", 0, date(2026, 6, 25))

    def test_negative_price_raises(self):
        with pytest.raises(ValueError, match="Last price cannot be negative"):
            OptionContract("NIFTY", "CE", 23000, date(2026, 6, 25), last_price=-10)

    def test_moneyness_call_itm(self):
        opt = OptionContract("NIFTY", "CE", 20000, date(2026, 6, 25), spot_price=21000)
        assert opt.moneyness == "ITM"

    def test_moneyness_call_otm(self):
        opt = OptionContract("NIFTY", "CE", 24000, date(2026, 6, 25), spot_price=23000)
        assert opt.moneyness == "OTM"

    def test_moneyness_call_atm(self):
        opt = OptionContract("NIFTY", "CE", 23000, date(2026, 6, 25), spot_price=23100)
        assert opt.moneyness == "ATM"

    def test_moneyness_put_itm(self):
        opt = OptionContract("NIFTY", "PE", 24000, date(2026, 6, 25), spot_price=23000)
        assert opt.moneyness == "ITM"

    def test_moneyness_unknown_when_no_spot(self):
        opt = OptionContract("NIFTY", "CE", 23000, date(2026, 6, 25))
        assert opt.moneyness == "UNKNOWN"

    def test_bid_ask_spread_pct(self):
        opt = OptionContract("NIFTY", "CE", 23000, date(2026, 6, 25),
                            bid=100, ask=110)
        spread = opt.bid_ask_spread_pct
        assert spread > 0

    def test_bid_ask_spread_zero_when_prices_zero(self):
        opt = OptionContract("NIFTY", "CE", 23000, date(2026, 6, 25))
        assert opt.bid_ask_spread_pct == 0.0

    def test_days_to_expiry(self):
        far = date(2099, 12, 31)
        opt = OptionContract("NIFTY", "CE", 23000, far)
        assert opt.days_to_expiry > 0


class TestFuturePosition:
    def test_valid_long(self):
        contract = FutureContract("NIFTY", date(2026, 6, 25), last_price=23000)
        pos = FuturePosition(contract, 50, 23000, 23100)
        assert pos.position_type == PositionType.LONG
        assert pos.pnl_points > 0

    def test_valid_short(self):
        contract = FutureContract("NIFTY", date(2026, 6, 25), last_price=23000)
        pos = FuturePosition(contract, -50, 23000, 22800)
        assert pos.position_type == PositionType.SHORT
        assert pos.pnl_points > 0  # Short, price went down = profit

    def test_zero_average_price_raises(self):
        contract = FutureContract("NIFTY", date(2026, 6, 25))
        with pytest.raises(ValueError, match="Average price must be positive"):
            FuturePosition(contract, 50, 0, 100)

    def test_zero_current_price_raises(self):
        contract = FutureContract("NIFTY", date(2026, 6, 25))
        with pytest.raises(ValueError, match="Current price must be positive"):
            FuturePosition(contract, 50, 100, 0)


class TestOptionPosition:
    def test_valid_long_option(self):
        opt = OptionContract("NIFTY", "CE", 23000, date(2026, 6, 25))
        pos = OptionPosition(opt, 50, 100, 150)
        assert pos.position_type == PositionType.LONG
        assert pos.is_long_option is True
        assert pos.is_short_option is False

    def test_valid_short_option(self):
        opt = OptionContract("NIFTY", "CE", 23000, date(2026, 6, 25))
        pos = OptionPosition(opt, -50, 100, 80)
        assert pos.position_type == PositionType.SHORT
        assert pos.is_long_option is False
        assert pos.is_short_option is True


class TestSpreadLeg:
    def test_valid_leg(self):
        opt = OptionContract("NIFTY", "CE", 23000, date(2026, 6, 25))
        leg = SpreadLeg(1, opt, 50, "BUY")
        assert leg.leg_id == 1
        assert leg.action == "BUY"

    def test_invalid_action_raises(self):
        opt = OptionContract("NIFTY", "CE", 23000, date(2026, 6, 25))
        with pytest.raises(ValueError, match="Action must be 'BUY' or 'SELL'"):
            SpreadLeg(1, opt, 50, "HOLD")

    def test_zero_quantity_raises(self):
        opt = OptionContract("NIFTY", "CE", 23000, date(2026, 6, 25))
        with pytest.raises(ValueError, match="Quantity must be positive"):
            SpreadLeg(1, opt, 0, "BUY")


class TestSpreadPosition:
    def test_valid_vertical_spread(self):
        opt1 = OptionContract("NIFTY", "CE", 23000, date(2026, 6, 25))
        opt2 = OptionContract("NIFTY", "CE", 23500, date(2026, 6, 25))
        legs = [SpreadLeg(1, opt1, 50, "BUY"), SpreadLeg(2, opt2, 50, "SELL")]
        spread = SpreadPosition(SpreadType.VERTICAL, legs)
        assert spread.num_legs == 2
        assert spread.spread_type == SpreadType.VERTICAL

    def test_empty_legs_raises(self):
        with pytest.raises(ValueError, match="Spread must have at least one leg"):
            SpreadPosition(SpreadType.CUSTOM, [])

    def test_credit_spread(self):
        opt1 = OptionContract("NIFTY", "PE", 23000, date(2026, 6, 25))
        opt2 = OptionContract("NIFTY", "PE", 22500, date(2026, 6, 25))
        legs = [SpreadLeg(1, opt1, 50, "SELL"), SpreadLeg(2, opt2, 50, "BUY")]
        spread = SpreadPosition(SpreadType.VERTICAL, legs, net_premium=-1000)
        assert spread.is_credit_spread is True
        assert spread.is_debit_spread is False

    def test_risk_reward_ratio(self):
        opt1 = OptionContract("NIFTY", "CE", 23000, date(2026, 6, 25))
        opt2 = OptionContract("NIFTY", "CE", 23500, date(2026, 6, 25))
        legs = [SpreadLeg(1, opt1, 50, "BUY"), SpreadLeg(2, opt2, 50, "SELL")]
        spread = SpreadPosition(SpreadType.VERTICAL, legs, max_profit=5000, max_loss=2000)
        assert spread.risk_reward_ratio == 2.5
