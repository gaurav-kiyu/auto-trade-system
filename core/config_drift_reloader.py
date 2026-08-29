"""Config Drift Auto-Reload (config key CONFIG_DRIFT_AUTO_RELOAD, opt-in via
config_drift_auto_reload_enabled, default OFF).

Periodically re-reads the config.json override layer from disk and, when it
has changed since the last check, hot-applies a small, deliberately
conservative allowlist of non-risk-sensitive keys into the live running
config dict - built on core/soft_reload_common.py's existing, tested
partition/apply primitives, which previously had zero real callers anywhere
in the codebase.

Any changed key NOT on the safe allowlist is left alone and logged as
"restart required" - this module never guesses at whether an arbitrary key
is safe to hot-swap.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any

from core.soft_reload_common import (
    apply_safe_key_patch,
    ignored_keys_warning,
    partition_soft_reload_changes,
)

_log = logging.getLogger(__name__)

# Config keys that must NEVER be hot-reloaded while the bot is running -
# a change to any of these requires a deliberate restart. Mirrors the
# config-key subset of scripts/pre_implementation_check.py's
# RISK_SENSITIVE_PATTERNS plus a few adjacent execution-mode keys.
IMMUTABLE_RELOAD_KEYS: frozenset[str] = frozenset({
    "MAX_DAILY_LOSS", "MAX_DRAWDOWN", "SL_PCT", "TARGET_PCT", "TRAIL_PCT",
    "PORTFOLIO_MAX_SL_RISK_PCT", "MAX_SINGLE_TRADE_LOSS_PCT",
    "MAX_CONSECUTIVE_LOSSES", "VIX_HALT_THRESHOLD", "VIX_BLOCK_THRESHOLD",
    "PAPER_MODE", "EXECUTION_MODE", "MANUAL_SIGNALS_ONLY",
    "BROKER_DRIVER", "BROKER_API_ENABLED", "live_trading_lockout_enabled",
})

# Deliberately small starting allowlist of keys safe to hot-apply without a
# restart - pure scoring/notification tuning values with no execution-safety
# implications. Expand cautiously; anything not listed here is ignored
# (logged, restart required) rather than guessed at.
SAFE_RELOAD_KEYS: frozenset[str] = frozenset({
    "BREAKOUT_BONUS", "MACD_BONUS", "VWAP_RECLAIM_BONUS",
    "TG_COOLDOWN_SECS", "TG_HEARTBEAT_INTERVAL",
    "AI_THRESHOLD", "IV_SPIKE_THRESHOLD", "VOL_RATIO_MIN",
})


class ConfigDriftReloader:
    """Tracks the on-disk config.json layer and hot-applies safe drift into
    a live, shared config dict on each check() call."""

    def __init__(self, cfg: dict[str, Any], config_path: str | Path | None = None) -> None:
        self._cfg = cfg
        self._config_path = Path(
            config_path or os.environ.get("OPBUYING_INDEX_CONFIG", "json/config.json"),
        )
        self._last_mtime: float | None = None

    def check(self) -> dict[str, list[str]]:
        """Re-read config.json if its mtime changed since the last check;
        hot-apply SAFE_RELOAD_KEYS, log the rest as restart-required.
        Never raises - a bug here must never affect the trading loop."""
        try:
            if not self._config_path.is_file():
                return {"reloaded": [], "blocked": [], "ignored": []}
            mtime = self._config_path.stat().st_mtime
            if mtime == self._last_mtime:
                return {"reloaded": [], "blocked": [], "ignored": []}
            self._last_mtime = mtime
            disk_cfg = json.loads(self._config_path.read_text(encoding="utf-8"))

            _changed, blocked, ignored = partition_soft_reload_changes(
                self._cfg, disk_cfg, IMMUTABLE_RELOAD_KEYS, SAFE_RELOAD_KEYS,
            )
            reloaded, _diff_log = apply_safe_key_patch(self._cfg, disk_cfg, SAFE_RELOAD_KEYS)

            if reloaded:
                _log.info("[CONFIG_DRIFT] Hot-applied: %s", ", ".join(reloaded))
            if blocked:
                _log.warning(
                    "[CONFIG_DRIFT] Risk-sensitive key(s) changed on disk but NOT "
                    "applied (restart required): %s", ", ".join(sorted(blocked)),
                )
            warn_msg = ignored_keys_warning(ignored)
            if warn_msg:
                _log.warning("[CONFIG_DRIFT] %s", warn_msg)
            return {"reloaded": reloaded, "blocked": blocked, "ignored": ignored}
        except (OSError, ValueError, TypeError, KeyError, AttributeError) as e:
            _log.debug("Config drift check failed (fail-open): %s", e)
            return {"reloaded": [], "blocked": [], "ignored": []}


_drift_reloader: ConfigDriftReloader | None = None
_drift_reloader_lock = threading.Lock()


def get_config_drift_reloader(
    cfg: dict[str, Any], config_path: str | Path | None = None,
) -> ConfigDriftReloader:
    """Process-wide singleton, mirroring get_intraday_monitor()/get_loop_watchdog()."""
    global _drift_reloader
    with _drift_reloader_lock:
        if _drift_reloader is None:
            _drift_reloader = ConfigDriftReloader(cfg, config_path)
        return _drift_reloader


def reset_config_drift_reloader() -> None:
    """Test-only reset of the singleton."""
    global _drift_reloader
    with _drift_reloader_lock:
        _drift_reloader = None


__all__ = [
    "IMMUTABLE_RELOAD_KEYS",
    "SAFE_RELOAD_KEYS",
    "ConfigDriftReloader",
    "get_config_drift_reloader",
    "reset_config_drift_reloader",
]
