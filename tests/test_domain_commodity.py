"""Tests for core.domains.commodity - Commodity derivatives domain models.

Covers:
  - ContractSpec validation and MCX_CONTRACT_SPECS presets
  - CommodityContract validation and properties (notional, margin)
  - CommodityPosition validation
  - Edge cases (zero prices, invalid categories)
"""

from __future__ import annotations

from datetime import date

import pytest
from core.domains.commodity import (
    MCX_CONTRACT_SPECS,
    CommodityCategory,
    CommodityContract,
    CommodityPosition,
    ContractSpec,
    PositionType,
)


class TestContractSpec:
    def test_valid_spec(self):
        spec = ContractSpec(
            "GOLD", "MCX", CommodityCategory.BULLION,
            1, 1.0, 1.0,
        )
        assert spec.symbol == "GOLD"
        assert spec.lot_size == 1

    def test_zero_lot_size_raises(self):
        with pytest.raises(ValueError, match="Lot size must be positive"):
            ContractSpec("GOLD", "MCX", CommodityCategory.BULLION, 0, 1.0, 1.0)

    def test_mcx_presets_have_all_commodities(self):
        expected = {"GOLD", "GOLDM", "SILVER", "SILVERM", "CRUDEOIL", "NATURALGAS", "COPPER", "ZINC", "ALUMINIUM"}
        assert set(MCX_CONTRACT_SPECS.keys()) == expected

    def test_mcx_presets_valid(self):
        for name, spec in MCX_CONTRACT_SPECS.items():
            assert spec.lot_size > 0
            assert spec.tick_size > 0
            assert spec.tick_value > 0


class TestCommodityContract:
    def test_valid_contract(self):
        contract = CommodityContract("GOLD", date(2026, 7, 5), MCX_CONTRACT_SPECS["GOLD"])
        assert contract.symbol == "GOLD"

    def test_notional_value(self):
        spec = MCX_CONTRACT_SPECS["GOLD"]
        contract = CommodityContract("GOLD", date(2026, 7, 5), spec, last_price=65000)
        assert contract.notional_value == 65000 * 1

    def test_margin_required(self):
        spec = MCX_CONTRACT_SPECS["GOLD"]
        contract = CommodityContract("GOLD", date(2026, 7, 5), spec, last_price=65000)
        expected_margin = 65000 * 1 * (5.0 / 100)
        assert abs(contract.margin_required - expected_margin) < 0.01

    def test_no_spec_margin_zero(self):
        contract = CommodityContract("GOLD", date(2026, 7, 5), last_price=65000)
        assert contract.margin_required == 0.0

    def test_negative_price_raises(self):
        with pytest.raises(ValueError, match="Last price cannot be negative"):
            CommodityContract("GOLD", date(2026, 7, 5), last_price=-100)


class TestCommodityPosition:
    def test_valid_long(self):
        contract = CommodityContract("GOLD", date(2026, 7, 5), last_price=65000)
        pos = CommodityPosition(contract, 1, 65000, 66500)
        assert pos.position_type == PositionType.LONG
        assert pos.pnl_points > 0

    def test_valid_short(self):
        contract = CommodityContract("GOLD", date(2026, 7, 5), last_price=65000)
        pos = CommodityPosition(contract, -1, 65000, 64000)
        assert pos.position_type == PositionType.SHORT
        assert pos.pnl_points > 0

    def test_zero_average_price_raises(self):
        contract = CommodityContract("GOLD", date(2026, 7, 5))
        with pytest.raises(ValueError, match="Average price must be positive"):
            CommodityPosition(contract, 1, 0, 100)
