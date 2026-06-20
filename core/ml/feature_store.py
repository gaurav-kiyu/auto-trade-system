"""
ML-Ready Feature Store - Item 21

Centralized feature history for ML:
- Feature computation
- Feature versioning
- Feature serving
- Training data export

Foundation for future ML models.
"""
from __future__ import annotations

import json
import logging
import threading

from core.db_utils import get_connection
from dataclasses import dataclass, field
from typing import Any

from core.time_provider import time_provider

_log = logging.getLogger(__name__)


@dataclass
class FeatureVector:
    """Feature vector for ML"""
    vector_id: str
    timestamp: str
    symbol: str
    features: dict[str, float]
    label: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class FeatureDefinition:
    """Feature definition"""
    name: str
    feature_type: str
    description: str
    computation_func: str
    version: str


class FeatureStore:
    """
    ML-ready feature store.
    Centralized feature history with versioning.
    """

    PERSISTENCE_PATH = "feature_store.db"

    def __init__(self):
        self._features: dict[str, list[float]] = {}
        self._definitions: dict[str, FeatureDefinition] = {}
        self._lock = threading.RLock()
        self._init_durable_storage()

    def _init_durable_storage(self) -> None:
        """Initialize feature store"""
        try:
            with get_connection(self.PERSISTENCE_PATH) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS feature_vectors (
                        vector_id TEXT PRIMARY KEY,
                        timestamp TEXT,
                        symbol TEXT,
                        features_json TEXT,
                        label TEXT,
                        metadata_json TEXT
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS feature_definitions (
                        name TEXT PRIMARY KEY,
                        feature_type TEXT,
                        description TEXT,
                        computation_func TEXT,
                        version TEXT
                    )
                """)
                conn.execute("CREATE INDEX idx_timestamp ON feature_vectors(timestamp)")
                conn.execute("CREATE INDEX idx_symbol ON feature_vectors(symbol)")
                conn.commit()
            _log.info("FeatureStore: Storage initialized")
        except Exception as e:
            _log.error(f"FeatureStore: Failed to init storage: {e} (type: {type(e).__name__})")

    def register_feature(self, definition: FeatureDefinition) -> None:
        """Register a feature definition"""
        with self._lock:
            self._definitions[definition.name] = definition
            self._persist_definition(definition)
            _log.info(f"Registered feature: {definition.name} v{definition.version}")

    def store_features(
        self,
        symbol: str,
        features: dict[str, float],
        label: str | None = None,
        metadata: dict = None,
    ) -> FeatureVector:
        """Store feature vector"""
        vector_id = f"FV-{symbol}-{int(time_provider.get_ts())}"

        vector = FeatureVector(
            vector_id=vector_id,
            timestamp=time_provider.format_ts(),
            symbol=symbol,
            features=features,
            label=label,
            metadata=metadata or {},
        )

        self._persist_vector(vector)
        _log.debug(f"Stored features for {symbol}")

        return vector

    def get_features_for_training(
        self,
        symbol: str = None,
        start_time: str = None,
        end_time: str = None,
        limit: int = 10000,
    ) -> list[FeatureVector]:
        """Get features for training"""
        try:
            with get_connection(self.PERSISTENCE_PATH) as conn:
                query = "SELECT * FROM feature_vectors WHERE 1=1"
                params = []

                if symbol:
                    query += " AND symbol = ?"
                    params.append(symbol)
                if start_time:
                    query += " AND timestamp >= ?"
                    params.append(start_time)
                if end_time:
                    query += " AND timestamp <= ?"
                    params.append(end_time)

                query += f" ORDER BY timestamp LIMIT {limit}"

                cursor = conn.execute(query, params)
                return self._rows_to_vectors(cursor)
        except Exception as e:
            _log.error(f"Failed to get features: {e} (type: {type(e).__name__})")
            return []

    def compute_features(self, market_data: dict[str, Any]) -> dict[str, float]:
        """Compute features from market data"""
        features = {}

        if "last_price" in market_data and "open" in market_data:
            features["return"] = (market_data["last_price"] - market_data["open"]) / market_data["open"]

        if "volume" in market_data:
            features["volume"] = float(market_data["volume"])

        if "bid" in market_data and "ask" in market_data:
            features["spread"] = (market_data["ask"] - market_data["bid"]) / market_data["bid"]

        if "iv" in market_data:
            features["iv_rank"] = market_data["iv"]

        return features

    def _persist_vector(self, vector: FeatureVector) -> None:
        """Persist vector to DB"""
        try:
            with get_connection(self.PERSISTENCE_PATH) as conn:
                conn.execute("""
                    INSERT INTO feature_vectors
                    (vector_id, timestamp, symbol, features_json, label, metadata_json)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    vector.vector_id,
                    vector.timestamp,
                    vector.symbol,
                    json.dumps(vector.features),
                    vector.label,
                    json.dumps(vector.metadata),
                ))
                conn.commit()
        except Exception as e:
            _log.error(f"Failed to persist vector: {e} (type: {type(e).__name__})")

    def _persist_definition(self, definition: FeatureDefinition) -> None:
        """Persist feature definition"""
        try:
            with get_connection(self.PERSISTENCE_PATH) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO feature_definitions
                    (name, feature_type, description, computation_func, version)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    definition.name,
                    definition.feature_type,
                    definition.description,
                    definition.computation_func,
                    definition.version,
                ))
                conn.commit()
        except Exception as e:
            _log.error(f"Failed to persist definition: {e} (type: {type(e).__name__})")

    def _rows_to_vectors(self, cursor) -> list[FeatureVector]:
        """Convert DB rows to FeatureVectors"""
        vectors = []
        for row in cursor:
            vectors.append(FeatureVector(
                vector_id=row[0],
                timestamp=row[1],
                symbol=row[2],
                features=json.loads(row[3]),
                label=row[4],
                metadata=json.loads(row[5] or "{}"),
            ))
        return vectors


_feature_store: FeatureStore | None = None
_store_lock = threading.RLock()


def get_feature_store() -> FeatureStore:
    """Get singleton feature store"""
    global _feature_store
    with _store_lock:
        if _feature_store is None:
            _feature_store = FeatureStore()
        return _feature_store
