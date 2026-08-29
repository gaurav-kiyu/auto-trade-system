#!/usr/bin/env python3
"""
Batch Portfolio Scanner

Automates multi-tenant portfolio scanning across multiple brokers using
the Admin Portfolio Analyzer 16-strategy engine.

This script demonstrates how to:
1. Iterate over all tenants configured in the MultiTenantManager.
2. Dynamically switch broker connections via BrokerGateway.
3. Extract live portfolios and generate deep scan reports offline (e.g. via Cron)
   without impacting the memory or latency of the live trading engine.
"""

import json
import logging

# Add project root to PYTHONPATH if run directly
import sys
from datetime import datetime
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Import your actual broker adapters here.
# (For demo purposes, we will register a MockAdapter if the real ones aren't available)
from core.adapters.base_adapter import BrokerAdapter, OrderRequest, OrderResponse, OrderStatus
from core.admin_portfolio_analyzer import get_admin_portfolio_analyzer
from core.config_loader import load_config
from core.execution.broker_gateway import broker_gateway
from core.multi_tenant import MultiTenantManager


class DemoMockAdapter(BrokerAdapter):
    def authenticate(self, credentials: dict) -> bool:
        return True

    def get_positions(self) -> list:
        # Mock portfolio for demonstration
        return [
            {"tradingsymbol": "RELIANCE", "quantity": 100, "average_price": 2800.0, "last_price": 3050.0},
            {"tradingsymbol": "HDFCBANK", "quantity": 300, "average_price": 1650.0, "last_price": 1420.0},
            {"tradingsymbol": "TCS", "quantity": 50, "average_price": 3800.0, "last_price": 4200.0}
        ]

    def get_ltp(self, symbol: str) -> float: return 0.0
    def place_order(self, request: OrderRequest) -> OrderResponse:
        return OrderResponse(order_id="demo", status=OrderStatus.FILLED)
    def cancel_order(self, order_id: str) -> bool: return True
    def get_order_status(self, order_id: str) -> OrderStatus: return OrderStatus.FILLED
    def get_instrument_token(self, symbol: str) -> str: return "123456"
    def is_healthy(self) -> bool: return True


def setup_adapters():
    """Register broker adapters with the gateway."""
    # You would typically register your real adapters here:
    # from core.adapters.broker.zerodha_adapter import ZerodhaAdapter
    # broker_gateway.register_adapter("zerodha", ZerodhaAdapter)

    # Registering a mock adapter so the script runs out of the box
    broker_gateway.register_adapter("zerodha", DemoMockAdapter)
    broker_gateway.register_adapter("angelone", DemoMockAdapter)
    broker_gateway.register_adapter("upstox", DemoMockAdapter)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    log = logging.getLogger("batch_scanner")

    log.info("Starting Batch Portfolio Scanner...")
    setup_adapters()

    cfg = load_config()
    # Ensure multi-tenant is enabled for the manager
    cfg["multi_tenant_enabled"] = True

    tenant_manager = MultiTenantManager(cfg)
    analyzer = get_admin_portfolio_analyzer()

    tenants = tenant_manager.list_tenants()
    if not tenants:
        log.warning("No tenants found in configuration. Please define 'tenants' array in config.json.")
        # We can simulate one for the demo
        from core.multi_tenant import Tenant
        demo_tenant = Tenant(
            tenant_id="demo_001",
            name="Demo Client",
            config_overrides={"BROKER_CODE": "zerodha", "BROKER_CREDENTIALS": {"api_key": "demo"}}
        )
        tenant_manager.register_tenant(demo_tenant)
        tenants = tenant_manager.list_tenants()

    reports_dir = project_root / "reports" / "portfolio_scans"
    reports_dir.mkdir(parents=True, exist_ok=True)

    today_str = datetime.now().strftime("%Y%m%d")

    for tenant in tenants:
        log.info(f"--- Scanning Portfolio for Tenant: {tenant.name} ({tenant.tenant_id}) ---")

        if not tenant.is_active:
            log.info(f"Skipping {tenant.name} - Tenant is inactive.")
            continue

        context = tenant_manager.get_context(tenant.tenant_id)
        eff_cfg = context.get_effective_config()

        # Get broker details from the tenant's isolated config overrides
        broker_code = eff_cfg.get("BROKER_CODE", "zerodha")
        credentials = eff_cfg.get("BROKER_CREDENTIALS", {"api_key": "demo_key"}) # Fallback for demo

        # Switch the gateway context to this specific user's broker session
        if broker_gateway.switch_broker(broker_code, credentials):
            log.info(f"Successfully authenticated with broker: {broker_code}")

            try:
                # Fetch live positions from the broker API
                raw_positions = broker_gateway.get_positions()
                log.info(f"Fetched {len(raw_positions)} raw positions.")

                # Normalize the broker-specific data into standard PortfolioPosition objects
                positions = analyzer.parse_portfolio(raw_positions)

                # Run the 16-Strategy Quantitative Scan
                report = analyzer.run_16_strategy_deep_scan(
                    user_name=tenant.name,
                    broker_code=broker_code,
                    positions=positions
                )

                # Save the JSON report
                report_path = reports_dir / f"scan_{tenant.tenant_id}_{today_str}.json"
                with open(report_path, "w", encoding="utf-8") as f:
                    json.dump(report, f, indent=4)

                score = report.get('portfolio_health_score', 0)
                pnl = report.get('total_unrealized_pnl', 0)
                log.info(f"Scan Complete -> Health Score: {score}/100 | PnL: ₹{pnl}")
                log.info(f"Report saved to: {report_path.relative_to(project_root)}\n")

            except Exception as e:
                log.error(f"Failed to scan portfolio for {tenant.name}: {e}")
        else:
            log.error(f"Failed to connect to broker '{broker_code}' for {tenant.name}. Check credentials.")

if __name__ == "__main__":
    main()
