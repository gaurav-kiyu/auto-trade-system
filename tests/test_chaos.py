"""Tests for the Chaos Engineering Framework (core/chaos/)."""

from __future__ import annotations

import json

from core.chaos import ChaosEngine, ChaosReport, ChaosScenario, FailureType


class TestChaosScenario:
    def test_create_scenario(self):
        s = ChaosScenario(name="test", failure_type="broker_outage", duration_seconds=10.0)
        assert s.name == "test"
        assert s.failure_type == FailureType.BROKER_OUTAGE
        assert s.duration_seconds == 10.0

    def test_string_failure_type(self):
        s = ChaosScenario(name="test", failure_type="api_outage")
        assert s.failure_type == FailureType.API_OUTAGE

    def test_default_params(self):
        s = ChaosScenario(name="test", failure_type="db_outage")
        assert s.params == {}
        assert s.target_service == "all"

    def test_custom_params(self):
        s = ChaosScenario(
            name="test",
            failure_type="network_loss",
            params={"latency_ms": 5000},
            target_service="broker",
        )
        assert s.params == {"latency_ms": 5000}
        assert s.target_service == "broker"


class TestChaosReport:
    def test_create_report(self):
        r = ChaosReport(passed=True, scenario_name="test", verdict="OK")
        assert r.passed is True
        assert r.scenario_name == "test"
        assert r.verdict == "OK"

    def test_summary_format(self):
        r = ChaosReport(
            passed=True, scenario_name="test_1", failure_type="broker_outage",
            verdict="PASSED",
        )
        summary = r.summary()
        assert "CHAOS SCENARIO" in summary
        assert "PASSED" in summary

    def test_failed_summary(self):
        r = ChaosReport(
            passed=False, scenario_name="test_fail", failure_type="db_outage",
            capital_preserved=False, fail_closed_verified=False,
            verdict="FAILED",
        )
        summary = r.summary()
        assert "FAILED" in summary
        assert "❌" in summary

    def test_to_dict(self):
        r = ChaosReport(
            passed=True, scenario_name="test", failure_type="broker_outage",
            verdict="OK", duration_seconds=5.0,
        )
        d = r.to_dict()
        assert d["scenario"] == "test"
        assert d["passed"] is True
        assert d["duration_seconds"] == 5.0
        json.dumps(d)  # Ensure serializable


class TestFailureType:
    def test_values(self):
        assert FailureType.API_OUTAGE.value == "api_outage"
        assert FailureType.DB_OUTAGE.value == "db_outage"
        assert FailureType.BROKER_OUTAGE.value == "broker_outage"
        assert FailureType.STALE_DATA.value == "stale_data"

    def test_all_str_types(self):
        for ft in FailureType:
            assert isinstance(ft.value, str)
            assert len(ft.value) > 0


class TestChaosEngine:
    def test_init(self):
        engine = ChaosEngine()
        assert engine is not None

    def test_register_service(self):
        engine = ChaosEngine()
        svc = engine.register_service("test_service")
        assert svc.name == "test_service"
        assert svc.is_healthy() is True

    def test_get_service(self):
        engine = ChaosEngine()
        engine.register_service("broker")
        svc = engine.get_service("broker")
        assert svc is not None
        assert svc.name == "broker"

    def test_get_nonexistent_service(self):
        engine = ChaosEngine()
        svc = engine.get_service("nonexistent")
        assert svc is None

    def test_run_basic_scenario(self):
        engine = ChaosEngine()
        engine.register_service("broker")
        engine.register_service("db")

        scenario = ChaosScenario(
            name="test_basic",
            failure_type="broker_outage",
            duration_seconds=0.1,
        )
        report = engine.run(scenario)
        assert report.scenario_name == "test_basic"
        assert report.failure_type == "broker_outage"
        assert report.duration_seconds > 0
        assert len(report.observations) > 0

    def test_run_suite(self):
        engine = ChaosEngine()
        engine.register_service("broker")
        engine.register_service("db")

        scenarios = [
            ChaosScenario("s1", "broker_outage", duration_seconds=0.1),
            ChaosScenario("s2", "db_outage", duration_seconds=0.1),
        ]
        reports = engine.run_suite(scenarios)
        assert len(reports) == 2
        assert all(isinstance(r, ChaosReport) for r in reports)

    def test_service_injection_and_heal(self):
        engine = ChaosEngine()
        svc = engine.register_service("app")

        assert svc.is_healthy() is True
        assert svc.has_failure is False

        engine.run(ChaosScenario("test", "api_outage", duration_seconds=0.1))

        # After run, service should be healed
        assert svc.is_healthy() is True
        assert svc.has_failure is False

    def test_multiple_targets(self):
        engine = ChaosEngine()
        svc1 = engine.register_service("broker")
        svc2 = engine.register_service("db")
        svc3 = engine.register_service("cache")

        # Run scenario targeting "all"
        engine.run(ChaosScenario("test", "network_loss", duration_seconds=0.1))

        # All services should be healed after run
        assert svc1.is_healthy()
        assert svc2.is_healthy()
        assert svc3.is_healthy()

    def test_run_chaos_suite(self):
        from core.chaos import run_chaos_suite
        reports = run_chaos_suite()
        assert len(reports) == 3  # 3 standard scenarios
        assert all(isinstance(r, ChaosReport) for r in reports)
