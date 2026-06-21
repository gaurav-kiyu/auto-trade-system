"""
Version Compatibility Matrix (Phase 29).

Tracks API compatibility between components and detects breaking changes
across versions. Each module declares its supported version range, and the
compatibility checker validates that all modules are compatible.

Usage
-----
    from core.version_compatibility import VersionCompatibilityMatrix

    vcm = VersionCompatibilityMatrix()
    report = vcm.check_all()
    print(report.summary())

    # Register a component's compatibility
    vcm.register("risk_service", "2.0.0", min_compat="2.0.0", max_compat="2.99.99")
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

_log = logging.getLogger(__name__)


# ── Version helpers ──────────────────────────────────────────────────────────

def _parse_version(version: str) -> tuple[int, ...]:
    """Parse a semver string into a tuple for comparison."""
    try:
        parts = version.replace("v", "").split(".")
        return tuple(int(p) for p in parts[:3])
    except (ValueError, TypeError):
        return (0, 0, 0)


def _version_in_range(
    version: str,
    min_version: str,
    max_version: str,
) -> bool:
    """Check if version is within [min_version, max_version]."""
    v = _parse_version(version)
    return _parse_version(min_version) <= v <= _parse_version(max_version)


# ── Dataclasses ──────────────────────────────────────────────────────────────

@dataclass
class ComponentVersion:
    """A component's version and compatibility range."""
    name: str
    version: str
    min_compat_version: str   # Minimum compatible version
    max_compat_version: str   # Maximum compatible version
    dependencies: list[str] = field(default_factory=list)  # Depends on these components

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "min_compat_version": self.min_compat_version,
            "max_compat_version": self.max_compat_version,
            "dependencies": self.dependencies,
        }


@dataclass
class CompatibilityResult:
    """Result of a compatibility check between two components."""
    component_a: str
    component_b: str
    compatible: bool
    a_version: str
    b_version: str
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "component_a": self.component_a,
            "component_b": self.component_b,
            "compatible": self.compatible,
            "a_version": self.a_version,
            "b_version": self.b_version,
            "reason": self.reason,
        }


@dataclass
class CompatibilityReport:
    """Full version compatibility report."""
    system_version: str = ""
    components: list[ComponentVersion] = field(default_factory=list)
    checks: list[CompatibilityResult] = field(default_factory=list)
    all_compatible: bool = True
    failures: list[str] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def summary(self) -> str:
        lines = [
            "=" * 60,
            "  Version Compatibility Report",
            "=" * 60,
            f"  System Version: {self.system_version}",
            f"  Components: {len(self.components)}",
            "",
            "  Registered Components:",
        ]
        for c in self.components:
            lines.append(f"    {c.name:<30s} v{c.version:<12s} "
                        f"(compat: {c.min_compat_version} - {c.max_compat_version})")

        lines.append("")
        lines.append(f"  Compatibility Checks: {len(self.checks)}")
        for chk in self.checks:
            icon = "[OK]" if chk.compatible else "[X]"
            lines.append(f"    {icon} {chk.component_a} <-> {chk.component_b}: {chk.reason}")

        if self.failures:
            lines.append("")
            lines.append(f"  Failures ({len(self.failures)}):")
            for f in self.failures:
                lines.append(f"    [X] {f}")

        lines.append("")
        status = "ALL COMPATIBLE" if self.all_compatible else "INCOMPATIBILITIES DETECTED"
        lines.append(f"  Verdict: {status}")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "system_version": self.system_version,
            "timestamp": self.timestamp,
            "all_compatible": self.all_compatible,
            "components": [c.to_dict() for c in self.components],
            "checks": [chk.to_dict() for chk in self.checks],
            "failures": self.failures[:20],
        }


# ── Version Compatibility Matrix ─────────────────────────────────────────────

class VersionCompatibilityMatrix:
    """Tracks and validates version compatibility across all components."""

    def __init__(self, system_version: str | None = None):
        self._system_version = system_version or self._detect_system_version()
        self._components: dict[str, ComponentVersion] = {}
        self._load_defaults()

    def _detect_system_version(self) -> str:
        """Detect system version from VERSION file."""
        try:
            from pathlib import Path
            vfile = Path("VERSION")
            if vfile.is_file():
                return vfile.read_text(encoding="utf-8").strip()
        except OSError:
            pass
        return "0.0.0"

    def _load_defaults(self) -> None:
        """Load default known components."""
        defaults = [
            ComponentVersion("risk_service", "2.53.0", "2.0.0", "2.99.99",
                           dependencies=["execution_service"]),
            ComponentVersion("execution_service", "2.53.0", "2.0.0", "2.99.99",
                           dependencies=["broker_adapter"]),
            ComponentVersion("signal_service", "2.53.0", "2.0.0", "2.99.99",
                           dependencies=["ml_classifier"]),
            ComponentVersion("ml_classifier", "2.53.0", "2.0.0", "2.99.99"),
            ComponentVersion("broker_adapter", "2.53.0", "2.0.0", "2.99.99"),
            ComponentVersion("portfolio_service", "2.53.0", "2.0.0", "2.99.99",
                           dependencies=["risk_service"]),
            ComponentVersion("event_store", "2.53.0", "2.53.0", "3.0.0"),
            ComponentVersion("certification_gate", "2.53.0", "2.53.0", "3.0.0",
                           dependencies=["strategy_certifier", "replay_certifier"]),
            ComponentVersion("strategy_certifier", "2.53.0", "2.0.0", "2.99.99"),
            ComponentVersion("replay_certifier", "2.53.0", "2.0.0", "2.99.99"),
            ComponentVersion("self_healing", "2.53.0", "2.53.0", "3.0.0",
                           dependencies=["health_checker", "circuit_breaker"]),
            ComponentVersion("health_checker", "2.53.0", "2.0.0", "2.99.99"),
            ComponentVersion("circuit_breaker", "2.53.0", "2.0.0", "2.99.99"),
            ComponentVersion("portfolio_optimizer", "2.53.0", "2.53.0", "3.0.0"),
        ]
        for c in defaults:
            self._components[c.name] = c

    def register(self, name: str, version: str,
                 min_compat: str = "2.0.0",
                 max_compat: str = "2.99.99",
                 dependencies: list[str] | None = None) -> None:
        """Register a component's version and compatibility range."""
        self._components[name] = ComponentVersion(
            name=name,
            version=version,
            min_compat_version=min_compat,
            max_compat_version=max_compat,
            dependencies=dependencies or [],
        )

    def check(self, component_a: str, component_b: str) -> CompatibilityResult:
        """Check compatibility between two components."""
        ca = self._components.get(component_a)
        cb = self._components.get(component_b)

        if not ca:
            return CompatibilityResult(
                component_a=component_a, component_b=component_b,
                compatible=False, a_version="?", b_version="?",
                reason=f"Unknown component: {component_a}",
            )
        if not cb:
            return CompatibilityResult(
                component_a=component_a, component_b=component_b,
                compatible=False, a_version=ca.version, b_version="?",
                reason=f"Unknown component: {component_b}",
            )

        # Check if component_b's version is within component_a's compat range
        b_in_a_range = _version_in_range(cb.version, ca.min_compat_version, ca.max_compat_version)
        a_in_b_range = _version_in_range(ca.version, cb.min_compat_version, cb.max_compat_version)

        if b_in_a_range and a_in_b_range:
            return CompatibilityResult(
                component_a=component_a, component_b=component_b,
                compatible=True,
                a_version=ca.version, b_version=cb.version,
                reason=f"v{ca.version} and v{cb.version} are compatible",
            )

        failures = []
        if not b_in_a_range:
            failures.append(f"v{cb.version} outside {component_a}'s range [{ca.min_compat_version}, {ca.max_compat_version}]")
        if not a_in_b_range:
            failures.append(f"v{ca.version} outside {component_b}'s range [{cb.min_compat_version}, {cb.max_compat_version}]")

        return CompatibilityResult(
            component_a=component_a, component_b=component_b,
            compatible=False,
            a_version=ca.version, b_version=cb.version,
            reason="; ".join(failures),
        )

    def check_all(self) -> CompatibilityReport:
        """Check compatibility across all registered components."""
        report = CompatibilityReport(
            system_version=self._system_version,
            components=list(self._components.values()),
        )

        # Check all dependency pairs
        checked: set[tuple[str, str]] = set()
        for name, comp in self._components.items():
            for dep in comp.dependencies:
                pair = tuple(sorted([name, dep]))
                if pair in checked:
                    continue
                checked.add(pair)
                result = self.check(name, dep)
                report.checks.append(result)
                if not result.compatible:
                    report.all_compatible = False
                    report.failures.append(
                        f"{result.component_a} v{result.a_version} "
                        f"<-> {result.component_b} v{result.b_version}: "
                        f"{result.reason}"
                    )

        # Check against system version
        for name, comp in self._components.items():
            result = self.check_system_compatibility(name)
            if not result.compatible:
                report.all_compatible = False
                report.failures.append(result.reason)

        return report

    def check_system_compatibility(self, component_name: str) -> CompatibilityResult:
        """Check if a component is compatible with the system version."""
        comp = self._components.get(component_name)
        if not comp:
            return CompatibilityResult(
                component_a="system", component_b=component_name,
                compatible=False, a_version=self._system_version, b_version="?",
                reason="Unknown component",
            )

        # System version must be within the component's compat range
        if _version_in_range(self._system_version, comp.min_compat_version, comp.max_compat_version):
            return CompatibilityResult(
                component_a="system", component_b=component_name,
                compatible=True,
                a_version=self._system_version, b_version=comp.version,
                reason=f"System v{self._system_version} compatible with {component_name} v{comp.version}",
            )

        return CompatibilityResult(
            component_a="system", component_b=component_name,
            compatible=False,
            a_version=self._system_version, b_version=comp.version,
            reason=f"System v{self._system_version} outside {component_name}'s range "
                   f"[{comp.min_compat_version}, {comp.max_compat_version}]",
        )

    def get_component(self, name: str) -> ComponentVersion | None:
        """Get a component's version info."""
        return self._components.get(name)

    def list_components(self) -> list[str]:
        """List all registered component names."""
        return list(self._components.keys())


# ── Convenience API ──────────────────────────────────────────────────────────

def check_version_compatibility() -> CompatibilityReport:
    """Convenience function to run full compatibility check."""
    vcm = VersionCompatibilityMatrix()
    return vcm.check_all()


# ── CLI ──────────────────────────────────────────────────────────────────────

def _cli() -> None:
    import argparse
    ap = argparse.ArgumentParser(prog="python -m core.version_compatibility")
    ap.add_argument("--json", action="store_true", help="Output JSON")
    ap.add_argument("--register", nargs=4, metavar=("name", "version", "min", "max"),
                    help="Register a component")
    ap.add_argument("--check", nargs=2, metavar=("a", "b"),
                    help="Check compatibility between two components")
    args = ap.parse_args()

    vcm = VersionCompatibilityMatrix()

    if args.register:
        name, version, min_v, max_v = args.register
        vcm.register(name, version, min_v, max_v)
        print(f"Registered {name} v{version} (compat: {min_v} - {max_v})")
        return

    if args.check:
        a, b = args.check
        result = vcm.check(a, b)
        if args.json:
            print(json.dumps(result.to_dict(), indent=2))
        else:
            icon = "[OK]" if result.compatible else "[X]"
            print(f"{icon} {result.component_a} <-> {result.component_b}: {result.reason}")
        return

    report = vcm.check_all()
    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(report.summary())


if __name__ == "__main__":
    _cli()
