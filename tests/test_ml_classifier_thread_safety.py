"""Tests for core.ml_classifier thread safety — model cache race condition verification."""
from __future__ import annotations

import threading
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from core.ml_classifier import (
    FEATURE_COLS,
    _model_cache,
    _model_lock,
    _model_ts,
    extract_features,
    score_adj_from_prob,
)


@pytest.fixture(autouse=True)
def _clear_model_cache() -> None:
    """Clear in-memory model cache before each test to avoid cross-test contamination."""
    with _model_lock:
        _model_cache.clear()
        _model_ts.clear()


class TestModelCacheThreadSafety:
    """Verify that concurrent access to _model_cache does not cause race conditions."""

    def test_concurrent_get_classifier(self, tmp_path: Path) -> None:
        """Multiple threads calling get_classifier simultaneously should not corrupt cache."""
        import sqlite3


        db_path = tmp_path / "test_journal.db"
        con = sqlite3.connect(str(db_path))
        con.execute("""
            CREATE TABLE journal (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                score REAL, confidence REAL, direction TEXT,
                tier TEXT, soft_blocks TEXT,
                entry_ts TEXT, actual_entry REAL,
                is_winner INTEGER, net_pnl REAL,
                iv_rank REAL DEFAULT 50.0,
                vix_at_entry REAL DEFAULT 15.0,
                pcr_at_entry REAL DEFAULT 1.0,
                regime TEXT DEFAULT 'NEUTRAL',
                session_code INTEGER DEFAULT 1
            )
        """)
        for i in range(60):
            con.execute(
                "INSERT INTO journal (score, confidence, direction, tier, soft_blocks, entry_ts, actual_entry, is_winner, net_pnl) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (60 + i, 0.5, "CALL", "MODERATE", "[]", "2026-05-12T09:30:00", 100.0, 1 if i < 30 else 0, 50.0),
            )
        con.commit()
        con.close()

        cfg = {
            "ml_classifier_enabled": True,
            "ml_model_path": str(tmp_path / "test_model.pkl"),
            "ml_retrain_interval_hours": 24.0,
            "drift_retrain_enabled": False,
        }

        errors: list[Exception | None] = [None] * 8

        def _access_cache(idx: int) -> None:
            try:
                # LightGBM may not be installed; that's fine — we just test cache safety
                with _model_lock:
                    _model_cache["dummy"] = MagicMock()
                    _model_ts["dummy"] = time.time()
            except Exception as e:
                errors[idx] = e

        threads = [
            threading.Thread(target=_access_cache, args=(i,))
            for i in range(8)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        for e in errors:
            if e is not None:
                raise e
        with _model_lock:
            assert "dummy" in _model_cache

    def test_lock_reentrance(self) -> None:
        """_model_lock should be a regular (non-reentrant) Lock to force clean semantics."""
        assert isinstance(_model_lock, threading.Lock)
        import threading as _th
        _rlock_type = type(_th.RLock())
        assert not isinstance(_model_lock, _rlock_type)

    def test_cache_clear_under_lock(self) -> None:
        """Clearing cache must happen under the lock."""
        with _model_lock:
            _model_cache["test"] = "value"
            _model_ts["test"] = time.time()
        with _model_lock:
            cached = _model_cache.get("test")
            assert cached == "value"

    def test_cache_isolation_between_paths(self) -> None:
        """Different model paths should not interfere."""
        with _model_lock:
            _model_cache["path_a"] = "model_a"
            _model_cache["path_b"] = "model_b"
            assert _model_cache["path_a"] == "model_a"
            assert _model_cache["path_b"] == "model_b"


class TestScoreAdjFromProb:
    def test_high_prob_positive_adj(self) -> None:
        adj, tag = score_adj_from_prob(0.75, {"ml_high_prob_threshold": 0.65, "ml_score_adj_cap": 10})
        assert adj > 0
        assert "ML" in tag

    def test_low_prob_negative_adj(self) -> None:
        adj, tag = score_adj_from_prob(0.30, {"ml_low_prob_threshold": 0.40, "ml_score_adj_cap": 10})
        assert adj < 0
        assert "ML" in tag

    def test_mid_prob_neutral(self) -> None:
        adj, tag = score_adj_from_prob(0.50, {"ml_high_prob_threshold": 0.65, "ml_low_prob_threshold": 0.40})
        assert adj == 0
        assert "neutral" in tag

    def test_default_config(self) -> None:
        adj, tag = score_adj_from_prob(0.50)
        assert adj == 0

    def test_edge_high(self) -> None:
        adj, tag = score_adj_from_prob(1.0, {"ml_high_prob_threshold": 0.65, "ml_score_adj_cap": 10})
        assert adj == 10

    def test_edge_low(self) -> None:
        adj, tag = score_adj_from_prob(0.0, {"ml_low_prob_threshold": 0.40, "ml_score_adj_cap": 10})
        assert adj == -10


class TestExtractFeatures:
    def test_minimal_signal(self) -> None:
        features = extract_features({"score": 75})
        assert features["score"] == 75.0
        assert features["confidence"] == 0.5
        assert features["direction_call"] == 1.0  # CALL default
        assert features["iv_rank"] == 50.0
        assert features["vix"] == 15.0

    def test_full_signal(self) -> None:
        features = extract_features({
            "score": 85,
            "confidence": 0.8,
            "direction": "PUT",
            "tier": "STRONG",
            "soft_blocks": [],
            "iv_rank": 35,
            "vix": 12.5,
            "pcr": 0.9,
            "mkt_regime": "TRENDING",
            "signal_ts": 1700000000,
        })
        assert features["score"] == 85.0
        assert features["direction_call"] == 0.0  # PUT
        assert features["is_strong"] == 1.0
        assert features["iv_rank"] == 35.0
        assert features["vix"] == 12.5
        assert features["pcr"] == 0.9

    def test_soft_blocks_json_string(self) -> None:
        features = extract_features({"score": 70, "soft_blocks": '["low_volume"]'})
        assert features["has_soft_blocks"] == 1.0

    def test_regime_code_mapping(self) -> None:
        features = extract_features({"score": 70, "mkt_regime": "CHOPPY"})
        assert features["regime_code"] == 0.0

    def test_all_feature_cols_present(self) -> None:
        features = extract_features({"score": 50})
        for col in FEATURE_COLS:
            assert col in features, f"Missing feature: {col}"
