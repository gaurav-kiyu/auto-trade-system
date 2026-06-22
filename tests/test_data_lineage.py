"""
Tests for core/data_lineage.py — Data Lineage Engine.

Covers:
- Record creation (single + computation chain)
- Lineage query (by artifact_id, feature_name, source, time range)
- Provenance chain retrieval
- Impact analysis
- Source health
- Integration bridge
- Singleton pattern
- Edge cases
"""
from __future__ import annotations

import os
import tempfile
import threading

import pytest

from core.data_lineage import (
    DataLineageEngine,
    DataLineageRecord,
    ImpactAnalysis,
    ProvenanceChain,
    get_lineage_engine,
)


@pytest.fixture
def db_path() -> str:
    """Create a temporary DB for test isolation."""
    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    f.close()
    yield f.name
    try:
        os.unlink(f.name)
    except PermissionError:
        pass


@pytest.fixture
def engine(db_path: str) -> DataLineageEngine:
    """Create a fresh engine instance for each test.

    Resets the singleton to None so each test starts isolated.
    Tests use the local ``eng`` variable, not ``get_lineage_engine()``.
    """
    eng = DataLineageEngine(db_path=db_path)
    # Reset singleton so cross-test isolation is maintained
    import core.data_lineage as _dl
    with _dl._engine_lock:
        _dl._lineage_engine = None
    yield eng


# ═══════════════════════════════════════════════════════════════════════════════
# Record Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestRecordLineage:
    def test_record_single(self, engine: DataLineageEngine) -> None:
        record = DataLineageRecord(
            artifact_id="FV-TEST-001",
            artifact_type="feature_vector",
            feature_name="rsi_14",
            source="yfinance",
            source_version="v2.53.0",
            computation_step="raw",
            quality_score=0.95,
            computed_at="2026-06-22T10:00:00",
        )
        assert engine.record_lineage(record) is True

        records = engine.query_lineage(artifact_id="FV-TEST-001")
        assert len(records) == 1
        assert records[0]["source"] == "yfinance"
        assert records[0]["feature_name"] == "rsi_14"
        assert records[0]["quality_score"] == 0.95

    def test_record_computation_chain(self, engine: DataLineageEngine) -> None:
        assert engine.record_computation_chain(
            artifact_id="FV-TEST-002",
            artifact_type="feature_vector",
            feature_name="momentum_5",
            source="nse_api",
            computation_chain=["raw_price", "returns", "rolling_mean_5"],
            source_version="v2.53.0",
            quality_score=0.88,
        )

        records = engine.query_lineage(artifact_id="FV-TEST-002")
        assert len(records) == 3
        steps = [r["computation_step"] for r in records]
        assert "raw_price" in steps
        assert "returns" in steps
        assert "rolling_mean_5" in steps

    def test_record_with_empty_chain_falls_back_to_raw(
        self, engine: DataLineageEngine
    ) -> None:
        assert engine.record_computation_chain(
            artifact_id="FV-TEST-003",
            artifact_type="feature_vector",
            feature_name="volume",
            source="websocket",
            computation_chain=[],
        )

        records = engine.query_lineage(artifact_id="FV-TEST-003")
        assert len(records) == 1
        assert records[0]["computation_step"] == "raw"

    def test_record_with_metadata(self, engine: DataLineageEngine) -> None:
        record = DataLineageRecord(
            artifact_id="FV-TEST-004",
            artifact_type="prediction",
            feature_name="win_prob",
            source="lightgbm_model",
            metadata={"model_version": "v3", "training_date": "2026-06-01"},
        )
        assert engine.record_lineage(record)
        records = engine.query_lineage(artifact_id="FV-TEST-004")
        assert records[0]["metadata"]["model_version"] == "v3"


# ═══════════════════════════════════════════════════════════════════════════════
# Query Tests
# ═══════════════════════════════════════════════════════════════════════════════

# Seed helper: callers pass the engine to populate test data
def _seed_queries(engine: DataLineageEngine) -> None:
    """Seed test data for query tests.

    Creates:
      ART-A: rsi_14 (2 steps) + macd (4 steps) — both from yfinance
      ART-B: oi_change (1 step) — from nse_api
      ART-C: win_prob (2 steps) — from lightgbm, type=prediction
    """
    engine.record_computation_chain(
        artifact_id="ART-A", artifact_type="feature_vector",
        feature_name="rsi_14", source="yfinance",
        computation_chain=["raw", "sma_14"],
    )
    engine.record_computation_chain(
        artifact_id="ART-A", artifact_type="feature_vector",
        feature_name="macd", source="yfinance",
        computation_chain=["raw", "ema_12", "ema_26", "macd_line"],
    )
    engine.record_computation_chain(
        artifact_id="ART-B", artifact_type="feature_vector",
        feature_name="oi_change", source="nse_api",
        computation_chain=["raw"],
    )
    engine.record_computation_chain(
        artifact_id="ART-C", artifact_type="prediction",
        feature_name="win_prob", source="lightgbm",
        computation_chain=["feature_vector", "predict"],
    )


class TestQueryLineage:
    def test_query_by_artifact_id(self, engine: DataLineageEngine) -> None:
        _seed_queries(engine)
        # ART-A has rsi_14 (2 steps) + macd (4 steps) = 6 records
        records = engine.query_lineage(artifact_id="ART-A")
        assert len(records) == 6

    def test_query_by_feature_name(self, engine: DataLineageEngine) -> None:
        _seed_queries(engine)
        records = engine.query_lineage(feature_name="rsi_14")
        # rsi_14 has 2 computation steps
        assert len(records) == 2
        assert records[0]["source"] == "yfinance"

    def test_query_by_source(self, engine: DataLineageEngine) -> None:
        _seed_queries(engine)
        records = engine.query_lineage(source="nse_api")
        # nse_api only appears in ART-B (oi_change, 1 step)
        assert len(records) == 1

    def test_query_by_artifact_type(self, engine: DataLineageEngine) -> None:
        _seed_queries(engine)
        records = engine.query_lineage(artifact_type="prediction")
        # prediction has 2 computation steps
        assert len(records) == 2

    def test_query_returns_empty_list_for_no_match(
        self, engine: DataLineageEngine
    ) -> None:
        records = engine.query_lineage(artifact_id="NONEXISTENT")
        assert records == []

    def test_query_respects_limit(self, engine: DataLineageEngine) -> None:
        for i in range(10):
            engine.record_computation_chain(
                artifact_id=f"ART-{i}",
                artifact_type="feature_vector",
                feature_name="test",
                source="test",
                computation_chain=["raw"],
            )
        records = engine.query_lineage(limit=3)
        assert len(records) <= 3


# ═══════════════════════════════════════════════════════════════════════════════
# Provenance Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestProvenance:
    def test_get_provenance(self, engine: DataLineageEngine) -> None:
        engine.record_computation_chain(
            artifact_id="PV-TEST",
            artifact_type="feature_vector",
            feature_name="sma_cross",
            source="yfinance",
            computation_chain=["raw_price", "sma_20", "sma_50", "cross_signal"],
            quality_score=0.92,
        )
        chain = engine.get_provenance("PV-TEST")
        assert chain is not None
        assert isinstance(chain, ProvenanceChain)
        assert chain.artifact_id == "PV-TEST"
        assert "yfinance" in chain.sources
        assert len(chain.computation_chain) >= 4
        assert chain.quality == 0.92
        assert "Data from" in chain.summary

    def test_get_provenance_returns_none_for_missing(
        self, engine: DataLineageEngine
    ) -> None:
        assert engine.get_provenance("DOES_NOT_EXIST") is None

    def test_get_provenance_summary(self, engine: DataLineageEngine) -> None:
        engine.record_computation_chain(
            artifact_id="PV-SUMMARY",
            artifact_type="feature_vector",
            feature_name="test_feat",
            source="websocket",
            computation_chain=["raw", "normalize"],
            quality_score=0.85,
        )
        summary = engine.get_provenance_summary("PV-SUMMARY")
        assert summary["artifact_id"] == "PV-SUMMARY"
        assert summary["sources"] == ["websocket"]
        assert summary["quality"] == 0.85
        assert "computation_chain" in summary
        assert "provenance" in summary

    def test_get_provenance_summary_no_data(
        self, engine: DataLineageEngine
    ) -> None:
        summary = engine.get_provenance_summary("MISSING")
        assert summary["provenance"] == "No lineage data available"


# ═══════════════════════════════════════════════════════════════════════════════
# Impact Analysis Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestImpactAnalysis:
    def test_analyze_impact(self, engine: DataLineageEngine) -> None:
        for i in range(3):
            engine.record_computation_chain(
                artifact_id=f"IMP-{i}",
                artifact_type="feature_vector",
                feature_name=f"feature_{i}",
                source="shared_broker",
                computation_chain=["raw"],
            )
        impact = engine.analyze_impact("shared_broker")
        assert isinstance(impact, ImpactAnalysis)
        assert impact.source == "shared_broker"
        assert impact.artifact_count == 3
        assert impact.feature_count == 3

    def test_analyze_impact_no_data(self, engine: DataLineageEngine) -> None:
        impact = engine.analyze_impact("nonexistent_source")
        assert impact.artifact_count == 0
        assert impact.downstream_artifacts == []

    def test_impact_includes_last_used(self, engine: DataLineageEngine) -> None:
        engine.record_computation_chain(
            artifact_id="IMP-LAST",
            artifact_type="feature_vector",
            feature_name="last_feat",
            source="my_source",
            computation_chain=["raw"],
        )
        impact = engine.analyze_impact("my_source")
        assert impact.last_used is not None


# ═══════════════════════════════════════════════════════════════════════════════
# Source Health Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestSourceHealth:
    def test_get_source_health(self, engine: DataLineageEngine) -> None:
        engine.record_computation_chain(
            artifact_id="HLTH-1", artifact_type="feature_vector",
            feature_name="feat_a", source="src_a",
            computation_chain=["raw"], quality_score=0.9,
        )
        engine.record_computation_chain(
            artifact_id="HLTH-2", artifact_type="feature_vector",
            feature_name="feat_b", source="src_a",
            computation_chain=["raw"], quality_score=0.8,
        )
        engine.record_computation_chain(
            artifact_id="HLTH-3", artifact_type="feature_vector",
            feature_name="feat_c", source="src_b",
            computation_chain=["raw"], quality_score=0.95,
        )
        health = engine.get_source_health()
        assert len(health) == 2

        src_a = [h for h in health if h["source"] == "src_a"][0]
        assert src_a["artifact_count"] == 2
        assert src_a["avg_quality"] == pytest.approx(0.85, rel=0.01)

    def test_get_source_health_empty(self, engine: DataLineageEngine) -> None:
        health = engine.get_source_health()
        assert health == []


# ═══════════════════════════════════════════════════════════════════════════════
# Integration Bridge Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestIntegrationBridge:
    def test_record_from_feature_store(self, engine: DataLineageEngine) -> None:
        assert engine.record_from_feature_store(
            vector_id="FS-BRIDGE-001",
            feature_name="macd_signal",
            source="yfinance",
            source_version="v2.53.0",
            computation_chain=["raw_price", "ema_12", "ema_26", "macd"],
            quality_score=0.93,
        )

        records = engine.query_lineage(artifact_id="FS-BRIDGE-001")
        assert len(records) == 4
        assert records[0]["artifact_type"] == "feature_vector"

    def test_record_from_feature_store_defaults(
        self, engine: DataLineageEngine
    ) -> None:
        assert engine.record_from_feature_store(
            vector_id="FS-BRIDGE-002",
            feature_name="rsi",
            source="nse_api",
        )

        records = engine.query_lineage(artifact_id="FS-BRIDGE-002")
        assert len(records) == 1
        assert records[0]["computation_step"] == "raw"


# ═══════════════════════════════════════════════════════════════════════════════
# Singleton Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestSingleton:
    def test_get_lineage_engine_returns_same_instance(self) -> None:
        import core.data_lineage as _dl
        with _dl._engine_lock:
            _dl._lineage_engine = None

        e1 = get_lineage_engine()
        e2 = get_lineage_engine()
        assert e1 is e2

    def test_get_lineage_engine_custom_db_returns_same_singleton(
        self, db_path: str
    ) -> None:
        """Singleton returns same instance even when a different db_path is passed."""
        import core.data_lineage as _dl
        with _dl._engine_lock:
            _dl._lineage_engine = None

        e1 = get_lineage_engine()
        e2 = get_lineage_engine(db_path=db_path)
        assert e1 is e2  # Singleton contract: same instance


# ═══════════════════════════════════════════════════════════════════════════════
# Edge Case Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestEdgeCases:
    def test_empty_artifact_id(self, engine: DataLineageEngine) -> None:
        assert engine.query_lineage(artifact_id="") == []

    def test_recent_lineage_empty(self, engine: DataLineageEngine) -> None:
        assert engine.get_recent_lineage(minutes=60) == []

    def test_source_health_no_data(self, engine: DataLineageEngine) -> None:
        assert engine.get_source_health() == []

    def test_many_features_same_artifact(self, engine: DataLineageEngine) -> None:
        for feat in [f"feat_{i}" for i in range(50)]:
            engine.record_computation_chain(
                artifact_id="MANY-FEAT",
                artifact_type="feature_vector",
                feature_name=feat,
                source="bulk_source",
                computation_chain=["raw"],
            )
        records = engine.query_lineage(artifact_id="MANY-FEAT")
        assert len(records) == 50

    def test_thread_safety(self, engine: DataLineageEngine) -> None:
        """Verify concurrent writes don't corrupt state."""
        errors: list[Exception] = []

        def writer(thread_id: int) -> None:
            try:
                for i in range(20):
                    engine.record_computation_chain(
                        artifact_id=f"THREAD-{thread_id}-{i}",
                        artifact_type="feature_vector",
                        feature_name="test",
                        source="thread_test",
                        computation_chain=["raw"],
                    )
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(tid,)) for tid in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Thread safety errors: {errors}"
        records = engine.query_lineage(source="thread_test")
        assert len(records) == 100  # 5 threads × 20 writes
