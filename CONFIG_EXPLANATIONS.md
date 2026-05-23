# Configuration Key Explanations

This document explains the magic numbers and critical values in `index_config.defaults.json`.

## Risk Parameters

| Key | Default | Explanation |
|-----|---------|-------------|
| BASE_CAPITAL | 5000 | Starting capital in ₹ (₹5,000 for small live testing) |
| MAX_DAILY_LOSS | -2000 | Hard stop: stop trading if daily P&L drops below -₹2,000 |
| MAX_DRAWDOWN | 0.3 | Maximum drawdown threshold (30%) before circuit breaker |
| RISK_PER_TRADE | 0.03 | Risk 3% of capital per trade (conservative) |
| MAX_LOT_CAPITAL_PCT | 0.85 | Use max 85% of capital for position sizing |

## Mandate Parameters (v2.49 - Actually Enforced)

| Key | Default | Explanation |
|-----|---------|-------------|
| MANDATE_RISK_PER_TRADE | 0.015 | Risk per trade: 1.5% (NOT 2% or 3%) - primary safety |
| MANDATE_DAILY_HARD_STOP | 0.025 | Daily hard stop: 2.5% of capital |
| MANDATE_WEEKLY_CIRCUIT_BREAKER | 0.05 | Weekly circuit: 5% loss → 0.75× sizing |
| MANDATE_MAX_DRAWDOWN_PROTECTION | 0.12 | Max drawdown protection: 12% |
| MANDATE_LOSS_STREAK_COOLDOWN_HOURS | 2 | Loss streak cooldown: 2 hours after 3 losses |

## Signal Thresholds

| Key | Default | Explanation |
|-----|---------|-------------|
| MANDATE_MIN_SCORE_TRENDING | 68 | Minimum score for trending regime |
| MANDATE_MIN_SCORE_SIDEWAYS | 73 | Minimum score for sideways regime |
| MANDATE_MIN_SCORE_RANGE | 78 | Minimum score for range regime |
| MANDATE_MIN_IV_RANK | 0.20 | Minimum IV Rank (20%) to avoid low volatility |
| MANDATE_VIX_MIN | 12.0 | VIX must be at least 12 (low vol warning) |
| MANDATE_VIX_MAX | 28.0 | VIX should be below 28 (high vol warning) |
| MANDATE_VIX_HARD_BLOCK | 30.0 | Hard block if VIX exceeds 30 |

## Position Sizing Multipliers

| Key | Default | Explanation |
|-----|---------|-------------|
| MANDATE_REGIME_SIZING_TRENDING | 1.2 | In trending: use 120% of base size |
| MANDATE_REGIME_SIZING_SIDEWAYS | 0.85 | In sideways: use 85% of base size |
| MANDATE_REGIME_SIZING_RANGE | 0.75 | In range: use 75% of base size |

## Trade Limits

| Key | Default | Explanation |
|-----|---------|-------------|
| MAX_OPEN | 1 | Maximum concurrent positions |
| MAX_TRADES_DAY | 3 | Maximum trades per day |
| MANDATE_LOSS_STREAK_THRESHOLD | 3 | After 3 consecutive losses: cooldown |
| MANDATE_MAX_POSITIONS_SAME_TIME | 2 | Max 2 positions across all indices |

## Time Windows (IST)

| Key | Default | Explanation |
|-----|---------|-------------|
| MANDATE_TIME_WINDOW_MORNING_START | 09:20 | Morning session starts at 9:20 AM |
| MANDATE_TIME_WINDOW_MORNING_END | 11:30 | Morning session ends at 11:30 AM |
| MANDATE_TIME_WINDOW_AFTERNOON_START | 13:00 | Afternoon session starts at 1:00 PM |
| MANDATE_TIME_WINDOW_AFTERNOON_END | 14:45 | Afternoon session ends at 2:45 PM |
| MANDATE_SKIP_FIRST_20_MINUTES | true | Skip first 20 min of market (spread widen) |
| MANDATE_SKIP_LAST_45_MINUTES | true | Skip last 45 min (unstable close) |

## Execution Parameters

| Key | Default | Explanation |
|-----|---------|-------------|
| SL_PCT | 0.012 | Stop loss: 1.2% of entry price |
| TARGET_PCT | 0.02 | Take profit: 2% of entry price (1.67:1 R:R) |
| TRAIL_PCT | 0.008 | Trailing stop: 0.8% |
| SLIPPAGE_PCT | 0.005 | Expected slippage: 0.5% per trade |

## Liquidity Guards

| Key | Default | Explanation |
|-----|---------|-------------|
| MIN_OI_THRESHOLD | 500 | Minimum Open Interest for trade eligibility |
| MIN_VOLUME_THRESHOLD | 100 | Minimum daily volume for trade eligibility |
| MAX_SPREAD_PCT | 0.02 | Maximum bid-ask spread: 2% of premium |
| MIN_PREMIUM | 5.0 | Minimum option premium: ₹5 (avoid illiquid deep OTM) |

## Model Parameters

| Key | Default | Explanation |
|-----|---------|-------------|
| OPTION_PREMIUM_DELTA | 0.45 | ATM delta approximation (empirically calibrated) |
| OPTION_PREMIUM_DELTA_SCALE | 1.5 | Premium scaling factor for NSE options |
| ATR_MULT_SL | 1.2 | ATR multiplier for stop loss |
| ATR_MULT_TARGET | 1.618 | ATR multiplier for take profit (Fibonacci) |

## Walk-Forward Parameters

| Key | Default | Explanation |
|-----|---------|-------------|
| WALKFORWARD_TRAIN_BARS | 500 | Training window: 500 bars (~8 hours) |
| WALKFORWARD_TEST_BARS | 100 | Test window: 100 bars (~1.5 hours) |
| WALKFORWARD_DRIFT_THRESHOLD_PCT | 20 | 20% drift triggers retrain warning |
| WALKFORWARD_MIN_CONFIDENCE | 0.80 | 80% statistical confidence required |

## Retry & Safety

| Key | Default | Explanation |
|-----|---------|-------------|
| EXECUTION_RETRIES | 3 | Number of retry attempts (legacy - now single attempt) |
| EXECUTION_TIMEOUT_SECONDS | 30 | Order timeout before ambiguity handling |
| BROKER_FAILOVER_THRESHOLD | 3 | Failover after 3 consecutive broker errors |
| BROKER_FAILOVER_RECOVERY_MINS | 15 | Recovery attempt after 15 minutes |

---
Updated: May 15, 2026 (v2.53)