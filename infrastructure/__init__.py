"""Infrastructure layer - adapters, config, security, and persistence implementations.

This package contains concrete implementations of the port interfaces defined
in ``core/ports/``.  The infrastructure layer is the outermost ring of the
hexagonal (ports & adapters) architecture - it depends on ``core`` but
``core`` never depends on ``infrastructure`` directly (resolved via DI).
"""

from __future__ import annotations

# Adapters are imported directly from their subdirectory paths (e.g.,
# ``from infrastructure.adapters.market_data.equity.nse_equity_adapter import NseEquityAdapter``).
# Consumers should import from the concrete subdirectory paths rather than from
# this top-level package to maintain clear dependency chains.
