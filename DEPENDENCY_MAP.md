# Dependency Map: NSE Index Options Trading Platform

## Overview
This document maps the dependencies between modules in the current NSE index options trading platform. It identifies:
- Internal module dependencies
- External library dependencies
- Circular dependencies
- Data flow patterns
- Coupling hotspots

## 1. External Dependencies

### Core Runtime Dependencies
```
Core (required by all scripts):
├── jsonschema>=4.20
├── requests>=2.31.0
├── yfinance>=0.2.36
├── pandas>=2.0.0
└── numpy>=1.24.0

Dashboard server:
├── flask>=3.0.0
└── flask-socketio>=5.3.0

Phase 5 — ML Signal Classifier:
├── lightgbm>=4.0.0
└── scikit-learn>=1.3.0

Phase 6 — PDF Report Generator:
└── reportlab>=4.0.0

v2.44 Item 12 — News Sentinel:
└── feedparser>=6.0.0

v2.44 Item 20 — A/B Strategy Tester:
└── scipy>=1.11.0 (optional)

v2.45 Item 19 — Prometheus metrics export:
└── prometheus-client>=0.20.0 (optional)

Live broker execution (optional):
├── kiteconnect>=5.0.0
└── pyotp>=2.9.0
```

### Development/Test Dependencies (requirements-dev.txt)
```
├── pytest>=7.0.0
├── typeguard>=4.0.0
├── pytest-mock>=3.0.0
├── pytest-cov>=4.0.0
├── Hypothesis>=6.0.0
├── factories>=3.0.0
├── freezegun>=1.0.0
├── responses>=0.20.0
├── Faker>=15.0.0
├── black>=22.0.0
├── flake8>=5.0.0
├── mypy>=0.9.0
├── bandit>=1.7.0
└── safety>=2.0.0
```

## 2. Internal Module Dependencies

### Key Files and Their Dependencies

#### Entry Points
- `INDEX_OPTION_BUYING_APP_1.0.py` → `import index_app.index_trader` (simple launcher)
- `launcher.py` → GUI wrapper
- `dashboard_server.py` → Flask web dashboard
- `run_backtest.py` → Backtesting engine
- `run_analysis.py` → Analysis/simulation
- `index_app/index_trader.py` → Main trading logic (21K+ lines)

#### Core Modules (analysis of key dependencies)

##### `core/adapters/broker_adapters.py`
Dependencies:
- Standard library: importlib, importlib.util, sys, threading, time, dataclasses, pathlib, typing
- Internal: core.config_helpers, core.shared_config_validate
- External (conditional): kiteconnect, pyotp (only if broker driver is KITE/ANGEL)

##### `core/config_bootstrap.py`
Dependencies:
- Standard library: json, os, time, collections, dataclasses, pathlib, typing
- Internal: core.config_helpers
- External: None

##### `core/config_helpers.py`
Dependencies:
- Standard library: json, os, base64, typing, pathlib, collections
- External: None

##### `core/risk_engine.py`
Dependencies:
- Standard library: dataclasses, typing, callable
- External: None

##### `core/ml_classifier.py`
Dependencies:
- Standard library: json, os, time, typing, pathlib, collections
- External: lightgbm, scikit-learn, numpy, pandas
- Internal: core.config_helpers, core.shared_config_validate, core.ml_performance_tracker

##### `core/signal_engine.py`
Dependencies:
- Standard library: typing, collections, dataclasses, datetime
- External: pandas, numpy, yfinance, requests, scipy (optional)
- Internal: core.feature_engine, core.pure_index_signal, core.session_classifier, core.iv_rank, core.ml_classifier

##### `core/feature_engine.py`
Dependencies:
- Standard library: math, statistics, typing, collections
- External: pandas, numpy
- Internal: core.pure_index_signal, core.session_classifier, core.iv_rank, core.vix_calculator

##### `core/pure_index_signal.py`
Dependencies:
- Standard library: typing, collections
- External: pandas, numpy, ta (technical analysis library - check if used)
- Internal: None (pure calculations)

##### `core/session_classifier.py`
Dependencies:
- Standard library: datetime, typing
- External: pandas
- Internal: None

##### `core/iv_rank.py`
Dependencies:
- Standard library: typing, collections
- External: pandas, numpy, yfinance (for VIX data)
- Internal: None

##### `core/ml_performance_tracker.py`
Dependencies:
- Standard library: json, os, time, typing, collections, datetime
- External: sqlite3, numpy, sklearn.metrics
- Internal: None

##### `core/concept_drift_detector.py`
Dependencies:
- Standard library: json, os, time, typing, collections
- External: scipy, scipy.stats, numpy, pandas
- Internal: core.ml_performance_tracker

##### `core/oi_snapshot_store.py`
Dependencies:
- Standard library: sqlite3, threading, time, typing, collections
- External: None
- Internal: None

##### `core/monte_carlo.py`
Dependencies:
- Standard library: random, typing, math, collections
- External: numpy
- Internal: None

##### `core/signal_autopsy.py`
Dependencies:
- Standard library: json, os, time, typing, collections, datetime
- External: sqlite3, pandas, numpy
- Internal: None

##### `core/spread_strategy.py`
Dependencies:
- Standard library: typing, dataclasses
- External: None
- Internal: core.strike_selector

##### `core/walkforward_engine.py`
Dependencies:
- Standard library: json, os, time, typing, collections
- External: None
- Internal: core.backtest_engine

##### `core/web_dashboard.py`
Dependencies:
- Standard library: json, os, time, typing, collections, threading
- External: flask, flask-socketio
- Internal: Multiple core modules for data

##### `core/report_generator.py`
Dependencies:
- Standard library: json, os, time, typing, collections, datetime
- External: reportlab, pandas, numpy
- Internal: Multiple core modules for data

##### `core/config_bootstrap.py` (already covered)
Dependencies:
- Standard library: json, os, time, collections, dataclasses, pathlib, typing
- Internal: core.config_helpers
- External: None

##### `core/shared_config_validate.py`
Dependencies:
- Standard library: typing, collections, re
- External: None
- Internal: core.config_helpers

##### `core/adaptive_signal.py`
Dependencies:
- Standard library: typing, collections
- External: None
- Internal: core.pure_index_signal, core.session_classifier, core.ml_classifier, core.iv_rank

##### `core/strike_selector.py`
Dependencies:
- Standard library: typing, math, collections
- External: None (may use scipy.stats for distributions)
- Internal: core.pure_index_signal, core.session_classifier

##### `core/fii_dii_tracker.py`
Dependencies:
- Standard library: typing, collections
- External: requests, pandas (for fetching FII/DII data)
- Internal: None

##### `core/implied_move.py`
Dependencies:
- Standard library: typing, math, collections
- External: None (Black-Scholes calculations)
- Internal: None

##### `core/gex_analyzer.py`
Dependencies:
- Standard library: typing, math, collections
- External: None (Black-Scholes gamma calculations)
- Internal: None

##### `core/regime_transition_detector.py`
Dependencies:
- Standard library: typing, collections
- External: None
- Internal: core.pure_index_signal

##### `core/kelly_sizer.py`
Dependencies:
- Standard library: json, os, typing, collections
- External: None
- Internal: None

##### `core/var_calculator.py`
Dependencies:
- Standard library: typing, math, collections
- External: None (parametric VaR calculations)
- Internal: None

##### `core/stress_tester.py`
Dependencies:
- Standard library: typing, collections
- External: None
- Internal: None

##### `core/scalein_manager.py`
Dependencies:
- Standard library: typing, collections
- External: None
- Internal: None

##### `core/straddle_strategy.py`
Dependencies:
- Standard library: typing, collections
- External: None
- Internal: core.strike_selector

##### `core/iron_condor_strategy.py`
Dependencies:
- Standard library: typing, collections
- External: None
- Internal: core.strike_selector

##### `core/limit_order_engine.py`
Dependencies:
- Standard library: typing, math, collections
- External: None
- Internal: None

##### `core/pnl_attribution.py`
Dependencies:
- Standard library: typing, collections
- External: pandas, numpy
- Internal: None

##### `core/slippage_model.py`
Dependencies:
- Standard library: typing, collections
- External: sklearn.linear_model, numpy, scipy.stats
- Internal: core.trade_journal

##### `core/underlying_analyzer.py`
Dependencies:
- Standard library: typing, collections
- External: yfinance, pandas
- Internal: None

##### `core/nlp_journal.py`
Dependencies:
- Standard library: json, os, time, typing, collections
- External: anthropic (Claude API)
- Internal: core.trade_journal

##### `core/param_optimizer.py`
Dependencies:
- Standard library: json, os, time, typing, collections
- External: None
- Internal: Multiple core modules for objective functions

##### `core/metrics_exporter.py`
Dependencies:
- Standard library: typing, collections
- External: prometheus_client
- Internal: Multiple core modules for data collection

##### `core/broker_failover.py`
Dependencies:
- Standard library: typing, collections, threading, time
- External: None
- Internal: core.adapters.broker_adapters

#### Main Trading Logic (`index_app/index_trader.py`)
This is the central hub with dependencies on:
- Nearly all core modules (direct imports or through other modules)
- GUI components (tkinter, conditional)
- Configuration system
- Database modules
- Notification systems
- Execution engines

Key internal dependencies:
- core.feature_engine
- core.ml_exit_classifier
- core.opbuying_observability
- core.adapters.broker_adapters
- core.risk_engine
- core.signal_engine
- core.portfolio_hedge
- core.manual_signal
- core.regime_transition_detector
- core.liquidity_guard
-.core.reentry_evaluator
- core.intraday_performance_monitor
- core.benchmark
- core.news_sentinel
- core.telegram_queue
- core.trade_replayer
- core.sensitivity_analyzer
- core.health_checker
- core.live_readiness_checker
- core.ab_strategy_tester
- core.fii_dii_tracker
- core.implied_move
- core.gex_analyzer
- core.regime_transition_detector
- core.kelly_sizer
- core.var_calculator
- core.stress_tester
- core.scalein_manager
- core.straddle_strategy
- core.iron_condor_strategy
- core.limit_order_engine
- core.pnl_attribution
- core.slippage_model
- core.underlying_analyzer
- core.nlp_journal
- core.param_optimizer
- core.metrics_exporter
- core.config_bootstrap
- core.shared_config_validate
- core.config_helpers

#### GUI-Specific Files
- `index_app/index_trader.py` (lines with GUI code)
- `templates/` directory (HTML templates for web dashboard)
- `launcher.py` (Tkinter launcher)

## 3. Circular Dependencies and Coupling Issues

### Potential Circular Dependencies
1. **Core ↔ Main Trading Script**: Many core modules import from or are imported by `index_app/index_trader.py`, creating tight coupling
2. **Config System**: Configuration modules are used throughout but may also depend on core functionality
3. **ML Modules**: ML classifier may depend on feature engine which may depend on ML outputs

### High-Coupling Modules (God Objects)
1. `index_app/index_trader.py` - Central hub with ~21K lines, depends on almost everything
2. `core/adapters/broker_adapters.py` - Central broker interface used throughout
3. `core/config_bootstrap.py` - Used by nearly all modules for configuration access
4. `core/signal_engine.py` - Central signal processing hub

### Data Flow Anti-Patterns
1. **Global State**: Heavy use of global `S` object in `index_trader.py` for state sharing
2. **Direct Database Access**: Multiple modules directly access SQLite databases without abstraction
3. **Tight GUI Coupling**: Trading logic mixed with GUI update calls
4. **Event Bus Missing**: No clear event-driven architecture; direct method calls prevalent

## 4. Layer Violations

### Presentation Layer Leaks into Domain
- GUI-related code in `index_trader.py` (tkinter imports, GUI update functions)
- Web dashboard concerns leaking into core modules

### Infrastructure Concerns in Domain
- Direct file I/O in domain modules
- Direct database connections in business logic
- Network calls in trading logic modules

### Domain Logic in Infrastructure
- Trading rules embedded in configuration validation
- Risk calculation logic in broker adapters
- Signal filtering in persistence layers

## 5. Dependency Hotspots (Most Depended Upon)

### Top 10 Most Imported Modules
1. `core.config_bootstrap` - Used by nearly every module for configuration access
2. `core.config_helpers` - Used for configuration processing and secret decoding
3. `core.shared_config_validate` - Used for configuration validation
4. `pandas` - Used throughout for data manipulation
5. `numpy` - Used throughout for numerical computations
6. `core.signal_engine` - Used for signal generation and processing
7. `core.risk_engine` - Used for risk validation and position sizing
8. `core.adapters.broker_adapters` - Used for broker interactions
9. `core.feature_engine` - Used for feature creation
10. `core.ml_classifier` - Used for ML signal enhancement

## 6. Recommendations for Dependency Improvement

### Immediate Actions
1. **Extract Configuration Interface**: Create a clear configuration port that decouples modules from config implementation
2. **Create Core Ports**: Define interfaces for external dependencies (brokers, market data, persistence)
3. **Reduce Main Script Dependencies**: Break up `index_app/index_trader.py` into smaller, focused modules
4. **Implement Dependency Injection**: Allow modules to receive dependencies rather than importing them directly
5. **Create Clear Boundaries**: Establish presentation, application, domain, and infrastructure layers

### Medium-Term Improvements
1. **Event-Driven Architecture**: Implement an internal event bus for loose coupling between components
2. **Service Locator Pattern**: For accessing shared services without tight coupling
3. **Plugin Architecture**: Allow features to be added/removed without core modifications
4. **Circuit Breakers**: For external dependencies to prevent cascade failures

### Long-Term Goals
1. **Hexagonal Architecture**: Complete separation of concerns with clear ports and adapters
2. **Domain-Driven Design**: Clear bounded contexts for trading, risk, portfolio, etc.
3. **Test Doubles Strategy**: Easy mocking of external dependencies for comprehensive testing
4. **Independent Deployability**: Ability to deploy and scale components independently

## 7. Visual Dependency Summary

```
EXTERNAL DEPENDENCIES
├── Data Sources: yfinance, NSE API, WebSocket feeds
├── Broker APIs: Kite Connect, Angel Broking
├── ML Frameworks: LightGBM, scikit-learn
├── Web Framework: Flask, Flask-SocketIO
├── Database: SQLite
├── Notification: Telegram Bot API
├── Reporting: ReportLab
├── Utilities: pandas, numpy, scipy, etc.
└── Configuration: JSON files, Environment Variables

INTERNAL MODULES (SIMPLIFIED)
ENTRY POINTS
├── index_app/index_trader.py (MAIN HUB)
├── launcher.py (GUI)
├── dashboard_server.py (WEB)
├── run_backtest.py, run_analysis.py (UTILITIES)

DOMAIN LOGIC (CORE/)
├── Strategy: signal_engine, feature_engine, pure_index_signal
├── ML: ml_classifier, ml_performance_tracker, concept_drift_detector
├── Risk: risk_engine, kelly_sizer, var_calculator
├── Execution: broker_adapters, limit_order_engine
├── Portfolio: position tracking, pnl_attribution
├── State: state management, recovery systems
├── Session: market hours, session classification
├── Analytics: signal_autopsy, monte_carlo, sensitivity_analyzer
├── Utilities: config_bootstrap, config_helpers, shared_config_validate
├── Notifications: telegram_engine, telegram_queue
├── Specialized: fii_dii_tracker, implied_move, gex_analyzer, etc.

PRESENTATION
├── GUI: Tkinter components in index_trader.py
├── Web: dashboard_server.py, web_dashboard.py
└── CLI: argparsers in various scripts
```