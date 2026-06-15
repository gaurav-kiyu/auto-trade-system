"""Backward-compatible shim for signal_engine.

This module has been moved to core/legacy/signal_engine.py.
This shim re-exports all public symbols for backward compatibility.

WARNING: This module is deprecated. Use core.signal_service.SignalService,
core.adaptive_signal, or core.pure_index_signal instead.
"""

import warnings

warnings.warn(
    "signal_engine.py is deprecated - use core.signal_service.SignalService, "
    "core.adaptive_signal, or core.pure_index_signal instead.",
    DeprecationWarning,
    stacklevel=2,
)

# Re-export all public functions from the new location
from core.legacy.signal_engine import (  # noqa: F401, E402
    _bundled_index_defaults,
    _bundled_stock_defaults,
    _learning_score_adj_limit,
    get_open,
    get_high,
    get_low,
    get_ema_series,
    breakout_strength_ok,
    calc_support_resistance_pivot,
    calc_fibonacci_targets,
    calc_chandelier_exit,
    calc_atr_stop_loss,
    classify_strength,
    classify_signal,
    score_to_stars,
    score_to_label,
    compute_score_stock,
    compute_score_index,
    detect_regime,
    build_full_signal,
    validate_ohlcv,
    explain_signal,
    score_breakdown,
    format_pnl,
    format_change,
)
