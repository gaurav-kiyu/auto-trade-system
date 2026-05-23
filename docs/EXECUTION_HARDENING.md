# Execution Hardening (v2.53)

## Overview

Comprehensive execution hardening implementing 24 improvements across 7 tiers.

## New Modules

### Core Modules
- `core/system_mode.py` - System mode manager (5 states)
- `core/audit_journal.py` - Immutable JSONL audit log
- `core/execution_guards.py` - Pre-trade validation guards
- `core/incident_alerting.py` - Priority queue incident alerting
- `core/startup_validation.py` - Startup risk engine validation
- `core/execution/continuous_reconciliation.py` - Continuous broker reconciliation
- `core/market_data_fallback.py` - Dual-source market data
- `core/exposure_limits.py` - Exposure concentration limits
- `core/secret_hygiene.py` - Secret hygiene validation
- `core/execution_hardening_integration.py` - Integration module

### Test Modules
- `tests/test_concurrency_stress.py` - Concurrency tests
- `tests/test_failure_injection.py` - Failure injection tests
- `tests/test_full_day_soak.py` - Soak tests
- `tests/test_smoke_execution_hardening.py` - Smoke tests

## Usage

### Quick Start (Optional)

```python
from core.execution_hardening_integration import init_execution_hardening

services = init_execution_hardening(
    config=config_dict,
    broker_port=broker_port,
    send_alert_fn=send_telegram_alert,
    get_price_fn=get_live_price
)
```

### Individual Modules

```python
# System mode
from core.system_mode import get_system_mode_manager
sm = get_system_mode_manager()
sm.can_enter_new_trade()  # Returns (allowed, reason)

# Execution guards  
from core.execution_guards import get_execution_guards
guards = get_execution_guards(config)
guards.check_all_guards(symbol, direction, model_price, live_price, ...)

# Audit journal
from core.audit_journal import get_audit_journal, AuditEventType, AuditSeverity
journal = get_audit_journal()
journal.log_event(AuditEventType.ORDER_FILLED, AuditSeverity.INFO, "Filled")
```

## Config Keys

### Reconciliation
- `CONTINUOUS_RECONCILIATION_ENABLED` (default: true)
- `RECONCILIATION_ACTIVE_INTERVAL_SEC` (default: 30)
- `RECONCILIATION_IDLE_INTERVAL_SEC` (default: 300)

### Execution Guards
- `SLIPPAGE_GUARD_THRESHOLD_PCT` (default: 2.0)
- `MAX_QUOTE_AGE_SECONDS` (default: 2.0)
- `MAX_TRADES_PER_DAY` (default: 10)
- `MAX_CONSECUTIVE_LOSSES` (default: 3)
- `LATE_SESSION_THRESHOLD` (default: "14:30")
- `LATE_SESSION_SIZE_MULT` (default: 0.5)

### Alerting
- `INCIDENT_ALERTING_ENABLED` (default: true)
- `INCIDENT_COOLDOWN_SECONDS` (default: 60)

### Market Data
- `market_data_secondary_enabled` (default: false)
- `market_data_mismatch_threshold_pct` (default: 1.0)

### Exposure
- `max_exposure_per_symbol_pct` (default: 30.0)
- `max_exposure_per_expiry_pct` (default: 50.0)
- `max_exposure_per_direction_pct` (default: 80.0)
- `max_exposure_per_strategy_pct` (default: 40.0)

### Security
- `SECRET_HYGIENE_ENABLED` (default: true)
- `SECRET_HYGIENE_SCAN_ON_STARTUP` (default: true)

## System States

- `NORMAL` - Full trading allowed
- `DEGRADED` - Partial functionality, reduced trading
- `BROKER_DOWN` - Broker unreachable, reconciliation only
- `MARKET_HALTED` - Market closed/halted
- `SAFE_MODE` - Risk breach or manual intervention

## Tests

```bash
# Smoke tests (fast)
python -m pytest tests/test_smoke_execution_hardening.py -v

# Concurrency tests
python -m pytest tests/test_concurrency_stress.py -v

# Failure injection
python -m pytest tests/test_failure_injection.py -v

# Full soak test
python tests/test_full_day_soak.py --days 5
```