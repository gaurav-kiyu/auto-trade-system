"""
MongoDB Database Adapter — implements DatabasePort for MongoDB document store.

Wraps pymongo (MongoClient) through the DatabasePort interface.
Uses lazy import so pymongo is only required when actually connecting.

Note: MongoDB is a document store, not a SQL database. Some DatabasePort
methods are mapped to MongoDB equivalents:
  - execute(command, args) → db.command(command, *args)
  - fetchone("find", ...) → collection.find_one(...)
  - fetchall("find", ...) → list(collection.find(...))
  - begin/commit/rollback → MongoDB has no multi-doc transactions by default
  - table_exists(name) → name in db.list_collection_names()
  - create_table(name) → create a collection

Usage:
    from core.adapters.database import MongoDBDatabaseAdapter

    db = MongoDBDatabaseAdapter(host="localhost", port=27017, database="trading")
    db.connect()
    db.execute("insert", ("items", {"name": "test", "value": 1.0}))
    result = db.fetchone("find", ("items", {"name": "test"}))
    db.disconnect()
"""

from __future__ import annotations

import logging
import re
import threading
import time
from typing import Any

from core.ports.database import DatabasePort, DatabaseStats

_log = logging.getLogger(__name__)


# ── Connection string parsing ──────────────────────────────────────────────

_MONGO_DSN_RE = re.compile(
    r"^(?:mongodb(?:\+srv)?(?:://)?)?"
    r"(?:(?P<user>[^:]+)(?::(?P<password>[^@]+))?@)?"
    r"(?P<host>[^:/,?]+(?:,[^:/,?]+)*)"
    r"(?::(?P<port>\d+))?"
    r"(?:/(?P<database>[^?]+))?"
    r"(?:\?(?P<params>.+))?$"
)


def _parse_mongo_dsn(dsn: str) -> dict[str, Any]:
    """Parse a MongoDB DSN string into connection parameters.

    Supports formats:
      - mongodb://user:pass@host:27017/database
      - mongodb+srv://host/database
      - mongodb://host:27017,host2:27017/database?replicaSet=rs
    """
    m = _MONGO_DSN_RE.match(dsn)
    if m:
        parts = m.groupdict(default=None)
        params: dict[str, Any] = {"host": dsn}  # Pass DSN directly for MongoDB URI
        if parts["database"]:
            params["database"] = parts["database"]
        return params
    return {"host": dsn}


class MongoDBDatabaseAdapter(DatabasePort):
    """DatabasePort implementation wrapping MongoDB via pymongo.

    Thread-safe: uses an RLock for all connection access.

    Args:
        dsn: Connection URI (``mongodb://user:pass@host:27017/db``)
             or individual keyword arguments.
        **kwargs: Connection parameters (host, port, database, username,
                  password, authSource, replicaSet, ssl, etc.)

    Note:
        Requires ``pymongo`` to be installed. Uses lazy import so
        the ImportError only surfaces when ``connect()`` is called.
    """

    def __init__(
        self,
        dsn: str | None = None,
        **kwargs: Any,
    ) -> None:
        self._dsn = dsn
        self._kwargs = kwargs
        self._client: Any = None  # MongoClient (lazy type)
        self._db: Any = None      # Database reference
        self._lock = threading.RLock()
        self._queries: int = 0
        self._errors: int = 0
        self._last_error: str = ""

        # Resolve connection params from DSN or kwargs
        self._conn_params: dict[str, Any] = {"host": "localhost", "port": 27017}
        if dsn:
            self._conn_params = _parse_mongo_dsn(dsn)
        # kwargs override DSN-derived values
        for key in ("host", "port", "database", "username", "password",
                     "authSource", "replicaSet", "ssl", "tls",
                     "connectTimeoutMS", "socketTimeoutMS", "serverSelectionTimeoutMS"):
            if key in kwargs:
                self._conn_params[key] = kwargs[key]
        self._db_name: str = str(self._conn_params.pop("database", "trading"))

    # ── Connection lifecycle ─────────────────────────────────────────────

    def connect(self) -> bool:
        """Establish a MongoDB connection.

        Returns True if the connection was established, False if already open.

        Raises:
            ImportError: If pymongo is not installed.
            ConnectionError: If connection fails.
        """
        if self._client is not None:
            return False

        try:
            import pymongo
        except ImportError as exc:
            raise ImportError(
                "pymongo is required for MongoDBDatabaseAdapter. "
                "Install it with: pip install pymongo"
            ) from exc

        try:
            self._client = pymongo.MongoClient(**self._conn_params)
            # Verify connection with a server ping
            self._client.admin.command("ping")
            self._db = self._client[self._db_name]
            _log.info(
                "[MONGO_DB] Connected to %s/%s",
                self._conn_params.get("host", "?"),
                self._db_name,
            )
            return True
        except Exception as exc:
            self._client = None
            self._db = None
            _log.error("[MONGO_DB] Connection failed: %s", exc)
            raise ConnectionError(f"MongoDB connection failed: {exc}") from exc

    def disconnect(self) -> None:
        """Close the MongoDB connection. Safe to call multiple times."""
        with self._lock:
            if self._client is not None:
                try:
                    self._client.close()
                except Exception as exc:
                    _log.warning("[MONGO_DB] Error closing connection: %s", exc)
                finally:
                    self._client = None
                    self._db = None
                    _log.info("[MONGO_DB] Disconnected")

    def is_connected(self) -> bool:
        if self._client is None:
            return False
        try:
            self._client.admin.command("ping")
            return True
        except Exception:
            return False

    def reconnect(self) -> bool:
        self.disconnect()
        return self.connect()

    # ── Execution ────────────────────────────────────────────────────────

    def execute(
        self,
        sql: str,
        params: tuple[Any, ...] | dict[str, Any] = (),
    ) -> Any:
        """Execute a MongoDB operation.

        Args:
            sql: Operation type (``insert``, ``update``, ``delete``,
                 ``command``, or a collection method name).
            params: (collection_name, *args) or (collection_name, kwargs_dict).

        Examples:
            adapter.execute("insert", ("items", {"name": "test"}))
            adapter.execute("command", ("ping",))
            adapter.execute("delete_many", ("items", {}))
        """
        client = self._require_client()
        db = self._db
        with self._lock:
            try:
                if not isinstance(params, (tuple, list)):
                    params = (params,)
                if not params:
                    result = db.command(sql)
                elif sql == "command":
                    result = db.command(*params)
                elif sql in ("insert", "insert_one"):
                    result = db[params[0]].insert_one(params[1] if len(params) > 1 else {})
                elif sql in ("insert_many",):
                    result = db[params[0]].insert_many(params[1] if len(params) > 1 else [])
                elif sql in ("find", "find_one"):
                    coll = params[0]
                    filt = params[1] if len(params) > 1 else {}
                    projection = params[2] if len(params) > 2 else None
                    if sql == "find_one":
                        result = db[coll].find_one(filt, projection)
                    else:
                        result = list(db[coll].find(filt, projection))
                elif sql in ("update", "update_one"):
                    result = db[params[0]].update_one(params[1], params[2] if len(params) > 2 else {"$set": params[1]})
                elif sql in ("update_many",):
                    result = db[params[0]].update_many(params[1] if len(params) > 1 else {}, params[2] if len(params) > 2 else {"$set": {}})
                elif sql in ("delete", "delete_one"):
                    result = db[params[0]].delete_one(params[1] if len(params) > 1 else {})
                elif sql in ("delete_many",):
                    result = db[params[0]].delete_many(params[1] if len(params) > 1 else {})
                elif sql in ("aggregate",):
                    result = list(db[params[0]].aggregate(params[1] if len(params) > 1 else []))
                elif sql in ("count", "count_documents"):
                    result = db[params[0]].count_documents(params[1] if len(params) > 1 else {})
                else:
                    # Direct collection method call
                    coll_name = params[0] if params else ""
                    if coll_name:
                        method = getattr(db[coll_name], sql, None)
                        if method:
                            result = method(*params[1:])
                        else:
                            result = db.command(sql, *params)
                    else:
                        result = db.command(sql, *params)
                self._queries += 1
                return result
            except Exception as exc:
                self._errors += 1
                self._last_error = str(exc)[:200]
                _log.warning("[MONGO_DB] Execute error: %s — OP: %s", exc, sql)
                raise

    def execute_many(
        self,
        sql: str,
        params_list: list[tuple[Any, ...] | dict[str, Any]],
    ) -> int:
        """Execute the same operation with multiple parameter sets."""
        count = 0
        for params in params_list:
            self.execute(sql, params)
            count += 1
        return count

    def fetchone(self, sql: str, params: tuple[Any, ...] | dict[str, Any] = ()) -> Any | None:
        try:
            return self.execute(sql, params)
        except Exception as exc:
            _log.warning("[MONGO_DB] fetchone error: %s", exc)
            return None

    def fetchall(self, sql: str, params: tuple[Any, ...] | dict[str, Any] = ()) -> list[Any]:
        try:
            result = self.execute(sql, params)
            if result is None:
                return []
            if isinstance(result, (list, tuple)):
                return list(result)
            return [result]
        except Exception as exc:
            _log.warning("[MONGO_DB] fetchall error: %s", exc)
            return []

    # ── Transactions ─────────────────────────────────────────────────────

    def begin(self) -> None:
        """Log warning — MongoDB transactions require a replica set."""
        _log.warning("[MONGO_DB] begin() called but transactions require replica set")

    def commit(self) -> None:
        """No-op for standalone MongoDB."""

    def rollback(self) -> None:
        """No-op for standalone MongoDB."""

    # ── DDL helpers ──────────────────────────────────────────────────────

    def table_exists(self, table_name: str) -> bool:
        """Check if a collection exists in the database."""
        try:
            return table_name in self._db.list_collection_names()
        except Exception:
            return False

    def create_table(self, sql: str) -> bool:
        """Create a collection (MongoDB creates implicitly on first insert).

        For MongoDB, this explicitly creates a capped/un-capped collection.
        ``sql`` is interpreted as the collection name.
        """
        try:
            self._db.create_collection(sql)
            self._queries += 1
            return True
        except Exception as exc:
            _log.warning("[MONGO_DB] create_table error: %s", exc)
            return False

    # ── Utilities ────────────────────────────────────────────────────────

    def health_check(self) -> dict[str, Any]:
        start = time.monotonic()
        try:
            connected = self.is_connected()
            server_info = {}
            if connected:
                server_info = self._client.server_info()
            latency = time.monotonic() - start
            return {
                "status": "healthy" if connected else "disconnected",
                "connected": connected,
                "backend": "MongoDB",
                "host": self._conn_params.get("host", "?"),
                "database": self._db_name,
                "latency_ms": round(latency * 1000, 1),
                "queries": self._queries,
                "errors": self._errors,
                "mongodb_version": server_info.get("version", "") if server_info else None,
            }
        except Exception as exc:
            return {
                "status": "unhealthy",
                "connected": False,
                "backend": "MongoDB",
                "error": str(exc)[:200],
            }

    def stats(self) -> DatabaseStats:
        return DatabaseStats(
            db_path=f"{self._conn_params.get('host', '?')}/{self._db_name}",
            is_connected=self.is_connected(),
            total_connections=1,
            queries_executed=self._queries,
            errors=self._errors,
            last_error=self._last_error,
            backend="MongoDB",
        )

    # ── Internal helpers ─────────────────────────────────────────────────

    def _require_client(self) -> Any:
        if self._client is None:
            raise ConnectionError(
                "MongoDB not connected. Call .connect() first."
            )
        return self._client


__all__ = [
    "MongoDBDatabaseAdapter",
]

