# Migration Plan: Splitting `index_trader.py` into Domain Services

## Current State

**File:** `index_app/index_trader.py` — ~8,200 lines  
**Problem:** Monolithic — combines signal generation, risk management, execution, position monitoring, config loading, telegram dispatch, WS feed, reconciliation, and admin control plane in a single file.

## Current Function Map

```
index_trader.py (~8,200 lines)
├── Config Loading (lines 1-350, ~350 lines)
│   ├── Config defaults, fail-safes, notification
│   ├── _load_config(), _set_config_fail_safe()
│   └── Environment variable handling
├── Broker/Warmup (lines 351-710, ~360 lines)
│   ├── _init_broker_truth_reconciler()
│   ├── _make_broker()
│   └── Broker configuration
├── Core Trading Functions (lines 711-1100, ~390 lines)
│   ├── enter_trade(), _exit_position()
│   ├── get_position_size()
│   ├── _generate_trading_signal()
│   └── validate_signal_pillars()
├── Reconciliation (lines 927-1080, ~150 lines)
│   ├── _reconcile_positions_live()
│   ├── _periodic_reconcile()
│   └── _broker_positions_snapshot()
├── Trading Loop (lines 1320-1450, ~130 lines)
│   ├── _run_trading_loop()
│   ├── _monitor_positions()
│   └── WebSocket handlers
├── DI Container (lines 1468-1650, ~180 lines)
│   ├── setup_di_container()
│   └── Service wiring
├── Admin Control Plane (lines 1828-1900, ~70 lines)
│   ├── _init_admin_control_plane()
│   └── _reload_config_handler()
├── main() Entry Point (lines 1907+, ~200 lines)
│   └── Boot sequence
└── Duplicate Code Block (lines 2200+)
    └── Dead code / duplicate module docstring
```

## Target Architecture

```
index_app/index_trader.py (~500 lines — orchestration only)
├── main() — boot sequence
├── setup_di_container() — wiring
├── run() — lifecycle management
└── imports from domain services
```

### New Domain Services

```
index_app/
  index_trader.py              ← Orchestrator (~500 lines)
domains/
  signal/
    __init__.py
    service.py                  ← SignalService
    generator.py                ← Signal generation logic
    scorer.py                   ← Score computation
    validator.py                ← Signal pillar validation
  risk/
    __init__.py
    service.py                  ← RiskService
    sizing.py                   ← Position sizing
    limits.py                   ← Hard stops, drawdown
  execution/
    __init__.py
    service.py                  ← ExecutionService
    position_manager.py         ← Position monitoring
    reconciliation.py           ← Broker reconciliation
  broker/
    __init__.py
    factory.py                  ← Broker creation
    health.py                   ← Broker health
  config/
    __init__.py
    loader.py                   ← Config loading
    manager.py                  ← Config lifecycle
  telegram/
    __init__.py
    dispatch.py                 ← Telegram dispatch
    formatting.py               ← Message formatting
  reconciliation/
    __init__.py
    service.py                  ← Position reconciliation
```

## Migration Strategy: 6-Phase Incremental Extraction

### Phase 1: Create Package Structure (0.5 day)

```python
# Create domain packages
mkdir -p index_app/domains/signal
mkdir -p index_app/domains/risk
mkdir -p index_app/domains/execution
mkdir -p index_app/domains/broker
mkdir -p index_app/domains/config
mkdir -p index_app/domains/telegram
mkdir -p index_app/domains/reconciliation

# Add __init__.py to each
for d in signal risk execution broker config telegram reconciliation; do
    touch index_app/domains/$d/__init__.py
done
```

### Phase 2: Extract Config Domain (1 day)

**Move:** Config loading functions from `index_trader.py` (lines 1-350)

```python
# index_app/domains/config/loader.py
class ConfigLoader:
    def load(force=False) -> dict: ...
    def set_fail_safe(cfg) -> None: ...
    def notify_failure(detail: str) -> None: ...

# index_app/domains/config/manager.py
class ConfigManager:
    def __init__(self, cfg: dict): ...
    def reload() -> dict: ...
    def get(key, default=None): ...
```

**Validation:** `python -c "from index_app.domains.config.loader import ConfigLoader; c=ConfigLoader(); print(c.load())"`

### Phase 3: Extract Signal Domain (2 days)

**Move:** `_generate_trading_signal()`, `validate_signal_pillars()`, signal quality reporting

```python
# index_app/domains/signal/service.py
class SignalService:
    def generate(index: str, frames: dict, vix: float) -> SignalResult: ...
    def validate_pillars(regime: str, score: int, iv_rank: float) -> tuple[bool, str]: ...
    def get_quality_report() -> dict: ...
    def get_top_signals(n: int) -> list: ...
```

**Wire via DI container:**
```python
# In setup_di_container():
container.register(SignalService, lambda: SignalService(config))
```

**Validation:** `pytest tests/test_signal*.py tests/test_adaptive_signal.py tests/test_pure_index_signal.py -q`

### Phase 4: Extract Risk Domain (2 days)

**Move:** `get_position_size()`, `_check_hard_stops_via_risk()`, mandate checks

```python
# index_app/domains/risk/service.py
class RiskDomainService:
    def get_position_size(self, name, entry, vix) -> int: ...
    def check_hard_stops(self) -> tuple[bool, str]: ...
    def check_mandate(regime, score, iv_rank) -> tuple[bool, str]: ...
    def get_mandate_status() -> dict: ...
    def adaptive_threshold_adjustment(regime, strength): ...
```

**Validation:** `pytest tests/test_risk*.py tests/test_mandate*.py tests/test_kelly_sizer.py -q`

### Phase 5: Extract Execution Domain (3 days)

**Move:** `enter_trade()`, `_exit_position()`, `_monitor_positions()`, position tracking

```python
# index_app/domains/execution/service.py
class ExecutionDomainService:
    def enter(self, name, signal) -> bool: ...
    def exit(self, name, reason) -> None: ...
    def monitor(self) -> None: ...
    def get_live_prices() -> dict: ...

# index_app/domains/execution/position_manager.py
class PositionManager:
    def get_snapshot() -> dict: ...
    def get_history() -> list: ...
    def get_state(name) -> PositionState: ...
```

**Validation:** `pytest tests/test_execution*.py tests/test_exit_*.py tests/test_position*.py -q`

### Phase 6: Extract Remaining Domains (2 days)

| Domain | Functions to Extract | Effort |
|--------|---------------------|--------|
| Broker | `_make_broker()`, broker init, WS feed | 1 day |
| Telegram | `_send_impl()`, `_buffered_send()`, message formatting | 0.5 day |
| Reconciliation | `_reconcile_positions_live()`, `_periodic_reconcile()` | 1 day |
| Trading Loop | `_run_trading_loop()`, `market_status()`, `daily_reset()` | 1 day |

## DI Container Wiring

```python
# setup_di_container() after extraction
def setup_di_container() -> None:
    container = DIContainer()
    
    # Core config
    container.register(ConfigManager, lambda: ConfigManager(cfg))
    
    # Domain services
    container.register(SignalDomainService, lambda: SignalDomainService(
        config=container.resolve(ConfigManager)
    ))
    container.register(RiskDomainService, lambda: RiskDomainService(
        config=container.resolve(ConfigManager)
    ))
    container.register(ExecutionDomainService, lambda: ExecutionDomainService(
        config=container.resolve(ConfigManager),
        broker=container.resolve(BrokerFactory),
        signal=container.resolve(SignalDomainService),
        risk=container.resolve(RiskDomainService),
    ))
    
    # Broker
    container.register(BrokerFactory, lambda: BrokerFactory(
        config=container.resolve(ConfigManager)
    ))
```

## Rollback Strategy

1. **Default path preservation:** Each new domain service has a `legacy_mode()` method that delegates to the original inline code if the DI container isn't wired
2. **Feature flags:** `USE_DOMAIN_SERVICES` config flag — when False, falls back to extracted static functions in a compatibility module
3. **Test coverage gates:** Each extraction phase requires 90%+ code coverage before the extracted module replaces the inline code

## Testing Strategy

| Phase | Unit Tests | Integration Tests | Regression |
|-------|-----------|-------------------|------------|
| Config | 10 | 3 | Full suite |
| Signal | 20 | 5 | Signal tests |
| Risk | 15 | 4 | Risk tests |
| Execution | 25 | 8 | Execution tests |
| Broker | 10 | 3 | Broker tests |
| Final Integration | — | 15 | Full suite (1,000+ tests) |

## Success Criteria

| Metric | Before | After |
|--------|--------|-------|
| index_trader.py lines | ~8,200 | < 500 |
| Total new domain files | 0 | 14 |
| New test count | — | +80 |
| Module dependency depth | Flat (1 file) | Layered (3 tiers) |
| DI integration tests | 34 | 50+ |
