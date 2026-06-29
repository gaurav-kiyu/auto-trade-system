"""
Domain Models Package - All asset class and business domain models.

Each sub-package models a specific domain:
  - execution      : Orders, fills, positions, execution context
  - ml             : ML predictions, features, model metrics
  - portfolio      : Portfolio snapshots, performance, exposures
  - risk           : Risk limits, decisions, market conditions
  - session        : Trading session classification
  - signal_engine  : Signal generation and scoring
  - state          : System state models
  - strategy       : Strategy decisions and configurations

  - fo             : Futures & Options (NFO/BFO - equity derivatives)
  - commodity      : Commodity derivatives (MCX - bullion, energy, metals)
  - currency       : Currency derivatives (CDS - USD/INR, EUR/INR, etc.)
  - equity         : Equity cash market (NSE/BSE - stocks, holdings, IPOs)
  - fixed_income   : Bonds, G-Sec, T-Bills, debentures, SDL
  - mutual_fund    : Mutual funds, ETFs, REITs, InvITs, SIPs

Usage:
    from core.domains.execution import Order, Fill
    from core.domains.fo import FutureContract, OptionContract
    from core.domains.equity import Stock, Holding, CorporateAction
    from core.domains.commodity import CommodityContract
    from core.domains.currency import CurrencyContract, CurrencyPair
    from core.domains.portfolio import PortfolioSnapshot, PortfolioPerformance
"""

from __future__ import annotations

from core.domains.commodity import (
    MCX_CONTRACT_SPECS,
    CommodityCategory,
    CommodityContract,
    CommodityPosition,
    DeliveryType,
)
from core.domains.commodity import (
    ContractSpec as CommodityContractSpec,
)
from core.domains.currency import (
    CURRENCY_CONTRACT_SPECS,
    CurrencyContract,
    CurrencyOptionContract,
    CurrencyPair,
    CurrencyPosition,
    SettlementType,
)
from core.domains.currency import (
    ContractSpec as CurrencyContractSpec,
)
from core.domains.equity import (
    IPO,
    BoardLot,
    CorporateAction,
    CorporateActionType,
    EquityPosition,
    Holding,
    IPOStatus,
    Sector,
    Stock,
    StockFundamentals,
)

# ── Core domain models ──────────────────────────────────────────────────
from core.domains.execution import (
    ExecutionContext,
    Fill,
    Order,
    OrderResult,
    OrderStatus,
    OrderType,
    Position,
    PositionSide,
)
from core.domains.fixed_income import (
    AccrualBasis,
    Bond,
    BondPosition,
    CorporateBond,
    GovernmentSecurity,
    SecurityType,
    TBill,
    YieldType,
)
from core.domains.fo import (
    NFO_CONTRACT_SPECS,
    ExpiryType,
    FutureContract,
    FuturePosition,
    OptionContract,
    OptionPosition,
    PositionType,
    SpreadLeg,
    SpreadPosition,
    SpreadType,
    UnderlyingType,
)

# ── Multi-asset domain models ───────────────────────────────────────────
from core.domains.fo import (
    ContractSpec as FOContractSpec,
)
from core.domains.ml import (
    MLConfidence,
    MLPrediction,
    ModelFeature,
    ModelMetrics,
)
from core.domains.mutual_fund import (
    ETF,
    REIT,
    SIP,
    DividendType,
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
from core.domains.portfolio import (
    ExposureRecord,
    MarginRequirement,
    PortfolioPerformance,
    PortfolioSnapshot,
    PositionSnapshot,
    StrategyBudget,
)
from core.domains.risk import (
    HistoricalStats,
    PortfolioRiskMetrics,
    PriceLevel,
    RiskDecision,
    RiskError,
    RiskLimits,
    VolumeProfile,
)
from core.domains.risk import (
    MarketConditions as RiskMarketConditions,
)
from core.domains.session import (
    MarketSession,
    MarketSessionType,
    SessionStats,
    TradingSession,
)
from core.domains.signal_engine import (
    Candle,
    MarketData,
    SignalQuality,
    SignalService,
    TechnicalIndicators,
    TimeFrame,
    TradingSignal,
    create_signal_service,
)
from core.domains.state import (
    SessionState,
    TradingState,
)
from core.domains.strategy import (
    SignalStrength,
    StrategyConfig,
    StrategyDecision,
)

__all__ = [
    # Execution
    "ExecutionContext",
    "Fill",
    "Order",
    "OrderResult",
    "OrderStatus",
    "OrderType",
    "Position",
    "PositionSide",
    # ML
    "MLConfidence",
    "MLPrediction",
    "ModelFeature",
    "ModelMetrics",
    # Portfolio
    "ExposureRecord",
    "MarginRequirement",
    "PortfolioPerformance",
    "PortfolioSnapshot",
    "PositionSnapshot",
    "StrategyBudget",
    # Risk
    "HistoricalStats",
    "RiskMarketConditions",
    "PortfolioRiskMetrics",
    "PriceLevel",
    "RiskDecision",
    "RiskError",
    "RiskLimits",
    "VolumeProfile",
    # Session
    "MarketSession",
    "MarketSessionType",
    "SessionStats",
    "TradingSession",
    # Signal Engine
    "Candle",
    "MarketData",
    "SignalQuality",
    "SignalService",
    "TechnicalIndicators",
    "TimeFrame",
    "TradingSignal",
    "create_signal_service",
    # State
    "SessionState",
    "TradingState",
    # Strategy
    "SignalStrength",
    "StrategyConfig",
    "StrategyDecision",
    # F&O
    "FOContractSpec",
    "ExpiryType",
    "FutureContract",
    "FuturePosition",
    "NFO_CONTRACT_SPECS",
    "OptionContract",
    "OptionPosition",
    "PositionType",
    "SpreadLeg",
    "SpreadPosition",
    "SpreadType",
    "UnderlyingType",
    # Commodity
    "CommodityCategory",
    "CommodityContract",
    "CommodityContractSpec",
    "CommodityPosition",
    "DeliveryType",
    "MCX_CONTRACT_SPECS",
    # Currency
    "CurrencyContract",
    "CurrencyContractSpec",
    "CURRENCY_CONTRACT_SPECS",
    "CurrencyOptionContract",
    "CurrencyPair",
    "CurrencyPosition",
    "SettlementType",
    # Equity
    "BoardLot",
    "CorporateAction",
    "CorporateActionType",
    "EquityPosition",
    "Holding",
    "IPO",
    "IPOStatus",
    "Sector",
    "Stock",
    "StockFundamentals",
    # Fixed Income
    "AccrualBasis",
    "Bond",
    "BondPosition",
    "CorporateBond",
    "GovernmentSecurity",
    "SecurityType",
    "TBill",
    "YieldType",
    # Mutual Fund / ETF / REIT / InvIT
    "DividendType",
    "ETF",
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
