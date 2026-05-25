"""Tests for core/rl_exit_optimizer.py — Q-learning exit timing optimizer."""

from __future__ import annotations

from core.rl_exit_optimizer import RLAction, RLExitOptimizer


class TestInit:
    def test_empty_q_table(self) -> None:
        opt = RLExitOptimizer({}, ":memory:")
        assert opt.q_table == {}

    def test_custom_learning_rate(self) -> None:
        opt = RLExitOptimizer({"rl_learning_rate": 0.5}, ":memory:")
        assert opt.learning_rate == 0.5

    def test_default_discount_factor(self) -> None:
        opt = RLExitOptimizer({}, ":memory:")
        assert opt.discount_factor == 0.95


class TestGetStateKey:
    def test_young_trade(self) -> None:
        opt = RLExitOptimizer({}, ":memory:")
        key = opt._get_state_key({"age_min": 5, "pnl_pct": 2.5, "vol_ratio": 0.7})
        # age=0 (5//15), pnl=2 (int(2.5//1)*1), vol='L' (<0.8)
        assert "a0" in key
        assert "p2" in key
        assert "vL" in key

    def test_older_trade(self) -> None:
        opt = RLExitOptimizer({}, ":memory:")
        key = opt._get_state_key({"age_min": 45, "pnl_pct": -3.2, "vol_ratio": 1.1})
        # age=3 (45//15), pnl=-4 (floor division: -3.2//1 = -4.0), vol='M'
        assert "a3" in key
        assert "p-4" in key
        assert "vM" in key

    def test_high_volatility(self) -> None:
        opt = RLExitOptimizer({}, ":memory:")
        key = opt._get_state_key({"age_min": 10, "pnl_pct": 0.5, "vol_ratio": 1.5})
        assert "vH" in key


class TestPredictAction:
    def test_no_q_table_defaults_to_hold(self) -> None:
        opt = RLExitOptimizer({}, ":memory:")
        action = opt.predict_action({"age_min": 10, "pnl_pct": 1.0, "vol_ratio": 1.0})
        assert action.action == "HOLD"
        assert 0 <= action.confidence <= 1.0

    def test_exit_when_greater_value(self) -> None:
        opt = RLExitOptimizer({}, ":memory:")
        # Manually set a state where EXIT > HOLD
        key = opt._get_state_key({"age_min": 10, "pnl_pct": 1.0, "vol_ratio": 1.0})
        opt.q_table[key] = {"HOLD": 0.0, "EXIT": 1.0}
        action = opt.predict_action({"age_min": 10, "pnl_pct": 1.0, "vol_ratio": 1.0})
        assert action.action == "EXIT"

    def test_hold_when_greater_value(self) -> None:
        opt = RLExitOptimizer({}, ":memory:")
        key = opt._get_state_key({"age_min": 10, "pnl_pct": 1.0, "vol_ratio": 1.0})
        opt.q_table[key] = {"HOLD": 2.0, "EXIT": -1.0}
        action = opt.predict_action({"age_min": 10, "pnl_pct": 1.0, "vol_ratio": 1.0})
        assert action.action == "HOLD"

    def test_expected_reward_is_max(self) -> None:
        opt = RLExitOptimizer({}, ":memory:")
        key = opt._get_state_key({"age_min": 10, "pnl_pct": 1.0, "vol_ratio": 1.0})
        opt.q_table[key] = {"HOLD": 3.0, "EXIT": 1.0}
        action = opt.predict_action({"age_min": 10, "pnl_pct": 1.0, "vol_ratio": 1.0})
        assert action.expected_reward == 3.0

    def test_different_state_uses_different_q(self) -> None:
        opt = RLExitOptimizer({}, ":memory:")
        opt.q_table["a0_p1_vL"] = {"HOLD": 0.0, "EXIT": 5.0}
        opt.q_table["a1_p1_vL"] = {"HOLD": 5.0, "EXIT": 0.0}
        action = opt.predict_action({"age_min": 5, "pnl_pct": 1.0, "vol_ratio": 0.7})  # a0_p1_vL
        assert action.action == "EXIT"


class TestUpdateQTable:
    def test_creates_state_entries(self) -> None:
        opt = RLExitOptimizer({}, ":memory:")
        opt.update_q_table("s1", "HOLD", 1.0, "s2")
        assert "s1" in opt.q_table
        assert "s2" in opt.q_table
        assert "HOLD" in opt.q_table["s1"]
        assert "EXIT" in opt.q_table["s1"]

    def test_updates_q_value(self) -> None:
        opt = RLExitOptimizer({}, ":memory:")
        opt.update_q_table("s1", "HOLD", 1.0, "s2")
        assert opt.q_table["s1"]["HOLD"] != 0.0

    def test_repeated_updates(self) -> None:
        opt = RLExitOptimizer({}, ":memory:")
        opt.update_q_table("s1", "HOLD", 1.0, "s2")
        val1 = opt.q_table["s1"]["HOLD"]
        opt.update_q_table("s1", "HOLD", -1.0, "s2")
        val2 = opt.q_table["s1"]["HOLD"]
        assert val2 != val1  # Value changed after update


class TestRLAction:
    def test_dataclass(self) -> None:
        a = RLAction(action="EXIT", confidence=0.85, expected_reward=10.0)
        assert a.action == "EXIT"
        assert a.confidence == 0.85
        assert a.expected_reward == 10.0
