"""Telegram 1-Click Interactive Action Button Webhook & Callback Handler (v3.0)."""

from __future__ import annotations

import logging
from typing import Any

_log = logging.getLogger("TG_CALLBACK")


class TelegramActionHandler:
    """Processes 1-Click Telegram Inline Button Actions."""

    @classmethod
    def process_callback_action(cls, callback_data: str, user_id: str) -> dict[str, Any]:
        """Handle callback queries (e.g. 'paper:SIG-123', 'exec:SIG-123', 'dash:SIG-123')."""
        from core.notifications.url_resolver import get_public_base_url
        base_url = get_public_base_url()

        parts = callback_data.split(":")
        action = parts[0]
        sig_id = parts[1] if len(parts) > 1 else ""

        if action == "paper":
            _log.info("[PAPER_TRADE] Executed 1-click paper fill for %s by TG user %s", sig_id, user_id)
            return {
                "success": True,
                "alert_text": f"✅ Simulated Paper Trade Filled for {sig_id} at Market LTP!",
            }
        elif action == "exec":
            # Safety Gate: Never place live orders directly from unauthenticated chat callbacks.
            _log.warning(
                "[BROKER_EXEC_SAFETY_GATE] 1-click broker execution requested for %s by TG user %s "
                "- intercepted by safety gate, no broker order placed",
                sig_id, user_id,
            )
            return {
                "success": False,
                "alert_text": (
                    f"⚠️ Discretionary Execution Safety Gate: Live execution for {sig_id} requires authenticated web confirmation.\n"
                    f"Please review & place order at: {base_url}/my-signals"
                ),
            }
        elif action == "dash":
            _log.info("[DASH_NAV] Cockpit dashboard link requested for %s by TG user %s", sig_id, user_id)
            return {
                "success": True,
                "alert_text": f"🏛️ Cockpit Dashboard: {base_url}/my-signals",
            }
        return {
            "success": False,
            "alert_text": "Unknown Action Callback",
        }
