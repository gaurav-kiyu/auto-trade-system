"""
Feature Flags - Item 14

Enable/disable safely without redeploy:
- live_vix
- expiry_guard
- circuit_breaker_mode

Clean feature toggle system.
"""
from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from core.datetime_ist import now_ist
from typing import Any

_log = logging.getLogger(__name__)


@dataclass
class FeatureFlag:
    """Feature flag definition"""
    name: str
    enabled: bool
    description: str = ""
    rollout_pct: float = 100.0
    created_at: str = ""
    updated_at: str = ""
    metadata: dict[str, Any] = None

    def __post_init__(self):
        if not self.created_at:
            from core.time_provider import time_provider
            self.created_at = time_provider.format_ts()
        if self.metadata is None:
            self.metadata = {}


class FeatureFlagManager:
    """
    Feature flag management system.
    Allows safe enable/disable of features without redeploy.
    """

    def __init__(self, storage_path: str = "feature_flags.json"):
        self._flags: dict[str, FeatureFlag] = {}
        self._storage_path = storage_path
        self._lock = threading.Lock()
        self._change_listeners: dict[str, list[Callable]] = {}
        self._load_flags()

    def _load_flags(self) -> None:
        """Load flags from storage"""
        try:
            with open(self._storage_path) as f:
                data = json.load(f)
                for name, flag_data in data.items():
                    self._flags[name] = FeatureFlag(**flag_data)
            _log.info(f"Loaded {len(self._flags)} feature flags")
        except FileNotFoundError:
            _log.info("No existing feature flags, starting fresh")
        except Exception as e:
            _log.warning(f"Failed to load feature flags: {e}")

    def _save_flags(self) -> None:
        """Save flags to storage"""
        try:
            data = {
                name: {
                    "name": f.name,
                    "enabled": f.enabled,
                    "description": f.description,
                    "rollout_pct": f.rollout_pct,
                    "created_at": f.created_at,
                    "updated_at": f.updated_at,
                    "metadata": f.metadata,
                }
                for name, f in self._flags.items()
            }
            with open(self._storage_path, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            _log.error(f"Failed to save feature flags: {e}")

    def register(self, name: str, default: bool = False, description: str = "", metadata: dict = None) -> None:
        """Register a new feature flag"""
        with self._lock:
            if name not in self._flags:
                self._flags[name] = FeatureFlag(
                    name=name,
                    enabled=default,
                    description=description,
                    metadata=metadata or {},
                )
                _log.info(f"Registered feature flag: {name} (default: {default})")

    def enable(self, name: str) -> bool:
        """Enable a feature flag"""
        with self._lock:
            if name in self._flags:
                old_value = self._flags[name].enabled
                self._flags[name].enabled = True
                self._flags[name].updated_at = now_ist().isoformat()
                self._save_flags()

                if old_value != True:
                    self._notify_change(name, True)

                _log.info(f"Enabled feature flag: {name}")
                return True
            return False

    def disable(self, name: str) -> bool:
        """Disable a feature flag"""
        with self._lock:
            if name in self._flags:
                old_value = self._flags[name].enabled
                self._flags[name].enabled = False
                self._flags[name].updated_at = now_ist().isoformat()
                self._save_flags()

                if old_value != False:
                    self._notify_change(name, False)

                _log.info(f"Disabled feature flag: {name}")
                return True
            return False

    def is_enabled(self, name: str) -> bool:
        """Check if feature flag is enabled"""
        with self._lock:
            return self._flags.get(name, FeatureFlag(name=name, enabled=False)).enabled

    def get(self, name: str, default: Any = None) -> Any:
        """Get feature flag value or default"""
        with self._lock:
            flag = self._flags.get(name)
            if flag:
                return flag.enabled
            return default

    def is_enabled_for_user(self, name: str, user_id: str = "default") -> bool:
        """
        Check if feature is enabled for specific user (for gradual rollout).
        
        Uses deterministic hashing for consistent rollout.
        """
        flag = self._flags.get(name)
        if not flag:
            return False

        if not flag.enabled:
            return False

        if flag.rollout_pct >= 100.0:
            return True

        hash_val = hash(f"{name}:{user_id}") % 100
        return hash_val < flag.rollout_pct

    def set_rollout(self, name: str, rollout_pct: float) -> bool:
        """Set rollout percentage (0-100)"""
        with self._lock:
            if name in self._flags:
                self._flags[name].rollout_pct = max(0, min(100, rollout_pct))
                self._flags[name].updated_at = now_ist().isoformat()
                self._save_flags()
                _log.info(f"Set rollout for {name}: {rollout_pct}%")
                return True
            return False

    def add_change_listener(self, name: str, callback: Callable[[str, bool], None]) -> None:
        """Add listener for flag changes"""
        if name not in self._change_listeners:
            self._change_listeners[name] = []
        self._change_listeners[name].append(callback)

    def _notify_change(self, name: str, new_value: bool) -> None:
        """Notify listeners of flag change"""
        for callback in self._change_listeners.get(name, []):
            try:
                callback(name, new_value)
            except Exception as e:
                _log.error(f"Feature flag listener error: {e}")

    def load_from_config(self, config: dict[str, Any], prefix: str = "FEATURE_") -> int:
        """Load feature flags from config"""
        loaded = 0
        for key, value in config.items():
            if key.startswith(prefix):
                flag_name = key[len(prefix):].lower()
                self.register(flag_name, bool(value), f"From config: {key}")
                loaded += 1
            elif key.startswith("enable_") or key.startswith("disable_"):
                flag_name = key.replace("enable_", "").replace("disable_", "").lower()
                self.register(flag_name, key.startswith("enable_"), f"From config: {key}")
                loaded += 1
        return loaded

    def list_all(self) -> dict[str, dict[str, Any]]:
        """List all feature flags"""
        with self._lock:
            return {
                name: {
                    "enabled": f.enabled,
                    "description": f.description,
                    "rollout_pct": f.rollout_pct,
                    "updated_at": f.updated_at,
                }
                for name, f in self._flags.items()
            }

    def get_enabled(self) -> list[str]:
        """Get list of enabled flags"""
        with self._lock:
            return [name for name, f in self._flags.items() if f.enabled]


_flag_manager: FeatureFlagManager | None = None
_flag_lock = threading.Lock()


def get_feature_flags() -> FeatureFlagManager:
    """Get singleton feature flag manager"""
    global _flag_manager
    with _flag_lock:
        if _flag_manager is None:
            _flag_manager = FeatureFlagManager()
        return _flag_manager


def is_enabled(flag_name: str) -> bool:
    """Quick check if flag is enabled"""
    return get_feature_flags().is_enabled(flag_name)
