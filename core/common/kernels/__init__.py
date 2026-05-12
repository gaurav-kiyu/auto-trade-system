"""
Shared Kernels

This package contains shared domain objects, value objects, and entities
that are used across multiple modules in the trading platform.
"""

from __future__ import annotations

# Import models to make them available at the package level
from .models import (
    Fill,
    Order,
    OrderResult,
    Position,
    Quote,
    Signal,
)

__all__ = [
    "Order",
    "OrderResult",
    "Position",
    "Quote",
    "Fill",
    "Signal",
]
