"""Unit tests for scripts/generate_pptx.py — PPTX presentation generation.

Verifies:
  - All slide builder functions produce valid slide objects
  - The generated presentation has exactly 13 slides
  - Helper functions work correctly
  - Backup/overwrite safety mechanism
  - No crashes on any slide function
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pptx import Presentation
from pptx.dml.color import RGBColor

from scripts.generate_pptx import (
    ROOT,
    _add_bg,
    _add_bullet_box,
    _add_shape,
    _add_table,
    _add_text_box,
    _add_title_bar,
    main,
    slide01_title,
    slide02_mission,
    slide03_architecture,
    slide04_trading_workflow,
    slide05_risk,
    slide06_performance,
    slide07_security,
    slide08_monitoring,
    slide09_deployment,
    slide10_certification,
    slide11_risk_register,
    slide12_recommendations,
    slide13_final,
)


# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture()
def prs() -> Presentation:
    """Blank presentation with widescreen dimensions."""
    p = Presentation()
    p.slide_width = 12192000  # 13.33 inches in EMU
    p.slide_height = 6858000  # 7.5 inches in EMU
    return p


# ── Helper Function Tests ─────────────────────────────────────────────


class TestAddBg:
    def test_fills_background(self, prs: Presentation) -> None:
        slide = prs.slides.add_slide(prs.slide_layouts[6])
        _add_bg(slide, RGBColor(0x1E, 0x1E, 0x2E))
        fill = slide.background.fill
        assert fill.fore_color.rgb == RGBColor(0x1E, 0x1E, 0x2E)


class TestAddShape:
    def test_creates_rectangle(self, prs: Presentation) -> None:
        slide = prs.slides.add_slide(prs.slide_layouts[6])
        from pptx.util import Inches

        shape = _add_shape(slide, Inches(0), Inches(0), Inches(1), Inches(1))
        assert shape is not None
        assert shape.width == Inches(1)

    def test_returns_shape_with_correct_color(self, prs: Presentation) -> None:
        slide = prs.slides.add_slide(prs.slide_layouts[6])
        from pptx.util import Inches

        shape = _add_shape(slide, Inches(0), Inches(0), Inches(1), Inches(1),
                           color=RGBColor(0x00, 0xD2, 0x8E))
        assert shape.fill.fore_color.rgb == RGBColor(0x00, 0xD2, 0x8E)


class TestAddTextBox:
    def test_adds_text_box(self, prs: Presentation) -> None:
        slide = prs.slides.add_slide(prs.slide_layouts[6])
        from pptx.util import Inches

        tb = _add_text_box(slide, Inches(0), Inches(0), Inches(5), Inches(1),
                           "Hello", font_size=14)
        assert tb is not None
        assert tb.text_frame.paragraphs[0].text == "Hello"

    def test_word_wrap_enabled(self, prs: Presentation) -> None:
        slide = prs.slides.add_slide(prs.slide_layouts[6])
        from pptx.util import Inches

        tb = _add_text_box(slide, Inches(0), Inches(0), Inches(5), Inches(1), "Test")
        assert tb.text_frame.word_wrap is True

    def test_bold_text(self, prs: Presentation) -> None:
        slide = prs.slides.add_slide(prs.slide_layouts[6])
        from pptx.util import Inches

        tb = _add_text_box(slide, Inches(0), Inches(0), Inches(5), Inches(1),
                           "Bold", bold=True)
        assert tb.text_frame.paragraphs[0].font.bold


class TestAddBulletBox:
    def test_adds_bullet_points(self, prs: Presentation) -> None:
        slide = prs.slides.add_slide(prs.slide_layouts[6])
        from pptx.util import Inches

        tb = _add_bullet_box(slide, Inches(0), Inches(0), Inches(5), Inches(2),
                             ["Item 1", "Item 2"])
        text = tb.text_frame.paragraphs[0].text
        assert "Item 1" in text

    def test_with_title(self, prs: Presentation) -> None:
        slide = prs.slides.add_slide(prs.slide_layouts[6])
        from pptx.util import Inches

        tb = _add_bullet_box(slide, Inches(0), Inches(0), Inches(5), Inches(2),
                             ["Item 1"], title="My Title")
        assert tb.text_frame.paragraphs[0].text == "My Title"


class TestAddTable:
    def test_creates_table(self, prs: Presentation) -> None:
        slide = prs.slides.add_slide(prs.slide_layouts[6])
        from pptx.util import Inches

        tbl = _add_table(slide, Inches(0), Inches(0), Inches(5), Inches(2),
                         ["A", "B"], [["1", "2"]])
        assert tbl.table.cell(0, 0).text == "A"
        assert tbl.table.cell(1, 0).text == "1"

    def test_header_formatting(self, prs: Presentation) -> None:
        slide = prs.slides.add_slide(prs.slide_layouts[6])
        from pptx.util import Inches

        tbl = _add_table(slide, Inches(0), Inches(0), Inches(5), Inches(2),
                         ["H1"], [["D1"]])
        cell = tbl.table.cell(0, 0)
        assert cell.text_frame.paragraphs[0].font.bold


class TestAddTitleBar:
    def test_adds_title_bar(self, prs: Presentation) -> None:
        slide = prs.slides.add_slide(prs.slide_layouts[6])
        _add_title_bar(slide, "Test Title")
        # Title bar creates a shape AND a text box — verify the text appears
        found = False
        for shape in slide.shapes:
            if hasattr(shape, "text_frame") and "Test Title" in shape.text_frame.text:
                found = True
                break
        assert found, "Title text not found in any shape's text frame"


# ── Slide Builder Tests ───────────────────────────────────────────────


class TestSlideBuilders:
    def test_slide01_title(self, prs: Presentation) -> None:
        slide01_title(prs)
        assert len(prs.slides) == 1

    def test_slide02_mission(self, prs: Presentation) -> None:
        slide02_mission(prs)
        assert len(prs.slides) == 1

    def test_slide03_architecture(self, prs: Presentation) -> None:
        slide03_architecture(prs)
        assert len(prs.slides) == 1

    def test_slide04_trading_workflow(self, prs: Presentation) -> None:
        slide04_trading_workflow(prs)
        assert len(prs.slides) == 1

    def test_slide05_risk(self, prs: Presentation) -> None:
        slide05_risk(prs)
        assert len(prs.slides) == 1

    def test_slide06_performance(self, prs: Presentation) -> None:
        slide06_performance(prs)
        assert len(prs.slides) == 1

    def test_slide07_security(self, prs: Presentation) -> None:
        slide07_security(prs)
        assert len(prs.slides) == 1

    def test_slide08_monitoring(self, prs: Presentation) -> None:
        slide08_monitoring(prs)
        assert len(prs.slides) == 1

    def test_slide09_deployment(self, prs: Presentation) -> None:
        slide09_deployment(prs)
        assert len(prs.slides) == 1

    def test_slide10_certification(self, prs: Presentation) -> None:
        slide10_certification(prs)
        assert len(prs.slides) == 1

    def test_slide11_risk_register(self, prs: Presentation) -> None:
        slide11_risk_register(prs)
        assert len(prs.slides) == 1

    def test_slide12_recommendations(self, prs: Presentation) -> None:
        slide12_recommendations(prs)
        assert len(prs.slides) == 1

    def test_slide13_final(self, prs: Presentation) -> None:
        slide13_final(prs)
        assert len(prs.slides) == 1


# ── Main Function Tests ───────────────────────────────────────────────


class TestMainFunction:
    def test_generates_13_slides(self, tmp_path: Path) -> None:
        """main() should produce a presentation with exactly 13 slides."""
        # Temporarily change ROOT to use tmp_path for output
        # We import the module's namespace to modify ROOT
        import scripts.generate_pptx as mod
        original_root = mod.ROOT
        try:
            mod.ROOT = tmp_path
            main()

            output_file = tmp_path / "OPB_Presentation_v2.53.0.pptx"
            assert output_file.exists(), "Output PPTX file was not created"

            prs_loaded = Presentation(str(output_file))
            assert len(prs_loaded.slides) == 13, (
                f"Expected 13 slides, got {len(prs_loaded.slides)}"
            )
        finally:
            mod.ROOT = original_root

    def test_backup_created_on_overwrite(self, tmp_path: Path) -> None:
        """Running main() twice should create a backup of the first file."""
        import scripts.generate_pptx as mod
        original_root = mod.ROOT
        try:
            mod.ROOT = tmp_path
            main()  # First run — creates the file
            main()  # Second run — should trigger backup

            output_file = tmp_path / "OPB_Presentation_v2.53.0.pptx"
            assert output_file.exists()

            # Check a backup file was created
            backups = list(tmp_path.glob("OPB_Presentation_v2.53.0.*.pptx.bak"))
            assert len(backups) >= 1, (
                f"No backup files found in {tmp_path}"
            )
        finally:
            mod.ROOT = original_root

    def test_no_crash_on_empty_environment(self, prs: Presentation) -> None:
        """All slide builders should run without errors on a blank presentation."""
        slide01_title(prs)
        slide02_mission(prs)
        slide03_architecture(prs)
        slide04_trading_workflow(prs)
        slide05_risk(prs)
        slide06_performance(prs)
        slide07_security(prs)
        slide08_monitoring(prs)
        slide09_deployment(prs)
        slide10_certification(prs)
        slide11_risk_register(prs)
        slide12_recommendations(prs)
        slide13_final(prs)
        assert len(prs.slides) == 13


# ── ROOT Path Verification ────────────────────────────────────────────


class TestRootPath:
    def test_root_points_to_project_root(self) -> None:
        """ROOT should be the parent of the scripts directory."""
        assert (ROOT / "scripts" / "generate_pptx.py").exists(), (
            "ROOT does not point to a directory containing scripts/generate_pptx.py"
        )
        assert (ROOT / "VERSION").exists(), (
            "ROOT does not contain VERSION file — not the project root"
        )
