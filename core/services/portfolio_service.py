import logging
from typing import Any

from core.state_manager import state_manager
from core.time_provider import time_provider

log = logging.getLogger("portfolio_service")

class PortfolioService:
    """
    Domain Service responsible for managing the financial state of the trading session.
    Replaces the legacy 'S' (SessionState) object and associated locks.
    
    Responsibilities:
    - Capital tracking and adjustments.
    - Daily PnL accounting.
    - Session lifecycle (daily resets).
    - Exposure monitoring.
    """

    def __init__(self, config: dict[str, Any]):
        self.config = config
        self._base_capital = float(config.get("BASE_CAPITAL", 100000.0))

    def get_capital(self) -> float:
        """Returns current available capital."""
        return float(state_manager.get("capital", self._base_capital))

    def get_available_margin(self) -> float:
        """Returns available margin (capital minus blocked margin for open positions)."""
        capital = self.get_capital()
        blocked = float(state_manager.get("blocked_margin", 0.0))
        return max(0.0, capital - blocked)

    def block_margin(self, amount: float) -> None:
        """Block margin for a new position."""
        current = float(state_manager.get("blocked_margin", 0.0))
        state_manager.set("blocked_margin", current + amount)

    def release_margin(self, amount: float) -> None:
        """Release margin when a position is closed."""
        current = float(state_manager.get("blocked_margin", 0.0))
        state_manager.set("blocked_margin", max(0.0, current - amount))

    def set_capital(self, value: float):
        """Updates the current capital."""
        state_manager.set("capital", value)

    def get_daily_pnl(self) -> float:
        """Returns the net PnL for the current day."""
        return float(state_manager.get("net_daily_pnl", 0.0))

    def update_daily_pnl(self, amount: float):
        """Increments the daily PnL."""
        current = self.get_daily_pnl()
        state_manager.set("net_daily_pnl", current + amount)

    def get_trade_count(self) -> int:
        """Returns total trades executed today."""
        return int(state_manager.get("trade_count", 0))

    def increment_trade_count(self):
        """Increments the daily trade counter."""
        count = self.get_trade_count()
        state_manager.set("trade_count", count + 1)

    def handle_daily_reset(self) -> bool:
        """
        Performs the EOD to BOD transition.
        Returns True if a reset actually occurred.
        """
        today = time_provider.today()
        last_reset = state_manager.get("last_reset_day")

        if last_reset and last_reset != str(today):
            # Check for zombie PnL before resetting
            adj = state_manager.get("capital_adj_pending", 0.0)
            if adj != 0:
                log.warning(f"ZOMBIE PnL detected during reset: {adj}")
                # We don't block the reset, but we log it for the operator

            state_manager.set("net_daily_pnl", 0.0)
            state_manager.set("trade_count", 0)
            state_manager.set("capital_adj_pending", 0.0)
            state_manager.set("last_reset_day", str(today))
            log.info(f"Daily reset performed for {today}")
            return True

        # Update last_reset_day if it was None (first run)
        if not last_reset:
            state_manager.set("last_reset_day", str(today))

        return False

    def get_pending_adjustment(self) -> float:
        """Returns any capital adjustments pending reconciliation."""
        return float(state_manager.get("capital_adj_pending", 0.0))

    def clear_pending_adjustment(self):
        """Clears the pending adjustment flag."""
        state_manager.set("capital_adj_pending", 0.0)

    def get_session_state(self) -> dict[str, Any]:
        """Returns a snapshot of the current portfolio state."""
        return {
            "capital": self.get_capital(),
            "daily_pnl": self.get_daily_pnl(),
            "trade_count": self.get_trade_count(),
            "last_reset": state_manager.get("last_reset_day"),
            "pending_adj": self.get_pending_adjustment()
        }
