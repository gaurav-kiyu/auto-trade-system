"""
Certification Framework — Institutional-grade release gates.

Replaces ad-hoc validation with deterministic, auditable certification suites
that must pass before every release.

Modules
-------
replay_certifier   :  Deterministic Replay Certification (Phase 4)
paper_certifier    :  Paper Trading Certification (Phase 5)
"""

from __future__ import annotations

from core.certification.replay_certifier import (
    ReplayCertificationReport,
    ReplayCertifier,
    certify_replay_determinism,
)
from core.certification.paper_certifier import (
    PaperCertificationReport,
    PaperCertifier,
    certify_paper_trading,
)
from core.certification.strategy_certifier import (
    StrategyCertificationReport,
    StrategyCertifier,
    certify_strategy,
)

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
]
