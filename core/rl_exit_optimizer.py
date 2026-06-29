import logging
import os
from dataclasses import dataclass
from typing import Any

__all__ = [
    "RLAction",
    "RLExitOptimizer",
]

@dataclass
class RLAction:
    action: str  # "HOLD" or "EXIT"
    confidence: float
    expected_reward: float

class RLExitOptimizer:
    """
    Sovereign Local Reinforcement Learning agent for exit timing.
    Uses a Q-Learning approach to maximize realized PnL.
    """
    def __init__(self, cfg: dict[str, Any], db_path: str):
        self.cfg = cfg
        self.db_path = db_path
        self.logger = logging.getLogger(__name__)
        self.q_table = {} # state -> action_values { "HOLD": val, "EXIT": val }
        self.learning_rate = float(cfg.get("rl_learning_rate", 0.1))
        self.discount_factor = float(cfg.get("rl_discount_factor", 0.95))
        self._load_q_table()

    def _get_state_key(self, trade_data: dict) -> str:
        """Discretizes continuous trade data into a state key."""
        # Age in 15m buckets
        age = int(trade_data['age_min'] // 15)
        # PnL in 1% buckets
        pnl = int((trade_data['pnl_pct'] // 1) * 1)
        # Volatility in 3 buckets (Low, Med, High)
        vol = "L" if trade_data['vol_ratio'] < 0.8 else "M" if trade_data['vol_ratio'] < 1.2 else "H"
        return f"a{age}_p{pnl}_v{vol}"

    def predict_action(self, trade_data: dict) -> RLAction:
        """Predicts whether to hold or exit based on the learned Q-table."""
        state = self._get_state_key(trade_data)
        values = self.q_table.get(state, {"HOLD": 0.0, "EXIT": 0.0})

        hold_val = values["HOLD"]
        exit_val = values["EXIT"]

        action = "EXIT" if exit_val > hold_val else "HOLD"
        confidence = abs(exit_val - hold_val) / (abs(exit_val) + abs(hold_val) + 1e-6)

        return RLAction(action=action, confidence=confidence, expected_reward=max(hold_val, exit_val))

    def update_q_table(self, state: str, action: str, reward: float, next_state: str):
        """Performs a Q-Learning update based on trade outcome."""
        if state not in self.q_table: self.q_table[state] = {"HOLD": 0.0, "EXIT": 0.0}
        if next_state not in self.q_table: self.q_table[next_state] = {"HOLD": 0.0, "EXIT": 0.0}

        max_next_q = max(self.q_table[next_state].values())
        current_q = self.q_table[state][action]

        # Q-Learning Formula: Q(s,a) = Q(s,a) + alpha * (reward + gamma * max(Q(s',a')) - Q(s,a))
        new_q = current_q + self.learning_rate * (reward + self.discount_factor * max_next_q - current_q)
        self.q_table[state][action] = new_q

    def _load_q_table(self):
        """Loads saved weights from disk."""
        try:
            import joblib
            if os.path.exists("models/rl_exit_qtable.joblib"):
                self.q_table = joblib.load("models/rl_exit_qtable.joblib")
        except Exception as e:
            self.logger.error(f"RL Q-Table load failed: {e} (type: {type(e).__name__})")

    def save_q_table(self):
        """Saves learned weights to disk."""
        try:
            import joblib
            os.makedirs("models", exist_ok=True)
            joblib.dump(self.q_table, "models/rl_exit_qtable.joblib")
        except Exception as e:
            self.logger.error(f"RL Q-Table save failed: {e} (type: {type(e).__name__})")
