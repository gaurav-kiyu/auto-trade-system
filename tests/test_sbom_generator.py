"""Tests for core/sbom_generator.py (Pillar 14: Governance & Compliance)."""

from __future__ import annotations

from core.sbom_generator import (
    PackageInfo,
    SBOMGenerator,
    SBOMReport,
    get_sbom_generator,
    reset_sbom_generator,
)


class TestPackageInfo:
    """Tests for PackageInfo dataclass."""

    def test_default_type_is_third_party(self):
        pkg = PackageInfo(name="requests", version="2.31.0")
        assert pkg.type == "third_party"
        assert pkg.license == "Unknown"

    def test_to_dict_returns_all_fields(self):
        pkg = PackageInfo(
            name="flask",
            version="3.0.0",
            license="BSD",
            source="requirements.txt",
        )
        d = pkg.to_dict()
        assert d["name"] == "flask"
        assert d["version"] == "3.0.0"
        assert d["license"] == "BSD"
        assert d["source"] == "requirements.txt"


class TestSBOMReport:
    """Tests for SBOMReport dataclass."""

    def test_empty_report_defaults(self):
        report = SBOMReport()
        assert report.total_packages == 0
        assert report.python_version == ""

    def test_to_dict_includes_all_fields(self):
        report = SBOMReport(
            packages=[PackageInfo(name="requests", version="2.31.0")],
            total_packages=1,
            third_party_count=1,
            first_party_modules=["core/foo", "core/bar"],
            doc_name="test-bot",
        )
        d = report.to_dict()
        assert d["total_packages"] == 1
        assert d["third_party_count"] == 1
        assert len(d["first_party_modules"]) == 2
        assert d["doc_name"] == "test-bot"

    def test_summary_text_includes_version(self):
        report = SBOMReport(
            packages=[PackageInfo(name="requests", version="2.31.0")],
            total_packages=1,
            third_party_count=1,
            creation_timestamp="2026-01-01",
            python_version="3.11",
            system_info="Linux",
        )
        text = report.summary_text()
        assert "requests==2.31.0" in text
        assert "SOFTWARE BILL OF MATERIALS" in text


class TestSBOMGenerator:
    """Tests for SBOMGenerator."""

    def setup_method(self):
        reset_sbom_generator()

    def test_singleton(self):
        g1 = get_sbom_generator()
        g2 = get_sbom_generator()
        assert g1 is g2

    def test_generate_returns_report(self):
        gen = SBOMGenerator()
        report = gen.generate()
        assert isinstance(report, SBOMReport)
        assert report.creation_timestamp != ""
        assert report.python_version != ""

    def test_generate_finds_first_party_modules(self):
        gen = SBOMGenerator()
        report = gen.generate()
        # Should find modules in core/, index_app/, infrastructure/, scripts/
        assert len(report.first_party_modules) > 0

    def test_generate_finds_requirements(self):
        gen = SBOMGenerator()
        report = gen.generate()
        # Should have at least some packages from requirements files or pip
        assert report.total_packages > 0

    def test_parse_requirements_returns_list(self):
        gen = SBOMGenerator()
        pkgs = gen._parse_requirements()
        assert isinstance(pkgs, list)

    def test_discover_first_party_returns_list(self):
        gen = SBOMGenerator()
        modules = gen._discover_first_party()
        assert isinstance(modules, list)
        assert len(modules) > 0
        # Should find core modules
        core_mods = [m for m in modules if m.startswith("core.")]
        assert len(core_mods) > 0

    def test_get_stats(self):
        gen = SBOMGenerator()
        stats = gen.get_stats()
        assert stats["available"] is True

    def test_generate_is_idempotent(self):
        gen = SBOMGenerator()
        r1 = gen.generate()
        r2 = gen.generate()
        assert r1.total_packages == r2.total_packages


class TestSingleton:
    """Tests for singleton factory."""

    def setup_method(self):
        reset_sbom_generator()

    def test_get_returns_same_instance(self):
        g1 = get_sbom_generator()
        g2 = get_sbom_generator()
        assert g1 is g2

    def test_reset_clears_instance(self):
        g1 = get_sbom_generator()
        reset_sbom_generator()
        g2 = get_sbom_generator()
        assert g1 is not g2
