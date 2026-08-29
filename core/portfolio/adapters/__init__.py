"""Multi-Asset Portfolio Adapters - Portfolio aggregation across all asset classes.

These adapters aggregate positions across equity, F&O, commodity, currency,
fixed income, and mutual funds into a unified portfolio view.

Usage:
    from core.portfolio.adapters import (
        MultiAssetPortfolioAggregator,
        AssetClassExposure,
    )
"""
from core.portfolio.adapters.multi_asset_aggregator import (
    AssetClassExposure,
    CapitalAllocationService,
    MultiAssetPortfolioAggregator,
)

__all__ = [
    "AssetClassExposure",
    "CapitalAllocationService",
    "MultiAssetPortfolioAggregator",
]
