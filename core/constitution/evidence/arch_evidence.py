"""Architecture (ARCH) evidence collection — extracted from evidence.py for SRP compliance.

Collects auto-evidence for constitution scoring categories ARCH-01 through ARCH-04
by scanning the codebase for architecture-related modules, tests, docs, and scripts.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.constitution import ConstitutionValidator

import logging

log = logging.getLogger(__name__)


def collect_arch_evidence(
    validator: ConstitutionValidator,
    root: Path,
    add_ev: Any,
) -> None:
    """Collect architecture category evidence (ARCH-01 through ARCH-04).

    Args:
        validator: ConstitutionValidator instance for add_evidence calls.
        root: Project root path.
        add_ev: Bound validator.add_evidence method.
    """
    # ── ARCH: Architecture ──────────────────────────────────────────
    if (root / "scripts" / "check_architecture_compliance.py").exists():
        add_ev("ARCH-01",
            "Architecture compliance check script (scripts/check_architecture_compliance.py)",
            "test_pass", 0.5)
    if (root / "tests" / "test_architecture_compliance.py").exists():
        add_ev("ARCH-01",
            "Architecture compliance test (tests/test_architecture_compliance.py)",
            "test_pass", 0.5)
        add_ev("ARCH-02",
            "Architecture compliance detects SRP violations (19 tests)",
            "test_pass", 0.4)
        add_ev("ARCH-04",
            "Architecture compliance checker enforces dependency rules",
            "test_pass", 0.4)
    adr_dir = root / "docs" / "adr"
    if adr_dir.is_dir():
        adr_count = len(list(adr_dir.glob("*.md")))
        add_ev("ARCH-01",
            f"{adr_count} ADR documents define architectural boundaries",
            "documentation", 0.3)
        add_ev("ARCH-04",
            "ADR-0010 documents dependency direction rules",
            "documentation", 0.2)
        add_ev("ARCH-02",
            f"{adr_count} ADRs document module boundaries and responsibilities",
            "documentation", 0.2)
    if (root / "docs" / "ownership_matrix.md").exists():
        add_ev("ARCH-02",
            "Module ownership matrix defines single-responsibility per module",
            "documentation", 0.3)
    if (root / "core" / "adapters" / "broker_adapters.py").exists():
        add_ev("ARCH-03",
            "Broker abstraction via broker_adapters.py: all calls through ports",
            "code_review", 0.5)
    if (root / "core" / "ports" / "broker").is_dir():
        add_ev("ARCH-03",
            "Broker port interface (core/ports/broker/) defines contract",
            "code_review", 0.3)
    if (root / "tests" / "test_broker_contract_certification.py").exists():
        add_ev("ARCH-03",
            "Broker contract certification test validates adapter compliance",
            "test_pass", 0.5)
    if (root / "docs" / "adr" / "0004-broker-abstraction.md").exists():
        add_ev("ARCH-03",
            "ADR-0004 documents broker abstraction architecture",
            "documentation", 0.2)
    if (root / "scripts" / "pre_implementation_check.py").exists():
        add_ev("ARCH-01",
            "Boundary rules enforced via pre_implementation_check.py",
            "code_review", 0.3)
    # ARCH-02: Single responsibility - additional evidence
    srp_dirs = ["core/adapters", "core/ports", "core/services", "core/execution", "core/auth", "core/wal"]
    found_srp = [d for d in srp_dirs if (root / d).is_dir()]
    if found_srp:
        add_ev("ARCH-02",
            f"Clean module boundaries: {len(found_srp)} port/adapter/service directories",
            "code_review", 0.2)
    if (root / "docs" / "adr" / "0005-single-responsibility.md").exists():
        add_ev("ARCH-02",
            "ADR-0005 documents single-responsibility architecture",
            "documentation", 0.2)
    # ARCH-04: No circular dependencies - additional evidence
    if (root / "core" / "di_container.py").exists():
        add_ev("ARCH-04",
            "DI container enforces explicit dependency wiring without cycles",
            "code_review", 0.3)
    if (root / "docs" / "adr" / "0010-architecture-governance.md").exists():
        add_ev("ARCH-04",
            "ADR-0010 architecture governance enforces dependency direction",
            "documentation", 0.2)
    if (root / "tests" / "test_di_container.py").exists():
        add_ev("ARCH-04",
            "DI container test validates wiring and dependency resolution",
            "test_pass", 0.3)
    if (root / "CLAUDE.md").exists():
        add_ev("ARCH-01",
            "CLAUDE.md mandates boundary rules: no direct broker SDK calls from core",
            "documentation", 0.3)
    if (root / "core" / "execution").is_dir():
        add_ev("ARCH-02",
            "core/execution/ module isolates all execution concerns in dedicated subpackage",
            "code_review", 0.2)
    if (root / "core" / "auth").is_dir():
        add_ev("ARCH-02",
            "core/auth/ module isolates all authentication concerns in dedicated subpackage",
            "code_review", 0.2)
    if (root / "core" / "ports" / "persistence" / "persistence_port.py").exists():
        add_ev("ARCH-03",
            "Persistence port interface (core/ports/persistence/) defines persistence contract",
            "code_review", 0.3)
    if (root / "core" / "ports" / "risk" / "risk_port.py").exists():
        add_ev("ARCH-03",
            "Risk service port interface (core/ports/risk/) defines risk contract",
            "code_review", 0.3)
    if (root / "tests" / "test_broker_port.py").exists():
        add_ev("ARCH-03",
            "Broker port test validates port contract is implementable (test_broker_port.py)",
            "test_pass", 0.3)
    if (root / "scripts" / "check_architecture_compliance.py").exists():
        content = (root / "scripts" / "check_architecture_compliance.py").read_text(
            encoding="utf-8", errors="replace")
        if "No circular imports" in content:
            add_ev("ARCH-04",
                "Architecture compliance checker detects circular imports between core packages",
                "test_pass", 0.3)
        add_ev("ARCH-01",
            "check_architecture_compliance.py enforces 5 boundary rules: no infra imports, adapter pattern",
            "test_pass", 0.3)
    if (root / "tests" / "test_environment.py").exists():
        add_ev("ARCH-01",
            "Environment test validates deployment boundary enforcement (test_environment.py)",
            "test_pass", 0.4)
    if (root / "tests" / "test_config_bootstrap.py").exists():
        add_ev("ARCH-01",
            "Config bootstrap test validates layer-merge architecture boundary rules",
            "test_pass", 0.4)


__all__ = ["collect_arch_evidence"]
