"""Property Auction Marketplace — bidding system with reserve prices, bid history.

Features:
  - Reserve price auctions (minimum bid threshold)
  - Real-time bid tracking with timestamps
  - Auto-outbid notifications
  - Auction lifecycle: scheduled → active → extended → closed
  - Anti-sniping (auto-extension in final minutes)
  - Buy-it-now option
"""

from __future__ import annotations

from realestate.auction.engine import (
    Auction,
    AuctionEngine,
    AuctionStatus,
    Bid,
    BidResult,
    create_auction_router,
)

__all__ = [
    "Auction", "AuctionEngine", "AuctionStatus", "Bid", "BidResult",
    "create_auction_router",
]
