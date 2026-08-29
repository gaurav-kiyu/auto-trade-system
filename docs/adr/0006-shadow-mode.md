# ADR 0006: Shadow Mode for Safe Feature Rollout

## Status
Accepted

## Date
2026-05-16

## Context
Enabling new strategy logic in production was risky with no way to validate behavior before actual trading.

## Decision
Implemented shadow mode with:
- System computes signals but does not trade
- Parallel execution: live strategy + shadow strategy
- Comparison of decisions: expected vs live behavior
- Shadow database for tracking hypothetical trades

## Consequences
- Safe validation of new logic before production
- A/B testing capability without financial risk
- Regression testing against historical data
- Confidence building for new strategies
- Added `core/execution/shadow_mode.py` module