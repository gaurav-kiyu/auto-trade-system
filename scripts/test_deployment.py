#!/usr/bin/env python3
"""OPBuying Trading Platform — Deployment Health Check

Validates that the platform is properly deployed and all endpoints respond.
Can be used as a smoke test after deployment or as a readiness probe.

Usage:
    python scripts/test_deployment.py                          # Test localhost:8765
    python scripts/test_deployment.py --url https://prod.example.com  # Test remote
    python scripts/test_deployment.py --verbose                 # Show response details
    python scripts/test_deployment.py --exit-on-fail            # Fail fast on first error
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Any
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import Request, build_opener

DEFAULT_URL = "http://localhost:8765"
TIMEOUT_SECONDS = 10

PASS = "✅"
FAIL = "❌"
SKIP = "⏭️"

results: list[dict[str, Any]] = []

_ALLOWED_URL_SCHEMES = ("http", "https")


def _assert_http_scheme(url: str) -> str:
    """Reject non-http(s) URLs before they reach urlopen.

    Blocks file:/, ftp: and custom schemes that could read local files or
    reach unexpected endpoints.
    """
    scheme = urlparse(url).scheme.lower()
    if scheme not in _ALLOWED_URL_SCHEMES:
        raise ValueError(f"Blocked URL scheme: {scheme!r}")
    return url


_OPENER = build_opener()


def check(
    name: str,
    path: str,
    expected_status: int = 200,
    expected_keys: list[str] | None = None,
    method: str = "GET",
    data: bytes | None = None,
    critical: bool = True,
) -> bool:
    """Run a single health check against the deployment."""
    url = f"{BASE_URL}{path}"
    _assert_http_scheme(url)
    start = time.time()

    try:
        req = Request(url, data=data, method=method)
        req.add_header("User-Agent", "DeploymentTest/1.0")
        req.add_header("Accept", "application/json")

        with _OPENER.open(req, timeout=TIMEOUT_SECONDS) as resp:
            elapsed = (time.time() - start) * 1000
            status = resp.status
            body = resp.read().decode("utf-8")
            content_type = resp.headers.get("Content-Type", "")

        ok = status == expected_status

        # Parse JSON if applicable
        parsed = None
        if "application/json" in content_type:
            try:
                parsed = json.loads(body)
                if expected_keys:
                    for key in expected_keys:
                        if key not in parsed:
                            ok = False
                            _log(f"  Missing key '{key}' in response")
            except json.JSONDecodeError:
                pass  # Non-JSON response is fine for some endpoints

        icon = PASS if ok else FAIL
        _log(f"  {icon} {name} — {status} ({elapsed:.0f}ms)")
        if not ok:
            _log(f"     Expected {expected_status}, got {status}")
            if parsed:
                _log(f"     Response: {json.dumps(parsed, indent=2)[:200]}")

    except (URLError, TimeoutError, ConnectionError) as exc:
        elapsed = (time.time() - start) * 1000
        ok = False
        status = 0
        _log(f"  {FAIL} {name} — CONNECTION ERROR ({elapsed:.0f}ms)")
        _log(f"     {exc}")

    results.append({"name": name, "path": path, "ok": ok, "status": status, "elapsed_ms": round(elapsed, 1)})

    if not ok and critical and args.exit_on_fail:
        sys.exit(1)

    return ok


def _log(msg: str) -> None:
    print(msg)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="OPBuying Trading Platform — Deployment Health Check",
    )
    parser.add_argument("--url", type=str, default=DEFAULT_URL, help=f"Base URL (default: {DEFAULT_URL})")
    parser.add_argument("--verbose", action="store_true", help="Show response details")
    parser.add_argument("--exit-on-fail", action="store_true", help="Exit with code 1 on first failure")
    parser.add_argument("--format", type=str, choices=["text", "json"], default="text", help="Output format")
    return parser.parse_args()


def main() -> int:
    global BASE_URL, args
    args = parse_args()
    BASE_URL = args.url.rstrip("/")

    print(f"\n{'='*60}")
    print("  OPBuying Trading Platform — Deployment Health Check")
    print(f"  Target: {BASE_URL}")
    print(f"  Time:   {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}\n")

    # ── 1. Core Infrastructure ──────────────────────────────────────────
    print("📦 Core Infrastructure")

    check("System Health", "/api/system/health", critical=True)
    check("System Uptime", "/api/system/uptime", critical=False)
    check("System Diagnostics", "/api/system/diagnostics", critical=False)
    check("Prometheus Metrics", "/metrics", expected_keys=[], critical=False)
    check("Robots TXT", "/robots.txt", expected_keys=[], critical=False)
    check("API Docs", "/docs", expected_keys=[], critical=False)

    # ── 2. Read-only trading platform smoke checks ───────────────────────
    print("\n📈 Trading Platform")

    check("System State", "/api/system/state", critical=False)
    check("Recent Trades", "/api/system/trades?n=5", critical=False)
    check("Signals", "/api/system/signals", critical=False)
    check("Performance", "/api/system/performance", critical=False)
    check("Governance Status", "/api/governance/status", critical=False)

    # NOTE: This smoke test intentionally performs no POST/PUT/DELETE calls
    # and never creates trades, properties, users, or other production data.

    # ── Summary ───────────────────────────────────────────────────────────
    total = len(results)
    passed = sum(1 for r in results if r["ok"])
    failed = total - passed

    print(f"\n{'='*60}")
    print(f"  RESULTS: {passed}/{total} checks passed")
    if failed > 0:
        print("  FAILED:")
        for r in results:
            if not r["ok"]:
                print(f"    {FAIL} {r['name']} ({r['path']})")
    print(f"{'='*60}\n")

    if args.format == "json":
        print(json.dumps({
            "target": BASE_URL,
            "timestamp": time.time(),
            "total": total,
            "passed": passed,
            "failed": failed,
            "results": results,
        }, indent=2))

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
