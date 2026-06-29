"""AD-KIYU Portfolio Authority - single portfolio engine."""
from __future__ import annotations

import logging
import threading
from typing import Any

from core.domains.portfolio.service import PortfolioDataService

__all__ = [
    "PortfolioAuthority",
]

_log = logging.getLogger(__name__)


class PortfolioAuthority:
    """Single authoritative portfolio engine - exposure, capital, margin, budgets."""

    def __init__(self, data_service: PortfolioDataService | None = None):
        self._lock = threading.RLock()
        self._data = data_service or PortfolioDataService()
        self._correlation_limits: dict[str, float] = {}
        self._max_gross_exposure: float = 1_000_000.0

    def get_exposures(self) -> dict[str, Any]:
        return self._data.get_exposures()

    def get_margin(self) -> dict[str, Any]:
        return self._data.get_margin_requirements()

    def get_strategy_budgets(self) -> dict[str, Any]:
        return self._data.get_strategy_budgets()

    def set_strategy_budget(self, strategy_id: str, capital: float, **kwargs) -> None:
        self._data.set_strategy_budget(strategy_id, capital, **kwargs)
        _log.info(f"[PORTFOLIO] Budget set for {strategy_id}: {capital}")

    def total_exposure(self) -> float:
        return self._data.total_exposure()

    def net_exposure(self) -> float:
        return self._data.net_exposure()

    def set_correlation_limit(self, pair: str, max_r: float) -> None:
        with self._lock:
            self._correlation_limits[pair] = max_r

    def set_max_gross_exposure(self, limit: float) -> None:
        with self._lock:
            self._max_gross_exposure = limit

    def can_enter_trade(self, estimated_cost: float) -> tuple[bool, str]:
        total = self.total_exposure()
        if total + estimated_cost > self._max_gross_exposure:
            return False, f"exposure {total + estimated_cost:.0f} > limit {self._max_gross_exposure:.0f}"
        return True, "ok"
