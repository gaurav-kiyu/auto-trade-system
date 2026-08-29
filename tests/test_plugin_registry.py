"""Tests for Plugin Registry module (core/plugin_registry.py)."""

from __future__ import annotations

import pytest
from core.plugin_registry import get_plugin_registry, reset_plugin_registry


@pytest.fixture(autouse=True)
def reset_registry():
    reset_plugin_registry()
    yield
    reset_plugin_registry()


class TestRegistration:
    def test_register_plugin(self):
        reg = get_plugin_registry()
        entry = reg.register_plugin("my_strategy", plugin_type="strategy", version="1.0.0")
        assert entry.meta.name == "my_strategy"
        assert entry.meta.plugin_type == "strategy"
        assert entry.meta.version == "1.0.0"

    def test_register_plugin_invalid_type(self):
        reg = get_plugin_registry()
        entry = reg.register_plugin("custom", plugin_type="invalid_type")
        assert entry.meta.plugin_type == "other"

    def test_get_plugin(self):
        reg = get_plugin_registry()
        reg.register_plugin("my_plugin")
        entry = reg.get_plugin("my_plugin")
        assert entry is not None
        assert entry.meta.name == "my_plugin"

    def test_get_plugin_unknown(self):
        reg = get_plugin_registry()
        assert reg.get_plugin("nonexistent") is None

    def test_unregister_plugin(self):
        reg = get_plugin_registry()
        reg.register_plugin("temp")
        assert reg.unregister_plugin("temp") is True
        assert reg.get_plugin("temp") is None

    def test_list_plugins(self):
        reg = get_plugin_registry()
        reg.register_plugin("a", plugin_type="strategy")
        reg.register_plugin("b", plugin_type="broker")
        assert len(reg.list_plugins()) == 2

    def test_list_by_type(self):
        reg = get_plugin_registry()
        reg.register_plugin("strat_a", plugin_type="strategy")
        reg.register_plugin("strat_b", plugin_type="strategy")
        reg.register_plugin("broker_c", plugin_type="broker")
        assert len(reg.list_plugins(plugin_type="strategy")) == 2
        assert len(reg.list_plugins(plugin_type="broker")) == 1

    def test_get_plugins_by_type(self):
        reg = get_plugin_registry()
        reg.register_plugin("s1", plugin_type="strategy")
        reg.register_plugin("b1", plugin_type="broker")
        by_type = reg.get_plugins_by_type()
        assert "strategy" in by_type
        assert "broker" in by_type
        assert len(by_type["strategy"]) == 1
        assert len(by_type["broker"]) == 1


class TestPluginLifecycle:
    def test_load_plugin_with_class(self):
        reg = get_plugin_registry()

        class DummyPlugin:
            def on_enable(self):
                pass
            def on_disable(self):
                pass

        reg.register_plugin("dummy", plugin_class=DummyPlugin)
        assert reg.load_plugin("dummy") is True
        entry = reg.get_plugin("dummy")
        assert entry.loaded is True
        assert entry.instance is not None

    def test_load_unknown_plugin(self):
        reg = get_plugin_registry()
        assert reg.load_plugin("unknown") is False

    def test_double_load_is_noop(self):
        reg = get_plugin_registry()

        class P:
            pass

        reg.register_plugin("p", plugin_class=P)
        assert reg.load_plugin("p") is True
        assert reg.load_plugin("p") is True  # Idempotent

    def test_enable_plugin(self):
        reg = get_plugin_registry()

        class P:
            def on_enable(self):
                self._enabled = True

        reg.register_plugin("p", plugin_class=P)
        reg.load_plugin("p")
        assert reg.enable_plugin("p") is True
        entry = reg.get_plugin("p")
        assert entry.enabled is True

    def test_enable_not_loaded(self):
        reg = get_plugin_registry()
        reg.register_plugin("p")
        assert reg.enable_plugin("p") is False  # Must load first

    def test_disable_plugin(self):
        reg = get_plugin_registry()

        class P:
            def on_enable(self):
                pass
            def on_disable(self):
                self._disabled = True

        reg.register_plugin("p", plugin_class=P)
        reg.load_plugin("p")
        reg.enable_plugin("p")
        assert reg.disable_plugin("p") is True
        entry = reg.get_plugin("p")
        assert entry.enabled is False

    def test_unload_plugin(self):
        reg = get_plugin_registry()

        class P:
            pass

        reg.register_plugin("p", plugin_class=P)
        reg.load_plugin("p")
        reg.enable_plugin("p")
        assert reg.unload_plugin("p") is True
        entry = reg.get_plugin("p")
        assert entry.loaded is False
        assert entry.instance is None

    def test_get_enabled_plugins(self):
        reg = get_plugin_registry()

        class P1:
            pass

        class P2:
            pass

        reg.register_plugin("p1", plugin_class=P1)
        reg.register_plugin("p2", plugin_class=P2)
        reg.load_plugin("p1")
        reg.load_plugin("p2")
        reg.enable_plugin("p1")
        enabled = reg.get_enabled_plugins()
        assert len(enabled) == 1
        assert enabled[0].meta.name == "p1"


class TestPluginMethodCall:
    def test_call_plugin_method(self):
        reg = get_plugin_registry()

        class Calc:
            def add(self, a, b):
                return a + b

        reg.register_plugin("calc", plugin_class=Calc)
        reg.load_plugin("calc")
        reg.enable_plugin("calc")
        result = reg.call_plugin_method("calc", "add", 3, 4)
        assert result == 7

    def test_call_method_not_found(self):
        reg = get_plugin_registry()

        class P:
            pass

        reg.register_plugin("p", plugin_class=P)
        reg.load_plugin("p")
        reg.enable_plugin("p")
        assert reg.call_plugin_method("p", "nonexistent") is None


class TestStats:
    def test_get_stats_empty(self):
        reg = get_plugin_registry()
        stats = reg.get_stats()
        assert stats["total_plugins"] == 0

    def test_get_stats_with_plugins(self):
        reg = get_plugin_registry()
        reg.register_plugin("a", plugin_type="strategy")
        reg.register_plugin("b", plugin_type="broker")
        stats = reg.get_stats()
        assert stats["total_plugins"] == 2
        assert stats["by_type"]["strategy"] == 1
        assert stats["by_type"]["broker"] == 1


class TestSingleton:
    def test_singleton(self):
        r1 = get_plugin_registry()
        r2 = get_plugin_registry()
        assert r1 is r2

    def test_reset(self):
        r1 = get_plugin_registry()
        reset_plugin_registry()
        r2 = get_plugin_registry()
        assert r1 is not r2
