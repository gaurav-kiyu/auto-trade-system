"""Tests for the Real Estate Notification Engine."""

from __future__ import annotations

from realestate.notifications import (
    NotificationCategory,
    NotificationEngine,
    NotificationPriority,
)


class TestNotificationEngine:
    def setup_method(self):
        self.engine = NotificationEngine()

    def test_create_notification(self):
        """Basic notification creation."""
        notif = self.engine.notify(
            user_id="user-1",
            category=NotificationCategory.ENQUIRY,
            title="New Enquiry",
            message="Someone is interested",
        )
        assert notif.notification_id is not None
        assert notif.user_id == "user-1"
        assert notif.category == NotificationCategory.ENQUIRY
        assert notif.title == "New Enquiry"
        assert not notif.is_read

    def test_notification_to_dict(self):
        """Notification serialization."""
        notif = self.engine.notify(
            user_id="user-1",
            category=NotificationCategory.PRICE_DROP,
            title="Price Drop",
            message="Price reduced by 10%",
            priority=NotificationPriority.HIGH,
            action_url="/properties/prop-1",
            related_id="prop-1",
        )
        d = notif.to_dict()
        assert d["category"] == "price_drop"
        assert d["priority"] == "high"
        assert d["action_url"] == "/properties/prop-1"
        assert d["related_id"] == "prop-1"
        assert "time_ago" in d

    def test_unread_count(self):
        """Unread count tracking."""
        self.engine.notify("user-1", NotificationCategory.ENQUIRY, "E1", "Msg")
        self.engine.notify("user-1", NotificationCategory.LEAD_UPDATE, "L1", "Msg")
        assert self.engine.get_unread_count("user-1") == 2
        assert self.engine.get_unread_count("user-2") == 0

    def test_mark_read(self):
        """Mark single notification as read."""
        n = self.engine.notify("user-1", NotificationCategory.SYSTEM, "S1", "Msg")
        assert self.engine.get_unread_count("user-1") == 1
        assert self.engine.mark_read(n.notification_id)
        assert self.engine.get_unread_count("user-1") == 0

    def test_mark_nonexistent_read(self):
        """Marking non-existent notification returns False."""
        assert not self.engine.mark_read("nonexistent")

    def test_mark_all_read(self):
        """Mark all notifications as read for a user."""
        self.engine.notify("user-1", NotificationCategory.ENQUIRY, "E1", "M")
        self.engine.notify("user-1", NotificationCategory.PRICE_DROP, "P1", "M")
        self.engine.notify("user-1", NotificationCategory.SYSTEM, "S1", "M")
        self.engine.notify("user-2", NotificationCategory.LEAD_UPDATE, "L1", "M")
        assert self.engine.mark_all_read("user-1") == 3
        assert self.engine.get_unread_count("user-1") == 0
        assert self.engine.get_unread_count("user-2") == 1  # Other user unaffected

    def test_get_notifications_ordered(self):
        """Notifications are returned newest first."""
        self.engine.notify("user-1", NotificationCategory.ENQUIRY, "First", "M")
        self.engine.notify("user-1", NotificationCategory.LEAD_UPDATE, "Second", "M")
        n = self.engine.notify("user-1", NotificationCategory.SYSTEM, "Third", "M")
        self.engine.mark_read(n.notification_id)

        all_notifs = self.engine.get_notifications("user-1")
        assert len(all_notifs) == 3
        assert all_notifs[0].title == "Third"  # Newest first

        unread = self.engine.get_notifications("user-1", unread_only=True)
        assert len(unread) == 2

    def test_get_notifications_limit(self):
        """Respects limit parameter."""
        for i in range(10):
            self.engine.notify("user-1", NotificationCategory.SYSTEM, f"N{i}", "M")
        assert len(self.engine.get_notifications("user-1", limit=3)) == 3

    def test_delete_notification(self):
        """Delete a notification."""
        n = self.engine.notify("user-1", NotificationCategory.SYSTEM, "Del", "M")
        assert self.engine.delete_notification(n.notification_id)
        assert self.engine.get_unread_count("user-1") == 0

    def test_delete_nonexistent(self):
        """Deleting non-existent notification returns False."""
        assert not self.engine.delete_notification("nonexistent")

    # ── Convenience Methods ──

    def test_notify_enquiry(self):
        """Enquiry notification for property owner."""
        n = self.engine.notify_enquiry("owner-1", "Beautiful Flat", "Raj", "prop-1")
        assert n.category == NotificationCategory.ENQUIRY
        assert n.priority == NotificationPriority.HIGH
        assert "Raj" in n.message
        assert "Beautiful Flat" in n.message
        assert n.related_id == "prop-1"

    def test_notify_price_drop(self):
        """Price drop notification."""
        n = self.engine.notify_price_drop("user-1", "Luxury Villa", 10000000, 8500000, "prop-2")
        assert n.category == NotificationCategory.PRICE_DROP
        assert n.priority == NotificationPriority.HIGH
        assert "15" in n.message  # (10M - 8.5M)/10M = 15%
        assert n.related_id == "prop-2"

    def test_notify_auction_outbid(self):
        """Outbid notification."""
        n = self.engine.notify_auction_outbid("bidder-1", "Penthouse", 2500000, "auc-1")
        assert n.category == NotificationCategory.AUCTION_OUTBID
        assert n.priority == NotificationPriority.HIGH
        assert "Outbid" in n.title
        assert "Penthouse" in n.message

    def test_notify_auction_won(self):
        """Auction won notification."""
        n = self.engine.notify_auction_won("bidder-1", "Sea View Apartment", 35000000, "auc-2")
        assert n.category == NotificationCategory.AUCTION_WON
        assert n.priority == NotificationPriority.CRITICAL
        assert "Congratulations" in n.message

    def test_notify_lead_update(self):
        """Lead status update for broker."""
        n = self.engine.notify_lead_update("broker-1", "Amit Sharma", "converted", "lead-1")
        assert n.category == NotificationCategory.LEAD_UPDATE
        assert "Amit Sharma" in n.message
        assert "converted" in n.message

    def test_notify_agreement_signed(self):
        """Agreement signed notification."""
        n = self.engine.notify_agreement_signed("user-1", "Lake View Flat", "ag-1")
        assert n.category == NotificationCategory.AGREEMENT_SIGNED
        assert n.priority == NotificationPriority.HIGH
        assert "e-signed" in n.message

    # ── Saved Searches ──

    def test_save_search(self):
        """Save a search query."""
        entry = self.engine.save_search("user-1", {"city": "Bangalore", "max_price": 10000000, "bedrooms": 3})
        assert "search_id" in entry
        assert entry["criteria"]["city"] == "Bangalore"

    def test_get_saved_searches(self):
        """Retrieve saved searches for a user."""
        self.engine.save_search("user-1", {"city": "Mumbai"})
        self.engine.save_search("user-1", {"city": "Pune", "max_price": 5000000})
        searches = self.engine.get_saved_searches("user-1")
        assert len(searches) == 2
        assert searches[0]["criteria"]["city"] == "Mumbai"

    def test_check_saved_searches_no_service(self):
        """check_saved_searches returns empty list without property_service."""
        self.engine.save_search("user-1", {"city": "Bangalore"})
        result = self.engine.check_saved_searches(None)
        assert result == []

    # ── Stats ──

    def test_stats_empty(self):
        """Stats for empty engine."""
        stats = self.engine.get_stats()
        assert stats["total_notifications"] == 0
        assert stats["unread"] == 0
        assert stats["users_with_notifications"] == 0

    def test_stats_with_data(self):
        """Stats with notifications."""
        self.engine.notify("u1", NotificationCategory.ENQUIRY, "E1", "M")
        self.engine.notify("u1", NotificationCategory.PRICE_DROP, "P1", "M")
        self.engine.notify("u2", NotificationCategory.LEAD_UPDATE, "L1", "M")
        stats = self.engine.get_stats()
        assert stats["total_notifications"] == 3
        assert stats["unread"] == 3
        assert stats["users_with_notifications"] == 2

    def test_stats_by_category(self):
        """Stats broken down by category."""
        self.engine.notify("u1", NotificationCategory.ENQUIRY, "E1", "M")
        self.engine.notify("u1", NotificationCategory.PRICE_DROP, "P1", "M")
        self.engine.notify("u1", NotificationCategory.AUCTION_WON, "A1", "M")
        stats = self.engine.get_stats()
        assert stats["by_category"]["enquiry"] == 1
        assert stats["by_category"]["price_drop"] == 1
        assert stats["by_category"]["auction_won"] == 1

    def test_singleton_pattern(self):
        """get_notification_engine returns the same instance."""
        from realestate.notifications import get_notification_engine
        e1 = get_notification_engine()
        e2 = get_notification_engine()
        assert e1 is e2
