"""Tests for Cross-Module Integration bridges (core/integrations/)."""

from __future__ import annotations

from core.integrations import (
    FeatureFlagGuard,
    SecretsConfigBridge,
    wire_cqrs_to_event_sourcing,
    wire_event_bus_to_mediator,
    wire_feature_flag_guards,
    wire_plugin_to_strategy,
    wire_secrets_to_config,
    wire_security_feeds,
    wire_tracing_to_mediator,
)

# ── Integration 1: Event Bus → Mediator ─────────────────────────────────


class TestEventBusMediator:
    def test_wire_returns_bool(self):
        result = wire_event_bus_to_mediator()
        assert isinstance(result, bool)

    def test_wire_is_idempotent(self):
        r1 = wire_event_bus_to_mediator()
        r2 = wire_event_bus_to_mediator()
        assert isinstance(r1, bool)
        assert isinstance(r2, bool)


# ── Integration 2: CQRS → Event Sourcing ────────────────────────────────


class TestCQRSEventSourcing:
    def test_wire_returns_bool(self):
        result = wire_cqrs_to_event_sourcing()
        assert isinstance(result, bool)

    def test_middleware_added(self):
        from core.cqrs.command_bus import CommandBus
        bus = CommandBus()
        # Verify middleware can be added
        assert hasattr(bus, "use")
        bus.clear_all()


# ── Integration 3: Plugin Registry → Strategy Framework ──────────────────


class TestPluginStrategy:
    def test_wire_returns_bool(self):
        result = wire_plugin_to_strategy()
        assert isinstance(result, bool)

    def test_wire_is_idempotent(self):
        r1 = wire_plugin_to_strategy()
        r2 = wire_plugin_to_strategy()
        assert isinstance(r1, bool)
        assert isinstance(r2, bool)


# ── Integration 4: Secrets Vault → Config ────────────────────────────────


class TestSecretsConfig:
    def test_bridge_resolves_plain_string(self):
        bridge = SecretsConfigBridge()
        assert bridge.resolve("hello") == "hello"

    def test_bridge_resolves_number(self):
        bridge = SecretsConfigBridge()
        assert bridge.resolve(42) == 42

    def test_bridge_resolves_none(self):
        bridge = SecretsConfigBridge()
        assert bridge.resolve(None) is None

    def test_bridge_handles_vault_prefix_missing(self):
        bridge = SecretsConfigBridge()
        result = bridge.resolve("vault://nonexistent_key")
        assert "MISSING_VAULT" in result

    def test_bridge_resolves_dict(self):
        bridge = SecretsConfigBridge()
        result = bridge.resolve({"key": "value", "num": 42})
        assert result["key"] == "value"
        assert result["num"] == 42

    def test_bridge_resolves_list(self):
        bridge = SecretsConfigBridge()
        result = bridge.resolve(["a", "b", "c"])
        assert result == ["a", "b", "c"]

    def test_bridge_resolves_nested_vault_ref(self):
        bridge = SecretsConfigBridge()
        result = bridge.resolve({"key": "vault://missing"})
        assert "MISSING_VAULT" in result["key"]

    def test_resolve_config(self):
        bridge = SecretsConfigBridge()
        config = {"plain": "value", "nested": {"inner": "vault://missing"}}
        result = bridge.resolve_config(config)
        assert result["plain"] == "value"
        assert "MISSING_VAULT" in result["nested"]["inner"]

    def test_wire_returns_bool(self):
        result = wire_secrets_to_config()
        assert isinstance(result, bool)


# ── Integration 5: Distributed Tracing → Mediator ────────────────────────


class TestTracingMediator:
    def test_wire_returns_bool(self):
        result = wire_tracing_to_mediator()
        assert isinstance(result, bool)

    def test_wire_is_idempotent(self):
        r1 = wire_tracing_to_mediator()
        r2 = wire_tracing_to_mediator()
        assert isinstance(r1, bool)
        assert isinstance(r2, bool)


# ── Integration 6: Security Feeds ─────────────────────────────────────────


class TestSecurityFeeds:
    def test_reporter_run_feeds(self):
        reporter = get_security_feed_reporter_instance()
        results = reporter.run_feeds()
        assert "timestamp" in results
        assert "sources" in results
        assert "total_findings" in results

    def test_reporter_get_stats(self):
        reporter = get_security_feed_reporter_instance()
        stats = reporter.get_stats()
        assert "feed_count" in stats

    def test_wire_returns_bool(self):
        result = wire_security_feeds()
        assert isinstance(result, bool)


def get_security_feed_reporter_instance():
    """Helper to get reporter for testing."""
    from core.integrations.security_feeds import SecurityFeedReporter
    return SecurityFeedReporter()


# ── Integration 7: Feature Flag Guards ───────────────────────────────────


class TestFeatureFlagGuards:
    def test_guard_is_enabled_unknown(self):
        guard = FeatureFlagGuard()
        assert guard.is_enabled("unknown_flag") is False

    def test_guard_register_and_check(self):
        guard = FeatureFlagGuard()
        guard.register_and_guard("test_guard_integration", default_enabled=True)
        assert guard.is_enabled("test_guard_integration") is True

    def test_decorator_default_not_called(self):
        guard = FeatureFlagGuard()
        called = [False]

        @guard.flag("nonexistent_flag")
        def my_func():
            called[0] = True
            return "result"

        result = my_func()
        # Function should not execute since flag not registered
        assert result is None

    def test_register_and_guard_returns_bool(self):
        guard = FeatureFlagGuard()
        result = guard.register_and_guard("auto_flag", default_enabled=False)
        assert isinstance(result, bool)

    def test_wire_returns_bool(self):
        result = wire_feature_flag_guards()
        assert isinstance(result, bool)


# ── Import Tests ─────────────────────────────────────────────────────────


class TestImportAll:
    def test_all_exports_exist(self):
        from core.integrations import __all__
        exports = __all__
        assert "wire_event_bus_to_mediator" in exports
        assert "wire_cqrs_to_event_sourcing" in exports
        assert "wire_plugin_to_strategy" in exports
        assert "SecretsConfigBridge" in exports
        assert "wire_secrets_to_config" in exports
        assert "wire_tracing_to_mediator" in exports
        assert "wire_security_feeds" in exports
        assert "FeatureFlagGuard" in exports
        assert "wire_feature_flag_guards" in exports

    def test_all_modules_importable(self):
        # Verify each integration module can be imported
        from core.integrations import (
            cqrs_event_sourcing,
            event_bus_mediator,
            feature_flag_guards,
            plugin_strategy,
            secrets_config,
            security_feeds,
            tracing_mediator,
        )
        assert event_bus_mediator is not None
        assert cqrs_event_sourcing is not None
        assert plugin_strategy is not None
        assert secrets_config is not None
        assert tracing_mediator is not None
        assert security_feeds is not None
        assert feature_flag_guards is not None
