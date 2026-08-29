"""PostgreSQL Persistence — SQLAlchemy models and repository for the real estate platform.

Provides:
  - SQLAlchemy ORM models for all domain entities
  - PostgreSQL repository implementation
  - Connection pooling and session management
  - Alembic-compatible Base metadata
  - Migration helper functions

Environment variables:
  - DATABASE_URL: PostgreSQL connection string (default: sqlite:///./realestate.db)
  - DB_POOL_SIZE: Connection pool size (default: 5)
  - DB_MAX_OVERFLOW: Max overflow connections (default: 10)
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import Generator
from contextlib import contextmanager
from decimal import Decimal
from typing import Any

from realestate.domain.models import (
    Address,
    Amenities,
    FurnishingStatus,
    Lead,
    LeadStatus,
    Location,
    MediaAsset,
    Property,
    PropertyType,
)

_log = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════════
# Connection Management
# ═══════════════════════════════════════════════════════════════════════════════

_DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    os.environ.get("RE_DATABASE_URL", "sqlite:///./db/realestate.db"),
)
_POOL_SIZE = int(os.environ.get("DB_POOL_SIZE", "5"))
_MAX_OVERFLOW = int(os.environ.get("DB_MAX_OVERFLOW", "10"))


def _create_engine():
    """Create SQLAlchemy engine with appropriate configuration."""
    try:
        from sqlalchemy import create_engine

        if _DATABASE_URL.startswith("postgresql"):
            engine = create_engine(
                _DATABASE_URL,
                pool_size=_POOL_SIZE,
                max_overflow=_MAX_OVERFLOW,
                pool_pre_ping=True,
                pool_recycle=3600,
                echo=False,
            )
        else:
            engine = create_engine(
                _DATABASE_URL,
                connect_args={"check_same_thread": False} if "sqlite" in _DATABASE_URL else {},
                echo=False,
            )
        return engine
    except ImportError:
        _log.warning("[DB] SQLAlchemy not installed — database unavailable")
        return None


def _create_session_factory(engine):
    """Create SQLAlchemy session factory."""
    try:
        from sqlalchemy.orm import sessionmaker
        return sessionmaker(bind=engine, autocommit=False, autoflush=False)
    except ImportError:
        return None


# Lazy initialization
_engine = None
_SessionFactory = None
_Base = None


def _ensure_db():
    """Ensure database engine and session factory are initialized."""
    global _engine, _SessionFactory, _Base
    if _engine is not None:
        return
    _engine = _create_engine()
    if _engine is None:
        return
    _SessionFactory = _create_session_factory(_engine)
    # Create Base (with extend_existing to allow redefinition in test environments)
    try:
        from sqlalchemy.orm import declarative_base
        _Base = declarative_base()
    except ImportError:
        _Base = None


def get_engine():
    """Get the SQLAlchemy engine (lazy init)."""
    _ensure_db()
    return _engine


def get_session_factory():
    """Get the session factory (lazy init)."""
    _ensure_db()
    return _SessionFactory


def get_base():
    """Get the declarative base (lazy init)."""
    _ensure_db()
    return _Base


@contextmanager
def session_scope() -> Generator[Any, None, None]:
    """Provide a transactional scope around a series of operations."""
    factory = get_session_factory()
    if factory is None:
        raise RuntimeError("Database not available — install SQLAlchemy")
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# ═══════════════════════════════════════════════════════════════════════════════
# SQLAlchemy ORM Models
# ═══════════════════════════════════════════════════════════════════════════════

def create_models() -> type | None:
    """Create and return ORM models dynamically.

    Returns the Base class if successful, None otherwise.
    """
    Base = get_base()
    if Base is None:
        return None

    try:
        from sqlalchemy import Boolean, Column, Float, Integer, String, Text
    except ImportError:
        return None

    class PropertyModel(Base):
        """SQLAlchemy model for Property."""
        __tablename__ = "re_properties"
        __table_args__ = {"extend_existing": True}

        property_id = Column(String(64), primary_key=True)
        title = Column(String(255), nullable=False, index=True)
        description = Column(Text, default="")
        property_type = Column(String(32), default="apartment", index=True)
        listing_type = Column(String(16), default="sell")
        transaction_type = Column(String(16), default="sale")
        price = Column(Float, default=0.0, index=True)
        price_per_sqft = Column(Float, default=0.0)

        # Address fields (denormalized for query performance)
        city = Column(String(64), default="", index=True)
        locality = Column(String(128), default="", index=True)
        state = Column(String(64), default="")
        pincode = Column(String(16), default="")
        latitude = Column(Float, default=0.0)
        longitude = Column(Float, default=0.0)

        # Amenities (denormalized)
        bedrooms = Column(Integer, default=0, index=True)
        bathrooms = Column(Integer, default=0)
        balconies = Column(Integer, default=0)
        carpet_area_sqft = Column(Float, default=0.0)
        super_area_sqft = Column(Float, default=0.0)
        plot_area_sqft = Column(Float, default=0.0)
        furnishing = Column(String(32), default="unfurnished")
        facing_direction = Column(String(16), default="")

        # JSON fields for complex structures
        amenities_json = Column(Text, default="[]")  # JSON list of amenity strings
        images_json = Column(Text, default="[]")     # JSON list of image URLs

        # Ownership
        owner_id = Column(String(64), default="", index=True)
        broker_id = Column(String(64), default="")

        # Flags
        is_featured = Column(Boolean, default=False)
        is_verified = Column(Boolean, default=False)
        is_active = Column(Boolean, default=True)
        rera_number = Column(String(64), default="")

        # Metrics
        views = Column(Integer, default=0)

        # Timestamps
        listed_at = Column(Float, default=0.0)
        updated_at = Column(Float, default=0.0)

        def to_domain(self) -> Property:
            """Convert ORM model to domain Property object."""
            amenities_list = json.loads(self.amenities_json or "[]")
            images_list = json.loads(self.images_json or "[]")

            return Property(
                property_id=self.property_id,
                title=self.title,
                description=self.description or "",
                property_type=PropertyType(self.property_type) if self.property_type in {p.value for p in PropertyType} else PropertyType.APARTMENT,
                price=Decimal(str(self.price)),
                price_per_sqft=Decimal(str(self.price_per_sqft)),
                location=Location(
                    address=Address(
                        city=self.city or "",
                        locality=self.locality or "",
                        state=self.state or "",
                        pincode=self.pincode or "",
                        latitude=self.latitude or 0.0,
                        longitude=self.longitude or 0.0,
                    ),
                ),
                amenities=Amenities(
                    bedrooms=self.bedrooms or 0,
                    bathrooms=self.bathrooms or 0,
                    balconies=self.balconies or 0,
                    carpet_area_sqft=self.carpet_area_sqft or 0.0,
                    super_area_sqft=self.super_area_sqft or 0.0,
                    plot_area_sqft=self.plot_area_sqft or 0.0,
                    furnishing=FurnishingStatus(self.furnishing) if self.furnishing in {f.value for f in FurnishingStatus} else FurnishingStatus.UNFURNISHED,
                    facing_direction=self.facing_direction or "",
                    amenities_list=amenities_list,
                ),
                owner_id=self.owner_id or "",
                broker_id=self.broker_id or "",
                is_featured=self.is_featured or False,
                is_verified=self.is_verified or False,
                is_active=self.is_active if self.is_active is not None else True,
                rera_number=self.rera_number or "",
                views=self.views or 0,
                listed_at=self.listed_at or 0.0,
                updated_at=self.updated_at or 0.0,
                media=[MediaAsset(url=url, asset_type="photo") for url in images_list],
            )

    class LeadModel(Base):
        """SQLAlchemy model for Lead/CRM."""
        __tablename__ = "re_leads"
        __table_args__ = {"extend_existing": True}

        lead_id = Column(String(64), primary_key=True)
        property_id = Column(String(64), default="", index=True)
        buyer_name = Column(String(128), default="")
        buyer_phone = Column(String(32), default="", index=True)
        buyer_email = Column(String(128), default="")
        budget = Column(Float, default=0.0)
        status = Column(String(32), default="new", index=True)
        notes = Column(Text, default="")
        source = Column(String(32), default="website")
        assigned_to = Column(String(64), default="")
        created_at = Column(Float, default=0.0)
        updated_at = Column(Float, default=0.0)

        def to_domain(self) -> Lead:
            return Lead(
                lead_id=self.lead_id,
                property_id=self.property_id or "",
                buyer_name=self.buyer_name or "",
                buyer_phone=self.buyer_phone or "",
                buyer_email=self.buyer_email or "",
                budget=Decimal(str(self.budget or 0)),
                status=LeadStatus(self.status) if self.status in {s.value for s in LeadStatus} else LeadStatus.NEW,
                notes=self.notes or "",
                source=self.source or "website",
                assigned_to=self.assigned_to or "",
                created_at=self.created_at or 0.0,
                updated_at=self.updated_at or 0.0,
            )

    # Create tables
    try:
        Base.metadata.create_all(bind=get_engine())
        _log.info("[DB] Database tables created/verified")
    except Exception as e:
        _log.warning("[DB] Table creation skipped: %s", e)

    return Base


# ═══════════════════════════════════════════════════════════════════════════════
# PostgreSQL Property Repository
# ═══════════════════════════════════════════════════════════════════════════════

class PostgresPropertyRepository:
    """PostgreSQL-backed property repository implementing the repository pattern.

    Provides persistent storage with full CRUD and search operations.
    Falls back gracefully if SQLAlchemy is not installed.
    """

    def __init__(self) -> None:
        self._available = False
        self._PropertyModel = None
        self._LeadModel = None
        self._init_models()

    def _init_models(self) -> None:
        """Initialize ORM models if SQLAlchemy is available."""
        Base = create_models()
        if Base is None:
            _log.warning("[DB] PostgreSQL repository unavailable — SQLAlchemy not installed")
            return
        try:
            for name, cls in Base.registry._class_registry.items():
                if hasattr(cls, "__tablename__"):
                    if cls.__tablename__ == "re_properties":
                        self._PropertyModel = cls
                    elif cls.__tablename__ == "re_leads":
                        self._LeadModel = cls
            self._available = self._PropertyModel is not None
        except Exception as e:
            _log.debug("[DB] Model init: %s", e)

    @property
    def available(self) -> bool:
        return self._available

    # ── Property Operations ───────────────────────────────────────────────

    def save(self, prop: Property) -> None:
        """Save a property to PostgreSQL."""
        if not self._available:
            _log.debug("[DB] PostgreSQL unavailable, skipping save")
            return
        try:
            with session_scope() as session:
                model = self._property_to_model(prop)
                existing = session.get(self._PropertyModel, prop.property_id)
                if existing:
                    for key, value in model.__dict__.items():
                        if not key.startswith("_"):
                            setattr(existing, key, value)
                else:
                    session.add(model)
        except Exception as e:
            _log.error("[DB] Save failed: %s", e)

    def get(self, property_id: str) -> Property | None:
        """Get a property by ID from PostgreSQL."""
        if not self._available:
            return None
        try:
            with session_scope() as session:
                model = session.get(self._PropertyModel, property_id)
                if model:
                    return model.to_domain()
                return None
        except Exception:
            return None

    def delete(self, property_id: str) -> bool:
        """Delete a property by ID."""
        if not self._available:
            return False
        try:
            with session_scope() as session:
                model = session.get(self._PropertyModel, property_id)
                if model:
                    session.delete(model)
                    return True
                return False
        except Exception:
            return False

    def count(self) -> int:
        """Count properties."""
        if not self._available:
            return 0
        try:
            with session_scope() as session:
                from sqlalchemy import func
                return session.query(func.count()).select_from(self._PropertyModel).scalar() or 0
        except Exception:
            return 0

    def list_all(self) -> list[Property]:
        """List all properties."""
        if not self._available:
            return []
        try:
            with session_scope() as session:
                models = session.query(self._PropertyModel).all()
                return [m.to_domain() for m in models]
        except Exception:
            return []

    def search(self, city: str | None = None, min_bedrooms: int = 0,
               max_price: float = 0.0, limit: int = 100) -> list[Property]:
        """Search properties with filters."""
        if not self._available:
            return []
        try:
            with session_scope() as session:
                query = session.query(self._PropertyModel)
                if city:
                    query = query.filter(self._PropertyModel.city.ilike(f"%{city}%"))
                if min_bedrooms > 0:
                    query = query.filter(self._PropertyModel.bedrooms >= min_bedrooms)
                if max_price > 0:
                    query = query.filter(self._PropertyModel.price <= max_price)
                query = query.limit(limit)
                return [m.to_domain() for m in query.all()]
        except Exception:
            return []

    def _property_to_model(self, prop: Property) -> Any:
        """Convert domain Property to ORM model."""
        if not self._PropertyModel:
            raise RuntimeError("PropertyModel not initialized")
        loc = prop.location
        addr = loc.address
        am = prop.amenities

        return self._PropertyModel(
            property_id=prop.property_id,
            title=prop.title,
            description=prop.description,
            property_type=prop.property_type.value,
            listing_type=prop.listing_type.value,
            transaction_type=prop.transaction_type.value,
            price=float(prop.price),
            price_per_sqft=float(prop.price_per_sqft),
            city=addr.city,
            locality=addr.locality,
            state=addr.state,
            pincode=addr.pincode,
            latitude=addr.latitude,
            longitude=addr.longitude,
            bedrooms=am.bedrooms,
            bathrooms=am.bathrooms,
            balconies=am.balconies,
            carpet_area_sqft=am.carpet_area_sqft,
            super_area_sqft=am.super_area_sqft,
            plot_area_sqft=am.plot_area_sqft,
            furnishing=am.furnishing.value if isinstance(am.furnishing, FurnishingStatus) else "unfurnished",
            facing_direction=am.facing_direction,
            amenities_json=json.dumps(am.amenities_list),
            images_json=json.dumps([m.url for m in prop.media if m.asset_type == "photo"]),
            owner_id=prop.owner_id,
            broker_id=prop.broker_id,
            is_featured=prop.is_featured,
            is_verified=prop.is_verified,
            is_active=prop.is_active,
            rera_number=prop.rera_number,
            views=prop.views,
            listed_at=prop.listed_at,
            updated_at=prop.updated_at,
        )

    # ── Lead Operations ───────────────────────────────────────────────────

    def save_lead(self, lead: Lead) -> None:
        """Save a lead to PostgreSQL."""
        if not self._available or not self._LeadModel:
            return
        try:
            with session_scope() as session:
                existing = session.get(self._LeadModel, lead.lead_id)
                if existing:
                    existing.status = lead.status.value
                    existing.updated_at = time.time()
                else:
                    model = self._LeadModel(
                        lead_id=lead.lead_id,
                        property_id=lead.property_id,
                        buyer_name=lead.buyer_name,
                        buyer_phone=lead.buyer_phone,
                        buyer_email=lead.buyer_email,
                        budget=float(lead.budget),
                        status=lead.status.value,
                        notes=lead.notes,
                        source=lead.source,
                        assigned_to=lead.assigned_to or "",
                        created_at=lead.created_at,
                        updated_at=time.time(),
                    )
                    session.add(model)
        except Exception as e:
            _log.error("[DB] Lead save failed: %s", e)

    def get_lead(self, lead_id: str) -> Lead | None:
        """Get a lead by ID."""
        if not self._available or not self._LeadModel:
            return None
        try:
            with session_scope() as session:
                model = session.get(self._LeadModel, lead_id)
                return model.to_domain() if model else None
        except Exception:
            return None

    def get_leads(self, status: str | None = None) -> list[Lead]:
        """Get leads, optionally filtered by status."""
        if not self._available or not self._LeadModel:
            return []
        try:
            with session_scope() as session:
                query = session.query(self._LeadModel)
                if status:
                    query = query.filter(self._LeadModel.status == status)
                query = query.order_by(self._LeadModel.created_at.desc())  # type: ignore[attr-defined]
                return [m.to_domain() for m in query.all()]
        except Exception:
            return []


# ═══════════════════════════════════════════════════════════════════════════════
# Migration Helpers
# ═══════════════════════════════════════════════════════════════════════════════

MIGRATIONS: list[dict[str, Any]] = [
    {
        "version": 1,
        "description": "Initial schema — properties and leads tables",
        "sql": """
            CREATE TABLE IF NOT EXISTS re_properties (
                property_id VARCHAR(64) PRIMARY KEY,
                title VARCHAR(255) NOT NULL,
                description TEXT DEFAULT '',
                property_type VARCHAR(32) DEFAULT 'apartment',
                listing_type VARCHAR(16) DEFAULT 'sell',
                transaction_type VARCHAR(16) DEFAULT 'sale',
                price FLOAT DEFAULT 0,
                price_per_sqft FLOAT DEFAULT 0,
                city VARCHAR(64) DEFAULT '',
                locality VARCHAR(128) DEFAULT '',
                state VARCHAR(64) DEFAULT '',
                pincode VARCHAR(16) DEFAULT '',
                latitude FLOAT DEFAULT 0,
                longitude FLOAT DEFAULT 0,
                bedrooms INTEGER DEFAULT 0,
                bathrooms INTEGER DEFAULT 0,
                balconies INTEGER DEFAULT 0,
                carpet_area_sqft FLOAT DEFAULT 0,
                super_area_sqft FLOAT DEFAULT 0,
                plot_area_sqft FLOAT DEFAULT 0,
                furnishing VARCHAR(32) DEFAULT 'unfurnished',
                facing_direction VARCHAR(16) DEFAULT '',
                amenities_json TEXT DEFAULT '[]',
                images_json TEXT DEFAULT '[]',
                owner_id VARCHAR(64) DEFAULT '',
                broker_id VARCHAR(64) DEFAULT '',
                is_featured BOOLEAN DEFAULT FALSE,
                is_verified BOOLEAN DEFAULT FALSE,
                is_active BOOLEAN DEFAULT TRUE,
                rera_number VARCHAR(64) DEFAULT '',
                views INTEGER DEFAULT 0,
                listed_at FLOAT DEFAULT 0,
                updated_at FLOAT DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_re_properties_city ON re_properties(city);
            CREATE INDEX IF NOT EXISTS idx_re_properties_type ON re_properties(property_type);
            CREATE INDEX IF NOT EXISTS idx_re_properties_price ON re_properties(price);
            CREATE INDEX IF NOT EXISTS idx_re_properties_bedrooms ON re_properties(bedrooms);
            CREATE INDEX IF NOT EXISTS idx_re_properties_owner ON re_properties(owner_id);

            CREATE TABLE IF NOT EXISTS re_leads (
                lead_id VARCHAR(64) PRIMARY KEY,
                property_id VARCHAR(64) DEFAULT '',
                buyer_name VARCHAR(128) DEFAULT '',
                buyer_phone VARCHAR(32) DEFAULT '',
                buyer_email VARCHAR(128) DEFAULT '',
                budget FLOAT DEFAULT 0,
                status VARCHAR(32) DEFAULT 'new',
                notes TEXT DEFAULT '',
                source VARCHAR(32) DEFAULT 'website',
                assigned_to VARCHAR(64) DEFAULT '',
                created_at FLOAT DEFAULT 0,
                updated_at FLOAT DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_re_leads_status ON re_leads(status);
            CREATE INDEX IF NOT EXISTS idx_re_leads_phone ON re_leads(buyer_phone);
        """,
    },
]


def run_migrations(engine: Any = None) -> list[dict[str, Any]]:
    """Run pending database migrations.

    Args:
        engine: Optional SQLAlchemy engine. If None, uses default.

    Returns:
        List of migration results with status.
    """
    results: list[dict[str, Any]] = []

    if engine is None:
        engine = get_engine()
    if engine is None:
        _log.warning("[DB] Cannot run migrations — no engine available")
        return [{"version": 0, "status": "skipped", "reason": "no engine"}]

    try:
        from sqlalchemy import text
        # Create migration tracking table
        with engine.connect() as conn:
            conn.execute(
                text("""CREATE TABLE IF NOT EXISTS re_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at FLOAT DEFAULT (strftime('%s', 'now'))
                )""")
            )
            conn.commit()
    except Exception:
        pass

    for migration in MIGRATIONS:
        version = migration["version"]
        try:
            with engine.connect() as conn:
                # Check if already applied
                # Use parameterized query for migration tracking
                raw = conn.execute(
                    text("SELECT version FROM re_migrations WHERE version = :v"),
                    {"v": version},
                )
                existing = raw.fetchone()
                if existing:
                    results.append({"version": version, "status": "already_applied"})
                    continue

                # Run migration
                for statement in migration["sql"].split(";"):
                    stmt = statement.strip()
                    if stmt:
                        conn.execute(text(stmt))
                conn.execute(
                    text("INSERT INTO re_migrations (version) VALUES (:v)"),
                    {"v": version},
                )
                conn.commit()
                results.append({"version": version, "status": "applied"})
                _log.info("[DB] Migration v%d applied: %s", version, migration["description"])
        except Exception as e:
            _log.error("[DB] Migration v%d failed: %s", version, e)
            results.append({"version": version, "status": "failed", "error": str(e)})

    return results
