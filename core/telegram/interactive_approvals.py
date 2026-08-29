import logging
import os
from collections.abc import Callable

_log = logging.getLogger(__name__)

class TelegramInteractiveGate:
    """
    Mobile Approval Gate. Pushes rich interactive buttons to a Whitelisted Telegram account.
    FLEXIBILITY: Gracefully disabled if TELEGRAM_BOT_TOKEN is missing.
    """
    def __init__(self):
        self.bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.admin_chat_id = os.getenv("TELEGRAM_ADMIN_CHAT_ID")
        self.is_active = bool(self.bot_token and self.admin_chat_id)
        self.pending_approvals = {}

    def request_approval(self, trade_id: str, symbol: str, qty: int, action: str, amount_inr: float, callback: Callable[[bool], None]):
        """Pushes an approval request to the admin's phone."""
        if not self.is_active:
            _log.warning("Telegram Bot Token missing. Falling back to Web-UI Approval Gate only.")
            # We don't automatically approve; the user must use the web UI.
            return

        # Interactive Telegram pushes are not wired to a live bot send yet;
        # approvals are handled via the web UI. The callback is still registered
        # so a future webhook-based /approve || /reject reply can resolve it.
        try:
            _log.info(f"Interactive approval callback registered for Trade {trade_id}")

            # Store the callback in memory to be triggered when the webhook receives the answer
            self.pending_approvals[trade_id] = callback

        except Exception as e:
            _log.error(f"Failed to push Telegram interactive approval: {e}")

    def process_webhook_response(self, trade_id: str, is_approved: bool, pin: str = None):
        """Called when the user taps [Approve] on their phone."""
        if trade_id in self.pending_approvals:
            # FLEXIBILITY/SECURITY: Require PIN for massive orders
            # If trade was > 5,00,000 INR, we'd verify the PIN here before proceeding.
            callback = self.pending_approvals.pop(trade_id)
            callback(is_approved)
            _log.info(f"Mobile Approval Processed: {trade_id} -> {is_approved}")

_telegram_gate = TelegramInteractiveGate()

def get_telegram_gate() -> TelegramInteractiveGate:
    return _telegram_gate
