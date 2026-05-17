"""
IV Rank / IV Percentile — 52-week VIX-based premium cost indicator.

Definitions
-----------
IV Rank    = (CurrentVIX - 52wk Low) / (52wk High - 52wk Low) × 100
IV Pct     = % of past-year daily sessions where VIX close < CurrentVIX

Trading logic for options BUYING
---------------------------------
High IV Rank (>70) : premiums are expensive  → reduce score (penalise buying)
Low  IV Rank (<30) : premiums are cheap      → boost score  (ideal for buying)
Neutral  (30-70)   : normal premium env      → no adjustment

Data source : Yahoo Finance ^INDIAVIX daily closes
Cache       : data/iv_history_cache.json, refreshed every 24 h
Fallback    : if data unavailable, multiplier = 1.0 (no-op), logged at WARNING

Config keys (all optional — safe defaults built in)
----------------------------------------------------
  iv_rank_high_threshold : float  default 70.0  (rank above which buying is expensive)
  iv_rank_low_threshold  : float  default 30.0  (rank below which buying is cheap)
  iv_rank_high_mult      : float  default 0.60  (score multiplier when rank > high)
  iv_rank_low_mult       : float  default 1.20  (score multiplier when rank < low)
  iv_rank_cache_hours    : float  default 24.0  (cache TTL)
  iv_rank_enabled        : bool   default true  (set false to disable entirely)
"""
from __future__ import annotations

import json
import logging
import time
from datetime import timedelta

from core.datetime_ist import now_ist
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

_SYMBOL            = "^INDIAVIX"
_HISTORY_DAYS      = 390          # fetch slightly more than 365 to cover gaps
_MIN_SESSIONS      = 20           # minimum history needed for a valid calculation
_CACHE_PATH        = Path("data") / "iv_history_cache.json"

# Default config values
_DEF_HIGH_THR  = 70.0
_DEF_LOW_THR   = 30.0
_DEF_HIGH_MULT = 0.60
_DEF_LOW_MULT  = 1.20
_DEF_TTL_HRS   = 24.0

# Module-level in-memory cache — avoids file I/O on every scan cycle
_mem_cache: dict[str, Any] = {}


# ── Cache helpers ─────────────────────────────────────────────────────────────

def _ttl_seconds(config: dict[str, Any]) -> float:
    return float(config.get("iv_rank_cache_hours", _DEF_TTL_HRS)) * 3600.0


def _cache_is_stale(cache: dict[str, Any], ttl: float) -> bool:
    return (time.time() - float(cache.get("fetched_at", 0.0))) > ttl


def _load_file_cache() -> dict[str, Any]:
    try:
        if _CACHE_PATH.exists():
            return json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        _log.debug("[IV_RANK] Cache file read error: %s", exc)
    return {}


def _save_file_cache(data: dict[str, Any]) -> None:
    try:
        _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _CACHE_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception as exc:
        _log.warning("[IV_RANK] Cache write error: %s", exc)


# ── Data fetching ─────────────────────────────────────────────────────────────

def _fetch_vix_history() -> list[float]:
    """Download ~52-week daily VIX closes from Yahoo Finance ^INDIAVIX."""
    try:
        import yfinance as yf  # already in requirements
        end   = now_ist()
        start = end - timedelta(days=_HISTORY_DAYS)
        ticker = yf.Ticker(_SYMBOL)
        df = ticker.history(
            start=start.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
            interval="1d",
        )
        if df is None or df.empty:
            _log.warning("[IV_RANK] Yahoo returned empty history for %s", _SYMBOL)
            return []
        closes = [float(v) for v in df["Close"].dropna().tolist() if v > 0]
        _log.info(
            "[IV_RANK] Fetched %d VIX sessions (%s → %s)",
            len(closes),
            df.index.min().date() if len(df) else "?",
            df.index.max().date() if len(df) else "?",
        )
        return closes
    except Exception as exc:
        _log.warning("[IV_RANK] History fetch failed: %s", exc)
        return []


def _get_history(config: dict[str, Any], force_refresh: bool = False) -> list[float]:
    """
    Return 52-week daily VIX closes.
    Priority: in-memory → file cache (if fresh) → Yahoo Finance → stale file.
    """
    global _mem_cache
    ttl = _ttl_seconds(config)

    # 1. In-memory hit
    if not force_refresh and _mem_cache and not _cache_is_stale(_mem_cache, ttl):
        return list(_mem_cache.get("closes", []))

    # 2. File cache hit
    file_data = _load_file_cache()
    if not force_refresh and file_data and not _cache_is_stale(file_data, ttl):
        _mem_cache = file_data
        return list(_mem_cache.get("closes", []))

    # 3. Fresh fetch from Yahoo
    closes = _fetch_vix_history()
    if closes:
        data: dict[str, Any] = {"fetched_at": time.time(), "closes": closes}
        _save_file_cache(data)
        _mem_cache = data
        return closes

    # 4. Stale fallback (data unavailable today)
    if file_data and file_data.get("closes"):
        _log.warning("[IV_RANK] Fetch failed — using stale cache (%d sessions)", len(file_data["closes"]))
        _mem_cache = file_data
        return list(file_data["closes"])

    return []


# ── Public API ────────────────────────────────────────────────────────────────

def get_iv_rank(
    current_vix: float,
    config: dict[str, Any] | None = None,
    force_refresh: bool = False,
) -> float:
    """
    Calculate IV Rank for the given VIX level using 52-week history.

    IV Rank = (CurrentVIX - 52wk Low) / (52wk High - 52wk Low) × 100

    Args:
        current_vix   : Today's India VIX reading.
        config        : Bot config dict (used for cache TTL settings).
        force_refresh : Bypass cache and re-fetch from Yahoo.

    Returns:
        Float in [0, 100], or -1.0 if insufficient history.
    """
    if current_vix <= 0:
        return -1.0
    cfg = config or {}
    closes = _get_history(cfg, force_refresh=force_refresh)
    if len(closes) < _MIN_SESSIONS:
        _log.debug("[IV_RANK] Insufficient history (%d sessions, need %d)", len(closes), _MIN_SESSIONS)
        return -1.0

    low_52w  = min(closes)
    high_52w = max(closes)
    if high_52w <= low_52w:
        return 50.0  # flat VIX environment — return neutral

    rank = (current_vix - low_52w) / (high_52w - low_52w) * 100.0
    return round(max(0.0, min(100.0, rank)), 2)


def get_iv_percentile(
    current_vix: float,
    config: dict[str, Any] | None = None,
    force_refresh: bool = False,
) -> float:
    """
    Calculate IV Percentile for the given VIX level.

    IV Percentile = % of past-year sessions where daily VIX close < current_vix

    Args:
        current_vix   : Today's India VIX reading.
        config        : Bot config dict (used for cache TTL settings).
        force_refresh : Bypass cache and re-fetch from Yahoo.

    Returns:
        Float in [0, 100], or -1.0 if insufficient history.
    """
    if current_vix <= 0:
        return -1.0
    cfg = config or {}
    closes = _get_history(cfg, force_refresh=force_refresh)
    if len(closes) < _MIN_SESSIONS:
        return -1.0

    below = sum(1 for c in closes if c < current_vix)
    return round(below / len(closes) * 100.0, 2)


def get_score_multiplier(
    current_vix: float,
    config: dict[str, Any] | None = None,
) -> tuple[float, float, str]:
    """
    Return (score_multiplier, iv_rank, reason_tag) for the current VIX level.

    Score multiplier:
        iv_rank > high_threshold → config["iv_rank_high_mult"]   (e.g. 0.60)
        iv_rank < low_threshold  → config["iv_rank_low_mult"]    (e.g. 1.20)
        otherwise                → 1.0 (neutral — no adjustment)

    Returns (1.0, -1.0, "iv_rank_unavailable") when history is missing.

    Args:
        current_vix : Today's India VIX reading.
        config      : Bot config dict for threshold / multiplier overrides.

    Returns:
        (multiplier: float, iv_rank: float, reason: str)
    """
    cfg = config or {}

    if not cfg.get("iv_rank_enabled", True):
        return 1.0, -1.0, "iv_rank_disabled"

    if current_vix <= 0:
        return 1.0, -1.0, "iv_rank_unavailable(vix=0)"

    high_thr  = float(cfg.get("iv_rank_high_threshold", _DEF_HIGH_THR))
    low_thr   = float(cfg.get("iv_rank_low_threshold",  _DEF_LOW_THR))
    high_mult = float(cfg.get("iv_rank_high_mult",      _DEF_HIGH_MULT))
    low_mult  = float(cfg.get("iv_rank_low_mult",       _DEF_LOW_MULT))

    rank = get_iv_rank(current_vix, config=cfg)
    if rank < 0:
        return 1.0, -1.0, "iv_rank_unavailable"

    if rank > high_thr:
        tag = f"iv_rank={rank:.1f}>{high_thr:.0f} expensive→×{high_mult}"
        return high_mult, rank, tag
    if rank < low_thr:
        tag = f"iv_rank={rank:.1f}<{low_thr:.0f} cheap→×{low_mult}"
        return low_mult, rank, tag

    return 1.0, rank, f"iv_rank={rank:.1f} neutral"


def iv_summary(
    current_vix: float,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Return a full IV snapshot dict for logging and Telegram alerts.

    Keys: iv_rank, iv_percentile, score_multiplier, regime, reason
    """
    cfg = config or {}
    rank = get_iv_rank(current_vix, config=cfg)
    pct  = get_iv_percentile(current_vix, config=cfg)
    mult, _, reason = get_score_multiplier(current_vix, config=cfg)

    high_thr = float(cfg.get("iv_rank_high_threshold", _DEF_HIGH_THR))
    low_thr  = float(cfg.get("iv_rank_low_threshold",  _DEF_LOW_THR))

    if rank < 0:
        regime = "UNKNOWN"
    elif rank > high_thr:
        regime = "HIGH_IV"
    elif rank < low_thr:
        regime = "LOW_IV"
    else:
        regime = "NEUTRAL_IV"

    return {
        "iv_rank":          rank,
        "iv_percentile":    pct,
        "score_multiplier": mult,
        "iv_regime":        regime,
        "reason":           reason,
    }


def invalidate_cache() -> None:
    """Force next call to re-fetch from Yahoo Finance (e.g. at daily reset)."""
    global _mem_cache
    _mem_cache = {}
    _log.info("[IV_RANK] In-memory cache invalidated — next call will re-fetch")


# ── IV Skew (Item 11 — v2.44) ─────────────────────────────────────────────────

from dataclasses import dataclass as _dataclass


@_dataclass(frozen=True)
class IVSkewData:
    put_skew:         float   # OTM put IV - OTM call IV (basis points)
    atm_iv:           float   # ATM implied volatility approximation
    put_25d_iv:       float   # 25-delta put IV approximation
    call_25d_iv:      float   # 25-delta call IV approximation
    skew_percentile:  float   # Rank vs 30-day history (0-100); -1 if unavailable
    regime:           str     # "NORMAL" | "ELEVATED" | "EXTREME"
    ts:               float   # epoch of calculation


def _bs_approx_iv(
    premium:    float,
    spot:       float,
    strike:     float,
    dte_days:   int,
    is_put:     bool = False,
) -> float:
    """
    Rough IV back-solve using Brenner-Subrahmanyam approximation.
    Returns IV in % (annualised), or 0.0 on failure.
    """
    try:
        import math
        if premium <= 0 or spot <= 0 or strike <= 0 or dte_days <= 0:
            return 0.0
        T = dte_days / 365.0
        # Approximation: IV ≈ (C / S) * sqrt(2π/T) for ATM options
        moneyness = abs(spot - strike) / spot
        if moneyness > 0.15:
            return 0.0  # too far OTM for reliable approximation
        iv_approx = (premium / spot) * (2.506706 / math.sqrt(T))  # sqrt(2π) ≈ 2.5067
        return round(max(0.0, min(200.0, iv_approx * 100)), 2)
    except Exception:
        return 0.0


def compute_iv_skew(
    option_chain: dict,
    spot_price:   float,
    dte:          int,
    cfg:          dict[str, Any] | None = None,
) -> IVSkewData | None:
    """
    Estimates put-call IV skew from option chain data.
    option_chain format: {"calls": {strike: premium}, "puts": {strike: premium}}
    Returns None if chain missing or insufficient strikes.
    Never raises.
    """
    c = cfg or {}
    if not c.get("iv_skew_enabled", True):
        return None
    try:
        if not option_chain or spot_price <= 0:
            return None

        calls: dict[int, float] = option_chain.get("calls") or {}
        puts:  dict[int, float] = option_chain.get("puts")  or {}

        if not calls or not puts:
            return None

        # ATM strike = nearest to spot
        all_strikes = sorted(set(calls.keys()) | set(puts.keys()))
        if not all_strikes:
            return None

        atm_strike = min(all_strikes, key=lambda s: abs(s - spot_price))
        atm_prem   = puts.get(atm_strike) or calls.get(atm_strike) or 0.0
        atm_iv     = _bs_approx_iv(atm_prem, spot_price, atm_strike, max(dte, 1))

        # 25-delta approximation: ≈ strikes at ±1.5σ from ATM
        # Using 15% OTM as a rough 25-delta proxy
        otm_offset = max(1, round(spot_price * 0.05))   # 5% OTM
        put_25d_strike  = min(all_strikes, key=lambda s: abs(s - (spot_price - otm_offset)))
        call_25d_strike = min(all_strikes, key=lambda s: abs(s - (spot_price + otm_offset)))

        put_25d_prem  = puts.get(put_25d_strike,  0.0)
        call_25d_prem = calls.get(call_25d_strike, 0.0)

        put_25d_iv  = _bs_approx_iv(put_25d_prem,  spot_price, put_25d_strike,  max(dte, 1), is_put=True)
        call_25d_iv = _bs_approx_iv(call_25d_prem, spot_price, call_25d_strike, max(dte, 1))

        put_skew = round(put_25d_iv - call_25d_iv, 2)

        el_thr = float(c.get("iv_skew_elevated_threshold", 3.0))
        ex_thr = float(c.get("iv_skew_extreme_threshold",  7.0))
        if put_skew >= ex_thr:
            regime = "EXTREME"
        elif put_skew >= el_thr:
            regime = "ELEVATED"
        else:
            regime = "NORMAL"

        return IVSkewData(
            put_skew=put_skew,
            atm_iv=atm_iv,
            put_25d_iv=put_25d_iv,
            call_25d_iv=call_25d_iv,
            skew_percentile=-1.0,   # no historical series available without OI DB
            regime=regime,
            ts=time.time(),
        )
    except Exception as exc:
        _log.debug("[IV_SKEW] compute error: %s", exc)
        return None


def get_skew_adjusted_premium(
    raw_premium: float,
    is_put:      bool,
    is_otm:      bool,
    skew_data:   IVSkewData | None,
    cfg:         dict[str, Any] | None = None,
) -> float:
    """
    Adjusts PUT OTM premium upward when IV skew is elevated/extreme.
    Returns raw_premium unchanged for calls or when skew_data is None.
    """
    if skew_data is None or not is_put or not is_otm:
        return raw_premium
    if skew_data.regime == "NORMAL":
        return raw_premium
    c         = cfg or {}
    adj_mult  = float(c.get("iv_skew_adj_mult", 0.5))
    adjustment = 1.0 + adj_mult * (skew_data.put_skew / 100.0)
    return round(raw_premium * max(1.0, adjustment), 4)
