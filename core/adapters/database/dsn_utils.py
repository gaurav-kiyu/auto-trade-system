"""DSN Parsing Utilities — Shared DSN parsing for PostgreSQL adapters.

Consolidates DSN parsing logic previously duplicated between
``postgres_adapter.py`` and ``connection_pool.py`` into a single
location to ensure consistent behavior across all PostgreSQL adapters.

Usage:
    from core.adapters.database.dsn_utils import parse_pg_dsn

    params = parse_pg_dsn("postgresql://user:pass@localhost:5432/mydb")
    # Returns: {"host": "localhost", "port": 5432, "dbname": "mydb", ...}
"""

from __future__ import annotations

import re
from typing import Any

# Regex for postgresql://user:pass@host:port/dbname format
_DEFAULT_DSN_RE = re.compile(
    r"^(?:postgresql(?:://)?)?"
    r"(?:(?P<user>[^:]+)(?::(?P<password>[^@]+))?@)?"
    r"(?P<host>[^:/]+)"
    r"(?::(?P<port>\d+))?"
    r"(?:/(?P<dbname>.+))?$",
)


def parse_pg_dsn(dsn: str) -> dict[str, Any]:
    """Parse a PostgreSQL DSN string into connection parameters.

    Supports formats:
      - postgresql://user:pass@host:5432/dbname
      - postgresql://user@host/dbname
      - host:port:dbname:user:password (traditional)

    Returns:
        Dict with keys: host, port, dbname, user, password (as available).
        Always includes at least ``host`` — falls back to defaults for
        missing values.

    """
    m = _DEFAULT_DSN_RE.match(dsn)
    if m:
        parts = m.groupdict(default=None)
        params: dict[str, Any] = {}
        if parts["host"]:
            params["host"] = parts["host"]
        if parts["port"]:
            params["port"] = int(parts["port"])
        if parts["dbname"]:
            params["dbname"] = parts["dbname"]
        if parts["user"]:
            params["user"] = parts["user"]
        if parts["password"]:
            params["password"] = parts["password"]
        # Set defaults for common missing fields
        params.setdefault("port", 5432)
        params.setdefault("dbname", "postgres")
        return params

    # Traditional format: host:port:dbname:user:password
    parts = dsn.split(":")
    if len(parts) >= 3:
        return {
            "host": parts[0],
            "port": int(parts[1]) if parts[1].isdigit() else 5432,
            "dbname": parts[2],
            "user": parts[3] if len(parts) > 3 else "postgres",
            "password": parts[4] if len(parts) > 4 else "",
        }

    # Just a hostname
    return {"host": dsn, "port": 5432, "dbname": "postgres"}


__all__ = [
    "parse_pg_dsn",
]
