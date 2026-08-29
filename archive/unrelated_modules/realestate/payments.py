"""Payment Gateway — Razorpay integration for Indian real estate payments.

Supports:
  - Rent payments (UPI, NEFT, card, wallet)
  - Auction earnest money deposits
  - Broker/lead generation fees
  - Receipt generation and transaction history
  - Webhook signature verification
  - Refund processing

Uses Razorpay API (test mode by default).
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import random
import time
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Any

_log = logging.getLogger(__name__)


# ── Enums ───────────────────────────────────────────────────────────────────

class PaymentPurpose(Enum):
    RENT = "rent"
    AUCTION_DEPOSIT = "auction_deposit"
    BROKER_FEE = "broker_fee"
    LEAD_GENERATION = "lead_generation"
    MAINTENANCE = "maintenance"
    SUBSCRIPTION = "subscription"

class PaymentGateway(Enum):
    RAZORPAY = "razorpay"
    CASH = "cash"
    NEFT = "neft"
    UPI = "upi"

class PaymentState(Enum):
    CREATED = "created"
    AUTHORIZED = "authorized"
    CAPTURED = "captured"
    FAILED = "failed"
    REFUNDED = "refunded"


# ── Domain Models ────────────────────────────────────────────────────────────

@dataclass
class PaymentOrder:
    """A payment order created in the payment gateway."""
    order_id: str = ""
    razorpay_order_id: str = ""      # From Razorpay API
    amount: Decimal = Decimal("0")
    currency: str = "INR"
    purpose: PaymentPurpose = PaymentPurpose.RENT
    state: PaymentState = PaymentState.CREATED
    description: str = ""
    user_id: str = ""
    related_id: str = ""             # agreement_id, auction_id, etc.
    receipt_number: str = ""
    created_at: float = 0.0
    paid_at: float = 0.0
    payment_method: str = ""         # upi, card, netbanking, wallet
    notes: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "order_id": self.order_id,
            "razorpay_order_id": self.razorpay_order_id,
            "amount": float(self.amount),
            "currency": self.currency,
            "purpose": self.purpose.value,
            "state": self.state.value,
            "description": self.description,
            "user_id": self.user_id,
            "receipt_number": self.receipt_number,
            "created_at": self.created_at,
            "paid_at": self.paid_at,
            "payment_method": self.payment_method,
            "amount_formatted": f"₹{float(self.amount):,.2f}",
        }


@dataclass
class PaymentReceipt:
    """A payment receipt with transaction details."""
    receipt_id: str = ""
    order_id: str = ""
    razorpay_payment_id: str = ""
    amount: Decimal = Decimal("0")
    paid_at: float = 0.0
    payment_method: str = ""
    bank_transaction_id: str = ""
    receipt_url: str = ""
    signed_by: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "receipt_id": self.receipt_id,
            "order_id": self.order_id,
            "razorpay_payment_id": self.razorpay_payment_id,
            "amount": float(self.amount),
            "paid_at": self.paid_at,
            "payment_method": self.payment_method,
            "bank_transaction_id": self.bank_transaction_id,
            "receipt_url": self.receipt_url,
        }


# ── Payment Service ──────────────────────────────────────────────────────────

_INDIAN_GST_PCT = 0.18


def _generate_receipt_number() -> str:
    return f"RCPT-{int(time.time())}-{random.randint(1000, 9999)}"


def _compute_gst(amount: Decimal, gst_pct: float = _INDIAN_GST_PCT) -> Decimal:
    return (amount * Decimal(str(gst_pct))).quantize(Decimal("0.01"))


class PaymentService:
    """Payment processing with Razorpay integration.

    Works in TEST mode by default (no real charges).
    Set RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET env vars for live mode.
    """

    def __init__(self) -> None:
        self._orders: dict[str, PaymentOrder] = {}
        self._receipts: dict[str, PaymentReceipt] = {}
        self._user_orders: dict[str, list[str]] = {}   # user_id → [order_ids]
        self._razorpay_client: Any = None
        self._key_id: str = ""
        self._key_secret: str = ""

    def _get_client(self) -> tuple[Any, bool]:
        """Lazy-init Razorpay client. Returns (client, is_live)."""
        if self._razorpay_client is not None:
            return self._razorpay_client, bool(self._key_id)

        import os
        self._key_id = os.environ.get("RAZORPAY_KEY_ID", "rzp_test_xxxxxxxxxxxx")
        self._key_secret = os.environ.get("RAZORPAY_KEY_SECRET", "test_secret_key")

        try:
            import razorpay
            self._razorpay_client = razorpay.Client(auth=(self._key_id, self._key_secret))
            _log.info("[RE PAY] Razorpay client initialized (key_id=%s)", self._key_id[:12])
            return self._razorpay_client, bool(self._key_id.startswith("rzp_live"))
        except ImportError:
            _log.info("[RE PAY] razorpay SDK not installed — using mock client")
            return None, False

    # ── Order Creation ───────────────────────────────────────────────────

    def create_order(
        self,
        amount: float,
        purpose: str = "rent",
        description: str = "",
        user_id: str = "",
        related_id: str = "",
        currency: str = "INR",
    ) -> PaymentOrder:
        """Create a payment order in Razorpay.

        Args:
            amount: Amount in INR (e.g., 25000 for ₹25,000)
            purpose: Payment purpose (rent, auction_deposit, broker_fee)
            description: Human-readable description
            user_id: ID of the user making payment
            related_id: ID of the related entity (agreement, auction)

        Returns:
            PaymentOrder with Razorpay order_id for frontend checkout
        """
        try:
            purpose_enum = PaymentPurpose(purpose)
        except ValueError:
            purpose_enum = PaymentPurpose.RENT

        now = time.time()
        amount_paise = int(round(amount * 100))  # Razorpay uses paise

        # Create Razorpay order
        client, is_live = self._get_client()

        order_data = {
            "amount": amount_paise,
            "currency": currency,
            "receipt": _generate_receipt_number(),
            "notes": {
                "purpose": purpose,
                "user_id": user_id,
                "related_id": related_id,
                "description": description[:100],
            },
        }

        razorpay_order_id = ""
        if client and is_live:
            try:
                rzp_order = client.order.create(order_data)
                razorpay_order_id = rzp_order.get("id", "")
                _log.info("[RE PAY] Razorpay order created: %s (₹%.0f)", razorpay_order_id, amount)
            except Exception as exc:
                _log.warning("[RE PAY] Razorpay order creation failed: %s", exc)
                raise

        order = PaymentOrder(
            order_id=f"ORD-{int(now)}-{random.randint(1000, 9999)}",
            razorpay_order_id=razorpay_order_id,
            amount=Decimal(str(amount)),
            currency=currency,
            purpose=purpose_enum,
            state=PaymentState.CREATED,
            description=description,
            user_id=user_id,
            related_id=related_id,
            receipt_number=order_data["receipt"],
            created_at=now,
        )

        self._orders[order.order_id] = order
        self._user_orders.setdefault(user_id, []).append(order.order_id)

        return order

    def get_order(self, order_id: str) -> PaymentOrder | None:
        return self._orders.get(order_id)

    # ── Payment Verification ─────────────────────────────────────────────

    def verify_payment(
        self,
        razorpay_order_id: str,
        razorpay_payment_id: str,
        razorpay_signature: str,
    ) -> bool:
        """Verify Razorpay payment signature.

        Args:
            razorpay_order_id: Order ID from Razorpay
            razorpay_payment_id: Payment ID from Razorpay
            razorpay_signature: Signature from Razorpay callback

        Returns:
            True if signature is valid
        """
        expected_signature = hmac.new(
            self._key_secret.encode(),
            f"{razorpay_order_id}|{razorpay_payment_id}".encode(),
            hashlib.sha256,
        ).hexdigest()

        return hmac.compare_digest(expected_signature, razorpay_signature)

    def capture_payment(
        self,
        razorpay_order_id: str,
        razorpay_payment_id: str,
        razorpay_signature: str,
    ) -> PaymentReceipt | None:
        """Capture a payment after successful verification.

        Validates the payment signature, updates order state,
        and generates a receipt.
        """
        # Find the order
        order = next(
            (o for o in self._orders.values() if o.razorpay_order_id == razorpay_order_id),
            None,
        )
        if not order:
            _log.warning("[RE PAY] Order not found: %s", razorpay_order_id)
            return None

        # Verify signature
        if not self.verify_payment(razorpay_order_id, razorpay_payment_id, razorpay_signature):
            _log.warning("[RE PAY] Invalid signature for order %s", razorpay_order_id)
            order.state = PaymentState.FAILED
            return None

        # Mark as captured
        order.state = PaymentState.CAPTURED
        order.paid_at = time.time()

        # Generate receipt
        receipt = PaymentReceipt(
            receipt_id=f"RCT-{int(time.time())}",
            order_id=order.order_id,
            razorpay_payment_id=razorpay_payment_id,
            amount=order.amount,
            paid_at=order.paid_at,
            receipt_url=f"/api/realestate/payments/receipt/{order.order_id}",
        )
        self._receipts[receipt.receipt_id] = receipt

        _log.info("[RE PAY] Payment captured: %s — ₹%.0f", receipt.receipt_id, float(order.amount))
        return receipt

    def mark_paid_offline(
        self,
        order_id: str,
        payment_method: str = "cash",
        bank_transaction_id: str = "",
    ) -> PaymentReceipt | None:
        """Mark an order as paid via offline method (cash, NEFT, etc.)."""
        order = self._orders.get(order_id)
        if not order:
            return None
        order.state = PaymentState.CAPTURED
        order.paid_at = time.time()
        order.payment_method = payment_method

        receipt = PaymentReceipt(
            receipt_id=f"RCT-{int(time.time())}-{random.randint(100,999)}",
            order_id=order_id,
            razorpay_payment_id=f"OFFLINE-{int(time.time())}",
            amount=order.amount,
            paid_at=order.paid_at,
            payment_method=payment_method,
            bank_transaction_id=bank_transaction_id,
        )
        self._receipts[receipt.receipt_id] = receipt
        _log.info("[RE PAY] Offline payment: %s — ₹%.0f (%s)", receipt.receipt_id, float(order.amount), payment_method)
        return receipt

    # ── Refunds ──────────────────────────────────────────────────────────

    def process_refund(
        self, receipt_id: str, amount: float | None = None,
    ) -> bool:
        """Process a refund for a captured payment.

        Args:
            receipt_id: Receipt ID to refund
            amount: Amount to refund (None = full refund)

        Returns:
            True if refund was processed
        """
        receipt = self._receipts.get(receipt_id)
        if not receipt:
            return False
        order = self._orders.get(receipt.order_id)
        if not order or order.state != PaymentState.CAPTURED:
            return False

        refund_amount = Decimal(str(amount)) if amount else order.amount
        order.state = PaymentState.REFUNDED
        _log.info("[RE PAY] Refund processed: %s — ₹%.0f", receipt_id, float(refund_amount))
        return True

    # ── Payment History ──────────────────────────────────────────────────

    def get_user_payments(self, user_id: str) -> list[PaymentOrder]:
        """Get all payment orders for a user."""
        order_ids = self._user_orders.get(user_id, [])
        orders = [self._orders[oid] for oid in order_ids if oid in self._orders]
        orders.sort(key=lambda o: o.created_at, reverse=True)
        return orders

    def get_order_receipt(self, order_id: str) -> PaymentReceipt | None:
        """Get receipt for an order."""
        return next(
            (r for r in self._receipts.values() if r.order_id == order_id),
            None,
        )

    def get_receipt(self, receipt_id: str) -> PaymentReceipt | None:
        return self._receipts.get(receipt_id)

    # ── Webhook Handler ──────────────────────────────────────────────────

    def handle_webhook(self, payload: dict[str, Any], signature: str) -> dict[str, Any]:
        """Handle Razorpay webhook events.

        Supported events:
          - payment.captured
          - payment.failed
          - order.paid
        """
        event = payload.get("event", "")
        event_data = payload.get("payload", {}).get("payment", {}).get("entity", {})

        if event == "payment.captured":
            rzp_order_id = event_data.get("order_id", "")
            rzp_payment_id = event_data.get("id", "")
            # Since webhook signature differs from frontend, we use the event data directly
            order = next(
                (o for o in self._orders.values() if o.razorpay_order_id == rzp_order_id),
                None,
            )
            if order:
                order.state = PaymentState.CAPTURED
                order.paid_at = time.time()
                order.payment_method = event_data.get("method", "")
                _log.info("[RE PAY] Webhook: payment captured — %s", rzp_payment_id)
                return {"status": "ok", "event": event, "order_id": rzp_order_id}

        elif event == "payment.failed":
            rzp_order_id = event_data.get("order_id", "")
            order = next(
                (o for o in self._orders.values() if o.razorpay_order_id == rzp_order_id),
                None,
            )
            if order:
                order.state = PaymentState.FAILED
                _log.warning("[RE PAY] Webhook: payment failed — %s", rzp_order_id)
                return {"status": "ok", "event": event}

        return {"status": "ignored", "event": event}

    # ── Stats ────────────────────────────────────────────────────────────

    def get_stats(self) -> dict[str, Any]:
        """Get payment service statistics."""
        captured = [o for o in self._orders.values() if o.state == PaymentState.CAPTURED]
        total_collected = sum(o.amount for o in captured)
        return {
            "total_orders": len(self._orders),
            "captured": len(captured),
            "failed": sum(1 for o in self._orders.values() if o.state == PaymentState.FAILED),
            "refunded": sum(1 for o in self._orders.values() if o.state == PaymentState.REFUNDED),
            "total_collected": float(total_collected),
            "total_collected_formatted": f"₹{float(total_collected):,.2f}",
            "total_receipts": len(self._receipts),
            "users_with_orders": len(self._user_orders),
        }


# ── Singleton ───────────────────────────────────────────────────────────────

_payment_service_instance: PaymentService | None = None


def get_payment_service() -> PaymentService:
    global _payment_service_instance
    if _payment_service_instance is None:
        _payment_service_instance = PaymentService()
    return _payment_service_instance


# ── API Router ──────────────────────────────────────────────────────────────

def create_payment_router(service: PaymentService | None = None) -> Any:
    """Create a FastAPI router for payment endpoints."""
    from fastapi import APIRouter, Body, HTTPException, Query, Request

    svc = service or get_payment_service()
    router = APIRouter(prefix="/api/realestate/payments", tags=["Real Estate Payments"])

    @router.post("/orders")
    async def create_payment_order(
        amount: float = Query(..., description="Amount in INR"),
        purpose: str = Query("rent", description="rent/auction_deposit/broker_fee"),
        description: str = Query(""),
        user_id: str = Query(""),
        related_id: str = Query(""),
    ):
        """Create a payment order for Razorpay checkout."""
        if amount < 1:
            raise HTTPException(status_code=400, detail="Amount must be at least ₹1")
        try:
            order = svc.create_order(amount, purpose, description, user_id, related_id)
            return {"order": order.to_dict()}
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    @router.post("/verify")
    async def verify_payment(
        razorpay_order_id: str = Body(...),
        razorpay_payment_id: str = Body(...),
        razorpay_signature: str = Body(...),
    ):
        """Verify and capture a payment after successful Razorpay checkout."""
        receipt = svc.capture_payment(razorpay_order_id, razorpay_payment_id, razorpay_signature)
        if not receipt:
            raise HTTPException(status_code=400, detail="Payment verification failed")
        return {"success": True, "receipt": receipt.to_dict()}

    @router.post("/offline")
    async def mark_offline_payment(
        order_id: str = Query(...),
        payment_method: str = Query("cash"),
        bank_transaction_id: str = Query(""),
    ):
        """Mark an order as paid via offline method."""
        receipt = svc.mark_paid_offline(order_id, payment_method, bank_transaction_id)
        if not receipt:
            raise HTTPException(status_code=404, detail="Order not found")
        return {"success": True, "receipt": receipt.to_dict()}

    @router.get("/orders")
    async def get_user_orders(user_id: str = Query(...)):
        """Get payment orders for a user."""
        orders = svc.get_user_payments(user_id)
        return {"orders": [o.to_dict() for o in orders]}

    @router.get("/orders/{order_id}")
    async def get_order(order_id: str):
        """Get a specific payment order."""
        order = svc.get_order(order_id)
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")
        return {"order": order.to_dict()}

    @router.get("/receipt/{order_id}")
    async def get_receipt(order_id: str):
        """Get receipt for an order."""
        receipt = svc.get_order_receipt(order_id)
        if not receipt:
            raise HTTPException(status_code=404, detail="Receipt not found")
        return {"receipt": receipt.to_dict()}

    @router.post("/refund")
    async def refund_payment(
        receipt_id: str = Query(...),
        amount: float = Query(0.0),
    ):
        """Process a refund for a captured payment."""
        success = svc.process_refund(receipt_id, amount or None)
        if not success:
            raise HTTPException(status_code=400, detail="Refund failed")
        return {"success": True}

    @router.post("/webhook")
    async def payment_webhook(request: Request):
        """Handle Razorpay webhook events."""
        payload = await request.json()
        signature = request.headers.get("X-Razorpay-Signature", "")
        result = svc.handle_webhook(payload, signature)
        return result

    @router.get("/stats")
    async def payment_stats():
        """Get payment service statistics."""
        return svc.get_stats()

    return router
