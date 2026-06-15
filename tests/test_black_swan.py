"""Tests for the Black Swan Testing Framework (core/black_swan/)."""

from __future__ import annotations

import json



from core.black_swan import (
    BlackSwanEngine,
    BlackSwanReport,
    BlackSwanType,
    SCENARIO_DEFINITIONS,
    run_black_swan_suite,
    run_critical_suite,
)


class TestBlackSwanType:
    def test_values(self):
        assert BlackSwanType.FLASH_CRASH.value == "flash_crash"
        assert BlackSwanType.GAP_UP.value == "gap_up"
        assert BlackSwanType.CIRCUIT_BREAKER.value == "circuit_breaker"
        assert BlackSwanType.VIX_SPIKE.value == "vix_spike"
        assert BlackSwanType.EXPIRY_CRUSH.value == "expiry_crush"

    def test_all_definitions_have_corresponding_enum(self):
        """Every scenario definition should have a matching enum."""
        for name in SCENARIO_DEFINITIONS:
            assert name in [t.value for t in BlackSwanType], f"Missing enum: {name}"


class TestBlackSwanEngine:
    def test_init(self):
        engine = BlackSwanEngine()
        assert engine is not None

    def test_list_scenarios(self):
        engine = BlackSwanEngine()
        scenarios = engine.list_scenarios()
        assert len(scenarios) == 8  # 8 predefined scenarios
        assert "flash_crash" in scenarios
        assert "gap_up" in scenarios
        assert "circuit_breaker" in scenarios

    def test_get_scenario_def(self):
        engine = BlackSwanEngine()
        defn = engine.get_scenario_def("flash_crash")
        assert defn is not None
        assert defn["name"] == "Flash Crash"
        assert defn["index"] == "NIFTY"
        assert defn["critical"] is True

    def test_get_nonexistent_scenario(self):
        engine = BlackSwanEngine()
        defn = engine.get_scenario_def("nonexistent")
        assert defn is None

    def test_run_flash_crash(self):
        engine = BlackSwanEngine()
        report = engine.run("flash_crash")
        assert report.passed is True
        assert report.scenario_name == "Flash Crash"
        assert report.index == "NIFTY"
        assert "FLASH_CRASH" or "Flash Crash" in report.scenario_name or report.verdict

    def test_run_gap_up(self):
        engine = BlackSwanEngine()
        report = engine.run("gap_up")
        assert report.passed is True
        assert report.index == "BANKNIFTY"

    def test_run_gap_down(self):
        engine = BlackSwanEngine()
        report = engine.run("gap_down")
        assert report.passed is True
        assert report.index == "FINNIFTY"

    def test_run_circuit_breaker(self):
        engine = BlackSwanEngine()
        report = engine.run("circuit_breaker")
        assert report.passed is True

    def test_run_unknown_scenario(self):
        engine = BlackSwanEngine()
        report = engine.run("unknown_scenario")
        assert report.passed is False
        assert "Unknown scenario" in report.verdict

    def test_run_critical_suite(self):
        reports = run_critical_suite()
        assert len(reports) > 0
        # All critical scenarios should pass
        for r in reports:
            assert r.passed is True, f"Failed: {r.scenario_name}"

    def test_run_full_suite(self):
        reports = run_black_swan_suite()
        assert len(reports) == 8  # All 8 scenarios
        for r in reports:
            assert r is not None
            assert isinstance(r, BlackSwanReport)


class TestBlackSwanReport:
    def test_create_report(self):
        r = BlackSwanReport(passed=True, scenario_name="test", verdict="OK")
        assert r.passed is True
        assert r.scenario_name == "test"

    def test_summary_format(self):
        r = BlackSwanReport(
            passed=True, scenario_name="Flash Crash", index="NIFTY",
            verdict="PASSED",
        )
        summary = r.summary()
        assert "BLACK SWAN" in summary
        assert "Flash Crash" in summary
        assert "PASSED" in summary

    def test_to_dict(self):
        r = BlackSwanReport(
            passed=True, scenario_name="test", index="NIFTY",
            verdict="OK", simulated_drawdown_pct=8.0,
            expected_max_drawdown_pct=10.0,
        )
        d = r.to_dict()
        assert d["scenario"] == "test"
        assert d["passed"] is True
        assert d["simulated_drawdown_pct"] == 8.0
        json.dumps(d)  # Ensure JSON-serializable

    def test_str_representation(self):
        r = BlackSwanReport(passed=True, scenario_name="test", verdict="OK")
        s = str(r)
        assert isinstance(s, str)
        assert len(s) > 0


class TestScenarioDefinitions:
    def test_all_critical_scenarios_have_expected_fields(self):
        """Critical scenarios must have all required fields."""
        required_fields = ["name", "description", "index", "expected_max_drawdown_pct", "critical"]
        for name, defn in SCENARIO_DEFINITIONS.items():
            if defn.get("critical"):
                for field in required_fields:
                    assert field in defn, f"Missing field '{field}' in {name}"

    def test_all_scenarios_have_valid_index(self):
        valid_indices = {"NIFTY", "BANKNIFTY", "FINNIFTY"}
        for name, defn in SCENARIO_DEFINITIONS.items():
            assert defn["index"] in valid_indices, f"Invalid index in {name}: {defn['index']}"

    def test_drawdown_limits_reasonable(self):
        """Drawdown limits should be between 1% and 20%."""
        for name, defn in SCENARIO_DEFINITIONS.items():
            dd = defn["expected_max_drawdown_pct"]
            assert 1.0 <= dd <= 20.0, f"Unreasonable drawdown in {name}: {dd}%"
