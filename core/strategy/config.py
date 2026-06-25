"""
AD-KIYU Structured Strategy Config v1.0

Provides a unified way to read strategy configuration from the structured
``strategies.{name}.{key}`` config block, falling back to legacy flat keys
for backward compatibility.

Example usage::

    from core.strategy.config import get_strategy_cfg

    cfg = get_strategy_cfg(config, "spread")
    if cfg.get("enabled", False):
        width = cfg.get("width_strikes", 2)

The structured block in ``index_config.defaults.json`` looks like::

    {
      "strategies": {
        "spread":      { "enabled": false, "width_strikes": 2, ... },
        "straddle":    { "enabled": false, "max_iv_rank": 20, ... },
        "strangle":    { "width_steps": 2 },
        "iron_condor": { "enabled": false, "max_adx": 18, ... }
      }
    }

Flat keys (e.g. ``spread_strategy_enabled``) are checked as fallback when
the structured block is absent or missing a specific key.
"""
from __future__ import annotations

from typing import Any


# ── Flat-key alias maps ──────────────────────────────────────────────────────
# Each entry: structured_key -> flat_key

_SPREAD_FLAT_ALIASES: dict[str, str] = {
    "enabled":           "spread_strategy_enabled",
    "width_strikes":     "spread_width_strikes",
    "slippage_pct":      "spread_slippage_pct",
    "exit_pnl_pct":      "spread_exit_pnl_pct",
    "stop_pct":          "spread_stop_pct",
    "partial_exit_pct":  "spread_partial_exit_pct",
    "partial_lots_pct":  "spread_partial_lots_pct",
    "theta_exit_dte":    "spread_theta_exit_dte",
    "theta_exit_time":   "spread_theta_exit_time",
}

_STRADDLE_FLAT_ALIASES: dict[str, str] = {
    "enabled":              "straddle_strategy_enabled",
    "max_iv_rank":          "straddle_max_iv_rank",
    "target_mult":          "straddle_target_mult",
    "stop_mult":            "straddle_stop_mult",
    "close_both_on_target": "straddle_close_both_on_target",
    "expiry":               "straddle_expiry",
}

_STRANGLE_FLAT_ALIASES: dict[str, str] = {
    "width_steps": "strangle_width_steps",
}

_IRON_CONDOR_FLAT_ALIASES: dict[str, str] = {
    "enabled":           "ic_strategy_enabled",
    "max_adx":           "ic_max_adx",
    "max_vix":           "ic_max_vix",
    "min_dte":           "ic_min_dte",
    "wing_width_steps":  "ic_wing_width_steps",
    "profit_target":     "ic_profit_target",
    "stop_mult":         "ic_stop_mult",
    "expiry":            "ic_expiry",
}

# ── Registry ──────────────────────────────────────────────────────────────────
_STRATEGY_ALIASES: dict[str, dict[str, str]] = {
    "spread":      _SPREAD_FLAT_ALIASES,
    "straddle":    _STRADDLE_FLAT_ALIASES,
    "strangle":    _STRANGLE_FLAT_ALIASES,
    "iron_condor": _IRON_CONDOR_FLAT_ALIASES,
}


# ── Public API ────────────────────────────────────────────────────────────────


def get_strategy_block(cfg: dict[str, Any], name: str) -> dict[str, Any]:
    """Return the structured config block for a strategy, or empty dict.

    Looks up ``strategies.{name}`` from the top-level config.
    Returns an empty dict if the block is absent or not a dict.
    """
    strategies = cfg.get("strategies", {}) or {}
    if not isinstance(strategies, dict):
        return {}
    block = strategies.get(name, {}) or {}
    if not isinstance(block, dict):
        return {}
    return block


def get_strategy_param(
    cfg: dict[str, Any],
    name: str,
    key: str,
    fallback: Any = None,
) -> Any:
    """Read a single strategy parameter with flat-key fallback.

    Priority:
      1. ``strategies.{name}.{key}`` (structured block)
      2. ``{flat_alias}`` (legacy flat key, if alias exists)
      3. ``fallback``

    Args:
        cfg:      Full merged config dict.
        name:     Strategy name (e.g. ``"spread"``, ``"straddle"``).
        key:      Parameter key inside the structured block.
        fallback: Default value if neither structured nor flat key exists.

    Returns:
        The parameter value, or ``fallback`` if absent.
    """
    # 1. Structured block
    block = get_strategy_block(cfg, name)
    if key in block:
        return block[key]

    # 2. Flat-key fallback
    aliases = _STRATEGY_ALIASES.get(name, {})
    flat_key = aliases.get(key)
    if flat_key is not None and flat_key in cfg:
        return cfg[flat_key]

    # 3. Pure default
    return fallback


class StrategyConfigView:
    """Dict-like view over a strategy's config block with flat-key fallback.

    Provides ``.get(key, fallback)`` access to strategy parameters.
    Accepts a full merged config dict + strategy name.

    Example::

        scfg = StrategyConfigView(config, "spread")
        if scfg.get("enabled", False):
            width = scfg.get("width_strikes", 2)
    """

    def __init__(self, cfg: dict[str, Any], name: str) -> None:
        self._cfg = cfg
        self._name = name
        self._block = get_strategy_block(cfg, name)
        self._aliases = _STRATEGY_ALIASES.get(name, {})

    def get(self, key: str, fallback: Any = None) -> Any:
        # 1. Structured block
        if key in self._block:
            return self._block[key]
        # 2. Flat-key fallback
        flat_key = self._aliases.get(key)
        if flat_key is not None and flat_key in self._cfg:
            return self._cfg[flat_key]
        # 3. Default
        return fallback

    def as_dict(self) -> dict[str, Any]:
        """Merge structured block + flat keys into a single flat dict.

        Structured keys win over flat keys. Only keys that have an alias
        mapping are included (plus any extra keys in the structured block).
        """
        result: dict[str, Any] = {}
        # Start with flat key values (using structured key names)
        for sk, fk in self._aliases.items():
            if fk in self._cfg:
                result[sk] = self._cfg[fk]
        # Overlay structured block
        result.update(self._block)
        return result


def get_strategy_cfg(cfg: dict[str, Any], name: str) -> StrategyConfigView:
    """Convenience: return a ``StrategyConfigView`` for the given strategy."""
    return StrategyConfigView(cfg, name)


__all__ = [
    "get_strategy_block",
    "get_strategy_param",
    "StrategyConfigView",
    "get_strategy_cfg",
]
