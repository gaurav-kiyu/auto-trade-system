"""Audit Database Safety Utility (OPB-FINAL-PHASE-GOVERNANCE-001).

Guarantees that audit, forensic, verification, and research tooling
cannot mutate the authoritative production database (db/signals_history.db).

Rules enforced:
1. Authoritative production DB access MUST be immutable read-only (mode=ro&immutable=1).
2. Direct instantiation of write-capable components (e.g. SignalTracker)
   against db/signals_history.db is strictly blocked.
3. Legacy APIs requiring a physical database file must operate on an isolated temporary copy.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import tempfile
from pathlib import Path


PRODUCTION_DB_BASENAME = "signals_history.db"
PRODUCTION_DB_REL_PATH = os.path.normpath("db/signals_history.db")


def is_production_db_path(path_or_uri: str | Path) -> bool:
    """Returns True if path_or_uri refers to the production signals_history.db."""
    s = str(path_or_uri).strip()
    if s.startswith("file:"):
        # Strip query parameters
        s = s.split("?")[0].replace("file:", "").strip()
    
    # Check if basename matches production DB
    norm = os.path.normpath(s)
    if os.path.basename(norm).lower() == PRODUCTION_DB_BASENAME.lower():
        # Check if resolving points to our workspace db/signals_history.db
        try:
            prod_real = os.path.realpath(PRODUCTION_DB_REL_PATH)
            target_real = os.path.realpath(norm)
            if prod_real == target_real:
                return True
        except Exception:
            pass
        if "signals_history.db" in norm.lower() and not "candidate_baseline" in norm and not "pre_restore" in norm and not "temp" in norm and not "isolated" in norm:
            return True
    return False


def assert_not_production_db(db_path: str | Path) -> None:
    """Hard safety assertion: raises PermissionError if db_path targets the production database in write mode."""
    if is_production_db_path(db_path):
        raise PermissionError(
            f"OPB-FINAL-PHASE-GOVERNANCE-001 VIOLATION: Write-capable access to production database "
            f"'{db_path}' is strictly prohibited. Use get_readonly_audit_connection() or create_isolated_audit_db_copy()."
        )


def validate_safe_audit_db_uri(uri_or_path: str | Path) -> str:
    """Validates that access to production database is explicitly read-only and immutable."""
    s = str(uri_or_path).strip()
    if is_production_db_path(s):
        if not s.startswith("file:"):
            raise PermissionError(
                f"OPB-FINAL-PHASE-GOVERNANCE-001: Production DB '{s}' cannot be accessed via raw file path. "
                f"Must use URI format with mode=ro&immutable=1."
            )
        # Check query parameters
        parts = s.split("?")
        if len(parts) < 2:
            raise PermissionError("OPB-FINAL-PHASE-GOVERNANCE-001: URI missing mode=ro&immutable=1 query parameters.")
        query = parts[1]
        params = dict(param.split("=") for param in query.split("&") if "=" in param)
        if params.get("mode") != "ro" or params.get("immutable") != "1":
            raise PermissionError(
                f"OPB-FINAL-PHASE-GOVERNANCE-001: URI '{s}' must have mode=ro and immutable=1. Found: {params}"
            )
    return s


def get_readonly_audit_connection(db_path: str | Path = PRODUCTION_DB_REL_PATH) -> sqlite3.Connection:
    """Constructs a guaranteed immutable read-only SQLite connection to the specified database."""
    abs_path = os.path.abspath(str(db_path)).replace("\\", "/")
    uri = f"file:{abs_path}?mode=ro&immutable=1"
    conn = sqlite3.connect(uri, uri=True)
    return conn


def create_isolated_audit_db_copy(src_db_path: str | Path = PRODUCTION_DB_REL_PATH) -> str:
    """Creates a byte-for-byte isolated temporary copy of the database.

    The returned path is safe for legacy audit APIs that may trigger SQLite write transactions
    or DDL migrations without endangering the authoritative production database.
    """
    src_real = os.path.realpath(str(src_db_path))
    if not os.path.exists(src_real):
        raise FileNotFoundError(f"Source database not found: {src_real}")
    
    # Create temp file in system temp or scratch
    fd, tmp_path = tempfile.mkstemp(prefix="isolated_audit_signals_", suffix=".db")
    os.close(fd)
    
    shutil.copy2(src_real, tmp_path)
    return Path(tmp_path)
