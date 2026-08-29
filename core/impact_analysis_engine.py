"""Intelligent Impact Analysis Engine (Pillar 4).

Automatically determines the blast radius of any file change:
- Which APIs are affected
- Which UI screens are affected
- Which services depend on it
- Which database objects are impacted
- Which tests need to run
- Which documentation needs updating
- Business impact
- Technical impact
- Estimated regression risk

Integrates with DataLineageEngine, ChangeManager, and the enterprise dashboard.

Usage:
    from core.impact_analysis_engine import ImpactAnalysisEngine

    engine = ImpactAnalysisEngine()
    report = engine.analyze_change("core/risk_service.py")
    print(report.summary())
    print(report.affected_apis)
    print(report.regression_risk)
"""

from __future__ import annotations

import ast
import logging
import re
import threading
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)


# ── Data Models ──────────────────────────────────────────────────────────────


@dataclass
class AffectedAPI:
    """An API endpoint affected by a change."""

    route: str
    method: str  # GET, POST, PUT, DELETE
    module: str  # Source file where this route is defined
    impact: str = "MODERATE"  # LOW, MODERATE, HIGH, CRITICAL


@dataclass
class AffectedService:
    """A service module affected by a change."""

    module: str
    class_name: str | None = None
    function_name: str | None = None
    impact: str = "MODERATE"


@dataclass
class AffectedDatabaseObject:
    """A database table or schema object affected by a change."""

    name: str
    type: str  # TABLE, INDEX, VIEW, TRIGGER
    operation: str = "READ"  # READ, WRITE, MIGRATE
    impact: str = "MODERATE"


@dataclass
class AffectedTestFile:
    """A test file that should be run after a change."""

    path: str
    relevance: str = "DIRECT"  # DIRECT, INDIRECT, COVERAGE
    priority: str = "HIGH"  # HIGH, MEDIUM, LOW


@dataclass
class AffectedDocumentation:
    """A documentation file that may need updating."""

    path: str
    section: str | None = None
    reason: str = ""


@dataclass
class ImpactReport:
    """Complete impact analysis report for a single change."""

    changed_file: str
    change_type: str  # ADD, MODIFY, DELETE, RENAME
    affected_apis: list[AffectedAPI] = field(default_factory=list)
    affected_services: list[AffectedService] = field(default_factory=list)
    affected_db_objects: list[AffectedDatabaseObject] = field(default_factory=list)
    affected_ui_screens: list[str] = field(default_factory=list)
    affected_tests: list[AffectedTestFile] = field(default_factory=list)
    affected_documentation: list[AffectedDocumentation] = field(default_factory=list)
    import_dependencies: list[str] = field(default_factory=list)  # files that import this module
    export_dependencies: list[str] = field(default_factory=list)  # files this module imports
    business_impact: str = "LOW"  # LOW, MEDIUM, HIGH, CRITICAL
    technical_impact: str = "LOW"
    regression_risk: str = "LOW"  # LOW, MEDIUM, HIGH, CRITICAL
    estimated_effort_minutes: int = 0
    recommended_actions: list[str] = field(default_factory=list)
    n_tests_to_run: int = 0
    n_docs_to_update: int = 0
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "changed_file": self.changed_file,
            "change_type": self.change_type,
            "affected_apis": [
                {"route": a.route, "method": a.method, "module": a.module, "impact": a.impact}
                for a in self.affected_apis
            ],
            "affected_services": [
                {"module": s.module, "class": s.class_name, "function": s.function_name, "impact": s.impact}
                for s in self.affected_services
            ],
            "affected_db_objects": [
                {"name": d.name, "type": d.type, "operation": d.operation, "impact": d.impact}
                for d in self.affected_db_objects
            ],
            "affected_ui_screens": self.affected_ui_screens,
            "affected_tests": [
                {"path": t.path, "relevance": t.relevance, "priority": t.priority} for t in self.affected_tests
            ],
            "affected_documentation": [
                {"path": d.path, "section": d.section, "reason": d.reason} for d in self.affected_documentation
            ],
            "import_dependencies": self.import_dependencies,
            "export_dependencies": self.export_dependencies,
            "business_impact": self.business_impact,
            "technical_impact": self.technical_impact,
            "regression_risk": self.regression_risk,
            "estimated_effort_minutes": self.estimated_effort_minutes,
            "recommended_actions": self.recommended_actions,
            "n_tests_to_run": self.n_tests_to_run,
            "n_docs_to_update": self.n_docs_to_update,
            "summary": self.summary,
        }

    def summary_text(self) -> str:
        lines = [
            "═" * 60,
            f"  IMPACT ANALYSIS: {self.changed_file}",
            "═" * 60,
            f"  Type: {self.change_type}",
            f"  Business Impact: {self.business_impact}",
            f"  Technical Impact: {self.technical_impact}",
            f"  Regression Risk: {self.regression_risk}",
            f"  Est. Effort: {self.estimated_effort_minutes} min",
            "",
        ]
        if self.affected_apis:
            lines.append(f"  APIs Affected ({len(self.affected_apis)}):")
            for a in self.affected_apis[:10]:
                lines.append(f"    [{a.impact}] {a.method} {a.route}")
        if self.affected_services:
            lines.append(f"  Services Affected ({len(self.affected_services)}):")
            for s in self.affected_services[:10]:
                lines.append(f"    [{s.impact}] {s.module}")
        if self.affected_db_objects:
            lines.append(f"  DB Objects Affected ({len(self.affected_db_objects)}):")
            for d in self.affected_db_objects[:5]:
                lines.append(f"    [{d.impact}] {d.name} ({d.type}, {d.operation})")
        if self.affected_tests:
            lines.append(f"  Tests to Run ({len(self.affected_tests)}):")
            for t in self.affected_tests[:10]:
                lines.append(f"    [{t.priority}] {t.path}")
        if self.affected_documentation:
            lines.append(f"  Docs to Update ({len(self.affected_documentation)}):")
            for d in self.affected_documentation[:5]:
                lines.append(f"    {d.path}")
        if self.recommended_actions:
            lines.append("  Recommended Actions:")
            for r in self.recommended_actions[:5]:
                lines.append(f"    → {r}")
        lines.append(f"  {self.summary}")
        lines.append("═" * 60)
        return "\n".join(lines)


# ── Impact Analysis Engine ─────────────────────────────────────────────────


class ImpactAnalysisEngine:
    """Intelligent Impact Analysis Engine.

    Analyzes file changes to determine:
    - Which APIs, services, DB objects, UI screens, tests, and docs are affected
    - Business and technical impact levels
    - Regression risk estimation
    - Recommended actions

    Builds and maintains a dependency graph of the entire codebase.
    Thread-safe singleton.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._dependency_graph: dict[str, set[str]] = {}  # module -> set of modules it imports
        self._reverse_graph: dict[str, set[str]] = {}  # module -> set of modules that import it
        self._api_route_map: dict[str, list[dict[str, str]]] = {}  # module -> [{route, method}]
        self._test_map: dict[str, list[str]] = {}  # module -> [test_file_paths]
        self._doc_map: dict[str, list[str]] = {}  # module -> [doc_file_paths]
        self._db_object_map: dict[str, list[dict[str, str]]] = {}  # module -> [{name, type, operation}]
        self._ui_screen_map: dict[str, list[str]] = {}  # module -> [screen_names]
        self._graph_built = False
        self._project_root = Path(".").resolve()

    # ── Graph Building ────────────────────────────────────────────────────

    def build_dependency_graph(self) -> None:
        """Build the full dependency graph of the codebase.

        Scans all Python files in core/, index_app/, infrastructure/, scripts/.
        Thread-safe; builds only once unless force=True.
        """
        with self._lock:
            if self._graph_built:
                return

            _log.info("[IMPACT] Building dependency graph...")
            scan_dirs = ["core", "index_app", "infrastructure", "scripts"]
            all_files: list[Path] = []
            for d in scan_dirs:
                p = Path(d)
                if p.is_dir():
                    all_files.extend(p.rglob("*.py"))

            for file_path in all_files:
                rel_path = self._to_rel(file_path)
                imports = self._parse_imports(file_path)
                self._dependency_graph[rel_path] = imports

                # Build reverse graph
                for imp in imports:
                    if imp not in self._reverse_graph:
                        self._reverse_graph[imp] = set()
                    self._reverse_graph[imp].add(rel_path)

                # Parse API routes
                routes = self._parse_api_routes(file_path)
                if routes:
                    self._api_route_map[rel_path] = routes

                # Parse DB operations
                db_ops = self._parse_db_operations(file_path)
                if db_ops:
                    self._db_object_map[rel_path] = db_ops

            # Build test map (tests/ directory)
            test_dir = Path("tests")
            if test_dir.is_dir():
                for test_file in test_dir.rglob("test_*.py"):
                    test_rel = self._to_rel(test_file)
                    tested_modules = self._parse_tested_modules(test_file)
                    for mod in tested_modules:
                        if mod not in self._test_map:
                            self._test_map[mod] = []
                        self._test_map[mod].append(test_rel)

            # Build doc map (docs/ directory)
            doc_dir = Path("docs")
            if doc_dir.is_dir():
                for doc_file in doc_dir.rglob("*.md"):
                    doc_rel = self._to_rel(doc_file)
                    referenced_modules = self._parse_doc_references(doc_file)
                    for mod in referenced_modules:
                        if mod not in self._doc_map:
                            self._doc_map[mod] = []
                        self._doc_map[mod].append(doc_rel)

            # Build UI screen map
            gui_dir = Path("index_app/gui")
            if gui_dir.is_dir():
                for gui_file in gui_dir.rglob("*.py"):
                    gui_rel = self._to_rel(gui_file)
                    screens = self._parse_ui_screens(gui_file)
                    if screens:
                        self._ui_screen_map[gui_rel] = screens

            self._graph_built = True
            _log.info(
                "[IMPACT] Dependency graph built: %d modules, %d test mappings, %d API routes",
                len(self._dependency_graph),
                sum(len(v) for v in self._test_map.values()),
                sum(len(v) for v in self._api_route_map.values()),
            )

    def reset_graph(self) -> None:
        """Force-reset the dependency graph (for testing or after major changes)."""
        with self._lock:
            self._dependency_graph.clear()
            self._reverse_graph.clear()
            self._api_route_map.clear()
            self._test_map.clear()
            self._doc_map.clear()
            self._db_object_map.clear()
            self._ui_screen_map.clear()
            self._graph_built = False

    # ── Analysis ──────────────────────────────────────────────────────────

    def analyze_change(
        self,
        changed_file: str,
        change_type: str = "MODIFY",
    ) -> ImpactReport:
        """Analyze the impact of a file change.

        Thread-safe: acquires the internal lock to protect reads of
        shared dependency graph data structures.

        Args:
            changed_file: Relative path to the changed file (e.g., 'core/risk_service.py').
            change_type: Type of change: ADD, MODIFY, DELETE, RENAME.

        Returns:
            ImpactReport with all affected items and risk assessment.
        """
        self.build_dependency_graph()
        rel_path = changed_file.replace("\\", "/")

        report = ImpactReport(
            changed_file=rel_path,
            change_type=change_type,
        )

        with self._lock:
            # 1. Find export dependencies (what this file imports)
            report.export_dependencies = list(self._dependency_graph.get(rel_path, set()))

            # 2. Find import dependencies (what imports this file)
            report.import_dependencies = list(self._reverse_graph.get(rel_path, set()))
        # Also search for the module without .py extension
        module_name = rel_path.replace(".py", "").replace("/", ".")
        for importer, imports in list(self._reverse_graph.items()):
            if module_name in imports:
                if importer not in report.import_dependencies:
                    report.import_dependencies.append(importer)
            # Also check for partial matches (e.g., "core.risk" imports "core.risk_service")
            for imp in imports:
                if module_name in imp or imp in module_name:
                    if importer not in report.import_dependencies:
                        report.import_dependencies.append(importer)

        # 3. Find all transitive dependents (recursive reverse lookup)
        all_dependents = self._find_transitive_dependents(rel_path)

        # 4. Find affected services (all transitive dependents)
        for dep in sorted(all_dependents):
            report.affected_services.append(
                AffectedService(
                    module=dep,
                    impact="HIGH" if dep in report.import_dependencies else "MODERATE",
                )
            )

        # 5. Find affected APIs
        seen_routes: set[str] = set()
        for dep in all_dependents:
            routes = self._api_route_map.get(dep, [])
            for route in routes:
                route_key = f"{route['method']}:{route['route']}"
                if route_key not in seen_routes:
                    seen_routes.add(route_key)
                    report.affected_apis.append(
                        AffectedAPI(
                            route=route["route"],
                            method=route["method"],
                            module=dep,
                            impact="HIGH" if dep in report.import_dependencies else "MODERATE",
                        )
                    )

        # 6. Find affected DB objects
        seen_db: set[str] = set()
        for dep in all_dependents:
            db_ops = self._db_object_map.get(dep, [])
            for db_obj in db_ops:
                if db_obj["name"] not in seen_db:
                    seen_db.add(db_obj["name"])
                    report.affected_db_objects.append(
                        AffectedDatabaseObject(
                            name=db_obj["name"],
                            type=db_obj.get("type", "TABLE"),
                            operation=db_obj.get("operation", "READ"),
                            impact="HIGH" if db_obj.get("operation") == "WRITE" else "MODERATE",
                        )
                    )

        # 7. Find affected UI screens
        seen_ui: set[str] = set()
        for dep in all_dependents:
            screens = self._ui_screen_map.get(dep, [])
            for screen in screens:
                if screen not in seen_ui:
                    seen_ui.add(screen)
                    report.affected_ui_screens.append(screen)

        # 8. Find affected tests
        seen_tests: set[str] = set()
        # Direct tests for the changed file
        for test_file in self._test_map.get(rel_path, []):
            if test_file not in seen_tests:
                seen_tests.add(test_file)
                report.affected_tests.append(
                    AffectedTestFile(
                        path=test_file,
                        relevance="DIRECT",
                        priority="HIGH",
                    )
                )
        # Tests for all dependent modules
        for dep in all_dependents:
            for test_file in self._test_map.get(dep, []):
                if test_file not in seen_tests:
                    seen_tests.add(test_file)
                    relevance = "DIRECT" if dep in report.import_dependencies else "INDIRECT"
                    priority = "HIGH" if relevance == "DIRECT" else "MEDIUM"
                    report.affected_tests.append(
                        AffectedTestFile(
                            path=test_file,
                            relevance=relevance,
                            priority=priority,
                        )
                    )

        # Also find tests matching by naming convention
        base_name = Path(rel_path).stem
        expected_test = f"tests/test_{base_name}.py"
        test_path = Path(expected_test)
        if test_path.is_file() and expected_test not in seen_tests:
            report.affected_tests.append(
                AffectedTestFile(
                    path=expected_test,
                    relevance="DIRECT",
                    priority="HIGH",
                )
            )

        # 9. Find affected documentation
        seen_docs: set[str] = set()
        for dep in all_dependents:
            for doc_file in self._doc_map.get(dep, []):
                if doc_file not in seen_docs:
                    seen_docs.add(doc_file)
                    report.affected_documentation.append(
                        AffectedDocumentation(
                            path=doc_file,
                            reason=f"References affected module: {dep}",
                        )
                    )
        # Also check README, CHANGELOG, and other root docs
        root_docs = ["README.md", "CLAUDE.md", "CHANGELOG.md", "docs/README.md"]
        for rd in root_docs:
            p = Path(rd)
            if p.is_file():
                content = p.read_text(encoding="utf-8", errors="ignore")
                if rel_path in content or module_name in content:
                    if rd not in seen_docs:
                        seen_docs.add(rd)
                        report.affected_documentation.append(
                            AffectedDocumentation(
                                path=rd,
                                reason=f"Contains references to {rel_path}",
                            )
                        )

        # 10. Assess impact levels
        report.business_impact = self._assess_business_impact(report)
        report.technical_impact = self._assess_technical_impact(report)
        report.regression_risk = self._assess_regression_risk(report)

        # 11. Estimate effort
        report.estimated_effort_minutes = self._estimate_effort(report)

        # 12. Generate recommendations
        report.recommended_actions = self._generate_recommendations(report)

        # 13. Summary
        report.n_tests_to_run = len(report.affected_tests)
        report.n_docs_to_update = len(report.affected_documentation)
        report.summary = (
            f"Change to {rel_path} affects {len(report.affected_services)} service(s), "
            f"{len(report.affected_apis)} API(s), "
            f"{len(report.affected_db_objects)} DB object(s), "
            f"{len(report.affected_tests)} test(s), "
            f"{len(report.affected_documentation)} doc(s). "
            f"Risk: {report.regression_risk}. "
            f"Est. effort: {report.estimated_effort_minutes} min."
        )

        return report

    # ── Private Helpers ───────────────────────────────────────────────────

    def _to_rel(self, path: Path) -> str:
        """Convert a file path to a relative path with forward slashes."""
        try:
            return str(path.relative_to(self._project_root)).replace("\\", "/")
        except ValueError:
            return str(path).replace("\\", "/")

    def _parse_imports(self, file_path: Path) -> set[str]:
        """Parse Python import statements from a file.

        Returns a set of module paths that this file imports.
        """
        imports: set[str] = set()
        try:
            tree = ast.parse(file_path.read_text(encoding="utf-8", errors="ignore"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        imports.add(alias.name)
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        imports.add(node.module)
                        # Also add the base module
                        parts = node.module.split(".")
                        if len(parts) > 1:
                            imports.add(parts[0])
        except (SyntaxError, OSError) as exc:
            _log.debug("[IMPACT] Parse error in %s: %s", file_path, exc)
        return imports

    def _parse_api_routes(self, file_path: Path) -> list[dict[str, str]]:
        """Parse FastAPI route decorators from a file."""
        routes: list[dict[str, str]] = []
        try:
            content = file_path.read_text(encoding="utf-8", errors="ignore")
            # Match @app.get(...), @app.post(...), @router.get(...), etc.
            pattern = r'@(?:app|router|api)\.(get|post|put|delete|patch)\s*\(\s*["\']([^"\']+)["\']'
            for match in re.finditer(pattern, content):
                routes.append(
                    {
                        "method": match.group(1).upper(),
                        "route": match.group(2),
                    }
                )
        except (OSError, re.error) as exc:
            _log.debug("[IMPACT] API route parse error in %s: %s", file_path, exc)
        return routes

    def _parse_db_operations(self, file_path: Path) -> list[dict[str, str]]:
        """Parse database operations (table names) from a file."""
        db_ops: list[dict[str, str]] = []
        try:
            content = file_path.read_text(encoding="utf-8", errors="ignore")
            # Match SQL operations
            tables: set[str] = set()
            patterns = [
                r"FROM\s+(\w+)",
                r"INSERT\s+(?:INTO\s+)?(\w+)",
                r"UPDATE\s+(\w+)",
                r"DELETE\s+(?:FROM\s+)?(\w+)",
                r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)",
                r"ALTER\s+TABLE\s+(\w+)",
                r"PRAGMA\s+(\w+)",
                r'"(\w+\.db)"',
            ]
            for pattern in patterns:
                for match in re.finditer(pattern, content, re.IGNORECASE):
                    table_name = match.group(1)
                    if table_name and len(table_name) < 100:  # Sanity check
                        tables.add(table_name)

            for table in tables:
                op_type = "TABLE"
                operation = "READ"
                if any(kw in content.upper() for kw in ["CREATE TABLE", f"FROM {table.upper()}"]):
                    if (
                        "CREATE TABLE" in content
                        and table.upper() in content.upper().split("CREATE TABLE")[-1].split(")")[0]
                        if "CREATE TABLE" in content
                        else False
                    ):
                        op_type = "TABLE"
                    operation = "READ"
                if re.search(
                    rf"INSERT\s+(?:INTO\s+)?{re.escape(table)}|UPDATE\s+{re.escape(table)}|DELETE\s+(?:FROM\s+)?{re.escape(table)}",
                    content,
                    re.IGNORECASE,
                ):
                    operation = "WRITE"

                db_ops.append(
                    {
                        "name": table,
                        "type": op_type,
                        "operation": operation,
                    }
                )
        except (OSError, re.error) as exc:
            _log.debug("[IMPACT] DB parse error in %s: %s", file_path, exc)
        return db_ops

    def _parse_tested_modules(self, test_file: Path) -> set[str]:
        """Parse which modules a test file tests.

        Looks for imports of the module being tested and test function names.
        """
        modules: set[str] = set()
        try:
            tree = ast.parse(test_file.read_text(encoding="utf-8", errors="ignore"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    if node.module:
                        modules.add(node.module)
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        modules.add(alias.name)
        except (SyntaxError, OSError) as exc:
            _log.debug("[IMPACT] Test parse error in %s: %s", test_file, exc)
        return modules

    def _parse_doc_references(self, doc_file: Path) -> set[str]:
        """Parse which modules a documentation file references."""
        refs: set[str] = set()
        try:
            content = doc_file.read_text(encoding="utf-8", errors="ignore")
            # Match patterns like `core.module`, core/module.py, etc.
            patterns = [
                r"`core\.(\w+)`",
                r"`index_app\.(\w+)`",
                r"`infrastructure\.(\w+)`",
                r"core/(\w+(?:/\w+)*\.py)",
                r"index_app/(\w+(?:/\w+)*\.py)",
            ]
            for pattern in patterns:
                for match in re.finditer(pattern, content):
                    ref = match.group(1).replace("/", ".")
                    refs.add(f"core.{ref}" if "infrastructure" not in pattern else f"infrastructure.{ref}")
        except (OSError, re.error) as exc:
            _log.debug("[IMPACT] Doc parse error in %s: %s", doc_file, exc)
        return refs

    def _parse_ui_screens(self, gui_file: Path) -> list[str]:
        """Parse UI screen/frame names from GUI files."""
        screens: list[str] = []
        try:
            content = gui_file.read_text(encoding="utf-8", errors="ignore")
            # Match Tkinter Frame/Window class definitions
            for match in re.finditer(r"class\s+(\w+(?:Frame|Window|Dialog|Screen|Page))\b", content):
                screens.append(match.group(1))
            # Match function/class names with "screen" or "page" or "view"
            for match in re.finditer(r"(?:def|class)\s+(\w*(?:[Ss]creen|[Pp]age|[Vv]iew|[Ww]indow)\w*)", content):
                name = match.group(1)
                if name not in screens:
                    screens.append(name)
        except (OSError, re.error) as exc:
            _log.debug("[IMPACT] UI parse error in %s: %s", gui_file, exc)
        return screens

    def _find_transitive_dependents(self, module_path: str) -> set[str]:
        """Find all modules that transitively depend on the given module.

        Uses BFS through the reverse dependency graph.
        """
        dependents: set[str] = set()
        queue = deque([module_path])
        visited: set[str] = set()

        while queue:
            current = queue.popleft()
            if current in visited:
                continue
            visited.add(current)

            # Direct dependents
            direct = self._reverse_graph.get(current, set())
            for dep in direct:
                if dep not in visited and dep != module_path:
                    dependents.add(dep)
                    queue.append(dep)

            # Also check module name without .py
            mod_name = current.replace(".py", "").replace("/", ".")
            for importer, imports in self._reverse_graph.items():
                if mod_name in imports and importer not in visited and importer != module_path:
                    dependents.add(importer)
                    queue.append(importer)

        return dependents

    def _assess_business_impact(self, report: ImpactReport) -> str:
        """Assess business impact based on what's affected."""
        high_impact_keywords = ["risk", "execution", "order", "portfolio", "broker", "position"]
        critical_impact_keywords = ["risk_service", "execution_service", "broker_adapters", "safety_state"]

        # Direct hits on a known critical module are CRITICAL regardless of
        # dependency graph depth (the module itself is the safety-critical code).
        changed = report.changed_file.lower()
        for kw in critical_impact_keywords:
            if kw in changed:
                return "CRITICAL"

        for dep in report.import_dependencies:
            for kw in critical_impact_keywords:
                if kw in dep.lower():
                    return "CRITICAL"
            for kw in high_impact_keywords:
                if kw in dep.lower():
                    return "HIGH"

        if len(report.affected_apis) > 5:
            return "HIGH"
        if len(report.affected_services) > 10:
            return "HIGH"
        if len(report.affected_services) > 3:
            return "MEDIUM"
        return "LOW"

    def _assess_technical_impact(self, report: ImpactReport) -> str:
        """Assess technical impact based on dependency breadth."""
        n_dependents = len(report.import_dependencies)
        n_services = len(report.affected_services)

        if n_dependents > 20 or n_services > 30:
            return "CRITICAL"
        if n_dependents > 10 or n_services > 15:
            return "HIGH"
        if n_dependents > 3 or n_services > 5:
            return "MEDIUM"
        return "LOW"

    def _assess_regression_risk(self, report: ImpactReport) -> str:
        """Assess regression risk based on change scope and test coverage."""
        has_tests = len(report.affected_tests) > 0
        n_dependents = len(report.import_dependencies)
        is_critical_domain = any(
            kw in report.changed_file.lower() for kw in ["risk", "execution", "broker", "order", "portfolio"]
        )

        if is_critical_domain and n_dependents > 5:
            return "HIGH"
        if not has_tests and n_dependents > 3:
            return "HIGH"
        if n_dependents > 10:
            return "HIGH"
        if n_dependents > 3:
            return "MEDIUM"
        if not has_tests:
            return "MEDIUM"
        return "LOW"

    def _estimate_effort(self, report: ImpactReport) -> int:
        """Estimate effort in minutes based on impact scope."""
        effort = 30  # baseline: 30 min for simple change

        # Add time for each category
        effort += len(report.affected_services) * 10
        effort += len(report.affected_apis) * 15
        effort += len(report.affected_db_objects) * 20
        effort += len(report.affected_ui_screens) * 30
        effort += len(report.affected_tests) * 5  # running tests
        effort += len(report.affected_documentation) * 15

        # Cap at reasonable max
        return min(effort, 480)  # max 8 hours

    def _generate_recommendations(self, report: ImpactReport) -> list[str]:
        """Generate actionable recommendations based on impact analysis."""
        recommendations: list[str] = []

        if report.affected_tests:
            recommendations.append(
                f"Run {len(report.affected_tests)} affected test(s): "
                f"{' '.join(t.path for t in report.affected_tests[:5])}"
            )
        if report.affected_documentation:
            recommendations.append(f"Update {len(report.affected_documentation)} documentation file(s)")
        if report.regression_risk in ("HIGH", "CRITICAL"):
            recommendations.append("Run full regression test suite before merging")
        if report.affected_apis:
            recommendations.append("Verify API contract compatibility with consumers")
        if report.affected_db_objects:
            recommendations.append("Review database migration impact for schema changes")
        if report.business_impact in ("HIGH", "CRITICAL"):
            recommendations.append("Notify stakeholders of high-impact change")
        if "test_" not in report.changed_file and not any(
            t.path for t in report.affected_tests if t.relevance == "DIRECT"
        ):
            recommendations.append("Consider adding unit tests for this change")

        return recommendations

    # ── Graph Queries ─────────────────────────────────────────────────────

    def get_dependents(self, module_path: str) -> list[str]:
        """Get all modules that directly import the given module."""
        self.build_dependency_graph()
        with self._lock:
            return sorted(self._reverse_graph.get(module_path, set()))

    def get_dependencies(self, module_path: str) -> list[str]:
        """Get all modules that the given module imports."""
        self.build_dependency_graph()
        with self._lock:
            return sorted(self._dependency_graph.get(module_path, set()))

    def get_module_stats(self) -> dict[str, Any]:
        """Get statistics about the dependency graph."""
        self.build_dependency_graph()
        with self._lock:
            most_imported = sorted(
                self._reverse_graph.items(),
                key=lambda x: len(x[1]),
                reverse=True,
            )[:10]

            return {
                "total_modules": len(self._dependency_graph),
                "total_edges": sum(len(v) for v in self._dependency_graph.values()),
                "total_apis": sum(len(v) for v in self._api_route_map.values()),
                "total_tests_mapped": sum(len(v) for v in self._test_map.values()),
                "total_docs_mapped": sum(len(v) for v in self._doc_map.values()),
                "most_depended_modules": [{"module": mod, "dependents": len(deps)} for mod, deps in most_imported],
            }

    def find_dead_modules(self) -> list[str]:
        """Find modules that appear to have no dependents (potential dead code)."""
        self.build_dependency_graph()
        with self._lock:
            dead: list[str] = []
            for module in self._dependency_graph:
                if module == module:  # skip itself
                    dependents = self._reverse_graph.get(module, set())
                    # Skip test files and __init__.py
                    if module.startswith("tests/"):
                        continue
                    if module.endswith("__init__.py"):
                        continue
                    if not dependents:
                        # Check if it's only imported by tests
                        dead.append(module)
            return sorted(dead)


# ── Singleton ───────────────────────────────────────────────────────────────


_engine: ImpactAnalysisEngine | None = None
_engine_lock = threading.RLock()


def get_impact_engine() -> ImpactAnalysisEngine:
    """Get the singleton ImpactAnalysisEngine instance."""
    global _engine
    with _engine_lock:
        if _engine is None:
            _engine = ImpactAnalysisEngine()
        return _engine


def reset_impact_engine() -> None:
    """Force-reset singleton (for testing)."""
    global _engine
    with _engine_lock:
        _engine = None


def analyze_change(file_path: str, change_type: str = "MODIFY") -> ImpactReport:
    """Convenience function: analyze a single file change."""
    return get_impact_engine().analyze_change(file_path, change_type)


__all__ = [
    "AffectedAPI",
    "AffectedDatabaseObject",
    "AffectedDocumentation",
    "AffectedService",
    "AffectedTestFile",
    "ImpactAnalysisEngine",
    "ImpactReport",
    "analyze_change",
    "get_impact_engine",
    "reset_impact_engine",
]
