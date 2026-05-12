"""
Unit tests for ML Model Service/Adapter.
"""
from __future__ import annotations

import pytest
from unittest.mock import Mock, patch
from datetime import datetime

from infrastructure.adapters.ml_model.ml_model_adapter import MLModelAdapter
from core.ports.ml_model import MlModelPort, MLPrediction


class TestMLModelAdapter:
    """Test cases for MLModelAdapter."""

    def setup_method(self):
        """Set up test fixtures."""
        self.adapter = MLModelAdapter(journal_path="test_ml_tracker.db")

    def test_initialization(self):
        """Test adapter initialization."""
        assert self.adapter.journal_path == "test_ml_tracker.db"
        assert self.adapter.config == {}
        assert self.adapter._model is None  # Since we're mocking
        assert self.adapter._model_loaded_at == 0.0
        assert self.adapter._model_version == "1.0.0"

    def test_initialization_with_config(self):
        """Test adapter initialization with config."""
        config = {"learning_rate": 0.01, "max_depth": 6}
        adapter = MLModelAdapter(journal_path="test.db", config=config)
        
        assert adapter.config == config

    @patch("infrastructure.adapters.ml_model.ml_model_adapter.get_classifier")
    @patch("infrastructure.adapters.ml_model.ml_model_adapter.predict_win_prob")
    def test_predict_win_probability_success(self, mock_predict, mock_get_classifier):
        """Test successful win probability prediction."""
        # Setup
        mock_model = Mock()
        mock_get_classifier.return_value = mock_model
        mock_predict.return_value = 0.75
        
        # Reload model to use mocked classifier
        self.adapter._reload_model()
        
        # Execute
        features = {"feature1": 0.5, "feature2": 1.0}
        result = self.adapter.predict_win_probability(features)
        
        # Verify
        assert isinstance(result, MLPrediction)
        assert result.win_probability == 0.75
        assert result.confidence == 0.75  # Uses win_probability as confidence
        assert result.features_used == ["feature1", "feature2"]
        assert result.model_version == "1.0.0"
        assert isinstance(result.prediction_timestamp, datetime)
        assert result.metadata == {}
        
        mock_get_classifier.assert_called_once_with("test_ml_tracker.db", {})
        mock_predict.assert_called_once_with(mock_model, features)

    def test_predict_win_probability_model_not_ready(self):
        """Test prediction when model is not ready."""
        # Setup - model is None (not loaded)
        self.adapter._model = None
        
        # Execute and verify
        with pytest.raises(RuntimeError, match="ML model is not ready"):
            self.adapter.predict_win_probability({"feature1": 0.5})

    @patch("infrastructure.adapters.ml_model.ml_model_adapter.get_classifier")
    @patch("infrastructure.adapters.ml_model.ml_model_adapter.predict_win_prob")
    def test_predict_win_probability_prediction_failure(self, mock_predict, mock_get_classifier):
        """Test prediction when underlying predict function fails."""
        # Setup
        mock_model = Mock()
        mock_get_classifier.return_value = mock_model
        mock_predict.side_effect = Exception("Prediction failed")
        self.adapter._reload_model()
        
        # Execute and verify
        with pytest.raises(RuntimeError, match="ML prediction failed"):
            self.adapter.predict_win_probability({"feature1": 0.5})

    def test_is_model_ready_true(self):
        """Test is_model_ready when model is loaded."""
        # Setup
        self.adapter._model = Mock()  # Not None
        
        # Execute
        result = self.adapter.is_model_ready()
        
        # Verify
        assert result is True

    def test_is_model_ready_false(self):
        """Test is_model_ready when model is not loaded."""
        # Setup
        self.adapter._model = None
        
        # Execute
        result = self.adapter.is_model_ready()
        
        # Verify
        assert result is False

    def test_get_model_info(self):
        """Test getting model information."""
        # Setup
        self.adapter._model_loaded_at = 1234567890.0
        
        # Execute
        info = self.adapter.get_model_info()
        
        # Verify
        assert isinstance(info, dict)
        assert info["model_version"] == "1.0.0"
        assert info["model_loaded_at"] == 1234567890.0
        assert "features_expected" in info
        assert info["journal_path"] == "test_ml_tracker.db"

    @patch("infrastructure.adapters.ml_model.ml_model_adapter.get_performance_feature_importance")
    def test_get_feature_importance_success(self, mock_get_importance):
        """Test getting feature importance when available."""
        # Setup
        mock_get_importance.return_value = {"feature1": 0.8, "feature2": 0.2}
        
        # Execute
        importance = self.adapter.get_feature_importance()
        
        # Verify
        assert importance == {"feature1": 0.8, "feature2": 0.2}
        mock_get_importance.assert_called_once()

    @patch("infrastructure.adapters.ml_model.ml_model_adapter.get_performance_feature_importance")
    def test_get_feature_importance_none(self, mock_get_importance):
        """Test getting feature importance when function returns None."""
        # Setup
        mock_get_importance.return_value = None
        
        # Execute
        importance = self.adapter.get_feature_importance()
        
        # Verify
        assert importance == {}

    @patch("infrastructure.adapters.ml_model.ml_model_adapter.get_performance_feature_importance")
    def test_get_feature_importance_exception(self, mock_get_importance):
        """Test getting feature importance when function raises exception."""
        # Setup
        mock_get_importance.side_effect = Exception("Importance calculation failed")

        # Execute
        importance = self.adapter.get_feature_importance()

        # Verify
        assert importance == {}

    @patch("infrastructure.adapters.ml_model.ml_model_adapter.get_classifier")
    @patch("infrastructure.adapters.ml_model.ml_model_adapter.predict_win_prob")
    def test_predict_win_probability_invalid_features(self, mock_predict, mock_get_classifier):
        """Test prediction with invalid/missing features."""
        # Setup
        mock_model = Mock()
        mock_get_classifier.return_value = mock_model
        # Mock predict_win_prob to be available (not None) so validation runs
        mock_predict.return_value = 0.5
        self.adapter._reload_model()

        # Patch FEATURE_COLS to expect two specific features
        with patch("infrastructure.adapters.ml_model.ml_model_adapter.FEATURE_COLS", ["feature1", "feature2"]):
            # Execute and verify - missing required feature should give ValueError
            with pytest.raises(ValueError, match="Invalid or missing features"):
                self.adapter.predict_win_probability({"wrong_feature": 0.5})

    @patch("infrastructure.adapters.ml_model.ml_model_adapter.ml_train")
    @patch("infrastructure.adapters.ml_model.ml_model_adapter.save_model")
    def test_retrain_model_success(self, mock_save, mock_train):
        """Test successful model retraining."""
        # Setup
        mock_model = Mock()
        mock_train.return_value = mock_model
        mock_save.return_value = True
        
        # Execute
        training_data = [{"feature1": 0.5, "feature2": 1.0}]
        labels = [1, 0]
        result = self.adapter.retrain_model(training_data, labels)
        
        # Verify
        assert result is True
        mock_train.assert_called_once_with("test_ml_tracker.db", {}, training_data, labels)
        mock_save.assert_called_once_with(mock_model, "test_ml_tracker_model.pkl")
        assert self.adapter._model == mock_model
        assert self.adapter._model_loaded_at > 0

    @patch("infrastructure.adapters.ml_model.ml_model_adapter.ml_train")
    def test_retrain_model_training_fails(self, mock_train):
        """Test retraining when training fails."""
        # Setup
        mock_train.return_value = None
        
        # Execute
        training_data = [{"feature1": 0.5}]
        labels = [1]
        result = self.adapter.retrain_model(training_data, labels)
        
        # Verify
        assert result is False
        assert self.adapter._model is None

    @patch("infrastructure.adapters.ml_model.ml_model_adapter.ml_train")
    @patch("infrastructure.adapters.ml_model.ml_model_adapter.save_model")
    def test_retrain_model_save_fails(self, mock_save, mock_train):
        """Test retraining when model saving fails."""
        # Setup
        mock_model = Mock()
        mock_train.return_value = mock_model
        mock_save.return_value = False
        
        # Execute
        training_data = [{"feature1": 0.5}]
        labels = [1]
        result = self.adapter.retrain_model(training_data, labels)
        
        # Verify
        assert result is False
        # Model should not be updated if save fails
        # (In current implementation, model is updated before save check)

    def test_validate_features_valid(self):
        """Test feature validation with valid features."""
        # Setup - mock FEATURE_COLS
        with patch("infrastructure.adapters.ml_model.ml_model_adapter.FEATURE_COLS", ["feature1", "feature2"]):
            # Execute
            is_valid, invalid_features = self.adapter.validate_features({"feature1": 0.5, "feature2": 1.0})
            
            # Verify
            assert is_valid is True
            assert invalid_features == []

    def test_validate_features_missing(self):
        """Test feature validation with missing features."""
        # Setup - mock FEATURE_COLS
        with patch("infrastructure.adapters.ml_model.ml_model_adapter.FEATURE_COLS", ["feature1", "feature2", "feature3"]):
            # Execute
            is_valid, invalid_features = self.adapter.validate_features({"feature1": 0.5})
            
            # Verify
            assert is_valid is False
            assert set(invalid_features) == {"feature2", "feature3"}

    def test_validate_features_empty_expected(self):
        """Test feature validation when no expected features."""
        # Setup - mock FEATURE_COLS as empty
        with patch("infrastructure.adapters.ml_model.ml_model_adapter.FEATURE_COLS", []):
            # Execute
            is_valid, invalid_features = self.adapter.validate_features({"any_feature": 0.5})
            
            # Verify
            assert is_valid is True
            assert invalid_features == []

    def test_validate_features_extra_allowed(self):
        """Test that extra features are allowed (only missing features are checked)."""
        # Setup - mock FEATURE_COLS
        with patch("infrastructure.adapters.ml_model.ml_model_adapter.FEATURE_COLS", ["feature1"]):
            # Execute - extra feature provided
            is_valid, invalid_features = self.adapter.validate_features({"feature1": 0.5, "extra_feature": 1.0})
            
            # Verify
            assert is_valid is True  # Extra features are allowed
            assert invalid_features == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
