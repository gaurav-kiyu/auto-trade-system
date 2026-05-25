"""
AD-KIYU AI Governance — Model Registry.

SQLite-backed registry for ML model provenance, versioning, and lifecycle tracking.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)

_DEFAULT_DB = "data/ml_registry.db"


@dataclass
class ModelRecord:
    model_id: str
    version: str               # semver e.g. "1.2.3"
    name: str                   # e.g. "win_prob_lgbm"
    status: str                 # DRAFT → VALIDATED → CANARY → ACTIVE → DEPRECATED → ROLLED_BACK
    created_ts: float = field(default_factory=time.time)
    approved_ts: float | None = None
    activated_ts: float | None = None
    rollback_ts: float | None = None
    metrics: dict[str, float] = field(default_factory=dict)    # accuracy, brier, sharpe, etc.
    metadata: dict[str, Any] = field(default_factory=dict)     # feature cols, training range, SHAP ref
    source_path: str = ""       # filesystem path to serialised model binary
    checksum: str = ""          # SHA256 of model binary
    approved_by: str = ""


class ModelRegistry:
    """Thread-safe SQLite-backed model registry."""

    def __init__(self, db_path: str | Path = _DEFAULT_DB):
        self._db = Path(db_path)
        self._db.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self) -> None:
        with self._lock:
            conn = sqlite3.connect(str(self._db))
            conn.execute("""
                CREATE TABLE IF NOT EXISTS model_registry (
                    model_id TEXT PRIMARY KEY,
                    version TEXT NOT NULL,
                    name TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'DRAFT',
                    created_ts REAL NOT NULL,
                    approved_ts REAL,
                    activated_ts REAL,
                    rollback_ts REAL,
                    metrics TEXT DEFAULT '{}',
                    metadata TEXT DEFAULT '{}',
                    source_path TEXT DEFAULT '',
                    checksum TEXT DEFAULT '',
                    approved_by TEXT DEFAULT ''
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_model_name ON model_registry(name)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_model_status ON model_registry(status)")
            conn.commit()
            conn.close()

    def register(self, model_id: str, version: str, name: str, **kwargs) -> ModelRecord:
        """Register a new model with status DRAFT."""
        rec = ModelRecord(
            model_id=model_id,
            version=version,
            name=name,
            status="DRAFT",
            source_path=kwargs.get("source_path", ""),
            checksum=kwargs.get("checksum", ""),
            metrics=kwargs.get("metrics", {}),
            metadata=kwargs.get("metadata", {}),
        )
        with self._lock:
            conn = sqlite3.connect(str(self._db))
            conn.execute(
                """INSERT OR REPLACE INTO model_registry
                   (model_id, version, name, status, created_ts, metrics, metadata, source_path, checksum)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (rec.model_id, rec.version, rec.name, rec.status, rec.created_ts,
                 json.dumps(rec.metrics), json.dumps(rec.metadata),
                 rec.source_path, rec.checksum),
            )
            conn.commit()
            conn.close()
        _log.info(f"[ML-REGISTRY] Registered model {name} v{version} as {model_id}")
        return rec

    def update_status(self, model_id: str, status: str, **kwargs) -> None:
        """Update model status and optionally set approval/activation timestamps."""
        with self._lock:
            conn = sqlite3.connect(str(self._db))
            fields = ["status = ?"]
            params: list[Any] = [status]
            if status == "ACTIVE" and "activated_ts" not in kwargs:
                fields.append("activated_ts = ?")
                params.append(time.time())
            if "activated_ts" in kwargs:
                fields.append("activated_ts = ?")
                params.append(kwargs["activated_ts"])
            if "approved_ts" in kwargs:
                fields.append("approved_ts = ?")
                params.append(kwargs["approved_ts"])
            if "approved_by" in kwargs:
                fields.append("approved_by = ?")
                params.append(kwargs["approved_by"])
            if "rollback_ts" in kwargs:
                fields.append("rollback_ts = ?")
                params.append(kwargs["rollback_ts"])
            fields_str = ", ".join(fields)
            conn.execute(f"UPDATE model_registry SET {fields_str} WHERE model_id = ?", (*params, model_id))
            conn.commit()
            conn.close()
        _log.info(f"[ML-REGISTRY] Model {model_id} status → {status}")

    def get(self, model_id: str) -> ModelRecord | None:
        """Get a model record by ID."""
        with self._lock:
            conn = sqlite3.connect(str(self._db))
            row = conn.execute("SELECT * FROM model_registry WHERE model_id = ?", (model_id,)).fetchone()
            conn.close()
        if row is None:
            return None
        return self._row_to_record(row)

    def get_active(self, name: str) -> ModelRecord | None:
        """Get the currently ACTIVE model for a given name."""
        with self._lock:
            conn = sqlite3.connect(str(self._db))
            row = conn.execute(
                "SELECT * FROM model_registry WHERE name = ? AND status = 'ACTIVE' ORDER BY activated_ts DESC LIMIT 1",
                (name,),
            ).fetchone()
            conn.close()
        if row is None:
            return None
        return self._row_to_record(row)

    def list_by_name(self, name: str) -> list[ModelRecord]:
        """List all model records for a given name, newest first."""
        with self._lock:
            conn = sqlite3.connect(str(self._db))
            rows = conn.execute(
                "SELECT * FROM model_registry WHERE name = ? ORDER BY created_ts DESC", (name,),
            ).fetchall()
            conn.close()
        return [self._row_to_record(r) for r in rows]

    def list_all(self) -> list[ModelRecord]:
        """List all models, newest first."""
        with self._lock:
            conn = sqlite3.connect(str(self._db))
            rows = conn.execute("SELECT * FROM model_registry ORDER BY created_ts DESC").fetchall()
            conn.close()
        return [self._row_to_record(r) for r in rows]

    def delete(self, model_id: str) -> bool:
        """Delete a model record. Returns True if existed."""
        with self._lock:
            conn = sqlite3.connect(str(self._db))
            cur = conn.execute("DELETE FROM model_registry WHERE model_id = ?", (model_id,))
            deleted = cur.rowcount > 0
            conn.commit()
            conn.close()
        if deleted:
            _log.info(f"[ML-REGISTRY] Deleted model {model_id}")
        return deleted

    @staticmethod
    def _row_to_record(row: sqlite3.Row | tuple) -> ModelRecord:
        def safe_load(val: str | None) -> Any:
            if val:
                try:
                    return json.loads(val)
                except (json.JSONDecodeError, TypeError):
                    pass
            return {}
        return ModelRecord(
            model_id=str(row[0]),
            version=str(row[1]),
            name=str(row[2]),
            status=str(row[3]),
            created_ts=float(row[4]),
            approved_ts=float(row[5]) if row[5] else None,
            activated_ts=float(row[6]) if row[6] else None,
            rollback_ts=float(row[7]) if row[7] else None,
            metrics=safe_load(row[8]),
            metadata=safe_load(row[9]),
            source_path=str(row[10]) if len(row) > 10 else "",
            checksum=str(row[11]) if len(row) > 11 else "",
            approved_by=str(row[12]) if len(row) > 12 else "",
        )
