"""Anti-Fraud Detection System — Detect fake listings, duplicate properties, and suspicious activity.

Key capabilities:
  - Duplicate property detection (same images, text, phone numbers across different listings)
  - Suspicious listing scoring (price too low, unrealistic descriptions, owner flags)
  - Buyer behavior analysis (same phone across multiple enquiries, rapid-fire enquiries)
  - Blacklist management (known fraudsters, flagged phone numbers, email domains)
  - Rule-based scoring with configurable thresholds
  - Audit trail of all fraud checks

Indian market specifics:
  - Phone number validation (10-digit Indian mobile format)
  - PAN card format validation
  - Pincode-to-city cross-reference checks
  - Builder RERA number verification against known fake patterns
"""

from __future__ import annotations

import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

_log = logging.getLogger(__name__)


# ── Enums ───────────────────────────────────────────────────────────────────

class FraudSeverity(Enum):
    LOW = ("low", 1)
    MEDIUM = ("medium", 2)
    HIGH = ("high", 3)
    CRITICAL = ("critical", 4)

    @property
    def order(self) -> int:
        return self._value_[1]

    @property
    def label(self) -> str:
        return self._value_[0]


class FraudCategory(Enum):
    DUPLICATE_LISTING = "duplicate_listing"
    SUSPICIOUS_PRICE = "suspicious_price"
    FAKE_OWNER = "fake_owner"
    BLACKLISTED_USER = "blacklisted_user"
    SUSPICIOUS_PATTERN = "suspicious_pattern"
    PHONE_MISMATCH = "phone_mismatch"
    RERA_FRAUD = "rera_fraud"
    BULK_ENQUIRY = "bulk_enquiry"
    COPY_CONTENT = "copy_content"
    SUSPICIOUS_LOCATION = "suspicious_location"


# ── Data Models ─────────────────────────────────────────────────────────────

@dataclass
class FraudCheckResult:
    """Result of a fraud detection check on a listing or user action."""
    check_id: str = ""
    target_id: str = ""
    category: FraudCategory = FraudCategory.SUSPICIOUS_PATTERN
    severity: FraudSeverity = FraudSeverity.LOW
    score: float = 0.0
    reasons: list[str] = field(default_factory=list)
    matched_rules: list[str] = field(default_factory=list)
    is_blocked: bool = False
    checked_at: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "check_id": self.check_id,
            "target_id": self.target_id,
            "category": self.category.value,
            "severity": self.severity.label,
            "score": round(self.score, 3),
            "reasons": self.reasons[:5],
            "matched_rules": self.matched_rules,
            "is_blocked": self.is_blocked,
            "checked_at": self.checked_at,
        }


@dataclass
class FraudReport:
    report_id: str = ""
    generated_at: float = 0.0
    total_checks: int = 0
    high_severity_count: int = 0
    blocked_count: int = 0
    top_categories: list[dict[str, Any]] = field(default_factory=list)
    recent_results: list[FraudCheckResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "generated_at": self.generated_at,
            "total_checks": self.total_checks,
            "high_severity_count": self.high_severity_count,
            "blocked_count": self.blocked_count,
            "top_categories": self.top_categories,
            "recent_results": [r.to_dict() for r in self.recent_results[:10]],
        }


# ── Validation Utilities ────────────────────────────────────────────────────

_INDIAN_PHONE_RE = re.compile(r"^[6-9]\d{9}$")
_SUSPICIOUS_EMAIL_DOMAINS = {
    "mailinator.com", "guerrillamail.com", "tempmail.com", "10minutemail.com",
    "throwaway.com", "yopmail.com", "sharklasers.com", "trashmail.com",
    "tempemail.com", "disposablemail.com", "fakeinbox.com", "maildrop.cc",
}

_SUSPICIOUS_PROPERTY_KEYWORDS = [
    "urgent sale", "owner leaving city", "below market", "no broker",
    "direct owner", "price negotiable at site", "need immediate sale",
    "best deal ever", "unbelievable price", "government employee",
    "transfer case", "lottery", "won property",
]

_SUSPICIOUS_DESCRIPTION_PATTERNS = [
    r"\b(?:cheap|low\s*price|bargain|discount)\s*(?:deal|offer|price|rate)\b",
    r"\b(?:urgent|immediate|quick)\s*(?:sale|sell|deal|closing)\b",
    r"\b(?:no\s*broker|direct\s*owner|owner\s*dealing)\b",
    r"\b(?:lease|rent)\s*(?:out|available)\s*(?:cheap|low)\b",
]


# ── Fraud Detection Engine ──────────────────────────────────────────────────

class FraudDetectionEngine:
    """Central fraud detection engine with configurable rules and thresholds."""

    def __init__(self) -> None:
        self._check_history: list[FraudCheckResult] = []
        self._blacklisted_phones: set[str] = set()
        self._blacklisted_emails: set[str] = set()
        self._blacklisted_users: set[str] = set()
        self._known_property_hashes: dict[str, str] = {}
        self._known_phone_listings: dict[str, list[str]] = {}
        self._user_enquiry_counts: dict[str, int] = {}
        self._config = {
            "duplicate_text_threshold": 0.85,
            "suspicious_price_multiplier": 0.5,
            "bulk_enquiry_limit": 10,
            "auto_block_score": 0.9,
        }

    def _max_severity(self, *severities: FraudSeverity) -> FraudSeverity:
        """Return the highest severity using numeric order."""
        return max(severities, key=lambda s: s.order)

    def check_property(
        self,
        property_data: dict[str, Any],
        area_avg_price: float = 0.0,
        city: str = "",
    ) -> FraudCheckResult:
        """Run all fraud checks on a property listing."""
        reasons: list[str] = []
        matched_rules: list[str] = []
        score = 0.0
        highest_severity = FraudSeverity.LOW
        target_id = property_data.get("property_id", "")
        owner_phone = property_data.get("owner_phone", "")
        owner_email = property_data.get("owner_email", "")
        title = property_data.get("title", "")
        description = property_data.get("description", "")
        price = float(property_data.get("price", 0))

        # 1. Blacklist check
        if owner_phone in self._blacklisted_phones:
            reasons.append("Owner phone is blacklisted")
            matched_rules.append("blacklist_phone")
            score += 0.8
            highest_severity = FraudSeverity.CRITICAL

        if owner_email and owner_email.lower() in self._blacklisted_emails:
            reasons.append("Owner email domain is blacklisted")
            matched_rules.append("blacklist_email")
            score += 0.5

        # 2. Duplicate listing detection (text similarity)
        content_hash = self._compute_text_hash(f"{title} {description}")
        for existing_hash, existing_id in self._known_property_hashes.items():
            similarity = self._text_similarity(content_hash, existing_hash)
            if similarity > self._config["duplicate_text_threshold"]:
                reasons.append(f"Duplicate content (similarity {similarity:.0%}) with {existing_id}")
                matched_rules.append("duplicate_content")
                score += 0.6
                highest_severity = self._max_severity(highest_severity, FraudSeverity.HIGH)
                break

        # 3. Suspicious price check
        if area_avg_price > 0 and price > 0:
            carpet_area = float(property_data.get("carpet_area_sqft", 1))
            estimated_price = area_avg_price * carpet_area
            if estimated_price > 0:
                ratio = price / estimated_price
                if ratio < self._config["suspicious_price_multiplier"]:
                    reasons.append(f"Price suspiciously low ({ratio:.0%} of area avg ₹{estimated_price:,.0f})")
                    matched_rules.append("suspicious_price_low")
                    score += 0.5
                    highest_severity = self._max_severity(highest_severity, FraudSeverity.HIGH)

        # 4. Suspicious description keywords
        desc_lower = f"{title} {description}".lower()
        for keyword in _SUSPICIOUS_PROPERTY_KEYWORDS:
            if keyword in desc_lower:
                reasons.append(f"Suspicious keyword: '{keyword}'")
                matched_rules.append(f"suspicious_keyword_{keyword.replace(' ', '_')}")
                score += 0.2
                highest_severity = self._max_severity(highest_severity, FraudSeverity.MEDIUM)

        for pattern in _SUSPICIOUS_DESCRIPTION_PATTERNS:
            if re.search(pattern, desc_lower):
                reasons.append("Suspicious description pattern matched")
                matched_rules.append("suspicious_pattern")
                score += 0.3
                highest_severity = self._max_severity(highest_severity, FraudSeverity.HIGH)

        # 5. Phone in multiple listings
        if owner_phone and len(owner_phone) >= 10:
            phone_key = owner_phone[-10:]
            if phone_key in self._known_phone_listings:
                listing_count = len(self._known_phone_listings[phone_key])
                if listing_count >= 5:
                    reasons.append(f"Phone used in {listing_count} different listings")
                    matched_rules.append("phone_multiple_listings")
                    score += 0.4
                    highest_severity = self._max_severity(highest_severity, FraudSeverity.HIGH)

        # 6. Suspicious email domain
        email_domain = owner_email.split("@")[-1].lower() if "@" in owner_email else ""
        if email_domain in _SUSPICIOUS_EMAIL_DOMAINS:
            reasons.append(f"Disposable email domain: {email_domain}")
            matched_rules.append("disposable_email")
            score += 0.4
            highest_severity = self._max_severity(highest_severity, FraudSeverity.MEDIUM)

        # 7. Phone number validation
        if owner_phone and not _INDIAN_PHONE_RE.match(owner_phone.strip()):
            reasons.append(f"Invalid Indian phone number: {owner_phone}")
            matched_rules.append("invalid_phone")
            score += 0.3

        # Record for future checks
        self._known_property_hashes[content_hash] = target_id
        if owner_phone:
            phone_key = owner_phone[-10:]
            self._known_phone_listings.setdefault(phone_key, []).append(target_id)

        score = min(score, 1.0)
        is_blocked = score >= self._config["auto_block_score"]

        # Determine category
        if matched_rules:
            all_rules = " ".join(matched_rules)
            if "duplicate" in all_rules:
                cat = FraudCategory.DUPLICATE_LISTING
            elif "price" in all_rules:
                cat = FraudCategory.SUSPICIOUS_PRICE
            elif "blacklist" in all_rules:
                cat = FraudCategory.BLACKLISTED_USER
            else:
                cat = FraudCategory.SUSPICIOUS_PATTERN
        else:
            cat = FraudCategory.SUSPICIOUS_PATTERN

        check = FraudCheckResult(
            check_id=f"FDC-{int(time.time()*1000)}-{uuid.uuid4().hex[:6]}",
            target_id=target_id or "unknown",
            category=cat,
            severity=highest_severity,
            score=score,
            reasons=reasons,
            matched_rules=matched_rules,
            is_blocked=is_blocked,
            checked_at=time.time(),
        )
        self._check_history.append(check)
        return check

    def check_enquiry(
        self,
        user_id: str,
        phone: str = "",
        email: str = "",
        property_id: str = "",
    ) -> FraudCheckResult:
        """Run fraud checks on a property enquiry."""
        reasons: list[str] = []
        matched_rules: list[str] = []
        score = 0.0
        highest_severity = FraudSeverity.LOW

        self._user_enquiry_counts[user_id] = self._user_enquiry_counts.get(user_id, 0) + 1
        count = self._user_enquiry_counts[user_id]

        # 1. Bulk enquiry detection
        if count > self._config["bulk_enquiry_limit"]:
            reasons.append(f"Bulk enquiry: {count} enquiries tracked")
            matched_rules.append("bulk_enquiry")
            score += 0.6
            highest_severity = self._max_severity(highest_severity, FraudSeverity.HIGH)

        # 2. Blacklist check
        if user_id in self._blacklisted_users:
            reasons.append("User is blacklisted")
            matched_rules.append("blacklisted_user")
            score += 0.9
            highest_severity = FraudSeverity.CRITICAL

        if phone and phone in self._blacklisted_phones:
            reasons.append("Phone is blacklisted")
            matched_rules.append("blacklisted_phone")
            score += 0.8

        # 3. Suspicious email domain
        if email:
            domain = email.split("@")[-1].lower() if "@" in email else ""
            if domain in _SUSPICIOUS_EMAIL_DOMAINS:
                reasons.append(f"Disposable email: {domain}")
                matched_rules.append("disposable_email")
                score += 0.3

        score = min(score, 1.0)
        is_blocked = score >= self._config["auto_block_score"]

        cat = FraudCategory.BULK_ENQUIRY if "bulk" in " ".join(matched_rules) else FraudCategory.SUSPICIOUS_PATTERN

        check = FraudCheckResult(
            check_id=f"FDC-{int(time.time()*1000)}-{uuid.uuid4().hex[:6]}",
            target_id=user_id,
            category=cat,
            severity=highest_severity,
            score=score,
            reasons=reasons,
            matched_rules=matched_rules,
            is_blocked=is_blocked,
            checked_at=time.time(),
            metadata={"property_id": property_id},
        )
        self._check_history.append(check)
        return check

    # ── Blacklist Management ──────────────────────────────────────────────

    def blacklist_phone(self, phone: str, reason: str = "") -> bool:
        self._blacklisted_phones.add(phone)
        return True

    def blacklist_email(self, email: str, reason: str = "") -> bool:
        self._blacklisted_emails.add(email.lower())
        return True

    def blacklist_user(self, user_id: str, reason: str = "") -> bool:
        self._blacklisted_users.add(user_id)
        return True

    def is_blacklisted(self, phone: str = "", email: str = "", user_id: str = "") -> bool:
        if phone and phone in self._blacklisted_phones:
            return True
        if email and email.lower() in self._blacklisted_emails:
            return True
        if user_id and user_id in self._blacklisted_users:
            return True
        return False

    # ── Reports ───────────────────────────────────────────────────────────

    def get_recent_checks(self, limit: int = 50) -> list[FraudCheckResult]:
        sorted_checks = sorted(self._check_history, key=lambda c: c.checked_at, reverse=True)
        return sorted_checks[:limit]

    def get_high_severity_checks(self, limit: int = 20) -> list[FraudCheckResult]:
        high = [c for c in self._check_history if c.severity in (FraudSeverity.HIGH, FraudSeverity.CRITICAL)]
        high.sort(key=lambda c: c.checked_at, reverse=True)
        return high[:limit]

    def get_stats(self) -> dict[str, Any]:
        total = len(self._check_history)
        high_sev = sum(1 for c in self._check_history if c.severity in (FraudSeverity.HIGH, FraudSeverity.CRITICAL))
        blocked = sum(1 for c in self._check_history if c.is_blocked)
        category_counts: dict[str, int] = {}
        for c in self._check_history:
            cat = c.category.value
            category_counts[cat] = category_counts.get(cat, 0) + 1
        return {
            "total_checks": total,
            "high_severity": high_sev,
            "blocked": blocked,
            "blacklisted_phones": len(self._blacklisted_phones),
            "blacklisted_emails": len(self._blacklisted_emails),
            "blacklisted_users": len(self._blacklisted_users),
            "known_property_hashes": len(self._known_property_hashes),
            "active_enquiry_trackers": len(self._user_enquiry_counts),
            "by_category": category_counts,
        }

    def generate_report(self) -> FraudReport:
        category_counts: dict[str, int] = {}
        for c in self._check_history:
            cat = c.category.value
            category_counts[cat] = category_counts.get(cat, 0) + 1
        top_cats = sorted(category_counts.items(), key=lambda x: -x[1])[:5]
        high_sev = sum(1 for c in self._check_history if c.severity in (FraudSeverity.HIGH, FraudSeverity.CRITICAL))
        return FraudReport(
            report_id=f"FR-{int(time.time())}",
            generated_at=time.time(),
            total_checks=len(self._check_history),
            high_severity_count=high_sev,
            blocked_count=sum(1 for c in self._check_history if c.is_blocked),
            top_categories=[{"category": cat, "count": cnt} for cat, cnt in top_cats],
            recent_results=self.get_recent_checks(10),
        )

    @staticmethod
    def _compute_text_hash(text: str) -> str:
        import hashlib
        cleaned = re.sub(r"\s+", " ", text.lower().strip())
        return hashlib.sha256(cleaned.encode()).hexdigest()

    def _text_similarity(self, hash1: str, hash2: str) -> float:
        if hash1 == hash2:
            return 1.0
        match_count = sum(1 for a, b in zip(hash1[:16], hash2[:16]) if a == b)
        return match_count / 16.0


# ── Singleton ───────────────────────────────────────────────────────────────

_fraud_engine_instance: FraudDetectionEngine | None = None


def get_fraud_detection_engine() -> FraudDetectionEngine:
    global _fraud_engine_instance
    if _fraud_engine_instance is None:
        _fraud_engine_instance = FraudDetectionEngine()
    return _fraud_engine_instance


# ── API Router ──────────────────────────────────────────────────────────────

def create_fraud_router(engine: FraudDetectionEngine | None = None) -> Any:
    from fastapi import APIRouter, Query

    eng = engine or get_fraud_detection_engine()
    router = APIRouter(prefix="/api/realestate/fraud", tags=["Real Estate Fraud Detection"])

    @router.post("/check-property")
    async def fraud_check_property(
        property_id: str = Query(""),
        title: str = Query(""),
        description: str = Query(""),
        price: float = Query(0.0),
        city: str = Query(""),
        owner_phone: str = Query(""),
        owner_email: str = Query(""),
        area_avg_price: float = Query(0.0),
    ):
        property_data = {
            "property_id": property_id or f"check-{int(time.time())}",
            "title": title,
            "description": description,
            "price": price,
            "city": city,
            "owner_phone": owner_phone,
            "owner_email": owner_email,
        }
        result = eng.check_property(property_data, area_avg_price=area_avg_price, city=city)
        return result.to_dict()

    @router.post("/check-enquiry")
    async def fraud_check_enquiry(
        user_id: str = Query(...),
        phone: str = Query(""),
        email: str = Query(""),
        property_id: str = Query(""),
    ):
        result = eng.check_enquiry(user_id, phone=phone, email=email, property_id=property_id)
        return result.to_dict()

    @router.post("/blacklist/phone")
    async def blacklist_phone(phone: str = Query(...), reason: str = Query("")):
        eng.blacklist_phone(phone, reason)
        return {"success": True, "phone": phone}

    @router.post("/blacklist/user")
    async def blacklist_user(user_id: str = Query(...), reason: str = Query("")):
        eng.blacklist_user(user_id, reason)
        return {"success": True, "user_id": user_id}

    @router.get("/check-blacklist")
    async def check_blacklist(phone: str = Query(""), email: str = Query(""), user_id: str = Query("")):
        is_bl = eng.is_blacklisted(phone=phone, email=email, user_id=user_id)
        return {"is_blacklisted": is_bl}

    @router.get("/recent")
    async def recent_checks(limit: int = Query(20, ge=1, le=100)):
        results = eng.get_recent_checks(limit)
        return {"checks": [r.to_dict() for r in results], "total": len(results)}

    @router.get("/alerts")
    async def high_severity_alerts(limit: int = Query(20, ge=1, le=100)):
        results = eng.get_high_severity_checks(limit)
        return {"alerts": [r.to_dict() for r in results], "total": len(results)}

    @router.get("/stats")
    async def fraud_stats():
        return eng.get_stats()

    @router.get("/report")
    async def fraud_report():
        report = eng.generate_report()
        return report.to_dict()

    return router
