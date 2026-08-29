"""Pydantic validation models for the real estate API endpoints.

Provides input validation, type coercion, and documentation for all
POST/PUT endpoints. Replaces raw Query() parameters with validated Body() models.
"""

from __future__ import annotations

import re
from typing import Any

try:
    from fastapi import HTTPException, status
except ImportError:
    class HTTPException(Exception):  # type: ignore
        def __init__(self, status_code: int = 500, detail: str = "") -> None:
            self.status_code = status_code
            self.detail = detail
            super().__init__(f"[{status_code}] {detail}")

    class status:  # type: ignore
        HTTP_400_BAD_REQUEST = 400
        HTTP_422_UNPROCESSABLE_ENTITY = 422


# ── Validation Helpers ──────────────────────────────────────────────────────

INDIAN_PHONE_RE = re.compile(r"^[6-9]\d{9}$")
INDIAN_PINCODE_RE = re.compile(r"^\d{6}$")
VALID_PROPERTY_TYPES = {
    "apartment", "house", "villa", "plot", "commercial_office",
    "commercial_shop", "commercial_warehouse", "farmhouse", "penthouse", "studio",
}
VALID_ENQUIRER_TYPES = {"buyer", "tenant", "broker", "seller"}
VALID_FURNISHING = {"furnished", "semi_furnished", "unfurnished"}
VALID_LISTING_TYPES = {"sell", "rent", "auction", "resale"}
MIN_PRICE = 1_000  # ₹1,000 minimum property price
MAX_PRICE = 1_000_000_000  # ₹100 crore max


def validate_phone(phone: str, field: str = "phone") -> str:
    """Validate Indian phone number (10 digits, starts with 6-9)."""
    if not INDIAN_PHONE_RE.match(phone):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{field}: Must be a valid 10-digit Indian phone number starting with 6-9",
        )
    return phone


def validate_email(email: str, field: str = "email") -> str:
    """Validate email format (basic)."""
    if email and "@" not in email:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{field}: Must be a valid email address",
        )
    return email


def validate_price(price: float, field: str = "price") -> float:
    """Validate price is within reasonable range."""
    if price < MIN_PRICE:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{field}: Price must be at least ₹{MIN_PRICE:,}",
        )
    if price > MAX_PRICE:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{field}: Price cannot exceed ₹{MAX_PRICE:,}",
        )
    return price


def validate_enum(value: str, valid_set: set[str], field: str = "value") -> str:
    """Validate a value against a set of allowed values."""
    if value and value not in valid_set:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{field}: Must be one of: {', '.join(sorted(valid_set))}",
        )
    return value


# ── Request Body Validators (use as Body() dependencies) ────────────────────

class PropertyCreateValidator:
    """Validate property creation parameters."""

    @staticmethod
    def validate(
        title: str,
        price: float,
        city: str,
        property_type: str = "apartment",
        description: str = "",
        locality: str = "",
        bedrooms: int = 0,
        bathrooms: int = 0,
        carpet_area_sqft: float = 0.0,
        owner_id: str = "",
        phone: str = "",
    ) -> dict[str, Any]:
        """Validate and return sanitized property creation data."""
        errors: list[str] = []

        if not title or len(title.strip()) < 3:
            errors.append("title: Must be at least 3 characters")
        if not city or len(city.strip()) < 2:
            errors.append("city: Must be at least 2 characters")
        if price < MIN_PRICE or price > MAX_PRICE:
            errors.append(f"price: Must be between ₹{MIN_PRICE:,} and ₹{MAX_PRICE:,}")
        if property_type and property_type not in VALID_PROPERTY_TYPES:
            errors.append(f"property_type: Must be one of: {', '.join(sorted(VALID_PROPERTY_TYPES))}")
        if bedrooms < 0 or bedrooms > 50:
            errors.append("bedrooms: Must be between 0 and 50")
        if bathrooms < 0 or bathrooms > 50:
            errors.append("bathrooms: Must be between 0 and 50")
        if carpet_area_sqft < 0 or carpet_area_sqft > 1_000_000:
            errors.append("carpet_area_sqft: Must be between 0 and 1,000,000")
        if phone and not INDIAN_PHONE_RE.match(phone):
            errors.append("phone: Must be a valid 10-digit Indian phone number")

        if errors:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"errors": errors},
            )

        return {
            "title": title.strip(),
            "description": description.strip(),
            "property_type": property_type,
            "price": price,
            "city": city.strip(),
            "locality": locality.strip(),
            "bedrooms": bedrooms,
            "bathrooms": bathrooms,
            "carpet_area_sqft": carpet_area_sqft,
            "owner_id": owner_id.strip(),
        }


class LeadCreateValidator:
    """Validate lead creation parameters."""

    @staticmethod
    def validate(
        buyer_name: str,
        buyer_phone: str,
        buyer_email: str = "",
        budget: float = 0.0,
    ) -> dict[str, Any]:
        errors: list[str] = []
        if not buyer_name or len(buyer_name.strip()) < 2:
            errors.append("buyer_name: Must be at least 2 characters")
        if not INDIAN_PHONE_RE.match(buyer_phone):
            errors.append("buyer_phone: Must be a valid 10-digit Indian phone number")
        if buyer_email and "@" not in buyer_email:
            errors.append("buyer_email: Must be a valid email address")
        if budget < 0 or budget > MAX_PRICE:
            errors.append(f"budget: Must be between 0 and ₹{MAX_PRICE:,}")

        if errors:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"errors": errors},
            )
        return {
            "buyer_name": buyer_name.strip(),
            "buyer_phone": buyer_phone,
            "buyer_email": buyer_email.strip(),
            "budget": budget,
        }


class EnquiryCreateValidator:
    """Validate property enquiry parameters."""

    @staticmethod
    def validate(
        name: str,
        email: str,
        phone: str,
        message: str = "",
        enquirer_type: str = "buyer",
    ) -> dict[str, Any]:
        errors: list[str] = []
        if not name or len(name.strip()) < 2:
            errors.append("name: Must be at least 2 characters")
        if not INDIAN_PHONE_RE.match(phone):
            errors.append("phone: Must be a valid 10-digit Indian phone number")
        if email and "@" not in email:
            errors.append("email: Must be a valid email address")
        if enquirer_type not in VALID_ENQUIRER_TYPES:
            errors.append(f"enquirer_type: Must be one of: {', '.join(sorted(VALID_ENQUIRER_TYPES))}")

        if errors:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"errors": errors},
            )
        return {
            "name": name.strip(),
            "email": email.strip(),
            "phone": phone,
            "message": message.strip(),
            "enquirer_type": enquirer_type,
        }


class AgreementCreateValidator:
    """Validate rent agreement creation parameters."""

    @staticmethod
    def validate(
        rent_amount: float,
        security_deposit: float,
        lease_start: str,
        lease_end: str,
        notice_period_days: int = 30,
    ) -> dict[str, Any]:
        errors: list[str] = []
        if rent_amount < 100:
            errors.append("rent_amount: Monthly rent must be at least ₹100")
        if security_deposit < 0:
            errors.append("security_deposit: Must be non-negative")
        if security_deposit > rent_amount * 12:
            errors.append("security_deposit: Should not exceed 12 months rent")
        if not lease_start or len(lease_start) < 8:
            errors.append("lease_start: Must be a valid date (YYYY-MM-DD)")
        if not lease_end or len(lease_end) < 8:
            errors.append("lease_end: Must be a valid date (YYYY-MM-DD)")
        if notice_period_days < 0 or notice_period_days > 365:
            errors.append("notice_period_days: Must be between 0 and 365")

        if errors:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"errors": errors},
            )
        return {
            "rent_amount": rent_amount,
            "security_deposit": security_deposit,
            "lease_start": lease_start,
            "lease_end": lease_end,
            "notice_period_days": notice_period_days,
        }
