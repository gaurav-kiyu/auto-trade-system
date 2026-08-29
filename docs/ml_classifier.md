# `core/ml_classifier.py` — ML Signal Classifier (Phase 5)

## What it does

Trains a LightGBM binary classifier on the trade journal to estimate each
signal's probability of being a winner. The predicted probability is
converted to a bounded score adjustment (`score_adj_from_prob()`) applied
inside `core/adaptive_signal.py`'s pipeline, just before final tier
classification.

Related, deeper architecture writeup: `docs/adr/0011-ml-classifier-architecture.md`.

## Feature set (14 features, all available from the journal at training time)

`score`, `confidence`, `direction_call`, `is_strong`, `is_moderate`,
`is_weak`, `has_soft_blocks`, `day_of_week` (0=Mon), `hour_of_entry`,
`iv_rank` (0-100, low = cheap premiums, favorable for option buying),
`vix` (India VIX raw value), `pcr` (Put-Call Ratio; >1.2 bullish, <0.8
bearish), `regime_code` (0=CHOPPY/1=NEUTRAL/2=TRENDING), `session_code`
(0=OPEN 9-10h/1=MID 10-13h/2=LATE 13-14h/3=CLOSE 14h+).

Target label: `is_winner` (1 if `net_pnl > 0`, else 0).

Existing 9-feature models still load and predict safely — `predict_win_prob()`
returns `0.5` (neutral) on a feature-count mismatch rather than raising.
Retrain with new data to activate the full 14-feature set.

## Key config keys (all optional, safe defaults)

`ml_classifier_enabled` (`true`), `ml_min_trades_to_train` (50),
`ml_model_path` (`"models/signal_classifier.pkl"`), `ml_score_adj_cap` (10),
`ml_high_prob_threshold` (0.65), `ml_low_prob_threshold` (0.40),
`ml_retrain_interval_hours` (24.0), plus drift-to-retrain keys
(`drift_retrain_enabled`, `drift_retrain_psi_threshold`, ...). See
`json/index_config.defaults.json` for the authoritative current values.

## Explainability

`explain_prediction()`/`get_top_features()`/`shap_to_json()` provide SHAP-
based explainability, surfaced through `core/ml_performance_tracker.py` and
the dashboard's ML status views.

## Concept drift

`core/concept_drift_detector.py` runs PSI + KS drift detection against
`db/ml_tracker.db` and can trigger retraining — see that module and the
`drift_retrain_*` config keys above. (`core.concept_drift_detector` and
`core.ml_classifier` have a deliberate lazy, function-local cross-import to
avoid a real circular dependency at module-load time — see
`core/architecture_analyzer.py`'s `_check_circular_imports()`.)

## Public API

`extract_features()`, `load_training_data()`, `train()`, `save_model()`,
`load_model()`, `predict_win_prob()`, `score_adj_from_prob()`,
`explain_prediction()`, `get_top_features()`, `get_classifier()` — see
`__all__` for the full list and the module's own docstrings for exact
signatures.

## Tests

`tests/test_ml_classifier.py`, `tests/test_concept_drift_detector.py`.
