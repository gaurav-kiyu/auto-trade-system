"""
Tests for broker_capture — JSONL broker event capture for replay and RCA.

Covers:
- BrokerEvent dataclass construction and defaults
- JsonlCaptureWriter file creation and appending
- Thread safety when writing from multiple threads
- Error handling (invalid paths)
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest
from core.broker_capture import BrokerEvent, JsonlCaptureWriter

# ── BrokerEvent Dataclass ──────────────────────────────────────────────────


class TestBrokerEvent:
    def test_creation(self):
        event = BrokerEvent(ts="2024-01-01T00:00:00", event="order_placed")
        assert event.ts == "2024-01-01T00:00:00"
        assert event.event == "order_placed"
        assert event.order_id is None
        assert event.symbol == ""
        assert event.qty == 0
        assert event.strike == 0
        assert event.price is None
        assert event.provider == ""
        assert event.note == ""

    def test_creation_all_fields(self):
        event = BrokerEvent(
            ts="2024-01-01T00:00:00",
            event="order_filled",
            order_id="ORD123",
            symbol="NIFTY",
            direction="BUY",
            qty=75,
            strike=23500,
            price=150.50,
            provider="zerodha",
            note="Filled at limit",
        )
        assert event.order_id == "ORD123"
        assert event.symbol == "NIFTY"
        assert event.direction == "BUY"
        assert event.qty == 75
        assert event.strike == 23500
        assert event.price == 150.50
        assert event.provider == "zerodha"
        assert event.note == "Filled at limit"

    def test_frozen(self):
        """BrokerEvent is frozen (immutable)."""
        event = BrokerEvent(ts="2024-01-01", event="test")
        with pytest.raises(AttributeError):
            event.ts = "2024-01-02"  # type: ignore[misc]

    def test_order_id_none_by_default(self):
        """order_id defaults to None for events that don't have an order."""
        event = BrokerEvent(ts="2024-01-01", event="quote_update")
        assert event.order_id is None

    def test_different_event_types(self):
        for event_name in (
            "order_placed",
            "order_filled",
            "order_cancelled",
            "order_rejected",
            "position_opened",
            "position_closed",
            "broker_disconnect",
            "broker_reconnect",
        ):
            event = BrokerEvent(ts="2024-01-01", event=event_name)
            assert event.event == event_name


# ── JsonlCaptureWriter ─────────────────────────────────────────────────────


class TestJsonlCaptureWriter:
    @pytest.fixture
    def tmp_path(self, tmp_path: Path) -> Path:
        return tmp_path

    def test_creates_file_on_write(self, tmp_path: Path):
        path = tmp_path / "capture.jsonl"
        writer = JsonlCaptureWriter(path)
        assert not path.exists()
        writer.write(BrokerEvent(ts="2024-01-01", event="test"))
        assert path.exists()
        assert path.stat().st_size > 0

    def test_creates_parent_directory(self, tmp_path: Path):
        path = tmp_path / "subdir" / "nested" / "capture.jsonl"
        writer = JsonlCaptureWriter(path)
        writer.write(BrokerEvent(ts="2024-01-01", event="test"))
        assert path.exists()

    def test_append_multiple_events(self, tmp_path: Path):
        path = tmp_path / "capture.jsonl"
        writer = JsonlCaptureWriter(path)
        writer.write(BrokerEvent(ts="2024-01-01", event="event1"))
        writer.write(BrokerEvent(ts="2024-01-02", event="event2"))
        writer.write(BrokerEvent(ts="2024-01-03", event="event3"))
        lines = path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 3
        data = [json.loads(line) for line in lines]
        assert data[0]["event"] == "event1"
        assert data[1]["event"] == "event2"
        assert data[2]["event"] == "event3"

    def test_write_dict_payload(self, tmp_path: Path):
        """write() accepts raw dict payload."""
        path = tmp_path / "capture.jsonl"
        writer = JsonlCaptureWriter(path)
        writer.write({"ts": "2024-01-01", "event": "dict_event", "extra": "value"})
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["event"] == "dict_event"
        assert data["extra"] == "value"

    def test_path_property(self, tmp_path: Path):
        path = tmp_path / "capture.jsonl"
        writer = JsonlCaptureWriter(path)
        assert writer.path == path

    def test_json_content_all_fields(self, tmp_path: Path):
        path = tmp_path / "capture.jsonl"
        writer = JsonlCaptureWriter(path)
        event = BrokerEvent(
            ts="2024-01-01T10:30:00",
            event="order_filled",
            order_id="ORD456",
            symbol="BANKNIFTY",
            direction="SELL",
            qty=150,
            strike=49000,
            price=250.75,
            provider="angel",
            note="Partial fill",
        )
        writer.write(event)
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["ts"] == "2024-01-01T10:30:00"
        assert data["order_id"] == "ORD456"
        assert data["symbol"] == "BANKNIFTY"
        assert data["direction"] == "SELL"
        assert data["qty"] == 150
        assert data["strike"] == 49000
        assert data["price"] == 250.75
        assert data["provider"] == "angel"
        assert data["note"] == "Partial fill"

    def test_ensure_ascii_true(self, tmp_path: Path):
        """JSON uses ASCII-safe encoding."""
        path = tmp_path / "capture.jsonl"
        writer = JsonlCaptureWriter(path)
        event = BrokerEvent(ts="2024-01-01", event="unicode", note="₹500")
        writer.write(event)
        content = path.read_text(encoding="utf-8")
        assert "₹" not in content  # ensure_ascii escapes unicode
        assert "\\u20b9" in content  # ₹ = U+20B9

    def test_newline_terminated(self, tmp_path: Path):
        """Each JSON line ends with newline."""
        path = tmp_path / "capture.jsonl"
        writer = JsonlCaptureWriter(path)
        writer.write(BrokerEvent(ts="2024-01-01", event="e1"))
        writer.write(BrokerEvent(ts="2024-01-01", event="e2"))
        content = path.read_bytes()
        assert content.endswith(b"\n")
        assert content.count(b"\n") == 2


# ── Thread Safety ──────────────────────────────────────────────────────────


class TestThreadSafety:
    def test_concurrent_writes(self, tmp_path: Path):
        """Multiple threads can write concurrently without corruption."""
        path = tmp_path / "concurrent.jsonl"
        writer = JsonlCaptureWriter(path)
        n = 50

        def write_events():
            for i in range(n):
                writer.write(BrokerEvent(ts=f"2024-01-01T00:00:{i:02d}", event="concurrent"))

        t1 = threading.Thread(target=write_events)
        t2 = threading.Thread(target=write_events)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        lines = path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2 * n
        # All lines should be valid JSON
        for line in lines:
            data = json.loads(line)
            assert data["event"] == "concurrent"

    def test_concurrent_mixed_event_types(self, tmp_path: Path):
        """Mixed event types from multiple threads."""
        path = tmp_path / "mixed.jsonl"
        writer = JsonlCaptureWriter(path)
        n = 30

        def write_orders():
            for i in range(n):
                writer.write(BrokerEvent(
                    ts="2024-01-01",
                    event="order_placed",
                    order_id=f"ORD{i}",
                    symbol="NIFTY",
                    direction="BUY" if i % 2 == 0 else "SELL",
                    qty=75,
                ))

        def write_fills():
            for i in range(n):
                writer.write(BrokerEvent(
                    ts="2024-01-01",
                    event="order_filled",
                    order_id=f"ORD{i}",
                    price=150.0 + i,
                ))

        t1 = threading.Thread(target=write_orders)
        t2 = threading.Thread(target=write_fills)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        lines = path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2 * n
        events = [json.loads(line)["event"] for line in lines]
        assert events.count("order_placed") == n
        assert events.count("order_filled") == n


# ── Edge Cases ─────────────────────────────────────────────────────────────


class TestEdgeCases:
    def test_empty_event_string(self, tmp_path: Path):
        path = tmp_path / "empty.jsonl"
        writer = JsonlCaptureWriter(path)
        writer.write(BrokerEvent(ts="2024-01-01", event=""))
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["event"] == ""

    def test_large_note(self, tmp_path: Path):
        path = tmp_path / "large.jsonl"
        writer = JsonlCaptureWriter(path)
        event = BrokerEvent(
            ts="2024-01-01",
            event="order_filled",
            note="x" * 10_000,
        )
        writer.write(event)
        data = json.loads(path.read_text(encoding="utf-8"))
        assert len(data["note"]) == 10_000

    def test_zero_qty(self, tmp_path: Path):
        path = tmp_path / "zero.jsonl"
        writer = JsonlCaptureWriter(path)
        writer.write(BrokerEvent(ts="2024-01-01", event="test", qty=0))
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["qty"] == 0

    def test_none_order_id(self, tmp_path: Path):
        """order_id=None is serialized as null in JSON."""
        path = tmp_path / "none_id.jsonl"
        writer = JsonlCaptureWriter(path)
        writer.write(BrokerEvent(ts="2024-01-01", event="test"))
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["order_id"] is None

    def test_existing_file_appends(self, tmp_path: Path):
        """Writing to an existing file appends rather than overwrites."""
        path = tmp_path / "append.jsonl"
        path.write_text('{"existing": true}\n', encoding="utf-8")
        writer = JsonlCaptureWriter(path)
        writer.write(BrokerEvent(ts="2024-01-01", event="appended"))
        lines = path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2
