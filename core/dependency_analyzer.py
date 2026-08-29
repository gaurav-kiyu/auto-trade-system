"""Dependency Analyzer — Module & Service Dependency Mapper.

Scans the entire Python codebase to:
  - Build a complete dependency graph (who imports whom)
  - Detect circular dependencies
  - Categorize dependencies (core, infrastructure, external, test)
  - Identify dead modules (no dependents)
  - Generate dependency metrics (coupling, stability, abstractness)
  - Produce human-readable dependency reports

Differs from ImpactAnalysisEngine:
  - ImpactAnalysisEngine focuses on "what breaks if X changes"
  - DependencyAnalyzer focuses on "how modules relate to each other"
    with architectural metrics, circular dependency detection, and
    dependency health scoring.

Usage:
    from core.dependency_analyzer import DependencyAnalyzer

    analyzer = DependencyAnalyzer()
    report = analyzer.analyze()
    print(report.summary_text())
    for cycle in report.circular_dependencies:
        print(f"  Cycle: {' → '.join(cycle)}")
    print(f"Coupling score: {report.coupling_score:.2f}")
"""

from __future__ import annotations

import ast
import logging
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)


# ── Data Models ──────────────────────────────────────────────────────────────


@dataclass
class DependencyNode:
    """A single module with its dependency metadata."""

    module_path: str
    imports: set[str] = field(default_factory=set)       # modules this imports
    imported_by: set[str] = field(default_factory=set)    # modules that import this
    category: str = "core"                                 # core, infrastructure, external, test, app
    lines_of_code: int = 0
    is_init: bool = False

    @property
    def fan_in(self) -> int:
        """Number of modules that import this module."""
        return len(self.imported_by)

    @property
    def fan_out(self) -> int:
        """Number of modules this module imports."""
        return len(self.imports)

    @property
    def instability(self) -> float:
        """Instability = fan_out / (fan_in + fan_out). 0=stable, 1=unstable.
        Robert Martin's metric: I = Ce / (Ca + Ce)
        """
        total = self.fan_in + self.fan_out
        return round(self.fan_out / max(1, total), 3)


@dataclass
class DependencyReport:
    """Complete dependency analysis report."""

    total_modules: int = 0
    total_edges: int = 0
    nodes: dict[str, DependencyNode] = field(default_factory=dict)
    circular_dependencies: list[list[str]] = field(default_factory=list)
    dead_modules: list[str] = field(default_factory=list)
    external_dependencies: dict[str, list[str]] = field(default_factory=dict)
    category_counts: dict[str, int] = field(default_factory=dict)
    coupling_score: float = 0.0   # 0.0 (loose) to 1.0 (tightly coupled)
    stability_score: float = 0.0  # 0.0 (unstable) to 1.0 (stable)
    top_imported: list[tuple[str, int]] = field(default_factory=list)
    top_importers: list[tuple[str, int]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_modules": self.total_modules,
            "total_edges": self.total_edges,
            "circular_dependencies": len(self.circular_dependencies),
            "dead_modules": len(self.dead_modules),
            "external_dependencies": {k: len(v) for k, v in self.external_dependencies.items()},
            "category_counts": self.category_counts,
            "coupling_score": round(self.coupling_score, 3),
            "stability_score": round(self.stability_score, 3),
            "top_imported": [{"module": m, "count": c} for m, c in self.top_imported[:10]],
            "top_importers": [{"module": m, "count": c} for m, c in self.top_importers[:10]],
            "module_count_by_category": {
                cat: sum(1 for n in self.nodes.values() if n.category == cat)
                for cat in set(n.category for n in self.nodes.values())
            },
        }

    def summary_text(self) -> str:
        lines = [
            "═" * 60,
            "  DEPENDENCY ANALYSIS REPORT",
            "═" * 60,
            f"  Total modules: {self.total_modules}",
            f"  Total import edges: {self.total_edges}",
            f"  Avg edges/module: {self.total_edges / max(1, self.total_modules):.1f}",
            "",
            f"  Coupling score: {self.coupling_score:.3f}  (0=loose, 1=tight)",
            f"  Stability score: {self.stability_score:.3f}  (0=unstable, 1=stable)",
            "",
        ]
        if self.category_counts:
            lines.append("  By Category:")
            for cat, count in sorted(self.category_counts.items()):
                lines.append(f"    {cat}: {count}")
        if self.circular_dependencies:
            lines.append(f"  Circular Dependencies: {len(self.circular_dependencies)}")
            for cycle in self.circular_dependencies[:5]:
                lines.append(f"    {' → '.join(cycle)}")
        if self.dead_modules:
            lines.append(f"  Dead Modules (no dependents): {len(self.dead_modules)}")
            for m in self.dead_modules[:10]:
                lines.append(f"    {m}")
        if self.external_dependencies:
            lines.append("  External Packages Used:")
            for pkg, mods in sorted(self.external_dependencies.items())[:15]:
                lines.append(f"    {pkg}: {len(mods)} modules")
        if self.top_imported:
            lines.append("  Most Imported Modules:")
            for mod, cnt in self.top_imported[:5]:
                lines.append(f"    {mod}: {cnt} dependents")
        lines.append("═" * 60)
        return "\n".join(lines)


# ── Dependency Analyzer ──────────────────────────────────────────────────────


class DependencyAnalyzer:
    """Scans the codebase and builds a comprehensive dependency graph.

    Thread-safe singleton.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._nodes: dict[str, DependencyNode] = {}
        self._built = False
        self._project_root = Path(".").resolve()
        self._scan_dirs = ["core", "index_app", "infrastructure", "scripts", "tests"]

    # ── Build ──────────────────────────────────────────────────────────────

    def build(self) -> None:
        """Build the full dependency graph (idempotent, runs once)."""
        with self._lock:
            if self._built:
                return
            _log.info("[DEP] Building dependency graph...")
            self._nodes.clear()

            # Collect all Python files
            all_files: list[Path] = []
            for d in self._scan_dirs:
                p = Path(d)
                if p.is_dir():
                    all_files.extend(p.rglob("*.py"))

            # First pass: create nodes and parse imports
            for file_path in all_files:
                rel = self._to_rel(file_path)
                node = DependencyNode(
                    module_path=rel,
                    category=self._categorize(rel),
                    is_init=file_path.name == "__init__.py",
                    lines_of_code=self._count_loc(file_path),
                )

                imports = self._parse_imports(file_path)
                # Filter out self-references and standard library
                for imp in sorted(imports):
                    if imp != rel.replace(".py", "").replace("/", "."):
                        node.imports.add(imp)

                self._nodes[rel] = node

            # Second pass: build reverse graph (imported_by)
            for node in self._nodes.values():
                for imp in list(node.imports):
                    # Find which module path matches this import
                    matched = self._resolve_import(imp, node.module_path)
                    if matched and matched in self._nodes:
                        self._nodes[matched].imported_by.add(node.module_path)

            self._built = True
            _log.info("[DEP] Graph built: %d nodes, %d edges", len(self._nodes),
                      sum(len(n.imports) for n in self._nodes.values()))

    def reset(self) -> None:
        """Force-reset the graph (for testing)."""
        with self._lock:
            self._nodes.clear()
            self._built = False

    # ── Analysis ───────────────────────────────────────────────────────────

    def analyze(self) -> DependencyReport:
        """Run full dependency analysis and return a report."""
        self.build()
        report = DependencyReport()

        with self._lock:
            report.nodes = dict(self._nodes)
            report.total_modules = len(self._nodes)
            report.total_edges = sum(len(n.imports) for n in self._nodes.values())

            # Category counts
            cat_counts: dict[str, int] = {}
            for n in self._nodes.values():
                cat_counts[n.category] = cat_counts.get(n.category, 0) + 1
            report.category_counts = cat_counts

            # Circular dependencies
            report.circular_dependencies = self._find_circular()

            # Dead modules (no dependents, not __init__.py, not test)
            report.dead_modules = sorted(
                n.module_path for n in self._nodes.values()
                if not n.imported_by and not n.is_init
                and n.category != "test"
            )

            # External dependencies
            ext_deps: dict[str, list[str]] = defaultdict(list)
            for n in self._nodes.values():
                for imp in n.imports:
                    if "." in imp:
                        pkg = imp.split(".")[0]
                    else:
                        pkg = imp
                    if pkg not in ("core", "index_app", "infrastructure", "scripts", "tests"):
                        if n.module_path not in ext_deps[pkg]:
                            ext_deps[pkg].append(n.module_path)
            report.external_dependencies = dict(ext_deps)

            # Coupling score: average instability
            instabilities = [n.instability for n in self._nodes.values()]
            report.coupling_score = round(
                sum(instabilities) / max(1, len(instabilities)), 3
            )

            # Stability score: proportion of modules with fan_in > fan_out
            stable_count = sum(1 for n in self._nodes.values() if n.fan_in >= n.fan_out)
            report.stability_score = round(
                stable_count / max(1, len(self._nodes)), 3
            )

            # Top imported (by fan_in)
            report.top_imported = sorted(
                [(n.module_path, n.fan_in) for n in self._nodes.values() if n.fan_in > 0],
                key=lambda x: -x[1],
            )[:20]

            # Top importers (by fan_out)
            report.top_importers = sorted(
                [(n.module_path, n.fan_out) for n in self._nodes.values() if n.fan_out > 0],
                key=lambda x: -x[1],
            )[:20]

        return report

    # ── Circular Dependency Detection ─────────────────────────────────────

    def _find_circular(self) -> list[list[str]]:
        """Find all circular dependencies using DFS with Tarjan-like approach.

        Returns a list of cycles, each cycle being a list of module paths.
        """
        visited: set[str] = set()
        in_stack: set[str] = set()
        stack: list[str] = []
        cycles: list[list[str]] = []

        def dfs(node_path: str) -> None:
            visited.add(node_path)
            in_stack.add(node_path)
            stack.append(node_path)

            node = self._nodes.get(node_path)
            if node:
                for imp in node.imports:
                    # Resolve import to module path
                    resolved = self._resolve_import(imp, node_path)
                    if resolved and resolved in self._nodes:
                        if resolved not in visited:
                            dfs(resolved)
                        elif resolved in in_stack:
                            # Found a cycle: extract it from stack
                            cycle_start = stack.index(resolved)
                            cycle = stack[cycle_start:] + [resolved]
                            # Normalize: ensure consistent ordering to avoid duplicates
                            if len(cycle) > 2:  # Ignore self-loops
                                cycles.append(cycle)

            stack.pop()
            in_stack.discard(node_path)

        for node_path in list(self._nodes.keys()):
            if node_path not in visited:
                dfs(node_path)

        # Deduplicate cycles that are permutations of each other
        seen_cycle_sets: set[str] = set()
        unique_cycles: list[list[str]] = []
        for cycle in cycles:
            # Normalize by rotating to smallest module
            min_idx = cycle.index(min(cycle))
            normalized = cycle[min_idx:] + cycle[1:min_idx + 1]
            key = "→".join(normalized)
            if key not in seen_cycle_sets:
                seen_cycle_sets.add(key)
                unique_cycles.append(normalized)

        return unique_cycles[:50]  # Cap at 50 cycles

    # ── Import Resolution ─────────────────────────────────────────────────

    def _resolve_import(self, import_name: str, from_module: str) -> str | None:
        """Resolve an import name to a module file path.

        E.g., 'core.di_container' → 'core/di_container.py'
        """
        # Direct match as module path
        candidate = import_name.replace(".", "/") + ".py"
        if candidate in self._nodes:
            return candidate

        # Try as package __init__
        candidate_init = import_name.replace(".", "/") + "/__init__.py"
        if candidate_init in self._nodes:
            return candidate_init

        # Try relative imports from the from_module
        if from_module:
            from_dir = "/".join(from_module.split("/")[:-1])
            if from_dir:
                candidate = f"{from_dir}/{import_name.replace('.', '/')}.py"
                if candidate in self._nodes:
                    return candidate

        return None

    # ── Parsing ───────────────────────────────────────────────────────────

    def _parse_imports(self, file_path: Path) -> set[str]:
        """Parse all import statements from a Python file."""
        imports: set[str] = set()
        try:
            tree = ast.parse(file_path.read_text(encoding="utf-8", errors="ignore"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        # Extract base package
                        base = alias.name.split(".")[0]
                        if base not in ("__future__", "__init__"):
                            imports.add(alias.name)
                elif isinstance(node, ast.ImportFrom):
                    if node.module and node.level is None or node.level == 0:
                        base = node.module.split(".")[0]
                        if base not in ("__future__", "__init__"):
                            imports.add(node.module)
                            for alias in node.names:
                                if alias.name and not alias.name.startswith("_"):
                                    imports.add(f"{node.module}.{alias.name}")
        except (SyntaxError, OSError) as exc:
            _log.debug("[DEP] Parse error in %s: %s", file_path, exc)
        return imports

    def _categorize(self, rel_path: str) -> str:
        """Categorize a module by its path prefix."""
        if rel_path.startswith("tests/"):
            return "test"
        if rel_path.startswith("infrastructure/"):
            return "infrastructure"
        if rel_path.startswith("scripts/"):
            return "scripts"
        if rel_path.startswith("index_app/"):
            return "app"
        if rel_path.startswith("core/"):
            # Sub-categorize core modules
            if rel_path.startswith("core/ports/"):
                return "core:ports"
            if rel_path.startswith("core/patterns/"):
                return "core:patterns"
            if rel_path.startswith("core/templates/"):
                return "core:templates"
            if rel_path.startswith("core/services/"):
                return "core:services"
            if rel_path.startswith("core/adapters/"):
                return "core:adapters"
            return "core"
        return "other"

    def _to_rel(self, path: Path) -> str:
        """Convert to relative path with forward slashes."""
        try:
            return str(path.relative_to(self._project_root)).replace("\\", "/")
        except ValueError:
            return str(path).replace("\\", "/")

    def _count_loc(self, file_path: Path) -> int:
        """Count non-empty, non-comment lines of code."""
        try:
            count = 0
            for line in file_path.read_text(encoding="utf-8", errors="ignore").splitlines():
                stripped = line.strip()
                if stripped and not stripped.startswith("#"):
                    count += 1
            return count
        except OSError:
            return 0

    # ── Public Query API ─────────────────────────────────────────────────

    def get_report(self) -> DependencyReport:
        """Get the full dependency report (builds if needed)."""
        return self.analyze()

    def get_stats(self) -> dict[str, Any]:
        """Get quick statistics without building the full report."""
        self.build()
        with self._lock:
            return {
                "total_modules": len(self._nodes),
                "total_edges": sum(len(n.imports) for n in self._nodes.values()),
                "total_core": sum(1 for n in self._nodes.values() if n.category == "core"),
                "total_tests": sum(1 for n in self._nodes.values() if n.category == "test"),
                "total_app": sum(1 for n in self._nodes.values() if n.category == "app"),
                "built": self._built,
            }

    def get_module_dependencies(self, module_path: str) -> list[str]:
        """Get sorted list of what a module imports."""
        self.build()
        with self._lock:
            node = self._nodes.get(module_path)
            if node:
                return sorted(node.imports)
            return []

    def get_module_dependents(self, module_path: str) -> list[str]:
        """Get sorted list of what imports a module."""
        self.build()
        with self._lock:
            node = self._nodes.get(module_path)
            if node:
                return sorted(node.imported_by)
            return []

    def get_circular_dependencies(self) -> list[list[str]]:
        """Get all circular dependency chains."""
        self.build()
        with self._lock:
            return self._find_circular()


# ── Singleton ───────────────────────────────────────────────────────────────

_instance: DependencyAnalyzer | None = None
_instance_lock = threading.RLock()


def get_dependency_analyzer() -> DependencyAnalyzer:
    """Return the process-level DependencyAnalyzer (creates on first call)."""
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = DependencyAnalyzer()
        return _instance


def reset_dependency_analyzer() -> None:
    """Force-reset singleton (for testing)."""
    global _instance
    with _instance_lock:
        _instance = None


__all__ = [
    "DependencyAnalyzer",
    "DependencyNode",
    "DependencyReport",
    "get_dependency_analyzer",
    "reset_dependency_analyzer",
]
