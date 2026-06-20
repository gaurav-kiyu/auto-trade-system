# Broker Inventory

Generated: 2026-06-20

## Supported Brokers
- Zerodha Kite (kiteconnect) - live execution
- Angel Broking - live execution
- PaperBrokerAdapter - simulation mode

## Broker Modules
- core/adapters/broker_adapters.py - Main broker abstraction
- core/ports/broker/ - Broker port interfaces
- core/execution/broker_gateway.py - Gateway pattern
- core/execution/broker_ack_validator.py - Ack validation
- core/execution/broker_state_handler.py - State handling
- core/execution/broker_truth_reconciliation.py - Truth reconciliation
- core/services/broker_health_service.py - Health monitoring
- core/broker_failover.py - Failover management

## Architecture
- Port/Adapter pattern: All broker calls go through BrokerPort interface
- Paper mode never reaches real broker API
- Multi-broker failover supported