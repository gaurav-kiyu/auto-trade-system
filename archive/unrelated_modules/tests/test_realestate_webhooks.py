"""Tests for the webhook system."""

from __future__ import annotations

from realestate.webhooks import (
    WebhookEngine,
    WebhookEvent,
)


class TestWebhookEngine:
    def setup_method(self):
        self.engine = WebhookEngine()

    def test_register_endpoint(self):
        ep = self.engine.register_endpoint(
            url="https://example.com/webhook",
            events=["property.created", "enquiry.created"],
            description="Test endpoint",
        )
        assert ep.endpoint_id.startswith("WH-")
        assert ep.url == "https://example.com/webhook"
        assert len(ep.events) == 2
        assert len(ep.secret) > 0

    def test_unregister_endpoint(self):
        ep = self.engine.register_endpoint(
            url="https://test.com/hook",
            events=["property.created"],
        )
        assert self.engine.unregister_endpoint(ep.endpoint_id)
        assert not self.engine.unregister_endpoint("nonexistent")

    def test_list_endpoints(self):
        self.engine.register_endpoint(url="https://a.com/h1", events=["e1"])
        self.engine.register_endpoint(url="https://b.com/h2", events=["e2"])
        assert len(self.engine.list_endpoints()) == 2

    def test_dispatch_no_subscribers(self):
        deliveries = self.engine.dispatch("property.created", {"id": "RE-001"})
        assert len(deliveries) == 0

    def test_dispatch_to_endpoint(self):
        """Dispatching with no matching subscribers returns empty."""
        self.engine.register_endpoint(
            url="https://httpbin.org/post",
            events=["property.created"],
        )
        deliveries = self.engine.dispatch("enquiry.created", {"id": "ENQ-001"})
        assert len(deliveries) == 0

    def test_signature_verification(self):
        secret = "test-secret-123"
        payload = '{"event": "test", "data": {"key": "val"}}'
        sig = self.engine._compute_signature(payload, secret)
        assert self.engine.verify_signature(payload, secret, sig)
        assert not self.engine.verify_signature(payload, secret, "wrong-signature")

    def test_get_stats_empty(self):
        stats = self.engine.get_stats()
        assert stats["total_endpoints"] == 0
        assert stats["total_deliveries"] == 0

    def test_get_stats_with_endpoint(self):
        self.engine.register_endpoint(url="https://x.com/h", events=["e1"])
        stats = self.engine.get_stats()
        assert stats["total_endpoints"] == 1
        assert stats["active_endpoints"] == 1

    def test_delivery_history_empty(self):
        assert len(self.engine.get_delivery_history()) == 0

    def test_failed_deliveries_empty(self):
        assert len(self.engine.get_failed_deliveries()) == 0

    def test_get_endpoint(self):
        ep = self.engine.register_endpoint(url="https://x.com/h", events=["e1"])
        assert self.engine.get_endpoint(ep.endpoint_id) is not None
        assert self.engine.get_endpoint("nonexistent") is None

    def test_register_with_webhook_event_enum(self):
        ep = self.engine.register_endpoint(
            url="https://x.com/h",
            events=[WebhookEvent.PROPERTY_CREATED, WebhookEvent.ENQUIRY_CREATED],
        )
        assert "property.created" in ep.events
        assert "enquiry.created" in ep.events


class TestWebhookEvent:
    def test_events_have_values(self):
        assert WebhookEvent.PROPERTY_CREATED.value == "property.created"
        assert WebhookEvent.PROPERTY_UPDATED.value == "property.updated"
        assert WebhookEvent.PAYMENT_COMPLETED.value == "payment.completed"
