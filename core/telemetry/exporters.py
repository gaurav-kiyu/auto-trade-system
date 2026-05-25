"""
AD-KIYU Telemetry — Metrics Exporters.

Supported export formats:
  - Prometheus text format (:9090/metrics)
  - JSON log lines (structured logging)
"""
from __future__ import annotations

import json
import logging
import threading
from typing import Any

from core.telemetry.metrics import MetricsCollector

_log = logging.getLogger(__name__)


class JSONLogExporter:
    """Exports metrics as JSON log lines."""

    def __init__(self, collector: MetricsCollector, log: logging.Logger | None = None):
        self._collector = collector
        self._log = log or _log
        self._last_snapshot: dict[str, Any] = {}

    def emit(self) -> None:
        """Write current metrics snapshot as a JSON log line."""
        snapshot = self._collector.snapshot()
        self._last_snapshot = snapshot
        self._log.info("[METRICS] %s", json.dumps(snapshot))

    def last_snapshot(self) -> dict[str, Any]:
        return self._last_snapshot


class PrometheusExporter:
    """Exports metrics in Prometheus text exposition format.

    Serves on a configurable HTTP endpoint (default :9090/metrics).
    """

    def __init__(self, collector: MetricsCollector):
        self._collector = collector
        self._lock = threading.Lock()
        self._registry: dict[str, str] = {}

    def generate_text(self) -> str:
        """Generate Prometheus text exposition format output."""
        snapshot = self._collector.snapshot()
        lines: list[str] = []
        lines.append("# HELP ad_kiyu_metrics AD-KIYU trading system metrics")
        lines.append("# TYPE ad_kiyu_metrics gauge")

        def _walk(prefix: str, data: Any) -> None:
            if isinstance(data, dict):
                for k, v in data.items():
                    _walk(f"{prefix}_{k}", v)
            elif isinstance(data, (int, float)):
                lines.append(f"{prefix} {data}")

        _walk("ad_kiyu", snapshot)
        lines.append("")
        return "\n".join(lines)

    def serve(self, host: str = "0.0.0.0", port: int = 9090) -> None:
        """Start a minimal HTTP server for Prometheus scraping."""
        from http.server import BaseHTTPRequestHandler, HTTPServer

        class _Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # type: ignore[override]
                if self.path == "/metrics":
                    body = self.server._exporter.generate_text()  # type: ignore[attr-defined]
                    self.send_response(200)
                    self.send_header("Content-Type", "text/plain; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(body.encode("utf-8"))
                else:
                    self.send_response(404)
                    self.end_headers()

            def log_message(self, fmt, *args) -> None:  # type: ignore[override]
                pass  # suppress HTTP server logs

        server = HTTPServer((host, port), _Handler)
        server._exporter = self  # type: ignore[attr-defined]
        _log.info(f"Prometheus exporter listening on {host}:{port}/metrics")
        try:
            server.serve_forever()
        except Exception as exc:
            _log.error(f"Prometheus exporter error: {exc}")


def start_prometheus_exporter(
    collector: MetricsCollector,
    host: str = "0.0.0.0",
    port: int = 9090,
) -> threading.Thread | None:
    """Start the Prometheus exporter in a daemon thread."""
    exporter = PrometheusExporter(collector)
    t = threading.Thread(target=exporter.serve, args=(host, port), daemon=True, name="prometheus-exporter")
    t.start()
    _log.info(f"Prometheus exporter thread started on {host}:{port}")
    return t
