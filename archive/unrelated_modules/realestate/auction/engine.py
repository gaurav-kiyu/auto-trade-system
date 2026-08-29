"""Auction engine — bidding logic, lifecycle management, anti-sniping.

Supports:
  - Reserved price auctions
  - Bid increment rules
  - Auto-extension (anti-sniping)
  - Buy-it-now option
  - Early bidder advantage scoring
"""

from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Any

_log = logging.getLogger(__name__)


# ── Enums ───────────────────────────────────────────────────────────────────

class AuctionStatus(Enum):
    """Lifecycle states for an auction."""
    SCHEDULED = "scheduled"
    ACTIVE = "active"
    EXTENDED = "extended"
    CLOSED = "closed"
    SOLD = "sold"
    RESERVE_NOT_MET = "reserve_not_met"
    CANCELLED = "cancelled"


# ── Domain Models ────────────────────────────────────────────────────────────

@dataclass
class Bid:
    """A single bid on a property."""
    bid_id: str = ""
    auction_id: str = ""
    bidder_id: str = ""
    bidder_name: str = ""
    amount: Decimal = Decimal("0")
    placed_at: float = 0.0
    is_winning: bool = False
    is_auto_bid: bool = False  # proxy/auto-bid

    def to_dict(self) -> dict[str, Any]:
        return {
            "bid_id": self.bid_id,
            "auction_id": self.auction_id,
            "bidder_id": self.bidder_id,
            "bidder_name": self.bidder_name,
            "amount": float(self.amount),
            "placed_at": self.placed_at,
            "is_winning": self.is_winning,
            "is_auto_bid": self.is_auto_bid,
        }


@dataclass
class Auction:
    """A property auction with lifecycle and bid management."""
    auction_id: str = ""
    property_id: str = ""
    property_title: str = ""
    city: str = ""
    locality: str = ""
    bedrooms: int = 0

    # Pricing
    starting_bid: Decimal = Decimal("0")
    reserve_price: Decimal = Decimal("0")  # Minimum sell price (hidden)
    current_bid: Decimal = Decimal("0")
    buy_it_now_price: Decimal = Decimal("0")  # 0 = not available
    bid_increment: Decimal = Decimal("10000")  # Minimum bid step

    # Winner
    winning_bidder_id: str = ""
    winning_bidder_name: str = ""
    total_bids: int = 0

    # Timing
    status: AuctionStatus = AuctionStatus.SCHEDULED
    starts_at: float = 0.0
    ends_at: float = 0.0
    extended_by_seconds: int = 0
    anti_sniping_seconds: int = 120  # Extend by 2 min if bid in last 2 min

    # Metadata
    seller_id: str = ""
    seller_name: str = ""
    created_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "auction_id": self.auction_id,
            "property_id": self.property_id,
            "property_title": self.property_title,
            "city": self.city,
            "locality": self.locality,
            "bedrooms": self.bedrooms,
            "starting_bid": float(self.starting_bid),
            "reserve_price": float(self.reserve_price),
            "current_bid": float(self.current_bid),
            "buy_it_now_price": float(self.buy_it_now_price),
            "bid_increment": float(self.bid_increment),
            "winning_bidder_id": self.winning_bidder_id,
            "winning_bidder_name": self.winning_bidder_name,
            "total_bids": self.total_bids,
            "status": self.status.value,
            "starts_at": self.starts_at,
            "ends_at": self.ends_at,
            "extended_by_seconds": self.extended_by_seconds,
            "time_remaining_sec": max(0, int(self.ends_at - time.time())) if self.status in (AuctionStatus.ACTIVE, AuctionStatus.EXTENDED) else 0,
            "seller_id": self.seller_id,
            "created_at": self.created_at,
        }

    @property
    def is_active(self) -> bool:
        return self.status in (AuctionStatus.ACTIVE, AuctionStatus.EXTENDED)

    @property
    def is_buy_it_now_available(self) -> bool:
        return self.is_active and self.buy_it_now_price > Decimal("0")


@dataclass
class BidResult:
    """Result of placing a bid."""
    success: bool = False
    bid: Bid | None = None
    auction: Auction | None = None
    message: str = ""
    outbid_user_id: str = ""  # Previous winning bidder who was outbid
    is_new_high_bid: bool = False
    is_buy_it_now: bool = False


# ── Auction Engine ───────────────────────────────────────────────────────────

BID_INCREMENT_TABLE = [
    (Decimal("0"), Decimal("1000")),           # < ₹1L → ₹1K
    (Decimal("100000"), Decimal("2500")),       # ₹1L-5L → ₹2.5K
    (Decimal("500000"), Decimal("5000")),       # ₹5L-10L → ₹5K
    (Decimal("1000000"), Decimal("10000")),     # ₹10L-50L → ₹10K
    (Decimal("5000000"), Decimal("25000")),     # ₹50L-1Cr → ₹25K
    (Decimal("10000000"), Decimal("50000")),    # ₹1Cr-5Cr → ₹50K
    (Decimal("50000000"), Decimal("100000")),   # ₹5Cr+ → ₹1L
]


def get_bid_increment(current_bid: Decimal) -> Decimal:
    """Get the minimum bid increment based on the current bid amount."""
    for threshold, increment in reversed(BID_INCREMENT_TABLE):
        if current_bid >= threshold:
            return increment
    return BID_INCREMENT_TABLE[0][1]


class AuctionEngine:
    """Core auction logic — scheduling, bidding, closing, anti-sniping."""

    def __init__(self) -> None:
        self._auctions: dict[str, Auction] = {}
        self._bids: dict[str, list[Bid]] = {}  # auction_id → bids

    # ── Auction CRUD ──────────────────────────────────────────────────────

    def create_auction(
        self,
        property_id: str,
        property_title: str,
        city: str,
        locality: str,
        bedrooms: int,
        starting_bid: float,
        reserve_price: float = 0.0,
        buy_it_now_price: float = 0.0,
        duration_hours: int = 48,
        seller_id: str = "",
        seller_name: str = "",
    ) -> Auction:
        """Create a new auction for a property."""
        now = time.time()
        auction = Auction(
            auction_id=f"AUC-{int(now)}-{random.randint(1000, 9999)}",
            property_id=property_id,
            property_title=property_title,
            city=city,
            locality=locality,
            bedrooms=bedrooms,
            starting_bid=Decimal(str(starting_bid)),
            reserve_price=Decimal(str(reserve_price)) if reserve_price > 0 else Decimal(str(starting_bid)),
            current_bid=Decimal(str(starting_bid)),
            buy_it_now_price=Decimal(str(buy_it_now_price)) if buy_it_now_price > 0 else Decimal("0"),
            bid_increment=get_bid_increment(Decimal(str(starting_bid))),
            status=AuctionStatus.SCHEDULED,
            starts_at=now,
            ends_at=now + (duration_hours * 3600),
            seller_id=seller_id,
            seller_name=seller_name,
            created_at=now,
        )
        self._auctions[auction.auction_id] = auction
        self._bids[auction.auction_id] = []
        _log.info("[RE] Auction created: %s — %s (starting ₹%.0f)",
                  auction.auction_id, property_title, starting_bid)
        return auction

    def get_auction(self, auction_id: str) -> Auction | None:
        """Get an auction by ID."""
        auction = self._auctions.get(auction_id)
        if auction and auction.is_active:
            self._check_auction_expiry(auction)
        return auction

    def list_auctions(self, status: str | None = None) -> list[Auction]:
        """List auctions, optionally filtered by status."""
        auctions = list(self._auctions.values())
        # Tick active auctions for expiry
        for a in auctions:
            if a.is_active:
                self._check_auction_expiry(a)
        if status:
            try:
                s = AuctionStatus(status)
                auctions = [a for a in auctions if a.status == s]
            except ValueError:
                pass
        auctions.sort(key=lambda a: a.created_at, reverse=True)
        return auctions

    def get_bids_for_auction(self, auction_id: str) -> list[Bid]:
        """Get all bids for an auction (newest/highest first)."""
        bids = list(self._bids.get(auction_id, []))
        bids.sort(key=lambda b: (b.placed_at, b.amount), reverse=True)
        return bids


    # ── Bidding Logic ─────────────────────────────────────────────────────

    def place_bid(
        self,
        auction_id: str,
        bidder_id: str,
        bidder_name: str,
        amount: float,
        is_auto_bid: bool = False,
    ) -> BidResult:
        """Place a bid on an auction. Validates amount, increments, and timing."""
        auction = self._auctions.get(auction_id)
        if not auction:
            return BidResult(success=False, message="Auction not found")

        # Check auction is active
        self._check_auction_expiry(auction)
        if not auction.is_active:
            return BidResult(success=False, message=f"Auction is {auction.status.value}")

        bid_amount = Decimal(str(amount))

        # Validate against current bid
        min_bid = auction.current_bid + auction.bid_increment
        if bid_amount < min_bid:
            return BidResult(
                success=False,
                message=f"Minimum bid is ₹{float(min_bid):,.0f} (current ₹{float(auction.current_bid):,.0f} + increment ₹{float(auction.bid_increment):,.0f})",
            )

        # Check buy it now
        if auction.is_buy_it_now_available and bid_amount >= auction.buy_it_now_price:
            return self._process_buy_it_now(auction, bidder_id, bidder_name, bid_amount)

        # Record the bid
        old_winner_id = auction.winning_bidder_id

        bid = Bid(
            bid_id=f"BID-{int(time.time()*1000)}-{random.randint(100, 999)}",
            auction_id=auction_id,
            bidder_id=bidder_id,
            bidder_name=bidder_name,
            amount=bid_amount,
            placed_at=time.time(),
            is_winning=True,
            is_auto_bid=is_auto_bid,
        )

        # Mark previous winning bid as not winning
        for existing_bid in self._bids.get(auction_id, []):
            if existing_bid.is_winning:
                existing_bid.is_winning = False

        self._bids.setdefault(auction_id, []).append(bid)

        # Update auction state
        auction.current_bid = bid_amount
        auction.winning_bidder_id = bidder_id
        auction.winning_bidder_name = bidder_name
        auction.total_bids += 1
        auction.bid_increment = get_bid_increment(bid_amount)

        # Anti-sniping: extend auction if bid placed in last N seconds
        time_left = auction.ends_at - time.time()
        if 0 < time_left < auction.anti_sniping_seconds:
            auction.ends_at = time.time() + auction.anti_sniping_seconds
            auction.extended_by_seconds += auction.anti_sniping_seconds
            auction.status = AuctionStatus.EXTENDED
            _log.info("[RE] Auction %s extended by %ds (anti-sniping)", auction_id, auction.anti_sniping_seconds)

        return BidResult(
            success=True,
            bid=bid,
            auction=auction,
            message="Bid placed successfully",
            outbid_user_id=old_winner_id if old_winner_id != bidder_id else "",
            is_new_high_bid=True,
        )

    def buy_it_now(self, auction_id: str, buyer_id: str, buyer_name: str) -> BidResult:
        """Purchase a property at the buy-it-now price."""
        auction = self._auctions.get(auction_id)
        if not auction:
            return BidResult(success=False, message="Auction not found")
        if not auction.is_buy_it_now_available:
            return BidResult(success=False, message="Buy it now not available")
        return self._process_buy_it_now(auction, buyer_id, buyer_name, auction.buy_it_now_price)

    def _process_buy_it_now(
        self, auction: Auction, buyer_id: str, buyer_name: str, amount: Decimal
    ) -> BidResult:
        """Process a buy-it-now purchase."""
        auction.status = AuctionStatus.SOLD
        auction.winning_bidder_id = buyer_id
        auction.winning_bidder_name = buyer_name
        auction.current_bid = amount
        auction.ends_at = time.time()

        bid = Bid(
            bid_id=f"BID-{int(time.time()*1000)}-BIN",
            auction_id=auction.auction_id,
            bidder_id=buyer_id,
            bidder_name=buyer_name,
            amount=amount,
            placed_at=time.time(),
            is_winning=True,
        )
        self._bids.setdefault(auction.auction_id, []).append(bid)
        auction.total_bids += 1

        _log.info("[RE] Auction %s — Buy it now by %s for ₹%.0f",
                  auction.auction_id, buyer_name, float(amount))
        return BidResult(
            success=True,
            bid=bid,
            auction=auction,
            message="Property purchased via Buy It Now!",
            is_buy_it_now=True,
        )

    # ── Lifecycle Management ──────────────────────────────────────────────

    def start_auction(self, auction_id: str) -> bool:
        """Manually start a scheduled auction."""
        auction = self._auctions.get(auction_id)
        if not auction or auction.status != AuctionStatus.SCHEDULED:
            return False
        auction.status = AuctionStatus.ACTIVE
        auction.starts_at = time.time()
        _log.info("[RE] Auction %s started", auction_id)
        return True

    def cancel_auction(self, auction_id: str) -> bool:
        """Cancel an auction before it closes."""
        auction = self._auctions.get(auction_id)
        if not auction or auction.status in (AuctionStatus.CLOSED, AuctionStatus.SOLD, AuctionStatus.CANCELLED):
            return False
        auction.status = AuctionStatus.CANCELLED
        _log.info("[RE] Auction %s cancelled", auction_id)
        return True

    def close_auction(self, auction_id: str) -> dict[str, Any]:
        """Force-close an auction and determine the final outcome."""
        auction = self._auctions.get(auction_id)
        if not auction:
            return {"success": False, "message": "Auction not found"}

        if auction.current_bid >= auction.reserve_price and auction.winning_bidder_id:
            auction.status = AuctionStatus.SOLD
            result = {
                "success": True,
                "sold": True,
                "price": float(auction.current_bid),
                "winner_id": auction.winning_bidder_id,
                "winner_name": auction.winning_bidder_name,
                "message": f"Auction closed — Sold to {auction.winning_bidder_name} for ₹{float(auction.current_bid):,.0f}",
            }
        elif auction.winning_bidder_id:
            auction.status = AuctionStatus.RESERVE_NOT_MET
            result = {
                "success": True,
                "sold": False,
                "price": float(auction.current_bid),
                "winner_id": auction.winning_bidder_id,
                "message": "Reserve price not met — highest bidder will be contacted",
            }
        else:
            auction.status = AuctionStatus.CLOSED
            result = {
                "success": True,
                "sold": False,
                "price": 0,
                "message": "Auction closed — No bids placed",
            }

        auction.ends_at = time.time()
        _log.info("[RE] Auction %s closed: %s", auction_id, result["message"])
        return result

    def _check_auction_expiry(self, auction: Auction) -> None:
        """Check if an active auction has expired and auto-close it."""
        if auction.is_active and time.time() >= auction.ends_at:
            self.close_auction(auction.auction_id)

    # ── Stats ─────────────────────────────────────────────────────────────

    def get_stats(self) -> dict[str, Any]:
        """Get auction marketplace statistics."""
        total = len(self._auctions)
        active = sum(1 for a in self._auctions.values() if a.is_active)
        scheduled = sum(1 for a in self._auctions.values() if a.status == AuctionStatus.SCHEDULED)
        sold = sum(1 for a in self._auctions.values() if a.status == AuctionStatus.SOLD)
        closed = sum(1 for a in self._auctions.values() if a.status == AuctionStatus.CLOSED)
        total_volume = sum(float(a.current_bid) for a in self._auctions.values() if a.status == AuctionStatus.SOLD)
        return {
            "total_auctions": total,
            "active": active,
            "scheduled": scheduled,
            "sold": sold,
            "closed": closed,
            "total_sales_volume": total_volume,
            "total_bids_placed": sum(len(bids) for bids in self._bids.values()),
        }


# ── API Router ──────────────────────────────────────────────────────────────

def create_auction_router(engine: AuctionEngine | None = None) -> Any:
    """Create a FastAPI router for auction endpoints."""
    from fastapi import APIRouter, HTTPException, Query

    eng = engine or AuctionEngine()
    router = APIRouter(prefix="/api/realestate/auctions", tags=["Real Estate Auctions"])

    @router.post("")
    async def create_auction(
        property_id: str = Query(...),
        property_title: str = Query(...),
        city: str = Query(...),
        locality: str = Query(""),
        bedrooms: int = Query(0),
        starting_bid: float = Query(...),
        reserve_price: float = Query(0.0),
        buy_it_now_price: float = Query(0.0),
        duration_hours: int = Query(48),
        seller_id: str = Query(""),
        seller_name: str = Query(""),
    ):
        auction = eng.create_auction(
            property_id=property_id, property_title=property_title,
            city=city, locality=locality, bedrooms=bedrooms,
            starting_bid=starting_bid, reserve_price=reserve_price,
            buy_it_now_price=buy_it_now_price, duration_hours=duration_hours,
            seller_id=seller_id, seller_name=seller_name,
        )
        return {"auction": auction.to_dict()}

    @router.get("")
    async def list_auctions(status: str = Query("")):
        auctions = eng.list_auctions(status or None)
        return {"auctions": [a.to_dict() for a in auctions]}

    @router.get("/stats")
    async def auction_stats():
        return eng.get_stats()

    @router.get("/{auction_id}")
    async def get_auction(auction_id: str):
        auction = eng.get_auction(auction_id)
        if not auction:
            raise HTTPException(status_code=404, detail="Auction not found")
        return {"auction": auction.to_dict()}

    @router.get("/{auction_id}/bids")
    async def get_bids(auction_id: str):
        auction = eng.get_auction(auction_id)
        if not auction:
            raise HTTPException(status_code=404, detail="Auction not found")
        bids = eng.get_bids_for_auction(auction_id)
        return {"bids": [b.to_dict() for b in bids]}

    @router.post("/{auction_id}/bid")
    async def place_bid(
        auction_id: str,
        bidder_id: str = Query(...),
        bidder_name: str = Query(...),
        amount: float = Query(...),
    ):
        result = eng.place_bid(auction_id, bidder_id, bidder_name, amount)
        if not result.success:
            raise HTTPException(status_code=400, detail=result.message)
        return {
            "success": True,
            "bid": result.bid.to_dict() if result.bid else None,
            "auction": result.auction.to_dict() if result.auction else None,
            "message": result.message,
        }

    @router.post("/{auction_id}/buy-it-now")
    async def buy_it_now(
        auction_id: str,
        buyer_id: str = Query(...),
        buyer_name: str = Query(...),
    ):
        result = eng.buy_it_now(auction_id, buyer_id, buyer_name)
        if not result.success:
            raise HTTPException(status_code=400, detail=result.message)
        return {"success": True, "auction": result.auction.to_dict(), "message": result.message}

    @router.post("/{auction_id}/start")
    async def start_auction(auction_id: str):
        if not eng.start_auction(auction_id):
            raise HTTPException(status_code=400, detail="Cannot start auction")
        return {"success": True, "auction": eng.get_auction(auction_id).to_dict()}

    @router.post("/{auction_id}/close")
    async def close_auction(auction_id: str):
        result = eng.close_auction(auction_id)
        if not result["success"]:
            raise HTTPException(status_code=404, detail=result["message"])
        return result

    return router
