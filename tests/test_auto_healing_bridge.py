"""Unit tests for core.self_healing.auto_healing_bridge."""
import time

from core.self_healing.auto_healing_bridge import AutoHealingBridge


def test_auto_healing_bridge_init():
    bridge = AutoHealingBridge()
    status = bridge.get_status()
    assert status["active"] is False
    assert "learner_state" in status


def test_auto_healing_bridge_cycle():
    bridge = AutoHealingBridge()
    report = bridge.run_health_and_remediate_cycle()
    assert "status" in report
    assert "timestamp" in report


def test_auto_healing_bridge_start_stop():
    bridge = AutoHealingBridge()
    bridge.start(poll_interval=0.1)
    time.sleep(0.3)
    status = bridge.get_status()
    assert status["active"] is True
    bridge.stop()
    status = bridge.get_status()
    assert status["active"] is False
