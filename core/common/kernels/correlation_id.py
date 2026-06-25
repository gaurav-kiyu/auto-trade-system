"""
Correlation ID Kernel

This module provides correlation ID generation and management for tracing
requests through the system.
"""

from __future__ import annotations

import threading
import uuid
from contextvars import ContextVar

# Context variable for storing correlation ID
correlation_id_context: ContextVar[str | None] = ContextVar('correlation_id', default=None)

# Thread-local storage for backward compatibility
_local = threading.local()


class CorrelationIdManager:
    """
    Manages correlation IDs for request tracing.

    Provides methods to generate, set, get, and clear correlation IDs
    using both context variables (preferred) and thread-local storage
    (for backward compatibility).
    """

    def generate_id(self) -> str:
        """
        Generate a new unique correlation ID.

        Returns:
            A unique string ID (UUID4)
        """
        return str(uuid.uuid4())

    def set_id(self, correlation_id: str) -> None:
        """
        Set the correlation ID in the current context.

        Args:
            correlation_id: The correlation ID to set
        """
        correlation_id_context.set(correlation_id)
        # Also set in thread-local for backward compatibility
        _local.correlation_id = correlation_id

    def get_id(self) -> str | None:
        """
        Get the current correlation ID.

        Returns:
            The current correlation ID, or None if not set
        """
        # Try context variable first (preferred)
        cid = correlation_id_context.get()
        if cid is not None:
            return cid

        # Fall back to thread-local storage
        return getattr(_local, 'correlation_id', None)

    def clear_id(self) -> None:
        """Clear the correlation ID from the current context."""
        correlation_id_context.set(None)
        # Also clear from thread-local storage
        if hasattr(_local, 'correlation_id'):
            delattr(_local, 'correlation_id')

    def has_id(self) -> bool:
        """
        Check if a correlation ID is currently set.

        Returns:
            True if a correlation ID is set, False otherwise
        """
        return self.get_id() is not None


# Global instance for convenience
correlation_id_manager = CorrelationIdManager()


def generate_correlation_id() -> str:
    """
    Generate a new correlation ID (convenience function).

    Returns:
        A new unique correlation ID
    """
    return correlation_id_manager.generate_id()


def set_correlation_id(correlation_id: str) -> None:
    """
    Set the correlation ID in the current context (convenience function).

    Args:
        correlation_id: The correlation ID to set
    """
    correlation_id_manager.set_id(correlation_id)


def get_correlation_id() -> str | None:
    """
    Get the current correlation ID (convenience function).

    Returns:
        The current correlation ID, or None if not set
    """
    return correlation_id_manager.get_id()


def clear_correlation_id() -> None:
    """Clear the correlation ID from the current context (convenience function)."""
    correlation_id_manager.clear_id()


def with_correlation_id(correlation_id: str):
    """
    Decorator/context manager to temporarily set a correlation ID.

    Args:
        correlation_id: The correlation ID to set for the duration

    Returns:
        Context manager that restores the previous correlation ID on exit
    """
    class CorrelationIdContext:
        def __enter__(self):
            self.previous_id = get_correlation_id()
            set_correlation_id(correlation_id)
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            if self.previous_id is not None:
                set_correlation_id(self.previous_id)
            else:
                clear_correlation_id()

    return CorrelationIdContext()


__all__ = [
    "CorrelationIdManager",
    "clear_correlation_id",
    "correlation_id_context",
    "correlation_id_manager",
    "generate_correlation_id",
    "get_correlation_id",
    "set_correlation_id",
    "with_correlation_id",
]

