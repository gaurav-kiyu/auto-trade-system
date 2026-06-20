"""
Strategy Versioning - Item 13

Track exactly which strategy version traded:
- strategy=orb_breakout
- version=2.3.1
- config_hash=...

Essential for debugging and regression analysis.
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading

from core.db_utils import get_connection
from dataclasses import dataclass, field
from typing import Any

from core.time_provider import time_provider

_log = logging.getLogger(__name__)


@dataclass
class StrategyVersion:
    """Strategy version record"""
    strategy_name: str
    version: str
    config_hash: str
    created_at: str
    is_active: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class TradeRecord:
    """Trade with strategy version info"""
    trade_id: str
    intent_id: str
    strategy_name: str
    strategy_version: str
    config_hash: str
    signal_score: float
    direction: str
    symbol: str
    quantity: int
    entry_price: float
    exit_price: float | None
    pnl: float | None
    entry_time: str
    exit_time: str | None
    outcome: str


class StrategyVersionManager:
    """
    Manages strategy versions and tracks trades with version info.
    """

    PERSISTENCE_PATH = "strategy_versioning.db"

    def __init__(self):
        self._versions: dict[str, list[StrategyVersion]] = {}
        self._lock = threading.RLock()
        self._init_durable_storage()

    def _init_durable_storage(self) -> None:
        """Initialize version tracking storage"""
        try:
            with get_connection(self.PERSISTENCE_PATH) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS strategy_versions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        strategy_name TEXT,
                        version TEXT,
                        config_hash TEXT,
                        created_at TEXT,
                        is_active INTEGER,
                        metadata_json TEXT
                    )
                """)

                conn.execute("""
                    CREATE TABLE IF NOT EXISTS trade_records (
                        trade_id TEXT PRIMARY KEY,
                        intent_id TEXT,
                        strategy_name TEXT,
                        strategy_version TEXT,
                        config_hash TEXT,
                        signal_score REAL,
                        direction TEXT,
                        symbol TEXT,
                        quantity INTEGER,
                        entry_price REAL,
                        exit_price REAL,
                        pnl REAL,
                        entry_time TEXT,
                        exit_time TEXT,
                        outcome TEXT
                    )
                """)

                conn.execute("CREATE INDEX idx_strategy_version ON trade_records(strategy_name, strategy_version)")
                conn.execute("CREATE INDEX idx_trade_time ON trade_records(entry_time)")
                conn.commit()
            _log.info("StrategyVersionManager: Storage initialized")
        except Exception as e:
            _log.error(f"StrategyVersionManager: Failed to init storage: {e} (type: {type(e).__name__})")

    def register_version(
        self,
        strategy_name: str,
        version: str,
        config: dict[str, Any],
        metadata: dict = None,
    ) -> StrategyVersion:
        """Register a new strategy version"""
        config_str = json.dumps(config, sort_keys=True)
        config_hash = hashlib.sha256(config_str.encode()).hexdigest()[:16]

        version_record = StrategyVersion(
            strategy_name=strategy_name,
            version=version,
            config_hash=config_hash,
            created_at=time_provider.format_ts(),
            is_active=True,
            metadata=metadata or {},
        )

        with self._lock:
            if strategy_name not in self._versions:
                self._versions[strategy_name] = []
            self._versions[strategy_name].append(version_record)

        self._persist_version(version_record)
        _log.info(f"Registered version: {strategy_name} v{version} ({config_hash})")

        return version_record

    def get_version(self, strategy_name: str, version: str) -> StrategyVersion | None:
        """Get specific version"""
        with self._lock:
            for v in self._versions.get(strategy_name, []):
                if v.version == version:
                    return v
        return None

    def get_latest_version(self, strategy_name: str) -> StrategyVersion | None:
        """Get latest version for strategy"""
        with self._lock:
            versions = self._versions.get(strategy_name, [])
            if versions:
                return versions[-1]
        return None

    def compute_config_hash(self, config: dict[str, Any]) -> str:
        """Compute hash for config"""
        config_str = json.dumps(config, sort_keys=True)
        return hashlib.sha256(config_str.encode()).hexdigest()[:16]

    def _persist_version(self, version: StrategyVersion) -> None:
        """Persist version to DB"""
        try:
            with get_connection(self.PERSISTENCE_PATH) as conn:
                conn.execute("""
                    INSERT INTO strategy_versions
                    (strategy_name, version, config_hash, created_at, is_active, metadata_json)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    version.strategy_name,
                    version.version,
                    version.config_hash,
                    version.created_at,
                    1 if version.is_active else 0,
                    json.dumps(version.metadata),
                ))
                conn.commit()
        except Exception as e:
            _log.error(f"Failed to persist version: {e} (type: {type(e).__name__})")


_version_manager: StrategyVersionManager | None = None
_manager_lock = threading.RLock()


def get_strategy_version_manager() -> StrategyVersionManager:
    """Get singleton strategy version manager"""
    global _version_manager
    with _manager_lock:
        if _version_manager is None:
            _version_manager = StrategyVersionManager()
        return _version_manager
