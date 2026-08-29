"""Notification engine — real-time alerts for the real estate platform.

Supports:
  - New enquiry alerts (property owner/broker)
  - Price drop alerts (saved properties)
  - Auction outbid/won notifications
  - Lead status changes (broker CRM)
  - Rent agreement milestone alerts
  - Builder project milestone updates
"""

from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any

_log = logging.getLogger(__name__)


# ── Enums ───────────────────────────────────────────────────────────────────

class NotificationPriority(Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class NotificationCategory(Enum):
    ENQUIRY = "enquiry"                  # New enquiry on a property
    LEAD_UPDATE = "lead_update"          # Lead status changed
    PRICE_DROP = "price_drop"            # Price was reduced
    AUCTION_OUTBID = "auction_outbid"    # Outbid in auction
    AUCTION_WON = "auction_won"          # Won an auction
    AUCTION_STARTING = "auction_starting" # Auction about to start
    AGREEMENT_SIGNED = "agreement_signed" # Rent agreement signed
    PROJECT_UPDATE = "project_update"    # Builder project milestone
    PROPERTY_MATCH = "property_match"    # New property matching saved search
    SYSTEM = "system"                    # General system notification


# ── Domain Models ────────────────────────────────────────────────────────────

@dataclass
class Notification:
    """A single notification with metadata."""
    notification_id: str = ""
    user_id: str = ""
    category: NotificationCategory = NotificationCategory.SYSTEM
    priority: NotificationPriority = NotificationPriority.NORMAL
    title: str = ""
    message: str = ""
    action_url: str = ""           # Deep link to relevant page
    related_id: str = ""           # Property ID, lead ID, etc.
    is_read: bool = False
    created_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "notification_id": self.notification_id,
            "user_id": self.user_id,
            "category": self.category.value,
            "priority": self.priority.value,
            "title": self.title,
            "message": self.message,
            "action_url": self.action_url,
            "related_id": self.related_id,
            "is_read": self.is_read,
            "created_at": self.created_at,
            "time_ago": _time_ago(self.created_at),
        }


def _time_ago(ts: float) -> str:
    """Human-readable relative time."""
    secs = time.time() - ts
    if secs < 60:
        return "Just now"
    mins = int(secs / 60)
    if mins < 60:
        return f"{mins}m ago"
    hours = int(mins / 60)
    if hours < 24:
        return f"{hours}h ago"
    days = int(hours / 24)
    if days < 30:
        return f"{days}d ago"
    return f"{int(days/30)}mo ago"


# ── Notification Engine ─────────────────────────────────────────────────────

class NotificationEngine:
    """Central notification engine — create, store, query, and manage alerts."""

    def __init__(self) -> None:
        self._notifications: dict[str, Notification] = {}  # user_id → sorted list
        self._user_notifications: dict[str, list[str]] = {}  # user_id → [notif_ids]
        self._saved_searches: dict[str, list[dict[str, Any]]] = {}  # user_id → saved search criteria

    # ── Create Notifications ──────────────────────────────────────────────

    def notify(
        self,
        user_id: str,
        category: NotificationCategory,
        title: str,
        message: str,
        priority: NotificationPriority = NotificationPriority.NORMAL,
        action_url: str = "",
        related_id: str = "",
    ) -> Notification:
        """Create and store a notification for a user."""
        now = time.time()
        notif = Notification(
            notification_id=f"NOTIF-{int(now*1000)}-{random.randint(100,999)}",
            user_id=user_id,
            category=category,
            priority=priority,
            title=title,
            message=message,
            action_url=action_url,
            related_id=related_id,
            created_at=now,
        )
        self._notifications[notif.notification_id] = notif
        self._user_notifications.setdefault(user_id, []).append(notif.notification_id)
        _log.debug("[RE NOTIF] %s → %s: %s", category.value, user_id, title)
        return notif

    # ── Convenience Methods ───────────────────────────────────────────────

    def notify_enquiry(self, owner_id: str, property_title: str, enquirer_name: str, property_id: str) -> Notification:
        """Alert property owner about a new enquiry."""
        return self.notify(
            user_id=owner_id,
            category=NotificationCategory.ENQUIRY,
            priority=NotificationPriority.HIGH,
            title="New Enquiry Received",
            message=f"{enquirer_name} is interested in \"{property_title}\"",
            action_url=f"/realestate/property/{property_id}",
            related_id=property_id,
        )

    def notify_price_drop(self, user_id: str, property_title: str, old_price: float, new_price: float, property_id: str) -> Notification:
        """Alert a user about a price drop on a saved/leaded property."""
        drop_pct = round((old_price - new_price) / old_price * 100, 1)
        return self.notify(
            user_id=user_id,
            category=NotificationCategory.PRICE_DROP,
            priority=NotificationPriority.HIGH,
            title="Price Dropped! 🏷️",
            message=f"\"{property_title}\" dropped by {drop_pct}% — ₹{new_price:,.0f}",
            action_url=f"/realestate/property/{property_id}",
            related_id=property_id,
        )

    def notify_auction_outbid(self, user_id: str, property_title: str, new_bid: float, auction_id: str) -> Notification:
        """Alert a bidder that they've been outbid."""
        return self.notify(
            user_id=user_id,
            category=NotificationCategory.AUCTION_OUTBID,
            priority=NotificationPriority.HIGH,
            title="You've Been Outbid! ⚡",
            message=f"Someone placed a higher bid on \"{property_title}\" — ₹{new_bid:,.0f}",
            action_url=f"/api/realestate/auctions/{auction_id}",
            related_id=auction_id,
        )

    def notify_auction_won(self, user_id: str, property_title: str, price: float, auction_id: str) -> Notification:
        """Alert a bidder that they won the auction."""
        return self.notify(
            user_id=user_id,
            category=NotificationCategory.AUCTION_WON,
            priority=NotificationPriority.CRITICAL,
            title="🎉 Auction Won!",
            message=f"Congratulations! You won \"{property_title}\" at ₹{price:,.0f}",
            action_url=f"/api/realestate/auctions/{auction_id}",
            related_id=auction_id,
        )

    def notify_lead_update(self, broker_id: str, lead_name: str, new_status: str, lead_id: str) -> Notification:
        """Alert broker about lead status change."""
        return self.notify(
            user_id=broker_id,
            category=NotificationCategory.LEAD_UPDATE,
            priority=NotificationPriority.NORMAL,
            title="Lead Status Updated",
            message=f"Lead {lead_name} moved to \"{new_status}\"",
            action_url="/realestate/leads",
            related_id=lead_id,
        )

    def notify_agreement_signed(self, user_id: str, property_title: str, agreement_id: str) -> Notification:
        """Alert about rent agreement e-sign completion."""
        return self.notify(
            user_id=user_id,
            category=NotificationCategory.AGREEMENT_SIGNED,
            priority=NotificationPriority.HIGH,
            title="Agreement Signed ✅",
            message=f"Rent agreement for \"{property_title}\" has been e-signed",
            action_url=f"/api/realestate/agreements/rent/{agreement_id}",
            related_id=agreement_id,
        )

    # ── Query ─────────────────────────────────────────────────────────────

    def get_notifications(
        self, user_id: str, unread_only: bool = False, limit: int = 50
    ) -> list[Notification]:
        """Get notifications for a user, newest first."""
        notif_ids = self._user_notifications.get(user_id, [])
        notifs = [self._notifications[nid] for nid in notif_ids if nid in self._notifications]
        if unread_only:
            notifs = [n for n in notifs if not n.is_read]
        notifs.sort(key=lambda n: n.created_at, reverse=True)
        return notifs[:limit]

    def get_unread_count(self, user_id: str) -> int:
        """Get count of unread notifications for a user."""
        return sum(1 for n in self.get_notifications(user_id, unread_only=True))

    def mark_read(self, notification_id: str) -> bool:
        """Mark a single notification as read."""
        notif = self._notifications.get(notification_id)
        if not notif:
            return False
        notif.is_read = True
        return True

    def mark_all_read(self, user_id: str) -> int:
        """Mark all notifications as read for a user. Returns count marked."""
        count = 0
        for nid in self._user_notifications.get(user_id, []):
            notif = self._notifications.get(nid)
            if notif and not notif.is_read:
                notif.is_read = True
                count += 1
        return count

    def delete_notification(self, notification_id: str) -> bool:
        """Delete a notification."""
        notif = self._notifications.pop(notification_id, None)
        if not notif:
            return False
        user_notifs = self._user_notifications.get(notif.user_id, [])
        if notification_id in user_notifs:
            user_notifs.remove(notification_id)
        return True

    # ── Saved Search Alerts ───────────────────────────────────────────────

    def save_search(self, user_id: str, search_criteria: dict[str, Any]) -> dict[str, Any]:
        """Save a search query for a user to enable property-match alerts."""
        search_id = f"SS-{int(time.time())}-{random.randint(100,999)}"
        entry = {
            "search_id": search_id,
            "criteria": search_criteria,
            "created_at": time.time(),
        }
        self._saved_searches.setdefault(user_id, []).append(entry)
        return entry

    def get_saved_searches(self, user_id: str) -> list[dict[str, Any]]:
        return self._saved_searches.get(user_id, [])

    def check_saved_searches(
        self, property_service: Any, enquirer_id: str | None = None
    ) -> list[Notification]:
        """Check saved searches against new / updated properties and generate alerts.

        Args:
            property_service: Service to query property data.
            enquirer_id: If set, only check saved searches for this user.

        Returns:
            List of generated notifications.
        """
        generated: list[Notification] = []
        users_to_check = [enquirer_id] if enquirer_id else list(self._saved_searches.keys())

        if not property_service:
            return generated

        try:
            all_props = property_service.list_all()
        except Exception:
            return generated

        for user_id in users_to_check:
            searches = self._saved_searches.get(user_id, [])
            for search_entry in searches:
                criteria = search_entry.get("criteria", {})
                matches = _match_criteria(all_props, criteria)
                if matches:
                    for prop in matches[:3]:  # Limit to avoid spam
                        notif = self.notify(
                            user_id=user_id,
                            category=NotificationCategory.PROPERTY_MATCH,
                            priority=NotificationPriority.NORMAL,
                            title="New Property Match 🔍",
                            message=f"\"{prop.title}\" in {prop.city} matches your saved search",
                            action_url=f"/realestate/property/{prop.property_id}",
                            related_id=prop.property_id,
                        )
                        generated.append(notif)
        return generated

    # ── Stats ─────────────────────────────────────────────────────────────

    def get_stats(self) -> dict[str, Any]:
        """Get notification engine statistics."""
        total = len(self._notifications)
        unread = sum(1 for n in self._notifications.values() if not n.is_read)
        return {
            "total_notifications": total,
            "unread": unread,
            "users_with_notifications": len(self._user_notifications),
            "saved_searches": sum(len(ss) for ss in self._saved_searches.values()),
            "by_category": {
                cat.value: sum(1 for n in self._notifications.values() if n.category.value == cat.value)
                for cat in NotificationCategory
            },
        }


def _match_criteria(properties: list[Any], criteria: dict[str, Any]) -> list[Any]:
    """Match a list of properties against saved search criteria."""
    matches: list[Any] = []
    for prop in properties:
        city = criteria.get("city", "")
        if city and city.lower() != prop.city.lower():
            continue
        max_price = criteria.get("max_price", 0)
        if max_price and prop.price > max_price:
            continue
        min_price = criteria.get("min_price", 0)
        if min_price and prop.price < min_price:
            continue
        bedrooms = criteria.get("bedrooms", 0)
        if bedrooms and prop.bedrooms < bedrooms:
            continue
        property_type = criteria.get("property_type", "")
        if property_type and prop.property_type != property_type:
            continue
        matches.append(prop)
    return matches


# ── Notification Router ─────────────────────────────────────────────────────

_notification_engine_instance: NotificationEngine | None = None


def get_notification_engine() -> NotificationEngine:
    """Get or create the singleton notification engine."""
    global _notification_engine_instance
    if _notification_engine_instance is None:
        _notification_engine_instance = NotificationEngine()
    return _notification_engine_instance


def create_notification_router(
    engine: NotificationEngine | None = None,
) -> Any:
    """Create a FastAPI router for notification endpoints."""
    from fastapi import APIRouter, Query

    eng = engine or get_notification_engine()
    router = APIRouter(prefix="/api/realestate/notifications", tags=["Real Estate Notifications"])

    @router.get("")
    async def get_notifications(
        user_id: str = Query(...),
        unread_only: bool = Query(False),
        limit: int = Query(50, ge=1, le=200),
    ):
        """Get notifications for a user."""
        notifs = eng.get_notifications(user_id, unread_only=unread_only, limit=limit)
        return {
            "notifications": [n.to_dict() for n in notifs],
            "unread_count": eng.get_unread_count(user_id),
            "total": len(notifs),
        }

    @router.get("/unread-count")
    async def unread_count(user_id: str = Query(...)):
        """Get unread notification count (for badge display)."""
        return {"unread_count": eng.get_unread_count(user_id)}

    @router.post("/{notification_id}/read")
    async def mark_read(notification_id: str):
        """Mark a notification as read."""
        success = eng.mark_read(notification_id)
        return {"success": success}

    @router.post("/mark-all-read")
    async def mark_all_read(user_id: str = Query(...)):
        """Mark all notifications as read for a user."""
        count = eng.mark_all_read(user_id)
        return {"success": True, "count": count}

    @router.delete("/{notification_id}")
    async def delete_notification(notification_id: str):
        """Delete a notification."""
        success = eng.delete_notification(notification_id)
        return {"success": success}

    @router.post("/saved-searches")
    async def save_search(
        user_id: str = Query(...),
        city: str = Query(""),
        min_price: float = Query(0.0),
        max_price: float = Query(0.0),
        bedrooms: int = Query(0),
        property_type: str = Query(""),
    ):
        """Save a search criteria for property-match alerts."""
        criteria = {k: v for k, v in {
            "city": city, "min_price": min_price, "max_price": max_price,
            "bedrooms": bedrooms, "property_type": property_type,
        }.items() if v}
        entry = eng.save_search(user_id, criteria)
        return {"success": True, "search": entry}

    @router.get("/saved-searches")
    async def get_saved_searches(user_id: str = Query(...)):
        """Get saved searches for a user."""
        return {"saved_searches": eng.get_saved_searches(user_id)}

    @router.get("/stats")
    async def notification_stats():
        """Get notification engine statistics."""
        return eng.get_stats()

    return router
