"""ICS-Telegram Alert Bridge — wires Incident Commander alerts to Telegram notifications.

Connects the Incident Command System's alert callback to the Telegram
notification infrastructure so critical/high incidents automatically
send real-time alerts to the trading bot's Telegram channel.

Usage:
    from core.ics_telegram_bridge import wire_ics_telegram_alerts

    # Auto-wire (reads env vars and configures the bridge)
    wire_ics_telegram_alerts()

    # Manual wire with explicit adapter
    from core.incident_command_system import get_incident_commander
    from core.ics_telegram_bridge import ICSTelegramBridge

    bridge = ICSTelegramBridge(bot_token="...", chat_id="...")
    bridge.wire(get_incident_commander())

Design:
- Lightweight bridge, no modification to existing IncidentCommander or Telegram adapter
- Uses TelegramNotificationAdapter's public send_raw() for direct text delivery
- Falls back silently if Telegram credentials are not configured
- Thread-safe with RLock
- Formats incident alerts with emoji badges for severity
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any

_log = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

ENV_BOT_TOKEN = "OPBUYING_TELEGRAM_BOT_TOKEN"
ENV_CHAT_ID = "OPBUYING_TELEGRAM_CHAT_ID"


# ── ICS Telegram Bridge ─────────────────────────────────────────────────────


class ICSTelegramBridge:
    """Bridges Incident Commander alerts to Telegram notifications.

    Uses TelegramNotificationAdapter's public send_raw() passthrough
    to deliver real-time incident alerts to the configured Telegram channel.

    Args:
        bot_token: Telegram bot token from @BotFather.
        chat_id: Target Telegram chat/channel ID.
        enabled: Whether the bridge is active (default True).
    """

    def __init__(
        self,
        bot_token: str,
        chat_id: str,
        enabled: bool = True,
    ) -> None:
        self._bot_token = bot_token
        self._chat_id = chat_id
        self._enabled = enabled
        self._lock = threading.RLock()
        self._client: Any = None  # TelegramNotificationAdapter instance (lazy init)
        self._wired: bool = False

    # ── Initialization ─────────────────────────────────────────────────────

    def _ensure_client(self) -> bool:
        """Lazily initialize the Telegram client.

        Returns:
            True if client is available, False if requests is not installed.
        """
        if self._client is not None:
            return True
        import importlib.util
        if not importlib.util.find_spec("requests"):
            _log.warning("[ICS_TG] requests library not installed — Telegram alerts disabled")
            return False

        try:
            # Late import to avoid circular deps. Uses the public
            # TelegramNotificationAdapter (+ its send_raw() passthrough)
            # rather than the private _TelegramClient it wraps internally.
            from infrastructure.adapters.notifications.telegram_adapter import (
                TelegramNotificationAdapter,
            )

            self._client = TelegramNotificationAdapter(
                bot_token=self._bot_token,
                default_chat_id=self._chat_id,
                enabled=self._enabled,
                cooldown_seconds=0,       # No cooldown for incident alerts
                rate_limit=30,            # Higher limit for critical alerts
            )
            return True
        except Exception as exc:
            _log.warning("[ICS_TG] Failed to initialize Telegram client: %s", exc)
            return False

    # ── Alert callback ─────────────────────────────────────────────────────

    def _alert_callback(self, message: str, is_critical: bool) -> None:
        """Callback function for IncidentCommander.set_alert_fn().

        Formats the alert message and sends via Telegram.

        Args:
            message: The alert message from the IncidentCommander.
            is_critical: True for CRITICAL incidents, False for INFO/resolved.
        """
        if not self._enabled:
            return

        if not self._ensure_client():
            return

        # Format the message with emoji prefix for Telegram
        prefix = "🚨 CRITICAL" if is_critical else "ℹ️ NOTIFICATION"
        formatted = f"{prefix}\n{message}"

        try:
            sent = self._client.send_raw(
                text=formatted,
                chat_id=self._chat_id,
                critical=is_critical,
            )
            if sent:
                _log.info("[ICS_TG] Alert sent: %s", message[:80])
            else:
                _log.warning("[ICS_TG] Alert send failed: %s", message[:80])
        except Exception as exc:
            _log.error("[ICS_TG] Alert send error: %s", exc)

    # ── Wiring ─────────────────────────────────────────────────────────

    def wire(self, commander: Any) -> bool:
        """Wire the alert callback into an IncidentCommander instance.

        Args:
            commander: IncidentCommander instance to wire into.

        Returns:
            True if wired successfully, False if disabled or missing deps.
        """
        if not self._enabled:
            _log.info("[ICS_TG] Bridge disabled — not wiring alerts")
            return False

        with self._lock:
            if self._wired:
                return True  # Already wired

            try:
                commander.set_alert_fn(self._alert_callback)
                self._wired = True
                _log.info("[ICS_TG] Alert callback wired into IncidentCommander")
                return True
            except Exception as exc:
                _log.error("[ICS_TG] Failed to wire alert callback: %s", exc)
                return False

    def unwire(self, commander: Any) -> None:
        """Remove the alert callback from the IncidentCommander."""
        with self._lock:
            try:
                commander.set_alert_fn(None)
                self._wired = False
                _log.info("[ICS_TG] Alert callback unwired")
            except Exception as exc:
                _log.warning("[ICS_TG] Failed to unwire: %s", exc)

    @property
    def is_wired(self) -> bool:
        return self._wired

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    def close(self) -> None:
        """Close the underlying Telegram client session."""
        with self._lock:
            if self._client is not None:
                try:
                    self._client.close()
                except Exception as exc:
                    _log.debug("[ICS_TG] Client close: %s", exc)
                self._client = None


# ── Singleton ────────────────────────────────────────────────────────────────

_bridge: ICSTelegramBridge | None = None
_bridge_lock = threading.RLock()


def get_ics_telegram_bridge(
    bot_token: str | None = None,
    chat_id: str | None = None,
    enabled: bool | None = None,
) -> ICSTelegramBridge:
    """Get or create the singleton ICSTelegramBridge.

    Args:
        bot_token: Override bot token (default: from OPBUYING_TELEGRAM_BOT_TOKEN env).
        chat_id: Override chat ID (default: from OPBUYING_TELEGRAM_CHAT_ID env).
        enabled: Override enabled state (default: True if both env vars are set).

    Returns:
        The singleton ICSTelegramBridge instance.
    """
    global _bridge
    if _bridge is None:
        with _bridge_lock:
            if _bridge is None:
                # Resolve credentials from env or overrides
                token = bot_token or os.environ.get(ENV_BOT_TOKEN, "")
                cid = chat_id or os.environ.get(ENV_CHAT_ID, "")
                # Auto-detect enabled: enabled only if credentials are available
                if enabled is None:
                    bridge_enabled = bool(token and cid)
                else:
                    bridge_enabled = enabled

                _bridge = ICSTelegramBridge(
                    bot_token=token,
                    chat_id=cid,
                    enabled=bridge_enabled,
                )

                if bridge_enabled and token and cid:
                    # Auto-wire into the IncidentCommander singleton
                    try:
                        from core.incident_command_system import (
                            get_incident_commander,
                        )

                        commander = get_incident_commander()
                        _bridge.wire(commander)
                        _log.info(
                            "[ICS_TG] Auto-wired into IncidentCommander singleton"
                        )
                    except Exception as exc:
                        _log.warning(
                            "[ICS_TG] Auto-wire skipped (IncidentCommander not available): %s",
                            exc,
                        )
                else:
                    _log.info(
                        "[ICS_TG] Bridge created in passive mode "
                        "(credentials not configured)"
                    )
    return _bridge


def reset_ics_telegram_bridge() -> None:
    """Reset the singleton (for testing)."""
    global _bridge
    with _bridge_lock:
        if _bridge is not None:
            _bridge.close()
            _bridge = None


def wire_ics_telegram_alerts(
    bot_token: str | None = None,
    chat_id: str | None = None,
    enabled: bool | None = None,
) -> bool:
    """Convenience function to wire ICS → Telegram alerts.

    Reads credentials from environment variables by default.
    Safe to call multiple times (idempotent via singleton).

    Args:
        bot_token: Override bot token.
        chat_id: Override chat ID.
        enabled: Force enable/disable.

    Returns:
        True if alerts are active and wired, False if credentials missing.
    """
    bridge = get_ics_telegram_bridge(
        bot_token=bot_token,
        chat_id=chat_id,
        enabled=enabled,
    )
    if bridge.is_enabled and bridge.is_wired:
        _log.info("[ICS_TG] ICS → Telegram alerts ACTIVE")
        return True
    _log.info("[ICS_TG] ICS → Telegram alerts NOT ACTIVE (credentials not set)")
    return False


__all__ = [
    "ICSTelegramBridge",
    "get_ics_telegram_bridge",
    "reset_ics_telegram_bridge",
    "wire_ics_telegram_alerts",
]
