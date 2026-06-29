"""
Certification Framework - Institutional-grade release gates.

Replaces ad-hoc validation with deterministic, auditable certification suites
that must pass before every release.

Modules
-------
replay_certifier   :  Deterministic Replay Certification (Phase 4)
paper_certifier    :  Paper Trading Certification (Phase 5)
gate               :  Unified Certification Gate (Phase 24)
"""

from __future__ import annotations

import importlib
from typing import Any

from core.certification.paper_certifier import (
    PaperCertificationReport,
    PaperCertifier,
    certify_paper_trading,
)
from core.certification.replay_certifier import (
    ReplayCertificationReport,
    ReplayCertifier,
    certify_replay_determinism,
)
from core.certification.strategy_certifier import (
    StrategyCertificationReport,
    StrategyCertifier,
    certify_strategy,
)

# Gate symbols loaded lazily to avoid RuntimeWarning when running
# python -m core.certification.gate (eager import conflicts with runpy)
_GATE_MODULE = None


def __getattr__(name: str) -> Any:
    """Lazy-load gate symbols on first access."""
    gate_symbols = {"CertificationGate", "CertificationGateResult", "run_certification_gate"}
    if name in gate_symbols:
        global _GATE_MODULE
        if _GATE_MODULE is None:
            _GATE_MODULE = importlib.import_module("core.certification.gate")
        return getattr(_GATE_MODULE, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "ReplayCertifier",
    "ReplayCertificationReport",
    "certify_replay_determinism",
    "PaperCertifier",
    "PaperCertificationReport",
    "certify_paper_trading",
    "StrategyCertifier",
    "StrategyCertificationReport",
    "certify_strategy",
    "CertificationGate",
    "CertificationGateResult",
    "run_certification_gate",
]
