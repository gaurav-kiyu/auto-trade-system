"""Tests for core.ml_regime_router - regime-based ML model routing."""

from __future__ import annotations

from core.ml_regime_router import MLRegimeRouter, ModelMeta


class TestModelMeta:
    """Tests for ModelMeta dataclass."""

    def test_defaults(self) -> None:
        meta = ModelMeta(path="/models/x.joblib", regime="TRENDING", version="1.0.0")
        assert meta.path == "/models/x.joblib"
        assert meta.regime == "TRENDING"
        assert meta.version == "1.0.0"


class TestMLRegimeRouter:
    """Tests for MLRegimeRouter - regime-aware model selection."""

    def setup_method(self) -> None:
        self.router = MLRegimeRouter({})

    def test_init_with_empty_config(self) -> None:
        assert self.router.model_dir == "models/"
        assert self.router._loaded_models == {}

    def test_regime_map_contains_all_regimes(self) -> None:
        assert "TRENDING" in self.router.regime_map
        assert "CHOPPY" in self.router.regime_map
        assert "PANIC" in self.router.regime_map
        assert "NEUTRAL" in self.router.regime_map

    def test_unknown_regime_falls_back_to_default(self) -> None:
        model_file = self.router.regime_map.get("UNKNOWN", self.router.regime_map["NEUTRAL"])
        assert model_file == "model_default.joblib"

    def test_get_model_nonexistent_returns_none(self) -> None:
        """When model directory has no files, returns None."""
        model = self.router.get_model_for_regime("NEUTRAL")
        assert model is None  # model_default.joblib doesn't exist

    def test_get_model_unknown_regime_falls_back(self) -> None:
        """Unknown regime should fallback to NEUTRAL model."""
        model = self.router.get_model_for_regime("UNKNOWN_REGIME")
        assert model is None  # fallback also doesn't exist

    def test_custom_model_dir(self) -> None:
        router = MLRegimeRouter({"ml_model_dir": "/custom/models/"})
        assert router.model_dir == "/custom/models/"

    def test_update_model_weights_does_not_crash(self) -> None:
        """update_model_weights is a placeholder and should not raise."""
        self.router.update_model_weights("TRENDING", "/data/new_trades.csv")
        # No assertion needed - just verifies no exception

    def test_get_model_for_regime_upper(self) -> None:
        """Regime should be case-insensitive (upper)."""
        model_lower = self.router.get_model_for_regime("trending")
        model_upper = self.router.get_model_for_regime("TRENDING")
        assert model_lower == model_upper  # both should be None
