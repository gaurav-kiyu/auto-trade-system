"""Admin Panel — property moderation, platform analytics, KYC, reports.

Features:
  - Property moderation (approve/reject listings)
  - Platform analytics (daily active users, listings, enquiries)
  - KYC verification for brokers/developers
  - Content moderation (reported listings)
  - Revenue/commission tracking
  - User management overview
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

class ModerationStatus(Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    FLAGGED = "flagged"
    BANNED = "banned"

class KYCStatus(Enum):
    NOT_SUBMITTED = "not_submitted"
    PENDING = "pending"
    VERIFIED = "verified"
    REJECTED = "rejected"

class ReportReason(Enum):
    SPAM = "spam"
    FRAUD = "fraud"
    MISLEADING = "misleading"
    WRONG_INFO = "wrong_info"
    DUPLICATE = "duplicate"
    OTHER = "other"


# ── Domain Models ────────────────────────────────────────────────────────────

@dataclass
class PlatformMetrics:
    """Platform analytics snapshot."""
    total_listings: int = 0
    pending_moderation: int = 0
    active_users: int = 0
    total_enquiries_today: int = 0
    total_leads: int = 0
    conversion_rate: float = 0.0
    total_payments_volume: float = 0.0
    active_auctions: int = 0
    builder_projects: int = 0
    rera_compliance_pct: float = 0.0
    timestamp: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items()}


@dataclass
class ReportedListing:
    """A property that has been reported by users."""
    report_id: str = ""
    property_id: str = ""
    reported_by: str = ""
    reason: ReportReason = ReportReason.OTHER
    description: str = ""
    reported_at: float = 0.0
    status: ModerationStatus = ModerationStatus.PENDING
    resolved_by: str = ""
    resolved_at: float = 0.0
    action_taken: str = ""  # warned, removed, nothing

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "property_id": self.property_id,
            "reported_by": self.reported_by,
            "reason": self.reason.value,
            "description": self.description,
            "reported_at": self.reported_at,
            "status": self.status.value,
            "action_taken": self.action_taken,
        }


# ── Admin Panel Engine ───────────────────────────────────────────────────────

class AdminPanel:
    """Central admin interface for platform management."""

    def __init__(self) -> None:
        self._moderation_queue: dict[str, ModerationStatus] = {}  # property_id → status
        self._reported_listings: dict[str, ReportedListing] = {}
        self._kyc_records: dict[str, KYCStatus] = {}  # user_id → status
        self._daily_metrics: dict[str, dict[str, Any]] = {}  # date → metrics

    # ── Moderation ────────────────────────────────────────────────────────

    def add_to_moderation(self, property_id: str) -> None:
        """Add a property to the moderation queue."""
        if property_id not in self._moderation_queue:
            self._moderation_queue[property_id] = ModerationStatus.PENDING

    def approve_listing(self, property_id: str) -> bool:
        """Approve a property listing."""
        if property_id not in self._moderation_queue:
            return False
        self._moderation_queue[property_id] = ModerationStatus.APPROVED
        _log.info("[RE ADMIN] Listing approved: %s", property_id)
        return True

    def reject_listing(self, property_id: str) -> bool:
        """Reject a property listing."""
        if property_id not in self._moderation_queue:
            return False
        self._moderation_queue[property_id] = ModerationStatus.REJECTED
        _log.info("[RE ADMIN] Listing rejected: %s", property_id)
        return True

    def get_moderation_queue(self, status: str | None = None) -> list[dict[str, Any]]:
        """Get moderation queue, optionally filtered by status."""
        items = []
        for prop_id, s in self._moderation_queue.items():
            if status and s.value != status:
                continue
            items.append({"property_id": prop_id, "status": s.value})
        return items

    def get_moderation_count(self, status: str | None = None) -> int:
        """Get count of items in moderation queue."""
        if status:
            return sum(1 for s in self._moderation_queue.values() if s.value == status)
        return len(self._moderation_queue)

    # ── Reports ───────────────────────────────────────────────────────────

    def report_listing(
        self, property_id: str, reported_by: str,
        reason: str = "other", description: str = "",
    ) -> ReportedListing:
        """Report a property listing for moderation review."""
        try:
            r = ReportReason(reason)
        except ValueError:
            r = ReportReason.OTHER
        report = ReportedListing(
            report_id=f"RPT-{int(time.time())}-{random.randint(100,999)}",
            property_id=property_id,
            reported_by=reported_by,
            reason=r,
            description=description,
            reported_at=time.time(),
            status=ModerationStatus.PENDING,
        )
        self._reported_listings[report.report_id] = report
        self._moderation_queue[property_id] = ModerationStatus.FLAGGED
        _log.info("[RE ADMIN] Property reported: %s — %s", property_id, reason)
        return report

    def resolve_report(
        self, report_id: str, action: str = "nothing",
        resolved_by: str = "admin",
    ) -> bool:
        """Resolve a reported listing."""
        report = self._reported_listings.get(report_id)
        if not report:
            return False
        report.status = ModerationStatus.APPROVED if action == "nothing" else ModerationStatus.BANNED
        report.resolved_by = resolved_by
        report.resolved_at = time.time()
        report.action_taken = action

        if action == "removed":
            self._moderation_queue[report.property_id] = ModerationStatus.REJECTED
        elif action == "warned":
            pass
        else:
            self._moderation_queue[report.property_id] = ModerationStatus.APPROVED

        _log.info("[RE ADMIN] Report %s resolved: %s", report_id, action)
        return True

    def get_reported_listings(self, status: str | None = None) -> list[ReportedListing]:
        """Get reported listings, optionally filtered."""
        reports = list(self._reported_listings.values())
        if status:
            reports = [r for r in reports if r.status.value == status]
        reports.sort(key=lambda r: r.reported_at, reverse=True)
        return reports

    # ── KYC Verification ──────────────────────────────────────────────────

    def submit_kyc(self, user_id: str) -> bool:
        """Submit KYC documents for a user."""
        if user_id in self._kyc_records and self._kyc_records[user_id] == KYCStatus.VERIFIED:
            return False
        self._kyc_records[user_id] = KYCStatus.PENDING
        return True

    def verify_kyc(self, user_id: str) -> bool:
        """Verify a user's KYC documents."""
        if user_id not in self._kyc_records:
            return False
        self._kyc_records[user_id] = KYCStatus.VERIFIED
        _log.info("[RE ADMIN] KYC verified: %s", user_id)
        return True

    def reject_kyc(self, user_id: str) -> bool:
        """Reject a user's KYC documents."""
        if user_id not in self._kyc_records:
            return False
        self._kyc_records[user_id] = KYCStatus.REJECTED
        return True

    def get_kyc_status(self, user_id: str) -> str:
        """Get KYC status for a user."""
        status = self._kyc_records.get(user_id, KYCStatus.NOT_SUBMITTED)
        return status.value

    def get_kyc_queue(self) -> list[dict[str, Any]]:
        """Get all users pending KYC verification."""
        return [
            {"user_id": uid, "status": s.value}
            for uid, s in self._kyc_records.items()
            if s == KYCStatus.PENDING
        ]

    # ── Analytics ─────────────────────────────────────────────────────────

    def generate_metrics(
        self,
        property_service: Any = None,
        auction_engine: Any = None,
        builder_portal: Any = None,
        lead_service: Any = None,
        notification_engine: Any = None,
    ) -> PlatformMetrics:
        """Generate platform analytics metrics from all services."""
        metrics = PlatformMetrics(
            pending_moderation=self.get_moderation_count("pending"),
            timestamp=time.time(),
        )
        if property_service:
            try:
                metrics.total_listings = len(property_service.list_all())
            except Exception:
                pass
        if auction_engine:
            try:
                stats = auction_engine.get_stats()
                metrics.active_auctions = stats.get("active", 0)
            except Exception:
                pass
        if builder_portal:
            try:
                stats = builder_portal.get_stats()
                metrics.builder_projects = stats.get("total_projects", 0)
            except Exception:
                pass
        if lead_service:
            try:
                leads = lead_service.get_leads()
                metrics.total_leads = len(leads)
                converted = sum(1 for lead in leads if getattr(lead, 'status', '') == 'converted')
                metrics.conversion_rate = round(converted / max(len(leads), 1) * 100, 1)
            except Exception:
                pass
        if notification_engine:
            try:
                nstats = notification_engine.get_stats()
                metrics.total_enquiries_today = nstats.get("by_category", {}).get("enquiry", 0)
            except Exception:
                pass
        return metrics

    def save_daily_snapshot(self, metrics: PlatformMetrics) -> None:
        """Save a daily metrics snapshot."""
        from core.datetime_ist import now_ist

        # Key by IST date to match get_daily_metrics() (which queries IST).
        # time.strftime() uses the machine-local zone, so on UTC hosts the
        # snapshot was stored under yesterday's date and IST queries missed it
        # during UTC 18:30-24:00 (IST already on the next day).
        date_key = now_ist().strftime("%Y-%m-%d")
        self._daily_metrics[date_key] = metrics.to_dict()

    def get_daily_metrics(self, days: int = 7) -> list[dict[str, Any]]:
        """Get daily metrics for the given number of days."""
        import datetime
        result = []
        for i in range(days):
            from core.datetime_ist import now_ist
            d = (now_ist() - datetime.timedelta(days=i)).strftime("%Y-%m-%d")
            metrics = self._daily_metrics.get(d, {})
            if metrics:
                result.append(metrics)
        return result

    # ── Stats ────────────────────────────────────────────────────────────

    def get_stats(self) -> dict[str, Any]:
        """Get admin panel statistics."""
        return {
            "moderation_queue": self.get_moderation_count(),
            "pending_moderation": self.get_moderation_count("pending"),
            "reported_listings": len(self._reported_listings),
            "pending_reports": sum(1 for r in self._reported_listings.values() if r.status == ModerationStatus.PENDING),
            "kyc_pending": len(self.get_kyc_queue()),
            "kyc_verified": sum(1 for s in self._kyc_records.values() if s == KYCStatus.VERIFIED),
            "snapshots_saved": len(self._daily_metrics),
        }


# ── API Router ──────────────────────────────────────────────────────────────

_admin_panel_instance: AdminPanel | None = None


def get_admin_panel() -> AdminPanel:
    global _admin_panel_instance
    if _admin_panel_instance is None:
        _admin_panel_instance = AdminPanel()
    return _admin_panel_instance


def create_admin_router(
    panel: AdminPanel | None = None,
    property_service: Any = None,
    auction_engine: Any = None,
    builder_portal: Any = None,
    lead_service: Any = None,
    notification_engine: Any = None,
) -> Any:
    """Create a FastAPI router for admin panel endpoints."""
    from fastapi import APIRouter, HTTPException, Query

    ap = panel or get_admin_panel()
    router = APIRouter(prefix="/api/realestate/admin", tags=["Real Estate Admin"])

    @router.get("/metrics")
    async def platform_metrics():
        """Get platform analytics metrics."""
        metrics = ap.generate_metrics(
            property_service=property_service,
            auction_engine=auction_engine,
            builder_portal=builder_portal,
            lead_service=lead_service,
            notification_engine=notification_engine,
        )
        return metrics.to_dict()

    # ── Moderation ──
    @router.get("/moderation")
    async def get_moderation_queue(status: str = Query("")):
        """Get the moderation queue."""
        return {
            "queue": ap.get_moderation_queue(status or None),
            "total": ap.get_moderation_count(),
            "pending": ap.get_moderation_count("pending"),
        }

    @router.post("/moderation/{property_id}/approve")
    async def approve_listing(property_id: str):
        """Approve a property listing."""
        if not ap.approve_listing(property_id):
            raise HTTPException(status_code=404, detail="Property not in moderation queue")
        return {"success": True}

    @router.post("/moderation/{property_id}/reject")
    async def reject_listing(property_id: str):
        """Reject a property listing."""
        if not ap.reject_listing(property_id):
            raise HTTPException(status_code=404, detail="Property not in moderation queue")
        return {"success": True}

    # ── Reports ──
    @router.post("/reports")
    async def report_listing(
        property_id: str = Query(...),
        reported_by: str = Query(...),
        reason: str = Query("other"),
        description: str = Query(""),
    ):
        """Report a property listing for review."""
        report = ap.report_listing(property_id, reported_by, reason, description)
        return {"report": report.to_dict()}

    @router.get("/reports")
    async def get_reports(status: str = Query("")):
        """Get reported listings."""
        reports = ap.get_reported_listings(status or None)
        return {"reports": [r.to_dict() for r in reports]}

    @router.post("/reports/{report_id}/resolve")
    async def resolve_report(
        report_id: str,
        action: str = Query("nothing", description="removed/warned/nothing"),
        resolved_by: str = Query("admin"),
    ):
        """Resolve a reported listing."""
        if not ap.resolve_report(report_id, action, resolved_by):
            raise HTTPException(status_code=404, detail="Report not found")
        return {"success": True}

    # ── KYC ──
    @router.post("/kyc/submit")
    async def submit_kyc(user_id: str = Query(...)):
        """Submit KYC documents."""
        if not ap.submit_kyc(user_id):
            raise HTTPException(status_code=400, detail="KYC already verified")
        return {"success": True, "status": "pending"}

    @router.post("/kyc/{user_id}/verify")
    async def verify_kyc(user_id: str):
        """Verify a user's KYC."""
        if not ap.verify_kyc(user_id):
            raise HTTPException(status_code=404, detail="User not found or KYC not submitted")
        return {"success": True}

    @router.get("/kyc/queue")
    async def kyc_queue():
        """Get pending KYC verifications."""
        return {"queue": ap.get_kyc_queue()}

    @router.get("/stats")
    async def admin_stats():
        """Get admin panel statistics."""
        return ap.get_stats()

    return router
