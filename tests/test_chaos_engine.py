"""Tests for core/chaos_engine.py (Phase 21: Chaos & Black Swan Testing)."""

from __future__ import annotations

from core.chaos_engine import (
    BlackSwanScenario,
    BrokerOutageScenario,
    ChaosReport,
    ChaosResult,
    ChaosScenario,
    DatabaseFailureScenario,
    ExchangeOutageScenario,
    FlashCrashScenario,
    RestartStormScenario,
    ScenarioVerdict,
    get_chaos_engine,
    reset_chaos_engine,
)


class TestScenarioVerdict:
    """Tests for ScenarioVerdict constants."""

    def test_constants_defined(self):
        assert ScenarioVerdict.PASS == "PASS"
        assert ScenarioVerdict.FAIL == "FAIL"
        assert ScenarioVerdict.WARN == "WARN"
        assert ScenarioVerdict.ERROR == "ERROR"
        assert ScenarioVerdict.SKIPPED == "SKIPPED"


class TestChaosResult:
    """Tests for ChaosResult dataclass."""

    def test_default_verdict_is_pass(self):
        r = ChaosResult(scenario="test")
        assert r.verdict == ScenarioVerdict.PASS
        assert r.duration_ms == 0.0

    def test_to_dict_returns_all_fields(self):
        r = ChaosResult(
            scenario="broker_test",
            verdict=ScenarioVerdict.FAIL,
            duration_ms=12.34,
            checks_passed=1,
            checks_failed=2,
            checks_total=3,
            details=["check1 failed"],
            error="Timeout",
        )
        d = r.to_dict()
        assert d["scenario"] == "broker_test"
        assert d["verdict"] == "FAIL"
        assert d["duration_ms"] == 12.3
        assert d["checks_failed"] == 2


class TestChaosReport:
    """Tests for ChaosReport dataclass."""

    def test_empty_report_defaults(self):
        report = ChaosReport()
        assert report.total_scenarios == 0
        assert report.pass_rate == 100.0

    def test_summary_text_includes_pass_rate(self):
        report = ChaosReport(
            total_scenarios=6,
            passed=5,
            failed=1,
            pass_rate=83.3,
        )
        text = report.summary_text()
        assert "83.3%" in text
        assert "5/6" in text

    def test_to_dict_includes_all_fields(self):
        report = ChaosReport(
            results=[ChaosResult(scenario="s1")],
            total_scenarios=1,
            passed=1,
        )
        d = report.to_dict()
        assert d["total_scenarios"] == 1
        assert len(d["results"]) == 1


class TestChaosScenario:
    """Tests for ChaosScenario base class."""

    def test_check_records_results(self):
        scenario = ChaosScenario("test_scenario")
        scenario.check("check1", True)
        scenario.check("check2", False)
        assert len(scenario._checks) == 2
        assert scenario._checks[0] == ("check1", True)
        assert scenario._checks[1] == ("check2", False)

    def test_run_reports_passed_and_failed(self):
        scenario = ChaosScenario("test_run")
        scenario.check("pass", True)
        scenario.check("fail", False)
        result = scenario.run()
        assert result.scenario == "test_run"
        assert result.checks_passed == 1
        assert result.checks_failed == 1
        assert result.checks_total == 2
        assert result.verdict in (ScenarioVerdict.PASS, ScenarioVerdict.FAIL, ScenarioVerdict.WARN)

    def test_run_all_pass(self):
        scenario = ChaosScenario("all_pass")
        scenario.check("p1", True)
        scenario.check("p2", True)
        result = scenario.run()
        assert result.verdict == ScenarioVerdict.PASS

    def test_run_handles_exception(self):
        class BrokenScenario(ChaosScenario):
            def _execute(self):
                raise RuntimeError("simulated failure")

        scenario = BrokenScenario("broken")
        result = scenario.run()
        assert result.verdict == ScenarioVerdict.ERROR
        assert "simulated failure" in result.error


class TestConcreteScenarios:
    """Tests for concrete chaos scenarios."""

    def test_broker_outage_runs_without_crash(self):
        scenario = BrokerOutageScenario()
        result = scenario.run()
        assert result.scenario == "broker_outage"
        assert result.checks_total >= 3
        assert result.verdict in (ScenarioVerdict.PASS, ScenarioVerdict.WARN, ScenarioVerdict.FAIL)

    def test_exchange_outage_runs_without_crash(self):
        scenario = ExchangeOutageScenario()
        result = scenario.run()
        assert result.scenario == "exchange_outage"
        assert result.checks_total >= 2

    def test_database_failure_runs_without_crash(self):
        scenario = DatabaseFailureScenario()
        result = scenario.run()
        assert result.scenario == "database_failure"
        assert result.checks_total >= 2

    def test_flash_crash_runs_without_crash(self):
        scenario = FlashCrashScenario()
        result = scenario.run()
        assert result.scenario == "flash_crash"
        assert result.checks_total >= 2

    def test_restart_storm_runs_without_crash(self):
        scenario = RestartStormScenario()
        result = scenario.run()
        assert result.scenario == "restart_storm"
        assert result.checks_total >= 2

    def test_black_swan_runs_without_crash(self):
        scenario = BlackSwanScenario()
        result = scenario.run()
        assert result.scenario == "black_swan"
        assert result.checks_total >= 3


class TestChaosEngine:
    """Tests for ChaosEngine."""

    def setup_method(self):
        reset_chaos_engine()

    def test_singleton(self):
        e1 = get_chaos_engine()
        e2 = get_chaos_engine()
        assert e1 is e2

    def test_get_available_scenarios(self):
        engine = get_chaos_engine()
        scenarios = engine.get_available_scenarios()
        assert len(scenarios) >= 5
        assert "broker_outage" in scenarios
        assert "flash_crash" in scenarios
        assert "black_swan" in scenarios

    def test_run_scenario_by_name(self):
        engine = get_chaos_engine()
        result = engine.run_scenario("broker_outage")
        assert result is not None
        assert result.scenario == "broker_outage"

    def test_run_scenario_unknown_returns_none(self):
        engine = get_chaos_engine()
        result = engine.run_scenario("nonexistent_scenario_xyz")
        assert result is None

    def test_run_all_scenarios_returns_report(self):
        engine = get_chaos_engine()
        report = engine.run_all_scenarios()
        assert isinstance(report, ChaosReport)
        assert report.total_scenarios >= 5
        assert report.pass_rate >= 0.0

    def test_register_custom_scenario(self):
        engine = get_chaos_engine()
        engine.register_scenario("custom_test", ChaosScenario)
        assert "custom_test" in engine.get_available_scenarios()

    def test_get_last_report_none_when_not_run(self):
        reset_chaos_engine()
        engine = get_chaos_engine()
        assert engine.get_last_report() is None

    def test_get_last_report_after_run(self):
        engine = get_chaos_engine()
        engine.run_all_scenarios()
        assert engine.get_last_report() is not None

    def test_get_stats(self):
        engine = get_chaos_engine()
        stats = engine.get_stats()
        assert "available_scenarios" in stats
        assert stats["available_scenarios"] >= 5


class TestSingleton:
    """Tests for singleton factory."""

    def setup_method(self):
        reset_chaos_engine()

    def test_get_returns_same_instance(self):
        e1 = get_chaos_engine()
        e2 = get_chaos_engine()
        assert e1 is e2

    def test_reset_clears_instance(self):
        e1 = get_chaos_engine()
        reset_chaos_engine()
        e2 = get_chaos_engine()
        assert e1 is not e2
