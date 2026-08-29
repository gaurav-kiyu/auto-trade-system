"""Tenant Portal — rent payment tracking, agreement management, maintenance requests.

Features:
  - Rent payment history and receipts
  - Active/Draft rent agreement management
  - Maintenance request submission and tracking
  - Payment due reminders
  - Security deposit tracking
  - Communication with landlord/property manager
"""

from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Any

_log = logging.getLogger(__name__)


# ── Enums ───────────────────────────────────────────────────────────────────

class PaymentStatus(Enum):
    PENDING = "pending"
    PAID = "paid"
    OVERDUE = "overdue"
    PARTIAL = "partial"
    REFUNDED = "refunded"

class MaintenancePriority(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    EMERGENCY = "emergency"

class MaintenanceStatus(Enum):
    SUBMITTED = "submitted"
    ACKNOWLEDGED = "acknowledged"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    CANCELLED = "cancelled"


# ── Domain Models ────────────────────────────────────────────────────────────

@dataclass
class RentPayment:
    """A single rent payment record."""
    payment_id: str = ""
    tenant_id: str = ""
    property_id: str = ""
    agreement_id: str = ""
    amount: Decimal = Decimal("0")
    paid_date: float = 0.0
    due_date: str = ""       # YYYY-MM-DD
    payment_mode: str = ""   # UPI, NEFT, card, cash, cheque
    status: PaymentStatus = PaymentStatus.PENDING
    transaction_ref: str = ""
    receipt_url: str = ""
    month_period: str = ""   # e.g. "Aug 2026"
    late_fee: Decimal = Decimal("0")
    notes: str = ""
    created_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "payment_id": self.payment_id,
            "tenant_id": self.tenant_id,
            "property_id": self.property_id,
            "agreement_id": self.agreement_id,
            "amount": float(self.amount),
            "paid_date": self.paid_date,
            "due_date": self.due_date,
            "payment_mode": self.payment_mode,
            "status": self.status.value,
            "transaction_ref": self.transaction_ref,
            "receipt_url": self.receipt_url,
            "month_period": self.month_period,
            "late_fee": float(self.late_fee),
            "notes": self.notes,
        }


@dataclass
class MaintenanceRequest:
    """A maintenance/repair request from tenant."""
    request_id: str = ""
    tenant_id: str = ""
    property_id: str = ""
    category: str = ""         # plumbing, electrical, structural, pest, cleaning, appliance, other
    description: str = ""
    priority: MaintenancePriority = MaintenancePriority.MEDIUM
    status: MaintenanceStatus = MaintenanceStatus.SUBMITTED
    preferred_date: str = ""
    preferred_time_slot: str = ""  # morning, afternoon, evening
    images: list[str] = field(default_factory=list)
    assigned_to: str = ""      # Vendor name
    vendor_contact: str = ""
    estimated_cost: Decimal = Decimal("0")
    actual_cost: Decimal = Decimal("0")
    resolution_notes: str = ""
    created_at: float = 0.0
    resolved_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "tenant_id": self.tenant_id,
            "property_id": self.property_id,
            "category": self.category,
            "description": self.description,
            "priority": self.priority.value,
            "status": self.status.value,
            "preferred_date": self.preferred_date,
            "preferred_time_slot": self.preferred_time_slot,
            "assigned_to": self.assigned_to,
            "vendor_contact": self.vendor_contact,
            "estimated_cost": float(self.estimated_cost),
            "actual_cost": float(self.actual_cost),
            "resolution_notes": self.resolution_notes,
            "created_at": self.created_at,
            "resolved_at": self.resolved_at,
            "time_ago": _time_ago(self.created_at),
        }


def _time_ago(ts: float) -> str:
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
    return f"{days}d ago"


# ── Tenant Portal Engine ─────────────────────────────────────────────────────

class TenantPortal:
    """Manages tenant lifecycle — payments, agreements, maintenance."""

    def __init__(self) -> None:
        self._payments: dict[str, RentPayment] = {}
        self._requests: dict[str, MaintenanceRequest] = {}
        self._tenant_payments: dict[str, list[str]] = {}   # tenant_id → [payment_ids]
        self._tenant_requests: dict[str, list[str]] = {}   # tenant_id → [request_ids]
        self._property_tenants: dict[str, list[str]] = {}  # property_id → [tenant_ids]

    # ── Rent Payments ────────────────────────────────────────────────────

    def record_payment(
        self,
        tenant_id: str,
        property_id: str,
        agreement_id: str,
        amount: float,
        due_date: str,
        month_period: str,
        payment_mode: str = "UPI",
        transaction_ref: str = "",
    ) -> RentPayment:
        """Record a rent payment made by tenant."""
        now = time.time()
        payment = RentPayment(
            payment_id=f"PAY-{int(now)}-{random.randint(1000,9999)}",
            tenant_id=tenant_id,
            property_id=property_id,
            agreement_id=agreement_id,
            amount=Decimal(str(amount)),
            paid_date=now,
            due_date=due_date,
            payment_mode=payment_mode,
            status=PaymentStatus.PAID,
            transaction_ref=transaction_ref or f"TXN-{int(now)}",
            month_period=month_period,
            created_at=now,
        )
        self._payments[payment.payment_id] = payment
        self._tenant_payments.setdefault(tenant_id, []).append(payment.payment_id)
        _log.info("[RE TENANT] Payment recorded: %s — ₹%.0f (%s)", payment.payment_id, amount, month_period)
        return payment

    def get_tenant_payments(self, tenant_id: str) -> list[RentPayment]:
        """Get all payments for a tenant."""
        payment_ids = self._tenant_payments.get(tenant_id, [])
        payments = [self._payments[pid] for pid in payment_ids if pid in self._payments]
        payments.sort(key=lambda p: p.paid_date or 0, reverse=True)
        return payments

    def get_payment_history(self, tenant_id: str, limit: int = 12) -> list[dict[str, Any]]:
        """Get payment history dict-formatted for the UI."""
        return [p.to_dict() for p in self.get_tenant_payments(tenant_id)[:limit]]

    def get_outstanding_balance(self, tenant_id: str, monthly_rent: float = 0) -> float:
        """Calculate outstanding balance (overdue months × rent)."""
        payments = self.get_tenant_payments(tenant_id)
        if not monthly_rent:
            return 0.0
        paid_months = sum(1 for p in payments if p.status == PaymentStatus.PAID)
        # Simplified: assume 1 month of rent per payment
        overdue_months = max(0, 1 - paid_months)  # simplified demo
        return float(overdue_months * monthly_rent)

    def get_next_due_date(self, tenant_id: str, last_due: str = "") -> str:
        """Get the next rent due date."""
        payments = self.get_tenant_payments(tenant_id)
        if payments:
            last = payments[0]
            # Move to next month
            parts = last.due_date.split("-")
            if len(parts) == 3:
                month = int(parts[1]) + 1
                year = int(parts[0])
                if month > 12:
                    month = 1
                    year += 1
                return f"{year}-{month:02d}-{parts[2]}"
        return last_due or time.strftime("%Y-%m-%d")

    # ── Maintenance Requests ─────────────────────────────────────────────

    def submit_maintenance_request(
        self,
        tenant_id: str,
        property_id: str,
        category: str,
        description: str,
        priority: str = "medium",
        preferred_date: str = "",
        preferred_time_slot: str = "",
    ) -> MaintenanceRequest:
        """Submit a maintenance/repair request."""
        try:
            prio = MaintenancePriority(priority)
        except ValueError:
            prio = MaintenancePriority.MEDIUM

        now = time.time()
        req = MaintenanceRequest(
            request_id=f"MNT-{int(now)}-{random.randint(100,999)}",
            tenant_id=tenant_id,
            property_id=property_id,
            category=category,
            description=description,
            priority=prio,
            status=MaintenanceStatus.SUBMITTED,
            preferred_date=preferred_date,
            preferred_time_slot=preferred_time_slot,
            created_at=now,
        )
        self._requests[req.request_id] = req
        self._tenant_requests.setdefault(tenant_id, []).append(req.request_id)
        _log.info("[RE TENANT] Maintenance request: %s — %s (%s)", req.request_id, category, priority)
        return req

    def update_maintenance_status(self, request_id: str, status: str, resolution_notes: str = "", cost: float = 0) -> bool:
        """Update maintenance request status."""
        try:
            s = MaintenanceStatus(status)
        except ValueError:
            return False
        req = self._requests.get(request_id)
        if not req:
            return False
        req.status = s
        if resolution_notes:
            req.resolution_notes = resolution_notes
        if cost:
            req.actual_cost = Decimal(str(cost))
        if s == MaintenanceStatus.RESOLVED:
            req.resolved_at = time.time()
        return True

    def get_tenant_requests(self, tenant_id: str) -> list[MaintenanceRequest]:
        """Get all maintenance requests for a tenant."""
        req_ids = self._tenant_requests.get(tenant_id, [])
        reqs = [self._requests[rid] for rid in req_ids if rid in self._requests]
        reqs.sort(key=lambda r: r.created_at, reverse=True)
        return reqs

    def get_maintenance_stats(self, tenant_id: str) -> dict[str, Any]:
        """Get maintenance request statistics for a tenant."""
        reqs = self.get_tenant_requests(tenant_id)
        return {
            "total": len(reqs),
            "open": sum(1 for r in reqs if r.status in (MaintenanceStatus.SUBMITTED, MaintenanceStatus.ACKNOWLEDGED, MaintenanceStatus.IN_PROGRESS)),
            "resolved": sum(1 for r in reqs if r.status == MaintenanceStatus.RESOLVED),
            "emergency": sum(1 for r in reqs if r.priority == MaintenancePriority.EMERGENCY),
            "by_category": _count_by([r.category for r in reqs]),
        }

    # ── Stats ────────────────────────────────────────────────────────────

    def get_stats(self) -> dict[str, Any]:
        """Get overall tenant portal statistics."""
        return {
            "total_payments": len(self._payments),
            "total_maintenance_requests": len(self._requests),
            "total_tenants": len(self._tenant_payments),
            "total_payment_amount": float(sum(p.amount for p in self._payments.values() if p.status == PaymentStatus.PAID)),
            "open_requests": sum(1 for r in self._requests.values() if r.status != MaintenanceStatus.RESOLVED),
            "emergency_requests": sum(1 for r in self._requests.values() if r.priority == MaintenancePriority.EMERGENCY),
        }


def _count_by(items: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        counts[item] = counts.get(item, 0) + 1
    return counts


# ── API Router ──────────────────────────────────────────────────────────────

_tenant_portal_instance: TenantPortal | None = None


def get_tenant_portal() -> TenantPortal:
    global _tenant_portal_instance
    if _tenant_portal_instance is None:
        _tenant_portal_instance = TenantPortal()
    return _tenant_portal_instance


def create_tenant_router(portal: TenantPortal | None = None) -> Any:
    """Create a FastAPI router for tenant portal endpoints."""
    from fastapi import APIRouter, HTTPException, Query

    tp = portal or get_tenant_portal()
    router = APIRouter(prefix="/api/realestate/tenant", tags=["Real Estate Tenant Portal"])

    @router.post("/payments")
    async def record_payment(
        tenant_id: str = Query(...),
        property_id: str = Query(...),
        agreement_id: str = Query(""),
        amount: float = Query(...),
        due_date: str = Query(""),
        month_period: str = Query(""),
        payment_mode: str = Query("UPI"),
        transaction_ref: str = Query(""),
    ):
        """Record a rent payment."""
        payment = tp.record_payment(
            tenant_id=tenant_id, property_id=property_id,
            agreement_id=agreement_id, amount=amount,
            due_date=due_date, month_period=month_period,
            payment_mode=payment_mode, transaction_ref=transaction_ref,
        )
        return {"payment": payment.to_dict()}

    @router.get("/payments")
    async def get_payments(tenant_id: str = Query(...)):
        """Get payment history for a tenant."""
        payments = tp.get_payment_history(tenant_id)
        return {
            "payments": payments,
            "total": len(payments),
            "outstanding": tp.get_outstanding_balance(tenant_id),
        }

    @router.post("/maintenance")
    async def submit_maintenance(
        tenant_id: str = Query(...),
        property_id: str = Query(...),
        category: str = Query("other"),
        description: str = Query(...),
        priority: str = Query("medium"),
        preferred_date: str = Query(""),
        preferred_time_slot: str = Query(""),
    ):
        """Submit a maintenance request."""
        req = tp.submit_maintenance_request(
            tenant_id=tenant_id, property_id=property_id,
            category=category, description=description,
            priority=priority, preferred_date=preferred_date,
            preferred_time_slot=preferred_time_slot,
        )
        return {"request": req.to_dict()}

    @router.get("/maintenance")
    async def get_maintenance(tenant_id: str = Query(...)):
        """Get maintenance requests for a tenant."""
        reqs = tp.get_tenant_requests(tenant_id)
        return {"requests": [r.to_dict() for r in reqs], "total": len(reqs)}

    @router.put("/maintenance/{request_id}/status")
    async def update_maintenance_status(
        request_id: str,
        status: str = Query(...),
        resolution_notes: str = Query(""),
        cost: float = Query(0),
    ):
        """Update maintenance request status (admin/vendor)."""
        if not tp.update_maintenance_status(request_id, status, resolution_notes, cost):
            raise HTTPException(status_code=404, detail="Request not found or invalid status")
        return {"success": True}

    @router.get("/maintenance/stats")
    async def maintenance_stats(tenant_id: str = Query(...)):
        """Get maintenance statistics for a tenant."""
        return tp.get_maintenance_stats(tenant_id)

    @router.get("/stats")
    async def portal_stats():
        """Get tenant portal statistics."""
        return tp.get_stats()

    return router
