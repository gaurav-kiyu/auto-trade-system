"""Infrastructure layer - adapters, config, security, and persistence implementations.

This package contains concrete implementations of the port interfaces defined
in ``core/ports/``.  The infrastructure layer is the outermost ring of the
hexagonal (ports & adapters) architecture - it depends on ``core`` but
``core`` never depends on ``infrastructure`` directly (resolved via DI).
"""

from __future__ import annotations

# Re-export adapters so consumers can do ``from infrastructure import NseEquityAdapter``
from infrastructure.adapters import (  # noqa: F401
    CdsCurrencyAdapter,
    McxCommodityAdapter,
    NseEquityAdapter,
)
