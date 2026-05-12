"""Shared numeric coercion for OHLCV / signals / Telegram (single implementation)."""

from __future__ import annotations

import math
from typing import Any


def safe_float(v: Any, default: float = 0.0) -> float:
    """Coerce to float; return ``default`` for None, NaN, Inf, or bad types."""
    if v is None:
        return default
    try:
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return default
        return f
    except (TypeError, ValueError):
        return default


def safe_num(v: Any, default: float = 0.0) -> float:
    """Alias for :func:`safe_float` (legacy name used across signal/Telegram modules)."""
    return safe_float(v, default)
