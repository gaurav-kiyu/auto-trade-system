"""Tests for ControlRBAC — RBAC facade for the admin control plane."""

from __future__ import annotations

import pytest

# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def rbac():
    """Create a ControlRBAC with a RoleManager."""
    from core.control_plane.rbac import ControlRBAC
    return ControlRBAC()


@pytest.fixture
def rbac_with_assignments(rbac):
    """Create a ControlRBAC with pre-assigned roles."""
    rbac.role_manager.assign("alice", "admin")
    rbac.role_manager.assign("bob", "operator")
    rbac.role_manager.assign("charlie", "observer")
    return rbac


# ──────────────────────────────────────────────────────────────────────────────
# Endpoint Authorization
# ──────────────────────────────────────────────────────────────────────────────


class TestEndpointAuthorization:
    def test_admin_can_kill_trading(self, rbac_with_assignments):
        allowed, reason = rbac_with_assignments.check_endpoint("alice", "control_kill")
        assert allowed
        assert reason == ""

    def test_admin_can_modify_config(self, rbac_with_assignments):
        allowed, reason = rbac_with_assignments.check_endpoint("alice", "control_capital")
        assert allowed

    def test_admin_can_modify_risk_limits(self, rbac_with_assignments):
        allowed, reason = rbac_with_assignments.check_endpoint("alice", "control_risk_limit")
        assert allowed

    def test_admin_can_deploy_models(self, rbac_with_assignments):
        allowed, reason = rbac_with_assignments.check_endpoint("alice", "control_ai_model")
        assert allowed

    def test_admin_can_view_state(self, rbac_with_assignments):
        allowed, reason = rbac_with_assignments.check_endpoint("alice", "control_state")
        assert allowed

    def test_operator_can_halt_trading(self, rbac_with_assignments):
        allowed, reason = rbac_with_assignments.check_endpoint("bob", "control_kill")
        assert allowed

    def test_operator_can_toggle_strategies(self, rbac_with_assignments):
        allowed, reason = rbac_with_assignments.check_endpoint("bob", "control_strategy_enable")
        assert allowed

    def test_operator_cannot_modify_risk_limits(self, rbac_with_assignments):
        allowed, reason = rbac_with_assignments.check_endpoint("bob", "control_risk_limit")
        assert not allowed
        assert "lacks" in reason.lower()

    def test_operator_cannot_modify_config(self, rbac_with_assignments):
        allowed, reason = rbac_with_assignments.check_endpoint("bob", "control_capital")
        assert not allowed

    def test_observer_can_view_state(self, rbac_with_assignments):
        allowed, reason = rbac_with_assignments.check_endpoint("charlie", "control_state")
        assert allowed

    def test_observer_cannot_halt_trading(self, rbac_with_assignments):
        allowed, reason = rbac_with_assignments.check_endpoint("charlie", "control_kill")
        assert not allowed

    def test_observer_cannot_modify_config(self, rbac_with_assignments):
        allowed, reason = rbac_with_assignments.check_endpoint("charlie", "control_capital")
        assert not allowed

    def test_unknown_endpoint_denied(self, rbac_with_assignments):
        allowed, reason = rbac_with_assignments.check_endpoint("alice", "nonexistent_endpoint")
        assert not allowed
        assert "Unknown" in reason

    def test_unknown_identity_default_role(self, rbac):
        """Unknown identity should get the default role."""
        allowed, reason = rbac.check_endpoint("unknown", "control_state")
        # Default is observer which can view state
        assert allowed


# ──────────────────────────────────────────────────────────────────────────────
# Permission Checks
# ──────────────────────────────────────────────────────────────────────────────


class TestPermissionChecks:
    def test_check_permission_allowed(self, rbac_with_assignments):
        from core.auth.permissions import Permission
        allowed, reason = rbac_with_assignments.check_permission("alice", Permission.MODIFY_CONFIG)
        assert allowed

    def test_check_permission_denied(self, rbac_with_assignments):
        from core.auth.permissions import Permission
        allowed, reason = rbac_with_assignments.check_permission("charlie", Permission.MODIFY_CONFIG)
        assert not allowed

    def test_check_permission_string(self, rbac_with_assignments):
        allowed, reason = rbac_with_assignments.check_permission("alice", "view_state")
        assert allowed

    def test_check_permission_denied_string(self, rbac_with_assignments):
        allowed, reason = rbac_with_assignments.check_permission("bob", "add_brokers")
        assert not allowed

    def test_require_endpoint_allowed(self, rbac_with_assignments):
        rbac_with_assignments.require_endpoint("alice", "control_kill")  # Should not raise

    def test_require_endpoint_denied(self, rbac_with_assignments):
        from core.auth.permissions import PermissionDenied
        with pytest.raises(PermissionDenied):
            rbac_with_assignments.require_endpoint("charlie", "control_kill")

    def test_require_permission_allowed(self, rbac_with_assignments):
        from core.auth.permissions import Permission
        rbac_with_assignments.require_permission("alice", Permission.MODIFY_CONFIG)

    def test_require_permission_denied(self, rbac_with_assignments):
        from core.auth.permissions import Permission, PermissionDenied
        with pytest.raises(PermissionDenied):
            rbac_with_assignments.require_permission("charlie", Permission.MODIFY_CONFIG)


# ──────────────────────────────────────────────────────────────────────────────
# Role Management
# ──────────────────────────────────────────────────────────────────────────────


class TestRoleManagement:
    def test_get_identity_role(self, rbac_with_assignments):
        from core.auth.permissions import Role
        assert rbac_with_assignments.get_identity_role("alice") == Role.ADMIN
        assert rbac_with_assignments.get_identity_role("unknown") == Role.OBSERVER

    def test_list_assignments(self, rbac_with_assignments):
        assignments = rbac_with_assignments.list_assignments()
        assert assignments.get("alice") == "admin"
        assert assignments.get("bob") == "operator"

    def test_get_permissions_for_admin(self, rbac_with_assignments):
        from core.auth.permissions import Role
        perms = rbac_with_assignments.get_permissions_for_role(Role.ADMIN)
        assert "view_state" in perms
        assert "modify_config" in perms
        assert "halt_trading" in perms
        assert "add_brokers" in perms

    def test_get_permissions_for_observer(self, rbac_with_assignments):
        from core.auth.permissions import Role
        perms = rbac_with_assignments.get_permissions_for_role(Role.OBSERVER)
        assert "view_state" in perms
        assert "view_logs" in perms
        assert "modify_config" not in perms

    def test_get_permissions_as_string(self, rbac_with_assignments):
        perms = rbac_with_assignments.get_permissions_for_role("admin")
        assert "modify_config" in perms

    def test_has_permission_true(self, rbac_with_assignments):
        from core.auth.permissions import Permission
        assert rbac_with_assignments.has_permission("alice", Permission.VIEW_STATE)
        assert rbac_with_assignments.has_permission("alice", Permission.MODIFY_CONFIG)

    def test_has_permission_false(self, rbac_with_assignments):
        from core.auth.permissions import Permission
        assert not rbac_with_assignments.has_permission("charlie", Permission.MODIFY_CONFIG)
        assert not rbac_with_assignments.has_permission("bob", Permission.ADD_BROKERS)


# ──────────────────────────────────────────────────────────────────────────────
# Config Loading
# ──────────────────────────────────────────────────────────────────────────────


class TestConfigLoading:
    def test_load_from_config(self, rbac):
        rbac.load_from_config({
            "admin_roles": {"alice": "admin", "bob": "operator"},
            "admin_default_role": "observer",
        })
        from core.auth.permissions import Role
        assert rbac.get_identity_role("alice") == Role.ADMIN
        assert rbac.get_identity_role("bob") == Role.OPERATOR
        assert rbac.get_identity_role("stranger") == Role.OBSERVER

    def test_load_from_config_empty(self, rbac):
        rbac.load_from_config({})
        from core.auth.permissions import Role
        assert rbac.get_identity_role("anyone") == Role.OBSERVER

    def test_load_from_config_overrides(self, rbac):
        rbac.role_manager.assign("alice", "observer")
        rbac.load_from_config({"admin_roles": {"alice": "admin"}})
        from core.auth.permissions import Role
        assert rbac.get_identity_role("alice") == Role.ADMIN


# ──────────────────────────────────────────────────────────────────────────────
# Role Manager Delegation
# ──────────────────────────────────────────────────────────────────────────────


class TestRoleManagerDelegation:
    def test_role_manager_property(self, rbac):
        from core.auth.role_manager import RoleManager
        assert isinstance(rbac.role_manager, RoleManager)

    def test_role_manager_direct_access(self, rbac):
        rbac.role_manager.assign("direct", "admin")
        from core.auth.permissions import Role
        assert rbac.get_identity_role("direct") == Role.ADMIN

    def test_all_endpoints_mapped(self, rbac_with_assignments):
        """Verify all mapped endpoints work for an admin."""
        endpoints = [
            "control_state", "control_audit",
            "control_strategy_enable", "control_strategy_disable",
            "control_asset_enable", "control_asset_disable",
            "control_kill", "control_capital",
            "control_risk_limit", "control_ai_model",
            "control_feature_flag",
        ]
        for ep in endpoints:
            allowed, reason = rbac_with_assignments.check_endpoint("alice", ep)
            assert allowed, f"Admin denied for endpoint {ep}: {reason}"
