"""
Real-Time Performance Monitor - Tracks performance and alerts on anomalies
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime

from core.datetime_ist import now_ist

_log = logging.getLogger(__name__)


@dataclass
class PerformanceConfig:
    enabled: bool = False
    alert_webhook_url: str = ""
    alert_drawdown_pct: float = 0.05
    alert_loss_streak: int = 3


@dataclass
class PerformanceSnapshot:
    timestamp: datetime
    total_trades: int
    win_rate: float
    total_pnl: float
    current_drawdown: float
    win_streak: int
    loss_streak: int


class RealtimePerformanceMonitor:
    def __init__(self, config: PerformanceConfig):
        self.config = config
        self._trades: list[dict] = []
        self._last_alert_time: datetime | None = None
        self._current_streak = 0
        self._streak_type: str | None = None

    def add_trade(self, pnl: float):
        self._trades.append({
            "pnl": pnl,
            "timestamp": now_ist().isoformat(),
        })
        self._update_streak(pnl)
        self._check_alerts()

    def _update_streak(self, pnl: float):
        if pnl > 0:
            if self._streak_type == "win":
                self._current_streak += 1
            else:
                self._streak_type = "win"
                self._current_streak = 1
        else:
            if self._streak_type == "lose":
                self._current_streak += 1
            else:
                self._streak_type = "lose"
                self._current_streak = 1

    def get_current_snapshot(self) -> PerformanceSnapshot:
        if not self._trades:
            return PerformanceSnapshot(
                timestamp=now_ist(),
                total_trades=0,
                win_rate=0.0,
                total_pnl=0.0,
                current_drawdown=0.0,
                win_streak=0,
                loss_streak=0,
            )

        wins = sum(1 for t in self._trades if t["pnl"] > 0)
        total_pnl = sum(t["pnl"] for t in self._trades)

        running_max = 0
        current_drawdown = 0
        peak = 0
        for t in self._trades:
            peak = max(peak, peak + t["pnl"])
            current_drawdown = max(current_drawdown, peak - (peak + t["pnl"]))

        win_streak = self._current_streak if self._streak_type == "win" else 0
        loss_streak = self._current_streak if self._streak_type == "lose" else 0

        return PerformanceSnapshot(
            timestamp=now_ist(),
            total_trades=len(self._trades),
            win_rate=wins / len(self._trades) * 100,
            total_pnl=total_pnl,
            current_drawdown=current_drawdown,
            win_streak=win_streak,
            loss_streak=loss_streak,
        )

    def _check_alerts(self):
        if not self.config.enabled or not self.config.alert_webhook_url:
            return

        snap = self.get_current_snapshot()

        if snap.current_drawdown > self.config.alert_drawdown_pct * 100:
            self._send_alert(f"DRAWDOWN ALERT: {snap.current_drawdown:.1f}% exceeded threshold")

        if self._streak_type == "lose" and self._current_streak >= self.config.alert_loss_streak:
            self._send_alert(f"LOSS STREAK ALERT: {self._current_streak} consecutive losses")

    def _send_alert(self, message: str):
        _log.warning(f"ALERT: {message}")
        if self.config.alert_webhook_url:
            try:
                import urllib.request
                data = json.dumps({"text": f"OPB: {message}"}).encode()
                req = urllib.request.Request(
                    self.config.alert_webhook_url,
                    data=data,
                    headers={"Content-Type": "application/json"},
                )
                urllib.request.urlopen(req, timeout=5)
            except Exception as e:
                _log.error(f"Failed to send webhook alert: {e}")


def create_performance_monitor(config: dict) -> RealtimePerformanceMonitor:
    cfg = PerformanceConfig(
        enabled=config.get("REAL_TIME_DASHBOARD_ENABLED", False),
        alert_webhook_url=config.get("REAL_TIME_ALERT_WEBHOOK_URL", ""),
        alert_drawdown_pct=config.get("REAL_TIME_ALERT_ON_DRAWDOWN_PCT", 0.05),
        alert_loss_streak=config.get("REAL_TIME_ALERT_ON_LOSS_STREAK", 3),
    )
    return RealtimePerformanceMonitor(cfg)
