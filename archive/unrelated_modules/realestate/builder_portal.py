"""Builder/Developer Portal — project management, unit tracking, RERA compliance.

Features:
  - Project creation and lifecycle management
  - Unit inventory tracking (per-project)
  - RERA registration and compliance dashboard
  - Milestone tracking (possession dates, approvals)
  - Sales pipeline per project
  - Bulk property upload for builders
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

class ProjectStatus(Enum):
    PRE_LAUNCH = "pre_launch"
    LAUNCHED = "launched"
    ONGOING = "ongoing"
    COMPLETED = "completed"
    DELAYED = "delayed"
    CANCELLED = "cancelled"


class UnitStatus(Enum):
    AVAILABLE = "available"
    BOOKED = "booked"
    SOLD = "sold"
    BLOCKED = "blocked"


# ── Domain Models ────────────────────────────────────────────────────────────

@dataclass
class ProjectMilestone:
    """A project milestone (e.g., foundation, possession, OC)."""
    milestone_id: str = ""
    name: str = ""
    description: str = ""
    planned_date: str = ""
    achieved_date: str = ""
    is_completed: bool = False
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__


@dataclass
class BuilderUnit:
    """A single unit/apartment within a builder project."""
    unit_id: str = ""
    project_id: str = ""
    unit_number: str = ""
    floor_number: int = 0
    unit_type: str = "2BHK"  # 1BHK, 2BHK, 3BHK, 4BHK, Penthouse, Studio
    carpet_area_sqft: float = 0.0
    super_area_sqft: float = 0.0
    price: Decimal = Decimal("0")
    status: UnitStatus = UnitStatus.AVAILABLE
    booking_date: float = 0.0
    buyer_id: str = ""
    buyer_name: str = ""
    facing: str = ""
    balcony: bool = False
    created_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "unit_id": self.unit_id,
            "project_id": self.project_id,
            "unit_number": self.unit_number,
            "floor_number": self.floor_number,
            "unit_type": self.unit_type,
            "carpet_area_sqft": self.carpet_area_sqft,
            "super_area_sqft": self.super_area_sqft,
            "price": float(self.price),
            "status": self.status.value,
            "booking_date": self.booking_date,
            "buyer_id": self.buyer_id,
            "buyer_name": self.buyer_name,
            "facing": self.facing,
            "balcony": self.balcony,
        }


@dataclass
class BuilderProject:
    """A real estate development project managed by a builder/developer."""
    project_id: str = ""
    developer_id: str = ""
    developer_name: str = ""
    name: str = ""
    description: str = ""
    location_city: str = ""
    location_locality: str = ""
    location_address: str = ""

    # RERA
    rera_registration: str = ""
    rera_approved_date: str = ""
    approval_authority: str = ""

    # Project details
    total_units: int = 0
    available_units: int = 0
    sold_units: int = 0
    total_area_sqft: float = 0.0

    # Pricing
    price_range_min: Decimal = Decimal("0")
    price_range_max: Decimal = Decimal("0")
    price_per_sqft_start: float = 0.0

    # Dates
    status: ProjectStatus = ProjectStatus.PRE_LAUNCH
    launch_date: str = ""
    possession_date: str = ""  # Expected possession
    created_at: float = 0.0
    updated_at: float = 0.0

    # Media
    images: list[str] = field(default_factory=list)
    brochure_url: str = ""
    video_url: str = ""

    # Amenities
    amenities: list[str] = field(default_factory=list)

    # Milestones
    milestones: list[ProjectMilestone] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "developer_id": self.developer_id,
            "developer_name": self.developer_name,
            "name": self.name,
            "description": self.description[:200],
            "location_city": self.location_city,
            "location_locality": self.location_locality,
            "rera_registration": self.rera_registration,
            "status": self.status.value,
            "total_units": self.total_units,
            "available_units": self.available_units,
            "sold_units": self.sold_units,
            "total_area_sqft": self.total_area_sqft,
            "price_range_min": float(self.price_range_min),
            "price_range_max": float(self.price_range_max),
            "price_per_sqft_start": self.price_per_sqft_start,
            "launch_date": self.launch_date,
            "possession_date": self.possession_date,
            "brochure_url": self.brochure_url,
            "amenities": self.amenities[:15],
            "milestones": len(self.milestones),
            "created_at": self.created_at,
        }


# ── Builder Portal Engine ───────────────────────────────────────────────────

class BuilderPortal:
    """Manages builder projects, units, and compliance."""

    def __init__(self) -> None:
        self._projects: dict[str, BuilderProject] = {}
        self._units: dict[str, list[BuilderUnit]] = {}  # project_id → units

    # ── Project Management ────────────────────────────────────────────────

    def create_project(
        self,
        developer_id: str,
        developer_name: str,
        name: str,
        description: str,
        city: str,
        locality: str,
        total_units: int,
        possession_date: str,
        rera_registration: str = "",
        price_per_sqft_start: float = 0.0,
        amenities: list[str] | None = None,
    ) -> BuilderProject:
        """Create a new builder project."""
        now = time.time()
        project = BuilderProject(
            project_id=f"BP-{int(now)}-{random.randint(100, 999)}",
            developer_id=developer_id,
            developer_name=developer_name,
            name=name,
            description=description,
            location_city=city,
            location_locality=locality,
            total_units=total_units,
            available_units=total_units,
            status=ProjectStatus.PRE_LAUNCH,
            rera_registration=rera_registration,
            possession_date=possession_date,
            price_per_sqft_start=price_per_sqft_start,
            amenities=amenities or [],
            created_at=now,
            updated_at=now,
        )
        self._projects[project.project_id] = project
        self._units[project.project_id] = []
        _log.info("[RE] Builder project created: %s — %s (%d units)",
                  project.project_id, name, total_units)
        return project

    def get_project(self, project_id: str) -> BuilderProject | None:
        return self._projects.get(project_id)

    def list_projects(self, developer_id: str | None = None) -> list[BuilderProject]:
        projects = list(self._projects.values())
        if developer_id:
            projects = [p for p in projects if p.developer_id == developer_id]
        projects.sort(key=lambda p: p.created_at, reverse=True)
        return projects

    def update_project_status(self, project_id: str, status: str) -> bool:
        try:
            s = ProjectStatus(status)
        except ValueError:
            return False
        project = self._projects.get(project_id)
        if not project:
            return False
        project.status = s
        project.updated_at = time.time()
        return True

    # ── Unit Management ──────────────────────────────────────────────────

    def add_units(
        self, project_id: str, units: list[dict[str, Any]]
    ) -> list[BuilderUnit]:
        """Add units to a project (bulk upload from builder)."""
        project = self._projects.get(project_id)
        if not project:
            return []

        new_units: list[BuilderUnit] = []
        for u in units:
            unit = BuilderUnit(
                unit_id=f"U-{project_id}-{u.get('unit_number', random.randint(1, 999))}",
                project_id=project_id,
                unit_number=str(u.get("unit_number", "")),
                floor_number=int(u.get("floor_number", 0)),
                unit_type=str(u.get("unit_type", "2BHK")),
                carpet_area_sqft=float(u.get("carpet_area_sqft", 0)),
                super_area_sqft=float(u.get("super_area_sqft", u.get("carpet_area_sqft", 0) * 1.25)),
                price=Decimal(str(u.get("price", 0))),
                facing=str(u.get("facing", "")),
                balcony=bool(u.get("balcony", False)),
                status=UnitStatus.AVAILABLE,
                created_at=time.time(),
            )
            new_units.append(unit)

        self._units.setdefault(project_id, []).extend(new_units)

        # Update price range
        prices = [u.price for u in self._units[project_id] if u.price > Decimal("0")]
        if prices:
            project.price_range_min = min(prices)
            project.price_range_max = max(prices)

        project.updated_at = time.time()
        _log.info("[RE] %d units added to project %s", len(new_units), project_id)
        return new_units

    def get_units(self, project_id: str, status: str | None = None) -> list[BuilderUnit]:
        units = list(self._units.get(project_id, []))
        if status:
            try:
                s = UnitStatus(status)
                units = [u for u in units if u.status == s]
            except ValueError:
                pass
        return units

    def book_unit(self, unit_id: str, buyer_id: str, buyer_name: str, project_id: str) -> bool:
        """Mark a unit as booked/sold."""
        for unit in self._units.get(project_id, []):
            if unit.unit_id == unit_id and unit.status == UnitStatus.AVAILABLE:
                unit.status = UnitStatus.BOOKED
                unit.buyer_id = buyer_id
                unit.buyer_name = buyer_name
                unit.booking_date = time.time()

                project = self._projects.get(project_id)
                if project:
                    project.available_units = max(0, project.available_units - 1)
                    project.sold_units += 1
                    project.updated_at = time.time()
                return True
        return False

    # ── Compliance Dashboard ─────────────────────────────────────────────

    def check_rera_compliance(self, developer_id: str) -> dict[str, Any]:
        """Check RERA compliance status for a developer's projects."""
        projects = self.list_projects(developer_id)
        total = len(projects)
        rera_registered = sum(1 for p in projects if bool(p.rera_registration))
        on_track = sum(1 for p in projects if p.status in
                       (ProjectStatus.COMPLETED, ProjectStatus.LAUNCHED))
        delayed = sum(1 for p in projects if p.status == ProjectStatus.DELAYED)

        return {
            "developer_id": developer_id,
            "total_projects": total,
            "rera_registered": rera_registered,
            "rera_compliance_pct": round(rera_registered / max(total, 1) * 100, 1),
            "on_track": on_track,
            "delayed": delayed,
            "total_units_launched": sum(p.total_units for p in projects),
            "total_sold": sum(p.sold_units for p in projects),
            "total_booked": sum(p.sold_units for p in projects),
            "sell_through_rate_pct": round(
                sum(p.sold_units for p in projects) / max(sum(p.total_units for p in projects), 1) * 100, 1
            ),
            "total_available": sum(
                max(p.total_units - p.sold_units, 0) for p in projects
            ),
        }

    def get_stats(self) -> dict[str, Any]:
        """Get overall builder portal statistics."""
        projects = list(self._projects.values())
        all_units: list[BuilderUnit] = []
        for u_list in self._units.values():
            all_units.extend(u_list)

        return {
            "total_projects": len(projects),
            "total_units": len(all_units),
            "sold_units": sum(1 for u in all_units if u.status in (UnitStatus.SOLD, UnitStatus.BOOKED)),
            "available_units": sum(1 for u in all_units if u.status == UnitStatus.AVAILABLE),
            "developers": len(set(p.developer_id for p in projects)),
            "rera_registered_projects": sum(1 for p in projects if bool(p.rera_registration)),
            "completed_projects": sum(1 for p in projects if p.status == ProjectStatus.COMPLETED),
            "delayed_projects": sum(1 for p in projects if p.status == ProjectStatus.DELAYED),
        }


# ── API Router ──────────────────────────────────────────────────────────────

def create_builder_router(portal: BuilderPortal | None = None) -> Any:
    """Create a FastAPI router for builder/developer portal endpoints."""
    from fastapi import APIRouter, Body, HTTPException, Query

    bp = portal or BuilderPortal()
    router = APIRouter(prefix="/api/realestate/builder", tags=["Real Estate Builder"])

    @router.post("/projects")
    async def create_project(
        developer_id: str = Query(...),
        developer_name: str = Query(...),
        name: str = Query(...),
        description: str = Query(""),
        city: str = Query(...),
        locality: str = Query(""),
        total_units: int = Query(1, ge=1),
        possession_date: str = Query(""),
        rera_registration: str = Query(""),
        price_per_sqft_start: float = Query(0.0),
        amenities: str = Query(""),
    ):
        project = bp.create_project(
            developer_id=developer_id, developer_name=developer_name,
            name=name, description=description, city=city, locality=locality,
            total_units=total_units, possession_date=possession_date,
            rera_registration=rera_registration,
            price_per_sqft_start=price_per_sqft_start,
            amenities=[a.strip() for a in amenities.split(",") if a.strip()] if amenities else None,
        )
        return {"project": project.to_dict()}

    @router.get("/projects")
    async def list_projects(developer_id: str = Query("")):
        projects = bp.list_projects(developer_id or None)
        return {"projects": [p.to_dict() for p in projects]}

    @router.get("/projects/{project_id}")
    async def get_project(project_id: str):
        project = bp.get_project(project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        return {"project": project.to_dict()}

    @router.post("/projects/{project_id}/units")
    async def add_units(project_id: str):
        """Stub for bulk unit upload — in production, use multipart JSON body."""
        return {"message": "Use POST /api/realestate/builder/units/bulk for batch upload"}

    @router.post("/projects/{project_id}/units/bulk")
    async def add_units_bulk(
        project_id: str,
        units: list[dict[str, Any]] = Body(..., description="Array of unit dicts"),
    ):
        project = bp.get_project(project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        added = bp.add_units(project_id, units)
        return {"added": len(added), "units": [u.to_dict() for u in added]}

    @router.get("/projects/{project_id}/units")
    async def get_units(project_id: str, status: str = Query("")):
        units = bp.get_units(project_id, status or None)
        return {"units": [u.to_dict() for u in units]}

    @router.post("/projects/{project_id}/units/{unit_id}/book")
    async def book_unit(
        project_id: str, unit_id: str,
        buyer_id: str = Query(...),
        buyer_name: str = Query(...),
    ):
        success = bp.book_unit(unit_id, buyer_id, buyer_name, project_id)
        if not success:
            raise HTTPException(status_code=400, detail="Unit not available")
        return {"success": True, "message": f"Unit {unit_id} booked for {buyer_name}"}

    @router.put("/projects/{project_id}/status")
    async def update_project_status(project_id: str, status: str = Query(...)):
        if not bp.update_project_status(project_id, status):
            raise HTTPException(status_code=400, detail="Invalid status or project not found")
        return {"success": True}

    @router.get("/compliance/{developer_id}")
    async def compliance_check(developer_id: str):
        return bp.check_rera_compliance(developer_id)

    @router.get("/stats")
    async def portal_stats():
        return bp.get_stats()

    return router
