"""Tests for core.domains.mutual_fund - Mutual Fund, ETF, REIT, InvIT domain models.

Covers:
  - NavRecord validation
  - FundHolding validation
  - PortfolioAllocation validation
  - MutualFund validation and properties
  - ETF-specific properties (premium/discount, tracking error)
  - REIT validation
  - InvIT validation
  - SIP validation
  - MFTransaction validation
  - Edge cases
"""

from __future__ import annotations

from datetime import date

import pytest
from core.domains.mutual_fund import (
    ETF,
    REIT,
    SIP,
    FundCategory,
    FundHolding,
    FundOption,
    FundPlan,
    FundType,
    InvIT,
    MFTransaction,
    MFTransactionType,
    MutualFund,
    NavRecord,
    PortfolioAllocation,
    SIPFrequency,
)


class TestNavRecord:
    def test_valid_nav(self):
        nav = NavRecord(date(2026, 6, 15), 125.50)
        assert nav.nav == 125.50

    def test_zero_nav_raises(self):
        with pytest.raises(ValueError, match="NAV must be positive"):
            NavRecord(date(2026, 6, 15), 0)

    def test_negative_nav_raises(self):
        with pytest.raises(ValueError, match="NAV must be positive"):
            NavRecord(date(2026, 6, 15), -10)

    def test_with_price_diff(self):
        nav = NavRecord(date(2026, 6, 15), 125.50, repurchase_price=124.50, sale_price=126.50)
        assert nav.repurchase_price == 124.50
        assert nav.sale_price == 126.50


class TestFundHolding:
    def test_valid_holding(self):
        h = FundHolding("Reliance Industries", allocation_pct=8.5)
        assert h.name == "Reliance Industries"
        assert h.allocation_pct == 8.5

    def test_empty_name_raises(self):
        with pytest.raises(ValueError, match="Holding name cannot be empty"):
            FundHolding("")

    def test_excessive_allocation_raises(self):
        with pytest.raises(ValueError, match="Allocation must be 0-100%"):
            FundHolding("Holding", allocation_pct=150)


class TestPortfolioAllocation:
    def test_valid_allocation(self):
        pa = PortfolioAllocation(equities=65, debt=25, cash=8, others=2)
        assert pa.is_invested is True

    def test_zero_allocation_not_invested(self):
        pa = PortfolioAllocation()
        assert pa.is_invested is False

    def test_over_100_raises(self):
        with pytest.raises(ValueError, match="Total allocation.*exceeds 100%"):
            PortfolioAllocation(equities=80, debt=30, cash=5)


class TestMutualFund:
    def test_valid_mf(self):
        mf = MutualFund("119551", "Nippon India Small Cap Fund - Direct Growth",
                        fund_house="Nippon India", fund_category=FundCategory.SMALL_CAP,
                        fund_type=FundType.OPEN_ENDED, plan=FundPlan.DIRECT,
                        option=FundOption.GROWTH, nav=150.25)
        assert mf.scheme_code == "119551"
        assert mf.nav == 150.25

    def test_empty_code_raises(self):
        with pytest.raises(ValueError, match="Scheme code cannot be empty"):
            MutualFund("", "")

    def test_empty_name_raises(self):
        with pytest.raises(ValueError, match="Scheme name cannot be empty"):
            MutualFund("119551", "")

    def test_negative_nav_raises(self):
        with pytest.raises(ValueError, match="NAV cannot be negative"):
            MutualFund("119551", "Fund", nav=-10)


class TestETF:
    def test_valid_etf(self):
        etf = ETF("119552", "Nippon India ETF Nifty 50 BeES",
                  fund_house="Nippon India", fund_category=FundCategory.ETF,
                  underlying_index="NIFTY 50", market_price=250.0)
        assert etf.underlying_index == "NIFTY 50"
        assert etf.is_premium is False  # premium_discount = 0

    def test_etf_premium(self):
        etf = ETF("119553", "Gold ETF", fund_house="Fund",
                  fund_category=FundCategory.GOLD_ETF,
                  is_gold=True, market_price=55.0, premium_discount=1.5)
        assert etf.is_gold is True
        assert etf.is_premium is True

    def test_zero_lot_size_raises(self):
        with pytest.raises(ValueError, match="Lot size must be positive"):
            ETF("E001", "ETF", fund_house="H", fund_category=FundCategory.ETF, lot_size=0)


class TestREIT:
    def test_valid_reit(self):
        reit = REIT("EMBASSY", "Embassy Office Parks REIT",
                    units_outstanding=100000000, market_price=350.0)
        assert reit.symbol == "EMBASSY"
        assert reit.market_cap > 0

    def test_empty_symbol_raises(self):
        with pytest.raises(ValueError, match="Symbol cannot be empty"):
            REIT("")

    def test_negative_price_raises(self):
        with pytest.raises(ValueError, match="Market price cannot be negative"):
            REIT("XYZ", market_price=-1)


class TestInvIT:
    def test_valid_invit(self):
        inv = InvIT("IRBINVIT", "IRB Infrastructure InvIT",
                    units_outstanding=200000000, market_price=120.0)
        assert inv.symbol == "IRBINVIT"
        assert inv.market_cap > 0

    def test_empty_symbol_raises(self):
        with pytest.raises(ValueError, match="Symbol cannot be empty"):
            InvIT("")


class TestSIP:
    def test_valid_sip(self):
        mf = MutualFund("119551", "Fund", fund_house="H")
        sip = SIP("SIP001", mf, SIPFrequency.MONTHLY, 5000)
        assert sip.sip_id == "SIP001"
        assert sip.amount == 5000

    def test_empty_id_raises(self):
        mf = MutualFund("119551", "Fund", fund_house="H")
        with pytest.raises(ValueError, match="SIP ID cannot be empty"):
            SIP("", mf, SIPFrequency.MONTHLY, 5000)

    def test_zero_amount_raises(self):
        mf = MutualFund("119551", "Fund", fund_house="H")
        with pytest.raises(ValueError, match="SIP amount must be positive"):
            SIP("SIP001", mf, SIPFrequency.MONTHLY, 0)

    def test_return_pct_with_profit(self):
        mf = MutualFund("119551", "Fund", fund_house="H")
        sip = SIP("SIP001", mf, SIPFrequency.MONTHLY, 5000,
                  total_invested=100000, current_value=120000)
        assert abs(sip.return_pct - 20.0) < 0.01


class TestMFTransaction:
    def test_valid_purchase(self):
        txn = MFTransaction("TXN001", "119551", MFTransactionType.PURCHASE,
                            5000, 40, 125.0, date(2026, 6, 15))
        assert txn.transaction_id == "TXN001"
        assert txn.amount == 5000

    def test_empty_id_raises(self):
        with pytest.raises(ValueError, match="Transaction ID cannot be empty"):
            MFTransaction("", "119551", MFTransactionType.PURCHASE, 5000, 40, 125.0, date.today())

    def test_negative_amount_raises(self):
        with pytest.raises(ValueError, match="Amount cannot be negative"):
            MFTransaction("T001", "119551", MFTransactionType.PURCHASE, -100, 10, 100, date.today())

    def test_zero_nav_raises(self):
        with pytest.raises(ValueError, match="NAV must be positive"):
            MFTransaction("T001", "119551", MFTransactionType.PURCHASE, 1000, 10, 0, date.today())

    def test_invalid_status_raises(self):
        with pytest.raises(ValueError, match="Invalid status"):
            MFTransaction("T001", "119551", MFTransactionType.PURCHASE,
                         1000, 10, 100.0, date.today(), status="UNKNOWN")
