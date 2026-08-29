"""
IIFL Broker Adapter Package.

Provides a ``BrokerPort`` implementation for IIFL Markets' XTS Interactive
Trading API.
"""

from __future__ import annotations

from infrastructure.adapters.brokers.iifl.adapter import (
    IIFLBrokerAdapter,
    create_iifl_adapter,
    create_iifl_adapter_from_context,
)

__all__ = [
    "IIFLBrokerAdapter",
    "create_iifl_adapter",
    "create_iifl_adapter_from_context",
]
