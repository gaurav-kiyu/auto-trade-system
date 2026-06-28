"""
Schema Registry — Phase 25: Data Governance & Schema Registry

Provides centralized schema management for all system data stores.
Maintains versioned schema definitions and migration paths.

Usage:
    from core.schema_registry import SchemaRegistry
    registry = SchemaRegistry()
    schema = registry.get_schema("trades", version=4)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

_log = logging.getLogger(__name__)


# ── Schema Definitions ──────────────────────────────────────────────────

_SCHEMAS: dict[str, dict[int, list[dict[str, Any]]]] = {
    "trades": {
        1: [
            {"name": "id", "type": "INTEGER", "primary_key": True},
            {"name": "intent_id", "type": "TEXT", "not_null": True},
            {"name": "symbol", "type": "TEXT", "not_null": True},
            {"name": "direction", "type": "TEXT", "not_null": True},
            {"name": "entry_price", "type": "REAL", "not_null": True},
            {"name": "quantity", "type": "INTEGER", "not_null": True},
            {"name": "entry_time", "type": "TEXT", "not_null": True},
            {"name": "exit_price", "type": "REAL"},
            {"name": "exit_time", "type": "TEXT"},
            {"name": "pnl", "type": "REAL"},
            {"name": "status", "type": "TEXT", "not_null": True},
        ],
        2: [
            {"name": "id", "type": "INTEGER", "primary_key": True},
            {"name": "intent_id", "type": "TEXT", "not_null": True},
            {"name": "symbol", "type": "TEXT", "not_null": True},
            {"name": "direction", "type": "TEXT", "not_null": True},
            {"name": "entry_price", "type": "REAL", "not_null": True},
            {"name": "quantity", "type": "INTEGER", "not_null": True},
            {"name": "entry_time", "type": "TEXT", "not_null": True},
            {"name": "exit_price", "type": "REAL"},
            {"name": "exit_time", "type": "TEXT"},
            {"name": "pnl", "type": "REAL"},
            {"name": "status", "type": "TEXT", "not_null": True},
            {"name": "exit_reason", "type": "TEXT"},
            {"name": "slippage", "type": "REAL"},
        ],
        3: [
            {"name": "id", "type": "INTEGER", "primary_key": True},
            {"name": "intent_id", "type": "TEXT", "not_null": True},
            {"name": "symbol", "type": "TEXT", "not_null": True},
            {"name": "direction", "type": "TEXT", "not_null": True},
            {"name": "entry_price", "type": "REAL", "not_null": True},
            {"name": "quantity", "type": "INTEGER", "not_null": True},
            {"name": "entry_time", "type": "TEXT", "not_null": True},
            {"name": "exit_price", "type": "REAL"},
            {"name": "exit_time", "type": "TEXT"},
            {"name": "pnl", "type": "REAL"},
            {"name": "status", "type": "TEXT", "not_null": True},
            {"name": "exit_reason", "type": "TEXT"},
            {"name": "slippage", "type": "REAL"},
            {"name": "correlation_id", "type": "TEXT"},
            {"name": "strategy_name", "type": "TEXT"},
        ],
        4: [
            {"name": "id", "type": "INTEGER", "primary_key": True},
            {"name": "intent_id", "type": "TEXT", "not_null": True},
            {"name": "symbol", "type": "TEXT", "not_null": True},
            {"name": "direction", "type": "TEXT", "not_null": True},
            {"name": "entry_price", "type": "REAL", "not_null": True},
            {"name": "quantity", "type": "INTEGER", "not_null": True},
            {"name": "entry_time", "type": "TEXT", "not_null": True},
            {"name": "exit_price", "type": "REAL"},
            {"name": "exit_time", "type": "TEXT"},
            {"name": "pnl", "type": "REAL"},
            {"name": "status", "type": "TEXT", "not_null": True},
            {"name": "exit_reason", "type": "TEXT"},
            {"name": "slippage", "type": "REAL"},
            {"name": "correlation_id", "type": "TEXT"},
            {"name": "strategy_name", "type": "TEXT"},
            {"name": "regime_code", "type": "INTEGER"},
            {"name": "session_code", "type": "INTEGER"},
        ],
    },
    "trade_journal": {
        1: [
            {"name": "id", "type": "INTEGER", "primary_key": True},
            {"name": "intent_id", "type": "TEXT", "not_null": True},
            {"name": "slippage_bps", "type": "REAL"},
            {"name": "latency_ms", "type": "REAL"},
            {"name": "fill_quality", "type": "TEXT"},
            {"name": "timestamp", "type": "TEXT", "not_null": True},
        ],
        2: [
            {"name": "id", "type": "INTEGER", "primary_key": True},
            {"name": "intent_id", "type": "TEXT", "not_null": True},
            {"name": "slippage_bps", "type": "REAL"},
            {"name": "latency_ms", "type": "REAL"},
            {"name": "fill_quality", "type": "TEXT"},
            {"name": "timestamp", "type": "TEXT", "not_null": True},
            {"name": "broker", "type": "TEXT"},
            {"name": "exchange", "type": "TEXT"},
        ],
    },
    "ml_predictions": {
        1: [
            {"name": "id", "type": "INTEGER", "primary_key": True},
            {"name": "intent_id", "type": "TEXT", "not_null": True},
            {"name": "predicted_win_prob", "type": "REAL", "not_null": True},
            {"name": "actual_outcome", "type": "INTEGER"},
            {"name": "features_version", "type": "INTEGER"},
            {"name": "prediction_time", "type": "TEXT", "not_null": True},
        ],
        2: [
            {"name": "id", "type": "INTEGER", "primary_key": True},
            {"name": "intent_id", "type": "TEXT", "not_null": True},
            {"name": "predicted_win_prob", "type": "REAL", "not_null": True},
            {"name": "actual_outcome", "type": "INTEGER"},
            {"name": "features_version", "type": "INTEGER"},
            {"name": "prediction_time", "type": "TEXT", "not_null": True},
            {"name": "model_version", "type": "TEXT"},
            {"name": "shap_values", "type": "TEXT"},
        ],
    },
}


@dataclass
class SchemaInfo:
    """Schema metadata and column definitions."""
    name: str
    version: int
    columns: list[dict[str, Any]]
    is_current: bool = False


class SchemaRegistry:
    """
    Centralized schema registry for all system data stores.

    Provides versioned schema definitions, compatibility checks,
    and migration path discovery.
    """

    def __init__(self) -> None:
        self._schemas: dict[str, dict[int, list[dict[str, Any]]]] = _SCHEMAS

    def get_schema(self, store: str, version: int | None = None) -> SchemaInfo | None:
        """Get schema definition for a data store at a given version."""
        if store not in self._schemas:
            _log.warning("Unknown data store: %s", store)
            return None
        versions = self._schemas[store]
        if version is None:
            version = max(versions.keys())
        if version not in versions:
            _log.warning("Unknown schema version %d for %s", version, store)
            return None
        return SchemaInfo(
            name=store,
            version=version,
            columns=versions[version],
            is_current=(version == max(versions.keys())),
        )

    def get_all_versions(self, store: str) -> list[int]:
        """Get all available schema versions for a data store."""
        return sorted(self._schemas.get(store, {}).keys())

    def get_migration_path(self, store: str, from_version: int, to_version: int) -> list[int]:
        """Get the migration path from one version to another."""
        versions = sorted(self._schemas.get(store, {}).keys())
        if from_version not in versions or to_version not in versions:
            return []
        step = 1 if to_version > from_version else -1
        return list(range(from_version, to_version + step, step))[1:]

    def is_compatible(self, store: str, version_a: int, version_b: int) -> bool:
        """
        Check if two schema versions are compatible.
        Compatibility means version difference <= 1 (minor upgrades only).
        """
        return abs(version_a - version_b) <= 1

    def list_stores(self) -> list[str]:
        """List all registered data stores."""
        return sorted(self._schemas.keys())

    def register_schema(self, store: str, version: int, columns: list[dict[str, Any]]) -> None:
        """Register a new schema definition."""
        if store not in self._schemas:
            self._schemas[store] = {}
        self._schemas[store][version] = columns
        _log.info("Registered schema %s v%d with %d columns", store, version, len(columns))


# Global registry instance
_registry: SchemaRegistry | None = None


def get_registry() -> SchemaRegistry:
    """Get the global schema registry instance."""
    global _registry
    if _registry is None:
        _registry = SchemaRegistry()
    return _registry


__all__ = [
    "SchemaInfo",
    "SchemaRegistry",
    "get_registry",
]
