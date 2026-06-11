"""
Pure, deterministic index signal evaluation (no I/O, no globals).

Used by live `index_app.index_trader` after data gates and by the candle backtester.
Orchestrator supplies OI/IV/VIX, regime thresholds, and learning score bonus; threshold
comparison stays in the orchestrator/backtest driver so adaptive / risk context stays
out of this module.
"""

from __future__ import annotations

import datetime
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import pandas as pd
import signal_engine as SE

from core.feature_engine import FeatureEngine
from core.market_calc import detect_regime_and_adx as mc_detect_regime_and_adx
from core.utils_numeric import safe_num


def _bar_signal_ts(df: pd.DataFrame) -> float:
    if df is None or len(df) < 1:
        return 0.0
    idx = df.index[-1]
    if hasattr(idx, "timestamp"):
        try:
            return float(idx.timestamp())
        except (AttributeError, ValueError, TypeError):
            return 0.0
    return 0.0


def _drop_partial_candle(df: pd.DataFrame | None) -> pd.DataFrame | None:
    if df is None or len(df) < 2:
        return df
    try:
        if float(df["Volume"].iloc[-1]) == 0 and float(df["Volume"].iloc[-2]) > 0:
            return df.iloc[:-1]
    except (KeyError, ValueError, TypeError, IndexError) as _candle_err:
        pass  # partial candle detection failed — return full df
    return df


def _validate_frame_alignment(
    df1: pd.DataFrame,
    df5: pd.DataFrame,
    df15: pd.DataFrame,
    tol_5m: float,
    tol_15m: float,
) -> bool:
    try:
        ts1 = float(df1.index[-1].timestamp()) if hasattr(df1.index[-1], "timestamp") else 0.0
        ts5 = float(df5.index[-1].timestamp()) if hasattr(df5.index[-1], "timestamp") else 0.0
        ts15 = float(df15.index[-1].timestamp()) if hasattr(df15.index[-1], "timestamp") else 0.0
        if ts1 == 0 or ts5 == 0 or ts15 == 0:
            return True
        if abs(ts1 - ts5) > tol_5m:
            return False
        if abs(ts1 - ts15) > tol_15m:
            return False
        return True
    except (IndexError, ValueError, TypeError, AttributeError):
        return True


def compute_index_score(
    t5: str,
    t15: str,
    price: float,
    vwap: float,
    atr: float,
    vol: float,
    d1: float,
    d5: float,
    pcr: float,
    smart: str,
    *,
    signal_cfg: Mapping[str, Any],
    vol_ratio_min: float,
    learning_score_bonus: int = 0,
    rsi: float = 50.0,
) -> int:
    """
    Index scoring — deterministic, regime-agnostic component scorer.

    Weight table (max without OI/PCR):
      TF aligned    18  — both 5m and 15m trending same direction
      VWAP confirm  15  — price on correct side of daily VWAP
      D1 momentum   12  — 10-bar 1m delta confirms direction
      D5 momentum    8  — 3-bar 5m delta confirms direction
      Volume spike   8  — current vol ≥ vol_ratio_min × average
      ATR floor      5  — sufficient ATR for viable trade
      RSI health    +8  — RSI in continuation zone (40-70 CALL, 30-60 PUT)
      RSI extreme   -8  — overbought (>75 CALL) or oversold (<25 PUT)
      SmartMoney    10  — open-interest sentiment aligns (live only)
      PCR confirm    5  — PCR aligns with direction (live only)
    Max without OI: 18+15+12+8+8+5+8 = 74  → spread to 82+ with breakout bonus
    Max with OI:    74+15 = 89              → spread to 97+ with breakout bonus
    """
    _atr_min   = float(signal_cfg.get("ATR_MIN_THRESHOLD", 0.5))
    _pcr_bull  = float(signal_cfg.get("PCR_BULLISH", 1.2))
    _pcr_bear  = float(signal_cfg.get("PCR_BEARISH", 0.8))
    _rsi_ob    = float(signal_cfg.get("INDEX_RSI_OVERBOUGHT", 75))
    _rsi_os    = float(signal_cfg.get("INDEX_RSI_OVERSOLD", 25))
    _rsi_hh_c  = float(signal_cfg.get("INDEX_RSI_HEALTHY_HIGH_CALL", 70))
    _rsi_hl_c  = float(signal_cfg.get("INDEX_RSI_HEALTHY_LOW_CALL", 40))
    _rsi_hh_p  = float(signal_cfg.get("INDEX_RSI_HEALTHY_HIGH_PUT", 60))
    _rsi_hl_p  = float(signal_cfg.get("INDEX_RSI_HEALTHY_LOW_PUT", 30))
    _rsi_bonus = int(signal_cfg.get("INDEX_RSI_BONUS", 8))
    _rsi_pen   = int(signal_cfg.get("INDEX_RSI_PENALTY", 8))

    s = 0
    # ── Timeframe alignment (20) ──────────────────────────────────────
    s += 20 if t5 == t15 else 0
    # ── VWAP confirmation (8-20, proportional to distance from VWAP) ─
    # Thin margin above VWAP = 8 pts; strong conviction (0.5%+) = 20 pts.
    # Prevents 1-tick VWAP crosses from scoring the same as clear breakouts.
    _vwap_ref = max(float(vwap), 1.0)
    if (t5 == "UP" and price > _vwap_ref) or (t5 == "DOWN" and price < _vwap_ref):
        _vwap_dist = abs(price - _vwap_ref) / _vwap_ref
        s += min(20, 8 + int(min(1.0, _vwap_dist / 0.005) * 12))
    # ── 1m momentum delta (15) ───────────────────────────────────────
    s += 15 if t5 == "UP"   and d1 > 0 else 0
    s += 15 if t5 == "DOWN" and d1 < 0 else 0
    # ── 5m momentum delta (10) ───────────────────────────────────────
    s += 10 if t5 == "UP"   and d5 > 0 else 0
    s += 10 if t5 == "DOWN" and d5 < 0 else 0
    # ── Volume spike (4-14, proportional to vol ratio excess) ────────
    # vol at vol_ratio_min = 4 pts; 2x vol_ratio_min = ~14 pts.
    if vol >= vol_ratio_min:
        _vol_excess = (vol - vol_ratio_min) / max(vol_ratio_min, 0.5)
        s += min(14, 4 + int(min(1.0, _vol_excess) * 10))
    # ── ATR floor (5) ────────────────────────────────────────────────
    s +=  5 if atr > _atr_min else 0
    # ── RSI: health bonus ONLY (no penalty — extreme RSI in a trending
    #    market is continuation, not reversal; penalty handled by regime
    #    filter and ADX penalty elsewhere) ────────────────────────────
    if t5 == "UP"   and _rsi_hl_c <= rsi <= _rsi_hh_c:
        s += _rsi_bonus
    elif t5 == "DOWN" and _rsi_hl_p <= rsi <= _rsi_hh_p:
        s += _rsi_bonus
    # ── Smart money / OI sentiment (10) — non-zero only with live OI ─
    s += 10 if t5 == "UP"   and smart == "BULLISH" else 0
    s += 10 if t5 == "DOWN" and smart == "BEARISH" else 0
    # ── PCR confirmation (5) — non-zero only with live OI ────────────
    s +=  5 if t5 == "UP"   and pcr > _pcr_bull else 0
    s +=  5 if t5 == "DOWN" and pcr < _pcr_bear else 0
    # ── Learning bonus (clamped) ──────────────────────────────────────
    s += max(0, int(learning_score_bonus))
    return max(0, min(100, s))


def _macd_bonus_delta(direction: str, macd: Mapping[str, Any], bonus: int) -> int:
    if not isinstance(macd, dict):
        return 0
    mh = float(macd.get("histogram") or 0)
    ml = float(macd.get("macd") or 0)
    ms = float(macd.get("signal") or 0)
    if (direction == "CALL" and mh > 0 and ml > ms) or (direction == "PUT" and mh < 0 and ml < ms):
        return max(0, int(bonus))
    return 0


@dataclass(frozen=True)
class PureIndexRegimeParams:
    vix_block_threshold: float
    adx_trend_threshold: float
    adx_chop_threshold: float


@dataclass(frozen=True)
class PureIndexSignalParams:
    """Immutable inputs for one evaluation (no runtime mutation)."""

    name: str
    signal_cfg: Mapping[str, Any]
    regime: PureIndexRegimeParams
    iv_spike_threshold: float
    vol_ratio_min: float
    is_early_session: bool
    min15_early: int = 4
    min15_normal: int = 5


def evaluate_index_signal_partial(
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
    force_direction: str | None = None,
) -> tuple[dict[str, Any] | None, str]:
    """
    Structural + scoring path only (no threshold pass/fail, no wall-clock stale checks).

    Returns (payload, "") on success; (None, reason_tag) on structural block.
    """
    sc = params.signal_cfg
    min15 = int(sc.get("EARLY_SESSION_MIN_15M", params.min15_early) if params.is_early_session else sc.get("NORMAL_SESSION_MIN_15M", params.min15_normal))

    if df1 is None or len(df1) < 30:
        return None, "1m_short"
    if df5 is None or len(df5) < 10:
        return None, "5m_short"
    if df15 is None or len(df15) < min15:
        return None, "15m_short"

    tol_5m = float(sc.get("FRAME_ALIGN_1M_5M", 120))
    tol_15m = float(sc.get("FRAME_ALIGN_1M_15M", 300))
    if not _validate_frame_alignment(df1, df5, df15, tol_5m, tol_15m):
        return None, "frame_align"

    df1 = _drop_partial_candle(df1)
    df5 = _drop_partial_candle(df5)
    if df1 is None or len(df1) < 30 or df5 is None or len(df5) < 10:
        return None, "partial_drop"

    t5 = FeatureEngine.ema_trend(df5)
    t15 = FeatureEngine.ema_trend(df15)
    if force_direction is None:
        if t5 == "FLAT" or t15 == "FLAT" or t5 != t15:
            return None, "tf_mismatch"

    price = FeatureEngine.get_price(df1)
    vwap_val = FeatureEngine.get_vwap(df1)
    atr = FeatureEngine.get_atr(df1)
    vol_ratio = FeatureEngine.get_vol_ratio(df1)
    d1 = FeatureEngine.price_delta(df1, 10)
    d5_ = FeatureEngine.price_delta(df5, 3)
    rsi_val = FeatureEngine.get_rsi(df5)   # RSI on 5m for smoother signal
    if price <= 0:
        return None, "bad_price"

    rp = params.regime
    mkt_regime, avg_adx = mc_detect_regime_and_adx(
        df5,
        df15,
        vix=vix,
        vix_block_threshold=rp.vix_block_threshold,
        adx_trend_threshold=rp.adx_trend_threshold,
        adx_chop_threshold=rp.adx_chop_threshold,
    )
    if mkt_regime == "CHOPPY":
        return None, "choppy"

    if force_direction is not None:
        direction = force_direction
        t5_scoring = "UP" if direction == "CALL" else "DOWN"
    else:
        direction = "CALL" if t5 == "UP" else "PUT"
        t5_scoring = t5
    if iv > 0 and iv > float(params.iv_spike_threshold):
        return None, "iv_spike"

    score = compute_index_score(
        t5_scoring, t15, price, vwap_val, atr, vol_ratio, d1, d5_, pcr, smart,
        signal_cfg=sc, vol_ratio_min=params.vol_ratio_min,
        learning_score_bonus=learning_score_bonus, rsi=rsi_val,
    )

    # Component-level breakdown — must mirror compute_index_score formulas exactly
    _vwap_ref_ = max(float(vwap_val), 1.0)
    if (t5_scoring == "UP" and price > _vwap_ref_) or (t5_scoring == "DOWN" and price < _vwap_ref_):
        _vwap_dist_ = abs(price - _vwap_ref_) / _vwap_ref_
        _vwap_pts = min(20, 8 + int(min(1.0, _vwap_dist_ / 0.005) * 12))
    else:
        _vwap_pts = 0
    _d1_pts   = 15 if (t5_scoring == "UP" and d1 > 0) or (t5_scoring == "DOWN" and d1 < 0) else 0
    _d5_pts   = 10 if (t5_scoring == "UP" and d5_ > 0) or (t5_scoring == "DOWN" and d5_ < 0) else 0
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
    _rsi_pts  = (_rsi_b if (t5_scoring == "UP" and _rsi_hl_c <= rsi_val <= _rsi_hh_c)
                 or (t5_scoring == "DOWN" and _rsi_hl_p <= rsi_val <= _rsi_hh_p) else 0)
    _sm_pts   = 10 if (t5_scoring == "UP" and smart == "BULLISH") or (t5_scoring == "DOWN" and smart == "BEARISH") else 0
    _pcr_bull = float(sc.get("PCR_BULLISH", 1.2))
    _pcr_bear = float(sc.get("PCR_BEARISH", 0.8))
    _pcr_pts  = 5 if (t5_scoring == "UP" and pcr > _pcr_bull) or (t5_scoring == "DOWN" and pcr < _pcr_bear) else 0
    _score_components: dict[str, int] = {
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
    macd_raw = FeatureEngine.get_macd(df5)
    macd_b = int(sc.get("MACD_BONUS", 5))
    _macd_delta = _macd_bonus_delta(direction, macd_raw, macd_b)
    score = min(100, int(score) + _macd_delta)
    _score_components["macd_bonus"] = _macd_delta

    # Breakout quality bonus/penalty
    breakout_ok = SE.breakout_strength_ok(df1)
    _breakout_bonus = int(sc.get("BREAKOUT_BONUS", 8))
    _bk_pts = 0
    if breakout_ok:
        _bk_pts = _breakout_bonus
        score = min(100, score + _breakout_bonus)
    else:
        _bk_pts = -4
        score = max(0, score - 4)
    _score_components["breakout"] = _bk_pts

    # ADX quality penalty
    _adx_chop_pen_thr = float(sc.get("ADX_PENALTY_THRESHOLD", 12))
    _adx_pen = int(sc.get("ADX_PENALTY_POINTS", 5))
    _adx_pen_applied = 0
    if avg_adx > 0 and avg_adx < _adx_chop_pen_thr:
        _adx_pen_applied = -_adx_pen
        score = max(0, score - _adx_pen)
    _score_components["adx_penalty"] = _adx_pen_applied

    # VWAP reclaim: price recently crossed from wrong side to correct side of VWAP.
    # This is the key component of the VWAP-Reclaim strategy — institutional order
    # flow confirming direction after a short-term deviation.
    # Gate: price must currently be on correct VWAP side (_vwap_pts > 0).
    _reclaim_bonus = int(sc.get("VWAP_RECLAIM_BONUS", 7))
    _reclaim_pts = 0
    if _vwap_pts > 0 and vwap_val > 0 and len(df1) >= 5:
        _recent_closes = df1["Close"].iloc[-5:-1].values
        _was_wrong_side = (
            any(c < vwap_val for c in _recent_closes) if direction == "CALL"
            else any(c > vwap_val for c in _recent_closes)
        )
        if _was_wrong_side:
            _reclaim_pts = _reclaim_bonus
            score = min(100, score + _reclaim_pts)
    _score_components["vwap_reclaim"] = _reclaim_pts

    # ADX trend bonus — symmetric with chop penalty. Strong trending markets
    # (ADX above trend threshold) are structurally safer for directional options.
    _adx_trend_thr = float(sc.get("ADX_TREND_THRESHOLD", 20))
    _adx_trend_bonus = int(sc.get("ADX_TREND_BONUS_POINTS", 5))
    _adx_trend_pts = 0
    if avg_adx >= _adx_trend_thr:
        _adx_trend_pts = _adx_trend_bonus
        score = min(100, score + _adx_trend_pts)
    _score_components["adx_trend_bonus"] = _adx_trend_pts

    # Regime-based score penalty — HIGH_VOLATILITY and EVENT regimes inflate
    # option premiums and widen spreads; require a higher quality bar before entry.
    _hv_pen = int(sc.get("REGIME_SCORE_PENALTY_HV", 8))
    _ev_pen = int(sc.get("REGIME_SCORE_PENALTY_EVENT", 10))
    _regime_pen = 0
    if mkt_regime == "HIGH_VOLATILITY":
        _regime_pen = -_hv_pen
        score = max(0, score - _hv_pen)
    elif mkt_regime == "EVENT":
        _regime_pen = -_ev_pen
        score = max(0, score - _ev_pen)
    _score_components["regime_penalty"] = _regime_pen

    # ORB (Opening Range Breakout) bonus — institutional breakout above/below
    # the 9:15–9:30 session range is a high-conviction directional signal.
    _orb_bonus = int(sc.get("ORB_BONUS", 10))
    _orb_pts = 0
    try:
        if _orb_bonus > 0 and hasattr(df1.index, "time"):
            _t915 = datetime.time(9, 15)
            _t930 = datetime.time(9, 30)
            _idx_times = [t.time() if hasattr(t, "time") else t for t in df1.index]
            _orb_mask = [_t915 <= t < _t930 for t in _idx_times]
            _orb_df = df1.loc[_orb_mask]
            if len(_orb_df) >= 5:
                _orb_high = float(_orb_df["High"].max())
                _orb_low = float(_orb_df["Low"].min())
                _is_call = (force_direction is not None and force_direction == "CALL") or (force_direction is None and direction == "CALL")
                _is_put = (force_direction is not None and force_direction == "PUT") or (force_direction is None and direction == "PUT")
                if _is_call and price > _orb_high * 1.001:
                    _orb_pts = _orb_bonus
                    score = min(100, score + _orb_pts)
                elif _is_put and price < _orb_low * 0.999:
                    _orb_pts = _orb_bonus
                    score = min(100, score + _orb_pts)
    except (ValueError, TypeError, KeyError, AttributeError, IndexError) as _orb_err:
        pass  # ORB bonus failed — continue without it
    _score_components["orb_bonus"] = _orb_pts

    atr_sl_mult = float(sc.get("ATR_SL_MULTIPLIER", 1.2))
    stop_loss = SE.calc_atr_stop_loss(price, safe_num(atr, price * 0.01), direction, atr_sl_mult)
    tps = SE.calc_fibonacci_targets(
        price,
        safe_num(atr, price * 0.01),
        direction,
        fib_r1=float(sc.get("FIB_TP1_RATIO", 0.618)),
        fib_r2=float(sc.get("FIB_TP2_RATIO", 1.618)),
        fib_r3=float(sc.get("FIB_TP3_RATIO", 2.618)),
        vix=vix,
    )
    ema20 = FeatureEngine.get_ema(df5["Close"], 20)
    ema50 = FeatureEngine.get_ema(df5["Close"], 50) if len(df5) >= 50 else 0.0
    ema200 = FeatureEngine.get_ema(df15["Close"], 200) if len(df15) >= 200 else 0.0
    signal_ts = _bar_signal_ts(df1)

    return {
        "name": params.name,
        "direction": direction,
        "price": price,
        "score": int(score),
        "vwap": round(float(vwap_val), 2),
        "atr": atr,
        "vol_ratio": vol_ratio,
        "trend": t5,
        "trend_5m": t5,
        "trend_15m": t15,
        "mkt_regime": mkt_regime,
        "adx": avg_adx,
        "pcr": pcr,
        "smart": smart,
        "sup": oi_sup,
        "res": oi_res,
        "iv": iv,
        "vix": round(vix, 1),
        "breakout_ok": breakout_ok,
        "rsi": rsi_val,
        "score_components": _score_components,
        "macd": macd_raw,
        "ema20": ema20,
        "ema50": ema50,
        "ema200": ema200,
        "stop_loss": stop_loss,
        "tp1": tps["tp1"],
        "tp2": tps["tp2"],
        "tp3": tps["tp3"],
        "support": oi_sup,
        "resistance": oi_res,
        "signal_ts": signal_ts,
        "signal_reason": f"score={score} regime={mkt_regime} dir={direction}",
    }, ""


def evaluate_dual_direction_signal(
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
    dual_direction_enabled: bool = True,
    counter_trend_penalty: int = 10,
    mean_reversion_enabled: bool = True,
    tf_divergence_fallback: bool = True,
) -> tuple[dict[str, Any] | None, str]:
    """
    Evaluates signals for both CALL and PUT directions and picks the best.

    Implements three enhancement modes:
    - **Dual-direction scoring:** evaluate both CALL and PUT, pick higher score
      with a configurable counter-trend penalty
    - **Mean-reversion mode:** waive counter-trend penalty when RSI is extreme
      (oversold for CALL, overbought for PUT), treating it as a reversion
      opportunity rather than a trend violation
    - **TF divergence fallback:** when 5m and 15m trends diverge (tf_mismatch),
      use the stronger (5m) timeframe direction instead of blocking

    Returns (payload, "") on success; (None, reason_tag) on hard block.
    """
    sc = params.signal_cfg

    # ── Primary evaluation (standard path) ───────────────────────────────────
    partial, reason = evaluate_index_signal_partial(
        params=params,
        df1=df1, df5=df5, df15=df15,
        vix=vix, iv=iv,
        oi_sup=oi_sup, oi_res=oi_res,
        pcr=pcr, smart=smart,
        learning_score_bonus=learning_score_bonus,
    )

    # ── TF divergence fallback (Option C) ────────────────────────────────────
    if partial is None and reason == "tf_mismatch" and tf_divergence_fallback:
        # Determine the stronger direction from whichever timeframe has a clear trend
        t5 = FeatureEngine.ema_trend(df5)
        t15 = FeatureEngine.ema_trend(df15)
        if t5 != "FLAT":
            fallback_dir = "CALL" if t5 == "UP" else "PUT"
        elif t15 != "FLAT":
            fallback_dir = "CALL" if t15 == "UP" else "PUT"
        else:
            return None, "tf_mismatch"

        partial, reason = evaluate_index_signal_partial(
            params=params,
            df1=df1, df5=df5, df15=df15,
            vix=vix, iv=iv,
            oi_sup=oi_sup, oi_res=oi_res,
            pcr=pcr, smart=smart,
            learning_score_bonus=learning_score_bonus,
            force_direction=fallback_dir,
        )
        if partial is not None:
            partial = dict(partial)
            partial["_tf_divergence_fallback"] = fallback_dir
            partial["signal_reason"] = (
                f"score={partial['score']} dir={fallback_dir} (tf_fallback)"
            )

    if partial is None:
        return None, reason

    # ── Determine real 5m trend for counter-trend detection ──────────────────
    t5 = FeatureEngine.ema_trend(df5)
    primary_dir = str(partial["direction"])

    # Check if the primary direction is counter-trend
    is_counter_primary = (
        (primary_dir == "CALL" and t5 == "DOWN")
        or (primary_dir == "PUT" and t5 == "UP")
    )
    # If TF fallback fired, the direction might be counter-trend — mark it
    if is_counter_primary and partial.get("_tf_divergence_fallback"):
        comps = dict(partial.get("score_components", {}))
        comps["counter_trend_penalty"] = -counter_trend_penalty
        partial["score_components"] = comps
        partial["score"] = max(0, int(partial["score"]) - counter_trend_penalty)
        partial["signal_reason"] = (
            f"score={partial['score']} dir={primary_dir} "
            f"(tf_fallback, ctr_pen={counter_trend_penalty})"
        )

    partial = dict(partial)
    partial["_dual_direction_evaluated"] = False

    # ── Dual-direction evaluation (Option A) ─────────────────────────────────
    if not dual_direction_enabled:
        return partial, ""

    opposite_dir = "PUT" if primary_dir == "CALL" else "CALL"

    # Check if TF fallback already fired — if so, the "primary" is already
    # the forced direction, so evaluate the original trend direction as well
    opp_partial, opp_reason = evaluate_index_signal_partial(
        params=params,
        df1=df1, df5=df5, df15=df15,
        vix=vix, iv=iv,
        oi_sup=oi_sup, oi_res=oi_res,
        pcr=pcr, smart=smart,
        learning_score_bonus=learning_score_bonus,
        force_direction=opposite_dir,
    )

    if opp_partial is None:
        return partial, ""

    primary_score = int(partial["score"])
    opp_score = int(opp_partial["score"])

    # Check if opposite direction is counter-trend
    is_counter_opp = (
        (opposite_dir == "CALL" and t5 == "DOWN")
        or (opposite_dir == "PUT" and t5 == "UP")
    )

    # Apply counter-trend penalty (Option A)
    penalty = 0
    if is_counter_opp:
        penalty = counter_trend_penalty
        # Mean-reversion mode (Option B): waive penalty when RSI is extreme
        # — overbought = PUT opportunity, oversold = CALL opportunity
        if mean_reversion_enabled:
            rsi_val = FeatureEngine.get_rsi(df5)
            _rsi_ob = float(sc.get("INDEX_RSI_OVERBOUGHT", 75))
            _rsi_os = float(sc.get("INDEX_RSI_OVERSOLD", 25))
            if (
                (opposite_dir == "PUT" and rsi_val >= _rsi_ob)
                or (opposite_dir == "CALL" and rsi_val <= _rsi_os)
            ):
                penalty = 0  # Waive — mean-reversion opportunity

    adjusted_opp_score = opp_score - penalty

    # Pick the better direction
    if adjusted_opp_score > primary_score:
        # Opposite direction wins
        best = dict(opp_partial)
        best["score"] = adjusted_opp_score
        comps = dict(best.get("score_components", {}))
        if penalty > 0:
            comps["counter_trend_penalty"] = -penalty
        best["score_components"] = comps
        best["signal_reason"] = (
            f"score={adjusted_opp_score} dir={opposite_dir} "
            f"(dual, primary={primary_score} opp={opp_score} pen={penalty})"
        )
        best["_dual_direction_evaluated"] = True
        best["_dual_chosen"] = opposite_dir
        best["_dual_primary_score"] = primary_score
        best["_dual_opponent_score"] = adjusted_opp_score
        best["_dual_counter_trend"] = is_counter_opp
        best["_dual_penalty"] = penalty
        return best, ""
    else:
        # Primary direction wins
        partial["_dual_direction_evaluated"] = True
        partial["_dual_chosen"] = primary_dir
        partial["_dual_primary_score"] = primary_score
        partial["_dual_opponent_score"] = adjusted_opp_score
        partial["_dual_counter_trend"] = is_counter_primary
        partial["_dual_penalty"] = 0
        return partial, ""


def finalize_index_signal_with_threshold(
    partial: Mapping[str, Any],
    *,
    threshold: int,
    regime: str,
    adaptive_delta: int,
    adaptive_reason: str,
    trace_id: str,
    signal_cfg: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Attach threshold + UI fields; does not apply orchestrator-only gates."""
    sc = signal_cfg or {}
    score = int(partial["score"])
    direction = str(partial["direction"])
    thr = int(max(0, min(100, threshold)))
    stars = SE.score_to_stars(score, thr)
    label = SE.score_to_label(score, direction, thr)
    strength = SE.classify_strength(
        score,
        thr,
        strong_min=int(sc.get("STRONG_THRESHOLD", 85)),
        moderate_min=int(sc.get("MODERATE_THRESHOLD", 70)),
    )
    sig = SE.classify_signal(direction, score, thr)
    action = "BUY" if sig == "BUY" else "HOLD"
    return {
        **dict(partial),
        "threshold": thr,
        "regime": regime,
        "stars": stars,
        "label": label,
        "strength": strength,
        "signal": sig,
        "action": action,
        "confidence": float(min(100, max(0, score))),
        "adaptive_delta": adaptive_delta,
        "adaptive_reason": adaptive_reason,
        "trace_id": trace_id,
    }
