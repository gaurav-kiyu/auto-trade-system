# Adaptive Signal Evaluator

**Module:** `core/adaptive_signal.py`

Soft-rejection wrapper around `evaluate_index_signal_partial`. Converts hard
rejections (tf_mismatch, choppy) into score penalties + confidence reduction
so the tiered system can trade partial setups at reduced position size.

## Architecture

```
Signal Request
    │
    ├─► Dual Direction Path (evaluate_dual_direction_signal)
    │      ├─ evaluates CALL + PUT concurrently
    │      ├─ applies counter-trend penalty
    │      └─ picks best direction with mean-reversion waive
    │
    └─► Fallback Path (_compute_features_and_score)
           ├─ allow_tf_mismatch=True  → soft penalty
           └─ allow_choppy=True       → soft penalty
```

## Key Classes

| Class | Purpose |
|-------|---------|
| `AdaptiveSignal` | Final signal result with tier, score, confidence, soft-blocks |
| `SignalConfidenceBand` | Wilson 95% CI for historical win rate in signal bucket |
| `TimeframeAgreement` | Agreement score across 1m/5m/15m timeframes |

## Soft-Rejection Penalties

| Condition | Score Penalty | Confidence Mult |
|-----------|--------------|-----------------|
| tf_mismatch | -20 | × 0.60 |
| choppy_regime | -15 | × 0.70 |

## Score Component Pipeline

1. **Base score** from `compute_index_score()` (VWAP, momentum, volume, RSI, PCR, smart money)
2. **MACD bonus** — histogram direction alignment (+/- 5pts)
3. **Breakout bonus** (+8 base / -4 penalty)
4. **ADX penalty** — low ADX <12 → -5pts
5. **ADX trend bonus** — high ADX ≥20 → +5pts
6. **Regime penalty** — HIGH_VOLATILITY (-8), EVENT (-10)
7. **VWAP reclaim bonus** — price reclaimed VWAP → +7pts
8. **ORB bonus** — opening range breakout → +10pts
9. **IV Rank multiplier** — scales score by IV environment
10. **IV Skew penalty** — extreme put skew → -5pts
11. **Session classifier** — time-of-day score adjustment
12. **ML classifier** — LightGBM win-prob score adjustment
13. **Optional layers** (v2.45): FII/DII, implied move, GEX, regime transition

## Config Keys

See `index_config.defaults.json` for the `ADAPTIVE_SIGNAL_*` and `*_enabled` keys.

## Dependencies

- `core/pure_index_signal.py` — base scoring functions
- `core/position_sizer.py` — position sizing from score/tier
- `core/tier_engine.py` — tier classification rules
- `core/ml_classifier.py` — LightGBM win-prob prediction (optional)
- `core/iv_rank.py` — IV rank multiplier + skew
- `core/session_classifier.py` — time-of-day session bands
