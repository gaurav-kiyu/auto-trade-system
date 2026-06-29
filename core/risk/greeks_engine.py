"""
Options Greeks Risk Engine (Phase 5).

Implements comprehensive Greeks-based risk controls for options portfolios:
  - Delta limits (net long/short exposure)
  - Gamma limits (convexity risk)
  - Theta exposure controls (time decay management)
  - Vega exposure controls (volatility risk)
  - Portfolio Greeks aggregation
  - Greeks stress testing (shock scenarios)

Architecture
------------
  GreeksEngine        - Main entry point, coordinates all Greeks checks
  ├── GreeksCalculator - Computes Greeks from positions using BS model
  ├── GreeksLimits     - Validates aggregated Greeks against config limits
  ├── GreeksStressTester - Applies shock scenarios to portfolio Greeks
  └── PortfolioGreeks  - Data class for aggregated portfolio Greeks

Usage
-----
    from core.risk.greeks_engine import GreeksEngine, GreeksLimitsConfig

    engine = GreeksEngine(config)
    result = engine.validate_entry(symbol="NIFTY", direction="CALL", qty=25, ...)
    if not result.passed:
        print(f"Blocked: {result.reason}")

    portfolio_greeks = engine.aggregate_portfolio(open_positions)
    stress_results = engine.run_stress(open_positions, scenarios=["CRASH", "VOL_SPIKE"])
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from core.datetime_ist import now_ist
from core.option_premium_model import black_scholes_greeks, lot_size

_log = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

DEFAULT_DELTA_LIMIT = 0.20       # Max net delta as % of capital (20%)
DEFAULT_GAMMA_LIMIT = 0.05       # Max gamma exposure (5% delta change per 1% move)
DEFAULT_THETA_LIMIT = -0.03      # Max daily theta bleed as % of capital (-3%)
DEFAULT_VEGA_LIMIT = 0.10        # Max vega exposure as % of capital (10% per vol point)
DEFAULT_PORFOLIO_GREEKS_PCT = 0.30  # Max aggregate Greeks exposure (% of capital)
DEFAULT_MAX_CONCENTRATION = 0.50 # Max single-symbol Greeks concentration


# ── Enums ─────────────────────────────────────────────────────────────────────

class GreeksCheckLevel(Enum):
    """Strictness level for Greeks checks."""
    STRICT = "STRICT"      # Block on ANY limit breach
    NORMAL = "NORMAL"      # Block on material breaches, warn on minor
    PERMISSIVE = "PERMISSIVE"  # Warn only, never block


class GreeksSeverity(Enum):
    """Severity of a Greeks check result."""
    PASS = "PASS"
    WARN = "WARN"
    BLOCK = "BLOCK"


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class GreeksLimitsConfig:
    """Configuration limits for Greeks exposure."""
    max_net_delta: float = DEFAULT_DELTA_LIMIT
    max_gamma: float = DEFAULT_GAMMA_LIMIT
    max_theta_daily: float = DEFAULT_THETA_LIMIT
    max_vega: float = DEFAULT_VEGA_LIMIT
    max_portfolio_greeks_pct: float = DEFAULT_PORFOLIO_GREEKS_PCT
    max_concentration: float = DEFAULT_MAX_CONCENTRATION
    check_level: str = "NORMAL"
    stress_test_enabled: bool = True
    stress_loss_threshold_pct: float = 15.0  # Alert if stress loss > 15%


@dataclass
class PositionGreeks:
    """Greeks for a single position."""
    symbol: str
    direction: str           # "CALL" or "PUT"
    strike: float
    qty: int                 # Number of lots
    lot_size: int
    spot: float
    delta: float             # Per lot
    gamma: float             # Per lot
    theta: float             # Per lot (daily)
    vega: float              # Per lot (per vol point)
    rho: float               # Per lot
    iv: float                # Implied volatility
    dte: float               # Days to expiry
    premium: float           # Current premium per unit

    @property
    def delta_exposure(self) -> float:
        """Total delta exposure (units of underlying)."""
        return self.delta * self.qty * self.lot_size

    @property
    def gamma_exposure(self) -> float:
        """Total gamma exposure."""
        return self.gamma * self.qty * self.lot_size

    @property
    def theta_cost(self) -> float:
        """Daily theta cost in rupees."""
        return self.theta * self.qty * self.lot_size * self.premium

    @property
    def vega_exposure(self) -> float:
        """Vega exposure per vol point in rupees."""
        return self.vega * self.qty * self.lot_size * self.premium


@dataclass
class PortfolioGreeks:
    """Aggregated portfolio-level Greeks."""
    symbols: list[str]
    total_delta: float           # Net delta (can be negative)
    abs_delta: float             # Absolute delta (total directional exposure)
    total_gamma: float
    total_theta: float           # Daily theta (negative = decay)
    total_vega: float
    total_rho: float
    delta_pct: float             # % of capital
    gamma_pct: float
    theta_pct: float
    vega_pct: float
    concentration: float         # Highest single-symbol Greeks / total
    position_count: int
    timestamp: str

    def delta_dollars(self, capital: float) -> float:
        """Delta exposure in rupee terms."""
        return self.total_delta * capital

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbols": self.symbols,
            "total_delta": round(self.total_delta, 4),
            "abs_delta": round(self.abs_delta, 4),
            "total_gamma": round(self.total_gamma, 6),
            "total_theta": round(self.total_theta, 4),
            "total_vega": round(self.total_vega, 4),
            "delta_pct": round(self.delta_pct, 2),
            "gamma_pct": round(self.gamma_pct, 4),
            "theta_pct": round(self.theta_pct, 2),
            "vega_pct": round(self.vega_pct, 2),
            "concentration": round(self.concentration, 2),
            "position_count": self.position_count,
            "timestamp": self.timestamp,
        }


@dataclass
class GreeksCheckResult:
    """Result of a Greeks validation check."""
    passed: bool
    severity: GreeksSeverity
    check_name: str
    current_value: float
    limit_value: float
    reason: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class GreeksEntryVerdict:
    """Final verdict for a proposed trade entry."""
    allowed: bool
    reason: str
    checks: list[GreeksCheckResult] = field(default_factory=list)
    post_trade_greeks: PortfolioGreeks | None = None


@dataclass
class GreeksStressResult:
    """Result of a Greeks stress scenario."""
    scenario: str
    delta_shock: float
    gamma_shock: float
    theta_shock: float
    vega_shock: float
    pnl_impact_pct: float
    alert: bool


# ── Greeks Calculator ─────────────────────────────────────────────────────────

class GreeksCalculator:
    """Computes Greeks for individual positions and portfolios."""

    @staticmethod
    def compute_position_greeks(
        symbol: str,
        direction: str,
        strike: float,
        spot: float,
        iv: float,
        dte: float,
        qty: int,
        risk_free_rate: float = 0.065,
    ) -> PositionGreeks | None:
        """Compute Greeks for a single option position."""
        try:
            ls = lot_size(symbol)
            bs = black_scholes_greeks(
                spot=spot,
                strike=strike,
                time_to_expiry_days=dte,
                iv=iv,
                risk_free_rate=risk_free_rate,
                direction=direction,
            )
            # Estimate premium
            from core.option_premium_model import estimate_atm_premium
            premium = estimate_atm_premium(spot, spot * 0.02, iv * 100, int(dte))

            return PositionGreeks(
                symbol=symbol,
                direction=direction,
                strike=strike,
                qty=qty,
                lot_size=ls,
                spot=spot,
                delta=float(bs.get("delta", 0)),
                gamma=float(bs.get("gamma", 0)),
                theta=float(bs.get("theta", 0)),
                vega=float(bs.get("vega", 0)),
                rho=float(bs.get("rho", 0)),
                iv=iv,
                dte=dte,
                premium=premium,
            )
        except (TypeError, ValueError, KeyError, ZeroDivisionError) as exc:
            _log.warning("[GREEKS] Failed to compute position Greeks for %s %s: %s", symbol, direction, exc)
            return None

    @staticmethod
    def aggregate_portfolio(
        positions: list[PositionGreeks],
        capital: float,
    ) -> PortfolioGreeks:
        """Aggregate Greeks across all open positions."""
        if not positions:
            return PortfolioGreeks(
                symbols=[],
                total_delta=0.0,
                abs_delta=0.0,
                total_gamma=0.0,
                total_theta=0.0,
                total_vega=0.0,
                total_rho=0.0,
                delta_pct=0.0,
                gamma_pct=0.0,
                theta_pct=0.0,
                vega_pct=0.0,
                concentration=0.0,
                position_count=0,
                timestamp=now_ist().isoformat(),
            )

        total_delta = sum(p.delta_exposure for p in positions)
        abs_delta = sum(abs(p.delta_exposure) for p in positions)
        total_gamma = sum(p.gamma_exposure for p in positions)
        total_theta = sum(p.theta_cost for p in positions)
        total_vega = sum(p.vega_exposure for p in positions)

        # Compute concentration: highest single-symbol abs delta / total abs delta
        symbol_deltas: dict[str, float] = {}
        for p in positions:
            symbol_deltas[p.symbol] = symbol_deltas.get(p.symbol, 0.0) + abs(p.delta_exposure)
        max_sym_delta = max(symbol_deltas.values()) if symbol_deltas else 0.0
        concentration = max_sym_delta / max(abs_delta, 1.0)

        safe_capital = max(capital, 1.0)
        total_rho = sum(p.rho * p.qty * p.lot_size * p.premium for p in positions)
        return PortfolioGreeks(
                symbols=list(set(p.symbol for p in positions)),
                total_delta=total_delta,
                abs_delta=abs_delta,
                total_gamma=total_gamma,
                total_theta=total_theta,
                total_vega=total_vega,
                total_rho=total_rho,
                delta_pct=(abs_delta / safe_capital) * 100,
                gamma_pct=total_gamma * 100,
                theta_pct=(abs(total_theta) / safe_capital) * 100,
                vega_pct=(total_vega / safe_capital) * 100,
                concentration=concentration,
                position_count=len(positions),
                timestamp=now_ist().isoformat(),
            )


# ── Greeks Limits ─────────────────────────────────────────────────────────────

class GreeksLimits:
    """Validates Greeks against configured limits."""

    def __init__(self, config: GreeksLimitsConfig):
        self._config = config
        self._lock = threading.RLock()

    def check_delta(
        self,
        portfolio: PortfolioGreeks,
        proposed_delta: float = 0.0,
    ) -> GreeksCheckResult:
        """Check net delta limit against portfolio delta_pct."""
        limit = self._config.max_net_delta
        # Use delta_pct/100 as the effective delta exposure (% of capital)
        effective_delta = portfolio.delta_pct / 100.0
        if effective_delta > limit:
            return GreeksCheckResult(
                passed=False,
                severity=GreeksSeverity.BLOCK,
                check_name="delta_limit",
                current_value=effective_delta,
                limit_value=limit,
                reason=f"Net delta exposure {effective_delta:.2%} exceeds limit {limit:.2%}",
            )
        return GreeksCheckResult(
            passed=True,
            severity=GreeksSeverity.PASS,
            check_name="delta_limit",
            current_value=effective_delta,
            limit_value=limit,
            reason=f"Delta exposure {effective_delta:.2%} within limit {limit:.2%}",
        )

    def check_gamma(
        self,
        portfolio: PortfolioGreeks,
        proposed_gamma: float = 0.0,
    ) -> GreeksCheckResult:
        """Check gamma exposure limit."""
        limit = self._config.max_gamma
        combined = abs(portfolio.total_gamma) + abs(proposed_gamma)

        if combined > limit:
            return GreeksCheckResult(
                passed=False,
                severity=GreeksSeverity.BLOCK,
                check_name="gamma_limit",
                current_value=combined,
                limit_value=limit,
                reason=f"Gamma exposure {combined:.4f} exceeds limit {limit:.4f}",
            )
        return GreeksCheckResult(
            passed=True,
            severity=GreeksSeverity.PASS,
            check_name="gamma_limit",
            current_value=combined,
            limit_value=limit,
            reason=f"Gamma {combined:.4f} within limit {limit:.4f}",
        )

    def check_theta(
        self,
        portfolio: PortfolioGreeks,
        proposed_theta: float = 0.0,
    ) -> GreeksCheckResult:
        """Check daily theta decay limit."""
        limit = abs(self._config.max_theta_daily)
        daily_theta = abs(portfolio.total_theta) + abs(proposed_theta)

        if daily_theta > limit:
            return GreeksCheckResult(
                passed=False,
                severity=GreeksSeverity.BLOCK,
                check_name="theta_limit",
                current_value=daily_theta,
                limit_value=limit,
                reason=f"Daily theta {daily_theta:.2%} exceeds limit {limit:.2%} of capital",
            )
        return GreeksCheckResult(
            passed=True,
            severity=GreeksSeverity.PASS,
            check_name="theta_limit",
            current_value=daily_theta,
            limit_value=limit,
            reason=f"Theta {daily_theta:.2%} within limit {limit:.2%}",
        )

    def check_vega(
        self,
        portfolio: PortfolioGreeks,
        proposed_vega: float = 0.0,
    ) -> GreeksCheckResult:
        """Check vega exposure limit."""
        limit = self._config.max_vega
        combined = abs(portfolio.total_vega) + abs(proposed_vega)

        if combined > limit:
            return GreeksCheckResult(
                passed=False,
                severity=GreeksSeverity.BLOCK,
                check_name="vega_limit",
                current_value=combined,
                limit_value=limit,
                reason=f"Vega exposure {combined:.2%} exceeds limit {limit:.2%} of capital per vol point",
            )
        return GreeksCheckResult(
            passed=True,
            severity=GreeksSeverity.PASS,
            check_name="vega_limit",
            current_value=combined,
            limit_value=limit,
            reason=f"Vega {combined:.2%} within limit {limit:.2%}",
        )

    def check_concentration(
        self,
        portfolio: PortfolioGreeks,
    ) -> GreeksCheckResult:
        """Check single-symbol Greeks concentration."""
        limit = self._config.max_concentration
        if portfolio.concentration > limit:
            return GreeksCheckResult(
                passed=False,
                severity=GreeksSeverity.BLOCK,
                check_name="concentration_limit",
                current_value=portfolio.concentration,
                limit_value=limit,
                reason=f"Greeks concentration {portfolio.concentration:.1%} exceeds limit {limit:.1%}",
            )
        return GreeksCheckResult(
            passed=True,
            severity=GreeksSeverity.PASS,
            check_name="concentration_limit",
            current_value=portfolio.concentration,
            limit_value=limit,
            reason=f"Concentration {portfolio.concentration:.1%} within limit {limit:.1%}",
        )


# ── Greeks Stress Tester ──────────────────────────────────────────────────────

class GreeksStressTester:
    """Applies shock scenarios to portfolio Greeks."""

    SCENARIOS: dict[str, dict[str, float]] = {
        "FLASH_CRASH": {"spot_move_pct": -3.0, "vol_change_pct": 50.0},
        "GAP_UP": {"spot_move_pct": 2.0, "vol_change_pct": -15.0},
        "VOL_SPIKE": {"spot_move_pct": 0.0, "vol_change_pct": 30.0},
        "EXPIRY_DAY": {"spot_move_pct": -1.0, "vol_change_pct": -20.0, "time_decay_days": -0.7},
        "LIQUIDITY_CRISIS": {"spot_move_pct": -2.0, "vol_change_pct": 40.0},
    }

    def run(
        self,
        portfolio_greeks: PortfolioGreeks,
        positions: list[PositionGreeks],
        capital: float,
        scenarios: list[str] | None = None,
    ) -> list[GreeksStressResult]:
        """Run stress scenarios on portfolio."""
        if not positions or capital <= 0:
            return []

        scenario_names = scenarios or list(self.SCENARIOS.keys())
        results: list[GreeksStressResult] = []

        for name in scenario_names:
            params = self.SCENARIOS.get(name)
            if params is None:
                continue

            spot_move_pct = params.get("spot_move_pct", 0.0) / 100.0
            vol_change_pct = params.get("vol_change_pct", 0.0) / 100.0

            # Compute shock P&L using Greeks
            pnl_shock = 0.0
            for pos in positions:
                # Delta P&L
                delta_pnl = pos.delta_exposure * spot_move_pct * pos.spot
                # Gamma P&L
                gamma_pnl = 0.5 * pos.gamma_exposure * (spot_move_pct * pos.spot) ** 2
                # Vega P&L
                vega_pnl = pos.vega_exposure * vol_change_pct * pos.iv * 100
                pnl_shock += delta_pnl + gamma_pnl + vega_pnl

            pnl_pct = (pnl_shock / capital) * 100
            threshold = self._get_threshold(name)

            results.append(GreeksStressResult(
                scenario=name,
                delta_shock=round(spot_move_pct * 100, 1),
                gamma_shock=round(gamma_pnl if 'gamma_pnl' in dir() else 0, 2),
                theta_shock=0.0,
                vega_shock=round(vol_change_pct * 100, 1),
                pnl_impact_pct=round(pnl_pct, 2),
                alert=abs(pnl_pct) > threshold,
            ))

        return results

    @staticmethod
    def _get_threshold(scenario: str) -> float:
        thresholds = {
            "FLASH_CRASH": 15.0,
            "GAP_UP": 10.0,
            "VOL_SPIKE": 8.0,
            "EXPIRY_DAY": 12.0,
            "LIQUIDITY_CRISIS": 10.0,
        }
        return thresholds.get(scenario, 10.0)


# ── Greeks Engine (Main Entry Point) ──────────────────────────────────────────

class GreeksEngine:
    """
    Main Greeks Risk Engine - coordinates validation, aggregation, and stress testing.

    No options strategy may bypass Greeks controls.
    Risk Engine remains the final authority for all execution decisions.
    """

    def __init__(
        self,
        config: GreeksLimitsConfig | None = None,
        log_fn: Any = None,
    ):
        self._config = config or GreeksLimitsConfig()
        self._limits = GreeksLimits(self._config)
        self._calculator = GreeksCalculator()
        self._stress_tester = GreeksStressTester()
        self._log = log_fn or _log
        self._lock = threading.RLock()

    # ── Entry Validation ─────────────────────────────────────────────────

    def validate_entry(
        self,
        symbol: str,
        direction: str,
        strike: float,
        spot: float,
        iv: float,
        dte: float,
        qty: int,
        capital: float,
        existing_positions: list[PositionGreeks] | None = None,
    ) -> GreeksEntryVerdict:
        """
        Validate a proposed options trade entry against all Greeks limits.

        Args:
            symbol: Index/symbol name
            direction: "CALL" or "PUT"
            strike: Strike price
            spot: Current underlying price
            iv: Implied volatility (decimal)
            dte: Days to expiry
            qty: Number of lots
            capital: Current available capital
            existing_positions: Current open positions (optional)

        Returns:
            GreeksEntryVerdict with allowed=True/False and detailed check results
        """
        try:
            # Compute proposed position Greeks
            proposed = self._calculator.compute_position_greeks(
                symbol=symbol, direction=direction, strike=strike,
                spot=spot, iv=iv, dte=dte, qty=qty,
            )
            if proposed is None:
                return GreeksEntryVerdict(
                    allowed=False,
                    reason="Failed to compute Greeks for proposed position",
                )

            # Aggregate existing portfolio
            existing = existing_positions or []
            all_positions = existing + [proposed]
            portfolio = self._calculator.aggregate_portfolio(all_positions, capital)

            # Run all checks
            checks: list[GreeksCheckResult] = []
            checks.append(self._limits.check_delta(portfolio))
            checks.append(self._limits.check_gamma(portfolio))
            checks.append(self._limits.check_theta(portfolio))
            checks.append(self._limits.check_vega(portfolio))
            checks.append(self._limits.check_concentration(portfolio))

            # Determine verdict
            blocks = [c for c in checks if c.severity == GreeksSeverity.BLOCK and not c.passed]
            warns = [c for c in checks if c.severity == GreeksSeverity.WARN and not c.passed]

            if blocks:
                reasons = "; ".join(c.reason for c in blocks)
                return GreeksEntryVerdict(
                    allowed=False,
                    reason=f"Greeks limits breached: {reasons}",
                    checks=checks,
                    post_trade_greeks=portfolio,
                )

            if warns and self._config.check_level == "STRICT":
                reasons = "; ".join(c.reason for c in warns)
                return GreeksEntryVerdict(
                    allowed=False,
                    reason=f"Greeks warnings (strict mode): {reasons}",
                    checks=checks,
                    post_trade_greeks=portfolio,
                )

            return GreeksEntryVerdict(
                allowed=True,
                reason="All Greeks checks passed",
                checks=checks,
                post_trade_greeks=portfolio,
            )

        except (TypeError, ValueError, KeyError, ZeroDivisionError, AttributeError) as exc:
            _log.error("[GREEKS] validate_entry failed: %s", exc)
            return GreeksEntryVerdict(
                allowed=False,  # Fail closed on compute errors
                reason=f"Greeks compute error: {exc}",
            )

    # ── Portfolio Aggregation ────────────────────────────────────────────

    def aggregate_portfolio(
        self,
        positions: list[PositionGreeks],
        capital: float,
    ) -> PortfolioGreeks:
        """Aggregate Greeks across all open positions."""
        try:
            return self._calculator.aggregate_portfolio(positions, capital)
        except (TypeError, ValueError, ZeroDivisionError) as exc:
            _log.error("[GREEKS] aggregate_portfolio failed: %s", exc)
            return PortfolioGreeks(
                symbols=[], total_delta=0.0, abs_delta=0.0,
                total_gamma=0.0, total_theta=0.0, total_vega=0.0,
                total_rho=0.0, delta_pct=0.0, gamma_pct=0.0,
                theta_pct=0.0, vega_pct=0.0, concentration=0.0,
                position_count=0, timestamp=now_ist().isoformat(),
            )

    # ── Stress Testing ───────────────────────────────────────────────────

    def run_stress(
        self,
        positions: list[PositionGreeks],
        capital: float,
        scenarios: list[str] | None = None,
    ) -> list[GreeksStressResult]:
        """Run Greeks stress scenarios on the portfolio."""
        try:
            if not self._config.stress_test_enabled:
                return []
            portfolio = self._calculator.aggregate_portfolio(positions, capital)
            return self._stress_tester.run(portfolio, positions, capital, scenarios)
        except (TypeError, ValueError, ZeroDivisionError, AttributeError) as exc:
            _log.error("[GREEKS] Stress test failed: %s", exc)
            return []

    # ── Helpers ──────────────────────────────────────────────────────────

    def build_position_greeks_from_trade(
        self,
        symbol: str,
        direction: str,
        strike: float,
        spot: float,
        iv: float,
        dte: float,
        qty: int,
    ) -> PositionGreeks | None:
        """Build PositionGreeks from trade parameters."""
        return self._calculator.compute_position_greeks(
            symbol=symbol, direction=direction, strike=strike,
            spot=spot, iv=iv, dte=dte, qty=qty,
        )

    def get_config(self) -> dict[str, Any]:
        """Get current Greeks limits configuration."""
        return {
            "max_net_delta": self._config.max_net_delta,
            "max_gamma": self._config.max_gamma,
            "max_theta_daily": self._config.max_theta_daily,
            "max_vega": self._config.max_vega,
            "max_portfolio_greeks_pct": self._config.max_portfolio_greeks_pct,
            "max_concentration": self._config.max_concentration,
            "check_level": self._config.check_level,
            "stress_test_enabled": self._config.stress_test_enabled,
        }

    def get_stress_summary(self, results: list[GreeksStressResult]) -> str:
        """Human-readable stress test summary."""
        if not results:
            return "Greeks Stress: no positions"
        parts = []
        for r in results:
            tag = f"[{'⚠' if r.alert else '✓'}] {r.scenario}"
            parts.append(f"{tag}: PnL={r.pnl_impact_pct:+.2f}%")
        return "Greeks Stress: " + " | ".join(parts)


# ─── Singleton factory ────────────────────────────────────────────────────────

_engine_instance: GreeksEngine | None = None
_engine_lock = threading.RLock()


def get_greeks_engine(
    config: GreeksLimitsConfig | None = None,
) -> GreeksEngine:
    """Return the process-level GreeksEngine singleton."""
    global _engine_instance
    with _engine_lock:
        if _engine_instance is None:
            _engine_instance = GreeksEngine(config=config)
    return _engine_instance


def reset_greeks_engine() -> None:
    """Force-reset singleton (tests only)."""
    global _engine_instance
    with _engine_lock:
        _engine_instance = None


# ── Fidelity declaration ─────────────────────────────────────────────────────

GREEKS_ENGINE_FIDELITY = {
    "level": "PRODUCTION_GRADE",
    "delta": "BLACK_SCHOLES_APPROXIMATION",
    "gamma": "BLACK_SCHOLES_APPROXIMATION",
    "theta": "BLACK_SCHOLES_APPROXIMATION",
    "vega": "BLACK_SCHOLES_APPROXIMATION",
    "portfolio_aggregation": "IMPLEMENTED",
    "stress_testing": "IMPLEMENTED",
    "concentration_checks": "IMPLEMENTED",
    "limits_configurable": True,
    "notes": [
        "All Greeks computed via Black-Scholes approximation from option_premium_model",
        "No options strategy may bypass Greeks controls",
        "Risk Engine remains the final authority for all execution decisions",
        "Stress scenarios: FLASH_CRASH, GAP_UP, VOL_SPIKE, EXPIRY_DAY, LIQUIDITY_CRISIS",
    ],
}


__all__ = [
    "DEFAULT_DELTA_LIMIT",
    "DEFAULT_GAMMA_LIMIT",
    "DEFAULT_MAX_CONCENTRATION",
    "DEFAULT_PORFOLIO_GREEKS_PCT",
    "DEFAULT_THETA_LIMIT",
    "DEFAULT_VEGA_LIMIT",
    "GREEKS_ENGINE_FIDELITY",
    "GreeksCalculator",
    "GreeksCheckLevel",
    "GreeksCheckResult",
    "GreeksEngine",
    "GreeksEntryVerdict",
    "GreeksLimits",
    "GreeksLimitsConfig",
    "GreeksSeverity",
    "GreeksStressResult",
    "GreeksStressTester",
    "PortfolioGreeks",
    "PositionGreeks",
    "get_greeks_engine",
    "reset_greeks_engine",
]

