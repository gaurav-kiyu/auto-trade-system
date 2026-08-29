"""Container healthcheck for the OPB Docker image.

Replaces the invalid multi-line ``python -c`` block that used to live inline in
the Dockerfile HEALTHCHECK (Docker does not allow raw newlines inside an
instruction, so ``import ...`` was parsed as an unknown instruction and the
image failed to build). The repo is COPYed to /app, so this file is present at
runtime and can be referenced as a single-line CMD.

Checks:
1. All core + enterprise-dashboard modules import cleanly.
2. If the dashboard is running, its /api/system/health/docker endpoint must not
   report ``degraded``.

Exit code 0 => healthy, non-zero => unhealthy.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

MODULES = [
    "core.token_refresh_service",
    "core.market_warmup",
    "core.ws_feed_manager",
    "core.kite_ticker_feed",
    "core.ltp_resolver",
    "core.metrics_exporter",
    "core.safety_state",
    "core.health_checker",
    "core.auth.handler",
    "core.auth.csrf",
    "core.auth.dependencies",
    "core.auth.routes",
    "core.enterprise_dashboard",
]


def main() -> int:
    # 1) Verify all critical modules are importable.
    for mod in MODULES:
        __import__(mod)

    # 2) Optional: check the dashboard HTTP health endpoint.
    try:
        resp = urllib.request.urlopen(
            "http://127.0.0.1:8765/api/system/health/docker", timeout=5
        )
        data = json.loads(resp.read().decode())
        if data.get("status") == "degraded":
            print("DEGRADED")
            return 1
        print("OK")
    except (urllib.error.URLError, ConnectionRefusedError):
        # Dashboard not running — still OK (bot may run without it).
        print("OK (no web)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
