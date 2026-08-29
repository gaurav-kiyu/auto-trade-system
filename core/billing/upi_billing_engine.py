"""100% Free Direct UPI QR Code Billing & Instant Auto-Provisioning Engine (v3.0).

Enables instant zero-fee subscription payments using native NPCI UPI protocol:
- Google Pay, PhonePe, Paytm, BHIM, Cred UPI support.
- Generates dynamic UPI intent & QR payment strings (upi://pay?pa=...&pn=...&am=...&cu=INR).
- Automatically provisions user permissions, unlocks categories, and sets quotas in UserPermissionManager.
- ZERO transaction fees, ZERO payment gateway middleman commissions.
"""

from __future__ import annotations

import time
import urllib.parse
from dataclasses import asdict, dataclass
from typing import Any

from core.auth.user_signal_permissions import ALL_CATEGORIES, UserPermissionManager


@dataclass
class SubscriptionPlan:
    plan_id: str
    name: str
    price_inr: int
    duration_days: int
    daily_quota: int
    allowed_categories: list[str]
    features: list[str]
    badge: str


class UpiBillingEngine:
    """Zero-Fee Native UPI Subscription & Provisioning Manager."""

    # Configurable UPI Merchant ID / VPA
    DEFAULT_UPI_VPA = "ai.auto.gaurav@okaxis"
    DEFAULT_PAYEE_NAME = "OPB Quant Trading Platform"

    PLANS = [
        SubscriptionPlan(
            plan_id="plan_free",
            name="Community Free Tier",
            price_inr=0,
            duration_days=365,
            daily_quota=2,
            allowed_categories=["INDEX_OPTIONS"],
            features=["2 High-Conviction Index Signals / Day", "Telegram Real-Time Alerts", "Personal Received Signals Feed"],
            badge="FREE FOREVER",
        ),
        SubscriptionPlan(
            plan_id="plan_options_vip",
            name="Options VIP Pro",
            price_inr=1999,
            duration_days=30,
            daily_quota=10,
            allowed_categories=["INDEX_OPTIONS", "WEEKLY_EXPIRY_SPECIAL", "HIGH_VOLATILITY_BREAKOUT"],
            features=["10 Options Signals / Day", "0DTE Expiry Special Setups", "Gamma Exposure (GEX) Surface", "1-Click Telegram Action Buttons"],
            badge="MOST POPULAR",
        ),
        SubscriptionPlan(
            plan_id="plan_all_access",
            name="Institutional All-Access",
            price_inr=3999,
            duration_days=30,
            daily_quota=0,  # Unlimited
            allowed_categories=list(ALL_CATEGORIES),
            features=["Unlimited Signals across ALL 8 Categories", "Sector Rotation Radar (+5 Boost)", "Master Trade Copier Access", "FII/DII Smart Money Radar", "AI Daily Cognitive Debrief"],
            badge="INSTITUTIONAL",
        ),
    ]

    @classmethod
    def get_plans(cls) -> list[dict[str, Any]]:
        return [asdict(p) for p in cls.PLANS]

    @classmethod
    def generate_upi_qr_string(cls, plan_id: str, username: str, upi_vpa: str | None = None) -> dict[str, Any]:
        """Generate a native NPCI UPI payment URI string and QR details."""
        plan = next((p for p in cls.PLANS if p.plan_id == plan_id), None)
        if not plan:
            return {"error": "Invalid plan ID"}

        vpa = upi_vpa or cls.DEFAULT_UPI_VPA
        payee = cls.DEFAULT_PAYEE_NAME

        # NPCI compliant UPI Intent URI
        # format: upi://pay?pa={vpa}&pn={payee}&am={amount}&cu=INR&tn=OPB-{plan_id}-{username}
        params = {
            "pa": vpa,
            "pn": payee,
            "am": str(plan.price_inr),
            "cu": "INR",
            "tn": f"OPB {plan.name} for {username}",
        }
        upi_uri = f"upi://pay?{urllib.parse.urlencode(params)}"

        return {
            "plan_id": plan.plan_id,
            "plan_name": plan.name,
            "price_inr": plan.price_inr,
            "upi_vpa": vpa,
            "payee_name": payee,
            "upi_uri": upi_uri,
            "username": username,
            "qr_generator_url": f"https://api.qrserver.com/v1/create-qr-code/?size=250x250&data={urllib.parse.quote(upi_uri)}",
        }

    @classmethod
    def confirm_and_provision_user(
        cls,
        username: str,
        plan_id: str,
        transaction_ref: str = "UPI-DIRECT",
    ) -> dict[str, Any]:
        """Instantly provision user signal permissions and quotas upon payment confirmation."""
        plan = next((p for p in cls.PLANS if p.plan_id == plan_id), None)
        if not plan:
            return {"success": False, "message": "Invalid plan ID"}

        mgr = UserPermissionManager.get_instance()
        ok, msg, updated = mgr.update_user_permissions(
            username=username,
            data={
                "signals_enabled": True,
                "allowed_categories": plan.allowed_categories,
                "max_signals_daily": plan.daily_quota,
                "min_signal_tier": "MODERATE_AND_STRONG",
                "notes": f"Active Plan: {plan.name} (Ref: {transaction_ref})",
            },
            admin_username="system_billing",
        )

        return {
            "success": ok,
            "message": f"Successfully activated {plan.name} for {username}!",
            "plan": asdict(plan),
            "user_permissions": updated,
            "timestamp": time.time(),
        }
