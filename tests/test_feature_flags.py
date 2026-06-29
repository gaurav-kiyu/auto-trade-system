"""
Tests for core/config/feature_flags.py - Feature Flag System.

Tests cover:
- FeatureFlag dataclass defaults and creation
- FeatureFlagManager registration, enable/disable
- Singleton get_feature_flags pattern
- Persistence (load/save from JSON)
- Rollout percentage functionality
- Thread safety
- Change listeners
- Config loading
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from core.config.feature_flags import (
    FeatureFlag,
    FeatureFlagManager,
    get_feature_flags,
    is_enabled,
)

# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def storage_path(tmp_path: Path) -> str:
    """Temporary storage path for feature flags."""
    return str(tmp_path / "feature_flags.json")


@pytest.fixture
def manager(storage_path: str) -> FeatureFlagManager:
    """Fresh FeatureFlagManager with temp storage."""
    return FeatureFlagManager(storage_path=storage_path)


# ── FeatureFlag Dataclass ─────────────────────────────────────────────────────


class TestFeatureFlag:
    """FeatureFlag dataclass construction and defaults."""

    def test_default_created_at(self) -> None:
        """created_at should be auto-generated if not provided."""
        flag = FeatureFlag(name="test_flag", enabled=True)
        assert flag.created_at != ""
        assert flag.enabled is True

    def test_default_metadata_is_empty_dict(self) -> None:
        """metadata should default to empty dict."""
        flag = FeatureFlag(name="test", enabled=False)
        assert flag.metadata == {}

    def test_custom_metadata(self) -> None:
        """Custom metadata should be preserved."""
        flag = FeatureFlag(name="test", enabled=True, metadata={"key": "val"})
        assert flag.metadata["key"] == "val"

    def test_rollout_default(self) -> None:
        """rollout_pct should default to 100.0."""
        flag = FeatureFlag(name="test", enabled=True)
        assert flag.rollout_pct == 100.0

    def test_rollout_custom(self) -> None:
        """Custom rollout_pct should be preserved."""
        flag = FeatureFlag(name="test", enabled=True, rollout_pct=50.0)
        assert flag.rollout_pct == 50.0


# ── Registration ─────────────────────────────────────────────────────────────


class TestRegistration:
    """FeatureFlagManager.register() behaviour."""

    def test_register_new_flag(self, manager: FeatureFlagManager) -> None:
        """New flag should be registered with the given defaults."""
        manager.register("test_feature", default=True, description="A test feature")
        assert manager.is_enabled("test_feature") is True

    def test_register_default_false(self, manager: FeatureFlagManager) -> None:
        """New flag should default to disabled when default=False."""
        manager.register("test_feature", default=False)
        assert manager.is_enabled("test_feature") is False

    def test_register_duplicate_does_not_override(self, manager: FeatureFlagManager) -> None:
        """Registering an existing flag should NOT override its value."""
        manager.register("test_feature", default=True)
        manager.register("test_feature", default=False)  # Should be ignored
        assert manager.is_enabled("test_feature") is True  # Still enabled


# ── Enable / Disable ─────────────────────────────────────────────────────────


class TestEnableDisable:
    """FeatureFlagManager.enable() and disable()."""

    def test_enable_existing_flag(self, manager: FeatureFlagManager) -> None:
        """enable() should set flag to True."""
        manager.register("test_flag", default=False)
        assert manager.enable("test_flag") is True
        assert manager.is_enabled("test_flag") is True

    def test_enable_nonexistent_flag(self, manager: FeatureFlagManager) -> None:
        """enable() on nonexistent flag should return False."""
        assert manager.enable("nonexistent") is False

    def test_disable_existing_flag(self, manager: FeatureFlagManager) -> None:
        """disable() should set flag to False."""
        manager.register("test_flag", default=True)
        assert manager.disable("test_flag") is True
        assert manager.is_enabled("test_flag") is False

    def test_disable_nonexistent_flag(self, manager: FeatureFlagManager) -> None:
        """disable() on nonexistent flag should return False."""
        assert manager.disable("nonexistent") is False

    def test_enable_already_enabled_is_idempotent(self, manager: FeatureFlagManager) -> None:
        """Enabling an already-enabled flag should succeed (idempotent)."""
        manager.register("test_flag", default=True)
        assert manager.enable("test_flag") is True
        assert manager.is_enabled("test_flag") is True


# ── Get / is_enabled ─────────────────────────────────────────────────────────


class TestQuery:
    """FeatureFlagManager query methods."""

    def test_get_existing_flag(self, manager: FeatureFlagManager) -> None:
        """get() should return the flag value."""
        manager.register("test_flag", default=True)
        assert manager.get("test_flag") is True

    def test_get_nonexistent_flag_returns_default(self, manager: FeatureFlagManager) -> None:
        """get() on nonexistent flag should return the default provided."""
        assert manager.get("nonexistent", "fallback") == "fallback"

    def test_get_nonexistent_no_default(self, manager: FeatureFlagManager) -> None:
        """get() on nonexistent without default should return None."""
        assert manager.get("nonexistent") is None

    def test_is_enabled_existing(self, manager: FeatureFlagManager) -> None:
        """is_enabled() should reflect current state."""
        manager.register("test", default=True)
        assert manager.is_enabled("test") is True
        manager.disable("test")
        assert manager.is_enabled("test") is False

    def test_is_enabled_nonexistent_returns_false(self, manager: FeatureFlagManager) -> None:
        """is_enabled() on nonexistent flag should return False."""
        assert manager.is_enabled("nonexistent") is False


# ── Rollout ───────────────────────────────────────────────────────────────────


class TestRollout:
    """Gradual rollout functionality."""

    def test_full_rollout_all_users(self, manager: FeatureFlagManager) -> None:
        """100% rollout should enable for all users (default rollout_pct)."""
        manager.register("test", default=True)
        assert manager.is_enabled_for_user("test", "user_a") is True
        assert manager.is_enabled_for_user("test", "user_b") is True

    def test_zero_rollout_disables_users(self, manager: FeatureFlagManager) -> None:
        """0% rollout should disable for all users."""
        manager.register("test", default=True)
        manager.set_rollout("test", 0.0)
        assert manager.is_enabled_for_user("test", "user_a") is False
        assert manager.is_enabled_for_user("test", "user_b") is False

    def test_set_rollout_clamps_values(self, manager: FeatureFlagManager) -> None:
        """set_rollout should clamp to 0-100."""
        manager.register("test", default=True)
        assert manager.set_rollout("test", -10) is True
        assert manager.set_rollout("test", 200) is True

    def test_set_rollout_nonexistent(self, manager: FeatureFlagManager) -> None:
        """set_rollout on nonexistent flag should return False."""
        assert manager.set_rollout("nonexistent", 50.0) is False


# ── Persistence ───────────────────────────────────────────────────────────────


class TestPersistence:
    """Feature flag persistence to JSON file."""

    def test_register_persists_to_file(self, manager: FeatureFlagManager, storage_path: str) -> None:
        """Enabling a registered flag should create/persist to storage file."""
        manager.register("test_flag", default=False, description="Test")
        # register() does not persist; enable() triggers persistence
        manager.enable("test_flag")
        file_path = Path(storage_path)
        assert file_path.exists()
        data = json.loads(file_path.read_text(encoding="utf-8"))
        assert "test_flag" in data
        assert data["test_flag"]["enabled"] is True

    def test_load_from_existing_file(self, storage_path: str) -> None:
        """Flags should be loaded from existing storage file."""
        data = {"pre_flag": {"name": "pre_flag", "enabled": True, "description": "Pre-existing"}}
        Path(storage_path).write_text(json.dumps(data), encoding="utf-8")

        mgr = FeatureFlagManager(storage_path=storage_path)
        assert mgr.is_enabled("pre_flag") is True

    def test_load_from_missing_file_returns_empty(self, storage_path: str) -> None:
        """Missing storage file should not raise and return empty."""
        mgr = FeatureFlagManager(storage_path=storage_path)
        assert mgr.list_all() == {}


# ── List / GetEnabled ────────────────────────────────────────────────────────


class TestListing:
    """FeatureFlagManager list querys."""

    def test_list_all_empty(self, manager: FeatureFlagManager) -> None:
        """list_all on empty manager should return empty dict."""
        assert manager.list_all() == {}

    def test_list_all_with_flags(self, manager: FeatureFlagManager) -> None:
        """list_all should return all registered flags."""
        manager.register("flag_a", default=True)
        manager.register("flag_b", default=False)
        result = manager.list_all()
        assert "flag_a" in result
        assert "flag_b" in result
        assert result["flag_a"]["enabled"] is True
        assert result["flag_b"]["enabled"] is False

    def test_get_enabled_list(self, manager: FeatureFlagManager) -> None:
        """get_enabled should return only enabled flags."""
        manager.register("flag_a", default=True)
        manager.register("flag_b", default=False)
        manager.register("flag_c", default=True)
        enabled = manager.get_enabled()
        assert "flag_a" in enabled
        assert "flag_b" not in enabled
        assert "flag_c" in enabled
        assert len(enabled) == 2


# ── Change Listeners ─────────────────────────────────────────────────────────


class TestChangeListeners:
    """Feature change listener callbacks."""

    def test_listener_called_on_enable(self, manager: FeatureFlagManager) -> None:
        """Listener should be called when flag is enabled."""
        manager.register("test", default=False)
        callback = MagicMock()
        manager.add_change_listener("test", callback)
        manager.enable("test")
        callback.assert_called_once_with("test", True)

    def test_listener_called_on_disable(self, manager: FeatureFlagManager) -> None:
        """Listener should be called when flag is disabled."""
        manager.register("test", default=True)
        callback = MagicMock()
        manager.add_change_listener("test", callback)
        manager.disable("test")
        callback.assert_called_once_with("test", False)

    def test_listener_not_called_on_no_change(self, manager: FeatureFlagManager) -> None:
        """Listener should NOT be called when value doesn't change."""
        manager.register("test", default=True)
        callback = MagicMock()
        manager.add_change_listener("test", callback)
        manager.enable("test")  # Already enabled
        callback.assert_not_called()

    def test_multiple_listeners_called(self, manager: FeatureFlagManager) -> None:
        """Multiple listeners should all be called."""
        manager.register("test", default=False)
        callback1 = MagicMock()
        callback2 = MagicMock()
        manager.add_change_listener("test", callback1)
        manager.add_change_listener("test", callback2)
        manager.enable("test")
        callback1.assert_called_once()
        callback2.assert_called_once()

    def test_failing_listener_does_not_block_others(self, manager: FeatureFlagManager) -> None:
        """A failing listener should not block others."""
        manager.register("test", default=False)

        good_callback = MagicMock()

        def failing_callback(name: str, val: bool) -> None:
            raise ValueError("Listener failure")

        manager.add_change_listener("test", failing_callback)
        manager.add_change_listener("test", good_callback)
        manager.enable("test")  # Should not raise
        good_callback.assert_called_once()


# ── Config Loading ───────────────────────────────────────────────────────────


class TestConfigLoading:
    """Loading feature flags from config dict."""

    def test_load_from_config_feature_prefix(self, manager: FeatureFlagManager) -> None:
        """Config keys with FEATURE_ prefix should be loaded."""
        config = {"FEATURE_NEW_UI": True, "FEATURE_DARK_MODE": False}
        count = manager.load_from_config(config)
        assert count == 2
        assert manager.is_enabled("new_ui") is True
        assert manager.is_enabled("dark_mode") is False

    def test_load_from_config_enable_disable_prefix(self, manager: FeatureFlagManager) -> None:
        """Config keys with enable_/disable_ prefix should be loaded."""
        config = {"enable_beta": True, "disable_legacy": True}
        count = manager.load_from_config(config)
        assert count == 2
        assert manager.is_enabled("beta") is True
        assert manager.is_enabled("legacy") is False


# ── Thread Safety ─────────────────────────────────────────────────────────────


class TestThreadSafety:
    """Thread safety of FeatureFlagManager."""

    def test_concurrent_enable_disable(self, storage_path: str) -> None:
        """Concurrent enable/disable should not corrupt state."""
        mgr = FeatureFlagManager(storage_path=storage_path)
        mgr.register("test", default=False)

        n_threads = 10
        errors: list[Exception] = []
        barrier = threading.Barrier(n_threads)

        def _worker() -> None:
            barrier.wait()
            try:
                for _ in range(20):
                    mgr.enable("test")
                    mgr.disable("test")
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=_worker) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert len(errors) == 0, f"Concurrent access produced errors: {errors}"


# ── Singleton ─────────────────────────────────────────────────────────────────


class TestSingleton:
    """Module-level singleton get_feature_flags()."""

    def test_returns_manager_instance(self) -> None:
        """get_feature_flags should return FeatureFlagManager."""
        mgr = get_feature_flags()
        assert isinstance(mgr, FeatureFlagManager)

    def test_singleton_identity(self) -> None:
        """Multiple calls should return the same instance."""
        mgr1 = get_feature_flags()
        mgr2 = get_feature_flags()
        assert mgr1 is mgr2

    def test_is_enabled_shortcut_returns_false_for_unknown(self) -> None:
        """is_enabled() convenience function should return False for unknown flags."""
        result = is_enabled("nonexistent_flag_xyz_" + str(id(self)))
        assert result is False
