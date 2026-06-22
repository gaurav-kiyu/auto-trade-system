# Missing Feature Matrix

**Generated:** June 21, 2026  
**Status:** Initial Assessment

---

## Purpose

This document tracks asset classes and features that are not yet fully supported by the OPB platform. It serves as a roadmap for market coverage expansion.

## Asset Class Coverage

| Asset Class | Status | Notes |
|-------------|--------|-------|
| **NIFTY** (index options) | ✅ Full | Primary supported instrument |
| **BANKNIFTY** (index options) | ✅ Full | Supported via multi-instrument |
| **FINNIFTY** (index options) | ✅ Full | Supported via multi-instrument |
| **MIDCAP NIFTY** | ⚠️ Partial | Data sources available, not actively traded |
| **SENSEX** | ⚠️ Partial | Data sources available via yfinance |
| **Equities (cash)** | ⚠️ Partial | Adapter exists (`NseEquityAdapter`) |
| **Equity Futures** | ⚠️ Partial | Data available, strategy not implemented |
| **Equity Options** | ⚠️ Partial | Data available, strategy not implemented |
| **Commodities** (MCX) | ⚠️ Partial | Adapter exists (`McxCommodityAdapter`) |
| **Currency** (CDS) | ⚠️ Partial | Adapter exists (`CdsCurrencyAdapter`) |
| **Bonds** | ❌ Missing | No data source configured |
| **Mutual Funds** | ❌ Missing | No data source configured |
| **ETFs** | ❌ Missing | Data available but not integrated |
| **REITs** | ❌ Missing | No data source configured |
| **InvITs** | ❌ Missing | No data source configured |
| **SME Stocks** | ❌ Missing | Requires BSE SME data source |
| **IPO/FPO/OFS/QIP** | ❌ Missing | Requires event calendar integration |
| **Corporate Actions** | ❌ Missing | Requires data feed integration |

## Feature Coverage

| Feature | Status | Notes |
|---------|--------|-------|
| **IV Surface** | ✅ Complete | `core/iv_surface.py` |
| **Max Pain** | ✅ Complete | `core/max_pain.py` |
| **Factor Models** | ✅ Complete | Fama-French 3-factor + Carhart 4-factor |
| **Portfolio Attribution** | ✅ Complete | `core/factor_models.py` (compute_portfolio_attribution) |
| **Risk Attribution** | ✅ Complete | Factor-based risk decomposition |
| **Cross Asset Analytics** | ✅ Complete | `core/cross_asset_analytics.py` |
| **Recommendation Engine** | ❌ Missing | Not implemented |
| **Liquidity Analytics** | ✅ Complete | `core/liquidity_analytics.py` |
| **Equal Risk Contribution** | ✅ Complete | `core/portfolio/optimizer.py` |
| **CVaR Optimization** | ✅ Complete | `core/portfolio/optimizer.py` |
| **OpenTelemetry Integration** | ❌ Missing | Requires external dependency |
| **Grafana Dashboard** | ⚠️ Partial | JSON dashboard exists at `deploy/grafana/` |
| **ELK/Loki Stack** | ❌ Missing | Not implemented |
| **FIX Protocol** | ❌ Missing | Not required for current brokers |

## Recommended Next Steps

1. **P0:** Equity options trading strategy (highest value)
2. **P1:** Bond/ETF data source integration
3. **P2:** OpenTelemetry distributed tracing
4. **P3:** Grafana dashboard from existing Prometheus metrics
5. **P4:** ELK/Loki log aggregation stack
