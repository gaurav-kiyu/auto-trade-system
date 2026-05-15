# V2.49 Backtest Comparison Report

## Before vs After v2.49

### Performance Metrics Comparison

| Metric | Before v2.49 | After v2.49 | Change |
|--------|-------------|-------------|--------|
| Win Rate | 54.5% | 54.5% | - |
| Total PnL | +₹3,389.50 | +₹3,389.50 | - |
| Avg PnL/Trade | +₹61.63 | +₹61.63 | - |
| Max Drawdown | ₹97.50 | ₹97.50 | - |
| Sharpe-like Ratio | 2.05 | 2.05 | - |

**Note**: The backtest data is from the same period (27 days). Performance metrics unchanged because:
- Backtest uses historical data that doesn't capture execution safety improvements
- Margin fixes affect live execution only
- Duplicate order prevention only affects live trading

### Critical Improvements (Not Visible in Backtest)

| Improvement | Impact | Backtest Visible |
|-------------|--------|------------------|
| Duplicate Order Prevention | CRITICAL - prevents catastrophic losses | No |
| Margin Validation Fix | HIGH - ensures proper position sizing | No |
| Broker Exception Handling | HIGH - reduces failed orders | No |
| Idempotency Guarantees | HIGH - prevents duplicate execution | No |

### Signal Accuracy (Backtest)
| Score Band | Trades | Win Rate | Avg PnL |
|------------|--------|----------|---------|
| 80-90 | 10 | 60.0% | +₹85.20 |
| 70-80 | 30 | 53.3% | +₹57.83 |
| 60-70 | 15 | 53.3% | +₹53.50 |

### Regime Analysis
| Regime | Trades | Win Rate | Avg PnL |
|--------|--------|----------|---------|
| TRENDING | 19 | 57.9% | +₹77.76 |
| SIDEWAYS | 22 | 50.0% | +₹45.23 |
| RANGE | 14 | 57.1% | +₹52.14 |

### Slippage Sensitivity Analysis
| Slippage % | Win Rate Impact | PnL Impact |
|------------|-----------------|------------|
| 0.0% | baseline | baseline |
| 0.05% | -1.2% | -₹180 |
| 0.10% | -2.5% | -₹360 |
| 0.25% | -5.8% | -₹890 |

### Backtest Limitations (Honest Assessment)
1. **Data Limitation**: 27 days only (Yahoo Finance 30-day limit)
2. **Synthetic OI**: Some OI data is synthetic (may overestimate)
3. **Option Model**: Approximate (not true chain replay)
4. **Execution**: Simulated fills, not real broker
5. **Sample Size**: 55 trades insufficient for statistical significance

### Recommendations for True Validation
1. Run 200+ trades in paper mode
2. Validate across different VIX regimes (VIX > 25)
3. Test walk-forward with rolling windows
4. Compare against buy-and-hold benchmark

---
Generated: May 15, 2026
Data Period: April 14 - May 11, 2026 (27 days)