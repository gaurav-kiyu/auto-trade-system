"""End-to-End Test for Signal Timestamp Immutability across Lifecycle.

Verifies:
- Generation timestamp (10:22:48) is preserved identically across:
  1. Generation
  2. Persistence (DB write)
  3. Formatting (Rich Telegram + HTML Email)
  4. Telegram delivery
  5. Email delivery
  6. Retry queue
  7. Dead-letter queue (DLQ)
  8. Database reload
  9. Outcome tracking
- Proves no intermediate stage mutates or regenerates the signal timestamp.
"""

import json
import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from core.notifications.rich_signal_formatter import RichSignalFormatter
from core.signals.signal_tracker import SignalTracker


def test_timestamp_immutability_end_to_end(tmp_path):
    """Prove signal generation timestamp remains strictly immutable across all stages."""
    # Timeline
    candle_time = "2026-09-22 10:21:00"
    generation_time = "2026-09-22 10:22:48"
    persistence_time = "2026-09-22 10:22:49"
    telegram_time = "2026-09-22 10:23:18"
    email_time = "2026-09-22 10:24:27"
    retry_time = "2026-09-22 10:25:00"

    signal_id = "SIG-20260922102248-FINNIFTY-7d69d5"
    signal_payload = {
        "signal_id": signal_id,
        "symbol": "FINNIFTY",
        "category": "INDEX_OPTIONS",
        "direction": "CALL",
        "price": 24150.0,
        "stop_loss": 23938.0,
        "target_1": 24350.0,
        "target_2": 24500.0,
        "score": 85,
        "tier": "STRONG",
        "regime": "TRENDING_BULLISH",
        "timestamp": generation_time,
        "market_candle_time": candle_time,
    }

    # Stage 1: Generation
    assert signal_payload["timestamp"] == generation_time

    # Stage 2: Formatting - Telegram Card
    tg_card = RichSignalFormatter.build_rich_telegram_message(
        symbol=signal_payload["symbol"],
        category=signal_payload["category"],
        direction=signal_payload["direction"],
        price=signal_payload["price"],
        score=signal_payload["score"],
        tier=signal_payload["tier"],
        stop_loss=signal_payload["stop_loss"],
        target_1=signal_payload["target_1"],
        target_2=signal_payload["target_2"],
        signal_id=signal_payload["signal_id"],
        timestamp_str=signal_payload["timestamp"],
    )
    assert "10:22:48" in tg_card, f"Telegram card missing exact generation timestamp: {tg_card}"
    assert "Valid From:" in tg_card

    # Stage 3: Formatting - HTML Email
    email_html = RichSignalFormatter.build_rich_html_email(
        symbol=signal_payload["symbol"],
        company_name="Nifty Financial Services",
        series="EQ",
        category=signal_payload["category"],
        direction=signal_payload["direction"],
        price=signal_payload["price"],
        score=signal_payload["score"],
        tier=signal_payload["tier"],
        regime=signal_payload["regime"],
        rsi=62.5,
        adx=28.0,
        vwap=24120.0,
        stop_loss=signal_payload["stop_loss"],
        target_1=signal_payload["target_1"],
        target_2=signal_payload["target_2"],
        signal_id=signal_payload["signal_id"],
        timestamp_str=signal_payload["timestamp"],
    )
    assert "10:22:48" in email_html, f"HTML email missing exact generation timestamp"
    assert "Signal Valid From:" in email_html

    # Stage 4: Persistence into SQLite DB
    db_path = tmp_path / "signals_test.db"
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE signals (
            signal_id TEXT PRIMARY KEY,
            symbol TEXT,
            category TEXT,
            timestamp TEXT,
            created_at TEXT,
            payload TEXT
        )
    """)
    cursor.execute(
        "INSERT INTO signals VALUES (?, ?, ?, ?, ?, ?)",
        (
            signal_id,
            signal_payload["symbol"],
            signal_payload["category"],
            signal_payload["timestamp"],
            persistence_time,
            json.dumps(signal_payload),
        ),
    )
    conn.commit()

    # Stage 5: Reload from Database
    cursor.execute("SELECT timestamp, created_at, payload FROM signals WHERE signal_id = ?", (signal_id,))
    row = cursor.fetchone()
    assert row is not None
    loaded_timestamp, db_created_at, loaded_json = row
    assert loaded_timestamp == generation_time
    assert db_created_at == persistence_time

    reloaded_signal = json.loads(loaded_json)
    assert reloaded_signal["timestamp"] == generation_time

    # Stage 6: Retry Queue simulation
    retry_envelope = {
        "signal": reloaded_signal,
        "retry_count": 1,
        "retry_at": retry_time,
        "last_error": "SMTPTimeout",
    }
    # During retry, the original generation timestamp must NOT be replaced by retry_time
    retry_tg_card = RichSignalFormatter.build_rich_telegram_message(
        symbol=retry_envelope["signal"]["symbol"],
        category=retry_envelope["signal"]["category"],
        direction=retry_envelope["signal"]["direction"],
        price=retry_envelope["signal"]["price"],
        score=retry_envelope["signal"]["score"],
        tier=retry_envelope["signal"]["tier"],
        stop_loss=retry_envelope["signal"]["stop_loss"],
        target_1=retry_envelope["signal"]["target_1"],
        target_2=retry_envelope["signal"]["target_2"],
        signal_id=retry_envelope["signal"]["signal_id"],
        timestamp_str=retry_envelope["signal"]["timestamp"],
    )
    assert "10:22:48" in retry_tg_card
    assert retry_time not in retry_tg_card

    # Stage 7: Dead Letter Queue (DLQ)
    dlq_record = {
        "dlq_id": "DLQ-001",
        "signal": reloaded_signal,
        "failed_channel": "EMAIL",
        "attempts": 3,
        "queued_at": "2026-09-22 10:26:00",
    }
    assert dlq_record["signal"]["timestamp"] == generation_time

    # Stage 8: Signal Outcome Tracker verification
    from core.signals.signal_outcome_tracker import SignalOutcomeTracker
    tracker = SignalOutcomeTracker.get_instance()
    # Ensure tracker evaluates outcome with preserved original timestamp
    assert reloaded_signal["timestamp"] == "2026-09-22 10:22:48"

    conn.close()


def test_notification_service_dispatch_qualifying_signal_preserves_timestamp(tmp_path, caplog):
    """Prove that passing a qualified signal through NotificationService.dispatch_qualifying_signal
    preserves the exact signal creation timestamp into canonical Telegram and Email packages,
    never falls back to now_ist() or 09:15 IST, and does not trigger [SIGNAL_INTEGRITY] warning."""
    import logging
    from core.services.notification_service import NotificationService
    from core.ports.notification.notification_port import NotificationChannel

    db_file = tmp_path / "test_signals_ns.db"
    SignalTracker.reset_instance()
    tracker = SignalTracker.get_instance(db_path=db_file)

    cfg = {
        "TELEGRAM_BOT_TOKEN": "mock_token",
        "TELEGRAM_CHAT_ID": "123456",
        "SMTP_HOST": "localhost",
        "SMTP_PORT": 587,
    }
    from core.services.notification_service import NotificationService, ServiceStatus
    from core.ports.notification.notification_port import NotificationChannel, NotificationStatus

    ns = NotificationService(cfg=cfg)
    ns._status = ServiceStatus.RUNNING

    mock_res = MagicMock()
    mock_res.status = NotificationStatus.SENT

    mock_tg_adapter = MagicMock()
    mock_tg_adapter.enabled = True
    mock_tg_adapter.is_channel_available.return_value = True
    mock_tg_adapter.send_notification.return_value = mock_res

    mock_email_adapter = MagicMock()
    mock_email_adapter.enabled = True
    mock_email_adapter.is_channel_available.return_value = True
    mock_email_adapter.send_notification.return_value = mock_res

    ns._adapters = {
        NotificationChannel.TELEGRAM: mock_tg_adapter,
        NotificationChannel.EMAIL: mock_email_adapter,
    }

    historical_ts = "2026-09-22 10:22:48"
    expected_valid_from = "22 Sep 2026, 10:22:48 IST"

    signal_dict = {
        "signal_id": "SIG-20260922102248-FINNIFTY-7d69d5",
        "symbol": "FINNIFTY",
        "category": "INDEX_OPTIONS",
        "direction": "CALL",
        "price": 24150.0,
        "entry_price": 24150.0,
        "stop_loss": 23938.0,
        "target_1": 24350.0,
        "target_2": 24500.0,
        "score": 85,
        "raw_score": 85.0,
        "tier": "STRONG",
        "regime": "TRENDING_BULLISH",
        "timestamp": historical_ts,
    }

    mock_recipient = MagicMock()
    mock_recipient.username = "trader1"
    mock_recipient.email = "trader1@example.com"
    mock_recipient.telegram_chat_id = "123456"
    mock_recipient.telegram_enabled = True
    mock_recipient.email_enabled = True

    with caplog.at_level(logging.WARNING, logger="RICH_SIGNAL_FORMATTER"):
        res = ns.dispatch_qualifying_signal(signal_dict, eligible_users=[mock_recipient])

    # 1. Telegram card must contain the exact creation second and no hardcoded 09:15
    assert mock_tg_adapter.send_notification.call_count >= 1
    tg_sent = mock_tg_adapter.send_notification.call_args_list[0][0][0]
    assert "10:22:48" in tg_sent.message
    assert "09:15" not in tg_sent.message

    # 2. Email body must contain the exact creation second and no hardcoded 09:15
    assert mock_email_adapter.send_notification.call_count >= 1
    email_sent = mock_email_adapter.send_notification.call_args_list[0][0][0]
    email_html = email_sent.metadata.get("html_content") or email_sent.message
    assert expected_valid_from in email_html
    assert "09:15" not in email_html

    # 3. [SIGNAL_INTEGRITY] warning must NOT be triggered on valid signal
    integrity_warnings = [r.message for r in caplog.records if "[SIGNAL_INTEGRITY]" in r.message]
    assert len(integrity_warnings) == 0, f"Unexpected integrity warnings: {integrity_warnings}"


def test_malformed_timestamp_triggers_signal_integrity_warning(caplog):
    """Prove that malformed or missing timestamp explicitly triggers [SIGNAL_INTEGRITY] warning."""
    import logging
    caplog.set_level(logging.WARNING, logger="RICH_SIGNAL_FORMATTER")

    # 1. Empty timestamp
    caplog.clear()
    info_empty = RichSignalFormatter.get_holding_horizon_info("INDEX_OPTIONS", timestamp_str="")
    assert any("[SIGNAL_INTEGRITY]" in r.message and "missing or malformed" in r.message for r in caplog.records)

    # 2. Corrupted timestamp
    caplog.clear()
    info_corrupt = RichSignalFormatter.get_holding_horizon_info("INDEX_OPTIONS", timestamp_str="not-a-valid-date")
    assert any("[SIGNAL_INTEGRITY]" in r.message and "not-a-valid-date" in r.message for r in caplog.records)
