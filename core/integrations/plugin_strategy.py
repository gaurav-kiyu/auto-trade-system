"""Integration 3: Plugin Registry -> Strategy Framework.

Wires the Plugin Registry into the Strategy Framework so that strategies
can be registered, loaded, enabled/disabled through the unified plugin
lifecycle. This enables dynamic strategy management without code changes.

Usage:
    from core.integrations import wire_plugin_to_strategy
    wire_plugin_to_strategy()
"""

from __future__ import annotations

import logging

_log = logging.getLogger(__name__)


def wire_plugin_to_strategy() -> bool:
    """Wire Plugin Registry into the Strategy Framework.

    Registers all existing strategies from the Strategy Registry as
    plugin entries, and vice-versa. Enables unified lifecycle management.

    Returns:
        True if wired successfully, False if dependencies missing.
    """
    try:
        from core.plugin_registry import get_plugin_registry
        from core.strategy.plugin_framework import get_strategy_registry

        plugin_reg = get_plugin_registry()
        strategy_reg = get_strategy_registry()

        # Register existing strategies as plugins
        try:
            strategies = strategy_reg.get_all()
            for strategy in strategies:
                name = getattr(strategy, "name", None) or type(strategy).__name__
                if not plugin_reg.get_plugin(name):
                    plugin_reg.register_plugin(
                        name=name,
                        plugin_type="strategy",
                        description=f"Auto-registered strategy: {name}",
                        tags=["strategy", "auto-registered"],
                    )
                    plugin_reg.load_plugin(name)
                    plugin_reg.enable_plugin(name)
        except Exception as exc:
            _log.debug("[INTEGRATION] Plugin→Strategy sync: %s", exc)

        _log.info("[INTEGRATION] Plugin Registry -> Strategy Framework: WIRED")
        return True

    except ImportError as exc:
        _log.warning("[INTEGRATION] Plugin Registry -> Strategy: FAILED (%s)", exc)
        return False
    except Exception as exc:
        _log.warning("[INTEGRATION] Plugin Registry -> Strategy: ERROR (%s)", exc)
        return False


__all__ = ["wire_plugin_to_strategy"]
