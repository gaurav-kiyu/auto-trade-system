"""Tests for core/performance_optimizer.py — Performance Optimizer module."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from core.performance_optimizer import (
    CacheOpportunity,
    ModuleScore,
    PerfFinding,
    PerformanceOptimizer,
    PerfReport,
    get_performance_optimizer,
    reset_performance_optimizer,
)


class TestPerfFinding:
    """Tests for PerfFinding data class."""

    def test_to_dict(self) -> None:
        f = PerfFinding(
            file_path="core/loop.py",
            line_number=15,
            pattern_name="Nested loop O(n²)",
            severity="MEDIUM",
            weight=6,
            snippet="for x in items: for y in items:",
            recommendation="Use dict lookups",
        )
        d = f.to_dict()
        assert d["file_path"] == "core/loop.py"
        assert d["pattern_name"] == "Nested loop O(n²)"
        assert d["recommendation"] == "Use dict lookups"


class TestCacheOpportunity:
    """Tests for CacheOpportunity data class."""

    def test_to_dict(self) -> None:
        co = CacheOpportunity(
            file_path="core/api.py",
            line_number=20,
            pattern_name="Repeated API call",
            severity="MEDIUM",
        )
        d = co.to_dict()
        assert d["pattern_name"] == "Repeated API call"


class TestModuleScore:
    """Tests for ModuleScore data class."""

    def test_to_dict(self) -> None:
        ms = ModuleScore(
            module_path="core/services",
            score=7.5,
            finding_count=3,
            top_issues=["Nested loop", "Sync DB"],
        )
        d = ms.to_dict()
        assert d["module_path"] == "core/services"
        assert d["score"] == 7.5


class TestPerfReport:
    """Tests for PerfReport data class."""

    def test_to_dict_empty(self) -> None:
        report = PerfReport(timestamp=1000.0, total_files_scanned=10)
        d = report.to_dict()
        assert d["total_files_scanned"] == 10
        assert d["findings_count"] == 0
        assert d["cache_opportunities_count"] == 0
        assert d["overall_score"] == 10.0

    def test_to_dict_with_findings(self) -> None:
        report = PerfReport(timestamp=1000.0, total_files_scanned=10)
        report.findings.append(PerfFinding(
            file_path="core/foo.py", pattern_name="Nested loop", severity="HIGH", weight=8
        ))
        report.cache_opportunities.append(CacheOpportunity(
            file_path="core/bar.py", pattern_name="Repeated API call"
        ))
        d = report.to_dict()
        assert d["findings_count"] == 1
        assert d["cache_opportunities_count"] == 1

    def test_summary_text(self) -> None:
        report = PerfReport(timestamp=1000.0, total_files_scanned=50)
        report.findings.append(PerfFinding(
            file_path="core/foo.py", pattern_name="Nested loop", severity="HIGH", weight=8
        ))
        report.overall_score = 8.5
        summary = report.summary_text()
        assert "PERFORMANCE ANALYSIS REPORT" in summary
        assert "8.5" in summary
        assert "High-severity: 1" in summary

    def test_summary_with_recommendations(self) -> None:
        report = PerfReport(timestamp=1000.0)
        report.recommendations.append("Fix nested loop")
        report.bottlenecks.append("core/services is slow")
        summary = report.summary_text()
        assert "Bottlenecks" in summary
        assert "Recommendations" in summary


class TestPerformanceOptimizer:
    """Tests for the PerformanceOptimizer class."""

    def setup_method(self) -> None:
        reset_performance_optimizer()

    def test_singleton(self) -> None:
        p1 = get_performance_optimizer()
        p2 = get_performance_optimizer()
        assert p1 is p2

    def test_reset(self) -> None:
        p1 = get_performance_optimizer()
        reset_performance_optimizer()
        p2 = get_performance_optimizer()
        assert p1 is not p2

    def test_initial_state(self) -> None:
        opt = get_performance_optimizer()
        assert opt.last_report is None
        stats = opt.get_stats()
        assert stats["total_analyses"] == 0

    def test_get_recommendation_known(self) -> None:
        opt = PerformanceOptimizer()
        rec = opt._get_recommendation("Nested loop O(n²)")
        assert "dict/set lookups" in rec

    def test_get_recommendation_unknown(self) -> None:
        opt = PerformanceOptimizer()
        rec = opt._get_recommendation("Unknown pattern")
        assert "potential performance improvement" in rec

    def test_generate_recommendations_clean(self) -> None:
        opt = PerformanceOptimizer()
        report = PerfReport(timestamp=1000.0)
        recs = opt._generate_recommendations(report)
        assert any("No critical performance issues" in r for r in recs)

    def test_generate_recommendations_with_high(self) -> None:
        opt = PerformanceOptimizer()
        report = PerfReport(timestamp=1000.0)
        report.findings.append(PerfFinding(pattern_name="Nested loop", severity="HIGH"))
        report.findings.append(PerfFinding(pattern_name="Sleep in loop", severity="HIGH"))
        recs = opt._generate_recommendations(report)
        assert any("high-severity" in r.lower() for r in recs)

    def test_generate_recommendations_with_cache(self) -> None:
        opt = PerformanceOptimizer()
        report = PerfReport(timestamp=1000.0)
        report.cache_opportunities.append(CacheOpportunity(pattern_name="Repeated API call"))
        recs = opt._generate_recommendations(report)
        assert any("caching" in r.lower() for r in recs)

    def test_get_stats_after_analysis(self) -> None:
        opt = PerformanceOptimizer()
        report = PerfReport(timestamp=2000.0, total_files_scanned=100)
        report.overall_score = 8.5
        report.findings.append(PerfFinding(pattern_name="Nested loop", severity="HIGH", weight=8))
        report.cache_opportunities.append(CacheOpportunity(pattern_name="Repeated call"))
        report.module_scores.append(ModuleScore(module_path="core/foo", score=6.0, finding_count=2))
        opt._report_history.append(report)
        opt._last_report = report
        opt._total_analyses = 1

        stats = opt.get_stats()
        assert stats["total_analyses"] == 1
        assert stats["last_score"] == 8.5
        assert stats["total_findings"] == 1
        assert stats["high_severity"] == 1
        assert stats["cache_opportunities"] == 1
        assert stats["worst_module"] is not None
        assert stats["worst_module"]["score"] == 6.0


class TestPerfPatternScanning:
    """Test that performance patterns are detected correctly."""

    def test_sleep_in_loop_pattern(self) -> None:
        import re
        # The sleep in loop pattern uses DOTALL and MULTILINE
        pattern = r"for.*\n.*time\.sleep|while.*\n.*time\.sleep"
        assert re.search(pattern, "for i in range(10):\n    time.sleep(1)", re.MULTILINE | re.DOTALL)
        assert re.search(pattern, "while True:\n    time.sleep(0.1)", re.MULTILINE | re.DOTALL)

    def test_missing_timeout_pattern(self) -> None:
        import re
        # Use the module's actual pattern - negative lookahead INSIDE parens
        pattern = r"requests\.(get|post|put)\((?!.*timeout)[^)]*\)"
        assert re.search(pattern, 'requests.get("http://example.com")')
        # Should NOT match when timeout IS present inside the parentheses
        assert not re.search(pattern, 'requests.get("http://example.com", timeout=5)')
        # Should NOT match when timeout is a keyword arg
        assert not re.search(pattern, 'requests.get(url, timeout=10)')

    def test_list_concat_waste(self) -> None:
        import re
        assert re.search(r"list\(\[", "result = list([1, 2, 3])")
        assert not re.search(r"list\(\[", "result = [1, 2, 3]")


class TestCoverageGaps:
    """Targeted tests for remaining uncovered code paths in PerformanceOptimizer."""

    @staticmethod
    def _make_temp_codebase(tmp_path: Path) -> Path:
        """Create a small temp codebase with sample .py files for testing run_analysis().

        This avoids scanning the real codebase (549+ files) which can timeout.
        """
        src = tmp_path / "core"
        src.mkdir(parents=True)
        # File with no issues
        (src / "clean.py").write_text("""\
def hello():
    return 42
""")
        # File with nested loop
        (src / "slow.py").write_text("""\
def process(items):
    for a in items:
        for b in items:
            pass
""")
        # File with sleep in loop
        (src / "blocking.py").write_text("""\
import time
def run(n):
    for i in range(n):
        time.sleep(0.1)
""")
        # File with missing timeout
        (src / "http.py").write_text("""\
import requests
def fetch():
    return requests.get("http://example.com")
""")
        # File with cache opportunity (repeated API call)
        (src / "cache_me.py").write_text("""\
import requests
def get_data():
    r1 = requests.get("http://api.example.com/data")
    r2 = requests.get("http://api.example.com/data")
    return r1, r2
""")
        # index_app with clean file
        idx = tmp_path / "index_app"
        idx.mkdir()
        (idx / "main.py").write_text("""\
def main():
    print('hello')
""")
        return tmp_path

    @pytest.mark.slow
    def test_run_analysis_returns_report(self, tmp_path: Path) -> None:
        """run_analysis() returns a valid PerfReport (uses temp dir, not real codebase)."""
        import core.performance_optimizer as perfmod
        codebase = self._make_temp_codebase(tmp_path)
        with patch.object(perfmod, "ROOT", codebase):
            reset_performance_optimizer()
            opt = get_performance_optimizer()
            report = opt.run_analysis()
            assert isinstance(report, PerfReport)
            assert report.timestamp > 0
            assert report.total_files_scanned > 0
            assert report.overall_score >= 0.0

    @pytest.mark.slow
    def test_last_report_property(self, tmp_path: Path) -> None:
        """last_report returns the most recent report after run_analysis (uses temp dir)."""
        import core.performance_optimizer as perfmod
        codebase = self._make_temp_codebase(tmp_path)
        with patch.object(perfmod, "ROOT", codebase):
            reset_performance_optimizer()
            opt = get_performance_optimizer()
            assert opt.last_report is None
            report = opt.run_analysis()
            assert opt.last_report is report
            assert opt.last_report.timestamp == report.timestamp

    def test_scan_file_detects_patterns(self) -> None:
        """_scan_file finds anti-patterns in content."""
        opt = PerformanceOptimizer()
        content = '''
def bad_func(items):
    for i in items:
        time.sleep(0.1)
        for j in items:
            requests.get("http://example.com")
'''
        findings, cache_ops = opt._scan_file("core/test.py", content)
        assert len(findings) > 0
        pattern_names = [f.pattern_name for f in findings]
        # Should detect sleep in loop and nested loop
        assert any("Sleep" in n or "sleep" in n.lower() for n in pattern_names)

    def test_scan_file_detects_list_waste(self) -> None:
        """_scan_file detects list() constructor waste."""
        opt = PerformanceOptimizer()
        content = "result = list([1, 2, 3])\n"
        findings, _ = opt._scan_file("core/test.py", content)
        assert any("list()" in f.pattern_name for f in findings)

    def test_scan_file_detects_missing_timeout(self) -> None:
        """_scan_file detects requests without timeout."""
        opt = PerformanceOptimizer()
        content = 'response = requests.get("http://example.com")\n'
        findings, _ = opt._scan_file("core/test.py", content)
        assert any("timeout" in f.pattern_name.lower() for f in findings)

    def test_scan_file_no_false_positives_with_timeout(self) -> None:
        """_scan_file does NOT flag requests WITH timeout."""
        opt = PerformanceOptimizer()
        content = 'response = requests.get("http://example.com", timeout=10)\n'
        findings, _ = opt._scan_file("core/test.py", content)
        timeout_findings = [f for f in findings if "timeout" in f.pattern_name.lower()]
        assert len(timeout_findings) == 0

    def test_get_stats_no_report(self) -> None:
        """get_stats returns defaults when no analysis has run."""
        reset_performance_optimizer()
        opt = PerformanceOptimizer()
        stats = opt.get_stats()
        assert stats["total_analyses"] == 0
        assert stats["last_score"] == 0
        assert stats["worst_module"] is None

    def test_generate_recommendations_sync_async(self) -> None:
        """_generate_recommendations flags sync DB calls for async migration."""
        opt = PerformanceOptimizer()
        report = PerfReport(timestamp=1000.0)
        report.findings.append(PerfFinding(pattern_name="Sync DB in async", severity="HIGH", weight=8))
        recs = opt._generate_recommendations(report)
        assert any("sync" in r.lower() or "async" in r.lower() for r in recs)

    def test_generate_recommendations_loop_issues(self) -> None:
        """_generate_recommendations flags loop-based patterns."""
        opt = PerformanceOptimizer()
        report = PerfReport(timestamp=1000.0)
        report.findings.append(PerfFinding(pattern_name="Nested loop O(n²)", severity="MEDIUM", weight=6))
        recs = opt._generate_recommendations(report)
        assert any("loop" in r.lower() for r in recs)

    def test_persist_creates_file(self) -> None:
        """_persist creates a JSON file with report history."""
        import json
        import tempfile
        reset_performance_optimizer()
        opt = PerformanceOptimizer()
        original_path = opt._persist_path
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                tmp = Path(tmpdir) / "test_perf_hist.json"
                opt._persist_path = tmp
                opt._report_history.append(PerfReport(timestamp=1000.0))
                opt._persist()
                assert tmp.exists()
                data = json.loads(tmp.read_text(encoding="utf-8"))
                assert len(data) == 1
                assert data[0]["timestamp"] == 1000.0
        finally:
            opt._persist_path = original_path

    def test_summary_with_bottlenecks(self) -> None:
        """summary_text includes bottleneck section when present."""
        report = PerfReport(timestamp=1000.0)
        report.bottlenecks.append("core/services (6.5/10) — slow")
        report.findings.append(PerfFinding(
            file_path="core/foo.py", pattern_name="Nested loop",
            severity="HIGH", weight=8, line_number=42,
        ))
        summary = report.summary_text()
        assert "Bottlenecks" in summary
        assert "High-severity" in summary
        assert "core/foo.py" in summary

    def test_empty_bottlenecks(self) -> None:
        """summary_text handles empty bottlenecks gracefully."""
        report = PerfReport(timestamp=1000.0, total_files_scanned=10)
        summary = report.summary_text()
        assert "Bottlenecks" not in summary

    def test_recommendation_lookup_all_patterns(self) -> None:
        """_get_recommendation returns advice for ALL 16 known patterns."""
        from core.performance_optimizer import PERF_PATTERNS
        opt = PerformanceOptimizer()
        for pattern_name, _, _, _ in PERF_PATTERNS:
            rec = opt._get_recommendation(pattern_name)
            assert rec, f"Missing recommendation for {pattern_name}"
            assert len(rec) > 10

    def test_get_recommendation_batched_insert(self) -> None:
        """_get_recommendation for unbatched insert suggests executemany."""
        opt = PerformanceOptimizer()
        rec = opt._get_recommendation("Unbatched insert")
        assert "executemany" in rec

    def test_get_recommendation_deep_nested(self) -> None:
        """_get_recommendation for deep nested loop suggests divide-and-conquer."""
        opt = PerformanceOptimizer()
        rec = opt._get_recommendation("Deep nested loop O(n³)")
        assert "divide-and-conquer" in rec or "Restructure" in rec

    def test_scan_file_cache_opportunity(self) -> None:
        """_scan_file detects cache opportunities for repeated API calls."""
        opt = PerformanceOptimizer()
        content = '''
def fetch_data():
    r1 = requests.get("http://api.example.com/data")
    r2 = requests.get("http://api.example.com/data")
    return r1, r2
'''
        findings, cache_ops = opt._scan_file("core/test_api.py", content)
        assert len(cache_ops) > 0
        assert any("Repeated" in c.pattern_name for c in cache_ops)

    def test_scan_file_empty_content(self) -> None:
        """_scan_file handles empty content gracefully."""
        opt = PerformanceOptimizer()
        findings, cache_ops = opt._scan_file("core/empty.py", "")
        assert len(findings) == 0
        assert len(cache_ops) == 0

    def test_generate_recommendations_loop_and_cache(self) -> None:
        """_generate_recommendations handles loop issues AND cache opportunities together."""
        opt = PerformanceOptimizer()
        report = PerfReport(timestamp=1000.0)
        report.findings.append(PerfFinding(pattern_name="Nested loop O(n²)", severity="MEDIUM"))
        report.findings.append(PerfFinding(pattern_name="Sync DB in async", severity="HIGH"))
        report.cache_opportunities.append(CacheOpportunity(pattern_name="Repeated API call"))
        recs = opt._generate_recommendations(report)
        assert any("loop" in r.lower() for r in recs)
        assert any("caching" in r.lower() for r in recs)
        assert any("high-severity" in r.lower() for r in recs)

    def test_scan_file_all_16_patterns(self) -> None:
        """_scan_file triggers ALL 16 anti-patterns with comprehensive test content."""
        opt = PerformanceOptimizer()
        content = '''import time
import subprocess
async def my_func(items):
    # Sleep in loop
    for i in items:
        time.sleep(0.1)

    # Sync DB in async
    await conn.execute("SELECT * FROM t")

    # Giant list comp
    result = [x for y in items for x in y]

    # Nested loop O(n²)
    for a in items:
        for b in items:
            pass

    # Missing set lookup
    if x in [1, 2, 3]:
        pass

    # subprocess in loop
    for i in items:
        subprocess.run(["cmd"])

    # json.load in loop
    for i in items:
        data = json.loads(i)

    # No batch processing
    for i in items:
        db.insert(i)

    # requests in loop
    for i in items:
        requests.get("http://example.com")

    # list() constructor waste
    result = list([1, 2, 3])

    # dict() constructor waste
    result = dict({"a": 1})

    # str concat in loop
    for i in items:
        s += "hello"

    # Large file read all
    data = f.read()
    for line in data:
        pass

    # Unbatched insert
    for i in items:
        cur.execute("INSERT INTO t (v) VALUES (1)")

    # Missing timeout
    response = requests.get("http://example.com")

    # Deep nested loop O(n³)
    for a in range(10):
        for b in range(10):
            for c in range(10):
                pass

    # Cache: Repeated API call
    r1 = requests.get("http://api.example.com")
    r2 = requests.get("http://api.example.com")

    # Cache: Identical query
    cur.execute("SELECT * FROM t")
    cur.execute("SELECT * FROM t")

    # Cache: Recomputed value
    print(len(items))
    print(len(items))
'''
        findings, cache_ops = opt._scan_file("core/comprehensive_test.py", content)
        pattern_names = [f.pattern_name for f in findings]
        cache_names = [c.pattern_name for c in cache_ops]

        # All 16 anti-patterns should be detected
        expected_anti_patterns = [
            "Sleep in loop",
            "Sync DB in async",
            "Giant list comp",
            "Nested loop O(n²)",
            "Missing set lookup",
            "subprocess in loop",
            "json.load in loop",
            "No batch processing",
            "requests in loop",
            "list() constructor waste",
            "dict() constructor waste",
            "str concat in loop",
            "Large file read all",
            "Unbatched insert",
            "Missing timeout",
            "Deep nested loop O(n³)",
        ]
        for p in expected_anti_patterns:
            assert any(p in n for n in pattern_names), f"Missing anti-pattern: {p}"

        # All 3 cache patterns should be detected
        expected_cache = [
            "Repeated API call",
            "Identical query",
            "Recomputed value",
        ]
        for c in expected_cache:
            assert any(c in cn for cn in cache_names), f"Missing cache pattern: {c}"
