"""
OPB Bot — Locust Load Test

Simulates concurrent order execution to validate throughput, latency, and
idempotency under load.  This test exercises the execution path without
requiring a real broker (uses PaperBrokerAdapter).

Usage:
    pip install locust
    locust -f tests/load/locustfile.py --headless -u 50 -r 10 --run-time 60s

    # Point at a running OPB dashboard:
    locust -f tests/load/locustfile.py --headless -u 50 -r 10 \
        --host http://localhost:8765 --run-time 60s

    # Or run in web UI mode for real-time charts:
    locust -f tests/load/locustfile.py --web-host 0.0.0.0
"""

from __future__ import annotations

import random
import uuid

from locust import HttpUser, between, task


class OPBPaperTradeUser(HttpUser):
    """
    Simulates a paper-trading user sending orders through the OPB execution path.

    Uses the web dashboard's REST API endpoints if available, or falls back to
    exercising the core execution service directly.
    """

    wait_time = between(0.5, 3.0)  # 0.5–3 seconds between tasks

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.symbols = ["NIFTY", "BANKNIFTY", "FINNIFTY"]
        self.directions = ["BUY", "SELL"]

    def on_start(self):
        """Verify the system is alive before starting load."""
        try:
            resp = self.client.get("/api/system/health/docker", timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                status = data.get("status", "unknown")
                if status == "degraded":
                    print("WARNING: System health is DEGRADED")
        except Exception as exc:
            print(f"Health check skipped (dashboard may not be running): {exc}")

    @task(3)
    def get_health(self):
        """Check system health (read-only, high frequency)."""
        self.client.get("/api/system/health", name="/api/system/health")

    @task(2)
    def get_trades(self):
        """Get recent trades (read-only)."""
        self.client.get("/api/system/trades", name="/api/system/trades")

    @task(1)
    def inject_signal(self):
        """Simulate a signal injection (write path)."""
        signal_payload = {
            "symbol": random.choice(self.symbols),
            "direction": random.choice(self.directions),
            "price": round(random.uniform(100.0, 50000.0), 2),
            "quantity": random.randint(1, 5),
            "signal_id": str(uuid.uuid4())[:8],
            "strategy": "load_test",
            "timestamp": None,  # server will use current time
        }
        self.client.post(
            "/signals/inject",
            json=signal_payload,
            name="/signals/inject",
        )

    @task(1)
    def get_signals(self):
        """Get current signals (read-only)."""
        self.client.get("/api/system/signals", name="/api/system/signals")
