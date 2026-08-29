#!/usr/bin/env python3
"""Database Integrity Checker — OPB v2.57.1

Verifies the integrity of all SQLite database files used by the trading system.

Checks:
  1. File existence and size
  2. SQLite header validation
  3. PRAGMA integrity_check
  4. PRAGMA quick_check (fast)
  5. Schema validation (expected tables exist)
  6. Foreign key integrity
  7. WAL mode status

Usage:
    python scripts/check_db_integrity.py
    python scripts/check_db_integrity.py --json
    python scripts/check_db_integrity.py --ci
    python scripts/check_db_integrity.py --repair  # Attempt VACUUM + reindex
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
import time
from pathlib import Path

# Configure UTF-8 for stdout on Windows terminals if supported
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from typing import Any

# ── Configuration ─────────────────────────────────────────────────────────────

REPORTS_DIR = Path(__file__).resolve().parent.parent / "reports"
HTML_REPORT = REPORTS_DIR / "db_integrity_report.html"
JSON_REPORT = REPORTS_DIR / "db_integrity_report.json"

# Expected tables per database (simplified — checks if these tables exist)
KNOWN_DATABASES: dict[str, list[str]] = {
    "db/trades.db": ["execution_orders"],
    "db/wal_journal.db": ["intents"],
    "db/ml_tracker.db": ["ml_predictions"],
    "db/trade_journal.db": ["executions"],
    "db/oi_snapshots.db": ["snapshots"],
    "db/execution_state.db": ["execution_state"],
    "execution_certifier.db": ["certs"],
    "db/strategy_performance.db": ["strategy_trades"],
    "db/strategy_versioning.db": ["strategy_versions"],
    "db/data_lineage.db": ["data_lineage"],
    "db/realestate.db": ["re_properties"],
    "db/order_state.db": ["orders"],
}

# Known test databases (skipped from checks)
TEST_DB_PATTERNS = ("test_", "temp_", "test_recon_", "nonexistent_")

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


def _find_databases() -> list[Path]:
    """Find all valid SQLite databases in the project root, data/, and db/ directories."""
    dbs = []
    root = Path.cwd()
    for pattern in ("*.db", "*.sqlite", "*.sqlite3"):
        # Check data/ and db/ directories first (production database locations)
        for sub_name in ("db", "data"):
            sub_dir = root / sub_name
            if sub_dir.exists():
                for f in sub_dir.glob(pattern):
                    if not any(f.name.startswith(p) for p in TEST_DB_PATTERNS) and f.stat().st_size > 0:
                        dbs.append(f)
        # Check root directory (only if not already added and file size > 0)
        existing_names = {d.name for d in dbs}
        for f in root.glob(pattern):
            if not any(f.name.startswith(p) for p in TEST_DB_PATTERNS) and f.name not in existing_names:
                if f.stat().st_size > 0:
                    dbs.append(f)
    return sorted(set(dbs), key=lambda p: p.name)


def _check_file_integrity(db_path: Path) -> dict[str, Any]:
    """Run SQLite integrity checks on a database file.

    Returns dict with check results.
    """
    result: dict[str, Any] = {
        "database": db_path.name,
        "path": str(db_path),
        "size_bytes": db_path.stat().st_size if db_path.exists() else 0,
        "exists": db_path.exists(),
        "readable": os.access(db_path, os.R_OK) if db_path.exists() else False,
        "writable": os.access(db_path, os.W_OK) if db_path.exists() else False,
        "checks": {},
        "schema_tables": [],
        "issues": [],
    }

    if not result["exists"]:
        result["issues"].append("File does not exist")
        return result

    # SQLite header check
    try:
        with open(db_path, "rb") as f:
            header = f.read(16)
        sqlite_header = b"SQLite format 3\x00"
        result["checks"]["valid_header"] = header.startswith(sqlite_header)
        if not result["checks"]["valid_header"]:
            result["issues"].append("Invalid SQLite header — not a valid SQLite database")
    except (OSError, PermissionError) as e:
        result["checks"]["valid_header"] = False
        result["issues"].append(f"Cannot read header: {e}")

    # Connect and run PRAGMA checks
    try:
        conn = sqlite3.connect(str(db_path), timeout=5)
        conn.execute("PRAGMA synchronous = OFF")  # Speed up checks
        cursor = conn.cursor()

        # WAL mode
        cursor.execute("PRAGMA journal_mode")
        journal_mode = cursor.fetchone()
        result["checks"]["journal_mode"] = journal_mode[0] if journal_mode else "unknown"

        # Quick integrity check (faster than full integrity_check)
        cursor.execute("PRAGMA quick_check")
        quick_check = cursor.fetchone()
        result["checks"]["quick_check"] = quick_check[0] if quick_check else "unknown"
        if quick_check and quick_check[0] != "ok":
            result["issues"].append(f"Quick check failed: {quick_check[0]}")

        # Full integrity check (slower but thorough)
        cursor.execute("PRAGMA integrity_check")
        integrity = cursor.fetchall()
        integrity_ok = all(row[0] == "ok" for row in integrity)
        result["checks"]["integrity_check"] = "ok" if integrity_ok else integrity
        if not integrity_ok:
            result["issues"].append(f"Integrity check found {len(integrity)} issues")

        # Foreign key check
        try:
            cursor.execute("PRAGMA foreign_key_check")
            fk_violations = cursor.fetchall()
            result["checks"]["foreign_keys_ok"] = len(fk_violations) == 0
            if fk_violations:
                result["issues"].append(f"{len(fk_violations)} foreign key violation(s)")
                result["foreign_key_violations"] = [
                    {"table": row[0], "rowid": row[1], "parent": row[2], "parent_rowid": row[3]}
                    for row in fk_violations[:20]
                ]
        except sqlite3.DatabaseError:
            result["checks"]["foreign_keys_ok"] = True  # Some DBs don't support FK

        # Schema: list all tables
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = [row[0] for row in cursor.fetchall()]
        result["schema_tables"] = tables

        # Verify expected tables exist
        db_name = db_path.name
        expected = KNOWN_DATABASES.get(db_name, [])
        if expected:
            missing = [t for t in expected if t not in tables]
            if missing:
                result["issues"].append(f"Missing expected tables: {', '.join(missing)}")
            result["checks"]["expected_tables_present"] = len(missing) == 0

        # Record count
        table_counts = {}
        for table in tables:
            try:
                # Identifier is allow-list validated by _safe_ident(); no user input.
                sql = "SELECT COUNT(*) FROM "
                sql += _safe_ident(table)
                cursor.execute(sql)
                table_counts[table] = cursor.fetchone()[0]
            except sqlite3.DatabaseError:
                table_counts[table] = -1
        result["table_counts"] = table_counts
        result["total_rows"] = sum(c for c in table_counts.values() if c > 0)

        # Schema version
        try:
            cursor.execute("PRAGMA user_version")
            result["schema_version"] = cursor.fetchone()[0]
        except sqlite3.DatabaseError:
            result["schema_version"] = -1

        conn.close()

    except sqlite3.DatabaseError as e:
        result["issues"].append(f"SQLite error: {e}")
    except Exception as e:
        result["issues"].append(f"Unexpected error: {e}")

    result["healthy"] = len(result["issues"]) == 0
    return result


def _try_repair(db_path: Path) -> dict[str, Any]:
    """Attempt to repair a database by running VACUUM and REINDEX."""
    repair_result = {"vacuum": False, "reindex": False, "error": ""}
    try:
        conn = sqlite3.connect(str(db_path), timeout=30)
        conn.execute("VACUUM")
        repair_result["vacuum"] = True
        conn.execute("REINDEX")
        repair_result["reindex"] = True
        conn.close()
    except (sqlite3.DatabaseError, OSError) as e:
        repair_result["error"] = str(e)
    return repair_result


def _generate_html(results: dict[str, Any]) -> str:
    """Generate HTML report."""
    timestamp = results.get("timestamp", "")
    total = results.get("total_dbs", 0)
    healthy = results.get("healthy_count", 0)

    rows = ""
    for db_result in results.get("databases", []):
        db_name = db_result["database"]
        status_icon = "✅" if db_result["healthy"] else "❌"
        color = "#4CAF50" if db_result["healthy"] else "#f44336"
        size_mb = db_result["size_bytes"] / (1024 * 1024)
        issues = "; ".join(db_result.get("issues", [])) or "None"
        tables = ", ".join(db_result.get("schema_tables", [])) or "None"
        rows += f"""
        <tr style="border-left: 4px solid {color};">
            <td>{status_icon}</td>
            <td><strong>{db_name}</strong></td>
            <td>{size_mb:.2f} MB</td>
            <td>{db_result['checks'].get('quick_check', 'N/A')}</td>
            <td>{db_result['checks'].get('journal_mode', 'N/A')}</td>
            <td>{db_result.get('total_rows', 0):,}</td>
            <td>{tables}</td>
            <td>{issues}</td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Database Integrity Report — OPB v2.57.1</title>
<style>
body {{ font-family: -apple-system, sans-serif; margin: 20px; background: #f5f5f5; }}
h1, h2 {{ color: #333; }}
table {{ border-collapse: collapse; width: 100%; margin: 10px 0; background: #fff; }}
th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
th {{ background: #4A90D9; color: white; }}
tr:nth-child(even) {{ background: #f9f9f9; }}
.summary {{ background: #e8f5e9; padding: 15px; border-radius: 5px; margin: 10px 0; }}
.summary.fail {{ background: #ffebee; }}
</style>
</head>
<body>
<h1>🗄️ Database Integrity Report</h1>
<div class="summary {'fail' if healthy < total else ''}">
<p><strong>Timestamp:</strong> {timestamp}</p>
<p><strong>Databases:</strong> {healthy}/{total} healthy</p>
</div>
<table>
<tr><th>Status</th><th>Database</th><th>Size</th><th>Integrity</th><th>Journal</th><th>Rows</th><th>Tables</th><th>Issues</th></tr>
{rows}
</table>
<p style="color:#888; margin-top:30px;">Generated by OPB Database Integrity Check v2.57.1</p>
</body>
</html>"""
    return html


def main() -> int:
    """CLI entry point."""
    import argparse
    parser = argparse.ArgumentParser(description="Database Integrity Checker")
    parser.add_argument("--json", action="store_true", help="Output JSON report")
    parser.add_argument("--no-html", action="store_true", help="Skip HTML generation")
    parser.add_argument("--ci", action="store_true", help="CI mode: exit non-zero on integrity failures")
    parser.add_argument("--repair", action="store_true", help="Attempt VACUUM + REINDEX on failed databases")
    args = parser.parse_args()

    os.makedirs(REPORTS_DIR, exist_ok=True)

    print("=" * 60)
    print("  DATABASE INTEGRITY CHECKER v2.57.1")
    print("=" * 60)

    databases = _find_databases()
    print(f"\nFound {len(databases)} database(s)")

    results: list[dict[str, Any]] = []
    healthy_count = 0
    failed_count = 0

    for db_path in databases:
        print(f"\n  Checking {db_path.name}...", end=" ")
        result = _check_file_integrity(db_path)

        if result["healthy"]:
            healthy_count += 1
            print("✅ OK")
        else:
            failed_count += 1
            print("❌ ISSUES FOUND")
            for issue in result.get("issues", []):
                print(f"       - {issue}")

        # Summary info
        if result.get("checks", {}).get("journal_mode"):
            print(f"       Journal: {result['checks']['journal_mode']}")
        if result.get("total_rows", 0) > 0:
            print(f"       Rows: {result['total_rows']:,}")
        if result.get("schema_tables"):
            print(f"       Tables: {', '.join(result['schema_tables'][:8])}"
                  f"{'...' if len(result['schema_tables']) > 8 else ''}")

        # Repair if requested and failed
        if args.repair and not result["healthy"]:
            print("       Attempting repair...", end=" ")
            repair = _try_repair(db_path)
            if repair["vacuum"] and repair["reindex"]:
                print("✅ VACUUM + REINDEX complete")
                # Re-check
                result = _check_file_integrity(db_path)
                if result["healthy"]:
                    print("       ✅ Repair successful")
                    healthy_count += 1
                    failed_count -= 1
            else:
                print(f"❌ Repair failed: {repair.get('error', 'unknown')}")

        results.append(result)

    summary = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S IST"),
        "total_dbs": len(databases),
        "healthy_count": healthy_count,
        "failed_count": failed_count,
        "databases": results,
    }

    if args.json:
        print(json.dumps(summary, indent=2, default=str))

    if not args.no_html:
        html = _generate_html(summary)
        HTML_REPORT.write_text(html, encoding="utf-8")
        print(f"\n  HTML report: {HTML_REPORT}")

    JSON_REPORT.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    print(f"  JSON report: {JSON_REPORT}")

    print(f"\n  Summary: {healthy_count}/{len(databases)} healthy")

    if args.ci and failed_count > 0:
        print(f"\n❌ CI FAILED: {failed_count} database(s) have integrity issues")
        return 1

    print("\n" + "=" * 60)
    print("  DATABASE CHECK COMPLETE")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
