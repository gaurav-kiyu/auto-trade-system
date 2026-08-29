#!/usr/bin/env python3
"""Real Estate Platform — Synthetic Monitoring Heartbeat.

Periodically checks all critical endpoints and reports status.
Designed to run as a cron job or scheduled task.

Usage:
    python scripts/realestate_synthetic_monitor.py                     # Default: check all, output table
    python scripts/realestate_synthetic_monitor.py --url http://prod.example.com
    python scripts/realestate_synthetic_monitor.py --json              # JSON output
    python scripts/realestate_synthetic_monitor.py --verbose           # Detailed output
    python scripts/realestate_synthetic_monitor.py --slack-webhook URL # Send alerts to Slack
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone

_ALLOWED_URL_SCHEMES = ("http", "https")


def _assert_http_scheme(url: str) -> str:
    """Reject non-http(s) URLs before they reach urlopen.

    Blocks file:/, ftp: and custom schemes that could read local files or
    reach unexpected endpoints.
    """
    scheme = urllib.parse.urlparse(url).scheme.lower()
    if scheme not in _ALLOWED_URL_SCHEMES:
        raise ValueError(f"Blocked URL scheme: {scheme!r}")
    return url


_OPENER = urllib.request.build_opener()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [MONITOR] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
_log = logging.getLogger("synthetic_monitor")

PASS = "✅"
FAIL = "❌"
WARN = "⚠️"


@dataclass
class CheckResult:
    name: str
    path: str
    ok: bool
    status: int = 0
    elapsed_ms: float = 0.0
    error: str = ""


@dataclass
class MonitorReport:
    timestamp: str = ""
    total: int = 0
    passed: int = 0
    failed: int = 0
    pass_rate: float = 0.0
    checks: list[CheckResult] = field(default_factory=list)


def check_url(
    base_url: str,
    path: str,
    expected_status: int = 200,
    expected_key: str | None = None,
    method: str = "GET",
    body: str | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = 10,
) -> CheckResult:
    """Check a URL and return the result."""
    name = path.split("?")[0]
    url = f"{base_url.rstrip('/')}{path}"
    _assert_http_scheme(url)
    start = time.time()

    req_headers = {"User-Agent": "SyntheticMonitor/1.0"}
    if headers:
        req_headers.update(headers)

    data = body.encode() if body else None

    try:
        req = urllib.request.Request(url, data=data, headers=req_headers, method=method)
        with _OPENER.open(req, timeout=timeout) as resp:
            elapsed = (time.time() - start) * 1000
            status = resp.status
            ok = status == expected_status

            if ok and expected_key:
                try:
                    resp_body = resp.read().decode()
                    parsed = json.loads(resp_body)
                    ok = expected_key in parsed
                except (json.JSONDecodeError, UnicodeDecodeError, KeyError):
                    ok = False

            return CheckResult(
                name=name,
                path=path,
                ok=ok,
                status=status,
                elapsed_ms=round(elapsed, 1),
            )
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
        elapsed = (time.time() - start) * 1000
        status = getattr(exc, "code", 0) if isinstance(exc, urllib.error.HTTPError) else 0
        return CheckResult(
            name=name,
            path=path,
            ok=False,
            status=status,
            elapsed_ms=round(elapsed, 1),
            error=str(exc),
        )


def run_all_checks(base_url: str) -> MonitorReport:
    """Run all synthetic checks against the platform."""
    now = datetime.now(timezone.utc).isoformat()

    checks: list[CheckResult] = []

    # ── Core Infrastructure ─────────────────────────────────────────────────
    checks.append(check_url(base_url, "/api/realestate/health", expected_key="status"))
    checks.append(check_url(base_url, "/robots.txt", expected_status=200))
    checks.append(check_url(base_url, "/sitemap.xml", expected_status=200))

    # ── Property Endpoints ──────────────────────────────────────────────────
    checks.append(check_url(base_url, "/api/realestate/properties?page=1&limit=5"))
    checks.append(check_url(base_url, "/api/realestate/properties/search?city=Mumbai"))
    checks.append(check_url(base_url, "/api/realestate/autocomplete?q=Mumbai"))

    # ── RERA Compliance ─────────────────────────────────────────────────────
    checks.append(check_url(base_url, "/api/realestate/rera/verify/TS/RERA12345"))

    # ── Admin / Dashboard ───────────────────────────────────────────────────
    checks.append(check_url(base_url, "/api/realestate/fraud/stats"))

    # ── Chatbot (basic health — POST requires body) ─────────────────────────
    checks.append(check_url(
        base_url,
        "/api/realestate/chat",
        method="POST",
        body=json.dumps({"message": "hello", "user_id": "monitor"}),
        headers={"Content-Type": "application/json"},
    ))

    total = len(checks)
    passed = sum(1 for c in checks if c.ok)
    failed = total - passed
    pass_rate = round(passed / total * 100, 1) if total > 0 else 0.0

    return MonitorReport(
        timestamp=now,
        total=total,
        passed=passed,
        failed=failed,
        pass_rate=pass_rate,
        checks=checks,
    )


def print_report(report: MonitorReport, verbose: bool = False) -> None:
    """Print a human-readable report."""
    print(f"\n{'=' * 60}")
    print("  Real Estate Platform — Synthetic Monitor")
    print(f"  {report.timestamp}")
    print(f"{'=' * 60}")
    print(f"  Total: {report.total}  |  PASS: {report.passed}  |  FAIL: {report.failed}  |  Rate: {report.pass_rate}%")
    print(f"{'=' * 60}")

    for check in report.checks:
        icon = PASS if check.ok else FAIL
        status_str = f"{check.status}" if check.status else "ERR"
        status_display = f"HTTP {status_str}" if check.status > 0 else "CONN ERR"
        detail = f" — {check.error}" if check.error and verbose else ""
        print(f"  {icon} {check.name:45s} {status_display:10s} {check.elapsed_ms:8.0f}ms{detail}")

    print(f"{'=' * 60}")

    if report.failed > 0:
        print(f"\n{WARN} Failed checks:")
        for check in report.checks:
            if not check.ok:
                print(f"     {FAIL} {check.path} — {check.error or f'HTTP {check.status}'}")


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Real Estate Platform — Synthetic Monitoring Heartbeat",
    )
    parser.add_argument(
        "--url",
        default=os.environ.get("RE_URL", "http://localhost:8765"),
        help="Base URL of the platform (default: http://localhost:8765)",
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--verbose", "-v", action="store_true", help="Detailed output")
    parser.add_argument(
        "--slack-webhook",
        default=os.environ.get("SLACK_WEBHOOK_URL", ""),
        help="Slack webhook URL for alerts",
    )

    args = parser.parse_args()

    _log.info("Starting synthetic monitoring checks against %s", args.url)

    report = run_all_checks(args.url)

    if args.json:
        data = {
            "timestamp": report.timestamp,
            "total": report.total,
            "passed": report.passed,
            "failed": report.failed,
            "pass_rate": report.pass_rate,
            "checks": [
                {"name": c.name, "ok": c.ok, "status": c.status, "elapsed_ms": c.elapsed_ms, "error": c.error}
                for c in report.checks
            ],
        }
        print(json.dumps(data, indent=2))
    else:
        print_report(report, verbose=args.verbose)

    # Slack alert if any checks fail and webhook is configured
    if report.failed > 0 and args.slack_webhook:
        try:
            payload = json.dumps({
                "text": f"⚠️ Real Estate Platform — {report.failed}/{report.total} checks FAILED ({report.pass_rate}% pass rate)",
                "attachments": [
                    {
                        "color": "danger",
                        "fields": [
                            {"title": c.name, "value": c.error or f"HTTP {c.status}", "short": True}
                            for c in report.checks if not c.ok
                        ],
                    }
                ],
            }).encode()
            _assert_http_scheme(args.slack_webhook)
            req = urllib.request.Request(
                args.slack_webhook,
                data=payload,
                headers={"Content-Type": "application/json"},
            )
            _OPENER.open(req, timeout=10)
            _log.info("Slack alert sent successfully")
        except Exception as exc:
            _log.error("Failed to send Slack alert: %s", exc)

    return 1 if report.failed > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
