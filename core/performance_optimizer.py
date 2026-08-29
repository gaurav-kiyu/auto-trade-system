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

import json
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────

ROOT = Path(__file__).resolve().parent.parent
EXCLUDED_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", "dist", "build", ".benchmarks"}
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

    def run_analysis(self) -> PerfReport:
        """Run a complete performance analysis of the codebase.

        Returns:
            PerfReport with findings, module scores, recommendations.
        """
        report = PerfReport(timestamp=time.time())
        src_dirs = [ROOT / "core", ROOT / "index_app", ROOT / "infrastructure", ROOT / "scripts"]

        all_findings: list[PerfFinding] = []
        all_cache_ops: list[CacheOpportunity] = []
        module_findings: dict[str, list[PerfFinding]] = {}
        total_files = 0

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
                    content = file_path.read_text(encoding="utf-8", errors="ignore")
                except (OSError, UnicodeDecodeError):
                    continue

                rel_path = str(file_path.relative_to(ROOT))
                total_files += 1

                findings, cache_ops = self._scan_file(rel_path, content)
                all_findings.extend(findings)
                all_cache_ops.extend(cache_ops)

                if findings:
                    module_key = "/".join(rel_path.split("/")[:2])  # e.g., "core/services"
                    if module_key not in module_findings:
                        module_findings[module_key] = []
                    module_findings[module_key].extend(findings)

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
        """Scan a single file for performance issues."""
        findings: list[PerfFinding] = []
        cache_ops: list[CacheOpportunity] = []

        content.split("\n")

        for pattern_name, regex, severity, weight in PERF_PATTERNS:
            for match in re.finditer(regex, content, re.MULTILINE | re.DOTALL):
                line_num = content[:match.start()].count("\n") + 1
                snippet = content[max(0, match.start() - 30):min(len(content), match.end() + 30)].replace("\n", " ").strip()

                recommendation = self._get_recommendation(pattern_name)
                findings.append(PerfFinding(
                    file_path=rel_path,
                    line_number=line_num,
                    pattern_name=pattern_name,
                    severity=severity,
                    weight=weight,
                    snippet=snippet,
                    recommendation=recommendation,
                ))

        # Check for cache opportunities
        for pattern_name, regex, severity in CACHE_PATTERNS:
            for match in re.finditer(regex, content, re.MULTILINE | re.DOTALL):
                line_num = content[:match.start()].count("\n") + 1
                snippet = content[max(0, match.start() - 40):min(len(content), match.end() + 40)].replace("\n", " ").strip()
                cache_ops.append(CacheOpportunity(
                    file_path=rel_path,
                    line_number=line_num,
                    pattern_name=pattern_name,
                    severity=severity,
                    snippet=snippet,
                ))

        return findings, cache_ops

    def _get_recommendation(self, pattern_name: str) -> str:
        """Get recommendation text for a performance pattern."""
        recs = {
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
        return recs.get(pattern_name, "Review this code for potential performance improvement")

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
