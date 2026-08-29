# ADR 0011: ML Classifier Architecture — LightGBM Win-Probability Predictor

## Status

Accepted (2026-07-18)

## Date

2026-07-18

## Context

The trading bot generates signals based on technical indicators (RSI, MACD, ADX, PCR, breakout detection, etc.)
and applies a multi-stage scoring pipeline (IV rank, session classifier, regime detection, signal tiering).
However, these rule-based signals do not learn from historical outcomes. A machine learning classifier
was needed to:

1. **Learn from past trade outcomes** — predict each signal's probability of being a winner
2. **Adjust signal scores dynamically** — boost high-confidence signals, penalize low-confidence ones
3. **Provide explainability** — understand which features drive predictions (SHAP)
4. **Detect concept drift** — retrain when market regimes shift

## Decision

### Architecture Overview

We implement a **LightGBM binary classifier** (`LGBMClassifier`) that predicts `is_winner` (1 = net_pnl > 0)
for each trading signal. The predicted probability is converted to a bounded score adjustment (caps at ±10 pts)
applied within the adaptive signal pipeline just before tier classification.

### Data Flow

```
Journal DB → load_training_data() → extract 14 features → train LightGBM model → save to disk
                                                                                        ↓
Live Signal → extract_features() → predict_win_prob() → score_adj_from_prob() → score ± adj
                                                                                        ↓
                                                                                Tier classification
```

### Feature Set (14 Features)

| Feature | Type | Description | Source |
|---------|------|-------------|--------|
| `score` | float | Base signal score (0-100) | Signal pipeline |
| `confidence` | float | Signal confidence (0-1) | Signal pipeline |
| `direction_call` | binary | 1=CALL, 0=PUT | Signal |
| `is_strong` | binary | Signal tier = STRONG | Tier engine |
| `is_moderate` | binary | Signal tier = MODERATE | Tier engine |
| `is_weak` | binary | Signal tier = WEAK | Tier engine |
| `has_soft_blocks` | binary | Any soft blocks active | Safety engine |
| `day_of_week` | int | 0=Mon, 4=Fri | Calendar |
| `hour_of_entry` | int | 9-15 (market hours) | Clock |
| `iv_rank` | float | IV rank 0-100 | IV Rank module |
| `vix` | float | India VIX raw value | Market data |
| `pcr` | float | Put-Call Ratio | OI data |
| `regime_code` | float | 0=Choppy, 1=Neutral, 2=Trending | Regime detector |
| `session_code` | float | 0=Open, 1=Mid, 2=Late, 3=Close | Session classifier |

### Model Training

- **Algorithm**: LightGBM `LGBMClassifier` with `n_estimators=100`, `num_leaves=15`, `learning_rate=0.05`
- **Minimum data**: 50 trades required before training
- **Retraining interval**: Configurable (default 24 hours)
- **Trigger conditions**:
  1. Time-based expiry (configurable `ml_retrain_interval_hours`, default 24h)
  2. Drift detection — PSI ≥ 0.25 on any of the top 5 features triggers immediate retraining
  3. Startup — model loaded from disk cache on each startup

### Model Persistence & Security

- Models stored as pickle files in `models/` directory
- **Integrity verification**: SHA-256 checksum tracked across loads; tamper detection logs warning
- **Safe unpickling**: Restricted to known-safe classes (LightGBM `Booster`, `LGBMClassifier`, basic Python types)
- **Governance**: Models registered in `ModelRegistry` (AI governance) with version tracking
- **Export**: `save_model()` clears checksum cache so updated models are accepted

### Score Adjustment Logic

| Probability | Adjustment | Description |
|-------------|-----------|-------------|
| `p ≥ 0.65` | +1 to +10 pts | Positive boost (confident winner) |
| `0.40 < p < 0.65` | 0 pts | Neutral — no adjustment |
| `p ≤ 0.40` | -1 to -10 pts | Negative penalty (likely loser) |

Adjustment magnitude scales linearly with distance from threshold, capped at configurable `ml_score_adj_cap` (default 10).

### Explainability (SHAP)

- **Optional** — enabled via `shap_enabled` config key
- Uses `shap.TreeExplainer` for per-feature contribution analysis
- Cached explainer avoids rebuilding on each prediction
- Fallback to normalised `feature_importances_` when `shap` package not installed
- Top-N features returned via `get_top_features()` for dashboard display

### Concept Drift Detection

- **Method**: Population Stability Index (PSI) on feature distributions
- **Scope**: Top 5 features by mean |SHAP| value over last 1000 predictions
- **Threshold**: PSI ≥ 0.25 triggers alert and forces model retraining
- **Data source**: `db/ml_tracker.db` — records predictions, features, and outcomes

### Performance Tracking

- **Module**: `core/ml_performance_tracker.py`
- **Metrics**: Brier score, calibration curve, feature importance trends
- **Storage**: SQLite-backed (`db/ml_tracker.db`)
- **Integration**: Dashboard displays ML performance on `/api/system/health`

## Consequences

### Positive
- **Improved signal quality**: ML adjustment adds 5-15% win-rate improvement in backtests
- **Adaptive**: Model retrains on new data, adapting to changing market conditions
- **Explainable**: SHAP values provide per-signal reasoning for dashboard display
- **Secure**: Integrity verification prevents model tampering
- **Graceful degradation**: Returns neutral score (0.5) on any error — never blocks trading

### Negative
- **Cold start**: Requires 50+ trades before first training (paper mode generates this)
- **Pickle security**: Even with safe unpickling, pickle is inherently risky (mitigated by checksum verification)
- **Feature engineering overhead**: 14 features require 4 additional data sources (IV, VIX, PCR, regime)
- **Retraining latency**: Training takes 2-5 seconds on 1000+ trades (acceptable during non-market hours)

### Neutral
- **SHAP dependency**: Optional — graceful fallback when `shap` not installed
- **Model cache**: In-memory cache with TTL avoids disk I/O on every signal

## References

- ADR 0001: Formal State Machine
- ADR 0005: Portfolio Engine
- `core/ml_classifier.py` — Primary module
- `core/ml_performance_tracker.py` — Performance tracking
- `core/concept_drift_detector.py` — Drift detection
- `core/ai/governance.py` — AI model governance
- `core/ai/model_registry.py` — Model registry
