"""RERA Compliance Checker — Verify builder registrations and property compliance.

RERA (Real Estate Regulatory Authority) is India's real estate regulator.
This module provides:
  - RERA number format validation
  - Builder registration status tracking
  - Property RERA compliance checks
  - Compliance dashboard API
  - Warning/blocked lists for non-compliant entities

RERA number format: RERA-{STATE}-{YEAR}-{SEQ} (e.g., RERA-MH-2024-00123)
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

_log = logging.getLogger(__name__)

_TEMPLATES_DIR = None


def _get_templates() -> Jinja2Templates:
    global _TEMPLATES_DIR
    if _TEMPLATES_DIR is None:
        from pathlib import Path
        _TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates" / "realestate"
        _TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    return Jinja2Templates(directory=str(_TEMPLATES_DIR))


# ═══════════════════════════════════════════════════════════════════════════════
# RERA Number Format
# ═══════════════════════════════════════════════════════════════════════════════

# Indian state codes for RERA
RERA_STATE_CODES = {
    "MH": "Maharashtra", "KA": "Karnataka", "DL": "Delhi",
    "HR": "Haryana", "UP": "Uttar Pradesh", "TN": "Tamil Nadu",
    "TS": "Telangana", "WB": "West Bengal", "GJ": "Gujarat",
    "RJ": "Rajasthan", "MP": "Madhya Pradesh", "BR": "Bihar",
    "PB": "Punjab", "UK": "Uttarakhand", "OR": "Odisha",
    "AP": "Andhra Pradesh", "KL": "Kerala", "JH": "Jharkhand",
    "CG": "Chhattisgarh", "AS": "Assam", "GA": "Goa",
}

# RERA number regex pattern
RERA_PATTERN = re.compile(r"^RERA[-/]?([A-Z]{2})[-/]?(\d{4})[-/]?(\d{1,6})$")


@dataclass
class RERARegistration:
    """A verified RERA registration record."""
    rera_number: str = ""
    state: str = ""
    state_name: str = ""
    registration_year: int = 0
    sequence_number: int = 0
    builder_name: str = ""
    project_name: str = ""
    project_address: str = ""
    status: str = "active"  # active, suspended, revoked, expired
    registration_date: str = ""
    validity_until: str = ""
    is_verified: bool = False
    last_checked: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "rera_number": self.rera_number,
            "state": self.state,
            "state_name": self.state_name,
            "registration_year": self.registration_year,
            "builder_name": self.builder_name,
            "project_name": self.project_name,
            "status": self.status,
            "registration_date": self.registration_date,
            "validity_until": self.validity_until,
            "is_verified": self.is_verified,
            "last_checked": self.last_checked,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# RERA Compliance Engine
# ═══════════════════════════════════════════════════════════════════════════════

class RERAComplianceEngine:
    """Verifies RERA registrations and tracks compliance status.

    In production, this would call the state RERA authority APIs.
    This implementation uses format validation + mock verification
    that demonstrates the full compliance workflow.
    """

    def __init__(self) -> None:
        # In-memory registry of verified RERA numbers
        self._registrations: dict[str, RERARegistration] = {}
        # Common mock builders for demo
        self._seed_mock_data()

    def _seed_mock_data(self) -> None:
        """Seed some mock RERA registrations for demo purposes."""
        mock_builders = [
            ("RERA-MH-2024-00123", "MH", 2024, 123, "ABC Builders Pvt Ltd", "Green Acres Phase 2", "Andheri, Mumbai", "active"),
            ("RERA-MH-2024-00456", "MH", 2024, 456, "Prestige Developers", "Prestige Lakeside", "Whitefield, Bangalore", "active"),
            ("RERA-KA-2023-00789", "KA", 2023, 789, "Brigade Group", "Brigade Golden Triangle", "Electronic City, Bangalore", "active"),
            ("RERA-DL-2024-00321", "DL", 2024, 321, "DLF Builders", "DLF The Crest", "Dwarka, Delhi", "active"),
            ("RERA-UP-2023-00111", "UP", 2023, 111, "Supertech Limited", "Supertech Eco Village", "Sector 137, Noida", "suspended"),
            ("RERA-HR-2024-00555", "HR", 2024, 555, "Godrej Properties", "Godrej The Isles", "Golf Course Road, Gurgaon", "active"),
            ("RERA-MH-2022-00777", "MH", 2022, 777, "Lodha Group", "Lodha Palava", "Dombivli, Thane", "active"),
        ]
        for num, state, year, seq, builder, project, addr, status in mock_builders:
            self._registrations[num] = RERARegistration(
                rera_number=num,
                state=state,
                state_name=RERA_STATE_CODES.get(state, "Unknown"),
                registration_year=year,
                sequence_number=seq,
                builder_name=builder,
                project_name=project,
                project_address=addr,
                status=status,
                registration_date=f"{year}-01-15",
                validity_until=f"{year + 5}-12-31",
                is_verified=True,
                last_checked=time.time(),
            )

    # ── Validation ────────────────────────────────────────────────────────

    @staticmethod
    def validate_format(rera_number: str) -> dict[str, Any] | None:
        """Validate RERA number format.

        Returns parsed components or None if invalid.
        """
        rera_number = rera_number.strip().upper()
        match = RERA_PATTERN.match(rera_number)
        if not match:
            return None
        state_code = match.group(1)
        if state_code not in RERA_STATE_CODES:
            return None
        return {
            "rera_number": f"RERA-{state_code}-{match.group(2)}-{match.group(3)}",
            "state": state_code,
            "state_name": RERA_STATE_CODES[state_code],
            "year": int(match.group(2)),
            "sequence": int(match.group(3)),
        }

    # ── Verification ──────────────────────────────────────────────────────

    def verify(self, rera_number: str) -> RERARegistration:
        """Verify a RERA registration number.

        Returns the registration record. If not found in local registry,
        returns a format-validated record with is_verified=False.
        """
        parsed = self.validate_format(rera_number)
        if not parsed:
            raise ValueError(f"Invalid RERA number format: {rera_number}")

        existing = self._registrations.get(parsed["rera_number"])
        if existing:
            existing.last_checked = time.time()
            return existing

        # Format valid but not in registry — return unverified
        return RERARegistration(
            rera_number=parsed["rera_number"],
            state=parsed["state"],
            state_name=parsed["state_name"],
            registration_year=parsed["year"],
            sequence_number=parsed["sequence"],
            is_verified=False,
            last_checked=time.time(),
        )

    def register_builder(
        self,
        rera_number: str,
        builder_name: str,
        project_name: str,
        project_address: str = "",
    ) -> RERARegistration:
        """Register a builder/project with a validated RERA number."""
        parsed = self.validate_format(rera_number)
        if not parsed:
            raise ValueError(f"Invalid RERA number format: {rera_number}")

        reg = RERARegistration(
            rera_number=parsed["rera_number"],
            state=parsed["state"],
            state_name=parsed["state_name"],
            registration_year=parsed["year"],
            sequence_number=parsed["sequence"],
            builder_name=builder_name,
            project_name=project_name,
            project_address=project_address,
            status="active",
            registration_date=time.strftime("%Y-%m-%d"),
            validity_until=f"{parsed['year'] + 5}-12-31",
            is_verified=True,
            last_checked=time.time(),
        )
        self._registrations[parsed["rera_number"]] = reg
        return reg

    # ── Compliance Checks ─────────────────────────────────────────────────

    def check_property_compliance(
        self,
        property_obj: Any,
        builder_portal: Any = None,
    ) -> dict[str, Any]:
        """Check compliance for a property.

        Checks:
          1. RERA number format validity
          2. RERA registration status (active/suspended/revoked)
          3. Builder registration in builder portal (if available)
          4. Project status in builder portal (if available)
          5. Overall compliance score
        """
        rera = getattr(property_obj, "rera_number", "") or ""
        if not rera:
            return {"status": "no_rera", "score": 0, "checks": {"rera_format": False}, "recommendations": ["RERA number not provided"]}

        # Check format
        parsed = self.validate_format(rera)
        if not parsed:
            return {"status": "invalid_format", "score": 0, "checks": {"rera_format": False}, "recommendations": ["Invalid RERA number format"]}

        # Check registration
        registration = self.verify(rera)
        checks = {"rera_format": True, "rera_registered": registration.is_verified}

        score = 0
        if registration.is_verified:
            score += 50
        if registration.status == "active":
            score += 30
        elif registration.status == "suspended":
            score -= 20
        elif registration.status == "revoked":
            score -= 50

        # Check builder portal
        builder_ok = False
        if builder_portal and hasattr(builder_portal, "check_rera_compliance"):
            try:
                builder_report = builder_portal.check_rera_compliance("")  # placeholder
                builder_ok = builder_report.get("rera_compliance_pct", 0) > 50
                checks["builder_compliance"] = builder_ok
                if builder_ok:
                    score += 20
            except Exception:
                pass

        recommendations = []
        if not registration.is_verified:
            recommendations.append("RERA number not verified in official registry")
        if registration.status == "suspended":
            recommendations.append("Builder's RERA registration is SUSPENDED — proceed with caution")
        if registration.status == "revoked":
            recommendations.append("Builder's RERA registration is REVOKED — do not proceed")
        if score < 50:
            recommendations.append("Overall compliance score is low — verify before proceeding")

        status = "compliant" if score >= 70 else ("warning" if score >= 30 else "non_compliant")

        return {
            "status": status,
            "score": min(100, max(0, score)),
            "checks": checks,
            "registration": registration.to_dict(),
            "recommendations": recommendations,
            "last_checked": time.time(),
        }

    def get_compliance_stats(self) -> dict[str, Any]:
        """Get overall compliance statistics."""
        total = len(self._registrations)
        active = sum(1 for r in self._registrations.values() if r.status == "active")
        suspended = sum(1 for r in self._registrations.values() if r.status == "suspended")
        revoked = sum(1 for r in self._registrations.values() if r.status == "revoked")
        expired = sum(1 for r in self._registrations.values() if r.status == "expired")

        return {
            "total_registrations": total,
            "active": active,
            "suspended": suspended,
            "revoked": revoked,
            "expired": expired,
            "compliance_rate": round(active / total * 100, 1) if total > 0 else 0.0,
            "states_covered": len(set(r.state for r in self._registrations.values())),
        }

    def get_registrations(self, state: str | None = None) -> list[dict[str, Any]]:
        """Get all registrations, optionally filtered by state."""
        regs = list(self._registrations.values())
        if state:
            regs = [r for r in regs if r.state == state.upper()]
        return [r.to_dict() for r in regs]


# ═══════════════════════════════════════════════════════════════════════════════
# Singleton
# ═══════════════════════════════════════════════════════════════════════════════

_rera_instance: RERAComplianceEngine | None = None


def get_rera_engine() -> RERAComplianceEngine:
    global _rera_instance
    if _rera_instance is None:
        _rera_instance = RERAComplianceEngine()
    return _rera_instance


# ═══════════════════════════════════════════════════════════════════════════════
# API Router
# ═══════════════════════════════════════════════════════════════════════════════

def create_rera_router() -> APIRouter:
    """Create the RERA compliance API router."""
    router = APIRouter(prefix="/api/realestate/rera", tags=["Real Estate RERA"])
    engine = get_rera_engine()

    @router.get("/verify")
    async def verify_rera(rera_number: str = Query(..., description="RERA registration number")):
        """Verify a RERA registration number."""
        try:
            result = engine.verify(rera_number)
            return {"success": True, "registration": result.to_dict()}
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @router.post("/register")
    async def register_builder(
        rera_number: str = Query(...),
        builder_name: str = Query(...),
        project_name: str = Query(...),
        project_address: str = Query(""),
    ):
        """Register a builder/project with RERA number."""
        try:
            result = engine.register_builder(rera_number, builder_name, project_name, project_address)
            return {"success": True, "registration": result.to_dict()}
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @router.get("/validate-format")
    async def validate_rera_format(rera_number: str = Query(...)):
        """Validate the format of a RERA number without verification."""
        parsed = RERAComplianceEngine.validate_format(rera_number)
        if not parsed:
            raise HTTPException(status_code=400, detail="Invalid RERA number format")
        return {"success": True, "valid": True, "parsed": parsed}

    @router.get("/check")
    async def check_compliance(property_id: str = Query("", description="Property ID to check")):
        """Check RERA compliance for a property."""
        # Try to get property if property_service is wired
        from realestate.application.services import create_default_services
        svc = create_default_services()
        ps = svc["property_service"]
        prop = ps.get_property(property_id) if property_id else None
        if property_id and not prop:
            raise HTTPException(status_code=404, detail="Property not found")
        result = engine.check_property_compliance(prop) if prop else {"status": "no_property", "score": 0, "checks": {}, "recommendations": ["No property provided"]}
        return {"success": True, "compliance": result}

    @router.get("/stats")
    async def compliance_stats():
        """Get RERA compliance statistics."""
        return {"success": True, "stats": engine.get_compliance_stats()}

    @router.get("/registrations")
    async def list_registrations(state: str = Query("", description="Filter by state code (e.g., MH, KA)")):
        """List all RERA registrations, optionally filtered by state."""
        return {"success": True, "registrations": engine.get_registrations(state or None)}

    return router


# ╀═════════════════════════════════════════════════════════════════════════════
# HTML Page Router
# ═══════════════════════════════════════════════════════════════════════════════

def create_rera_page_router() -> APIRouter:
    """Create router for the RERA compliance dashboard page."""
    router = APIRouter(tags=["Real Estate Pages"])
    templates = _get_templates()

    @router.get("/realestate/rera", response_class=HTMLResponse)
    async def rera_dashboard(request: Request):
        """RERA compliance dashboard page."""
        return templates.TemplateResponse(
            request=request,
            name="rera_dashboard.html",
            context={},
        )

    return router
