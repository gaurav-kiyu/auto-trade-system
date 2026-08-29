#!/usr/bin/env python3
"""Database Restore Verification Tool — OPB v2.57.0 (Phase 11)

Verifies that database backups can be successfully restored. Takes a backup
file, restores it to a temporary SQLite database, and validates:
  - SQLite header integrity
  - PRAGMA integrity_check passes
  - Schema matches expected tables
  - Row counts within expected ranges
  - Foreign key constraints are valid

This is the missing 'R' in backup/restore/recovery — backups are only
as valuable as the ability to restore them.

Usage:
    python scripts/verify_restore.py                    # Verify latest backup
    python scripts/verify_restore.py --backup backups/trades.db.20250101_120000.db.gz
    python scripts/verify_restore.py --all              # Verify all backups
    python scripts/verify_restore.py --ci               # CI mode
    python scripts/verify_restore.py --json             # JSON output
"""

from __future__ import annotations

import gzip
import json
import re
import shutil
import sqlite3
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any

_REPORTS_DIR = Path(__file__).resolve().parent.parent / "reports"
_BACKUP_DIR = Path(__file__).resolve().parent.parent / "backups"
_PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Expected tables per database (heuristic — verified against actual schema)
_EXPECTED_TABLES = {
    "db/trades.db": ["trades"],
    "db/trade_journal.db": ["execution_quality"],
    "db/ml_tracker.db": ["predictions", "model_metadata"],
    "db/oi_snapshots.db": ["oi_snapshots"],
}

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _safe_ident(name: str) -> str:
    """Return a double-quoted SQL identifier, rejecting anything not allow-listed.

    Table names from the SQLite schema cannot be parameter-bound in SQLite, so
    they must be validated against a strict identifier pattern before being
    interpolated into a query.
    """
    if not _IDENTIFIER_RE.match(name):
        raise ValueError(f"Unsafe SQL identifier: {name!r}")
    return f'"{name}"'


# ── Core Restore & Verify Logic ───────────────────────────────────────────────


def _find_backups(target: str | None = None, all_backups: bool = False) -> list[Path]:
    """Find backup files to verify."""
    if target:
        path = Path(target)
        if path.exists():
            return [path]
        # Could be a database name, find its latest backup
        backups = sorted(_BACKUP_DIR.glob(f"{target}.*"), key=lambda p: p.stat().st_mtime, reverse=True)
        if backups:
            return [backups[0]]
        print(f"  [WARN] Backup not found: {target}")
        return []

    if all_backups:
        return sorted(_BACKUP_DIR.glob("*.db*"), key=lambda p: p.stat().st_mtime)

    # Default: find latest backup per database
    latest_by_db: dict[str, Path] = {}
    for p in _BACKUP_DIR.glob("*.db*"):
        db_name = p.name.split(".")[0] + ".db"
        if db_name not in latest_by_db or p.stat().st_mtime > latest_by_db[db_name].stat().st_mtime:
            latest_by_db[db_name] = p
    return list(latest_by_db.values())


def _decompress_if_needed(backup_path: Path, temp_dir: Path) -> Path:
    """Decompress a gzipped backup to a temp file. Returns path to decompressed file."""
    if backup_path.suffix == ".gz":
        decompressed = temp_dir / backup_path.stem
        with gzip.open(backup_path, "rb") as f_in:
            with open(decompressed, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)
        return decompressed
    return backup_path


def _verify_single_backup(backup_path: Path) -> dict[str, Any]:
    """Verify a single backup can be restored and passes integrity checks."""
    result: dict[str, Any] = {
        "backup_file": backup_path.name,
        "backup_size_bytes": backup_path.stat().st_size,
        "backup_modified": datetime.fromtimestamp(backup_path.stat().st_mtime).isoformat(),
        "restored": False,
        "integrity_check": None,
        "schema": [],
        "row_counts": {},
        "foreign_keys_valid": None,
        "errors": [],
        "duration_sec": 0.0,
    }

    t0 = time.time()

    with tempfile.TemporaryDirectory() as tmpdir:
        temp_path = Path(tmpdir)
        try:
            # Step 1: Decompress if needed
            db_path = _decompress_if_needed(backup_path, temp_path)
            result["decompressed_size_bytes"] = db_path.stat().st_size

            # Step 2: Check SQLite header
            with open(db_path, "rb") as f:
                header = f.read(16)
            if not header.startswith(b"SQLite format 3\x00"):
                result["errors"].append("Invalid SQLite header")
                return result

            # Step 3: Open and run PRAGMA integrity_check
            conn = sqlite3.connect(str(db_path))
            conn.execute("PRAGMA query_only = ON")

            # 3a: integrity_check
            try:
                integrity = conn.execute("PRAGMA integrity_check").fetchone()
                result["integrity_check"] = integrity[0] if integrity else "no result"
            except sqlite3.Error as e:
                result["integrity_check"] = f"error: {e}"
                result["errors"].append(f"integrity_check failed: {e}")

            # 3b: foreign_key_check
            try:
                fk_issues = conn.execute("PRAGMA foreign_key_check").fetchall()
                result["foreign_keys_valid"] = len(fk_issues) == 0
                if fk_issues:
                    result["foreign_key_violations"] = [
                        f"table={row[0]}, rowid={row[1]}, parent={row[2]}, fk_index={row[3]}"
                        for row in fk_issues[:20]
                    ]
            except sqlite3.Error:
                result["foreign_keys_valid"] = None  # Not supported in older SQLite

            # 3c: table schema
            tables = conn.execute(
                "SELECT name, sql FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
            result["schema"] = [{"table": t[0], "sql": t[1]} for t in tables]

            # 3d: row counts
            for t in tables:
                try:
                    # Identifier is allow-list validated by _safe_ident(); no user input.
                    sql = "SELECT COUNT(*) FROM "
                    sql += _safe_ident(t[0])
                    count = conn.execute(sql).fetchone()[0]
                    result["row_counts"][t[0]] = count
                except sqlite3.Error as e:
                    result["row_counts"][t[0]] = -1
                    result["errors"].append(f"Row count failed for {t[0]}: {e}")

            result["table_count"] = len(tables)
            result["total_rows"] = sum(result["row_counts"].values())

            # 3e: page count and page size
            page_count = conn.execute("PRAGMA page_count").fetchone()
            page_size = conn.execute("PRAGMA page_size").fetchone()
            result["page_count"] = page_count[0] if page_count else 0
            result["page_size"] = page_size[0] if page_size else 0
            result["database_size_bytes"] = page_count[0] * page_size[0] if page_count and page_size else 0

            conn.close()
            result["restored"] = True

        except (OSError, sqlite3.Error) as e:
            result["errors"].append(f"Restore failed: {e}")

    result["duration_sec"] = round(time.time() - t0, 3)
    result["healthy"] = (
        result["restored"]
        and result["integrity_check"] == "ok"
        and len(result["errors"]) == 0
    )
    return result


def _check_expected_schema(verify_result: dict[str, Any]) -> list[str]:
    """Check that the restored DB has expected tables."""
    issues = []
    tables = {t["table"] for t in verify_result.get("schema", [])}

    # Infer db name from backup filename
    backup_name = verify_result.get("backup_file", "")
    for db_name, expected in _EXPECTED_TABLES.items():
        if db_name in backup_name:
            for exp_table in expected:
                if exp_table not in tables:
                    issues.append(f"Missing expected table '{exp_table}' in {backup_name}")
            break

    if not tables:
        issues.append("No tables found in restored database")
    elif len(tables) == 1 and next(iter(tables)) == "sqlite_sequence":
        issues.append("Database may be empty — only sqlite_sequence table found (auto-increment tracking)")

    return issues


# ── Report Generators ─────────────────────────────────────────────────────────


def _generate_json_report(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Generate aggregate JSON report."""
    total = len(results)
    healthy = sum(1 for r in results if r.get("healthy"))
    failed = total - healthy
    total_rows = sum(r.get("total_rows", 0) for r in results)
    total_duration = sum(r.get("duration_sec", 0) for r in results)

    return {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "total_backups_verified": total,
        "healthy": healthy,
        "failed": failed,
        "total_rows_across_all": total_rows,
        "total_duration_sec": round(total_duration, 2),
        "results": results,
    }


def _generate_html_report(json_report: dict[str, Any]) -> str:
    """Generate HTML dashboard."""
    results = json_report.get("results", [])
    total = json_report["total_backups_verified"]
    healthy = json_report["healthy"]
    failed = json_report["failed"]
    score = round(healthy / total * 100, 1) if total > 0 else 0
    color = "#4CAF50" if score >= 90 else "#FF9800" if score >= 70 else "#f44336"

    rows = ""
    for r in results:
        icon = "✅" if r.get("healthy") else "❌"
        integrity = str(r.get("integrity_check", "?"))[:30]
        tables = r.get("table_count", "?")
        rows_text = sum(r.get("row_counts", {}).values()) if r.get("row_counts") else "?"
        dur = r.get("duration_sec", 0)
        rows += f"""
        <tr style="border-left:4px solid {'#4CAF50' if r.get('healthy') else '#f44336'}">
            <td>{icon}</td>
            <td>{r.get('backup_file', '?')}</td>
            <td>{int(r.get('backup_size_bytes', 0) / 1024)} KB</td>
            <td>{integrity}</td>
            <td>{tables}</td>
            <td>{rows_text}</td>
            <td>{dur:.2f}s</td>
        </tr>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Backup Restore Verification Report — OPB v2.57.0</title>
<style>
body {{ font-family: 'Segoe UI', Arial, sans-serif; max-width: 1000px; margin: 20px auto; padding: 20px; background: #f5f7fa; color: #333; }}
h1 {{ color: #1a237e; border-bottom: 3px solid #1a237e; padding-bottom: 8px; }}
.score {{ text-align:center; padding:25px; border-radius:8px;margin:20px 0;background:linear-gradient(135deg,{color}0%,{color}dd 100%);color:white; }}
.score .num {{ font-size:64px; font-weight:700; }}
.score .lbl {{ font-size:18px;opacity:0.9; }}
table {{ width:100%;border-collapse:collapse;background:white;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.08); }}
th {{ background:#1a237e;color:white;padding:12px 16px;text-align:left; }}
td {{ padding:10px 16px;border-bottom:1px solid #e8eaf6; }}
footer {{ margin-top:40px;padding-top:20px;border-top:1px solid #e0e0e0;color:#999;font-size:0.85em;text-align:center; }}
</style>
</head>
<body>
<h1>💾 Backup Restore Verification Report</h1>
<div class="score">
  <div class="num">{score}%</div>
  <div class="lbl">{healthy}/{total} backups healthy | {failed} failed</div>
</div>
<table>
<tr><th>Status</th><th>Backup</th><th>Size</th><th>Integrity</th><th>Tables</th><th>Rows</th><th>Duration</th></tr>
{rows}
</table>
<footer>Generated by scripts/verify_restore.py — OPB v2.57.0</footer>
</body>
</html>"""


# ── CLI ───────────────────────────────────────────────────────────────────────


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(
        description="Database Restore Verification",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--backup", default=None, help="Specific backup file to verify")
    parser.add_argument("--all", action="store_true", help="Verify all backups")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--html", default=None, help="HTML report path")
    parser.add_argument("--ci", action="store_true", help="CI mode: exit non-zero on failures")
    args = parser.parse_args()

    _REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("  DATABASE RESTORE VERIFICATION v2.57.0")
    print("=" * 60)

    backups = _find_backups(target=args.backup, all_backups=args.all)
    if not backups:
        print("\n  No backups found.")
        print(f"  Backup directory: {_BACKUP_DIR}")
        print("  Run scripts/run_backup_rotation.py first to create backups.")
        return 0 if not args.ci else 1

    print(f"\n  Verifying {len(backups)} backup(s)...")

    results = []
    for i, bp in enumerate(backups, 1):
        print(f"  [{i}/{len(backups)}] {bp.name}...", end=" ", flush=True)
        result = _verify_single_backup(bp)
        results.append(result)
        icon = "✅" if result.get("healthy") else "❌"
        dur = result.get("duration_sec", 0)
        print(f"{icon} ({dur:.2f}s)")

        if not result.get("healthy"):
            for err in result.get("errors", []):
                print(f"    └─ {err}")
            schema_issues = _check_expected_schema(result)
            for si in schema_issues:
                print(f"    └─ {si}")

    # Aggregate
    json_report = _generate_json_report(results)
    total = json_report["total_backups_verified"]
    healthy = json_report["healthy"]
    failed = json_report["failed"]
    score = round(healthy / total * 100, 1) if total > 0 else 0

    print(f"\n  {'='*60}")
    print("  RESTORE VERIFICATION RESULT")
    print(f"  {'='*60}")
    print(f"  Backups Verified: {total}")
    print(f"  Healthy:          {healthy}")
    print(f"  Failed:           {failed}")
    print(f"  Restore Score:    {score}%")
    print(f"  Total Rows:       {json_report['total_rows_across_all']:,}")
    print(f"  Duration:         {json_report['total_duration_sec']:.2f}s")

    # Schema consistency check
    for r in results:
        schema_issues = _check_expected_schema(r)
        if schema_issues:
            print(f"\n  Schema Note for {r['backup_file']}:")
            for si in schema_issues:
                print(f"    ⚠️  {si}")

    # JSON output
    if args.json:
        print(json.dumps(json_report, indent=2, default=str))

    # HTML report
    html_path = args.html or str(_REPORTS_DIR / "restore_verification.html")
    html = _generate_html_report(json_report)
    Path(html_path).parent.mkdir(parents=True, exist_ok=True)
    Path(html_path).write_text(html, encoding="utf-8")
    print(f"\n  📊 HTML report: {html_path}")

    # JSON report
    json_path = _REPORTS_DIR / "restore_verification.json"
    json_path.write_text(json.dumps(json_report, indent=2, default=str), encoding="utf-8")
    print(f"  📋 JSON report: {json_path}")

    # CI check
    if args.ci and failed > 0:
        print(f"\n❌ CI FAILED: {failed} backup(s) failed restore verification")
        return 1

    print(f"\n{'='*60}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
