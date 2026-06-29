"""Tests for core.domains.sme - SME equity domain models.

Covers:
  - SmeStock validation and properties (circuit limits, T2T)
  - SmeStockFundamentals validation
  - SmeIpo lifecycle and pricing
  - SmePosition validation
  - Edge cases and validation errors
"""

from __future__ import annotations

from datetime import date

import pytest
from core.domains.equity import CorporateAction, CorporateActionType, Sector
from core.domains.sme import (
    SmeIpo,
    SmeIssueType,
    SmeListingBasis,
    SmePlatform,
    SmePosition,
    SmeStock,
    SmeStockFundamentals,
    SmeTradingRestriction,
)


class TestSmeStockFundamentals:
    def test_valid_fundamentals(self):
        f = SmeStockFundamentals(market_cap=100, promoter_holding=45, circuit_limit_pct=5.0)
        assert f.market_cap == 100
        assert f.circuit_limit_pct == 5.0
        assert f.is_small_cap is True

    def test_invalid_promoter_holding_raises(self):
        with pytest.raises(ValueError, match="Promoter holding must be 0-100%"):
            SmeStockFundamentals(promoter_holding=150)

    def test_negative_market_cap_raises(self):
        with pytest.raises(ValueError, match="Market cap cannot be negative"):
            SmeStockFundamentals(market_cap=-100)

    def test_invalid_circuit_limit_raises(self):
        with pytest.raises(ValueError, match="Circuit limit must be 0-20%"):
            SmeStockFundamentals(circuit_limit_pct=0)

    def test_default_circuit_limit(self):
        """Default circuit limit for SME stocks should be 5%."""
        f = SmeStockFundamentals()
        assert f.circuit_limit_pct == 5.0


class TestSmeStock:
    def test_valid_stock(self):
        stock = SmeStock("XYZLTD", "XYZ Ltd", isin="INE123456789", sector=Sector.INFORMATION_TECHNOLOGY)
        assert stock.symbol == "XYZLTD"
        assert stock.platform == SmePlatform.NSE_EMERGE
        assert stock.has_t2t_restriction is False

    def test_empty_symbol_raises(self):
        with pytest.raises(ValueError, match="SME stock symbol cannot be empty"):
            SmeStock("")

    def test_negative_price_raises(self):
        with pytest.raises(ValueError, match="Last price cannot be negative"):
            SmeStock("XYZLTD", last_price=-10)

    def test_zero_face_value_raises(self):
        with pytest.raises(ValueError, match="Face value must be positive"):
            SmeStock("XYZLTD", face_value=0)

    def test_negative_issue_price_raises(self):
        with pytest.raises(ValueError, match="Issue price cannot be negative"):
            SmeStock("XYZLTD", issue_price=-1)

    def test_circuit_price_calculation(self):
        """Verify upper and lower circuit prices."""
        stock = SmeStock("XYZLTD", last_price=100.0)
        stock.fundamentals = SmeStockFundamentals(circuit_limit_pct=5.0)
        assert stock.upper_circuit == 105.0
        assert stock.lower_circuit == 95.0

    def test_t2t_restriction_detection(self):
        stock = SmeStock("XYZLTD", last_price=50.0,
                         restrictions=[SmeTradingRestriction.TRADE_TO_TRADE])
        assert stock.has_t2t_restriction is True

    def test_no_t2t_by_default(self):
        stock = SmeStock("XYZLTD", last_price=50.0)
        assert stock.has_t2t_restriction is False

    def test_10pct_circuit_limit(self):
        """Some SME stocks have 10% circuit limits."""
        stock = SmeStock("XYZLTD", last_price=100.0)
        stock.fundamentals = SmeStockFundamentals(circuit_limit_pct=10.0)
        assert stock.upper_circuit == pytest.approx(110.0, rel=1e-9)
        assert stock.lower_circuit == pytest.approx(90.0, rel=1e-9)

    def test_bse_sme_platform(self):
        stock = SmeStock("XYZLTD", platform=SmePlatform.BSE_SME)
        assert stock.platform == SmePlatform.BSE_SME

    def test_corporate_action_forward_ref(self):
        stock = SmeStock("XYZLTD", last_price=100.0)
        ca = CorporateAction("XYZLTD", CorporateActionType.DIVIDEND, amount=2.0)
        stock.corporate_actions.append(ca)
        assert len(stock.corporate_actions) == 1
        assert stock.corporate_actions[0].amount == 2.0

    def test_52_week_range(self):
        stock = SmeStock("XYZLTD", last_price=75.0, week_52_high=120.0, week_52_low=40.0)
        assert stock.week_52_high == 120.0
        assert stock.week_52_low == 40.0

    def test_multiple_restrictions(self):
        stock = SmeStock(
            "XYZLTD", last_price=100.0,
            restrictions=[
                SmeTradingRestriction.TRADE_TO_TRADE,
                SmeTradingRestriction.FIXED_PRICE_BAND,
            ],
        )
        assert len(stock.restrictions) == 2
        assert stock.has_t2t_restriction is True

    def test_circuit_percentage_fallback(self):
        """When no fundamentals set, circuit_percentage should default to 5%."""
        stock = SmeStock("XYZLTD", last_price=100.0)
        assert stock.circuit_percentage == 5.0

    def test_circuit_percentage_from_fundamentals(self):
        stock = SmeStock("XYZLTD", last_price=100.0)
        stock.fundamentals = SmeStockFundamentals(circuit_limit_pct=10.0)
        assert stock.circuit_percentage == 10.0

    def test_newly_listed_flag(self):
        stock = SmeStock("XYZLTD", last_price=120.0, issue_price=100.0,
                         listed_date=date(2026, 6, 15))
        assert stock.issue_price == 100.0
        assert stock.listed_date == date(2026, 6, 15)


class TestSmeIpo:
    def test_valid_ipo(self):
        ipo = SmeIpo(
            "TechSME Ltd", symbol="TECHSME",
            issue_price_min=100, issue_price_max=120,
            lot_size=15000, lot_shares=300,
            open_date=date(2026, 7, 1), close_date=date(2026, 7, 3),
        )
        assert ipo.symbol == "TECHSME"
        assert ipo.is_open is False
        assert ipo.price_band == (100, 120)
        assert ipo.min_investment_retail == 15000

    def test_min_exceeds_max_raises(self):
        with pytest.raises(ValueError, match="Min price.*> max price"):
            SmeIpo("Test Co", issue_price_min=200, issue_price_max=100)

    def test_negative_issue_price_raises(self):
        with pytest.raises(ValueError, match="Issue price min cannot be negative"):
            SmeIpo("Test Co", issue_price_min=-10)

    def test_open_status(self):
        ipo = SmeIpo("Test Co", status="OPEN")
        assert ipo.is_open is True

    def test_sme_ipo_retail_quota(self):
        """SME IPOs should have higher retail quota than mainboard."""
        ipo = SmeIpo("Test Co")
        assert ipo.retail_quota >= 35.0  # Minimum 35% retail quota for SME

    def test_fresh_plus_ofs_issue(self):
        ipo = SmeIpo("Test Co", issue_type=SmeIssueType.FRESH_OFS,
                      fresh_issue=30.0, offer_for_sale=10.0)
        assert ipo.issue_type == SmeIssueType.FRESH_OFS
        assert ipo.fresh_issue == 30.0
        assert ipo.offer_for_sale == 10.0

    def test_listing_date(self):
        ipo = SmeIpo("Test Co", listing_date=date(2026, 8, 1))
        assert ipo.listing_date == date(2026, 8, 1)

    def test_total_issue_calculation(self):
        ipo = SmeIpo("Test Co", total_issue_size=45.0)
        assert ipo.total_issue_size == 45.0

    def test_nse_emerge_default_platform(self):
        ipo = SmeIpo("Test Co")
        assert ipo.platform == SmePlatform.NSE_EMERGE

    def test_bse_sme_platform(self):
        ipo = SmeIpo("Test Co", platform=SmePlatform.BSE_SME)
        assert ipo.platform == SmePlatform.BSE_SME

    def test_subscription_tracking(self):
        ipo = SmeIpo("Test Co", total_subscription=150.0, retail_subscription=200.0)
        assert ipo.total_subscription == 150.0
        assert ipo.retail_subscription == 200.0

    def test_lot_sizes_table(self):
        ipo = SmeIpo("Test Co", lot_sizes=[{"category": "retail", "lots": 1}])
        assert len(ipo.lot_sizes) == 1

    def test_invalid_retail_quota_raises(self):
        with pytest.raises(ValueError, match="Retail quota must be 0-100%"):
            SmeIpo("Test Co", retail_quota=150)

    def test_proportionate_allotment_default(self):
        ipo = SmeIpo("Test Co")
        assert ipo.basis_of_allotment == SmeListingBasis.PROPORTIONATE

    def test_lottery_allotment_basis(self):
        ipo = SmeIpo("Test Co", basis_of_allotment=SmeListingBasis.LOTTERY)
        assert ipo.basis_of_allotment == SmeListingBasis.LOTTERY

    def test_empty_company_name_raises(self):
        with pytest.raises(ValueError, match="Company name cannot be empty"):
            SmeIpo("")


class TestSmePosition:
    def test_valid_long_position(self):
        stock = SmeStock("XYZLTD", last_price=100.0)
        pos = SmePosition(stock, 300, 95.0, 105.0)
        assert pos.quantity == 300
        assert pos.pnl_points == 300 * (105 - 95)
        assert pos.position_value == 300 * 105.0

    def test_valid_lot_check(self):
        stock = SmeStock("XYZLTD", last_price=100.0)
        pos = SmePosition(stock, 300, 95.0, 100.0, min_lot_quantity=300)
        assert pos.is_valid_lot is True

    def test_invalid_lot_check(self):
        stock = SmeStock("XYZLTD", last_price=100.0)
        pos = SmePosition(stock, 100, 95.0, 100.0, min_lot_quantity=300)
        assert pos.is_valid_lot is False

    def test_zero_average_price_raises(self):
        stock = SmeStock("XYZLTD", last_price=100.0)
        with pytest.raises(ValueError, match="Average price must be positive"):
            SmePosition(stock, 300, 0, 100.0)

    def test_zero_current_price_raises(self):
        stock = SmeStock("XYZLTD", last_price=100.0)
        with pytest.raises(ValueError, match="Current price must be positive"):
            SmePosition(stock, 300, 95.0, 0)

    def test_t2t_position(self):
        stock = SmeStock("XYZLTD", last_price=100.0)
        pos = SmePosition(stock, 300, 95.0, 100.0, is_t2t=True)
        assert pos.is_t2t is True

    def test_short_position(self):
        stock = SmeStock("XYZLTD", last_price=100.0)
        pos = SmePosition(stock, -300, 105.0, 95.0)
        assert pos.quantity == -300
        assert pos.pnl_points == -300 * (95 - 105)  # Short position profit
