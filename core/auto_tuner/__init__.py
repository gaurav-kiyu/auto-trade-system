"""
Safe auto-tuning system for the OPB index options trading bot.

Philosophy: Suggestions over actions. Stability over optimisation.
"""

from __future__ import annotations

from core.auto_tuner.models import (
    _BLOCKED_KEYS,
    _TUNABLE_PARAMS,
    AppliedChange,
    Recommendation,
    TuneResult,
)
from core.auto_tuner.tuner import (  # noqa: F401 — imported by tests/auto_tuner
    _check_direction_skew,
    _check_drawdown,
    _check_regime_sizes,
    _check_score_threshold,
    _compute_safe_change,
    _in_cooldown,
    _parse_bin_range,
    apply_recommendations,
    backup_config,
    eod_auto_tune_hook,
    generate_recommendations,
    log,
    print_tune_report,
    run_auto_tune,
)

__all__ = [
    "AppliedChange",
    "Recommendation",
    "TuneResult",
    "_BLOCKED_KEYS",
    "_TUNABLE_PARAMS",
    "apply_recommendations",
    "backup_config",
    "eod_auto_tune_hook",
    "generate_recommendations",
    "log",
    "print_tune_report",
    "run_auto_tune",
]
