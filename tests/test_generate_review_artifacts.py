"""Smoke tests for scripts/generate_review_artifacts.py.

Verifies the review-deliverable generator runs end-to-end and produces the
summary PDF and architecture PPTX under docs/review/.
"""
from __future__ import annotations

from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _PROJECT_ROOT / "scripts" / "generate_review_artifacts.py"
_REVIEW_DIR = _PROJECT_ROOT / "docs" / "review"
_PDF = _REVIEW_DIR / "SYSTEM_REVIEW_SUMMARY.pdf"
_PPTX = _REVIEW_DIR / "ARCHITECTURE_OVERVIEW.pptx"


@pytest.mark.skipif(not _SCRIPT.exists(), reason="generator script not present")
def test_script_exists() -> None:
    assert _SCRIPT.is_file()


@pytest.mark.skipif(not _SCRIPT.exists(), reason="generator script not present")
def test_generator_produces_pdf_and_pptx(tmp_path) -> None:
    """Running the real generator functions must not mutate release artifacts."""
    from scripts import generate_review_artifacts as generator

    output_dir = tmp_path / "review"
    output_dir.mkdir()

    pdf_path = output_dir / "SYSTEM_REVIEW_SUMMARY.pdf"
    pptx_path = output_dir / "ARCHITECTURE_OVERVIEW.pptx"

    generator.build_pdf(str(pdf_path))
    generator.build_ppt(str(pptx_path))

    assert pdf_path.is_file(), f"PDF not produced: {pdf_path}"
    assert pptx_path.is_file(), f"PPTX not produced: {pptx_path}"
    assert pdf_path.stat().st_size > 1000, "PDF looks empty"
    assert pptx_path.stat().st_size > 1000, "PPTX looks empty"


@pytest.mark.skipif(not (_PDF.exists() and _PPTX.exists()),
                    reason="deliverables not generated yet")
def test_pdf_starts_with_pdf_magic() -> None:
    assert _PDF.read_bytes()[:5] == b"%PDF-"


@pytest.mark.skipif(not _PPTX.exists(), reason="PPTX not generated yet")
def test_pptx_is_valid_zip_container() -> None:
    import zipfile

    assert zipfile.is_zipfile(_PPTX), "PPTX is not a valid OOXML zip container"
    with zipfile.ZipFile(_PPTX) as zf:
        names = zf.namelist()
        assert "[Content_Types].xml" in names
        slides = [n for n in names if n.startswith("ppt/slides/slide") and n.endswith(".xml")]
        assert len(slides) >= 5, f"expected >=5 slides, found {len(slides)}"
