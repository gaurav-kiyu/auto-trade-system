"""Tests for core/constitution/_evidence_main.py.

Verifies the auto-evidence collection entry point delegates to the
category evidence sub-modules without raising.
"""
from __future__ import annotations

from pathlib import Path

from core.constitution._evidence_main import collect_auto_evidence

_ROOT = Path(__file__).resolve().parents[1]


class _RecordingValidator:
    """Minimal validator that records add_evidence calls."""

    PROJECT_ROOT = _ROOT

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def add_evidence(self, *args: object, **kwargs: object) -> None:
        self.calls.append((args, kwargs))


def test_collect_auto_evidence_runs():
    """collect_auto_evidence must run without raising against the real root."""
    validator = _RecordingValidator()
    collect_auto_evidence(validator)  # type: ignore[arg-type]
    assert isinstance(validator.calls, list)
