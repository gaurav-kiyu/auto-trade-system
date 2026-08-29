"""Software Bill of Materials (SBOM) Generator — Pillar 14: Governance & Compliance.

Generates a comprehensive SBOM from:
  - requirements.txt / requirements-lock.txt
  - Installed Python packages (via importlib.metadata)
  - Core application modules (first-party code)
  - Optional dependency tracking via pip

Outputs SPDX-compatible JSON and summary text reports.

Usage:
    from core.sbom_generator import get_sbom_generator

    gen = get_sbom_generator()
    report = gen.generate()
    print(report.summary_text())
    print(json.dumps(report.to_dict(), indent=2))
"""

from __future__ import annotations

import logging
import pathlib
import platform
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any

_log = logging.getLogger(__name__)


# ── Data Models ──────────────────────────────────────────────────────────────


@dataclass
class PackageInfo:
    """Information about a single package."""

    name: str
    version: str
    type: str = "third_party"  # third_party, first_party, system
    license: str = "Unknown"
    source: str = ""  # requirements file or pip
    summary: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "name": self.name,
            "version": self.version,
            "type": self.type,
            "license": self.license,
            "source": self.source,
            "summary": self.summary,
        }


@dataclass
class SBOMReport:
    """Complete Software Bill of Materials report."""

    packages: list[PackageInfo] = field(default_factory=list)
    first_party_modules: list[str] = field(default_factory=list)
    total_packages: int = 0
    third_party_count: int = 0
    first_party_count: int = 0
    spdx_id: str = "SPDXRef-DOCUMENT"
    doc_name: str = "opb-index-trading-bot"
    creation_timestamp: str = ""
    python_version: str = ""
    system_info: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "spdx_id": self.spdx_id,
            "doc_name": self.doc_name,
            "creation_timestamp": self.creation_timestamp,
            "python_version": self.python_version,
            "system_info": self.system_info,
            "total_packages": self.total_packages,
            "third_party_count": self.third_party_count,
            "first_party_count": self.first_party_count,
            "packages": [p.to_dict() for p in self.packages],
            "first_party_modules": self.first_party_modules,
        }

    def summary_text(self) -> str:
        lines = [
            "═" * 60,
            "  SOFTWARE BILL OF MATERIALS",
            "═" * 60,
            f"  Document: {self.doc_name}",
            f"  Created: {self.creation_timestamp}",
            f"  Python: {self.python_version}",
            f"  System: {self.system_info}",
            "",
            f"  Total packages: {self.total_packages}",
            f"  Third-party: {self.third_party_count}",
            f"  First-party: {self.first_party_count}",
            "",
            "  Third-Party Dependencies:",
        ]
        for p in self.packages:
            if p.type == "third_party":
                lic = f" ({p.license})" if p.license and p.license != "Unknown" else ""
                lines.append(f"    {p.name}=={p.version}{lic}")
        lines.append("")
        if self.first_party_modules:
            lines.append(f"  First-Party Modules ({len(self.first_party_modules)}):")
            for mod in sorted(self.first_party_modules)[:20]:
                lines.append(f"    {mod}")
            if len(self.first_party_modules) > 20:
                lines.append(f"    ... and {len(self.first_party_modules) - 20} more")
        lines.append("═" * 60)
        return "\n".join(lines)


# ── SBOM Generator ──────────────────────────────────────────────────────────


class SBOMGenerator:
    """Generates Software Bill of Materials from the codebase.

    Thread-safe singleton.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()

    def generate(self) -> SBOMReport:
        """Generate a complete SBOM report."""
        with self._lock:
            t0 = time.time()
            report = SBOMReport(
                creation_timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                python_version=platform.python_version(),
                system_info=f"{platform.system()} {platform.release()}",
            )

            # 1. Parse requirements files
            req_pkgs = self._parse_requirements()
            for pkg in req_pkgs:
                report.packages.append(pkg)

            # 2. Parse installed packages via importlib.metadata
            installed = self._parse_installed_packages(existing_names={p.name for p in report.packages})
            for pkg in installed:
                report.packages.append(pkg)

            # 3. Discover first-party modules
            report.first_party_modules = self._discover_first_party()

            # Compute counts
            report.total_packages = len(report.packages)
            report.third_party_count = sum(1 for p in report.packages if p.type == "third_party")
            report.first_party_count = sum(1 for p in report.packages if p.type == "first_party")

            _log.info(
                "[SBOM] Generated: %d packages (%d third-party, %d first-party) in %.1fs",
                report.total_packages,
                report.third_party_count,
                report.first_party_count,
                time.time() - t0,
            )
            return report

    def _parse_requirements(self) -> list[PackageInfo]:
        """Parse requirements.txt and requirements-lock.txt files."""
        packages: dict[str, PackageInfo] = {}
        req_files = ["requirements-lock.txt", "requirements.txt"]

        for req_file in req_files:
            path = pathlib.Path(req_file)
            if not path.is_file():
                continue
            try:
                for line in path.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line or line.startswith("#") or line.startswith("-"):
                        continue
                    # Parse name and version
                    match = re.match(r"^([a-zA-Z0-9_.-]+)\s*(==|>=|<=|~=|!=)\s*([a-zA-Z0-9_.*-]+)", line)
                    if match:
                        name = match.group(1).lower()
                        version = match.group(3)
                        # Remove wildcards
                        version = version.replace("*", "")
                        if name not in packages:
                            packages[name] = PackageInfo(
                                name=name,
                                version=version,
                                source=req_file,
                            )
            except OSError as exc:
                _log.warning("[SBOM] Failed to read %s: %s", req_file, exc)

        return list(packages.values())

    def _parse_installed_packages(self, existing_names: set[str]) -> list[PackageInfo]:
        """Parse installed packages via importlib.metadata, skipping already-found ones."""
        packages: list[PackageInfo] = []
        try:
            from importlib.metadata import distributions

            for dist in distributions():
                name = dist.metadata.get("Name", "").lower()
                if not name or name in existing_names:
                    continue
                version = dist.metadata.get("Version", "0.0.0")
                license_info = dist.metadata.get("License", "Unknown")
                summary = dist.metadata.get("Summary", "")

                packages.append(PackageInfo(
                    name=name,
                    version=version,
                    license=license_info,
                    summary=summary[:120] if summary else "",
                    source="pip",
                ))
        except Exception as exc:
            _log.warning("[SBOM] Failed to scan installed packages: %s", exc)

        return packages

    def _discover_first_party(self) -> list[str]:
        """Discover first-party Python modules in the project."""
        modules: list[str] = []
        scan_dirs = ["core", "index_app", "infrastructure", "scripts"]
        for d in scan_dirs:
            path = pathlib.Path(d)
            if path.is_dir():
                for py_file in sorted(path.rglob("*.py")):
                    rel = str(py_file.relative_to(".")).replace("\\", "/").replace("/", ".")[:-3]
                    # Skip __init__ and __pycache__
                    if "__init__" not in rel and "__pycache__" not in rel:
                        modules.append(rel)
        return modules[:500]  # Cap at 500

    def get_stats(self) -> dict[str, Any]:
        """Get quick SBOM statistics."""
        return {
            "available": True,
            "packages_count": 0,
            "last_generated": None,
        }


# ── Singleton ────────────────────────────────────────────────────────────────

_instance: SBOMGenerator | None = None
_instance_lock = threading.RLock()


def get_sbom_generator() -> SBOMGenerator:
    """Return the process-level SBOMGenerator singleton."""
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = SBOMGenerator()
        return _instance


def reset_sbom_generator() -> None:
    """Force-reset the singleton (for testing)."""
    global _instance
    with _instance_lock:
        _instance = None


__all__ = [
    "PackageInfo",
    "SBOMGenerator",
    "SBOMReport",
    "get_sbom_generator",
    "reset_sbom_generator",
]
