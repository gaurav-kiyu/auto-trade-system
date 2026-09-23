"""Performance Optimizer — Performance analysis and recommendation engine (Vision Module).

Detects and recommends performance improvements:
- N+1 query patterns in loops
- Sync I/O in async contexts (blocking calls)
- Expensive list comprehensions / nested loops
- Repeated computations that could be cached
- Inefficient data structures (list lookups vs set/dict)
- Large file processing without streaming
- Missing connection pooling
- Unbatched database operations
- Memory-inefficient patterns (building giant lists)

Integrates with:
- BIDashboard for performance trend tracking
- ChangeRiskScorer for performance regression risk

Usage:
    from core.performance_optimizer import get_performance_optimizer
    optimizer = get_performance_optimizer()
    report = optimizer.run_analysis()
    print(report.summary_text())
"""

from __future__ import annotations

import ast
import json
import logging
import os
import re
import threading
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────

ROOT = Path(__file__).resolve().parent.parent
EXCLUDED_DIRS = {
    ".git",
    "__pycache__",
    "node_modules",
    ".venv",
    "venv",
    "dist",
    "build",
    ".benchmarks",
    "backups",
    "data",
    "db",
    "logs",
    "reports",
    "archive",
    "_phase14_browser_runner",
    "pre_deploy_snapshots",
    "scratch",
    "tmp",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
}
MAX_FILE_SIZE = 1024 * 50  # 50KB max for scanning

# Performance anti-patterns to detect
PERF_PATTERNS: list[tuple[str, str, str, int]] = [
    # (pattern_name, regex_pattern, severity, weight)
    ("Sync DB in async", r"await.*\.(execute|fetch|fetchall|fetchone)", "HIGH", 8),
    ("Sleep in loop", r"for.*\n.*time\.sleep|while.*\n.*time\.sleep", "HIGH", 9),
    ("Giant list comp", r"\[.*for.*in.*for.*in", "MEDIUM", 5),
    ("Nested loop O(n²)", r"for.*in.*:\s*\n\s+for.*in", "MEDIUM", 6),
    ("Missing set lookup", r"if.*in\s+\[.*\]|if.*in\s+list\(|in\s+self\.\w+list", "MEDIUM", 4),
    ("subprocess in loop", r"for.*\n.*subprocess\.run|for.*\n.*subprocess\.call", "HIGH", 9),
    ("json.load in loop", r"for.*\n.*json\.loads|for.*\n.*json\.load\(", "MEDIUM", 5),
    ("No batch processing", r"for.*in.*:\s*\n\s+.*\.(insert|update|delete|save)\(", "HIGH", 7),
    ("requests in loop", r"for.*\n.*requests\.(get|post|put|delete)\(", "HIGH", 9),
    ("list() constructor waste", r"list\(\[", "LOW", 2),
    ("dict() constructor waste", r"dict\(\{", "LOW", 2),
    ("str concat in loop", r"for.*\n\s+\w+\s*\+=\s*['\"]", "MEDIUM", 4),
    ("Large file read all", r"\.read\(\).*\n.*for|\.readlines\(\)", "MEDIUM", 5),
    ("Unbatched insert", r"for.*\n.*\.execute\(.*INSERT", "HIGH", 8),
    ("Missing timeout", r"requests\.(get|post|put)\((?!.*timeout)[^)]*\)", "MEDIUM", 4),
    ("Deep nested loop O(n³)", r"for.*:\s*\n\s+for.*:\s*\n\s+for.*:", "HIGH", 8),
]

# Cache opportunities
CACHE_PATTERNS: list[tuple[str, str, str]] = [
    ("Repeated API call", r"(requests\.get|requests\.post).*\n.*(requests\.get|requests\.post)", "MEDIUM"),
    ("Identical query", r"execute\(.*\).*\n.*execute\(.*\)", "MEDIUM"),
    ("Recomputed value", r"len\(.*\).*\n.*len\(.*\)", "LOW"),
]


# ── Data Models ────────────────────────────────────────────────────────────


@dataclass
class PerfFinding:
    """A detected performance anti-pattern."""

    file_path: str = ""
    line_number: int = 0
    pattern_name: str = ""
    severity: str = "MEDIUM"
    weight: int = 5
    snippet: str = ""
    recommendation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "file_path": self.file_path,
            "line_number": self.line_number,
            "pattern_name": self.pattern_name,
            "severity": self.severity,
            "weight": self.weight,
            "snippet": self.snippet[:200],
            "recommendation": self.recommendation,
        }


@dataclass
class CacheOpportunity:
    """A detected caching opportunity."""

    file_path: str = ""
    line_number: int = 0
    pattern_name: str = ""
    severity: str = "MEDIUM"
    snippet: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "file_path": self.file_path,
            "line_number": self.line_number,
            "pattern_name": self.pattern_name,
            "severity": self.severity,
            "snippet": self.snippet[:200],
        }


@dataclass
class ModuleScore:
    """Per-module performance score."""

    module_path: str = ""
    score: float = 10.0
    finding_count: int = 0
    top_issues: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "module_path": self.module_path,
            "score": round(self.score, 1),
            "finding_count": self.finding_count,
            "top_issues": self.top_issues[:5],
        }


@dataclass
class PerfReport:
    """Complete performance analysis report."""

    timestamp: float = 0.0
    total_files_scanned: int = 0
    findings: list[PerfFinding] = field(default_factory=list)
    cache_opportunities: list[CacheOpportunity] = field(default_factory=list)
    module_scores: list[ModuleScore] = field(default_factory=list)
    overall_score: float = 10.0
    bottlenecks: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "date": datetime.fromtimestamp(self.timestamp).isoformat() if self.timestamp else "",
            "total_files_scanned": self.total_files_scanned,
            "findings": [f.to_dict() for f in self.findings],
            "cache_opportunities": [c.to_dict() for c in self.cache_opportunities],
            "findings_count": len(self.findings),
            "cache_opportunities_count": len(self.cache_opportunities),
            "module_scores": [m.to_dict() for m in self.module_scores],
            "overall_score": round(self.overall_score, 1),
            "bottlenecks": self.bottlenecks[:10],
            "recommendations": self.recommendations[:10],
        }

    def summary_text(self) -> str:
        lines = [
            "═" * 60,
            "  PERFORMANCE ANALYSIS REPORT",
            "═" * 60,
            f"  Scanned: {self.total_files_scanned} files",
            f"  Score: {self.overall_score:.1f}/10.0",
            "",
        ]
        high = [f for f in self.findings if f.severity == "HIGH"]
        med = [f for f in self.findings if f.severity == "MEDIUM"]
        if high:
            lines.append(f"  🔴 High-severity: {len(high)}")
            for h in high[:5]:
                lines.append(f"     {h.pattern_name} in {h.file_path}:{h.line_number}")
        if med:
            lines.append(f"  🟡 Medium-severity: {len(med)}")
        if self.bottlenecks:
            lines.append("  Bottlenecks:")
            for b in self.bottlenecks[:5]:
                lines.append(f"    ⚠ {b}")
        if self.recommendations:
            lines.append("  Recommendations:")
            for r in self.recommendations[:5]:
                lines.append(f"    → {r}")
        lines.append("═" * 60)
        return "\n".join(lines)


# ── Anti-Pattern Recommendations Map ───────────────────────────────────────

_RECOMMENDATIONS_MAP: dict[str, str] = {
    "Sync DB in async": "Use async database driver (asyncpg, aiosqlite) or wrap in run_in_executor",
    "Sleep in loop": "Use asyncio.sleep() or batch delay — avoid blocking the event loop",
    "Giant list comp": "Use generator expression instead of list comprehension for large datasets",
    "Nested loop O(n²)": "Consider using dict/set lookups or itertools.product to reduce complexity",
    "Missing set lookup": "Convert list to set for O(1) membership tests",
    "subprocess in loop": "Move subprocess calls outside the loop or batch inputs",
    "json.load in loop": "Load JSON once outside the loop when possible",
    "No batch processing": "Use bulk operations instead of individual inserts/updates",
    "requests in loop": "Use asyncio/aiohttp or batch requests outside the loop",
    "list() constructor waste": "Use list literal [...] instead of list([...])",
    "dict() constructor waste": "Use dict literal {...} instead of dict({...})",
    "str concat in loop": "Use ''.join(list) for string concatenation in loops",
    "Large file read all": "Use streaming/iterator to process files line by line",
    "Unbatched insert": "Use executemany() or bulk_insert for batch database operations",
    "Missing timeout": "Always set timeout parameter on network requests",
    "Deep nested loop O(n³)": "Restructure algorithm — consider alternatives like early exit, caching, or divide-and-conquer",
}


RE_AWAIT = re.compile(r"await\s+.*\.(execute|fetch|fetchall|fetchone)")
RE_SET_LOOKUP = re.compile(r"if\s+.*in\s+\[.*\]|if\s+.*in\s+list\(|in\s+self\.\w+list")


class UnifiedVisitor(ast.NodeVisitor):
    __slots__ = ("rel_path", "lines", "findings", "cache_ops", "loop_stack", "scope_stack")

    def __init__(
        self,
        rel_path: str,
        lines: list[str],
        findings: list[PerfFinding],
        cache_ops: list[CacheOpportunity],
    ) -> None:
        self.rel_path = rel_path
        self.lines = lines
        self.findings = findings
        self.cache_ops = cache_ops
        self.loop_stack: list[int] = []
        self.scope_stack: list[dict[str, list[tuple[str, int, str]]]] = [
            {"api": [], "queries": [], "len": []}
        ]

    def _enter_scope(self) -> None:
        self.scope_stack.append({"api": [], "queries": [], "len": []})

    def _exit_scope(self) -> None:
        scope = self.scope_stack.pop()
        # Repeated API calls
        seen_api: set[str] = set()
        for url, l_num, snip in scope["api"]:
            if url in seen_api:
                self.cache_ops.append(CacheOpportunity(
                    file_path=self.rel_path,
                    line_number=l_num,
                    pattern_name="Repeated API call",
                    severity="MEDIUM",
                    snippet=snip,
                ))
            seen_api.add(url)

        # Identical queries
        seen_q: set[str] = set()
        for q, l_num, snip in scope["queries"]:
            if q in seen_q:
                self.cache_ops.append(CacheOpportunity(
                    file_path=self.rel_path,
                    line_number=l_num,
                    pattern_name="Identical query",
                    severity="MEDIUM",
                    snippet=snip,
                ))
            seen_q.add(q)

        # Recomputed len()
        seen_len: set[str] = set()
        for arg, l_num, snip in scope["len"]:
            if arg in seen_len:
                self.cache_ops.append(CacheOpportunity(
                    file_path=self.rel_path,
                    line_number=l_num,
                    pattern_name="Recomputed value",
                    severity="LOW",
                    snippet=snip,
                ))
            seen_len.add(arg)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._enter_scope()
        self.generic_visit(node)
        self._exit_scope()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._enter_scope()
        self.generic_visit(node)
        self._exit_scope()

    def visit_For(self, node: ast.For) -> None:
        self._check_loop(node)
        self.generic_visit(node)
        self.loop_stack.pop()

    def visit_While(self, node: ast.While) -> None:
        self._check_loop(node)
        self.generic_visit(node)
        self.loop_stack.pop()

    def _check_loop(self, node: ast.AST) -> None:
        loop_line = getattr(node, "lineno", 1)
        self.loop_stack.append(loop_line)
        depth = len(self.loop_stack)
        snip = self.lines[loop_line - 1].strip() if loop_line <= len(self.lines) else ""
        if depth == 2:
            self.findings.append(PerfFinding(
                file_path=self.rel_path,
                line_number=loop_line,
                pattern_name="Nested loop O(n²)",
                severity="MEDIUM",
                weight=6,
                snippet=snip,
                recommendation=_RECOMMENDATIONS_MAP.get("Nested loop O(n²)", ""),
            ))
        elif depth >= 3:
            self.findings.append(PerfFinding(
                file_path=self.rel_path,
                line_number=loop_line,
                pattern_name="Deep nested loop O(n³)",
                severity="HIGH",
                weight=8,
                snippet=snip,
                recommendation=_RECOMMENDATIONS_MAP.get("Deep nested loop O(n³)", ""),
            ))

    def visit_ListComp(self, node: ast.ListComp) -> None:
        if len(node.generators) > 1:
            lineno = getattr(node, "lineno", 1)
            snip = self.lines[lineno - 1].strip() if lineno <= len(self.lines) else ""
            self.findings.append(PerfFinding(
                file_path=self.rel_path,
                line_number=lineno,
                pattern_name="Giant list comp",
                severity="MEDIUM",
                weight=5,
                snippet=snip,
                recommendation=_RECOMMENDATIONS_MAP.get("Giant list comp", ""),
            ))
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        lineno = getattr(node, "lineno", 1)
        snip = self.lines[lineno - 1].strip() if lineno <= len(self.lines) else ""
        func = node.func
        cur_scope = self.scope_stack[-1]

        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id == "requests":
            if func.attr in ("get", "post", "put"):
                if node.args and isinstance(node.args[0], ast.Constant):
                    cur_scope["api"].append((str(node.args[0].value), lineno, snip))
                if not any(kw.arg == "timeout" for kw in node.keywords):
                    self.findings.append(PerfFinding(
                        file_path=self.rel_path,
                        line_number=lineno,
                        pattern_name="Missing timeout",
                        severity="MEDIUM",
                        weight=4,
                        snippet=snip,
                        recommendation=_RECOMMENDATIONS_MAP.get("Missing timeout", ""),
                    ))
                if self.loop_stack:
                    self.findings.append(PerfFinding(
                        file_path=self.rel_path,
                        line_number=self.loop_stack[-1],
                        pattern_name="requests in loop",
                        severity="HIGH",
                        weight=9,
                        snippet=snip,
                        recommendation=_RECOMMENDATIONS_MAP.get("requests in loop", ""),
                    ))

        elif isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id in ("time", "_time") and func.attr == "sleep":
            if self.loop_stack:
                self.findings.append(PerfFinding(
                    file_path=self.rel_path,
                    line_number=self.loop_stack[-1],
                    pattern_name="Sleep in loop",
                    severity="HIGH",
                    weight=9,
                    snippet=snip,
                    recommendation=_RECOMMENDATIONS_MAP.get("Sleep in loop", ""),
                ))

        elif isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id == "subprocess":
            if self.loop_stack and func.attr in ("run", "call", "Popen"):
                self.findings.append(PerfFinding(
                    file_path=self.rel_path,
                    line_number=self.loop_stack[-1],
                    pattern_name="subprocess in loop",
                    severity="HIGH",
                    weight=9,
                    snippet=snip,
                    recommendation=_RECOMMENDATIONS_MAP.get("subprocess in loop", ""),
                ))

        elif isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id == "json":
            if self.loop_stack and func.attr in ("load", "loads"):
                self.findings.append(PerfFinding(
                    file_path=self.rel_path,
                    line_number=self.loop_stack[-1],
                    pattern_name="json.load in loop",
                    severity="MEDIUM",
                    weight=5,
                    snippet=snip,
                    recommendation=_RECOMMENDATIONS_MAP.get("json.load in loop", ""),
                ))

        elif isinstance(func, ast.Name) and func.id == "len":
            if node.args and isinstance(node.args[0], ast.Name):
                cur_scope["len"].append((node.args[0].id, lineno, snip))

        elif isinstance(func, ast.Attribute):
            if func.attr in ("execute", "executemany") and node.args and isinstance(node.args[0], ast.Constant):
                cur_scope["queries"].append((str(node.args[0].value), lineno, snip))

            if self.loop_stack:
                loop_line = self.loop_stack[-1]
                if func.attr in ("insert", "update", "delete", "save"):
                    self.findings.append(PerfFinding(
                        file_path=self.rel_path,
                        line_number=loop_line,
                        pattern_name="No batch processing",
                        severity="HIGH",
                        weight=7,
                        snippet=snip,
                        recommendation=_RECOMMENDATIONS_MAP.get("No batch processing", ""),
                    ))
                elif func.attr in ("execute", "executemany"):
                    if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                        if "INSERT" in node.args[0].value.upper():
                            self.findings.append(PerfFinding(
                                file_path=self.rel_path,
                                line_number=loop_line,
                                pattern_name="Unbatched insert",
                                severity="HIGH",
                                weight=8,
                                snippet=snip,
                                recommendation=_RECOMMENDATIONS_MAP.get("Unbatched insert", ""),
                            ))

        self.generic_visit(node)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        if self.loop_stack and isinstance(node.op, ast.Add):
            if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                lineno = getattr(node, "lineno", 1)
                snip = self.lines[lineno - 1].strip() if lineno <= len(self.lines) else ""
                self.findings.append(PerfFinding(
                    file_path=self.rel_path,
                    line_number=self.loop_stack[-1],
                    pattern_name="str concat in loop",
                    severity="MEDIUM",
                    weight=4,
                    snippet=snip,
                    recommendation=_RECOMMENDATIONS_MAP.get("str concat in loop", ""),
                ))
        self.generic_visit(node)


def _scan_source_content(rel_path: str, content: str) -> tuple[list[PerfFinding], list[CacheOpportunity]]:
    """Scan source code for performance issues and cache opportunities in a single pass."""
    findings: list[PerfFinding] = []
    cache_ops: list[CacheOpportunity] = []

    if not content.strip():
        return findings, cache_ops

    lines = content.splitlines()

    # 1. Fast line-by-line checks
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if "await" in line and ("execute" in line or "fetch" in line):
            if RE_AWAIT.search(line):
                findings.append(PerfFinding(
                    file_path=rel_path,
                    line_number=i,
                    pattern_name="Sync DB in async",
                    severity="HIGH",
                    weight=8,
                    snippet=stripped[:200],
                    recommendation=_RECOMMENDATIONS_MAP.get("Sync DB in async", ""),
                ))
        if "list([" in line:
            findings.append(PerfFinding(
                file_path=rel_path,
                line_number=i,
                pattern_name="list() constructor waste",
                severity="LOW",
                weight=2,
                snippet=stripped[:200],
                recommendation=_RECOMMENDATIONS_MAP.get("list() constructor waste", ""),
            ))
        if "dict({" in line:
            findings.append(PerfFinding(
                file_path=rel_path,
                line_number=i,
                pattern_name="dict() constructor waste",
                severity="LOW",
                weight=2,
                snippet=stripped[:200],
                recommendation=_RECOMMENDATIONS_MAP.get("dict() constructor waste", ""),
            ))
        if "if " in line and ("[" in line or "list(" in line or "list" in line):
            if RE_SET_LOOKUP.search(line):
                findings.append(PerfFinding(
                    file_path=rel_path,
                    line_number=i,
                    pattern_name="Missing set lookup",
                    severity="MEDIUM",
                    weight=4,
                    snippet=stripped[:200],
                    recommendation=_RECOMMENDATIONS_MAP.get("Missing set lookup", ""),
                ))
        if ".readlines()" in line or ".read()" in line:
            surrounding = "\n".join(lines[max(0, i - 1):min(len(lines), i + 3)])
            if "for " in surrounding:
                findings.append(PerfFinding(
                    file_path=rel_path,
                    line_number=i,
                    pattern_name="Large file read all",
                    severity="MEDIUM",
                    weight=5,
                    snippet=stripped[:200],
                    recommendation=_RECOMMENDATIONS_MAP.get("Large file read all", ""),
                ))

    # 2. Parse AST for structural / loop anti-patterns and cache opportunities
    try:
        tree = ast.parse(content)
    except Exception:
        return findings, cache_ops

    visitor = UnifiedVisitor(rel_path, lines, findings, cache_ops)
    visitor.visit(tree)
    visitor._exit_scope()

    return findings, cache_ops


def _worker_scan_file(item: tuple[str, str]) -> tuple[str, list[tuple], list[tuple]]:
    """Worker process helper for parallel file scanning using fast tuple serialization."""
    rel_path, file_str = item
    try:
        p = Path(file_str)
        content = p.read_text(encoding="utf-8", errors="ignore")
        findings, cache_ops = _scan_source_content(rel_path, content)
        f_tuples = [(f.file_path, f.line_number, f.pattern_name, f.severity, f.weight, f.snippet, f.recommendation) for f in findings]
        c_tuples = [(c.file_path, c.line_number, c.pattern_name, c.severity, c.snippet) for c in cache_ops]
        return rel_path, f_tuples, c_tuples
    except Exception:
        return rel_path, [], []


# ── Performance Optimizer ──────────────────────────────────────────────────


class PerformanceOptimizer:
    """Performance analysis and recommendation engine.

    Scans source code for:
    - Performance anti-patterns (sync IO in async, nested loops, missing cache)
    - Cache opportunities (repeated computations)
    - Module-level performance scores
    - Bottleneck identification

    Thread-safe. Results are persisted for trend tracking.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._report_history: list[PerfReport] = []
        self._last_report: PerfReport | None = None
        self._total_analyses: int = 0
        self._persist_path = Path("json/perf_optimizer_history.json")

    @property
    def last_report(self) -> PerfReport | None:
        return self._last_report

    # ── Analysis ──────────────────────────────────────────────────────────

    def run_analysis(self, force: bool = False) -> PerfReport:
        """Run a complete performance analysis of the codebase.

        Returns:
            PerfReport with findings, module scores, recommendations.
        """
        with self._lock:
            if not force and self._last_report is not None and (time.time() - self._last_report.timestamp < 300.0):
                return self._last_report

        report = PerfReport(timestamp=time.time())
        src_dirs = [ROOT / "core", ROOT / "index_app", ROOT / "infrastructure", ROOT / "scripts"]

        all_findings: list[PerfFinding] = []
        all_cache_ops: list[CacheOpportunity] = []
        module_findings: dict[str, list[PerfFinding]] = {}

        file_items: list[tuple[str, str]] = []
        for src_dir in src_dirs:
            if not src_dir.is_dir():
                continue

            for file_path in src_dir.rglob("*.py"):
                if "__pycache__" in str(file_path) or any(
                    ex in str(file_path) for ex in EXCLUDED_DIRS
                ):
                    continue
                try:
                    if file_path.stat().st_size > MAX_FILE_SIZE:
                        continue
                    rel_path = str(file_path.relative_to(ROOT))
                    file_items.append((rel_path, str(file_path)))
                except (OSError, UnicodeDecodeError):
                    continue

        total_files = len(file_items)

        # Parallel file scan with chunked batching, safe sequential fallback
        try:
            with ProcessPoolExecutor(max_workers=min(6, os.cpu_count() or 1)) as ex:
                results = list(ex.map(_worker_scan_file, file_items, chunksize=30))
            for rel_p, f_tuples, c_tuples in results:
                f_objs = [
                    PerfFinding(
                        file_path=t[0],
                        line_number=t[1],
                        pattern_name=t[2],
                        severity=t[3],
                        weight=t[4],
                        snippet=t[5],
                        recommendation=t[6],
                    )
                    for t in f_tuples
                ]
                c_objs = [
                    CacheOpportunity(
                        file_path=t[0],
                        line_number=t[1],
                        pattern_name=t[2],
                        severity=t[3],
                        snippet=t[4],
                    )
                    for t in c_tuples
                ]
                all_findings.extend(f_objs)
                all_cache_ops.extend(c_objs)
                if f_objs:
                    module_key = "/".join(rel_p.split("/")[:2])
                    module_findings.setdefault(module_key, []).extend(f_objs)
        except Exception as pool_ex:
            _log.warning("ProcessPoolExecutor unavailable (%s); falling back to sequential scan", pool_ex)
            for rel_p, f_path_str in file_items:
                try:
                    content = Path(f_path_str).read_text(encoding="utf-8", errors="ignore")
                    f_objs, c_objs = self._scan_file(rel_p, content)
                    all_findings.extend(f_objs)
                    all_cache_ops.extend(c_objs)
                    if f_objs:
                        module_key = "/".join(rel_p.split("/")[:2])
                        module_findings.setdefault(module_key, []).extend(f_objs)
                except Exception:
                    continue

        report.findings = all_findings
        report.cache_opportunities = all_cache_ops
        report.total_files_scanned = total_files

        # Compute module scores
        for module_key, findings in module_findings.items():
            score = 10.0
            for f in findings:
                score -= (f.weight * 0.2)
            score = max(0.0, min(10.0, score))
            report.module_scores.append(ModuleScore(
                module_path=module_key,
                score=score,
                finding_count=len(findings),
                top_issues=list({f.pattern_name for f in findings}),
            ))

        # Overall score
        total_weight = sum(f.weight for f in all_findings)
        report.overall_score = max(0.0, min(10.0, 10.0 - (total_weight * 0.05)))

        # Identify bottlenecks
        module_scores_sorted = sorted(report.module_scores, key=lambda m: m.score)
        worst = module_scores_sorted[:3] if module_scores_sorted else []
        for m in worst:
            if m.score < 7.0:
                report.bottlenecks.append(f"{m.module_path} ({m.score:.1f}/10) — {m.finding_count} issues")

        # Generate recommendations
        report.recommendations = self._generate_recommendations(report)

        with self._lock:
            self._report_history.append(report)
            self._last_report = report
            self._total_analyses += 1
            self._persist()

        return report

    def _scan_file(self, rel_path: str, content: str) -> tuple[list[PerfFinding], list[CacheOpportunity]]:
        """Scan a single file for performance issues using fast AST analysis and line checks."""
        return _scan_source_content(rel_path, content)

    def _get_recommendation(self, pattern_name: str) -> str:
        """Get recommendation text for a performance pattern."""
        return _RECOMMENDATIONS_MAP.get(pattern_name, "Review this code for potential performance improvement")

    def _generate_recommendations(self, report: PerfReport) -> list[str]:
        """Generate actionable performance recommendations."""
        recs: list[str] = []

        high_sev = [f for f in report.findings if f.severity == "HIGH"]
        if high_sev:
            bot_names = list({f.pattern_name for f in high_sev[:3]})
            recs.append(f"Address {len(high_sev)} high-severity issues: {', '.join(bot_names)}")

        if report.cache_opportunities:
            recs.append(f"Add caching for {len(report.cache_opportunities)} repeated computations")

        sync_async = [f for f in report.findings if "Sync" in f.pattern_name]
        if sync_async:
            recs.append(f"Migrate {len(sync_async)} sync DB calls to async equivalents")

        loop_issues = [f for f in report.findings if "loop" in f.pattern_name.lower() or "Loop" in f.pattern_name]
        if loop_issues:
            recs.append(f"Optimize {len(loop_issues)} loop-based patterns — consider batch processing or caching")

        if not recs:
            recs.append("No critical performance issues found — maintain current practices")

        recs.append("Add performance benchmarks with pytest-benchmark to track regressions")
        return recs

    # ── Persistence ───────────────────────────────────────────────────────

    def _persist(self) -> None:
        """Persist report history to disk."""
        try:
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)
            data = [r.to_dict() for r in self._report_history[-100:]]
            self._persist_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except (OSError, ValueError) as exc:
            _log.debug("[PERF] Persist: %s", exc)

    # ── Statistics ────────────────────────────────────────────────────────

    def get_stats(self) -> dict[str, Any]:
        """Get optimizer statistics."""
        with self._lock:
            last = self._last_report
            return {
                "total_analyses": self._total_analyses,
                "history_length": len(self._report_history),
                "last_analysis_ts": last.timestamp if last else 0,
                "last_score": round(last.overall_score, 1) if last else 0,
                "total_findings": len(last.findings) if last else 0,
                "high_severity": len([f for f in last.findings if f.severity == "HIGH"]) if last else 0,
                "cache_opportunities": len(last.cache_opportunities) if last else 0,
                "worst_module": min(last.module_scores, key=lambda m: m.score).to_dict() if last and last.module_scores else None,
            }


# ── Singleton ──────────────────────────────────────────────────────────────

_perf_optimizer: PerformanceOptimizer | None = None
_perf_optimizer_lock = threading.RLock()


def get_performance_optimizer() -> PerformanceOptimizer:
    """Get the singleton PerformanceOptimizer instance."""
    global _perf_optimizer
    with _perf_optimizer_lock:
        if _perf_optimizer is None:
            _perf_optimizer = PerformanceOptimizer()
        return _perf_optimizer


def reset_performance_optimizer() -> None:
    """Force-reset singleton (for testing)."""
    global _perf_optimizer
    with _perf_optimizer_lock:
        _perf_optimizer = None


__all__ = [
    "CacheOpportunity",
    "ModuleScore",
    "PerfFinding",
    "PerfReport",
    "PerformanceOptimizer",
    "get_performance_optimizer",
    "reset_performance_optimizer",
]
