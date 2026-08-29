# Admin Multi-Broker Portfolio Inspector & Automation Guide

## 1. Overview
The **Admin Portfolio Analyzer** is a multi-tenant enterprise tool that allows administrators to connect to different client broker accounts (Zerodha, Angel One, Upstox, etc.), import live portfolios, and run a **16-Strategy Deep Scan** to generate stock-by-stock hold/sell/buy guidance with mathematical proofs.

## 2. Using the UI (Portfolio Inspector)
1. **Navigate to the Inspector**: Click `Portfolio Inspector` in the top admin navigation bar.
2. **Select Client's Broker**: Click on the specific broker your client uses from the grid (e.g., Zerodha).
3. **OAuth Login**: A secure login panel will appear. The client authenticates via OAuth 2.0 directly with their broker. The system securely receives an API token (it never sees their password).
4. **Run Scan**: Once the portfolio is imported, click `Confirm & Run 16-Strategy Deep Scan`.
5. **View Results**: The system will display:
   - Portfolio Health Score
   - Unrealized PnL
   - Recommended Actions (SELL_IMMEDIATELY, STRONG_HOLD, etc.)
   - Quantitative Proofs (Click "View Proof" for detailed reasoning and SHAP values).

## 3. How to Automate & Build Custom Scripts (Future Sustainability)
If you are managing dozens of clients and want to build a sustainable, automated portfolio management system, you should leverage the existing **Multi-Tenant Architecture**.

### A. The Core Components
1. **`core.multi_tenant.MultiTenantManager`**: Manages isolated configurations for each client.
2. **`core.execution.broker_gateway.BrokerGateway`**: Allows on-the-fly switching between broker SDKs.
3. **`core.admin_portfolio_analyzer.AdminPortfolioAnalyzer`**: The engine that runs the 16-strategy logic.

### B. Suggested Automation Architecture
To sustainably automate portfolio scanning across multiple clients, write a Python script (e.g., `scripts/batch_portfolio_scan.py`) that runs daily via Cron/Task Scheduler.

```python
import asyncio
from core.multi_tenant import MultiTenantManager
from core.execution.broker_gateway import broker_gateway
from core.admin_portfolio_analyzer import get_admin_portfolio_analyzer

async def run_daily_client_scans():
    tenant_manager = MultiTenantManager()
    analyzer = get_admin_portfolio_analyzer()
    
    # 1. Iterate over all registered clients
    for tenant_id, tenant in tenant_manager.get_all_tenants().items():
        print(f"Scanning portfolio for {tenant.name}...")
        
        # 2. Get the client's broker credentials from their isolated config
        cfg = tenant_manager.get_context(tenant_id).get_effective_config()
        broker_code = cfg.get("BROKER_CODE", "zerodha")
        credentials = cfg.get("BROKER_CREDENTIALS", {})
        
        # 3. Switch the gateway to this client's broker account
        if broker_gateway.switch_broker(broker_code, credentials):
            # 4. Fetch live positions
            raw_positions = broker_gateway.get_positions()
            positions = analyzer.parse_portfolio(raw_positions)
            
            # 5. Run the 16-Strategy Deep Scan
            report = analyzer.run_16_strategy_deep_scan(
                user_name=tenant.name, 
                broker_code=broker_code, 
                positions=positions
            )
            
            # 6. Save or email the report
            save_report_to_db(tenant_id, report)
            print(f"Health Score: {report['portfolio_health_score']}")
```

### C. Why this is the best path forward
1. **Strict Data Isolation**: Using `MultiTenantManager` ensures you never accidentally mix Client A's trades with Client B's config.
2. **Scalability**: `BrokerGateway` abstracts away the broker differences. Your script doesn't need to know if the client uses Upstox or Angel One; the Gateway handles the API quirks.
3. **State Management**: Using a batch script over `cron` prevents the main trading engine from blocking or running out of memory when managing hundreds of users.

## Advanced Super Platform Features
As of v2.0, the Portfolio Analyzer acts as a quantitative Super Platform featuring:
- **One-Click Auto-Hedging**: Converts 'Rebalance' signals into live dry-run approved Delta-neutral options trades.
- **Tax-Loss Harvesting**: Dynamically identifies >10% losing positions for capital loss offset and recommends correlated index tracking swaps.
- **Generative AI Reports**: Exports fully personalized client-facing PDF/Markdown portfolios via Gemini GenAI integration.

- **Redis Pub/Sub Tick Interception**: Achieves microsecond data resolution.
- **Agentic Sentiment Ingestion**: Ingests LLM-driven event-based momentum shifts with strict +/- 2.5% impact caps to mitigate hallucination risks.
- **Collateral Sweep (LIQUIDBEES)**: Automatically manages cash buffers, optimizing margin pledges on idle capital.

## 10. Dynamic VIX Intelligence & UI Command Center
As of the latest upgrade, parameters are no longer hardcoded. The system dynamically reads the India VIX. 
- A VIX > 20 mathematically scales the safety Cash Buffer up to 40% and restricts LLM agent impact to 0.5% (Trust Math).
- A VIX < 15 mathematically drops the safety Buffer to 10% (Yield Maximize) and opens LLM agent impact to 2.5%.
All of this is monitored live via the **Enterprise Command Center HUD** at the top of the Portfolio Analyzer UI, providing instant visibility into Redis connection status, LLM Sentiment Score, and live VIX thresholds.
