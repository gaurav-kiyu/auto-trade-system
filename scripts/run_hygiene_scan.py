#!/usr/bin/env python3
"""Hygiene Security Scanner — OPB v2.57.0

Scans the codebase for:
  - Hardcoded secrets and credentials
  - API tokens and keys
  - Private keys and certificates
  - Connection strings with passwords
  - Placeholder values in config files
  - World-readable permissions on sensitive files
  - Stale temporary files

This is a lightweight alternative to commercial scanners like detect-secrets
or truffleHog, tailored to this project's patterns.

Usage:
    python scripts/run_hygiene_scan.py
    python scripts/run_hygiene_scan.py --json
    python scripts/run_hygiene_scan.py --ci
    python scripts/run_hygiene_scan.py --fix   # Auto-fix placeholder tokens
"""

from __future__ import annotations

import json
import os
import re
import stat
import sys
import time
from pathlib import Path
from typing import Any

# ── Configuration ─────────────────────────────────────────────────────────────

REPORTS_DIR = Path(__file__).resolve().parent.parent / "reports"
HTML_REPORT = REPORTS_DIR / "hygiene_scan_report.html"
JSON_REPORT = REPORTS_DIR / "hygiene_scan_report.json"

# Files and directories to exclude
EXCLUDE_PATTERNS = {
    ".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    ".venv", "venv", "node_modules", ".hypothesis", ".benchmarks",
    "logs", "models", "dist", "build", "*.egg-info",
    ".coverage", "coverage_html", "htmlcov",
    "reports",  # generated scan output must never become scan input
}

EXCLUDE_EXTENSIONS = {".pyc", ".pyo", ".db", ".db-shm", ".db-wal",
                       ".jpg", ".png", ".gif", ".svg", ".ico",
                       ".woff", ".woff2", ".ttf", ".eot",
                       ".pdf", ".pptx", ".xlsx",
                       ".exe", ".dll", ".so", ".dylib"}

# Patterns to detect
SECRET_PATTERNS: list[dict[str, Any]] = [
    # API Keys and Tokens
    {"pattern": r'(?i)(api[_-]?key|api[_-]?secret|api[_-]?token)\s*[:=]\s*["\']?[A-Za-z0-9_\-]{16,}["\']?',
     "name": "API Key/Token", "severity": "high"},
    {"pattern": r'(?i)(bot_token|chat_id)\s*[:=]\s*["\']["\']?[A-Za-z0-9_:]{20,}["\']?',
     "name": "Telegram Bot Token", "severity": "high"},
    {"pattern": r'(?i)(bearer|auth|authorization)\s*[:=]\s*["\']?[A-Za-z0-9_\-\.]{20,}["\']?',
     "name": "Bearer/Auth Token", "severity": "high"},
    # Password patterns
    {"pattern": r'(?i)(password|pwd|passwd)\s*[:=]\s*["\'][^"\']+["\']',
     "name": "Password", "severity": "high"},
    {"pattern": r'(?i)(secret|token|credential)\s*[:=]\s*["\'][^"\']{8,}["\']',
     "name": "Secret/Credential", "severity": "high"},
    # Connection strings
    {"pattern": r'(?i)(postgres(ql)?|mysql|mongodb|redis)://[^:]+:[^@]+@',
     "name": "Database Connection String (with password)", "severity": "high"},
    # Private keys
    {"pattern": r'-----BEGIN (RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----',
     "name": "Private Key", "severity": "critical"},
    # JWT tokens
    {"pattern": r'eyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}',
     "name": "JWT Token", "severity": "high"},
    # Placeholder tokens (low severity)
    {"pattern": r'(?i)(your_|change_me|placeholder|xxx|test_token|dummy|sample)',
     "name": "Placeholder Value", "severity": "low"},
    # AWS keys
    {"pattern": r'AKIA[0-9A-Z]{16}',
     "name": "AWS Access Key", "severity": "critical"},
    # GitHub tokens
    {"pattern": r'ghp_[A-Za-z0-9]{36}',
     "name": "GitHub Token", "severity": "critical"},
    # Slack tokens
    {"pattern": r'xox[baprs]-[0-9]{10,13}-[0-9]{10,13}-[A-Za-z0-9]{24}',
     "name": "Slack Token", "severity": "high"},
    # Generic base64-encoded secrets
    {"pattern": r'(?i)(base64|b64)[:=]\s*["\'][A-Za-z0-9+/=]{40,}["\']',
     "name": "Base64-encoded Secret", "severity": "medium"},
    # NSE/Broker credentials
    {"pattern": r'(?i)(kite|angel|zerodha|upstox|dhan)_?(api|secret|token|key|pass|pwd|password)\s*[:=]\s*["\'][^"\']+["\']',
     "name": "Broker Credential", "severity": "high"},
]

# Sensitive file patterns (files that should have restricted permissions)
SENSITIVE_FILES = [
    "*.key", "*.pem", "*.p12", "*.pfx", "*.crt", "*.cert",
    ".env", ".env.*", "json/config.local.json", "json/config.json",
    "credentials*.json", "secrets*.json",
]


def _should_exclude(filepath: Path) -> bool:
    """Check if a file should be excluded from scanning."""
    for part in filepath.parts:
        if part in EXCLUDE_PATTERNS:
            return True
    ext = filepath.suffix.lower()
    if ext in EXCLUDE_EXTENSIONS:
        return True
    return False


def _is_text_file(filepath: Path) -> bool:
    """Check if a file is likely a text file."""
    try:
        with open(filepath, "rb") as f:
            chunk = f.read(8192)
        return not bool(chunk.translate(None, bytes(range(32, 127)) + b"\n\r\t\f"))
    except OSError:
        return False


def _check_file_permissions(filepath: Path) -> dict[str, Any] | None:
    """Check if a sensitive file has world-readable permissions (Unix only)."""
    try:
        mode = os.stat(filepath).st_mode
        if mode & stat.S_IROTH:  # World-readable
            return {
                "file": str(filepath),
                "issue": "World-readable permissions",
                "permissions": oct(mode & 0o777),
                "severity": "medium",
            }
    except (OSError, AttributeError):
        pass
    return None


def scan_repository() -> dict[str, Any]:
    """Scan the repository for security hygiene issues."""
    root = Path.cwd()
    findings: list[dict[str, Any]] = []
    files_scanned = 0
    files_with_issues = 0
    sensitive_file_issues: list[dict[str, Any]] = []

    print("  Scanning for secrets, credentials, and hygiene issues...")

    for filepath in sorted(root.rglob("*")):
        if not filepath.is_file():
            continue
        if _should_exclude(filepath):
            continue
        if not _is_text_file(filepath):
            continue

        files_scanned += 1
        file_findings = 0

        try:
            relative = filepath.relative_to(root)
            content = filepath.read_text(encoding="utf-8", errors="replace")

            for i, line in enumerate(content.splitlines(), 1):
                for secret_def in SECRET_PATTERNS:
                    match = re.search(secret_def["pattern"], line)
                    if match:
                        # Test fixtures commonly use deterministic non-secret credentials
                        # (test_token, test_secret, redis://user:pass@...). They are not
                        # production credentials and should not block release hygiene.
                        rel_str = str(relative).replace("\\", "/")
                        test_fixture = rel_str.startswith("tests/") or rel_str.startswith("archive/unrelated_modules/tests/")
                        benign_test_credential = test_fixture and bool(re.search(
                            r"(?i)(test[:_-](token|secret|key|client|password)|test[_-](token|secret|key|client|password)|redis://user:pass@|instrument_token=\"?NSE_FO\|)",
                            line,
                        ))
                        if benign_test_credential and secret_def["severity"] == "high":
                            continue

                        # Mask the actual value in the finding
                        masked_line = line[:60] + "..." if len(line) > 60 else line
                        finding = {
                            "file": str(relative),
                            "line": i,
                            "pattern": secret_def["name"],
                            "severity": secret_def["severity"],
                            "match": masked_line[:100],
                            "type": "secret_pattern",
                        }
                        findings.append(finding)
                        file_findings += 1

        except (OSError, UnicodeDecodeError):
            continue

        if file_findings > 0:
            files_with_issues += 1

    # Check for sensitive files with world-readable permissions
    for pattern in SENSITIVE_FILES:
        for filepath in root.glob(pattern):
            if filepath.exists():
                issue = _check_file_permissions(filepath)
                if issue:
                    sensitive_file_issues.append(issue)

    # Summary by severity
    severity_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for f in findings:
        severity_counts[f["severity"]] = severity_counts.get(f["severity"], 0) + 1

    return {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S IST"),
        "root": str(root),
        "files_scanned": files_scanned,
        "files_with_issues": files_with_issues,
        "total_findings": len(findings),
        "findings": findings,
        "sensitive_file_issues": sensitive_file_issues,
        "by_severity": severity_counts,
        "has_critical": severity_counts["critical"] > 0,
        "has_high": severity_counts["high"] > 0,
    }


def _auto_fix_placeholders(results: dict[str, Any]) -> int:
    """Auto-fix placeholder values in config template files only.

    SAFETY: Only modifies .template.json and .env.example files to avoid
    accidentally corrupting production code or legitimate variable names.
    """
    fixed = 0
    CONFIG_TEMPLATE_FILES = {
        "json/config.template.json", "json/stock_config.template.json",
        ".env.example",
    }
    for finding in results.get("findings", []):
        if finding["severity"] != "low":
            continue
        filename = Path(finding["file"]).name
        if filename not in CONFIG_TEMPLATE_FILES:
            continue
        filepath = Path(finding["file"])
        if not filepath.exists():
            continue
        try:
            content = filepath.read_text(encoding="utf-8")
            if finding["pattern"] == "Placeholder Value":
                new_content = content.replace("your_", "__YOUR_")
                new_content = new_content.replace("change_me", "__CHANGE_ME__")
                if new_content != content:
                    filepath.write_text(new_content, encoding="utf-8")
                    fixed += 1
                    print(f"    🔧 Fixed placeholder in {finding['file']}")
        except OSError:
            pass
    return fixed


def _generate_html(results: dict[str, Any]) -> str:
    """Generate HTML report."""
    timestamp = results.get("timestamp", "")
    total = results.get("total_findings", 0)
    files_scanned = results.get("files_scanned", 0)

    by_severity = results.get("by_severity", {})

    rows = ""
    for f in results.get("findings", []):
        color = {"critical": "red", "high": "red", "medium": "orange", "low": "#FF9800"}.get(f["severity"], "")
        rows += f"""
        <tr style="color:{color};">
            <td>{f['severity'].upper()}</td>
            <td><code>{f['file']}:{f['line']}</code></td>
            <td>{f['pattern']}</td>
            <td>{f['match'][:80]}</td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Hygiene Scan Report — OPB v2.57.0</title>
<style>
body {{ font-family: -apple-system, sans-serif; margin: 20px; background: #f5f5f5; }}
h1, h2 {{ color: #333; }}
table {{ border-collapse: collapse; width: 100%; margin: 10px 0; background: #fff; }}
th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
th {{ background: #4A90D9; color: white; }}
tr:nth-child(even) {{ background: #f9f9f9; }}
.summary {{ background: #e8f5e9; padding: 15px; border-radius: 5px; margin: 10px 0; }}
.critical {{ background: #ffebee; padding: 15px; border-radius: 5px; margin: 10px 0; }}
</style>
</head>
<body>
<h1>🔒 Hygiene Security Scan Report</h1>
<div class="summary {'critical' if results['has_critical'] or results['has_high'] else ''}">
<p><strong>Timestamp:</strong> {timestamp}</p>
<p><strong>Files Scanned:</strong> {files_scanned}</p>
<p><strong>Total Findings:</strong> {total}</p>
<p><strong>By Severity:</strong> C={by_severity.get('critical',0)} H={by_severity.get('high',0)} M={by_severity.get('medium',0)} L={by_severity.get('low',0)}</p>
</div>
<h2>🔍 Findings</h2>
{'<table><tr><th>Severity</th><th>Location</th><th>Pattern</th><th>Match</th></tr>' + rows + '</table>' if rows else '<p>✅ No security findings. Repository is clean.</p>'}
<p style="color:#888; margin-top:30px;">Generated by OPB Hygiene Scanner v2.57.0</p>
</body>
</html>"""
    return html


def main() -> int:
    """CLI entry point."""
    import argparse
    parser = argparse.ArgumentParser(description="Hygiene Security Scanner")
    parser.add_argument("--json", action="store_true", help="Output JSON report")
    parser.add_argument("--no-html", action="store_true", help="Skip HTML generation")
    parser.add_argument("--ci", action="store_true", help="CI mode: exit non-zero on critical/high findings")
    parser.add_argument("--fix", action="store_true", help="Auto-fix placeholder values")
    args = parser.parse_args()

    os.makedirs(REPORTS_DIR, exist_ok=True)

    print("=" * 60)
    print("  HYGIENE SECURITY SCANNER v2.57.0")
    print("=" * 60)

    results = scan_repository()

    print(f"\n  Files scanned:     {results['files_scanned']}")
    print(f"  Files with issues: {results['files_with_issues']}")
    print(f"  Total findings:    {results['total_findings']}")
    print(f"  Critical:          {results['by_severity'].get('critical', 0)}")
    print(f"  High:              {results['by_severity'].get('high', 0)}")
    print(f"  Medium:            {results['by_severity'].get('medium', 0)}")
    print(f"  Low:               {results['by_severity'].get('low', 0)}")

    if results["findings"]:
        print("\n  Findings:")
        for f in results["findings"][:20]:
            print(f"    [{f['severity'].upper()}] {f['file']}:{f['line']} - {f['pattern']}: {f['match'][:60]}")
        if len(results["findings"]) > 20:
            print(f"    ... and {len(results['findings']) - 20} more")

    # Auto-fix if requested
    if args.fix:
        fixed = _auto_fix_placeholders(results)
        if fixed > 0:
            print(f"\n  🔧 Auto-fixed {fixed} placeholder(s)")

    if args.json:
        print(json.dumps(results, indent=2, default=str))

    if not args.no_html:
        html = _generate_html(results)
        HTML_REPORT.write_text(html, encoding="utf-8")
        print(f"\n  HTML report: {HTML_REPORT}")

    JSON_REPORT.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    print(f"  JSON report: {JSON_REPORT}")

    if args.ci:
        critical_high = results["by_severity"].get("critical", 0) + results["by_severity"].get("high", 0)
        if critical_high > 0:
            print(f"\n❌ CI FAILED: {critical_high} critical/high severity finding(s)")
            return 1

    print("\n" + "=" * 60)
    print("  HYGIENE SCAN COMPLETE")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
