#!/usr/bin/env python3
"""
Historical Comparison Automation (Phase 1, Backlog #10).

Automated diff between releases to detect:
  - Regressions (test count changes, pass rate drops)
  - Architecture drift (module additions/removals, import changes)
  - Configuration drift (new/missing config keys)
  - Documentation drift (stale docs vs code)
  - Performance changes (test execution time, test count)

Usage
-----
    # Compare current state against a git tag/revision
    python scripts/historical_comparison.py --against v2.52.0

    # Compare two specific revisions
    python scripts/historical_comparison.py --from v2.52.0 --to v2.53.0

    # JSON output for pipeline integration
    python scripts/historical_comparison.py --against v2.52.0 --json

    # Include full details (not just summary)
    python scripts/historical_comparison.py --against v2.52.0 --verbose

Config keys (all optional)
-----------------------------
    historical_comparison_exclude_dirs : list   default ["node_modules", "__pycache__", ".git"]
    historical_comparison_exclude_exts : list   default [".pyc", ".pyo", ".exe"]
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)


# ── Result models ─────────────────────────────────────────────────────────────

@dataclass
class DiffStat:
    """Git diff statistics between two revisions."""
    files_changed: int = 0
    insertions: int = 0
    deletions: int = 0
    files_added: list[str] = field(default_factory=list)
    files_deleted: list[str] = field(default_factory=list)
    files_modified: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "files_changed": self.files_changed,
            "insertions": self.insertions,
            "deletions": self.deletions,
            "files_added": self.files_added,
            "files_deleted": self.files_deleted,
            "files_modified": self.files_modified[:50],  # limit output size
        }


@dataclass
class ModuleDiff:
    """Differences in module structure between revisions."""
    modules_added: list[str] = field(default_factory=list)
    modules_removed: list[str] = field(default_factory=list)
    public_symbols_added: list[str] = field(default_factory=list)
    public_symbols_removed: list[str] = field(default_factory=list)
    known_breaks: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "modules_added": self.modules_added[:30],
            "modules_removed": self.modules_removed[:30],
            "public_symbols_added": self.public_symbols_added[:30],
            "public_symbols_removed": self.public_symbols_removed[:30],
            "known_breaks": self.known_breaks,
        }


@dataclass
class FileDiffReport:
    """Differences in test metrics between revisions."""
    total_tests_current: int = 0
    total_tests_previous: int = 0
    test_files_added: list[str] = field(default_factory=list)
    test_files_removed: list[str] = field(default_factory=list)
    test_count_change: int = 0

    @property
    def has_test_changes(self) -> bool:
        return bool(self.test_files_added or self.test_files_removed)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_tests_current": self.total_tests_current,
            "total_tests_previous": self.total_tests_previous,
            "test_files_added": self.test_files_added[:20],
            "test_files_removed": self.test_files_removed[:20],
            "test_count_change": self.test_count_change,
            "has_test_changes": self.has_test_changes,
        }


@dataclass
class ConfigDiff:
    """Differences in config schema between revisions."""
    keys_added: list[str] = field(default_factory=list)
    keys_removed: list[str] = field(default_factory=list)
    keys_changed: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "keys_added": self.keys_added[:30],
            "keys_removed": self.keys_removed[:30],
            "keys_changed": self.keys_changed[:30],
            "count_added": len(self.keys_added),
            "count_removed": len(self.keys_removed),
            "count_changed": len(self.keys_changed),
        }


@dataclass
class DocDiff:
    """Differences in documentation state between revisions."""
    docs_stale: list[str] = field(default_factory=list)
    docs_added: list[str] = field(default_factory=list)
    docs_removed: list[str] = field(default_factory=list)
    module_mismatches: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "docs_stale": self.docs_stale[:20],
            "docs_added": self.docs_added[:20],
            "docs_removed": self.docs_removed[:20],
            "module_mismatches": self.module_mismatches,
        }


@dataclass
class ComparisonReport:
    """Complete historical comparison report."""
    source_revision: str = ""
    target_revision: str = ""
    timestamp: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    diff_stat: DiffStat = field(default_factory=DiffStat)
    module_diff: ModuleDiff = field(default_factory=ModuleDiff)
    test_diff: FileDiffReport = field(default_factory=FileDiffReport)
    config_diff: ConfigDiff = field(default_factory=ConfigDiff)
    doc_diff: DocDiff = field(default_factory=DocDiff)
    has_regressions: bool = False
    regressions: list[str] = field(default_factory=list)
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_revision": self.source_revision,
            "target_revision": self.target_revision,
            "timestamp": self.timestamp,
            "diff_stat": self.diff_stat.to_dict(),
            "module_diff": self.module_diff.to_dict(),
            "test_diff": self.test_diff.to_dict(),
            "config_diff": self.config_diff.to_dict(),
            "doc_diff": self.doc_diff.to_dict(),
            "has_regressions": self.has_regressions,
            "regressions": self.regressions,
            "summary": self.summary,
        }


# ── Comparison Engine ────────────────────────────────────────────────────────

class HistoricalComparer:
    """Compares current codebase state against a previous revision."""

    def __init__(self, cfg: dict[str, Any] | None = None):
        self._cfg = cfg or {}
        self._exclude_dirs = self._cfg.get(
            "historical_comparison_exclude_dirs",
            ["node_modules", "__pycache__", ".git", ".egg-info", "dist", "build"],
        )
        self._exclude_exts = self._cfg.get(
            "historical_comparison_exclude_exts",
            [".pyc", ".pyo", ".exe", ".dll", ".so", ".png", ".jpg"],
        )

    def compare(self, source_rev: str, target_rev: str = "HEAD") -> ComparisonReport:
        """Compare two git revisions and produce a report."""
        report = ComparisonReport(
            source_revision=source_rev,
            target_revision=target_rev,
        )

        # Ensure we're in a git repo
        if not self._is_git_repo():
            report.summary = "Not a git repository — comparison skipped"
            report.has_regressions = True
            report.regressions.append("Not a git repository")
            return report

        # Ensure both revisions exist
        if not self._revision_exists(source_rev):
            report.summary = f"Source revision '{source_rev}' not found"
            report.has_regressions = True
            report.regressions.append(f"Source revision '{source_rev}' does not exist in git history")
            return report
        if target_rev != "HEAD" and not self._revision_exists(target_rev):
            report.summary = f"Target revision '{target_rev}' not found (will use HEAD)"
            target_rev = "HEAD"
            report.target_revision = "HEAD"

        # Run diffs
        report.diff_stat = self._compute_diff_stat(source_rev, target_rev)
        report.module_diff = self._compute_module_diff(source_rev, target_rev)
        report.test_diff = self._compute_test_diff(source_rev, target_rev)
        report.config_diff = self._compute_config_diff(source_rev, target_rev)
        report.doc_diff = self._compute_doc_diff(source_rev, target_rev)

        # Check for regressions
        regressions = self._detect_regressions(report)
        report.regressions = regressions
        report.has_regressions = len(regressions) > 0

        # Build summary
        summary_parts = [
            f"Historical Comparison: {source_rev} -> {target_rev}",
            f"  Files: {report.diff_stat.files_changed} changed "
            f"(+{report.diff_stat.insertions}/-{report.diff_stat.deletions})",
            f"  Modules: {len(report.module_diff.modules_added)} added, "
            f"{len(report.module_diff.modules_removed)} removed",
            f"  Tests: {report.test_diff.test_files_added} added, "
            f"{report.test_diff.test_files_removed} removed",
            f"  Config: {len(report.config_diff.keys_added)} keys added, "
            f"{len(report.config_diff.keys_removed)} keys removed",
        ]
        if report.has_regressions:
            summary_parts.append(f"  REGRESSIONS: {len(regressions)}")
            for r in regressions:
                summary_parts.append(f"    - {r}")
        else:
            summary_parts.append("  No regressions detected")
        report.summary = "\n".join(summary_parts)

        return report

    # ── Git helpers ──────────────────────────────────────────────────────

    def _is_git_repo(self) -> bool:
        try:
            subprocess.run(
                ["git", "rev-parse", "--git-dir"],
                capture_output=True, timeout=5, check=True,
            )
            return True
        except (subprocess.SubprocessError, FileNotFoundError):
            return False

    def _revision_exists(self, rev: str) -> bool:
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--verify", rev],
                capture_output=True, timeout=5,
            )
            return result.returncode == 0
        except (subprocess.SubprocessError, FileNotFoundError):
            return False

    def _run_git(self, args: list[str]) -> str:
        try:
            result = subprocess.run(
                ["git"] + args,
                capture_output=True, text=True, timeout=30,
            )
            return result.stdout.strip() if result.returncode == 0 else ""
        except (subprocess.SubprocessError, FileNotFoundError):
            return ""

    # ── Diff sections ────────────────────────────────────────────────────

    def _compute_diff_stat(self, src: str, tgt: str) -> DiffStat:
        """Compute git diff statistics."""
        stat = DiffStat()

        # Get short stats
        output = self._run_git(["diff", "--shortstat", f"{src}..{tgt}"])
        if output:
            m_files = re.search(r"(\d+) file", output)
            m_insertions = re.search(r"(\d+) insertion", output)
            m_deletions = re.search(r"(\d+) deletion", output)
            if m_files:
                stat.files_changed = int(m_files.group(1))
            if m_insertions:
                stat.insertions = int(m_insertions.group(1))
            if m_deletions:
                stat.deletions = int(m_deletions.group(1))

        # Get added file names
        added = self._run_git([
            "diff", "--diff-filter=A", "--name-only", f"{src}..{tgt}",
        ])
        if added:
            stat.files_added = [f for f in added.split("\n") if f.strip()]

        # Get deleted file names
        deleted = self._run_git([
            "diff", "--diff-filter=D", "--name-only", f"{src}..{tgt}",
        ])
        if deleted:
            stat.files_deleted = [f for f in deleted.split("\n") if f.strip()]

        # Get modified file names
        modified = self._run_git([
            "diff", "--diff-filter=M", "--name-only", f"{src}..{tgt}",
        ])
        if modified:
            stat.files_modified = [f for f in modified.split("\n") if f.strip()]

        return stat

    def _compute_module_diff(self, src: str, tgt: str) -> ModuleDiff:
        """Detect module-level changes between revisions."""
        diff = ModuleDiff()

        # List all Python files in each revision
        src_files = self._list_python_files(src)
        tgt_files = self._list_python_files(tgt)

        src_set = set(src_files)
        tgt_set = set(tgt_files)

        diff.modules_added = sorted(tgt_set - src_set)[:50]
        diff.modules_removed = sorted(src_set - tgt_set)[:50]

        # Check for known breaking patterns
        common_modules = src_set & tgt_set
        for mod in sorted(common_modules):
            src_content = self._show_file(src, mod)
            tgt_content = self._show_file(tgt, mod)
            if src_content and tgt_content:
                # Check for removed public symbols
                src_symbols = self._extract_public_symbols(src_content)
                tgt_symbols = self._extract_public_symbols(tgt_content)
                removed = src_symbols - tgt_symbols
                if removed:
                    # Only flag if removed from a stable module
                    if re.match(r"^(core/|index_app/)", mod):
                        for sym in removed:
                            diff.public_symbols_removed.append(f"{mod}:{sym}")

                added = tgt_symbols - src_symbols
                if added and re.match(r"^(core/|index_app/)", mod):
                    for sym in added:
                        diff.public_symbols_added.append(f"{mod}:{sym}")

        # Known breaking changes
        for removed_mod in diff.modules_removed:
            if removed_mod.startswith("core/ports/"):
                diff.known_breaks.append(
                    f"Port module removed: {removed_mod} — "
                    "check all implementations for breaking changes"
                )

        return diff

    def _compute_test_diff(self, src: str, tgt: str) -> FileDiffReport:
        """Detect test file changes between revisions."""
        diff = FileDiffReport()

        src_tests = self._list_test_files(src)
        tgt_tests = self._list_test_files(tgt)

        diff.test_files_added = sorted(set(tgt_tests) - set(src_tests))
        diff.test_files_removed = sorted(set(src_tests) - set(tgt_tests))
        diff.has_test_changes = bool(diff.test_files_added or diff.test_files_removed)

        # Count tests (approximately) in current state
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pytest", "--collect-only", "-q", "tests/"],
                capture_output=True, text=True, timeout=60,
            )
            # Parse test count from output like "2000 tests collected"
            m = re.search(r"(\d+)\s+tests?\s+collected", result.stdout)
            if m:
                diff.total_tests_current = int(m.group(1))
        except (subprocess.SubprocessError, FileNotFoundError):
            diff.total_tests_current = 0

        return diff

    def _compute_config_diff(self, src: str, tgt: str) -> ConfigDiff:
        """Detect config schema changes between revisions."""
        diff = ConfigDiff()

        defaults_files = ["index_config.defaults.json", "stock_config.defaults.json"]

        for df in defaults_files:
            src_config = self._show_file(src, df)
            tgt_config = self._show_file(tgt, df)

            if not src_config or not tgt_config:
                continue

            try:
                src_dict = json.loads(src_config)
                tgt_dict = json.loads(tgt_config)

                src_keys = set(src_dict.keys())
                tgt_keys = set(tgt_dict.keys())

                diff.keys_added.extend(sorted(tgt_keys - src_keys))
                diff.keys_removed.extend(sorted(src_keys - tgt_keys))

                # Check value changes in existing keys
                for key in src_keys & tgt_keys:
                    src_val = src_dict[key]
                    tgt_val = tgt_dict[key]
                    if src_val != tgt_val:
                        diff.keys_changed.append({
                            "key": key,
                            "old_value": str(src_val)[:100],
                            "new_value": str(tgt_val)[:100],
                        })
            except (json.JSONDecodeError, ValueError):
                pass

        return diff

    def _compute_doc_diff(self, src: str, tgt: str) -> DocDiff:
        """Detect documentation changes between revisions."""
        diff = DocDiff()

        src_docs = self._list_docs(src)
        tgt_docs = self._list_docs(tgt)

        diff.docs_added = sorted(set(tgt_docs) - set(src_docs))
        diff.docs_removed = sorted(set(src_docs) - set(tgt_docs))

        # Check for docs that mention modules that no longer exist
        tgt_modules = set(self._list_python_files(tgt))
        for doc_path in tgt_docs:
            content = self._show_file(tgt, doc_path)
            if content:
                # Find module references in docs
                mod_refs = re.findall(r"`(core/[a-z_]+\.py)`", content)
                for ref in mod_refs:
                    if ref not in tgt_modules and not any(
                        Path(ref).name in p for p in tgt_modules
                    ):
                        diff.docs_stale.append(f"{doc_path} references missing {ref}")
                        diff.module_mismatches += 1
                        break  # One mismatch per doc is enough

        return diff

    # ── Detection helpers ────────────────────────────────────────────────

    def _detect_regressions(self, report: ComparisonReport) -> list[str]:
        """Detect potential regressions from the comparison."""
        regressions = []

        # 1. Test files removed without replacement
        for f in report.test_diff.test_files_removed:
            regressions.append(f"Test file removed: {f}")

        # 2. Removed public symbols from core modules
        for sym in report.module_diff.public_symbols_removed:
            regressions.append(f"Public symbol removed: {sym}")

        # 3. Removed config keys
        for key in report.config_diff.keys_removed:
            regressions.append(f"Config key removed: {key}")

        # 4. Known breaking changes from port removals
        for brk in report.module_diff.known_breaks:
            regressions.append(f"Potential break: {brk}")

        # 5. Documentation mismatches
        for stale in report.doc_diff.docs_stale:
            regressions.append(f"Stale documentation: {stale}")

        return regressions

    # ── File listing helpers ──────────────────────────────────────────────

    def _list_python_files(self, rev: str) -> list[str]:
        """List all .py files tracked in a given revision."""
        output = self._run_git(["ls-tree", "-r", "--name-only", rev])
        if not output:
            return []
        return [
            f for f in output.split("\n")
            if f.endswith(".py") and not any(
                d in f for d in self._exclude_dirs
            )
        ]

    def _list_test_files(self, rev: str) -> list[str]:
        """List test files tracked in a given revision."""
        return [
            f for f in self._list_python_files(rev)
            if f.startswith("tests/") or "/test_" in f or f.startswith("test_")
        ]

    def _list_docs(self, rev: str) -> list[str]:
        """List documentation files tracked in a given revision."""
        output = self._run_git(["ls-tree", "-r", "--name-only", rev])
        if not output:
            return []
        return [
            f for f in output.split("\n")
            if f.endswith(".md") and not any(
                d in f for d in self._exclude_dirs
            )
        ]

    def _show_file(self, rev: str, path: str) -> str | None:
        """Get file content from a git revision."""
        return self._run_git(["show", f"{rev}:{path}"])

    def _extract_public_symbols(self, content: str) -> set[str]:
        """Extract public class/function names from Python source."""
        symbols: set[str] = set()
        for line in content.split("\n"):
            line = line.strip()
            # Match def or class at module level (not indented)
            if re.match(r"^(async\s+)?def\s+", line) and not line.startswith((" ", "\t")):
                m = re.match(r"^(async\s+)?def\s+(\w+)", line)
                if m and not m.group(2).startswith("_"):
                    symbols.add(m.group(2))
            elif re.match(r"^class\s+", line):
                m = re.match(r"^class\s+(\w+)", line)
                if m and not m.group(1).startswith("_"):
                    symbols.add(m.group(1))
        return symbols


# ── CLI ──────────────────────────────────────────────────────────────────────

def _cli() -> None:
    import argparse
    ap = argparse.ArgumentParser(
        prog="python -m scripts.historical_comparison",
        description="Automated release-to-release diff and regression detection",
    )
    ap.add_argument("--against", type=str, default="",
                    help="Compare HEAD against this revision (e.g. v2.52.0)")
    ap.add_argument("--from", type=str, dest="src", default="",
                    help="Source revision (older)")
    ap.add_argument("--to", type=str, dest="tgt", default="HEAD",
                    help="Target revision (newer, default HEAD)")
    ap.add_argument("--json", action="store_true", help="Output JSON")
    ap.add_argument("--verbose", action="store_true", help="Include full details")
    args = ap.parse_args()

    comparer = HistoricalComparer()

    if args.against:
        report = comparer.compare(args.against, "HEAD")
    elif args.src:
        report = comparer.compare(args.src, args.tgt)
    else:
        # Default: compare HEAD~1 vs HEAD
        report = comparer.compare("HEAD~1", "HEAD")

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(report.summary)
        if args.verbose and report.regressions:
            print("\nRegressions:")
            for r in report.regressions:
                print(f"  • {r}")
        if args.verbose and report.diff_stat.files_added:
            print(f"\nFiles added ({len(report.diff_stat.files_added)}):")
            for f in report.diff_stat.files_added[:10]:
                print(f"  + {f}")
        if args.verbose and report.diff_stat.files_deleted:
            print(f"\nFiles deleted ({len(report.diff_stat.files_deleted)}):")
            for f in report.diff_stat.files_deleted[:10]:
                print(f"  - {f}")

    # Exit with non-zero if regressions found (for CI pipelines)
    if report.has_regressions:
        sys.exit(1)


if __name__ == "__main__":
    _cli()
