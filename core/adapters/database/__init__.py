"""
Database Adapters — low-level connection wrappers implementing DatabasePort.

Each adapter wraps a specific database engine (SQLite, PostgreSQL, etc.)
and provides connection lifecycle + raw SQL execution + transaction control.

    from core.adapters.database import SQLiteDatabaseAdapter

    db = SQLiteDatabaseAdapter("trades.db")
    db.connect()
    rows = db.fetchall("SELECT * FROM trades")
    db.disconnect()
"""

from __future__ import annotations

from core.adapters.database.duckdb_adapter import DuckDBDatabaseAdapter
from core.adapters.database.mongodb_adapter import MongoDBDatabaseAdapter
from core.adapters.database.mysql_adapter import MySQLDatabaseAdapter
from core.adapters.database.postgres_adapter import PostgreSQLDatabaseAdapter
from core.adapters.database.redis_adapter import RedisDatabaseAdapter
from core.adapters.database.sqlalchemy_adapter import SQLAlchemyDatabaseAdapter
from core.adapters.database.sqlite_adapter import SQLiteDatabaseAdapter

__all__ = [
    "DuckDBDatabaseAdapter",
    "MongoDBDatabaseAdapter",
    "MySQLDatabaseAdapter",
    "PostgreSQLDatabaseAdapter",
    "RedisDatabaseAdapter",
    "SQLAlchemyDatabaseAdapter",
    "SQLiteDatabaseAdapter",
]

