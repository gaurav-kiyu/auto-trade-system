"""
Correlation ID Adapter

Adapter that implements the CorrelationIdPort interface using threading.local.
"""

from __future__ import annotations

import threading
from typing import Optional

# Import the port interface
from core.ports.correlation_id import CorrelationIdPort


class CorrelationIdAdapter(CorrelationIdPort):
    """
    Adapter that implements CorrelationIdPort using threading.local.

    This follows the Dependency Inversion Principle - high-level modules (trading logic)
    depend on abstractions (CorrelationIdPort), not concretions (specific correlation ID implementation).
    """

    def __init__(self):
        """Initialize the correlation ID adapter."""
        self._local = threading.local()

    def get_correlation_id(self) -> str:
        """Get the current correlation ID."""
        return getattr(self._local, 'correlation_id', '')

    def set_correlation_id(self, correlation_id: str) -> None:
        """Set the correlation ID for the current context."""
        self._local.correlation_id = correlation_id

    def new_correlation_id(self) -> str:
        """Generate a new correlation ID.

        Returns:
            A new correlation ID (using UUID4 for uniqueness).
        """
        import uuid
        correlation_id = str(uuid.uuid4())
        self.set_correlation_id(correlation_id)
        return correlation_id

    def reset(self) -> None:
        """Reset the correlation ID to None/empty."""
        if hasattr(self._local, 'correlation_id'):
            del self._local.correlation_id