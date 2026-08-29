"""Infrastructure adapters - concrete implementations of port interfaces.

Each sub-package in this directory implements one or more ``core.ports.*``
interfaces and is wired into the application via ``core.di_container``.
"""

from __future__ import annotations

import logging

_log = logging.getLogger(__name__)


# ── Market data adapters (lazy-loaded via factory) ──────────────────────────

try:
    from infrastructure.adapters.market_data.equity.nse_equity_adapter import (
        NseEquityAdapter,
    )
except ImportError:
    NseEquityAdapter = None  # type: ignore[assignment]

try:
    from infrastructure.adapters.market_data.commodity.mcx_commodity_adapter import (
        McxCommodityAdapter,
    )
except ImportError:
    McxCommodityAdapter = None  # type: ignore[assignment]

try:
    from infrastructure.adapters.market_data.currency.cds_currency_adapter import (
        CdsCurrencyAdapter,
    )
except ImportError:
    CdsCurrencyAdapter = None  # type: ignore[assignment]


__all__ = [
    "NseEquityAdapter",
    "McxCommodityAdapter",
    "CdsCurrencyAdapter",
]
