"""Webhook System — External integration event notifications for the real estate platform.

Allows external services to subscribe to real-time events:
  - property.created, property.updated, property.price_changed
  - enquiry.created
  - lead.status_changed
  - auction.outbid, auction.won, auction.started
  - agreement.signed
  - payment.completed

Features:
  - Per-event-type webhook registration
  - HMAC-SHA256 signature for payload verification
  - Retry with exponential backoff (up to 3 attempts)
  - Delivery logging and stats
  - Payload validation
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from urllib.request import Request as URLRequest
from urllib.request import urlopen

_log = logging.getLogger(__name__)


# ── Enums ───────────────────────────────────────────────────────────────────

class WebhookEvent(Enum):
    PROPERTY_CREATED = "property.created"
    PROPERTY_UPDATED = "property.updated"
    PROPERTY_PRICE_CHANGED = "property.price_changed"
    ENQUIRY_CREATED = "enquiry.created"
    LEAD_STATUS_CHANGED = "lead.status_changed"
    AUCTION_OUTBID = "auction.outbid"
    AUCTION_WON = "auction.won"
    AUCTION_STARTED = "auction.started"
    AGREEMENT_SIGNED = "agreement.signed"
    PAYMENT_COMPLETED = "payment.completed"


# ── Data Models ─────────────────────────────────────────────────────────────

@dataclass
class WebhookEndpoint:
    """A registered webhook endpoint that receives event notifications."""
    endpoint_id: str = ""
    url: str = ""
    secret: str = ""
    events: list[str] = field(default_factory=list)  # event type strings
    description: str = ""
    is_active: bool = True
    created_at: float = 0.0
    headers: dict[str, str] = field(default_factory=lambda: {"Content-Type": "application/json"})

    def to_dict(self) -> dict[str, Any]:
        return {
            "endpoint_id": self.endpoint_id,
            "url": self.url,
            "events": self.events,
            "description": self.description,
            "is_active": self.is_active,
            "created_at": self.created_at,
        }


@dataclass
class WebhookDelivery:
    """Record of a webhook delivery attempt."""
    delivery_id: str = ""
    endpoint_id: str = ""
    event_type: str = ""
    payload_size: int = 0
    status_code: int = 0
    success: bool = False
    attempt: int = 0
    error: str = ""
    duration_ms: float = 0.0
    delivered_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "delivery_id": self.delivery_id,
            "endpoint_id": self.endpoint_id,
            "event_type": self.event_type,
            "status_code": self.status_code,
            "success": self.success,
            "attempt": self.attempt,
            "duration_ms": round(self.duration_ms, 1),
            "delivered_at": self.delivered_at,
        }


# ── Webhook Engine ──────────────────────────────────────────────────────────

class WebhookEngine:
    """Manages webhook endpoints and dispatches events to registered subscribers."""

    def __init__(self) -> None:
        self._endpoints: dict[str, WebhookEndpoint] = {}  # endpoint_id → endpoint
        self._deliveries: list[WebhookDelivery] = []
        self._max_retries = 3
        self._timeout_seconds = 10

    # ── Registration ──────────────────────────────────────────────────────

    def register_endpoint(
        self,
        url: str,
        events: list[str],
        secret: str = "",
        description: str = "",
        headers: dict[str, str] | None = None,
    ) -> WebhookEndpoint:
        """Register a new webhook endpoint.

        Args:
            url: HTTPS URL to receive webhook POST requests.
            events: List of event types to subscribe to (e.g., ["property.created"]).
            secret: Secret key for HMAC signature (auto-generated if empty).
            description: Human-readable description.
            headers: Optional custom headers to include in requests.

        Returns:
            The registered WebhookEndpoint.
        """
        endpoint = WebhookEndpoint(
            endpoint_id=f"WH-{uuid.uuid4().hex[:12]}",
            url=url,
            secret=secret or uuid.uuid4().hex,
            events=[e.value if isinstance(e, WebhookEvent) else e for e in events],
            description=description,
            created_at=time.time(),
        )
        if headers:
            endpoint.headers.update(headers)

        self._endpoints[endpoint.endpoint_id] = endpoint
        _log.info("[WEBHOOK] Registered endpoint %s → %s (%d events)",
                  endpoint.endpoint_id, url, len(endpoint.events))
        return endpoint

    def unregister_endpoint(self, endpoint_id: str) -> bool:
        """Remove a webhook endpoint."""
        if endpoint_id not in self._endpoints:
            return False
        del self._endpoints[endpoint_id]
        _log.info("[WEBHOOK] Unregistered endpoint %s", endpoint_id)
        return True

    def get_endpoint(self, endpoint_id: str) -> WebhookEndpoint | None:
        return self._endpoints.get(endpoint_id)

    def list_endpoints(self) -> list[WebhookEndpoint]:
        return list(self._endpoints.values())

    # ── Event Dispatch ────────────────────────────────────────────────────

    def dispatch(self, event_type: str, payload: dict[str, Any]) -> list[WebhookDelivery]:
        """Dispatch an event to all registered webhook endpoints.

        Args:
            event_type: The event type string (e.g., "property.created").
            payload: The event payload dict (will be JSON-serialized).

        Returns:
            List of delivery results.
        """
        deliveries: list[WebhookDelivery] = []
        event_val = event_type.value if isinstance(event_type, WebhookEvent) else event_type

        # Find matching endpoints
        matching = [
            ep for ep in self._endpoints.values()
            if ep.is_active and event_val in ep.events
        ]

        if not matching:
            _log.debug("[WEBHOOK] No subscribers for event: %s", event_val)
            return deliveries

        # Build payload
        body = json.dumps({
            "event": event_val,
            "timestamp": time.time(),
            "data": payload,
        }, default=str)

        # Dispatch to each endpoint (with retries)
        for endpoint in matching:
            delivery = self._deliver_to_endpoint(endpoint, event_val, body)
            deliveries.append(delivery)
            self._deliveries.append(delivery)

        return deliveries

    def _deliver_to_endpoint(
        self, endpoint: WebhookEndpoint, event_type: str, body: str,
    ) -> WebhookDelivery:
        """Deliver a webhook payload to a single endpoint with retries."""
        last_error = ""
        last_status = 0

        for attempt in range(1, self._max_retries + 1):
            start = time.time()
            try:
                signature = self._compute_signature(body, endpoint.secret)

                req_headers = dict(endpoint.headers)
                req_headers["X-Webhook-Signature"] = signature
                req_headers["X-Webhook-Event"] = event_type
                req_headers["X-Webhook-Delivery"] = f"del-{uuid.uuid4().hex[:8]}"
                req_headers["User-Agent"] = "RealEstateWebhook/1.0"

                req = URLRequest(
                    endpoint.url,
                    data=body.encode("utf-8"),
                    headers=req_headers,
                    method="POST",
                )

                with urlopen(req, timeout=self._timeout_seconds) as resp:
                    status = resp.status
                    elapsed = (time.time() - start) * 1000

                    delivery = WebhookDelivery(
                        delivery_id=f"DEL-{uuid.uuid4().hex[:10]}",
                        endpoint_id=endpoint.endpoint_id,
                        event_type=event_type,
                        payload_size=len(body),
                        status_code=status,
                        success=200 <= status < 300,
                        attempt=attempt,
                        duration_ms=elapsed,
                        delivered_at=time.time(),
                    )
                    if delivery.success:
                        _log.debug("[WEBHOOK] Delivered %s to %s (attempt %d, %dms)",
                                   event_type, endpoint.endpoint_id, attempt, elapsed)
                        return delivery
                    last_error = f"HTTP {status}"
                    last_status = status

            except Exception as exc:
                elapsed = (time.time() - start) * 1000
                last_error = str(exc)[:200]
                _log.warning("[WEBHOOK] Delivery failed %s → %s (attempt %d/%d): %s",
                             event_type, endpoint.endpoint_id, attempt, self._max_retries, last_error)

                if attempt < self._max_retries:
                    # Exponential backoff: 2^attempt seconds
                    backoff = 2 ** attempt
                    _log.debug("[WEBHOOK] Backing off %ds before retry", backoff)
                    time.sleep(backoff)

        # All attempts failed
        return WebhookDelivery(
            delivery_id=f"DEL-{uuid.uuid4().hex[:10]}",
            endpoint_id=endpoint.endpoint_id,
            event_type=event_type,
            payload_size=len(body),
            status_code=last_status,
            success=False,
            attempt=self._max_retries,
            error=last_error,
            delivered_at=time.time(),
        )

    # ── Stats & History ───────────────────────────────────────────────────

    def get_delivery_history(self, limit: int = 50) -> list[WebhookDelivery]:
        """Get recent webhook deliveries, newest first."""
        sorted_deliveries = sorted(self._deliveries, key=lambda d: d.delivered_at, reverse=True)
        return sorted_deliveries[:limit]

    def get_failed_deliveries(self, limit: int = 20) -> list[WebhookDelivery]:
        """Get failed deliveries."""
        failed = [d for d in self._deliveries if not d.success]
        failed.sort(key=lambda d: d.delivered_at, reverse=True)
        return failed[:limit]

    def get_stats(self) -> dict[str, Any]:
        """Get webhook engine statistics."""
        total = len(self._deliveries)
        success = sum(1 for d in self._deliveries if d.success)
        failed = total - success

        event_counts: dict[str, int] = {}
        for d in self._deliveries:
            event_counts[d.event_type] = event_counts.get(d.event_type, 0) + 1

        return {
            "total_endpoints": len(self._endpoints),
            "active_endpoints": sum(1 for e in self._endpoints.values() if e.is_active),
            "total_deliveries": total,
            "successful_deliveries": success,
            "failed_deliveries": failed,
            "success_rate": round(success / max(total, 1) * 100, 1),
            "by_event": event_counts,
        }

    @staticmethod
    def _compute_signature(payload: str, secret: str) -> str:
        """Compute HMAC-SHA256 signature for webhook payload verification."""
        return hmac.new(
            secret.encode(),
            payload.encode(),
            hashlib.sha256,
        ).hexdigest()

    @staticmethod
    def verify_signature(payload: str, secret: str, signature: str) -> bool:
        """Verify a webhook payload signature (for receiver-side verification)."""
        expected = WebhookEngine._compute_signature(payload, secret)
        return hmac.compare_digest(expected, signature)


# ── Singleton ───────────────────────────────────────────────────────────────

_webhook_engine_instance: WebhookEngine | None = None


def get_webhook_engine() -> WebhookEngine:
    global _webhook_engine_instance
    if _webhook_engine_instance is None:
        _webhook_engine_instance = WebhookEngine()
    return _webhook_engine_instance


# ── API Router ──────────────────────────────────────────────────────────────

def create_webhook_router(engine: WebhookEngine | None = None) -> Any:
    """Create FastAPI router for webhook management endpoints."""
    from fastapi import APIRouter, HTTPException, Query

    eng = engine or get_webhook_engine()
    router = APIRouter(prefix="/api/realestate/webhooks", tags=["Real Estate Webhooks"])

    @router.post("/register")
    async def register_webhook(
        url: str = Query(..., description="HTTPS endpoint URL"),
        events: str = Query(..., description="Comma-separated event types"),
        description: str = Query(""),
    ):
        """Register a new webhook endpoint."""
        event_list = [e.strip() for e in events.split(",") if e.strip()]
        endpoint = eng.register_endpoint(url, event_list, description=description)
        return {"success": True, "endpoint": endpoint.to_dict(), "secret": endpoint.secret}

    @router.delete("/{endpoint_id}")
    async def unregister_webhook(endpoint_id: str):
        """Remove a webhook endpoint."""
        if not eng.unregister_endpoint(endpoint_id):
            raise HTTPException(status_code=404, detail="Endpoint not found")
        return {"success": True}

    @router.get("/endpoints")
    async def list_endpoints():
        """List all registered webhook endpoints."""
        return {"endpoints": [ep.to_dict() for ep in eng.list_endpoints()]}

    @router.post("/test/{event_type}")
    async def test_dispatch(
        event_type: str,
        payload: str = Query("{}", description="JSON payload to test with"),
    ):
        """Test-dispatch an event to all matching endpoints."""
        import json
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            data = {"test": True}
        deliveries = eng.dispatch(event_type, data)
        return {
            "success": True,
            "event": event_type,
            "deliveries": [d.to_dict() for d in deliveries],
            "matched_endpoints": len(deliveries),
        }

    @router.get("/deliveries")
    async def delivery_history(limit: int = Query(50, ge=1, le=200)):
        """Get recent webhook deliveries."""
        deliveries = eng.get_delivery_history(limit)
        return {"deliveries": [d.to_dict() for d in deliveries]}

    @router.get("/deliveries/failed")
    async def failed_deliveries(limit: int = Query(20, ge=1, le=100)):
        """Get failed webhook deliveries."""
        deliveries = eng.get_failed_deliveries(limit)
        return {"deliveries": [d.to_dict() for d in deliveries]}

    @router.get("/stats")
    async def webhook_stats():
        """Get webhook engine statistics."""
        return eng.get_stats()

    return router
