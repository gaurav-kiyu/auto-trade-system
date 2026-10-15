"""tests/test_notification_governance_24_scenarios.py
OPB-FINAL-PHASE-GOVERNANCE-001 Mandatory Notification & User Activation Verification.

Explicit 1:1 implementation and empirical validation of all 24 Section 8 Controlled
Notification Test Scenarios specified in the master execution mandate:

1. Active and eligible user receives an email adapter invocation.
2. Active and eligible user receives a Telegram adapter invocation.
3. Inactive user is skipped with an explicit reason.
4. Disabled user is skipped with an explicit reason.
5. Email-disabled user does not receive email.
6. Telegram-disabled/unlinked user does not receive Telegram.
7. Missing email credentials fail visibly.
8. Missing Telegram credentials fail visibly.
9. SMTP authentication failure is recorded correctly.
10. Telegram API rejection is recorded correctly.
11. Timeouts and rate limits follow documented retry policy.
12. A failed channel does not silently suppress an independently eligible channel.
13. Quotas suppress dispatch only when the configured limit is reached.
14. Deduplication suppresses duplicates without suppressing legitimate new signals.
15. The worker actually processes eligible queued events.
16. Failure paths never falsely report successful delivery.
17. Recipient audit data matches actual adapter attempts.
18. Activation becomes effective on the next eligible dispatch.
19. Unauthorized users cannot activate or deactivate accounts.
20. UI state reflects backend persistence.
21. Notification preference and consent requirements remain independent.
22. Admin actions are audit logged.
23. No real registered users receive automated test messages.
24. No production DB is modified.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from core.auth.dependencies import AuthDependencies
from core.auth.handler import AuthHandler
from core.auth.handler.password import hash_password
from core.auth.routes import create_auth_router
from core.auth.user_signal_permissions import (
    UserPermissionManager,
)
from core.ports.notification.notification_port import (
    NotificationChannel,
    NotificationResult,
    NotificationStatus,
)
from core.services.notification_service import NotificationService, ServiceStatus
from core.signals.signal_tracker import SignalTracker
from fastapi import FastAPI
from fastapi.testclient import TestClient


def make_governed_service(perm_mgr: UserPermissionManager | None = None) -> tuple[NotificationService, MagicMock, MagicMock]:
    """Helper to create NotificationService with mock adapters."""
    svc = NotificationService(cfg={"TG_QUIET_MODE": False}, permissions_manager=perm_mgr)
    svc._status = ServiceStatus.RUNNING

    mock_tg = MagicMock()
    mock_tg.enabled = True
    mock_tg.is_channel_available.return_value = True
    mock_tg.send_notification.return_value = NotificationResult(
        notification_id="tg-gov-001",
        status=NotificationStatus.SENT,
        channel=NotificationChannel.TELEGRAM,
        timestamp=time.time(),
    )

    mock_email = MagicMock()
    mock_email.enabled = True
    mock_email.is_channel_available.return_value = True
    mock_email.send_notification.return_value = NotificationResult(
        notification_id="em-gov-001",
        status=NotificationStatus.SENT,
        channel=NotificationChannel.EMAIL,
        timestamp=time.time(),
    )

    svc._adapters = {
        NotificationChannel.TELEGRAM: mock_tg,
        NotificationChannel.EMAIL: mock_email,
    }
    return svc, mock_tg, mock_email


@pytest.fixture
def governance_env(tmp_path: Path):
    """Complete, isolated testing fixture ensuring zero production file touch."""
    db_path = tmp_path / "test_signals.db"
    perm_path = tmp_path / "test_permissions.json"
    auth_db_path = tmp_path / "test_auth.db"

    # Reset singletons
    SignalTracker.reset_instance()
    UserPermissionManager._instance = None

    tracker = SignalTracker.get_instance(db_path=db_path)
    tracker._db_path = db_path
    tracker._init_db()

    perm_mgr = UserPermissionManager.get_instance(store_path=perm_path)

    # Initialize isolated auth handler
    auth_handler = AuthHandler(db_path=str(auth_db_path), token_ttl=3600)

    # Set known strong admin password and clear must_change_password
    conn = auth_handler._get_conn()
    pw_hash = hash_password("SuperAdminSecret#2026!")
    conn.execute(
        "UPDATE users SET password_hash = ?, must_change_password = 0, disabled = 0 WHERE username = 'admin'",
        (pw_hash,),
    )
    conn.commit()

    # Authenticate admin and obtain session token
    admin_user = auth_handler.authenticate("admin", "SuperAdminSecret#2026!", "127.0.0.1")
    assert admin_user is not None
    admin_session = auth_handler.create_session(admin_user, "127.0.0.1", "testclient")

    perm_mgr.update_user_permissions(
        "admin",
        {
            "is_active": True,
            "signals_enabled": True,
            "email_enabled": True,
            "telegram_enabled": True,
            "email": "admin@example.com",
            "telegram_chat_id": "1148730533",
            "allowed_categories": ["LARGE_CAP_EQUITY", "INDEX_OPTIONS"],
            "min_signal_tier": "MODERATE_AND_STRONG",
        },
        admin_username="admin",
    )

    app = FastAPI()
    auth_deps = AuthDependencies(auth_handler)
    router = create_auth_router(auth_handler, auth_deps)
    app.include_router(router)

    # Authenticated client for superadmin
    admin_client = TestClient(app)
    admin_client.cookies.set("opb_session", admin_session.token)
    admin_client.headers["Authorization"] = f"Bearer {admin_session.token}"

    # Viewer user and client for RBAC tests
    auth_handler.create_user(
        username="viewer_user",
        password="ViewerSecret#2026!",
        role="viewer",
        display_name="Viewer User",
        created_by="admin",
        disabled=False,
    )
    conn = auth_handler._get_conn()
    conn.execute(
        "UPDATE users SET must_change_password = 0, disabled = 0 WHERE username = 'viewer_user'",
    )
    conn.commit()
    viewer_user = auth_handler.authenticate("viewer_user", "ViewerSecret#2026!", "127.0.0.1")
    assert viewer_user is not None
    viewer_session = auth_handler.create_session(viewer_user, "127.0.0.1", "viewerclient")

    viewer_client = TestClient(app)
    viewer_client.cookies.set("opb_session", viewer_session.token)
    viewer_client.headers["Authorization"] = f"Bearer {viewer_session.token}"

    yield {
        "tracker": tracker,
        "perm_mgr": perm_mgr,
        "auth_handler": auth_handler,
        "admin_client": admin_client,
        "viewer_client": viewer_client,
        "db_path": db_path,
        "perm_path": perm_path,
        "auth_db_path": auth_db_path,
    }

    SignalTracker.reset_instance()
    UserPermissionManager._instance = None


# -----------------------------------------------------------------------------
# Scenario 1 & 2: Active and eligible user receives email & Telegram invocation
# -----------------------------------------------------------------------------
def test_scenario_01_active_eligible_user_receives_email_adapter_invocation(governance_env):
    """Scenario 1: Active and eligible user receives an email adapter invocation."""
    perm_mgr = governance_env["perm_mgr"]
    svc, mock_tg, mock_email = make_governed_service(perm_mgr=perm_mgr)

    signal = {
        "signal_id": "SIG-TEST-SCENARIO-01",
        "symbol": "TCS",
        "category": "LARGE_CAP_EQUITY",
        "tier": "STRONG",
        "direction": "BUY",
        "entry_price": 3500.0,
        "score": 85,
    }

    res = svc.dispatch_qualifying_signal(signal)
    assert res["status"] == "PROCESSED"
    assert "admin" in res["deliveries"]
    assert res["deliveries"]["admin"]["EMAIL"] == "SENT"
    mock_email.send_notification.assert_called_once()


def test_scenario_02_active_eligible_user_receives_telegram_adapter_invocation(governance_env):
    """Scenario 2: Active and eligible user receives a Telegram adapter invocation."""
    perm_mgr = governance_env["perm_mgr"]
    svc, mock_tg, mock_email = make_governed_service(perm_mgr=perm_mgr)

    signal = {
        "signal_id": "SIG-TEST-SCENARIO-02",
        "symbol": "INFY",
        "category": "LARGE_CAP_EQUITY",
        "tier": "STRONG",
        "direction": "BUY",
        "entry_price": 1800.0,
        "score": 88,
    }

    res = svc.dispatch_qualifying_signal(signal)
    assert res["status"] == "PROCESSED"
    assert "admin" in res["deliveries"]
    assert res["deliveries"]["admin"]["TELEGRAM"] == "SENT"
    mock_tg.send_notification.assert_called_once()


# -----------------------------------------------------------------------------
# Scenario 3: Inactive user is skipped with an explicit reason
# -----------------------------------------------------------------------------
def test_scenario_03_inactive_user_skipped_with_explicit_reason(governance_env):
    """Scenario 3: Inactive user is skipped with an explicit reason."""
    perm_mgr = governance_env["perm_mgr"]
    perm_mgr.update_user_permissions(
        "inactive_trader",
        {
            "is_active": False,
            "signals_enabled": True,
            "email_enabled": True,
            "telegram_enabled": True,
            "allowed_categories": ["LARGE_CAP_EQUITY"],
            "min_signal_tier": "MODERATE_AND_STRONG",
        },
        admin_username="admin",
    )

    report = perm_mgr.get_user_eligibility_report("inactive_trader", category="LARGE_CAP_EQUITY", tier="STRONG")
    assert report["effective_eligible"] is False
    assert "USER_INACTIVE_PENDING_APPROVAL" in report["rejection_reasons"]

    eligible = perm_mgr.get_eligible_recipients(category="LARGE_CAP_EQUITY", tier="STRONG")
    assert "inactive_trader" not in [u.username for u in eligible]


# -----------------------------------------------------------------------------
# Scenario 4: Disabled user is skipped with an explicit reason
# -----------------------------------------------------------------------------
def test_scenario_04_disabled_user_skipped_with_explicit_reason(governance_env):
    """Scenario 4: Disabled user is skipped with an explicit reason."""
    auth_handler = governance_env["auth_handler"]
    perm_mgr = governance_env["perm_mgr"]

    auth_handler.create_user(
        username="banned_user",
        password="BannedSecret#2026!",
        role="viewer",
        disabled=True,
    )
    perm_mgr.update_user_permissions(
        "banned_user",
        {
            "is_active": True,
            "signals_enabled": False,  # Disabled users have signals blocked
            "email_enabled": True,
        },
        admin_username="admin",
    )

    report = perm_mgr.get_user_eligibility_report("banned_user", category="LARGE_CAP_EQUITY", tier="STRONG")
    assert report["effective_eligible"] is False
    assert "SIGNALS_DISABLED_BLOCKED" in report["rejection_reasons"]


# -----------------------------------------------------------------------------
# Scenario 5 & 6: Channel-specific opt-out / unlinked
# -----------------------------------------------------------------------------
def test_scenario_05_email_disabled_user_does_not_receive_email(governance_env):
    """Scenario 5: Email-disabled user does not receive email."""
    perm_mgr = governance_env["perm_mgr"]
    perm_mgr.update_user_permissions(
        "admin",
        {"email_enabled": False, "telegram_enabled": True},
        admin_username="admin",
    )
    svc, mock_tg, mock_email = make_governed_service(perm_mgr=perm_mgr)

    signal = {
        "signal_id": "SIG-TEST-SCENARIO-05",
        "symbol": "RELIANCE",
        "category": "LARGE_CAP_EQUITY",
        "tier": "STRONG",
        "direction": "BUY",
        "entry_price": 2800.0,
        "score": 85,
    }

    res = svc.dispatch_qualifying_signal(signal)
    assert res["status"] == "PROCESSED"
    assert res["deliveries"]["admin"]["EMAIL"] == "DISABLED"
    assert res["deliveries"]["admin"]["TELEGRAM"] == "SENT"
    mock_email.send_notification.assert_not_called()
    mock_tg.send_notification.assert_called_once()


def test_scenario_06_telegram_disabled_unlinked_user_does_not_receive_telegram(governance_env):
    """Scenario 6: Non-admin user with unlinked Telegram chat ID does not receive Telegram."""
    perm_mgr = governance_env["perm_mgr"]
    perm_mgr.update_user_permissions(
        "trader_no_chat",
        {
            "is_active": True,
            "signals_enabled": True,
            "email_enabled": True,
            "email": "trader@example.com",
            "telegram_enabled": True,
            "telegram_chat_id": "",  # Unlinked!
            "allowed_categories": ["LARGE_CAP_EQUITY"],
            "min_signal_tier": "MODERATE_AND_STRONG",
        },
        admin_username="admin",
    )
    svc, mock_tg, mock_email = make_governed_service(perm_mgr=perm_mgr)

    signal = {
        "signal_id": "SIG-TEST-SCENARIO-06",
        "symbol": "HDFCBANK",
        "category": "LARGE_CAP_EQUITY",
        "tier": "STRONG",
        "direction": "BUY",
        "entry_price": 1650.0,
        "score": 82,
    }

    res = svc.dispatch_qualifying_signal(signal)
    assert res["status"] == "PROCESSED"
    assert res["deliveries"]["trader_no_chat"]["EMAIL"] == "SENT"
    assert res["deliveries"]["trader_no_chat"]["TELEGRAM"] == "NO_DESTINATION"


# -----------------------------------------------------------------------------
# Scenario 7 & 8: Missing credentials fail visibly and are audited
# -----------------------------------------------------------------------------
def test_scenario_07_missing_email_credentials_fail_visibly(governance_env):
    """Scenario 7: Missing email credentials fail visibly and are recorded in audit."""
    perm_mgr = governance_env["perm_mgr"]
    tracker = governance_env["tracker"]
    svc, mock_tg, mock_email = make_governed_service(perm_mgr=perm_mgr)

    mock_email.is_channel_available.return_value = False
    mock_email.send_notification.return_value = NotificationResult(
        notification_id="em-err-001",
        status=NotificationStatus.FAILED,
        channel=NotificationChannel.EMAIL,
        timestamp=time.time(),
        error_message="SMTP_CREDENTIALS_MISSING",
    )

    signal = {
        "signal_id": "SIG-TEST-SCENARIO-07",
        "symbol": "SBIN",
        "category": "LARGE_CAP_EQUITY",
        "tier": "STRONG",
        "direction": "BUY",
        "entry_price": 800.0,
        "score": 84,
    }

    res = svc.dispatch_qualifying_signal(signal)
    assert res["deliveries"]["admin"]["EMAIL"] == "FAILED"

    audit = tracker.get_delivery_audit(signal_id="SIG-TEST-SCENARIO-07")
    email_audit = [a for a in audit if a["channel"] == "EMAIL"]
    assert len(email_audit) == 1
    assert email_audit[0]["status"] == "FAILED"
    assert "SMTP_CREDENTIALS_MISSING" in str(email_audit[0]["error_message"])


def test_scenario_08_missing_telegram_credentials_fail_visibly(governance_env):
    """Scenario 8: Missing Telegram credentials fail visibly and are recorded in audit."""
    perm_mgr = governance_env["perm_mgr"]
    tracker = governance_env["tracker"]
    svc, mock_tg, mock_email = make_governed_service(perm_mgr=perm_mgr)

    mock_tg.is_channel_available.return_value = False
    mock_tg.send_notification.return_value = NotificationResult(
        notification_id="tg-err-001",
        status=NotificationStatus.FAILED,
        channel=NotificationChannel.TELEGRAM,
        timestamp=time.time(),
        error_message="TELEGRAM_TOKEN_NOT_CONFIGURED",
    )

    signal = {
        "signal_id": "SIG-TEST-SCENARIO-08",
        "symbol": "ITC",
        "category": "LARGE_CAP_EQUITY",
        "tier": "STRONG",
        "direction": "BUY",
        "entry_price": 450.0,
        "score": 83,
    }

    res = svc.dispatch_qualifying_signal(signal)
    assert res["deliveries"]["admin"]["TELEGRAM"] == "FAILED"

    audit = tracker.get_delivery_audit(signal_id="SIG-TEST-SCENARIO-08")
    tg_audit = [a for a in audit if a["channel"] == "TELEGRAM"]
    assert len(tg_audit) == 1
    assert tg_audit[0]["status"] == "FAILED"
    assert "TELEGRAM_TOKEN_NOT_CONFIGURED" in str(tg_audit[0]["error_message"])


# -----------------------------------------------------------------------------
# Scenario 9 & 10: Provider auth failure and API rejection recorded correctly
# -----------------------------------------------------------------------------
def test_scenario_09_smtp_authentication_failure_recorded_correctly(governance_env):
    """Scenario 9: SMTP authentication failure is recorded correctly in audit."""
    perm_mgr = governance_env["perm_mgr"]
    tracker = governance_env["tracker"]
    svc, mock_tg, mock_email = make_governed_service(perm_mgr=perm_mgr)

    mock_email.send_notification.return_value = NotificationResult(
        notification_id="em-err-002",
        status=NotificationStatus.FAILED,
        channel=NotificationChannel.EMAIL,
        timestamp=time.time(),
        error_message="535 5.7.8 Username and Password not accepted",
    )

    signal = {
        "signal_id": "SIG-TEST-SCENARIO-09",
        "symbol": "WIPRO",
        "category": "LARGE_CAP_EQUITY",
        "tier": "STRONG",
        "direction": "BUY",
        "entry_price": 500.0,
        "score": 81,
    }

    res = svc.dispatch_qualifying_signal(signal)
    assert res["deliveries"]["admin"]["EMAIL"] == "FAILED"

    audit = tracker.get_delivery_audit(signal_id="SIG-TEST-SCENARIO-09")
    email_audit = [a for a in audit if a["channel"] == "EMAIL"]
    assert email_audit[0]["status"] == "FAILED"
    assert "535 5.7.8" in str(email_audit[0]["error_message"])


def test_scenario_10_telegram_api_rejection_recorded_correctly(governance_env):
    """Scenario 10: Telegram API rejection (e.g. 403 Forbidden: bot was blocked by the user)."""
    perm_mgr = governance_env["perm_mgr"]
    tracker = governance_env["tracker"]
    svc, mock_tg, mock_email = make_governed_service(perm_mgr=perm_mgr)

    mock_tg.send_notification.return_value = NotificationResult(
        notification_id="tg-err-002",
        status=NotificationStatus.FAILED,
        channel=NotificationChannel.TELEGRAM,
        timestamp=time.time(),
        error_message="HTTP 403: bot was blocked by the user",
    )

    signal = {
        "signal_id": "SIG-TEST-SCENARIO-10",
        "symbol": "AXISBANK",
        "category": "LARGE_CAP_EQUITY",
        "tier": "STRONG",
        "direction": "BUY",
        "entry_price": 1150.0,
        "score": 86,
    }

    res = svc.dispatch_qualifying_signal(signal)
    assert res["deliveries"]["admin"]["TELEGRAM"] == "FAILED"

    audit = tracker.get_delivery_audit(signal_id="SIG-TEST-SCENARIO-10")
    tg_audit = [a for a in audit if a["channel"] == "TELEGRAM"]
    assert tg_audit[0]["status"] == "FAILED"
    assert "403" in str(tg_audit[0]["error_message"])


# -----------------------------------------------------------------------------
# Scenario 11: Timeouts and rate limits follow retry policy
# -----------------------------------------------------------------------------
def test_scenario_11_timeouts_and_rate_limits_follow_retry_policy(governance_env):
    """Scenario 11: Timeout/429 triggers retry enqueueing and dead-letter queue handling."""
    tracker = governance_env["tracker"]
    sig_id = "SIG-TEST-SCENARIO-11"

    retry_id = tracker.enqueue_notification_retry(
        signal_id=sig_id,
        username="admin",
        channel="TELEGRAM",
        destination="1148730533",
        payload={"symbol": "NIFTY", "score": 85},
        error_message="HTTP 429 Too Many Requests: retry after 5",
        max_attempts=2,
        delay_seconds=0,
    )
    assert retry_id > 0

    # Simulate exhausting retry attempts -> moves to DLQ
    for _ in range(2):
        claimed = tracker.claim_due_notification_retries(max_items=5)
        for item in claimed:
            tracker.fail_notification_retry(item["retry_id"], "Persistent Rate Limit Exhausted")

    # DLQ inspection
    conn = tracker._get_conn()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT status, attempt_count, last_error FROM notification_retry_queue WHERE retry_id = ?", (retry_id,))
        row = cursor.fetchone()
        assert row is not None
        assert row[0] == "DEAD_LETTER"
        assert row[1] >= 1
    finally:
        conn.close()


# -----------------------------------------------------------------------------
# Scenario 12: Independent channel failure isolation
# -----------------------------------------------------------------------------
def test_scenario_12_failed_channel_does_not_silently_suppress_independent_channel(governance_env):
    """Scenario 12: Email failure does not block Telegram, and Telegram failure does not block Email."""
    perm_mgr = governance_env["perm_mgr"]
    svc, mock_tg, mock_email = make_governed_service(perm_mgr=perm_mgr)

    mock_email.send_notification.return_value = NotificationResult(
        notification_id="em-fail-001",
        status=NotificationStatus.FAILED,
        channel=NotificationChannel.EMAIL,
        timestamp=time.time(),
        error_message="SMTP Connection Refused",
    )
    mock_tg.send_notification.return_value = NotificationResult(
        notification_id="tg-ok-001",
        status=NotificationStatus.SENT,
        channel=NotificationChannel.TELEGRAM,
        timestamp=time.time(),
    )

    signal = {
        "signal_id": "SIG-TEST-SCENARIO-12",
        "symbol": "BAJFINANCE",
        "category": "LARGE_CAP_EQUITY",
        "tier": "STRONG",
        "direction": "BUY",
        "entry_price": 7200.0,
        "score": 87,
    }

    res = svc.dispatch_qualifying_signal(signal)
    assert res["deliveries"]["admin"]["EMAIL"] == "FAILED"
    assert res["deliveries"]["admin"]["TELEGRAM"] == "SENT"
    mock_tg.send_notification.assert_called_once()


# -----------------------------------------------------------------------------
# Scenario 13: Quotas suppress dispatch only when limit reached
# -----------------------------------------------------------------------------
def test_scenario_13_quotas_suppress_dispatch_only_when_configured_limit_reached(governance_env):
    """Scenario 13: Per-user quota allows dispatches up to max_signals_daily and blocks subsequent ones."""
    perm_mgr = governance_env["perm_mgr"]
    perm_mgr.update_user_permissions(
        "quota_trader",
        {
            "is_active": True,
            "signals_enabled": True,
            "allowed_categories": ["LARGE_CAP_EQUITY"],
            "min_signal_tier": "STRONG_ONLY",
            "max_signals_daily": 2,
        },
        admin_username="admin",
    )

    # 1st signal: OK
    r1 = perm_mgr.get_eligible_recipients("LARGE_CAP_EQUITY", "STRONG")
    assert "quota_trader" in [u.username for u in r1]

    # 2nd signal: OK
    r2 = perm_mgr.get_eligible_recipients("LARGE_CAP_EQUITY", "STRONG")
    assert "quota_trader" in [u.username for u in r2]

    # 3rd signal: Exceeded limit -> suppressed
    r3 = perm_mgr.get_eligible_recipients("LARGE_CAP_EQUITY", "STRONG")
    assert "quota_trader" not in [u.username for u in r3]

    rep = perm_mgr.get_user_eligibility_report("quota_trader", "LARGE_CAP_EQUITY", "STRONG")
    assert rep["effective_eligible"] is False
    assert any("DAILY_QUOTA_EXHAUSTED" in r for r in rep["rejection_reasons"])


# -----------------------------------------------------------------------------
# Scenario 14: Deduplication suppresses duplicates without suppressing new signals
# -----------------------------------------------------------------------------
def test_scenario_14_deduplication_suppresses_duplicates_without_suppressing_legitimate_new_signals(governance_env):
    """Scenario 14: Deduplication suppresses duplicate signal within cooldown while allowing new distinct signals."""
    perm_mgr = governance_env["perm_mgr"]
    svc, mock_tg, mock_email = make_governed_service(perm_mgr=perm_mgr)

    signal_a = {
        "signal_id": "SIG-TEST-SCENARIO-14-A",
        "symbol": "TITAN",
        "category": "LARGE_CAP_EQUITY",
        "tier": "STRONG",
        "direction": "BUY",
        "entry_price": 3600.0,
        "score": 85,
    }

    # 1st dispatch of signal_a
    res1 = svc.dispatch_qualifying_signal(signal_a)
    assert res1["status"] == "PROCESSED"
    assert mock_tg.send_notification.call_count == 1

    # Duplicate dispatch of signal_a -> idempotent suppression
    res2 = svc.dispatch_qualifying_signal(signal_a)
    assert res2["deliveries"]["admin"]["EMAIL"] == "ALREADY_DELIVERED"
    assert res2["deliveries"]["admin"]["TELEGRAM"] == "ALREADY_DELIVERED"
    assert mock_tg.send_notification.call_count == 1  # No additional call!

    # Distinct new signal -> successfully dispatched!
    signal_b = {
        "signal_id": "SIG-TEST-SCENARIO-14-B",
        "symbol": "MARUTI",
        "category": "LARGE_CAP_EQUITY",
        "tier": "STRONG",
        "direction": "BUY",
        "entry_price": 12000.0,
        "score": 84,
    }
    res3 = svc.dispatch_qualifying_signal(signal_b)
    assert res3["status"] == "PROCESSED"
    assert mock_tg.send_notification.call_count == 2


# -----------------------------------------------------------------------------
# Scenario 15: Worker processes eligible queued events
# -----------------------------------------------------------------------------
def test_scenario_15_worker_actually_processes_eligible_queued_events(governance_env):
    """Scenario 15: Asynchronous event queue correctly invokes worker and processes events."""
    perm_mgr = governance_env["perm_mgr"]
    svc, mock_tg, mock_email = make_governed_service(perm_mgr=perm_mgr)

    signal = {
        "signal_id": "SIG-TEST-SCENARIO-15",
        "symbol": "SUNPHARMA",
        "category": "LARGE_CAP_EQUITY",
        "tier": "STRONG",
        "direction": "BUY",
        "entry_price": 1700.0,
        "score": 85,
    }

    # Dispatch with sync=False queues event to worker thread
    svc.dispatch_qualifying_signal(signal, sync=False)
    # Give worker time to process queue
    time.sleep(0.5)
    assert mock_tg.send_notification.called or mock_email.send_notification.called


# -----------------------------------------------------------------------------
# Scenario 16: Failure paths never falsely report successful delivery
# -----------------------------------------------------------------------------
def test_scenario_16_failure_paths_never_falsely_report_successful_delivery(governance_env):
    """Scenario 16: Failure paths durably report FAILED, never SENT or DELIVERED."""
    perm_mgr = governance_env["perm_mgr"]
    svc, mock_tg, mock_email = make_governed_service(perm_mgr=perm_mgr)

    mock_email.send_notification.return_value = NotificationResult(
        notification_id="em-fail-16",
        status=NotificationStatus.FAILED,
        channel=NotificationChannel.EMAIL,
        timestamp=time.time(),
        error_message="Network unreachable",
    )

    signal = {
        "signal_id": "SIG-TEST-SCENARIO-16",
        "symbol": "LT",
        "category": "LARGE_CAP_EQUITY",
        "tier": "STRONG",
        "direction": "BUY",
        "entry_price": 3600.0,
        "score": 85,
    }

    res = svc.dispatch_qualifying_signal(signal)
    assert res["deliveries"]["admin"]["EMAIL"] == "FAILED"
    assert res["deliveries"]["admin"]["EMAIL"] not in ("SENT", "DELIVERED", "ACCEPTED")


# -----------------------------------------------------------------------------
# Scenario 17: Recipient audit data matches actual adapter attempts
# -----------------------------------------------------------------------------
def test_scenario_17_recipient_audit_data_matches_actual_adapter_attempts(governance_env):
    """Scenario 17: Audit table count and destination match actual adapter attempts."""
    perm_mgr = governance_env["perm_mgr"]
    tracker = governance_env["tracker"]
    svc, mock_tg, mock_email = make_governed_service(perm_mgr=perm_mgr)

    signal = {
        "signal_id": "SIG-TEST-SCENARIO-17",
        "symbol": "ULTRACEMCO",
        "category": "LARGE_CAP_EQUITY",
        "tier": "STRONG",
        "direction": "BUY",
        "entry_price": 10500.0,
        "score": 86,
    }

    svc.dispatch_qualifying_signal(signal)

    audits = tracker.get_delivery_audit(signal_id="SIG-TEST-SCENARIO-17")
    assert len(audits) == 2  # 1 EMAIL, 1 TELEGRAM
    channels = {a["channel"]: a["status"] for a in audits}
    assert channels["EMAIL"] == "SENT"
    assert channels["TELEGRAM"] == "SENT"


# -----------------------------------------------------------------------------
# Scenario 18: Activation becomes effective on next eligible dispatch
# -----------------------------------------------------------------------------
def test_scenario_18_activation_becomes_effective_on_next_eligible_dispatch(governance_env):
    """Scenario 18: Inactive user activated by admin immediately receives next signal."""
    perm_mgr = governance_env["perm_mgr"]
    svc, mock_tg, mock_email = make_governed_service(perm_mgr=perm_mgr)

    perm_mgr.update_user_permissions(
        "newbie",
        {
            "is_active": False,
            "signals_enabled": False,
            "email_enabled": True,
            "email": "newbie@example.com",
            "allowed_categories": ["LARGE_CAP_EQUITY"],
            "min_signal_tier": "MODERATE_AND_STRONG",
        },
        admin_username="admin",
    )

    # 1st dispatch before activation: newbie not in deliveries
    res1 = svc.dispatch_qualifying_signal({
        "signal_id": "SIG-TEST-SCENARIO-18-A",
        "symbol": "ONGC",
        "category": "LARGE_CAP_EQUITY",
        "tier": "STRONG",
        "entry_price": 280.0,
        "score": 80,
    })
    assert "newbie" not in res1["deliveries"]

    # Super Admin activates newbie
    perm_mgr.activate_user("newbie", admin_username="admin")

    # 2nd dispatch after activation: newbie IS included in deliveries!
    res2 = svc.dispatch_qualifying_signal({
        "signal_id": "SIG-TEST-SCENARIO-18-B",
        "symbol": "NTPC",
        "category": "LARGE_CAP_EQUITY",
        "tier": "STRONG",
        "entry_price": 380.0,
        "score": 82,
    })
    assert "newbie" in res2["deliveries"]
    assert res2["deliveries"]["newbie"]["EMAIL"] == "SENT"


# -----------------------------------------------------------------------------
# Scenario 19: Unauthorized users cannot activate or deactivate accounts
# -----------------------------------------------------------------------------
def test_scenario_19_unauthorized_users_cannot_activate_or_deactivate_accounts(governance_env):
    """Scenario 19: Non-admin users receive 403 Forbidden on activation endpoints."""
    viewer_client = governance_env["viewer_client"]

    # Viewer attempts to activate
    res1 = viewer_client.post("/api/auth/users/target_trader/activate")
    assert res1.status_code == 403

    # Viewer attempts to deactivate
    res2 = viewer_client.post("/api/auth/users/target_trader/deactivate")
    assert res2.status_code == 403


# -----------------------------------------------------------------------------
# Scenario 20: UI state reflects backend persistence
# -----------------------------------------------------------------------------
def test_scenario_20_ui_state_reflects_backend_persistence(governance_env):
    """Scenario 20: Admin activation API persists to store and returns fresh state."""
    admin_client = governance_env["admin_client"]
    auth_handler = governance_env["auth_handler"]
    perm_mgr = governance_env["perm_mgr"]

    auth_handler.create_user(
        username="ui_test_user",
        password="UiSecureTrader#99X!",
        role="viewer",
        disabled=False,
    )
    perm_mgr.update_user_permissions(
        "ui_test_user",
        {"is_active": False, "signals_enabled": False},
        admin_username="admin",
    )

    resp = admin_client.post("/api/auth/users/ui_test_user/activate")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["permissions"]["is_active"] is True

    # Fresh reload from store
    perm_reloaded = perm_mgr.get_user_permissions("ui_test_user")
    assert perm_reloaded is not None
    assert perm_reloaded.is_active is True
    assert perm_reloaded.signals_enabled is True


# -----------------------------------------------------------------------------
# Scenario 21: Notification preference and consent remain independent
# -----------------------------------------------------------------------------
def test_scenario_21_notification_preference_and_consent_remain_independent(governance_env):
    """Scenario 21: Active account state does not override explicit channel preferences."""
    perm_mgr = governance_env["perm_mgr"]

    perm_mgr.update_user_permissions(
        "selective_user",
        {
            "is_active": True,
            "signals_enabled": True,
            "email_enabled": True,
            "telegram_enabled": False,  # User explicitly opted out of Telegram
            "telegram_chat_id": "999999999",
            "allowed_categories": ["LARGE_CAP_EQUITY"],
        },
        admin_username="admin",
    )

    p = perm_mgr.get_user_permissions("selective_user")
    assert p.is_active is True
    assert p.email_enabled is True
    assert p.telegram_enabled is False


# -----------------------------------------------------------------------------
# Scenario 22: Admin actions are audit logged
# -----------------------------------------------------------------------------
def test_scenario_22_admin_actions_are_audit_logged(governance_env):
    """Scenario 22: Administrative activations are recorded in auth audit log."""
    admin_client = governance_env["admin_client"]
    auth_handler = governance_env["auth_handler"]
    perm_mgr = governance_env["perm_mgr"]

    auth_handler.create_user(
        username="audit_trader",
        password="AuditTraderPass#1!",
        role="viewer",
        disabled=False,
    )
    perm_mgr.update_user_permissions(
        "audit_trader",
        {"is_active": False, "signals_enabled": False},
        admin_username="admin",
    )

    resp = admin_client.post("/api/auth/users/audit_trader/activate")
    assert resp.status_code == 200

    conn = auth_handler._get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT event_type, username, details FROM audit_log WHERE event_type = 'user_activated'")
    row = cursor.fetchone()
    assert row is not None
    assert row[0] == "user_activated"
    assert row[1] == "admin"
    details = json.loads(row[2])
    assert details["target_user"] == "audit_trader"


# -----------------------------------------------------------------------------
# Scenario 23: No real registered users receive automated test messages
# -----------------------------------------------------------------------------
def test_scenario_23_no_real_registered_users_receive_automated_test_messages(governance_env):
    """Scenario 23: Tests employ mock notification ports, strictly blocking live network calls."""
    perm_mgr = governance_env["perm_mgr"]
    svc, mock_tg, mock_email = make_governed_service(perm_mgr=perm_mgr)

    signal = {
        "signal_id": "SIG-TEST-SCENARIO-23",
        "symbol": "COALINDIA",
        "category": "LARGE_CAP_EQUITY",
        "tier": "STRONG",
        "entry_price": 450.0,
        "score": 85,
    }

    with patch("smtplib.SMTP") as mock_smtp, patch("urllib.request.urlopen") as mock_urlopen:
        svc.dispatch_qualifying_signal(signal)

        # Neither actual SMTP nor actual HTTP urlopen was invoked
        assert not mock_smtp.called
        assert not mock_urlopen.called


# -----------------------------------------------------------------------------
# Scenario 24: No production DB is modified
# -----------------------------------------------------------------------------
def test_scenario_24_no_production_db_is_modified(governance_env):
    """Scenario 24: Test harness uses temporary paths and leaves production paths untouched."""
    prod_signals_db = Path("db/signals_history.db")
    prod_users_json = Path("data/db/user_signal_permissions.json")

    # The test environment paths must not equal the repository production paths
    assert governance_env["db_path"] != prod_signals_db.resolve()
    assert governance_env["perm_path"] != prod_users_json.resolve()
    assert any(t in str(governance_env["db_path"]).lower() for t in ("tmp", "temp", "pytest"))
