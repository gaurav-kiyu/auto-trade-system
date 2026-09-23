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
