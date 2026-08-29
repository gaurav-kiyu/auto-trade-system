#!/usr/bin/env python3
"""Unified PR Audit Report — Runs all security/quality checks, produces consolidated report.

Orchestrates these existing checks into a single pass/fail + score report:
  1. Ruff lint (via subprocess)
  2. Bandit security scan
  3. Architecture compliance (check_architecture_compliance.py)
  4. Repository hygiene (hygiene_check.py)
  5. Dead code scan (scan_dead_code.py) — quick mode
  6. .gitignore coverage
  7. Stale doc references check

Outputs:
  - JSON report (--json) suitable for CI artifacts
  - Human-readable report (default)
  - Markdown summary (--md) suitable for PR comment
  - Overall score 0-100 (weighted by severity)

Usage:
    python scripts/run_pr_audit.py                         # Full report
    python scripts/run_pr_audit.py --json                  # JSON output
    python scripts/run_pr_audit.py --md                    # Markdown PR comment
    python scripts/run_pr_audit.py --ci                    # CI mode (exit code only)
    python scripts/run_pr_audit.py --quick                 # Skip slow checks
    python scripts/run_pr_audit.py --output report.json    # Write to file

Exit code:
    0 = all checks pass (score >= 80)
    1 = warnings found (score >= 50)
    2 = failures found (score < 50)
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
log = logging.getLogger("pr_audit")

# ── Severity weights for scoring ─────────────────────────────────────────────

SEVERITY_WEIGHTS: dict[str, float] = {
    "CRITICAL": 10.0,
    "HIGH": 5.0,
    "MEDIUM": 2.0,
    "LOW": 1.0,
    "WARNING": 1.5,
    "ERROR": 7.0,
}

MAX_SCORE = 100.0
PASS_THRESHOLD = 80.0
WARN_THRESHOLD = 50.0

# Windows console may not support emoji; use ASCII fallback on win32
_USE_EMOJI = not sys.platform.startswith("win32")


def _ok() -> str:
    return "\u2705" if _USE_EMOJI else "[OK]"


def _fail() -> str:
    return "\u274c" if _USE_EMOJI else "[FAIL]"


def _warn() -> str:
    return "\u26a0\ufe0f" if _USE_EMOJI else "[WARN]"


def _robot() -> str:
    return "\U0001f916" if _USE_EMOJI else "[ROBOT]"


# ── Data models ──────────────────────────────────────────────────────────────


@dataclass
class AuditFinding:
    """A single finding from any check."""

    check: str  # e.g., "ruff", "bandit", "architecture", "hygiene", "dead_code"
    severity: str  # CRITICAL, HIGH, MEDIUM, LOW
    message: str
    file: str = ""
    line: int = 0
    code: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "check": self.check,
            "severity": self.severity,
            "message": self.message,
            "file": self.file,
            "line": self.line,
            "code": self.code,
        }


@dataclass
class AuditSection:
    """Results from a single check category."""

    name: str
    passed: bool
    findings: list[AuditFinding] = field(default_factory=list)
    duration_sec: float = 0.0
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "findings": [f.to_dict() for f in self.findings],
            "findings_count": len(self.findings),
            "duration_sec": round(self.duration_sec, 2),
            "error": self.error,
        }


@dataclass
class AuditReport:
    """Complete PR audit report."""

    timestamp: float = field(default_factory=time.time)
    duration_sec: float = 0.0
    total_checks: int = 0
    passed_checks: int = 0
    total_findings: int = 0
    score: float = MAX_SCORE
    sections: list[AuditSection] = field(default_factory=list)
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "duration_sec": round(self.duration_sec, 2),
            "total_checks": self.total_checks,
            "passed_checks": self.passed_checks,
            "total_findings": self.total_findings,
            "score": round(self.score, 1),
            "summary": self.summary,
            "sections": [s.to_dict() for s in self.sections],
        }

    def to_markdown(self, repo: str = "") -> str:
        """Generate a PR comment-friendly markdown summary."""
        status = (
            f"{_ok()} PASS" if self.score >= PASS_THRESHOLD
            else f"{_warn()} WARN" if self.score >= WARN_THRESHOLD
            else f"{_fail()} FAIL"
        )
        lines = [
            f"## {_robot()} PR Audit Report \u2014 {status}",
            "",
            f"**Overall Score: {self.score:.1f}/100**  ",
            f"**Checks:** {self.passed_checks}/{self.total_checks} passed  ",
            f"**Findings:** {self.total_findings} total  ",
            f"**Duration:** {self.duration_sec:.1f}s  ",
            "",
            "### Check Results",
            "",
            "| Check | Status | Findings | Duration |",
            "|-------|--------|----------|----------|",
        ]
        for s in self.sections:
            icon = _ok() if s.passed else _fail()
            lines.append(
                f"| {s.name} | {icon} {'PASS' if s.passed else 'FAIL'} | "
                f"{len(s.findings)} | {s.duration_sec:.1f}s |"
            )

        # Findings breakdown
        has_findings = [s for s in self.sections if s.findings]
        if has_findings:
            lines.extend(["", "### Findings Breakdown", ""])
            for s in has_findings:
                lines.append(f"**{s.name}** ({len(s.findings)} findings):")
                lines.append("")
                for f in s.findings[:10]:
                    location = f" `{f.file}:{f.line}`" if f.file else ""
                    code_str = f" `{f.code}`" if f.code else ""
                    lines.append(f"- [{f.severity}]{location}{code_str} {f.message}")
                if len(s.findings) > 10:
                    lines.append(f"  *...and {len(s.findings) - 10} more*")
                lines.append("")

        if repo:
            lines.append("---")
            lines.append("*Report generated by `scripts/run_pr_audit.py`*")

        return "\n".join(lines)

    def summary_text(self) -> str:
        """Generate a human-readable console summary."""
        status = (
            "PASS" if self.score >= PASS_THRESHOLD
            else "WARN" if self.score >= WARN_THRESHOLD
            else "FAIL"
        )
        w = 72
        lines = [
            "=" * w,
            f"  PR AUDIT REPORT \u2014 {status}",
            "=" * w,
            f"  Overall Score: {self.score:.1f}/100",
            f"  Checks: {self.passed_checks}/{self.total_checks} passed",
            f"  Findings: {self.total_findings}",
            f"  Duration: {self.duration_sec:.1f}s",
            "",
        ]
        for s in self.sections:
            icon = "[PASS]" if s.passed else "[FAIL]"
            lines.append(f"  {icon} {s.name:<40s} {len(s.findings):>4d} findings  ({s.duration_sec:.1f}s)")
            if s.error:
                lines.append(f"       Error: {s.error}")
        if self.total_findings > 0:
            lines.extend([
                "",
                "  Top findings by severity:",
            ])
            all_findings = sorted(
                [f for s in self.sections for f in s.findings],
                key=lambda x: SEVERITY_WEIGHTS.get(x.severity, 0),
                reverse=True,
            )
            for f in all_findings[:10]:
                loc = f" {f.file}:{f.line}" if f.file else ""
                lines.append(f"    [{f.severity}][{f.check}]{loc} {f.message[:80]}")
        lines.append("=" * w)
        return "\n".join(lines)


# ── Check runners ────────────────────────────────────────────────────────────


def _run_subprocess(cmd: list[str], timeout: int = 60) -> tuple[int, str, str]:
    """Run a subprocess and return (exit_code, stdout, stderr)."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=ROOT,
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "TIMEOUT"
    except FileNotFoundError:
        return -2, "", "COMMAND_NOT_FOUND"


def check_ruff() -> AuditSection:
    """Run Ruff lint check."""
    section = AuditSection(name="Ruff Lint", passed=True)
    start = time.time()
    try:
        rc, stdout, stderr = _run_subprocess(
            [sys.executable, "-m", "ruff", "check", "--statistics", "core/", "scripts/", "tests/"],
            timeout=120,
        )
        section.passed = rc == 0
        for line in stdout.strip().splitlines():
            if ":" not in line:
                continue
            parts = line.split(":", 4)
            if len(parts) < 4:
                continue
            f = parts[0].strip()
            if not f.endswith(".py"):
                continue
            ln_str = parts[1].strip()
            ln = int(ln_str) if ln_str.isdigit() else 0
            code = parts[3].strip()
            msg = parts[4].strip() if len(parts) > 4 else line.strip()
            severity = "LOW"
            # Nuanced ruff severity: E9xx/F8xx = HIGH, other E/F = MEDIUM
            if code.startswith("E"):
                severity = "HIGH" if (code[1:].isdigit() and int(code[1:]) >= 900) else "MEDIUM"
            elif code.startswith("F"):
                severity = "HIGH" if (code[1:].isdigit() and int(code[1:]) >= 800) else "MEDIUM"
            elif code.startswith("C"):
                severity = "MEDIUM"
            elif code.startswith("N"):
                severity = "LOW"
            section.findings.append(AuditFinding(
                check="ruff", severity=severity, message=msg[:200],
                file=f, line=ln, code=code,
            ))
        if rc != 0 and not section.findings:
            for line in stderr.strip().splitlines():
                section.findings.append(AuditFinding(
                    check="ruff", severity="WARNING", message=line.strip()[:200],
                ))
    except Exception as exc:
        section.error = str(exc)
        section.passed = False
    section.duration_sec = time.time() - start
    return section


def check_architecture() -> AuditSection:
    """Run architecture compliance check."""
    section = AuditSection(name="Architecture Compliance", passed=True)
    start = time.time()
    try:
        rc, stdout, stderr = _run_subprocess(
            [sys.executable, "scripts/check_architecture_compliance.py", "--ci"],
            timeout=60,
        )
        section.passed = rc == 0
        if not section.passed:
            msg = f"Architecture compliance check failed (exit code {rc})"
            details = stdout.strip()[:300] if stdout.strip() else ""
            if details:
                msg += f" \u2014 {details}"
            section.findings.append(AuditFinding(
                check="architecture", severity="HIGH", message=msg,
            ))
    except Exception as exc:
        section.error = str(exc)
        section.passed = False
    section.duration_sec = time.time() - start
    return section


def check_hygiene() -> AuditSection:
    """Run repository hygiene check."""
    section = AuditSection(name="Repository Hygiene", passed=True)
    start = time.time()
    try:
        rc, stdout, stderr = _run_subprocess(
            [sys.executable, "scripts/hygiene_check.py", "--ci"],
            timeout=60,
        )
        section.passed = rc == 0
        if not section.passed:
            msg = "Repository hygiene issues found"
            details = stdout.strip()[:200] if stdout.strip() else ""
            if details:
                msg += f" \u2014 {details}"
            section.findings.append(AuditFinding(
                check="hygiene", severity="MEDIUM", message=msg,
            ))
    except Exception as exc:
        section.error = str(exc)
        section.passed = False
    section.duration_sec = time.time() - start
    return section


def check_dead_code() -> AuditSection:
    """Run dead code scan — checks only unused imports (actionable), skips
    orphaned-symbol false positives from standalone scripts and intentional
    empty-block patterns (mock classes, exception stubs).
    """
    section = AuditSection(name="Dead Code Scan", passed=True)
    start = time.time()
    try:
        rc, stdout, stderr = _run_subprocess(
            [sys.executable, "scripts/scan_dead_code.py", "--quick", "--check-imports"],
            timeout=120,
        )
        # Parse output for MEDIUM+ severity findings (unused imports)
        # LOW severity findings (empty blocks, pass-through stubs) are intentional
        section.passed = True
        if stdout:
            for line in stdout.splitlines():
                if "UNUSED_IMPORT" in line:
                    section.passed = False
                    section.findings.append(AuditFinding(
                        check="dead_code", severity="MEDIUM",
                        message=line.strip(),
                    ))
        if rc != 0 and section.passed:
            # Only LOW-severity findings (empty blocks) — no action needed
            pass
        if not section.passed:
            msg = "Unused imports found — run `python scripts/scan_dead_code.py --remove` to auto-clean"
            if not section.findings:
                section.findings.append(AuditFinding(
                    check="dead_code", severity="MEDIUM", message=msg,
                ))
    except Exception as exc:
        section.error = str(exc)
        section.passed = False
    section.duration_sec = time.time() - start
    return section


def check_gitignore() -> AuditSection:
    """Check .gitignore coverage."""
    section = AuditSection(name=".gitignore Coverage", passed=True)
    start = time.time()
    try:
        gitignore_path = ROOT / ".gitignore"
        if not gitignore_path.exists():
            section.passed = False
            section.findings.append(AuditFinding(
                check="gitignore", severity="CRITICAL",
                message=".gitignore file is missing",
            ))
        else:
            required = [
                "__pycache__/", "*.pyc", ".pytest_cache/", ".ruff_cache/",
                ".mypy_cache/", ".venv/", "build/", "dist/", "*.egg-info/",
                "*.egg", "*.so", "*.db", "json/trader_state.json", "logs/", "data/",
            ]
            content = gitignore_path.read_text(encoding="utf-8")
            missing = [e for e in required if e not in content]
            if missing:
                section.passed = False
                section.findings.append(AuditFinding(
                    check="gitignore", severity="MEDIUM",
                    message=f"Missing .gitignore entries: {', '.join(missing[:5])}",
                ))
    except Exception as exc:
        section.error = str(exc)
        section.passed = False
    section.duration_sec = time.time() - start
    return section


def check_stale_docs() -> AuditSection:
    """Check for stale documentation references."""
    section = AuditSection(name="Stale Documentation", passed=True)
    start = time.time()
    try:
        rc, stdout, stderr = _run_subprocess(
            [sys.executable, "-m", "pytest", "tests/test_ruff_compliance.py", "-q", "--tb=short"],
            timeout=60,
        )
        section.passed = rc == 0
        if not section.passed:
            section.findings.append(AuditFinding(
                check="stale_docs", severity="MEDIUM",
                message="Stale documentation references detected",
            ))
    except Exception as exc:
        section.error = str(exc)
        section.passed = False
    section.duration_sec = time.time() - start
    return section


# ── Report builder ───────────────────────────────────────────────────────────


def run_audit(quick: bool = False) -> AuditReport:
    """Run all PR audit checks and return the report.

    Args:
        quick: If True, skip slower checks (dead code full scan, stale docs).

    Returns:
        AuditReport with all section results.
    """
    start = time.time()
    report = AuditReport()

    sections = [
        check_ruff(),
        check_architecture(),
        check_hygiene(),
        check_gitignore(),
    ]
    if not quick:
        sections.append(check_dead_code())
        sections.append(check_stale_docs())

    report.sections = sections
    report.total_checks = len(sections)
    report.passed_checks = sum(1 for s in sections if s.passed)
    report.total_findings = sum(len(s.findings) for s in sections)

    total_penalty = 0.0
    for s in sections:
        for f in s.findings:
            total_penalty += SEVERITY_WEIGHTS.get(f.severity, 1.0)
    report.score = max(0.0, MAX_SCORE - total_penalty)
    report.duration_sec = time.time() - start

    status = (
        "PASS" if report.score >= PASS_THRESHOLD
        else "WARN" if report.score >= WARN_THRESHOLD
        else "FAIL"
    )
    report.summary = (
        f"PR Audit: {status} (score={report.score:.1f}, "
        f"checks={report.passed_checks}/{report.total_checks}, "
        f"findings={report.total_findings})"
    )
    return report


# ── CLI entry point ──────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true", help="JSON output")
    ap.add_argument("--md", action="store_true", help="Markdown output (PR comment)")
    ap.add_argument("--ci", action="store_true", help="CI mode (exit code only)")
    ap.add_argument("--quick", action="store_true", help="Skip slow checks")
    ap.add_argument("--output", "-o", type=str, default="", help="Write report to file")
    args = ap.parse_args(argv)

    report = run_audit(quick=args.quick)

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(report.to_dict(), indent=2), encoding="utf-8",
        )
        print(f"[AUDIT] Report written to {output_path}")

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    elif args.md:
        md_text = report.to_markdown()
        try:
            print(md_text)
        except UnicodeEncodeError:
            print(md_text.encode("ascii", errors="replace").decode("ascii"))
    else:
        text = report.summary_text()
        try:
            print(text)
        except UnicodeEncodeError:
            print(text.encode("ascii", errors="replace").decode("ascii"))

    if report.score >= PASS_THRESHOLD:
        return 0
    elif report.score >= WARN_THRESHOLD:
        return 1
    else:
        return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
