"""Tests for core.recommendation_engine - trade recommendation generation."""

from __future__ import annotations

from core.recommendation_engine import (
    Recommendation,
    RecommendationEngine,
    RecommendationReport,
    generate_recommendations,
)


class TestRecommendationDataClasses:
    """Tests for Recommendation and RecommendationReport dataclasses."""

    def test_recommendation_defaults(self) -> None:
        rec = Recommendation()
        assert rec.direction == "HOLD"
        assert rec.confidence == 0.0
        assert rec.source == "ANALYTICS"
        assert rec.priority == "NORMAL"

    def test_recommendation_to_dict(self) -> None:
        rec = Recommendation(
            recommendation_id="REC-000001",
            direction="BUY",
            instrument="NIFTY",
            confidence=0.85,
            score=85.0,
            source="FACTOR",
            priority="HIGH",
            tags=["alpha", "buy_signal"],
            rationale="Strong alpha generation",
        )
        d = rec.to_dict()
        assert d["direction"] == "BUY"
        assert d["instrument"] == "NIFTY"
        assert d["confidence"] == 0.85
        assert d["score"] == 85.0
        assert d["priority"] == "HIGH"

    def test_recommendation_summary(self) -> None:
        rec = Recommendation(
            direction="BUY",
            instrument="NIFTY",
            confidence=0.85,
            score=85.0,
            priority="HIGH",
            rationale="Strong alpha",
        )
        summary = rec.summary()
        assert "HIGH" in summary
        assert "BUY" in summary
        assert "NIFTY" in summary
        assert "85.0" in summary

    def test_recommendation_report_empty(self) -> None:
        report = RecommendationReport()
        assert report.total_recommendations == 0
        assert report.high_priority_count == 0
        assert report.avg_confidence == 0.0

    def test_recommendation_report_with_data(self) -> None:
        recs = [
            Recommendation(direction="BUY", priority="HIGH", confidence=0.9, score=90.0, source="FACTOR"),
            Recommendation(direction="SELL", priority="NORMAL", confidence=0.7, score=70.0, source="CROSS_ASSET"),
            Recommendation(direction="HOLD", priority="NORMAL", confidence=0.5, score=50.0, source="LIQUIDITY"),
        ]
        RecommendationReport(
            recommendations=recs,
            total_recommendations=len(recs),
            high_priority_count=1,
            buy_count=1,
            sell_count=1,
            hold_count=1,
            avg_confidence=0.7,
        )


DEMO_ANALYTICS = {
    "instrument": "NIFTY",
    "factor_attribution": {
        "alpha_contribution": 0.008,
        "r_squared": 0.75,
        "loadings": {"market": 1.05, "smb": 0.3, "hml": -0.2},
    },
    "cross_asset": {
        "relative_values": [
            {"asset_a": "NIFTY", "asset_b": "BANKNIFTY", "z_score": 2.5},
        ],
        "flight_to_safety": {
            "is_flight_to_safety": False,
            "strength": "NONE",
        },
    },
    "liquidity": {
        "regime": "LIQUID",
        "composite_score": 88.0,
        "spread_score": 92.0,
        "volume_score": 85.0,
    },
    "risk": {
        "risk_attribution": {
            "total_risk": 0.25,
            "specific_risk": 0.02,
            "explained_risk_pct": 85.0,
        },
        "stress_test": [],
    },
    "signals": [
        {"score": 85, "direction": "CALL", "instrument": "NIFTY", "confidence": 0.85},
    ],
}


class TestRecommendationEngine:
    """Tests for RecommendationEngine - recommendation generation."""

    def setup_method(self) -> None:
        self.engine = RecommendationEngine()

    def test_generate_with_empty_data_returns_hold(self) -> None:
        report = self.engine.generate({})
        assert report.total_recommendations >= 1
        assert report.recommendations[0].direction == "HOLD"
        assert report.recommendations[0].source == "ANALYTICS"

    def test_generate_with_demo_data(self) -> None:
        report = self.engine.generate(DEMO_ANALYTICS)
        assert report.total_recommendations >= 1

    def test_generate_returns_prioritized(self) -> None:
        report = self.engine.generate(DEMO_ANALYTICS)
        # Should sort by priority: CRITICAL > HIGH > NORMAL > LOW
        priority_order = {"CRITICAL": 0, "HIGH": 1, "NORMAL": 2, "LOW": 3}
        for i in range(len(report.recommendations) - 1):
            p1 = priority_order.get(report.recommendations[i].priority, 99)
            p2 = priority_order.get(report.recommendations[i + 1].priority, 99)
            assert p1 <= p2

    def test_factor_recommendation_strong_alpha(self) -> None:
        recs = self.engine._factor_recommendations({
            "factor_attribution": {
                "alpha_contribution": 0.008,
                "r_squared": 0.75,
            },
        })
        assert len(recs) >= 1
        assert recs[0].direction == "BUY"
        assert recs[0].source == "FACTOR"

    def test_factor_recommendation_negative_alpha(self) -> None:
        recs = self.engine._factor_recommendations({
            "factor_attribution": {
                "alpha_contribution": -0.006,
                "r_squared": 0.6,
            },
        })
        assert len(recs) >= 1
        assert recs[0].direction == "REDUCE"
        assert recs[0].source == "FACTOR"

    def test_factor_recommendation_empty_data(self) -> None:
        recs = self.engine._factor_recommendations({})
        assert recs == []

    def test_cross_asset_recommendation_z_score(self) -> None:
        recs = self.engine._cross_asset_recommendations({
            "cross_asset": {
                "relative_values": [
                    {"asset_a": "NIFTY", "asset_b": "BANKNIFTY", "z_score": 2.5},
                ],
            },
        })
        assert len(recs) >= 1
        assert "NIFTY" in recs[0].instrument

    def test_cross_asset_flight_to_safety(self) -> None:
        recs = self.engine._cross_asset_recommendations({
            "cross_asset": {
                "flight_to_safety": {
                    "is_flight_to_safety": True,
                    "strength": "STRONG",
                },
            },
        })
        assert len(recs) >= 1
        assert recs[0].direction == "REDUCE"
        assert recs[0].priority == "HIGH"

    def test_liquidity_illiquid_regime(self) -> None:
        recs = self.engine._liquidity_recommendations({
            "liquidity": {
                "regime": "ILLIQUID",
                "composite_score": 20.0,
            },
        })
        assert len(recs) >= 1
        assert recs[0].direction == "HOLD"

    def test_liquidity_liquid_regime(self) -> None:
        recs = self.engine._liquidity_recommendations({
            "liquidity": {
                "regime": "LIQUID",
                "composite_score": 90.0,
            },
        })
        assert len(recs) >= 1
        assert recs[0].direction == "BUY"

    def test_risk_recommendation_stress_alert(self) -> None:
        recs = self.engine._risk_recommendations({
            "risk": {
                "stress_test": [
                    {"scenario": "FLASH_CRASH", "alert": True, "pct_of_capital": 15.0, "worst_position": "BANKNIFTY"},
                ],
            },
        })
        assert len(recs) >= 1
        assert recs[0].priority == "CRITICAL"
        assert recs[0].direction == "REDUCE"

    def test_score_recommendation_high_score(self) -> None:
        recs = self.engine._score_recommendations({
            "signals": [
                {"score": 85, "direction": "CALL", "instrument": "NIFTY", "confidence": 0.85},
            ],
        })
        assert len(recs) >= 1
        assert recs[0].direction == "BUY"
        assert recs[0].priority == "HIGH"

    def test_score_recommendation_moderate_score(self) -> None:
        recs = self.engine._score_recommendations({
            "signals": [
                {"score": 75, "direction": "PUT", "instrument": "BANKNIFTY", "confidence": 0.7},
            ],
        })
        assert len(recs) >= 1
        assert recs[0].direction == "BUY"
        assert recs[0].priority == "NORMAL"


class TestGenerateRecommendations:
    """Tests for generate_recommendations convenience function."""

    def test_with_empty_data(self) -> None:
        result = generate_recommendations({})
        assert "recommendations" in result
        assert result["total_recommendations"] >= 1

    def test_with_demo_data(self) -> None:
        result = generate_recommendations(DEMO_ANALYTICS)
        assert result["total_recommendations"] >= 1
        assert result["avg_confidence"] > 0


class TestEngineeringRecommendations:
    """Tests for engineering recommendations (new in v2.57)."""

    def setup_method(self) -> None:
        self.engine = RecommendationEngine()
        # Reset ID counter for deterministic tests
        self.engine._recommendation_id_counter = 0

    def test_empty_engineering_data_returns_empty(self) -> None:
        """No engineering data → no engineering recs."""
        recs = self.engine._engineering_recommendations({})
        assert recs == []

    def test_design_smells_high(self) -> None:
        """High design smells should trigger IMPROVE recommendation."""
        recs = self.engine._engineering_recommendations({
            "code_quality": {
                "design_smells": 25,
                "dead_code_count": 10,
                "test_coverage_pct": 80.0,
            },
        })
        assert len(recs) >= 1
        assert recs[0].direction == "IMPROVE"
        assert recs[0].source == "ENGINEERING"
        assert "design smells" in recs[0].rationale.lower()

    def test_low_test_coverage(self) -> None:
        """Low test coverage should trigger HIGH priority recommendation."""
        recs = self.engine._engineering_recommendations({
            "code_quality": {
                "test_coverage_pct": 45.0,
            },
        })
        assert len(recs) >= 1
        assert recs[0].direction == "IMPROVE"
        assert recs[0].priority == "HIGH"
        assert "coverage" in recs[0].rationale.lower()

    def test_dead_code_threshold(self) -> None:
        """High dead code should trigger CLEANUP recommendation."""
        recs = self.engine._engineering_recommendations({
            "code_quality": {
                "dead_code_count": 100,
            },
        })
        assert len(recs) >= 1
        assert recs[0].direction == "CLEANUP"

    def test_architecture_violations(self) -> None:
        """Architecture violations should trigger REFACTOR recommendation."""
        recs = self.engine._engineering_recommendations({
            "architecture": {
                "violations": 8,
                "circular_dependencies": ["mod_a -> mod_b -> mod_a"],
            },
        })
        assert len(recs) >= 1
        assert recs[0].direction == "REFACTOR"
        assert "violations" in recs[0].rationale.lower()

    def test_security_vulnerabilities(self) -> None:
        """Security vulnerabilities should trigger CRITICAL recommendation."""
        recs = self.engine._engineering_recommendations({
            "security": {
                "vulnerabilities": 5,
                "exposed_secrets": 0,
            },
        })
        assert len(recs) >= 1
        assert recs[0].direction == "FIX"
        assert recs[0].priority == "CRITICAL"

    def test_hardcoded_secrets(self) -> None:
        """Hardcoded secrets should trigger CRITICAL REMOVE recommendation."""
        recs = self.engine._engineering_recommendations({
            "security": {
                "vulnerabilities": 0,
                "exposed_secrets": 3,
            },
        })
        assert len(recs) >= 1
        assert recs[0].direction == "REMOVE"
        assert "secrets" in recs[0].rationale.lower()

    def test_constitution_gap_recommendations(self) -> None:
        """Constitution scoring gap should trigger recommendations."""
        recs = self.engine._constitution_recommendations({
            "constitution": {
                "overall_score": 6.5,
                "categories": {
                    "RSK-01": {"name": "Hard Halt", "score": 6.0, "max_score": 9.9},
                },
            },
        })
        assert len(recs) >= 1
        assert recs[0].source == "CONSTITUTION"

    def test_generate_engineering_recommendations_convenience(self) -> None:
        """Test the convenience function for engineering recs."""
        from core.recommendation_engine import generate_engineering_recommendations
        result = generate_engineering_recommendations({
            "code_quality": {
                "design_smells": 30,
                "test_coverage_pct": 45.0,
            },
            "security": {
                "vulnerabilities": 3,
                "exposed_secrets": 1,
            },
        })
        assert result["total_recommendations"] >= 1
        assert "recommendations" in result
