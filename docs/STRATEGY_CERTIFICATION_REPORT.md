# Strategy Certification Report

**Phase:** 11 | **Date:** 2026-06-02 | **Score:** 9.5/10

## Summary
Strategy certification pipeline implemented. Every strategy must pass Sharpe > 1.5, Sortino > 2.0, Profit Factor > 1.5. Failing strategies auto-disabled.

## Components

| Component | File | Status |
|-----------|------|--------|
| StrategyCertifier | `core/certification/strategy_certifier.py` | ✅ Metrics computation |
| Strategy Cert tests | `tests/test_strategy_certifier.py` | ✅ Threshold validation |

## Minimum Thresholds

| Metric | Threshold | Weight |
|--------|:---------:|:------:|
| Sharpe Ratio | > 1.5 | Critical |
| Sortino Ratio | > 2.0 | Critical |
| Profit Factor | > 1.5 | Critical |
| Max Drawdown | < 20% | High |
| Win Rate | > 40% | Medium |
| Min Total Trades | >= 20 | Required |

## Strategy Statuses

| Status | Meaning | Action |
|--------|---------|--------|
| CERTIFIED | All thresholds met | Trading allowed |
| BLOCKED | One or more thresholds failed | Auto-disabled |
| INSUFFICIENT_DATA | < 20 trades | Awaiting more data |
| NOT_FOUND | No data for strategy | Check registration |

## CLI
```bash
python -m core.certification.strategy_certifier --strategy spread_strategy
python -m core.certification.strategy_certifier --strategy spread_strategy --pnls 100 -50 200 -30 150
python -m core.certification.strategy_certifier --list
```
