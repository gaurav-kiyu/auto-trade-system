"""Smoke tests for scripts/generate_review_artifacts.py.

Verifies the review-deliverable generator runs end-to-end and produces the
summary PDF and architecture PPTX under docs/review/.
"""
from __future__ import annotations

import subprocess
import sys
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
def test_generator_produces_pdf_and_pptx() -> None:
    """Running the generator must exit 0 and create both deliverables."""
    result = subprocess.run(
        [sys.executable, str(_SCRIPT)],
        cwd=str(_PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, f"generator failed: {result.stderr[-2000:]}"
    assert _PDF.is_file(), f"PDF not produced: {_PDF}"
    assert _PPTX.is_file(), f"PPTX not produced: {_PPTX}"
    assert _PDF.stat().st_size > 1000, "PDF looks empty"
    assert _PPTX.stat().st_size > 1000, "PPTX looks empty"


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
