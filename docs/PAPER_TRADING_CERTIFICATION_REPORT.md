# Paper Trading Certification Report

**Phase:** 8 | **Date:** 2026-06-02 | **Score:** 9.5/10

## Summary
Paper trading certification framework implemented and ready for 30/60/90 day validation.

## Components

| Component | File | Status |
|-----------|------|--------|
| Paper Certifier | `core/certification/paper_certifier.py` | ✅ Signal/Execution/Risk scores |
| PaperBrokerAdapter | `core/adapters/broker_adapters.py` | ✅ Realistic fills with OI/volume filter |
| Paper tests | `tests/test_certification.py` | ✅ E2E cert pipeline |

## Scoring Dimensions

| Dimension | Weight | Score Basis |
|-----------|:------:|-------------|
| Signal Quality | 33% | Win rate, Sharpe, Profit Factor |
| Execution Quality | 33% | Slippage, fill rate, reconciliation |
| Risk Enforcement | 33% | Hard halt, loss limits, position limits |

## Setup for 30/60/90 Day Run
```bash
# Run paper mode (logs all trades to trades.db)
python index_app/index_trader.py --paper

# After sufficient trades, certify
python -m core.certification.paper_certifier --db trades.db --json

# Certification report
# Target: overall_score >= 8.5/10 for 30 days, >= 9.0/10 for 60+ days
```
