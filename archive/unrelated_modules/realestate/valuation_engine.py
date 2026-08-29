"""Real Estate Property Valuation & Financial Yield Engine.

Calculates property valuation, Net Operating Income (NOI), Cap Rate,
Gross Rent Multiplier (GRM), and Discounted Cash Flow (DCF) yield metrics.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PropertyValuationResult:
    property_name: str
    purchase_price: float
    gross_annual_rent: float
    operating_expenses: float
    net_operating_income: float
    cap_rate_pct: float
    grm: float
    dcf_valuation: float
    recommendation: str


class PropertyValuationEngine:
    """Valuation and yield analysis engine for real estate assets."""

    def __init__(self, discount_rate: float = 0.08, terminal_growth: float = 0.02) -> None:
        self.discount_rate = discount_rate
        self.terminal_growth = terminal_growth

    def calculate_valuation(
        self,
        property_name: str,
        purchase_price: float,
        gross_annual_rent: float,
        operating_expenses: float,
        hold_years: int = 5,
    ) -> PropertyValuationResult:
        """Calculate valuation metrics and DCF yield for a real estate property."""
        noi = gross_annual_rent - operating_expenses
        cap_rate = (noi / purchase_price * 100.0) if purchase_price > 0 else 0.0
        grm = (purchase_price / gross_annual_rent) if gross_annual_rent > 0 else 0.0

        # DCF Calculation over hold period
        pv_cash_flows = 0.0
        current_noi = noi
        for year in range(1, hold_years + 1):
            current_noi *= (1.0 + self.terminal_growth)
            pv_cash_flows += current_noi / ((1.0 + self.discount_rate) ** year)

        # Terminal Value
        terminal_value = (current_noi * (1.0 + self.terminal_growth)) / (self.discount_rate - self.terminal_growth)
        pv_terminal = terminal_value / ((1.0 + self.discount_rate) ** hold_years)
        dcf_val = pv_cash_flows + pv_terminal

        rec = "STRONG_BUY" if cap_rate >= 8.0 and dcf_val > purchase_price else ("BUY" if cap_rate >= 6.0 else "HOLD")

        return PropertyValuationResult(
            property_name=property_name,
            purchase_price=round(purchase_price, 2),
            gross_annual_rent=round(gross_annual_rent, 2),
            operating_expenses=round(operating_expenses, 2),
            net_operating_income=round(noi, 2),
            cap_rate_pct=round(cap_rate, 2),
            grm=round(grm, 2),
            dcf_valuation=round(dcf_val, 2),
            recommendation=rec,
        )
