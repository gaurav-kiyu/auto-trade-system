"""Tests for the AI Safety Gate (core/ai/safety_gate.py)."""

from __future__ import annotations

import json

from core.ai.safety_gate import (
    ALLOWED_ACTIONS,
    FORBIDDEN_ACTIONS,
    AISafetyGate,
    AISafetyVerdict,
    check_ai_action,
    get_safety_gate,
)


class TestAISafetyVerdict:
    def test_create_verdict(self):
        v = AISafetyVerdict(allowed=True, action_type="score_signal", reason="OK")
        assert v.allowed is True
        assert v.action_type == "score_signal"
        assert v.reason == "OK"

    def test_create_blocked_verdict(self):
        v = AISafetyVerdict(
            allowed=False,
            action_type="place_order",
            reason="AI cannot place orders",
            failures=["Forbidden"],
        )
        assert v.allowed is False
        assert len(v.failures) == 1

    def test_to_dict(self):
        v = AISafetyVerdict(allowed=True, action_type="score_signal", reason="OK")
        d = v.to_dict()
        assert d["allowed"] is True
        assert d["action_type"] == "score_signal"
        json.dumps(d)

    def test_timestamp_auto_set(self):
        v = AISafetyVerdict(allowed=True, action_type="test")
        assert v.timestamp > 0


class TestAISafetyGate:
    def test_init(self):
        gate = AISafetyGate()
        assert gate is not None

    def test_block_place_order(self):
        gate = AISafetyGate()
        verdict = gate.check_action("place_order", source="test_agent")
        assert verdict.allowed is False
        assert "cannot place orders" in verdict.reason

    def test_block_modify_risk_limit(self):
        gate = AISafetyGate()
        verdict = gate.check_action("modify_risk_limit")
        assert verdict.allowed is False
        assert "cannot modify risk limits" in verdict.reason

    def test_block_disable_hard_halt(self):
        gate = AISafetyGate()
        verdict = gate.check_action("disable_hard_halt")
        assert verdict.allowed is False

    def test_block_bypass_circuit_breaker(self):
        gate = AISafetyGate()
        verdict = gate.check_action("bypass_circuit_breaker")
        assert verdict.allowed is False

    def test_allow_score_signal(self):
        gate = AISafetyGate()
        verdict = gate.check_action("score_signal")
        assert verdict.allowed is True

    def test_allow_rank_strategies(self):
        gate = AISafetyGate()
        verdict = gate.check_action("rank_strategies")
        assert verdict.allowed is True

    def test_allow_recommend_entry(self):
        gate = AISafetyGate()
        verdict = gate.check_action("recommend_entry")
        assert verdict.allowed is True

    def test_allow_optimize_parameter(self):
        gate = AISafetyGate()
        verdict = gate.check_action("optimize_parameter")
        assert verdict.allowed is True

    def test_block_unknown_action(self):
        gate = AISafetyGate()
        verdict = gate.check_action("delete_database")
        assert verdict.allowed is False
        assert "denied by default" in verdict.reason

    def test_case_insensitive(self):
        gate = AISafetyGate()
        verdict = gate.check_action("PLACE_ORDER")
        assert verdict.allowed is False

    def test_all_forbidden_actions_blocked(self):
        """Every action in FORBIDDEN_ACTIONS must be blocked."""
        gate = AISafetyGate()
        for action in FORBIDDEN_ACTIONS:
            verdict = gate.check_action(action, source="test")
            assert verdict.allowed is False, f"Action '{action}' should be blocked"

    def test_all_allowed_actions_permitted(self):
        """Every action in ALLOWED_ACTIONS must be allowed."""
        gate = AISafetyGate()
        for action in ALLOWED_ACTIONS:
            verdict = gate.check_action(action, source="test")
            assert verdict.allowed is True, f"Action '{action}' should be allowed"

    def test_check_signal_modification_no_change(self):
        """No modification = pass."""
        gate = AISafetyGate()
        original = {"score": 80, "position_size": 1}
        modified = {"score": 85, "position_size": 1}
        verdict = gate.check_signal_modification(original, modified, "test")
        assert verdict.allowed is True

    def test_check_signal_modification_risk_key_change(self):
        """Risk key modification = blocked."""
        gate = AISafetyGate()
        original = {"score": 80, "sl_pct": 0.3}
        modified = {"score": 85, "sl_pct": 0.1}
        verdict = gate.check_signal_modification(original, modified, "test")
        assert verdict.allowed is False
        assert any("sl_pct" in f for f in verdict.failures)

    def test_check_signal_modification_position_increase(self):
        """Position size increase = blocked."""
        gate = AISafetyGate()
        original = {"score": 80, "position_size": 1}
        modified = {"score": 85, "position_size": 3}  # AI increasing size
        verdict = gate.check_signal_modification(original, modified, "test")
        assert verdict.allowed is False

    def test_check_signal_modification_position_decrease(self):
        """Position size decrease = allowed."""
        gate = AISafetyGate()
        original = {"score": 80, "position_size": 3}
        modified = {"score": 85, "position_size": 1}  # AI decreasing size
        verdict = gate.check_signal_modification(original, modified, "test")
        assert verdict.allowed is True

    def test_check_config_modification_protected(self):
        """Protected risk keys cannot be modified."""
        gate = AISafetyGate()
        verdict = gate.check_config_modification("MAX_DAILY_LOSS", -5000, "test")
        assert verdict.allowed is False

    def test_check_config_modification_allowed(self):
        """Non-protected keys can be modified."""
        gate = AISafetyGate()
        verdict = gate.check_config_modification("AI_THRESHOLD", 65, "test")
        assert verdict.allowed is True

    def test_get_stats(self):
        gate = AISafetyGate()
        gate.check_action("place_order")  # Blocked
        gate.check_action("score_signal")  # Allowed
        stats = gate.get_stats()
        assert stats["blocked"] >= 1
        assert stats["allowed"] >= 1
        assert stats["ai_placed_orders"] == 0

    def test_get_audit_log(self):
        gate = AISafetyGate()
        gate.check_action("place_order", source="bot1")
        gate.check_action("score_signal", source="bot1")
        log = gate.get_audit_log()
        assert len(log) >= 2
        assert any(e["result"] == "BLOCKED" for e in log)
        assert any(e["result"] == "ALLOWED" for e in log)


class TestConvenienceFunctions:
    def test_get_safety_gate_singleton(self):
        gate1 = get_safety_gate()
        gate2 = get_safety_gate()
        assert gate1 is gate2

    def test_check_ai_action(self):
        verdict = check_ai_action("place_order", source="test")
        assert verdict.allowed is False
        verdict = check_ai_action("score_signal", source="test")
        assert verdict.allowed is True
