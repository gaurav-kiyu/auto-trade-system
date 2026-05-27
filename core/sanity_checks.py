"""Shared price / sanity gates for index + stock entry scripts."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def ltp_sane(
    ltp: Any,
    *,
    name: str = "",
    log_fn: Callable[[str], None] | None = None,
    lo: float = 0.5,
    hi: float = 500_000,
) -> bool:
    """Reject None, non-positive tiny values, or absurdly large LTP (₹ instruments)."""
    if ltp is None or ltp <= lo or ltp > hi:
        if name and log_fn is not None:
            log_fn(f"[SANITY] {name} rejected LTP={ltp}")
        return False
    return True


def volume_sane(
    vol: Any,
    *,
    name: str = "",
    log_fn: Callable[[str], None] | None = None,
    min_vol: float = 0.0,
    max_vol: float = 1e12,
) -> bool:
    """Reject missing/negative volume or absurd spikes (bad ticks / corrupt bars)."""
    try:
        v = float(vol)
    except (TypeError, ValueError):
        if name and log_fn is not None:
            log_fn(f"[SANITY] {name} rejected volume (non-numeric)={vol!r}")
        return False
    if v < min_vol or v > max_vol:
        if name and log_fn is not None:
            log_fn(f"[SANITY] {name} rejected volume={v}")
        return False
    return True


def spread_sane(
    high: Any,
    low: Any,
    *,
    name: str = "",
    log_fn: Callable[[str], None] | None = None,
    max_spread_pct: float = 0.25,
) -> bool:
    """Reject inverted H/L or single-bar spread wider than ``max_spread_pct`` of mid."""
    try:
        h = float(high)
        lo = float(low)
    except (TypeError, ValueError):
        if name and log_fn is not None:
            log_fn(f"[SANITY] {name} rejected spread (non-numeric H/L)")
        return False
    if h <= 0 or lo <= 0 or h < lo:
        if name and log_fn is not None:
            log_fn(f"[SANITY] {name} rejected spread high={h} low={lo}")
        return False
    mid = (h + lo) / 2.0
    if mid <= 0:
        return False
    if (h - lo) / mid > max_spread_pct:
        if name and log_fn is not None:
            log_fn(f"[SANITY] {name} rejected wide spread {(h-lo)/mid:.2%} vs mid {mid}")
        return False
    return True


def ohlcv_bar_sane(
    o: Any,
    h: Any,
    low: Any,
    c: Any,
    v: Any,
    *,
    name: str = "",
    log_fn: Callable[[str], None] | None = None,
    max_spread_pct: float = 0.25,
) -> bool:
    """Last-bar OHLCV consistency: positive H/L/V, O/C inside range, spread cap."""
    try:
        fo, fh, fl, fc, fv = float(o), float(h), float(low), float(c), float(v)
    except (TypeError, ValueError):
        if name and log_fn is not None:
            log_fn(f"[SANITY] {name} rejected OHLCV (non-numeric)")
        return False
    if not volume_sane(fv, name=name, log_fn=log_fn):
        return False
    if fh < fl or fh <= 0 or fl <= 0:
        if name and log_fn is not None:
            log_fn(f"[SANITY] {name} rejected OHLCV high/low")
        return False
    if fc < fl or fc > fh or fo < fl or fo > fh:
        if name and log_fn is not None:
            log_fn(f"[SANITY] {name} rejected OHLCV open/close outside range")
        return False
    return spread_sane(fh, fl, name=name, log_fn=log_fn, max_spread_pct=max_spread_pct)
