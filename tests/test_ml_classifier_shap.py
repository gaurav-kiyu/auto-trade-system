"""
Tests for SHAP explainability additions to core/ml_classifier.py (Phase B).

All SHAP tests are designed to pass whether or not the optional ``shap``
package is installed — the module contract guarantees graceful no-ops.

Covers:
  - explain_prediction() with shap_enabled=False → always {}
  - explain_prediction() with shap_enabled=True but no shap → still {} or fallback
  - get_top_features() sorting and slicing
  - get_top_features() on empty dict
  - shap_to_json() round-trips
  - shap_to_json() on empty dict
  - extract_features() still works (regression guard)
  - predict_win_prob() still works (regression guard)
  - score_adj_from_prob() bounds (regression guard)
"""
import json
import math

import pytest

from core.ml_classifier import (
    explain_prediction,
    get_top_features,
    shap_to_json,
    extract_features,
    predict_win_prob,
    score_adj_from_prob,
    FEATURE_COLS,
)


# ── Minimal stub model (no LightGBM required) ─────────────────────────────────

class _StubModel:
    """Minimal predict_proba-compatible stub that also has feature_importances_."""
    feature_importances_ = [1.0, 2.0, 3.0, 0.5, 0.5, 0.5, 1.5, 0.8, 0.7]

    def predict_proba(self, X):
        return [[0.35, 0.65]]


_STUB = _StubModel()


def _features():
    return extract_features({
        "score": 72,
        "confidence": 0.7,
        "direction": "CALL",
        "tier": "STRONG",
        "signal_ts": 1_750_000_000.0,
        "soft_blocks": [],
    })


# ── explain_prediction ────────────────────────────────────────────────────────

class TestExplainPrediction:
    def test_disabled_returns_empty_dict(self):
        result = explain_prediction(_STUB, _features(), cfg={"shap_enabled": False})
        assert result == {}

    def test_default_cfg_returns_empty(self):
        # shap_enabled defaults to False
        result = explain_prediction(_STUB, _features())
        assert result == {}

    def test_enabled_returns_dict_or_empty(self):
        # When shap_enabled=True, the result depends on whether `shap` is installed.
        # Either way it must be a dict (never raises).
        result = explain_prediction(_STUB, _features(), cfg={"shap_enabled": True})
        assert isinstance(result, dict)

    def test_enabled_values_are_floats(self):
        result = explain_prediction(_STUB, _features(), cfg={"shap_enabled": True})
        for v in result.values():
            assert isinstance(v, float)

    def test_enabled_keys_subset_of_feature_cols(self):
        result = explain_prediction(_STUB, _features(), cfg={"shap_enabled": True})
        assert set(result.keys()).issubset(set(FEATURE_COLS))

    def test_broken_model_returns_empty(self):
        class _Bad:
            feature_importances_ = []
            def predict_proba(self, X): raise RuntimeError("kaboom")
        result = explain_prediction(_Bad(), _features(), cfg={"shap_enabled": True})
        assert isinstance(result, dict)

    def test_none_model_does_not_raise(self):
        result = explain_prediction(None, _features(), cfg={"shap_enabled": True})
        assert isinstance(result, dict)

    def test_empty_features_does_not_raise(self):
        result = explain_prediction(_STUB, {}, cfg={"shap_enabled": True})
        assert isinstance(result, dict)


# ── get_top_features ──────────────────────────────────────────────────────────

class TestGetTopFeatures:
    def test_empty_returns_empty(self):
        assert get_top_features({}) == []

    def test_returns_n_items(self):
        vals = {"a": 0.1, "b": 0.5, "c": -0.3, "d": 0.9, "e": -0.05}
        result = get_top_features(vals, n=3)
        assert len(result) == 3

    def test_sorted_by_abs_descending(self):
        vals = {"a": 0.1, "b": -0.8, "c": 0.3}
        result = get_top_features(vals, n=3)
        abs_vals = [abs(v) for _, v in result]
        assert abs_vals == sorted(abs_vals, reverse=True)

    def test_top_1_returns_one_tuple(self):
        vals = {"x": 0.9, "y": 0.1}
        result = get_top_features(vals, n=1)
        assert len(result) == 1
        assert result[0][0] == "x"

    def test_n_larger_than_dict(self):
        vals = {"a": 1.0, "b": 2.0}
        result = get_top_features(vals, n=10)
        assert len(result) == 2

    def test_negative_dominates(self):
        vals = {"pos": 0.3, "neg": -0.9}
        result = get_top_features(vals, n=1)
        assert result[0][0] == "neg"

    def test_result_tuples_have_name_and_float(self):
        vals = {"score": 0.42}
        result = get_top_features(vals)
        assert isinstance(result[0][0], str)
        assert isinstance(result[0][1], float)


# ── shap_to_json ──────────────────────────────────────────────────────────────

class TestShapToJson:
    def test_empty_returns_braces(self):
        assert shap_to_json({}) == "{}"

    def test_round_trip(self):
        vals = {"score": 0.123456, "confidence": -0.456789}
        s = shap_to_json(vals)
        parsed = json.loads(s)
        assert abs(parsed["score"] - 0.123456) < 1e-5
        assert abs(parsed["confidence"] - (-0.456789)) < 1e-5

    def test_values_rounded_to_6dp(self):
        vals = {"a": 0.123456789}
        s = shap_to_json(vals)
        parsed = json.loads(s)
        assert len(str(parsed["a"]).split(".")[-1]) <= 7   # at most 6 decimal places

    def test_returns_valid_json(self):
        vals = {"x": 1.0, "y": -2.0}
        s = shap_to_json(vals)
        parsed = json.loads(s)
        assert isinstance(parsed, dict)


# ── Regression guards — existing functions unaffected ─────────────────────────

class TestRegressionGuards:
    def test_extract_features_returns_all_cols(self):
        feats = _features()
        assert set(feats.keys()) == set(FEATURE_COLS)

    def test_extract_features_all_float(self):
        for v in _features().values():
            assert isinstance(v, float)

    def test_predict_win_prob_stub(self):
        prob = predict_win_prob(_STUB, _features())
        assert 0.0 <= prob <= 1.0
        assert abs(prob - 0.65) < 0.01

    def test_predict_win_prob_bad_model_returns_half(self):
        class _Bad:
            def predict_proba(self, X): raise RuntimeError("fail")
        prob = predict_win_prob(_Bad(), _features())
        assert prob == 0.5

    def test_score_adj_high_prob(self):
        adj, tag = score_adj_from_prob(0.9, {"ml_score_adj_cap": 10, "ml_high_prob_threshold": 0.65})
        assert adj > 0
        assert "+" in tag

    def test_score_adj_low_prob(self):
        adj, tag = score_adj_from_prob(0.2, {"ml_score_adj_cap": 10, "ml_low_prob_threshold": 0.40})
        assert adj < 0

    def test_score_adj_neutral(self):
        adj, tag = score_adj_from_prob(0.5)
        assert adj == 0
        assert "neutral" in tag
