"""
Telegram Command Auditor.

Records all incoming commands and their outcomes for security and compliance.
"""

from __future__ import annotations

import logging
from core.datetime_ist import now_ist

_log = logging.getLogger("tg_audit")

class TelegramAuditManager:
    def __init__(self, log_file: str = "logs/telegram_audit.log"):
        self.log_file = log_file
        # In a real implementation, this would write to a secure DB or file
        self._setup_audit_logger()

    def _setup_audit_logger(self):
        # Simple logger for demonstration; would be a dedicated audit log in production
        pass

    def record_command(self, user_id: str, username: str, command: str, args: list[str], result: str):
        """Log a command execution event."""
        timestamp = now_ist().isoformat()
        audit_entry = (
            f"[{timestamp}] USER:{user_id} NAME:{username} "
            f"CMD:{command} ARGS:{args} RESULT:{result}"
        )
        _log.info(f"AUDIT: {audit_entry}")
        # Append to file
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(audit_entry + "\n")

    def record_unauthorized_attempt(self, user_id: str, username: str, command: str):
        """Log an unauthorized access attempt."""
        timestamp = now_ist().isoformat()
        entry = f"[{timestamp}] UNAUTHORIZED ATTEMPT: USER:{user_id} NAME:{username} CMD:{command}"
        _log.warning(f"SECURITY: {entry}")
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(entry + "\n")
