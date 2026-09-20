import json
import os
import sqlite3
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.datetime_ist import now_ist
from core.ports.notification.notification_port import (
    Notification,
    NotificationChannel,
    NotificationPriority,
    NotificationResult,
    NotificationStatus,
)
from core.services.notification_service import NotificationService, ServiceStatus
from core.signals.signal_tracker import SignalTracker


@pytest.fixture
def temp_tracker(tmp_path):
    """Provide an isolated SignalTracker instance with its own database."""
    db_file = tmp_path / "test_signals.db"
    SignalTracker.reset_instance()
    tracker = SignalTracker(db_path=db_file)
    yield tracker
    SignalTracker.reset_instance()


def test_enqueue_notification_retry_idempotence(temp_tracker):
    """Test enqueuing retries is idempotent and does not create duplicate rows."""
    sig_id = "SIG-TEST-001"
    uname = "admin"
    channel = "TELEGRAM"
    dest = "12345678"
    payload = {"symbol": "NIFTY", "score": 85}

    retry_id1 = temp_tracker.enqueue_notification_retry(
        signal_id=sig_id,
        username=uname,
        channel=channel,
        destination=dest,
        payload=payload,
        error_message="Connection timed out",
        max_attempts=3,
        delay_seconds=5,
    )
    assert retry_id1 > 0

    # Second enqueue for same (signal_id, username, channel) must update, not create duplicate
    retry_id2 = temp_tracker.enqueue_notification_retry(
        signal_id=sig_id,
        username=uname,
        channel=channel,
        destination=dest,
        payload=payload,
        error_message="Connection refused",
        max_attempts=3,
        delay_seconds=10,
    )
    assert retry_id2 == retry_id1

    metrics = temp_tracker.get_notification_queue_metrics()
    assert metrics["pending_retries"] == 1


def test_claim_due_notification_retries_atomic(temp_tracker):
    """Test atomic claiming transitions items to PROCESSING and prevents double claiming."""
    # Enqueue item due in past (-1 second)
    temp_tracker.enqueue_notification_retry(
        signal_id="SIG-DUE-001",
        username="admin",
        channel="TELEGRAM",
        destination="111",
        payload={"msg": "hello"},
        error_message="fail",
        max_attempts=3,
        delay_seconds=-1,
    )

    # Enqueue item due in future (+300 seconds)
    temp_tracker.enqueue_notification_retry(
        signal_id="SIG-FUTURE-002",
        username="admin",
        channel="EMAIL",
        destination="admin@opb.com",
        payload={"msg": "future"},
        error_message="fail",
        max_attempts=3,
        delay_seconds=300,
    )

    # Worker 1 claims due items
    claimed1 = temp_tracker.claim_due_notification_retries(max_items=10)
    assert len(claimed1) == 1
    assert claimed1[0]["signal_id"] == "SIG-DUE-001"
    assert claimed1[0]["status"] == "PROCESSING"

    # Worker 2 simultaneously attempts to claim: must get 0 because item is PROCESSING
    claimed2 = temp_tracker.claim_due_notification_retries(max_items=10)
    assert len(claimed2) == 0


def test_complete_notification_retry(temp_tracker):
    """Test completing a retry transitions it to COMPLETED."""
    retry_id = temp_tracker.enqueue_notification_retry(
        signal_id="SIG-COMP-001",
        username="admin",
        channel="TELEGRAM",
        destination="111",
        payload={"msg": "hello"},
        error_message="fail",
    )

    success = temp_tracker.complete_notification_retry(retry_id)
    assert success is True

    metrics = temp_tracker.get_notification_queue_metrics()
    assert metrics["completed_retries"] == 1
    assert metrics["pending_retries"] == 0


def test_fail_notification_retry_moves_to_dlq(temp_tracker):
    """Test that exhausting max attempts moves the item to notification_dead_letter."""
    sig_id = "SIG-EXHAUST-001"
    retry_id = temp_tracker.enqueue_notification_retry(
        signal_id=sig_id,
        username="admin",
        channel="TELEGRAM",
        destination="111",
        payload={"msg": "test_exhaust"},
        error_message="initial error",
        max_attempts=3,
        delay_seconds=-1,
    )

    # Attempt 1 -> 2 (rescheduled)
    outcome1 = temp_tracker.fail_notification_retry(retry_id, "fail 2", next_delay_seconds=5)
    assert outcome1 == "RETRY_SCHEDULED"

    # Attempt 2 -> 3 (rescheduled)
    outcome2 = temp_tracker.fail_notification_retry(retry_id, "fail 3", next_delay_seconds=15)
    assert outcome2 == "RETRY_SCHEDULED"

    # Attempt 3 -> 4 (exhausted, next_delay_seconds=None)
    outcome3 = temp_tracker.fail_notification_retry(retry_id, "terminal error", next_delay_seconds=None)
    assert outcome3 == "DEAD_LETTER"

    # Verify DLQ table has entry
    dlq_records = temp_tracker.get_dead_letters(limit=10)
    assert len(dlq_records) == 1
    assert dlq_records[0]["signal_id"] == sig_id
    assert dlq_records[0]["channel"] == "TELEGRAM"
    assert dlq_records[0]["last_error"] == "terminal error"

    metrics = temp_tracker.get_notification_queue_metrics()
    assert metrics["dlq_total"] == 1
    assert metrics["dlq_by_channel"].get("TELEGRAM") == 1


def test_independent_channel_failure_and_retry(temp_tracker):
    """Test that Telegram failure and Email success results in only Telegram being queued for retry."""
    with patch("core.signals.signal_tracker.SignalTracker.get_instance", return_value=temp_tracker):
        svc = NotificationService()
        svc._status = svc._status.__class__.RUNNING

        mock_tg = MagicMock()
        mock_tg.enabled = True
        mock_tg.send_notification.return_value = NotificationResult(
            notification_id="fail_tg",
            status=NotificationStatus.FAILED,
            channel=NotificationChannel.TELEGRAM,
            timestamp=now_ist(),
            error_message="Telegram 502 Bad Gateway",
        )

        mock_email = MagicMock()
        mock_email.enabled = True
        mock_email.send_notification.return_value = NotificationResult(
            notification_id="succ_em",
            status=NotificationStatus.SENT,
            channel=NotificationChannel.EMAIL,
            timestamp=now_ist(),
        )

        svc._adapters[NotificationChannel.TELEGRAM] = mock_tg
        svc._adapters[NotificationChannel.EMAIL] = mock_email

        signal = {
            "signal_id": "SIG-INDEP-001",
            "symbol": "BANKNIFTY",
            "tier": "STRONG",
            "score": 85,
            "entry_price": 50000.0,
            "category": "INDEX_OPTIONS",
        }

        user_mock = MagicMock()
        user_mock.username = "admin"
        user_mock.telegram_enabled = True
        user_mock.telegram_chat_id = "987654"
        user_mock.email_enabled = True
        user_mock.email = "admin@example.com"

        res = svc.dispatch_qualifying_signal(signal, eligible_users=[user_mock])

        # Verify dispatch results
        assert res["deliveries"]["admin"]["TELEGRAM"] == "FAILED"
        assert res["deliveries"]["admin"]["EMAIL"] == "SENT"

        # Verify only Telegram is enqueued for retry
        metrics = temp_tracker.get_notification_queue_metrics()
        assert metrics["pending_retries"] == 1
        assert metrics["pending_by_channel"].get("TELEGRAM") == 1
        assert metrics["pending_by_channel"].get("EMAIL", 0) == 0

        # Now test process_retry_queue when Telegram adapter recovers
        mock_tg.send_notification.return_value = NotificationResult(
            notification_id="recovered_tg",
            status=NotificationStatus.SENT,
            channel=NotificationChannel.TELEGRAM,
            timestamp=now_ist(),
        )

        # Force next_attempt_at into past to simulate expiration
        conn = temp_tracker._get_conn()
        cur = conn.cursor()
        cur.execute("UPDATE notification_retry_queue SET next_attempt_at = '2020-01-01 00:00:00'")
        conn.commit()
        conn.close()

        retry_counts = svc.process_retry_queue(max_items=10)
        assert retry_counts["processed"] == 1
        assert retry_counts["succeeded"] == 1

        # Check delivery audit: Telegram should now be delivered
        assert temp_tracker.is_signal_delivered("SIG-INDEP-001", "admin", "TELEGRAM") is True


def test_notification_health_watchdog(temp_tracker):
    """Test get_notification_health reflects subsystem status and queue metrics."""
    with patch("core.signals.signal_tracker.SignalTracker.get_instance", return_value=temp_tracker):
        svc = NotificationService()
        svc._status = ServiceStatus.RUNNING

        health = svc.get_notification_health()
        assert health["service_status"].upper() == "RUNNING"
        assert "queue_metrics" in health
        assert health["healthy"] is True
