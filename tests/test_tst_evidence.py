"""Tests for core/constitution/evidence/tst_evidence.py."""
from __future__ import annotations

from pathlib import Path

from core.constitution.evidence.tst_evidence import collect_tst_evidence

_ROOT = Path(__file__).resolve().parents[1]


def test_collect_tst_evidence_runs():
    calls: list[tuple] = []
    collect_tst_evidence(
        validator=None,  # type: ignore[arg-type]
        root=_ROOT,
        add_ev=lambda *a, **k: calls.append(a),
    )
    assert isinstance(calls, list)


def test_collect_tst_evidence_produces_evidence():
    calls: list[tuple] = []
    collect_tst_evidence(
        validator=None,  # type: ignore[arg-type]
        root=_ROOT,
        add_ev=lambda *a, **k: calls.append(a),
    )
    assert len(calls) > 0
