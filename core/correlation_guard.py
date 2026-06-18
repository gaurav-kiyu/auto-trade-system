"""
Multi-Instrument Correlation Guard (Phase 8).

Blocks or warns when two correlated index options are about to be entered
in the same direction simultaneously, increasing hidden portfolio risk.

Example: If NIFTY CALL is already open and BANKNIFTY sends a CALL signal,
and the last N bars of their price history are highly correlated (r > threshold),
the BANKNIFTY entry is blocked - it would just double the same risk exposure.

Config keys (all optional - safe defaults built in)
---------------------------------------------------
  correlation_guard_enabled  : bool  default true
  correlation_threshold      : float default 0.85  (block when r > this)
  correlation_lookback_bars  : int   default 20    (bars of 1m closes to use)
  correlation_warn_threshold : float default 0.70  (log WARNING when r > this)

Known correlated pairs (hard-coded, extensible via config):
  NIFTY ↔ BANKNIFTY
  NIFTY ↔ FINNIFTY
  BANKNIFTY ↔ FINNIFTY
"""
from __future__ import annotations

import logging
import math
from collections import deque
from typing import Any

_log = logging.getLogger(__name__)

# ── Known correlated index pairs ──────────────────────────────────────────────

_CORR_PAIRS: frozenset[frozenset[str]] = frozenset({
    frozenset({"NIFTY", "BANKNIFTY"}),
    frozenset({"NIFTY", "FINNIFTY"}),
    frozenset({"BANKNIFTY", "FINNIFTY"}),
})


# ── In-process rolling close price cache ─────────────────────────────────────

_closes_cache: dict[str, deque[float]] = {}
_CACHE_MAX = 60   # keep up to 60 bars per symbol


def update_closes(name: str, closes: list[float]) -> None:
    """
    Push recent 1m close prices for `name` into the rolling cache.

    Called from the main scan loop after every frame fetch.

    Args:
        name   : Index name (e.g. "NIFTY", "BANKNIFTY").
        closes : List of recent 1m close prices, newest last.
    """
    if name not in _closes_cache:
        _closes_cache[name] = deque(maxlen=_CACHE_MAX)
    q = _closes_cache[name]
    for c in closes:
        if c and c > 0:
            q.append(float(c))


def get_closes(name: str, n: int) -> list[float]:
    """Return the last `n` cached closes for `name`, or [] if unavailable."""
    q = _closes_cache.get(name)
    if not q:
        return []
    return list(q)[-n:]


# ── Correlation calculation ───────────────────────────────────────────────────

def pearson_r(series1: list[float], series2: list[float]) -> float:
    """
    Compute Pearson correlation coefficient between two equal-length series.

    Returns:
        Float in [-1, 1], or 0.0 if calculation is impossible (too few points
        or zero variance).
    """
    n = min(len(series1), len(series2))
    if n < 5:
        return 0.0
    x = series1[-n:]
    y = series2[-n:]
    mean_x = sum(x) / n
    mean_y = sum(y) / n
    cov = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y))
    var_x = sum((xi - mean_x) ** 2 for xi in x)
    var_y = sum((yi - mean_y) ** 2 for yi in y)
    denom = math.sqrt(var_x * var_y)
    if denom == 0:
        return 0.0
    return round(cov / denom, 4)


# ── Public API ────────────────────────────────────────────────────────────────

def are_correlated_pair(name1: str, name2: str) -> bool:
    """True if (name1, name2) is a known correlated index pair."""
    return frozenset({name1, name2}) in _CORR_PAIRS


def check_portfolio_correlation(
    new_name: str,
    new_direction: str,
    open_positions: dict[str, Any],
    cfg: dict[str, Any] | None = None,
) -> tuple[bool, str]:
    """
    Check whether opening a new position in `new_name` would create excessive
    correlated exposure relative to existing open positions.

    Args:
        new_name       : Index being considered for entry (e.g. "BANKNIFTY").
        new_direction  : "CALL" or "PUT".
        open_positions : Current positions dict {name: pos_dict}.
        cfg            : Bot config dict.

    Returns:
        (allowed, reason)
            allowed=True  → no correlation concern, proceed.
            allowed=False → blocked; reason explains why.
    """
    c = cfg or {}
    if not c.get("correlation_guard_enabled", True):
        return True, ""

    threshold   = float(c.get("correlation_threshold",      0.85))
    warn_thresh = float(c.get("correlation_warn_threshold", 0.70))
    lookback    = int(c.get("correlation_lookback_bars",     20))

    new_dir_norm = str(new_direction).upper()

    for existing_name, pos in open_positions.items():
        if existing_name == new_name:
            continue
        if not are_correlated_pair(new_name, existing_name):
            continue
        existing_dir = str(pos.get("signal", "")).upper()
        if existing_dir != new_dir_norm:
            continue  # opposite directions hedge each other - fine

        # Same direction in a correlated pair - check price correlation
        closes_new      = get_closes(new_name,      lookback)
        closes_existing = get_closes(existing_name, lookback)

        if len(closes_new) < 5 or len(closes_existing) < 5:
            _log.debug(
                "[CORR_GUARD] Insufficient price history for %s↔%s - skipping check",
                new_name, existing_name,
            )
            continue

        r = pearson_r(closes_new, closes_existing)

        if r >= threshold:
            reason = (
                f"Correlation guard: {new_name}/{existing_name} both {new_dir_norm}, "
                f"r={r:.3f} ≥ threshold={threshold:.2f} - blocked"
            )
            _log.info("[CORR_GUARD] %s", reason)
            return False, reason

        if r >= warn_thresh:
            _log.warning(
                "[CORR_GUARD] %s/%s both %s, r=%.3f (warn threshold=%.2f) - proceeding with caution",
                new_name, existing_name, new_dir_norm, r, warn_thresh,
            )

    return True, ""


def correlation_summary(cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return a snapshot of current cached correlations for all known pairs."""
    c = cfg or {}
    lookback = int(c.get("correlation_lookback_bars", 20))
    results: dict[str, float] = {}
    seen: set[frozenset[str]] = set()
    names = list(_closes_cache.keys())
    for i, n1 in enumerate(names):
        for n2 in names[i + 1:]:
            pair = frozenset({n1, n2})
            if pair in seen:
                continue
            seen.add(pair)
            r = pearson_r(get_closes(n1, lookback), get_closes(n2, lookback))
            results[f"{n1}/{n2}"] = r
    return {
        "enabled":   c.get("correlation_guard_enabled", True),
        "threshold": c.get("correlation_threshold", 0.85),
        "pairs":     results,
    }
