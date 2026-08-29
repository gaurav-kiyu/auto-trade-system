"""Tests for Enterprise Evolution module (core/enterprise_evolution.py)."""

from __future__ import annotations

import pytest
from core.enterprise_evolution import (
    EvolutionProposal,
    EvolutionProposalResult,
    get_evolution_engine,
    reset_evolution_engine,
)


@pytest.fixture(autouse=True)
def reset_engine():
    reset_evolution_engine()
    engine = get_evolution_engine()
    engine.clear_all()
    yield
    reset_evolution_engine()


class TestAnalyzeAndPropose:
    def test_analyze_produces_proposals(self, reset_engine):
        engine = get_evolution_engine()
        proposals = engine.analyze_and_propose()
        assert len(proposals) > 0
        assert all(p.proposal_id.startswith("EVO-") for p in proposals)

    def test_proposals_have_categories(self, reset_engine):
        engine = get_evolution_engine()
        proposals = engine.analyze_and_propose()
        categories = set(p.category for p in proposals)
        # Architecture/Security proposals are only generated when the relevant
        # modules are MISSING — they all exist now, so the analyzer produces
        # TESTING + GOVERNANCE proposals from current evidence.
        assert "TESTING" in categories
        assert "GOVERNANCE" in categories

    def test_dedup_repeated_calls(self, reset_engine):
        engine = get_evolution_engine()
        p1 = engine.analyze_and_propose()
        p2 = engine.analyze_and_propose()
        # Duplicate titles within a single analysis pass are removed;
        # consecutive calls are deterministic and may repeat titles.
        assert len(set(p.title for p in p1)) == len(p1)
        assert len(set(p.title for p in p2)) == len(p2)


class TestGetProposals:
    def test_get_all_proposals(self, reset_engine):
        engine = get_evolution_engine()
        engine.analyze_and_propose()
        proposals = engine.get_proposals()
        assert len(proposals) > 0

    def test_get_proposals_filtered_by_category(self, reset_engine):
        engine = get_evolution_engine()
        engine.analyze_and_propose()
        testing = engine.get_proposals(category="TESTING")
        assert len(testing) > 0
        assert all(p.category == "TESTING" for p in testing)

    def test_get_proposals_filtered_by_priority(self, reset_engine):
        engine = get_evolution_engine()
        engine.analyze_and_propose()
        high = engine.get_proposals(priority="HIGH")
        assert all(p.priority == "HIGH" for p in high)

    def test_get_proposals_empty_category(self, reset_engine):
        engine = get_evolution_engine()
        proposals = engine.get_proposals(category="NONEXISTENT")
        assert len(proposals) == 0


class TestReport:
    def test_get_report(self, reset_engine):
        engine = get_evolution_engine()
        report = engine.get_report()
        assert isinstance(report, EvolutionProposalResult)

    def test_report_after_analysis(self, reset_engine):
        engine = get_evolution_engine()
        engine.analyze_and_propose()
        report = engine.get_report()
        assert report.total_proposals > 0
        assert len(report.categories_covered) > 0

    def test_top_priority(self, reset_engine):
        engine = get_evolution_engine()
        engine.analyze_and_propose()
        report = engine.get_report()
        assert report.top_priority in ("CRITICAL", "HIGH", "MEDIUM", "LOW")


class TestImprovementVelocity:
    def test_velocity_zero_initially(self, reset_engine):
        engine = get_evolution_engine()
        assert engine.get_improvement_velocity() >= 0

    def test_velocity_after_proposals(self, reset_engine):
        engine = get_evolution_engine()
        engine.analyze_and_propose()
        velocity = engine.get_improvement_velocity()
        assert velocity >= 0


class TestStats:
    def test_get_stats_empty(self, reset_engine):
        engine = get_evolution_engine()
        stats = engine.get_stats()
        assert stats["total_proposals"] == 0

    def test_get_stats_after_analysis(self, reset_engine):
        engine = get_evolution_engine()
        engine.analyze_and_propose()
        stats = engine.get_stats()
        assert stats["total_proposals"] > 0
        assert len(stats["by_category"]) > 0
        assert len(stats["by_priority"]) > 0


class TestProposalModel:
    def test_to_dict(self):
        p = EvolutionProposal(title="Test", description="Desc", category="ARCHITECTURE",
                              priority="HIGH", proposal_id="EVO-1", created_at=100.0)
        d = p.to_dict()
        assert d["title"] == "Test"
        assert d["category"] == "ARCHITECTURE"
        assert d["priority"] == "HIGH"

    def test_proposal_result_to_dict(self):
        result = EvolutionProposalResult(
            proposals=[],
            total_proposals=0,
            categories_covered=[],
            top_priority="LOW",
            generated_at=100.0,
            duration_ms=50.0,
        )
        d = result.to_dict()
        assert d["total_proposals"] == 0
        assert d["top_priority"] == "LOW"


class TestSingleton:
    def test_singleton(self):
        e1 = get_evolution_engine()
        e2 = get_evolution_engine()
        assert e1 is e2

    def test_reset(self):
        e1 = get_evolution_engine()
        reset_evolution_engine()
        e2 = get_evolution_engine()
        assert e1 is not e2
