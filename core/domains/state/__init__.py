"""State Domain Models - System and session state management.

Models system-wide state and session state for checkpoint/restore:
  - TradingState: Current system state snapshot
  - SessionState: Per-session state tracking

Usage:
    from core.domains.state import (
        TradingState, SessionState
    )
"""
from core.domains.state.model import (
    SessionState,
    TradingState,
)

__all__ = [
    "SessionState",
    "TradingState",
]
