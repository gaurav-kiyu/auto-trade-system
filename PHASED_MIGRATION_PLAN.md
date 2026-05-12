# Phased Migration Plan: Refactoring to Clean Architecture

## Overview
This document outlines a detailed, low-risk migration plan to refactor the current monolithic NSE index options trading platform into a clean, modular architecture based on SOLID principles, Clean Architecture, and Domain-Driven Design. The plan prioritizes maintaining backward compatibility, minimizing disruption, and ensuring the system remains functional throughout the migration process.

## Migration Principles

### 1. Strangler Fig Pattern
Gradually replace functionality of the monolith with new implementations, allowing the old system to "die off" over time.

### 2. Backward Compatibility
Ensure all existing interfaces (CLI, configuration files, APIs) remain functional during migration.

### 3. Incremental Delivery
Deliver value in small, verifiable increments rather than attempting a big-bang rewrite.

### 4. Testing First
Write tests before refactoring to ensure behavior preservation.

### 5. Feature Toggles
Use configuration flags to enable/disable new functionality during transition.

## Migration Phases

### Phase 0: Preparation (Weeks 1-2)
**Goal**: Set up the foundation for migration without changing production code.

**Activities**:
1. **Create New Directory Structure**
   - Set up the proposed folder structure in a parallel directory or version control branch
   - Create all necessary directories as defined in PROPOSED_STRUCTURE.md

2. **Establish Baseline Tests**
   - Ensure existing test suite passes (1563 passing tests as seen in last run)
   - Identify critical paths for regression testing
   - Create characterization tests for complex business logic if needed

3. **Define Core Ports and Interfaces**
   - Create interface definitions in `core/ports/` for:
     - BrokerPort
     - MarketDataPort
     - PersistencePort
     - NotificationPort
     - MlModelPort
     - ConfigPort
   - Keep interfaces minimal and focused

4. **Set Up Shared Kernel**
   - Create `core/shared/` with:
     - Exceptions domain
     - Constants
     - Basic utilities
     - Domain primitives (Value Objects, Entities)

5. **Configure Build and CI**
   - Update requirements.txt to separate core vs optional dependencies
   - Configure pre-commit hooks for linting and formatting
   - Set up basic CI pipeline

**Deliverables**:
- New directory structure created
- Core ports defined
- Shared kernel established
- Baseline passing tests confirmed
- Preparation complete - no production changes yet

### Phase 1: Configuration and Logging Infrastructure (Weeks 3-4)
**Goal**: Replace configuration management and logging with new implementations while keeping existing interfaces.

**Activities**:
1. **New Configuration System**
   - Implement `infrastructure/config/` with:
     - Layered configuration loading (defaults → files → env → secrets)
     - Schema validation using jsonschema
     - Hot-reload capability
     - Secure secret handling
   - Create `core/ports/config.py` interface
   - Implement `infrastructure/config/` adapter

2. **New Logging System**
   - Implement `infrastructure/logging/` with:
     - Structured JSON logging
     - Correlation ID support
     - Contextual logging (trade_id, symbol, strategy)
     - Multiple output handlers (file, console, external)
   - Replace ad-hoc logging throughout codebase

3. **Adapter Pattern for Existing Systems**
   - Create compatibility layer that allows new systems to work with old interfaces
   - Gradually migrate modules to use new configuration/logging

4. **Feature Toggle for New Systems**
   - Add config flags to enable new configuration/logging systems
   - Default to old systems for safety

**Deliverables**:
- New configuration and logging systems implemented
- Optional toggles to switch between old/new systems
- All existing tests still pass
- Migration path established for modules

### Phase 2: Core Domain Extraction - State Management (Weeks 5-6)
**Goal**: Extract state management functionality into clean domain with clear interfaces.

**Activities**:
1. **Identify State Management Code**
   - Locate all state-related code in `index_app/index_trader.py` and other modules
   - Identify state persistence mechanisms (trader_state.json, various .db files)
   - Find state restoration logic (reconcile_on_startup, load_state, save_state)

2. **Create State Domain**
   - Define state domain model in `core/domains/state/`:
     - Aggregates: TradingState, SessionState, RiskState
     - Value Objects: Position, Order, Signal, Trade
     - Events: StateChanged, ConfigurationChanged
   - Create state management services:
     - StateManager (application service)
     - StatePersistence (domain service)
     - RecoveryEngine (domain service)

3. **Create Persistence Ports**
   - Define `core/ports/persistence.py` with methods like:
     - save_state(state)
     - load_state() -> state
     - save_trade(trade)
     - get_recent_trades(limit)
     - save_position(position)
     - get_open_positions() -> [positions]

4. **Implement Adapters**
   - Create SQLite persistence adapter in `infrastructure/adapters/persistence/sqlite/`
   - Create file-based adapter as alternative
   - Implement port interfaces using existing database/file code

5. **Migration Strategy**
   - Keep existing state files functional
   - New state system writes to new location/format
   - Read from both locations during transition (prefer new, fallback to old)
   - Gradual cutover as confidence increases

**Deliverables**:
- Clean state management domain implemented
- Persistence ports and adapters created
- Dual-write/read capability for migration
- Existing state functionality preserved
- New tests for state domain

### Phase 3: Risk Management Domain (Weeks 7-8)
**Goal**: Extract risk management logic into clean domain with well-defined interfaces.

**Activities**:
1. **Identify Risk Management Code**
   - Locate risk-related code in:
     - `core/risk_engine.py`
     - Risk checks in `index_app/index_trader.py` (pre-trade validation)
     - Position sizing logic scattered throughout
     - Drawdown checks, loss limits, etc.

2. **Create Risk Domain**
   - Define risk domain model in `core/domains/risk/`:
     - Aggregates: RiskLimits, PortfolioRisk, TradeRisk
     - Value Objects: Exposure, Volatility, Drawdown
     - Enums: RiskLevel, RiskAction
   - Create risk management services:
     - RiskValidator (validates trades against limits)
     - PositionSizingEngine (calculates appropriate sizes)
     - PortfolioRiskMonitor (tracks overall portfolio risk)
     - DrawdownProtector (enforces drawdown limits)
     - CorrelationMonitor (tracks cross-position correlations)

3. **Create Risk Ports**
   - Define `core/ports/risk.py` interface (if needed as separate port)
   - Or integrate risk validation into execution/trading flow interfaces

4. **Implement Adapters**
   - Create adapters that wrap existing risk logic:
     - ExistingRiskEngineAdapter (wraps current risk_engine.py)
     - NewPureRiskEngine (clean implementation)
   - Allow switching between them via configuration

5. **Integration Points**
   - Modify signal validation to use new risk validation
   - Update position sizing calls to use new engine
   - Maintain existing behavior through adapter pattern

**Deliverables**:
- Clean risk management domain implemented
- Dual implementations (legacy wrapper + clean version)
- Migration toggles to switch between implementations
- All risk-related tests passing
- Improved testability of risk logic

### Phase 4: Signal Generation and Strategy Domain (Weeks 9-12)
**Goal**: Extract signal generation and strategy logic into clean domains.

**Activities**:
1. **Identify Signal Generation Code**
   - Locate signal-related code in:
     - `core/signal_engine.py`
     - `core/feature_engine.py`
     - `core/pure_index_signal.py`
     - `core/adaptive_signal.py`
     - Signal generation in `index_app/index_trader.py`

2. **Create Strategy and Signal Engine Domains**
   - **Strategy Domain** (`core/domains/strategy/`):
     - Trading strategies as domain services
     - Strategy selection logic
     - Strategy parameters and configuration
   - **Signal Engine Domain** (`core/domains/signal_engine/`):
     - Signal processing pipeline
     - Technical indicator calculations
     - ML signal integration
     - Signal validation and scoring
     - Regime detection and filtering

3. **Create Relevant Ports**
   - Define `core/ports/market_data.py` for market data access
   - Define `core/ports/ml_model.py` for ML integration
   - These will be implemented in later phases

4. **Implement Adapters**
   - Create adapters that wrap existing signal logic:
     - ExistingSignalEngineAdapter (wraps current signal processing)
     - NewCleanSignalEngine (progressive implementation)
   - Allow gradual replacement of signal components

5. **ML Integration**
   - Keep existing ML classifier functional
   - Create clean ML domain that can wrap or replace existing implementation
   - Implement `core/ports/ml_model.py` interface
   - Create adapters for LightGBM, scikit-learn, etc.

**Deliverables**:
- Clean strategy and signal engine domains implemented
- Market data and ML model ports defined
- Adapter implementations for existing signal logic
- Progressive enhancement capability
- Signal generation tests passing
- ML integration maintained

### Phase 5: Execution and Broker Gateway (Weeks 13-14)
**Goal**: Extract execution logic and create clean broker abstraction.

**Activities**:
1. **Identify Execution Code**
   - Locate execution-related code in:
     - `core/adapters/broker_adapters.py`
     - Order management in `index_app/index_trader.py`
     - Execution engines, fill reconciliation
     - Position tracking and updates

2. **Create Execution Domain**
   - Define execution domain model in `core/domains/execution/`:
     - Aggregates: Order, Position, Trade, Fill
     - Value Objects: Price, Quantity, Symbol, Exchange
     - Enums: OrderType, OrderSide, OrderStatus, PositionSide
   - Create execution services:
     - OrderManager (manages order lifecycle)
     - PositionManager (tracks positions)
     - FillReconciler (matches expected/actual fills)
     - SlippageMonitor (tracks execution quality)

3. **Create Broker Ports**
   - Define `core/ports/broker.py` with methods like:
     - connect(credentials) -> connection
     - disconnect()
     - place_order(order) -> order_id
     - cancel_order(order_id)
     - modify_order(order_id, modifications)
     - get_order_status(order_id) -> status
     - get_positions() -> [positions]
     - get_quote(symbol) -> quote
     - subscribe_to_market_data(symbols, callback)
     - unsubscribe_from_market_data(symbols)

4. **Implement Broker Adapters**
   - Create clean adapter implementations:
     - KiteBrokerAdapter (infrastructure/adapters/brokers/kite/)
     - AngelBrokerAdapter (infrastructure/adapters/brokers/angel/)
     - PaperBrokerAdapter (infrastructure/adapters/brokers/paper/)
   - Each implements the BrokerPort interface
   - Wrap existing broker_adapters.py code in adapters initially

5. **Migration Strategy**
   - Keep existing broker_adapters.py functional
   - New adapters can be enabled via configuration
   - Gradual cutover as confidence increases
   - Maintain paper trading/live trading distinction

**Deliverables**:
- Clean execution domain implemented
- Broker port interface defined
- Clean broker adapter implementations
- Dual broker systems (legacy + new)
- Execution tests passing
- Paper trading preserved

### Phase 6: Portfolio and Analytics Domain (Weeks 15-16)
**Goal**: Extract portfolio management and analytics into clean domains.

**Activities**:
1. **Identify Portfolio and Analytics Code**
   - Locate portfolio-related code in:
     - Position tracking in `index_app/index_trader.py`
     - P&L calculation logic scattered throughout
     - Trade journal implementation
     - Analytics modules (signal_autopsy, monte_carlo, etc.)
     - Report generation code

2. **Create Portfolio Domain**
   - Define portfolio domain model in `core/domains/portfolio/`:
     - Aggregates: Portfolio, Position, Trade, PerformanceSnapshot
     - Value Objects: Money, Return, SharpeRatio, Drawdown
     - Services: PositionSizer, PnlCalculator, TradeJournal, PerformanceAnalyzer

3. **Create Analytics Domain**
   - Define analytics capabilities:
     - SignalAutopsy: Signal performance analysis
     - MonteCarlo: Portfolio simulation
     - SensitivityAnalysis: Parameter sensitivity
     - PerformanceAttribution: P&L decomposition
     - RiskMetrics: VaR, CVaR, volatility, etc.

4. **Create Relevant Ports**
   - Ensure persistence port covers portfolio/trade storage needs
   - Notification port for alerts and reports
   - Consider metrics port for analytics data export

5. **Implement Adapters**
   - Create adapters wrapping existing analytics code:
     - ExistingAnalyticsAdapter (wraps signal_autopsy.py, monte_carlo.py, etc.)
     - NewCleanAnalyticsModules (progressive implementation)
   - Wrap existing report generator
   - Wrap existing trade journal and position tracking

**Deliverables**:
- Clean portfolio domain implemented
- Clean analytics domain with modular capabilities
- Adapter implementations for existing analytics
- Report generation preserved
- Trade journal and position tracking maintained
- Analytics tests passing

### Phase 7: Session and Market Data Infrastructure (Weeks 17-18)
**Goal**: Extract session management and improve market data handling.

**Activities**:
1. **Identify Session and Market Data Code**
   - Locate session-related code in:
     - Market hours logic in `index_app/index_trader.py`
     - Holiday calendars
     - Session classification (pre-market, open, lunch, close)
     - Timing and scheduling logic
   - Locate market data code in:
     - Market data fetching in various modules
     - Data caching and validation
     - Error handling and retries

2. **Create Session Domain**
   - Define session domain model in `core/domains/session/`:
     - Aggregates: TradingSession, MarketHours, HolidayCalendar
     - Value Objects: TimeWindow, Schedule, Countdown
     - Services: SessionDetector, TradingWindowEnforcer, ScheduleManager

3. **Improve Market Data Handling**
   - Create `core/domains/market_data/` if needed (or use existing signal_engine)
   - Focus on:
     - Data validation and cleaning
     - Freshness checking and staleness detection
     - Error handling and recovery
     - Rate limiting and backoff
     - WebSocket connection management

4. **Create Market Data Ports**
   - Refine `core/ports/market_data.py` based on needs
   - Implement adapters:
     - YahooFinanceAdapter
     - NseWebSocketAdapter
     - PolygonIoAdapter (for future expansion)
     - CSVFileAdapter (for testing/historical data)

5. **Integration**
   - Replace direct market data calls with port-based access
   - Update session timing to use new session domain
   - Maintain existing behavior through adapters

**Deliverables**:
- Clean session domain implemented
- Improved market data handling with validation and error recovery
- Market data port implementations
- Session management tests passing
- Market data adapter tests passing

### Phase 8: Notification and External Integration (Weeks 19-20)
**Goal**: Extract notification systems and external integrations.

**Activities**:
1. **Identify Notification Code**
   - Locate notification-related code in:
     - `core/telegram_engine.py`
     - `core/telegram_queue.py`
     - Notification calls scattered throughout `index_app/index_trader.py`
     - Dashboard notification systems

2. **Create Notification Domain**
   - Define notification domain model:
     - Notification types (alert, signal, trade, error, report)
     - Priority levels (critical, high, normal, low)
     - Delivery channels (Telegram, email, SMS, webhook, dashboard)

3. **Create Notification Port**
   - Define `core/ports/notification.py` with methods like:
     - send_notification(notification)
     - send_alert(alert)
     - send_trade_notification(trade)
     - send_signal_notification(signal)
     - send_error_notification(error)

4. **Implement Notification Adapters**
   - Create adapter implementations:
     - TelegramNotificationAdapter (wraps existing telegram_engine.py)
     - EmailNotificationAdapter
     - DashboardNotificationAdapter (for web dashboard)
     - WebhookNotificationAdapter
     - LogNotificationAdapter (for development/testing)

5. **External Systems Integration**
   - Web dashboard: Create clean interface in `infrastructure/web/`
   - CLI: Extract to `presentation/cli/`
   - GUI: Extract to `presentation/gui/` (Tkinter)
   - Consider API layer in `presentation/api/`

**Deliverables**:
- Clean notification domain implemented
- Notification port interface defined
- Multiple notification channel adapters
- External system interfaces cleaned up
- Notification tests passing
- Dashboard, CLI, GUI maintained through adapters

### Phase 9: Presentation Layers and External APIs (Weeks 21-22)
**Goal**: Extract and clean up presentation layers while maintaining existing interfaces.

**Activities**:
1. **CLI Layer**
   - Extract argument parsing and command handling to `presentation/cli/`
   - Create clean CLI application using argparse or click
   - Map CLI commands to application service use cases
   - Maintain backward compatibility with existing command-line interface

2. **GUI Layer**
   - Extract Tkinter GUI code to `presentation/gui/`
   - Create clean MVC or MVVM architecture
   - Decouple GUI from trading logic using observer/publish-subscribe
   - Maintain exact same GUI appearance and behavior
   - Ensure headless operation still works (GUI optional)

3. **Web Dashboard/API Layer**
   - Extract web server code to `infrastructure/web/` and `presentation/api/`
   - Create clean REST/WebSocket API
   - Map endpoints to application service use cases
   - Maintain backward compatibility with existing endpoints
   - Add proper authentication, rate limiting, input validation

4. **Dependency Injection Container**
   - Implement or integrate a DI container (could be simple or use framework like dependency-injector)
   - Wire up all components:
     - Domain services
     - Infrastructure adapters
     - Presentation layers
   - Allow easy swapping of implementations
   - Facilitate testing with mock objects

5. **Configuration Migration**
   - Migrate from old configuration system to new one
   - Remove dual-write/read complexity
   - Update all modules to use new configuration port
   - Remove old configuration code

**Deliverables**:
- Clean CLI, GUI, and web presentation layers
- Dependency injection container wiring all components
- Backward compatibility maintained for all external interfaces
- All existing tests still pass
- New clean architecture fully operational

### Phase 10: Testing, Validation, and Cutover (Weeks 23-24)
**Goal**: Comprehensive testing, validation, and production cutover.

**Activities**:
1. **Comprehensive Testing**
   - Run full existing test suite (should still pass)
   - Add unit tests for new domain logic
   - Add integration tests for adapter implementations
   - Add end-to-end tests for critical workflows
   - Perform exploratory testing for edge cases

2. **Performance Validation**
   - Benchmark critical paths (signal generation, order execution)
   - Compare performance with original implementation
   - Optimize where necessary
   - Ensure latency requirements are met

3. **Security Review**
   - Conduct security audit of new implementation
   - Verify secret handling, input validation, output encoding
   - Check for vulnerabilities in new code
   - Validate authentication and authorization mechanisms

4. **Production Cutover Preparation**
   - Create deployment scripts for new architecture
   - Create rollback procedures
   - Prepare monitoring and alerting for new system
   - Create runbooks for operations team

5. **Gradual Cutover Strategy**
   - Deploy new system alongside old (canary deployment)
   - Route small percentage of traffic to new system
   - Monitor metrics, errors, and business outcomes
   - Gradually increase traffic to new system
   - Have rollback plan ready at all times

6. **Final Cutover**
   - Once confidence is high, route 100% of traffic to new system
   - Monitor closely for any issues
   - Have rollback plan available for 24-48 hours post-cutover
   - Decommission old system after stabilization period

**Deliverables**:
- Comprehensive test suite passing
- Performance benchmarks met or exceeded
- Security review completed and passed
- Production deployment procedures created
- Successful cutover to new architecture
- Rollback procedures tested and ready
- Legacy system decommissioned after successful transition

## Risk Mitigation Strategies

### 1. Data Loss Prevention
- **Strategy**: Dual-write during migration, read from both sources with fallback
- **Validation**: Regular consistency checks between old and new data stores
- **Backup**: Frequent automated backups of all state and databases

### 2. Behavioral Changes Prevention
- **Strategy**: Characterization tests for complex logic before refactoring
- **Validation**: Side-by-side testing of old vs new implementations
- **Approval**: Business stakeholder sign-off on critical behavior preservation

### 3. Performance Degradation Prevention
- **Strategy**: Performance benchmarks established before changes
- **Validation**: Regular performance testing during migration
- **Optimization**: Profiling and optimization of critical paths

### 4. Team Knowledge Transfer Prevention
- **Strategy**: Pair programming during migration
- **Documentation**: Update documentation as components are migrated
- **Training**: Knowledge sharing sessions for team members

### 5. Schedule Slippage Prevention
- **Strategy**: Time-boxed phases with clear exit criteria
- **Validation**: Definition of done for each phase includes tested, working code
- **Adjustment**: Ability to extend phases based on learned velocity

## Success Criteria

### Technical Success Criteria
1. All existing tests pass after each phase
2. New unit test coverage > 80% for new domain logic
3. Performance of critical paths within 10% of original
4. Zero security vulnerabilities introduced
5. Clean architecture principles verified through code reviews

### Business Success Criteria
1. Zero data loss during migration
2. Zero disruption to existing users/clients
3. All existing functionality preserved
4. Improved system observability and monitoring
5. Reduced mean time to recovery from failures
6. Improved developer velocity for future features

### Operational Success Criteria
1. Successful deployment and rollback procedures tested
2. Comprehensive monitoring and alerting in place
3. Clear runbooks for common operational scenarios
4. Improved logging and debugging capabilities
5. Reduced operational burden through better design

## Rollback Plan

At any phase, if critical issues are found:
1. **Immediate Rollback**: Redirect traffic back to previous stable version
2. **Data Synchronization**: Ensure any new data written is backfilled to old system
3. **Investigation**: Root cause analysis of issues
4. **Fix and Retry**: Address issues and retry migration when ready
5. **Escalation Path**: Clear escalation procedures for severe issues

Each phase should have a defined rollback procedure tested before implementation.

## Conclusion

This phased migration plan provides a low-risk path to transform the monolithic trading platform into a clean, modular architecture. By following the strangler fig pattern, maintaining backward compatibility, and delivering incremental value, we can refactor the system while keeping it fully operational throughout the process.

The plan emphasizes testing, validation, and risk mitigation at each step, ensuring that the final architecture is not only cleaner and more maintainable but also more reliable and observable than the original system.

Successful execution of this plan will result in a production-grade trading platform that is easier to maintain, test, extend, and operate while preserving all existing functionality and business value.