"""Mutual Fund & ETF Domain Models - Indian MF, ETF, REIT, InvIT market.

Models the complete Indian mutual fund, ETF, REIT, and InvIT ecosystem:
  - Open-ended & close-ended mutual fund schemes
  - Equity, Debt, Hybrid, Liquid, Index fund categories
  - Direct & Regular plans, Growth & Dividend options
  - ETFs (index, gold, international)
  - REITs (Real Estate Investment Trusts)
  - InvITs (Infrastructure Investment Trusts)
  - NAV tracking, SIP/STP modeling
  - Portfolio holdings and sector allocation

Usage:
    from core.domains.mutual_fund import (
        MutualFund, ETF, FundCategory,
        NavRecord, REIT, InvIT, FundHolding
    )
"""
from core.domains.mutual_fund.models import (
    ETF,
    REIT,
    SIP,
    DividendType,
    ExpenseRatioType,
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

__all__ = [
    "DividendType",
    "ETF",
    "ExpenseRatioType",
    "FundCategory",
    "FundHolding",
    "FundOption",
    "FundPlan",
    "FundType",
    "InvIT",
    "MFTransaction",
    "MFTransactionType",
    "MutualFund",
    "NavRecord",
    "PortfolioAllocation",
    "REIT",
    "SIP",
    "SIPFrequency",
]
