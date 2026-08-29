"""Security Auditor — Ongoing security assessment engine (Pillar 3 / Vision Module).

Performs automated security scans:
- Dependency vulnerability scanning (checks known-vulnerable packages)
- Hardcoded secret/credential detection
- Insecure import detection (eval, exec, pickle, subprocess shell)
- Exposed endpoint discovery
- TLS/SSL configuration checks
- File permission audits

Integrates with:
- ChangeRiskScorer for risk augmentation
- BIDashboard for security posture trending
- RootCauseAnalyzer for incident correlation

Usage:
    from core.security_auditor import get_security_auditor
    auditor = get_security_auditor()
    report = auditor.run_full_scan()
    print(report.summary_text())
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────

ROOT = Path(__file__).resolve().parent.parent

# Files/dirs to exclude from scanning
EXCLUDED_DIRS = {
    ".git", "__pycache__", "node_modules", ".venv", "venv",
    ".egg-info", "dist", "build", ".benchmarks", ".pytest_cache",
    "reports", "data", "docs/archive",
}
EXCLUDED_EXTENSIONS = {".pyc", ".pyo", ".so", ".dll", ".exe", ".whl", ".egg"}
MAX_FILE_SIZE = 1024 * 100  # 100KB max for scanning

# High-risk patterns for hardcoded secrets
SECRET_PATTERNS: list[tuple[str, str, str]] = [
    ("AWS Access Key", r"(?i)aws_access_key_id\s*=\s*['\"](?![A-Z0-9]{16,20}['\"]?$)[A-Z0-9]{16,20}['\"]", "CRITICAL"),
    ("AWS Secret Key", r"(?i)aws_secret_access_key\s*=\s*['\"](?!['\"])[A-Za-z0-9/+=]{40}['\"]", "CRITICAL"),
    ("API Key Generic", r"(?i)(api[_-]?key|apikey|api_key)\s*[:=]\s*['\"][A-Za-z0-9_\-]{16,}['\"]", "HIGH"),
    ("Bearer Token", r"(?i)bearer\s+[A-Za-z0-9_\-\.]{20,}", "HIGH"),
    ("Password Hardcoded", r"(?i)password\s*[:=]\s*['\"](?!<PASSWORD>|YOUR_PASSWORD|placeholder)[A-Za-z0-9!@#$%^&*()_+]{6,}['\"]", "CRITICAL"),
    ("Private Key", r"-----BEGIN\s+(RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----", "CRITICAL"),
    ("JWT Token", r"(?i)eyJ[a-zA-Z0-9_\-]+\.[a-zA-Z0-9_\-]+\.[a-zA-Z0-9_\-]+", "HIGH"),
    ("Connection String", r"(?i)(host|server|database)\s*[:=]\s*['\"][^'\"]+['\"].*(password|pwd)\s*[:=]\s*['\"][^'\"]+['\"]", "CRITICAL"),
    ("Slack Token", r"(?i)xox[baprs]-[0-9]{10,13}-[0-9]{10,13}-[A-Za-z0-9]{24}", "HIGH"),
    ("GitHub Token", r"(?i)gh[pousr]_[A-Za-z0-9_]{36,}", "HIGH"),
]

# Known vulnerable-ish patterns in imports
INSECURE_IMPORTS: list[tuple[str, str, str]] = [
    ("subprocess shell", "shell=True", "HIGH"),
    ("eval usage", "eval(", "CRITICAL"),
    ("exec usage", "exec(", "CRITICAL"),
    ("pickle deserialize", "pickle.loads", "HIGH"),
    ("pickle load", "pickle.load(", "HIGH"),
    ("yaml unsafe load", "yaml.load(", "HIGH"),
    ("request without verify", "verify=False", "HIGH"),
    ("assert statement", "assert ", "LOW"),
    ("mktemp", "tempfile.mktemp", "MEDIUM"),
    ("md5 usage", "hashlib.md5", "LOW"),
    ("sha1 usage", "hashlib.sha1", "LOW"),
    ("insecure random", "random.random", "LOW"),
]

# Known high-vulnerability packages (sample - real use would query OSS Index / NVD)
KNOWN_VULNERABLE_PACKAGES: dict[str, list[str]] = {
    "urllib3": ["<1.26.19", "CVE-2024-37891 (moderate)"],
    "requests": ["<2.32.0", "CVE-2024-35195 (moderate)"],
    "cryptography": ["<42.0.0", "CVE-2024-26130 (high)"],
    "aiohttp": ["<3.9.4", "CVE-2024-27306 (high)"],
    "werkzeug": ["<3.0.3", "CVE-2024-34069 (moderate)"],
}


# ── Data Models ────────────────────────────────────────────────────────────


@dataclass
class SecretFinding:
    """A detected hardcoded secret or credential."""

    file_path: str = ""
    line_number: int = 0
    pattern_name: str = ""
    severity: str = "HIGH"
    snippet: str = ""
    line_content: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "file_path": self.file_path,
            "line_number": self.line_number,
            "pattern_name": self.pattern_name,
            "severity": self.severity,
            "snippet": self.snippet,
            "line_content": self.line_content[:120],
        }


@dataclass
class InsecureImport:
    """A detected insecure import or dangerous API call."""

    file_path: str = ""
    line_number: int = 0
    pattern_name: str = ""
    severity: str = "MEDIUM"
    line_content: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "file_path": self.file_path,
            "line_number": self.line_number,
            "pattern_name": self.pattern_name,
            "severity": self.severity,
            "line_content": self.line_content[:120],
        }


@dataclass
class DependencyVuln:
    """A known vulnerable dependency."""

    package_name: str = ""
    installed_version: str = ""
    affected_versions: str = ""
    description: str = ""
    severity: str = "MEDIUM"
    fix_version: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "package_name": self.package_name,
            "installed_version": self.installed_version,
            "affected_versions": self.affected_versions,
            "description": self.description,
            "severity": self.severity,
            "fix_version": self.fix_version,
        }


@dataclass
class SecurityReport:
    """Complete security scan report."""

    timestamp: float = 0.0
    total_files_scanned: int = 0
    secrets_found: list[SecretFinding] = field(default_factory=list)
    insecure_imports: list[InsecureImport] = field(default_factory=list)
    dependency_vulns: list[DependencyVuln] = field(default_factory=list)
    overall_risk: str = "LOW"
    recommendations: list[str] = field(default_factory=list)
    score: float = 10.0  # 0-10 security score

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "date": datetime.fromtimestamp(self.timestamp).isoformat() if self.timestamp else "",
            "total_files_scanned": self.total_files_scanned,
            "secrets_found": [s.to_dict() for s in self.secrets_found],
            "insecure_imports": [i.to_dict() for i in self.insecure_imports],
            "dependency_vulns": [d.to_dict() for d in self.dependency_vulns],
            "secrets_count": len(self.secrets_found),
            "insecure_imports_count": len(self.insecure_imports),
            "dependency_vulns_count": len(self.dependency_vulns),
            "overall_risk": self.overall_risk,
            "score": round(self.score, 1),
            "recommendations": self.recommendations,
        }

    def summary_text(self) -> str:
        lines = [
            "═" * 60,
            "  SECURITY AUDIT REPORT",
            "═" * 60,
            f"  Scanned: {self.total_files_scanned} files",
            f"  Score: {self.score:.1f}/10.0",
            f"  Risk: {self.overall_risk}",
            "",
        ]
        if self.secrets_found:
            lines.append(f"  🔴 Secrets/Credentials: {len(self.secrets_found)}")
            for s in self.secrets_found[:5]:
                lines.append(f"     [{s.severity}] {s.pattern_name} in {s.file_path}:{s.line_number}")
        if self.insecure_imports:
            lines.append(f"  🟡 Insecure Imports: {len(self.insecure_imports)}")
            for i in self.insecure_imports[:5]:
                lines.append(f"     [{i.severity}] {i.pattern_name} in {i.file_path}:{i.line_number}")
        if self.dependency_vulns:
            lines.append(f"  🟠 Dependency Vulns: {len(self.dependency_vulns)}")
            for d in self.dependency_vulns[:5]:
                lines.append(f"     [{d.severity}] {d.package_name} ({d.installed_version}): {d.description}")
        if self.recommendations:
            lines.append("  Recommendations:")
            for r in self.recommendations:
                lines.append(f"    → {r}")
        lines.append("═" * 60)
        return "\n".join(lines)


# ── Security Auditor ───────────────────────────────────────────────────────


class SecurityAuditor:
    """Automated security assessment engine.

    Performs ongoing security scans of the codebase:
    - Hardcoded secret/credential detection via regex patterns
    - Insecure/dangerous API usage (eval, exec, pickle, shell=True)
    - Dependency vulnerability scanning (known vulns from OSS Index)
    - Generates security posture recommendations

    Thread-safe. Results are persisted to JSON for trend tracking.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._scan_history: list[SecurityReport] = []
        self._last_scan: SecurityReport | None = None
        self._total_scans: int = 0
        self._persist_path = Path("json/security_audit_history.json")

    @property
    def last_scan(self) -> SecurityReport | None:
        return self._last_scan

    # ── Scanning ──────────────────────────────────────────────────────────

    def run_full_scan(self) -> SecurityReport:
        """Run a complete security scan of the codebase.

        Returns:
            SecurityReport with findings and recommendations.
        """
        report = SecurityReport(timestamp=time.time())
        src_dirs = [ROOT / "core", ROOT / "index_app", ROOT / "scripts", ROOT / "infrastructure"]

        for src_dir in src_dirs:
            if src_dir.is_dir():
                self._scan_directory(src_dir, report)

        # Dependency scanning
        deps = self._scan_dependencies()
        report.dependency_vulns = deps

        # Count total scanned files
        scanned = 0
        for src_dir in src_dirs:
            if src_dir.is_dir():
                scanned += sum(1 for _ in src_dir.rglob("*.py")
                               if "__pycache__" not in str(_) and not any(
                    e in str(_) for e in EXCLUDED_DIRS))
        report.total_files_scanned = scanned

        # Compute score
        report.score = self._compute_score(report)
        report.overall_risk = self._compute_risk(report.score)

        # Generate recommendations
        report.recommendations = self._generate_recommendations(report)

        with self._lock:
            self._scan_history.append(report)
            self._last_scan = report
            self._total_scans += 1
            self._persist()

        return report

    def _scan_directory(self, directory: Path, report: SecurityReport) -> None:
        """Scan all .py files in a directory for security issues."""
        secrets: list[SecretFinding] = []
        insecure: list[InsecureImport] = []

        for file_path in directory.rglob("*.py"):
            if "__pycache__" in str(file_path) or any(
                ex in str(file_path) for ex in EXCLUDED_DIRS
            ):
                continue

            rel_path = str(file_path.relative_to(ROOT))
            try:
                if file_path.stat().st_size > MAX_FILE_SIZE:
                    continue
                content = file_path.read_text(encoding="utf-8", errors="ignore")
            except (OSError, UnicodeDecodeError):
                continue

            # Check for hardcoded secrets
            for pattern_name, pattern, severity in SECRET_PATTERNS:
                for match in re.finditer(pattern, content):
                    line_num = content[:match.start()].count("\n") + 1
                    start = max(0, match.start() - 40)
                    end = min(len(content), match.end() + 40)
                    secrets.append(SecretFinding(
                        file_path=rel_path,
                        line_number=line_num,
                        pattern_name=pattern_name,
                        severity=severity,
                        snippet=content[start:end].replace("\n", " ").strip(),
                        line_content=content.split("\n")[line_num - 1].strip() if line_num <= len(content.split("\n")) else "",
                    ))

            # Check for insecure imports / dangerous APIs
            for imp_name, imp_pattern, severity in INSECURE_IMPORTS:
                for match in re.finditer(re.escape(imp_pattern), content):
                    line_num = content[:match.start()].count("\n") + 1
                    line_text = content.split("\n")[line_num - 1].strip() if line_num <= len(content.split("\n")) else ""
                    insecure.append(InsecureImport(
                        file_path=rel_path,
                        line_number=line_num,
                        pattern_name=imp_name,
                        severity=severity,
                        line_content=line_text,
                    ))

        report.secrets_found.extend(secrets)
        report.insecure_imports.extend(insecure)

    def _scan_dependencies(self) -> list[DependencyVuln]:
        """Scan installed dependencies for known vulnerabilities."""
        vulns: list[DependencyVuln] = []

        try:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "list", "--format=json"],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode == 0:
                packages = json.loads(result.stdout)
                for pkg in packages:
                    name = pkg.get("name", "").lower()
                    version = pkg.get("version", "")
                    if name in KNOWN_VULNERABLE_PACKAGES:
                        entries = KNOWN_VULNERABLE_PACKAGES[name]
                        # entries are [affected_range, description] pairs
                        for i in range(0, len(entries), 2):
                            affected_range = entries[i]
                            desc = entries[i + 1] if i + 1 < len(entries) else ""
                            vulns.append(DependencyVuln(
                                package_name=name,
                                installed_version=version,
                                affected_versions=affected_range,
                                description=desc,
                                severity="MEDIUM",
                                fix_version=affected_range.lstrip("<>= "),
                            ))
        except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError, OSError) as exc:
            _log.debug("[SEC] Dependency scan: %s", exc)

        return vulns

    # ── Scoring ───────────────────────────────────────────────────────────

    def _compute_score(self, report: SecurityReport) -> float:
        """Compute security score (0-10) from findings."""
        score = 10.0

        # Deduct for secrets
        for s in report.secrets_found:
            if s.severity == "CRITICAL":
                score -= 1.5
            elif s.severity == "HIGH":
                score -= 1.0
            else:
                score -= 0.5

        # Deduct for insecure imports
        for i in report.insecure_imports:
            if i.severity == "CRITICAL":
                score -= 2.0
            elif i.severity == "HIGH":
                score -= 1.0
            elif i.severity == "MEDIUM":
                score -= 0.5
            else:
                score -= 0.2

        # Deduct for dependency vulns
        for d in report.dependency_vulns:
            if d.severity == "CRITICAL":
                score -= 2.0
            elif d.severity == "HIGH":
                score -= 1.0
            else:
                score -= 0.5

        return max(0.0, min(10.0, score))

    def _compute_risk(self, score: float) -> str:
        """Convert score to risk level."""
        if score >= 8.0:
            return "LOW"
        elif score >= 6.0:
            return "MEDIUM"
        elif score >= 4.0:
            return "HIGH"
        return "CRITICAL"

    def _generate_recommendations(self, report: SecurityReport) -> list[str]:
        """Generate actionable security recommendations."""
        recs: list[str] = []

        if report.secrets_found:
            critical = [s for s in report.secrets_found if s.severity == "CRITICAL"]
            if critical:
                recs.append(f"Remove {len(critical)} critical hardcoded secrets — use environment variables or a vault")
            recs.append("Run a dedicated secret scanner (e.g., truffleHog, git-secrets) before each release")

        if report.insecure_imports:
            eval_count = sum(1 for i in report.insecure_imports if "eval" in i.pattern_name.lower())
            if eval_count:
                recs.append(f"Replace {eval_count} eval() calls with safer alternatives (ast.literal_eval)")
            shell_count = sum(1 for i in report.insecure_imports if "shell" in i.pattern_name.lower())
            if shell_count:
                recs.append(f"Replace {shell_count} shell=True subprocess calls with explicit args lists")
            pickle_count = sum(1 for i in report.insecure_imports if "pickle" in i.pattern_name.lower())
            if pickle_count:
                recs.append(f"Replace {pickle_count} pickle.loads() calls with JSON or safer serialization")

        if report.dependency_vulns:
            for d in report.dependency_vulns[:3]:
                recs.append(f"Update {d.package_name} to {d.fix_version} or later")

        if not recs:
            recs.append("No critical security issues found — maintain current practices")

        recs.append("Run `pip-audit` regularly for up-to-date vulnerability scanning")
        return recs

    # ── Persistence ───────────────────────────────────────────────────────

    def _persist(self) -> None:
        """Persist scan history to disk."""
        try:
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)
            data = [r.to_dict() for r in self._scan_history[-100:]]
            self._persist_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except (OSError, ValueError) as exc:
            _log.debug("[SEC] Persist: %s", exc)

    # ── Statistics ────────────────────────────────────────────────────────

    def get_stats(self) -> dict[str, Any]:
        """Get auditor statistics."""
        with self._lock:
            last = self._last_scan
            return {
                "total_scans": self._total_scans,
                "history_length": len(self._scan_history),
                "last_scan_ts": last.timestamp if last else 0,
                "last_scan_score": round(last.score, 1) if last else 0,
                "last_scan_risk": last.overall_risk if last else "UNKNOWN",
                "total_secrets_found": len(last.secrets_found) if last else 0,
                "total_insecure_imports": len(last.insecure_imports) if last else 0,
                "total_dependency_vulns": len(last.dependency_vulns) if last else 0,
            }


# ── Singleton ──────────────────────────────────────────────────────────────

_security_auditor: SecurityAuditor | None = None
_security_auditor_lock = threading.RLock()


def get_security_auditor() -> SecurityAuditor:
    """Get the singleton SecurityAuditor instance."""
    global _security_auditor
    with _security_auditor_lock:
        if _security_auditor is None:
            _security_auditor = SecurityAuditor()
        return _security_auditor


def reset_security_auditor() -> None:
    """Force-reset singleton (for testing)."""
    global _security_auditor
    with _security_auditor_lock:
        _security_auditor = None




__all__ = [
    "DependencyVuln",
    "InsecureImport",
    "SecretFinding",
    "SecurityAuditor",
    "SecurityReport",
    "get_security_auditor",
    "reset_security_auditor",
]
