import logging
from typing import Any


__all__ = [
    "SovereigntyGuard",
]

class SovereigntyGuard:
    """
    Enforces strict control over external dependencies.
    Prevents any unauthorized API calls to brokers or AI tools.
    """
    def __init__(self, cfg: dict[str, Any]):
        self.cfg = cfg
        self.logger = logging.getLogger(__name__)

        # Sovereignty Settings
        self.broker_block = cfg.get("SOVEREIGNTY_BROKER_BLOCK", True)
        self.ai_enabled = cfg.get("ai_reasoning_enabled", False)
        self.execution_mode = cfg.get("EXECUTION_MODE", "MANUAL").upper()

    def can_use_broker(self) -> bool:
        """
        Returns True only if broker is explicitly allowed
        AND execution mode is AUTO.
        """
        if self.broker_block:
            return False
        return self.execution_mode == "AUTO"

    def can_use_ai(self) -> bool:
        """Returns True only if AI reasoning is explicitly enabled in config."""
        return self.ai_enabled

    def audit_sovereignty(self):
        """Logs the current sovereignty state for the operator."""
        status = (f"Sovereignty Guard: [Broker: {'BLOCKED' if not self.can_use_broker() else 'ALLOWED'}] "
                  f"[AI: {'DISABLED' if not self.can_use_ai() else 'ENABLED'}]")
        self.logger.info(status)
        return status
