"""SQLite-backed PropertyRepository implementation.

Provides persistent storage for properties using SQLite.
Supports all PropertyRepository interface methods and includes
automatic schema creation and migration.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from decimal import Decimal
from pathlib import Path
from typing import Any

from realestate.domain.models import (
    Address,
    Amenities,
    FurnishingStatus,
    ListingType,
    Location,
    Property,
    PropertyType,
    TransactionType,
)
from realestate.infrastructure.repository import PropertyRepository

_log = logging.getLogger(__name__)

# ── Default database path ────────────────────────────────────────────────────

DEFAULT_DB_PATH = Path("db/realestate.db")


# ── SQLite Repository ────────────────────────────────────────────────────────

class SQLitePropertyRepository(PropertyRepository):
    """SQLite-backed property repository with automatic schema management.

    Thread-safe using a per-thread connection pool pattern with a write lock.
    Creates the database and schema automatically on first use.

    Schema:
        properties (
            property_id TEXT PRIMARY KEY,
            title TEXT,
            description TEXT,
            price_cents INTEGER,
            data_json TEXT  -- all other fields serialized as JSON
        )
    """

    def __init__(self, db_path: str | Path | None = None) -> None:
        self._db_path = Path(db_path or DEFAULT_DB_PATH)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._write_lock = threading.Lock()
        self._init_schema()

    def _get_conn(self) -> sqlite3.Connection:
        """Get a thread-local database connection."""
        if not hasattr(self._local, "conn") or self._local.conn is None:
            conn = sqlite3.connect(str(self._db_path), timeout=10)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            self._local.conn = conn
        return self._local.conn

    def _init_schema(self) -> None:
        """Create the properties table if it doesn't exist."""
        conn = self._get_conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS properties (
                property_id TEXT PRIMARY KEY,
                title TEXT NOT NULL DEFAULT '',
                description TEXT NOT NULL DEFAULT '',
                price_cents INTEGER NOT NULL DEFAULT 0,
                city TEXT NOT NULL DEFAULT '',
                locality TEXT NOT NULL DEFAULT '',
                property_type TEXT NOT NULL DEFAULT 'apartment',
                bedrooms INTEGER NOT NULL DEFAULT 0,
                bathrooms INTEGER NOT NULL DEFAULT 0,
                carpet_area_sqft REAL NOT NULL DEFAULT 0.0,
                owner_id TEXT NOT NULL DEFAULT '',
                is_active INTEGER NOT NULL DEFAULT 1,
                is_featured INTEGER NOT NULL DEFAULT 0,
                is_verified INTEGER NOT NULL DEFAULT 0,
                rera_number TEXT NOT NULL DEFAULT '',
                listed_at REAL NOT NULL DEFAULT 0.0,
                updated_at REAL NOT NULL DEFAULT 0.0,
                views INTEGER NOT NULL DEFAULT 0,
                slug TEXT NOT NULL DEFAULT '',
                data_json TEXT NOT NULL DEFAULT '{}'
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_properties_city
            ON properties(city)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_properties_type
            ON properties(property_type)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_properties_active
            ON properties(is_active)
        """)
        conn.commit()

    def save(self, prop: Property) -> Property:
        """Insert or replace a property in the database."""
        data_json = json.dumps({
            "listing_type": prop.listing_type.value,
            "transaction_type": prop.transaction_type.value,
            "state": prop.location.address.state,
            "pincode": prop.location.address.pincode,
            "latitude": prop.location.address.latitude,
            "longitude": prop.location.address.longitude,
            "balconies": prop.amenities.balconies,
            "super_area_sqft": float(prop.amenities.super_area_sqft),
            "plot_area_sqft": float(prop.amenities.plot_area_sqft),
            "furnishing": prop.amenities.furnishing.value,
            "facing_direction": prop.amenities.facing_direction,
            "amenities_list": prop.amenities.amenities_list,
            "gated_community": prop.amenities.gated_community,
            "power_backup": prop.amenities.power_backup,
            "water_supply_24x7": prop.amenities.water_supply_24x7,
            "swimming_pool": prop.amenities.swimming_pool,
            "gym": prop.amenities.gym,
            "vaastu_compliant": prop.amenities.vaastu_compliant,
            "loan_available": prop.amenities.loan_available,
            "nearby_transit": prop.location.nearby_transit,
            "walk_score": prop.location.walk_score,
            "transit_score": prop.location.transit_score,
            "aqi_rating": prop.location.aqi_rating,
            "media_urls": [m.to_dict() for m in prop.media],
            "full_address": prop.location.address.full_address,
            "broker_id": prop.broker_id,
            "featured_until": prop.expiry_date,
            "verification_date": prop.verification_date,
        })

        with self._write_lock:
            conn = self._get_conn()
            conn.execute("""
                INSERT OR REPLACE INTO properties (
                    property_id, title, description, price_cents,
                    city, locality, property_type,
                    bedrooms, bathrooms, carpet_area_sqft,
                    owner_id, is_active, is_featured, is_verified,
                    rera_number, listed_at, updated_at, views, slug,
                    data_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                prop.property_id, prop.title, prop.description,
                int(float(prop.price) * 100),
                prop.location.address.city, prop.location.address.locality,
                prop.property_type.value,
                prop.amenities.bedrooms, prop.amenities.bathrooms,
                float(prop.amenities.carpet_area_sqft),
                prop.owner_id, int(prop.is_active), int(prop.is_featured),
                int(prop.is_verified),
                prop.rera_number, prop.listed_at, time.time(),
                prop.views, prop.slug, data_json,
            ))
            conn.commit()
        return prop

    def get(self, property_id: str) -> Property | None:
        """Get a property by ID."""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM properties WHERE property_id = ?",
            (property_id,),
        ).fetchone()
        return self._row_to_property(row) if row else None

    def delete(self, property_id: str) -> bool:
        """Delete a property by ID. Returns True if deleted."""
        with self._write_lock:
            conn = self._get_conn()
            cursor = conn.execute(
                "DELETE FROM properties WHERE property_id = ?",
                (property_id,),
            )
            conn.commit()
            return cursor.rowcount > 0

    def list_all(self) -> list[Property]:
        """List all properties."""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM properties ORDER BY listed_at DESC"
        ).fetchall()
        return [self._row_to_property(r) for r in rows if r is not None]

    def count(self) -> int:
        """Get total property count."""
        conn = self._get_conn()
        row = conn.execute("SELECT COUNT(*) as cnt FROM properties").fetchone()
        return row["cnt"] if row else 0

    def search(self, **filters: Any) -> list[Property]:
        """Search properties by field values."""
        conn = self._get_conn()
        conditions: list[str] = []
        params: list[Any] = []

        for key, value in filters.items():
            if value is not None:
                if key == "city":
                    conditions.append("LOWER(city) = LOWER(?)")
                    params.append(value)
                elif key == "property_type":
                    conditions.append("property_type = ?")
                    params.append(value)
                elif key == "is_active":
                    conditions.append("is_active = ?")
                    params.append(int(value))
                elif key == "owner_id":
                    conditions.append("owner_id = ?")
                    params.append(value)
                else:
                    # Fall back to JSON data_json field
                    conditions.append("data_json LIKE ?")
                    params.append(f'%"{key}": "{value}"%')

        where = " AND ".join(conditions) if conditions else "1=1"
        rows = conn.execute(
            f"SELECT * FROM properties WHERE {where} ORDER BY listed_at DESC",
            params,
        ).fetchall()
        return [self._row_to_property(r) for r in rows if r is not None]

    def search_by_city(self, city: str) -> list[Property]:
        """Search properties by city."""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM properties WHERE LOWER(city) = LOWER(?) ORDER BY listed_at DESC",
            (city,),
        ).fetchall()
        return [self._row_to_property(r) for r in rows]

    def get_by_owner(self, owner_id: str) -> list[Property]:
        """Get all properties for an owner."""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM properties WHERE owner_id = ? ORDER BY listed_at DESC",
            (owner_id,),
        ).fetchall()
        return [self._row_to_property(r) for r in rows]

    def update_views(self, property_id: str) -> None:
        """Increment view count for a property."""
        with self._write_lock:
            conn = self._get_conn()
            conn.execute(
                "UPDATE properties SET views = views + 1 WHERE property_id = ?",
                (property_id,),
            )
            conn.commit()

    def get_map_data(self, city: str | None = None) -> list[dict[str, Any]]:
        """Get property coordinates and basic info for map visualization."""
        conn = self._get_conn()
        if city:
            rows = conn.execute(
                "SELECT property_id, title, price_cents, city, locality, "
                "data_json FROM properties WHERE LOWER(city) = LOWER(?) "
                "AND is_active = 1",
                (city,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT property_id, title, price_cents, city, locality, "
                "data_json FROM properties WHERE is_active = 1"
            ).fetchall()

        results = []
        for row in rows:
            data = json.loads(row["data_json"] or "{}")
            lat = data.get("latitude", 0)
            lng = data.get("longitude", 0)
            if lat and lng:
                results.append({
                    "property_id": row["property_id"],
                    "title": row["title"],
                    "price": row["price_cents"] / 100.0,
                    "city": row["city"],
                    "locality": row["locality"],
                    "lat": lat,
                    "lng": lng,
                })
        return results

    @staticmethod
    def _row_to_property(row: sqlite3.Row) -> Property | None:
        """Convert a database row to a Property domain object."""
        if row is None:
            return None
        try:
            data = json.loads(row["data_json"] or "{}")
        except (json.JSONDecodeError, ValueError, TypeError):
            data = {}

        am = Amenities(
            bedrooms=row["bedrooms"],
            bathrooms=row["bathrooms"],
            balconies=data.get("balconies", 0),
            carpet_area_sqft=row["carpet_area_sqft"],
            super_area_sqft=data.get("super_area_sqft", 0.0),
            plot_area_sqft=data.get("plot_area_sqft", 0.0),
            furnishing=FurnishingStatus(data["furnishing"]) if data.get("furnishing") else FurnishingStatus.UNFURNISHED,
            facing_direction=data.get("facing_direction", ""),
            gated_community=data.get("gated_community", False),
            power_backup=data.get("power_backup", False),
            water_supply_24x7=data.get("water_supply_24x7", False),
            swimming_pool=data.get("swimming_pool", False),
            gym=data.get("gym", False),
            vaastu_compliant=data.get("vaastu_compliant", False),
            loan_available=data.get("loan_available", False),
            amenities_list=data.get("amenities_list", []),
        )

        loc = Location(
            address=Address(
                city=row["city"],
                locality=row["locality"],
                state=data.get("state", ""),
                pincode=data.get("pincode", ""),
                latitude=data.get("latitude", 0.0),
                longitude=data.get("longitude", 0.0),
                full_address=data.get("full_address", ""),
            ),
            nearby_transit=data.get("nearby_transit", []),
            walk_score=data.get("walk_score", 0),
            transit_score=data.get("transit_score", 0),
            aqi_rating=data.get("aqi_rating", ""),
        )

        return Property(
            property_id=row["property_id"],
            title=row["title"],
            description=row["description"],
            price=Decimal(str(row["price_cents"] / 100.0)),
            property_type=PropertyType(row["property_type"]) if row["property_type"] in {p.value for p in PropertyType} else PropertyType.APARTMENT,
            listing_type=ListingType(data.get("listing_type", "sell")) if isinstance(data.get("listing_type"), str) else ListingType.SELL,
            transaction_type=TransactionType(data.get("transaction_type", "sale")) if isinstance(data.get("transaction_type"), str) else TransactionType.SALE,
            location=loc,
            amenities=am,
            owner_id=row["owner_id"],
            broker_id=data.get("broker_id", ""),
            is_active=bool(row["is_active"]),
            is_featured=bool(row["is_featured"]),
            is_verified=bool(row["is_verified"]),
            rera_number=row["rera_number"],
            listed_at=row["listed_at"],
            updated_at=row["updated_at"],
            views=row["views"],
            slug=row["slug"],
        )

    def close(self) -> None:
        """Close the database connection for the current thread."""
        if hasattr(self._local, "conn") and self._local.conn is not None:
            try:
                self._local.conn.close()
            except Exception as exc:
                _log.debug("[RE] SQLite close error: %s", exc)
            self._local.conn = None


def create_sqlite_repository(db_path: str | Path | None = None) -> SQLitePropertyRepository:
    """Create a SQLitePropertyRepository instance (factory)."""
    return SQLitePropertyRepository(db_path=db_path)
