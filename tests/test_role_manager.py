"""Tests for core/auth/role_manager.py - RBAC RoleManager.

Covers:
- RoleManager init with default Role.OBSERVER
- assign() with Role objects and strings
- revoke() and fallback to default
- get_role() for assigned and unknown identities
- check() - passes and raises PermissionDenied
- has_permission() boolean checks
- list_assignments() sorted output
- load_from_config() with valid/invalid roles
- Thread safety with concurrent access
- Edge cases: empty identity, case insensitivity
"""

from __future__ import annotations

import threading

import pytest

from core.auth.permissions import Permission, PermissionDenied, Role
from core.auth.role_manager import RoleManager


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def rbac() -> RoleManager:
    """RoleManager with default OBSERVER role."""
    return RoleManager()


@pytest.fixture
def rbac_with_assignments(rbac: RoleManager) -> RoleManager:
    """RoleManager with pre-assigned roles."""
    rbac.assign("alice", Role.ADMIN)
    rbac.assign("bob", Role.OPERATOR)
    rbac.assign("charlie", "viewer")
    return rbac


# ── Initialization Tests ──────────────────────────────────────────────────────


class TestInit:
    def test_default_role_is_observer(self, rbac: RoleManager):
        assert rbac._default_role == Role.OBSERVER

    def test_custom_default_role(self):
        rbac = RoleManager(default_role=Role.VIEWER)
        assert rbac._default_role == Role.VIEWER

    def test_custom_default_role_string(self):
        rbac = RoleManager(default_role="admin")
        assert rbac._default_role == Role.ADMIN

    def test_empty_roles_dict(self, rbac: RoleManager):
        assert rbac._roles == {}

    def test_has_lock(self, rbac: RoleManager):
        assert hasattr(rbac, "_lock")


# ── assign() Tests ────────────────────────────────────────────────────────────


class TestAssign:
    def test_assign_with_role_enum(self, rbac: RoleManager):
        rbac.assign("alice", Role.ADMIN)
        assert rbac.get_role("alice") == Role.ADMIN

    def test_assign_with_string(self, rbac: RoleManager):
        rbac.assign("bob", "operator")
        assert rbac.get_role("bob") == Role.OPERATOR

    def test_assign_case_insensitive_string(self, rbac: RoleManager):
        rbac.assign("carol", "ADMIN")
        assert rbac.get_role("carol") == Role.ADMIN

    def test_assign_overwrites_existing(self, rbac: RoleManager):
        rbac.assign("alice", Role.VIEWER)
        rbac.assign("alice", Role.ADMIN)
        assert rbac.get_role("alice") == Role.ADMIN

    def test_assign_multiple_identities(self, rbac: RoleManager):
        rbac.assign("alice", Role.ADMIN)
        rbac.assign("bob", Role.OPERATOR)
        rbac.assign("charlie", Role.VIEWER)
        assert rbac.get_role("alice") == Role.ADMIN
        assert rbac.get_role("bob") == Role.OPERATOR
        assert rbac.get_role("charlie") == Role.VIEWER

    def test_assign_invalid_role_string_raises(self, rbac: RoleManager):
        with pytest.raises(ValueError):
            rbac.assign("mallory", "superadmin")


# ── revoke() Tests ────────────────────────────────────────────────────────────


class TestRevoke:
    def test_revoke_returns_to_default(self, rbac: RoleManager):
        rbac.assign("alice", Role.ADMIN)
        rbac.revoke("alice")
        assert rbac.get_role("alice") == Role.OBSERVER  # default

    def test_revoke_nonexistent_does_nothing(self, rbac: RoleManager):
        rbac.revoke("nonexistent")  # Should not raise

    def test_revoke_then_reassign(self, rbac: RoleManager):
        rbac.assign("alice", Role.ADMIN)
        rbac.revoke("alice")
        rbac.assign("alice", Role.OPERATOR)
        assert rbac.get_role("alice") == Role.OPERATOR

    def test_revoke_does_not_affect_others(self, rbac_with_assignments: RoleManager):
        rbac_with_assignments.revoke("alice")
        assert rbac_with_assignments.get_role("bob") == Role.OPERATOR


# ── get_role() Tests ──────────────────────────────────────────────────────────


class TestGetRole:
    def test_known_identity(self, rbac_with_assignments: RoleManager):
        assert rbac_with_assignments.get_role("alice") == Role.ADMIN

    def test_unknown_identity_returns_default(self, rbac: RoleManager):
        assert rbac.get_role("unknown") == Role.OBSERVER

    def test_unknown_identity_with_custom_default(self):
        rbac = RoleManager(default_role=Role.VIEWER)
        assert rbac.get_role("unknown") == Role.VIEWER

    def test_case_sensitive_identity(self, rbac_with_assignments: RoleManager):
        # Identity lookup should be exact match
        assert rbac_with_assignments.get_role("Alice") == Role.OBSERVER  # not 'alice'


# ── check() Tests ─────────────────────────────────────────────────────────────


class TestCheck:
    def test_admin_has_all_permissions(self, rbac_with_assignments: RoleManager):
        for perm in Permission:
            rbac_with_assignments.check("alice", perm)  # Should not raise

    def test_operator_permitted(self, rbac_with_assignments: RoleManager):
        rbac_with_assignments.check("bob", Permission.VIEW_STATE)  # Should not raise
        rbac_with_assignments.check("bob", Permission.HALT_TRADING)  # Should not raise

    def test_operator_denied_for_risk(self, rbac_with_assignments: RoleManager):
        with pytest.raises(PermissionDenied):
            rbac_with_assignments.check("bob", Permission.MODIFY_RISK_LIMITS)

    def test_viewer_denied_for_halt(self, rbac_with_assignments: RoleManager):
        with pytest.raises(PermissionDenied):
            rbac_with_assignments.check("charlie", Permission.HALT_TRADING)

    def test_unknown_identity_denied(self, rbac: RoleManager):
        with pytest.raises(PermissionDenied):
            rbac.check("unknown", Permission.HALT_TRADING)

    def test_string_permission(self, rbac_with_assignments: RoleManager):
        rbac_with_assignments.check("alice", "view_state")  # Should not raise

    def test_parent_exception_type(self, rbac_with_assignments: RoleManager):
        with pytest.raises(PermissionDenied):
            rbac_with_assignments.check("charlie", Permission.HALT_TRADING)

    def test_error_message_contains_identity(self, rbac: RoleManager):
        with pytest.raises(PermissionDenied, match="unknown"):
            rbac.check("unknown", Permission.HALT_TRADING)


# ── has_permission() Tests ────────────────────────────────────────────────────


class TestHasPermission:
    def test_admin_has_all(self, rbac_with_assignments: RoleManager):
        for perm in Permission:
            assert rbac_with_assignments.has_permission("alice", perm)

    def test_observer_has_view_only(self, rbac: RoleManager):
        assert rbac.has_permission("unknown", Permission.VIEW_STATE) is True
        assert rbac.has_permission("unknown", Permission.VIEW_LOGS) is True
        assert rbac.has_permission("unknown", Permission.HALT_TRADING) is False

    def test_viewer_denied_for_code(self, rbac_with_assignments: RoleManager):
        assert rbac_with_assignments.has_permission("charlie", Permission.MODIFY_CODE) is False

    def test_unknown_role_default(self, rbac: RoleManager):
        assert rbac.has_permission("nobody", Permission.VIEW_STATE) is True
        assert rbac.has_permission("nobody", Permission.HALT_TRADING) is False

    def test_string_permission(self, rbac_with_assignments: RoleManager):
        assert rbac_with_assignments.has_permission("alice", "halt_trading") is True


# ── list_assignments() Tests ──────────────────────────────────────────────────


class TestListAssignments:
    def test_empty_when_no_assignments(self, rbac: RoleManager):
        assert rbac.list_assignments() == {}

    def test_returns_sorted(self, rbac_with_assignments: RoleManager):
        assignments = rbac_with_assignments.list_assignments()
        # Should be sorted by identity name
        keys = list(assignments.keys())
        assert keys == sorted(keys)

    def test_includes_all_assignments(self, rbac_with_assignments: RoleManager):
        assignments = rbac_with_assignments.list_assignments()
        assert assignments["alice"] == "admin"
        assert assignments["bob"] == "operator"
        assert assignments["charlie"] == "viewer"

    def test_excludes_revoked(self, rbac_with_assignments: RoleManager):
        rbac_with_assignments.revoke("bob")
        assert "bob" not in rbac_with_assignments.list_assignments()

    def test_does_not_include_default_role(self, rbac: RoleManager):
        # Unknown identities are not in list_assignments
        assert rbac.list_assignments() == {}


# ── load_from_config() Tests ──────────────────────────────────────────────────


class TestLoadFromConfig:
    def test_load_valid_roles(self, rbac: RoleManager):
        config = {
            "admin_roles": {
                "alice": "admin",
                "bob": "operator",
            }
        }
        rbac.load_from_config(config)
        assert rbac.get_role("alice") == Role.ADMIN
        assert rbac.get_role("bob") == Role.OPERATOR

    def test_load_with_default_role(self, rbac: RoleManager):
        config = {
            "admin_roles": {},
            "admin_default_role": "viewer",
        }
        rbac.load_from_config(config)
        assert rbac._default_role == Role.VIEWER

    def test_invalid_role_skipped(self, rbac: RoleManager):
        config = {
            "admin_roles": {
                "alice": "superadmin",  # invalid
                "bob": "operator",  # valid
            }
        }
        rbac.load_from_config(config)
        # alice should not be assigned (invalid role)
        assert rbac.get_role("alice") == Role.OBSERVER  # default
        assert rbac.get_role("bob") == Role.OPERATOR

    def test_invalid_default_role_keeps_current(self, rbac: RoleManager):
        config = {
            "admin_default_role": "superadmin",  # invalid
        }
        rbac.load_from_config(config)
        assert rbac._default_role == Role.OBSERVER  # unchanged

    def test_empty_config(self, rbac: RoleManager):
        rbac.load_from_config({})
        assert rbac._default_role == Role.OBSERVER

    def test_missing_admin_roles_key(self, rbac: RoleManager):
        """If 'admin_roles' key is missing, nothing should load."""
        rbac.load_from_config({"other_key": "value"})
        assert rbac.list_assignments() == {}

    def test_overrides_existing_assignments(self, rbac_with_assignments: RoleManager):
        config = {
            "admin_roles": {"alice": "viewer"},  # downgrade
        }
        rbac_with_assignments.load_from_config(config)
        assert rbac_with_assignments.get_role("alice") == Role.VIEWER


# ── Thread Safety Tests ───────────────────────────────────────────────────────


class TestRoleManagerThreadSafety:
    def test_concurrent_assign(self, rbac: RoleManager):
        """Multiple concurrent assignments should be safe."""
        errors = []

        def _assign(i: int):
            try:
                rbac.assign(f"user_{i}", "admin" if i % 2 == 0 else "operator")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=_assign, args=(i,)) for i in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert len(rbac.list_assignments()) == 50

    def test_concurrent_check_and_assign(self, rbac: RoleManager):
        """Concurrent permission checks and assignments should not crash."""
        rbac.assign("alice", Role.ADMIN)
        errors = []
        lock = threading.Lock()

        def _check():
            try:
                for _ in range(20):
                    rbac.check("alice", Permission.VIEW_STATE)
                    rbac.has_permission("alice", Permission.HALT_TRADING)
            except Exception as e:
                with lock:
                    errors.append(e)

        def _assign():
            try:
                for i in range(10):
                    rbac.assign("alice", Role.ADMIN if i % 2 == 0 else Role.OPERATOR)
            except Exception as e:
                with lock:
                    errors.append(e)

        threads = [threading.Thread(target=_check) for _ in range(5)]
        threads += [threading.Thread(target=_assign) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0

    def test_concurrent_revoke_and_assign(self, rbac: RoleManager):
        """Concurrent revoke/assign of same identity should be safe."""
        rbac.assign("alice", Role.ADMIN)
        errors = []

        def _revoke():
            try:
                rbac.revoke("alice")
            except Exception as e:
                errors.append(e)

        def _assign():
            try:
                rbac.assign("alice", Role.ADMIN)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=_revoke) for _ in range(10)]
        threads += [threading.Thread(target=_assign) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        # Final state should be valid (either assigned or default)
        assert rbac.get_role("alice") in (Role.ADMIN, Role.ADMIN, Role.OBSERVER)
