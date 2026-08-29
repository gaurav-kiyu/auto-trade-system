"""Infrastructure persistence layer — in-memory + SQLite backends.

PropertyRepository is the abstract interface/port.
InMemoryPropertyRepository implements it for transient storage.
SearchEngine adds full-text and faceted search on top.
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from realestate.domain.models import Property

_log = logging.getLogger(__name__)


# ── Repository Interface (Port) ──────────────────────────────────────────────

class PropertyRepository(ABC):
    """Interface for property persistence."""

    @abstractmethod
    def save(self, prop: Property) -> Property: ...

    @abstractmethod
    def get(self, property_id: str) -> Property | None: ...

    @abstractmethod
    def delete(self, property_id: str) -> bool: ...

    @abstractmethod
    def list_all(self) -> list[Property]: ...

    @abstractmethod
    def count(self) -> int: ...

    @abstractmethod
    def search(self, **filters: Any) -> list[Property]: ...


# ── In-Memory Implementation ─────────────────────────────────────────────────

class InMemoryPropertyRepository(PropertyRepository):
    """In-memory property store (thread-safe for single-thread use)."""

    def __init__(self) -> None:
        self._store: dict[str, Property] = {}

    def save(self, prop: Property) -> Property:
        prop.updated_at = time.time()
        self._store[prop.property_id] = prop
        return prop

    def get(self, property_id: str) -> Property | None:
        return self._store.get(property_id)

    def delete(self, property_id: str) -> bool:
        return self._store.pop(property_id, None) is not None

    def list_all(self) -> list[Property]:
        return list(self._store.values())

    def count(self) -> int:
        return len(self._store)

    def search(self, **filters: Any) -> list[Property]:
        """Filter properties by arbitrary field values."""
        results = list(self._store.values())
        for key, value in filters.items():
            if value is None:
                continue
            results = [p for p in results if _get_nested(p, key) == value]
        return results


def _get_nested(obj: object, path: str) -> Any:
    """Get a nested attribute via dot-separated path."""
    for part in path.split("."):
        if hasattr(obj, part):
            obj = getattr(obj, part)
        else:
            return None
    return obj


# ── Search Engine ────────────────────────────────────────────────────────────

@dataclass
class SearchResult:
    """A single search hit."""
    property_id: str = ""
    score: float = 0.0
    highlights: list[str] = field(default_factory=list)


@dataclass
class SearchResults:
    """Aggregated search results."""
    hits: list[SearchResult] = field(default_factory=list)
    total: int = 0
    query_time_ms: float = 0.0
    facets: dict[str, dict[str, int]] = field(default_factory=dict)


class SearchEngine:
    """Full-text + faceted search over properties.

    Supports: keyword query, city, locality, property type, price range,
    bedroom count, furnishing status, amenities filter.
    """

    def __init__(self, repository: PropertyRepository):
        self._repo = repository

    def search(
        self,
        *,
        query: str = "",
        city: str = "",
        locality: str = "",
        property_type: str = "",
        min_price: float = 0.0,
        max_price: float = 1e12,
        min_bedrooms: int = 0,
        max_bedrooms: int = 10,
        furnishing: str = "",
        amenities: list[str] | None = None,
        page: int = 1,
        page_size: int = 20,
        sort_by: str = "listed_at",
        sort_order: str = "desc",
    ) -> SearchResults:
        """Execute a multi-criteria search with faceted results."""
        start = time.time()
        props = self._repo.list_all()
        amenities = amenities or []
        query_lower = query.lower().strip()

        # Filter
        filtered: list[Property] = []
        for p in props:
            # City/locality
            if city and city.lower() not in p.location.address.city.lower():
                continue
            if locality and locality.lower() not in p.location.address.locality.lower():
                continue
            # Property type
            if property_type and p.property_type.value != property_type:
                continue
            # Price
            price_f = float(p.price)
            if price_f < min_price or price_f > max_price:
                continue
            # Bedrooms
            if p.amenities.bedrooms < min_bedrooms or p.amenities.bedrooms > max_bedrooms:
                continue
            # Furnishing
            if furnishing and p.amenities.furnishing.value != furnishing:
                continue
            # Amenities
            if amenities:
                p_amenities = set(a.lower() for a in p.amenities.amenities_list)
                if not all(a.lower() in p_amenities for a in amenities):
                    continue
            # Keyword search
            if query_lower:
                searchable = f"{p.title} {p.description} {p.location.address.locality} {p.location.address.city}".lower()
                if query_lower not in searchable:
                    continue
            filtered.append(p)

        # Sort
        reverse = sort_order == "desc"
        if sort_by == "price":
            filtered.sort(key=lambda x: float(x.price), reverse=reverse)
        elif sort_by == "area":
            filtered.sort(key=lambda x: x.amenities.carpet_area_sqft, reverse=reverse)
        elif sort_by == "views":
            filtered.sort(key=lambda x: x.views, reverse=reverse)
        else:
            filtered.sort(key=lambda x: x.listed_at, reverse=reverse)

        # Build facets
        facets: dict[str, dict[str, int]] = {}
        city_facet: dict[str, int] = {}
        type_facet: dict[str, int] = {}
        for p in props:
            city_name = p.location.address.city
            city_facet[city_name] = city_facet.get(city_name, 0) + 1
            ptype = p.property_type.value
            type_facet[ptype] = type_facet.get(ptype, 0) + 1
        facets["city"] = city_facet
        facets["property_type"] = type_facet

        # Paginate
        total = len(filtered)
        total_pages = max(1, (total + page_size - 1) // page_size)
        page = min(page, total_pages)
        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size
        page_items = filtered[start_idx:end_idx]

        hits = [
            SearchResult(
                property_id=p.property_id,
                score=float(p.price) / 1e7 if float(p.price) > 0 else 0.5,
                highlights=[p.title[:80]] if query_lower and query_lower in p.title.lower() else [],
            )
            for p in page_items
        ]

        elapsed = (time.time() - start) * 1000

        return SearchResults(
            hits=hits,
            total=total,
            query_time_ms=round(elapsed, 2),
            facets=facets,
        )
