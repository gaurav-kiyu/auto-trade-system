"""
Tests for Phase 5 — ML Signal Classifier (core/ml_classifier.py).

Covers:
  - extract_features: correct values, all FEATURE_COLS present, types are float
  - load_training_data: returns None on missing DB; correct structure on valid DB
  - train: returns None below min_trades; returns fitted model above threshold
  - save_model / load_model: round-trip through disk
  - predict_win_prob: output in [0,1], returns 0.5 on failure
  - score_adj_from_prob: correct sign and cap for high/low/neutral prob
  - get_classifier: returns None when disabled; returns None below min_trades
"""
from __future__ import annotations

import json
import pickle
import sqlite3
import time
from pathlib import Path

import pytest

from core.ml_classifier import (
    FEATURE_COLS,
    extract_features,
    load_training_data,
    predict_win_prob,
    save_model,
    load_model,
    score_adj_from_prob,
    get_classifier,
    train,
    _model_cache,
    _model_ts,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_journal(path: Path, n_trades: int, win_frac: float = 0.55) -> None:
    """Create a minimal journal.db with n_trades rows."""
    con = sqlite3.connect(str(path))
    con.execute("""
        CREATE TABLE IF NOT EXISTS journal (
            score INTEGER, confidence REAL, direction TEXT, tier TEXT,
            soft_blocks TEXT, entry_ts TEXT, is_winner INTEGER,
            actual_entry REAL, net_pnl REAL
        )
    """)
    import datetime as _dt
    base = _dt.datetime(2026, 1, 2, 10, 0, 0)
    for i in range(n_trades):
        is_w = 1 if i < round(n_trades * win_frac) else 0
        con.execute(
            "INSERT INTO journal VALUES (?,?,?,?,?,?,?,?,?)",
            (
                70 + (i % 15),           # score 70-84
                0.6 + (i % 3) * 0.05,   # confidence
                "CALL" if i % 2 == 0 else "PUT",
                "STRONG" if i % 3 == 0 else "MODERATE",
                "[]",
                (base + _dt.timedelta(days=i)).isoformat(),
                is_w,
                100.0 + i,              # actual_entry > 0
                50.0 if is_w else -30.0,
            ),
        )
    con.commit()
    con.close()


def _dummy_signal(score: int = 75, direction: str = "CALL", tier: str = "STRONG") -> dict:
    return {
        "score":      score,
        "confidence": 0.65,
        "direction":  direction,
        "strength":   tier,
        "soft_blocks": [],
        "signal_ts":  time.time(),
    }


# ── extract_features ──────────────────────────────────────────────────────────

class TestExtractFeatures:
    def test_returns_all_feature_cols(self):
        f = extract_features(_dummy_signal())
        assert set(f.keys()) == set(FEATURE_COLS)

    def test_all_values_are_float(self):
        f = extract_features(_dummy_signal())
        for k, v in f.items():
            assert isinstance(v, float), f"{k} is not float"

    def test_call_direction(self):
        f = extract_features(_dummy_signal(direction="CALL"))
        assert f["direction_call"] == 1.0

    def test_put_direction(self):
        f = extract_features(_dummy_signal(direction="PUT"))
        assert f["direction_call"] == 0.0

    def test_strong_tier(self):
        f = extract_features(_dummy_signal(tier="STRONG"))
        assert f["is_strong"] == 1.0
        assert f["is_moderate"] == 0.0
        assert f["is_weak"] == 0.0

    def test_moderate_tier(self):
        f = extract_features(_dummy_signal(tier="MODERATE"))
        assert f["is_moderate"] == 1.0
        assert f["is_strong"] == 0.0

    def test_score_passed_through(self):
        f = extract_features(_dummy_signal(score=82))
        assert f["score"] == 82.0

    def test_has_soft_blocks_list(self):
        sig = _dummy_signal()
        sig["soft_blocks"] = ["choppy_regime"]
        f = extract_features(sig)
        assert f["has_soft_blocks"] == 1.0

    def test_has_soft_blocks_json_string(self):
        sig = _dummy_signal()
        sig["soft_blocks"] = '["choppy_regime"]'
        f = extract_features(sig)
        assert f["has_soft_blocks"] == 1.0

    def test_no_soft_blocks(self):
        f = extract_features(_dummy_signal())
        assert f["has_soft_blocks"] == 0.0

    def test_hour_within_range(self):
        f = extract_features(_dummy_signal())
        assert 0 <= f["hour_of_entry"] <= 23

    def test_day_of_week_within_range(self):
        f = extract_features(_dummy_signal())
        assert 0 <= f["day_of_week"] <= 6


# ── load_training_data ─────────────────────────────────────────────────────────

class TestLoadTrainingData:
    def test_returns_none_when_db_missing(self, tmp_path):
        result = load_training_data(tmp_path / "nonexistent.db")
        assert result is None

    def test_returns_none_when_no_complete_trades(self, tmp_path):
        db = tmp_path / "journal.db"
        con = sqlite3.connect(str(db))
        con.execute("""
            CREATE TABLE journal (
                score INTEGER, confidence REAL, direction TEXT, tier TEXT,
                soft_blocks TEXT, entry_ts TEXT, is_winner INTEGER,
                actual_entry REAL, net_pnl REAL
            )
        """)
        con.commit()
        con.close()
        assert load_training_data(db) is None

    def test_returns_data_with_trades(self, tmp_path):
        db = tmp_path / "journal.db"
        _make_journal(db, 10)
        result = load_training_data(db)
        assert result is not None
        X, y = result
        assert len(X) == 10
        assert len(y) == 10

    def test_feature_vector_length(self, tmp_path):
        db = tmp_path / "journal.db"
        _make_journal(db, 5)
        X, y = load_training_data(db)
        assert len(X[0]) == len(FEATURE_COLS)

    def test_labels_are_binary(self, tmp_path):
        db = tmp_path / "journal.db"
        _make_journal(db, 10)
        _, y = load_training_data(db)
        assert all(v in (0, 1) for v in y)


# ── train ─────────────────────────────────────────────────────────────────────

class TestTrain:
    def test_returns_none_when_db_missing(self, tmp_path):
        model = train(tmp_path / "no.db", {"ml_min_trades_to_train": 10})
        assert model is None

    def test_returns_none_below_min_trades(self, tmp_path):
        db = tmp_path / "journal.db"
        _make_journal(db, 5)
        model = train(db, {"ml_min_trades_to_train": 50})
        assert model is None

    def test_returns_model_above_min_trades(self, tmp_path):
        db = tmp_path / "journal.db"
        _make_journal(db, 60)
        model = train(db, {"ml_min_trades_to_train": 50})
        assert model is not None

    def test_model_has_predict_proba(self, tmp_path):
        db = tmp_path / "journal.db"
        _make_journal(db, 60)
        model = train(db, {"ml_min_trades_to_train": 50})
        assert hasattr(model, "predict_proba")


# ── save_model / load_model ───────────────────────────────────────────────────

class TestSaveLoadModel:
    def test_roundtrip(self, tmp_path):
        db = tmp_path / "journal.db"
        _make_journal(db, 60)
        model = train(db, {"ml_min_trades_to_train": 50})
        assert model is not None
        model_path = tmp_path / "models" / "clf.pkl"
        assert save_model(model, model_path) is True
        loaded = load_model(model_path)
        assert loaded is not None
        assert hasattr(loaded, "predict_proba")

    def test_load_missing_returns_none(self, tmp_path):
        assert load_model(tmp_path / "nonexistent.pkl") is None

    def test_save_creates_parent_dirs(self, tmp_path):
        db = tmp_path / "journal.db"
        _make_journal(db, 60)
        model = train(db, {"ml_min_trades_to_train": 50})
        nested = tmp_path / "a" / "b" / "c" / "model.pkl"
        save_model(model, nested)
        assert nested.is_file()


# ── predict_win_prob ───────────────────────────────────────────────────────────

class TestPredictWinProb:
    def _trained_model(self, tmp_path):
        db = tmp_path / "journal.db"
        _make_journal(db, 60)
        return train(db, {"ml_min_trades_to_train": 50})

    def test_output_in_0_1(self, tmp_path):
        model = self._trained_model(tmp_path)
        features = extract_features(_dummy_signal())
        prob = predict_win_prob(model, features)
        assert 0.0 <= prob <= 1.0

    def test_returns_05_on_bad_model(self):
        prob = predict_win_prob(object(), {"score": 75.0, **{c: 0.0 for c in FEATURE_COLS if c != "score"}})
        assert prob == 0.5

    def test_consistent_for_same_input(self, tmp_path):
        model = self._trained_model(tmp_path)
        features = extract_features(_dummy_signal())
        p1 = predict_win_prob(model, features)
        p2 = predict_win_prob(model, features)
        assert p1 == p2


# ── score_adj_from_prob ────────────────────────────────────────────────────────

class TestScoreAdjFromProb:
    def _cfg(self, **kw):
        return {"ml_score_adj_cap": 10, "ml_high_prob_threshold": 0.65,
                "ml_low_prob_threshold": 0.40, **kw}

    def test_high_prob_positive_adj(self):
        adj, tag = score_adj_from_prob(0.80, self._cfg())
        assert adj > 0
        assert "+" in tag

    def test_low_prob_negative_adj(self):
        adj, tag = score_adj_from_prob(0.20, self._cfg())
        assert adj < 0
        assert "→" in tag

    def test_neutral_prob_zero_adj(self):
        adj, tag = score_adj_from_prob(0.52, self._cfg())
        assert adj == 0
        assert "neutral" in tag

    def test_cap_respected_at_extreme_prob(self):
        adj, _ = score_adj_from_prob(1.0, self._cfg(ml_score_adj_cap=10))
        assert abs(adj) <= 10

    def test_adj_at_least_1_when_outside_neutral(self):
        adj_high, _ = score_adj_from_prob(0.66, self._cfg())
        adj_low, _  = score_adj_from_prob(0.39, self._cfg())
        assert adj_high >= 1
        assert adj_low <= -1

    def test_no_cfg_uses_defaults(self):
        adj, _ = score_adj_from_prob(0.90)
        assert adj > 0


# ── get_classifier ─────────────────────────────────────────────────────────────

class TestGetClassifier:
    def setup_method(self):
        _model_cache.clear()
        _model_ts.clear()

    def test_returns_none_when_disabled(self, tmp_path):
        clf = get_classifier(tmp_path / "j.db", {"ml_classifier_enabled": False})
        assert clf is None

    def test_returns_none_below_min_trades(self, tmp_path):
        db = tmp_path / "journal.db"
        _make_journal(db, 5)
        clf = get_classifier(db, {"ml_classifier_enabled": True, "ml_min_trades_to_train": 50,
                                   "ml_model_path": str(tmp_path / "m.pkl")})
        assert clf is None

    def test_returns_model_above_min_trades(self, tmp_path):
        db = tmp_path / "journal.db"
        _make_journal(db, 60)
        clf = get_classifier(db, {"ml_classifier_enabled": True, "ml_min_trades_to_train": 50,
                                   "ml_model_path": str(tmp_path / "m.pkl")})
        assert clf is not None

    def test_cached_model_reused(self, tmp_path):
        db = tmp_path / "journal.db"
        _make_journal(db, 60)
        cfg = {"ml_classifier_enabled": True, "ml_min_trades_to_train": 50,
               "ml_model_path": str(tmp_path / "m.pkl"), "ml_retrain_interval_hours": 24.0}
        clf1 = get_classifier(db, cfg)
        clf2 = get_classifier(db, cfg)
        assert clf1 is clf2  # same object from cache

    def test_persisted_model_loaded_from_disk(self, tmp_path):
        db = tmp_path / "journal.db"
        _make_journal(db, 60)
        model_path = str(tmp_path / "m.pkl")
        cfg = {"ml_classifier_enabled": True, "ml_min_trades_to_train": 50,
               "ml_model_path": model_path, "ml_retrain_interval_hours": 24.0}
        get_classifier(db, cfg)
        _model_cache.clear()  # evict cache
        _model_ts.clear()
        clf2 = get_classifier(db, cfg)
        assert clf2 is not None  # loaded from disk
