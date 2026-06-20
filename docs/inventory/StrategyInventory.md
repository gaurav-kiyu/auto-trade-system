# Strategy Inventory

Generated: 2026-06-20

## Strategy Modules
- core/strategy/strategies.py - Strategy definitions
- core/strategy/plugin_framework.py - Plugin system
- core/strategy/orchestrator.py - Orchestration
- core/strategy/sandbox.py - Sandbox testing
- core/strategy/strategy_versioning.py - Version management
- core/adaptive_signal.py - Signal scoring pipeline
- core/pure_index_signal.py - Base signal generation
- core/spread_strategy.py - Debit spread engine
- core/straddle_strategy.py - Straddle/Strangle engine
- core/iron_condor_strategy.py - Iron Condor engine
- core/scalein_manager.py - Scale-in entries

## Strategy Registry
- Plugin framework supports multiple strategy types
- Sandbox for offline replay
- Versioning with migration support
- A/B testing via ab_strategy_tester