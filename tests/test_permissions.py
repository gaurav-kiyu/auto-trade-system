"""Tests for core/auth/permissions.py - RBAC Permission Matrix.

Covers:
- Role enum values and string conversion
- Permission enum values
- Permission matrix: each role has correct permissions
- role_has_permission() with Role objects and strings
- get_role_permissions()
- PermissionDenied exception
- Edge cases: unknown roles, unknown permissions, case insensitivity
"""

from __future__ import annotations

import pytest
from core.auth.permissions import (
    Permission,
    PermissionDenied,
    Role,
    get_role_permissions,
    role_has_permission,
)

# ── Role Enum Tests ──────────────────────────────────────────────────────────


class TestRole:
    def test_values(self):
        assert Role.ADMIN.value == "admin"
        assert Role.OPERATOR.value == "operator"
        assert Role.VIEWER.value == "viewer"
        assert Role.OBSERVER.value == "observer"
        assert Role.DEVELOPER.value == "developer"

    def test_all_roles_unique(self):
        values = [r.value for r in Role]
        assert len(values) == len(set(values))

    def test_lowercase(self):
        for r in Role:
            assert r.value == r.value.lower()

    def test_from_string(self):
        assert Role("admin") == Role.ADMIN
        assert Role("operator") == Role.OPERATOR
        assert Role("viewer") == Role.VIEWER

    def test_invalid_role_raises(self):
        with pytest.raises(ValueError):
            Role("superadmin")


# ── Permission Enum Tests ────────────────────────────────────────────────────


class TestPermission:
    def test_values(self):
        assert Permission.VIEW_STATE.value == "view_state"
        assert Permission.HALT_TRADING.value == "halt_trading"
        assert Permission.MODIFY_RISK_LIMITS.value == "modify_risk_limits"
        assert Permission.TOGGLE_STRATEGIES.value == "toggle_strategies"
        assert Permission.DEPLOY_MODELS.value == "deploy_models"
        assert Permission.MODIFY_CODE.value == "modify_code"
        assert Permission.VIEW_LOGS.value == "view_logs"
        assert Permission.ADD_BROKERS.value == "add_brokers"
        assert Permission.MODIFY_CONFIG.value == "modify_config"

    def test_all_permissions_unique(self):
        values = [p.value for p in Permission]
        assert len(values) == len(set(values))


# ── Permission Matrix Tests ──────────────────────────────────────────────────


class TestPermissionMatrix:
    """Verify the permission matrix matches the documented RBAC policy."""

    # ADMIN has ALL permissions
    def test_admin_has_all_permissions(self):
        for perm in Permission:
            assert role_has_permission(Role.ADMIN, perm), f"ADMIN lacks {perm}"

    # OPERATOR permissions
    def test_operator_can_view_state(self):
        assert role_has_permission(Role.OPERATOR, Permission.VIEW_STATE)

    def test_operator_can_halt_trading(self):
        assert role_has_permission(Role.OPERATOR, Permission.HALT_TRADING)

    def test_operator_can_toggle_strategies(self):
        assert role_has_permission(Role.OPERATOR, Permission.TOGGLE_STRATEGIES)

    def test_operator_can_view_logs(self):
        assert role_has_permission(Role.OPERATOR, Permission.VIEW_LOGS)

    def test_operator_cannot_modify_risk(self):
        assert not role_has_permission(Role.OPERATOR, Permission.MODIFY_RISK_LIMITS)

    def test_operator_cannot_deploy_models(self):
        assert not role_has_permission(Role.OPERATOR, Permission.DEPLOY_MODELS)

    def test_operator_cannot_modify_code(self):
        assert not role_has_permission(Role.OPERATOR, Permission.MODIFY_CODE)

    def test_operator_cannot_add_brokers(self):
        assert not role_has_permission(Role.OPERATOR, Permission.ADD_BROKERS)

    def test_operator_cannot_modify_config(self):
        assert not role_has_permission(Role.OPERATOR, Permission.MODIFY_CONFIG)

    # VIEWER permissions
    def test_viewer_can_view_state(self):
        assert role_has_permission(Role.VIEWER, Permission.VIEW_STATE)

    def test_viewer_can_view_logs(self):
        assert role_has_permission(Role.VIEWER, Permission.VIEW_LOGS)

    def test_viewer_cannot_halt_trading(self):
        assert not role_has_permission(Role.VIEWER, Permission.HALT_TRADING)

    def test_viewer_cannot_toggle_strategies(self):
        assert not role_has_permission(Role.VIEWER, Permission.TOGGLE_STRATEGIES)

    def test_viewer_cannot_modify_code(self):
        assert not role_has_permission(Role.VIEWER, Permission.MODIFY_CODE)

    # OBSERVER permissions (same as VIEWER currently)
    def test_observer_can_view_state(self):
        assert role_has_permission(Role.OBSERVER, Permission.VIEW_STATE)

    def test_observer_can_view_logs(self):
        assert role_has_permission(Role.OBSERVER, Permission.VIEW_LOGS)

    def test_observer_cannot_halt_trading(self):
        assert not role_has_permission(Role.OBSERVER, Permission.HALT_TRADING)

    def test_observer_cannot_modify_risk(self):
        assert not role_has_permission(Role.OBSERVER, Permission.MODIFY_RISK_LIMITS)

    # DEVELOPER permissions
    def test_developer_can_view_state(self):
        assert role_has_permission(Role.DEVELOPER, Permission.VIEW_STATE)

    def test_developer_can_toggle_strategies(self):
        assert role_has_permission(Role.DEVELOPER, Permission.TOGGLE_STRATEGIES)

    def test_developer_can_deploy_models(self):
        assert role_has_permission(Role.DEVELOPER, Permission.DEPLOY_MODELS)

    def test_developer_can_modify_code(self):
        assert role_has_permission(Role.DEVELOPER, Permission.MODIFY_CODE)

    def test_developer_can_modify_config(self):
        assert role_has_permission(Role.DEVELOPER, Permission.MODIFY_CONFIG)

    def test_developer_cannot_halt_trading(self):
        assert not role_has_permission(Role.DEVELOPER, Permission.HALT_TRADING)

    def test_developer_cannot_add_brokers(self):
        assert not role_has_permission(Role.DEVELOPER, Permission.ADD_BROKERS)

    def test_developer_cannot_modify_risk(self):
        assert not role_has_permission(Role.DEVELOPER, Permission.MODIFY_RISK_LIMITS)


# ── role_has_permission Edge Cases ───────────────────────────────────────────


class TestRoleHasPermissionEdgeCases:
    def test_unknown_role_returns_false(self):
        assert role_has_permission("superadmin", Permission.VIEW_STATE) is False

    def test_unknown_permission_returns_false(self):
        assert role_has_permission(Role.ADMIN, "super_permission") is False

    def test_string_role_case_insensitive(self):
        assert role_has_permission("ADMIN", Permission.VIEW_STATE) is True
        assert role_has_permission("Operator", Permission.HALT_TRADING) is True

    def test_string_permission_case_insensitive(self):
        assert role_has_permission(Role.ADMIN, "VIEW_STATE") is True
        assert role_has_permission(Role.ADMIN, "Halt_Trading") is True

    def test_empty_string_role_returns_false(self):
        assert role_has_permission("", Permission.VIEW_STATE) is False

    def test_none_role_returns_false(self):
        assert role_has_permission(None, Permission.VIEW_STATE) is False  # type: ignore[arg-type]

    def test_none_permission_returns_false(self):
        assert role_has_permission(Role.VIEWER, None) is False  # type: ignore[arg-type]


# ── get_role_permissions Tests ───────────────────────────────────────────────


class TestGetRolePermissions:
    def test_admin_has_9_permissions(self):
        perms = get_role_permissions(Role.ADMIN)
        assert len(perms) == 9  # All permissions

    def test_operator_has_4_permissions(self):
        perms = get_role_permissions(Role.OPERATOR)
        assert len(perms) == 4
        assert Permission.VIEW_STATE in perms
        assert Permission.HALT_TRADING in perms
        assert Permission.TOGGLE_STRATEGIES in perms
        assert Permission.VIEW_LOGS in perms

    def test_viewer_has_2_permissions(self):
        perms = get_role_permissions(Role.VIEWER)
        assert len(perms) == 2
        assert Permission.VIEW_STATE in perms
        assert Permission.VIEW_LOGS in perms

    def test_observer_has_2_permissions(self):
        perms = get_role_permissions(Role.OBSERVER)
        assert len(perms) == 2
        assert Permission.VIEW_STATE in perms
        assert Permission.VIEW_LOGS in perms

    def test_developer_has_6_permissions(self):
        perms = get_role_permissions(Role.DEVELOPER)
        assert len(perms) == 6
        assert Permission.VIEW_STATE in perms
        assert Permission.TOGGLE_STRATEGIES in perms
        assert Permission.DEPLOY_MODELS in perms
        assert Permission.MODIFY_CODE in perms
        assert Permission.VIEW_LOGS in perms
        assert Permission.MODIFY_CONFIG in perms

    def test_string_role(self):
        perms = get_role_permissions("admin")
        assert len(perms) == 9

    def test_unknown_role_returns_empty(self):
        perms = get_role_permissions("superadmin")
        assert perms == set()

    def test_returns_copy(self):
        perms1 = get_role_permissions(Role.ADMIN)
        perms2 = get_role_permissions(Role.ADMIN)
        assert perms1 is not perms2  # Should be different objects
        assert perms1 == perms2

    def test_modifying_returned_set_does_not_affect_matrix(self):
        perms = get_role_permissions(Role.ADMIN)
        perms.clear()
        # Original matrix should be unchanged
        assert len(get_role_permissions(Role.ADMIN)) == 9


# ── PermissionDenied Exception Tests ─────────────────────────────────────────


class TestPermissionDenied:
    def test_is_exception(self):
        assert issubclass(PermissionDenied, Exception)

    def test_raise_with_message(self):
        with pytest.raises(PermissionDenied, match="access denied"):
            raise PermissionDenied("access denied")
