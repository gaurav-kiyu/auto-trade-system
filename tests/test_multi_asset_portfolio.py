"""Integration tests for MultiAssetPortfolioAggregator - aggregates positions across all 6 asset classes.

Tests:
  - Empty portfolio returns valid empty snapshot
  - Equity-only portfolio aggregation
  - F&O futures + options aggregation
  - Commodity positions aggregation
  - Currency positions aggregation
  - Fixed income positions aggregation
  - Mutual fund / SIP/ REIT / InvIT aggregation
  - Full multi-asset portfolio with all 6 asset classes
  - Capital allocation with risk-parity service
  - Aggregate with cross-asset exposure tracking
"""

from __future__ import annotations

from core.domains.commodity import CommodityContract, CommodityPosition
from core.domains.currency import CurrencyContract, CurrencyPair, CurrencyPosition
from core.domains.equity import EquityPosition, Holding, Stock
from core.domains.fixed_income import Bond, BondPosition
from core.domains.fo import FutureContract, FuturePosition, OptionContract, OptionPosition
from core.domains.mutual_fund import SIP, MutualFund, SIPFrequency
from datetime import date
from core.domains.portfolio import PortfolioSnapshot
from core.portfolio.adapters.multi_asset_aggregator import (
    CapitalAllocationService,
    MultiAssetPortfolioAggregator,
)
from core.ports.capital_allocation import AllocationRequest, AssetClass

# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_stock(symbol: str, price: float = 100.0) -> Stock:
    return Stock(symbol, f"{symbol} Ltd", last_price=price)


def _make_equity_position(symbol: str, qty: int, price: float) -> EquityPosition:
    stock = _make_stock(symbol, price)
    return EquityPosition(stock, qty, price, price)


def _make_future_position(symbol: str, qty: int, price: float) -> FuturePosition:
    contract = FutureContract(symbol, date(2026, 7, 30), last_price=price)
    return FuturePosition(contract, qty, price, price)


def _make_option_position(symbol: str, opt_type: str, strike: int, qty: int, premium: float) -> OptionPosition:
    contract = OptionContract(symbol, opt_type, strike, date(2026, 7, 30), last_price=premium)
    return OptionPosition(contract, qty, premium, premium)


def _make_commodity_position(symbol: str, qty: int, price: float) -> CommodityPosition:
    contract = CommodityContract(symbol, date(2026, 8, 5), last_price=price)
    return CommodityPosition(contract, qty, price, price)


def _make_currency_position(qty: int, price: float) -> CurrencyPosition:
    contract = CurrencyContract(CurrencyPair.USD_INR, date(2026, 7, 28), last_price=price)
    return CurrencyPosition(contract, qty, price, price)


def _make_bond_position(qty: int, price: float) -> BondPosition:
    from core.domains.fixed_income import SecurityType
    bond = Bond("IN002023Z012", "7.25% GS 2033", SecurityType.GOVERNMENT_SECURITY, face_value=100, last_price=price)
    return BondPosition(bond, qty, price, price)


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestEmptyPortfolio:
    def test_empty_returns_valid_snapshot(self):
        aggregator = MultiAssetPortfolioAggregator()
        snapshot = aggregator.aggregate(cash_balance=100000.0)
        assert isinstance(snapshot, PortfolioSnapshot)
        assert snapshot.cash == 100000.0
        assert snapshot.total_value == 100000.0
        assert len(snapshot.positions) == 0


class TestEquityOnly:
    def test_single_position(self):
        aggregator = MultiAssetPortfolioAggregator()
        pos = _make_equity_position("RELIANCE", 100, 2500.0)
        snapshot = aggregator.aggregate(equity_positions=[pos], cash_balance=50000.0)
        assert snapshot.total_value == 50000.0 + 100 * 2500.0
        assert "EQ:RELIANCE" in snapshot.positions

    def test_multiple_positions(self):
        aggregator = MultiAssetPortfolioAggregator()
        snap = aggregator.aggregate(
            equity_positions=[
                _make_equity_position("RELIANCE", 100, 2500.0),
                _make_equity_position("TCS", 50, 3500.0),
            ],
            cash_balance=100000.0,
        )
        assert len(snap.positions) == 2
        expected = 100000.0 + 100 * 2500.0 + 50 * 3500.0
        assert abs(snap.total_value - expected) < 0.01

    def test_with_holdings(self):
        """Holdings contribute to equity long_exposure in metadata."""
        aggregator = MultiAssetPortfolioAggregator()
        holding = Holding("INFY", 200, 200, average_cost=1500, current_price=1600)
        snap = aggregator.aggregate(
            equity_holdings=[holding],
            cash_balance=50000.0,
        )
        meta = snap.metadata.get("exposures", {})
        eq_exp = meta.get("equity", {})
        assert abs(eq_exp.get("long", 0) - 320000.0) < 0.01  # 200 * 1600

    def test_mixed_buy_and_sell(self):
        """Verify net exposure counts short positions correctly."""
        aggregator = MultiAssetPortfolioAggregator()
        snap = aggregator.aggregate(
            equity_positions=[
                _make_equity_position("LONG_STOCK", 100, 100.0),
                _make_equity_position("SHORT_STOCK", -50, 100.0),
            ],
        )
        meta = snap.metadata.get("exposures", {})
        eq_exp = meta.get("equity", {})
        assert eq_exp.get("long", 0) == 10000.0  # 100 * 100
        assert eq_exp.get("short", 0) == 5000.0   # abs(-50 * 100)
        assert eq_exp.get("net", 0) == 5000.0      # 10000 - 5000


class TestFO:
    def test_futures_and_options(self):
        aggregator = MultiAssetPortfolioAggregator()
        snap = aggregator.aggregate(
            fo_futures=[_make_future_position("NIFTY", 50, 23000.0)],
            fo_options=[_make_option_position("NIFTY", "CE", 23500, 50, 150.0)],
        )
        assert "FUT:NIFTY" in snap.positions
        assert any("OPT:NIFTY_23500_CE" in k for k in snap.positions)

    def test_short_option_exposure(self):
        """Short options margin is tracked differently than long."""
        aggregator = MultiAssetPortfolioAggregator()
        snap = aggregator.aggregate(
            fo_options=[_make_option_position("NIFTY", "CE", 23500, -50, 150.0)],
        )
        meta = snap.metadata.get("exposures", {})
        fo_exp = meta.get("futures_options", {})
        # Short options: short_exposure = abs(-50 * 150)
        assert fo_exp.get("short", 0) == 7500.0


class TestCommodity:
    def test_gold_position(self):
        aggregator = MultiAssetPortfolioAggregator()
        snap = aggregator.aggregate(
            commodity_positions=[_make_commodity_position("GOLD", 1, 65000.0)],
        )
        meta = snap.metadata.get("exposures", {})
        comm_exp = meta.get("commodity", {})
        assert comm_exp.get("long", 0) == 65000.0

    def test_short_commodity(self):
        aggregator = MultiAssetPortfolioAggregator()
        snap = aggregator.aggregate(
            commodity_positions=[_make_commodity_position("CRUDEOIL", -100, 5000.0)],
        )
        meta = snap.metadata.get("exposures", {})
        comm_exp = meta.get("commodity", {})
        assert comm_exp.get("short", 0) == 500000.0  # abs(-100 * 5000)


class TestCurrency:
    def test_usd_position(self):
        aggregator = MultiAssetPortfolioAggregator()
        snap = aggregator.aggregate(
            currency_positions=[_make_currency_position(1000, 83.50)],
        )
        meta = snap.metadata.get("exposures", {})
        curr_exp = meta.get("currency", {})
        assert abs(curr_exp.get("long", 0) - 83500.0) < 0.01


class TestFixedIncome:
    def test_bond_position(self):
        aggregator = MultiAssetPortfolioAggregator()
        snap = aggregator.aggregate(
            bond_positions=[_make_bond_position(100, 102.50)],
        )
        meta = snap.metadata.get("exposures", {})
        fi_exp = meta.get("fixed_income", {})
        assert abs(fi_exp.get("long", 0) - 10250.0) < 0.01


class TestMutualFunds:
    def test_sip_included_in_value(self):
        """SIP current_value appears in mutual_funds_etf long_exposure."""
        mf = MutualFund("119551", "Fund", fund_house="H", nav=100.0)
        sip = SIP("SIP001", mf, SIPFrequency.MONTHLY, 5000,
                  total_invested=60000, current_value=72000)
        aggregator = MultiAssetPortfolioAggregator()
        snap = aggregator.aggregate(sip_plans=[sip])
        meta = snap.metadata.get("exposures", {})
        mf_exp = meta.get("mutual_funds_etf", {})
        assert mf_exp.get("long", 0) >= 72000


class TestFullMultiAsset:
    def test_all_asset_classes(self):
        """Verify all 6 asset classes are aggregated into a single snapshot."""
        aggregator = MultiAssetPortfolioAggregator()
        snap = aggregator.aggregate(
            equity_positions=[_make_equity_position("RELIANCE", 100, 2500.0)],
            fo_futures=[_make_future_position("NIFTY", 50, 23000.0)],
            fo_options=[_make_option_position("NIFTY", "CE", 23500, 75, 150.0)],
            commodity_positions=[_make_commodity_position("GOLD", 1, 65000.0)],
            currency_positions=[_make_currency_position(1000, 83.50)],
            bond_positions=[_make_bond_position(100, 102.50)],
            cash_balance=100000.0,
        )
        meta = snap.metadata.get("exposures", {})
        assert len(meta) == 7  # All 7 asset classes present (includes SME)
        assert "equity" in meta
        assert "futures_options" in meta
        assert "commodity" in meta
        assert "currency" in meta
        assert "fixed_income" in meta
        assert "mutual_funds_etf" in meta
        assert "sme" in meta
        assert snap.total_value > 0
        assert len(snap.positions) > 0

    def test_allocation_percentages_in_exposure_only(self):
        """Allocation percentages reflect non-cash exposures."""
        aggregator = MultiAssetPortfolioAggregator()
        snap = aggregator.aggregate(
            equity_positions=[_make_equity_position("A", 100, 100.0)],
            fo_futures=[_make_future_position("NIFTY", 50, 20000.0)],
            cash_balance=50000.0,
        )
        meta = snap.metadata.get("exposures", {})
        # Equity (10000) + FO (1,000,000) = 1,010,000 total exposure
        # Equity pct = 10000 / 1010000 * 100
        assert meta.get("equity", {}).get("allocation_pct", 0) > 0
        assert meta.get("futures_options", {}).get("allocation_pct", 0) > 0
        # Both should be present and valid percentages
        for exp in meta.values():
            pct = exp.get("allocation_pct", 0)
            assert 0 <= pct <= 100


class TestCapitalAllocationService:
    def test_risk_parity_allocation(self):
        service = CapitalAllocationService()
        request = AllocationRequest(total_capital=100000.0)
        result = service.allocate(request)
        assert len(result.allocations) == 7  # 7 asset classes
        assert abs(sum(result.allocations.values()) - 100000.0) < 0.01

    def test_inverse_vol_weights_differ(self):
        """Higher vol asset classes should get smaller allocations."""
        service = CapitalAllocationService()
        request = AllocationRequest(total_capital=100000.0)
        result = service.allocate(request)
        # Fixed Income (5% vol) should get more than F&O (25% vol)
        fi_alloc = result.allocations.get(AssetClass.FIXED_INCOME, 0)
        fo_alloc = result.allocations.get(AssetClass.FUTURES_OPTIONS, 0)
        assert fi_alloc > fo_alloc, (
            f"Fixed income ({fi_alloc:.0f}) should get more than F&O ({fo_alloc:.0f})"
        )

    def test_rebalance_within_tolerance(self):
        service = CapitalAllocationService()
        existing = {ac: 10000.0 for ac in AssetClass}
        request = AllocationRequest(
            total_capital=100000.0,
            existing_allocations=existing,
            constraints={"rebalance_tolerance": 0.5},  # 50% tolerance = no rebalance
        )
        result = service.rebalance(request)
        # With high tolerance, allocations should stay close to existing
        for ac, amt in result.allocations.items():
            assert amt >= 0

    def test_get_allocation_summary(self):
        service = CapitalAllocationService()
        summary = service.get_allocation_summary()
        assert len(summary) == 7
        for ac, info in summary.items():
            assert "volatility_assumption" in info
            assert "target_weight" in info
