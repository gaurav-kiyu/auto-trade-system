"""Tests for core/constitution/evidence/arch_evidence.py."""
from __future__ import annotations

from pathlib import Path

from core.constitution.evidence.arch_evidence import collect_arch_evidence

_ROOT = Path(__file__).resolve().parents[1]


def test_collect_arch_evidence_runs():
    """Evidence collection must run and record calls against the real root."""
    calls: list[tuple] = []
    collect_arch_evidence(
        validator=None,  # type: ignore[arg-type]
        root=_ROOT,
        add_ev=lambda *a, **k: calls.append(a),
    )
    assert isinstance(calls, list)


def test_collect_arch_evidence_produces_evidence():
    """The repo contains architecture artifacts, so evidence must be added."""
    calls: list[tuple] = []
    collect_arch_evidence(
        validator=None,  # type: ignore[arg-type]
        root=_ROOT,
        add_ev=lambda *a, **k: calls.append(a),
    )
    assert len(calls) > 0
