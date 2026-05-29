"""
A/B Strategy Tester (v2.44 Item 20).

Runs two config variants — CONTROL (current live config) and VARIANT — on the
same signal stream in paper mode.  For each signal, both variants decide
independently whether to enter and at what parameters.  Outcomes are recorded
so statistical significance can be assessed via Mann-Whitney U test.

Requirements: scipy (for Mann-Whitney U).  Falls back to a simple t-test if
scipy is not installed.

Public API
----------
    ABStrategyTester(cfg, variant_cfg) — initialise the tester
    tester.evaluate_signal(signal_dict) → ABSignalDecision
    tester.record_trade_outcome(variant, pnl)
    tester.get_comparison() → ABComparisonResult
    tester.save_state(path) / tester.load_state(path)

    cli: python -m core.ab_strategy_tester

Config keys (index_config.defaults.json)
-----------------------------------------
    ab_testing_enabled              : bool  default false
    ab_variant_name                 : str   default "VARIANT_A"
    ab_variant_overrides            : dict  default {}
    ab_min_trades_for_significance  : int   default 30
    ab_state_path                   : str   default "ab_state.json"
"""
from __future__ import annotations

import argparse
import json
import logging
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)


# ── Dataclasses ───────────────────────────────────────────────────────────────

@dataclass
class ABVariantState:
    name:         str
    n_trades:     int   = 0
    n_wins:       int   = 0
    total_pnl:    float = 0.0
    pnls:         list[float] = field(default_factory=list)

    @property
    def win_rate(self) -> float:
        return (self.n_wins / self.n_trades) if self.n_trades > 0 else 0.0

    @property
    def profit_factor(self) -> float:
        wins   = sum(p for p in self.pnls if p > 0)
        losses = abs(sum(p for p in self.pnls if p < 0))
        return (wins / losses) if losses > 0 else (10.0 if wins > 0 else 0.0)

    @property
    def sharpe(self) -> float:
        n = len(self.pnls)
        if n < 2:
            return 0.0
        mean = sum(self.pnls) / n
        std  = math.sqrt(sum((p - mean) ** 2 for p in self.pnls) / n)
        return mean / std if std > 0 else 0.0

    def add_outcome(self, pnl: float) -> None:
        self.n_trades += 1
        if pnl > 0:
            self.n_wins += 1
        self.total_pnl += pnl
        self.pnls.append(pnl)


@dataclass
class ABSignalDecision:
    control_enter:  bool
    variant_enter:  bool
    control_score:  int
    variant_score:  int
    control_reason: str = ""
    variant_reason: str = ""


@dataclass
class ABComparisonResult:
    control:           ABVariantState
    variant:           ABVariantState
    is_significant:    bool
    p_value:           float
    winner:            str   = ""
    summary:           str   = ""
    min_trades_met:    bool  = False


# ── Core tester ───────────────────────────────────────────────────────────────

class ABStrategyTester:
    """
    Runs two config variants on the same live signal stream in paper mode.

    Args:
        cfg         : Base (CONTROL) config dict.
        variant_cfg : Dict of overrides for the VARIANT.  E.g. {"SL_PCT": 0.25}.
        enabled     : If False, all methods return no-ops.
    """

    def __init__(
        self,
        cfg:         dict[str, Any] | None = None,
        variant_cfg: dict[str, Any] | None = None,
    ) -> None:
        self._cfg      = cfg or {}
        self._var_cfg  = dict(self._cfg, **(variant_cfg or self._cfg.get("ab_variant_overrides", {})))
        variant_name   = self._cfg.get("ab_variant_name", "VARIANT_A")
        self._enabled  = bool(self._cfg.get("ab_testing_enabled", False))
        self._min_trades = int(self._cfg.get("ab_min_trades_for_significance", 30))

        self.control = ABVariantState(name="CONTROL")
        self.variant = ABVariantState(name=variant_name)

    # ── Signal evaluation ─────────────────────────────────────────────────────

    def evaluate_signal(self, signal: dict[str, Any]) -> ABSignalDecision:
        """
        Given a signal dict, decide whether CONTROL and VARIANT would enter.

        The primary difference between variants is score threshold — if the
        VARIANT has a different AI_THRESHOLD override, it may accept signals
        that CONTROL rejects and vice-versa.

        Args:
            signal : Dict with at least "score" and "allowed" keys.

        Returns:
            ABSignalDecision — both enter flags and the effective scores.
        """
        if not self._enabled:
            return ABSignalDecision(True, True, 0, 0, "AB_DISABLED", "AB_DISABLED")

        base_score     = int(signal.get("score",   0))
        base_allowed   = bool(signal.get("allowed", True))

        ctrl_threshold = int(self._cfg.get("AI_THRESHOLD",      60))
        var_threshold  = int(self._var_cfg.get("AI_THRESHOLD",  60))

        ctrl_enter = base_allowed and (base_score >= ctrl_threshold)
        var_enter  = base_allowed and (base_score >= var_threshold)

        ctrl_reason = "score_ok" if ctrl_enter else f"score {base_score} < {ctrl_threshold}"
        var_reason  = "score_ok" if var_enter  else f"score {base_score} < {var_threshold}"

        return ABSignalDecision(
            control_enter=ctrl_enter,
            variant_enter=var_enter,
            control_score=base_score,
            variant_score=base_score,
            control_reason=ctrl_reason,
            variant_reason=var_reason,
        )

    # ── Outcome recording ─────────────────────────────────────────────────────

    def record_trade_outcome(self, variant: str, pnl: float) -> None:
        """
        Record a closed trade outcome for a given variant.

        Args:
            variant : "CONTROL" or the variant name.
            pnl     : Net P&L of the trade.
        """
        if not self._enabled:
            return
        if variant.upper() == "CONTROL":
            self.control.add_outcome(pnl)
        else:
            self.variant.add_outcome(pnl)

    # ── Statistical comparison ────────────────────────────────────────────────

    def get_comparison(self) -> ABComparisonResult:
        """
        Compute a statistical comparison between CONTROL and VARIANT.

        Uses Mann-Whitney U (via scipy) if available, else Welch's t-test
        approximation.

        Returns:
            ABComparisonResult with significance flags and winner.
        """
        min_n = self._min_trades
        min_met = (
            self.control.n_trades >= min_n
            and self.variant.n_trades >= min_n
        )
        p_value = 1.0
        is_sig  = False

        if min_met and self.control.pnls and self.variant.pnls:
            p_value = _mann_whitney_p(self.control.pnls, self.variant.pnls)
            is_sig  = p_value < 0.05

        winner = ""
        if is_sig:
            winner = (
                "CONTROL"
                if self.control.sharpe >= self.variant.sharpe
                else self.variant.name
            )
        elif min_met:
            winner = "NOT_SIGNIFICANT"
        else:
            winner = "INSUFFICIENT_DATA"

        ctrl = self.control
        var  = self.variant
        summary = (
            f"A/B Test: CONTROL {ctrl.n_trades}T {ctrl.win_rate*100:.1f}% WR "
            f"PF={ctrl.profit_factor:.2f} Sharpe={ctrl.sharpe:.3f} | "
            f"{var.name} {var.n_trades}T {var.win_rate*100:.1f}% WR "
            f"PF={var.profit_factor:.2f} Sharpe={var.sharpe:.3f} | "
            f"p={p_value:.4f} {'SIGNIFICANT' if is_sig else 'not significant'} | "
            f"Winner: {winner}"
        )

        return ABComparisonResult(
            control=self.control,
            variant=self.variant,
            is_significant=is_sig,
            p_value=round(p_value, 6),
            winner=winner,
            summary=summary,
            min_trades_met=min_met,
        )

    # ── Persistence ───────────────────────────────────────────────────────────

    def save_state(self, path: str | None = None) -> None:
        """Save current A/B state to a JSON file."""
        if not self._enabled:
            return
        fpath = path or self._cfg.get("ab_state_path", "ab_state.json")
        try:
            data = {
                "control": asdict(self.control),
                "variant": asdict(self.variant),
            }
            Path(fpath).write_text(json.dumps(data, indent=2))
            _log.debug("[AB] State saved to %s", fpath)
        except Exception as exc:
            _log.warning("[AB] save_state failed: %s", exc)

    def load_state(self, path: str | None = None) -> None:
        """Load A/B state from a JSON file (if it exists)."""
        fpath = path or self._cfg.get("ab_state_path", "ab_state.json")
        p = Path(fpath)
        if not p.is_file():
            return
        try:
            data = json.loads(p.read_text())
            for attr, cls, obj in (("control", ABVariantState, self.control),
                                   ("variant", ABVariantState, self.variant)):
                raw = data.get(attr, {})
                obj.n_trades  = int(raw.get("n_trades", 0))
                obj.n_wins    = int(raw.get("n_wins",   0))
                obj.total_pnl = float(raw.get("total_pnl", 0.0))
                obj.pnls      = [float(x) for x in raw.get("pnls", [])]
            _log.debug("[AB] State loaded from %s", fpath)
        except Exception as exc:
            _log.warning("[AB] load_state failed: %s", exc)

    def reset(self) -> None:
        """Reset both variant states (start a fresh experiment)."""
        variant_name = self.variant.name
        self.control = ABVariantState(name="CONTROL")
        self.variant = ABVariantState(name=variant_name)


# ── Statistical helper ────────────────────────────────────────────────────────

def _mann_whitney_p(a: list[float], b: list[float]) -> float:
    """Return two-sided Mann-Whitney U p-value; falls back to approx t-test."""
    if not a or not b:
        return 1.0
    try:
        from scipy.stats import mannwhitneyu  # type: ignore
        result = mannwhitneyu(a, b, alternative="two-sided")
        p = float(result.pvalue)
        return p if not math.isnan(p) else 1.0
    except ImportError:
        pass
    # Welch's t-test fallback
    na, nb = len(a), len(b)
    if na < 2 or nb < 2:
        return 1.0
    mean_a = sum(a) / na
    mean_b = sum(b) / nb
    var_a  = sum((x - mean_a) ** 2 for x in a) / (na - 1)
    var_b  = sum((x - mean_b) ** 2 for x in b) / (nb - 1)
    se     = math.sqrt(var_a / na + var_b / nb)
    if se == 0:
        return 1.0
    t  = abs(mean_a - mean_b) / se
    df = (var_a / na + var_b / nb) ** 2 / (
        (var_a / na) ** 2 / (na - 1) + (var_b / nb) ** 2 / (nb - 1)
    )
    # Rough p approximation via t-distribution CDF (two-sided)
    x   = df / (df + t * t)
    p   = _betainc(df / 2, 0.5, x)
    return min(1.0, max(0.0, p))


def _betainc(a: float, b: float, x: float) -> float:
    """Regularised incomplete beta function (rough approximation for two-sided p)."""
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    # Simple series approximation — sufficient for p-value indication
    try:
        import math
        ln_beta = math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)
        val     = math.exp(a * math.log(x) + b * math.log(1 - x) - ln_beta) / a
        return min(1.0, val * 2)  # two-sided
    except Exception:
        return 1.0


# ── CLI ───────────────────────────────────────────────────────────────────────

def _cli() -> None:
    ap = argparse.ArgumentParser(
        prog="python -m core.ab_strategy_tester",
        description="Show current A/B test comparison results.",
    )
    ap.add_argument("--state", default="ab_state.json", help="Path to ab_state.json")
    ap.add_argument("--reset", action="store_true",     help="Reset A/B state")
    args = ap.parse_args()

    cfg     = {"ab_testing_enabled": True, "ab_state_path": args.state}
    tester  = ABStrategyTester(cfg)
    tester.load_state(args.state)

    if args.reset:
        tester.reset()
        tester.save_state(args.state)
        _log.info("A/B state reset.")
        return

    result = tester.get_comparison()
    print(result.summary)
    _log.info(f"\nControl:  {result.control.n_trades} trades, "
          f"win_rate={result.control.win_rate*100:.1f}%, "
          f"pf={result.control.profit_factor:.3f}, "
          f"sharpe={result.control.sharpe:.3f}")
    _log.info(f"Variant:  {result.variant.n_trades} trades, "
          f"win_rate={result.variant.win_rate*100:.1f}%, "
          f"pf={result.variant.profit_factor:.3f}, "
          f"sharpe={result.variant.sharpe:.3f}")
    _log.info(f"\np-value={result.p_value:.6f}, "
          f"significant={'YES' if result.is_significant else 'NO'}, "
          f"winner={result.winner}")


if __name__ == "__main__":
    _cli()
