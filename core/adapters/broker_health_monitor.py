"""
Sample Broker Latency Data Generator (NOT a real health/ping monitor)

Despite the name, ping_all_brokers() never makes a real network call to any
broker - it generates latency numbers via random.uniform() around hardcoded
per-broker baselines. No credentials for any of these 14 brokers exist in
this environment, so there is nothing real to ping yet. Every result is
flagged is_demo_data=True; treat this as a UI placeholder, not telemetry.
A real implementation would need to route each broker's actual REST/WS ping
through core/adapters/broker_adapters.py (the one real broker chokepoint),
per-broker, with real credentials.
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from datetime import datetime, timezone

_log = logging.getLogger(__name__)


@dataclass
class BrokerHealthStatus:
    broker_code: str
    broker_name: str
    is_active: bool
    latency_ms: float
    latency_tier: str  # ULTRA_FAST / HEALTHY / DEGRADED / OFFLINE
    http_status: int
    health_score: float
    last_ping_time: str
    recommended_for_orders: bool
    is_demo_data: bool = True


class BrokerHealthMonitor:
    """Generates sample per-broker latency data - see module docstring.

    Does not make any real network call to any broker.
    """

    def __init__(self) -> None:
        self._broker_names = {
            "zerodha": "Zerodha (Kite)",
            "angelone": "Angel One",
            "iifl": "IIFL Markets",
            "upstox": "Upstox",
            "groww": "Groww",
            "icicidirect": "ICICI Direct",
            "hdfcsecurities": "HDFC Securities",
            "kotak": "Kotak Neo",
            "dhan": "Dhan",
            "fyers": "Fyers",
            "motilaloswal": "Motilal Oswal",
            "sharekhan": "Sharekhan",
            "paytmmoney": "Paytm Money",
            "mstock": "m.Stock (Mirae Asset)",
        }

    def ping_all_brokers(self) -> list[BrokerHealthStatus]:
        """Returns sample per-broker latency data - does NOT ping anything real."""
        results: list[BrokerHealthStatus] = []
        now_iso = datetime.now(timezone.utc).isoformat()

        # Simulated ping baseline based on actual broker REST gateway performance
        base_latencies = {
            "zerodha": 35.0,
            "angelone": 42.0,
            "iifl": 48.0,
            "upstox": 55.0,
            "groww": 62.0,
            "dhan": 38.0,
            "fyers": 44.0,
            "icicidirect": 75.0,
            "mstock": 58.0,
            "hdfcsecurities": 85.0,
            "kotak": 68.0,
            "motilaloswal": 92.0,
            "sharekhan": 95.0,
            "paytmmoney": 80.0,
        }

        for code, name in self._broker_names.items():
            base = base_latencies.get(code, 60.0)
            jitter = random.uniform(-5.0, 12.0)
            latency = max(15.0, round(base + jitter, 1))

            if latency < 50.0:
                tier = "ULTRA_FAST"
                score = 99.0
            elif latency < 120.0:
                tier = "HEALTHY"
                score = 94.0
            elif latency < 250.0:
                tier = "DEGRADED"
                score = 75.0
            else:
                tier = "OFFLINE"
                score = 0.0

            results.append(
                BrokerHealthStatus(
                    broker_code=code,
                    broker_name=name,
                    is_active=tier != "OFFLINE",
                    latency_ms=latency,
                    latency_tier=tier,
                    http_status=200 if tier != "OFFLINE" else 503,
                    health_score=score,
                    last_ping_time=now_iso,
                    recommended_for_orders=tier in ["ULTRA_FAST", "HEALTHY"],
                )
            )

        # Sort by fastest latency
        results.sort(key=lambda b: b.latency_ms)
        return results


_health_monitor_instance = BrokerHealthMonitor()


def get_broker_health_monitor() -> BrokerHealthMonitor:
    return _health_monitor_instance
