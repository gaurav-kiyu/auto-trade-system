"""Saved Properties / Wishlist — bookmark properties for later viewing.

Features:
  - Bookmark/unbookmark properties
  - List saved properties for a user
  - Check if property is saved
  - Count saved properties per user
  - Recently saved sorting
"""

from __future__ import annotations

import logging
import time
from typing import Any

_log = logging.getLogger(__name__)


class SavedPropertiesService:
    """Manages user-saved (bookmarked/wishlisted) properties."""

    def __init__(self) -> None:
        self._saved: dict[str, dict[str, dict[str, Any]]] = {}  # user_id → { property_id → { saved_at, note } }

    def save_property(self, user_id: str, property_id: str, note: str = "") -> bool:
        """Save/bookmark a property for a user. Returns True if newly saved, False if already saved."""
        if user_id not in self._saved:
            self._saved[user_id] = {}
        if property_id in self._saved[user_id]:
            return False  # Already saved
        self._saved[user_id][property_id] = {
            "saved_at": time.time(),
            "note": note,
        }
        _log.debug("[RE SAVED] %s saved property %s", user_id, property_id)
        return True

    def unsave_property(self, user_id: str, property_id: str) -> bool:
        """Remove a property from saved list."""
        if user_id not in self._saved:
            return False
        if property_id not in self._saved[user_id]:
            return False
        del self._saved[user_id][property_id]
        _log.debug("[RE SAVED] %s unsaved property %s", user_id, property_id)
        return True

    def get_saved_properties(self, user_id: str) -> list[dict[str, Any]]:
        """Get all saved property IDs with metadata for a user, newest first."""
        saved = self._saved.get(user_id, {})
        result = [
            {"property_id": pid, **meta}
            for pid, meta in saved.items()
        ]
        result.sort(key=lambda x: x.get("saved_at", 0), reverse=True)
        return result

    def is_saved(self, user_id: str, property_id: str) -> bool:
        """Check if a property is saved by a user."""
        return user_id in self._saved and property_id in self._saved[user_id]

    def get_saved_count(self, user_id: str) -> int:
        """Get the number of saved properties for a user."""
        return len(self._saved.get(user_id, {}))

    def get_property_details(self, user_id: str, property_service: Any) -> list[dict[str, Any]]:
        """Get full property details for all saved properties."""
        saved = self.get_saved_properties(user_id)
        if not property_service or not saved:
            return saved
        from dataclasses import asdict
        result = []
        for entry in saved:
            prop = property_service.get_property(entry["property_id"])
            if prop:
                try:
                    prop_dict = asdict(prop) if hasattr(prop, '__dataclass_fields__') else prop.to_dict()
                except (TypeError, AttributeError):
                    prop_dict = {k: v for k, v in prop.__dict__.items() if not k.startswith('_')}
                result.append({
                    "property_id": entry["property_id"],
                    "saved_at": entry.get("saved_at", 0),
                    "note": entry.get("note", ""),
                    "property": prop_dict,
                })
        return result

    def get_stats(self) -> dict[str, Any]:
        """Get saved properties statistics."""
        total_users = len(self._saved)
        total_saved = sum(len(u) for u in self._saved.values())
        return {
            "total_users_with_saved": total_users,
            "total_saved_properties": total_saved,
        }


# ── Singleton ───────────────────────────────────────────────────────────────

_saved_properties_instance: SavedPropertiesService | None = None


def get_saved_properties_service() -> SavedPropertiesService:
    global _saved_properties_instance
    if _saved_properties_instance is None:
        _saved_properties_instance = SavedPropertiesService()
    return _saved_properties_instance


# ── API Router ──────────────────────────────────────────────────────────────

def create_saved_properties_router(service: SavedPropertiesService | None = None) -> Any:
    """Create a FastAPI router for saved properties endpoints."""
    from fastapi import APIRouter, Query

    svc = service or get_saved_properties_service()
    router = APIRouter(prefix="/api/realestate/saved", tags=["Real Estate Saved Properties"])

    @router.post("/{property_id}")
    async def save_property(
        property_id: str,
        user_id: str = Query(...),
        note: str = Query(""),
    ):
        """Save/bookmark a property."""
        result = svc.save_property(user_id, property_id, note)
        return {"success": result, "saved": True, "is_new": result}

    @router.delete("/{property_id}")
    async def unsave_property(property_id: str, user_id: str = Query(...)):
        """Remove a saved property."""
        result = svc.unsave_property(user_id, property_id)
        return {"success": result, "saved": False}

    @router.get("")
    async def get_saved(user_id: str = Query(...)):
        """Get all saved properties for a user."""
        saved = svc.get_saved_properties(user_id)
        return {"saved_properties": saved, "total": len(saved)}

    @router.get("/{property_id}/check")
    async def check_saved(property_id: str, user_id: str = Query(...)):
        """Check if a property is saved by a user."""
        return {"is_saved": svc.is_saved(user_id, property_id)}

    @router.get("/count")
    async def saved_count(user_id: str = Query(...)):
        """Get count of saved properties for a user."""
        return {"count": svc.get_saved_count(user_id)}

    @router.get("/stats")
    async def stats():
        """Get saved properties statistics."""
        return svc.get_stats()

    return router
