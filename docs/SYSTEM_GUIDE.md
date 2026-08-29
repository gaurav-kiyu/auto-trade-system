# OPBuying System Guide

Welcome to the **OPBuying Super Platform**. This document outlines the major architectural components of the platform, designed for multi-broker scaling, AI-driven quantitative analysis, and automated execution.

## 1. Multi-Tenant Broker Gateway
The platform utilizes a MultiTenantManager (core/multi_tenant.py) and a BrokerGateway (core/execution/broker_gateway.py) to seamlessly hot-swap API keys on the fly. 
This allows a single running instance to manage hundreds of distinct clients across ZeroDha, Upstox, and AngelOne without crossover.

## 2. 16-Strategy Quantitative Engine
Located in core/admin_portfolio_analyzer.py, this engine evaluates every stock against 16 distinct quantitative parameters.

## 3. Live Indicators (core/ai/live_indicators.py)
Provides deterministic metrics (RSI, Beta, VWAP distance, 30D Volatility) based on real-time execution pipelines, enhancing the reasoning of the 16-strategy engine.

## 4. One-Click Auto-Hedger
Options tail-risk is analyzed and mitigated in core/risk/auto_hedger.py. Using the UI, admins can stage delta-neutral trades. All live trades pass through an **Approval Gate (Dry-Run)** before being passed to roker_gateway.place_order().

## 5. Tax-Loss Harvester
core/risk/tax_loss_harvester.py dynamically scans client portfolios for unrealized losses exceeding 10%. It flags these for tax offset and mathematically suggests a highly correlated replacement asset to maintain systemic market exposure.

## 6. Generative AI Client Reports
core/ai/report_generator.py digests the raw JSON outputs of the 16-strategy engine and interfaces with Gemini (gemini-1.5-flash) to generate PDF-ready executive summaries for clients. If no API key is provided, it seamlessly fails over to a robust local template generator.

## 7. Market Data Infrastructure (Redis & Time-Series DB)
The platform features an ultra-low latency RedisMarketDataBus (core/execution/redis_pubsub.py) that handles real-time WebSocket ticks, preventing 3rd-party REST API rate limits. Additionally, a DuckDB-backed TimeSeriesDataLake (core/persistence/timeseries_db.py) allows for high-speed ML backtesting on millions of historical candles.

## 8. Agentic Sentiment Analysis
core/ai/agentic_sentiment.py uses LLMs (Google Gemini) to read news and financial reports, dynamically generating a quantitative score (-100 to +100) that feeds directly into the 16-strategy analyzer to adjust position recommendations before the market reacts.

## 9. Automated Collateral Management
core/portfolio/collateral_manager.py analyzes un-deployed cash. It maintains a 20% pure cash safety buffer, sweeping any excess into margin-pledgable ETFs (like LIQUIDBEES) to eliminate cash drag while keeping liquidity high.

## 10. Dynamic VIX Intelligence & UI Command Center
As of the latest upgrade, parameters are no longer hardcoded. The system dynamically reads the India VIX. 
- A VIX > 20 mathematically scales the safety Cash Buffer up to 40% and restricts LLM agent impact to 0.5% (Trust Math).
- A VIX < 15 mathematically drops the safety Buffer to 10% (Yield Maximize) and opens LLM agent impact to 2.5%.
All of this is monitored live via the **Enterprise Command Center HUD** at the top of the Portfolio Analyzer UI, providing instant visibility into Redis connection status, LLM Sentiment Score, and live VIX thresholds.

## 11. Interactive Telegram Approvals (Phase 3)
Supports pushing execution confirmations directly to a Telegram device via core/telegram/interactive_approvals.py. Falls back to UI if missing token.

## 12. Algorithmic Execution Routing (TWAP)
TWAP execution slices large orders to avoid slippage.
