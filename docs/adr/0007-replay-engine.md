# ADR 0007: Replay Engine for Incident Debugging

## Status
Accepted

## Date
2026-05-16

## Context
Debugging trading incidents required expensive live market replay, with no way to reproduce exact conditions.

## Decision
Implemented replay engine with:
- Tick-by-tick historical session replay
- Uses production logic unchanged
- ASCII bar-chart visualization in terminal
- Web endpoint for visual replay
- Supports replay of any closed trade

## Consequences
- Perfect incident reproduction
- Strategy debugging without production risk
- Regression testing capability
- Performance analysis under historical conditions
- Added `core/trade_replayer.py` module