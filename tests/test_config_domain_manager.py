"""Unit tests for index_app.domains.config.manager — ConfigManager."""

from __future__ import annotations

import threading

import pytest
from index_app.domains.config.manager import ConfigManager

# ==============================================================================
# Fixtures
# ==============================================================================


@pytest.fixture()
def sample_cfg() -> dict:
    return {"KEY_STR": "hello", "KEY_INT": 42, "KEY_FLOAT": 3.14, "KEY_BOOL": True, "KEY_NONE": None}


@pytest.fixture()
def manager(sample_cfg: dict) -> ConfigManager:
    return ConfigManager(initial_cfg=sample_cfg, name="test")


# ==============================================================================
# Tests — Construction
# ==============================================================================


class TestConfigManagerInit:
    def test_init_empty(self):
        mgr = ConfigManager()
        assert mgr.all() == {}

    def test_init_with_config(self, sample_cfg: dict):
        mgr = ConfigManager(initial_cfg=sample_cfg)
        assert mgr.get("KEY_STR") == "hello"

    def test_init_with_name(self):
        mgr = ConfigManager(name="my-app")
        assert "my-app" in repr(mgr)

    def test_init_does_not_share_dict(self, sample_cfg: dict):
        mgr = ConfigManager(initial_cfg=sample_cfg)
        sample_cfg["NEW_KEY"] = "should_not_appear"
        assert mgr.get("NEW_KEY") is None


# ==============================================================================
# Tests — Read operations
# ==============================================================================


class TestConfigManagerRead:
    def test_get_existing_key(self, manager: ConfigManager):
        assert manager.get("KEY_STR") == "hello"

    def test_get_missing_key_default(self, manager: ConfigManager):
        assert manager.get("NONEXISTENT") is None
        assert manager.get("NONEXISTENT", 99) == 99

    def test_get_int(self, manager: ConfigManager):
        assert manager.get_int("KEY_INT") == 42

    def test_get_int_default(self, manager: ConfigManager):
        assert manager.get_int("NONEXISTENT", 10) == 10

    def test_get_float(self, manager: ConfigManager):
        assert manager.get_float("KEY_FLOAT") == 3.14

    def test_get_float_default(self, manager: ConfigManager):
        assert manager.get_float("NONEXISTENT", 1.5) == 1.5

    def test_get_bool(self, manager: ConfigManager):
        assert manager.get_bool("KEY_BOOL") is True

    def test_get_bool_default(self, manager: ConfigManager):
        assert manager.get_bool("NONEXISTENT", True) is True

    def test_get_str(self, manager: ConfigManager):
        assert manager.get_str("KEY_STR") == "hello"

    def test_get_str_default(self, manager: ConfigManager):
        assert manager.get_str("NONEXISTENT", "fallback") == "fallback"

    def test_all_returns_copy(self, manager: ConfigManager):
        all_cfg = manager.all()
        all_cfg["TAMPER"] = "yes"
        assert manager.get("TAMPER") is None

    def test_keys(self, manager: ConfigManager):
        keys = manager.keys()
        assert "KEY_STR" in keys
        assert "KEY_INT" in keys
        assert len(keys) == 5


# ==============================================================================
# Tests — Write operations
# ==============================================================================


class TestConfigManagerWrite:
    def test_set_new_key(self, manager: ConfigManager):
        manager.set("NEW_KEY", "new_val")
        assert manager.get("NEW_KEY") == "new_val"

    def test_set_updates_existing(self, manager: ConfigManager):
        manager.set("KEY_STR", "world")
        assert manager.get("KEY_STR") == "world"

    def test_update_merges(self, manager: ConfigManager):
        manager.update({"KEY_INT": 100, "NEW_KEY": "added"})
        assert manager.get("KEY_INT") == 100
        assert manager.get("NEW_KEY") == "added"
        assert manager.get("KEY_STR") == "hello"  # unchanged

    def test_replace_entire_config(self, manager: ConfigManager):
        manager.replace({"A": 1, "B": 2})
        assert manager.get("A") == 1
        assert manager.get("KEY_STR") is None  # old keys gone

    def test_hot_reload(self, manager: ConfigManager):
        result = manager.hot_reload({"X": 1})
        assert result["status"] == "ok"
        assert result["keys_before"] == 5
        assert result["keys_after"] == 1


# ==============================================================================
# Tests — Observer pattern
# ==============================================================================


class TestConfigManagerObservers:
    def test_observer_notified_on_set(self, manager: ConfigManager):
        observed: list[tuple] = []

        def obs(key, old, new):
            observed.append((key, old, new))

        manager.observe(obs)
        manager.set("KEY_INT", 99)
        assert len(observed) == 1
        assert observed[0] == ("KEY_INT", 42, 99)

    def test_observer_not_notified_on_new_key(self, manager: ConfigManager):
        """Setting a key that didn't exist before should NOT notify."""
        observed: list[tuple] = []

        def obs(key, old, new):
            observed.append((key, old, new))

        manager.observe(obs)
        manager.set("BRAND_NEW", "val")
        assert len(observed) == 0  # sentinel check prevents notification

    def test_observer_notified_on_update(self, manager: ConfigManager):
        observed: list[tuple] = []

        def obs(key, old, new):
            observed.append((key, old, new))

        manager.observe(obs)
        manager.update({"KEY_INT": 50, "KEY_STR": "updated"})
        assert len(observed) == 2

    def test_observer_notified_on_replace(self, manager: ConfigManager):
        observed: list[tuple] = []

        def obs(key, old, new):
            observed.append((key, old, new))

        manager.observe(obs)
        manager.replace({"KEY_INT": 99, "KEY_STR": "x"})
        assert len(observed) == 2

    def test_remove_observer(self, manager: ConfigManager):
        observed: list[tuple] = []

        def obs(key, old, new):
            observed.append((key, old, new))

        remove = manager.observe(obs)
        remove()
        manager.set("KEY_INT", 99)
        assert len(observed) == 0

    def test_observer_exception_does_not_crash(self, manager: ConfigManager):
        def bad_obs(key, old, new):
            raise ValueError("oops")

        def good_obs(key, old, new):
            good_obs.called = True

        good_obs.called = False
        manager.observe(bad_obs)
        manager.observe(good_obs)
        manager.set("KEY_INT", 99)
        assert good_obs.called is True


# ==============================================================================
# Tests — Thread safety
# ==============================================================================


class TestConfigManagerThreadSafety:
    def test_concurrent_set_and_get(self):
        mgr = ConfigManager({"counter": 0})
        n_threads = 10
        iterations = 100
        errors: list[Exception] = []

        def worker():
            for _ in range(iterations):
                try:
                    val = mgr.get_int("counter", 0)
                    mgr.set("counter", val + 1)
                except Exception as e:
                    errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Thread safety errors: {errors}"
        # Final value should be n_threads * iterations
        assert mgr.get_int("counter") == n_threads * iterations

    def test_concurrent_update_and_read(self):
        mgr = ConfigManager({"x": 0})
        n_threads = 5
        iterations = 50
        errors: list[Exception] = []

        def writer():
            for i in range(iterations):
                try:
                    mgr.update({"x": i})
                except Exception as e:
                    errors.append(e)

        def reader():
            for _ in range(iterations):
                try:
                    _ = mgr.get("x")
                except Exception as e:
                    errors.append(e)

        threads = [threading.Thread(target=writer) for _ in range(n_threads)]
        threads += [threading.Thread(target=reader) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0

    def test_concurrent_observer_add_remove(self, manager: ConfigManager):
        """Registering and removing observers from multiple threads should be safe."""
        errors: list[Exception] = []

        def add_remove():
            for _ in range(20):
                try:
                    remove = manager.observe(lambda k, o, n: None)
                    remove()
                except Exception as e:
                    errors.append(e)

        threads = [threading.Thread(target=add_remove) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0


# ==============================================================================
# Tests — Utility
# ==============================================================================


class TestConfigManagerUtils:
    def test_repr(self, manager: ConfigManager):
        r = repr(manager)
        assert "test" in r
        assert "5" in r
