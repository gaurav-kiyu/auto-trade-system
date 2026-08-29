# 🏛️ OPB SUPER-PLATFORM: PHASE 7 STRATEGY INVENTORY

**Audit Standard**: `FINAL-PHASE NO-REGRESSION LAW` (`.agents/rules/00-final-phase-no-regression-law.md`)  
**Scope**: 16 Registered & Implemented Strategy Modules  
**Date**: August 23, 2026  
**Auditor**: Senior Quantitative Research Architect & Algorithmic Trading Auditor  

---

## 📋 EXECUTIVE INVENTORY SUMMARY

The repository strategy catalog defines 16 operational modules across Indian Equities, Index Derivatives (NIFTY / BANKNIFTY / FINNIFTY / MIDCPNIFTY), Sector ETFs, Commodities (MCX), Currencies (CDS), REITs/InvITs, and IPO listing gains.

However, adversarial code-level architectural analysis reveals that the 16 items fall into three distinct functional classifications:
1. **True Alpha / Execution Strategies (13 Modules)**: Standalone signal generation and trade execution engines.
2. **Derivative Payoff Builder (1 Module - `STRAT-08 OptionStrategyBuilder`)**: Mathematical option structuring and payoff modeling utility.
3. **Execution Infrastructure & Routing (2 Modules - `STRAT-09 SmartOrderRouter`, `STRAT-16 MultiAssetDispatcher`)**: Low-latency broker routing and asset class dispatching buses.

---

## 🔍 COMPREHENSIVE STRATEGY REGISTRY TABLE

| Strategy ID | Name | Module Path | Asset Class | Primary Engine / Mechanism | Timeframe | Long/Short | Risk Limits & Stop-Loss | Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :---: |
| **STRAT-01** | `pure_index_momentum` | `core.pure_index_signal` | Index Options | Trend Alignment + VWAP + Vol Surge | 5m / 15m | Long CALL / PUT | Dynamic ATR (1.5x - 2.5x) | 🟢 **ACTIVE** |
| **STRAT-02** | `ma_crossover` | `core.strategy.ma_crossover` | Equity / Futures | Fast/Slow EMA (9/21, 20/50, 50/200) | 15m / 1h / Daily | Long / Short | 1.5% fixed SL or Swing Low | 🟢 **ACTIVE** |
| **STRAT-03** | `mean_reversion` | `core.strategy.mean_reversion` | Indices / Equity | Bollinger Bands + RSI(14) + VWAP | 5m / 15m | Long / Short | 2.0x Band Width / 1.0% SL | 🟢 **ACTIVE** |
| **STRAT-04** | `futures_basis_arbitrage` | `core.strategy.futures_trader` | Equity Futures | Spot-Futures Fair Value Spread | 1m / Tick | Cash-Futures Arb | Basis Convergence / Expiry | 🟢 **ACTIVE** |
| **STRAT-05** | `index_option_straddle` | `core.straddle_strategy` | NIFTY / BANKNIFTY | ATM Short / Long Straddle | Intraday (9:20 - 15:15) | Short Delta Neutral | 25% Premium Stop Loss | 🟢 **ACTIVE** |
| **STRAT-06** | `vertical_option_spreads` | `core.spread_strategy` | NIFTY / BANKNIFTY | Bull Call / Bear Put / Credit Spreads | Weekly / Monthly | Directional Hedged | Max Loss capped at Spread Width | 🟢 **ACTIVE** |
| **STRAT-07** | `iron_condor_neutral` | `core.iron_condor_strategy` | NIFTY / BANKNIFTY | 4-Leg OTM Call/Put Wing Condor | Weekly Expiry | Delta Neutral Range | Wing Width - Net Premium | 🟢 **ACTIVE** |
| **STRAT-08** | `option_strategy_builder` | `core.trading.option_strategy_builder` | Options Structuring | Payoff Calculator & Greek Modeler | On-Demand | Multi-Leg Arbitrary | Greek Exposure Thresholds | 🔵 **TOOL** |
| **STRAT-09** | `smart_order_router` | `core.trading.smart_order_router` | Multi-Broker Execution | Latency / Margin / Fill Rate Optimizer | Real-Time | Order Execution | Broker Fallback / Re-routing | 🔵 **ROUTER** |
| **STRAT-10** | `equity_momentum` | `core.equity_trader` | NSE Cash (Nifty 500) | Breakout + Relative Volume + ADX | Daily / 1h | Long Delivery / Intraday | 2.0% Risk / Trailing Supertrend | 🟢 **ACTIVE** |
| **STRAT-11** | `sector_etf_allocation` | `core.etf_trader` | Nifty Sector ETFs | Relative Strength Index Ranking | Daily / Weekly | Long Rotational | Sector Drawdown 5.0% | 🟢 **ACTIVE** |
| **STRAT-12** | `commodity_trend_spread` | `core.commodity_trader` | MCX Gold/Silver/Crude | Calendar & Inter-Commodity Spread | 15m / 1h | Long / Short Spread | Margin Risk Multiplier | 🟢 **ACTIVE** |
| **STRAT-13** | `currency_volatility` | `core.currency_trader` | NSE USDINR / EURINR | Implied Volatility Mean Reversion | 15m / Hourly | Neutral / Directional | Reserve Bank Intervention Bound | 🟢 **ACTIVE** |
| **STRAT-14** | `reit_high_yield` | `core.reit_trader` | Embassy / Mindspace | Dividend Yield + NAV Discount Model | Weekly / Monthly | Long Term Yield | NAV Discount > 15% | 🟢 **ACTIVE** |
| **STRAT-15** | `ipo_listing_gain` | `core.ipo_trader` | Mainboard & SME IPOs | GMP (Grey Market) + QIB Subscription | T+3 Listing Day | Listing Day Flip | First 15m Low Break | 🟢 **ACTIVE** |
| **STRAT-16** | `multi_asset_dispatcher` | `core.strategy.multi_asset_dispatcher` | Unified Portfolio | Dynamic Capital Allocation Bus | Real-Time | Cross-Asset Router | Portfolio VaR / Total Capital Limit | 🔵 **DISPATCHER** |

---

## 🎯 ARCHITECTURAL RECONCILIATION

- **Alpha Generating Strategies**: 13 Strategies (`STRAT-01` to `STRAT-07`, `STRAT-10` to `STRAT-15`).
- **Option Engine Support Tool**: `STRAT-08` (`OptionStrategyBuilder`) provides standard analytical functions (`calculate_payoff_profile`, `black_scholes_price`, `find_breakevens`).
- **Execution & Routing Subsystems**: `STRAT-09` (`SmartOrderRouter`) and `STRAT-16` (`MultiAssetDispatcher`) govern trade dispatch and broker failover.
- **Total Cataloged Entities**: Exactly **16 Modules** accounted for and audited.
