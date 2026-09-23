"""tests/test_super_admin_dual_channel_notifications.py
Empirical test suite for Super Admin Dual-Channel Signal Notifications (Telegram + Email).
Validates all requirements for qualifying signal dispatch, channel independence,
audit trail persistence, idempotency, user permission defaults, and safety invariants.
"""

import os
import sqlite3
import time
from unittest.mock import MagicMock, patch

import pytest

from core.auth.user_signal_permissions import UserPermissionManager, UserSignalPermission
from core.ports.notification.notification_port import (
    Notification,
    NotificationChannel,
    NotificationPriority,
    NotificationResult,
    NotificationStatus,
)
from core.position_service import PositionService
from core.services.notification_service import NotificationService, ServiceStatus
from core.signals.signal_tracker import SignalTracker


@pytest.fixture(autouse=True)
def clean_database(tmp_path):
    """Point SQLite database and permission store to clean temporary files."""
    from pathlib import Path
    db_path = Path(tmp_path) / "test_signals.db"
    SignalTracker.reset_instance()
    tracker = SignalTracker.get_instance(db_path=db_path)
    tracker._db_path = db_path
    tracker._init_db()

    perm_store_path = Path(tmp_path) / "test_users.json"
    UserPermissionManager._instance = None
    perm_mgr = UserPermissionManager.get_instance(store_path=perm_store_path)

    # Ensure admin has valid destinations by default for positive test cases
    perm_mgr.update_user_permissions("admin", {"telegram_chat_id": "1148730533", "email": "admin@example.com"})

    yield {
        "tracker": tracker,
        "perm_mgr": perm_mgr,
        "db_path": db_path,
        "perm_path": perm_store_path,
    }

    SignalTracker.reset_instance()
    UserPermissionManager._instance = None


def make_mock_notification_service():
    """Construct NotificationService with mock adapters."""
    svc = NotificationService(cfg={"TG_QUIET_MODE": False})
    svc._status = ServiceStatus.RUNNING

    # Mock Telegram Adapter
    mock_tg = MagicMock()
    mock_tg.enabled = True
    mock_tg.is_channel_available.return_value = True
    mock_tg.send_notification.return_value = NotificationResult(
        notification_id="tg-001",
        status=NotificationStatus.SENT,
        channel=NotificationChannel.TELEGRAM,
        timestamp=time.time(),
    )

    # Mock Email Adapter
    mock_email = MagicMock()
    mock_email.enabled = True
    mock_email.is_channel_available.return_value = True
    mock_email.send_notification.return_value = NotificationResult(
        notification_id="em-001",
        status=NotificationStatus.SENT,
        channel=NotificationChannel.EMAIL,
        timestamp=time.time(),
    )

    svc._adapters = {
        NotificationChannel.TELEGRAM: mock_tg,
        NotificationChannel.EMAIL: mock_email,
    }
    return svc, mock_tg, mock_email


# ==============================================================================
# 1. TIER QUALIFICATION TESTS
# ==============================================================================

def test_qualifying_tier_strong_dispatches_both_channels(clean_database):
    """STRONG tier signals must dispatch to both Telegram and Email."""
    svc, mock_tg, mock_email = make_mock_notification_service()
    tracker = clean_database["tracker"]

    signal = {
        "signal_id": "SIG-TEST-STRONG-001",
        "symbol": "NIFTY",
        "direction": "CALL",
        "tier": "STRONG",
        "score": 88,
        "entry_price": 24500.0,
        "category": "INDEX_OPTIONS",
    }

    res = svc.dispatch_qualifying_signal(signal)

    assert res["status"] == "PROCESSED"
    assert "admin" in res["deliveries"]
    assert res["deliveries"]["admin"]["TELEGRAM"] == "SENT"
    assert res["deliveries"]["admin"]["EMAIL"] == "SENT"

    mock_tg.send_notification.assert_called_once()
    mock_email.send_notification.assert_called_once()

    # Verify audit persistence
    audit = tracker.get_delivery_audit(signal_id="SIG-TEST-STRONG-001")
    channels = {a["channel"]: a["status"] for a in audit}
    assert channels.get("TELEGRAM") == "SENT"
    assert channels.get("EMAIL") == "SENT"


def test_qualifying_tier_moderate_dispatches_both_channels(clean_database):
    """MODERATE tier signals must dispatch to both Telegram and Email."""
    svc, mock_tg, mock_email = make_mock_notification_service()
    tracker = clean_database["tracker"]

    signal = {
        "signal_id": "SIG-TEST-MODERATE-001",
        "symbol": "BANKNIFTY",
        "direction": "PUT",
        "tier": "MODERATE",
        "score": 74,
        "entry_price": 51200.0,
        "category": "INDEX_OPTIONS",
    }

    res = svc.dispatch_qualifying_signal(signal)

    assert res["status"] == "PROCESSED"
    assert res["deliveries"]["admin"]["TELEGRAM"] == "SENT"
    assert res["deliveries"]["admin"]["EMAIL"] == "SENT"

    mock_tg.send_notification.assert_called_once()
    mock_email.send_notification.assert_called_once()


def test_non_qualifying_tier_weak_skipped(clean_database):
    """WEAK tier signals must NOT be dispatched."""
    svc, mock_tg, mock_email = make_mock_notification_service()
    tracker = clean_database["tracker"]

    signal = {
        "signal_id": "SIG-TEST-WEAK-001",
        "symbol": "NIFTY",
        "direction": "CALL",
        "tier": "WEAK",
        "score": 62,
        "entry_price": 24500.0,
    }

    res = svc.dispatch_qualifying_signal(signal)

    assert res["status"] == "NON_QUALIFYING_TIER"
    mock_tg.send_notification.assert_not_called()
    mock_email.send_notification.assert_not_called()

    audit = tracker.get_delivery_audit(signal_id="SIG-TEST-WEAK-001")
    assert len(audit) == 0


def test_missing_signal_id_rejected():
    """Signals lacking an ID cannot be dispatched."""
    svc, mock_tg, mock_email = make_mock_notification_service()
    signal = {"symbol": "NIFTY", "tier": "STRONG"}
    res = svc.dispatch_qualifying_signal(signal)
    assert res["status"] == "NO_SIGNAL_ID"
    mock_tg.send_notification.assert_not_called()
    mock_email.send_notification.assert_not_called()


# ==============================================================================
# 2. CHANNEL INDEPENDENCE & ISOLATION
# ==============================================================================

def test_telegram_failure_does_not_block_email(clean_database):
    """If Telegram fails or raises an exception, Email must still succeed."""
    svc, mock_tg, mock_email = make_mock_notification_service()
    mock_tg.send_notification.side_effect = Exception("Telegram API Network Timeout")
    tracker = clean_database["tracker"]

    signal = {
        "signal_id": "SIG-FAILOVER-TG-001",
        "symbol": "NIFTY",
        "direction": "CALL",
        "tier": "STRONG",
        "score": 85,
    }

    res = svc.dispatch_qualifying_signal(signal)

    assert res["deliveries"]["admin"]["TELEGRAM"] == "FAILED"
    assert res["deliveries"]["admin"]["EMAIL"] == "SENT"

    mock_email.send_notification.assert_called_once()

    audit = tracker.get_delivery_audit(signal_id="SIG-FAILOVER-TG-001")
    statuses = {a["channel"]: a["status"] for a in audit}
    assert statuses["TELEGRAM"] == "FAILED"
    assert statuses["EMAIL"] == "SENT"


def test_email_failure_does_not_block_telegram(clean_database):
    """If Email fails or raises an exception, Telegram must still succeed."""
    svc, mock_tg, mock_email = make_mock_notification_service()
    mock_email.send_notification.side_effect = Exception("SMTP Connection Refused")
    tracker = clean_database["tracker"]

    signal = {
        "signal_id": "SIG-FAILOVER-EM-001",
        "symbol": "NIFTY",
        "direction": "PUT",
        "tier": "MODERATE",
        "score": 75,
    }

    res = svc.dispatch_qualifying_signal(signal)

    assert res["deliveries"]["admin"]["TELEGRAM"] == "SENT"
    assert res["deliveries"]["admin"]["EMAIL"] == "FAILED"

    mock_tg.send_notification.assert_called_once()

    audit = tracker.get_delivery_audit(signal_id="SIG-FAILOVER-EM-001")
    statuses = {a["channel"]: a["status"] for a in audit}
    assert statuses["TELEGRAM"] == "SENT"
    assert statuses["EMAIL"] == "FAILED"


def test_both_channels_failure_handled_gracefully(clean_database):
    """When both channels fail, system records failures without crashing."""
    svc, mock_tg, mock_email = make_mock_notification_service()
    mock_tg.send_notification.side_effect = Exception("TG Crash")
    mock_email.send_notification.side_effect = Exception("Email Crash")
    tracker = clean_database["tracker"]

    signal = {
        "signal_id": "SIG-BOTH-FAIL-001",
        "symbol": "NIFTY",
        "tier": "STRONG",
        "score": 90,
    }

    res = svc.dispatch_qualifying_signal(signal)

    assert res["deliveries"]["admin"]["TELEGRAM"] == "FAILED"
    assert res["deliveries"]["admin"]["EMAIL"] == "FAILED"

    audit = tracker.get_delivery_audit(signal_id="SIG-BOTH-FAIL-001")
    assert len(audit) == 2
    for entry in audit:
        assert entry["status"] == "FAILED"
        assert entry["error_message"] is not None


# ==============================================================================
# 3. IDEMPOTENCY & DEDUPLICATION
# ==============================================================================

def test_idempotent_dispatch_prevents_duplicate_notifications(clean_database):
    """Subsequent dispatches for the same signal_id must be suppressed."""
    svc, mock_tg, mock_email = make_mock_notification_service()

    signal = {
        "signal_id": "SIG-IDEMPOTENT-001",
        "symbol": "NIFTY",
        "tier": "STRONG",
        "score": 92,
    }

    # First dispatch
    res1 = svc.dispatch_qualifying_signal(signal)
    assert res1["deliveries"]["admin"]["TELEGRAM"] == "SENT"
    assert res1["deliveries"]["admin"]["EMAIL"] == "SENT"
    assert mock_tg.send_notification.call_count == 1
    assert mock_email.send_notification.call_count == 1

    # Second dispatch with identical signal_id
    res2 = svc.dispatch_qualifying_signal(signal)
    assert res2["deliveries"]["admin"]["TELEGRAM"] == "ALREADY_DELIVERED"
    assert res2["deliveries"]["admin"]["EMAIL"] == "ALREADY_DELIVERED"
    # Call counts must NOT increase
    assert mock_tg.send_notification.call_count == 1
    assert mock_email.send_notification.call_count == 1


# ==============================================================================
# 4. USER PERMISSION DEFAULTS & DESTINATION AUDITING
# ==============================================================================

def test_super_admin_default_tier_permission(clean_database):
    """Super Admin admin must default to MODERATE_AND_STRONG."""
    perm_mgr = clean_database["perm_mgr"]
    admin = perm_mgr.get_user_permissions("admin")

    assert admin is not None
    assert admin.min_signal_tier == "MODERATE_AND_STRONG"
    assert admin.telegram_enabled is True
    assert admin.email_enabled is True
    assert admin.role == "admin"


def test_channel_disabled_audits_as_disabled(clean_database):
    """If a channel is disabled on user permissions, audit records DISABLED."""
    svc, mock_tg, mock_email = make_mock_notification_service()
    perm_mgr = clean_database["perm_mgr"]
    tracker = clean_database["tracker"]

    # Disable telegram for admin
    perm_mgr.update_user_permissions("admin", {"telegram_enabled": False})

    signal = {
        "signal_id": "SIG-DISABLED-TG-001",
        "symbol": "NIFTY",
        "tier": "STRONG",
        "score": 85,
    }

    res = svc.dispatch_qualifying_signal(signal)

    assert res["deliveries"]["admin"]["TELEGRAM"] == "DISABLED"
    assert res["deliveries"]["admin"]["EMAIL"] == "SENT"
    mock_tg.send_notification.assert_not_called()
    mock_email.send_notification.assert_called_once()

    audit = tracker.get_delivery_audit(signal_id="SIG-DISABLED-TG-001")
    tg_audit = next(a for a in audit if a["channel"] == "TELEGRAM")
    assert tg_audit["status"] == "DISABLED"
    assert tg_audit["attempted"] == 0


def test_missing_destination_audits_as_no_destination(clean_database):
    """If destination email/chat_id is missing, audit records NO_DESTINATION."""
    svc, mock_tg, mock_email = make_mock_notification_service()
    perm_mgr = clean_database["perm_mgr"]
    tracker = clean_database["tracker"]

    # Remove email for admin
    perm_mgr.update_user_permissions("admin", {"email": ""})

    signal = {
        "signal_id": "SIG-NO-DEST-001",
        "symbol": "NIFTY",
        "tier": "STRONG",
        "score": 85,
    }

    with patch.dict(os.environ, {"OPBUYING_EMAIL_TO": ""}):
        svc._cfg["EMAIL_TO"] = ""
        res = svc.dispatch_qualifying_signal(signal)

    assert res["deliveries"]["admin"]["EMAIL"] == "NO_DESTINATION"
    mock_email.send_notification.assert_not_called()

    audit = tracker.get_delivery_audit(signal_id="SIG-NO-DEST-001")
    em_audit = next(a for a in audit if a["channel"] == "EMAIL")
    assert em_audit["status"] == "NO_DESTINATION"
    assert em_audit["attempted"] == 0


# ==============================================================================
# 5. AUDIT TRAIL PERSISTENCE & PRUNING
# ==============================================================================

def test_delivery_audit_schema_and_query(clean_database):
    """Verify all columns of signal_delivery_audit are correctly stored."""
    tracker = clean_database["tracker"]
    audit_id = tracker.record_delivery_attempt(
        signal_id="SIG-SCHEMA-001",
        username="admin",
        channel="TELEGRAM",
        destination="1148730533",
        attempted=True,
        status="ATTEMPTED",
    )
    assert audit_id > 0

    tracker.update_delivery_status(audit_id, "SENT")

    records = tracker.get_delivery_audit(signal_id="SIG-SCHEMA-001")
    assert len(records) == 1
    rec = records[0]
    assert rec["signal_id"] == "SIG-SCHEMA-001"
    assert rec["username"] == "admin"
    assert rec["channel"] == "TELEGRAM"
    assert rec["destination"] == "1148730533"
    assert rec["attempted"] == 1
    assert rec["status"] == "SENT"
    assert rec["timestamp"] is not None


def test_delivery_audit_pruning(clean_database):
    """Pruning signals older than max_age_days also prunes delivery audit."""
    tracker = clean_database["tracker"]
    archive_dir = clean_database["db_path"].parent / "archives"

    # Insert old record into system_signals and signal_delivery_audit
    old_ts = "2020-01-01 10:00:00"
    with sqlite3.connect(tracker._db_path) as conn:
        conn.execute("""
            INSERT INTO system_signals 
            (signal_id, timestamp, created_date, created_week, created_month, created_year, symbol, category, direction, score, tier, entry_price, stop_loss, target_1, target_2, current_price, status, pnl_pct)
            VALUES ('SIG-OLD-001', ?, '2020-01-01', '2020-W01', '2020-01', '2020', 'NIFTY', 'INDEX_OPTIONS', 'CALL', 80, 'STRONG', 100.0, 95.0, 105.0, 110.0, 100.0, 'CLOSED', 0.0)
        """, (old_ts,))
        conn.execute("""
            INSERT INTO signal_delivery_audit 
            (signal_id, username, channel, destination, attempted, status, timestamp)
            VALUES ('SIG-OLD-001', 'admin', 'TELEGRAM', '123', 1, 'SENT', ?)
        """, (old_ts,))
        conn.commit()

    records_before = tracker.get_delivery_audit(signal_id="SIG-OLD-001")
    assert len(records_before) == 1

    tracker.prune_old_signals(max_age_days=30, archive_dir=archive_dir)

    records_after = tracker.get_delivery_audit(signal_id="SIG-OLD-001")
    assert len(records_after) == 0


# ==============================================================================
# 6. MESSAGE FORMATTING & FINTECH CONTENT
# ==============================================================================

def test_formatted_alert_contains_paper_mode_and_metadata(clean_database):
    """Message content must state PAPER/SIGNAL_ONLY mode and no live execution."""
    svc, mock_tg, mock_email = make_mock_notification_service()

    signal = {
        "signal_id": "SIG-MSG-FINTECH-001",
        "symbol": "NIFTY",
        "direction": "CALL",
        "tier": "STRONG",
        "score": 89,
        "entry_price": 24550.0,
        "stop_loss": 24400.0,
        "target_1": 24800.0,
        "target_2": 25000.0,
        "category": "INDEX_OPTIONS",
        "strategy": "nifty_momentum",
    }

    svc.dispatch_qualifying_signal(signal)

    call_args = mock_tg.send_notification.call_args[0][0]
    msg = call_args.message

    assert "SIG-MSG-FINTECH-001" in msg
    assert "NIFTY" in msg
    assert "CALL" in msg
    assert "STRONG" in msg
    assert "PAPER / SIGNAL_ONLY" in msg
    assert "no live trade executed" in msg.lower()
    assert "24,550.00" in msg or "24550" in msg


# ==============================================================================
# 7. POSITION SERVICE INTEGRATION & CANONICAL THRESHOLD
# ==============================================================================

def test_position_service_canonical_moderate_threshold():
    """PositionService._is_qualified_signal follows canonical 70 threshold."""
    svc = PositionService.__new__(PositionService)

    assert svc._is_qualified_signal({"tier": "STRONG"}) is True
    assert svc._is_qualified_signal({"tier": "MODERATE"}) is True
    assert svc._is_qualified_signal({"tier": "WEAK"}) is False

    # Score fallback
    assert svc._is_qualified_signal({"score": 70.0}) is True
    assert svc._is_qualified_signal({"score": 69.9}) is False
    assert svc._is_qualified_signal({"score": 85.0}) is True


def test_position_service_dispatches_out_of_band(clean_database):
    """PositionService._ensure_signal_persisted triggers notification dispatch."""
    ps = PositionService.__new__(PositionService)
    mock_notif_svc = MagicMock()
    ps._notification_service = mock_notif_svc

    sig = {
        "symbol": "NIFTY",
        "direction": "CALL",
        "score": 82,
        "tier": "STRONG",
        "strike": 25000,
        "strategy": "test_strat",
    }

    sig_id = ps._ensure_signal_persisted(name="NIFTY", sig=sig, order_direction="CALL", price=100.0)

    assert sig_id is not None
    mock_notif_svc.dispatch_qualifying_signal.assert_called_once()
    dispatched_sig = mock_notif_svc.dispatch_qualifying_signal.call_args[0][0]
    assert dispatched_sig["signal_id"] == sig_id
    assert dispatched_sig["symbol"] == "NIFTY"


# ==============================================================================
# 8. LIFECYCLE & STOP RESPONSIVENESS
# ==============================================================================

def test_notification_service_stop_responsiveness():
    """NotificationService.stop() terminates worker threads within timeout."""
    svc = NotificationService()
    svc.start()
    assert svc.is_running is True

    start_time = time.time()
    svc.stop()
    elapsed = time.time() - start_time

    assert svc.is_running is False
    assert elapsed < 3.0


# ==============================================================================
# 9. BOUNDARY AND INVARIANT TESTS
# ==============================================================================

def test_score_qualification_boundaries_edge_cases(clean_database):
    """Test boundary scores without explicit tier string."""
    svc, mock_tg, mock_email = make_mock_notification_service()

    # 69 score (WEAK) -> suppressed
    res_weak = svc.dispatch_qualifying_signal({"signal_id": "SIG-69", "score": 69, "symbol": "NIFTY"})
    assert res_weak["status"] == "NON_QUALIFYING_TIER"

    # 70 score (MODERATE) -> processed
    res_mod = svc.dispatch_qualifying_signal({"signal_id": "SIG-70", "score": 70, "symbol": "NIFTY"})
    assert res_mod["status"] == "PROCESSED"

    # 80 score (STRONG) -> processed
    res_strong = svc.dispatch_qualifying_signal({"signal_id": "SIG-80", "score": 80, "symbol": "NIFTY"})
    assert res_strong["status"] == "PROCESSED"


def test_telegram_adapter_routing_custom_chat_id():
    """Telegram client must route to custom chat_id when provided in signal."""
    from infrastructure.adapters.notifications.telegram_adapter import _TelegramClient
    client = _TelegramClient(bot_token="test_token", default_chat_id="1148730533")
    
    # Direct recipient
    channels = client._resolve_channel({"chat_id": "999888777", "symbol": "NIFTY"})
    assert "999888777" in channels


def test_p0_safety_invariants_preserved():
    """Verify non-negotiable safety constants and configuration remain intact."""
    import json
    from pathlib import Path
    
    cfg_path = Path("json/config.json")
    if cfg_path.exists():
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        assert cfg.get("SL_PCT", 0.88) == 0.88
        assert cfg.get("BASE_CAPITAL", 3000) == 3000
        assert cfg.get("SIGNAL_ONLY", True) is True


def test_non_admin_no_chat_id_records_no_destination(clean_database):
    """A viewer user with no telegram_chat_id must get NO_DESTINATION, not fallback to admin chat ID."""
    perm_mgr = clean_database["perm_mgr"]
    perm_mgr.update_user_permissions("admin", {"telegram_chat_id": "1148730533", "email": "admin@example.com"})
    perm_mgr.update_user_permissions("kiyu", {
        "is_active": True,
        "signals_enabled": True,
        "telegram_enabled": True,
        "telegram_chat_id": "",
        "email_enabled": True,
        "email": "kiyu@example.com",
        "min_signal_tier": "MODERATE_AND_STRONG",
        "allowed_categories": ["INDEX_OPTIONS"],
    })

    svc, mock_tg, mock_email = make_mock_notification_service()
    signal = {
        "signal_id": "SIG-NO-DEST-001",
        "symbol": "FINNIFTY",
        "direction": "CALL",
        "tier": "STRONG",
        "score": 88,
        "price": 25000.0,
        "category": "INDEX_OPTIONS",
    }

    res = svc.dispatch_qualifying_signal(signal)
    deliveries = res["deliveries"]

    assert deliveries["admin"]["TELEGRAM"] == "SENT"
    assert deliveries["kiyu"]["TELEGRAM"] == "NO_DESTINATION"
    assert deliveries["kiyu"]["EMAIL"] == "SENT"

    tracker = clean_database["tracker"]
    audit = tracker.get_delivery_audit(signal_id="SIG-NO-DEST-001")
    kiyu_tg = [a for a in audit if a["username"] == "kiyu" and a["channel"] == "TELEGRAM"][0]
    assert kiyu_tg["status"] == "NO_DESTINATION"
    assert kiyu_tg["attempted"] == 0


