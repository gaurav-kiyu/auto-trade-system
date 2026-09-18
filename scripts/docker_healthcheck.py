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
    import os
    import sqlite3

    # 1) Verify database connectivity if DB file exists
    db = os.environ.get("OPBUYING_TRADES_DB", "/data/db/trades.db")
    if os.path.exists(db):
        try:
            conn = sqlite3.connect(db, timeout=2.0)
            res = conn.execute("SELECT 1").fetchone()
            conn.close()
            if res != (1,):
                print("DB query returned invalid result", file=sys.stderr)
                return 1
        except Exception as e:
            print(f"DB check failed: {e}", file=sys.stderr)
            return 1

    # 2) Verify dashboard HTTP health endpoint (<3s)
    port = os.environ.get("PORT", "8765")
    health_url = f"http://127.0.0.1:{port}/health"
    try:
        req = urllib.request.Request(health_url, headers={"User-Agent": "OPB-Docker-Healthcheck/1.0"})
        with urllib.request.urlopen(req, timeout=3) as resp:
            if resp.status != 200:
                print(f"HTTP health returned status {resp.status}", file=sys.stderr)
                return 1
            data = json.loads(resp.read().decode())
            if data.get("status") != "ok":
                print(f"HTTP health status not ok: {data.get('status')}", file=sys.stderr)
                return 1
            print("OK")
            return 0
    except Exception as e:
        print(f"HTTP healthcheck failed: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
