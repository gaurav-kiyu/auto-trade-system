"""Digital Twin — Real-Time System State Mirroring (Constitution v4.0, Layer 5).

Provides a real-time digital twin of the live trading system:
- Capital & P&L tracking (snapshots + trends)
- Position mirroring across all instruments
- Signal pipeline state (queued, evaluating, executing, completed)
- Broker connection health
- Data provider health (yfinance, NSE, WebSocket)
- System resource usage (CPU, memory, disk)
- Trade journal state

Integrates with:
- StateManager for persisted state
- PerformanceTracker for P&L history
- HealthChecker for system health
- BIDashboard for trend analytics

Usage:
    from core.digital_twin import get_digital_twin

    twin = get_digital_twin()
    twin.snapshot(
        capital=100000.0,
        positions=[{"instrument": "NIFTY", "qty": 50, "pnl": 250.0}],
        broker_connected=True,
        data_provider_healthy=True,
    )
    state = twin.get_current_state()
    print(state.summary_text())
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────

MAX_SNAPSHOT_HISTORY = 1000  # Keep last 1000 snapshots
TREND_WINDOW_SECONDS = 3600  # 1 hour for short-term trends


# ── Data Models ────────────────────────────────────────────────────────────


@dataclass
class PositionMirror:
    """Mirror of a single position."""

    instrument: str = ""
    asset_type: str = ""  # INDEX, COMMODITY, CURRENCY, FUTURES, OPTION
    direction: str = "LONG"  # LONG, SHORT
    quantity: int = 0
    entry_price: float = 0.0
    current_price: float = 0.0
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    timestamp: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "instrument": self.instrument,
            "asset_type": self.asset_type,
            "direction": self.direction,
            "quantity": self.quantity,
            "entry_price": round(self.entry_price, 2),
            "current_price": round(self.current_price, 2),
            "unrealized_pnl": round(self.unrealized_pnl, 2),
            "realized_pnl": round(self.realized_pnl, 2),
            "timestamp": self.timestamp,
        }


@dataclass
class BrokerHealth:
    """Health state of broker connections."""

    primary_connected: bool = False
    failover_connected: bool = False
    latency_ms: float = 0.0
    last_sync: float = 0.0
    orders_pending: int = 0
    errors_last_minute: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "primary_connected": self.primary_connected,
            "failover_connected": self.failover_connected,
            "latency_ms": round(self.latency_ms, 1),
            "last_sync": self.last_sync,
            "orders_pending": self.orders_pending,
            "errors_last_minute": self.errors_last_minute,
        }


@dataclass
class DataProviderHealth:
    """Health state of data providers."""

    yfinance_healthy: bool = False
    nse_healthy: bool = False
    websocket_healthy: bool = False
    oldest_data_age_seconds: float = 0.0
    providers_connected: int = 0
    providers_total: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "yfinance_healthy": self.yfinance_healthy,
            "nse_healthy": self.nse_healthy,
            "websocket_healthy": self.websocket_healthy,
            "oldest_data_age_seconds": round(self.oldest_data_age_seconds, 1),
            "providers_connected": self.providers_connected,
            "providers_total": self.providers_total,
        }


@dataclass
class SystemResources:
    """System resource usage snapshot."""

    cpu_percent: float = 0.0
    memory_percent: float = 0.0
    disk_percent: float = 0.0
    threads_active: int = 0
    uptime_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "cpu_percent": round(self.cpu_percent, 1),
            "memory_percent": round(self.memory_percent, 1),
            "disk_percent": round(self.disk_percent, 1),
            "threads_active": self.threads_active,
            "uptime_seconds": round(self.uptime_seconds, 1),
        }


@dataclass
class SystemSnapshot:
    """A single point-in-time snapshot of the entire system."""

    timestamp: float = 0.0
    capital: float = 0.0
    total_pnl: float = 0.0
    positions: list[PositionMirror] = field(default_factory=list)
    signals_pending: int = 0
    signals_processing: int = 0
    broker: BrokerHealth = field(default_factory=BrokerHealth)
    data_providers: DataProviderHealth = field(default_factory=DataProviderHealth)
    resources: SystemResources = field(default_factory=SystemResources)
    mode: str = ""  # PAPER, LIVE, SHADOW
    operating_state: str = "RUNNING"  # RUNNING, PAUSED, HALTED, SHUTDOWN
    trading_hours_active: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "date": datetime.fromtimestamp(self.timestamp).isoformat() if self.timestamp else "",
            "capital": round(self.capital, 2),
            "total_pnl": round(self.total_pnl, 2),
            "positions": [p.to_dict() for p in self.positions],
            "positions_count": len(self.positions),
            "signals_pending": self.signals_pending,
            "signals_processing": self.signals_processing,
            "broker": self.broker.to_dict(),
            "data_providers": self.data_providers.to_dict(),
            "resources": self.resources.to_dict(),
            "mode": self.mode,
            "operating_state": self.operating_state,
            "trading_hours_active": self.trading_hours_active,
        }


@dataclass
class DigitalTwinState:
    """Current state of the digital twin with trend data."""

    current: SystemSnapshot = field(default_factory=SystemSnapshot)
    capital_trend: list[dict[str, Any]] = field(default_factory=list)
    pnl_trend: list[dict[str, Any]] = field(default_factory=list)
    capital_change_1h: float = 0.0
    capital_change_24h: float = 0.0
    pnl_change_1h: float = 0.0
    broker_uptime_percent: float = 100.0
    data_provider_uptime_percent: float = 100.0
    snapshot_count: int = 0
    last_update: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "current": self.current.to_dict(),
            "capital_trend": self.capital_trend[-60:],
            "pnl_trend": self.pnl_trend[-60:],
            "capital_change_1h": round(self.capital_change_1h, 2),
            "capital_change_24h": round(self.capital_change_24h, 2),
            "pnl_change_1h": round(self.pnl_change_1h, 2),
            "broker_uptime_percent": round(self.broker_uptime_percent, 1),
            "data_provider_uptime_percent": round(self.data_provider_uptime_percent, 1),
            "snapshot_count": self.snapshot_count,
            "last_update": self.last_update,
        }

    def summary_text(self) -> str:
        c = self.current
        lines = [
            "═" * 60,
            "  DIGITAL TWIN — SYSTEM STATE",
            "═" * 60,
            f"  Capital: ₹{c.capital:,.2f}  |  P&L: ₹{c.total_pnl:+,.2f}",
            f"  Positions: {len(c.positions)} active",
            f"  Mode: {c.mode}  |  State: {c.operating_state}",
            f"  Trading Hours: {'✅ Active' if c.trading_hours_active else '⏸️ Inactive'}",
            "",
            "  ┌─ Broker Connection",
            f"  │  Primary: {'✅ Connected' if c.broker.primary_connected else '❌ Disconnected'}",
            f"  │  Failover: {'✅ Ready' if c.broker.failover_connected else '❌ Unavailable'}",
            f"  │  Latency: {c.broker.latency_ms:.0f}ms  |  Pending Orders: {c.broker.orders_pending}",
            "  └─",
            "  ┌─ Data Providers",
            f"  │  yfinance: {'✅' if c.data_providers.yfinance_healthy else '❌'}  ",
            f"  │  NSE: {'✅' if c.data_providers.nse_healthy else '❌'}  ",
            f"  │  WebSocket: {'✅' if c.data_providers.websocket_healthy else '❌'}",
            "  └─",
            "  ┌─ System Resources",
            f"  │  CPU: {c.resources.cpu_percent:.0f}%  |  RAM: {c.resources.memory_percent:.0f}%  ",
            f"  │  Disk: {c.resources.disk_percent:.0f}%  |  Threads: {c.resources.threads_active}",
            "  └─",
        ]
        if self.capital_trend:
            first = self.capital_trend[0].get("capital", 0)
            last = self.capital_trend[-1].get("capital", 0)
            if first:
                change_pct = ((last - first) / first) * 100
                lines.append(f"  Capital Trend (1h): ₹{first:,.0f} → ₹{last:,.0f} ({change_pct:+.1f}%)")
        lines.append("═" * 60)
        return "\n".join(lines)


# ── Digital Twin ──────────────────────────────────────────────────────────


class DigitalTwin:
    """Digital Twin — Real-Time System State Mirroring.

    Maintains a constantly-updated digital twin of the live trading system,
    tracking capital, positions, broker health, data providers, and system
    resources. Provides trend analysis and health scoring.

    Thread-safe. Persisted to JSON for continuity.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._snapshots: list[SystemSnapshot] = []
        self._last_state: DigitalTwinState = DigitalTwinState()
        self._start_time = time.time()
        self._persist_path = Path("json/digital_twin.json")
        self._load_state()

    # ── Public API ────────────────────────────────────────────────────────

    def snapshot(
        self,
        capital: float = 0.0,
        total_pnl: float = 0.0,
        positions: list[dict[str, Any]] | None = None,
        signals_pending: int = 0,
        signals_processing: int = 0,
        broker_connected: bool | None = None,
        broker_failover_connected: bool | None = None,
        broker_latency_ms: float = 0.0,
        yfinance_healthy: bool | None = None,
        nse_healthy: bool | None = None,
        websocket_healthy: bool | None = None,
        cpu_percent: float = 0.0,
        memory_percent: float = 0.0,
        disk_percent: float = 0.0,
        mode: str = "",
        operating_state: str = "RUNNING",
        trading_hours_active: bool = False,
    ) -> SystemSnapshot:
        """Take a point-in-time snapshot of the system.

        Args:
            capital: Current available capital.
            total_pnl: Total realized + unrealized P&L.
            positions: List of position dicts (instrument, direction, qty, pnl, etc.).
            signals_pending: Number of signals waiting for evaluation.
            signals_processing: Number of signals currently being evaluated.
            broker_connected: Whether primary broker is connected.
            broker_failover_connected: Whether failover broker is ready.
            broker_latency_ms: Broker API latency in milliseconds.
            yfinance_healthy: Whether yfinance data provider is healthy.
            nse_healthy: Whether NSE data provider is healthy.
            websocket_healthy: Whether WebSocket feed is healthy.
            cpu_percent: CPU usage percentage.
            memory_percent: Memory usage percentage.
            disk_percent: Disk usage percentage.
            mode: Execution mode (PAPER, LIVE, SHADOW).
            operating_state: System operating state.
            trading_hours_active: Whether within trading hours.

        Returns:
            SystemSnapshot with all current state.
        """
        now = time.time()

        # Build position mirrors
        position_mirrors: list[PositionMirror] = []
        for p in (positions or []):
            if isinstance(p, dict):
                position_mirrors.append(PositionMirror(
                    instrument=p.get("instrument", ""),
                    asset_type=p.get("asset_type", ""),
                    direction=p.get("direction", "LONG"),
                    quantity=p.get("quantity", 0),
                    entry_price=p.get("entry_price", 0.0),
                    current_price=p.get("current_price", 0.0),
                    unrealized_pnl=p.get("unrealized_pnl", 0.0),
                    realized_pnl=p.get("realized_pnl", 0.0),
                    timestamp=now,
                ))

        # Build broker health
        broker = BrokerHealth(
            primary_connected=broker_connected or False,
            failover_connected=broker_failover_connected or False,
            latency_ms=broker_latency_ms,
            last_sync=now,
        )

        # Build data provider health
        providers = DataProviderHealth(
            yfinance_healthy=yfinance_healthy or False,
            nse_healthy=nse_healthy or False,
            websocket_healthy=websocket_healthy or False,
            providers_connected=sum([1 for h in [yfinance_healthy, nse_healthy, websocket_healthy] if h]) if any([yfinance_healthy, nse_healthy, websocket_healthy]) else 0,
            providers_total=3,
        )

        # Resources
        resources = SystemResources(
            cpu_percent=cpu_percent,
            memory_percent=memory_percent,
            disk_percent=disk_percent,
            uptime_seconds=now - self._start_time,
        )

        snap = SystemSnapshot(
            timestamp=now,
            capital=capital,
            total_pnl=total_pnl,
            positions=position_mirrors,
            signals_pending=signals_pending,
            signals_processing=signals_processing,
            broker=broker,
            data_providers=providers,
            resources=resources,
            mode=mode,
            operating_state=operating_state,
            trading_hours_active=trading_hours_active,
        )

        with self._lock:
            self._snapshots.append(snap)
            if len(self._snapshots) > MAX_SNAPSHOT_HISTORY:
                self._snapshots = self._snapshots[-MAX_SNAPSHOT_HISTORY:]
            self._update_state(snap)
            self._persist()

        return snap

    def get_current_state(self) -> DigitalTwinState:
        """Get the current digital twin state with trends."""
        with self._lock:
            return self._last_state

    def get_snapshot_history(
        self, limit: int = 100, since: float = 0.0
    ) -> list[SystemSnapshot]:
        """Get snapshot history, optionally filtered by time."""
        with self._lock:
            snaps = self._snapshots
            if since > 0:
                snaps = [s for s in snaps if s.timestamp >= since]
            return snaps[-limit:]

    def get_capital_trend(self, window_minutes: int = 60) -> list[dict[str, Any]]:
        """Get capital trend over time."""
        with self._lock:
            cutoff = time.time() - (window_minutes * 60)
            relevant = [s for s in self._snapshots if s.timestamp >= cutoff]
            return [
                {"timestamp": s.timestamp, "capital": s.capital, "pnl": s.total_pnl}
                for s in relevant[-100:]
            ]

    def get_stats(self) -> dict[str, Any]:
        """Get digital twin statistics."""
        with self._lock:
            state = self._last_state
            return {
                "snapshot_count": len(self._snapshots),
                "uptime_seconds": round(time.time() - self._start_time, 1),
                "current_capital": state.current.capital,
                "current_pnl": state.current.total_pnl,
                "active_positions": len(state.current.positions),
                "broker_connected": state.current.broker.primary_connected,
                "operating_state": state.current.operating_state,
                "mode": state.current.mode,
                "capital_change_1h": state.capital_change_1h,
                "capital_change_24h": state.capital_change_24h,
            }

    def get_health_score(self) -> float:
        """Get overall system health score (0.0 to 1.0)."""
        with self._lock:
            c = self._last_state.current
            score = 1.0

            # Broker health (30% weight)
            if not c.broker.primary_connected:
                score -= 0.3
            if c.broker.errors_last_minute > 5:
                score -= 0.1

            # Data provider health (25% weight)
            connected = c.data_providers.providers_connected
            total = c.data_providers.providers_total
            if total > 0:
                provider_health = connected / total
                score -= (1.0 - provider_health) * 0.25

            # System resources (20% weight)
            if c.resources.cpu_percent > 90:
                score -= 0.1
            if c.resources.memory_percent > 90:
                score -= 0.1
            if c.resources.disk_percent > 90:
                score -= 0.1

            # Operating state (25% weight)
            if c.operating_state == "HALTED":
                score -= 0.25
            elif c.operating_state == "PAUSED":
                score -= 0.1

            return max(0.0, min(1.0, score))

    def clear_history(self) -> None:
        """Clear all snapshot history."""
        with self._lock:
            self._snapshots.clear()
            if self._persist_path.exists():
                self._persist_path.unlink()

    # ── Internal ─────────────────────────────────────────────────────────

    def _update_state(self, snap: SystemSnapshot) -> None:
        """Update the aggregated state with trends."""
        state = self._last_state
        state.current = snap
        state.last_update = snap.timestamp
        state.snapshot_count = len(self._snapshots)

        # Update capital trend
        state.capital_trend.append({"timestamp": snap.timestamp, "capital": snap.capital})
        if len(state.capital_trend) > 1000:
            state.capital_trend = state.capital_trend[-1000:]

        # Update P&L trend
        state.pnl_trend.append({"timestamp": snap.timestamp, "pnl": snap.total_pnl})
        if len(state.pnl_trend) > 1000:
            state.pnl_trend = state.pnl_trend[-1000:]

        # Calculate 1h changes
        cutoff_1h = snap.timestamp - TREND_WINDOW_SECONDS
        capital_1h_ago = [
            p["capital"] for p in state.capital_trend
            if p["timestamp"] <= cutoff_1h
        ]
        if capital_1h_ago:
            state.capital_change_1h = snap.capital - capital_1h_ago[-1]
        pnl_1h_ago = [
            p["pnl"] for p in state.pnl_trend
            if p["timestamp"] <= cutoff_1h
        ]
        if pnl_1h_ago:
            state.pnl_change_1h = snap.total_pnl - pnl_1h_ago[-1]

        # Calculate 24h changes
        cutoff_24h = snap.timestamp - (86400)
        capital_24h_ago = [
            p["capital"] for p in state.capital_trend
            if p["timestamp"] <= cutoff_24h
        ]
        if capital_24h_ago:
            state.capital_change_24h = snap.capital - capital_24h_ago[-1]

        # Broker uptime from last 100 snapshots
        recent = self._snapshots[-100:]
        if recent:
            connected_count = sum(1 for s in recent if s.broker.primary_connected)
            state.broker_uptime_percent = (connected_count / len(recent)) * 100

        # Data provider uptime
        if recent:
            healthy_count = sum(
                1 for s in recent
                if s.data_providers.yfinance_healthy and s.data_providers.nse_healthy
            )
            state.data_provider_uptime_percent = (healthy_count / len(recent)) * 100

    # ── Persistence ──────────────────────────────────────────────────────

    def _persist(self) -> None:
        """Persist latest state to disk."""
        try:
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "last_state": self._last_state.to_dict(),
                "recent_snapshots": [s.to_dict() for s in self._snapshots[-50:]],
            }
            self._persist_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except (OSError, ValueError) as exc:
            _log.debug("[DTWIN] Persist: %s", exc)

    def _load_state(self) -> None:
        """Load previous state from disk."""
        try:
            if not self._persist_path.is_file():
                return
            data = json.loads(self._persist_path.read_text(encoding="utf-8"))
            # We only restore snapshot history, not the live state
            recent = data.get("recent_snapshots", [])
            for item in recent[-50:]:
                try:
                    snap = SystemSnapshot(
                        timestamp=item.get("timestamp", 0),
                        capital=item.get("capital", 0),
                        total_pnl=item.get("total_pnl", 0),
                        positions=self._load_positions(item.get("positions", [])),
                        mode=item.get("mode", ""),
                        operating_state=item.get("operating_state", "RUNNING"),
                    )
                    self._snapshots.append(snap)
                except (TypeError, ValueError) as exc:
                    _log.debug("[DTWIN] Load skip: %s", exc)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            _log.debug("[DTWIN] Load failed: %s", exc)

    def _load_positions(self, positions_data: list[dict]) -> list[PositionMirror]:
        """Load position mirrors from dict data."""
        result: list[PositionMirror] = []
        for p in positions_data:
            if isinstance(p, dict):
                result.append(PositionMirror(
                    instrument=p.get("instrument", ""),
                    direction=p.get("direction", "LONG"),
                    quantity=p.get("quantity", 0),
                    unrealized_pnl=p.get("unrealized_pnl", 0.0),
                ))
        return result


# ── CLI ────────────────────────────────────────────────────────────────────


def _cli() -> None:
    import argparse
    ap = argparse.ArgumentParser(
        prog="python -m core.digital_twin",
        description="Digital Twin — Real-time system state mirror",
    )
    ap.add_argument("--state", action="store_true", help="Show current system state")
    ap.add_argument("--health", action="store_true", help="Show health score")
    ap.add_argument("--stats", action="store_true", help="Show statistics")
    ap.add_argument("--snapshot", action="store_true", help="Take a test snapshot")
    ap.add_argument("--json", action="store_true", help="Output as JSON")
    args = ap.parse_args()

    twin = get_digital_twin()

    if args.snapshot:
        snap = twin.snapshot(capital=100000.0, total_pnl=0, mode="PAPER")
        print(f"Snapshot taken: capital={snap.capital:.0f}, ts={snap.timestamp:.0f}")
        return

    if args.state:
        state = twin.get_current_state()
        if args.json:
            import json
            print(json.dumps(state.to_dict(), indent=2))
        else:
            print(state.summary_text())
        return

    if args.health:
        score = twin.get_health_score()
        print(f"Health Score: {score:.3f}")
        return

    if args.stats:
        stats = twin.get_stats()
        if args.json:
            import json
            print(json.dumps(stats, indent=2))
        else:
            print(f"Snapshots: {stats['snapshot_count']}")
            print(f"Capital: {stats['current_capital']:.0f}")
            print(f"P&L: {stats['current_pnl']:.0f}")
            print(f"Mode: {stats['mode']}")
        return

    ap.print_help()


if __name__ == "__main__":
    _cli()

# ── Singleton ──────────────────────────────────────────────────────────────

_twin: DigitalTwin | None = None
_twin_lock = threading.RLock()


def get_digital_twin() -> DigitalTwin:
    """Get the singleton DigitalTwin instance."""
    global _twin
    with _twin_lock:
        if _twin is None:
            _twin = DigitalTwin()
        return _twin


def reset_digital_twin() -> None:
    """Force-reset singleton (for testing)."""
    global _twin
    with _twin_lock:
        _twin = None


__all__ = [
    "BrokerHealth",
    "DataProviderHealth",
    "DigitalTwin",
    "DigitalTwinState",
    "PositionMirror",
    "SystemResources",
    "SystemSnapshot",
    "get_digital_twin",
    "reset_digital_twin",
]
