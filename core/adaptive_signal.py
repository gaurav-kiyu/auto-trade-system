"""Adaptive signal evaluator - soft-rejection wrapper around evaluate_index_signal_partial.

Hard rejections in evaluate_index_signal_partial (tf_mismatch, choppy) are converted
to score penalties + confidence reduction instead of returning None. This lets the
tiered system trade partial setups at reduced position size rather than skip entirely.

Hard blocks that stay hard (genuine data gaps - no signal is possible):
    1m_short, 5m_short, 15m_short, partial_drop, bad_price, iv_spike

Soft-converted blocks (traded with penalty):
    tf_mismatch  → -20 score, confidence × 0.60, direction from stronger TF
    choppy       → -15 score, confidence × 0.70

The returned AdaptiveSignal drives position sizing via PositionSizer and carries
tier-specific risk/execution parameters from TierRules.
"""

from __future__ import annotations

__all__ = [
    "AdaptiveSignal",
    "SignalConfidenceBand",
    "TimeframeAgreement",
    "compute_confidence_band",
    "compute_timeframe_agreement",
    "evaluate_adaptive_signal",
]

import datetime
import logging
import sqlite3
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from core.feature_engine import FeatureEngine
from core.market_calc import detect_regime_and_adx as mc_detect_regime_and_adx
from core.pure_index_signal import (
    PureIndexSignalParams,
    _drop_partial_candle,  # resampling artifact cleaner
    _macd_bonus_delta,  # MACD histogram direction check
    compute_index_score,
    evaluate_dual_direction_signal,
)
from core.services.risk_service import PositionSizer, PositionSpec  # consolidated
from core.signal_utils import breakout_strength_ok
from core.tier_engine import TIER_RULES, classify_tier, tier_bounds_from_config

_log = logging.getLogger(__name__)

# ── Soft-rejection penalty constants ─────────────────────────────────────────
# v2.54: Tightened to reduce false positives. Tf_mismatch penalty increased 20→25,
# choppy increased 15→18, confidence multipliers reduced to penalise weak signals harder.
_SOFT_PENALTY_TF_MISMATCH: int = 25
_SOFT_PENALTY_CHOPPY: int = 18
_CONF_MULT_TF_MISMATCH: float = 0.50
_CONF_MULT_CHOPPY: float = 0.60

# ── Conviction filter threshold (v2.54) ──────────────────────────────────────
# When high_conviction_mode is enabled, additional gates raise the entry bar:
#   - Minimum ML win probability (default 0.50)
#   - Minimum volume ratio (default 1.3x)
#   - Minimum adjusted score (default 70)
#   - Block soft-converted tf_mismatch/choppy signals entirely
_HIGH_CONVICTION_ML_MIN: float = 0.50
_HIGH_CONVICTION_VOL_MIN: float = 1.3
_HIGH_CONVICTION_SCORE_MIN: int = 70


# ── Result dataclass ──────────────────────────────────────────────────────────
@dataclass
class AdaptiveSignal:
    # Classification
    tier: str  # STRONG / MODERATE / WEAK / IGNORE
    score: int  # final adjusted score
    raw_score: int  # score before soft-block penalties
    confidence: float  # 0.0-1.0 (1.0 = no soft blocks)
    direction: str  # CALL / PUT

    # Context
    regime: str
    soft_blocks: list[str]  # e.g. ["tf_mismatch", "choppy_regime"]
    reasons: list[str]  # human-readable component breakdown
    score_components: dict[str, int]  # per-component point contribution
    features: list[str]  # component keys with positive points

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
    ml_probability: float = 0.5

    # ML reasoning explanation (top features contributing to the prediction)
    reasoning: str = ""

    # Wilson 95% confidence interval for win rate at this signal's parameters
    # (None when confidence_band_enabled=False or insufficient trade history)
    confidence_band: SignalConfidenceBand | None = None


# ── Confidence Band (v2.44 Item 18) ──────────────────────────────────────────


@dataclass
class SignalConfidenceBand:
    """Wilson 95% confidence interval for historical win rate in a signal bucket."""

    n_trades: int
    n_wins: int
    win_rate: float  # point estimate
    ci_low: float  # 95% CI lower bound
    ci_high: float  # 95% CI upper bound
    score_bin: str = ""
    regime: str = ""
    session: str = ""
    direction: str = ""

    def __str__(self) -> str:
        return f"[CI: {self.ci_low * 100:.0f}-{self.ci_high * 100:.0f}%] n={self.n_trades}"


def _wilson_ci(wins: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Return (low, high) Wilson score interval for wins/n at z-sigma."""
    if n == 0:
        return 0.0, 1.0
    p = wins / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    margin = z * (p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5 / denom
    return max(0.0, center - margin), min(1.0, center + margin)


def compute_confidence_band(
    score: int,
    regime: str,
    session: str,
    direction: str,
    db_path: str,
    cfg: dict[str, Any],
) -> SignalConfidenceBand | None:
    """Query trades.db and compute a Wilson 95% CI for win rate in the matching bucket.

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

    bin_w = int(cfg.get("confidence_band_score_bin_width", 5))
    lo, hi = score - bin_w, score + bin_w

    from pathlib import Path as _Path

    from core.db_utils import get_connection as _get_conn

    p = _Path(db_path)
    if not p.is_file():
        return None

    try:
        conn = _get_conn(str(p), timeout=3, row_factory=False)
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

        pnls = [float(r[0]) for r in rows]
        n = len(pnls)
        wins = sum(1 for p in pnls if p > 0)
        wr = wins / n
        ci_lo, ci_hi = _wilson_ci(wins, n)

        bin_label = f"{lo}-{hi}"
        return SignalConfidenceBand(
            n_trades=n,
            n_wins=wins,
            win_rate=round(wr, 4),
            ci_low=round(ci_lo, 4),
            ci_high=round(ci_hi, 4),
            score_bin=bin_label,
            regime=regime,
            session=session,
            direction=direction,
        )
    except (sqlite3.Error, OSError, ValueError, TypeError, AttributeError):
        return None


# ── Timeframe Agreement (v2.45 Item 5) ───────────────────────────────────────


@dataclass
class TimeframeAgreement:
    """Agreement score across 1m / 5m / 15m timeframes."""

    agreement_score: float  # 0.0 (full divergence) - 1.0 (all agree)
    bullish_count: int  # how many TFs are bullish
    bearish_count: int  # how many TFs are bearish
    divergence_detail: str  # human-readable summary


def compute_timeframe_agreement(
    dir_1m: str,
    dir_5m: str,
    dir_15m: str,
    cfg: dict[str, Any] | None = None,
) -> TimeframeAgreement:
    """Compute agreement across 1m, 5m, 15m trend directions.

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
        agreement_score=score,
        bullish_count=bull,
        bearish_count=bear,
        divergence_detail=detail,
    )


def _apply_conviction_filter(
    score: int,
    ml_prob: float,
    vol_ratio: float,
    soft_blocks: list[str],
    config: dict[str, Any],
) -> tuple[bool, str]:
    """Optional high-conviction quality gate (v2.54).

    When ``high_conviction_mode`` is enabled in config, this filter applies
    additional entry requirements that raise the quality bar:

    1. ML win probability >= ``HIGH_CONVICTION_ML_THRESHOLD`` (default 0.50)
    2. Volume ratio >= ``HIGH_CONVICTION_VOL_RATIO_MIN`` (default 1.3)
    3. Adjusted score >= ``HIGH_CONVICTION_SCORE_MIN`` (default 70)
    4. No soft-converted tf_mismatch or choppy blocks

    Returns:
        (True, "") if all gates pass
        (False, reason_tag) if any gate fails

    """
    if not config.get("high_conviction_mode", False):
        return True, ""

    ml_min = float(config.get("HIGH_CONVICTION_ML_THRESHOLD", _HIGH_CONVICTION_ML_MIN))
    vol_min = float(config.get("HIGH_CONVICTION_VOL_RATIO_MIN", _HIGH_CONVICTION_VOL_MIN))
    score_min = int(config.get("HIGH_CONVICTION_SCORE_MIN", _HIGH_CONVICTION_SCORE_MIN))

    # Gate 1: Minimum ML win probability
    if ml_prob < ml_min:
        return False, f"conviction_ml_prob_{ml_prob:.2f}_below_{ml_min:.2f}"

    # Gate 2: Minimum volume ratio
    if vol_ratio < vol_min:
        return False, f"conviction_vol_ratio_{vol_ratio:.2f}_below_{vol_min:.2f}"

    # Gate 3: Minimum adjusted score
    if score < score_min:
        return False, f"conviction_score_{score}_below_{score_min}"

    # Gate 4: No soft-converted tf_mismatch or choppy blocks
    for sb in soft_blocks:
        if sb in ("tf_mismatch", "choppy_regime", "tf_divergence_fallback"):
            return False, f"conviction_blocked_soft_{sb}"

    return True, ""


def _build_risk_dict(tier: str) -> dict[str, Any]:
    rules = TIER_RULES.get(tier)
    if rules is None:
        return {}
    return {
        "sl_mult_adj": rules.sl_mult_adj,
        "tp_mult_adj": rules.tp_mult_adj,
        "trail_enabled": rules.trail_enabled,
        "trail_activate_pct": rules.trail_activate_pct,
        "trail_from_peak_pct": rules.trail_from_peak_pct,
        "max_bars_mult": rules.max_bars_mult,
        "partial_exit_enabled": rules.partial_exit_enabled,
        "partial_exit_pct": rules.partial_exit_pct,
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
    force_direction: str | None = None,
) -> dict[str, Any] | None:
    """Core feature extraction + scoring, with selectable relaxation of tf and regime gates.
    Returns a partial-signal dict, or None if data is genuinely insufficient.
    """
    sc = params.signal_cfg
    min15 = int(
        sc.get("EARLY_SESSION_MIN_15M", params.min15_early)
        if params.is_early_session
        else sc.get("NORMAL_SESSION_MIN_15M", params.min15_normal),
    )

    if df1 is None or len(df1) < 30:
        return None
    if df5 is None or len(df5) < 10:
        return None
    if df15 is None or len(df15) < min15:
        return None

    df1 = _drop_partial_candle(df1)
    df5 = _drop_partial_candle(df5)
    if df1 is None or len(df1) < 30 or df5 is None or len(df5) < 10:
        return None

    t5 = FeatureEngine.ema_trend(df5)
    t15 = FeatureEngine.ema_trend(df15)

    if force_direction is not None:
        # Direction is forced - use its corresponding trend for scoring
        direction_tf = "UP" if force_direction == "CALL" else "DOWN"
    elif not allow_tf_mismatch:
        if t5 == "FLAT" or t15 == "FLAT" or t5 != t15:
            return None
        direction_tf = t5
    else:
        # Pick direction from the stronger (5m) timeframe; fall back to 15m
        if t5 == "FLAT" and t15 == "FLAT":
            return None  # no direction at all - irrecoverable
        direction_tf = t5 if t5 != "FLAT" else t15

    price = FeatureEngine.get_price(df1)
    if price <= 0:
        return None

    vwap_val = FeatureEngine.get_vwap(df1)
    atr = FeatureEngine.get_atr(df1)
    vol_ratio = FeatureEngine.get_vol_ratio(df1)
    d1 = FeatureEngine.price_delta(df1, 10)
    d5_ = FeatureEngine.price_delta(df5, 3)
    rsi_val = FeatureEngine.get_rsi(df5)

    rp = params.regime
    mkt_regime, avg_adx = mc_detect_regime_and_adx(
        df5,
        df15,
        vix=vix,
        vix_block_threshold=rp.vix_block_threshold,
        adx_trend_threshold=rp.adx_trend_threshold,
        adx_chop_threshold=rp.adx_chop_threshold,
    )

    if mkt_regime == "CHOPPY" and not allow_choppy:
        return None

    direction = force_direction if force_direction is not None else ("CALL" if direction_tf == "UP" else "PUT")

    # Compute the component score without an early 0-100 clamp.  The previous
    # implementation capped the base score at 100 and then added several more
    # bonuses (MACD/ADX/breakout/ORB/etc.), making 100 a saturation bucket rather
    # than a calibrated high-conviction score.  Retain the uncapped component
    # total and normalize it once, at the boundary of this scoring stage.
    _base_raw = compute_index_score(
        direction_tf,
        t15,
        price,
        vwap_val,
        atr,
        vol_ratio,
        d1,
        d5_,
        pcr,
        smart,
        signal_cfg=sc,
        vol_ratio_min=params.vol_ratio_min,
        learning_score_bonus=learning_score_bonus,
        rsi=rsi_val,
        return_raw=True,
    )

    # Component breakdown - mirrors pure_index_signal.py formulas exactly.
    _vwap_ref_ = max(float(vwap_val), 1.0)
    if (direction_tf == "UP" and price > _vwap_ref_) or (direction_tf == "DOWN" and price < _vwap_ref_):
        _vwap_dist_ = abs(price - _vwap_ref_) / _vwap_ref_
        _vwap_pts = min(20, 8 + int(min(1.0, _vwap_dist_ / 0.005) * 12))
    else:
        _vwap_pts = 0
    _d1_pts = 15 if (direction_tf == "UP" and d1 > 0) or (direction_tf == "DOWN" and d1 < 0) else 0
    _d5_pts = 10 if (direction_tf == "UP" and d5_ > 0) or (direction_tf == "DOWN" and d5_ < 0) else 0
    if vol_ratio >= params.vol_ratio_min:
        _vol_excess_ = (vol_ratio - params.vol_ratio_min) / max(params.vol_ratio_min, 0.5)
        _vol_pts = min(14, 4 + int(min(1.0, _vol_excess_) * 10))
    else:
        _vol_pts = 0
    _rsi_b = int(sc.get("INDEX_RSI_BONUS", 8))
    _rsi_hl_c = float(sc.get("INDEX_RSI_HEALTHY_LOW_CALL", 40))
    _rsi_hh_c = float(sc.get("INDEX_RSI_HEALTHY_HIGH_CALL", 70))
    _rsi_hl_p = float(sc.get("INDEX_RSI_HEALTHY_LOW_PUT", 30))
    _rsi_hh_p = float(sc.get("INDEX_RSI_HEALTHY_HIGH_PUT", 60))
    _rsi_pts = (
        _rsi_b
        if (direction_tf == "UP" and _rsi_hl_c <= rsi_val <= _rsi_hh_c)
        or (direction_tf == "DOWN" and _rsi_hl_p <= rsi_val <= _rsi_hh_p)
        else 0
    )
    _sm_pts = (
        10 if (direction_tf == "UP" and smart == "BULLISH") or (direction_tf == "DOWN" and smart == "BEARISH") else 0
    )
    _pcr_bull = float(sc.get("PCR_BULLISH", 1.2))
    _pcr_bear = float(sc.get("PCR_BEARISH", 0.8))
    _pcr_pts = 5 if (direction_tf == "UP" and pcr > _pcr_bull) or (direction_tf == "DOWN" and pcr < _pcr_bear) else 0

    score_components: dict[str, int] = {
        "tf_aligned": 20 if t5 == t15 else 0,
        "vwap": _vwap_pts,
        "d1_momentum": _d1_pts,
        "d5_momentum": _d5_pts,
        "volume": _vol_pts,
        "atr_floor": 5 if atr > float(sc.get("ATR_MIN_THRESHOLD", 0.5)) else 0,
        "rsi_bonus": _rsi_pts,
        "smart_money": _sm_pts,
        "pcr": _pcr_pts,
        "learning_bonus": max(0, int(learning_score_bonus)),
    }

    macd_raw = FeatureEngine.get_macd(df5)
    macd_b = int(sc.get("MACD_BONUS", 5))
    macd_delta = _macd_bonus_delta(direction, macd_raw, macd_b)
    score_components["macd_bonus"] = macd_delta

    breakout_ok = breakout_strength_ok(df1)
    _breakout_bonus = int(sc.get("BREAKOUT_BONUS", 8))
    bk_pts = _breakout_bonus if breakout_ok else -4
    score_components["breakout"] = bk_pts

    _adx_pen_thr = float(sc.get("ADX_PENALTY_THRESHOLD", 12))
    _adx_pen = int(sc.get("ADX_PENALTY_POINTS", 5))
    adx_pen_pts = -_adx_pen if avg_adx > 0 and avg_adx < _adx_pen_thr else 0
    score_components["adx_penalty"] = adx_pen_pts

    _adx_trend_thr = float(sc.get("ADX_TREND_THRESHOLD", 20))
    _adx_trend_b = int(sc.get("ADX_TREND_BONUS_POINTS", 5))
    _adx_trend_pts = _adx_trend_b if avg_adx >= _adx_trend_thr else 0
    score_components["adx_trend_bonus"] = _adx_trend_pts

    _hv_pen = int(sc.get("REGIME_SCORE_PENALTY_HV", 8))
    _ev_pen = int(sc.get("REGIME_SCORE_PENALTY_EVENT", 10))
    _reg_pen = -_hv_pen if mkt_regime == "HIGH_VOLATILITY" else (-_ev_pen if mkt_regime == "EVENT" else 0)
    score_components["regime_penalty"] = _reg_pen

    _reclaim_b = int(sc.get("VWAP_RECLAIM_BONUS", 7))
    _reclaim_pts = 0
    if _vwap_pts > 0 and vwap_val > 0 and len(df1) >= 5:
        _recent_closes = df1["Close"].iloc[-5:-1].values
        _was_wrong = (
            any(c < vwap_val for c in _recent_closes)
            if direction == "CALL"
            else any(c > vwap_val for c in _recent_closes)
        )
        if _was_wrong:
            _reclaim_pts = _reclaim_b
    score_components["vwap_reclaim"] = _reclaim_pts

    _orb_b = int(sc.get("ORB_BONUS", 10))
    _orb_pts = 0
    try:
        if _orb_b > 0 and hasattr(df1.index, "time"):
            _t915 = datetime.time(9, 15)
            _t930 = datetime.time(9, 30)
            _idx_times = [t.time() if hasattr(t, "time") else t for t in df1.index]
            _orb_df = df1.loc[[_t915 <= t < _t930 for t in _idx_times]]
            if len(_orb_df) >= 5:
                _orb_high = float(_orb_df["High"].max())
                _orb_low = float(_orb_df["Low"].min())
                if (direction == "CALL" and price > _orb_high * 1.001) or (direction == "PUT" and price < _orb_low * 0.999):
                    _orb_pts = _orb_b
    except (ValueError, TypeError, AttributeError, KeyError, IndexError):
        _log.debug("[SIGNAL] ORB bonus skipped")
    score_components["orb_bonus"] = _orb_pts

    component_raw_score = int(sum(score_components.values()))
    # Keep the canonical base ceiling configurable.  With the v18 defaults the
    # theoretical positive base is 150; 100 therefore means the full base score,
    # not merely "any raw value >= 100".
    base_max = max(100, int(sc.get("COMPOSITE_BASE_MAX_SCORE", 150)))
    normalized_base_score = max(0, min(100, round(component_raw_score * 100.0 / base_max)))
    # Sanity-check the independently calculated component total against the raw
    # scorer. A mismatch is observable rather than silently ignored.
    _base_component_total = sum(
        score_components.get(k, 0)
        for k in (
            "tf_aligned", "vwap", "d1_momentum", "d5_momentum", "volume",
            "atr_floor", "rsi_bonus", "smart_money", "pcr", "learning_bonus"
        )
    )
    if abs(int(_base_raw) - int(_base_component_total)) > 1:
        reasons.append(
            f"[SCORE_AUDIT] base_components={int(_base_component_total)} scorer_raw={int(_base_raw)}"
        )

    return {
        "score": normalized_base_score,
        "raw_score": component_raw_score,
        "base_score": normalized_base_score,
        "score_components": score_components,
        "direction": direction,
        "mkt_regime": mkt_regime,
        "adx": avg_adx,
        "rsi": rsi_val,
        "vwap": vwap_val,
        "atr": atr,
        "vol_ratio": vol_ratio,
        "price": price,
        "macd": macd_raw,
        "breakout_ok": breakout_ok,
        "t5": t5,
        "t15": t15,
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
    dual_direction_enabled: bool = True,
    counter_trend_penalty: int = 10,
    mean_reversion_enabled: bool = True,
    tf_divergence_fallback: bool = True,
) -> tuple[AdaptiveSignal | None, str]:
    """Evaluate signal with dual-direction scoring and soft rejection.

    Uses evaluate_dual_direction_signal() as the primary path (evaluates both
    CALL and PUT, picks the best with counter-trend penalty and mean-reversion
    waive). Falls back to evaluate_index_signal_partial() with soft-rejection
    gates if the dual path fails with tf_mismatch or choppy.

    Returns:
        (AdaptiveSignal, "")   on success (including soft-penalised paths)
        (None, reason_tag)     on hard block (data gap, iv_spike, etc.)

    """
    sc = dict(params.signal_cfg)
    reasons: list[str] = []
    soft_blocks: list[str] = []
    confidence = 1.0
    data: dict[str, Any] | None = None

    # ── Try dual-direction path first (evaluates both CALL and PUT) ──────────
    dual_partial, reason = evaluate_dual_direction_signal(
        params=params,
        df1=df1,
        df5=df5,
        df15=df15,
        vix=vix,
        iv=iv,
        oi_sup=oi_sup,
        oi_res=oi_res,
        pcr=pcr,
        smart=smart,
        learning_score_bonus=learning_score_bonus,
        dual_direction_enabled=dual_direction_enabled,
        counter_trend_penalty=counter_trend_penalty,
        mean_reversion_enabled=mean_reversion_enabled,
        tf_divergence_fallback=tf_divergence_fallback,
    )

    if dual_partial is not None:
        data = dict(dual_partial)
        if data.get("_dual_direction_evaluated"):
            reasons.append(
                f"[DUAL] chosen={data.get('_dual_chosen', '?')} "
                f"primary={data.get('_dual_primary_score', 0)} "
                f"opponent={data.get('_dual_opponent_score', 0)} "
                f"pen={data.get('_dual_penalty', 0)}"
            )
        if data.get("_tf_divergence_fallback"):
            soft_blocks.append("tf_divergence_fallback")
            confidence *= _CONF_MULT_TF_MISMATCH
            reasons.append(f"[TF] divergence fallback → {data['_tf_divergence_fallback']}")
    elif reason == "tf_mismatch":
        # Fall back to soft-rejection path - allow both tf_mismatch AND choppy
        data = _compute_features_and_score(
            params=params,
            df1=df1,
            df5=df5,
            df15=df15,
            vix=vix,
            oi_sup=oi_sup,
            oi_res=oi_res,
            pcr=pcr,
            smart=smart,
            learning_score_bonus=learning_score_bonus,
            allow_tf_mismatch=True,
            allow_choppy=True,
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
            df1=df1,
            df5=df5,
            df15=df15,
            vix=vix,
            oi_sup=oi_sup,
            oi_res=oi_res,
            pcr=pcr,
            smart=smart,
            learning_score_bonus=learning_score_bonus,
            allow_tf_mismatch=False,
            allow_choppy=True,
        )
        if data is None:
            return None, reason
        soft_blocks.append("choppy_regime")
        confidence *= _CONF_MULT_CHOPPY
    else:
        # Hard block: 1m_short, 5m_short, 15m_short, bad_price, iv_spike, etc.
        return None, reason

    # ── Apply soft-block score penalties ─────────────────────────────────
    raw_score = int(data.get("raw_score", data["score"]))
    # `score` is the normalized 0-100 base score.  `raw_score` is retained
    # separately for audit/analytics and must never be used as the 0-100
    # admission score.
    adjusted_score = int(data.get("base_score", data["score"]))
    baseline_score = adjusted_score
    if "tf_mismatch" in soft_blocks:
        adjusted_score -= _SOFT_PENALTY_TF_MISMATCH
    if "choppy_regime" in soft_blocks:
        adjusted_score -= _SOFT_PENALTY_CHOPPY
    adjusted_score = max(0, adjusted_score)

    # ── IV Rank score multiplier ──────────────────────────────────────────
    from core.adaptive_signal_score_adjusters import apply_iv_rank_adjustment

    adjusted_score, _iv_rank_pts = apply_iv_rank_adjustment(
        vix=vix,
        score=adjusted_score,
        config=sc,
        soft_blocks=soft_blocks,
        reasons=reasons,
    )  # ── IV Skew score penalty (v2.44 Item 11) ────────────────────────────────
    from core.adaptive_signal_score_adjusters import apply_iv_skew_adjustment

    adjusted_score, _skew_adj_pts = apply_iv_skew_adjustment(
        data=data,
        score=adjusted_score,
        config=sc,
        soft_blocks=soft_blocks,
        reasons=reasons,
    )  # ── Session Classifier score adjustment ───────────────────────────────────
    from core.adaptive_signal_score_adjusters import apply_session_adjustment

    adjusted_score, _session_adj_pts = apply_session_adjustment(
        score=adjusted_score,
        config=sc,
        soft_blocks=soft_blocks,
        reasons=reasons,
    )
    # Session hard-block (opt-in, default OFF — see session_hard_block_enabled).
    # apply_session_adjustment() only tags a session_*_blocked soft_block;
    # nothing downstream previously consumed that tag, so the documented
    # "hard block" (core/session_classifier.py::session_entry_allowed) was
    # silently only ever a score penalty in the live pipeline. When enabled,
    # this restores the documented behavior using the same hard-block idiom
    # already used above for iv_spike/bad_price/etc.
    if sc.get("session_hard_block_enabled", False):
        for _sb in soft_blocks:
            if _sb.startswith("session_") and _sb.endswith("_blocked"):
                return None, _sb
    # ── ML Signal Classifier score adjustment ─────────────────────────────────
    from core.adaptive_signal_score_adjusters import apply_ml_adjustment

    ml_config = dict(params.signal_cfg)
    adjusted_score, _ml_adj_pts, _ml_prob, _ml_pred_id, _ml_reasoning = apply_ml_adjustment(
        data=data,
        score=adjusted_score,
        config=ml_config,
        vix=vix,
        pcr=pcr,
        soft_blocks=soft_blocks,
        reasons=reasons,
    )

    _strong_min, _moderate_min, _weak_min = tier_bounds_from_config(sc)

    # Intraday session win-rate adaptive score threshold (opt-in, default
    # OFF — same core.intraday_performance_monitor singleton the position-
    # sizing half in position_service.py uses; see intraday_performance_monitor_enabled).
    # Raises the bar for STRONG/MODERATE on a CAUTIOUS/DEFENSIVE session
    # instead of silently only affecting a display multiplier no one reads.
    if sc.get("intraday_performance_monitor_enabled", False):
        try:
            from core.intraday_performance_monitor import get_intraday_monitor
            _intraday_boost = get_intraday_monitor(sc).get_current_params().score_threshold_boost
            _strong_min += _intraday_boost
            _moderate_min += _intraday_boost
        except (ValueError, TypeError, KeyError, AttributeError, IndexError, OSError):
            pass

    # Signal Refiner (opt-in, default OFF — core/signal_refiner.py). Fully
    # built and unit-tested (regime-aware threshold adjustment, multi-
    # indicator confirmation, false-signal filter) but never called from the
    # live pipeline (see REGIME_AWARE_THRESHOLDS_ENABLED / FALSE_SIGNAL_
    # FILTER_ENABLED). Its own sub-config is intentionally strict by design
    # (e.g. VOLATILITY_RSI_CONFIRM_THRESHOLD=45 blocks all but extreme RSI
    # readings, confirmed intentional by its own tests) — gated behind one
    # fresh master switch rather than activated silently via its already-
    # true sub-flags, so today's signal volume is unchanged until an admin
    # deliberately opts in after reviewing/tuning those sub-thresholds.
    if sc.get("signal_refiner_enabled", False):
        try:
            from core.iv_rank import get_iv_rank
            from core.signal_refiner import create_signal_refiner

            _refiner = create_signal_refiner(sc)
            _regime_now = str(data.get("mkt_regime", "NEUTRAL"))
            _strong_min = _refiner.get_regime_adjusted_threshold(_strong_min, _regime_now)
            _moderate_min = _refiner.get_regime_adjusted_threshold(_moderate_min, _regime_now)
            _weak_min = _refiner.get_regime_adjusted_threshold(_weak_min, _regime_now)

            _macd_data = data.get("macd") or {}
            _macd_trend = "NEUTRAL"
            if isinstance(_macd_data, dict):
                _mh, _ml, _ms = (float(_macd_data.get(k) or 0) for k in ("histogram", "macd", "signal"))
                if _mh > 0 and _ml > _ms:
                    _macd_trend = "BULLISH"
                elif _mh < 0 and _ml < _ms:
                    _macd_trend = "BEARISH"

            _iv_rank_now = get_iv_rank(vix, sc)
            if _iv_rank_now >= 0:
                _refiner_blocked, _refiner_reason = _refiner.should_block_signal(
                    score=adjusted_score,
                    regime=_regime_now,
                    iv_rank=_iv_rank_now,
                    rsi=float(data.get("rsi", 50.0)),
                    macd=_macd_trend,
                    adx=float(data.get("adx", 0.0)),
                    vix=vix,
                )
                if _refiner_blocked:
                    return None, f"signal_refiner_{_refiner_reason}"
        except (ValueError, TypeError, KeyError, AttributeError, IndexError, OSError) as _refiner_err:
            _log.debug("Signal refiner check failed (fail-open, signal unaffected): %s", _refiner_err)

    tier = classify_tier(adjusted_score, strong_min=_strong_min, moderate_min=_moderate_min, weak_min=_weak_min)
    direction = str(data.get("direction", "CALL"))
    regime = str(data.get("mkt_regime", "NEUTRAL"))
    score_comps = dict(data.get("score_components") or {})
    score_comps["iv_rank_adj"] = _iv_rank_pts
    score_comps["iv_skew_adj"] = _skew_adj_pts
    score_comps["session_adj"] = _session_adj_pts
    score_comps["ml_adj"] = _ml_adj_pts
    features = [k for k, v in score_comps.items() if v > 0]

    reasons += [f"{k}={v:+d}pts" for k, v in score_comps.items() if v != 0]
    if soft_blocks:
        reasons += [
            f"[SOFT] {b}" for b in soft_blocks
        ]  # ── v2.45 optional score layers (Items 1-4) ──────────────────────────────
    v245_config = dict(params.signal_cfg)

    # Item 1: FII/DII institutional flow
    from core.adaptive_signal_score_adjusters import apply_fii_dii_adjustment

    adjusted_score, _fii_pts = apply_fii_dii_adjustment(direction, adjusted_score, v245_config)

    # Item 2: Implied move gate
    from core.adaptive_signal_score_adjusters import apply_implied_move_adjustment

    adjusted_score, _im_pts = apply_implied_move_adjustment(data, adjusted_score, v245_config)

    # Item 3: GEX regime adjustment
    from core.adaptive_signal_score_adjusters import apply_gex_adjustment

    adjusted_score, _gex_pts = apply_gex_adjustment(data, direction, adjusted_score, v245_config)

    # Item 4: Regime transition bonus
    from core.adaptive_signal_score_adjusters import apply_regime_transition_adjustment

    adjusted_score, _rt_pts = apply_regime_transition_adjustment(regime, data, vix, adjusted_score, v245_config)

    # Item 5: Mean Reversion score adjustment
    from core.adaptive_signal_score_adjusters import apply_mean_reversion_adjustment

    adjusted_score, _mr_pts = apply_mean_reversion_adjustment(data, adjusted_score, sc, soft_blocks, reasons, df1=df1)

    # Item 6: MA Crossover score adjustment (v2.54)
    from core.adaptive_signal_score_adjusters import apply_ma_crossover_adjustment

    adjusted_score, _ma_pts = apply_ma_crossover_adjustment(data, adjusted_score, sc, soft_blocks, reasons, df1=df1)

    score_comps["fii_dii_adj"] = _fii_pts
    score_comps["implied_move_adj"] = _im_pts
    score_comps["gex_adj"] = _gex_pts
    score_comps["regime_trans_adj"] = _rt_pts
    score_comps["mean_rev_adj"] = _mr_pts
    score_comps["ma_crossover_adj"] = _ma_pts

    # ── Conviction filter (v2.54) ────────────────────────────────────────────
    # When high_conviction_mode is enabled, this additional gate filters out
    # marginal signals that fail ML probability, volume, score, or soft-block checks.
    # This is the key enhancement for higher win rate — it lets through only the
    # highest-quality setups while rejecting borderline entries.
    # Uses _ml_prob captured from the ML classifier section above (default 0.5).
    _conviction_ok, _conviction_reason = _apply_conviction_filter(
        score=adjusted_score,
        ml_prob=_ml_prob,
        vol_ratio=float(data.get("vol_ratio", 0.0)),
        soft_blocks=soft_blocks,
        config=sc,
    )
    if not _conviction_ok:
        log_msg = f"[CONVICTION] {_conviction_reason}"
        _log.info("Signal blocked by conviction filter: %s", _conviction_reason)
        soft_blocks = list(soft_blocks)
        soft_blocks.append(f"conviction_blocked_{_conviction_reason}")
        reasons.append(log_msg)
        # When high-conviction mode is explicitly enabled, this is an admission
        # gate, not merely a reporting annotation.
        return None, f"conviction_{_conviction_reason}"

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
            _db_path2 = _scfg2.get("trades_db", "db/trades.db")
            _session2 = ""
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
        except (ValueError, TypeError, IndexError):
            _log.debug("[SIGNAL] Confidence band skipped")

    # ── Apply max penalty cap (v2.45: safety guard) ────────────────────────────
    from core.adaptive_signal_score_adjusters import apply_max_penalty_cap

    adjusted_score = apply_max_penalty_cap(adjusted_score, baseline_score, sc)
    tier = classify_tier(adjusted_score, strong_min=_strong_min, moderate_min=_moderate_min, weak_min=_weak_min)

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
        ml_probability=round(float(_ml_prob), 4),
        confidence_band=_conf_band,
    ), ""
