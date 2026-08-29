"""Signal Action Functions — extracted from ``index_trader.py`` (DEBT-008).

Contains small utility functions for signal quality checks, config fail-safe,
trade entry dispatch, and WebSocket tick handling.

Each function takes its dependencies as explicit parameters rather than
relying on module-level globals.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

__all__ = [
    "notify_config_failure",
    "on_ws_tick",
    "set_config_fail_safe",
    "telegram_action_body",
    "telegram_action_quality",
]

_log = logging.getLogger(__name__)


def set_config_fail_safe(
    make_fail_safe_config_fn: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    """Build and return a fail-safe config dict for MANUAL mode.

    Called when config loading fails — forces the system into safe mode.

    Args:
        make_fail_safe_config_fn: Factory that returns a safe config dict.

    Returns:
        The fail-safe config dict.
    """
    return make_fail_safe_config_fn()


def notify_config_failure(
    detail: str,
    send_fn: Callable[..., None],
    log_fn: Callable[..., None] = _log.warning,
) -> None:
    """Send a critical Telegram alert about config failure.

    Args:
        detail: Error description.
        send_fn: Notification dispatch function.
        log_fn: Logger function for fallback on failure.
    """
    try:
        send_fn(f"[CONFIG_CRITICAL] {detail}. Force MANUAL mode.", critical=True)
    except (ValueError, TypeError, KeyError, AttributeError, IndexError, OSError):
        log_fn("Failed to send config failure notification")


def telegram_action_quality(sig: dict[str, Any]) -> tuple[bool, str]:
    """Check signal quality for Telegram manual signal dispatch.

    Args:
        sig: Signal dict with at least a ``breakout_ok`` key.

    Returns:
        ``(True, "ok")`` if signal quality is acceptable,
        ``(False, reason)`` if blocked.
    """
    breakout_ok = sig.get("breakout_ok", True)
    if not breakout_ok:
        return False, "breakout_ok false"
    return True, "ok"


def telegram_action_body(
    learning_state: dict[str, Any],
    name: str = "",
) -> str:
    """Build the Telegram message body for a manual signal.

    Args:
        learning_state: Module-level learning state dict.
        name: Optional index name for context.

    Returns:
        Formatted message string.
    """
    confidence = learning_state.get("confidence", 0)
    label = f" [{name}]" if name else ""
    return f"[MANUAL SIGNAL]{label} Conf={confidence} Learner"


def on_ws_tick(
    msg: dict[str, Any],
    log_fn: Callable[..., None] = _log.info,
    debug_fn: Callable[..., None] = _log.debug,
) -> None:
    """Callback for KiteTickerFeedManager tick messages.

    Args:
        msg: Tick message dict.
        log_fn: Logger for info-level messages.
        debug_fn: Logger for debug-level messages.
    """
    if not isinstance(msg, dict):
        return
    msg_type = msg.get("type", "")
    if msg_type == "connect":
        log_fn("[WS] KiteTicker feed connected")
    elif msg_type == "ticks":
        ticks = msg.get("data", [])
        if ticks:
            first = ticks[0]
            token = first.get("instrument_token", "?")
            price = first.get("last_price", "?")
            debug_fn("[WS] tick: token=%s price=%s", token, price)
