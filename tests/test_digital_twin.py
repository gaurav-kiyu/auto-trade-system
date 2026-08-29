"""Tests for Digital Twin module."""

from __future__ import annotations

from pathlib import Path

import pytest
from core.digital_twin import (
    BrokerHealth,
    PositionMirror,
    SystemSnapshot,
    get_digital_twin,
    reset_digital_twin,
)


@pytest.fixture(autouse=True)
def reset_twin():
    reset_digital_twin()
    p = Path("json/digital_twin.json")
    if p.exists():
        p.unlink()
    yield
    reset_digital_twin()


class TestDigitalTwinSnapshot:
    def test_take_snapshot_basic(self):
        twin = get_digital_twin()
        snap = twin.snapshot(capital=100000.0, total_pnl=2500.0, mode="PAPER")
        assert snap.capital == 100000.0
        assert snap.total_pnl == 2500.0
        assert snap.mode == "PAPER"
        assert snap.operating_state == "RUNNING"
        assert len(snap.positions) == 0

    def test_take_snapshot_with_positions(self):
        twin = get_digital_twin()
        snap = twin.snapshot(
            capital=100000.0,
            total_pnl=1500.0,
            positions=[
                {"instrument": "NIFTY", "direction": "LONG", "quantity": 50,
                 "entry_price": 23300, "current_price": 23350, "unrealized_pnl": 2500},
                {"instrument": "BANKNIFTY", "direction": "LONG", "quantity": 25,
                 "entry_price": 51000, "current_price": 50900, "unrealized_pnl": -2500},
            ],
            mode="LIVE",
        )
        assert len(snap.positions) == 2
        assert snap.positions[0].instrument == "NIFTY"
        assert snap.positions[1].instrument == "BANKNIFTY"

    def test_take_snapshot_with_broker_health(self):
        twin = get_digital_twin()
        snap = twin.snapshot(
            capital=100000.0, total_pnl=0,
            broker_connected=True,
            broker_latency_ms=45.0,
        )
        assert snap.broker.primary_connected is True
        assert snap.broker.latency_ms == 45.0

    def test_take_snapshot_with_data_providers(self):
        twin = get_digital_twin()
        snap = twin.snapshot(
            capital=100000.0, total_pnl=0,
            yfinance_healthy=True,
            nse_healthy=False,
            websocket_healthy=True,
        )
        assert snap.data_providers.yfinance_healthy is True
        assert snap.data_providers.nse_healthy is False
        assert snap.data_providers.websocket_healthy is True
        assert snap.data_providers.providers_connected >= 2

    def test_take_snapshot_with_resources(self):
        twin = get_digital_twin()
        snap = twin.snapshot(
            capital=100000.0, total_pnl=0,
            cpu_percent=45.0, memory_percent=62.0, disk_percent=55.0,
        )
        assert snap.resources.cpu_percent == 45.0
        assert snap.resources.memory_percent == 62.0

    def test_snapshot_history(self):
        twin = get_digital_twin()
        twin.snapshot(capital=100000.0, total_pnl=0)
        twin.snapshot(capital=101000.0, total_pnl=1000)
        twin.snapshot(capital=102000.0, total_pnl=2000)
        history = twin.get_snapshot_history(limit=10)
        assert len(history) == 3


class TestDigitalTwinState:
    def test_get_current_state(self):
        twin = get_digital_twin()
        twin.snapshot(capital=100000.0, total_pnl=500, mode="PAPER")
        state = twin.get_current_state()
        assert state.current.capital == 100000.0
        assert state.current.total_pnl == 500
        assert state.current.mode == "PAPER"
        assert state.snapshot_count >= 1

    def test_state_trends(self):
        twin = get_digital_twin()
        twin.snapshot(capital=100000.0, total_pnl=0)
        twin.snapshot(capital=101000.0, total_pnl=1000)
        state = twin.get_current_state()
        assert len(state.capital_trend) >= 2
        assert len(state.pnl_trend) >= 2

    def test_state_summary_text(self):
        twin = get_digital_twin()
        twin.snapshot(capital=100000.0, total_pnl=500, mode="PAPER")
        state = twin.get_current_state()
        summary = state.summary_text()
        assert "DIGITAL TWIN" in summary
        assert "100,000" in summary
        assert "PAPER" in summary


class TestDigitalTwinHealth:
    def test_health_score_healthy(self):
        twin = get_digital_twin()
        twin.snapshot(
            capital=100000.0, total_pnl=0,
            broker_connected=True,
            broker_failover_connected=True,
            yfinance_healthy=True,
            nse_healthy=True,
            websocket_healthy=True,
            cpu_percent=30, memory_percent=50, disk_percent=40,
        )
        score = twin.get_health_score()
        assert score > 0.5

    def test_health_score_broker_down(self):
        twin = get_digital_twin()
        twin.snapshot(
            capital=100000.0, total_pnl=0,
            broker_connected=False,
            operating_state="PAUSED",
        )
        score = twin.get_health_score()
        assert score < 1.0

    def test_get_stats(self):
        twin = get_digital_twin()
        twin.snapshot(capital=100000.0, total_pnl=0)
        stats = twin.get_stats()
        assert stats["snapshot_count"] == 1
        assert stats["current_capital"] == 100000.0

    def test_capital_trend(self):
        twin = get_digital_twin()
        twin.snapshot(capital=100000.0, total_pnl=0)
        twin.snapshot(capital=100500.0, total_pnl=500)
        twin.snapshot(capital=101000.0, total_pnl=1000)
        trend = twin.get_capital_trend(window_minutes=60)
        assert len(trend) >= 2


class TestDigitalTwinModels:
    def test_system_snapshot_to_dict(self):
        snap = SystemSnapshot(capital=100000.0, total_pnl=500)
        d = snap.to_dict()
        assert d["capital"] == 100000.0
        assert d["total_pnl"] == 500.0

    def test_position_mirror_to_dict(self):
        p = PositionMirror(instrument="NIFTY", quantity=50, unrealized_pnl=2500)
        d = p.to_dict()
        assert d["instrument"] == "NIFTY"
        assert d["quantity"] == 50

    def test_broker_health_to_dict(self):
        b = BrokerHealth(primary_connected=True, latency_ms=25.0)
        d = b.to_dict()
        assert d["primary_connected"] is True

    def test_clear_history(self):
        twin = get_digital_twin()
        twin.snapshot(capital=100000.0, total_pnl=0)
        twin.clear_history()
        assert len(twin.get_snapshot_history()) == 0
