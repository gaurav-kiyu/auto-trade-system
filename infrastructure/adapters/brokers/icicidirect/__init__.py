"""
ICICI Direct Broker Adapter Package.

Provides a ``BrokerPort`` implementation for ICICI Securities' Breeze API.
"""

from __future__ import annotations

from infrastructure.adapters.brokers.icicidirect.adapter import (
    ICICIDirectBrokerAdapter,
    create_icicidirect_adapter,
    create_icicidirect_adapter_from_context,
)

__all__ = [
    "ICICIDirectBrokerAdapter",
    "create_icicidirect_adapter",
    "create_icicidirect_adapter_from_context",
]
