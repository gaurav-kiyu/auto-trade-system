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

__all__ = [
    "FeatureDefinition",
    "FeatureStore",
    "FeatureVector",
    "get_feature_store",
]

_log = logging.getLogger(__name__)


@dataclass
class FeatureVector:
    """Feature vector for ML with provenance tracking."""
    vector_id: str
    timestamp: str
    symbol: str
    features: dict[str, float]
    label: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    # Data lineage / provenance fields (new)
    source: str | None = None           # e.g., "yfinance", "nse_api", "websocket"
    source_version: str | None = None   # e.g., "v2.53.0"
    computation_chain: list[str] | None = None  # e.g., ["raw_price", "returns", "rolling_mean_5"]
    quality_score: float | None = None  # 0.0-1.0 data quality confidence


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
    ML-ready feature store with data lineage and provenance tracking.

    Centralized feature history with:
    - Feature versioning
    - Feature serving / training data export
    - Data lineage tracking (source, computation chain, quality)
    - Feature provenance queries

    Foundation for future ML models and regulatory explainability.
    """

    PERSISTENCE_PATH = "feature_store.db"

    def __init__(self):
        self._features: dict[str, list[float]] = {}
        self._definitions: dict[str, FeatureDefinition] = {}
        self._lock = threading.RLock()
        self._init_durable_storage()

    def _init_durable_storage(self) -> None:
        """Initialize feature store with lineage support."""
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
                # Data lineage table (new)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS feature_lineage (
                        vector_id TEXT,
                        feature_name TEXT,
                        source TEXT,
                        source_version TEXT,
                        computation_step TEXT,
                        quality_score REAL,
                        computed_at TEXT,
                        PRIMARY KEY (vector_id, feature_name)
                    )
                """)
                # Feature statistics table (new)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS feature_statistics (
                        feature_name TEXT,
                        symbol TEXT,
                        min_val REAL,
                        max_val REAL,
                        mean_val REAL,
                        std_val REAL,
                        count INTEGER,
                        null_count INTEGER,
                        updated_at TEXT,
                        PRIMARY KEY (feature_name, symbol)
                    )
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_timestamp ON feature_vectors(timestamp)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_symbol ON feature_vectors(symbol)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_lineage_source ON feature_lineage(source)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_lineage_vector ON feature_lineage(vector_id)")
                conn.commit()
            _log.info("FeatureStore: Storage initialized with lineage tracking")
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
        metadata: dict | None = None,
        source: str | None = None,
        source_version: str | None = None,
        computation_chain: list[str] | None = None,
        quality_score: float | None = None,
    ) -> FeatureVector:
        """Store feature vector with optional data lineage metadata.

        Args:
            symbol: Trading symbol.
            features: Feature name -> value dict.
            label: Optional label for supervised learning.
            metadata: Optional additional metadata.
            source: Data source (e.g., "yfinance", "nse_api").
            source_version: Source version (e.g., "v2.53.0").
            computation_chain: Chain of computations applied (e.g.,
                ["raw_price", "returns", "rolling_mean_5"]).
            quality_score: Data quality confidence 0.0-1.0.

        Returns:
            The stored FeatureVector with provenance info.
        """
        vector_id = f"FV-{symbol}-{int(time_provider.now().timestamp())}"

        vector = FeatureVector(
            vector_id=vector_id,
            timestamp=time_provider.format_ts(),
            symbol=symbol,
            features=features,
            label=label,
            metadata=metadata or {},
            source=source,
            source_version=source_version,
            computation_chain=computation_chain,
            quality_score=quality_score,
        )

        self._persist_vector(vector)
        self._persist_lineage(vector)
        self._update_statistics(vector)
        _log.debug(f"Stored features for {symbol} "
                   f"(source={source}, quality={quality_score})")

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

    # ── Persistence ────────────────────────────────────────────────────────

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

    def _persist_lineage(self, vector: FeatureVector) -> None:
        """Persist data lineage records for each feature in the vector.

        Records provenance information including source, version, computation
        chain, and quality score for regulatory explainability and debugging.
        """
        if not vector.source and not vector.computation_chain:
            return  # No lineage to record

        try:
            with get_connection(self.PERSISTENCE_PATH) as conn:
                for feature_name in vector.features:
                    # Record each step in the computation chain as a lineage entry
                    chain = vector.computation_chain or []
                    steps = chain if chain else ["raw"]
                    for step_idx, step in enumerate(steps):
                        conn.execute("""
                            INSERT OR REPLACE INTO feature_lineage
                            (vector_id, feature_name, source, source_version,
                             computation_step, quality_score, computed_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                        """, (
                            vector.vector_id,
                            feature_name,
                            vector.source or "unknown",
                            vector.source_version or "",
                            step,
                            vector.quality_score if step_idx == len(steps) - 1 else None,
                            vector.timestamp,
                        ))
                conn.commit()
        except Exception as e:
            _log.error(f"Failed to persist lineage: {e} (type: {type(e).__name__})")

    def _update_statistics(self, vector: FeatureVector) -> None:
        """Update running feature statistics for the given vector.

        Maintains min/max/mean/std/count per (feature_name, symbol) pair
        using incremental Welford's algorithm for numerical stability.
        """
        try:
            with get_connection(self.PERSISTENCE_PATH) as conn:
                for feature_name, value in vector.features.items():
                    symbol = vector.symbol
                    # Fetch current stats
                    row = conn.execute(
                        "SELECT min_val, max_val, mean_val, count FROM feature_statistics "
                        "WHERE feature_name = ? AND symbol = ?",
                        (feature_name, symbol),
                    ).fetchone()

                    if row:
                        cur_min, cur_max, cur_mean, cur_count = row
                        new_count = cur_count + 1
                        # Welford's incremental update for mean
                        delta = value - cur_mean
                        new_mean = cur_mean + delta / new_count
                        new_min = min(cur_min, value) if cur_min is not None else value
                        new_max = max(cur_max, value) if cur_max is not None else value
                    else:
                        new_count = 1
                        new_mean = value
                        new_min = value
                        new_max = value

                    conn.execute("""
                        INSERT OR REPLACE INTO feature_statistics
                        (feature_name, symbol, min_val, max_val, mean_val,
                         count, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (
                        feature_name, symbol, new_min, new_max,
                        round(new_mean, 6), new_count, vector.timestamp,
                    ))
                conn.commit()
        except Exception as e:
            _log.error(f"Failed to update statistics: {e} (type: {type(e).__name__})")

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

    # ── Query methods ──────────────────────────────────────────────────────

    def get_lineage(
        self,
        vector_id: str | None = None,
        feature_name: str | None = None,
        source: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Query data lineage records.

        Args:
            vector_id: Filter by vector ID.
            feature_name: Filter by feature name.
            source: Filter by data source.
            limit: Max results.

        Returns:
            List of lineage records as dicts.
        """
        try:
            with get_connection(self.PERSISTENCE_PATH) as conn:
                query = "SELECT * FROM feature_lineage WHERE 1=1"
                params: list[Any] = []
                if vector_id:
                    query += " AND vector_id = ?"
                    params.append(vector_id)
                if feature_name:
                    query += " AND feature_name = ?"
                    params.append(feature_name)
                if source:
                    query += " AND source = ?"
                    params.append(source)
                query += f" ORDER BY computed_at DESC LIMIT {limit}"

                rows = conn.execute(query, params).fetchall()
                return [
                    {
                        "vector_id": r[0],
                        "feature_name": r[1],
                        "source": r[2],
                        "source_version": r[3],
                        "computation_step": r[4],
                        "quality_score": r[5],
                        "computed_at": r[6],
                    }
                    for r in rows
                ]
        except Exception as e:
            _log.error(f"Failed to query lineage: {e} (type: {type(e).__name__})")
            return []

    def get_feature_statistics(
        self,
        feature_name: str | None = None,
        symbol: str | None = None,
    ) -> list[dict[str, Any]]:
        """Query feature statistics.

        Args:
            feature_name: Filter by feature name.
            symbol: Filter by symbol.

        Returns:
            List of statistics records as dicts.
        """
        try:
            with get_connection(self.PERSISTENCE_PATH) as conn:
                query = "SELECT * FROM feature_statistics WHERE 1=1"
                params: list[Any] = []
                if feature_name:
                    query += " AND feature_name = ?"
                    params.append(feature_name)
                if symbol:
                    query += " AND symbol = ?"
                    params.append(symbol)
                query += " ORDER BY feature_name, symbol"

                rows = conn.execute(query, params).fetchall()
                return [
                    {
                        "feature_name": r[0],
                        "symbol": r[1],
                        "min_val": r[2],
                        "max_val": r[3],
                        "mean_val": r[4],
                        "std_val": r[5],
                        "count": r[6],
                        "null_count": r[7],
                        "updated_at": r[8],
                    }
                    for r in rows
                ]
        except Exception as e:
            _log.error(f"Failed to query statistics: {e} (type: {type(e).__name__})")
            return []

    def get_lineage_summary(self, vector_id: str) -> dict[str, Any]:
        """Get a human-readable lineage summary for a specific vector.

        Tells the story of how a feature vector was created:
        - What source provided the raw data
        - What computations were applied
        - What confidence/quality rating it has

        Useful for:
        - Regulatory explainability
        - Debugging prediction errors
        - Auditing data pipelines
        """
        lineage = self.get_lineage(vector_id=vector_id)
        if not lineage:
            return {
                "vector_id": vector_id,
                "provenance": "No lineage data available",
                "confidence": None,
            }

        sources = set(r["source"] for r in lineage)
        versions = set(r["source_version"] for r in lineage if r["source_version"])
        steps = list(dict.fromkeys(r["computation_step"] for r in lineage))  # ordered unique
        quality_scores = [r["quality_score"] for r in lineage if r["quality_score"] is not None]

        return {
            "vector_id": vector_id,
            "source": ", ".join(sorted(sources)),
            "source_version": ", ".join(sorted(versions)) if versions else "unknown",
            "computation_chain": steps,
            "quality": round(sum(quality_scores) / len(quality_scores), 3) if quality_scores else None,
            "feature_count": len(lineage),
            "provenance": f"Data from {', '.join(sorted(sources))} "
                          f"processed through {len(steps)} computation step(s)",
        }

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
