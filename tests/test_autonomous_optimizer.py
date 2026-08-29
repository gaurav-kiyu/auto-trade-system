"""Tests for core/autonomous_optimizer.py — Autonomous Optimization Engine."""

from __future__ import annotations

import json

from core.autonomous_optimizer import (
    OPTIMIZATION_DOMAINS,
    OPTIMIZATION_LEVELS,
    OptimizationApplied,
    OptimizationReport,
    OptimizerFinding,
    get_autonomous_optimizer,
    reset_autonomous_optimizer,
)

# ── Data Model Tests ────────────────────────────────────────────────────────


class TestOptimizerFinding:
    def test_defaults(self):
        f = OptimizerFinding(
            domain="SQL_QUERY",
            description="Test finding",
            current_value=100.0,
            expected_value=50.0,
            improvement_pct=50.0,
        )
        assert f.domain == "SQL_QUERY"
        assert f.severity == "MEDIUM"
        assert f.risk_level == "MEDIUM"
        assert f.auto_appliable is False

    def test_to_dict(self):
        f = OptimizerFinding(
            domain="CACHE",
            description="Large cache directory",
            current_value=200.0,
            expected_value=10.0,
            improvement_pct=95.0,
            severity="HIGH",
            risk_level="SAFE",
            auto_appliable=True,
            recommendation="Clean cache",
            module_path="__pycache__",
            metric_name="cache_size_mb",
        )
        d = f.to_dict()
        assert d["domain"] == "CACHE"
        assert d["severity"] == "HIGH"
        assert d["auto_appliable"] is True
        assert d["improvement_pct"] == 95.0

    def test_to_dict_truncates_long_strings(self):
        f = OptimizerFinding(
            domain="SQL_QUERY",
            description="X" * 500,
            current_value=0,
            expected_value=0,
            improvement_pct=0,
            recommendation="Y" * 500,
        )
        d = f.to_dict()
        assert len(d["description"]) <= 200
        assert len(d["recommendation"]) <= 200


class TestOptimizationReport:
    def test_defaults(self):
        r = OptimizationReport(timestamp=100.0)
        assert r.timestamp == 100.0
        assert r.findings == []
        assert r.overall_optimization_score == 10.0

    def test_to_dict(self):
        findings = [
            OptimizerFinding("SQL_QUERY", "Slow query", 100, 50, 50, "HIGH"),
            OptimizerFinding("CACHE", "Large cache", 200, 10, 95, "MEDIUM"),
        ]
        r = OptimizationReport(
            timestamp=200.0,
            duration_sec=5.0,
            findings=findings,
            domains_checked=["SQL_QUERY", "CACHE"],
            overall_optimization_score=7.5,
        )
        d = r.to_dict()
        assert d["duration_sec"] == 5.0
        assert d["findings_count"] == 2
        assert d["overall_optimization_score"] == 7.5

    def test_summary_text(self):
        r = OptimizationReport(
            timestamp=300.0,
            findings=[OptimizerFinding("SQL_QUERY", "Slow", 100, 50, 50, "CRITICAL")],
            overall_optimization_score=6.0,
        )
        text = r.summary_text()
        assert "AUTONOMOUS OPTIMIZATION REPORT" in text
        assert "Critical" in text


class TestOptimizationApplied:
    def test_defaults(self):
        a = OptimizationApplied(
            finding_index=0,
            domain="CACHE",
            description="Cleaned cache",
            applied_at=100.0,
            approved_by="auto",
            baseline_value=200.0,
            current_value=10.0,
            improvement_measured=95.0,
        )
        assert a.domain == "CACHE"
        assert a.rolled_back is False
        assert a.improvement_measured == 95.0

    def test_to_dict(self):
        a = OptimizationApplied(
            finding_index=1,
            domain="SQL_QUERY",
            description="Added index",
            applied_at=200.0,
            approved_by="admin",
            baseline_value=500.0,
            current_value=50.0,
            improvement_measured=90.0,
        )
        d = a.to_dict()
        assert d["improvement_measured"] == 90.0
        assert d["approved_by"] == "admin"


# ── Constants Tests ─────────────────────────────────────────────────────────


class TestConstants:
    def test_optimization_domains(self):
        assert "SQL_QUERY" in OPTIMIZATION_DOMAINS
        assert "CACHE" in OPTIMIZATION_DOMAINS
        assert "API_PERFORMANCE" in OPTIMIZATION_DOMAINS
        assert "CONFIG" in OPTIMIZATION_DOMAINS
        assert len(OPTIMIZATION_DOMAINS) == 8

    def test_optimization_levels(self):
        assert OPTIMIZATION_LEVELS == ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]


# ── AutonomousOptimizer Tests ──────────────────────────────────────────────


class TestAutonomousOptimizerInit:
    def test_init(self):
        reset_autonomous_optimizer()
        optimizer = get_autonomous_optimizer()
        assert optimizer is not None
        assert optimizer._history == []

    def test_singleton(self):
        reset_autonomous_optimizer()
        o1 = get_autonomous_optimizer()
        o2 = get_autonomous_optimizer()
        assert o1 is o2

    def test_reset(self):
        reset_autonomous_optimizer()
        o1 = get_autonomous_optimizer()
        reset_autonomous_optimizer()
        o2 = get_autonomous_optimizer()
        assert o1 is not o2


class TestAutonomousOptimizerCycle:
    def test_run_optimization_cycle_produces_report(self):
        reset_autonomous_optimizer()
        optimizer = get_autonomous_optimizer()
        report = optimizer.run_optimization_cycle(auto_apply_safe=True)
        assert isinstance(report, OptimizationReport)
        assert report.timestamp > 0
        assert report.domains_checked is not None

    def test_cycle_includes_domains_checked(self):
        reset_autonomous_optimizer()
        optimizer = get_autonomous_optimizer()
        report = optimizer.run_optimization_cycle()
        assert len(report.domains_checked) >= 2

    def test_history_recorded(self):
        reset_autonomous_optimizer()
        optimizer = get_autonomous_optimizer()
        optimizer.run_optimization_cycle()
        history = optimizer.get_history()
        assert len(history) == 1

    def test_multiple_cycles(self):
        reset_autonomous_optimizer()
        optimizer = get_autonomous_optimizer()
        optimizer.run_optimization_cycle()
        optimizer.run_optimization_cycle()
        assert len(optimizer.get_history()) == 2

    def test_auto_apply_creates_applied_records(self):
        reset_autonomous_optimizer()
        optimizer = get_autonomous_optimizer()
        report = optimizer.run_optimization_cycle(auto_apply_safe=True)
        # auto_apply may or may not produce applied records depending on findings
        assert isinstance(report.auto_applied, list)

    def test_get_applied_history(self):
        reset_autonomous_optimizer()
        optimizer = get_autonomous_optimizer()
        optimizer.run_optimization_cycle()
        applied = optimizer.get_applied_history()
        assert isinstance(applied, list)


class TestAutonomousOptimizerStats:
    def test_empty_stats(self):
        reset_autonomous_optimizer()
        optimizer = get_autonomous_optimizer()
        stats = optimizer.get_stats()
        assert stats["total_cycles"] == 0

    def test_stats_after_cycle(self):
        reset_autonomous_optimizer()
        optimizer = get_autonomous_optimizer()
        optimizer.run_optimization_cycle()
        stats = optimizer.get_stats()
        assert stats["total_cycles"] >= 1
        assert "total_findings" in stats
        assert "avg_optimization_score" in stats

    def test_stats_latest_score(self):
        reset_autonomous_optimizer()
        optimizer = get_autonomous_optimizer()
        optimizer.run_optimization_cycle()
        stats = optimizer.get_stats()
        assert stats["latest_score"] >= 0


class TestAutonomousOptimizerClearHistory:
    def test_clear_history(self):
        reset_autonomous_optimizer()
        optimizer = get_autonomous_optimizer()
        optimizer.run_optimization_cycle()
        assert len(optimizer.get_history()) >= 1
        optimizer.clear_history()
        assert len(optimizer.get_history()) == 0

    def test_clear_history_removes_file(self, tmp_path):
        reset_autonomous_optimizer()
        optimizer = get_autonomous_optimizer()
        optimizer._persist_path = tmp_path / "opt_test.json"
        optimizer.run_optimization_cycle()
        assert optimizer._persist_path.exists()
        optimizer.clear_history()
        assert not optimizer._persist_path.exists()


class TestAutonomousOptimizerPersistence:
    def test_persist_creates_file(self, tmp_path):
        reset_autonomous_optimizer()
        optimizer = get_autonomous_optimizer()
        optimizer._persist_path = tmp_path / "opt_persist.json"
        optimizer.run_optimization_cycle()
        assert optimizer._persist_path.exists()
        data = json.loads(optimizer._persist_path.read_text(encoding="utf-8"))
        assert "reports" in data

    def test_persisted_content(self, tmp_path):
        reset_autonomous_optimizer()
        optimizer = get_autonomous_optimizer()
        optimizer._persist_path = tmp_path / "opt_content.json"
        optimizer.run_optimization_cycle()
        data = json.loads(optimizer._persist_path.read_text(encoding="utf-8"))
        assert len(data["reports"]) >= 1
        assert len(data["applied"]) >= 0
