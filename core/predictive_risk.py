import logging
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd


@dataclass
class RiskBudget:
    multiplier: float
    expected_var: float
    confidence_level: float
    recommendation: str

class PredictiveRiskEngine:
    """
    Uses Monte Carlo simulations to predict potential drawdowns
    and adjust the weekly risk budget accordingly.
    """
    def __init__(self, cfg: dict[str, Any], db_path: str):
        self.cfg = cfg
        self.db_path = db_path
        self.logger = logging.getLogger(__name__)
        self.simulations = int(cfg.get("monte_carlo_sims", 10000))
        self.confidence = float(cfg.get("var_confidence_level", 0.95))

    def get_historical_pnl_dist(self) -> list[float]:
        """Fetches all completed trade PnLs from the database."""
        try:
            import sqlite3
            conn = sqlite3.connect(self.db_path)
            df = pd.read_sql_query("SELECT net_pnl FROM trades WHERE net_pnl IS NOT NULL", conn)
            conn.close()
            return df['net_pnl'].tolist()
        except Exception as e:
            self.logger.error(f"Failed to fetch PnL history: {e}")
            return []

    def simulate_weekly_drawdown(self, trades_per_week: int = 10) -> RiskBudget:
        """
        Runs Monte Carlo simulations to estimate the 95% Value at Risk (VaR)
        for the coming week.
        """
        pnls = self.get_historical_pnl_dist()
        if len(pnls) <<  20:
            return RiskBudget(1.0, 0.0, 0.0, "Insufficient history for MC simulation. Using default risk.")

        # Simulate 10,000 weeks of trading
        weekly_outcomes = []
        for _ in range(self.simulations):
            # Randomly sample 'trades_per_week' from history
            sample = np.random.choice(pnls, size=trades_per_week, replace=True)
            weekly_outcomes.append(sum(sample))

        # Calculate Value at Risk (VaR) - the 5th percentile of outcomes
        var_95 = np.percentile(weekly_outcomes, (1 - self.confidence) * 100)

        # Determine budget multiplier
        # Logic: If the 95% worst-case week exceeds 10% of current capital, scale down
        # This requires the current capital, which we'll pass during the call or get from cfg
        # For the standalone engine, we return the raw VaR and let the trader decide the multiplier
        return RiskBudget(
            multiplier=1.0, # Placeholder, calculated in trader loop
            expected_var=var_95,
            confidence_level=self.confidence,
            recommendation=f"95% Weekly VaR is ₹{round(var_95, 2)}"
        )

    def calculate_multiplier(self, var: float, current_capital: float) -> float:
        """Converts VaR into a risk multiplier."""
        if current_capital <= 0: return 1.0

        drawdown_pct = abs(var) / current_capital
        if drawdown_pct > 0.15: return 0.2  # Extreme risk: scale to 20%
        if drawdown_pct > 0.10: return 0.5  # High risk: scale to 50%
        if drawdown_pct > 0.05: return 0.8  # Moderate risk: scale to 80%
        return 1.0
