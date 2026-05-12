"""
ML Signal Classifier (Phase 5) — LightGBM binary win/loss predictor.

Trains a gradient-boosted classifier on the trade journal to estimate each
signal's probability of being a winner.  The predicted probability is
converted to a bounded score adjustment applied inside the adaptive signal
pipeline, just before tier classification.

Feature set (all available from journal at training time):
  score, confidence, direction_call, is_strong, is_moderate, is_weak,
  has_soft_blocks, day_of_week (0=Mon), hour_of_entry
  iv_rank,           # 0–100 (low IV = cheap premiums = favourable for option buying)
  vix,               # India VIX raw value
  pcr,               # Put-Call Ratio (>1.2 bullish, <0.8 bearish)
  regime_code,       # 0=CHOPPY, 1=NEUTRAL, 2=TRENDING / other
  session_code,      # 0=OPEN(9-10h), 1=MID(10-13h), 2=LATE(13-14h), 3=CLOSE(14h+)

Target: ``is_winner`` (1 = net_pnl > 0, 0 otherwise).

Config keys (all optional — safe defaults built in)
---------------------------------------------------
  ml_classifier_enabled      : bool   default true
  ml_min_trades_to_train     : int    default 50
  ml_model_path              : str    default "models/signal_classifier.pkl"
  ml_score_adj_cap           : int    default 10   (max ±pts applied to score)
  ml_high_prob_threshold     : float  default 0.65 (above → positive adj)
  ml_low_prob_threshold      : float  default 0.40 (below → negative adj)
  ml_retrain_interval_hours  : float  default 24.0
  # Drift-to-retraining configuration
  drift_retrain_enabled      : bool   default true   # Enable drift detection to trigger retraining
  drift_retrain_psi_threshold: float  default 0.25   # PSI threshold for alert (drift detected)
  drift_retrain_top_features : int    default 5      # Number of top features to check for drift
  drift_retrain_trend_count  : int    default 1000   # Number of recent predictions to use for feature importance trend
"""
from __future__ import annotations

import json
import logging
import pickle
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)

# Thread-safe model cache (guarded by _model_lock)
_model_lock: threading.Lock = threading.Lock()

# ── Feature definition ────────────────────────────────────────────────────────

FEATURE_COLS: list[str] = [
    "score",
    "confidence",
    "direction_call",    # 1 = CALL, 0 = PUT
    "is_strong",         # tier == STRONG
    "is_moderate",       # tier == MODERATE
    "is_weak",           # tier == WEAK
    "has_soft_blocks",   # 1 if any soft_blocks logged
    "day_of_week",       # 0 = Monday … 4 = Friday
    "hour_of_entry",     # 9 … 15
    # Extended features (Phase B+ — added when live values are available at signal time)
    "iv_rank",           # 0–100 (low IV = cheap premiums = favourable for option buying)
    "vix",               # India VIX raw value
    "pcr",               # Put-Call Ratio (>1.2 bullish, <0.8 bearish)
    "regime_code",       # 0=CHOPPY, 1=NEUTRAL, 2=TRENDING / other
    "session_code",      # 0=OPEN(9-10h), 1=MID(10-13h), 2=LATE(13-14h), 3=CLOSE(14h+)
]

_REGIME_CODE_MAP: dict[str, float] = {"CHOPPY": 0.0, "NEUTRAL": 1.0}


def _regime_to_code(regime: str) -> float:
    return _REGIME_CODE_MAP.get(str(regime).upper(), 2.0)


def _hour_to_session_code(hour: int) -> float:
    if hour < 10:
        return 0.0
    if hour < 13:
        return 1.0
    if hour < 14:
        return 2.0
    return 3.0

# ── In-process model cache ────────────────────────────────────────────────────

_model_cache: dict[str, Any] = {}     # {model_path: lgbm_model} — guarded by _model_lock
_model_ts:    dict[str, float] = {}   # {model_path: load_time} — guarded by _model_lock


# ── Feature extraction ────────────────────────────────────────────────────────

def extract_features(signal: dict[str, Any]) -> dict[str, float]:
    """
    Extract ML features from a live signal dict (as produced by generate_signal).

    All values are floats for compatibility with LightGBM.
    """
    import datetime as _dt

    entry_ts = signal.get("signal_ts") or signal.get("entry_ts") or 0.0
    try:
        dt = _dt.datetime.fromtimestamp(float(entry_ts))
    except (ValueError, OSError, TypeError):
        dt = _dt.datetime.now()

    tier = str(signal.get("tier") or signal.get("strength") or "").upper()
    direction = str(signal.get("direction") or signal.get("signal") or "CALL").upper()
    soft_blocks = signal.get("soft_blocks") or []
    if isinstance(soft_blocks, str):
        try:
            soft_blocks = json.loads(soft_blocks)
        except Exception:
            soft_blocks = []

    regime = str(signal.get("mkt_regime") or signal.get("regime") or "NEUTRAL")

    return {
        "score":           float(signal.get("score", 0)),
        "confidence":      float(signal.get("confidence", 0.5)),
        "direction_call":  1.0 if direction == "CALL" else 0.0,
        "is_strong":       1.0 if tier == "STRONG" else 0.0,
        "is_moderate":     1.0 if tier == "MODERATE" else 0.0,
        "is_weak":         1.0 if tier == "WEAK" else 0.0,
        "has_soft_blocks": 1.0 if soft_blocks else 0.0,
        "day_of_week":     float(dt.weekday()),
        "hour_of_entry":   float(dt.hour),
        # Extended features
        "iv_rank":         float(signal.get("iv_rank", 50.0)),
        "vix":             float(signal.get("vix", 15.0)),
        "pcr":             float(signal.get("pcr", 1.0)),
        "regime_code":     _regime_to_code(regime),
        "session_code":    _hour_to_session_code(dt.hour),
    }


# ── Training data loader ──────────────────────────────────────────────────────

def load_training_data(
    journal_path: str | Path,
) -> tuple[list[list[float]], list[int]] | None:
    """
    Load completed trades from the journal SQLite DB.

    Returns (X_rows, y_labels) where each row is ordered per FEATURE_COLS,
    or None if fewer than 1 complete trade exists.
    """
    db = Path(journal_path)
    if not db.is_file():
        return None

    # Try to load extended feature columns if the journal schema has them.
    # Falls back to a base 7-column query when those columns are absent (older DB).
    try:
        con = sqlite3.connect(str(db), check_same_thread=False)
        try:
            rows = con.execute(
                """
                SELECT score, confidence, direction, tier, soft_blocks, entry_ts, is_winner,
                       COALESCE(iv_rank, 50.0),
                       COALESCE(vix_at_entry, 15.0),
                       COALESCE(pcr_at_entry, 1.0),
                       COALESCE(regime, 'NEUTRAL')
                FROM journal
                WHERE is_winner IS NOT NULL AND actual_entry > 0
                """
            ).fetchall()
            has_extended = True
        except Exception:
            rows = con.execute(
                """
                SELECT score, confidence, direction, tier, soft_blocks,
                       entry_ts, is_winner
                FROM journal
                WHERE is_winner IS NOT NULL AND actual_entry > 0
                """
            ).fetchall()
            has_extended = False
        con.close()
    except Exception as exc:
        _log.debug("[ML] Journal read failed: %s", exc)
        return None

    if not rows:
        return None

    import datetime as _dt

    X: list[list[float]] = []
    y: list[int] = []
    for row in rows:
        if has_extended:
            score, conf, direction, tier, soft_blocks_json, entry_ts_str, is_winner, \
                iv_rank_val, vix_val, pcr_val, regime_str = row
        else:
            score, conf, direction, tier, soft_blocks_json, entry_ts_str, is_winner = row
            iv_rank_val, vix_val, pcr_val, regime_str = 50.0, 15.0, 1.0, "NEUTRAL"

        try:
            dt = _dt.datetime.fromisoformat(str(entry_ts_str))
        except Exception:
            dt = _dt.datetime.now()
        direction = str(direction or "CALL").upper()
        tier = str(tier or "").upper()
        try:
            sb = json.loads(soft_blocks_json or "[]")
        except Exception:
            sb = []

        feat_row = [
            float(score or 0),
            float(conf or 0.5),
            1.0 if direction == "CALL" else 0.0,
            1.0 if tier == "STRONG" else 0.0,
            1.0 if tier == "MODERATE" else 0.0,
            1.0 if tier == "WEAK" else 0.0,
            1.0 if sb else 0.0,
            float(dt.weekday()),
            float(dt.hour),
            float(iv_rank_val or 50.0),
            float(vix_val or 15.0),
            float(pcr_val or 1.0),
            _regime_to_code(str(regime_str or "NEUTRAL")),
            _hour_to_session_code(dt.hour),
        ]
        X.append(feat_row)
        y.append(int(is_winner or 0))
    return (X, y) if X else None


# ── Model train / save / load ─────────────────────────────────────────────────

def train(
    journal_path: str | Path,
    cfg: dict[str, Any] | None = None,
) -> Any | None:
    """
    Train a LightGBM classifier on journal data.

    Returns the fitted model or None if insufficient data or import failure.
    """
    c = cfg or {}
    min_trades = int(c.get("ml_min_trades_to_train", 50))
    data = load_training_data(journal_path)
    if data is None:
        _log.debug("[ML] No journal data — skipping training")
        return None
    X, y = data
    if len(X) < min_trades:
        _log.debug("[ML] Only %d trades in journal (need %d) — skipping training", len(X), min_trades)
        return None
    try:
        import lightgbm as lgb
        model = lgb.LGBMClassifier(
            n_estimators=100,
            num_leaves=15,
            learning_rate=0.05,
            min_child_samples=5,
            n_jobs=1,
            verbose=-1,
        )
        model.fit(X, y, feature_name=FEATURE_COLS)
        _log.info("[ML] Trained on %d trades — %d winners", len(X), sum(y))
        return model
    except Exception as exc:
        _log.warning("[ML] Training failed: %s", exc)
        return None


def save_model(model: Any, path: str | Path) -> bool:
    """Persist trained model to disk. Returns True on success."""
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "wb") as f:
            pickle.dump(model, f)
        return True
    except Exception as exc:
        _log.warning("[ML] Save failed: %s", exc)
        return False


def load_model(path: str | Path) -> Any | None:
    """Load persisted model. Returns None if file missing or unpickleable."""
    try:
        p = Path(path)
        if not p.is_file():
            return None
        with open(p, "rb") as f:
            return pickle.load(f)
    except Exception as exc:
        _log.debug("[ML] Load failed: %s", exc)
        return None


# ── Prediction ────────────────────────────────────────────────────────────────

def predict_win_prob(model: Any, features: dict[str, float]) -> float:
    """
    Return the model's estimated probability that this signal is a winner.

    Returns 0.5 (neutral) on any error.
    """
    try:
        import pandas as _pd
        row = _pd.DataFrame([[features[col] for col in FEATURE_COLS]], columns=FEATURE_COLS)
        prob = float(model.predict_proba(row)[0][1])
        return round(max(0.0, min(1.0, prob)), 4)
    except ImportError:
        try:
            row = [[features[col] for col in FEATURE_COLS]]
            prob = float(model.predict_proba(row)[0][1])
            return round(max(0.0, min(1.0, prob)), 4)
        except Exception as exc:
            _log.debug("[ML] predict_win_prob error: %s", exc)
            return 0.5
    except Exception as exc:
        _log.debug("[ML] predict_win_prob error: %s", exc)
        return 0.5


def score_adj_from_prob(prob: float, cfg: dict[str, Any] | None = None) -> tuple[int, str]:
    """
    Convert a win-probability to a bounded score adjustment.

    Returns:
        (adj_pts, tag)
            adj_pts > 0  → boost (model confident this is a winner)
            adj_pts < 0  → penalty (model doubts this signal)
            adj_pts = 0  → neutral
        tag: human-readable label for logging
    """
    c = cfg or {}
    cap = int(c.get("ml_score_adj_cap", 10))
    high = float(c.get("ml_high_prob_threshold", 0.65))
    low  = float(c.get("ml_low_prob_threshold",  0.40))

    if prob >= high:
        strength = min(1.0, (prob - high) / (1.0 - high + 1e-9))
        adj = max(1, round(cap * strength))
        return adj, f"ML:p={prob:.2f}→+{adj}pts"
    if prob <= low:
        strength = min(1.0, (low - prob) / (low + 1e-9))
        adj = -max(1, round(cap * strength))
        return adj, f"ML:p={prob:.2f}→{adj}pts"
    return 0, f"ML:p={prob:.2f}→neutral"


# ── SHAP explainability ───────────────────────────────────────────────────────

# In-process SHAP explainer cache (avoid rebuilding TreeExplainer each call)
_shap_explainer_cache: dict[int, Any] = {}   # {id(model): shap.TreeExplainer}


def explain_prediction(
    model: Any,
    features: dict[str, float],
    cfg: dict[str, Any] | None = None,
) -> dict[str, float]:
    """
    Return per-feature SHAP values for a single prediction.

    Requires the optional ``shap`` package (pip install shap).
    Falls back to feature_importances_ (normalised) when SHAP is unavailable.
    Returns an empty dict on any error so callers can always treat the result
    as optional.

    Args:
        model    : Fitted LightGBM (or compatible) classifier.
        features : Feature dict as returned by extract_features().
        cfg      : Bot config dict; respects ``shap_enabled`` key.

    Returns:
        {feature_name: shap_value} — positive values push towards winner,
        negative towards loser.  Values sum to approx. log-odds contribution.
    """
    c = cfg or {}
    if not c.get("shap_enabled", False):
        return {}

    try:
        import shap as _shap

        model_id = id(model)
        explainer = _shap_explainer_cache.get(model_id)
        if explainer is None:
            explainer = _shap.TreeExplainer(model)
            _shap_explainer_cache[model_id] = explainer

        row = [[features.get(col, 0.0) for col in FEATURE_COLS]]
        shap_vals = explainer.shap_values(row)

        # LightGBM binary: shap_values returns list of [neg_class, pos_class]
        # or a 2-D array depending on version. We want the positive-class values.
        if isinstance(shap_vals, list):
            vals = shap_vals[1][0] if len(shap_vals) > 1 else shap_vals[0][0]
        else:
            vals = shap_vals[0]

        return {col: float(v) for col, v in zip(FEATURE_COLS, vals)}

    except ImportError:
        # shap not installed — fall back to normalised feature_importances_
        try:
            fi = model.feature_importances_
            total = sum(abs(x) for x in fi) or 1.0
            prob = predict_win_prob(model, features)
            sign = 1.0 if prob >= 0.5 else -1.0
            return {col: sign * abs(float(v)) / total
                    for col, v in zip(FEATURE_COLS, fi)}
        except Exception:
            return {}

    except Exception as exc:
        _log.debug("[ML][SHAP] explain_prediction failed: %s", exc)
        return {}


def get_top_features(
    shap_vals: dict[str, float],
    n: int = 3,
) -> list[tuple[str, float]]:
    """
    Return the top-N features sorted by absolute SHAP value.

    Args:
        shap_vals : Dict as returned by explain_prediction().
        n         : Number of features to return.

    Returns:
        List of (feature_name, shap_value) tuples, highest |value| first.
        Empty list if shap_vals is empty.
    """
    if not shap_vals:
        return []
    ranked = sorted(shap_vals.items(), key=lambda kv: abs(kv[1]), reverse=True)
    return ranked[:n]


def shap_to_json(shap_vals: dict[str, float]) -> str:
    """Serialise a SHAP value dict to a compact JSON string for DB storage."""
    if not shap_vals:
        return "{}"
    try:
        return json.dumps({k: round(v, 6) for k, v in shap_vals.items()},
                          separators=(",", ":"))
    except Exception:
        return "{}"


# ── Cached classifier accessor ────────────────────────────────────────────────

def get_classifier(
    journal_path: str | Path,
    cfg: dict[str, Any] | None = None,
) -> Any | None:
    """
    Return a ready-to-use classifier.

    Strategy:
      1. If in-memory cache is fresh (within retrain_interval) and no drift detected, return it.
      2. Try loading the persisted model from disk.
      3. If drift is detected (if enabled) or model is missing/stale, train a new model.
      4. Save and cache the model (whether loaded or newly trained).
      5. Return None if training is impossible (too few trades).
    """
    c = cfg or {}
    if not c.get("ml_classifier_enabled", True):
        return None

    # Import here to avoid circular imports
    from core.concept_drift_detector import detect_drift
    from core.ml_performance_tracker import get_feature_importance_trend

    model_path = str(c.get("ml_model_path", "models/signal_classifier.pkl"))
    retrain_h  = float(c.get("ml_retrain_interval_hours", 24.0))
    retrain_s  = retrain_h * 3600.0
    now        = time.time()

    # Configuration for drift-based retraining
    drift_retrain_enabled      = c.get("drift_retrain_enabled", True)
    drift_retrain_psi_threshold: float  = c.get("drift_retrain_psi_threshold", 0.25)
    drift_retrain_top_features : int    = c.get("drift_retrain_top_features", 5)
    drift_retrain_trend_count  : int    = c.get("drift_retrain_trend_count", 1000)
    tracker_db_path            = c.get("ml_tracker_db_path", "ml_tracker.db")

    # Helper to check for drift in top features
    def _check_for_drift() -> bool:
        """Return True if drift detected in any of the top features."""
        try:
            # Get top N features by mean |SHAP| from the last `trend_count` predictions
            trend = get_feature_importance_trend(
                n_last=drift_retrain_trend_count,
                db_path=tracker_db_path
            )
            if not trend:
                return False
            top_features = list(trend.keys())[:drift_retrain_top_features]

            # For each top feature, check for drift
            for feat in top_features:
                result = detect_drift(
                    feature=feat,
                    db_path=tracker_db_path,
                    psi_alert=drift_retrain_psi_threshold
                )
                if result.status == "ALERT":  # PSI >= threshold
                    _log.info("[ML] Drift detected in feature %s: %s", feat, result.message)
                    return True
            return False
        except Exception as exc:
            _log.debug("[ML] Drift check failed: %s", exc)
            return False  # Assume no drift on error to avoid blocking

    # Thread-safe check of the model cache
    with _model_lock:
        cached = _model_cache.get(model_path)
        if cached is not None and (now - _model_ts.get(model_path, 0)) < retrain_s:
            if not (drift_retrain_enabled and _check_for_drift()):
                return cached
            # else: drift detected, fall through to retrain

        # No valid cached model (or drift detected), try to load from disk
        model = load_model(model_path)
        need_retrain = model is None  # If we couldn't load, we need to train

        # If we have a model but drift-based retraining is enabled, check
        if model is not None and drift_retrain_enabled and not need_retrain:
            if _check_for_drift():
                need_retrain = True
                _log.info("[ML] Drift detected, forcing retrain of loaded model")

        # If we still don't have a model or need to retrain, train a new one
        if need_retrain:
            model = train(journal_path, c)
            if model is not None:
                save_model(model, model_path)
            else:
                _log.warning("[ML] Training failed, returning None")
                return None

        # Cache the model within the lock
        _model_cache[model_path] = model
        _model_ts[model_path] = now
        _log.debug("[ML] Returning model from %s", model_path)
    return model
