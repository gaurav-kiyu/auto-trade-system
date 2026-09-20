import json
from pathlib import Path
import pytest
from unittest.mock import MagicMock

from core.signals.signal_tracker import SignalTracker


@pytest.fixture
def temp_tracker(tmp_path):
    """Provide an isolated SignalTracker instance with its own database."""
    db_file = tmp_path / "test_explain_signals.db"
    SignalTracker.reset_instance()
    tracker = SignalTracker(db_path=db_file)
    yield tracker
    SignalTracker.reset_instance()


def test_get_signal_explanation_persisted_components(temp_tracker):
    """Test retrieving canonical persisted score components without runtime recalculation."""
    sample_components = {
        "trend_alignment": 25.0,
        "volume_surge": 20.0,
        "volatility_contraction": 15.0,
        "regime_bonus": 10.0,
        "ml_probability": 0.82,
    }

    signal_dict = {
        "symbol": "RELIANCE",
        "company_name": "Reliance Industries Ltd",
        "direction": "CALL",
        "price": 2500.0,
        "stop_loss": 2425.0,
        "target_1": 2600.0,
        "target_2": 2700.0,
        "score": 85,
        "raw_score": 88.5,
        "normalized_score": 85,
        "tier": "STRONG",
        "category": "LARGE_CAP_EQUITY",
        "score_components": sample_components,
        "confidence": 0.95,
        "ml_probability": 0.82,
    }

    sig_id = temp_tracker.record_generated_signal(signal_dict)
    assert sig_id != ""

    explanation = temp_tracker.get_signal_explanation(sig_id)
    assert explanation is not None
    assert explanation["signal_id"] == sig_id
    assert explanation["symbol"] == "RELIANCE"
    assert explanation["score"] == 85
    assert explanation["tier"] == "STRONG"
    assert explanation["direction"] == "CALL"
    assert explanation["entry_price"] == 2500.0
    assert explanation["score_components"] == sample_components
    assert explanation["metadata"]["raw_score"] == 88.5
    assert explanation["metadata"]["normalized_score"] == 85


def test_get_signal_explanation_fallback_structure(temp_tracker):
    """Test that signals without explicit score_components dict still get structured explanation."""
    signal_dict = {
        "symbol": "TCS",
        "direction": "PUT",
        "price": 3400.0,
        "score": 75,
        "raw_score": 75,
        "normalized_score": 75,
        "tier": "MODERATE",
        "category": "LARGE_CAP_EQUITY",
    }

    sig_id = temp_tracker.record_generated_signal(signal_dict)
    assert sig_id != ""

    explanation = temp_tracker.get_signal_explanation(sig_id)
    assert explanation is not None
    assert explanation["signal_id"] == sig_id
    assert "base_score" in explanation["score_components"]
    assert explanation["score_components"]["base_score"] == 75


def test_get_signal_explanation_not_found(temp_tracker):
    """Test that an unknown signal_id returns None."""
    assert temp_tracker.get_signal_explanation("NON_EXISTENT_SIG_ID") is None


def test_analytics_attaches_score_components(temp_tracker):
    """Test get_admin_signal_analytics attaches score_components to each signal."""
    components = {"factor_a": 40, "factor_b": 45}
    sig_id = temp_tracker.record_generated_signal({
        "symbol": "INFY",
        "direction": "CALL",
        "price": 1800.0,
        "score": 85,
        "tier": "STRONG",
        "category": "LARGE_CAP_EQUITY",
        "score_components": components,
    })

    analytics = temp_tracker.get_admin_signal_analytics(include_seed_samples=False)
    assert len(analytics["signals"]) >= 1
    found = next((s for s in analytics["signals"] if s["signal_id"] == sig_id), None)
    assert found is not None
    assert found["score_components"] == components
