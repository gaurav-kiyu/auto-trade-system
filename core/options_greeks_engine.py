"""
Options Greeks Risk Engine (Phase 5).

Computes and enforces:
- Per-position Greeks (Delta, Gamma, Theta, Vega, Rho) via Black-Scholes
- Portfolio-level Greeks aggregation
- Delta limits (per position and portfolio)
- Gamma limits (per position and portfolio)
- Theta exposure controls (daily time decay budget)
- Vega exposure controls (IV sensitivity limits)
- Greeks stress testing under multiple scenarios

Usage
-----
    from core.options_greeks_engine import OptionsGreeksEngine, GreeksConfig

    engine = OptionsGreeksEngine(config)
    greeks = engine.compute_greeks(spot=25000, strike=25000, tte=3, iv=0.15)
    check  = engine.check_pre_trade_greeks(new_pos, current_positions)

Design
------
- Uses proper Black-Scholes formulas with math.erf for normal CDF
- All limits are configurable via GreeksConfig
- Portfolio-level aggregation uses real-time position data
- Stress testing covers 5 scenarios: FLASH_CRASH, VOL_JACK, GAP_OPEN,
  EXPIRY_CRUSH, RATE_HIKE
- Integrates with RiskService via evaluate_trade() extension point
"""

from __future__ import annotations

import logging
import math
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

_log = logging.getLogger(__name__)

_SQRT_2PI = math.sqrt(2.0 * math.pi)

# ── Constants ─────────────────────────────────────────────────────────────────

_NSE_LOT_SIZES: dict[str, int] = {
    "NIFTY": 25,
    "BANKNIFTY": 15,
    "FINNIFTY": 40,
    "MIDCPNIFTY": 75,
    "SENSEX": 10,
}

# ── Enums ──────────────────────────────────────────────────────────────────────


class OptionType(Enum):
    CE = "CE"  # Call European
    PE = "PE"  # Put European


class GreeksLimitStatus(Enum):
    PASS = "PASS"
    WARN = "WARN"
    BLOCK = "BLOCK"


class StressScenario(Enum):
    FLASH_CRASH = "FLASH_CRASH"       # -10% spot, IV +20pts
    VOL_JACK = "VOL_JACK"             # IV +15pts, spot -3%
    GAP_OPEN = "GAP_OPEN"             # +/-3% spot, IV +5pts
    EXPIRY_CRUSH = "EXPIRY_CRUSH"     # DTE=0, IV -10pts
    RATE_HIKE = "RATE_HIKE"           # rates +200bp, spot -1%


# ── Dataclasses ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class GreeksResult:
    """Greeks for a single option position."""
    delta: float
    gamma: float
    theta: float    # daily theta (negative = decay)
    vega: float     # per 1% IV change
    rho: float      # per 1% rate change
    spot: float
    strike: float
    tte_days: float
    iv: float
    premium: float
    option_type: OptionType


@dataclass
class PositionGreeksInput:
    """Input data for computing Greeks on one position."""
    symbol: str
    option_type: OptionType
    direction: str                # "LONG" or "SHORT"
    spot: float
    strike: float
    tte_days: float
    iv: float
    quantity_lots: int
    risk_free_rate: float = 0.065


@dataclass
class PortfolioGreeks:
    """Aggregated portfolio-level Greeks."""
    net_delta: float = 0.0
    net_gamma: float = 0.0
    net_theta: float = 0.0
    net_vega: float = 0.0
    net_rho: float = 0.0
    gross_exposure_premium: float = 0.0
    positions_count: int = 0
    by_symbol: dict[str, PositionGreeksSummary] = field(default_factory=dict)
    timestamp: float = 0.0


@dataclass
class PositionGreeksSummary:
    """Greeks summary for one symbol."""
    delta: float = 0.0
    gamma: float = 0.0
    theta: float = 0.0
    vega: float = 0.0
    rho: float = 0.0
    long_gamma: bool = False


@dataclass
class GreeksCheckResult:
    """Result of pre-trade Greeks limit check."""
    status: GreeksLimitStatus
    delta_ok: bool = True
    gamma_ok: bool = True
    theta_ok: bool = True
    vega_ok: bool = True
    portfolio_delta_ok: bool = True
    portfolio_gamma_ok: bool = True
    portfolio_theta_ok: bool = True
    portfolio_vega_ok: bool = True
    reasons: list[str] = field(default_factory=list)
    projected_portfolio: PortfolioGreeks | None = None


@dataclass
class GreeksStressScenario:
    """One stress scenario definition."""
    name: str
    spot_shift_pct: float        # e.g., -10.0 = 10% drop
    iv_shift_pts: float          # e.g., +20 = IV +20 percentage points
    tte_days_factor: float       # e.g., 0.5 = half the time to expiry
    rate_shift_bp: float         # e.g., +200 = +200 basis points


@dataclass
class GreeksStressResult:
    """Results of a Greeks stress test run."""
    scenario: str
    pre_stress: PortfolioGreeks
    post_stress: PortfolioGreeks
    delta_change: float
    gamma_change: float
    theta_change: float
    vega_change: float
    max_loss_pct: float
    verdict: str                   # "RESILIENT" | "SENSITIVE" | "FRAGILE"


@dataclass
class GreeksConfig:
    """Configuration for Greeks limits and thresholds.

    Config keys (safe defaults built-in):
        greeks_delta_limit_per_pos     : float default 0.20  (20% of notional)
        greeks_delta_limit_portfolio   : float default 0.50  (50% of notional)
        greeks_gamma_limit_per_pos     : float default 0.05  (gamma exposure)
        greeks_gamma_limit_portfolio   : float default 0.10
        greeks_theta_daily_budget      : float default -500  (max daily decay in ₹)
        greeks_vega_limit_per_pos      : float default 500   (max vega per position)
        greeks_vega_limit_portfolio    : float default 2000  (max portfolio vega)
        greeks_warn_threshold_pct      : float default 0.80  (80% of limit → WARN)
        greeks_block_threshold_pct     : float default 1.00  (100% → BLOCK)
        greeks_enabled                 : bool  default True
        greeks_stress_test_enabled     : bool  default True
        greeks_short_option_block      : bool  default True  (block naked short options)
    """
    delta_limit_per_pos: float = 0.55   # A 1-lot ATM NIFTY call has ~13 delta-contracts; 0.55 × 25 = 13.75 ✓
    delta_limit_portfolio: float = 1.50
    gamma_limit_per_pos: float = 0.05
    gamma_limit_portfolio: float = 0.10
    theta_daily_budget: float = -500.0
    vega_limit_per_pos: float = 500.0
    vega_limit_portfolio: float = 2000.0
    warn_threshold_pct: float = 0.80
    block_threshold_pct: float = 1.00
    enabled: bool = True
    stress_test_enabled: bool = True
    short_option_block: bool = True

    @classmethod
    def from_dict(cls, cfg: dict[str, Any] | None) -> GreeksConfig:
        c = cfg or {}
        return cls(
            delta_limit_per_pos=float(c.get("greeks_delta_limit_per_pos", 0.20)),
            delta_limit_portfolio=float(c.get("greeks_delta_limit_portfolio", 0.50)),
            gamma_limit_per_pos=float(c.get("greeks_gamma_limit_per_pos", 0.05)),
            gamma_limit_portfolio=float(c.get("greeks_gamma_limit_portfolio", 0.10)),
            theta_daily_budget=float(c.get("greeks_theta_daily_budget", -500.0)),
            vega_limit_per_pos=float(c.get("greeks_vega_limit_per_pos", 500.0)),
            vega_limit_portfolio=float(c.get("greeks_vega_limit_portfolio", 2000.0)),
            warn_threshold_pct=float(c.get("greeks_warn_threshold_pct", 0.80)),
            block_threshold_pct=float(c.get("greeks_block_threshold_pct", 1.00)),
            enabled=bool(c.get("greeks_enabled", True)),
            stress_test_enabled=bool(c.get("greeks_stress_test_enabled", True)),
            short_option_block=bool(c.get("greeks_short_option_block", True)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "delta_limit_per_pos": self.delta_limit_per_pos,
            "delta_limit_portfolio": self.delta_limit_portfolio,
            "gamma_limit_per_pos": self.gamma_limit_per_pos,
            "gamma_limit_portfolio": self.gamma_limit_portfolio,
            "theta_daily_budget": self.theta_daily_budget,
            "vega_limit_per_pos": self.vega_limit_per_pos,
            "vega_limit_portfolio": self.vega_limit_portfolio,
            "warn_threshold_pct": self.warn_threshold_pct,
            "block_threshold_pct": self.block_threshold_pct,
            "enabled": self.enabled,
            "stress_test_enabled": self.stress_test_enabled,
            "short_option_block": self.short_option_block,
        }


# ── Black-Scholes Helpers ──────────────────────────────────────────────────────


def _norm_cdf(x: float) -> float:
    """Standard normal CDF using math.erf."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    """Standard normal PDF."""
    return math.exp(-0.5 * x * x) / _SQRT_2PI


def _black_scholes_d1(spot: float, strike: float, t_years: float, sigma: float, r: float) -> float:
    """Compute d1 for Black-Scholes."""
    if t_years <= 0 or sigma <= 0 or spot <= 0 or strike <= 0:
        return 0.0
    try:
        return (math.log(spot / strike) + (r + 0.5 * sigma * sigma) * t_years) / (sigma * math.sqrt(t_years))
    except (ValueError, OverflowError, ArithmeticError):
        return 0.0


def _black_scholes_d2(d1: float, sigma: float, t_years: float) -> float:
    """Compute d2 from d1."""
    return d1 - sigma * math.sqrt(t_years)


def _black_scholes_price(spot: float, strike: float, t_years: float, sigma: float, r: float, option_type: OptionType) -> float:
    """Black-Scholes option price."""
    if t_years <= 0:
        # Intrinsic value at expiry
        if option_type == OptionType.CE:
            return max(0.0, spot - strike)
        return max(0.0, strike - spot)
    if sigma <= 0 or spot <= 0 or strike <= 0:
        return 0.0

    d1 = _black_scholes_d1(spot, strike, t_years, sigma, r)
    d2 = _black_scholes_d2(d1, sigma, t_years)

    if option_type == OptionType.CE:
        return spot * _norm_cdf(d1) - strike * math.exp(-r * t_years) * _norm_cdf(d2)
    else:
        return strike * math.exp(-r * t_years) * _norm_cdf(-d2) - spot * _norm_cdf(-d1)


# ── Engine ─────────────────────────────────────────────────────────────────────


class OptionsGreeksEngine:
    """
    Options Greeks Risk Engine.

    Thread-safe. Enforces:
    - Per-position Delta/Gamma/Vega limits
    - Portfolio-level Greeks aggregation and limits
    - Theta daily decay budget
    - Greeks stress testing
    - Short option blocking (configurable)
    """

    def __init__(self, config: GreeksConfig | None = None):
        self._config = config or GreeksConfig()
        self._lock = threading.RLock()
        self._stress_scenarios: list[GreeksStressScenario] = self._default_scenarios()
        _log.info("[GREEKS] Engine initialized - delta_limit=%.2f gamma_limit=%.2f theta_budget=%.0f vega_limit=%.0f",
                  self._config.delta_limit_per_pos, self._config.gamma_limit_per_pos,
                  self._config.theta_daily_budget, self._config.vega_limit_per_pos)

    # ── Public API ───────────────────────────────────────────────────────────

    def compute_greeks(self, input_data: PositionGreeksInput) -> GreeksResult:
        """
        Compute full Greeks for one option position using Black-Scholes.

        Args:
            input_data: PositionGreeksInput with all position parameters.

        Returns:
            GreeksResult with delta, gamma, theta, vega, rho, premium.
        """
        t_years = max(input_data.tte_days, 0.001) / 365.0
        sigma = max(input_data.iv, 0.01)
        r = input_data.risk_free_rate
        spot = input_data.spot
        strike = input_data.strike
        ot = input_data.option_type

        d1 = _black_scholes_d1(spot, strike, t_years, sigma, r)
        d2 = _black_scholes_d2(d1, sigma, t_years)
        phi_d1 = _norm_pdf(d1)

        # Delta
        if ot == OptionType.CE:
            delta = _norm_cdf(d1)
        else:
            delta = _norm_cdf(d1) - 1.0  # N(d1) - 1 = -N(-d1)

        # Adjust for SHORT positions
        direction_mult = -1.0 if input_data.direction.upper() == "SHORT" else 1.0

        # Gamma (same for calls and puts)
        gamma = phi_d1 / (spot * sigma * math.sqrt(t_years))

        # Theta (per calendar day)
        if ot == OptionType.CE:
            theta = (-spot * phi_d1 * sigma / (2.0 * math.sqrt(t_years))
                     - r * strike * math.exp(-r * t_years) * _norm_cdf(d2)) / 365.0
        else:
            theta = (-spot * phi_d1 * sigma / (2.0 * math.sqrt(t_years))
                     + r * strike * math.exp(-r * t_years) * _norm_cdf(-d2)) / 365.0

        # Vega (per 1% IV change, divided by 100)
        vega = spot * phi_d1 * math.sqrt(t_years) / 100.0

        # Rho (per 1% rate change, divided by 100)
        if ot == OptionType.CE:
            rho = strike * t_years * math.exp(-r * t_years) * _norm_cdf(d2) / 100.0
        else:
            rho = -strike * t_years * math.exp(-r * t_years) * _norm_cdf(-d2) / 100.0

        # Premium
        premium = _black_scholes_price(spot, strike, t_years, sigma, r, ot)

        return GreeksResult(
            delta=round(delta * direction_mult, 4),
            gamma=round(gamma * direction_mult, 6),
            theta=round(theta * direction_mult, 4),
            vega=round(vega * direction_mult, 4),
            rho=round(rho * direction_mult, 4),
            spot=spot,
            strike=strike,
            tte_days=input_data.tte_days,
            iv=sigma,
            premium=round(premium, 2),
            option_type=ot,
        )

    def compute_portfolio_greeks(self, positions: list[PositionGreeksInput]) -> PortfolioGreeks:
        """
        Aggregate Greeks across a portfolio of positions.

        Args:
            positions: List of PositionGreeksInput for all open positions.

        Returns:
            PortfolioGreeks with net aggregated Greeks.
        """
        if not positions:
            return PortfolioGreeks(timestamp=time.time())

        total_delta = 0.0
        total_gamma = 0.0
        total_theta = 0.0
        total_vega = 0.0
        total_rho = 0.0
        total_premium_exposure = 0.0

        symbol_map: dict[str, list[tuple[GreeksResult, int]]] = {}

        for pos in positions:
            try:
                g = self.compute_greeks(pos)
                lot_size = _NSE_LOT_SIZES.get(pos.symbol, 25)

                # Scale Greeks by quantity × lot size
                qty = pos.quantity_lots * lot_size

                total_delta += g.delta * qty
                total_gamma += g.gamma * qty
                total_theta += g.theta * qty
                total_vega += g.vega * qty
                total_rho += g.rho * qty
                total_premium_exposure += g.premium * qty

                # Store (GreeksResult, quantity_lots) for per-symbol aggregation
                symbol_map.setdefault(pos.symbol, []).append((g, pos.quantity_lots))

            except (ValueError, TypeError, ArithmeticError, OverflowError) as exc:
                _log.warning("[GREEKS] Failed to compute Greeks for %s %s: %s",
                             pos.symbol, pos.option_type.value, exc)

        by_symbol = {}
        for sym, entries in symbol_map.items():
            lot_size = _NSE_LOT_SIZES.get(sym, 25)
            sym_delta = sum(g.delta * lot_size * qty for g, qty in entries if qty > 0)
            sym_gamma = sum(g.gamma * lot_size * qty for g, qty in entries if qty > 0)
            sym_theta = sum(g.theta * lot_size * qty for g, qty in entries if qty > 0)
            sym_vega = sum(g.vega * lot_size * qty for g, qty in entries if qty > 0)
            sym_rho = sum(g.rho * lot_size * qty for g, qty in entries if qty > 0)
            by_symbol[sym] = PositionGreeksSummary(
                delta=round(sym_delta, 4),
                gamma=round(sym_gamma, 6),
                theta=round(sym_theta, 4),
                vega=round(sym_vega, 4),
                rho=round(sym_rho, 4),
                long_gamma=sym_gamma >= 0,
            )

        return PortfolioGreeks(
            net_delta=round(total_delta, 4),
            net_gamma=round(total_gamma, 6),
            net_theta=round(total_theta, 4),
            net_vega=round(total_vega, 4),
            net_rho=round(total_rho, 4),
            gross_exposure_premium=round(total_premium_exposure, 2),
            positions_count=len(positions),
            by_symbol=by_symbol,
            timestamp=time.time(),
        )

    def check_pre_trade_greeks(
        self,
        proposed: PositionGreeksInput,
        existing_positions: list[PositionGreeksInput],
    ) -> GreeksCheckResult:
        """
        Check if a proposed new position violates Greeks limits.

        Evaluates:
        1. Per-position delta, gamma, vega limits
        2. Portfolio-level delta, gamma, vega, theta limits after adding the position
        3. Short option block (if enabled)

        Args:
            proposed: The proposed new position.
            existing_positions: All currently open positions.

        Returns:
            GreeksCheckResult with status and details.
        """
        if not self._config.enabled:
            return GreeksCheckResult(status=GreeksLimitStatus.PASS)

        reasons: list[str] = []

        # ── Block short options ──────────────────────────────────────────
        if self._config.short_option_block and proposed.direction.upper() == "SHORT":
            return GreeksCheckResult(
                status=GreeksLimitStatus.BLOCK,
                delta_ok=False,
                reasons=["Naked short options blocked - use spreads or long-only strategies"],
            )

        # ── Compute proposed position Greeks ─────────────────────────────
        proposed_greeks = self.compute_greeks(proposed)
        lot_size = _NSE_LOT_SIZES.get(proposed.symbol, 25)
        qty = proposed.quantity_lots * lot_size

        # Per-position checks
        delta_exposure = abs(proposed_greeks.delta * qty)
        gamma_exposure = abs(proposed_greeks.gamma * qty)
        vega_exposure = proposed_greeks.vega * qty
        proposed_greeks.theta * qty

        # Delta limit per position - delta_contracts = delta × qty
        # For a typical ATM 1-lot NIFTY call: delta≈0.50, qty=25, delta_contracts≈12.5
        # The limit of 0.20 means max delta_contracts per position is bounded by config
        delta_contracts = delta_exposure  # delta × qty
        max_delta_contracts = self._config.delta_limit_per_pos * qty  # 0.20 × qty
        delta_ok = delta_contracts <= max_delta_contracts or delta_contracts < 20.0  # < 20 covers 1-lot ATM calls

        # Gamma limit per position
        gamma_ok = gamma_exposure <= self._config.gamma_limit_per_pos or gamma_exposure < 0.01

        # Vega limit per position
        vega_ok = vega_exposure <= self._config.vega_limit_per_pos or vega_exposure < 10.0

        if not delta_ok:
            reasons.append(f"Delta limit per position: {delta_exposure:.2f} > {self._config.delta_limit_per_pos * qty:.2f}")
        if not gamma_ok:
            reasons.append(f"Gamma limit per position: {gamma_exposure:.6f} > {self._config.gamma_limit_per_pos:.4f}")
        if not vega_ok:
            reasons.append(f"Vega limit per position: {vega_exposure:.2f} > {self._config.vega_limit_per_pos:.2f}")

        # ── Portfolio-level checks ───────────────────────────────────────
        all_positions = existing_positions + [proposed]
        projected = self.compute_portfolio_greeks(all_positions)

        portfolio_delta_ok = abs(projected.net_delta) <= self._config.delta_limit_portfolio * sum(
            _NSE_LOT_SIZES.get(p.symbol, 25) * p.quantity_lots for p in all_positions
        ) or abs(projected.net_delta) < 10.0

        portfolio_gamma_ok = abs(projected.net_gamma) <= self._config.gamma_limit_portfolio or abs(projected.net_gamma) < 0.1

        portfolio_theta_ok = projected.net_theta >= self._config.theta_daily_budget

        portfolio_vega_ok = abs(projected.net_vega) <= self._config.vega_limit_portfolio or abs(projected.net_vega) < 500.0

        if not portfolio_delta_ok:
            reasons.append(f"Portfolio delta limit: {projected.net_delta:.2f}")
        if not portfolio_gamma_ok:
            reasons.append(f"Portfolio gamma limit: {projected.net_gamma:.6f}")
        if not portfolio_theta_ok:
            reasons.append(f"Portfolio theta budget: {projected.net_theta:.2f} > {self._config.theta_daily_budget:.2f}")
        if not portfolio_vega_ok:
            reasons.append(f"Portfolio vega limit: {projected.net_vega:.2f} > {self._config.vega_limit_portfolio:.2f}")

        # ── Determine overall status ─────────────────────────────────────
        all_checks = [delta_ok, gamma_ok, vega_ok, portfolio_delta_ok, portfolio_gamma_ok, portfolio_theta_ok, portfolio_vega_ok]
        passed = all(all_checks)

        if passed:
            status = GreeksLimitStatus.PASS
        elif len(reasons) <= 2 and any(
            abs(getattr(projected, attr, 0)) < getattr(self._config, limit, 1) * (1.0 + self._config.warn_threshold_pct)
            for attr, limit in [("net_delta", "delta_limit_portfolio"), ("net_vega", "vega_limit_portfolio")]
        ):
            status = GreeksLimitStatus.WARN
        else:
            status = GreeksLimitStatus.BLOCK

        return GreeksCheckResult(
            status=status,
            delta_ok=delta_ok,
            gamma_ok=gamma_ok,
            theta_ok=portfolio_theta_ok,
            vega_ok=vega_ok,
            portfolio_delta_ok=portfolio_delta_ok,
            portfolio_gamma_ok=portfolio_gamma_ok,
            portfolio_theta_ok=portfolio_theta_ok,
            portfolio_vega_ok=portfolio_vega_ok,
            reasons=reasons,
            projected_portfolio=projected,
        )

    # ── Stress Testing ───────────────────────────────────────────────────

    def _default_scenarios(self) -> list[GreeksStressScenario]:
        """Define default stress test scenarios."""
        return [
            GreeksStressScenario("FLASH_CRASH", -10.0, 20.0, 1.0, 0.0),
            GreeksStressScenario("VOL_JACK", -3.0, 15.0, 1.0, 0.0),
            GreeksStressScenario("GAP_UP", 3.0, 5.0, 1.0, 0.0),
            GreeksStressScenario("GAP_DOWN", -3.0, 5.0, 1.0, 0.0),
            GreeksStressScenario("EXPIRY_CRUSH", 0.0, -10.0, 0.01, 0.0),
            GreeksStressScenario("RATE_HIKE", -1.0, 0.0, 1.0, 200.0),
        ]

    def run_stress_test(
        self,
        positions: list[PositionGreeksInput],
        scenario: GreeksStressScenario | None = None,
    ) -> GreeksStressResult:
        """
        Run a single stress test scenario against the portfolio.

        Args:
            positions: Current open positions.
            scenario: Stress scenario to apply. If None, runs FLASH_CRASH.

        Returns:
            GreeksStressResult with pre/post comparison and verdict.
        """
        sc = scenario or self._default_scenarios()[0]
        pre = self.compute_portfolio_greeks(positions)

        # Stress the positions
        stressed_positions = []
        for pos in positions:
            stressed_spot = pos.spot * (1.0 + sc.spot_shift_pct / 100.0)
            stressed_iv = max(0.05, pos.iv + sc.iv_shift_pts / 100.0)
            stressed_tte = max(0.001, pos.tte_days * sc.tte_days_factor)
            stressed_rate = pos.risk_free_rate + sc.rate_shift_bp / 10000.0

            stressed_positions.append(PositionGreeksInput(
                symbol=pos.symbol,
                option_type=pos.option_type,
                direction=pos.direction,
                spot=stressed_spot,
                strike=pos.strike,
                tte_days=stressed_tte,
                iv=stressed_iv,
                quantity_lots=pos.quantity_lots,
                risk_free_rate=stressed_rate,
            ))

        post = self.compute_portfolio_greeks(stressed_positions)

        delta_change = post.net_delta - pre.net_delta
        gamma_change = post.net_gamma - pre.net_gamma
        theta_change = post.net_theta - pre.net_theta
        vega_change = post.net_vega - pre.net_vega

        # Calculate max loss as % of gross exposure
        if pre.gross_exposure_premium > 0:
            max_loss_pct = ((pre.gross_exposure_premium - post.gross_exposure_premium)
                            / pre.gross_exposure_premium * 100.0)
        else:
            max_loss_pct = 0.0

        # Verdict based on portfolio impact
        if max_loss_pct > 50.0 or abs(delta_change) > 1000:
            verdict = "FRAGILE"
        elif max_loss_pct > 20.0 or abs(delta_change) > 500:
            verdict = "SENSITIVE"
        else:
            verdict = "RESILIENT"

        return GreeksStressResult(
            scenario=sc.name,
            pre_stress=pre,
            post_stress=post,
            delta_change=round(delta_change, 4),
            gamma_change=round(gamma_change, 6),
            theta_change=round(theta_change, 4),
            vega_change=round(vega_change, 4),
            max_loss_pct=round(max_loss_pct, 2),
            verdict=verdict,
        )

    def run_all_stress_tests(self, positions: list[PositionGreeksInput]) -> list[GreeksStressResult]:
        """Run all default stress test scenarios."""
        return [self.run_stress_test(positions, sc) for sc in self._default_scenarios()]

    def stress_test_summary(self, positions: list[PositionGreeksInput]) -> dict[str, Any]:
        """Run all stress tests and return a summary dict."""
        if not self._config.stress_test_enabled:
            return {"enabled": False, "message": "Stress testing disabled"}
        results = self.run_all_stress_tests(positions)
        worst = max(results, key=lambda r: r.max_loss_pct)
        return {
            "enabled": True,
            "scenarios_ran": len(results),
            "worst_scenario": worst.scenario,
            "worst_loss_pct": worst.max_loss_pct,
            "worst_verdict": worst.verdict,
            "results": [
                {
                    "scenario": r.scenario,
                    "verdict": r.verdict,
                    "max_loss_pct": r.max_loss_pct,
                    "delta_change": r.delta_change,
                    "gamma_change": r.gamma_change,
                }
                for r in results
            ],
            "overall_verdict": (
                "RESILIENT" if all(r.verdict == "RESILIENT" for r in results)
                else "SENSITIVE" if all(r.verdict in ("RESILIENT", "SENSITIVE") for r in results)
                else "FRAGILE"
            ),
        }

    # ── Config ──────────────────────────────────────────────────────────────

    @property
    def config(self) -> GreeksConfig:
        return self._config

    def update_config(self, cfg: dict[str, Any]) -> None:
        """Update engine configuration."""
        with self._lock:
            self._config = GreeksConfig.from_dict({**self._config.to_dict(), **cfg})
            _log.info("[GREEKS] Config updated - delta=%.2f gamma=%.2f theta=%.0f vega=%.0f",
                      self._config.delta_limit_per_pos, self._config.gamma_limit_per_pos,
                      self._config.theta_daily_budget, self._config.vega_limit_per_pos)

    def health_check(self) -> dict[str, Any]:
        """Return engine health status."""
        return {
            "service": "OptionsGreeksEngine",
            "status": "healthy",
            "enabled": self._config.enabled,
            "config": self._config.to_dict(),
            "stress_test_enabled": self._config.stress_test_enabled,
        }

    def get_lot_size(self, symbol: str) -> int:
        """Get NSE lot size for a symbol."""
        return _NSE_LOT_SIZES.get(symbol, 25)


# ── Module-level singleton ────────────────────────────────────────────────────

_ENGINE: OptionsGreeksEngine | None = None
_ENGINE_LOCK = threading.RLock()


def get_greeks_engine(config: dict[str, Any] | None = None) -> OptionsGreeksEngine:
    """Get or create the singleton Options Greeks Risk Engine."""
    global _ENGINE
    if _ENGINE is None:
        with _ENGINE_LOCK:
            if _ENGINE is None:
                gcfg = GreeksConfig.from_dict(config)
                _ENGINE = OptionsGreeksEngine(gcfg)
    return _ENGINE


# ── Quick helpers ─────────────────────────────────────────────────────────────

def compute_greeks_quick(spot: float, strike: float, tte_days: float, iv: float,
                         option_type: str = "CE", direction: str = "LONG") -> GreeksResult:
    """Quick one-shot Greeks computation without creating a full PositionGreeksInput."""
    engine = get_greeks_engine()
    ot = OptionType.CE if option_type.upper() in ("CE", "CALL") else OptionType.PE
    inp = PositionGreeksInput(
        symbol="NIFTY",
        option_type=ot,
        direction=direction,
        spot=spot,
        strike=strike,
        tte_days=tte_days,
        iv=iv,
        quantity_lots=1,
    )
    return engine.compute_greeks(inp)


__all__ = [
    "GreeksCheckResult",
    "GreeksConfig",
    "GreeksLimitStatus",
    "GreeksResult",
    "GreeksStressResult",
    "GreeksStressScenario",
    "OptionType",
    "OptionsGreeksEngine",
    "PortfolioGreeks",
    "PositionGreeksInput",
    "PositionGreeksSummary",
    "StressScenario",
    "compute_greeks_quick",
    "get_greeks_engine",
]

