"""
Tests for core/concept_drift_detector.py (Phase C).

Covers:
  - compute_psi() known values, edge cases
  - compute_ks() known values, edge cases
  - detect_drift() status classification
  - detect_drift() with real sqlite data
  - detect_all_features() runs without error
  - format_drift_report() string contract
  - Missing DB file handling
  - Constant-feature edge case
"""
import json
import math
import sqlite3
import time

import pytest

from core.concept_drift_detector import (
    compute_psi,
    compute_ks,
    detect_drift,
    detect_all_features,
    format_drift_report,
    DriftResult,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_tracker_db(tmp_path, ref_vals, recent_vals, feature="score",
                     ref_offset_days=60, recent_offset_days=5):
    """
    Create an ml_tracker.db with SHAP values split into reference and recent windows.
    """
    db = str(tmp_path / "ml_tracker.db")
    conn = sqlite3.connect(db)
    conn.execute("""
        CREATE TABLE ml_predictions (
            id INTEGER PRIMARY KEY,
            ts REAL,
            trade_id TEXT,
            predicted_prob REAL,
            actual_outcome INTEGER,
            shap_json TEXT DEFAULT '{}'
        )
    """)
    now = time.time()

    # Reference window: ~ ref_offset_days ago
    for i, v in enumerate(ref_vals):
        ts = now - ref_offset_days * 86400 + i * 60
        shap = json.dumps({feature: float(v)})
        conn.execute(
            "INSERT INTO ml_predictions (ts, trade_id, predicted_prob, shap_json) VALUES (?,?,?,?)",
            (ts, f"ref_{i}", 0.5, shap),
        )

    # Recent window: ~ recent_offset_days ago
    for i, v in enumerate(recent_vals):
        ts = now - recent_offset_days * 86400 + i * 60
        shap = json.dumps({feature: float(v)})
        conn.execute(
            "INSERT INTO ml_predictions (ts, trade_id, predicted_prob, shap_json) VALUES (?,?,?,?)",
            (ts, f"rec_{i}", 0.5, shap),
        )

    conn.commit()
    conn.close()
    return db


# ── compute_psi ───────────────────────────────────────────────────────────────

class TestComputePsi:
    def test_identical_distributions_near_zero(self):
        vals = [float(i) for i in range(100)]
        psi = compute_psi(vals, vals)
        assert psi < 0.01

    def test_empty_reference_returns_zero(self):
        assert compute_psi([], [1.0, 2.0]) == 0.0

    def test_empty_recent_returns_zero(self):
        assert compute_psi([1.0, 2.0], []) == 0.0

    def test_completely_different_distributions_high_psi(self):
        ref    = [0.0] * 100
        recent = [1.0] * 100
        psi = compute_psi(ref, recent, n_bins=10)
        assert psi > 0.1

    def test_psi_non_negative(self):
        import random
        rng = random.Random(42)
        ref    = [rng.gauss(0, 1) for _ in range(200)]
        recent = [rng.gauss(0.5, 1) for _ in range(200)]
        psi = compute_psi(ref, recent)
        assert psi >= 0.0

    def test_constant_feature_returns_float(self):
        ref    = [5.0] * 50
        recent = [5.0] * 50
        psi = compute_psi(ref, recent)
        assert isinstance(psi, float)
        assert psi < 0.1

    def test_constant_ref_shifted_recent(self):
        ref    = [5.0] * 50
        recent = [6.0] * 50    # entirely outside reference range
        psi = compute_psi(ref, recent)
        assert psi >= 0.0      # must not raise

    def test_large_shift_exceeds_alert_threshold(self):
        ref    = list(range(100))
        recent = [x + 200 for x in range(100)]
        psi = compute_psi(ref, recent, n_bins=10)
        assert psi > 0.25


# ── compute_ks ────────────────────────────────────────────────────────────────

class TestComputeKs:
    def test_identical_distributions_zero(self):
        vals = [float(i) for i in range(50)]
        ks = compute_ks(vals, vals)
        assert ks < 1e-6

    def test_empty_reference_returns_zero(self):
        assert compute_ks([], [1.0, 2.0]) == 0.0

    def test_empty_recent_returns_zero(self):
        assert compute_ks([1.0, 2.0], []) == 0.0

    def test_disjoint_distributions_near_one(self):
        ref    = [0.0] * 50
        recent = [1.0] * 50
        ks = compute_ks(ref, recent)
        assert ks > 0.8

    def test_ks_in_range(self):
        import random
        rng = random.Random(7)
        ref    = [rng.gauss(0, 1) for _ in range(200)]
        recent = [rng.gauss(1, 1) for _ in range(200)]
        ks = compute_ks(ref, recent)
        assert 0.0 <= ks <= 1.0

    def test_single_element_each(self):
        ks = compute_ks([0.0], [1.0])
        assert isinstance(ks, float)

    def test_symmetry(self):
        ref    = [1.0, 2.0, 3.0]
        recent = [4.0, 5.0, 6.0]
        assert abs(compute_ks(ref, recent) - compute_ks(recent, ref)) < 1e-9


# ── detect_drift ──────────────────────────────────────────────────────────────

class TestDetectDrift:
    def test_returns_drift_result(self, tmp_path):
        db = str(tmp_path / "no.db")
        result = detect_drift("score", db_path=db)
        assert isinstance(result, DriftResult)

    def test_missing_db_returns_ok(self, tmp_path):
        db = str(tmp_path / "no.db")
        result = detect_drift("score", db_path=db)
        assert result.status == "OK"

    def test_stable_feature_is_ok(self, tmp_path):
        ref    = list(range(50))
        recent = list(range(50))
        db = _make_tracker_db(tmp_path, ref, recent, feature="score")
        result = detect_drift("score", db_path=db,
                              ref_days=90, recent_days=7)
        assert result.status in ("OK", "WARN")
        assert result.psi >= 0.0

    def test_heavily_drifted_feature_warns_or_alerts(self, tmp_path):
        ref    = list(range(100))
        recent = [x + 500 for x in range(100)]
        db = _make_tracker_db(tmp_path, ref, recent, feature="score")
        result = detect_drift("score", db_path=db,
                              ref_days=90, recent_days=7,
                              psi_warn=0.10, psi_alert=0.25)
        assert result.status in ("WARN", "ALERT")

    def test_result_has_feature_name(self, tmp_path):
        db = str(tmp_path / "no.db")
        result = detect_drift("confidence", db_path=db)
        assert result.feature == "confidence"

    def test_ref_n_and_recent_n(self, tmp_path):
        ref    = [float(i) for i in range(20)]
        recent = [float(i) for i in range(10)]
        db = _make_tracker_db(tmp_path, ref, recent)
        result = detect_drift("score", db_path=db, ref_days=90, recent_days=7)
        assert result.ref_n == 20
        assert result.recent_n == 10

    def test_alert_threshold_respected(self, tmp_path):
        ref    = [0.0] * 100
        recent = [10.0] * 100
        db = _make_tracker_db(tmp_path, ref, recent)
        result = detect_drift("score", db_path=db,
                              ref_days=90, recent_days=7,
                              psi_alert=0.01)   # very low threshold
        assert result.status == "ALERT"

    def test_message_is_non_empty_string(self, tmp_path):
        db = str(tmp_path / "no.db")
        result = detect_drift("score", db_path=db)
        assert isinstance(result.message, str) and len(result.message) > 0


# ── detect_all_features ───────────────────────────────────────────────────────

class TestDetectAllFeatures:
    def test_returns_dict(self, tmp_path):
        db = str(tmp_path / "no.db")
        result = detect_all_features(["score", "confidence"], db_path=db)
        assert isinstance(result, dict)

    def test_all_features_present(self, tmp_path):
        db = str(tmp_path / "no.db")
        feats = ["score", "confidence", "day_of_week"]
        result = detect_all_features(feats, db_path=db)
        assert set(result.keys()) == set(feats)

    def test_all_results_are_drift_results(self, tmp_path):
        db = str(tmp_path / "no.db")
        result = detect_all_features(["score"], db_path=db)
        for v in result.values():
            assert isinstance(v, DriftResult)

    def test_uses_feature_cols_when_none(self, tmp_path):
        from core.ml_classifier import FEATURE_COLS
        db = str(tmp_path / "no.db")
        result = detect_all_features(db_path=db)
        assert set(result.keys()) == set(FEATURE_COLS)


# ── format_drift_report ───────────────────────────────────────────────────────

class TestFormatDriftReport:
    def test_empty_results_returns_string(self):
        s = format_drift_report({})
        assert isinstance(s, str)

    def test_contains_feature_name(self):
        result = {"score": DriftResult("score", 0.05, 0.1, 50, 20, "OK", "stable")}
        s = format_drift_report(result)
        assert "score" in s

    def test_alert_features_appear_first(self):
        results = {
            "feat_ok":    DriftResult("feat_ok",    0.01, 0.05, 10, 10, "OK",    "ok"),
            "feat_alert": DriftResult("feat_alert", 0.30, 0.25, 10, 10, "ALERT", "alert"),
            "feat_warn":  DriftResult("feat_warn",  0.15, 0.18, 10, 10, "WARN",  "warn"),
        }
        s = format_drift_report(results)
        pos_alert = s.index("feat_alert")
        pos_warn  = s.index("feat_warn")
        pos_ok    = s.index("feat_ok")
        assert pos_alert < pos_warn < pos_ok

    def test_counts_in_header(self):
        results = {
            "x": DriftResult("x", 0.30, 0.0, 10, 10, "ALERT", "alert"),
            "y": DriftResult("y", 0.12, 0.0, 10, 10, "WARN",  "warn"),
            "z": DriftResult("z", 0.02, 0.0, 10, 10, "OK",    "ok"),
        }
        s = format_drift_report(results)
        assert "ALERT:1" in s
        assert "WARN:1"  in s
        assert "OK:1"    in s
