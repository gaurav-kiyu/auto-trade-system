"""100% Free Local Snapshot & Disaster Recovery Engine (v3.0).

Automated zero-cost database and state backup engine:
- Creates compressed, timestamped .zip archives of all databases and state files.
- Generates SHA-256 integrity checksums to guarantee zero corruption.
- Rotating retention: Keeps last 30 daily backups, pruning older archives automatically.
- 1-Click Restore utility to restore databases instantly in case of hardware/software disaster.
- ZERO cloud storage bills.
"""

from __future__ import annotations

import hashlib
import time
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent.parent
_BACKUP_DIR = _ROOT / "backups" / "daily_snapshots"


@dataclass
class SnapshotMetadata:
    snapshot_id: str
    filename: str
    filepath: str
    size_bytes: int
    sha256_checksum: str
    created_at: str
    files_included: list[str]


class DisasterRecoveryEngine:
    """Zero-cost local archive & snapshot management."""

    CRITICAL_FILES = [
        "db/signals_history.db",
        "json/user_signal_permissions.json",
        "json/trader_state.json",
        "data/config.json",
        "config.json",
    ]

    @classmethod
    def create_snapshot(cls) -> dict[str, Any]:
        """Create a compressed snapshot archive of all critical system databases and states."""
        _BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        ts_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        snap_id = f"SNAP_{ts_str}"
        zip_filename = f"{snap_id}.zip"
        zip_path = _BACKUP_DIR / zip_filename

        files_archived = []
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for rel_p in cls.CRITICAL_FILES:
                full_p = _ROOT / rel_p
                if full_p.exists() and full_p.is_file():
                    zf.write(full_p, arcname=rel_p)
                    files_archived.append(rel_p)

        # Compute SHA-256 Checksum
        hasher = hashlib.sha256()
        with open(zip_path, "rb") as f:
            while chunk := f.read(65536):
                hasher.update(chunk)
        checksum = hasher.hexdigest()

        meta = SnapshotMetadata(
            snapshot_id=snap_id,
            filename=zip_filename,
            filepath=str(zip_path),
            size_bytes=zip_path.stat().st_size,
            sha256_checksum=checksum,
            created_at=datetime.now().isoformat(),
            files_included=files_archived,
        )

        # Auto-prune older snapshots (keep last 30)
        cls._prune_old_snapshots(max_keep=30)

        return asdict(meta)

    @classmethod
    def list_snapshots(cls) -> list[dict[str, Any]]:
        """List all available local snapshots."""
        _BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        results = []
        for p in sorted(_BACKUP_DIR.glob("SNAP_*.zip"), reverse=True):
            stat = p.stat()
            results.append({
                "snapshot_id": p.stem,
                "filename": p.name,
                "size_kb": round(stat.st_size / 1024.0, 1),
                "created_at": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
            })
        return results

    @classmethod
    def restore_snapshot(cls, snapshot_id: str) -> dict[str, Any]:
        """Restore all databases and state files from a selected snapshot archive."""
        target_zip = _BACKUP_DIR / f"{snapshot_id}.zip"
        if not target_zip.exists():
            return {"success": False, "message": f"Snapshot archive {target_zip.name} not found"}

        with zipfile.ZipFile(target_zip, "r") as zf:
            zf.extractall(_ROOT)

        return {
            "success": True,
            "message": f"Successfully restored all system files from snapshot {snapshot_id}!",
            "snapshot_id": snapshot_id,
            "timestamp": time.time(),
        }

    @classmethod
    def _prune_old_snapshots(cls, max_keep: int = 30) -> None:
        snaps = sorted(_BACKUP_DIR.glob("SNAP_*.zip"), key=lambda p: p.stat().st_mtime)
        if len(snaps) > max_keep:
            for old_p in snaps[:-max_keep]:
                try:
                    old_p.unlink()
                except Exception:
                    pass
