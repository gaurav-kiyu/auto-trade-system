"""
DEPRECATED — Legacy stock option buying monolith.

This file was the original ~3890-line monolithic stock-trading script.
It has been retained for reference only and is NOT used by the current
index-options trading platform.

The current entry point is ``index_app/index_trader.py`` for index options.
Stock trading functionality has been split into:
  - ``core/`` modules for signal generation, risk, execution
  - ``infrastructure/adapters/`` for broker, data, and persistence

This module will be removed in v3.0.
"""
from __future__ import annotations

import sys
import warnings

warnings.warn(
    "STOCK_OPTION_BUYING_APP_1.0 is deprecated and no longer maintained. "
    "Use the index trading platform via index_app/index_trader.py instead.",
    DeprecationWarning,
    stacklevel=2,
)

if __name__ == "__main__":
    print("=" * 60)
    print("  STOCK_OPTION_BUYING_APP_1.0 is DEPRECATED.")
    print("  Use index_app/index_trader.py for the current trading platform.")
    print("=" * 60)
    sys.exit(0)
