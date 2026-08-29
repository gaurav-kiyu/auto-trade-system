"""Regression tests for deterministic real-estate ML price prediction.

Covers the flaky-training bug where ``/predict`` auto-trained a fresh unseeded
random model per process — CI observed a negative prediction (-959194) that
flaked ``tests/e2e/test_realestate_flows.py::TestMlPredictionFlow``.

Two guards were added:
1. Training draws from a dedicated fixed-seed RNG (``_TRAIN_RNG``) so every cold
   start trains the identical model, without touching the process-global RNG.
2. ``predict()`` clamps nonsensical ML extrapolation (<= 0 or below the
   minimum) back to the heuristic formula.
"""

from realestate.ml_prediction import PricePredictionInput, PricePredictor

MIN_PRICE = 500000


def _mumbai_2bhk() -> PricePredictionInput:
    return PricePredictionInput(
        city="mumbai",
        bedrooms=2,
        bathrooms=2,
        carpet_area_sqft=800,
        furnishing="furnished",
        property_type="apartment",
    )


def test_training_is_deterministic_across_instances():
    p1, p2 = PricePredictor(), PricePredictor()
    p1.train()
    p2.train()
    r1 = p1.predict(_mumbai_2bhk())
    r2 = p2.predict(_mumbai_2bhk())
    assert r1.predicted_price == r2.predicted_price
    assert r1.min_price == r2.min_price
    assert r1.max_price == r2.max_price


def test_predictions_never_below_minimum_price():
    p = PricePredictor()
    p.train()
    for city in ("mumbai", "delhi", "pune", "chennai", "kolkata", "nowhere"):
        result = p.predict(
            PricePredictionInput(
                city=city,
                bedrooms=2,
                bathrooms=2,
                carpet_area_sqft=800,
                furnishing="furnished",
                property_type="apartment",
            )
        )
        assert result.predicted_price >= MIN_PRICE, (city, result.predicted_price)
        assert result.min_price <= result.predicted_price <= result.max_price
        assert result.price_per_sqft > 0


def test_heuristic_fallback_stays_sane():
    """Heuristic path (no sklearn) must also respect the minimum price."""
    from realestate.ml_prediction import _heuristic_price

    price = _heuristic_price(
        {
            "city": "mumbai",
            "carpet_area_sqft": 800,
            "total_area_sqft": 900,
            "furnishing": "furnished",
            "property_type": "apartment",
            "bedrooms": 2,
            "gated_community": 0,
            "age_years": 0,
        }
    )
    assert price >= MIN_PRICE
