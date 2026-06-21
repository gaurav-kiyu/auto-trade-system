"""Tests for core.multi_tenant — multi-tenant readiness module."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from core.multi_tenant import (
    MultiTenantManager,
    Tenant,
    TenantContext,
    get_multi_tenant_manager,
)


class TestTenant:
    """Tenant dataclass tests."""

    def test_defaults(self):
        tenant = Tenant(tenant_id="t1", name="Test Tenant")
        assert tenant.tenant_id == "t1"
        assert tenant.name == "Test Tenant"
        assert tenant.is_active is True
        assert tenant.max_daily_trades == 10
        assert tenant.max_open_positions == 5
        assert tenant.max_daily_loss == -2000.0
        assert tenant.max_capital == 100000.0
        assert tenant.feature_flags["ml_enabled"] is True
        assert tenant.feature_flags["equity_trading"] is False

    def test_custom_values(self):
        tenant = Tenant(
            tenant_id="t2",
            name="Custom Corp",
            is_active=False,
            max_daily_trades=20,
            max_open_positions=3,
            max_daily_loss=-5000.0,
            max_capital=500000.0,
            feature_flags={"ml_enabled": False, "webhook_enabled": True},
            config_overrides={"SL_PCT": 0.25},
        )
        assert tenant.tenant_id == "t2"
        assert tenant.is_active is False
        assert tenant.max_daily_trades == 20
        assert tenant.config_overrides["SL_PCT"] == 0.25

    def test_to_dict(self):
        tenant = Tenant(tenant_id="t1", name="Test")
        d = tenant.to_dict()
        assert d["tenant_id"] == "t1"
        assert d["name"] == "Test"
        assert d["is_active"] is True
        assert "created_at" in d
        assert "feature_flags" in d


class TestTenantContext:
    """TenantContext tests."""

    def test_init(self):
        tenant = Tenant(tenant_id="t1", name="Test")
        ctx = TenantContext(tenant)
        assert ctx.tenant_id == "t1"
        assert ctx.is_active is True

    def test_is_active_reflects_tenant(self):
        active = Tenant(tenant_id="a", name="Active")
        inactive = Tenant(tenant_id="i", name="Inactive", is_active=False)
        assert TenantContext(active).is_active is True
        assert TenantContext(inactive).is_active is False

    def test_can_trade_active(self):
        ctx = TenantContext(Tenant(tenant_id="t1", name="T"))
        assert ctx.can_trade() is True

    def test_can_trade_inactive(self):
        ctx = TenantContext(Tenant(tenant_id="t1", name="T", is_active=False))
        assert ctx.can_trade() is False

    def test_get_effective_config_base_only(self):
        ctx = TenantContext(Tenant(tenant_id="t1", name="T"), base_config={"MAX_TRADES_DAY": 15})
        cfg = ctx.get_effective_config()
        assert cfg["MAX_TRADES_DAY"] == 10  # Capped by tenant max_daily_trades

    def test_get_effective_config_with_overrides(self):
        tenant = Tenant(
            tenant_id="t1", name="T",
            max_daily_trades=8,
            config_overrides={"AI_THRESHOLD": 70},
        )
        ctx = TenantContext(tenant, base_config={"MAX_TRADES_DAY": 20, "AI_THRESHOLD": 60})
        cfg = ctx.get_effective_config()
        assert cfg["MAX_TRADES_DAY"] == 8  # Capped by tenant
        assert cfg["AI_THRESHOLD"] == 70  # Override

    def test_get_effective_config_loss_limit(self):
        """Takes the more conservative (less negative) of the two."""
        tenant = Tenant(tenant_id="t1", name="T", max_daily_loss=-3000.0)
        ctx = TenantContext(tenant, base_config={"MAX_DAILY_LOSS": -1000})
        cfg = ctx.get_effective_config()
        # max(-1000, -3000) = -1000 (less restrictive wins)
        assert cfg["MAX_DAILY_LOSS"] == -1000.0

    def test_get_trades_inactive(self):
        ctx = TenantContext(Tenant(tenant_id="t1", name="T", is_active=False))
        assert ctx.get_trades() == []

    def test_get_trades_db_error(self):
        ctx = TenantContext(Tenant(tenant_id="t1", name="T"))
        # Non-existent DB path returns empty list
        result = ctx.get_trades(db_path="/nonexistent/db.sqlite")
        assert result == []

    def test_get_state_missing_file(self):
        ctx = TenantContext(Tenant(tenant_id="t1", name="T"))
        state = ctx.get_state()
        assert state == {}

    def test_to_dict(self):
        ctx = TenantContext(Tenant(tenant_id="t1", name="Test"))
        d = ctx.to_dict()
        assert d["tenant_id"] == "t1"
        assert d["name"] == "Test"


class TestMultiTenantManager:
    """MultiTenantManager tests."""

    def test_init_disabled(self):
        mtm = MultiTenantManager({})
        assert mtm.enabled is False
        assert mtm.list_tenants() == []

    def test_init_enabled_no_tenants(self):
        mtm = MultiTenantManager({"multi_tenant_enabled": True})
        assert mtm.enabled is True

    def test_init_with_tenants_from_config(self):
        cfg = {
            "multi_tenant_enabled": True,
            "tenants": [
                {"tenant_id": "t1", "name": "Alpha"},
                {"tenant_id": "t2", "name": "Beta", "max_daily_trades": 25},
            ],
        }
        mtm = MultiTenantManager(cfg)
        assert mtm.enabled is True
        assert len(mtm.list_tenants()) == 2

    def test_register_tenant(self):
        mtm = MultiTenantManager({"multi_tenant_enabled": True})
        tenant = Tenant(tenant_id="t1", name="Test")
        ok = mtm.register_tenant(tenant)
        assert ok is True
        assert len(mtm.list_tenants()) == 1

    def test_register_duplicate_tenant(self):
        mtm = MultiTenantManager({"multi_tenant_enabled": True})
        tenant = Tenant(tenant_id="t1", name="Test")
        mtm.register_tenant(tenant)
        ok = mtm.register_tenant(tenant)
        assert ok is False

    def test_register_max_tenants(self):
        mtm = MultiTenantManager({"multi_tenant_enabled": True, "multi_tenant_max_tenants": 1})
        mtm.register_tenant(Tenant(tenant_id="t1", name="A"))
        ok = mtm.register_tenant(Tenant(tenant_id="t2", name="B"))
        assert ok is False

    def test_deactivate_tenant(self):
        mtm = MultiTenantManager({"multi_tenant_enabled": True})
        mtm.register_tenant(Tenant(tenant_id="t1", name="Test"))
        ok = mtm.deactivate_tenant("t1")
        assert ok is True
        tenant = mtm.get_tenant("t1")
        assert tenant is not None
        assert tenant.is_active is False

    def test_deactivate_nonexistent(self):
        mtm = MultiTenantManager({"multi_tenant_enabled": True})
        ok = mtm.deactivate_tenant("nonexistent")
        assert ok is False

    def test_activate_tenant(self):
        mtm = MultiTenantManager({"multi_tenant_enabled": True})
        mtm.register_tenant(Tenant(tenant_id="t1", name="Test"))
        mtm.deactivate_tenant("t1")
        mtm.activate_tenant("t1")
        tenant = mtm.get_tenant("t1")
        assert tenant is not None
        assert tenant.is_active is True

    def test_get_context_disabled(self):
        mtm = MultiTenantManager({})
        ctx = mtm.get_context("t1")
        assert ctx is None

    def test_get_context_nonexistent(self):
        mtm = MultiTenantManager({"multi_tenant_enabled": True})
        ctx = mtm.get_context("t1")
        assert ctx is None

    def test_get_context_with_registered(self):
        mtm = MultiTenantManager({"multi_tenant_enabled": True})
        mtm.register_tenant(Tenant(tenant_id="t1", name="Test"))
        ctx = mtm.get_context("t1")
        assert ctx is not None
        assert ctx.tenant_id == "t1"

    def test_get_context_caching(self):
        mtm = MultiTenantManager({"multi_tenant_enabled": True})
        mtm.register_tenant(Tenant(tenant_id="t1", name="Test"))
        ctx1 = mtm.get_context("t1")
        ctx2 = mtm.get_context("t1")
        assert ctx1 is ctx2  # Same instance (cached)

    def test_get_tenant(self):
        mtm = MultiTenantManager({"multi_tenant_enabled": True})
        mtm.register_tenant(Tenant(tenant_id="t1", name="Test"))
        tenant = mtm.get_tenant("t1")
        assert tenant is not None
        assert tenant.name == "Test"

    def test_get_tenant_nonexistent(self):
        mtm = MultiTenantManager({"multi_tenant_enabled": True})
        assert mtm.get_tenant("nonexistent") is None

    def test_get_stats(self):
        mtm = MultiTenantManager({"multi_tenant_enabled": True})
        mtm.register_tenant(Tenant(tenant_id="t1", name="A", is_active=True))
        mtm.register_tenant(Tenant(tenant_id="t2", name="B", is_active=False))
        stats = mtm.get_stats()
        assert stats["enabled"] is True
        assert stats["total_tenants"] == 2
        assert stats["active_tenants"] == 1

    def test_get_stats_disabled(self):
        mtm = MultiTenantManager({})
        stats = mtm.get_stats()
        assert stats["enabled"] is False
        assert stats["total_tenants"] == 0

    def test_thread_safety(self):
        """Concurrent access should not crash."""
        mtm = MultiTenantManager({"multi_tenant_enabled": True})
        import threading

        errors = []

        def _access():
            try:
                for i in range(5):
                    t = Tenant(tenant_id=f"t_{threading.get_ident()}_{i}", name="Test")
                    mtm.register_tenant(t)
                    mtm.get_tenant(t.tenant_id)
                    mtm.get_context(t.tenant_id)
                    mtm.deactivate_tenant(t.tenant_id)
                    mtm.activate_tenant(t.tenant_id)
                    mtm.get_stats()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=_access) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert len(errors) == 0, f"Thread safety errors: {errors}"


class TestSingleton:
    """Singleton accessor tests."""

    def test_get_multi_tenant_manager_singleton(self):
        m1 = get_multi_tenant_manager()
        m2 = get_multi_tenant_manager()
        assert m1 is m2

    def test_initialization_with_config(self):
        """Config should be applied on construction (test via constructor, not singleton)."""
        from core.multi_tenant import MultiTenantManager
        cfg = {"multi_tenant_enabled": True, "tenants": [
            {"tenant_id": "cfg_t1", "name": "Config Tenant"},
        ]}
        mtm = MultiTenantManager(cfg)
        assert mtm.enabled is True
        assert len(mtm.list_tenants()) == 1
        assert mtm.list_tenants()[0].tenant_id == "cfg_t1"
