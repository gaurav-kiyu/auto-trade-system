#!/usr/bin/env python3
"""Docker Security Hardening Scanner (Phase 12).

Scans Dockerfile and docker-compose files for CIS Docker benchmark violations,
missing security best practices, and common misconfigurations. Generates HTML
and JSON security reports.

Checks performed:
  CIS-DI-001: Use specific version tags (not 'latest')
  CIS-DI-002: USER directive present (not running as root)
  CIS-DI-003: HEALTHCHECK instruction present
  CIS-DI-004: COPY preferred over ADD
  CIS-DI-005: Multi-stage build used
  CIS-DI-006: No sensitive secrets in ARG/ENV
  CIS-DI-007: .dockerignore exists
  CIS-DI-008: No EXPOSE of privileged ports (<1024)
  CIS-DI-009: Read-only root filesystem in compose
  CIS-DI-010: Resource limits set in compose
  CIS-DI-011: No privileged mode in compose
  CIS-DI-012: Security options in compose
  CIS-DI-013: Capabilities drop in compose
  CIS-DI-014: No host network mode in compose
  CIS-DI-015: Restart policy not 'always' (prefer 'unless-stopped')
  CIS-DI-016: Logging driver configured in compose

Usage:
    python scripts/check_docker_security.py
    python scripts/check_docker_security.py --dockerfile path/to/Dockerfile
    python scripts/check_docker_security.py --ci
    python scripts/check_docker_security.py --json
    python scripts/check_docker_security.py --html report.html
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_REPORTS_DIR = Path(__file__).resolve().parent.parent / "reports"
_PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Default Docker files to scan
_DEFAULT_DOCKERFILE = "Dockerfile"
_DEFAULT_DOCKERFILE_REALESTATE = "Dockerfile.realestate"
_DEFAULT_COMPOSE_FILES = ["docker-compose.yml", "docker-compose.realestate.yml"]


@dataclass
class DockerCheck:
    """Represents a single CIS check result."""
    id: str
    description: str
    severity: str  # critical / high / medium / low / info
    passed: bool
    detail: str = ""
    recommendation: str = ""


# ── Check Registry ────────────────────────────────────────────────────────────

_CHECKS: list[dict[str, Any]] = [
    # Dockerfile checks
    {
        "id": "CIS-DI-001",
        "description": "Use specific version tags (not 'latest')",
        "severity": "medium",
        "scope": "dockerfile",
        "pattern": r"FROM\s+(\S+):latest\b",
        "recommendation": "Replace 'FROM ...:latest' with a specific version tag (e.g., python:3.11-slim)",
    },
    {
        "id": "CIS-DI-002",
        "description": "USER directive present (not running as root)",
        "severity": "high",
        "scope": "dockerfile",
        "pattern": r"^\s*USER\s+\w+",
        "recommendation": "Add 'USER appuser' (or similar non-root user) before CMD/ENTRYPOINT",
    },
    {
        "id": "CIS-DI-003",
        "description": "HEALTHCHECK instruction present",
        "severity": "medium",
        "scope": "dockerfile",
        "pattern": r"^\s*HEALTHCHECK\s+",
        "recommendation": "Add HEALTHCHECK instruction for container orchestration liveness probes",
    },
    {
        "id": "CIS-DI-004",
        "description": "COPY preferred over ADD",
        "severity": "low",
        "scope": "dockerfile",
        "pattern": r"^\s*ADD\s+",
        "recommendation": "Use COPY instead of ADD unless you need automatic tar extraction or URL handling",
    },
    {
        "id": "CIS-DI-005",
        "description": "Multi-stage build used",
        "severity": "info",
        "scope": "dockerfile",
        "pattern": r"^\s*FROM\s+\S+\s+AS\s+\w+",
        "recommendation": "Consider using multi-stage builds to reduce final image size",
    },
    {
        "id": "CIS-DI-006",
        "description": "No sensitive secrets in ARG/ENV",
        "severity": "high",
        "scope": "dockerfile",
        "patterns": [
            r"(?i)(password|secret|token|api_key|apikey|auth|credential)\s*=",
        ],
        "recommendation": "Use Docker build secrets (--secret) or external secret management instead of ENV/ARG for secrets",
    },
    {
        "id": "CIS-DI-007",
        "description": ".dockerignore exists",
        "severity": "medium",
        "scope": "file_exists",
        "pattern": "",
        "filename": ".dockerignore",
        "recommendation": "Create .dockerignore to exclude unnecessary files from build context",
    },
    {
        "id": "CIS-DI-008",
        "description": "No EXPOSE of privileged ports (<1024)",
        "severity": "medium",
        "scope": "dockerfile",
        "pattern": r"EXPOSE\s+([0-9]+)",
        "recommendation": "Avoid exposing privileged ports (<1024). Use ports >= 1024 and map via docker-compose",
    },
]

_COMPOSE_CHECKS: list[dict[str, Any]] = [
    {
        "id": "CIS-DI-009",
        "description": "Read-only root filesystem",
        "severity": "medium",
        "scope": "compose",
        "pattern": r"read_only\s*:\s*true",
        "recommendation": "Set 'read_only: true' on containers to prevent runtime filesystem modifications",
    },
    {
        "id": "CIS-DI-010",
        "description": "Resource limits set",
        "severity": "high",
        "scope": "compose",
        "pattern": r"(memory|mem_limit|cpus|cpu_count):\s*[\"\']?[0-9]+(?:\.[0-9]+)?(?:[KMG]i?B)?[\"\']?",
        "recommendation": "Set memory and CPU limits on all services to prevent resource exhaustion",
    },
    {
        "id": "CIS-DI-011",
        "description": "No privileged mode",
        "severity": "critical",
        "scope": "compose",
        "pattern": r"privileged\s*:\s*true",
        "recommendation": "Remove 'privileged: true' — containers should run with least privilege",
    },
    {
        "id": "CIS-DI-012",
        "description": "Security options configured",
        "severity": "medium",
        "scope": "compose",
        "pattern": r"security_opt\s*:",
        "recommendation": "Add security options (e.g., 'no-new-privileges:true') to restrict container capabilities",
    },
    {
        "id": "CIS-DI-013",
        "description": "Capabilities drop configured",
        "severity": "high",
        "scope": "compose",
        "pattern": r"cap_drop\s*:",
        "recommendation": "Drop all capabilities with 'cap_drop: [ALL]' and add only required ones",
    },
    {
        "id": "CIS-DI-014",
        "description": "No host network mode",
        "severity": "high",
        "scope": "compose",
        "pattern": r"network_mode\s*:\s*[\"']host[\"']",
        "recommendation": "Avoid 'network_mode: host' — use bridge/dedicated networks for isolation",
    },
    {
        "id": "CIS-DI-015",
        "description": "Restart policy not 'always' (prefer 'unless-stopped')",
        "severity": "low",
        "scope": "compose",
        "pattern": r"restart\s*:\s*always\b",
        "recommendation": "Use 'restart: unless-stopped' instead of 'always' to avoid unintended restarts",
    },
    {
        "id": "CIS-DI-016",
        "description": "Logging driver configured",
        "severity": "low",
        "scope": "compose",
        "pattern": r"logging\s*:",
        "recommendation": "Configure logging driver (e.g., json-file with rotation or loki) for observability",
    },
]


# ── Scanner Engine ────────────────────────────────────────────────────────────


def _scan_dockerfile(path: Path) -> list[DockerCheck]:
    """Scan a single Dockerfile for CIS violations."""
    results: list[DockerCheck] = []
    if not path.exists():
        results.append(DockerCheck(
            id="CIS-DI-FILE",
            description=f"Dockerfile not found: {path.name}",
            severity="info",
            passed=False,
            detail=f"File {path} does not exist",
            recommendation="Create a Dockerfile for containerized deployment",
        ))
        return results

    content = path.read_text(encoding="utf-8", errors="replace")
    lines = content.splitlines()

    for check in _CHECKS:
        if check["scope"] == "file_exists":
            fname = check.get("filename", "")
            fpath = path.parent / fname if fname else Path(fname)
            passed = fpath.exists()
            results.append(DockerCheck(
                id=check["id"],
                description=check["description"],
                severity=check["severity"],
                passed=passed,
                detail=f"{fpath} {'exists' if passed else 'not found'}",
                recommendation=check["recommendation"],
            ))
            continue

        if check["scope"] != "dockerfile":
            continue

        if "pattern" in check and check["pattern"]:
            pat = re.compile(check["pattern"], re.MULTILINE)
            passed = bool(pat.search(content))
            if check["id"] == "CIS-DI-001":
                # Specific-tag check: PASSED when no :latest base image is used.
                passed = not passed
            elif check["id"] == "CIS-DI-004":
                # ADD check: PASSED = no ADD (inverted logic)
                passed = not passed
            elif check["id"] == "CIS-DI-006":
                # ENV/ARG secrets check: applies patterns against ENV/ARG lines
                secrets_found = False
                env_patterns = check.get("patterns", [check.get("pattern", "")])
                for line in lines:
                    stripped = line.strip()
                    if stripped.startswith("ENV ") or stripped.startswith("ARG "):
                        for sp in env_patterns:
                            if re.search(sp, stripped):
                                secrets_found = True
                                break
                passed = not secrets_found
            elif check["id"] == "CIS-DI-008":
                # EXPOSE privileged port check
                privileged_found = False
                for m in re.finditer(pat, content):
                    port = int(m.group(1))
                    if port < 1024:
                        privileged_found = True
                        break
                passed = not privileged_found
            elif check["id"] == "CIS-DI-005":
                # Multi-stage: PASSED if pattern found (at least one FROM ... AS)
                pass  # already set by search result

        detail = "Passed" if passed else "Not found"
        results.append(DockerCheck(
            id=check["id"],
            description=check["description"],
            severity=check["severity"],
            passed=passed,
            detail=detail,
            recommendation=check["recommendation"],
        ))

    return results


def _scan_compose(path: Path) -> list[DockerCheck]:
    """Scan a docker-compose file for CIS violations."""
    results: list[DockerCheck] = []
    if not path.exists():
        results.append(DockerCheck(
            id="CIS-DI-FILE",
            description=f"Compose file not found: {path.name}",
            severity="info",
            passed=False,
            detail=f"File {path} does not exist",
            recommendation="Create a docker-compose file for orchestration",
        ))
        return results

    content = path.read_text(encoding="utf-8", errors="replace")

    for check in _COMPOSE_CHECKS:
        pat = re.compile(check["pattern"], re.MULTILINE)
        if check["id"] in ("CIS-DI-009", "CIS-DI-010", "CIS-DI-012", "CIS-DI-013", "CIS-DI-016"):
            # These should be present (positive check)
            passed = bool(pat.search(content))
        elif check["id"] in ("CIS-DI-011", "CIS-DI-014", "CIS-DI-015"):
            # These should NOT be present (negative check)
            passed = not bool(pat.search(content))
        else:
            passed = bool(pat.search(content))

        detail = "Configured" if passed else "Not configured"
        if check["id"] == "CIS-DI-011":
            detail = "No privileged mode" if passed else "WARNING: privileged mode detected"
        elif check["id"] == "CIS-DI-014":
            detail = "No host network" if passed else "WARNING: host network mode detected"
        elif check["id"] == "CIS-DI-015":
            detail = "restart: always not used" if passed else "WARNING: restart: always detected"

        results.append(DockerCheck(
            id=check["id"],
            description=check["description"],
            severity=check["severity"],
            passed=passed,
            detail=detail,
            recommendation=check["recommendation"],
        ))

    return results


# ─── Report generator ─────────────────────────────────────────────────────────


def _severity_score(severity: str) -> int:
    return {"critical": 4, "high": 3, "medium": 2, "low": 1, "info": 0}.get(severity, 0)


def generate_html_report(all_checks: list[DockerCheck], filename: str = "Docker") -> str:
    """Generate a self-contained HTML security report."""
    total = len(all_checks)
    passed = sum(1 for c in all_checks if c.passed)
    failed = total - passed
    critical = sum(1 for c in all_checks if c.severity == "critical" and not c.passed)
    high = sum(1 for c in all_checks if c.severity == "high" and not c.passed)
    medium = sum(1 for c in all_checks if c.severity == "medium" and not c.passed)

    score = round(passed / total * 100, 1) if total > 0 else 0
    status = "PASS" if score >= 80 and critical == 0 else "WARN" if score >= 50 else "FAIL"

    rows_html = ""
    for check in all_checks:
        sev = check.severity.upper()
        sev_colors = {
            "CRITICAL": "#d32f2f",
            "HIGH": "#f57c00",
            "MEDIUM": "#fbc02d",
            "LOW": "#7cb342",
            "INFO": "#78909c",
        }
        sev_color = sev_colors.get(sev, "#999")
        status_icon = "✅" if check.passed else "❌"
        rows_html += f"""
<tr style="background:{'#e8f5e9' if check.passed else '#ffebee'}">
  <td><strong>{check.id}</strong></td>
  <td><span style="background:{sev_color};color:white;padding:2px 8px;border-radius:3px;font-size:0.85em">{sev}</span></td>
  <td>{status_icon} {'Passed' if check.passed else 'FAILED'}</td>
  <td>{check.description}</td>
  <td style="font-size:0.9em;color:#666">{check.detail}</td>
  <td style="font-size:0.85em;color:{'#2e7d32' if check.passed else '#c62828'}">{check.recommendation}</td>
</tr>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Docker Security Hardening Report — {filename}</title>
<style>
  body {{ font-family: 'Segoe UI', Arial, sans-serif; max-width: 1100px; margin: 20px auto; padding: 20px; background: #f5f7fa; color: #333; }}
  h1 {{ color: #1a237e; border-bottom: 3px solid #1a237e; padding-bottom: 8px; }}
  h2 {{ color: #283593; margin-top: 30px; }}
  table {{ width: 100%; border-collapse: collapse; background: white; box-shadow: 0 2px 4px rgba(0,0,0,0.1); border-radius: 4px; }}
  th {{ background: #1a237e; color: white; padding: 10px 14px; text-align: left; font-weight: 500; }}
  td {{ padding: 8px 14px; border-bottom: 1px solid #e0e0e0; }}
  .score-box {{ text-align: center; padding: 20px; margin: 20px 0; border-radius: 8px; }}
  .score-pass {{ background: linear-gradient(135deg, #2e7d32, #4caf50); color: white; }}
  .score-warn {{ background: linear-gradient(135deg, #e65100, #ff9800); color: white; }}
  .score-fail {{ background: linear-gradient(135deg, #b71c1c, #f44336); color: white; }}
  .score-number {{ font-size: 3em; font-weight: 700; }}
  footer {{ margin-top: 40px; padding-top: 20px; border-top: 1px solid #e0e0e0; color: #999; font-size: 0.85em; text-align: center; }}
</style>
</head>
<body>
<h1>🐳 Docker Security Hardening Report</h1>    <p>File: <code>{filename}</code> | Generated: {datetime.now(timezone.utc).isoformat()}Z</p>

<div class="score-box score-{status.lower()}">
  <div class="score-number">{score}%</div>
  <div>Security Score</div>
  <div style="margin-top:10px;font-size:1.1em">{failed} failed / {total} total checks</div>
  <div style="margin-top:5px">
    {f'<span style="background:#b71c1c;color:white;padding:2px 8px;border-radius:3px;margin:2px">{critical} Critical</span>' if critical else ''}
    {f'<span style="background:#e65100;color:white;padding:2px 8px;border-radius:3px;margin:2px">{high} High</span>' if high else ''}
    {f'<span style="background:#f57f17;color:white;padding:2px 8px;border-radius:3px;margin:2px">{medium} Medium</span>' if medium else ''}
  </div>
</div>

<table>
<tr><th>ID</th><th>Severity</th><th>Status</th><th>Description</th><th>Detail</th><th>Recommendation</th></tr>
{rows_html}
</table>

<footer>
  OPB Docker Security Hardening Scanner | CIS Docker Benchmark-aligned checks
</footer>
</body>
</html>"""


# ── Main CLI ──────────────────────────────────────────────────────────────────


def run_scan(
    dockerfile: str | None = None,
    compose_file: str | None = None,
) -> list[DockerCheck]:
    """Run Docker security scan on specified files."""
    all_checks: list[DockerCheck] = []

    # Scan Dockerfiles
    dockerfiles_to_scan = []
    if dockerfile:
        dockerfiles_to_scan.append(Path(dockerfile))
    else:
        for df in [_DEFAULT_DOCKERFILE, _DEFAULT_DOCKERFILE_REALESTATE]:
            p = _PROJECT_ROOT / df
            if p.exists():
                dockerfiles_to_scan.append(p)
        if not dockerfiles_to_scan:
            dockerfiles_to_scan.append(_PROJECT_ROOT / _DEFAULT_DOCKERFILE)

    for df_path in dockerfiles_to_scan:
        print(f"  Scanning Dockerfile: {df_path.name}")
        all_checks.extend(_scan_dockerfile(df_path))

    # Scan compose files
    composes_to_scan = []
    if compose_file:
        composes_to_scan.append(Path(compose_file))
    else:
        for cf in _DEFAULT_COMPOSE_FILES:
            p = _PROJECT_ROOT / cf
            if p.exists():
                composes_to_scan.append(p)

    for cf_path in composes_to_scan:
        print(f"  Scanning compose: {cf_path.name}")
        all_checks.extend(_scan_compose(cf_path))

    return all_checks


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Docker Security Hardening Scanner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--dockerfile", default=None, help="Path to Dockerfile")
    parser.add_argument("--compose", default=None, help="Path to docker-compose file")
    parser.add_argument("--json", action="store_true", help="Output JSON report")
    parser.add_argument("--json-stdout", action="store_true", help="Print JSON report to stdout")
    parser.add_argument("--html", default=None, help="Path to HTML report file")
    parser.add_argument("--ci", action="store_true",
                        help="CI mode: exit non-zero if any critical or high severity issues")
    args = parser.parse_args()

    print("\n  Running Docker security hardening scan...")
    all_checks = run_scan(
        dockerfile=args.dockerfile,
        compose_file=args.compose,
    )

    total = len(all_checks)
    passed = sum(1 for c in all_checks if c.passed)
    failed = total - passed
    critical = [c for c in all_checks if c.severity == "critical" and not c.passed]
    high = [c for c in all_checks if c.severity == "high" and not c.passed]
    medium = [c for c in all_checks if c.severity == "medium" and not c.passed]
    score = round(passed / total * 100, 1) if total > 0 else 0
    status = "PASS" if score >= 80 and not critical else "WARN" if score >= 50 else "FAIL"

    print(f"\n{'='*60}")
    print("  DOCKER SECURITY HARDENING REPORT")
    print(f"{'='*60}")
    print(f"  Score: {score}% ({passed}/{total} passed)")
    print(f"  Status: {status}")
    print(f"  Critical: {len(critical)} | High: {len(high)} | Medium: {len(medium)} | Failed: {failed}")
    print()

    if failed > 0:
        for c in all_checks:
            if not c.passed:
                print(f"  [{c.severity.upper()}] {c.id}: {c.description}")
                print(f"    {c.recommendation}")
                print()

    # HTML report
    html_path = args.html or str(_REPORTS_DIR / f"docker_security_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.html")
    Path(html_path).parent.mkdir(parents=True, exist_ok=True)
    html = generate_html_report(all_checks, args.dockerfile or "Dockerfile")
    Path(html_path).write_text(html, encoding="utf-8")
    print(f"  HTML report: {html_path}")

    # JSON output
    if args.json:
        report_json = {
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "score": score,
            "status": status,
            "total_checks": total,
            "passed": passed,
            "failed": failed,
            "critical": len(critical),
            "high": len(high),
            "medium": len(medium),
            "checks": [
                {
                    "id": c.id,
                    "description": c.description,
                    "severity": c.severity,
                    "passed": c.passed,
                    "detail": c.detail,
                    "recommendation": c.recommendation,
                }
                for c in all_checks
            ],
        }
        json_path = _REPORTS_DIR / "docker_security.json"
        json_path.write_text(json.dumps(report_json, indent=2), encoding="utf-8")
        if args.json_stdout:
            print(json.dumps(report_json, indent=2))

    # CI check
    if args.ci and (critical or high):
        print(f"\n  [CI FAIL] {len(critical)} critical + {len(high)} high issues found")
        return 1

    print(f"{'='*60}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
