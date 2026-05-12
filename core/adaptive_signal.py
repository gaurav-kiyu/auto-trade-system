"""
Adaptive signal evaluator — soft-rejection wrapper around evaluate_index_signal_partial.

Hard rejections in evaluate_index_signal_partial (tf_mismatch, choppy) are converted
to score penalties + confidence reduction instead of returning None. This lets the
tiered system trade partial setups at reduced position size rather than skip entirely.

Hard blocks that stay hard (genuine data gaps — no signal is possible):
    1m_short, 5m_short, 15m_short, partial_drop, bad_price, iv_spike

Soft-converted blocks (traded with penalty):
    tf_mismatch  → -20 score, confidence × 0.60, direction from stronger TF
    choppy       → -15 score, confidence × 0.70

The returned AdaptiveSignal drives position sizing via PositionSizer and carries
tier-specific risk/execution parameters from TierRules.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Any

import pandas as pd
import signal_engine as SE

from core.feature_engine import FeatureEngine
from core.market_calc import detect_regime_and_adx as mc_detect_regime_and_adx
from core.position_sizer import PositionSizer, PositionSpec
from core.pure_index_signal import (
    PureIndexSignalParams,
    _drop_partial_candle,  # resampling artifact cleaner
    _macd_bonus_delta,  # MACD histogram direction check
    compute_index_score,
    evaluate_index_signal_partial,
)
from core.tier_engine import TIER_RULES, classify_tier

# ── Soft-rejection penalty constants ─────────────────────────────────────────
_SOFT_PENALTY_TF_MISMATCH: int   = 20
_SOFT_PENALTY_CHOPPY: int        = 15
_CONF_MULT_TF_MISMATCH: float    = 0.60
_CONF_MULT_CHOPPY: float         = 0.70


# ── Result dataclass ──────────────────────────────────────────────────────────
@dataclass
class AdaptiveSignal:
    # Classification
    tier: str                           # STRONG / MODERATE / WEAK / IGNORE
    score: int                          # final adjusted score
    raw_score: int                      # score before soft-block penalties
    confidence: float                   # 0.0-1.0 (1.0 = no soft blocks)
    direction: str                      # CALL / PUT

    # Context
    regime: str
    soft_blocks: list[str]              # e.g. ["tf_mismatch", "choppy_regime"]
    reasons: list[str]                  # human-readable component breakdown
    score_components: dict[str, int]    # per-component point contribution
    features: list[str]                 # component keys with positive points

    # Market data at signal time
    atr: float = 0.0
    rsi: float = 50.0
    adx: float = 0.0
    vwap: float = 0.0
    vol_ratio: float = 0.0
    price: float = 0.0
    macd: dict[str, float] = field(default_factory=dict)
    risk: dict[str, Any] = field(default_factory=dict)
    position_spec: PositionSpec | None = None

    # ML performance tracking (empty string when ml_tracker disabled or model absent)
    ml_pred_id: str = ""

    # ML reasoning explanation (top features contributing to the prediction)
    reasoning: str = ""

    # Wilson 95% confidence interval for win rate at this signal's parameters
    # (None when confidence_band_enabled=False or insufficient trade history)
    confidence_band: SignalConfidenceBand | None = None


# ── Confidence Band (v2.44 Item 18) ──────────────────────────────────────────

@dataclass
class SignalConfidenceBand:
    """Wilson 95% confidence interval for historical win rate in a signal bucket."""
    n_trades:   int
    n_wins:     int
    win_rate:   float           # point estimate
    ci_low:     float           # 95% CI lower bound
    ci_high:    float           # 95% CI upper bound
    score_bin:  str  = ""
    regime:     str  = ""
    session:    str  = ""
    direction:  str  = ""

    def __str__(self) -> str:
        return (
            f"[CI: {self.ci_low*100:.0f}-{self.ci_high*100:.0f}%] "
            f"n={self.n_trades}"
        )


def _wilson_ci(wins: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Return (low, high) Wilson score interval for wins/n at z-sigma."""
    if n == 0:
        return 0.0, 1.0
    p    = wins / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    margin = z * (p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5 / denom
    return max(0.0, center - margin), min(1.0, center + margin)


def compute_confidence_band(
    score:     int,
    regime:    str,
    session:   str,
    direction: str,
    db_path:   str,
    cfg:       dict[str, Any],
) -> SignalConfidenceBand | None:
    """
    Query trades.db and compute a Wilson 95% CI for win rate in the matching bucket.

    Bucket = trades with score ± bin_width, same regime, session, direction.
    Returns None on DB error, disabled config, or too few trades.

    Config keys used:
        confidence_band_enabled           : bool  default true
        confidence_band_score_bin_width   : int   default 5
        confidence_band_high_threshold    : int   default 30 (min trades for high CI)
        confidence_band_moderate_threshold: int   default 10
    """
    if not cfg.get("confidence_band_enabled", True):
        return None

    bin_w   = int(cfg.get("confidence_band_score_bin_width", 5))
    lo, hi  = score - bin_w, score + bin_w

    import sqlite3 as _sqlite3
    from pathlib import Path as _Path

    p = _Path(db_path)
    if not p.is_file():
        return None

    try:
        conn = _sqlite3.connect(str(p), check_same_thread=False, timeout=3)
        try:
            rows = conn.execute(
                "SELECT net_pnl FROM trades "
                "WHERE score BETWEEN ? AND ? "
                "  AND regime = ? "
                "  AND direction = ? "
                "  AND net_pnl IS NOT NULL",
                (lo, hi, regime, direction),
            ).fetchall()
        finally:
            conn.close()

        if not rows:
            return None

        pnls  = [float(r[0]) for r in rows]
        n     = len(pnls)
        wins  = sum(1 for p in pnls if p > 0)
        wr    = wins / n
        ci_lo, ci_hi = _wilson_ci(wins, n)

        bin_label = f"{lo}-{hi}"
        return SignalConfidenceBand(
            n_trades=n, n_wins=wins,
            win_rate=round(wr, 4),
            ci_low=round(ci_lo, 4),
            ci_high=round(ci_hi, 4),
            score_bin=bin_label,
            regime=regime,
            session=session,
            direction=direction,
        )
    except Exception:
        return None


# ── Timeframe Agreement (v2.45 Item 5) ───────────────────────────────────────

@dataclass
class TimeframeAgreement:
    """Agreement score across 1m / 5m / 15m timeframes."""
    agreement_score:  float   # 0.0 (full divergence) – 1.0 (all agree)
    bullish_count:    int     # how many TFs are bullish
    bearish_count:    int     # how many TFs are bearish
    divergence_detail: str    # human-readable summary


def compute_timeframe_agreement(
    dir_1m:  str,
    dir_5m:  str,
    dir_15m: str,
    cfg:     dict[str, Any] | None = None,
) -> TimeframeAgreement:
    """
    Compute agreement across 1m, 5m, 15m trend directions.

    Args:
        dir_1m / dir_5m / dir_15m : "UP", "DOWN", or "FLAT"
        cfg: config dict (timeframe_divergence_block_enabled etc.)

    Returns:
        TimeframeAgreement with agreement_score 0-1.
    """
    dirs = [dir_1m, dir_5m, dir_15m]
    bull = sum(1 for d in dirs if d == "UP")
    bear = sum(1 for d in dirs if d == "DOWN")
    n_defined = bull + bear
    if n_defined == 0:
        score = 0.0
    elif n_defined == 3:
        score = 1.0 if (bull == 3 or bear == 3) else round(max(bull, bear) / 3, 3)
    else:
        score = round(max(bull, bear) / n_defined, 3) if n_defined else 0.0

    labels = ["1m", "5m", "15m"]
    detail = " | ".join(f"{labels[i]}={dirs[i]}" for i in range(3))
    return TimeframeAgreement(
        agreement_score  = score,
        bullish_count    = bull,
        bearish_count    = bear,
        divergence_detail= detail,
    )


def _build_risk_dict(tier: str) -> dict[str, Any]:
    rules = TIER_RULES.get(tier)
    if rules is None:
        return {}
    return {
        "sl_mult_adj":          rules.sl_mult_adj,
        "tp_mult_adj":          rules.tp_mult_adj,
        "trail_enabled":        rules.trail_enabled,
        "trail_activate_pct":   rules.trail_activate_pct,
        "trail_from_peak_pct":  rules.trail_from_peak_pct,
        "max_bars_mult":        rules.max_bars_mult,
        "partial_exit_enabled": rules.partial_exit_enabled,
        "partial_exit_pct":     rules.partial_exit_pct,
    }


def _compute_features_and_score(
    *,
    params: PureIndexSignalParams,
    df1: pd.DataFrame,
    df5: pd.DataFrame,
    df15: pd.DataFrame,
    vix: float,
    oi_sup: float,
    oi_res: float,
    pcr: float,
    smart: str,
    learning_score_bonus: int,
    allow_tf_mismatch: bool,
    allow_choppy: bool,
) -> dict[str, Any] | None:
    """
    Core feature extraction + scoring, with selectable relaxation of tf and regime gates.
    Returns a partial-signal dict, or None if data is genuinely insufficient.
    """
    sc = params.signal_cfg
    min15 = int(
        sc.get("EARLY_SESSION_MIN_15M", params.min15_early)
        if params.is_early_session
        else sc.get("NORMAL_SESSION_MIN_15M", params.min15_normal)
    )

    if df1 is None or len(df1) < 30: return None
    if df5 is None or len(df5) < 10: return None
    if df15 is None or len(df15) < min15: return None

    df1 = _drop_partial_candle(df1)
    df5 = _drop_partial_candle(df5)
    if df1 is None or len(df1) < 30 or df5 is None or len(df5) < 10:
        return None

    t5  = FeatureEngine.ema_trend(df5)
    t15 = FeatureEngine.ema_trend(df15)

    if not allow_tf_mismatch:
        if t5 == "FLAT" or t15 == "FLAT" or t5 != t15:
            return None
    else:
        # Pick direction from the stronger (5m) timeframe; fall back to 15m
        if t5 == "FLAT" and t15 == "FLAT":
            return None  # no direction at all — irrecoverable

    direction_tf = t5 if t5 != "FLAT" else t15

    price = FeatureEngine.get_price(df1)
    if price <= 0:
        return None

    vwap_val  = FeatureEngine.get_vwap(df1)
    atr       = FeatureEngine.get_atr(df1)
    vol_ratio = FeatureEngine.get_vol_ratio(df1)
    d1        = FeatureEngine.price_delta(df1, 10)
    d5_       = FeatureEngine.price_delta(df5, 3)
    rsi_val   = FeatureEngine.get_rsi(df5)

    rp = params.regime
    mkt_regime, avg_adx = mc_detect_regime_and_adx(
        df5, df15,
        vix=vix,
        vix_block_threshold=rp.vix_block_threshold,
        adx_trend_threshold=rp.adx_trend_threshold,
        adx_chop_threshold=rp.adx_chop_threshold,
    )

    if mkt_regime == "CHOPPY" and not allow_choppy:
        return None

    direction = "CALL" if direction_tf == "UP" else "PUT"

    score = compute_index_score(
        direction_tf, t15, price, vwap_val, atr, vol_ratio, d1, d5_, pcr, smart,
        signal_cfg=sc, vol_ratio_min=params.vol_ratio_min,
        learning_score_bonus=learning_score_bonus, rsi=rsi_val,
    )

    # Component breakdown — mirrors pure_index_signal.py formulas exactly
    _vwap_ref_ = max(float(vwap_val), 1.0)
    if (direction_tf == "UP" and price > _vwap_ref_) or (direction_tf == "DOWN" and price < _vwap_ref_):
        _vwap_dist_ = abs(price - _vwap_ref_) / _vwap_ref_
        _vwap_pts = min(20, 8 + int(min(1.0, _vwap_dist_ / 0.005) * 12))
    else:
        _vwap_pts = 0
    _d1_pts   = 15 if (direction_tf == "UP" and d1 > 0) or (direction_tf == "DOWN" and d1 < 0) else 0
    _d5_pts   = 10 if (direction_tf == "UP" and d5_ > 0) or (direction_tf == "DOWN" and d5_ < 0) else 0
    if vol_ratio >= params.vol_ratio_min:
        _vol_excess_ = (vol_ratio - params.vol_ratio_min) / max(params.vol_ratio_min, 0.5)
        _vol_pts = min(14, 4 + int(min(1.0, _vol_excess_) * 10))
    else:
        _vol_pts = 0
    _rsi_b    = int(sc.get("INDEX_RSI_BONUS", 8))
    _rsi_hl_c = float(sc.get("INDEX_RSI_HEALTHY_LOW_CALL", 40))
    _rsi_hh_c = float(sc.get("INDEX_RSI_HEALTHY_HIGH_CALL", 70))
    _rsi_hl_p = float(sc.get("INDEX_RSI_HEALTHY_LOW_PUT", 30))
    _rsi_hh_p = float(sc.get("INDEX_RSI_HEALTHY_HIGH_PUT", 60))
    _rsi_pts  = (
        _rsi_b if (direction_tf == "UP" and _rsi_hl_c <= rsi_val <= _rsi_hh_c)
               or (direction_tf == "DOWN" and _rsi_hl_p <= rsi_val <= _rsi_hh_p)
        else 0
    )
    _sm_pts   = 10 if (direction_tf == "UP" and smart == "BULLISH") or (direction_tf == "DOWN" and smart == "BEARISH") else 0
    _pcr_bull = float(sc.get("PCR_BULLISH", 1.2))
    _pcr_bear = float(sc.get("PCR_BEARISH", 0.8))
    _pcr_pts  = 5 if (direction_tf == "UP" and pcr > _pcr_bull) or (direction_tf == "DOWN" and pcr < _pcr_bear) else 0

    score_components: dict[str, int] = {
        "tf_aligned":  20 if t5 == t15 else 0,
        "vwap":        _vwap_pts,
        "d1_momentum": _d1_pts,
        "d5_momentum": _d5_pts,
        "volume":      _vol_pts,
        "atr_floor":   5 if atr > float(sc.get("ATR_MIN_THRESHOLD", 0.5)) else 0,
        "rsi_bonus":   _rsi_pts,
        "smart_money": _sm_pts,
        "pcr":         _pcr_pts,
    }

    macd_raw   = FeatureEngine.get_macd(df5)
    macd_b     = int(sc.get("MACD_BONUS", 5))
    macd_delta = _macd_bonus_delta(direction, macd_raw, macd_b)
    score      = min(100, int(score) + macd_delta)
    score_components["macd_bonus"] = macd_delta

    breakout_ok      = SE.breakout_strength_ok(df1)
    _breakout_bonus  = int(sc.get("BREAKOUT_BONUS", 8))
    bk_pts           = _breakout_bonus if breakout_ok else -4
    score            = min(100, score + bk_pts) if breakout_ok else max(0, score + bk_pts)
    score_components["breakout"] = bk_pts

    # ADX penalty
    _adx_pen_thr  = float(sc.get("ADX_PENALTY_THRESHOLD", 12))
    _adx_pen      = int(sc.get("ADX_PENALTY_POINTS", 5))
    adx_pen_pts   = 0
    if avg_adx > 0 and avg_adx < _adx_pen_thr:
        adx_pen_pts = -_adx_pen
        score = max(0, score - _adx_pen)
    score_components["adx_penalty"] = adx_pen_pts

    # ADX trend bonus
    _adx_trend_thr  = float(sc.get("ADX_TREND_THRESHOLD", 20))
    _adx_trend_b    = int(sc.get("ADX_TREND_BONUS_POINTS", 5))
    _adx_trend_pts  = 0
    if avg_adx >= _adx_trend_thr:
        _adx_trend_pts = _adx_trend_b
        score = min(100, score + _adx_trend_pts)
    score_components["adx_trend_bonus"] = _adx_trend_pts

    # Regime penalty
    _hv_pen    = int(sc.get("REGIME_SCORE_PENALTY_HV", 8))
    _ev_pen    = int(sc.get("REGIME_SCORE_PENALTY_EVENT", 10))
    _reg_pen   = 0
    if mkt_regime == "HIGH_VOLATILITY":
        _reg_pen = -_hv_pen
        score = max(0, score - _hv_pen)
    elif mkt_regime == "EVENT":
        _reg_pen = -_ev_pen
        score = max(0, score - _ev_pen)
    score_components["regime_penalty"] = _reg_pen

    # VWAP reclaim bonus
    _reclaim_b   = int(sc.get("VWAP_RECLAIM_BONUS", 7))
    _reclaim_pts = 0
    if _vwap_pts > 0 and vwap_val > 0 and len(df1) >= 5:
        _recent_closes = df1["Close"].iloc[-5:-1].values
        _was_wrong = (
            any(c < vwap_val for c in _recent_closes) if direction == "CALL"
            else any(c > vwap_val for c in _recent_closes)
        )
        if _was_wrong:
            _reclaim_pts = _reclaim_b
            score = min(100, score + _reclaim_pts)
    score_components["vwap_reclaim"] = _reclaim_pts

    # ORB bonus
    _orb_b   = int(sc.get("ORB_BONUS", 10))
    _orb_pts = 0
    try:
        if _orb_b > 0 and hasattr(df1.index, "time"):
            _t915 = datetime.time(9, 15)
            _t930 = datetime.time(9, 30)
            _idx_times = [t.time() if hasattr(t, "time") else t for t in df1.index]
            _orb_mask = [_t915 <= t < _t930 for t in _idx_times]
            _orb_df = df1.loc[_orb_mask]
            if len(_orb_df) >= 5:
                _orb_high = float(_orb_df["High"].max())
                _orb_low  = float(_orb_df["Low"].min())
                if direction == "CALL" and price > _orb_high * 1.001:
                    _orb_pts = _orb_b
                    score = min(100, score + _orb_pts)
                elif direction == "PUT" and price < _orb_low * 0.999:
                    _orb_pts = _orb_b
                    score = min(100, score + _orb_pts)
    except Exception:
        pass
    score_components["orb_bonus"] = _orb_pts

    return {
        "score":            score,
        "direction":        direction,
        "mkt_regime":       mkt_regime,
        "adx":              avg_adx,
        "rsi":              rsi_val,
        "vwap":             vwap_val,
        "atr":              atr,
        "vol_ratio":        vol_ratio,
        "price":            price,
        "score_components": score_components,
        "macd":             macd_raw,
        "breakout_ok":      breakout_ok,
        "t5":               t5,
        "t15":              t15,
    }


def evaluate_adaptive_signal(
    *,
    params: PureIndexSignalParams,
    df1: pd.DataFrame,
    df5: pd.DataFrame,
    df15: pd.DataFrame,
    vix: float,
    iv: float,
    oi_sup: float,
    oi_res: float,
    pcr: float,
    smart: str,
    learning_score_bonus: int = 0,
    max_lots: int = 1,
    capital: float = 100_000.0,
) -> tuple[AdaptiveSignal | None, str]:
    """
    Evaluate signal with soft rejection for tf_mismatch and choppy.

    Try the standard path first. If it fails with a soft-convertible reason
    (tf_mismatch or choppy), re-evaluate with relaxed gates and apply penalties.

    Returns:
        (AdaptiveSignal, "")   on success (including soft-penalised paths)
        (None, reason_tag)     on hard block (data gap, iv_spike, etc.)
    """
    # ── Try standard path ─────────────────────────────────────────────────
    partial, reason = evaluate_index_signal_partial(
        params=params,
        df1=df1, df5=df5, df15=df15,
        vix=vix, iv=iv,
        oi_sup=oi_sup, oi_res=oi_res,
        pcr=pcr, smart=smart,
        learning_score_bonus=learning_score_bonus,
    )

    soft_blocks: list[str] = []
    confidence = 1.0

    if partial is not None:
        # Clean pass — no soft blocks
        data = dict(partial)
    elif reason == "tf_mismatch":
        # Allow both tf_mismatch AND choppy — bars blocked by tf_mismatch are often also
        # in a CHOPPY regime (misaligned trends happen when market is directionless).
        # If both conditions are present, both penalties stack: -20 (tf) + -15 (choppy).
        data = _compute_features_and_score(
            params=params,
            df1=df1, df5=df5, df15=df15,
            vix=vix, oi_sup=oi_sup, oi_res=oi_res,
            pcr=pcr, smart=smart, learning_score_bonus=learning_score_bonus,
            allow_tf_mismatch=True, allow_choppy=True,
        )
        if data is None:
            return None, reason
        soft_blocks.append("tf_mismatch")
        confidence *= _CONF_MULT_TF_MISMATCH
        if data.get("mkt_regime") == "CHOPPY":
            soft_blocks.append("choppy_regime")
            confidence *= _CONF_MULT_CHOPPY
    elif reason == "choppy":
        data = _compute_features_and_score(
            params=params,
            df1=df1, df5=df5, df15=df15,
            vix=vix, oi_sup=oi_sup, oi_res=oi_res,
            pcr=pcr, smart=smart, learning_score_bonus=learning_score_bonus,
            allow_tf_mismatch=False, allow_choppy=True,
        )
        if data is None:
            return None, reason
        soft_blocks.append("choppy_regime")
        confidence *= _CONF_MULT_CHOPPY
    else:
        # Hard block: 1m_short, 5m_short, 15m_short, bad_price, iv_spike, etc.
        return None, reason

    # ── Apply soft-block score penalties ─────────────────────────────────
    raw_score      = int(data["score"])
    adjusted_score = raw_score
    if "tf_mismatch" in soft_blocks:
        adjusted_score -= _SOFT_PENALTY_TF_MISMATCH
    if "choppy_regime" in soft_blocks:
        adjusted_score -= _SOFT_PENALTY_CHOPPY
    adjusted_score = max(0, adjusted_score)

    # ── IV Rank score multiplier ──────────────────────────────────────────
    # High IV (expensive premiums) → reduce score so we are more selective.
    # Low IV  (cheap premiums)     → boost score, ideal for option buying.
    # Graceful no-op if iv_rank module unavailable or VIX data missing.
    _iv_rank_pts: int  = 0
    _skew_adj_pts: int = 0
    if vix > 0:
        try:
            from core.iv_rank import get_score_multiplier as _iv_mult_fn
            _iv_mult, _iv_rank_val, _iv_tag = _iv_mult_fn(vix, dict(params.signal_cfg))
            if _iv_mult != 1.0:
                _pre_iv = adjusted_score
                adjusted_score = max(0, min(100, int(round(adjusted_score * _iv_mult))))
                _iv_rank_pts = adjusted_score - _pre_iv
                soft_blocks = list(soft_blocks)  # ensure mutable copy
                if _iv_rank_pts < 0:
                    soft_blocks.append("high_iv")
                reasons.append(f"[IV] {_iv_tag}")
        except Exception:
            pass  # iv_rank is always optional — never block a signal on its failure

    # ── IV Skew score penalty (v2.44 Item 11) ────────────────────────────────
    # EXTREME put skew → penalise CALL signals (market pricing in downside risk).
    # Graceful no-op if iv_rank module / option chain unavailable.
    _skew_adj_pts: int = 0
    if dict(params.signal_cfg).get("iv_skew_enabled", True):
        try:
            from core.iv_rank import compute_iv_skew as _compute_skew
            _option_chain = data.get("option_chain")  # {calls: {strike:prem}, puts: {strike:prem}}
            _spot         = float(data.get("price", 0.0))
            _dte          = int(data.get("dte", 7))
            if _option_chain and _spot > 0:
                _scfg     = dict(params.signal_cfg)
                _skew_dat = _compute_skew(_option_chain, _spot, _dte, _scfg)
                if _skew_dat is not None and _skew_dat.regime == "EXTREME":
                    _pen = int(_scfg.get("iv_skew_extreme_score_penalty", 5))
                    _direction = str(data.get("direction", "CALL")).upper()
                    if _direction in ("CALL", "CE"):
                        _pre_skew    = adjusted_score
                        adjusted_score = max(0, adjusted_score - _pen)
                        _skew_adj_pts  = adjusted_score - _pre_skew
                        soft_blocks    = list(soft_blocks)
                        soft_blocks.append("extreme_put_skew")
                        reasons.append(f"[SKEW] EXTREME put_skew={_skew_dat.put_skew:.1f} pen={_pen:+d}")
        except Exception:
            pass  # iv_skew is always optional

    # ── Session Classifier score adjustment ───────────────────────────────────
    # Applies per-session score delta (e.g. -15 for CHOPPY, +5 for TRENDING).
    # Returns a hard-block soft_blocks entry when session_*_allowed=False in cfg.
    # Graceful no-op if session_classifier module is unavailable.
    _session_adj_pts: int = 0
    if dict(params.signal_cfg).get("session_classifier_enabled", True):
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
            _session = _cls_session(_now_ist().time(), dict(params.signal_cfg))
            if not _sess_allowed_fn(_session, dict(params.signal_cfg)):
                soft_blocks = list(soft_blocks)
                soft_blocks.append(f"session_{_session.value.lower()}_blocked")
            _sess_adj = _sess_adj_fn(_session, dict(params.signal_cfg))
            if _sess_adj != 0:
                _pre_sess   = adjusted_score
                adjusted_score = max(0, min(100, adjusted_score + _sess_adj))
                _session_adj_pts = adjusted_score - _pre_sess
            reasons.append(f"[SESSION] {_session.value} adj={_sess_adj:+d}")
        except Exception:
            pass  # session_classifier is always optional

    # ── ML Signal Classifier score adjustment ─────────────────────────────────
    # Trained on journal win/loss history; boosts high-probability signals and
    # penalises low-probability ones.  Graceful no-op if model not yet trained.
    _ml_adj_pts: int = 0
    _ml_pred_id: str = ""
    if dict(params.signal_cfg).get("ml_classifier_enabled", True):
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
            _scfg = dict(params.signal_cfg)
            _journal_path = _pl.Path(_scfg.get("ml_journal_path", "trade_journal.db"))
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
                _ml_adj, _ml_tag = _prob_adj(_prob, _scfg)
                if _ml_adj != 0:
                    _pre_ml = adjusted_score
                    adjusted_score = max(0, min(100, adjusted_score + _ml_adj))
                    _ml_adj_pts = adjusted_score - _pre_ml
                reasons.append(f"[ML] {_ml_tag}")

                # ML Reasoning (SHAP) and confidence integration
                try:
                    _shap_vals = _explain_pred(_clf, _feat_dict, _scfg)
                    if _shap_vals:
                        from core.ml_classifier import get_top_features as _get_top
                        top_f = _get_top(_shap_vals)
                        _reason_str = " | ".join([f"{k}:{round(v,2)}" for k,v in top_f])
                        _ml_reasoning = f"Top Features: {_reason_str}"

                        # Integrate SHAP values into ML confidence scoring
                        # Calculate confidence based on SHAP value concentration (lower entropy = higher confidence)
                        shap_values = list(_shap_vals.values())
                        if shap_values:
                            # Normalize SHAP values to get probability distribution
                            abs_shap = [abs(v) for v in shap_values]
                            total_abs = sum(abs_shap)
                            if total_abs > 0:
                                prob_dist = [v/total_abs for v in abs_shap]
                                # Calculate entropy (lower entropy = more concentrated = higher confidence)
                                import math
                                entropy = -sum(p * math.log(p) for p in prob_dist if p > 0)
                                # Normalize entropy to 0-1 range (max entropy = log(n_features))
                                max_entropy = math.log(len(prob_dist)) if len(prob_dist) > 1 else 1
                                normalized_entropy = entropy / max_entropy if max_entropy > 0 else 0
                                # SHAP confidence is inverse of normalized entropy (0-1 range)
                                shap_confidence = 1.0 - normalized_entropy

                                # Apply SHAP confidence to ML adjustment (reduce adjustment when SHAP confidence is low)
                                if shap_confidence < 0.5:  # Only reduce if confidence is low
                                    confidence_factor = shap_confidence * 2  # Scale 0-0.5 to 0-1
                                    _ml_adj = int(_ml_adj * confidence_factor)
                                    _ml_tag = f"{_ml_tag} (SHAP conf={shap_confidence:.2f})"
                    else:
                        _ml_reasoning = ""
                except Exception:
                    _ml_reasoning = ""

                # Record prediction for calibration tracking (ml_performance_tracker)
                if _scfg.get("ml_tracker_enabled", True):
                    try:
                        import time as _time_mod

                        from core.ml_performance_tracker import record_prediction as _ml_rec
                        _ml_pred_id = (
                            f"sig_{int(_time_mod.time())}_{data.get('index_name', 'X')}"
                        )
                        _ml_rec(
                            _ml_pred_id, _prob,
                            shap_json=_shap_json(_shap_vals),
                            db_path=_scfg.get("ml_tracker_db_path", "ml_tracker.db"),
                        )
                    except Exception:
                        pass
        except Exception:
            pass  # ml_classifier is always optional

    tier           = classify_tier(adjusted_score)
    direction      = str(data.get("direction", "CALL"))
    regime         = str(data.get("mkt_regime", "NEUTRAL"))
    score_comps    = dict(data.get("score_components") or {})
    score_comps["iv_rank_adj"]   = _iv_rank_pts
    score_comps["iv_skew_adj"]   = _skew_adj_pts
    score_comps["session_adj"]   = _session_adj_pts
    score_comps["ml_adj"]        = _ml_adj_pts
    features       = [k for k, v in score_comps.items() if v > 0]

    reasons: list[str] = [f"{k}={v:+d}pts" for k, v in score_comps.items() if v != 0]
    if soft_blocks:
        reasons += [f"[SOFT] {b}" for b in soft_blocks]

    # ── v2.45 optional score layers (Items 1-4) ──────────────────────────────
    # Each is a thin try/except wrapper — never blocks signal on failure.

    # Item 1: FII/DII institutional flow
    _fii_pts: int = 0
    if dict(params.signal_cfg).get("fii_dii_enabled", False):
        try:
            from core.fii_dii_tracker import FIIDIITracker as _FIITkr
            _fii_tracker = _FIITkr(dict(params.signal_cfg))
            _fii_adj = _fii_tracker.score_adjustment(direction)
            if _fii_adj != 0:
                _pre_fii = adjusted_score
                adjusted_score = max(0, min(100, adjusted_score + _fii_adj))
                _fii_pts = adjusted_score - _pre_fii
        except Exception:
            pass

    # Item 2: Implied move gate (soft block as score penalty)
    _im_pts: int = 0
    if dict(params.signal_cfg).get("implied_move_enabled", False):
        try:
            from core.implied_move import get_implied_move_score_adj as _im_adj_fn
            _sl_mult = float(dict(params.signal_cfg).get("SL_PCT", 0.30))
            _signal_move_pct = _sl_mult * 100
            _im_adj = _im_adj_fn(data.get("_implied_move"), _signal_move_pct, dict(params.signal_cfg))
            if _im_adj != 0:
                _pre_im = adjusted_score
                adjusted_score = max(0, min(100, adjusted_score + _im_adj))
                _im_pts = adjusted_score - _pre_im
        except Exception:
            pass

    # Item 3: GEX regime adjustment
    _gex_pts: int = 0
    if dict(params.signal_cfg).get("gex_enabled", False):
        try:
            from core.gex_analyzer import compute_gex as _cgex
            from core.gex_analyzer import get_gex_score_adj as _gex_adj_fn
            _gex_chain = data.get("option_chain")
            _gex_spot  = float(data.get("price", 0.0))
            _gex_res   = _cgex(_gex_chain, _gex_spot, dict(params.signal_cfg))
            _gex_adj   = _gex_adj_fn(_gex_res, direction, dict(params.signal_cfg))
            if _gex_adj != 0:
                _pre_gex = adjusted_score
                adjusted_score = max(0, min(100, adjusted_score + _gex_adj))
                _gex_pts = adjusted_score - _pre_gex
        except Exception:
            pass

    # Item 4: Regime transition bonus
    _rt_pts: int = 0
    if dict(params.signal_cfg).get("regime_transition_enabled", False):
        try:
            from core.regime_transition_detector import detect_transition as _det_trans
            from core.regime_transition_detector import get_transition_score_adj as _trans_adj
            _adx_ser  = data.get("adx_series", [float(data.get("adx", 0.0))])
            _macd_ser = data.get("macd_hist_series", [])
            _rt_sig   = _det_trans(regime, data.get("prev_regime", regime),
                                   _adx_ser, vix, _macd_ser, dict(params.signal_cfg))
            _rt_adj   = _trans_adj(_rt_sig, dict(params.signal_cfg))
            if _rt_adj != 0:
                _pre_rt = adjusted_score
                adjusted_score = max(0, min(100, adjusted_score + _rt_adj))
                _rt_pts = adjusted_score - _pre_rt
        except Exception:
            pass

    score_comps["fii_dii_adj"]   = _fii_pts
    score_comps["implied_move_adj"] = _im_pts
    score_comps["gex_adj"]       = _gex_pts
    score_comps["regime_trans_adj"] = _rt_pts

    # ── Position sizing ───────────────────────────────────────────────────
    position_spec = PositionSizer.calculate(
        score=adjusted_score,
        tier=tier,
        regime=regime,
        max_lots=max_lots,
        atr=float(data.get("atr", 0.0)),
        capital=capital,
    )

    # ── Signal Confidence Band (v2.44 Item 18) ───────────────────────────────
    _conf_band: SignalConfidenceBand | None = None
    _scfg2 = dict(params.signal_cfg)
    if _scfg2.get("confidence_band_enabled", True):
        try:
            _db_path2  = _scfg2.get("trades_db", "trades.db")
            _session2  = ""
            for _sb in soft_blocks:
                if "session" in _sb:
                    _session2 = _sb
                    break
            _conf_band = compute_confidence_band(
                score=adjusted_score,
                regime=regime,
                session=_session2,
                direction=direction,
                db_path=str(_db_path2),
                cfg=_scfg2,
            )
        except Exception:
            pass  # always optional

    # ── Apply max penalty cap (v2.45: safety guard) ────────────────────────────
    # Total penalty (adjusted_score - raw_score) must not exceed config maximum.
    # This prevents penalty stacking from suppressing valid signals.
    _max_penalty = int(_scfg.get("ADAPTIVE_SIGNAL_MAX_TOTAL_PENALTY", -50))
    total_penalty = adjusted_score - raw_score
    if total_penalty < _max_penalty:
        old_score = adjusted_score
        adjusted_score = max(0, raw_score + _max_penalty)  # Clamp to max penalty
        if _scfg.get("ADAPTIVE_SIGNAL_PENALTY_ALERT_THRESHOLD"):
            _pen_alert_thr = float(_scfg.get("ADAPTIVE_SIGNAL_PENALTY_ALERT_THRESHOLD", 0.6))
            _rej_rate = total_penalty / max(1, raw_score) if raw_score > 0 else 0
            if _rej_rate < -_pen_alert_thr:  # More than 60% of score rejected
                log.warning(
                    "[ADAPTIVE] Penalty cap applied: %d -> %d (total_penalty=%d, raw=%d)",
                    old_score, adjusted_score, total_penalty, raw_score
                )
        # Don't reject signal; just cap the penalty

    return AdaptiveSignal(
        tier=tier,
        score=adjusted_score,
        raw_score=raw_score,
        confidence=round(confidence, 3),
        direction=direction,
        regime=regime,
        soft_blocks=soft_blocks,
        reasons=reasons,
        score_components=score_comps,
        features=features,
        reasoning=locals().get("_ml_reasoning", ""),
        atr=float(data.get("atr", 0.0)),
        rsi=float(data.get("rsi", 50.0)),
        adx=float(data.get("adx", 0.0)),
        vwap=float(data.get("vwap", 0.0)),
        vol_ratio=float(data.get("vol_ratio", 0.0)),
        price=float(data.get("price", 0.0)),
        macd=dict(data.get("macd") or {}),
        risk=_build_risk_dict(tier),
        position_spec=position_spec,
        ml_pred_id=_ml_pred_id,
        confidence_band=_conf_band,
    ), ""
