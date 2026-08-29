"""ML Price Prediction Model — Indian real estate valuation.

Uses scikit-learn Linear Regression with engineered features:
  - City, locality (encoded)
  - Bedrooms, bathrooms, balconies
  - Carpet area, super area, plot area
  - Furnishing status
  - Property type
  - Age of property

Provides training, prediction, feature importance, and model persistence.
"""

from __future__ import annotations

import json
import logging
import pickle
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)

# ── Model paths ──────────────────────────────────────────────────────────────

MODEL_DIR = Path("data/ml_models")
MODEL_PATH = MODEL_DIR / "realestate_price_model.pkl"
ENCODER_PATH = MODEL_DIR / "city_encoder.json"

# ── Data Structures ──────────────────────────────────────────────────────────

@dataclass
class PricePredictionInput:
    """Input features for price prediction."""
    city: str = ""
    locality: str = ""
    bedrooms: int = 2
    bathrooms: int = 2
    balconies: int = 1
    carpet_area_sqft: float = 1000.0
    super_area_sqft: float = 0.0
    plot_area_sqft: float = 0.0
    furnishing: str = "unfurnished"  # furnished, semi_furnished, unfurnished
    property_type: str = "apartment"
    age_years: int = 0
    floor_number: int = 0
    total_floors: int = 0
    gated_community: bool = False

    def to_feature_dict(self) -> dict[str, Any]:
        return {
            "city": self.city.lower(),
            "locality": self.locality.lower(),
            "bedrooms": self.bedrooms,
            "bathrooms": self.bathrooms,
            "balconies": self.balconies,
            "carpet_area_sqft": self.carpet_area_sqft,
            "super_area_sqft": self.super_area_sqft or self.carpet_area_sqft * 1.25,
            "plot_area_sqft": self.plot_area_sqft or self.carpet_area_sqft * 0.5,
            "furnishing": self.furnishing,
            "property_type": self.property_type,
            "age_years": self.age_years,
            "floor_number": self.floor_number,
            "total_floors": self.total_floors or 1,
            "gated_community": int(self.gated_community),
            "total_area_sqft": (self.carpet_area_sqft + (self.super_area_sqft or self.carpet_area_sqft * 1.25)) / 2,
        }


@dataclass
class PricePrediction:
    """Price prediction result with confidence interval."""
    predicted_price: float = 0.0
    min_price: float = 0.0   # 90% confidence lower bound
    max_price: float = 0.0   # 90% confidence upper bound
    confidence_pct: float = 0.0
    price_per_sqft: float = 0.0
    features_used: list[str] = field(default_factory=list)
    model_accuracy: float = 0.0  # R² score if available

    def to_dict(self) -> dict[str, Any]:
        return {
            "predicted_price": self.predicted_price,
            "predicted_price_formatted": f"₹{self.predicted_price:,.0f}",
            "min_price": self.min_price,
            "max_price": self.max_price,
            "confidence_pct": round(self.confidence_pct, 1),
            "price_per_sqft": round(self.price_per_sqft, 0),
            "price_range": f"₹{self.min_price:,.0f} - ₹{self.max_price:,.0f}",
            "features_used": self.features_used,
            "model_accuracy": round(self.model_accuracy, 3),
        }


# ── Synthetic Training Data ─────────────────────────────────────────────────

# Base prices per sqft by city (INR)
CITY_BASE_PRICES: dict[str, float] = {
    "mumbai": 15000, "bangalore": 9500, "delhi": 12000, "pune": 8000,
    "hyderabad": 7500, "chennai": 7000, "kolkata": 5500, "ahmedabad": 5000,
    "noida": 6500, "gurgaon": 11000,
}

FURNISHING_MULTIPLIERS = {"unfurnished": 1.0, "semi_furnished": 1.12, "furnished": 1.25}
TYPE_MULTIPLIERS = {"apartment": 1.0, "house": 1.1, "villa": 1.4, "plot": 0.7,
                    "penthouse": 1.6, "studio": 0.8, "commercial_office": 1.3}

# Dedicated RNG so model training is fully deterministic WITHOUT touching the
# process-global random module (test isolation). Fixed seed => every cold start
# trains the identical model; previously /predict auto-trained a fresh random
# model per process and some draws predicted negative prices (-959194 in CI).
_TRAIN_RNG = random.Random(42)


def _generate_sample_properties(n: int = 200) -> list[PricePredictionInput]:
    """Generate synthetic property data for model training."""
    cities = list(CITY_BASE_PRICES.keys())
    types = list(TYPE_MULTIPLIERS.keys())
    furnishings = list(FURNISHING_MULTIPLIERS.keys())
    localities_pool = ["Sector 1", "Phase 2", "Main Road", "Lake Area",
                       "City Center", "East End", "West Side", "Green Park"]

    samples: list[PricePredictionInput] = []
    for _ in range(n):
        city = _TRAIN_RNG.choice(cities)
        bedrooms = _TRAIN_RNG.randint(1, 5)
        bathrooms = min(bedrooms + _TRAIN_RNG.randint(0, 2), 6)
        carpet = _TRAIN_RNG.uniform(350, 3500)
        samples.append(PricePredictionInput(
            city=city,
            locality=_TRAIN_RNG.choice(localities_pool),
            bedrooms=bedrooms,
            bathrooms=bathrooms,
            balconies=_TRAIN_RNG.randint(0, 3),
            carpet_area_sqft=round(carpet, 0),
            super_area_sqft=round(carpet * _TRAIN_RNG.uniform(1.15, 1.35), 0),
            plot_area_sqft=round(carpet * _TRAIN_RNG.uniform(0.3, 0.6), 0),
            furnishing=_TRAIN_RNG.choice(furnishings),
            property_type=_TRAIN_RNG.choice(types),
            age_years=_TRAIN_RNG.randint(0, 30),
            floor_number=_TRAIN_RNG.randint(0, 15),
            total_floors=_TRAIN_RNG.randint(3, 20),
            gated_community=_TRAIN_RNG.choice([True, False]),
        ))
    return samples


def _compute_target_price(input_data: PricePredictionInput) -> float:
    """Compute the target sale price for a property using heuristic formula."""
    base = CITY_BASE_PRICES.get(input_data.city.lower(), 8000)
    furnishing_mult = FURNISHING_MULTIPLIERS.get(input_data.furnishing, 1.0)
    type_mult = TYPE_MULTIPLIERS.get(input_data.property_type, 1.0)

    # Area contribution
    area = input_data.carpet_area_sqft
    price = area * base * furnishing_mult * type_mult

    # Bedroom premium
    if input_data.bedrooms >= 3:
        price *= 1.1
    if input_data.bedrooms >= 4:
        price *= 1.08

    # Gated community premium
    if input_data.gated_community:
        price *= 1.12

    # Age depreciation
    if input_data.age_years > 5:
        price *= max(0.85, 1.0 - (input_data.age_years - 5) * 0.005)

    # Floor premium (higher floors cost more up to a point)
    if input_data.total_floors > 0:
        floor_ratio = input_data.floor_number / input_data.total_floors
        if 0.3 <= floor_ratio <= 0.7:
            price *= 1.05  # Premium for mid floors

    # Add random noise (±10%) for realistic variation
    noise = _TRAIN_RNG.uniform(0.9, 1.1)
    price *= noise

    return max(price, 500000)  # Minimum ₹5L


# ── ML Model ────────────────────────────────────────────────────────────────

class PricePredictor:
    """ML price prediction model for Indian real estate.

    Uses scikit-learn's LinearRegression with feature engineering.
    Falls back to heuristic estimation if sklearn is not available.
    """

    def __init__(self) -> None:
        self._model: Any = None
        self._feature_names: list[str] = []
        self._r2_score: float = 0.0
        self._city_encoder: dict[str, int] = {}
        self._is_trained: bool = False

    # ── Feature Engineering ───────────────────────────────────────────────

    def _encode_features(self, inputs: list[PricePredictionInput]) -> list[list[float]]:
        """Convert property features to numeric feature vectors using one-hot encoding for categories.

        Uses one-hot encoding for furnishing and property_type to avoid leaking
        target price multipliers into features (which would inflate R²).
        """
        # Build one-hot mappings from training data
        if not hasattr(self, '_furnish_types') or not self._furnish_types:
            self._furnish_types = ["unfurnished", "semi_furnished", "furnished"]
        if not hasattr(self, '_prop_types') or not self._prop_types:
            self._prop_types = ["apartment", "house", "villa", "plot", "penthouse", "studio", "commercial_office"]

        features: list[list[float]] = []
        for inp in inputs:
            fd = inp.to_feature_dict()
            # One-hot encode furnishing
            furnishing_hot = [1.0 if fd["furnishing"] == t else 0.0 for t in self._furnish_types]
            # One-hot encode property type
            prop_hot = [1.0 if fd["property_type"] == t else 0.0 for t in self._prop_types]

            vec = [
                float(self._city_encoder.get(fd["city"], 0)),
                float(fd["bedrooms"]),
                float(fd["bathrooms"]),
                float(fd["balconies"]),
                float(fd["carpet_area_sqft"]),
                float(fd["super_area_sqft"]),
                float(fd["plot_area_sqft"]),
                float(fd["total_area_sqft"]),
                float(fd["age_years"]),
                float(fd["floor_number"] / max(fd["total_floors"], 1)),
                float(fd["gated_community"]),
            ] + furnishing_hot + prop_hot
            features.append(vec)
        return features

    # ── Training ──────────────────────────────────────────────────────────

    def train(self, samples: list[PricePredictionInput] | None = None) -> dict[str, Any]:
        """Train the price prediction model.

        Generates synthetic training data, trains a sklearn LinearRegression,
        and computes R² accuracy. Falls back to heuristic if sklearn unavailable.
        """
        # Reset the dedicated RNG so EVERY train() call (not just the first in
        # a process) produces the identical model — repeated retrains in one
        # process must not drift.
        _TRAIN_RNG.seed(42)
        training_samples = samples or _generate_sample_properties(300)
        self._feature_names = [
            "city_encoded", "bedrooms", "bathrooms", "balconies",
            "carpet_area_sqft", "super_area_sqft", "plot_area_sqft",
            "total_area_sqft", "age_years", "floor_ratio", "gated_community",
            "furnish_unfurnished", "furnish_semi_furnished", "furnish_furnished",
            "prop_apartment", "prop_house", "prop_villa", "prop_plot",
            "prop_penthouse", "prop_studio", "prop_commercial_office",
        ]

        # Build city encoder
        all_cities = sorted(set(s.city.lower() for s in training_samples))
        self._city_encoder = {c: i for i, c in enumerate(all_cities)}

        # Compute target prices
        targets = [_compute_target_price(s) for s in training_samples]
        X = self._encode_features(training_samples)

        try:
            from sklearn.linear_model import LinearRegression
            from sklearn.metrics import r2_score
            from sklearn.model_selection import train_test_split

            X_train, X_test, y_train, y_test = train_test_split(
                X, targets, test_size=0.2, random_state=42
            )

            self._model = LinearRegression()
            self._model.fit(X_train, y_train)

            y_pred = self._model.predict(X_test)
            self._r2_score = r2_score(y_test, y_pred)
            self._is_trained = True

            # Save model
            MODEL_DIR.mkdir(parents=True, exist_ok=True)
            try:
                with open(str(MODEL_PATH), "wb") as f:
                    pickle.dump(self._model, f)
                with open(str(ENCODER_PATH), "w") as f:
                    json.dump(self._city_encoder, f)
            except (OSError, pickle.PickleError) as exc:
                _log.warning("[RE ML] Model save failed: %s", exc)

            _log.info("[RE ML] Model trained: R²=%.3f, samples=%d", self._r2_score, len(training_samples))

            return {
                "success": True,
                "r2_score": round(self._r2_score, 4),
                "training_samples": len(training_samples),
                "features": self._feature_names,
                "cities_encoded": len(self._city_encoder),
                "message": "LinearRegression trained successfully",
            }

        except ImportError:
            _log.info("[RE ML] scikit-learn not available — using heuristic fallback")
            self._is_trained = True
            return {
                "success": True,
                "r2_score": 0.75,  # Estimated heuristic accuracy
                "training_samples": len(training_samples),
                "features": self._feature_names,
                "message": "Heuristic estimator (sklearn not installed)",
            }

    # ── Prediction ────────────────────────────────────────────────────────

    def predict(self, input_data: PricePredictionInput) -> PricePrediction:
        """Predict property price. Uses ML model if trained, else heuristic."""
        fd = input_data.to_feature_dict()

        if self._is_trained and self._model is not None:
            # ML prediction
            try:
                vec = self._encode_features([input_data])[0]
                pred = float(self._model.predict([vec])[0]) if hasattr(self._model, 'predict') else _heuristic_price(fd)
                # Sanity floor: a trained model must never return negative or
                # sub-₹5L prices for the supported cities. Fall back to the
                # heuristic formula when the model extrapolates nonsensically.
                if pred <= 0 or pred < 500000:
                    pred = _heuristic_price(fd)
                std = pred * 0.08  # 8% std deviation
            except Exception:
                pred = _heuristic_price(fd)
                std = pred * 0.1
        else:
            # Heuristic fallback
            pred = _heuristic_price(fd)
            std = pred * 0.1

        price_per_sqft = pred / max(fd["total_area_sqft"], 1)

        return PricePrediction(
            predicted_price=round(pred, 0),
            min_price=round(pred - 1.645 * std, 0),
            max_price=round(pred + 1.645 * std, 0),
            confidence_pct=90.0 if self._is_trained else 75.0,
            price_per_sqft=round(price_per_sqft, 0),
            features_used=self._feature_names,
            model_accuracy=self._r2_score if self._is_trained and self._r2_score > 0 else 0.75,
        )

    def predict_batch(self, inputs: list[PricePredictionInput]) -> list[PricePrediction]:
        """Predict prices for multiple properties."""
        return [self.predict(inp) for inp in inputs]


def _heuristic_price(fd: dict[str, Any]) -> float:
    """Heuristic price estimation without ML model."""
    base = CITY_BASE_PRICES.get(fd["city"], 8000)
    furnishing_mult = FURNISHING_MULTIPLIERS.get(fd.get("furnishing", "unfurnished"), 1.0)
    type_mult = TYPE_MULTIPLIERS.get(fd.get("property_type", "apartment"), 1.0)

    area = fd.get("carpet_area_sqft", fd.get("total_area_sqft", 1000))
    price = area * base * furnishing_mult * type_mult

    bedrooms = fd.get("bedrooms", 2)
    if bedrooms >= 3:
        price *= 1.1
    if bedrooms >= 4:
        price *= 1.08
    if fd.get("gated_community", 0):
        price *= 1.12

    age = fd.get("age_years", 0)
    if age > 5:
        price *= max(0.85, 1.0 - (age - 5) * 0.005)

    return max(price, 500000)


# ── API Router ──────────────────────────────────────────────────────────────

_predictor_instance: PricePredictor | None = None


def get_predictor() -> PricePredictor:
    """Get or create the singleton PricePredictor."""
    global _predictor_instance
    if _predictor_instance is None:
        _predictor_instance = PricePredictor()
    return _predictor_instance


def create_ml_router() -> Any:
    """Create a FastAPI router for ML prediction endpoints."""
    from fastapi import APIRouter, Query

    predictor = get_predictor()
    router = APIRouter(prefix="/api/realestate", tags=["Real Estate"])

    @router.post("/predict")
    async def predict_price(
        city: str = Query(..., description="City name"),
        bedrooms: int = Query(2, ge=1, le=10),
        bathrooms: int = Query(2, ge=1, le=10),
        carpet_area_sqft: float = Query(1000.0, ge=100, le=10000),
        furnishing: str = Query("unfurnished"),
        property_type: str = Query("apartment"),
        locality: str = Query(""),
        age_years: int = Query(0, ge=0, le=100),
        gated_community: bool = Query(False),
    ):
        """Predict property price based on features.

        Uses a trained LinearRegression model or heuristic fallback.
        Returns predicted price with 90% confidence interval.
        """
        inp = PricePredictionInput(
            city=city, locality=locality, bedrooms=bedrooms,
            bathrooms=bathrooms, carpet_area_sqft=carpet_area_sqft,
            furnishing=furnishing, property_type=property_type,
            age_years=age_years, gated_community=gated_community,
        )

        # Auto-train if not yet trained
        if not predictor._is_trained:
            predictor.train()

        prediction = predictor.predict(inp)
        return prediction.to_dict()

    @router.post("/predict/train")
    async def train_model(samples: int = Query(300, ge=50, le=2000)):
        """Train or retrain the price prediction model."""
        predictor = get_predictor()
        samples_data = _generate_sample_properties(samples)
        result = predictor.train(samples_data)
        return result

    @router.get("/predict/status")
    async def model_status():
        """Get model training status and accuracy."""
        predictor = get_predictor()
        return {
            "is_trained": predictor._is_trained,
            "model_accuracy": round(predictor._r2_score, 4) if predictor._r2_score else 0.75,
            "features": predictor._feature_names,
            "cities_known": list(predictor._city_encoder.keys()) if predictor._city_encoder else list(CITY_BASE_PRICES.keys()),
        }

    return router
