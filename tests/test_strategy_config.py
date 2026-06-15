"""
Tests for ``core.strategy.config`` — structured strategy config reader.

Covers:
  - get_strategy_block() — raw dict extraction
  - get_strategy_param() — single param with fallback
  - get_strategy_cfg() / StrategyConfigView — dict-like view
  - Flat-key backward compatibility
  - Structured block wins over flat keys
  - Unknown strategy names
  - Edge cases (None, empty dict, missing keys)
"""
from __future__ import annotations

from typing import Any

from core.strategy.config import (
    StrategyConfigView,
    get_strategy_block,
    get_strategy_cfg,
    get_strategy_param,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────


def _make_flat_cfg(**overrides: Any) -> dict[str, Any]:
    """Config with only flat (legacy) keys."""
    base: dict[str, Any] = {
        "spread_strategy_enabled": True,
        "spread_width_strikes": 3,
        "spread_slippage_pct": 0.005,
        "spread_exit_pnl_pct": 0.50,
        "spread_stop_pct": 0.80,
        "spread_partial_exit_pct": 0.75,
        "spread_partial_lots_pct": 0.50,
        "spread_theta_exit_dte": 0,
        "spread_theta_exit_time": "14:00",
        "straddle_strategy_enabled": True,
        "straddle_max_iv_rank": 20,
        "straddle_target_mult": 1.5,
        "straddle_stop_mult": 0.6,
        "straddle_close_both_on_target": False,
        "strangle_width_steps": 2,
        "ic_strategy_enabled": False,
        "ic_max_adx": 18,
        "ic_max_vix": 15,
        "ic_min_dte": 3,
        "ic_wing_width_steps": 1,
        "ic_profit_target": 0.5,
        "ic_stop_mult": 0.8,
    }
    base.update(overrides)
    return base


def _make_struct_cfg(**overrides: Any) -> dict[str, Any]:
    """Config with only the structured 'strategies' block."""
    base: dict[str, Any] = {
        "strategies": {
            "spread": {
                "enabled": False,
                "width_strikes": 5,
                "slippage_pct": 0.001,
            },
            "straddle": {
                "enabled": False,
                "max_iv_rank": 30,
            },
            "iron_condor": {
                "enabled": True,
                "max_adx": 25,
            },
        }
    }
    if overrides:
        # Deep-merge overrides into strategies
        result: dict[str, Any] = {"strategies": {}}
        for name, block in base["strategies"].items():
            result["strategies"][name] = dict(block)
        for name, block in overrides.items():
            if name in result["strategies"]:
                result["strategies"][name].update(block)
            else:
                result["strategies"][name] = block
        return result
    return base


# ── get_strategy_block ────────────────────────────────────────────────────────


class TestGetStrategyBlock:
    def test_structured_block_present(self) -> None:
        cfg = _make_struct_cfg()
        block = get_strategy_block(cfg, "spread")
        assert isinstance(block, dict)
        assert block.get("enabled") is False
        assert block.get("width_strikes") == 5

    def test_flat_only_config_returns_empty(self) -> None:
        cfg = _make_flat_cfg()
        block = get_strategy_block(cfg, "spread")
        assert block == {}

    def test_unknown_strategy_returns_empty(self) -> None:
        cfg = _make_struct_cfg()
        block = get_strategy_block(cfg, "nonexistent")
        assert block == {}

    def test_no_strategies_key_returns_empty(self) -> None:
        assert get_strategy_block({}, "spread") == {}

    def test_strategies_is_not_dict_returns_empty(self) -> None:
        assert get_strategy_block({"strategies": "nope"}, "spread") == {}

    def test_block_is_not_dict_returns_empty(self) -> None:
        assert get_strategy_block({"strategies": {"spread": "nope"}}, "spread") == {}


# ── get_strategy_param ────────────────────────────────────────────────────────


class TestGetStrategyParam:
    def test_structured_block_wins(self) -> None:
        cfg = _make_struct_cfg(spread={"width_strikes": 10})
        assert get_strategy_param(cfg, "spread", "width_strikes") == 10

    def test_flat_key_fallback(self) -> None:
        cfg = _make_flat_cfg(spread_width_strikes=7)
        assert get_strategy_param(cfg, "spread", "width_strikes") == 7

    def test_fallback_default(self) -> None:
        cfg: dict[str, Any] = {}
        assert get_strategy_param(cfg, "spread", "nonexistent", fallback=42) == 42

    def test_none_default_when_absent(self) -> None:
        assert get_strategy_param({}, "spread", "missing") is None

    def test_structured_wins_over_flat(self) -> None:
        cfg = _make_flat_cfg(spread_width_strikes=3)
        cfg.setdefault("strategies", {})["spread"] = {"width_strikes": 99}
        assert get_strategy_param(cfg, "spread", "width_strikes") == 99

    def test_unknown_strategy_uses_only_global_fallback(self) -> None:
        cfg = _make_flat_cfg()
        # No alias exists for "unknown_param" in "unknown_strategy"
        assert get_strategy_param(cfg, "unknown", "foo", fallback="bar") == "bar"

    def test_iron_condor_ic_prefix_fallback(self) -> None:
        cfg = _make_flat_cfg(ic_strategy_enabled=True, ic_max_adx=22)
        assert get_strategy_param(cfg, "iron_condor", "enabled") is True
        assert get_strategy_param(cfg, "iron_condor", "max_adx") == 22

    def test_strangle_width_steps(self) -> None:
        cfg = _make_flat_cfg(strangle_width_steps=3)
        assert get_strategy_param(cfg, "strangle", "width_steps") == 3

    def test_straddle_close_both_on_target(self) -> None:
        cfg = _make_flat_cfg(straddle_close_both_on_target=True)
        assert get_strategy_param(cfg, "straddle", "close_both_on_target") is True

    def test_enabled_false_from_structured(self) -> None:
        cfg = _make_struct_cfg(spread={"enabled": False})
        assert get_strategy_param(cfg, "spread", "enabled") is False


# ── StrategyConfigView / get_strategy_cfg ─────────────────────────────────────


class TestStrategyConfigView:
    def test_flat_key_via_get(self) -> None:
        cfg = _make_flat_cfg()
        view = get_strategy_cfg(cfg, "spread")
        assert view.get("enabled") is True
        assert view.get("width_strikes") == 3

    def test_structured_block_via_get(self) -> None:
        cfg = _make_struct_cfg(spread={"enabled": True, "width_strikes": 7})
        view = get_strategy_cfg(cfg, "spread")
        assert view.get("enabled") is True
        assert view.get("width_strikes") == 7

    def test_get_with_fallback(self) -> None:
        view = get_strategy_cfg({}, "spread")
        assert view.get("nonexistent", 123) == 123

    def test_get_returns_none_by_default(self) -> None:
        view = get_strategy_cfg({}, "spread")
        assert view.get("missing") is None

    def test_as_dict_flat_only(self) -> None:
        cfg = _make_flat_cfg()
        view = get_strategy_cfg(cfg, "spread")
        d = view.as_dict()
        assert isinstance(d, dict)
        assert d.get("enabled") is True
        assert d.get("width_strikes") == 3
        assert d.get("stop_pct") == 0.80

    def test_as_dict_structured_wins(self) -> None:
        cfg = _make_flat_cfg(spread_width_strikes=3)
        cfg.setdefault("strategies", {})["spread"] = {
            "enabled": False,
            "width_strikes": 99,
            "extra_key": "present",
        }
        view = get_strategy_cfg(cfg, "spread")
        d = view.as_dict()
        assert d["enabled"] is False  # structured wins
        assert d["width_strikes"] == 99  # structured wins
        assert d.get("extra_key") == "present"  # extra key from structured
        assert d.get("stop_pct") == 0.80  # flat fallback for unmapped keys

    def test_as_dict_empty_config(self) -> None:
        view = get_strategy_cfg({}, "spread")
        assert view.as_dict() == {}

    def test_as_dict_partial_config(self) -> None:
        view = get_strategy_cfg({"spread_strategy_enabled": True}, "spread")
        d = view.as_dict()
        assert d.get("enabled") is True


# ── Integration: structured + flat in real-world scenarios ────────────────────


class TestIntegration:
    def test_flat_keys_still_work_with_strategy_engines(self) -> None:
        """Verify spread_strategy.py's pattern works with flat keys only."""
        cfg = _make_flat_cfg(spread_strategy_enabled=True)
        scfg = get_strategy_cfg(cfg, "spread")
        assert scfg.get("enabled") is True
        assert scfg.get("width_strikes") == 3
        # Pattern used in spread_strategy.py
        if not scfg.get("enabled", False):
            raise AssertionError("should be enabled")
        width = int(scfg.get("width_strikes", 2))
        assert width == 3

    def test_structured_block_works_with_strategy_engines(self) -> None:
        """Verify spread_strategy.py's pattern works with structured block."""
        cfg = _make_struct_cfg(spread={"enabled": True, "width_strikes": 4})
        scfg = get_strategy_cfg(cfg, "spread")
        assert scfg.get("enabled") is True
        width = int(scfg.get("width_strikes", 2))
        assert width == 4

    def test_straddle_mixed_config(self) -> None:
        """Mix structured and flat across different strategies."""
        cfg = {
            "strategies": {"straddle": {"enabled": True}},
            "spread_strategy_enabled": False,
            "straddle_max_iv_rank": 25,
        }
        straddle_view = get_strategy_cfg(cfg, "straddle")
        spread_view = get_strategy_cfg(cfg, "spread")
        assert straddle_view.get("enabled") is True  # structured
        assert straddle_view.get("max_iv_rank") == 25  # flat fallback
        assert spread_view.get("enabled") is False  # flat

    def test_iron_condor_disabled_by_default(self) -> None:
        """IC is disabled by default even without any config keys."""
        view = get_strategy_cfg({}, "iron_condor")
        assert view.get("enabled") is None  # no default in config
        # The strategy engine checks for False, so absent is same as False
        assert view.get("enabled", False) is False
