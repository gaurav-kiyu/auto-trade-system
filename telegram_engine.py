"""Backward-compatible shim for telegram_engine.

This module has been moved to core/legacy/telegram_engine.py.
This shim re-exports all public symbols for backward compatibility.

WARNING: This module is deprecated. Use core.alert_router or
infrastructure.adapters.notifications.telegram_adapter instead.
"""

import warnings

warnings.warn(
    "telegram_engine.py is deprecated - use core.alert_router or "
    "infrastructure.adapters.notifications.telegram_adapter instead.",
    DeprecationWarning,
    stacklevel=2,
)

# Re-export all public symbols from the new location
from core.legacy.telegram_engine import TelegramEngine  # noqa: F401, E402

# Note: SmartTelegramAlertEngine was never defined in the original telegram_engine.py
# The reference in infrastructure/adapters/notifications/telegram_adapter.py is dead code
