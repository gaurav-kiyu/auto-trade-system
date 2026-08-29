"""Architecture Analyzer — Architecture compliance and dependency analysis engine.

Detects architectural violations and provides analysis:
- Core → infrastructure import violations (adapter pattern enforcement)
- Strategy → broker SDK direct imports
- Dead module imports
- Missing canonical modules
- Circular dependency detection
- Module boundary health scoring

Wraps the existing scripts/check_architecture_compliance.py in a proper
core module with API endpoints, persistence, and trend tracking.

Usage:
    from core.architecture_analyzer import get_architecture_analyzer
    analyzer = get_architecture_analyzer()
    report = analyzer.run_analysis()
    print(report.summary_text())
"""

from __future__ import annotations

import ast
import importlib.util
import json
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────

ROOT = Path(__file__).resolve().parent.parent

# core/ modules exempt from the no-infrastructure-import rule
CORE_NO_INFRA_MODULES = {
    "core.adapters",
    "core.config_bootstrap",
    "core.data_engine",
    "core.nse_option_recorder",
    "core.persistence",
    "core.services.notification_service",
    "core.services.persistence_service",
    "core.alert_router",
    # Uses the public TelegramNotificationAdapter (+ its send_raw() passthrough),
    # not the private _TelegramClient - same legitimate pattern as
    # core.services.notification_service above. Note: the "from ..." formatted
    # entries in KNOWN_EXEMPT_PATTERNS below never actually match anything (see
    # _check_core_infra_imports - imp/key never contain a "from " prefix), so
    # this module-level skip is the mechanism that actually works.
    "core.ics_telegram_bridge",
}

# Strategy modules that must NOT import broker adapters directly
STRATEGY_NO_BROKER_MODULES = {
    "core.strategy",
    "core.strategy_engine",
    "core.scoring_engine",
    "core.tier_engine",
    "core.signal_router",
}

# Dead/removed modules - any import is a violation
DEAD_MODULES = {
    "core.risk.authoritative_engine",
    "core.admin_control_plane",
    "core.signal_router",
    "core.strategy_engine_v2",
    "core.predictive_risk",
    "core.trading_risk",
    "core.risk.risk_policy_engine",
    "core.dynamic_risk_sizer",
}

# Canonical modules that MUST be importable
REQUIRED_CANONICAL = [
    "core.services.risk_service",
    "core.strategy.orchestrator",
    "core.services.execution_service",
    "core.invariants.engine",
    "core.operating_mode",
    "core.di_container",
    "core.oi_snapshot_store",
    "core.audit_engine",
    "core.config_bootstrap",
    "core.datetime_ist",
    "core.security_auditor",
    "core.performance_optimizer",
    "core.architecture_analyzer",
]

# Known exempt import patterns
KNOWN_EXEMPT_PATTERNS: list[str] = [
    "core.config_bootstrap:from infrastructure.config.secure_config",
    "core.data_engine:from infrastructure.market_data",
    "core.nse_option_recorder:from infrastructure.adapters.market_data.nse.adapter",
    "core.persistence.trades.manager:from infrastructure.adapters.persistence.sqlite_adapter",
    "core.services.notification_service:from infrastructure.adapters",
    "core.services.persistence_service:from infrastructure.adapters.persistence.sqlite_adapter",
    "core.kite_ticker_feed",
    "core.token_refresh_service:from kiteconnect",
    "core.security_auditor:from core.security_auditor import sys",
    "core.performance_optimizer",
    "core.architecture_analyzer",
]

# Broker SDK keywords
BROKER_SDK_KEYWORDS = ("kiteconnect", "angelbroking", "pykiteconnect", "kite")
BROKER_SDK_EXEMPT = {"core.kite_ticker_feed", "core.token_refresh_service"}


# ── Data Models ────────────────────────────────────────────────────────────


@dataclass
class Violation:
    """An architecture violation."""

    check_name: str = ""
    message: str = ""
    severity: str = "HIGH"  # HIGH, MEDIUM, LOW
    module: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "check_name": self.check_name,
            "message": self.message,
            "severity": self.severity,
            "module": self.module,
        }


@dataclass
class DependencyEdge:
    """A dependency between two modules."""

    source: str = ""
    target: str = ""
    import_path: str = ""
    is_exempt: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "target": self.target,
            "import_path": self.import_path,
            "is_exempt": self.is_exempt,
        }


@dataclass
class ArchitectureReport:
    """Complete architecture analysis report."""

    timestamp: float = 0.0
    total_modules_scanned: int = 0
    violations: list[Violation] = field(default_factory=list)
    dependency_edges: list[DependencyEdge] = field(default_factory=list)
    canonical_modules_found: list[str] = field(default_factory=list)
    canonical_modules_missing: list[str] = field(default_factory=list)
    check_results: dict[str, dict[str, Any]] = field(default_factory=dict)
    overall_health: str = "HEALTHY"
    score: float = 10.0
    recommendations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "date": datetime.fromtimestamp(self.timestamp).isoformat() if self.timestamp else "",
            "total_modules_scanned": self.total_modules_scanned,
            "violations": [v.to_dict() for v in self.violations],
            "violations_count": len(self.violations),
            "dependency_edges_count": len(self.dependency_edges),
            "canonical_modules_found": self.canonical_modules_found,
            "canonical_modules_missing": self.canonical_modules_missing,
            "check_results": self.check_results,
            "overall_health": self.overall_health,
            "score": round(self.score, 1),
            "recommendations": self.recommendations,
        }

    def summary_text(self) -> str:
        lines = [
            "═" * 60,
            "  ARCHITECTURE ANALYSIS REPORT",
            "═" * 60,
            f"  Scanned: {self.total_modules_scanned} modules",
            f"  Score: {self.score:.1f}/10.0",
            f"  Health: {self.overall_health}",
            "",
        ]
        if self.violations:
            lines.append(f"  🔴 Violations: {len(self.violations)}")
            for v in self.violations[:5]:
                lines.append(f"     [{v.severity}] {v.check_name}: {v.message}")
        if self.canonical_modules_missing:
            lines.append(f"  🟡 Missing Canonical Modules: {len(self.canonical_modules_missing)}")
            for m in self.canonical_modules_missing:
                lines.append(f"     - {m}")
        if self.check_results:
            lines.append("  Check Results:")
            for check_name, result in self.check_results.items():
                status = "✅" if result.get("passed") else "❌"
                lines.append(f"     {status} {check_name}: {result.get('violations', 0)} violations")
        if self.recommendations:
            lines.append("  Recommendations:")
            for r in self.recommendations:
                lines.append(f"    → {r}")
        lines.append("═" * 60)
        return "\n".join(lines)


# ── Architecture Analyzer ──────────────────────────────────────────────────


class ArchitectureAnalyzer:
    """Architecture compliance and dependency analysis engine.

    Analyzes:
    - Import boundary violations (core → infrastructure, strategy → broker)
    - Dead module imports
    - Missing canonical modules
    - Module dependency graph
    - Architecture health scoring

    Thread-safe. Results persisted for trend tracking.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._report_history: list[ArchitectureReport] = []
        self._last_report: ArchitectureReport | None = None
        self._total_analyses: int = 0
        self._persist_path = Path("json/architecture_analyzer_history.json")

    @property
    def last_report(self) -> ArchitectureReport | None:
        return self._last_report

    # ── Analysis ──────────────────────────────────────────────────────────

    def run_analysis(self, force: bool = False) -> ArchitectureReport:
        """Run a complete architecture analysis.

        Returns:
            ArchitectureReport with violations, dependencies, and recommendations.
        """
        with self._lock:
            if not force and self._last_report is not None and (time.time() - self._last_report.timestamp < 60.0):
                return self._last_report

        report = ArchitectureReport(timestamp=time.time())

        violations: list[Violation] = []
        edges: list[DependencyEdge] = []

        # Run all checks
        self._check_core_infra_imports(violations, edges)
        self._check_dead_modules(violations)
        self._check_canonical_modules(report)
        self._check_direct_broker_sdk(violations)
        self._check_circular_imports(violations)

        report.violations = violations
        report.dependency_edges = edges
        report.total_modules_scanned = self._count_modules()

        # Summarize check results
        report.check_results = {
            "Core→Infra Boundary": {
                "passed": not any("CORE_TO_INFRA" in v.check_name for v in violations),
                "violations": sum(1 for v in violations if "CORE_TO_INFRA" in v.check_name),
            },
            "Dead Module Imports": {
                "passed": not any("DEAD_MODULE" in v.check_name for v in violations),
                "violations": sum(1 for v in violations if "DEAD_MODULE" in v.check_name),
            },
            "Canonical Modules": {
                "passed": len(report.canonical_modules_missing) == 0,
                "violations": len(report.canonical_modules_missing),
            },
            "Direct Broker SDK": {
                "passed": not any("BROKER_SDK" in v.check_name for v in violations),
                "violations": sum(1 for v in violations if "BROKER_SDK" in v.check_name),
            },
            "Circular Dependencies": {
                "passed": not any("CIRCULAR" in v.check_name for v in violations),
                "violations": sum(1 for v in violations if "CIRCULAR" in v.check_name),
            },
        }

        # Compute score
        report.score = self._compute_score(report)
        report.overall_health = "HEALTHY" if report.score >= 8.0 else \
            "WARNING" if report.score >= 6.0 else "CRITICAL"

        # Generate recommendations
        report.recommendations = self._generate_recommendations(report)

        with self._lock:
            self._report_history.append(report)
            self._last_report = report
            self._total_analyses += 1
            self._persist()

        return report

    # ── Check Implementations ─────────────────────────────────────────────

    def _check_core_infra_imports(
        self, violations: list[Violation], edges: list[DependencyEdge]
    ) -> None:
        """Check 1: core/ modules must not import from infrastructure/ directly."""
        core_dir = ROOT / "core"
        if not core_dir.is_dir():
            return

        for pyfile in sorted(core_dir.rglob("*.py")):
            if "__pycache__" in str(pyfile):
                continue

            mod = self._module_name(pyfile)
            if any(mod.startswith(p) for p in CORE_NO_INFRA_MODULES):
                continue

            imports = self._list_imports(pyfile)
            for imp in imports:
                if imp.startswith("infrastructure") or imp.startswith("infra"):
                    key = f"{mod}:{imp}"
                    is_exempt = any(key.startswith(e) for e in KNOWN_EXEMPT_PATTERNS)
                    if not is_exempt:
                        violations.append(Violation(
                            check_name="CORE_TO_INFRA",
                            message=f"'{mod}' imports '{imp}'",
                            severity="HIGH",
                            module=mod,
                        ))
                    edges.append(DependencyEdge(
                        source=mod, target=imp.split(".")[0],
                        import_path=imp, is_exempt=is_exempt,
                    ))

    def _check_dead_modules(self, violations: list[Violation]) -> None:
        """Check 2: Dead modules must not be imported."""
        src_dirs = [ROOT / "core", ROOT / "index_app", ROOT / "scripts", ROOT / "infrastructure"]
        for src in src_dirs:
            if not src.is_dir():
                continue
            for pyfile in src.rglob("*.py"):
                if "__pycache__" in str(pyfile):
                    continue
                mod = self._module_name(pyfile)
                imports = self._list_imports(pyfile)
                for imp in imports:
                    for dead in DEAD_MODULES:
                        if imp == dead or imp.startswith(dead + "."):
                            violations.append(Violation(
                                check_name="DEAD_MODULE",
                                message=f"'{mod}' imports dead module '{imp}'",
                                severity="HIGH",
                                module=mod,
                            ))

    def _check_canonical_modules(self, report: ArchitectureReport) -> None:
        """Check 3: Canonical modules must be importable."""
        found: list[str] = []
        missing: list[str] = []
        for mod_path in REQUIRED_CANONICAL:
            spec = importlib.util.find_spec(mod_path)
            if spec is not None:
                found.append(mod_path)
            else:
                missing.append(mod_path)
        report.canonical_modules_found = found
        report.canonical_modules_missing = missing

    def _check_direct_broker_sdk(self, violations: list[Violation]) -> None:
        """Check 4: No direct broker SDK imports outside broker_adapters."""
        core_dir = ROOT / "core"
        if not core_dir.is_dir():
            return
        for pyfile in sorted(core_dir.rglob("*.py")):
            if "__pycache__" in str(pyfile):
                continue
            mod = self._module_name(pyfile)
            if "broker_adapter" in mod or mod in BROKER_SDK_EXEMPT:
                continue
            imports = self._list_imports(pyfile)
            for imp in imports:
                top = imp.split(".")[0]
                if top in BROKER_SDK_KEYWORDS:
                    violations.append(Violation(
                        check_name="BROKER_SDK",
                        message=f"'{mod}' directly imports '{imp}' — must go through broker_adapters.py",
                        severity="HIGH",
                        module=mod,
                    ))

    def _check_circular_imports(self, violations: list[Violation]) -> None:
        """Check 5: Detect circular imports (first-order resolution)."""
        core_dir = ROOT / "core"
        if not core_dir.is_dir():
            return

        # Build import map
        import_map: dict[str, set[str]] = {}
        for pyfile in core_dir.rglob("*.py"):
            if "__pycache__" in str(pyfile):
                continue
            mod = self._module_name(pyfile)
            imports = set(self._list_module_level_imports(pyfile))
            # Only track core.* imports
            core_imports = {i for i in imports if i.startswith("core.")}
            import_map[mod] = core_imports

        # Detect simple cycles (A imports B, B imports A)
        for mod_a, imps_a in import_map.items():
            for mod_b, imps_b in import_map.items():
                if mod_a < mod_b:  # Check each pair once
                    if mod_a in imps_b and mod_b in imps_a:
                        violations.append(Violation(
                            check_name="CIRCULAR",
                            message=f"Circular dependency: '{mod_a}' <-> '{mod_b}'",
                            severity="MEDIUM",
                            module=mod_a,
                        ))

    # ── Helpers ───────────────────────────────────────────────────────────

    def _module_name(self, filepath: Path) -> str:
        """Convert file path to dotted module name."""
        try:
            rel = filepath.relative_to(ROOT)
        except ValueError:
            return filepath.stem
        parts = list(rel.parts)
        if parts[-1] == "__init__.py":
            parts = parts[:-1]
        else:
            parts[-1] = parts[-1].removesuffix(".py")
        return ".".join(parts)

    def _list_module_level_imports(self, filepath: Path) -> list[str]:
        """Extract only import paths that execute at module load time.

        Unlike _list_imports() (which walks the whole tree, including
        function bodies), this only looks at the module's direct top-level
        statements. A function-local "lazy import to avoid circular deps" is
        a deliberate, safe pattern - it doesn't run until the function is
        called, so it can't actually crash Python at import time the way a
        genuine module-level A<->B import cycle would. _check_circular_imports
        needs this distinction; the CORE_TO_INFRA/BROKER_SDK checks
        deliberately keep using the full-walk _list_imports() below, since a
        lazily-deferred infra import is still an architecture violation, just
        a deferred one.
        """
        try:
            tree = ast.parse(filepath.read_text(encoding="utf-8", errors="ignore"))
        except (SyntaxError, UnicodeDecodeError, OSError):
            return []
        imports: list[str] = []
        for node in tree.body:
            for sub in ([node] if not isinstance(node, ast.Try) else [node, *node.body]):
                if isinstance(sub, ast.Import):
                    for alias in sub.names:
                        imports.append(alias.name)
                elif isinstance(sub, ast.ImportFrom):
                    if sub.module:
                        imports.append(sub.module)
                        for alias in sub.names:
                            imports.append(f"{sub.module}.{alias.name}")
        return imports

    def _list_imports(self, filepath: Path) -> list[str]:
        """Extract all import paths from a Python file."""
        try:
            tree = ast.parse(filepath.read_text(encoding="utf-8", errors="ignore"))
        except (SyntaxError, UnicodeDecodeError, OSError):
            return []
        imports: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.append(node.module)
                    for alias in node.names:
                        if node.module:
                            imports.append(f"{node.module}.{alias.name}")
        return imports

    def _count_modules(self) -> int:
        """Count total Python modules in the project."""
        count = 0
        for src in [ROOT / "core", ROOT / "index_app"]:
            if src.is_dir():
                count += sum(1 for _ in src.rglob("*.py")
                             if "__pycache__" not in str(_))
        return count

    # ── Scoring ───────────────────────────────────────────────────────────

    def _compute_score(self, report: ArchitectureReport) -> float:
        """Compute architecture health score (0-10)."""
        score = 10.0
        for v in report.violations:
            if v.severity == "HIGH":
                score -= 1.0
            elif v.severity == "MEDIUM":
                score -= 0.5
            else:
                score -= 0.2
        if report.canonical_modules_missing:
            score -= len(report.canonical_modules_missing) * 0.5
        return max(0.0, min(10.0, score))

    def _generate_recommendations(self, report: ArchitectureReport) -> list[str]:
        """Generate actionable architecture recommendations."""
        recs: list[str] = []

        infra_violations = [v for v in report.violations if "CORE_TO_INFRA" in v.check_name]
        if infra_violations:
            recs.append(f"Fix {len(infra_violations)} core→infrastructure import violations — use adapter pattern")

        dead_violations = [v for v in report.violations if "DEAD_MODULE" in v.check_name]
        if dead_violations:
            recs.append(f"Remove {len(dead_violations)} dead module imports")

        if report.canonical_modules_missing:
            recs.append(f"Create {len(report.canonical_modules_missing)} missing canonical modules")

        broker_violations = [v for v in report.violations if "BROKER_SDK" in v.check_name]
        if broker_violations:
            recs.append(f"Route {len(broker_violations)} broker SDK imports through broker_adapters.py")

        circular_violations = [v for v in report.violations if "CIRCULAR" in v.check_name]
        if circular_violations:
            recs.append(f"Resolve {len(circular_violations)} circular dependencies by extracting shared interfaces")

        if not recs:
            recs.append("No architecture violations found — maintain current practices")

        recs.append("Run architecture compliance check before every release")
        return recs

    # ── Persistence ───────────────────────────────────────────────────────

    def _persist(self) -> None:
        """Persist report history to disk."""
        try:
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)
            data = [r.to_dict() for r in self._report_history[-100:]]
            self._persist_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except (OSError, ValueError) as exc:
            _log.debug("[ARCH] Persist: %s", exc)

    # ── Statistics ────────────────────────────────────────────────────────

    def get_stats(self) -> dict[str, Any]:
        """Get architecture analyzer statistics."""
        with self._lock:
            last = self._last_report
            return {
                "total_analyses": self._total_analyses,
                "history_length": len(self._report_history),
                "last_analysis_ts": last.timestamp if last else 0,
                "last_score": round(last.score, 1) if last else 0,
                "last_health": last.overall_health if last else "UNKNOWN",
                "total_violations": len(last.violations) if last else 0,
                "high_severity_violations": len(
                    [v for v in last.violations if v.severity == "HIGH"]
                ) if last else 0,
                "canonical_missing": len(last.canonical_modules_missing) if last else 0,
            }


# ── Singleton ──────────────────────────────────────────────────────────────

_arch_analyzer: ArchitectureAnalyzer | None = None
_arch_analyzer_lock = threading.RLock()


def get_architecture_analyzer() -> ArchitectureAnalyzer:
    """Get the singleton ArchitectureAnalyzer instance."""
    global _arch_analyzer
    with _arch_analyzer_lock:
        if _arch_analyzer is None:
            _arch_analyzer = ArchitectureAnalyzer()
        return _arch_analyzer


def reset_architecture_analyzer() -> None:
    """Force-reset singleton (for testing)."""
    global _arch_analyzer
    with _arch_analyzer_lock:
        _arch_analyzer = None


__all__ = [
    "ArchitectureAnalyzer",
    "ArchitectureReport",
    "DependencyEdge",
    "Violation",
    "get_architecture_analyzer",
    "reset_architecture_analyzer",
]
