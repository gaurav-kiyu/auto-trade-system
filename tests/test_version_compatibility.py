"""Unit tests for version_compatibility.py."""

from __future__ import annotations

import pytest

from core.version_compatibility import (
    ComponentVersion,
    CompatibilityReport,
    CompatibilityResult,
    VersionCompatibilityMatrix,
    check_version_compatibility,
)


class TestParseVersion:
    """Internal _parse_version helper tests."""

    def test_semver_parses_correctly(self):
        from core.version_compatibility import _parse_version
        assert _parse_version("2.53.0") == (2, 53, 0)
        assert _parse_version("1.0.0") == (1, 0, 0)
        assert _parse_version("v2.53.0") == (2, 53, 0)

    def test_invalid_version_returns_zeros(self):
        from core.version_compatibility import _parse_version
        assert _parse_version("not-a-version") == (0, 0, 0)
        assert _parse_version("") == (0, 0, 0)

    def test_partial_version(self):
        from core.version_compatibility import _parse_version
        assert _parse_version("2") == (2,)
        assert _parse_version("2.53") == (2, 53)


class TestVersionInRange:
    """Internal _version_in_range helper tests."""

    def test_version_in_range(self):
        from core.version_compatibility import _version_in_range
        assert _version_in_range("2.53.0", "2.0.0", "2.99.99") is True
        assert _version_in_range("1.0.0", "1.0.0", "1.0.0") is True

    def test_version_outside_range(self):
        from core.version_compatibility import _version_in_range
        assert _version_in_range("1.0.0", "2.0.0", "2.99.99") is False
        assert _version_in_range("3.0.0", "2.0.0", "2.99.99") is False

    def test_version_at_bounds(self):
        from core.version_compatibility import _version_in_range
        assert _version_in_range("2.0.0", "2.0.0", "2.99.99") is True
        assert _version_in_range("2.99.99", "2.0.0", "2.99.99") is True


class TestComponentVersion:
    """ComponentVersion dataclass tests."""

    def test_basic_creation(self):
        cv = ComponentVersion(
            name="risk_service", version="2.53.0",
            min_compat_version="2.0.0", max_compat_version="2.99.99",
        )
        assert cv.name == "risk_service"
        assert cv.version == "2.53.0"

    def test_with_dependencies(self):
        cv = ComponentVersion(
            name="execution_service", version="2.53.0",
            min_compat_version="2.0.0", max_compat_version="2.99.99",
            dependencies=["broker_adapter"],
        )
        assert "broker_adapter" in cv.dependencies

    def test_to_dict(self):
        cv = ComponentVersion(
            name="test", version="1.0.0",
            min_compat_version="1.0.0", max_compat_version="1.99.99",
            dependencies=["dep1"],
        )
        d = cv.to_dict()
        assert d["name"] == "test"
        assert d["version"] == "1.0.0"
        assert d["dependencies"] == ["dep1"]


class TestCompatibilityResult:
    """CompatibilityResult dataclass tests."""

    def test_compatible_result(self):
        r = CompatibilityResult(
            component_a="a", component_b="b", compatible=True,
            a_version="2.0.0", b_version="2.0.0",
            reason="Compatible",
        )
        assert r.compatible is True
        assert r.reason == "Compatible"

    def test_incompatible_result(self):
        r = CompatibilityResult(
            component_a="a", component_b="b", compatible=False,
            a_version="1.0.0", b_version="3.0.0",
            reason="Version mismatch",
        )
        assert r.compatible is False

    def test_to_dict(self):
        r = CompatibilityResult(
            component_a="a", component_b="b", compatible=True,
            a_version="1.0.0", b_version="1.5.0",
            reason="OK",
        )
        d = r.to_dict()
        assert d["compatible"] is True
        assert d["a_version"] == "1.0.0"


class TestCompatibilityReport:
    """CompatibilityReport dataclass tests."""

    def test_default_all_compatible(self):
        report = CompatibilityReport(system_version="2.53.0")
        assert report.all_compatible is True
        assert report.failures == []

    def test_summary_includes_verdict(self):
        report = CompatibilityReport(system_version="2.53.0")
        text = report.summary()
        assert "ALL COMPATIBLE" in text or "INCOMPATIBILITIES" in text

    def test_failures_appear_in_summary(self):
        report = CompatibilityReport(
            system_version="2.53.0",
            all_compatible=False,
            failures=["component_a v2.0.0 <-> component_b v3.0.0: Version mismatch"],
        )
        text = report.summary()
        assert "INCOMPATIBILITIES DETECTED" in text
        assert "component_a" in text

    def test_to_dict_structure(self):
        report = CompatibilityReport(system_version="2.53.0")
        d = report.to_dict()
        assert d["system_version"] == "2.53.0"
        assert "timestamp" in d
        assert "components" in d
        assert "checks" in d


class TestVersionCompatibilityMatrix:
    """VersionCompatibilityMatrix tests."""

    def test_init_detects_version(self):
        """Matrix initializes and detects system version from VERSION file."""
        vcm = VersionCompatibilityMatrix()
        assert len(vcm._system_version) > 0
        assert vcm._system_version != "0.0.0"

    def test_init_loads_defaults(self):
        vcm = VersionCompatibilityMatrix()
        assert len(vcm._components) > 0
        assert "risk_service" in vcm._components

    def test_default_components_count(self):
        vcm = VersionCompatibilityMatrix()
        assert len(vcm._components) >= 10

    def test_register_component(self):
        vcm = VersionCompatibilityMatrix()
        vcm.register("test_component", "1.0.0", "1.0.0", "1.99.99")
        comp = vcm.get_component("test_component")
        assert comp is not None
        assert comp.version == "1.0.0"

    def test_register_overrides_default(self):
        vcm = VersionCompatibilityMatrix()
        vcm.register("risk_service", "3.0.0", "3.0.0", "3.99.99")
        comp = vcm.get_component("risk_service")
        assert comp.version == "3.0.0"

    def test_check_known_components(self):
        vcm = VersionCompatibilityMatrix()
        result = vcm.check("risk_service", "execution_service")
        assert result is not None
        assert result.compatible is True

    def test_check_unknown_component_returns_incompatible(self):
        vcm = VersionCompatibilityMatrix()
        result = vcm.check("risk_service", "unknown_component")
        assert result.compatible is False
        assert "unknown" in result.reason.lower()

    def test_check_all_returns_report(self):
        vcm = VersionCompatibilityMatrix()
        report = vcm.check_all()
        assert isinstance(report, CompatibilityReport)
        assert len(report.checks) >= 5  # Many dependency pairs checked

    def test_check_all_system_compatibility(self):
        """check_all includes system version checks."""
        vcm = VersionCompatibilityMatrix()
        report = vcm.check_all()
        assert report.all_compatible is True

    def test_check_system_compatibility_known_component(self):
        vcm = VersionCompatibilityMatrix()
        result = vcm.check_system_compatibility("risk_service")
        assert result.compatible is True
        assert result.component_a == "system"

    def test_check_system_compatibility_unknown_component(self):
        vcm = VersionCompatibilityMatrix()
        result = vcm.check_system_compatibility("unknown_component")
        assert result.compatible is False

    def test_list_components(self):
        vcm = VersionCompatibilityMatrix()
        components = vcm.list_components()
        assert len(components) >= 10
        assert "risk_service" in components

    def test_get_component_known(self):
        vcm = VersionCompatibilityMatrix()
        comp = vcm.get_component("risk_service")
        assert comp is not None
        assert comp.name == "risk_service"

    def test_get_component_unknown(self):
        vcm = VersionCompatibilityMatrix()
        comp = vcm.get_component("nonexistent")
        assert comp is None

    def test_register_with_dependencies(self):
        vcm = VersionCompatibilityMatrix()
        vcm.register("new_svc", "1.0.0", "1.0.0", "1.99.99",
                     dependencies=["risk_service", "execution_service"])
        comp = vcm.get_component("new_svc")
        assert len(comp.dependencies) == 2


class TestConvenienceAPI:
    """Convenience API tests."""

    def test_check_version_compatibility(self):
        report = check_version_compatibility()
        assert isinstance(report, CompatibilityReport)
        assert report.all_compatible is True
