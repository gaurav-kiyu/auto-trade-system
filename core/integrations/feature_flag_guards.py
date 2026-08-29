"""Integration 7: Feature Flags -> All Modules.

Provides a FeatureFlagGuard utility that wraps any module or function
with conditional behavior based on feature flags. Enables gradual
rollouts, kill-switches, and A/B testing across the entire platform.

Usage:
    from core.integrations import FeatureFlagGuard

    guard = FeatureFlagGuard()

    # Guard a function call
    @guard.flag("new_algorithm")
    def experimental_func():
        return "new stuff"

    # Guard a conditional block
    if guard.is_enabled("new_dashboard", user_id="user123"):
        show_new_dashboard()
    else:
        show_old_dashboard()
"""

from __future__ import annotations

import functools
import logging
from collections.abc import Callable
from typing import Any

_log = logging.getLogger(__name__)


class FeatureFlagGuard:
    """Guard module/function behavior with Feature Flags.

    Provides decorators and context managers for feature-flag-gated code.
    """

    def __init__(self) -> None:
        self._fm = None

    def _get_manager(self):
        """Lazy-load feature flag manager."""
        if self._fm is None:
            try:
                from core.feature_flags import get_feature_flag_manager
                self._fm = get_feature_flag_manager()
            except ImportError:
                return None
        return self._fm

    def is_enabled(self, flag_key: str, user_id: str = "",
                   context: dict[str, Any] | None = None) -> bool:
        """Check if a feature flag is enabled.

        Args:
            flag_key: Feature flag key.
            user_id: Optional user identifier for gradual rollout.
            context: Optional context dict.

        Returns:
            True if the feature is enabled.
        """
        fm = self._get_manager()
        if fm is None:
            return False  # Safe default when flags not available
        return fm.is_enabled(flag_key, user_id, context)

    _SENTINEL = object()

    def flag(self, flag_key: str, default_return: Any = _SENTINEL) -> Callable:
        """Decorator: Guard a function with a feature flag.

        If the flag is disabled, returns ``default_return`` instead of
        executing the function. If ``default_return`` is not provided,
        returns ``None``.

        Usage:
            @guard.flag("experimental_feature")
            def my_func():
                return "result"

            @guard.flag("new_algo", default_return=0)
            def calculate():
                return 42
        """
        def decorator(func: Callable) -> Callable:
            @functools.wraps(func)
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                if self.is_enabled(flag_key):
                    return func(*args, **kwargs)
                return default_return if default_return is not self._SENTINEL else None
            return wrapper
        return decorator

    def register_and_guard(self, flag_key: str, default_enabled: bool = False,
                           description: str = "", module_name: str = "") -> bool:
        """Register a flag and return its current state.

        Convenience method for modules to self-register their feature flag.

        Args:
            flag_key: Feature flag key.
            default_enabled: Default state.
            description: Human-readable description.
            module_name: Owning module name.

        Returns:
            Current enabled state.
        """
        fm = self._get_manager()
        if fm is None:
            return default_enabled

        if not fm.get_flag(flag_key):
            fm.register_flag(
                key=flag_key,
                default=default_enabled,
                description=description or f"Feature flag for {flag_key}",
                owners=[module_name] if module_name else [],
                tags=["auto-registered"],
            )
        return fm.is_enabled(flag_key)


_guard: FeatureFlagGuard | None = None


def get_feature_flag_guard() -> FeatureFlagGuard:
    """Get the singleton FeatureFlagGuard."""
    global _guard
    if _guard is None:
        _guard = FeatureFlagGuard()
    return _guard


def wire_feature_flag_guards() -> bool:
    """Wire Feature Flags into module behavior gating.

    Creates the FeatureFlagGuard singleton for use across all modules.

    Returns:
        True if wired successfully.
    """
    try:
        get_feature_flag_guard()
        _log.info("[INTEGRATION] Feature Flags -> All Modules: WIRED")
        return True
    except Exception as exc:
        _log.warning("[INTEGRATION] Feature Flag Guards: ERROR (%s)", exc)
        return False


__all__ = ["FeatureFlagGuard", "get_feature_flag_guard", "wire_feature_flag_guards"]
