# ML Signal Classifier

**Module:** `core/ml_classifier.py`

LightGBM binary win/loss predictor. Trains a gradient-boosted classifier on the
trade journal to estimate each signal's probability of being a winner. The
predicted probability is converted to a bounded score adjustment applied inside
the adaptive signal pipeline, just before tier classification.

## Feature Set (14 features)

| Feature | Type | Description |
|---------|------|-------------|
| `score` | float | Raw signal score |
| `confidence` | float | Signal confidence (0-1) |
| `direction_call` | binary | 1=CALL, 0=PUT |
| `is_strong` | binary | Tier == STRONG |
| `is_moderate` | binary | Tier == MODERATE |
| `is_weak` | binary | Tier == WEAK |
| `has_soft_blocks` | binary | Any soft blocks logged |
| `day_of_week` | int | 0=Mon ... 4=Fri |
| `hour_of_entry` | int | 9 ... 15 |
| `iv_rank` | float | IV rank 0-100 |
| `vix` | float | India VIX |
| `pcr` | float | Put-Call Ratio |
| `regime_code` | float | 0=CHOPPY, 1=NEUTRAL, 2=TRENDING |
| `session_code` | float | 0=OPEN, 1=MID, 2=LATE, 3=CLOSE |

## Score Adjustment

| Probability | Adjustment | Description |
|------------|-----------|-------------|
| ≥ 0.65 | +1 to +10 | Model confident signal is a winner |
| 0.40–0.65 | 0 | Neutral |
| ≤ 0.40 | -1 to -10 | Model doubts signal |

## SHAP Explainability

When optional `shap` package is installed, per-feature SHAP values are computed
for each prediction. Top-3 contributing features are included in signal logging.
Falls back to normalised `feature_importances_` when SHAP is unavailable.

## Drift Detection

The classifier supports drift-triggered retraining:
- **PSI drift detection** on top-5 features
- **Feature importance trend** monitoring over N recent predictions
- Auto-retrains when drift exceeds configurable threshold

## Config Keys

See `index_config.defaults.json` for `ml_classifier_enabled`, `ml_min_trades_to_train`,
`ml_model_path`, `ml_score_adj_cap`, `ml_high_prob_threshold`, `ml_low_prob_threshold`,
`ml_retrain_interval_hours`, `drift_retrain_*` keys.

## Dependencies

- `lightgbm` (required for training/prediction)
- `shap` (optional — for SHAP explainability)
- `pandas` (dataframe for prediction)
- `scikit-learn` (train/test split)
- `core/concept_drift_detector.py` — PSI + KS drift detection
- `core/ml_performance_tracker.py` — prediction calibration tracking
