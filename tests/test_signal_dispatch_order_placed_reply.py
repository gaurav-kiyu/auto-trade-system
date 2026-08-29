"""Tests for AllNSEScanner._dispatch_alert_if_eligible()'s signal_id embedding.

record_generated_signal() now runs BEFORE the Telegram/email message is
composed and sent (previously it ran after), so the returned signal_id can
be embedded in the outbound message as a "/placed {signal_id}" reply hint.
That lets the recipient mark a signal as "order actually placed" from
Telegram via the already-live TelegramCommander polling bot
(core/telegram_commander.py's /placed and /unplaced commands), writing to
the exact same core.signals.signal_tracker.mark_order_placed() record the
admin dashboard checkbox uses - one persisted history, not two.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from unittest.mock import MagicMock

from core.all_nse_scanner import AllNSEScanner, ScannedStockSignal
from core.auth.user_signal_permissions import UserSignalPermission


def _make_signal(**overrides) -> ScannedStockSignal:
    base = dict(
        symbol="RELIANCE",
        company_name="Reliance Industries",
        series="EQ",
        direction="CALL",
        score=100,
        raw_score=100,
        tier="STRONG",
        regime="TRENDING",
        price=2500.0,
        rsi=60.0,
        adx=30.0,
        vwap=2490.0,
    )
    base.update(overrides)
    return ScannedStockSignal(**base)


class _FakeTelegramResponse:
    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def read(self) -> bytes:
        return json.dumps({"ok": True, "result": {"message_id": 1}}).encode("utf-8")


class TestSignalIdEmbeddedBeforeDispatch:
    def _make_scanner(self) -> AllNSEScanner:
        scanner = AllNSEScanner(cfg={})
        # _reload_config_credentials() re-reads the REAL json/config.json on
        # every call (including a second call inside _dispatch_alert_if_eligible
        # itself, right before the score gate) - it ignores whatever cfg dict
        # was passed to the constructor. No-op it so the test-controlled
        # credentials below aren't clobbered mid-method.
        scanner._reload_config_credentials = MagicMock()
        scanner._bot_token = "test:token"
        scanner._chat_id = "12345"
        scanner._email_enabled = False
        scanner._email_to = ""
        scanner._cooldown_secs = 0
        return scanner

    def test_record_generated_signal_called_before_telegram_send(self, monkeypatch) -> None:
        scanner = self._make_scanner()

        recipient = UserSignalPermission(
            username="test_trader",
            display_name="Test Trader",
            role="viewer",
            is_active=True,
            signals_enabled=True,
            allowed_categories=["STOCK_OPTIONS"],
            min_signal_tier="STRONG_ONLY",
            telegram_enabled=True,
            telegram_chat_id="12345",
            email_enabled=False,
            email="",
            max_signals_daily=0,
            max_signals_weekly=0,
            max_signals_monthly=0,
            max_signals_yearly=0,
        )

        permission_manager = MagicMock()
        permission_manager.get_eligible_recipients.return_value = [recipient]

        monkeypatch.setattr(
            "core.auth.user_signal_permissions.UserPermissionManager.get_instance",
            MagicMock(return_value=permission_manager),
        )

        tracker_mock = MagicMock()
        tracker_mock.count_generated_today.return_value = 0
        tracker_mock.record_generated_signal.return_value = "SIG-ABC-123"
        monkeypatch.setattr(
            "core.signals.signal_tracker.SignalTracker.get_instance",
            MagicMock(return_value=tracker_mock),
        )

        sent_payloads: list[dict[str, list[str]]] = []

        def _fake_urlopen(req, timeout=10):
            body = req.data.decode("utf-8")
            sent_payloads.append(urllib.parse.parse_qs(body))
            return _FakeTelegramResponse()

        monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen)

        scanner._dispatch_alert_if_eligible(_make_signal())

        tracker_mock.record_generated_signal.assert_called_once()
        assert sent_payloads, "Telegram send was never attempted"

    def test_signal_id_and_reply_hint_appear_in_telegram_message(self, monkeypatch) -> None:
        scanner = self._make_scanner()

        recipient = UserSignalPermission(
            username="test_trader",
            display_name="Test Trader",
            role="viewer",
            is_active=True,
            signals_enabled=True,
            allowed_categories=["STOCK_OPTIONS"],
            min_signal_tier="STRONG_ONLY",
            telegram_enabled=True,
            telegram_chat_id="12345",
            email_enabled=False,
            email="",
            max_signals_daily=0,
            max_signals_weekly=0,
            max_signals_monthly=0,
            max_signals_yearly=0,
        )

        permission_manager = MagicMock()
        permission_manager.get_eligible_recipients.return_value = [recipient]

        monkeypatch.setattr(
            "core.auth.user_signal_permissions.UserPermissionManager.get_instance",
            MagicMock(return_value=permission_manager),
        )

        tracker_mock = MagicMock()
        tracker_mock.count_generated_today.return_value = 0
        tracker_mock.record_generated_signal.return_value = "SIG-ABC-123"
        monkeypatch.setattr(
            "core.signals.signal_tracker.SignalTracker.get_instance",
            MagicMock(return_value=tracker_mock),
        )

        sent_payloads: list[dict[str, list[str]]] = []

        def _fake_urlopen(req, timeout=10):
            body = req.data.decode("utf-8")
            sent_payloads.append(urllib.parse.parse_qs(body))
            return _FakeTelegramResponse()

        monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen)

        scanner._dispatch_alert_if_eligible(_make_signal())

        sent_text = sent_payloads[0]["text"][0]
        assert "SIG-ABC-123" in sent_text
        assert "/placed SIG-ABC-123" in sent_text

    def test_no_signal_id_omits_reply_hint_without_crashing(self, monkeypatch) -> None:
        """If SignalTracker errors, record_generated_signal's exception is
        swallowed and signal_id stays "" - the message must still send
        successfully, just without the reply-hint line (regression guard)."""
        scanner = self._make_scanner()

        recipient = UserSignalPermission(
            username="test_trader",
            display_name="Test Trader",
            role="viewer",
            is_active=True,
            signals_enabled=True,
            allowed_categories=["STOCK_OPTIONS"],
            min_signal_tier="STRONG_ONLY",
            telegram_enabled=True,
            telegram_chat_id="12345",
            email_enabled=False,
            email="",
            max_signals_daily=0,
            max_signals_weekly=0,
            max_signals_monthly=0,
            max_signals_yearly=0,
        )

        permission_manager = MagicMock()
        permission_manager.get_eligible_recipients.return_value = [recipient]

        monkeypatch.setattr(
            "core.auth.user_signal_permissions.UserPermissionManager.get_instance",
            MagicMock(return_value=permission_manager),
        )

        tracker_mock = MagicMock()
        tracker_mock.count_generated_today.return_value = 0
        tracker_mock.record_generated_signal.side_effect = ValueError("db locked")
        monkeypatch.setattr(
            "core.signals.signal_tracker.SignalTracker.get_instance",
            MagicMock(return_value=tracker_mock),
        )

        sent_payloads: list[dict[str, list[str]]] = []

        def _fake_urlopen(req, timeout=10):
            body = req.data.decode("utf-8")
            sent_payloads.append(urllib.parse.parse_qs(body))
            return _FakeTelegramResponse()

        monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen)

        scanner._dispatch_alert_if_eligible(_make_signal())  # must not raise

        # A signal without a persisted signal ID is not externally dispatchable.
        # This is a deliberate delivery safety guard: without durable identity,
        # the notification cannot be reliably tracked/reconciled later.
        assert not sent_payloads, (
            "Telegram must not be sent when signal persistence fails"
        )
