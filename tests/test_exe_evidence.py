"""Tests for core/constitution/evidence/exe_evidence.py."""
from __future__ import annotations

from pathlib import Path

from core.constitution.evidence.exe_evidence import collect_exe_evidence

_ROOT = Path(__file__).resolve().parents[1]


def test_collect_exe_evidence_runs():
    calls: list[tuple] = []
    collect_exe_evidence(
        validator=None,  # type: ignore[arg-type]
        root=_ROOT,
        add_ev=lambda *a, **k: calls.append(a),
    )
    assert isinstance(calls, list)


def test_collect_exe_evidence_produces_evidence():
    calls: list[tuple] = []
    collect_exe_evidence(
        validator=None,  # type: ignore[arg-type]
        root=_ROOT,
        add_ev=lambda *a, **k: calls.append(a),
    )
    assert len(calls) > 0
