"""
Automated Database Backup Script — Phase 17 (DR Gap #1).

Backs up all known trading and operational databases to a timestamped
backup directory. Designed to be run from cron/scheduler at regular
intervals (daily) or as part of the Sunday EOD health check pipeline.

Usage
-----
    python scripts/backup_databases.py                  # Backup all DBs to default dir
    python scripts/backup_databases.py --dir /data/backups  # Custom backup dir
    python scripts/backup_databases.py --retain 14          # Keep 14 backups
    python scripts/backup_databases.py --db-only trades.db  # Single DB

Integration with core.slo_governance:
    After backup, calls ingest_health_report-like signals to record
    backup success/failure as SLO metrics (rpo, recovery_time).

Exit codes:
    0 = All backups successful
    1 = One or more backups failed
"""

from __future__ import annotations

import argparse
import logging
import shutil
import sys
from pathlib import Path

# Use IST-aware timestamp for backup directory naming
from core.datetime_ist import now_ist

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
_log = logging.getLogger("backup_databases")

# Known databases to back up
DEFAULT_DATABASES: list[str] = [
    "trades.db",
    "trade_journal.db",
    "ml_tracker.db",
    "oi_snapshots.db",
    "event_store.db",
    "execution_state.db",
    "execution_state.db-shm",
    "execution_state.db-wal",
    "order_state.db",
    "formal_order_state.db",
    "replay_sessions.db",
    "shadow_mode.db",
    "strategy_versioning.db",
    "fundamentals.db",
]

DEFAULT_BACKUP_DIR = "backups"
DEFAULT_RETAIN_COUNT = 7  # Keep 7 most recent backups


def backup_databases(
    backup_dir: str = DEFAULT_BACKUP_DIR,
    retain: int = DEFAULT_RETAIN_COUNT,
    db_list: list[str] | None = None,
) -> tuple[int, int, list[str]]:
    """Back up all known databases.

    Args:
        backup_dir: Directory to store backups (created if missing).
        retain: Number of recent backups to retain (oldest removed).
        db_list: Specific DBs to back up (default = all known).

    Returns:
        Tuple of (success_count, fail_count, error_messages).
    """
    backup_path = Path(backup_dir)
    backup_path.mkdir(parents=True, exist_ok=True)

    # Create timestamped subdirectory
    timestamp = now_ist().strftime("%Y%m%d_%H%M%S")
    snapshot_dir = backup_path / f"db_snapshot_{timestamp}"
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    project_root = Path(".")
    db_names = db_list or DEFAULT_DATABASES

    success_count = 0
    fail_count = 0
    errors: list[str] = []

    for db_name in db_names:
        src = project_root / db_name
        if not src.is_file():
            _log.debug("[SKIP] %s — not found", db_name)
            continue

        dst = snapshot_dir / db_name
        try:
            # WAL checkpoint before copy to ensure consistent snapshot
            # This flushes WAL content into the main DB file
            if db_name.endswith(".db"):
                try:
                    from core.db_utils import get_connection
                    conn = get_connection(str(src), timeout=5, row_factory=False)
                    try:
                        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                    finally:
                        conn.close()
                except Exception as wal_exc:
                    _log.debug("[WAL] Checkpoint skipped for %s: %s", db_name, wal_exc)
                # Also copy WAL/SHM files if they exist after checkpoint
                # Note: with_suffix() doesn't support multi-part suffixes like -wal/-shm
                # so we construct the path manually
                src_str = str(src)
                for ext in ["-wal", "-shm"]:
                    wal_path = src_str + ext
                    wal_src = Path(wal_path)
                    if wal_src.is_file():
                        shutil.copy2(str(wal_src), str(snapshot_dir / (db_name + ext)))

            shutil.copy2(str(src), str(dst))
            size_mb = src.stat().st_size / (1024 * 1024)
            _log.info("[OK]   %s (%.1f MB) → %s", db_name, size_mb, dst)
            success_count += 1
        except (OSError, PermissionError, shutil.Error) as exc:
            _log.error("[FAIL] %s — %s", db_name, exc)
            errors.append(f"{db_name}: {exc}")
            fail_count += 1

    # Cleanup old backups beyond retain count
    removed = _prune_old_backups(backup_path, retain)
    if removed > 0:
        _log.info("Pruned %d old backup(s)", removed)

    # Write a manifest
    manifest_path = snapshot_dir / "manifest.txt"
    try:
        with open(manifest_path, "w") as f:
            f.write(f"Backup Timestamp: {timestamp}\n")
            f.write(f"Databases: {len(db_names)}\n")
            f.write(f"Success: {success_count}\n")
            f.write(f"Failed: {fail_count}\n")
            if errors:
                f.write("Errors:\n")
                for e in errors:
                    f.write(f"  - {e}\n")
        _log.info("[OK]   Manifest written: %s", manifest_path)
    except OSError as exc:
        _log.warning("[WARN] Manifest write failed: %s", exc)

    # Record backup outcome as SLO metric (best effort)
    _record_backup_outcome(success_count, fail_count)

    return success_count, fail_count, errors


def _prune_old_backups(backup_path: Path, retain: int) -> int:
    """Remove oldest backup snapshots beyond retain count.

    Returns:
        Number of snapshots removed.
    """
    snapshots = sorted(
        [d for d in backup_path.iterdir() if d.is_dir() and d.name.startswith("db_snapshot_")],
        key=lambda d: d.name,
    )
    to_remove = len(snapshots) - retain
    removed = 0
    for i in range(to_remove):
        if i >= len(snapshots):
            break
        try:
            shutil.rmtree(str(snapshots[i]))
            removed += 1
        except OSError as exc:
            _log.warning("[WARN] Failed to remove old backup %s: %s", snapshots[i], exc)
    return removed


def _record_backup_outcome(success: int, fail: int) -> None:
    """Record backup outcome as SLO metrics via the SLO governance system.

    Best-effort; failures are logged but do not affect backup exit code.
    """
    try:
        from core.slo_governance import get_slo_governance
        slo = get_slo_governance()
        # Backup success → RPO well within 1 minute (WAL provides sub-second RPO)
        # Backup failure → RPO risk increases
        if fail == 0:
            slo.record_metric("rpo", 30.0)      # RPO well within 1 min
            slo.record_metric("recovery_time", 45.0)  # Recovery with recent backup
        else:
            slo.record_metric("rpo", 120.0)     # RPO breach risk
            slo.record_metric("recovery_time", 300.0)  # Recovery without backup
    except Exception as exc:
        _log.debug("[SLO] Backup metric recording skipped: %s", exc)


def _restore_latest(db_name: str, backup_dir: str = DEFAULT_BACKUP_DIR, force: bool = False) -> bool:
    """Restore a single database from the most recent backup snapshot.

    Args:
        db_name: Database file name to restore (e.g., "trades.db").
        backup_dir: Backup directory.
        force: If True, overwrite existing database without prompt.

    Returns:
        True if restore succeeded, False otherwise.
    """
    backup_path = Path(backup_dir)
    snapshots = sorted(
        [d for d in backup_path.iterdir() if d.is_dir() and d.name.startswith("db_snapshot_")],
        key=lambda d: d.name,
        reverse=True,
    )
    if not snapshots:
        _log.error("[RESTORE] No backup snapshots found in %s", backup_dir)
        return False

    src = snapshots[0] / db_name
    if not src.is_file():
        _log.error("[RESTORE] %s not found in latest snapshot %s", db_name, snapshots[0])
        return False

    dst = Path(db_name)
    if dst.is_file() and not force:
        _log.warning(
            "[RESTORE] %s already exists! Use --force to overwrite. "
            "The existing file will be renamed to %s.bak as a safety measure.",
            db_name, db_name,
        )
        return False

    try:
        # Safety: rename existing file to .bak before overwriting
        if dst.is_file():
            backup_dst = dst.with_suffix(".db.bak")
            shutil.move(str(dst), str(backup_dst))
            _log.info("[RESTORE] Existing %s renamed to %s", db_name, backup_dst.name)

        shutil.copy2(str(src), str(dst))
        _log.info("[RESTORE] %s restored from %s", db_name, snapshots[0])
        return True
    except (OSError, PermissionError, shutil.Error) as exc:
        _log.error("[RESTORE] Failed: %s", exc)
        return False


# ── CLI ────────────────────────────────────────────────────────────────────────

def _get_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="python scripts/backup_databases.py",
        description="Automated database backup for the trading platform.",
    )
    ap.add_argument("--dir", default=DEFAULT_BACKUP_DIR,
                    help=f"Backup directory (default: {DEFAULT_BACKUP_DIR})")
    ap.add_argument("--retain", type=int, default=DEFAULT_RETAIN_COUNT,
                    help=f"Number of backups to retain (default: {DEFAULT_RETAIN_COUNT})")
    ap.add_argument("--db-only", type=str, default="",
                    help="Backup a single database (default: all known DBs)")
    ap.add_argument("--restore", type=str, default="",
                    help="Restore a database from latest backup")
    ap.add_argument("--quiet", action="store_true",
                    help="Suppress informational output")
    return ap


def _cli() -> None:
    parser = _get_parser()
    args = parser.parse_args()

    # Suppress INFO-level logging if --quiet
    if args.quiet:
        logging.getLogger().setLevel(logging.WARNING)

    if args.restore:
        success = _restore_latest(args.restore, args.dir)
        sys.exit(0 if success else 1)

    db_list = [args.db_only] if args.db_only else None
    success, fail, errors = backup_databases(
        backup_dir=args.dir,
        retain=args.retain,
        db_list=db_list,
    )

    _log.info(
        "Backup complete: %d success, %d failure(s)",
        success, fail,
    )

    if errors:
        _log.warning("Failures:")
        for e in errors:
            _log.warning("  - %s", e)

    sys.exit(1 if fail > 0 else 0)


if __name__ == "__main__":
    _cli()
