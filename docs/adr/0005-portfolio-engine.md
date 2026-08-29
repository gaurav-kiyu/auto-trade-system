# ADR 0005: Portfolio Engine for Multi-Strategy Tracking

## Status
Accepted

## Date
2026-05-16

## Context
System lacked centralized portfolio-level visibility when trading multiple strategies, leading to siloed risk management.

## Decision
Implemented centralized portfolio engine with:
- Real-time position aggregation across all strategies
- Exposure tracking per strategy and asset class
- Margin utilization monitoring
- Correlation-aware capital allocation
- Portfolio snapshot generation for reporting

## Consequences
- Unified view of all strategy positions
- Better risk management at portfolio level
- Dynamic capital reallocation based on performance
- Correlation-based exposure limits
- Added `core/portfolio/portfolio_engine.py` module