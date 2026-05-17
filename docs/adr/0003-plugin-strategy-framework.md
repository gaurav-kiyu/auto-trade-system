# ADR 0003: Plugin Strategy Framework

## Status
Accepted

## Date
2026-05-16

## Context
Strategy logic was hardwired into the main trading system, making it difficult to experiment with different strategies or scale to multiple strategies.

## Decision
Implemented a clean plugin strategy framework with well-defined interfaces:
- Base `Strategy` class with lifecycle hooks: `on_market_data()`, `generate_signal()`, `on_fill()`, `on_risk_update()`
- Strategy registry for discovering and loading strategies
- Version tracking for each strategy instance
- Config hash for reproducible strategy configuration

## Consequences
- Easier experimentation with new strategies
- Multi-strategy scaling capability
- Cleaner separation of concerns
- Strategy versioning and rollback capability
- Added `core/strategy/plugin_framework.py` module