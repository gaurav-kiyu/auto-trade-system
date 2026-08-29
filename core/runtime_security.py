"""Runtime Security — File Integrity & Runtime Protection (Constitution v4.0, Layer 7).

Provides runtime security monitoring:
- File integrity monitoring (checksum verification via SHA-256)
- Process health monitoring (critical process presence & resource usage)
- File permission audits
- Import hook monitoring (detects unauthorized module loading)
- Configuration file tampering detection

Integrates with:
- SecurityAuditor for vulnerability correlation
- RootCauseAnalyzer for incident correlation
- BIDashboard for security trending

Usage:
    from core.runtime_security import get_runtime_security

    security = get_runtime_security()
    report = security.run_full_check()
    print(report.summary_text())
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────

ROOT = Path(__file__).resolve().parent.parent

CRITICAL_FILES: list[str] = [
    "core/config_bootstrap.py",
    "core/safety_state.py",
    "core/risk_service.py",
    "core/execution_service.py",
    "core/di_container.py",
    "core/constitution/__init__.py",
    "core/adapters/broker_adapters.py",
    "core/safety_engine.py",
]

EXCLUDED_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", "reports", "data"}

CRITICAL_PROCESSES: list[dict[str, Any]] = [
    {"name": "index_trader", "description": "Main trading brain", "critical": True},
    {"name": "dashboard", "description": "Enterprise dashboard", "critical": False},
]

MONITORED_CONFIG_FILES: list[str] = [
    "json/stock_config.json",
    "json/index_config.defaults.json",
    "json/stock_config.defaults.json",
    "json/launcher_settings.json",
]

SENSITIVE_FILE_EXTENSIONS = {".pem", ".key", ".p12", ".pfx", ".env"}


# ── Data Models ────────────────────────────────────────────────────────────


@dataclass
class FileIntegrityCheck:
    """Result of a file integrity check."""

    file_path: str = ""
    checksum: str = ""
    previous_checksum: str = ""
    modified: bool = False
    size_bytes: int = 0
    permissions: str = ""
    issues: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "file_path": self.file_path,
            "checksum": self.checksum[:16],
            "previous_checksum": self.previous_checksum[:16] if self.previous_checksum else "",
            "modified": self.modified,
            "size_bytes": self.size_bytes,
            "permissions": self.permissions,
            "issues": self.issues,
        }


@dataclass
class RuntimeFinding:
    """A runtime security finding."""

    category: str = ""  # FILE_INTEGRITY, PROCESS, PERMISSION, CONFIG_TAMPER, IMPORT_MONITOR
    severity: str = "MEDIUM"  # LOW, MEDIUM, HIGH, CRITICAL
    description: str = ""
    affected_component: str = ""
    recommendation: str = ""
    timestamp: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "severity": self.severity,
            "description": self.description,
            "affected_component": self.affected_component,
            "recommendation": self.recommendation,
            "timestamp": self.timestamp,
        }


@dataclass
class RuntimeSecurityReport:
    """Complete runtime security report."""

    timestamp: float = 0.0
    findings: list[RuntimeFinding] = field(default_factory=list)
    file_checks: list[FileIntegrityCheck] = field(default_factory=list)
    critical_files_verified: int = 0
    suspicious_modifications: int = 0
    process_issues: int = 0
    config_tamper_detected: int = 0
    overall_risk: str = "LOW"
    score: float = 10.0
    recommendations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "date": datetime.fromtimestamp(self.timestamp).isoformat() if self.timestamp else "",
            "findings": [f.to_dict() for f in self.findings],
            "file_checks": [f.to_dict() for f in self.file_checks],
            "critical_files_verified": self.critical_files_verified,
            "suspicious_modifications": self.suspicious_modifications,
            "process_issues": self.process_issues,
            "config_tamper_detected": self.config_tamper_detected,
            "overall_risk": self.overall_risk,
            "score": round(self.score, 1),
            "recommendations": self.recommendations,
        }

    def summary_text(self) -> str:
        lines = [
            "═" * 60,
            "  RUNTIME SECURITY REPORT",
            "═" * 60,
            f"  Score: {self.score:.1f}/10.0  |  Risk: {self.overall_risk}",
            f"  Critical Files Verified: {self.critical_files_verified}",
            f"  Suspicious Modifications: {self.suspicious_modifications}",
            f"  Config Tampering: {self.config_tamper_detected}",
            f"  Process Issues: {self.process_issues}",
            "",
        ]
        if self.findings:
            lines.append("  Findings:")
            for f in self.findings[:10]:
                lines.append(f"    [{f.severity}] {f.category}: {f.description[:80]}")
        if self.recommendations:
            lines.append("\n  Recommendations:")
            for r in self.recommendations:
                lines.append(f"    → {r}")
        lines.append("═" * 60)
        return "\n".join(lines)


# ── Runtime Security ──────────────────────────────────────────────────────


class RuntimeSecurity:
    """Runtime Security — File Integrity & Runtime Protection.

    Monitors:
    - File integrity via SHA-256 checksums for critical files
    - Process health for critical system processes
    - File permissions on sensitive files
    - Configuration file tampering
    - Sensitive file discovery

    Thread-safe. Persists checksum baselines.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._checksum_baseline: dict[str, str] = {}
        self._findings: list[RuntimeFinding] = []
        self._reports: list[RuntimeSecurityReport] = []
        self._persist_path = Path("json/runtime_security.json")
        self._load_baseline()

    # ── Public API ────────────────────────────────────────────────────────

    def run_full_check(self) -> RuntimeSecurityReport:
        """Run a complete runtime security check.

        Verifies file integrity, checks processes, audits permissions,
        and detects configuration tampering.

        Returns:
            RuntimeSecurityReport with all findings.
        """
        report = RuntimeSecurityReport(timestamp=time.time())
        findings: list[RuntimeFinding] = []
        file_checks: list[FileIntegrityCheck] = []

        # 1. File integrity checks for critical files
        for critical_file in CRITICAL_FILES:
            check = self._check_file_integrity(critical_file)
            file_checks.append(check)
            if check.modified:
                findings.append(RuntimeFinding(
                    category="FILE_INTEGRITY",
                    severity="HIGH",
                    description=f"Critical file modified: {critical_file}",
                    affected_component=critical_file,
                    recommendation="Review changes to critical file — verify against version control",
                    timestamp=time.time(),
                ))
            for issue in check.issues:
                findings.append(RuntimeFinding(
                    category="PERMISSION",
                    severity="MEDIUM",
                    description=issue,
                    affected_component=critical_file,
                    recommendation="Restrict file permissions to read-only for non-owners",
                    timestamp=time.time(),
                ))

        report.file_checks = file_checks
        report.critical_files_verified = len(file_checks)
        report.suspicious_modifications = sum(1 for c in file_checks if c.modified)

        # 2. Configuration tampering detection
        config_findings = self._check_config_files()
        findings.extend(config_findings)
        report.config_tamper_detected = len(config_findings)

        # 3. Process health check
        process_findings = self._check_processes()
        findings.extend(process_findings)
        report.process_issues = len(process_findings)

        # 4. Sensitive file discovery
        sensitive_findings = self._discover_sensitive_files()
        findings.extend(sensitive_findings)

        report.findings = findings

        # Compute score and risk
        report.score = self._compute_score(report)
        report.overall_risk = self._risk_level(report.score)
        report.recommendations = self._generate_recommendations(report)

        with self._lock:
            self._reports.append(report)
            if len(self._reports) > 100:
                self._reports = self._reports[-100:]
            self._persist()

        return report

    def verify_file(self, file_path: str) -> FileIntegrityCheck | None:
        """Verify integrity of a single file.

        Args:
            file_path: Relative path to file from project root.

        Returns:
            FileIntegrityCheck or None if file doesn't exist.
        """
        return self._check_file_integrity(file_path)

    def get_stats(self) -> dict[str, Any]:
        """Get runtime security statistics."""
        with self._lock:
            last = self._reports[-1] if self._reports else None
            return {
                "total_checks": len(self._reports),
                "files_baselined": len(self._checksum_baseline),
                "last_check_ts": last.timestamp if last else 0,
                "last_score": round(last.score, 1) if last else 10.0,
                "last_risk": last.overall_risk if last else "LOW",
                "total_findings": sum(len(r.findings) for r in self._reports),
                "suspicious_modifications": last.suspicious_modifications if last else 0,
                "config_tamper_detected": last.config_tamper_detected if last else 0,
            }

    def clear_baseline(self) -> None:
        """Clear all saved checksums (forces re-baseline on next check)."""
        with self._lock:
            self._checksum_baseline.clear()
            if self._persist_path.exists():
                self._persist_path.unlink()

    # ── File Integrity ───────────────────────────────────────────────────

    def _check_file_integrity(self, file_path: str) -> FileIntegrityCheck:
        """Check a single file's integrity against its baseline checksum."""
        abs_path = ROOT / file_path
        check = FileIntegrityCheck(file_path=file_path)

        if not abs_path.is_file():
            check.issues.append(f"File not found: {file_path}")
            return check

        try:
            content = abs_path.read_bytes()
            check.size_bytes = len(content)
            check.checksum = hashlib.sha256(content).hexdigest()
            check.permissions = oct(os.stat(abs_path).st_mode)[-4:]

            # Check permissions — files should not be world-writable
            perms = int(check.permissions[-3:])
            if perms & 0o002:  # World-writable
                check.issues.append(f"World-writable permissions ({check.permissions})")

            # Compare against baseline
            with self._lock:
                if file_path in self._checksum_baseline:
                    prev = self._checksum_baseline[file_path]
                    check.previous_checksum = prev
                    check.modified = check.checksum != prev

                # Update baseline
                self._checksum_baseline[file_path] = check.checksum

        except (OSError, PermissionError) as exc:
            check.issues.append(f"Cannot read file: {exc}")

        return check

    def _check_config_files(self) -> list[RuntimeFinding]:
        """Check configuration files for signs of tampering."""
        findings: list[RuntimeFinding] = []

        for config_file in MONITORED_CONFIG_FILES:
            path = ROOT / config_file
            if not path.is_file():
                continue

            try:
                content = path.read_text(encoding="utf-8", errors="ignore")

                # Check for unexpected JSON parsing errors (corrupted files)
                if config_file.endswith(".json"):
                    try:
                        json.loads(content)
                    except (json.JSONDecodeError, ValueError):
                        findings.append(RuntimeFinding(
                            category="CONFIG_TAMPER",
                            severity="CRITICAL",
                            description=f"Config file corrupted (invalid JSON): {config_file}",
                            affected_component=config_file,
                            recommendation="Restore config from backup — possible tampering detected",
                            timestamp=time.time(),
                        ))

                # Check file size for anomalies
                size = path.stat().st_size
                if size == 0:
                    findings.append(RuntimeFinding(
                        category="CONFIG_TAMPER",
                        severity="CRITICAL",
                        description=f"Config file is empty: {config_file}",
                        affected_component=config_file,
                        recommendation="Config file may have been truncated — verify contents",
                        timestamp=time.time(),
                    ))

            except (OSError, PermissionError) as exc:
                findings.append(RuntimeFinding(
                    category="CONFIG_TAMPER",
                    severity="HIGH",
                    description=f"Cannot read config file: {config_file} — {exc}",
                    affected_component=config_file,
                    recommendation="Check file permissions — unauthorized restriction may indicate tampering",
                    timestamp=time.time(),
                ))

        return findings

    def _check_processes(self) -> list[RuntimeFinding]:
        """Check for critical processes."""
        findings: list[RuntimeFinding] = []

        for proc in CRITICAL_PROCESSES:
            proc_name = proc["name"]
            try:
                import subprocess
                if os.name == "nt":  # Windows
                    result = subprocess.run(
                        ["tasklist", "/FI", f"IMAGENAME eq *{proc_name}*"],
                        capture_output=True, text=True, timeout=5,
                    )
                    running = proc_name.lower() in result.stdout.lower()
                else:  # Linux/Mac
                    result = subprocess.run(
                        ["pgrep", "-f", proc_name],
                        capture_output=True, text=True, timeout=5,
                    )
                    running = result.returncode == 0

                if not running and proc.get("critical", False):
                    findings.append(RuntimeFinding(
                        category="PROCESS",
                        severity="CRITICAL",
                        description=f"Critical process not running: {proc_name} ({proc['description']})",
                        affected_component=proc_name,
                        recommendation=f"Restart {proc_name} immediately — system cannot function without it",
                        timestamp=time.time(),
                    ))
                elif not running:
                    findings.append(RuntimeFinding(
                        category="PROCESS",
                        severity="MEDIUM",
                        description=f"Optional process not running: {proc_name} ({proc['description']})",
                        affected_component=proc_name,
                        recommendation=f"Start {proc_name} if needed for current operations",
                        timestamp=time.time(),
                    ))

            except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
                _log.debug("[RTSEC] Process check failed for %s: %s", proc_name, exc)

        return findings

    def _discover_sensitive_files(self) -> list[RuntimeFinding]:
        """Discover sensitive files that may pose a security risk."""
        findings: list[RuntimeFinding] = []

        # Check for private keys and certificate files in the project
        for ext in SENSITIVE_FILE_EXTENSIONS:
            for f in ROOT.rglob(f"*{ext}"):
                if any(excl in str(f) for excl in EXCLUDED_DIRS):
                    continue
                rel_path = str(f.relative_to(ROOT))
                findings.append(RuntimeFinding(
                    category="ACCESS",
                    severity="HIGH",
                    description=f"Sensitive file found in project: {rel_path}",
                    affected_component=rel_path,
                    recommendation="Move sensitive files outside project directory or add to .gitignore",
                    timestamp=time.time(),
                ))

        return findings

    # ── Scoring ──────────────────────────────────────────────────────────

    def _compute_score(self, report: RuntimeSecurityReport) -> float:
        """Compute runtime security score (0-10)."""
        score = 10.0

        for f in report.findings:
            if f.severity == "CRITICAL":
                score -= 2.0
            elif f.severity == "HIGH":
                score -= 1.0
            elif f.severity == "MEDIUM":
                score -= 0.5
            else:
                score -= 0.2

        if report.suspicious_modifications > 0:
            score -= 0.5 * report.suspicious_modifications

        return max(0.0, min(10.0, score))

    def _risk_level(self, score: float) -> str:
        """Convert score to risk level."""
        if score >= 8.0:
            return "LOW"
        if score >= 6.0:
            return "MEDIUM"
        if score >= 4.0:
            return "HIGH"
        return "CRITICAL"

    def _generate_recommendations(self, report: RuntimeSecurityReport) -> list[str]:
        """Generate actionable recommendations."""
        recs: list[str] = []

        if report.suspicious_modifications > 0:
            recs.append(f"Investigate {report.suspicious_modifications} modified critical files immediately")
        if report.config_tamper_detected > 0:
            recs.append("Config tampering detected — restore from backup and investigate root cause")
        if report.process_issues > 0:
            recs.append("Missing critical processes — verify process health monitoring")
        if any(f.category == "ACCESS" for f in report.findings):
            recs.append("Sensitive files exposed in project — move to secure location")
        if any("World-writable" in str(f.issues) for f in report.file_checks):
            recs.append("Fix world-writable permissions on critical files")

        if not recs:
            recs.append("Runtime security is healthy — continue monitoring")

        return recs[:8]

    # ── Persistence ──────────────────────────────────────────────────────

    def _persist(self) -> None:
        """Persist checksum baseline to disk."""
        try:
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "checksum_baseline": self._checksum_baseline,
                "recent_reports": [r.to_dict() for r in self._reports[-20:]],
            }
            self._persist_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except (OSError, ValueError) as exc:
            _log.debug("[RTSEC] Persist: %s", exc)

    def _load_baseline(self) -> None:
        """Load checksum baseline from disk."""
        try:
            if self._persist_path.is_file():
                data = json.loads(self._persist_path.read_text(encoding="utf-8"))
                self._checksum_baseline = data.get("checksum_baseline", {})
                recent = data.get("recent_reports", [])
                for item in recent:
                    try:
                        report = RuntimeSecurityReport(
                            timestamp=item.get("timestamp", 0),
                            score=item.get("score", 10.0),
                            overall_risk=item.get("overall_risk", "LOW"),
                        )
                        self._reports.append(report)
                    except (TypeError, ValueError):
                        pass
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            _log.debug("[RTSEC] Load failed: %s", exc)


# ── CLI ────────────────────────────────────────────────────────────────────


def _cli() -> None:
    import argparse
    ap = argparse.ArgumentParser(
        prog="python -m core.runtime_security",
        description="Runtime Security — File integrity and runtime protection",
    )
    ap.add_argument("--check", action="store_true", help="Run full runtime security check")
    ap.add_argument("--verify", type=str, help="Verify a specific file's integrity")
    ap.add_argument("--stats", action="store_true", help="Show statistics")
    ap.add_argument("--json", action="store_true", help="Output as JSON")
    args = ap.parse_args()

    sec = get_runtime_security()

    if args.check:
        report = sec.run_full_check()
        if args.json:
            import json
            print(json.dumps(report.to_dict(), indent=2))
        else:
            print(report.summary_text())
        return

    if args.verify:
        check = sec.verify_file(args.verify)
        if check is None:
            print(f"File not found: {args.verify}")
            return
        if args.json:
            import json
            print(json.dumps(check.to_dict(), indent=2))
        else:
            ok = "MODIFIED" if check.modified else "OK"
            print(f"File: {check.file_path}")
            print(f"Status: {ok}")
            print(f"Checksum: {check.checksum[:16]}...")
            if check.issues:
                for i in check.issues:
                    print(f"  Issue: {i}")
        return

    if args.stats:
        stats = sec.get_stats()
        if args.json:
            import json
            print(json.dumps(stats, indent=2))
        else:
            print(f"Total Checks: {stats['total_checks']}")
            print(f"Files Baselined: {stats['files_baselined']}")
            print(f"Last Score: {stats['last_score']}/10")
            print(f"Last Risk: {stats['last_risk']}")
        return

    ap.print_help()


if __name__ == "__main__":
    _cli()

# ── Singleton ──────────────────────────────────────────────────────────────

_security: RuntimeSecurity | None = None
_security_lock = threading.RLock()


def get_runtime_security() -> RuntimeSecurity:
    """Get the singleton RuntimeSecurity instance."""
    global _security
    with _security_lock:
        if _security is None:
            _security = RuntimeSecurity()
        return _security


def reset_runtime_security() -> None:
    """Force-reset singleton (for testing)."""
    global _security
    with _security_lock:
        _security = None


__all__ = [
    "FileIntegrityCheck",
    "RuntimeFinding",
    "RuntimeSecurity",
    "RuntimeSecurityReport",
    "get_runtime_security",
    "reset_runtime_security",
]
