"""Export/Import — property data migration and bulk operations.

Supports:
  - Export properties to CSV and JSON formats
  - Import properties from CSV files (schema validation)
  - Bulk property creation from parsed data
  - Export statistics and asset summaries
"""

from __future__ import annotations

import csv
import io
import json
import logging
import time
from typing import Any

_log = logging.getLogger(__name__)

# ── Export Format ────────────────────────────────────────────────────────────

EXPORT_FIELDS = [
    "property_id", "title", "description", "property_type", "listing_type",
    "price", "city", "locality", "state", "pincode",
    "latitude", "longitude",
    "bedrooms", "bathrooms", "balconies",
    "carpet_area_sqft", "super_area_sqft", "plot_area_sqft",
    "furnishing", "facing_direction",
    "is_featured", "is_verified", "rera_number",
    "owner_id", "broker_id",
    "amenities", "listed_at", "views",
]

CSV_HEADER_MAP = {
    "property_id": "Property ID",
    "title": "Title",
    "price": "Price (INR)",
    "city": "City",
    "locality": "Locality",
    "property_type": "Property Type",
    "bedrooms": "Bedrooms",
    "bathrooms": "Bathrooms",
    "carpet_area_sqft": "Carpet Area (sq.ft)",
    "furnishing": "Furnishing",
    "latitude": "Latitude",
    "longitude": "Longitude",
    "is_featured": "Featured",
    "is_verified": "Verified",
    "description": "Description",
}

# ── Export Engine ────────────────────────────────────────────────────────────

def export_to_json(properties: list[Any]) -> str:
    """Export properties to a JSON string.

    Args:
        properties: List of PropertyDTO objects.

    Returns:
        Pretty-printed JSON string with metadata.
    """
    data = {
        "exported_at": time.time(),
        "exported_at_formatted": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
        "total_properties": len(properties),
        "properties": [],
    }

    for p in properties:
        entry: dict[str, Any] = {
            "property_id": p.property_id,
            "title": p.title,
            "description": p.description[:500] if p.description else "",
            "property_type": p.property_type,
            "listing_type": p.listing_type,
            "price": p.price,
            "city": p.city,
            "locality": p.locality,
            "latitude": p.latitude,
            "longitude": p.longitude,
            "bedrooms": p.bedrooms,
            "bathrooms": p.bathrooms,
            "balconies": p.balconies,
            "carpet_area_sqft": p.carpet_area_sqft,
            "super_area_sqft": p.super_area_sqft,
            "furnishing": p.furnishing,
            "is_featured": p.is_featured,
            "is_verified": p.is_verified,
            "amenities": p.amenities,
            "views": p.views,
        }
        # Only add non-empty optional fields
        if p.rera_number:
            entry["rera_number"] = p.rera_number
        if p.owner_id:
            entry["owner_id"] = p.owner_id
        data["properties"].append(entry)

    return json.dumps(data, indent=2, ensure_ascii=False)


def export_to_csv(properties: list[Any]) -> str:
    """Export properties to a CSV string.

    Args:
        properties: List of PropertyDTO objects.

    Returns:
        CSV string with BOM and header row.
    """
    output = io.StringIO()
    # BOM for Excel compatibility
    output.write("\ufeff")
    writer = csv.writer(output)

    # Header row (use friendly names)
    headers = [CSV_HEADER_MAP.get(f, f.replace("_", " ").title()) for f in EXPORT_FIELDS]
    writer.writerow(headers)

    for p in properties:
        amenities_str = "; ".join(p.amenities[:10]) if p.amenities else ""
        row = [
            p.property_id, p.title, p.description[:500], p.property_type, p.listing_type,
            p.price, p.city, p.locality, "", "",  # state, pincode
            p.latitude, p.longitude,
            p.bedrooms, p.bathrooms, p.balconies,
            p.carpet_area_sqft, p.super_area_sqft, p.plot_area_sqft,
            p.furnishing, p.facing_direction or "",
            "Yes" if p.is_featured else "No", "Yes" if p.is_verified else "No", p.rera_number or "",
            p.owner_id or "", "",
            amenities_str, p.listed_at, p.views,
        ]
        writer.writerow(row)

    return output.getvalue()


# ── Import Engine ────────────────────────────────────────────────────────────

def parse_csv_import(csv_content: str) -> tuple[list[dict[str, Any]], list[str]]:
    """Parse CSV content into property data dicts.

    Args:
        csv_content: Raw CSV string content.

    Returns:
        Tuple of (parsed_properties, error_messages).
    """
    reader = csv.DictReader(io.StringIO(csv_content))
    properties: list[dict[str, Any]] = []
    errors: list[str] = []
    row_num = 0

    for row in reader:
        row_num += 1
        try:
            prop = _parse_row(row)
            if prop:
                properties.append(prop)
        except (ValueError, KeyError) as exc:
            errors.append(f"Row {row_num}: {exc}")

    return properties, errors


def _parse_row(row: dict[str, str]) -> dict[str, Any] | None:
    """Parse a single CSV row into a property data dict."""
    # Find the mapped fields
    title = row.get("Title") or row.get("title") or ""
    city = row.get("City") or row.get("city") or ""
    if not title or not city:
        return None

    # Parse price - handle "₹" prefix and commas
    price_raw = row.get("Price (INR)") or row.get("price") or "0"
    price_raw = price_raw.replace("₹", "").replace(",", "").strip()
    try:
        price = float(price_raw)
    except (ValueError, TypeError):
        price = 0.0

    # Parse bedrooms
    bedrooms_raw = row.get("Bedrooms") or row.get("bedrooms") or "0"
    try:
        bedrooms = int(bedrooms_raw)
    except (ValueError, TypeError):
        bedrooms = 0

    # Parse area
    area_raw = row.get("Carpet Area (sq.ft)") or row.get("carpet_area_sqft") or "0"
    try:
        area = float(area_raw)
    except (ValueError, TypeError):
        area = 0.0

    # Parse lat/lng
    lat_raw = row.get("Latitude") or row.get("latitude") or "0"
    lng_raw = row.get("Longitude") or row.get("longitude") or "0"
    try:
        lat = float(lat_raw)
    except (ValueError, TypeError):
        lat = 0.0
    try:
        lng = float(lng_raw)
    except (ValueError, TypeError):
        lng = 0.0

    property_type = (row.get("Property Type") or row.get("property_type") or "apartment").lower()
    furnishing = (row.get("Furnishing") or row.get("furnishing") or "unfurnished").lower()
    locality = row.get("Locality") or row.get("locality") or ""
    bathrooms_raw = row.get("bathrooms") or "0"

    try:
        bathrooms = int(bathrooms_raw)
    except (ValueError, TypeError):
        bathrooms = bedrooms

    return {
        "title": title.strip()[:100],
        "description": row.get("Description", row.get("description", ""))[:1000],
        "property_type": property_type,
        "price": price,
        "city": city.strip(),
        "locality": locality.strip(),
        "bedrooms": bedrooms,
        "bathrooms": bathrooms,
        "carpet_area_sqft": area,
        "furnishing": furnishing,
        "latitude": lat,
        "longitude": lng,
        "owner_id": row.get("owner_id") or "import-user",
    }


def import_properties(
    parsed: list[dict[str, Any]],
    property_service: Any,
) -> tuple[int, list[str]]:
    """Import parsed properties into the platform.

    Args:
        parsed: List of property data dicts from parse_csv_import().
        property_service: PropertyService instance to create properties.

    Returns:
        Tuple of (created_count, error_messages).
    """
    created = 0
    errors: list[str] = []
    for i, data in enumerate(parsed):
        try:
            result = property_service.create_property(
                title=data["title"],
                description=data.get("description", ""),
                property_type=data.get("property_type", "apartment"),
                price=data.get("price", 0),
                city=data.get("city", ""),
                locality=data.get("locality", ""),
                owner_id=data.get("owner_id", "import"),
                bedrooms=data.get("bedrooms", 0),
                bathrooms=data.get("bathrooms", 0),
                carpet_area_sqft=data.get("carpet_area_sqft", 0),
            )
            if result:
                created += 1
        except Exception as exc:
            errors.append(f"Property {i + 1}: {exc}")

    _log.info("[RE] Imported %d/%d properties", created, len(parsed))
    return created, errors


# ── API Router ──────────────────────────────────────────────────────────────

def create_export_router(property_service: Any = None) -> Any:
    """Create a FastAPI router for export/import endpoints."""
    from fastapi import APIRouter, HTTPException, Query, Response

    router = APIRouter(prefix="/api/realestate/export", tags=["Real Estate Export/Import"])

    @router.get("/json")
    async def export_json(
        city: str = Query("", description="City filter"),
        property_service: Any = property_service,
    ):
        """Export properties as JSON."""
        if not property_service:
            raise HTTPException(status_code=503, detail="Property service not available")
        props = property_service.list_all()
        if city:
            props = [p for p in props if p.city.lower() == city.lower()]
        data = export_to_json(props)
        return Response(
            content=data,
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="properties_{city or "all"}.json"'},
        )

    @router.get("/csv")
    async def export_csv(
        city: str = Query("", description="City filter"),
        property_service: Any = property_service,
    ):
        """Export properties as CSV."""
        if not property_service:
            raise HTTPException(status_code=503, detail="Property service not available")
        props = property_service.list_all()
        if city:
            props = [p for p in props if p.city.lower() == city.lower()]
        data = export_to_csv(props)
        return Response(
            content=data,
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="properties_{city or "all"}.csv"'},
        )

    @router.post("/import")
    async def import_csv(
        csv_content: str = Query(..., description="CSV content"),
        property_service: Any = property_service,
    ):
        """Import properties from CSV content."""
        if not property_service:
            raise HTTPException(status_code=503, detail="Property service not available")
        parsed, parse_errors = parse_csv_import(csv_content)
        if not parsed:
            return {"success": False, "imported": 0, "parse_errors": parse_errors or ["No valid rows found"]}
        created, import_errors = import_properties(parsed, property_service)
        return {
            "success": True,
            "imported": created,
            "total_rows": len(parsed),
            "parse_errors": parse_errors,
            "import_errors": import_errors,
        }

    @router.get("/stats")
    async def export_stats(
        property_service: Any = property_service,
    ):
        """Get export statistics — total properties by city, avg prices, etc."""
        if not property_service:
            raise HTTPException(status_code=503, detail="Property service not available")
        props = property_service.list_all()
        cities: dict[str, dict[str, Any]] = {}
        for p in props:
            if p.city not in cities:
                cities[p.city] = {"count": 0, "total_price": 0, "total_area": 0}
            cities[p.city]["count"] += 1
            cities[p.city]["total_price"] += p.price
            cities[p.city]["total_area"] += p.carpet_area_sqft or 1

        city_stats = {}
        for city, stats in cities.items():
            city_stats[city] = {
                "count": stats["count"],
                "avg_price": round(stats["total_price"] / stats["count"]),
                "avg_area_sqft": round(stats["total_area"] / stats["count"]),
            }

        return {
            "total_properties": len(props),
            "total_cities": len(cities),
            "total_locations": len(set(p.locality for p in props if p.locality)),
            "by_city": city_stats,
        }

    return router
