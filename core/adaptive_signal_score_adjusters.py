"""
Score Adjustment Helpers — extracted from `adaptive_signal.py` for SRP compliance.

Each function applies ONE score adjustment layer from the signal pipeline.
All business logic is preserved exactly from the original `evaluate_adaptive_signal`
and `_compute_features_and_score` functions.

Usage:
    score, pts, tag = apply_iv_rank_adjustment(vix, score, config)
    score, pts, tag = apply_session_adjustment(score, config, soft_blocks)
"""

from __future__ import annotations

import logging
import math
from typing import Any

# Rate-limited warning tracking for optional module failures
_WARNED_MODULES: set[str] = set()


def _log_missing_module(module_name: str, exc: Exception) -> None:
    """Log missing module warning on first occurrence, debug thereafter."""
    if module_name not in _WARNED_MODULES:
        _WARNED_MODULES.add(module_name)
        _log.warning("[SIGNAL] Optional module %s not available: %s", module_name, exc)
    else:
        _log.debug("[SIGNAL] Optional module %s skipped: %s", module_name, exc)

_log = logging.getLogger(__name__)


# ── IV Rank / IV Percentile adjustment ────────────────────────────────────────
def apply_iv_rank_adjustment(
    vix: float,
    score: int,
    config: dict[str, Any],
    soft_blocks: list[str],
    reasons: list[str],
) -> tuple[int, int]:
    """Apply IV Rank score multiplier to adjust for expensive/cheap premium.

    Returns:
        (adjusted_score, iv_rank_points)
    """
    _iv_rank_pts: int = 0
    if vix > 0:
        try:
            from core.iv_rank import get_score_multiplier as _iv_mult_fn
            _iv_mult, _iv_rank_val, _iv_tag = _iv_mult_fn(vix, config)
            if _iv_mult != 1.0:
                _pre_iv = score
                score = max(0, min(100, int(round(score * _iv_mult))))
                _iv_rank_pts = score - _pre_iv
                if _iv_rank_pts < 0:
                    soft_blocks.append("high_iv")
                reasons.append(f"[IV] {_iv_tag}")
        except (ValueError, TypeError, IndexError) as _iv_err:
            _log.debug("[SIGNAL] IV rank skipped: %s", _iv_err)
    return score, _iv_rank_pts


# ── IV Skew adjustment ────────────────────────────────────────────────────────
def apply_iv_skew_adjustment(
    data: dict[str, Any],
    score: int,
    config: dict[str, Any],
    soft_blocks: list[str],
    reasons: list[str],
) -> tuple[int, int]:
    """Apply IV Skew score penalty for extreme put skew.

    Returns:
        (adjusted_score, skew_points)
    """
    _skew_adj_pts: int = 0
    if config.get("iv_skew_enabled", True):
        try:
            from core.iv_rank import compute_iv_skew as _compute_skew

            _option_chain = data.get("option_chain")
            _spot = float(data.get("price", 0.0))
            _dte = int(data.get("dte", 7))
            if _option_chain and _spot > 0:
                _skew_dat = _compute_skew(_option_chain, _spot, _dte, config)
                if _skew_dat is not None and _skew_dat.regime == "EXTREME":
                    _pen = int(config.get("iv_skew_extreme_score_penalty", 5))
                    _direction = str(data.get("direction", "CALL")).upper()
                    if _direction in ("CALL", "CE"):
                        _pre_skew = score
                        score = max(0, score - _pen)
                        _skew_adj_pts = score - _pre_skew
                        soft_blocks.append("extreme_put_skew")
                        reasons.append(f"[SKEW] EXTREME put_skew={_skew_dat.put_skew:.1f} pen={_pen:+d}")
        except (ValueError, TypeError, AttributeError) as _skew_err:
            _log.debug("[SIGNAL] IV skew skipped: %s", _skew_err)
    return score, _skew_adj_pts


# ── Session Classifier adjustment ──────────────────────────────────────────────
def apply_session_adjustment(
    score: int,
    config: dict[str, Any],
    soft_blocks: list[str],
    reasons: list[str],
) -> tuple[int, int]:
    """Apply time-of-day session classifier score adjustment.

    Returns:
        (adjusted_score, session_points)
    """
    _session_adj_pts: int = 0
    if config.get("session_classifier_enabled", True):
        try:
            from core.datetime_ist import now_ist as _now_ist
            from core.session_classifier import (
                classify_session as _cls_session,
            )
            from core.session_classifier import (
                get_session_score_adj as _sess_adj_fn,
            )
            from core.session_classifier import (
                session_entry_allowed as _sess_allowed_fn,
            )

            _session = _cls_session(_now_ist().time(), config)
            if not _sess_allowed_fn(_session, config):
                soft_blocks.append(f"session_{_session.value.lower()}_blocked")
            _sess_adj = _sess_adj_fn(_session, config)
            if _sess_adj != 0:
                _pre_sess = score
                score = max(0, min(100, score + _sess_adj))
                _session_adj_pts = score - _pre_sess
            reasons.append(f"[SESSION] {_session.value} adj={_sess_adj:+d}")
        except (ValueError, TypeError, AttributeError, ImportError) as _sess_err:
            _log.debug("[SIGNAL] Session classifier skipped: %s", _sess_err)
    return score, _session_adj_pts


# ── ML Signal Classifier adjustment ────────────────────────────────────────────
def apply_ml_adjustment(
    data: dict[str, Any],
    score: int,
    config: dict[str, Any],
    vix: float,
    pcr: float,
    soft_blocks: list[str],
    reasons: list[str],
) -> tuple[int, int, float, str, str]:
    """Apply LightGBM ML win-probability classifier score adjustment.

    Returns:
        (adjusted_score, ml_points, ml_prob, ml_pred_id, ml_reasoning)
    """
    _ml_adj_pts: int = 0
    _ml_pred_id: str = ""
    _ml_prob: float = 0.5
    _ml_reasoning: str = ""

    if config.get("ml_classifier_enabled", True):
        try:
            import pathlib as _pl

            from core.ml_classifier import (
                explain_prediction as _explain_pred,
            )
            from core.ml_classifier import (
                extract_features as _extract_feat,
            )
            from core.ml_classifier import (
                get_classifier as _get_clf,
            )
            from core.ml_classifier import (
                predict_win_prob as _predict_prob,
            )
            from core.ml_classifier import (
                score_adj_from_prob as _prob_adj,
            )
            from core.ml_classifier import (
                shap_to_json as _shap_json,
            )

            _scfg = dict(config)
            _journal_path = _pl.Path(_scfg.get("ml_journal_path", "db/trade_journal.db"))
            _clf = _get_clf(_journal_path, _scfg)
            if _clf is not None:
                _feat_input = dict(data)
                _feat_input["tier"] = str(data.get("strength", "MODERATE"))
                _feat_input["direction"] = str(data.get("direction", "CALL"))
                _feat_input["soft_blocks"] = soft_blocks
                _feat_input["confidence"] = float(data.get("confidence", 0.5))
                _feat_input["vix"] = float(vix)
                _feat_input["pcr"] = float(pcr)
                _feat_dict = _extract_feat(_feat_input)
                _prob = _predict_prob(_clf, _feat_dict)
                _ml_prob = float(_prob)
                _ml_adj, _ml_tag = _prob_adj(_prob, _scfg)
                if _ml_adj != 0:
                    _pre_ml = score
                    score = max(0, min(100, score + _ml_adj))
                    _ml_adj_pts = score - _pre_ml
                reasons.append(f"[ML] {_ml_tag}")

                # ML Reasoning (SHAP)
                try:
                    _shap_vals = _explain_pred(_clf, _feat_dict, _scfg)
                    if _shap_vals:
                        from core.ml_classifier import get_top_features as _get_top

                        top_f = _get_top(_shap_vals)
                        _reason_str = " | ".join([f"{k}:{round(v, 2)}" for k, v in top_f])
                        _ml_reasoning = f"Top Features: {_reason_str}"

                        # SHAP confidence integration
                        shap_values = list(_shap_vals.values())
                        if shap_values:
                            abs_shap = [abs(v) for v in shap_values]
                            total_abs = sum(abs_shap)
                            if total_abs > 0:
                                prob_dist = [v / total_abs for v in abs_shap]
                                entropy = -sum(p * math.log(p) for p in prob_dist if p > 0)
                                max_entropy = math.log(len(prob_dist)) if len(prob_dist) > 1 else 1
                                normalized_entropy = entropy / max_entropy if max_entropy > 0 else 0
                                shap_confidence = 1.0 - normalized_entropy
                                if shap_confidence < 0.5:
                                    confidence_factor = shap_confidence * 2
                                    _ml_adj = int(_ml_adj * confidence_factor)
                                    _ml_tag = f"{_ml_tag} (SHAP conf={shap_confidence:.2f})"
                    else:
                        _ml_reasoning = ""
                except (ValueError, TypeError, AttributeError):
                    _ml_reasoning = ""

                # Record prediction for calibration tracking
                if _scfg.get("ml_tracker_enabled", True):
                    try:
                        import time as _time_mod

                        from core.ml_performance_tracker import record_prediction as _ml_rec

                        _ml_pred_id = f"sig_{int(_time_mod.time())}_{data.get('index_name', 'X')}"
                        _ml_rec(
                            _ml_pred_id,
                            _prob,
                            shap_json=_shap_json(_shap_vals),
                            db_path=_scfg.get("ml_tracker_db_path", "db/ml_tracker.db"),
                        )
                    except (ValueError, TypeError, AttributeError) as e:
                        _log.debug("[ADAPTIVE_SIGNAL] non-critical error: %s", e)
        except (ImportError, ValueError, TypeError, AttributeError) as _ml_err:
            _log.debug("[SIGNAL] ML classifier skipped: %s", _ml_err)

    return score, _ml_adj_pts, _ml_prob, _ml_pred_id, _ml_reasoning


# ── FII/DII Institutional Flow adjustment ──────────────────────────────────────
def apply_fii_dii_adjustment(
    direction: str,
    score: int,
    config: dict[str, Any],
) -> tuple[int, int]:
    """Apply FII/DII institutional flow score adjustment.

    Returns:
        (adjusted_score, fii_dii_points)
    """
    _fii_pts: int = 0
    if config.get("fii_dii_enabled", False):
        try:
            from core.fii_dii_tracker import FIIDIITracker as _FIITkr

            _fii_tracker = _FIITkr(dict(config))
            _fii_adj = _fii_tracker.score_adjustment(direction)
            if _fii_adj != 0:
                _pre_fii = score
                score = max(0, min(100, score + _fii_adj))
                _fii_pts = score - _pre_fii
        except (ImportError, ValueError, TypeError, AttributeError, KeyError):
            _log.debug("[SIGNAL] Optional feature skipped")
    return score, _fii_pts


# ── Implied Move adjustment ────────────────────────────────────────────────────
def apply_implied_move_adjustment(
    data: dict[str, Any],
    score: int,
    config: dict[str, Any],
) -> tuple[int, int]:
    """Apply implied move score adjustment.

    Returns:
        (adjusted_score, implied_move_points)
    """
    _im_pts: int = 0
    if config.get("implied_move_enabled", False):
        try:
            from core.implied_move import get_implied_move_score_adj as _im_adj_fn

            _sl_mult = float(config.get("SL_PCT", 0.30))
            _signal_move_pct = _sl_mult * 100
            _im_adj = _im_adj_fn(data.get("_implied_move"), _signal_move_pct, dict(config))
            if _im_adj != 0:
                _pre_im = score
                score = max(0, min(100, score + _im_adj))
                _im_pts = score - _pre_im
        except (ImportError, ValueError, TypeError, AttributeError, KeyError) as e:
            _log.debug("[ADAPTIVE_SIGNAL] non-critical error: %s", e)
    return score, _im_pts


# ── GEX regime adjustment ──────────────────────────────────────────────────────
def apply_gex_adjustment(
    data: dict[str, Any],
    direction: str,
    score: int,
    config: dict[str, Any],
) -> tuple[int, int]:
    """Apply Gamma Exposure (GEX) regime score adjustment.

    Returns:
        (adjusted_score, gex_points)
    """
    _gex_pts: int = 0
    if config.get("gex_enabled", False):
        try:
            from core.gex_analyzer import compute_gex as _cgex
            from core.gex_analyzer import get_gex_score_adj as _gex_adj_fn

            _gex_chain = data.get("option_chain")
            _gex_spot = float(data.get("price", 0.0))
            _gex_res = _cgex(_gex_chain, _gex_spot, dict(config))
            _gex_adj = _gex_adj_fn(_gex_res, direction, dict(config))
            if _gex_adj != 0:
                _pre_gex = score
                score = max(0, min(100, score + _gex_adj))
                _gex_pts = score - _pre_gex
        except (ImportError, ValueError, TypeError, AttributeError, KeyError) as e:
            _log.debug("[ADAPTIVE_SIGNAL] non-critical error: %s", e)
    return score, _gex_pts


# ── Regime Transition adjustment ───────────────────────────────────────────────
def apply_regime_transition_adjustment(
    regime: str,
    data: dict[str, Any],
    vix: float,
    score: int,
    config: dict[str, Any],
) -> tuple[int, int]:
    """Apply regime transition detection score bonus.

    Returns:
        (adjusted_score, regime_transition_points)
    """
    _rt_pts: int = 0
    if config.get("regime_transition_enabled", False):
        try:
            from core.regime_transition_detector import detect_transition as _det_trans
            from core.regime_transition_detector import get_transition_score_adj as _trans_adj

            _adx_ser = data.get("adx_series", [float(data.get("adx", 0.0))])
            _macd_ser = data.get("macd_hist_series", [])
            _rt_sig = _det_trans(
                regime,
                data.get("prev_regime", regime),
                _adx_ser,
                vix,
                _macd_ser,
                dict(config),
            )
            _rt_adj = _trans_adj(_rt_sig, dict(config))
            if _rt_adj != 0:
                _pre_rt = score
                score = max(0, min(100, score + _rt_adj))
                _rt_pts = score - _pre_rt
        except (ImportError, ValueError, TypeError, AttributeError, KeyError) as e:
            _log.debug("[ADAPTIVE_SIGNAL] non-critical error: %s", e)
    return score, _rt_pts


# ── MA Crossover adjustment (v2.54) ────────────────────────────────────────────
def apply_ma_crossover_adjustment(
    data: dict[str, Any],
    score: int,
    config: dict[str, Any],
    soft_blocks: list[str],
    reasons: list[str],
    df1: Any = None,  # 1m OHLCV DataFrame passed directly
) -> tuple[int, int]:
    """Apply Moving Average Crossover score adjustment for trend-following setups.

    Detects golden crosses (CALL) and death crosses (PUT) across multiple MA
    configurations as additional score layers.

    Enabled via config key ``ma_crossover_score_adjustment_enabled`` (default false).

    Returns:
        (adjusted_score, ma_crossover_points)
    """
    _ma_pts: int = 0
    if config.get("ma_crossover_score_adjustment_enabled", False):
        try:
            from core.strategy.ma_crossover import detect_ma_crossover as _ma_detect

            _ma_df = df1
            if _ma_df is not None:
                _fast_p = int(config.get("MA_CROSSOVER_FAST_PERIOD", 9))
                _slow_p = int(config.get("MA_CROSSOVER_SLOW_PERIOD", 21))
                _ma_type = str(config.get("MA_CROSSOVER_MA_TYPE", "ema"))
                _adx_min = float(config.get("MA_CROSSOVER_ADX_MIN", 20.0))
                _result = _ma_detect(
                    _ma_df,
                    fast_period=_fast_p,
                    slow_period=_slow_p,
                    ma_type=_ma_type,
                    adx_min=_adx_min,
                    min_score=30,
                )
                if _result.signal and _result.direction == str(data.get("direction", "")).upper():
                    _ma_pts = min(25, _result.score // 3)
                    _pre_ma = score
                    score = max(0, min(100, score + _ma_pts))
                    _ma_pts = score - _pre_ma
                    reasons.append(f"[MA] {_result.reason} ma_adj={_ma_pts:+d}")
                    if _ma_pts > 0:
                        _log.debug(
                            "[SIGNAL] MA crossover bonus: %+d pts (%s)", _ma_pts, _result.reason
                        )
        except (ImportError, ValueError, TypeError, AttributeError, KeyError) as _ma_err:
            _log_missing_module("ma_crossover", _ma_err)
    return score, _ma_pts


# ── Mean Reversion adjustment (v2.54) ────────────────────────────────────────
def apply_mean_reversion_adjustment(
    data: dict[str, Any],
    score: int,
    config: dict[str, Any],
    soft_blocks: list[str],
    reasons: list[str],
    df1: Any = None,  # 1m OHLCV DataFrame passed directly
) -> tuple[int, int]:
    """Apply Mean Reversion score adjustment for range-bound/overextended markets.

    Detects pullbacks to Bollinger Bands, RSI extremes, and VWAP distance
    as additional score layers for mean-reversion setups.

    Enabled via config key ``mean_reversion_score_adjustment_enabled`` (default false).

    Returns:
        (adjusted_score, mean_reversion_points)
    """
    _mr_pts: int = 0
    if config.get("mean_reversion_score_adjustment_enabled", False):
        try:
            from core.strategy.mean_reversion import detect_mean_reversion as _mr_detect

            _mr_df = df1  # DataFrame passed directly from caller
            if _mr_df is not None:
                _mr_result = _mr_detect(_mr_df, min_score=30)
                if _mr_result.signal and _mr_result.direction == str(data.get("direction", "")).upper():
                    _mr_pts = min(20, _mr_result.score // 3)
                    _pre_mr = score
                    score = max(0, min(100, score + _mr_pts))
                    _mr_pts = score - _pre_mr
                    reasons.append(f"[MR] {_mr_result.reason} mr_adj={_mr_pts:+d}")
                    if _mr_pts > 0:
                        _log.debug("[SIGNAL] Mean reversion bonus: %+d pts (%s)", _mr_pts, _mr_result.reason)
        except (ImportError, ValueError, TypeError, AttributeError, KeyError) as _mr_err:
            _log_missing_module("mean_reversion", _mr_err)
    return score, _mr_pts


# ── Max Penalty Cap ────────────────────────────────────────────────────────────
def apply_max_penalty_cap(
    score: int,
    raw_score: int,
    config: dict[str, Any],
) -> int:
    """Apply maximum penalty cap to prevent penalty stacking.

    Returns:
        capped_score
    """
    _max_penalty = int(config.get("ADAPTIVE_SIGNAL_MAX_TOTAL_PENALTY", -50))
    total_penalty = score - raw_score
    if total_penalty < _max_penalty:
        old_score = score
        score = max(0, raw_score + _max_penalty)
        if config.get("ADAPTIVE_SIGNAL_PENALTY_ALERT_THRESHOLD"):
            _pen_alert_thr = float(config.get("ADAPTIVE_SIGNAL_PENALTY_ALERT_THRESHOLD", 0.6))
            _rej_rate = total_penalty / max(1, raw_score) if raw_score > 0 else 0
            if _rej_rate < -_pen_alert_thr:
                import logging as _lg

                _lg.getLogger(__name__).warning(
                    "[ADAPTIVE] Penalty cap applied: %d -> %d (total_penalty=%d, raw=%d)",
                    old_score,
                    score,
                    total_penalty,
                    raw_score,
                )
    return score


__all__ = [
    "apply_fii_dii_adjustment",
    "apply_gex_adjustment",
    "apply_implied_move_adjustment",
    "apply_iv_rank_adjustment",
    "apply_iv_skew_adjustment",
    "apply_ma_crossover_adjustment",
    "apply_max_penalty_cap",
    "apply_mean_reversion_adjustment",
    "apply_ml_adjustment",
    "apply_regime_transition_adjustment",
    "apply_session_adjustment",
]
