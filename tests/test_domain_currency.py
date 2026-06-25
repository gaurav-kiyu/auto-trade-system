"""Tests for core.domains.currency - Currency derivatives domain models.

Covers:
  - ContractSpec validation and CURRENCY_CONTRACT_SPECS presets
  - CurrencyContract validation
  - CurrencyOptionContract validation
  - CurrencyPosition validation
  - Edge cases
"""

from __future__ import annotations

from datetime import date

import pytest

from core.domains.currency.models import (
    ContractSpec,
    CURRENCY_CONTRACT_SPECS,
    CurrencyContract,
    CurrencyOptionContract,
    CurrencyPair,
    CurrencyPosition,
    PositionType,
)


class TestContractSpec:
    def test_valid_spec(self):
        spec = ContractSpec(CurrencyPair.USD_INR, "CDS", 1000, 0.0025, 2.5)
        assert spec.pair == CurrencyPair.USD_INR
        assert spec.lot_size == 1000

    def test_zero_lot_size_raises(self):
        with pytest.raises(ValueError, match="Lot size must be positive"):
            ContractSpec(CurrencyPair.USD_INR, "CDS", 0, 0.0025, 2.5)

    def test_presets_have_all_pairs(self):
        expected = {"USDINR", "EURINR", "GBPINR", "JPYINR"}
        assert set(CURRENCY_CONTRACT_SPECS.keys()) == expected


class TestCurrencyContract:
    def test_valid_contract(self):
        contract = CurrencyContract(CurrencyPair.USD_INR, date(2026, 7, 28))
        assert contract.pair == CurrencyPair.USD_INR

    def test_notional_value(self):
        spec = CURRENCY_CONTRACT_SPECS["USDINR"]
        contract = CurrencyContract(CurrencyPair.USD_INR, date(2026, 7, 28), spec, last_price=83.50)
        assert abs(contract.notional_value - 83.50 * 1000) < 0.01

    def test_negative_price_raises(self):
        with pytest.raises(ValueError, match="Last price cannot be negative"):
            CurrencyContract(CurrencyPair.USD_INR, date(2026, 7, 28), last_price=-10)


class TestCurrencyOptionContract:
    def test_valid_call(self):
        opt = CurrencyOptionContract(CurrencyPair.USD_INR, "CE", 84.0, date(2026, 7, 28))
        assert opt.is_call is True
        assert opt.is_put is False

    def test_valid_put(self):
        opt = CurrencyOptionContract(CurrencyPair.USD_INR, "PE", 84.0, date(2026, 7, 28))
        assert opt.is_call is False
        assert opt.is_put is True

    def test_invalid_option_type_raises(self):
        with pytest.raises(ValueError, match="Option type must be 'CE' or 'PE'"):
            CurrencyOptionContract(CurrencyPair.USD_INR, "XX", 84.0, date(2026, 7, 28))

    def test_zero_strike_raises(self):
        with pytest.raises(ValueError, match="Strike must be positive"):
            CurrencyOptionContract(CurrencyPair.USD_INR, "CE", 0, date(2026, 7, 28))


class TestCurrencyPosition:
    def test_valid_long(self):
        contract = CurrencyContract(CurrencyPair.USD_INR, date(2026, 7, 28), last_price=83.50)
        pos = CurrencyPosition(contract, 1000, 83.50, 84.00)
        assert pos.position_type == PositionType.LONG

    def test_invalid_average_price_raises(self):
        contract = CurrencyContract(CurrencyPair.USD_INR, date(2026, 7, 28))
        with pytest.raises(ValueError, match="Average price must be positive"):
            CurrencyPosition(contract, 1000, 0, 84.00)
