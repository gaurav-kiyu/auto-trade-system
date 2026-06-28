"""Multi-Asset Portfolio Aggregator - Unified portfolio view across asset classes.

Aggregates positions and exposures from:
  - Equity (cash market stocks + holdings)
  - Futures & Options (NFO/BFO index & stock derivatives)
  - Commodity (MCX bullion, energy, metals)
  - Currency (CDS futures & options)
  - Fixed Income (G-Sec, bonds, T-Bills)
  - Mutual Funds / ETFs / REITs / InvITs

Provides:
  - Unified portfolio snapshot with total exposure
  - Per-asset-class P&L breakdown
  - Cross-asset correlation analysis
  - Capital allocation and rebalancing
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from core.domains.commodity import CommodityPosition
from core.domains.currency import CurrencyPosition
from core.domains.equity import EquityPosition, Holding
from core.domains.sme import SmePosition
from core.domains.fixed_income import BondPosition
from core.domains.fo import FuturePosition, OptionPosition
from core.domains.mutual_fund import FundHolding, InvIT, REIT, SIP
from core.domains.portfolio import (
    PortfolioSnapshot,
    PositionSnapshot,
)
from core.ports.capital_allocation import (
    AllocationRequest,
    AllocationResult,
    AssetClass,
    CapitalAllocationPort,
)


@dataclass
class AssetClassExposure:
    """Exposure breakdown for a single asset class.

    Attributes:
        asset_class: Name of the asset class
        long_exposure: Total long exposure (INR)
        short_exposure: Total short exposure (INR)
        net_exposure: Net exposure (long - short)
        gross_exposure: Gross exposure (long + short)
        margin_used: Margin/blocked capital (INR)
        pnl: Unrealized + realized P&L (INR)
        position_count: Number of open positions
    """
    asset_class: str
    long_exposure: float = 0.0
    short_exposure: float = 0.0
    net_exposure: float = 0.0
    gross_exposure: float = 0.0
    margin_used: float = 0.0
    pnl: float = 0.0
    position_count: int = 0
    allocation_pct: float = 0.0


class MultiAssetPortfolioAggregator:
    """Aggregates positions across all asset classes into a unified portfolio view.

    Usage:
        aggregator = MultiAssetPortfolioAggregator()
        snapshot = aggregator.aggregate(
            equity_positions=[...],
            fo_positions=[...],
            commodity_positions=[...],
            currency_positions=[...],
            bond_positions=[...],
            cash_balance=100000.0,
        )
    """

    def __init__(self, capital_allocation: CapitalAllocationPort | None = None):
        self._capital_allocation = capital_allocation

    def aggregate(
        self,
        *,
        equity_positions: list[EquityPosition] | None = None,
        equity_holdings: list[Holding] | None = None,
        fo_futures: list[FuturePosition] | None = None,
        fo_options: list[OptionPosition] | None = None,
        commodity_positions: list[CommodityPosition] | None = None,
        currency_positions: list[CurrencyPosition] | None = None,
        bond_positions: list[BondPosition] | None = None,
        fund_holdings: list[FundHolding] | None = None,
        sip_plans: list[SIP] | None = None,
        reit_holdings: list[REIT] | None = None,
        invit_holdings: list[InvIT] | None = None,
        sme_positions: list[SmePosition] | None = None,
        cash_balance: float = 0.0,
        daily_pnl: float = 0.0,
        total_pnl: float = 0.0,
    ) -> PortfolioSnapshot:
        """Aggregate all positions into a single portfolio snapshot.

        Args:
            equity_positions: Active equity trading positions
            equity_holdings: Demat holdings
            fo_futures: Open futures positions
            fo_options: Open options positions
            commodity_positions: Open commodity positions
            currency_positions: Open currency positions
            bond_positions: Fixed income positions
            fund_holdings: Mutual fund portfolio holdings
            sip_plans: Active SIP investments
            reit_holdings: REIT holdings
            invit_holdings: InvIT holdings
            sme_positions: SME equity positions (NSE EMERGE / BSE SME)
            cash_balance: Available cash balance
            daily_pnl: Day's P&L
            total_pnl: Total P&L

        Returns:
            PortfolioSnapshot with aggregated positions and exposures
        """
        exposures: list[AssetClassExposure] = []
        all_position_snapshots: dict[str, PositionSnapshot] = {}

        # Equity positions
        eq_exposure = self._aggregate_equity(equity_positions or [], equity_holdings or [])
        exposures.append(eq_exposure)
        for pos in equity_positions or []:
            snap = PositionSnapshot(
                symbol=pos.stock.symbol,
                quantity=pos.quantity,
                average_price=pos.average_price,
                current_price=pos.current_price,
                realized_pnl=pos.realized_pnl,
            )
            all_position_snapshots[f"EQ:{pos.stock.symbol}"] = snap

        # F&O futures
        fo_exposure = self._aggregate_fo(fo_futures or [], fo_options or [])
        exposures.append(fo_exposure)
        for pos in fo_futures or []:
            snap = PositionSnapshot(
                symbol=f"FUT:{pos.contract.symbol}",
                quantity=pos.quantity,
                average_price=pos.average_price,
                current_price=pos.current_price,
                realized_pnl=pos.realized_pnl,
            )
            all_position_snapshots[f"FUT:{pos.contract.symbol}"] = snap
        for pos in fo_options or []:
            sym = f"OPT:{pos.contract.symbol}_{pos.contract.strike}_{pos.contract.option_type}"
            snap = PositionSnapshot(
                symbol=sym,
                quantity=pos.quantity,
                average_price=pos.average_price,
                current_price=pos.current_price,
                realized_pnl=pos.realized_pnl,
            )
            all_position_snapshots[sym] = snap

        # Commodity
        comm_exposure = self._aggregate_commodity(commodity_positions or [])
        exposures.append(comm_exposure)

        # Currency
        curr_exposure = self._aggregate_currency(currency_positions or [])
        exposures.append(curr_exposure)

        # Fixed Income
        fi_exposure = self._aggregate_fixed_income(bond_positions or [])
        exposures.append(fi_exposure)

        # Mutual Funds / SIPs
        mf_exposure = self._aggregate_mutual_funds(fund_holdings or [], sip_plans or [],
                                                    reit_holdings or [], invit_holdings or [])
        exposures.append(mf_exposure)

        # SME stocks
        sme_exposure = self._aggregate_sme(sme_positions or [])
        exposures.append(sme_exposure)

        # Calculate totals
        total_long = sum(e.long_exposure for e in exposures)
        total_short = sum(e.short_exposure for e in exposures)
        total_margin = sum(e.margin_used for e in exposures)
        total_pnl_val = sum(e.pnl for e in exposures) + total_pnl
        total_positions = sum(e.position_count for e in exposures)

        # Compute allocation percentages
        total_exposure = total_long + total_short + cash_balance
        if total_exposure > 0:
            for e in exposures:
                e.allocation_pct = (e.long_exposure + e.short_exposure) / total_exposure * 100.0

        return PortfolioSnapshot(
            timestamp=datetime.now(),
            total_value=cash_balance + total_long,
            cash=cash_balance,
            positions=all_position_snapshots,
            daily_pnl=daily_pnl,
            total_pnl=total_pnl_val,
            metadata={
                "exposures": {e.asset_class: {
                    "long": e.long_exposure,
                    "short": e.short_exposure,
                    "net": e.net_exposure,
                    "gross": e.gross_exposure,
                    "margin": e.margin_used,
                    "pnl": e.pnl,
                    "positions": e.position_count,
                    "allocation_pct": e.allocation_pct,
                } for e in exposures},
                "total_positions": total_positions,
                "total_margin": total_margin,
            },
        )

    def _aggregate_equity(
        self,
        positions: list[EquityPosition],
        holdings: list[Holding],
    ) -> AssetClassExposure:
        """Aggregate equity cash market positions and holdings."""
        exposure = AssetClassExposure(asset_class="equity")
        for pos in positions:
            val = pos.quantity * pos.current_price
            if pos.quantity > 0:
                exposure.long_exposure += val
            else:
                exposure.short_exposure += abs(val)
            exposure.pnl += pos.unrealized_pnl + pos.realized_pnl
            exposure.position_count += 1
        for h in holdings:
            exposure.long_exposure += h.market_value
            exposure.pnl += h.pnl
            exposure.position_count += 1
        exposure.net_exposure = exposure.long_exposure - exposure.short_exposure
        exposure.gross_exposure = exposure.long_exposure + exposure.short_exposure
        return exposure

    def _aggregate_fo(
        self,
        futures: list[FuturePosition],
        options: list[OptionPosition],
    ) -> AssetClassExposure:
        """Aggregate F&O futures and options positions."""
        exposure = AssetClassExposure(asset_class="futures_options")
        for pos in futures:
            val = pos.quantity * pos.current_price
            if pos.quantity > 0:
                exposure.long_exposure += val
            else:
                exposure.short_exposure += abs(val)
            exposure.margin_used += pos.margin_used
            exposure.pnl += pos.unrealized_pnl + pos.realized_pnl
            exposure.position_count += 1
        for pos in options:
            premium_val = pos.quantity * pos.current_price
            if pos.quantity > 0:
                exposure.long_exposure += premium_val
            else:
                exposure.short_exposure += abs(premium_val)
            exposure.margin_used += abs(premium_val) if pos.quantity < 0 else 0
            exposure.pnl += pos.unrealized_pnl + pos.realized_pnl
            exposure.position_count += 1
        exposure.net_exposure = exposure.long_exposure - exposure.short_exposure
        exposure.gross_exposure = exposure.long_exposure + exposure.short_exposure
        return exposure

    def _aggregate_commodity(self, positions: list[CommodityPosition]) -> AssetClassExposure:
        """Aggregate commodity positions."""
        exposure = AssetClassExposure(asset_class="commodity")
        for pos in positions:
            val = abs(pos.quantity * pos.current_price)
            if pos.quantity > 0:
                exposure.long_exposure += val
            else:
                exposure.short_exposure += val
            exposure.margin_used += pos.margin_used
            exposure.pnl += pos.unrealized_pnl + pos.realized_pnl
            exposure.position_count += 1
        exposure.net_exposure = exposure.long_exposure - exposure.short_exposure
        exposure.gross_exposure = exposure.long_exposure + exposure.short_exposure
        return exposure

    def _aggregate_currency(self, positions: list[CurrencyPosition]) -> AssetClassExposure:
        """Aggregate currency derivative positions."""
        exposure = AssetClassExposure(asset_class="currency")
        for pos in positions:
            val = abs(pos.quantity * pos.current_price)
            if pos.quantity > 0:
                exposure.long_exposure += val
            else:
                exposure.short_exposure += val
            exposure.margin_used += pos.margin_used
            exposure.pnl += pos.unrealized_pnl + pos.realized_pnl
            exposure.position_count += 1
        exposure.net_exposure = exposure.long_exposure - exposure.short_exposure
        exposure.gross_exposure = exposure.long_exposure + exposure.short_exposure
        return exposure

    def _aggregate_fixed_income(self, positions: list[BondPosition]) -> AssetClassExposure:
        """Aggregate fixed income positions."""
        exposure = AssetClassExposure(asset_class="fixed_income")
        for pos in positions:
            exposure.long_exposure += pos.market_value
            exposure.pnl += pos.unrealized_pnl + pos.realized_pnl + pos.interest_income
            exposure.position_count += 1
        exposure.net_exposure = exposure.long_exposure
        exposure.gross_exposure = exposure.long_exposure
        return exposure

    def _aggregate_sme(self, positions: list[SmePosition]) -> AssetClassExposure:
        """Aggregate SME equity positions."""
        exposure = AssetClassExposure(asset_class="sme")
        for pos in positions:
            val = abs(pos.quantity * pos.current_price)
            if pos.quantity > 0:
                exposure.long_exposure += val
            else:
                exposure.short_exposure += val
            exposure.pnl += pos.unrealized_pnl + pos.realized_pnl
            exposure.position_count += 1
        exposure.net_exposure = exposure.long_exposure - exposure.short_exposure
        exposure.gross_exposure = exposure.long_exposure + exposure.short_exposure
        return exposure

    def _aggregate_mutual_funds(
        self,
        fund_holdings: list[FundHolding],
        sip_plans: list[SIP],
        reit_holdings: list[REIT],
        invit_holdings: list[InvIT],
    ) -> AssetClassExposure:
        """Aggregate mutual fund, ETF, REIT, and InvIT holdings."""
        exposure = AssetClassExposure(asset_class="mutual_funds_etf")
        for h in fund_holdings:
            exposure.long_exposure += h.market_value
            exposure.position_count += 1
        for sip in sip_plans:
            exposure.long_exposure += sip.current_value
            exposure.pnl += sip.current_value - sip.total_invested
            exposure.position_count += 1
        for reit in reit_holdings:
            exposure.long_exposure += reit.market_price * (reit.units_outstanding or 0)
            exposure.position_count += 1
        for inv in invit_holdings:
            exposure.long_exposure += inv.market_price * (inv.units_outstanding or 0)
            exposure.position_count += 1
        exposure.net_exposure = exposure.long_exposure
        exposure.gross_exposure = exposure.long_exposure
        return exposure

    def get_capital_allocation(self, total_capital: float) -> dict[str, float]:
        """Get recommended capital allocation across asset classes.

        Uses the configured CapitalAllocationPort if available, otherwise
        provides a simple default allocation.

        Args:
            total_capital: Total capital to allocate

        Returns:
            Dict mapping asset class name -> allocated capital
        """
        if self._capital_allocation:
            request = AllocationRequest(total_capital=total_capital)
            result = self._capital_allocation.allocate(request)
            return {k.value: v for k, v in result.allocations.items()}

        # Default allocation (equal-weight fallback)
        n_classes = 5  # equity, fo, commodity, currency, fixed_income
        per_class = total_capital / n_classes
        return {
            "equity": per_class,
            "futures_options": per_class,
            "commodity": per_class,
            "currency": per_class,
            "fixed_income": per_class,
        }


class CapitalAllocationService(CapitalAllocationPort):
    """Default implementation of CapitalAllocationPort.

    Uses a simple risk-parity approach: allocates inversely proportional
    to estimated asset class volatility.
    """

    # Default volatility assumptions per asset class (annualized)
    DEFAULT_VOLATILITY: dict[AssetClass, float] = {
        AssetClass.EQUITY: 0.20,
        AssetClass.FUTURES_OPTIONS: 0.25,
        AssetClass.COMMODITY: 0.18,
        AssetClass.CURRENCY: 0.08,
        AssetClass.FIXED_INCOME: 0.05,
        AssetClass.MUTUAL_FUNDS: 0.15,
        AssetClass.CASH: 0.01,
    }

    def __init__(self, volatility_assumptions: dict[AssetClass, float] | None = None):
        self._volatilities = volatility_assumptions or dict(self.DEFAULT_VOLATILITY)

    def allocate(self, request: AllocationRequest) -> AllocationResult:
        """Allocate capital using inverse-volatility (risk-parity) weighting."""
        target_classes = list(self._volatilities.keys())
        if request.constraints.get("asset_classes"):
            target_classes = [
                ac for ac in target_classes
                if ac in request.constraints["asset_classes"]
            ]

        # Inverse-volatility weights
        inv_vol = {ac: 1.0 / max(v, 0.01) for ac, v in self._volatilities.items() if ac in target_classes}
        total_inv_vol = sum(inv_vol.values())
        weights = {ac: v / total_inv_vol for ac, v in inv_vol.items()}

        # Apply capital
        allocations: dict[AssetClass, float] = {}
        allocated = 0.0
        for ac, weight in weights.items():
            amt = round(request.total_capital * weight, 2)
            # Apply min/max constraints
            min_amt = request.constraints.get("min_per_class", 0)
            max_amt = request.constraints.get("max_per_class", request.total_capital)
            amt = max(min_amt, min(max_amt, amt))
            allocations[ac] = amt
            allocated += amt

        remaining = max(0.0, request.total_capital - allocated)

        return AllocationResult(
            allocations=allocations,
            remaining_cash=remaining,
            strategy_used="risk_parity_inverse_vol",
            explanation=f"Risk-parity allocation across {len(allocations)} asset classes using inverse volatility weights",
            risk_metrics={
                "n_asset_classes": len(allocations),
                "avg_weight": 1.0 / len(allocations) if allocations else 0,
            },
        )

    def rebalance(self, request: AllocationRequest) -> AllocationResult:
        """Rebalance towards target risk-parity weights.

        Simpler rebalance: adjust to target weights within tolerance bands.
        """
        target = self.allocate(request)
        current = request.existing_allocations

        rebalanced: dict[AssetClass, float] = {}
        for ac, target_amt in target.allocations.items():
            current_amt = current.get(ac, 0.0)
            tolerance = request.constraints.get("rebalance_tolerance", 0.05)
            diff_pct = abs(current_amt - target_amt) / max(target_amt, 1)

            if diff_pct > tolerance:
                rebalanced[ac] = target_amt  # Rebalance to target
            else:
                rebalanced[ac] = current_amt  # Keep current

        return AllocationResult(
            allocations=rebalanced,
            remaining_cash=target.remaining_cash,
            strategy_used="rebalance_to_risk_parity",
            explanation=f"Rebalanced {len(rebalanced)} asset classes within tolerance bands",
        )

    def get_allocation_summary(self) -> dict[AssetClass, dict[str, Any]]:
        """Get current allocation policy summary."""
        return {
            ac: {
                "volatility_assumption": self._volatilities.get(ac, 0.0),
                "target_weight": 1.0 / max(len(self._volatilities), 1),
            }
            for ac in self._volatilities
        }


__all__ = [
    "AssetClassExposure",
    "CapitalAllocationService",
    "MultiAssetPortfolioAggregator",
]
