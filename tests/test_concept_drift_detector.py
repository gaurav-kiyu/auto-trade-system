"""Tests for core.concept_drift_detector — PSI and KS drift statistics."""

from __future__ import annotations

import json
import math
import time
from pathlib import Path
from unittest.mock import patch


from core.concept_drift_detector import (
    DriftResult,
    compute_ks,
    compute_psi,
    detect_all_features,
    detect_drift,
    format_drift_report,
)


# ── PSI computation tests ────────────────────────────────────────────────────

class TestComputePsi:
    """Test the Population Stability Index calculation."""

    def test_identical_distributions(self):
        """PSI should be ~0 for identical distributions."""
        ref = [1.0, 2.0, 3.0, 4.0, 5.0] * 10
        recent = [1.0, 2.0, 3.0, 4.0, 5.0] * 10
        psi = compute_psi(ref, recent, n_bins=5)
        assert psi < 0.01  # Near zero

    def test_different_distributions(self):
        """PSI should be > 0 for different distributions."""
        ref = [1.0] * 80 + [10.0] * 20   # 80% low, 20% high
        recent = [1.0] * 20 + [10.0] * 80  # 20% low, 80% high
        psi = compute_psi(ref, recent, n_bins=5)
        assert psi > 0.01

    def test_shifted_distribution_high_psi(self):
        """Significantly shifted distributions should have high PSI."""
        ref = [1.0, 2.0] * 50
        recent = [50.0, 60.0] * 50
        psi = compute_psi(ref, recent, n_bins=10)
        assert psi > 0.5  # Major shift

    def test_empty_reference(self):
        """Empty reference should return 0.0."""
        assert compute_psi([], [1.0, 2.0, 3.0]) == 0.0

    def test_empty_recent(self):
        """Empty recent should return 0.0."""
        assert compute_psi([1.0, 2.0, 3.0], []) == 0.0

    def test_constant_reference(self):
        """Constant reference values should still work."""
        ref = [5.0] * 50
        recent = [5.0] * 30 + [6.0] * 20
        psi = compute_psi(ref, recent, n_bins=5)
        assert psi >= 0.0

    def test_single_value(self):
        """Single value samples should not crash."""
        psi = compute_psi([1.0], [2.0], n_bins=5)
        assert isinstance(psi, float)
        assert psi >= 0.0

    def test_epsilon_smoothing(self):
        """Should handle bins where recent has zero count."""
        ref = [1.0] * 50 + [100.0] * 50
        recent = [1.0] * 100  # All in one bin
        psi = compute_psi(ref, recent, n_bins=10)
        assert psi >= 0.0
        assert not math.isinf(psi)
        assert not math.isnan(psi)


# ── KS computation tests ─────────────────────────────────────────────────────

class TestComputeKs:
    """Test the Kolmogorov-Smirnov statistic."""

    def test_identical_distributions(self):
        """KS should be ~0 for identical distributions."""
        ref = [1.0, 2.0, 3.0, 4.0, 5.0]
        recent = [1.0, 2.0, 3.0, 4.0, 5.0]
        ks = compute_ks(ref, recent)
        assert ks < 0.01

    def test_very_different(self):
        """Very different distributions should have high KS."""
        ref = [1.0] * 50
        recent = [50.0] * 50
        ks = compute_ks(ref, recent)
        assert ks >= 0.8

    def test_partial_overlap(self):
        """Partially overlapping distributions should have moderate KS."""
        ref = [1.0, 2.0, 3.0] * 10
        recent = [3.0, 4.0, 5.0] * 10
        ks = compute_ks(ref, recent)
        assert 0.1 < ks < 0.8

    def test_empty_reference(self):
        """Empty reference should return 0.0."""
        assert compute_ks([], [1.0, 2.0]) == 0.0

    def test_empty_recent(self):
        """Empty recent should return 0.0."""
        assert compute_ks([1.0, 2.0], []) == 0.0

    def test_single_values(self):
        """Single values should not crash."""
        ks = compute_ks([1.0], [2.0])
        assert isinstance(ks, float)
        assert ks >= 0.0


# ── DriftResult tests ────────────────────────────────────────────────────────

class TestDriftResult:
    """Test the DriftResult dataclass."""

    def test_ok_status(self):
        r = DriftResult(feature="score", psi=0.01, ks=0.01, ref_n=100, recent_n=50, status="OK", message="stable")
        assert r.status == "OK"
        assert r.psi == 0.01

    def test_warn_status(self):
        r = DriftResult(feature="score", psi=0.15, ks=0.05, ref_n=100, recent_n=50, status="WARN", message="moderate")
        assert r.status == "WARN"

    def test_alert_status(self):
        r = DriftResult(feature="score", psi=0.35, ks=0.10, ref_n=100, recent_n=50, status="ALERT", message="significant")
        assert r.status == "ALERT"


# ── detect_drift tests ───────────────────────────────────────────────────────

class TestDetectDrift:
    """Test the detection function."""

    def test_no_data_returns_ok(self, tmp_path: Path):
        """Missing DB should return OK with insufficient data message."""
        db_path = tmp_path / "nonexistent.db"
        result = detect_drift("score", db_path=str(db_path))
        assert result.status == "OK"
        assert "Insufficient data" in result.message

    def test_custom_time(self, tmp_path: Path):
        """Custom _now should be used for time window calculation."""
        db_path = tmp_path / "ml_tracker.db"
        # Create a minimal DB with the expected schema
        import sqlite3
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE ml_predictions (id TEXT, ts REAL, shap_json TEXT)")
        conn.execute(
            "INSERT INTO ml_predictions VALUES ('p1', ?, ?)",
            (time.time() - 100, json.dumps({"score": 0.5})),
        )
        conn.commit()
        conn.close()

        result = detect_drift("score", db_path=str(db_path), _now=time.time())
        assert result.status in ("OK", "WARN", "ALERT")
        assert result.feature == "score"

    @patch("core.concept_drift_detector._load_feature_values")
    def test_detect_alert(self, mock_load):
        """High PSI should produce ALERT status."""
        mock_load.side_effect = [
            [1.0] * 100,  # ref values
            [50.0] * 100,  # recent values
        ]
        result = detect_drift("score", psi_warn=0.10, psi_alert=0.25, ks_warn=0.20, _now=time.time())
        assert result.status == "ALERT"

    @patch("core.concept_drift_detector._load_feature_values")
    def test_detect_warn(self, mock_load):
        """Moderate shift should produce WARN status via KS threshold."""
        # Use slightly shifted distributions: ref=[1-5], recent=[2-6]
        # PSI≈1.52, KS≈0.20 — set psi_alert > PSI and ks_warn < KS so KS triggers WARN
        mock_load.side_effect = [
            [1.0, 2.0, 3.0, 4.0, 5.0] * 20,  # ref
            [2.0, 3.0, 4.0, 5.0, 6.0] * 20,  # recent (shifted by +1)
        ]
        result = detect_drift("score", psi_warn=0.10, psi_alert=10.0, ks_warn=0.15, _now=time.time())
        # PSI≈1.52 < 10.0 (no ALERT), KS≈0.20 >= 0.15 (triggers WARN)
        assert result.status == "WARN", f"Expected WARN, got {result.status}: psi={result.psi}, ks={result.ks}"

    @patch("core.concept_drift_detector._load_feature_values")
    def test_detect_ok(self, mock_load):
        """Identical distributions should produce OK status."""
        mock_load.side_effect = [
            [1.0, 2.0, 3.0] * 100,  # ref
            [1.0, 2.0, 3.0] * 100,  # recent - same
        ]
        result = detect_drift("score", psi_warn=0.10, psi_alert=0.50, ks_warn=0.20, _now=time.time())
        assert result.status == "OK"


# ── detect_all_features tests ────────────────────────────────────────────────

class TestDetectAllFeatures:
    """Test multi-feature drift detection."""

    @patch("core.concept_drift_detector.detect_drift")
    def test_all_features(self, mock_detect):
        """Should run detection on all specified features."""
        mock_detect.return_value = DriftResult(feature="score", psi=0.01, ks=0.01, ref_n=50, recent_n=50, status="OK", message="stable")
        results = detect_all_features(features=["score", "vix", "pcr"], _now=time.time())
        assert len(results) == 3
        assert all(r.status == "OK" for r in results.values())

    def test_empty_features(self):
        """Empty feature list should return empty dict."""
        results = detect_all_features(features=[], _now=time.time())
        assert results == {}


# ── format_drift_report tests ────────────────────────────────────────────────

class TestFormatDriftReport:
    """Test the drift report formatter."""

    def test_empty_results(self):
        """Empty results should return appropriate message."""
        report = format_drift_report({})
        assert "no features" in report.lower()

    def test_all_sorted_by_severity(self):
        """Results should be sorted ALERT → WARN → OK."""
        results = {
            "feature_a": DriftResult("a", 0.30, 0.10, 100, 50, "OK", "stable"),
            "feature_b": DriftResult("b", 0.30, 0.10, 100, 50, "ALERT", "alert"),
            "feature_c": DriftResult("c", 0.30, 0.10, 100, 50, "WARN", "warn"),
        }
        report = format_drift_report(results)
        lines = report.split("\n")
        # Find the feature lines
        feature_lines = [l for l in lines if l.strip().startswith("[")]
        # First should be ALERT
        assert "[!!]" in feature_lines[0]
        # Then WARN
        if len(feature_lines) > 1:
            assert "[~~]" in feature_lines[1]
        # Then OK
        if len(feature_lines) > 2:
            assert "[OK]" in feature_lines[2]

    def test_counts_in_header(self):
        """Header should show count of ALERT/WARN/OK."""
        results = {
            "a": DriftResult("a", 0.01, 0.01, 100, 50, "OK", "stable"),
            "b": DriftResult("b", 0.30, 0.10, 100, 50, "ALERT", "alert"),
            "c": DriftResult("c", 0.15, 0.05, 100, 50, "WARN", "warn"),
        }
        report = format_drift_report(results)
        assert "ALERT:1" in report
        assert "WARN:1" in report
        assert "OK:1" in report
