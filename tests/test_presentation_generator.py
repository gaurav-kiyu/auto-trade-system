"""Tests for core.presentation_generator — PPTX generation with multi-template support.

Covers:
- PresentationConfig dataclass and factory
- PresentationGenerator construction and disabled mode
- Template generation (executive, developer, client) with mock data
- generate_all() for all templates
- Singleton factory (get_presentation_generator / reset_presentation_generator)
- Error handling (missing python-pptx, invalid template, template build errors)
- Edge cases (empty data, missing keys, default fallbacks)
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from core.presentation_generator import (
    PresentationConfig,
    PresentationGenerator,
    get_presentation_generator,
    presentation_config_from_cfg,
    reset_presentation_generator,
)

# ── PresentationConfig ──────────────────────────────────────────────────


class TestPresentationConfig:
    def test_defaults(self) -> None:
        cfg = PresentationConfig()
        assert cfg.enabled is True
        assert cfg.output_dir == "reports/presentations"
        assert cfg.default_template == "executive"
        assert cfg.auto_save is True

    def test_custom_values(self) -> None:
        cfg = PresentationConfig(
            enabled=False,
            output_dir="/tmp/pres",
            default_template="developer",
            auto_save=False,
        )
        assert cfg.enabled is False
        assert cfg.output_dir == "/tmp/pres"
        assert cfg.default_template == "developer"

    def test_presentation_config_from_cfg_empty(self) -> None:
        cfg = presentation_config_from_cfg({})
        assert cfg.enabled is True
        assert cfg.output_dir == "reports/presentations"

    def test_presentation_config_from_cfg_override(self) -> None:
        cfg = presentation_config_from_cfg({
            "PRESENTATION_GENERATOR_ENABLED": False,
            "PRESENTATION_GENERATOR_OUTPUT_DIR": "/custom/path",
        })
        assert cfg.enabled is False
        assert cfg.output_dir == "/custom/path"

    def test_presentation_config_from_cfg_partial(self) -> None:
        cfg = presentation_config_from_cfg({"PRESENTATION_GENERATOR_ENABLED": False})
        assert cfg.enabled is False
        assert cfg.output_dir == "reports/presentations"  # default preserved


# ── PresentationGenerator Construction ──────────────────────────────────


class TestPresentationGeneratorConstruction:
    def test_available_templates(self) -> None:
        gen = PresentationGenerator(PresentationConfig())
        templates = gen.available_templates()
        assert "executive" in templates
        assert "developer" in templates
        assert "client" in templates
        assert len(templates) == 3

    def test_disabled_return_empty_string(self) -> None:
        gen = PresentationGenerator(PresentationConfig(enabled=False))
        with patch("core.presentation_generator._HAS_PPTX", True):
            result = gen.generate("executive", {"version": "test"})
            assert result == ""

    def test_log_fn_called(self) -> None:
        msgs: list[str] = []
        gen = PresentationGenerator(PresentationConfig(enabled=False), log_fn=lambda msg: msgs.append(msg))
        gen.generate("executive")
        assert any("disabled" in m for m in msgs)


# ── Template Generation ─────────────────────────────────────────────────


def _mock_pptx_module() -> MagicMock:
    """Mock the python-pptx module for template tests that don't need real PPTX."""
    mock_prs = MagicMock()
    mock_prs.slide_layouts = [MagicMock()]
    mock_slide = MagicMock()
    mock_slide.background = MagicMock()
    mock_prs.slides.add_slide.return_value = mock_slide
    return mock_prs


class TestTemplateExecutive:
    def test_generate_executive_not_disabled_auto_save(self, tmp_path: Path) -> None:
        """Executive template with auto_save writes a file."""
        gen = PresentationGenerator(
            PresentationConfig(enabled=True, output_dir=str(tmp_path), auto_save=True),
        )
        with patch("core.presentation_generator._HAS_PPTX", True):
            with patch("core.presentation_generator.Presentation") as mock_pptx_cls:
                mock_prs = mock_pptx_cls.return_value
                mock_slide = MagicMock()
                mock_slide.background = MagicMock()
                mock_prs.slides.add_slide.return_value = mock_slide

                result = gen.generate("executive", {"version": "2.56.0"})
                assert ".pptx" in result
                assert "executive" in result.lower()

    def test_executive_structure(self) -> None:
        """Executive template uses _build_executive builder function."""
        from core.presentation_generator import _TEMPLATE_BUILDERS
        assert "executive" in _TEMPLATE_BUILDERS
        assert callable(_TEMPLATE_BUILDERS["executive"])


class TestTemplateDeveloper:
    def test_generate_developer_auto_save(self, tmp_path: Path) -> None:
        gen = PresentationGenerator(
            PresentationConfig(enabled=True, output_dir=str(tmp_path), auto_save=True),
        )
        with patch("core.presentation_generator._HAS_PPTX", True):
            with patch("core.presentation_generator.Presentation") as mock_pptx_cls:
                mock_prs = mock_pptx_cls.return_value
                mock_slide = MagicMock()
                mock_slide.background = MagicMock()
                mock_prs.slides.add_slide.return_value = mock_slide

                result = gen.generate("developer", {"version": "2.56.0"})
                assert ".pptx" in result
                assert "developer" in result.lower()

    def test_developer_structure(self) -> None:
        from core.presentation_generator import _TEMPLATE_BUILDERS
        assert "developer" in _TEMPLATE_BUILDERS
        assert callable(_TEMPLATE_BUILDERS["developer"])


class TestTemplateClient:
    def test_generate_client_auto_save(self, tmp_path: Path) -> None:
        gen = PresentationGenerator(
            PresentationConfig(enabled=True, output_dir=str(tmp_path), auto_save=True),
        )
        with patch("core.presentation_generator._HAS_PPTX", True):
            with patch("core.presentation_generator.Presentation") as mock_pptx_cls:
                mock_prs = mock_pptx_cls.return_value
                mock_slide = MagicMock()
                mock_slide.background = MagicMock()
                mock_prs.slides.add_slide.return_value = mock_slide

                result = gen.generate("client", {"version": "2.56.0"})
                assert ".pptx" in result
                assert "client" in result.lower()

    def test_client_structure(self) -> None:
        from core.presentation_generator import _TEMPLATE_BUILDERS
        assert "client" in _TEMPLATE_BUILDERS
        assert callable(_TEMPLATE_BUILDERS["client"])


class TestGenerateAll:
    def test_generate_all_produces_all_templates(self, tmp_path: Path) -> None:
        gen = PresentationGenerator(
            PresentationConfig(enabled=True, output_dir=str(tmp_path), auto_save=True),
        )
        with patch("core.presentation_generator._HAS_PPTX", True):
            with patch("core.presentation_generator.Presentation") as mock_pptx_cls:
                mock_prs = mock_pptx_cls.return_value
                mock_slide = MagicMock()
                mock_slide.background = MagicMock()
                mock_prs.slides.add_slide.return_value = mock_slide

                results = gen.generate_all({"version": "2.56.0"})
                assert "executive" in results
                assert "developer" in results
                assert "client" in results
                for tpl, path in results.items():
                    assert ".pptx" in path, f"{tpl} expected .pptx in {path}"
                    assert tpl in path.lower(), f"{tpl} expected in filename"


# ── Error Handling ──────────────────────────────────────────────────────


class TestErrorHandling:
    def test_no_pptx_raises_import_error(self) -> None:
        gen = PresentationGenerator(PresentationConfig(enabled=True))
        with patch("core.presentation_generator._HAS_PPTX", False):
            with pytest.raises(ImportError):
                gen.generate("executive")

    def test_invalid_template_falls_back_to_default(self) -> None:
        gen = PresentationGenerator(PresentationConfig(enabled=True, default_template="executive"))
        with patch("core.presentation_generator._HAS_PPTX", True):
            with patch("core.presentation_generator.Presentation") as mock_pptx_cls:
                mock_prs = mock_pptx_cls.return_value
                mock_slide = MagicMock()
                mock_slide.background = MagicMock()
                mock_prs.slides.add_slide.return_value = mock_slide

                # Invalid template should fall back to default "executive"
                result = gen.generate("nonexistent_template", {"version": "test"})
                # Should succeed (executive fallback)
                assert isinstance(result, str)

    def test_empty_template_uses_default(self) -> None:
        gen = PresentationGenerator(
            PresentationConfig(enabled=True, default_template="developer", auto_save=False),
        )
        with patch("core.presentation_generator._HAS_PPTX", True):
            with patch("core.presentation_generator.Presentation") as mock_pptx_cls:
                mock_prs = mock_pptx_cls.return_value
                mock_slide = MagicMock()
                mock_slide.background = MagicMock()
                mock_prs.slides.add_slide.return_value = mock_slide

                path = gen.generate("", {"version": "test"})
                assert path == ""  # auto_save=False returns ""

    def test_template_build_error_raised(self) -> None:
        """Template build errors propagate to the caller."""
        gen = PresentationGenerator(PresentationConfig(enabled=True, auto_save=False))
        with patch("core.presentation_generator._HAS_PPTX", True):
            with patch("core.presentation_generator._TEMPLATE_BUILDERS", new={
                "executive": MagicMock(side_effect=ValueError("test error")),
            }):
                with pytest.raises(ValueError, match="test error"):
                    gen.generate("executive", {})

    def test_auto_save_failure_raised(self, tmp_path: Path) -> None:
        """If PPTX save fails, the exception propagates."""
        gen = PresentationGenerator(
            PresentationConfig(enabled=True, output_dir=str(tmp_path), auto_save=True),
        )
        with patch("core.presentation_generator._HAS_PPTX", True):
            with patch("core.presentation_generator.Presentation") as mock_pptx_cls:
                mock_prs = mock_pptx_cls.return_value
                mock_prs.save.side_effect = OSError("disk full")
                mock_slide = MagicMock()
                mock_slide.background = MagicMock()
                mock_prs.slides.add_slide.return_value = mock_slide

                with pytest.raises(OSError, match="disk full"):
                    gen.generate("executive", {"version": "test"})


# ── Edge Cases ──────────────────────────────────────────────────────────


class TestEdgeCases:
    def test_empty_data_uses_defaults(self) -> None:
        """Empty data dict should not crash — templates have hardcoded defaults."""
        gen = PresentationGenerator(PresentationConfig(enabled=True, auto_save=False))
        with patch("core.presentation_generator._HAS_PPTX", True):
            with patch("core.presentation_generator.Presentation") as mock_pptx_cls:
                mock_prs = mock_pptx_cls.return_value
                mock_slide = MagicMock()
                mock_slide.background = MagicMock()
                mock_prs.slides.add_slide.return_value = mock_slide

                # Should not raise
                path = gen.generate("executive", {})
                assert path == ""

    def test_empty_data_for_all_templates(self) -> None:
        """All three templates should handle empty data gracefully."""
        gen = PresentationGenerator(PresentationConfig(enabled=True, auto_save=False))
        with patch("core.presentation_generator._HAS_PPTX", True):
            with patch("core.presentation_generator.Presentation") as mock_pptx_cls:
                mock_prs = mock_pptx_cls.return_value
                mock_slide = MagicMock()
                mock_slide.background = MagicMock()
                mock_prs.slides.add_slide.return_value = mock_slide

                for tpl in gen.available_templates():
                    path = gen.generate(tpl, {})
                    assert path == ""  # auto_save=False

    def test_generate_all_handles_partial_failure(self, tmp_path: Path) -> None:
        """If one template fails, generate_all still runs others."""
        gen = PresentationGenerator(
            PresentationConfig(enabled=True, output_dir=str(tmp_path), auto_save=True),
        )
        with patch("core.presentation_generator._HAS_PPTX", True):
            with patch("core.presentation_generator.Presentation") as mock_pptx_cls:
                mock_prs = mock_pptx_cls.return_value
                mock_slide = MagicMock()
                mock_slide.background = MagicMock()
                mock_prs.slides.add_slide.return_value = mock_slide

                # Patch the TEMPLATE_BUILDERS dict to make one builder fail
                original_builders = {}
                with patch("core.presentation_generator._TEMPLATE_BUILDERS", new=original_builders):
                    # Manually populate with one failing and the rest working
                    original_builders["executive"] = MagicMock(side_effect=ValueError("fail"))
                    original_builders["developer"] = MagicMock()  # will work (mock)
                    original_builders["client"] = MagicMock()  # will work (mock)

                    results = gen.generate_all({"version": "test"})
                    assert results["executive"] == ""  # failed
                    assert "developer" in results

    def test_no_data_arg_generates_with_empty_dict(self) -> None:
        """generate() without data should not crash."""
        gen = PresentationGenerator(PresentationConfig(enabled=True, auto_save=False))
        with patch("core.presentation_generator._HAS_PPTX", True):
            with patch("core.presentation_generator.Presentation") as mock_pptx_cls:
                mock_prs = mock_pptx_cls.return_value
                mock_slide = MagicMock()
                mock_slide.background = MagicMock()
                mock_prs.slides.add_slide.return_value = mock_slide

                path = gen.generate("executive")
                assert path == ""  # auto_save=False returns empty string


# ── Singleton Factory ───────────────────────────────────────────────────


class TestSingletonFactory:
    def test_get_presentation_generator_returns_instance(self) -> None:
        reset_presentation_generator()
        gen = get_presentation_generator()
        assert isinstance(gen, PresentationGenerator)
        reset_presentation_generator()

    def test_get_presentation_generator_singleton(self) -> None:
        reset_presentation_generator()
        g1 = get_presentation_generator({"PRESENTATION_GENERATOR_ENABLED": True})
        g2 = get_presentation_generator({"PRESENTATION_GENERATOR_ENABLED": True})
        assert g1 is g2
        reset_presentation_generator()

    def test_get_presentation_generator_with_output_dir(self) -> None:
        reset_presentation_generator()
        gen = get_presentation_generator(output_dir="/custom/output")
        assert gen._cfg.output_dir == "/custom/output"
        reset_presentation_generator()

    def test_reset_presentation_generator_clears_singleton(self) -> None:
        reset_presentation_generator()
        g1 = get_presentation_generator()
        reset_presentation_generator()
        g2 = get_presentation_generator()
        assert g1 is not g2


# ── Auto-Fetch / generate_report ──────────────────────────────────────


class TestGenerateReport:
    def test_fetch_version_returns_string(self) -> None:
        gen = PresentationGenerator(PresentationConfig(enabled=False))
        version = gen._fetch_version()
        assert isinstance(version, str)
        assert len(version) > 0

    def test_fetch_file_counts_returns_dict(self) -> None:
        gen = PresentationGenerator(PresentationConfig(enabled=False))
        counts = gen._fetch_file_counts()
        assert isinstance(counts, dict)
        assert "core" in counts
        assert "tests" in counts
        assert isinstance(counts["core"], int)
        assert counts["core"] > 0  # should find some files

    def test_fetch_coverage_data_returns_list(self) -> None:
        gen = PresentationGenerator(PresentationConfig(enabled=False))
        data = gen._fetch_coverage_data()
        assert isinstance(data, list)
        assert len(data) > 0
        assert len(data[0]) == 2  # each row is [key, value]

    def test_generate_report_produces_file(self, tmp_path: Path) -> None:
        """generate_report with auto-fetch should produce a valid PPTX."""
        gen = PresentationGenerator(
            PresentationConfig(enabled=True, output_dir=str(tmp_path), auto_save=True),
        )
        with patch("core.presentation_generator._HAS_PPTX", True):
            with patch("core.presentation_generator.Presentation") as mock_pptx_cls:
                mock_prs = mock_pptx_cls.return_value
                mock_slide = MagicMock()
                mock_slide.background = MagicMock()
                mock_prs.slides.add_slide.return_value = mock_slide

                path = gen.generate_report("executive")
                assert ".pptx" in path
                # Verify version from auto-fetch was used (version-agnostic —
                # the filename embeds the CURRENT version, which changes on bump)
                import re
                assert re.search(r"\d+\.\d+\.\d+", path) or "unknown" in path

    def test_generate_report_with_user_data_merge(self, tmp_path: Path) -> None:
        """User data should override auto-fetched data."""
        gen = PresentationGenerator(
            PresentationConfig(enabled=True, output_dir=str(tmp_path), auto_save=True),
        )
        with patch("core.presentation_generator._HAS_PPTX", True):
            with patch("core.presentation_generator.Presentation") as mock_pptx_cls:
                mock_prs = mock_pptx_cls.return_value
                mock_slide = MagicMock()
                mock_slide.background = MagicMock()
                mock_prs.slides.add_slide.return_value = mock_slide

                # User provides version override
                path = gen.generate_report("executive", {"version": "99.99.99"})
                assert "99.99.99" in path

    def test_generate_report_with_kpis_merge(self, tmp_path: Path) -> None:
        """User KPIs should merge with auto-fetched KPIs (dict merge)."""
        gen = PresentationGenerator(
            PresentationConfig(enabled=True, output_dir=str(tmp_path), auto_save=True),
        )
        with patch("core.presentation_generator._HAS_PPTX", True):
            with patch("core.presentation_generator.Presentation") as mock_pptx_cls:
                mock_prs = mock_pptx_cls.return_value
                mock_slide = MagicMock()
                mock_slide.background = MagicMock()
                mock_prs.slides.add_slide.return_value = mock_slide

                path = gen.generate_report("executive", {"kpis": {"Custom KPI": "42"}})
                # Should not crash; user KPIs merged with auto-fetched
                assert ".pptx" in path or path == ""

    def test_generate_report_empty_template(self, tmp_path: Path) -> None:
        """Empty template falls back to default."""
        gen = PresentationGenerator(
            PresentationConfig(enabled=True, default_template="developer", auto_save=False),
        )
        with patch("core.presentation_generator._HAS_PPTX", True):
            with patch("core.presentation_generator.Presentation") as mock_pptx_cls:
                mock_prs = mock_pptx_cls.return_value
                mock_slide = MagicMock()
                mock_slide.background = MagicMock()
                mock_prs.slides.add_slide.return_value = mock_slide

                path = gen.generate_report("", {})
                assert path == ""  # auto_save=False

    def test_generate_report_disabled_returns_empty(self) -> None:
        """Disabled generator returns empty string."""
        gen = PresentationGenerator(PresentationConfig(enabled=False))
        with patch("core.presentation_generator._HAS_PPTX", True):
            path = gen.generate_report("executive")
            assert path == ""


# ── Module-Level Attributes ─────────────────────────────────────────────


class TestModuleAttributes:
    def test_all_exports(self) -> None:
        from core.presentation_generator import __all__
        assert "PresentationConfig" in __all__
        assert "PresentationGenerator" in __all__
        assert "get_presentation_generator" in __all__
        assert "presentation_config_from_cfg" in __all__
        assert "reset_presentation_generator" in __all__

    def test_theme_colors_have_all_templates(self) -> None:
        from core.presentation_generator import _THEMES
        assert "executive" in _THEMES
        assert "developer" in _THEMES
        assert "client" in _THEMES
        for tpl in _THEMES:
            t = _THEMES[tpl]
            for key in ("bg", "accent", "accent2", "text", "muted", "danger", "warning", "card_bg"):
                assert key in t, f"{tpl} theme missing {key}"
