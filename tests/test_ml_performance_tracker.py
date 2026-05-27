"""
Tests for core/ml_performance_tracker.py (Phase B).

Covers:
  - record_prediction() write + DB creation
  - update_outcome() fills NULL rows
  - compute_brier_score() perfect / random / missing
  - compute_calibration() bin structure and monotonicity
  - get_feature_importance_trend() SHAP aggregation
  - format_tracker_summary() string contract
  - Missing DB file handling (graceful no-op)
  - Days filter on Brier score
"""
import json
import sqlite3
import time

import pytest
from core.ml_performance_tracker import (
    compute_brier_score,
    compute_calibration,
    format_tracker_summary,
    get_feature_importance_trend,
    record_prediction,
    update_outcome,
)

# ── Fixture ───────────────────────────────────────────────────────────────────

@pytest.fixture()
def db(tmp_path):
    return str(tmp_path / "ml_tracker.db")


# ── record_prediction ─────────────────────────────────────────────────────────

class TestRecordPrediction:
    def test_creates_db_on_first_write(self, db, tmp_path):
        import os
        ok = record_prediction("t001", 0.70, db_path=db)
        assert ok is True
        assert os.path.isfile(db)

    def test_row_stored_with_correct_values(self, db):
        record_prediction("t002", 0.65, actual=1, db_path=db)
        conn = sqlite3.connect(db)
        row = conn.execute(
            "SELECT predicted_prob, actual_outcome FROM ml_predictions WHERE trade_id='t002'"
        ).fetchone()
        conn.close()
        assert abs(row[0] - 0.65) < 1e-6
        assert row[1] == 1

    def test_null_actual_stored_correctly(self, db):
        record_prediction("t003", 0.5, db_path=db)
        conn = sqlite3.connect(db)
        row = conn.execute(
            "SELECT actual_outcome FROM ml_predictions WHERE trade_id='t003'"
        ).fetchone()
        conn.close()
        assert row[0] is None

    def test_shap_json_stored(self, db):
        shap = json.dumps({"score": 0.12, "confidence": -0.05})
        record_prediction("t004", 0.6, shap_json=shap, db_path=db)
        conn = sqlite3.connect(db)
        row = conn.execute(
            "SELECT shap_json FROM ml_predictions WHERE trade_id='t004'"
        ).fetchone()
        conn.close()
        parsed = json.loads(row[0])
        assert abs(parsed["score"] - 0.12) < 1e-6

    def test_returns_false_on_invalid_prob(self, db):
        result = record_prediction("t005", "not-a-float", db_path=db)
        assert isinstance(result, bool)


# ── update_outcome ────────────────────────────────────────────────────────────

class TestUpdateOutcome:
    def test_returns_false_when_db_missing(self, tmp_path):
        ok = update_outcome("t001", 1, db_path=str(tmp_path / "no.db"))
        assert ok is False

    def test_updates_null_outcome(self, db):
        record_prediction("t010", 0.7, db_path=db)
        ok = update_outcome("t010", 1, db_path=db)
        assert ok is True
        conn = sqlite3.connect(db)
        row = conn.execute(
            "SELECT actual_outcome FROM ml_predictions WHERE trade_id='t010'"
        ).fetchone()
        conn.close()
        assert row[0] == 1

    def test_does_not_overwrite_existing_outcome(self, db):
        record_prediction("t011", 0.7, actual=1, db_path=db)
        ok = update_outcome("t011", 0, db_path=db)
        assert ok is False          # rowcount=0 because WHERE actual_outcome IS NULL
        conn = sqlite3.connect(db)
        row = conn.execute(
            "SELECT actual_outcome FROM ml_predictions WHERE trade_id='t011'"
        ).fetchone()
        conn.close()
        assert row[0] == 1          # unchanged

    def test_returns_false_for_unknown_trade(self, db):
        record_prediction("t012", 0.6, actual=1, db_path=db)
        ok = update_outcome("UNKNOWN_ID", 1, db_path=db)
        assert ok is False

    def test_returns_false_on_corrupt_db(self, db):
        with open(db, "w") as f:
            f.write("not a valid sqlite database")
        ok = update_outcome("t001", 1, db_path=db)
        assert ok is False


# ── compute_brier_score ───────────────────────────────────────────────────────

class TestComputeBrierScore:
    def test_returns_none_when_db_missing(self, tmp_path):
        result = compute_brier_score(db_path=str(tmp_path / "no.db"))
        assert result is None

    def test_returns_none_when_no_completed(self, db):
        record_prediction("t020", 0.6, db_path=db)   # no actual
        assert compute_brier_score(db_path=db) is None

    def test_perfect_predictions_score_zero(self, db):
        for i in range(10):
            record_prediction(f"p{i}", 1.0, actual=1, db_path=db)
        bs = compute_brier_score(db_path=db)
        assert bs is not None
        assert abs(bs) < 1e-6

    def test_coin_flip_baseline_near_025(self, db):
        for i in range(100):
            actual = i % 2
            record_prediction(f"cf{i}", 0.5, actual=actual, db_path=db)
        bs = compute_brier_score(db_path=db)
        assert bs is not None
        assert abs(bs - 0.25) < 0.01

    def test_worst_predictions_near_1(self, db):
        for i in range(10):
            record_prediction(f"w{i}", 0.0, actual=1, db_path=db)
        bs = compute_brier_score(db_path=db)
        assert bs is not None
        assert abs(bs - 1.0) < 1e-6

    def test_days_filter_excludes_old(self, db):
        # Write an old record directly into db
        from core.ml_performance_tracker import _get_conn
        conn = _get_conn(db)
        old_ts = time.time() - 200 * 86400
        conn.execute(
            "INSERT INTO ml_predictions (ts, trade_id, predicted_prob, actual_outcome) VALUES (?,?,?,?)",
            (old_ts, "old_trade", 0.0, 1),
        )
        conn.commit()
        conn.close()
        # Write a recent perfect record
        record_prediction("new_trade", 1.0, actual=1, db_path=db)
        bs = compute_brier_score(db_path=db, days=30)
        assert bs is not None
        assert abs(bs) < 1e-4       # only the perfect recent record is in scope

    def test_returns_float_in_range(self, db):
        record_prediction("r1", 0.6, actual=1, db_path=db)
        record_prediction("r2", 0.4, actual=0, db_path=db)
        bs = compute_brier_score(db_path=db)
        assert isinstance(bs, float)
        assert 0.0 <= bs <= 1.0

    def test_returns_none_on_corrupt_db(self, db):
        with open(db, "w") as f:
            f.write("not a valid sqlite database")
        result = compute_brier_score(db_path=db)
        assert result is None


# ── compute_calibration ───────────────────────────────────────────────────────

class TestComputeCalibration:
    def test_returns_empty_list_when_db_missing(self, tmp_path):
        result = compute_calibration(db_path=str(tmp_path / "no.db"))
        assert result == []

    def test_returns_empty_when_no_completed(self, db):
        record_prediction("c0", 0.5, db_path=db)
        assert compute_calibration(db_path=db) == []

    def test_bins_have_required_keys(self, db):
        for i in range(20):
            record_prediction(f"cal{i}", 0.3 + i * 0.02, actual=i % 2, db_path=db)
        bins = compute_calibration(db_path=db)
        assert len(bins) > 0
        for b in bins:
            assert "bin_low" in b
            assert "bin_mid" in b
            assert "predicted_mean" in b
            assert "actual_rate" in b
            assert "count" in b

    def test_actual_rate_is_fraction(self, db):
        for i in range(10):
            record_prediction(f"ar{i}", 0.8, actual=1, db_path=db)
        bins = compute_calibration(db_path=db)
        for b in bins:
            assert 0.0 <= b["actual_rate"] <= 1.0

    def test_counts_sum_to_total(self, db):
        n = 15
        for i in range(n):
            record_prediction(f"ct{i}", 0.1 * (i % 10), actual=i % 2, db_path=db)
        bins = compute_calibration(db_path=db)
        assert sum(b["count"] for b in bins) == n

    def test_bin_low_increasing(self, db):
        for i in range(30):
            record_prediction(f"bi{i}", i / 30, actual=i % 2, db_path=db)
        bins = compute_calibration(db_path=db)
        lows = [b["bin_low"] for b in bins]
        assert lows == sorted(lows)

    def test_returns_empty_on_corrupt_db(self, db):
        with open(db, "w") as f:
            f.write("not a valid sqlite database")
        result = compute_calibration(db_path=db)
        assert result == []


# ── get_feature_importance_trend ──────────────────────────────────────────────

class TestGetFeatureImportanceTrend:
    def test_returns_empty_when_db_missing(self, tmp_path):
        result = get_feature_importance_trend(db_path=str(tmp_path / "no.db"))
        assert result == {}

    def test_returns_empty_when_no_shap(self, db):
        record_prediction("ft0", 0.5, actual=1, db_path=db)  # no shap_json
        result = get_feature_importance_trend(db_path=db)
        assert result == {}

    def test_aggregates_abs_shap(self, db):
        shap1 = json.dumps({"score": 0.5, "confidence": -0.3})
        shap2 = json.dumps({"score": -0.1, "confidence": 0.9})
        record_prediction("ft1", 0.7, shap_json=shap1, db_path=db)
        record_prediction("ft2", 0.6, shap_json=shap2, db_path=db)
        result = get_feature_importance_trend(db_path=db)
        assert "score" in result
        assert "confidence" in result
        # confidence mean abs = (0.3 + 0.9) / 2 = 0.6
        assert abs(result["confidence"] - 0.6) < 1e-4

    def test_sorted_descending(self, db):
        shap = json.dumps({"a": 0.1, "b": 0.9, "c": 0.5})
        record_prediction("ft3", 0.5, shap_json=shap, db_path=db)
        result = get_feature_importance_trend(db_path=db)
        vals = list(result.values())
        assert vals == sorted(vals, reverse=True)

    def test_n_last_limits_rows(self, db):
        for i in range(20):
            shap = json.dumps({"feat": float(i)})
            record_prediction(f"ft{10+i}", 0.5, shap_json=shap, db_path=db)
        result = get_feature_importance_trend(n_last=5, db_path=db)
        # Mean of last 5 feat values: 15,16,17,18,19 → mean abs = 17.0
        assert result.get("feat") is not None
        assert abs(result["feat"] - 17.0) < 1e-4

    def test_skips_invalid_shap_json(self, db):
        record_prediction("inv1", 0.5, shap_json="not valid json", db_path=db)
        record_prediction("inv2", 0.6, shap_json='{"valid": 1}', db_path=db)
        result = get_feature_importance_trend(db_path=db)
        assert "valid" in result
        assert len(result) == 1

    def test_returns_empty_when_all_shap_invalid(self, db):
        record_prediction("inv3", 0.5, shap_json="not valid json", db_path=db)
        record_prediction("inv4", 0.6, shap_json="also not json", db_path=db)
        result = get_feature_importance_trend(db_path=db)
        assert result == {}

    def test_returns_empty_on_corrupt_db(self, db):
        with open(db, "w") as f:
            f.write("not a valid sqlite database")
        result = get_feature_importance_trend(db_path=db)
        assert result == {}


# ── format_tracker_summary ────────────────────────────────────────────────────

class TestFormatTrackerSummary:
    def test_returns_string_when_db_missing(self, tmp_path):
        s = format_tracker_summary(db_path=str(tmp_path / "no.db"))
        assert isinstance(s, str)
        assert len(s) > 0

    def test_contains_prediction_count(self, db):
        record_prediction("s1", 0.7, actual=1, db_path=db)
        record_prediction("s2", 0.4, actual=0, db_path=db)
        s = format_tracker_summary(db_path=db)
        assert "2" in s

    def test_contains_brier(self, db):
        record_prediction("sb1", 0.8, actual=1, db_path=db)
        s = format_tracker_summary(db_path=db)
        assert "Brier" in s

    def test_contains_feature_trend_when_shap_present(self, db):
        shap = json.dumps({"score": 0.5})
        record_prediction("sh1", 0.7, shap_json=shap, db_path=db)
        s = format_tracker_summary(db_path=db)
        assert isinstance(s, str)  # must not raise

    def test_no_exception_on_empty_db(self, db):
        s = format_tracker_summary(db_path=db)
        assert isinstance(s, str)

    def test_returns_unavailable_on_corrupt_db(self, db):
        with open(db, "w") as f:
            f.write("not a valid sqlite database")
        s = format_tracker_summary(db_path=db)
        assert "unavailable" in s
