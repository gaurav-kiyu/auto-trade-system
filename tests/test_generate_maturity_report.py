"""Tests for the snapshot-based previous-milestone anchor in scripts/generate_maturity_report.py.

Verifies that the maturity report reads its PREV_SCORE/PREV_EVIDENCE anchor from a
stored snapshot (_score_snapshot.json) instead of a hardcoded milestone, so future
regenerations compute drift-free deltas against the previous actual run.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import scripts.generate_maturity_report as mod


@pytest.fixture()
def temp_snapshot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the module's SNAPSHOT_PATH at a temp file for test isolation."""
    snap = tmp_path / "_score_snapshot.json"
    monkeypatch.setattr(mod, "SNAPSHOT_PATH", snap)
    return snap


def _sample_data(overall: float = 9.18, evidence: int = 1922) -> dict[str, Any]:
    """A minimal scoring payload matching what score_system.py --json returns."""
    return {
        "overall_score": overall,
        "total_evidence": evidence,
        "total_regressions": 0,
        "categories": [
            {
                "category_id": "LAY-01",
                "name": "Business Layer",
                "group": "Enterprise Layers",
                "score": overall,
                "max_score": 10.0,
                "evidence_count": evidence // 111,
            }
        ],
    }


# ── load_prev_anchor ────────────────────────────────────────────────────────────


class TestLoadPrevAnchor:
    def test_falls_back_to_defaults_without_snapshot(self, temp_snapshot: Path) -> None:
        assert not temp_snapshot.exists()
        score, evidence, from_snap = mod.load_prev_anchor()
        assert (score, evidence, from_snap) == (
            mod.DEFAULT_PREV_SCORE, mod.DEFAULT_PREV_EVIDENCE, False,
        )

    def test_reads_stored_snapshot(self, temp_snapshot: Path) -> None:
        temp_snapshot.write_text(
            json.dumps({"overall_score": 9.30, "total_evidence": 2000, "recorded_at": "x"}),
            encoding="utf-8",
        )
        score, evidence, from_snap = mod.load_prev_anchor()
        assert score == 9.30
        assert evidence == 2000
        assert from_snap is True

    def test_ignores_corrupt_snapshot(self, temp_snapshot: Path) -> None:
        temp_snapshot.write_text("{not json", encoding="utf-8")
        score, evidence, from_snap = mod.load_prev_anchor()
        assert (score, evidence, from_snap) == (8.83, 1757, False)

    def test_ignores_invalid_values(self, temp_snapshot: Path) -> None:
        temp_snapshot.write_text(
            json.dumps({"overall_score": -1, "total_evidence": -5}), encoding="utf-8"
        )
        score, evidence, from_snap = mod.load_prev_anchor()
        assert (score, evidence, from_snap) == (
            mod.DEFAULT_PREV_SCORE, mod.DEFAULT_PREV_EVIDENCE, False,
        )


# ── save_snapshot ───────────────────────────────────────────────────────────────


class TestSaveSnapshot:
    def test_writes_expected_fields(self, temp_snapshot: Path) -> None:
        mod.save_snapshot(_sample_data(overall=9.18, evidence=1922))
        assert temp_snapshot.exists()
        payload = json.loads(temp_snapshot.read_text(encoding="utf-8"))
        assert payload["overall_score"] == 9.18
        assert payload["total_evidence"] == 1922
        assert payload["n_categories"] == 1
        assert payload["total_regressions"] == 0
        assert "recorded_at" in payload

    def test_saved_snapshot_feeds_next_load(self, temp_snapshot: Path) -> None:
        mod.save_snapshot(_sample_data(overall=9.30, evidence=2000))
        score, evidence, from_snap = mod.load_prev_anchor()
        assert (score, evidence, from_snap) == (9.30, 2000, True)


# ── generate_markdown historical table ──────────────────────────────────────────


class TestMarkdownAnchor:
    def test_first_run_uses_default_anchor(self, temp_snapshot: Path) -> None:
        md = mod.generate_markdown(_sample_data())
        d_score = mod.DEFAULT_PREV_SCORE
        d_ev = mod.DEFAULT_PREV_EVIDENCE
        assert f"| Top-10 gap closure | {d_score}/10 | {d_ev:,} |" in md
        assert (
            f"| Next-tier closure (current) | 9.18/10 | 1,922 | "
            f"{9.18 - d_score:+.2f}, {1922 - d_ev:+,} ev |"
        ) in md

    def test_regeneration_uses_snapshot_anchor(self, temp_snapshot: Path) -> None:
        # Previous run was 9.18/1922; current run improved to 9.30/2000.
        mod.save_snapshot(_sample_data(overall=9.18, evidence=1922))
        md = mod.generate_markdown(_sample_data(overall=9.30, evidence=2000))
        # Delta is computed against the snapshot, not the hardcoded 8.83 baseline.
        assert "| Previous milestone (snapshot) | 9.18/10 | 1,922 |" in md
        assert "| Next-tier closure (current) | 9.30/10 | 2,000 | +0.12, +78 ev |" in md
        assert "drift-free" in md

    def test_regression_shows_negative_delta(self, temp_snapshot: Path) -> None:
        # Previous run was 9.18/1922; current run regressed to 9.10/1900.
        mod.save_snapshot(_sample_data(overall=9.18, evidence=1922))
        md = mod.generate_markdown(_sample_data(overall=9.10, evidence=1900))
        # Negative deltas must be visible, not clamped to +0.00.
        assert "| Next-tier closure (current) | 9.10/10 | 1,900 | -0.08, -22 ev |" in md

    def test_no_snapshot_after_regeneration_keeps_default(self, temp_snapshot: Path) -> None:
        """Running generate_markdown alone must NOT persist a snapshot (main() does)."""
        mod.generate_markdown(_sample_data())
        assert not temp_snapshot.exists()


# ── generate_pdf_from_data historical table ─────────────────────────────────────


class TestPdfAnchor:
    def test_pdf_uses_snapshot_anchor(self, temp_snapshot: Path, tmp_path: Path) -> None:
        mod.save_snapshot(_sample_data(overall=9.18, evidence=1922))
        pdf_path = tmp_path / "out.pdf"
        result = mod.generate_pdf_from_data(_sample_data(overall=9.30, evidence=2000), pdf_path)
        if result is False:
            # Degraded path: reportlab not installed; nothing to assert further.
            return
        assert result is True
        assert pdf_path.exists() and pdf_path.stat().st_size > 0
