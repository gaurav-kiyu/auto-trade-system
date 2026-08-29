"""Multi-Leg Option Strategy Builder & Payoff Calculator.

Provides institutional-grade option strategy construction, payoff curve calculation,
max profit/loss estimation, break-even points identification, and portfolio Greeks aggregation.

SUPERSEDED (2026-08-21): `build_straddle()`/`build_iron_condor()` here are
exact-duplicate implementations of the real, live, opt-in strategy engines
`core/straddle_strategy.py` and `core/iron_condor_strategy.py` respectively
(see `docs/duplicate_code_register.md` DUP-182/DUP-116) -- those two files
are the ones actually wired per CLAUDE.md's module table. This module's
generic `add_leg()`/`calculate_payoff_profile()` primitives are not used by
either real strategy file today. Kept only for backward compatibility with
its existing direct tests (`tests/test_competitor_features.py`,
`tests/test_strategy_catalog.py`) -- do not wire this in as a new live
strategy path, it would just add duplicate/dead functionality.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class OptionLeg:
    strike: float
    option_type: str  # 'CE' or 'PE'
    action: str  # 'BUY' or 'SELL'
    quantity: int
    premium: float
    iv: float = 0.20
    t_days: float = 30.0

    def payoff_at_expiry(self, spot_price: float) -> float:
        """Calculate profit/loss for this leg at expiry for a given spot price."""
        if self.option_type.upper() == "CE":
            intrinsic = max(0.0, spot_price - self.strike)
        else:
            intrinsic = max(0.0, self.strike - spot_price)

        if self.action.upper() == "BUY":
            pnl_per_unit = intrinsic - self.premium
        else:
            pnl_per_unit = self.premium - intrinsic

        return pnl_per_unit * self.quantity


@dataclass
class StrategyPayoffProfile:
    strategy_name: str
    legs: list[OptionLeg]
    max_profit: float
    max_loss: float
    break_evens: list[float]
    net_premium: float  # Debit (+) or Credit (-)
    payoff_curve: list[tuple[float, float]]  # List of (spot_price, pnl)


class OptionStrategyBuilder:
    """Builder and analyzer for multi-leg option strategies."""

    def __init__(self, spot_price: float) -> None:
        self.spot_price = spot_price
        self.legs: list[OptionLeg] = []

    def add_leg(
        self,
        strike: float,
        option_type: str,
        action: str,
        quantity: int,
        premium: float,
        iv: float = 0.20,
        t_days: float = 30.0,
    ) -> OptionStrategyBuilder:
        """Add an option leg to the strategy."""
        leg = OptionLeg(
            strike=strike,
            option_type=option_type,
            action=action,
            quantity=quantity,
            premium=premium,
            iv=iv,
            t_days=t_days,
        )
        self.legs.append(leg)
        return self

    def build_straddle(
        self, strike: float, call_premium: float, put_premium: float, quantity: int = 1
    ) -> OptionStrategyBuilder:
        """Construct a Long Straddle strategy."""
        self.legs.clear()
        self.add_leg(strike, "CE", "BUY", quantity, call_premium)
        self.add_leg(strike, "PE", "BUY", quantity, put_premium)
        return self

    def build_iron_condor(
        self,
        sell_put_strike: float,
        buy_put_strike: float,
        sell_call_strike: float,
        buy_call_strike: float,
        put_sell_prem: float,
        put_buy_prem: float,
        call_sell_prem: float,
        call_buy_prem: float,
        quantity: int = 1,
    ) -> OptionStrategyBuilder:
        """Construct an Iron Condor strategy."""
        self.legs.clear()
        self.add_leg(buy_put_strike, "PE", "BUY", quantity, put_buy_prem)
        self.add_leg(sell_put_strike, "PE", "SELL", quantity, put_sell_prem)
        self.add_leg(sell_call_strike, "CE", "SELL", quantity, call_sell_prem)
        self.add_leg(buy_call_strike, "CE", "BUY", quantity, call_buy_prem)
        return self

    def calculate_payoff_profile(
        self, price_range_pct: float = 0.20, points: int = 100
    ) -> StrategyPayoffProfile:
        """Calculate payoff curve, max profit/loss, and break-even points."""
        if not self.legs:
            return StrategyPayoffProfile("Empty", [], 0.0, 0.0, [], 0.0, [])

        low_spot = self.spot_price * (1.0 - price_range_pct)
        high_spot = self.spot_price * (1.0 + price_range_pct)
        step = (high_spot - low_spot) / float(points)

        payoff_curve: list[tuple[float, float]] = []
        break_evens: list[float] = []
        prev_pnl: float | None = None
        prev_spot: float | None = None

        net_premium = sum(
            (leg.premium if leg.action.upper() == "BUY" else -leg.premium) * leg.quantity
            for leg in self.legs
        )

        for i in range(points + 1):
            spot = low_spot + i * step
            total_pnl = sum(leg.payoff_at_expiry(spot) for leg in self.legs)
            payoff_curve.append((round(spot, 2), round(total_pnl, 2)))

            # Detect break-even zero crossing
            if prev_pnl is not None and prev_spot is not None:
                if (prev_pnl < 0 <= total_pnl) or (prev_pnl >= 0 > total_pnl):
                    # Linear interpolation for zero crossing
                    be_spot = prev_spot + (0.0 - prev_pnl) * (spot - prev_spot) / (
                        total_pnl - prev_pnl
                    )
                    break_evens.append(round(be_spot, 2))

            prev_pnl = total_pnl
            prev_spot = spot

        pnls = [pnl for _, pnl in payoff_curve]
        max_profit = max(pnls)
        max_loss = min(pnls)

        return StrategyPayoffProfile(
            strategy_name="Custom Strategy",
            legs=list(self.legs),
            max_profit=round(max_profit, 2),
            max_loss=round(max_loss, 2),
            break_evens=break_evens,
            net_premium=round(net_premium, 2),
            payoff_curve=payoff_curve,
        )
