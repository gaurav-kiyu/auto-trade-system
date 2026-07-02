"""Infrastructure layer - adapters, config, security, and persistence implementations.

This package contains concrete implementations of the port interfaces defined
in ``core/ports/``.  The infrastructure layer is the outermost ring of the
hexagonal (ports & adapters) architecture - it depends on ``core`` but
``core`` never depends on ``infrastructure`` directly (resolved via DI).
"""

from __future__ import annotations

# Re-export adapters so consumers can do ``from infrastructure import NseEquityAdapter``
from .adapters.market_data.commodity.mcx_commodity_adapter import McxCommodityAdapter
from .adapters.market_data.currency.cds_currency_adapter import CdsCurrencyAdapter
from .adapters.market_data.equity.nse_equity_adapter import NseEquityAdapter
