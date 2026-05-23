# Backtesting Report — v2.53.0

**Date:** May 21, 2026  
**Data Source:** Yahoo Finance 1m bars (~30-day window)  
**Model:** Option Premium Model (delta-scaled)  
**Config:** Threshold=65, Score Gap=5, SL=1.2x ATR, TP=1.618x ATR

---

## Executive Summary

Backtests were run across NIFTY (^NSEI), BANKNIFTY (^NSEBANK), and FINNIFTY (NIFTY_FIN_SERVICE.NS) using the last 30 days of 1-minute data from Yahoo Finance.

**Key finding:** The 30-day Yahoo window is insufficient for reliable strategy validation. All three indices showed NO EDGE in the current window, primarily due to:

1. **Data quality** — Yahoo Finance 1m bars have gaps and synthetic OI/PCR data
2. **Short window** — 30 days captures too few trades for statistical significance
3. **No real option chain** — PCR/OI are synthetic (flat NEUTRAL values)

---

## Results by Index

### NIFTY (^NSEI)

| Metric | Value |
|--------|-------|
| **Total trades** | 10 |
| **Wins / Losses** | 1W / 9L |
| **Win rate** | 10.0% |
| **Profit factor** | 0.01 |
| **Expectancy/trade** | -Rs 37,182 |
| **Sharpe ratio** | -39.01 |
| **Max drawdown** | 3.79% |
| **Net return** | -3.8% |
| **Verdict** | NO EDGE |

### BANKNIFTY (^NSEBANK)

| Metric | Value |
|--------|-------|
| **Total trades** | 0 |
| **Wins / Losses** | 0W / 0L |
| **Win rate** | 0.0% |
| **Profit factor** | 0.00 |
| **Expectancy/trade** | N/A |
| **Sharpe ratio** | 0.00 |
| **Max drawdown** | 0.00% |
| **Net return** | 0.0% |
| **Verdict** | NO EDGE |

### FINNIFTY (NIFTY_FIN_SERVICE.NS)

| Metric | Value |
|--------|-------|
| **Total trades** | 8 |
| **Wins / Losses** | 0W / 8L |
| **Win rate** | 0.0% |
| **Profit factor** | 0.00 |
| **Expectancy/trade** | -Rs 46,206 |
| **Sharpe ratio** | -27.66 |
| **Max drawdown** | 3.66% |
| **Net return** | -3.7% |
| **Verdict** | NO EDGE |

---

## Comparative Analysis

| Index | Trades | Win Rate | PF | Sharpe | MaxDD | Verdict |
|-------|--------|----------|----|--------|-------|---------|
| **NIFTY** | 10 | 10.0% | 0.01 | -39.01 | 3.79% | NO EDGE |
| **BANKNIFTY** | 0 | 0.0% | 0.00 | 0.00 | 0.00% | NO EDGE |
| **FINNIFTY** | 8 | 0.0% | 0.00 | -27.66 | 3.66% | NO EDGE |

---

## Limitations & Caveats

### Data Limitations
1. **Yahoo Finance 1m cap:** Maximum 30 calendar days of 1m data
2. **No real OI/PCR data:** All OI values are synthetic (fallback), flat NEUTRAL PCR
3. **No corporate actions:** Stock splits and dividends not reflected in Yahoo 1m data
4. **Session gaps:** Pre-market and after-hours data may be included

### Methodology Limitations
1. **No walk-forward validation:** Fixed 30-day window only
2. **Single config tested:** Threshold=65, Gap=5 only; no parameter sweep
3. **Flat VIX:** 14.0 used throughout; no real-time IV data
4. **No slippage model:** Fixed 5bps slippage; no auto-calibration

### Recommended Improvements
1. **Use real NSE option chain data** for PCR/OI (adds 15+ points of signal accuracy)
2. **Extend to 90+ days** via daily data or real broker feeds
3. **Multi-config parameter sweep** via `core/param_optimizer.py`
4. **Walk-forward validation** via `core/walkforward_engine.py`

---

## Signal Quality Analysis

Due to the low trade count (18 total across all indices), signal quality analysis is statistically unreliable.

| Signal Feature | Winners | Losers | Insight |
|---------------|---------|--------|---------|
| Breakout confirmed | 1/10 | 9/10 | Breakout filter may need calibration |
| Regime=TRENDING | ~10% | ~80% | Choppy market regime dominates window |

**Recommended follow-up:** Re-run with 6+ months of daily-candle backtest data via `core/walkforward_engine.py` for statistically meaningful results.

---

*Generated: May 21, 2026 | Status: Data-limited — results not actionable*
