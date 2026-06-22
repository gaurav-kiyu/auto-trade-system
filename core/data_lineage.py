"""
Data Lineage Engine (v1.0)

Standalone module for tracking data provenance, computation chains, and
impact analysis across the platform. Extracted from FeatureStore's embedded
lineage tracking into a dedicated module with its own API.

Provides:
- Provenance record tracking with source, version, computation step metadata
- Lineage query API (by vector_id, feature_name, source, time range)
- Impact analysis: which downstream objects depend on a given source
- Integration bridge with FeatureStore
- Human-readable lineage summaries for regulatory explainability

Part of the Master Constitution Prompt v1.0 — Additional Capabilities.
"""
from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from core.db_utils import get_connection
from core.time_provider import time_provider

_log = logging.getLogger(__name__)

__all__ = [
    "DataLineageEngine",
    "DataLineageRecord",
    "ProvenanceChain",
    "ImpactAnalysis",
    "get_lineage_engine",
]


# ── Data Structures ───────────────────────────────────────────────────────────


@dataclass
class DataLineageRecord:
    """Single provenance record tracking a data artifact's lineage.

    Attributes:
        artifact_id: Unique ID of the data artifact (e.g., feature vector ID).
        artifact_type: Type of artifact (feature_vector, trade_signal, prediction, report).
        feature_name: Name of the specific feature/data element.
        source: Data source (e.g., "yfinance", "nse_api", "websocket", "broker").
        source_version: Version of the data source (e.g., "v2.53.0").
        computation_step: Step in the computation chain (e.g., "raw", "returns", "rolling_mean_5").
        quality_score: Data quality confidence 0.0-1.0.
        computed_at: Timestamp when this record was created.
        metadata: Additional metadata as JSON-serializable dict.
    """
    artifact_id: str
    artifact_type: str = "feature_vector"
    feature_name: str = ""
    source: str = "unknown"
    source_version: str = ""
    computation_step: str = "raw"
    quality_score: float | None = None
    computed_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProvenanceChain:
    """Complete provenance chain for an artifact.

    Tells the full story of how a data artifact was created,
    from raw source through all computation steps.
    """
    artifact_id: str
    artifact_type: str
    sources: list[str]
    computation_chain: list[str]
    quality: float | None
    feature_count: int
    created_at: str
    summary: str


@dataclass
class ImpactAnalysis:
    """Results of an impact analysis query.

    Shows which downstream artifacts depend on a given source,
    useful for understanding blast radius of data source changes.
    """
    source: str
    downstream_artifacts: list[dict[str, str]]
    artifact_count: int
    feature_count: int
    last_used: str | None


# ── Main Engine ───────────────────────────────────────────────────────────────


class DataLineageEngine:
    """Data Lineage Engine — tracks and queries data provenance.

    Thread-safe singleton. Persists lineage records to SQLite for
    auditability and regulatory compliance.
    """

    PERSISTENCE_PATH = "data_lineage.db"

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or self.PERSISTENCE_PATH
        self._lock = threading.RLock()
        self._init_storage()

    def _init_storage(self) -> None:
        """Initialize the lineage storage schema."""
        try:
            with get_connection(self._db_path) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS data_lineage (
                        artifact_id TEXT,
                        artifact_type TEXT DEFAULT 'feature_vector',
                        feature_name TEXT,
                        source TEXT,
                        source_version TEXT DEFAULT '',
                        computation_step TEXT DEFAULT 'raw',
                        quality_score REAL,
                        computed_at TEXT,
                        metadata_json TEXT DEFAULT '{}',
                        PRIMARY KEY (artifact_id, feature_name, computation_step)
                    )
                """)
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_dl_artifact
                    ON data_lineage(artifact_id)
                """)
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_dl_source
                    ON data_lineage(source)
                """)
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_dl_feature
                    ON data_lineage(feature_name)
                """)
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_dl_computed_at
                    ON data_lineage(computed_at)
                """)
                conn.commit()
            _log.info("DataLineageEngine: Storage initialized at %s", self._db_path)
        except Exception as e:
            _log.error("DataLineageEngine: Failed to init storage: %s", e)

    # ── Record Methods ────────────────────────────────────────────────────

    def record_lineage(self, record: DataLineageRecord) -> bool:
        """Record a single lineage entry.

        Args:
            record: The lineage record to persist.

        Returns:
            True if recorded successfully.
        """
        try:
            with get_connection(self._db_path) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO data_lineage
                    (artifact_id, artifact_type, feature_name, source,
                     source_version, computation_step, quality_score,
                     computed_at, metadata_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    record.artifact_id,
                    record.artifact_type,
                    record.feature_name,
                    record.source,
                    record.source_version,
                    record.computation_step,
                    record.quality_score,
                    record.computed_at or time_provider.format_ts(),
                    json.dumps(record.metadata),
                ))
                conn.commit()
            return True
        except Exception as e:
            _log.error("DataLineageEngine: Failed to record lineage: %s", e)
            return False

    def record_computation_chain(
        self,
        artifact_id: str,
        artifact_type: str,
        feature_name: str,
        source: str,
        computation_chain: list[str],
        source_version: str = "",
        quality_score: float | None = None,
        metadata: dict | None = None,
    ) -> bool:
        """Record a complete computation chain for a feature.

        Creates one lineage record per step in the chain, capturing
        the progressive transformation from raw data to final feature.

        Args:
            artifact_id: Unique artifact identifier.
            artifact_type: Type of artifact.
            feature_name: Feature name.
            source: Data source.
            computation_chain: Ordered list of computation steps.
            source_version: Version of data source.
            quality_score: Final quality score (applied to last step).
            metadata: Additional metadata.

        Returns:
            True if all steps recorded successfully.
        """
        ts = time_provider.format_ts()
        metadata_json = json.dumps(metadata or {})

        try:
            with get_connection(self._db_path) as conn:
                steps = computation_chain if computation_chain else ["raw"]
                for step_idx, step in enumerate(steps):
                    qs = quality_score if step_idx == len(steps) - 1 else None
                    conn.execute("""
                        INSERT OR REPLACE INTO data_lineage
                        (artifact_id, artifact_type, feature_name, source,
                         source_version, computation_step, quality_score,
                         computed_at, metadata_json)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        artifact_id,
                        artifact_type,
                        feature_name,
                        source,
                        source_version,
                        step,
                        qs,
                        ts,
                        metadata_json,
                    ))
                conn.commit()
            return True
        except Exception as e:
            _log.error("DataLineageEngine: Failed to record chain: %s", e)
            return False

    # ── Query Methods ─────────────────────────────────────────────────────

    def query_lineage(
        self,
        artifact_id: str | None = None,
        feature_name: str | None = None,
        source: str | None = None,
        artifact_type: str | None = None,
        start_time: str | None = None,
        end_time: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Query lineage records with flexible filters.

        Args:
            artifact_id: Filter by artifact ID.
            feature_name: Filter by feature name.
            source: Filter by data source.
            artifact_type: Filter by artifact type.
            start_time: Filter by computed_at >= start_time (ISO format).
            end_time: Filter by computed_at <= end_time (ISO format).
            limit: Max results.

        Returns:
            List of lineage records as dicts.
        """
        try:
            with get_connection(self._db_path) as conn:
                query = "SELECT * FROM data_lineage WHERE 1=1"
                params: list[Any] = []

                if artifact_id:
                    query += " AND artifact_id = ?"
                    params.append(artifact_id)
                if feature_name:
                    query += " AND feature_name = ?"
                    params.append(feature_name)
                if source:
                    query += " AND source = ?"
                    params.append(source)
                if artifact_type:
                    query += " AND artifact_type = ?"
                    params.append(artifact_type)
                if start_time:
                    query += " AND computed_at >= ?"
                    params.append(start_time)
                if end_time:
                    query += " AND computed_at <= ?"
                    params.append(end_time)

                query += " ORDER BY computed_at DESC"
                query += f" LIMIT {limit}"

                rows = conn.execute(query, params).fetchall()
                return [
                    {
                        "artifact_id": r[0],
                        "artifact_type": r[1],
                        "feature_name": r[2],
                        "source": r[3],
                        "source_version": r[4],
                        "computation_step": r[5],
                        "quality_score": r[6],
                        "computed_at": r[7],
                        "metadata": json.loads(r[8] or "{}"),
                    }
                    for r in rows
                ]
        except Exception as e:
            _log.error("DataLineageEngine: Failed to query lineage: %s", e)
            return []

    def get_provenance(self, artifact_id: str) -> ProvenanceChain | None:
        """Get the full provenance chain for an artifact.

        Args:
            artifact_id: Artifact to trace.

        Returns:
            ProvenanceChain with full story, or None if not found.
        """
        records = self.query_lineage(artifact_id=artifact_id)
        if not records:
            return None

        sources = list(dict.fromkeys(r["source"] for r in records))
        steps = list(dict.fromkeys(
            r["computation_step"] for r in records
            if r["computation_step"] and r["computation_step"] != "raw"
        ))
        quality_scores = [
            r["quality_score"] for r in records
            if r["quality_score"] is not None
        ]

        # Prepend "raw" if steps exist but don't include it
        chain = ["raw"] + steps if steps else ["raw"]

        return ProvenanceChain(
            artifact_id=artifact_id,
            artifact_type=records[0]["artifact_type"],
            sources=sources,
            computation_chain=chain,
            quality=round(sum(quality_scores) / len(quality_scores), 3)
                if quality_scores else None,
            feature_count=len(set(r["feature_name"] for r in records)),
            created_at=records[0]["computed_at"],
            summary=(
                f"Data from {', '.join(sources)} "
                f"processed through {len(chain)} computation step(s)"
            ),
        )

    def get_provenance_summary(self, artifact_id: str) -> dict[str, Any]:
        """Get a human-readable provenance summary for an artifact.

        Useful for:
        - Regulatory explainability
        - Debugging prediction errors
        - Auditing data pipelines

        Args:
            artifact_id: Artifact to summarize.

        Returns:
            Dict with provenance summary.
        """
        chain = self.get_provenance(artifact_id)
        if not chain:
            return {
                "artifact_id": artifact_id,
                "provenance": "No lineage data available",
                "confidence": None,
            }

        return {
            "artifact_id": artifact_id,
            "artifact_type": chain.artifact_type,
            "sources": chain.sources,
            "computation_chain": chain.computation_chain,
            "quality": chain.quality,
            "feature_count": chain.feature_count,
            "created_at": chain.created_at,
            "provenance": chain.summary,
        }

    def analyze_impact(self, source: str) -> ImpactAnalysis:
        """Analyze the downstream impact of a data source.

        Shows which artifacts depend on a given source, useful for
        understanding blast radius when a data source changes or fails.

        Args:
            source: The data source to analyze.

        Returns:
            ImpactAnalysis with downstream artifact details.
        """
        records = self.query_lineage(source=source)
        if not records:
            return ImpactAnalysis(
                source=source,
                downstream_artifacts=[],
                artifact_count=0,
                feature_count=0,
                last_used=None,
            )

        # Group by artifact_id
        artifacts: dict[str, set[str]] = {}
        for r in records:
            aid = r["artifact_id"]
            if aid not in artifacts:
                artifacts[aid] = set()
            artifacts[aid].add(r["feature_name"])

        downstream = [
            {
                "artifact_id": aid,
                "features": ", ".join(sorted(features)),
                "feature_count": len(features),
            }
            for aid, features in sorted(artifacts.items())
        ]

        timestamps = [r["computed_at"] for r in records if r["computed_at"]]
        last_used = max(timestamps) if timestamps else None

        return ImpactAnalysis(
            source=source,
            downstream_artifacts=downstream,
            artifact_count=len(downstream),
            feature_count=len(set(r["feature_name"] for r in records)),
            last_used=last_used,
        )

    def get_recent_lineage(
        self,
        minutes: int = 60,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Get lineage records from the last N minutes.

        Args:
            minutes: Lookback window in minutes.
            limit: Max results.

        Returns:
            Recent lineage records.
        """
        try:
            now = time_provider.now()
            start = now - timedelta(minutes=minutes)
            start_ts = start.isoformat()
            return self.query_lineage(start_time=start_ts, limit=limit)
        except Exception as e:
            _log.error("DataLineageEngine: Recent query failed: %s", e)
            return []

    def get_source_health(self) -> list[dict[str, Any]]:
        """Get health summary of all data sources.

        Returns per-source metrics: total artifacts, average quality,
        most recent use, feature diversity.

        Returns:
            List of source health dicts.
        """
        try:
            with get_connection(self._db_path) as conn:
                rows = conn.execute("""
                    SELECT
                        source,
                        COUNT(DISTINCT artifact_id) AS artifact_count,
                        COUNT(DISTINCT feature_name) AS feature_count,
                        ROUND(AVG(quality_score), 3) AS avg_quality,
                        MAX(computed_at) AS last_used
                    FROM data_lineage
                    GROUP BY source
                    ORDER BY last_used DESC
                """).fetchall()
                return [
                    {
                        "source": r[0],
                        "artifact_count": r[1],
                        "feature_count": r[2],
                        "avg_quality": r[3],
                        "last_used": r[4],
                    }
                    for r in rows
                ]
        except Exception as e:
            _log.error("DataLineageEngine: Source health query failed: %s", e)
            return []

    # ── Integration Bridge ────────────────────────────────────────────────

    def record_from_feature_store(
        self,
        vector_id: str,
        feature_name: str,
        source: str,
        source_version: str = "",
        computation_chain: list[str] | None = None,
        quality_score: float | None = None,
    ) -> bool:
        """Convenience bridge for FeatureStore integration.

        Records a feature vector's lineage in the standalone engine
        so FeatureStore and DataLineageEngine stay in sync.

        Args:
            vector_id: Feature vector ID from FeatureStore.
            feature_name: Feature name.
            source: Data source.
            source_version: Source version.
            computation_chain: Computation steps.
            quality_score: Quality score.

        Returns:
            True if recorded.
        """
        return self.record_computation_chain(
            artifact_id=vector_id,
            artifact_type="feature_vector",
            feature_name=feature_name,
            source=source,
            computation_chain=computation_chain or ["raw"],
            source_version=source_version,
            quality_score=quality_score,
        )


# ── Singleton ─────────────────────────────────────────────────────────────────


_lineage_engine: DataLineageEngine | None = None
_engine_lock = threading.RLock()


def get_lineage_engine(db_path: str | None = None) -> DataLineageEngine:
    """Get singleton DataLineageEngine instance.

    Args:
        db_path: Optional custom DB path for testing.

    Returns:
        Shared DataLineageEngine instance.
    """
    global _lineage_engine
    with _engine_lock:
        if _lineage_engine is None:
            _lineage_engine = DataLineageEngine(db_path=db_path)
        return _lineage_engine
