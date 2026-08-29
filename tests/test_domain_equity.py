"""Tests for core.domains.equity - Equity cash market domain models.

Covers:
  - Stock validation and fundamentals
  - CorporateAction types and validation
  - Holding validation and properties
  - IPO lifecycle and validation
  - EquityPosition validation
  - StockFundamentals validation
  - Edge cases
"""

from __future__ import annotations

from datetime import date

import pytest
from core.domains.equity import (
    IPO,
    CorporateAction,
    CorporateActionType,
    EquityPosition,
    Holding,
    Sector,
    Stock,
    StockFundamentals,
)


class TestStockFundamentals:
    def test_valid_fundamentals(self):
        f = StockFundamentals(market_cap=100000, pe_ratio=25, promoter_holding=45)
        assert f.market_cap == 100000
        assert f.pe_ratio == 25
        assert f.promoter_holding == 45

    def test_invalid_promoter_holding_raises(self):
        with pytest.raises(ValueError, match="Promoter holding must be 0-100%"):
            StockFundamentals(promoter_holding=150)

    def test_negative_market_cap_raises(self):
        with pytest.raises(ValueError, match="Market cap cannot be negative"):
            StockFundamentals(market_cap=-100)

    def test_total_holding(self):
        f = StockFundamentals(promoter_holding=50, fii_holding=15, dii_holding=15, public_holding=20)
        assert abs(f.total_holding - 100) < 0.01


class TestStock:
    def test_valid_stock(self):
        s = Stock("RELIANCE", "Reliance Industries Ltd", isin="INE002A01018",
                  sector=Sector.ENERGY)
        assert s.symbol == "RELIANCE"
        assert s.isin == "INE002A01018"

    def test_empty_symbol_raises(self):
        with pytest.raises(ValueError, match="Stock symbol cannot be empty"):
            Stock("")

    def test_negative_price_raises(self):
        with pytest.raises(ValueError, match="Last price cannot be negative"):
            Stock("RELIANCE", last_price=-10)

    def test_zero_face_value_raises(self):
        with pytest.raises(ValueError, match="Face value must be positive"):
            Stock("RELIANCE", face_value=0)

    def test_corporate_action_with_forward_ref(self):
        """Verify forward reference list['CorporateAction'] works at runtime."""
        s = Stock("TCS", isin="INE467B01029")
        ca = CorporateAction("TCS", CorporateActionType.DIVIDEND, amount=15.0)
        s.corporate_actions.append(ca)
        assert len(s.corporate_actions) == 1
        assert s.corporate_actions[0].amount == 15.0


class TestCorporateAction:
    def test_valid_dividend(self):
        ca = CorporateAction("RELIANCE", CorporateActionType.DIVIDEND,
                             ex_date=date(2026, 6, 20), amount=15.0)
        assert ca.action_type == CorporateActionType.DIVIDEND
        assert ca.amount == 15.0

    def test_negative_amount_raises(self):
        with pytest.raises(ValueError, match="Amount cannot be negative"):
            CorporateAction("RELIANCE", CorporateActionType.DIVIDEND, amount=-5)

    def test_empty_symbol_raises(self):
        with pytest.raises(ValueError, match="Stock symbol cannot be empty"):
            CorporateAction("", CorporateActionType.BONUS)

    def test_bonus_ratio(self):
        ca = CorporateAction("RELIANCE", CorporateActionType.BONUS, ratio="1:1")
        assert ca.ratio == "1:1"


class TestHolding:
    def test_valid_holding(self):
        h = Holding("RELIANCE", 100, 100, average_cost=2500, current_price=2600)
        assert h.investment_value == 250000
        assert h.market_value == 260000

    def test_available_exceeds_total_raises(self):
        with pytest.raises(ValueError, match="Available quantity.*> total quantity"):
            Holding("RELIANCE", 100, 150)

    def test_negative_quantity_raises(self):
        with pytest.raises(ValueError, match="Quantity cannot be negative"):
            Holding("RELIANCE", -1, 0)

    def test_zero_cost_raises(self):
        with pytest.raises(ValueError, match="Average cost cannot be negative"):
            Holding("RELIANCE", 100, 100, average_cost=-10)


class TestIPO:
    def test_valid_ipo(self):
        ipo = IPO("TechCorp Ltd", symbol="TECHCORP",
                   issue_price_min=100, issue_price_max=120,
                   lot_size=50, open_date=date(2026, 7, 1), close_date=date(2026, 7, 3))
        assert ipo.symbol == "TECHCORP"
        assert ipo.is_open is False  # status not set to OPEN
        assert ipo.price_band == (100, 120)

    def test_min_exceeds_max_raises(self):
        with pytest.raises(ValueError, match="Min price.*> max price"):
            IPO("Test Co", issue_price_min=200, issue_price_max=100)


class TestEquityPosition:
    def test_valid_position(self):
        stock = Stock("RELIANCE")
        pos = EquityPosition(stock, 100, 2500, 2550)
        assert pos.pnl_points == 100 * 50
        assert pos.position_value == 255000

    def test_zero_average_price_raises(self):
        stock = Stock("RELIANCE")
        with pytest.raises(ValueError, match="Average price must be positive"):
            EquityPosition(stock, 100, 0, 2500)
