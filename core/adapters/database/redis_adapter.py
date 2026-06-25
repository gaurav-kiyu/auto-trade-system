"""
Redis Database Adapter — implements DatabasePort for Redis key-value store.

Wraps redis-py (StrictRedis) through the DatabasePort interface.
Uses lazy import so redis is only required when actually connecting.

Note: Redis is a key-value store, not a SQL database. Some DatabasePort
methods are mapped to Redis equivalents:
  - execute(command, args) → Redis command execution
  - fetchone(key) → GET key
  - fetchall(pattern) → KEYS pattern + MGET
  - table_exists(key) → EXISTS key
  - begin/commit/rollback → MULTI/EXEC/DISCARD

Usage:
    from core.adapters.database import RedisDatabaseAdapter

    db = RedisDatabaseAdapter(host="localhost", port=6379, db=0)
    db.connect()
    db.execute("SET", "mykey", "myvalue")
    val = db.fetchone("GET", "mykey")
    db.disconnect()

    # Context manager:
    with RedisDatabaseAdapter("redis://localhost:6379/0") as db:
        db.execute("SET", "k", "v")
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

_REDIS_DSN_RE = re.compile(
    r"^(?:redis(?:://)?)?"
    r"(?:(?P<user>[^:]+)(?::(?P<password>[^@]+))?@)?"
    r"(?P<host>[^:/]+)"
    r"(?::(?P<port>\d+))?"
    r"(?:/(?P<db>\d+))?"
    r"(?:\?(?P<params>.+))?$"
)


def _parse_redis_dsn(dsn: str) -> dict[str, Any]:
    """Parse a Redis DSN string into connection parameters.

    Supports formats:
      - redis://user:pass@host:6379/0
      - redis://host:6379/0
      - host:6379:0:user:password (traditional)
      - host (simple — defaults to port 6379)
    """
    m = _REDIS_DSN_RE.match(dsn)
    if m:
        parts = m.groupdict(default=None)
        params: dict[str, Any] = {}
        if parts["host"]:
            params["host"] = parts["host"]
        if parts["port"]:
            params["port"] = int(parts["port"])
        else:
            params["port"] = 6379  # default Redis port
        if parts.get("db") is not None:
            params["db"] = int(parts["db"])
        else:
            params["db"] = 0  # default Redis DB
        if parts["user"]:
            params["username"] = parts["user"]
        if parts["password"]:
            params["password"] = parts["password"]
        return params

    # Traditional format: host:port:db:password
    parts = dsn.split(":")
    if len(parts) >= 2:
        result: dict[str, Any] = {
            "host": parts[0],
            "port": int(parts[1]) if parts[1].isdigit() else 6379,
        }
        if len(parts) > 2 and parts[2].isdigit():
            result["db"] = int(parts[2])
        if len(parts) > 3:
            result["password"] = parts[3]
        return result

    return {"host": dsn, "port": 6379}


class RedisDatabaseAdapter(DatabasePort):
    """DatabasePort implementation wrapping Redis via redis-py.

    Thread-safe: uses an RLock for all connection access.

    Args:
        dsn: Connection string (``redis://user:pass@host:port/db``)
             or individual keyword arguments.
        **kwargs: Connection parameters (host, port, db, password,
                  socket_connect_timeout, socket_timeout, etc.)

    Note:
        Requires ``redis`` to be installed. Uses lazy import so
        the ImportError only surfaces when ``connect()`` is called.
    """

    def __init__(
        self,
        dsn: str | None = None,
        **kwargs: Any,
    ) -> None:
        self._dsn = dsn
        self._kwargs = kwargs
        self._client: Any = None  # redis.Redis (lazy type)
        self._lock = threading.RLock()
        self._queries: int = 0
        self._errors: int = 0
        self._last_error: str = ""

        # Resolve connection params from DSN or kwargs
        self._conn_params: dict[str, Any] = {}
        if dsn:
            self._conn_params = _parse_redis_dsn(dsn)
        # kwargs override DSN-derived values
        for key in ("host", "port", "db", "password", "username",
                     "socket_connect_timeout", "socket_timeout",
                     "socket_keepalive", "ssl", "ssl_certfile",
                     "ssl_keyfile", "ssl_ca_certs", "decode_responses"):
            if key in kwargs:
                self._conn_params[key] = kwargs[key]
        # Default to decode_responses=True for usability
        self._conn_params.setdefault("decode_responses", True)

    # ── Connection lifecycle ─────────────────────────────────────────────

    def connect(self) -> bool:
        """Establish a Redis connection.

        Returns True if the connection was established, False if already open.

        Raises:
            ImportError: If redis is not installed.
            ConnectionError: If connection parameters are missing or connection fails.
        """
        if self._client is not None:
            return False

        try:
            import redis as redis_module
        except ImportError as exc:
            raise ImportError(
                "redis is required for RedisDatabaseAdapter. "
                "Install it with: pip install redis"
            ) from exc

        if not self._conn_params:
            raise ConnectionError(
                "No connection parameters provided. "
                "Pass a DSN string or connection keyword arguments."
            )

        try:
            self._client = redis_module.StrictRedis(**self._conn_params)
            # Verify connection with a ping
            self._client.ping()
            _log.info(
                "[REDIS_DB] Connected to %s@%s:%s/%s",
                self._conn_params.get("username", "default"),
                self._conn_params.get("host", "?"),
                self._conn_params.get("port", "?"),
                self._conn_params.get("db", 0),
            )
            return True
        except Exception as exc:
            self._client = None
            _log.error("[REDIS_DB] Connection failed: %s", exc)
            raise ConnectionError(f"Redis connection failed: {exc}") from exc

    def disconnect(self) -> None:
        """Close the Redis connection. Safe to call multiple times."""
        with self._lock:
            if self._client is not None:
                try:
                    self._client.close()
                except Exception as exc:
                    _log.warning("[REDIS_DB] Error closing connection: %s", exc)
                finally:
                    self._client = None
                    _log.info("[REDIS_DB] Disconnected")

    def is_connected(self) -> bool:
        if self._client is None:
            return False
        try:
            return self._client.ping()
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
        """Execute a Redis command.

        Args:
            sql: Redis command name (e.g. ``SET``, ``GET``, ``LPUSH``).
            params: Command arguments as a tuple.

        Returns:
            The Redis command response.
        """
        client = self._require_client()
        with self._lock:
            try:
                result = client.execute_command(sql, *params)
                self._queries += 1
                return result
            except Exception as exc:
                self._errors += 1
                self._last_error = str(exc)[:200]
                _log.warning("[REDIS_DB] Execute error: %s — CMD: %s", exc, sql)
                raise

    def execute_many(
        self,
        sql: str,
        params_list: list[tuple[Any, ...] | dict[str, Any]],
    ) -> int:
        """Execute the same Redis command with multiple parameter sets via pipeline.

        Args:
            sql: Redis command name.
            params_list: List of parameter tuples.

        Returns:
            Number of commands executed.
        """
        client = self._require_client()
        with self._lock:
            try:
                pipe = client.pipeline()
                for params in params_list:
                    pipe.execute_command(sql, *params)
                results = pipe.execute()
                self._queries += len(params_list)
                return len(results)
            except Exception as exc:
                self._errors += 1
                self._last_error = str(exc)[:200]
                _log.warning("[REDIS_DB] ExecuteMany error: %s — CMD: %s", exc, sql)
                raise

    def fetchone(self, sql: str, params: tuple[Any, ...] | dict[str, Any] = ()) -> Any | None:
        """Fetch a single result from a Redis command.

        Args:
            sql: Redis command (e.g. ``GET``, ``HGETALL``).
            params: Command arguments.

        Returns:
            Single result or None.
        """
        try:
            return self.execute(sql, params)
        except Exception as exc:
            _log.warning("[REDIS_DB] fetchone error: %s", exc)
            return None

    def fetchall(self, sql: str, params: tuple[Any, ...] | dict[str, Any] = ()) -> list[Any]:
        """Fetch all results from a Redis command.

        For commands like ``KEYS *``, returns the list of matching keys.
        For ``MGET``, returns the list of values.

        Args:
            sql: Redis command (e.g. ``KEYS``, ``MGET``).
            params: Command arguments.

        Returns:
            List of results.
        """
        try:
            result = self.execute(sql, params)
            if result is None:
                return []
            if isinstance(result, (list, tuple)):
                return list(result)
            return [result]
        except Exception as exc:
            _log.warning("[REDIS_DB] fetchall error: %s", exc)
            return []

    # ── Transactions ─────────────────────────────────────────────────────

    def begin(self) -> None:
        """Start a Redis transaction (MULTI)."""
        self.execute("MULTI")

    def commit(self) -> None:
        """Execute the Redis transaction (EXEC)."""
        self.execute("EXEC")

    def rollback(self) -> None:
        """Discard the Redis transaction (DISCARD)."""
        try:
            self.execute("DISCARD")
        except Exception as _rb_exc:
            _log.debug("[REDIS_DB] Rollback (DISCARD) skipped: %s", _rb_exc)

    # ── DDL helpers ──────────────────────────────────────────────────────

    def table_exists(self, table_name: str) -> bool:
        """Check if a key exists in Redis (analogous to table existence)."""
        try:
            result = self.execute("EXISTS", (table_name,))
            return result > 0
        except Exception:
            return False

    def create_table(self, sql: str) -> bool:
        """No-op for Redis (no DDL). Always returns True."""
        return True

    # ── Utilities ────────────────────────────────────────────────────────

    def health_check(self) -> dict[str, Any]:
        start = time.monotonic()
        try:
            connected = self.is_connected()
            info = {}
            if connected:
                self.execute("PING")
                try:
                    info = self.execute("INFO", ("server",))
                except Exception as _info_exc:
                    _log.debug("[REDIS_DB] INFO fetch skipped: %s", _info_exc)
            latency = time.monotonic() - start
            return {
                "status": "healthy" if connected else "disconnected",
                "connected": connected,
                "backend": "Redis",
                "host": self._conn_params.get("host", "?"),
                "port": self._conn_params.get("port", 6379),
                "db": self._conn_params.get("db", 0),
                "latency_ms": round(latency * 1000, 1),
                "queries": self._queries,
                "errors": self._errors,
                "redis_version": self._parse_redis_version(info) if connected else None,
            }
        except Exception as exc:
            return {
                "status": "unhealthy",
                "connected": False,
                "backend": "Redis",
                "error": str(exc)[:200],
            }

    def _parse_redis_version(self, info: Any) -> str | None:
        """Extract redis_version from INFO SERVER output."""
        if isinstance(info, dict):
            return info.get("redis_version")
        if isinstance(info, str):
            for line in info.splitlines():
                if line.startswith("redis_version:"):
                    return line.split(":", 1)[1].strip()
        return None

    def stats(self) -> DatabaseStats:
        return DatabaseStats(
            db_path=f"{self._conn_params.get('host', '?')}:{self._conn_params.get('port', 6379)}/{self._conn_params.get('db', 0)}",
            is_connected=self.is_connected(),
            total_connections=1,
            queries_executed=self._queries,
            errors=self._errors,
            last_error=self._last_error,
            backend="Redis",
        )

    # ── Internal helpers ─────────────────────────────────────────────────

    def _require_client(self) -> Any:
        if self._client is None:
            raise ConnectionError(
                "Redis not connected. Call .connect() first."
            )
        return self._client


__all__ = [
    "RedisDatabaseAdapter",
]

