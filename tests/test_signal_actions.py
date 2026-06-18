"""Unit tests for ``index_app.domains.trading.signal_actions`` (DEBT-008).

Covers all 5 extracted functions:
- set_config_fail_safe()
- notify_config_failure()
- telegram_action_quality()
- telegram_action_body()
- on_ws_tick()
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


# ── set_config_fail_safe ────────────────────────────────────────────────


class TestSetConfigFailSafe:
    def test_returns_fail_safe_config(self) -> None:
        from index_app.domains.trading.signal_actions import set_config_fail_safe

        def _factory() -> dict:
            return {"MODE": "MANUAL", "PAPER_MODE": True}

        result = set_config_fail_safe(make_fail_safe_config_fn=_factory)
        assert result == {"MODE": "MANUAL", "PAPER_MODE": True}

    def test_factory_called_once(self) -> None:
        from index_app.domains.trading.signal_actions import set_config_fail_safe

        mock_factory = MagicMock(return_value={"mode": "safe"})
        result = set_config_fail_safe(make_fail_safe_config_fn=mock_factory)
        mock_factory.assert_called_once()
        assert result == {"mode": "safe"}


# ── notify_config_failure ───────────────────────────────────────────────


class TestNotifyConfigFailure:
    def test_sends_critical_notification(self) -> None:
        from index_app.domains.trading.signal_actions import notify_config_failure

        mock_send = MagicMock()
        notify_config_failure(
            detail="Config parse error",
            send_fn=mock_send,
        )
        mock_send.assert_called_once_with(
            "[CONFIG_CRITICAL] Config parse error. Force MANUAL mode.",
            critical=True,
        )

    def test_logs_on_send_failure(self) -> None:
        from index_app.domains.trading.signal_actions import notify_config_failure

        def failing_send(*args, **kwargs) -> None:
            raise ValueError("telegram down")

        mock_log = MagicMock()
        notify_config_failure(
            detail="Broken",
            send_fn=failing_send,
            log_fn=mock_log,
        )
        mock_log.assert_called_once_with("Failed to send config failure notification")


# ── telegram_action_quality ─────────────────────────────────────────────


class TestTelegramActionQuality:
    def test_breakout_ok_returns_true(self) -> None:
        from index_app.domains.trading.signal_actions import telegram_action_quality

        ok, reason = telegram_action_quality({"breakout_ok": True})
        assert ok is True
        assert reason == "ok"

    def test_breakout_false_returns_blocked(self) -> None:
        from index_app.domains.trading.signal_actions import telegram_action_quality

        ok, reason = telegram_action_quality({"breakout_ok": False})
        assert ok is False
        assert "breakout_ok false" in reason

    def test_missing_breakout_defaults_true(self) -> None:
        from index_app.domains.trading.signal_actions import telegram_action_quality

        ok, reason = telegram_action_quality({})
        assert ok is True
        assert reason == "ok"

    def test_explicit_false_returns_blocked(self) -> None:
        from index_app.domains.trading.signal_actions import telegram_action_quality

        ok, reason = telegram_action_quality({"breakout_ok": False})
        assert ok is False


# ── telegram_action_body ────────────────────────────────────────────────


class TestTelegramActionBody:
    def test_includes_confidence(self) -> None:
        from index_app.domains.trading.signal_actions import telegram_action_body

        body = telegram_action_body(learning_state={"confidence": 85})
        assert "Conf=85" in body
        assert "MANUAL SIGNAL" in body

    def test_default_confidence_zero(self) -> None:
        from index_app.domains.trading.signal_actions import telegram_action_body

        body = telegram_action_body(learning_state={})
        assert "Conf=0" in body

    def test_includes_name_when_provided(self) -> None:
        from index_app.domains.trading.signal_actions import telegram_action_body

        body = telegram_action_body(learning_state={"confidence": 70}, name="NIFTY")
        assert "[NIFTY]" in body

    def test_omits_name_when_empty(self) -> None:
        from index_app.domains.trading.signal_actions import telegram_action_body

        body = telegram_action_body(learning_state={"confidence": 50})
        assert "[]" not in body
        assert body.strip().endswith("Learner")


# ── on_ws_tick ──────────────────────────────────────────────────────────


class TestOnWsTick:
    def test_non_dict_ignored(self) -> None:
        from index_app.domains.trading.signal_actions import on_ws_tick

        mock_log = MagicMock()
        mock_debug = MagicMock()

        on_ws_tick("not a dict", log_fn=mock_log, debug_fn=mock_debug)
        mock_log.assert_not_called()
        mock_debug.assert_not_called()

    def test_connect_logs_info(self) -> None:
        from index_app.domains.trading.signal_actions import on_ws_tick

        mock_log = MagicMock()
        mock_debug = MagicMock()

        on_ws_tick({"type": "connect"}, log_fn=mock_log, debug_fn=mock_debug)
        mock_log.assert_called_once()
        mock_debug.assert_not_called()

    def test_ticks_logs_debug(self) -> None:
        from index_app.domains.trading.signal_actions import on_ws_tick

        mock_log = MagicMock()
        mock_debug = MagicMock()

        on_ws_tick(
            {"type": "ticks", "data": [{"instrument_token": 123, "last_price": 23400.5}]},
            log_fn=mock_log,
            debug_fn=mock_debug,
        )
        mock_log.assert_not_called()
        mock_debug.assert_called_once()

    def test_empty_ticks_no_debug(self) -> None:
        from index_app.domains.trading.signal_actions import on_ws_tick

        mock_log = MagicMock()
        mock_debug = MagicMock()

        on_ws_tick({"type": "ticks", "data": []}, log_fn=mock_log, debug_fn=mock_debug)
        mock_debug.assert_not_called()

    def test_unknown_type_ignored(self) -> None:
        from index_app.domains.trading.signal_actions import on_ws_tick

        mock_log = MagicMock()
        mock_debug = MagicMock()

        on_ws_tick({"type": "unknown"}, log_fn=mock_log, debug_fn=mock_debug)
        mock_log.assert_not_called()
        mock_debug.assert_not_called()
