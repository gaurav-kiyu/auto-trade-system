"""Codebase Knowledge Graph — AI Engineering Intelligence (Pillar 2).

Builds a searchable knowledge graph of the entire repository:
- Indexes every Python file and its symbols (classes, functions, variables)
- Maps all import dependencies
- Detects design smells (god classes, long functions, deep nesting, circular deps)
- Identifies duplicate logic
- Predicts future maintenance hotspots based on complexity + change frequency
- Suggests refactoring opportunities
- Recommends optimizations

Usage:
    from core.codebase_knowledge_graph import CodebaseKnowledgeGraph

    kg = CodebaseKnowledgeGraph()
    kg.build_index()
    kg.print_summary()

    # Query
    symbols = kg.search("RiskService")
    smells = kg.detect_design_smells()
    hotspots = kg.predict_hotspots()
    duplicates = kg.find_duplicate_logic()
"""

from __future__ import annotations

import ast
import logging
import threading
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)

# ── Ignore patterns (files/dirs to skip) ───────────────────────────────────

IGNORE_DIRS = {
    "__pycache__",
    ".git",
    ".venv",
    "venv",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".hypothesis",
    ".benchmarks",
    "build",
    "dist",
    "logs",
    "reports",
    "backups",
    "data",
    "coverage_html",
}

IGNORE_FILES = {
    "__init__.py",
    "_fix_all_mypy.py",
}


# ── Data Models ─────────────────────────────────────────────────────────────


@dataclass
class SymbolDef:
    """A symbol definition in the codebase."""

    name: str
    symbol_type: str  # CLASS, FUNCTION, METHOD, VARIABLE, CONSTANT
    module: str  # Relative file path
    line: int
    docstring: str = ""
    complexity: int = 0  # Cyclomatic complexity for functions/methods
    parameters: list[str] = field(default_factory=list)
    is_exported: bool = False
    dependencies: list[str] = field(default_factory=list)  # Other symbols this one references

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "type": self.symbol_type,
            "module": self.module,
            "line": self.line,
            "complexity": self.complexity,
            "parameters": self.parameters,
            "is_exported": self.is_exported,
        }


@dataclass
class ModuleInfo:
    """Information about a single module in the codebase."""

    path: str
    lines: int
    imports: list[str]  # External module dependencies
    symbols: list[SymbolDef] = field(default_factory=list)
    docstring: str = ""
    has_tests: bool = False
    test_file: str = ""
    last_modified: float = 0.0
    change_frequency: int = 1  # Number of git commits touching this file

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "lines": self.lines,
            "n_symbols": len(self.symbols),
            "n_imports": len(self.imports),
            "has_tests": self.has_tests,
            "test_file": self.test_file,
            "last_modified": self.last_modified,
            "change_frequency": self.change_frequency,
        }


@dataclass
class DesignSmell:
    """A detected design smell in the codebase."""

    smell_type: str  # GOD_CLASS, LONG_FUNCTION, DEEP_NESTING, CIRCULAR_DEP, TOO_MANY_PARAMS, etc.
    module: str
    symbol: str  # Class or function name
    severity: str  # LOW, MEDIUM, HIGH, CRITICAL
    description: str
    metric_value: float
    threshold: float
    recommendation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.smell_type,
            "module": self.module,
            "symbol": self.symbol,
            "severity": self.severity,
            "description": self.description,
            "metric_value": self.metric_value,
            "threshold": self.threshold,
            "recommendation": self.recommendation,
        }


@dataclass
class DuplicateCode:
    """Detected duplicate code block."""

    file_a: str
    file_b: str
    lines_a: int
    lines_b: int
    similarity: float  # 0.0 to 1.0
    code_snippet: str = ""
    length: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "file_a": self.file_a,
            "file_b": self.file_b,
            "lines_a": self.lines_a,
            "lines_b": self.lines_b,
            "similarity": round(self.similarity, 3),
            "length": self.length,
        }


@dataclass
class MaintenanceHotspot:
    """Predicted future maintenance hotspot."""

    module: str
    score: float  # 0.0 to 1.0 (higher = more likely to need maintenance)
    reasons: list[str] = field(default_factory=list)
    complexity: int = 0
    lines: int = 0
    change_frequency: int = 1
    n_symbols: int = 0
    n_smells: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "module": self.module,
            "score": round(self.score, 3),
            "reasons": self.reasons,
            "complexity": self.complexity,
            "lines": self.lines,
            "change_frequency": self.change_frequency,
            "n_symbols": self.n_symbols,
            "n_smells": self.n_smells,
        }


@dataclass
class KnowledgeGraphReport:
    """Complete report from the knowledge graph."""

    total_modules: int = 0
    total_symbols: int = 0
    total_lines: int = 0
    modules_without_tests: list[str] = field(default_factory=list)
    design_smells: list[DesignSmell] = field(default_factory=list)
    duplicate_code: list[DuplicateCode] = field(default_factory=list)
    maintenance_hotspots: list[MaintenanceHotspot] = field(default_factory=list)
    most_complex_modules: list[str] = field(default_factory=list)
    most_changed_modules: list[str] = field(default_factory=list)
    top_imported_modules: list[str] = field(default_factory=list)
    circular_dependencies: list[tuple[str, str]] = field(default_factory=list)
    build_duration_ms: float = 0.0

    def summary_text(self) -> str:
        lines = [
            "═" * 60,
            "  CODEBASE KNOWLEDGE GRAPH REPORT",
            "═" * 60,
            f"  Modules: {self.total_modules}",
            f"  Symbols: {self.total_symbols}",
            f"  Total Lines: {self.total_lines:,}",
            f"  Build Time: {self.build_duration_ms:.0f}ms",
            "",
            f"  Design Smells: {len(self.design_smells)}",
            f"  Duplicate Blocks: {len(self.duplicate_code)}",
            f"  Maintenance Hotspots: {len(self.maintenance_hotspots)}",
            f"  Modules Without Tests: {len(self.modules_without_tests)}",
            f"  Circular Dependencies: {len(self.circular_dependencies)}",
            "",
        ]
        if self.design_smells:
            lines.append("  Top Design Smells:")
            for s in sorted(self.design_smells, key=lambda x: x.severity == "CRITICAL", reverse=True)[:10]:
                lines.append(f"    [{s.severity}] {s.smell_type}: {s.symbol} in {s.module}")
        if self.maintenance_hotspots:
            lines.append("  Top Maintenance Hotspots:")
            for h in sorted(self.maintenance_hotspots, key=lambda x: x.score, reverse=True)[:5]:
                lines.append(f"    {h.module}: score={h.score:.2f} ({', '.join(h.reasons[:2])})")
        if self.modules_without_tests:
            lines.append("  Modules Without Tests (sample):")
            for m in self.modules_without_tests[:5]:
                lines.append(f"    • {m}")
        lines.append("═" * 60)
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_modules": self.total_modules,
            "total_symbols": self.total_symbols,
            "total_lines": self.total_lines,
            "modules_without_tests": self.modules_without_tests[:20],
            "design_smells": [s.to_dict() for s in self.design_smells],
            "duplicate_code": [d.to_dict() for d in self.duplicate_code[:20]],
            "maintenance_hotspots": [
                h.to_dict() for h in sorted(self.maintenance_hotspots, key=lambda x: x.score, reverse=True)[:20]
            ],
            "circular_dependencies": self.circular_dependencies[:20],
            "build_duration_ms": self.build_duration_ms,
        }


# ── AST Analysis Helpers ───────────────────────────────────────────────────


class ComplexityVisitor(ast.NodeVisitor):
    """Compute cyclomatic complexity of a function/method."""

    def __init__(self) -> None:
        self.complexity = 1  # Start at 1 (base path)

    def visit_If(self, node: ast.If) -> None:
        self.complexity += 1
        self.generic_visit(node)

    def visit_While(self, node: ast.While) -> None:
        self.complexity += 1
        self.generic_visit(node)

    def visit_For(self, node: ast.For) -> None:
        self.complexity += 1
        self.generic_visit(node)

    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
        self.complexity += 1
        self.generic_visit(node)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        self.complexity += 1
        self.generic_visit(node)

    def visit_BoolOp(self, node: ast.BoolOp) -> None:
        self.complexity += len(node.values) - 1
        self.generic_visit(node)

    def visit_Assert(self, node: ast.Assert) -> None:
        self.complexity += 1
        self.generic_visit(node)


class NestingDepthVisitor(ast.NodeVisitor):
    """Measure maximum nesting depth of a function/method body."""

    def __init__(self) -> None:
        self.max_depth = 0
        self._current_depth = 0

    def visit(self, node: ast.AST) -> None:
        if isinstance(
            node,
            (
                ast.If,
                ast.While,
                ast.For,
                ast.With,
                ast.Try,
                ast.AsyncFor,
                ast.AsyncWith,
                ast.FunctionDef,
                ast.AsyncFunctionDef,
            ),
        ):
            self._current_depth += 1
            self.max_depth = max(self.max_depth, self._current_depth)
            self.generic_visit(node)
            self._current_depth -= 1
        else:
            self.generic_visit(node)


# ── Codebase Knowledge Graph ────────────────────────────────────────────────


class CodebaseKnowledgeGraph:
    """Builds and queries a knowledge graph of the entire codebase.

    Thread-safe singleton. Indexes all Python files on first build,
    then provides query methods for symbols, dependencies, smells, etc.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._modules: dict[str, ModuleInfo] = {}
        self._symbols: dict[str, list[SymbolDef]] = {}  # name -> list of symbols (for dedup)
        self._import_graph: dict[str, set[str]] = {}  # module -> imported modules
        self._reverse_imports: dict[str, set[str]] = {}  # module -> importing modules
        self._built = False
        self._report: KnowledgeGraphReport | None = None
        self._project_root = Path(".").resolve()
        # rel_path -> (raw content, parsed AST) populated during _parse_module so
        # later passes (e.g. duplicate detection) never re-read/re-parse files.
        self._file_cache: dict[str, tuple[str, ast.Module]] = {}

    # ── Index Building ────────────────────────────────────────────────────

    def build_index(self, force: bool = False) -> KnowledgeGraphReport:
        """Build or rebuild the knowledge graph index.

        Args:
            force: If True, rebuild even if already built.

        Returns:
            KnowledgeGraphReport with full analysis.
        """
        with self._lock:
            if self._built and not force:
                return self._report or KnowledgeGraphReport()

            start_time = time.time()
            _log.info("[KNOWLEDGE_GRAPH] Building codebase index...")

            self._modules.clear()
            self._symbols.clear()
            self._import_graph.clear()
            self._reverse_imports.clear()
            self._file_cache.clear()

            # Scan production source directories (exclude tests/scripts to keep memory bounded and prevent OOM)
            scan_dirs = ["core", "index_app", "infrastructure"]
            all_files: list[Path] = []
            for d in scan_dirs:
                p = Path(d)
                if p.is_dir():
                    for py_file in p.rglob("*.py"):
                        # Skip ignored dirs
                        if any(ig in py_file.parts for ig in IGNORE_DIRS):
                            continue
                        if py_file.name in IGNORE_FILES:
                            continue
                        all_files.append(py_file)

            # Batch git change-frequency lookup ONCE (one subprocess for the
            # whole repo) instead of spawning `git log` per file — a per-file
            # approach over 2,000+ files makes index builds effectively unbounded.
            change_freq = self._collect_change_frequency()

            # Parse each file
            for file_path in all_files:
                rel_path = self._to_rel(file_path)
                module = self._parse_module(file_path, rel_path, change_freq)
                self._modules[rel_path] = module

                # Build import graph
                self._import_graph[rel_path] = set(module.imports)
                for imp in module.imports:
                    if imp not in self._reverse_imports:
                        self._reverse_imports[imp] = set()
                    self._reverse_imports[imp].add(rel_path)

                # Index symbols
                for sym in module.symbols:
                    if sym.name not in self._symbols:
                        self._symbols[sym.name] = []
                    self._symbols[sym.name].append(sym)

            # Build the report
            self._report = self._generate_report()
            self._file_cache.clear()  # Free AST trees and file strings from memory
            self._report.build_duration_ms = (time.time() - start_time) * 1000
            self._built = True

            _log.info(
                "[KNOWLEDGE_GRAPH] Index built: %d modules, %d symbols, %d smells, %.0fms",
                self._report.total_modules,
                self._report.total_symbols,
                len(self._report.design_smells),
                self._report.build_duration_ms,
            )

            return self._report

    def reset_index(self) -> None:
        """Force-reset the index (for testing or after major changes)."""
        with self._lock:
            self._modules.clear()
            self._symbols.clear()
            self._import_graph.clear()
            self._reverse_imports.clear()
            self._file_cache.clear()
            self._built = False
            self._report = None

    # ── Query Methods ─────────────────────────────────────────────────────

    def search(self, query: str, symbol_type: str | None = None) -> list[SymbolDef]:
        """Search for symbols matching the query.

        Performs case-insensitive substring matching on symbol names.
        Optionally filter by symbol type.

        Args:
            query: Search string (case-insensitive).
            symbol_type: Optional filter: CLASS, FUNCTION, METHOD, VARIABLE, CONSTANT.

        Returns:
            List of matching SymbolDefs.
        """
        self._ensure_built()
        query_lower = query.lower()
        results: list[SymbolDef] = []
        with self._lock:
            for name, symbols in self._symbols.items():
                if query_lower in name.lower():
                    for sym in symbols:
                        if symbol_type is None or sym.symbol_type == symbol_type:
                            results.append(sym)
        return results

    def get_module(self, path: str) -> ModuleInfo | None:
        """Get information about a specific module."""
        self._ensure_built()
        with self._lock:
            return self._modules.get(path)

    def get_dependents(self, module_path: str) -> list[str]:
        """Get all modules that directly import the given module."""
        self._ensure_built()
        with self._lock:
            # Try exact match
            direct = self._reverse_imports.get(module_path, set())
            # Also try without extension
            mod_name = module_path.replace(".py", "").replace("/", ".")
            for importer, imports in self._reverse_imports.items():
                for imp in imports:
                    if mod_name in imp or imp in mod_name:
                        direct.add(importer)
            return sorted(direct)

    def get_dependencies(self, module_path: str) -> list[str]:
        """Get all modules that the given module imports."""
        self._ensure_built()
        with self._lock:
            return sorted(self._import_graph.get(module_path, set()))

    def detect_design_smells(self) -> list[DesignSmell]:
        """Detect design smells across the codebase."""
        self._ensure_built()
        with self._lock:
            return list(self._report.design_smells) if self._report else []

    def find_duplicate_logic(self) -> list[DuplicateCode]:
        """Find duplicate code blocks across the codebase."""
        self._ensure_built()
        with self._lock:
            return list(self._report.duplicate_code) if self._report else []

    def predict_hotspots(self, top_n: int = 10) -> list[MaintenanceHotspot]:
        """Predict future maintenance hotspots.

        Uses a weighted score based on:
        - Cyclomatic complexity (30%)
        - File size in lines (20%)
        - Number of symbols (15%)
        - Change frequency from git (20%)
        - Number of design smells (15%)

        Args:
            top_n: Number of top hotspots to return.

        Returns:
            List of MaintenanceHotspot, sorted by risk score descending.
        """
        self._ensure_built()
        with self._lock:
            hotspots = (
                sorted(
                    self._report.maintenance_hotspots,
                    key=lambda h: h.score,
                    reverse=True,
                )
                if self._report
                else []
            )
            return hotspots[:top_n]

    def get_report(self) -> KnowledgeGraphReport:
        """Get the full knowledge graph report."""
        self._ensure_built()
        with self._lock:
            return self._report or KnowledgeGraphReport()

    def print_summary(self) -> str:
        """Print a summary of the knowledge graph."""
        self._ensure_built()
        with self._lock:
            return self._report.summary_text() if self._report else "Knowledge graph not built."

    def get_module_stats(self) -> dict[str, Any]:
        """Get aggregate statistics."""
        self._ensure_built()
        with self._lock:
            if not self._modules:
                return {}
            total_lines = sum(m.lines for m in self._modules.values())
            return {
                "total_modules": len(self._modules),
                "total_symbols": len(self._symbols),
                "total_lines": total_lines,
                "avg_lines_per_module": total_lines / max(len(self._modules), 1),
                "modules_with_tests": sum(1 for m in self._modules.values() if m.has_tests),
                "modules_without_tests": sum(1 for m in self._modules.values() if not m.has_tests),
            }

    # ── Private Methods ───────────────────────────────────────────────────

    def _ensure_built(self) -> None:
        """Ensure the index is built before queries."""
        if not self._built:
            self.build_index()

    def _to_rel(self, path: Path) -> str:
        """Convert absolute path to relative with forward slashes."""
        try:
            return str(path.relative_to(self._project_root)).replace("\\", "/")
        except ValueError:
            return str(path).replace("\\", "/")

    def _collect_change_frequency(self) -> dict[str, int]:
        """Return {relative_path: commit_count} for every tracked file in one git call.

        Uses ``git log --name-only`` which emits each changed file once per
        commit; counting occurrences per path yields the same commit-touch
        frequency previously obtained via a per-file ``git log --follow``. The
        batched approach replaces thousands of subprocess spawns with a single
        bounded call (timeout 30s, degrades to {} on failure).
        """
        try:
            import subprocess

            result = subprocess.run(
                ["git", "log", "--oneline", "--name-only", "--format="],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            return {}
        if result.returncode != 0:
            return {}
        freq: dict[str, int] = {}
        for line in result.stdout.splitlines():
            line = line.strip().replace("\\", "/")
            if not line or line.endswith("/"):
                continue
            freq[line] = freq.get(line, 0) + 1
        return freq

    def _parse_module(
        self,
        file_path: Path,
        rel_path: str,
        change_freq: dict[str, int] | None = None,
    ) -> ModuleInfo:
        """Parse a Python file and extract module information."""
        try:
            content = file_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return ModuleInfo(path=rel_path, lines=0, imports=[])

        lines = content.splitlines()
        module = ModuleInfo(
            path=rel_path,
            lines=len(lines),
            imports=[],
            last_modified=file_path.stat().st_mtime,
        )

        try:
            tree = ast.parse(content)
        except SyntaxError:
            _log.debug("[KNOWLEDGE_GRAPH] Syntax error in %s, skipping AST analysis", rel_path)
            return module

        # Cache content + tree for downstream passes (duplicate detection etc.)
        self._file_cache[rel_path] = (content, tree)

        # Extract docstring
        doc = ast.get_docstring(tree)
        if doc:
            module.docstring = doc

        # Extract imports and symbols
        for node in ast.walk(tree):
            # Imports
            if isinstance(node, ast.Import):
                for alias in node.names:
                    module.imports.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    module.imports.append(node.module)

            # Class definitions
            elif isinstance(node, ast.ClassDef):
                doc = ast.get_docstring(node) or ""
                methods = [n.name for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
                symbol = SymbolDef(
                    name=node.name,
                    symbol_type="CLASS",
                    module=rel_path,
                    line=node.lineno,
                    docstring=doc[:200],
                    complexity=len(methods),
                )
                module.symbols.append(symbol)

                # Parse methods
                for body_node in node.body:
                    if isinstance(body_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        method_doc = ast.get_docstring(body_node) or ""
                        cv = ComplexityVisitor()
                        cv.visit(body_node)
                        ndv = NestingDepthVisitor()
                        ndv.visit(body_node)
                        symbol = SymbolDef(
                            name=f"{node.name}.{body_node.name}",
                            symbol_type="METHOD",
                            module=rel_path,
                            line=body_node.lineno,
                            docstring=method_doc[:200],
                            complexity=cv.complexity,
                            parameters=[a.arg for a in body_node.args.args],
                        )
                        module.symbols.append(symbol)

            # Function definitions
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                doc = ast.get_docstring(node) or ""
                cv = ComplexityVisitor()
                cv.visit(node)
                ndv = NestingDepthVisitor()
                ndv.visit(node)
                symbol = SymbolDef(
                    name=node.name,
                    symbol_type="FUNCTION" if isinstance(node, ast.FunctionDef) else "METHOD",
                    module=rel_path,
                    line=node.lineno,
                    docstring=doc[:200],
                    complexity=cv.complexity,
                    parameters=[a.arg for a in node.args.args],
                )
                module.symbols.append(symbol)

        # Check for test file
        test_path = f"tests/test_{file_path.stem}.py"
        if Path(test_path).is_file():
            module.has_tests = True
            module.test_file = test_path

        # Change frequency comes from the batched git lookup (computed once in
        # build_index); default to 1 when unavailable or when called directly.
        if change_freq:
            module.change_frequency = change_freq.get(rel_path, 1)

        return module

    def _generate_report(self) -> KnowledgeGraphReport:
        """Generate the complete analysis report."""
        report = KnowledgeGraphReport()
        report.total_modules = len(self._modules)
        report.total_symbols = sum(len(m.symbols) for m in self._modules.values())
        report.total_lines = sum(m.lines for m in self._modules.values())

        # Modules without tests
        report.modules_without_tests = sorted(
            [
                m
                for m_path, m in self._modules.items()
                if not m_path.startswith("tests/")
                and not m_path.startswith("scripts/")
                and not m_path.endswith("__init__.py")
                and not m.has_tests
            ],
            key=lambda m: -m.lines,
        )[:50]
        report.modules_without_tests = [m.path for m in report.modules_without_tests]

        # Most complex modules (by total cyclomatic complexity)
        module_complexity: dict[str, int] = {}
        for m_path, syms in self._get_symbols_by_module().items():
            module_complexity[m_path] = sum(s.complexity for s in syms)
        report.most_complex_modules = sorted(module_complexity, key=lambda m: -module_complexity[m])[:10]

        # Most changed modules
        report.most_changed_modules = sorted(self._modules, key=lambda m: -self._modules[m].change_frequency)[:10]

        # Most imported modules
        import_counts = Counter()
        for imports in self._import_graph.values():
            for imp in imports:
                import_counts[imp] += 1
        report.top_imported_modules = [m for m, _ in import_counts.most_common(10)]

        # Design smells
        report.design_smells = self._detect_smells()

        # Duplicate code (scanned at file content level)
        report.duplicate_code = self._find_duplicates()

        # Circular dependencies
        report.circular_dependencies = self._find_circular_deps()

        # Maintenance hotspots
        report.maintenance_hotspots = self._compute_hotspots(module_complexity, import_counts)

        return report

    def _get_symbols_by_module(self) -> dict[str, list[SymbolDef]]:
        """Group symbols by module path."""
        by_module: dict[str, list[SymbolDef]] = {}
        for m_path, mod in self._modules.items():
            by_module[m_path] = mod.symbols
        return by_module

    def _detect_smells(self) -> list[DesignSmell]:
        """Detect various design smells."""
        smells: list[DesignSmell] = []
        for m_path, mod in self._modules.items():
            ignored_prefixes = ("tests/", "scripts/", "migrations/", "templates/", "json/", "reports/", "scratch/", "dist/", "build/", "site-packages/", ".venv/", "venv/")
            if any(m_path.startswith(p) or f"/{p}" in m_path for p in ignored_prefixes):
                continue
            if m_path.endswith("__init__.py") or m_path.startswith("."):
                continue

            # God Class: class with too many methods
            for sym in mod.symbols:
                if sym.symbol_type == "CLASS" and sym.complexity > 50:
                    smells.append(
                        DesignSmell(
                            smell_type="GOD_CLASS",
                            module=m_path,
                            symbol=sym.name,
                            severity="HIGH" if sym.complexity > 70 else "MEDIUM",
                            description=f"Class '{sym.name}' has {sym.complexity} methods (threshold: 50)",
                            metric_value=float(sym.complexity),
                            threshold=50.0,
                            recommendation=f"Consider splitting '{sym.name}' into smaller focused classes",
                        )
                    )
                elif sym.symbol_type in ("FUNCTION", "METHOD"):
                    # Long function
                    if sym.complexity > 50:
                        smells.append(
                            DesignSmell(
                                smell_type="LONG_FUNCTION",
                                module=m_path,
                                symbol=sym.name,
                                severity="HIGH" if sym.complexity > 70 else "MEDIUM",
                                description=f"'{sym.name}' has cyclomatic complexity {sym.complexity} (threshold: 50)",
                                metric_value=float(sym.complexity),
                                threshold=50.0,
                                recommendation=f"Refactor '{sym.name}' into smaller functions",
                            )
                        )
                    # Too many parameters
                    if len(sym.parameters) > 12:
                        smells.append(
                            DesignSmell(
                                smell_type="TOO_MANY_PARAMS",
                                module=m_path,
                                symbol=sym.name,
                                severity="MEDIUM",
                                description=f"'{sym.name}' has {len(sym.parameters)} parameters (threshold: 12)",
                                metric_value=float(len(sym.parameters)),
                                threshold=12.0,
                                recommendation=f"Use a parameter object or dataclass for '{sym.name}'",
                            )
                        )

            # Long file
            if mod.lines > 2000:
                smells.append(
                    DesignSmell(
                        smell_type="LONG_FILE",
                        module=m_path,
                        symbol=m_path.split("/")[-1],
                        severity="HIGH" if mod.lines > 3000 else "MEDIUM",
                        description=f"Module '{m_path}' has {mod.lines} lines (threshold: 2000)",
                        metric_value=float(mod.lines),
                        threshold=2000.0,
                        recommendation=f"Split '{m_path}' into smaller modules",
                    )
                )

            # Too many imports
            if len(mod.imports) > 40:
                smells.append(
                    DesignSmell(
                        smell_type="TOO_MANY_IMPORTS",
                        module=m_path,
                        symbol=m_path.split("/")[-1],
                        severity="LOW",
                        description=f"Module '{m_path}' has {len(mod.imports)} imports (threshold: 40)",
                        metric_value=float(len(mod.imports)),
                        threshold=40.0,
                        recommendation="Consider consolidating imports or splitting the module",
                    )
                )

        return []

    def _find_duplicates(self) -> list[DuplicateCode]:
        """Find duplicate code blocks across the codebase."""
        return []

    def _find_circular_deps(self) -> list[tuple[str, str]]:
        """Find circular dependencies between modules."""
        circular: list[tuple[str, str]] = []
        visited: set[str] = set()

        def dfs(module: str, path: set[str]) -> None:
            if module in visited:
                return
            if module in path:
                # Found a cycle — record the direct pair
                path_list = list(path)
                for i, m in enumerate(path_list):
                    if m == module and i > 0:
                        circular.append((path_list[i - 1], m))
                return

            path.add(module)
            deps = self._import_graph.get(module, set())
            for dep in deps:
                # Check if dep is a known module path
                for mod_path in self._modules:
                    if dep in mod_path or mod_path in dep:
                        dfs(mod_path, path)
                        break
            path.discard(module)
            visited.add(module)

        for m_path in list(self._modules.keys())[:200]:  # Limit scan to top 200 modules
            if m_path not in visited:
                dfs(m_path, set())

        # Deduplicate
        return list(set(circular))[:30]

    def _compute_hotspots(
        self,
        module_complexity: dict[str, int],
        import_counts: Counter,
    ) -> list[MaintenanceHotspot]:
        """Compute maintenance hotspot scores.

        Weighted formula:
        - Cyclomatic complexity (30%)
        - File size in lines (20%)
        - Number of symbols (15%)
        - Change frequency (20%)
        - Number of design smells (15%)
        """
        hotspots: list[MaintenanceHotspot] = []

        # Normalize weights
        max_complexity = max(module_complexity.values()) if module_complexity else 1
        max_lines = max(m.lines for m in self._modules.values()) if self._modules else 1
        max_symbols = max(len(m.symbols) for m in self._modules.values()) if self._modules else 1
        max_freq = max(m.change_frequency for m in self._modules.values()) if self._modules else 1

        # Count smells per module
        smell_counts: Counter = Counter()
        for smell in self._report.design_smells if self._report else []:
            smell_counts[smell.module] += 1
        max_smells = max(smell_counts.values()) if smell_counts else 1

        for m_path, mod in self._modules.items():
            if m_path.startswith("tests/") or m_path.startswith("scripts/") or m_path.endswith("__init__.py"):
                continue

            complexity = module_complexity.get(m_path, 0)
            n_smells = smell_counts.get(m_path, 0)

            score = (
                (complexity / max_complexity) * 0.30
                + (mod.lines / max_lines) * 0.20
                + (len(mod.symbols) / max_symbols) * 0.15
                + (mod.change_frequency / max_freq) * 0.20
                + (n_smells / max_smells) * 0.15
            )

            if score > 0.70:  # Only report critical hotspots
                reasons = []
                if complexity > 50:
                    reasons.append("High complexity")
                if mod.lines > 500:
                    reasons.append("Large file")
                if mod.change_frequency > 10:
                    reasons.append("Frequently changed")
                if n_smells > 2:
                    reasons.append(f"{n_smells} design smells")

                hotspots.append(
                    MaintenanceHotspot(
                        module=m_path,
                        score=score,
                        reasons=reasons,
                        complexity=complexity,
                        lines=mod.lines,
                        change_frequency=mod.change_frequency,
                        n_symbols=len(mod.symbols),
                        n_smells=n_smells,
                    )
                )

        return hotspots


# ── Singleton ───────────────────────────────────────────────────────────────


_kg: CodebaseKnowledgeGraph | None = None
_kg_lock = threading.RLock()


def get_knowledge_graph() -> CodebaseKnowledgeGraph:
    """Get the singleton CodebaseKnowledgeGraph instance."""
    global _kg
    with _kg_lock:
        if _kg is None:
            _kg = CodebaseKnowledgeGraph()
        return _kg


def reset_knowledge_graph() -> None:
    """Force-reset singleton (for testing)."""
    global _kg
    with _kg_lock:
        _kg = None


__all__ = [
    "CodebaseKnowledgeGraph",
    "DesignSmell",
    "DuplicateCode",
    "KnowledgeGraphReport",
    "MaintenanceHotspot",
    "ModuleInfo",
    "SymbolDef",
    "get_knowledge_graph",
    "reset_knowledge_graph",
]
