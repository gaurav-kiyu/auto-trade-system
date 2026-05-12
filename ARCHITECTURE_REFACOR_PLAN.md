# OPB_FINAL_MT Monolith Refactor Architecture Plan

## Executive Summary

This document outlines a comprehensive refactor plan to transform the monolithic STOCK_OPTION_BUYING_APP_1.0.py (~29K lines) into a modular, maintainable, and scalable trading system while preserving all existing functionality and safety guarantees.

## Current State Analysis

The current system exhibits:
- **God Object**: STOCK_OPTION_BUYING_APP_1.0.py contains mixed concerns (configuration, state management, signal generation, execution, risk management, notifications, persistence)
- **Tight Coupling**: Hundreds of functions directly access global variables (_CFG, S, positions, etc.)
- **Hidden Dependencies**: Implicit global state affects function behavior unpredictably
- **Scalability Limitations**: Single process architecture with fixed thread pools and SQLite bottleneck
- **Complex Locking Hierarchy**: Multiple locks (_state_lock, _pos_lock, _history_lock, etc.) creating deadlock risks

## Target Architecture

### High-Level Module Structure

```
trading_system/
├── core/                    # Fundamental infrastructure
│   ├── config/              # Configuration management
│   ├── logging/             # Structured logging
│   ├── datetime/            # IST timezone handling
│   └── exceptions/          # Custom exceptions
├── services/                # Business logic services
│   ├── state/               # Trading state management
│   ├── signal/              # Signal generation pipeline
│   ├── execution/           # Order execution & capital management
│   ├── risk/                # Risk calculation & enforcement
│   ├── notification/        # Telegram/logging/fallback handling
│   └── persistence/         # Database/JSON/CSV operations
├── adapters/                # External system integrations
│   ├── broker/              # Broker abstraction layer
│   ├── data/                # Market data providers (Yahoo Finance, NSE)
│   └── external/            # Other external services
├── api/                     # Internal & external APIs
│   ├── dashboard/           # Console/dashboard output
│   ├── metrics/             # Prometheus metrics exporter
│   └── rest/                # REST API (if needed)
├── orchestrator/            # Main trading orchestration
│   ├── engine.py            # Main trading loop
│   ├── scheduler/           # Task scheduling
│   └── workers/             # Background workers
└── shared/                  # Shared utilities & constants
    ├── models/              # Data models & DTOs
    ├── utils/               # Utility functions
    └── constants/           # System constants
```

### Detailed Component Responsibilities

#### 1. Core Infrastructure (`trading_system/core`)
- **Configuration Service**: Immutable configuration objects with validation
- **Logging Service**: Structured logging with JSON and file outputs
- **Datetime Service**: IST timezone handling eliminating `datetime.now()` usage
- **Exception Hierarchy**: Custom exceptions for different error categories

#### 2. Business Logic Services (`trading_system/services`)
- **State Service**: Thread-safe trading state management (capital, PnL, trade counts)
- **Signal Service**: 
  - FeatureEngine (technical indicators)
  - SignalProcessor (filtering, scoring, caching)
  - AdaptiveLearning (threshold adjustments)
- **Execution Service**:
  - OrderManager (placement, cancellation, status verification)
  - CapitalManager (reservation, allocation)
  - BrokerGateway (broker abstraction)
- **Risk Service**:
  - PositionSizer (volatility-adjusted, drawdown-scaled sizing)
  - RiskEvaluator (pre-trade, intra-trade checks)
  - CircuitBreaker (API failure protection)
- **Notification Service**:
  - TelegramDispatcher (rate limiting, fallback, critical patterns)
  - AlertFormatter (message templates)
  - FallbackLogger (file logging when Telegram fails)
- **Persistence Service**:
  - TradeRepository (SQLite operations)
  - StateRepository (JSON state persistence)
  - CSVLogger (human-readable trade logging)

#### 3. Adapters (`trading_system/adapters`)
- **Broker Adapter**: Abstract interface with PaperBrokerAdapter, Kite/Angel implementations
- **Data Adapter**: Unified market data interface (Yahoo Finance, NSE)
- **External Adapter**: Third-party service integrations (if any)

#### 4. API Layer (`trading_system/api`)
- **Dashboard API**: Console output and web dashboard endpoints
- **Metrics API**: Prometheus metrics export
- **Internal API**: Service-to-service communication interfaces

#### 5. Orchestrator (`trading_system/orchestrator`)
- **Trading Engine**: Main orchestration loop coordinating all services
- **Scheduler**: Background task scheduling (reconciliation, heartbeat, etc.)
- **Worker Pool**: Managed background workers for non-blocking operations

#### 6. Shared Components (`trading_system/shared`)
- **Data Models**: Pydantic dataclasses for type safety
- **Utilities**: Helper functions used across modules
- **Constants**: System-wide constants and enums

## Refactor Strategy

### Phase 1: Foundation Services (Low Risk)
1. Extract Configuration Service
2. Extract Logging Service  
3. Extract Datetime Service
4. Extract Exception Hierarchy
5. Create shared models and constants

### Phase 2: Isolated Services (Medium Risk)
1. Extract FeatureEngine (already well-separated)
2. Extract Notification Service
3. Extract Persistence Service
4. Extract Broker Adapter layer

### Phase 3: Core Business Logic (High Risk)
1. Extract State Service (most coupled component)
2. Extract Risk Service
3. Extract Execution Service
4. Extract Signal Service

### Phase 4: Orchestration & Integration
1. Create Trading Engine orchestrator
2. Implement dependency injection
3. Replace global state with service injection
4. Update main entry point

### Phase 5: Validation & Testing
1. Ensure all existing tests pass
2. Add integration tests for service boundaries
3. Validate configuration-driven behavior preservation
4. Performance benchmarking

## Dependency Injection Pattern

### Service Interfaces
```python
# Example: State Service Interface
class IStateService(ABC):
    @abstractmethod
    def get_capital(self) -> float: ...
    @abstractmethod
    def update_capital(self, amount: float) -> None: ...
    @abstractmethod
    def get_positions(self) -> Dict[str, Position]: ...
    @abstractmethod
    def update_position(self, symbol: str, position: Position) -> None: ...
    # ... other state operations
```

### Service Locator / Container
```python
# Services are instantiated once and injected where needed
class ServiceContainer:
    def __init__(self):
        self.config_service = ConfigService()
        self.logging_service = LoggingService()
        self.state_service = StateService()
        # ... other services
    
    def get_state_service(self) -> IStateService:
        return self.state_service
```

### Constructor Injection
```python
class SignalProcessor:
    def __init__(
        self, 
        feature_engine: IFeatureEngine,
        state_service: IStateService,
        config_service: IConfigService
    ):
        self.feature_engine = feature_engine
        self.state_service = state_service
        self.config_service = config_service
```

## Migration Approach

### Strangler Fig Pattern
1. Keep existing monolith running
2. Extract services one by one
3. Route calls to new services via facade/adapters
4. Eventually decompose the monolith completely

### Backward Compatibility Measures
1. Maintain existing public APIs where possible
2. Preserve configuration file formats
3. Keep command-line interface unchanged
4. Preserve all existing behavior and safety mechanisms

## Risk Mitigation

### 1. Gradual Extraction
- Extract one service at a time
- Run both old and new implementations in parallel
- Compare outputs to ensure behavioral equivalence

### 2. Comprehensive Testing
- Unit tests for each extracted service
- Integration tests for service interactions
- End-to-end tests preserving existing test suite
- Property-based testing for critical algorithms

### 3. Configuration Preservation
- Maintain exact same configuration loading logic
- Preserve all config keys and defaults
- Keep environment variable override mechanism
- Maintain soft-reload functionality

### 4. Safety Mechanism Preservation
- Keep all risk limits and circuit breakers
- Preserve hard halt and kill switch functionality
- Maintain paper/live trading mode separation
- Preserve all validation and sanity checks

## Expected Benefits

### 1. Improved Maintainability
- Smaller, focused modules (~500-2000 lines each)
- Clear separation of concerns
- Reduced cognitive overhead for developers
- Easier to locate and fix bugs

### 2. Enhanced Testability
- Each service can be tested in isolation
- Mock dependencies for focused testing
- Clear test boundaries
- Reduced test setup complexity

### 3. Better Scalability
- Services can be scaled independently
- Opportunity to introduce async/await patterns
- Potential for distributed deployment
- Reduced lock contention

### 4. Improved Observability
- Structured logging throughout
- Clear metrics boundaries per service
- Easier to trace requests across services
- Better monitoring and alerting capabilities

### 5. Reduced Coupling
- Explicit dependencies via constructor injection
- Interface-based programming
- Easier to swap implementations
- Reduced risk of unintended side effects

## Implementation Guidelines

### 1. Service Design Principles
- Single Responsibility Principle
- Dependency Inversion Principle
- Interface Segregation Principle
- Immutable data transfer between services
- Fail-fast validation at service boundaries

### 2. Coding Standards
- Type hints on all public functions
- Comprehensive docstrings for public APIs
- Consistent error handling patterns
- Avoid global state in services
- Prefer composition over inheritance

### 3. Concurrency Approach
- Thread-safe services using appropriate locking
- Consider async/await for I/O-bound operations
- Bounded queues for producer-consumer patterns
- Avoid shared mutable state between services

### 4. Error Handling
- Service-specific exception types
- Clear error propagation strategies
- Circuit breaker patterns for external dependencies
- Graceful degradation where appropriate

## Success Criteria

### 1. Functional Equivalence
- All existing tests pass
- Identical behavior for same inputs/configuration
- Preserved safety mechanisms and limits
- Same command-line interface and outputs

### 2. Structural Improvements
- No service exceeds 2000 lines
- Clear separation of concerns
- Minimal global state (only in infrastructure layer)
- Explicit dependencies via injection

### 3. Quality Metrics
- Test coverage >80% for new services
- Cyclomatic complexity <15 for most functions
- Duplication <5% across services
- Dependency graph shows clear layering

### 4. Non-Functional Requirements
- Startup time within 10% of original
- Memory usage within 15% of original
- Latency for critical path within 10% of original
- Throughput maintained or improved

## Next Steps

1. Begin Phase 1: Extract foundation services (config, logging, datetime, exceptions)
2. Create service interfaces and base implementations
3. Update monolith to use extracted services via adapter pattern
4. Verify all existing tests still pass
5. Proceed to Phase 2: Extract isolated services (notification, persistence, broker)
6. Continue iterative extraction until full refactor complete

This architecture plan provides a roadmap for transforming the monolithic trading system into a maintainable, scalable, and production-grade platform while preserving all existing functionality and safety guarantees.