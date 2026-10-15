"""Tests for OPB v2.61 Administrative User Activation, Eligibility, and Quota Remediation.

Investigation ID: OPB-V261-ADMIN-ACTIVATION-EMAIL-QUOTA-001
Governance: OPB-FINAL-PHASE-GOVERNANCE-001
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from core.auth.dependencies import AuthDependencies
from core.auth.handler import AuthHandler
from core.auth.handler.password import hash_password
from core.auth.routes import _register_rate_limiter, create_auth_router
from core.auth.user_signal_permissions import UserPermissionManager
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def isolated_env(tmp_path):
    """Create isolated auth DB and permission store paths for testing."""
    auth_db_path = str(tmp_path / "test_auth.db")
    perm_store_path = tmp_path / "test_user_permissions.json"

    # Reset and configure singleton with isolated store
    UserPermissionManager.reset_instance_for_testing()
    perm_mgr = UserPermissionManager.get_instance(store_path=perm_store_path)

    # Auth handler
    auth_handler = AuthHandler(db_path=auth_db_path, token_ttl=3600)

    # Set known strong admin password and clear must_change_password
    conn = auth_handler._get_conn()
    pw_hash = hash_password("AdminSecure99X!abc")
    conn.execute(
        "UPDATE users SET password_hash = ?, must_change_password = 0, disabled = 0 WHERE username = 'admin'",
        (pw_hash,),
    )
    conn.commit()

    # Authenticate admin and obtain token
    admin_user = auth_handler.authenticate("admin", "AdminSecure99X!abc", "127.0.0.1")
    assert admin_user is not None
    token = auth_handler.create_session(admin_user, "127.0.0.1", "testclient")

    # App and TestClient
    app = FastAPI()
    auth_deps = AuthDependencies(auth_handler)
    router = create_auth_router(auth_handler, auth_deps)
    app.include_router(router)
    client = TestClient(app)

    # Attach admin session to client
    client.cookies.set("opb_session", token.token)
    client.headers["Authorization"] = f"Bearer {token.token}"

    yield {
        "auth_handler": auth_handler,
        "perm_mgr": perm_mgr,
        "client": client,
        "app": app,
        "tmp_path": tmp_path,
        "admin_token": token.token,
    }

    # Teardown
    UserPermissionManager.reset_instance_for_testing()


def test_self_registration_creates_inactive_user(isolated_env):
    """Phase 1: Self-registration must default is_active=False and signals_enabled=False."""
    perm_mgr = isolated_env["perm_mgr"]

    _register_rate_limiter.reset("register:testclient")
    _register_rate_limiter.reset("register:127.0.0.1")

    # Use client without admin cookies for registration
    reg_client = TestClient(isolated_env["app"])
    resp = reg_client.post(
        "/api/auth/register",
        json={
            "username": "new_trader",
            "password": "TraderSecret#99X!",
            "email": "new_trader@example.com",
            "display_name": "New Trader",
        },
    )
    assert resp.status_code == 200, f"Registration failed: {resp.text}"
    assert resp.json()["success"] is True

    perm = perm_mgr.get_user_permissions("new_trader")
    assert perm is not None
    assert perm.is_active is False
    assert perm.signals_enabled is False
    assert perm.email == "new_trader@example.com"


def test_inactive_user_excluded_from_eligible_recipients(isolated_env):
    """Phase 4: Inactive users MUST be excluded from signal dispatch even if signals_enabled=True."""
    perm_mgr = isolated_env["perm_mgr"]

    # Create a user with signals_enabled=True BUT is_active=False
    perm_mgr.update_user_permissions(
        "inactive_user",
        {
            "display_name": "Inactive User",
            "role": "viewer",
            "is_active": False,
            "signals_enabled": True,  # Misleading state
            "allowed_categories": ["LARGE_CAP_EQUITY"],
            "min_signal_tier": "STRONG_ONLY",
            "email": "inactive@example.com",
            "email_enabled": True,
        },
        admin_username="admin",
    )

    eligible = perm_mgr.get_eligible_recipients(category="LARGE_CAP_EQUITY", tier="STRONG")
    eligible_usernames = [u.username for u in eligible]
    assert "inactive_user" not in eligible_usernames


def test_explicit_admin_activation_and_deactivation(isolated_env):
    """Phase 2 & 3: Admin explicit activation sets is_active=True and enables delivery."""
    perm_mgr = isolated_env["perm_mgr"]

    perm_mgr.update_user_permissions(
        "pending_user",
        {
            "display_name": "Pending User",
            "role": "viewer",
            "is_active": False,
            "signals_enabled": False,
            "allowed_categories": ["LARGE_CAP_EQUITY"],
            "min_signal_tier": "STRONG_ONLY",
            "email": "pending@example.com",
            "email_enabled": True,
        },
        admin_username="admin",
    )

    # 1. Activate
    ok, msg, updated = perm_mgr.activate_user("pending_user", admin_username="admin")
    assert ok is True
    assert updated["is_active"] is True
    assert updated["signals_enabled"] is True

    # Now eligible!
    eligible = perm_mgr.get_eligible_recipients(category="LARGE_CAP_EQUITY", tier="STRONG")
    assert "pending_user" in [u.username for u in eligible]

    # 2. Deactivate
    ok_deact, msg_deact, updated_deact = perm_mgr.deactivate_user("pending_user", admin_username="admin")
    assert ok_deact is True
    assert updated_deact["is_active"] is False
    assert updated_deact["signals_enabled"] is False

    # Excluded again!
    eligible_after = perm_mgr.get_eligible_recipients(category="LARGE_CAP_EQUITY", tier="STRONG")
    assert "pending_user" not in [u.username for u in eligible_after]


def test_preflight_cannot_deactivate_super_admin(isolated_env):
    """Phase 6: Super Admin account cannot be deactivated."""
    perm_mgr = isolated_env["perm_mgr"]
    ok, msg, _ = perm_mgr.deactivate_user("admin", admin_username="admin")
    assert ok is False
    assert "Cannot deactivate Super Admin" in msg


def test_user_eligibility_report_diagnostics(isolated_env):
    """Phase 4: Detailed diagnostic report of effective recipient eligibility."""
    perm_mgr = isolated_env["perm_mgr"]

    perm_mgr.update_user_permissions(
        "diag_user",
        {
            "is_active": False,
            "signals_enabled": False,
            "allowed_categories": ["INDEX_OPTIONS"],
            "min_signal_tier": "STRONG_ONLY",
            "max_signals_daily": 2,
        },
        admin_username="admin",
    )

    # Inactive report
    rep = perm_mgr.get_user_eligibility_report("diag_user", category="LARGE_CAP_EQUITY", tier="MODERATE")
    assert rep["effective_eligible"] is False
    assert "USER_INACTIVE_PENDING_APPROVAL" in rep["rejection_reasons"]
    assert "SIGNALS_DISABLED_BLOCKED" in rep["rejection_reasons"]
    assert "CATEGORY_UNSUBSCRIBED_LARGE_CAP_EQUITY" in rep["rejection_reasons"]
    assert "TIER_BELOW_MINIMUM_STRONG_ONLY" in rep["rejection_reasons"]

    # Activate and check
    perm_mgr.activate_user("diag_user", admin_username="admin")
    perm_mgr.update_user_permissions(
        "diag_user",
        {"allowed_categories": ["LARGE_CAP_EQUITY"], "min_signal_tier": "MODERATE_AND_STRONG"},
        admin_username="admin",
    )

    rep2 = perm_mgr.get_user_eligibility_report("diag_user", category="LARGE_CAP_EQUITY", tier="MODERATE")
    assert rep2["effective_eligible"] is True
    assert len(rep2["rejection_reasons"]) == 0


def test_multi_timeframe_quota_enforcement(isolated_env):
    """Phase 5: Per-user quota boundary enforcement."""
    perm_mgr = isolated_env["perm_mgr"]

    perm_mgr.update_user_permissions(
        "quota_user",
        {
            "is_active": True,
            "signals_enabled": True,
            "allowed_categories": ["LARGE_CAP_EQUITY"],
            "min_signal_tier": "STRONG_ONLY",
            "max_signals_daily": 2,
        },
        admin_username="admin",
    )

    # 1st signal -> OK
    r1 = perm_mgr.get_eligible_recipients("LARGE_CAP_EQUITY", "STRONG")
    assert "quota_user" in [u.username for u in r1]

    # 2nd signal -> OK
    r2 = perm_mgr.get_eligible_recipients("LARGE_CAP_EQUITY", "STRONG")
    assert "quota_user" in [u.username for u in r2]

    # 3rd signal -> EXCEEDED
    r3 = perm_mgr.get_eligible_recipients("LARGE_CAP_EQUITY", "STRONG")
    assert "quota_user" not in [u.username for u in r3]

    # Diagnostic report shows quota exhausted
    rep = perm_mgr.get_user_eligibility_report("quota_user", "LARGE_CAP_EQUITY", "STRONG")
    assert rep["effective_eligible"] is False
    assert any("DAILY_QUOTA_EXHAUSTED" in r for r in rep["rejection_reasons"])


def test_api_activate_deactivate_and_eligibility_endpoints(isolated_env):
    """Phase 2 & 3: FastAPI endpoints for administrative activation and eligibility."""
    client = isolated_env["client"]
    auth_handler = isolated_env["auth_handler"]
    perm_mgr = isolated_env["perm_mgr"]

    # Create target user in auth DB and permissions
    auth_handler.create_user(
        username="target_trader",
        password="TraderSecret#99X!",
        role="viewer",
        display_name="Target Trader",
        created_by="self-register",
        disabled=False,
    )
    perm_mgr.update_user_permissions(
        "target_trader",
        {"is_active": False, "signals_enabled": False, "allowed_categories": ["LARGE_CAP_EQUITY"]},
        admin_username="system-sync",
    )

    # 1. Check eligibility before activation
    elig_resp = client.get("/api/auth/users/target_trader/eligibility?category=LARGE_CAP_EQUITY&tier=STRONG")
    assert elig_resp.status_code == 200
    assert elig_resp.json()["report"]["effective_eligible"] is False
    assert "USER_INACTIVE_PENDING_APPROVAL" in elig_resp.json()["report"]["rejection_reasons"]

    # 2. Activate target user
    act_resp = client.post("/api/auth/users/target_trader/activate")
    assert act_resp.status_code == 200
    assert act_resp.json()["permissions"]["is_active"] is True
    assert act_resp.json()["permissions"]["signals_enabled"] is True

    # 3. Check eligibility after activation
    elig_resp2 = client.get("/api/auth/users/target_trader/eligibility?category=LARGE_CAP_EQUITY&tier=STRONG")
    assert elig_resp2.status_code == 200
    assert elig_resp2.json()["report"]["effective_eligible"] is True

    # 4. Deactivate target user
    deact_resp = client.post("/api/auth/users/target_trader/deactivate")
    assert deact_resp.status_code == 200
    assert deact_resp.json()["permissions"]["is_active"] is False

    # 5. Cannot deactivate admin via API
    admin_deact = client.post("/api/auth/users/admin/deactivate")
    assert admin_deact.status_code == 400
    assert "Cannot deactivate Super Admin" in admin_deact.json()["detail"]


def test_api_update_user_permissions_with_is_active(isolated_env):
    """Phase 3: Saving permissions via /users/{username}/permissions respects is_active."""
    client = isolated_env["client"]
    auth_handler = isolated_env["auth_handler"]
    perm_mgr = isolated_env["perm_mgr"]

    auth_handler.create_user(
        username="perm_user",
        password="TraderSecret#99X!",
        role="viewer",
        created_by="admin",
        disabled=False,
    )
    perm_mgr.update_user_permissions("perm_user", {"is_active": False}, admin_username="admin")

    # Update permissions including is_active=True
    update_resp = client.post(
        "/api/auth/users/perm_user/permissions",
        json={
            "is_active": True,
            "signals_enabled": True,
            "role": "viewer",
            "max_signals_daily": 25,
            "email": "perm@test.com",
            "email_enabled": True,
        },
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["permissions"]["is_active"] is True

    perm = perm_mgr.get_user_permissions("perm_user")
    assert perm.is_active is True
    assert perm.max_signals_daily == 25


def test_global_scanner_daily_alert_limit_governed_invariant():
    """Phase 5: Governed MAX_ALERTS_PER_DAY=100 ceiling invariant test."""
    from core.all_nse_scanner import AllNSEScanner

    # Test that scanner loads MAX_ALERTS_PER_DAY=100 by default from config
    scanner = AllNSEScanner(cfg={"MAX_ALERTS_PER_DAY": 100})
    assert scanner._max_alerts_per_day == 100

    # Test suppression when count reaches max_alerts_per_day
    with patch("core.signals.signal_tracker.SignalTracker.get_instance") as mock_tracker:
        instance = MagicMock()
        mock_tracker.return_value = instance

        # Under limit: 99 / 100 -> allowed
        instance.count_generated_today.return_value = 99
        assert scanner._daily_signal_limit_allows_dispatch() is True

        # At limit: 100 / 100 -> suppressed
        instance.count_generated_today.return_value = 100
        assert scanner._daily_signal_limit_allows_dispatch() is False

        # Over limit: 101 / 100 -> suppressed
        instance.count_generated_today.return_value = 101
        assert scanner._daily_signal_limit_allows_dispatch() is False


def test_admin_users_ui_contract_elements():
    """Phase 2 & 8: Verify admin_users.html UI contract elements."""
    html_path = Path("templates/enterprise/admin_users.html")
    assert html_path.exists()
    content = html_path.read_text(encoding="utf-8")

    # Account approval elements
    assert 'id="permIsActive"' in content
    assert 'data-action="activate-user"' in content
    assert "activateUser(username)" in content
    assert "/api/auth/users/${username}/activate" in content
    assert "colFilterSignalStatus" in content
    assert 'value="pending"' in content
    assert "badge-warning" in content
    assert "PENDING" in content

    # Notification & Email Delivery Audit elements
    assert 'id="notifAuditTableBody"' in content
    assert 'id="userNotifTimelineModal"' in content
    assert 'data-action="notif-timeline"' in content
    assert 'id="btnRefreshNotifAudit"' in content
    assert 'id="notifFilterUser"' in content
    assert 'id="notifFilterChannel"' in content
    assert 'id="notifFilterStatus"' in content
    assert "loadNotificationAuditLog" in content
    assert "openUserNotifTimeline" in content


def test_admin_notification_audit_endpoint(isolated_env):
    """Verify GET /api/auth/admin/notifications/audit endpoint."""
    client = isolated_env["client"]

    mock_audit_records = [
        {
            "id": 1,
            "signal_id": "SIG-TEST-001",
            "username": "trader1",
            "channel": "EMAIL",
            "destination": "trader1@example.com",
            "attempted": 1,
            "status": "SENT",
            "error_message": "250 OK",
            "timestamp": "2026-10-13 10:00:00",
        }
    ]

    with patch("core.signals.signal_tracker.SignalTracker.get_instance") as mock_tracker_cls:
        mock_tracker = MagicMock()
        mock_tracker_cls.return_value = mock_tracker
        mock_tracker.get_delivery_audit.return_value = mock_audit_records
        mock_tracker.get_delivery_audit_count.return_value = 1

        resp = client.get("/api/auth/admin/notifications/audit?username=trader1&channel=EMAIL&status=SENT")
        assert resp.status_code == 200, f"Failed: {resp.text}"
        data = resp.json()
        assert data["success"] is True
        assert data["total"] == 1
        assert len(data["items"]) == 1
        assert data["items"][0]["username"] == "trader1"
        assert data["items"][0]["status"] == "SENT"
        # Admin gets unmasked destination
        assert data["items"][0]["destination"] == "trader1@example.com"

        mock_tracker.get_delivery_audit.assert_called_once_with(
            signal_id=None,
            username="trader1",
            channel="EMAIL",
            status="SENT",
            limit=50,
            offset=0,
        )


def test_admin_user_notification_timeline_endpoint(isolated_env):
    """Verify GET /api/auth/admin/users/{username}/notification-timeline endpoint."""
    client = isolated_env["client"]
    auth_handler = isolated_env["auth_handler"]
    perm_mgr = isolated_env["perm_mgr"]

    # Create user with inactive status
    auth_handler.create_user(
        username="timeline_user",
        password="TraderSecret#99X!",
        role="viewer",
        created_by="admin",
        disabled=False,
    )
    perm_mgr.update_user_permissions(
        "timeline_user",
        {"is_active": False, "signals_enabled": True, "email": "timeline@example.com"},
        admin_username="admin",
    )

    mock_events = [
        {
            "id": 1,
            "signal_id": "SIG-TEST-002",
            "username": "timeline_user",
            "channel": "EMAIL",
            "destination": "timeline@example.com",
            "attempted": 0,
            "status": "SUPPRESSED",
            "error_message": "User inactive / pending admin approval",
            "timestamp": "2026-10-13 10:15:00",
            "symbol": "RELIANCE",
        }
    ]

    with patch("core.signals.signal_tracker.SignalTracker.get_instance") as mock_tracker_cls:
        mock_tracker = MagicMock()
        mock_tracker_cls.return_value = mock_tracker
        mock_tracker.get_user_notification_timeline.return_value = mock_events

        resp = client.get("/api/auth/admin/users/timeline_user/notification-timeline")
        assert resp.status_code == 200, f"Failed: {resp.text}"
        data = resp.json()
        assert data["success"] is True
        assert data["username"] == "timeline_user"

        prof = data["user_profile"]
        assert prof["is_active"] is False
        assert prof["effective_eligible"] is False
        assert any("approval" in r.lower() or "active" in r.lower() for r in prof["rejection_reasons"])

        summary = data["summary"]
        assert summary["suppressed_count"] == 1
        assert summary["sent_count"] == 0

        timeline = data["timeline"]
        assert len(timeline) == 1
        assert timeline[0]["symbol"] == "RELIANCE"

    # Non-existent user returns 404
    resp_404 = client.get("/api/auth/admin/users/non_existent_user_999/notification-timeline")
    assert resp_404.status_code == 404


def test_admin_ui_template_activate_and_deactivate_contract():
    """Verify that admin_users.html implements complete, auditable controls."""
    template_path = (
        Path(__file__).resolve().parents[1]
        / "templates"
        / "enterprise"
        / "admin_users.html"
    )
    assert template_path.exists(), "admin_users.html must exist"
    html = template_path.read_text(encoding="utf-8")

    # 1. UI renders PENDING status button when !u.is_active with activate-user
    assert 'data-action="activate-user"' in html
    assert "Pending administrative approval" in html

    # 2. UI renders Approve button when !u.is_active
    assert 'title="Approve & Activate Signals"' in html

    # 3. UI renders symmetric Deactivate button when u.is_active
    assert 'data-action="deactivate-user"' in html
    assert 'title="Deactivate Signal Access"' in html
    assert "u.username !== 'admin'" in html

    # 4. JS functions activateUser & deactivateUser call endpoints
    assert "async function activateUser(username)" in html
    assert "`/api/auth/users/${username}/activate`" in html
    assert "async function deactivateUser(username)" in html
    assert "`/api/auth/users/${username}/deactivate`" in html

    # 5. Delegated event listener on permissionsTableBody routes both actions
    assert "permissionsTableBody" in html
    assert "btn.dataset.action === 'activate-user'" in html
    assert "btn.dataset.action === 'deactivate-user'" in html

    # 6. Edit modal contains account approval toggle switch
    assert 'id="permIsActive"' in html
    assert "Account Approval &amp; Activation" in html

    # 7. CSRF token is attached to non-GET requests in apiFetch
    assert "X-CSRF-Token" in html
    assert "opb_csrf" in html
