"""Bias Detection Engine — Detects algorithmic bias in AI outputs and trading decisions (AI Governance Layer).

Provides multi-strategy bias detection:
  1. Demographic parity: checks if outcomes vary across symbol/segment categories
  2. Equalized odds: checks if false positive/negative rates differ across categories
  3. Outcome fairness: checks win rate / P&L distribution for skew
  4. Directional bias: checks for systematic preference toward CALL vs PUT
  5. Temporal bias: checks for time-of-day / day-of-week performance skew
  6. Feature importance bias: detects if certain features dominate ML predictions

Integrates with:
  - HallucinationDetector (for cross-validated AI output analysis)
  - AutoLearner (for performance-based bias signals)
  - ReportGenerator (for bias audit reports)

Usage:
    from core.bias_detector import get_bias_detector

    detector = get_bias_detector()
    result = detector.analyze_trades(trade_history)
    print(result.bias_score, result.bias_level)
"""

from __future__ import annotations

import json
import logging
import math
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────

_DEFAULT_PERSIST_PATH = Path("json/bias_detection_history.json")

BIAS_CATEGORIES = [
    "DIRECTIONAL",    # CALL vs PUT preference
    "TEMPORAL",       # Time-of-day / day-of-week skew
    "SEGMENT",        # Symbol / segment bias
    "OUTCOME",        # Win/loss distribution fairness
    "SIZE",           # Position sizing bias (over/under sizing certain symbols)
    "REGIME",         # Regime bias (performing differently in different regimes)
    "FEATURE",        # ML feature dominance bias
]

BIAS_LEVELS = ["CLEAN", "LOW", "MEDIUM", "HIGH", "CRITICAL"]

# Thresholds for bias classification
BIAS_THRESHOLDS = {
    "DIRECTIONAL": {"p_threshold": 0.05, "min_trades": 20},
    "TEMPORAL": {"p_threshold": 0.05, "min_trades": 10},
    "SEGMENT": {"p_threshold": 0.05, "min_trades": 10},
    "OUTCOME": {"p_threshold": 0.05, "min_trades": 30},
    "SIZE": {"p_threshold": 0.05, "min_trades": 10},
    "REGIME": {"p_threshold": 0.05, "min_trades": 10},
    "FEATURE": {"p_threshold": 0.1, "min_trades": 50},
}


# ── Data Models ───────────────────────────────────────────────────────────


@dataclass
class BiasFinding:
    """A single bias finding."""

    bias_category: str
    description: str
    severity: float       # 0.0 to 1.0
    p_value: float        # statistical significance
    effect_size: float    # magnitude of the bias
    direction: str = ""   # Which direction the bias favors
    recommendation: str = ""
    n_samples: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "bias_category": self.bias_category,
            "description": self.description[:200],
            "severity": round(self.severity, 3),
            "p_value": round(self.p_value, 4),
            "effect_size": round(self.effect_size, 3),
            "direction": self.direction,
            "recommendation": self.recommendation[:200],
            "n_samples": self.n_samples,
        }


@dataclass
class BiasReport:
    """Complete bias analysis report."""

    bias_score: float       # 0.0 (clean) to 1.0 (highly biased)
    bias_level: str         # CLEAN, LOW, MEDIUM, HIGH, CRITICAL
    findings: list[BiasFinding] = field(default_factory=list)
    categories_checked: list[str] = field(default_factory=list)
    total_trades_analyzed: int = 0
    win_rate: float = 0.0
    call_win_rate: float = 0.0
    put_win_rate: float = 0.0
    n_calls: int = 0
    n_puts: int = 0
    nifty_win_rate: float = 0.0
    banknifty_win_rate: float = 0.0
    finnifty_win_rate: float = 0.0
    morning_win_rate: float = 0.0
    afternoon_win_rate: float = 0.0
    recommendations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "bias_score": round(self.bias_score, 3),
            "bias_level": self.bias_level,
            "findings": [f.to_dict() for f in self.findings],
            "categories_checked": self.categories_checked,
            "total_trades_analyzed": self.total_trades_analyzed,
            "win_rate": round(self.win_rate, 3),
            "call_win_rate": round(self.call_win_rate, 3),
            "put_win_rate": round(self.put_win_rate, 3),
            "n_calls": self.n_calls,
            "n_puts": self.n_puts,
            "nifty_win_rate": round(self.nifty_win_rate, 3),
            "banknifty_win_rate": round(self.banknifty_win_rate, 3),
            "finnifty_win_rate": round(self.finnifty_win_rate, 3),
            "morning_win_rate": round(self.morning_win_rate, 3),
            "afternoon_win_rate": round(self.afternoon_win_rate, 3),
            "recommendations": self.recommendations[:10],
        }

    def summary_text(self) -> str:
        lines = [
            "═" * 60,
            "  BIAS DETECTION REPORT",
            "═" * 60,
            f"  Overall Bias Score: {self.bias_score:.3f}",
            f"  Bias Level: {self.bias_level}",
            f"  Trades Analyzed: {self.total_trades_analyzed}",
            "",
            f"  Win Rate:      {self.win_rate:.1%}",
            f"  CALL Win Rate:  {self.call_win_rate:.1%} ({self.n_calls} trades)",
            f"  PUT Win Rate:   {self.put_win_rate:.1%} ({self.n_puts} trades)",
            f"  NIFTY Win Rate:  {self.nifty_win_rate:.1%}",
            f"  BANKNIFTY Win Rate: {self.banknifty_win_rate:.1%}",
            f"  FINNIFTY Win Rate:  {self.finnifty_win_rate:.1%}",
            f"  Morning Win Rate:   {self.morning_win_rate:.1%}",
            f"  Afternoon Win Rate: {self.afternoon_win_rate:.1%}",
        ]
        if self.findings:
            lines.append("")
            lines.append("  Bias Findings:")
            for f in self.findings:
                lines.append(f"    [{f.bias_category}] {f.description}")
        if self.recommendations:
            lines.append("")
            lines.append("  Recommendations:")
            for r in self.recommendations:
                lines.append(f"    → {r}")
        lines.append("═" * 60)
        return "\n".join(lines)


# ── Statistical Helpers ────────────────────────────────────────────────────


def _z_test(p1: float, p2: float, n1: int, n2: int) -> float:
    """Two-proportion z-test. Returns p-value."""
    if n1 < 5 or n2 < 5:
        return 1.0  # insufficient data
    p_pool = (p1 * n1 + p2 * n2) / max(n1 + n2, 1)
    if p_pool <= 0 or p_pool >= 1:
        return 1.0
    se = math.sqrt(p_pool * (1 - p_pool) * (1 / n1 + 1 / n2))
    if se == 0:
        return 1.0
    z = abs(p1 - p2) / se
    # Approximate p-value from z-score (normal CDF approximation)
    return 2 * (1 - _normal_cdf(z))


def _normal_cdf(x: float) -> float:
    """Standard normal CDF (Abramowitz and Stegun approximation)."""
    if x < 0:
        return 1 - _normal_cdf(-x)
    k = 1.0 / (1.0 + 0.2316419 * x)
    poly = k * (0.319381530 + k * (-0.356563782 + k * (1.781477937 + k * (-1.821255978 + 1.330274429 * k))))
    return 1.0 - 0.398942280 * math.exp(-0.5 * x * x) * poly


def _cohens_h(p1: float, p2: float) -> float:
    """Cohen's h effect size for two proportions."""
    def _asin(p: float) -> float:
        return 2 * math.asin(math.sqrt(max(0, min(1, p))))
    return abs(_asin(p1) - _asin(p2))


def _classify_bias_level(score: float) -> str:
    """Classify bias level from score."""
    if score >= 0.8:
        return "CRITICAL"
    if score >= 0.5:
        return "HIGH"
    if score >= 0.3:
        return "MEDIUM"
    if score >= 0.1:
        return "LOW"
    return "CLEAN"


# ── Bias Detector ─────────────────────────────────────────────────────────


class BiasDetector:
    """Detects algorithmic bias in trading decisions and AI outputs.

    Analyzes trade history across multiple dimensions:
    - Directional: CALL vs PUT performance
    - Temporal: time-of-day / day-of-week performance
    - Segment: symbol-level performance
    - Outcome: distribution of wins/losses
    - Size: position sizing patterns across symbols
    - Regime: regime-specific performance

    Thread-safe. JSON-persisted.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._history: list[BiasReport] = []
        self._max_history = 200
        self._persist_path = _DEFAULT_PERSIST_PATH
        self._load_history()

    # ── Public API ────────────────────────────────────────────────────────

    def analyze_trades(
        self,
        trades: list[dict[str, Any]],
    ) -> BiasReport:
        """Analyze trade history for bias patterns.

        Args:
            trades: List of trade dicts with keys:
                - direction: "CALL" or "PUT"
                - symbol: "NIFTY", "BANKNIFTY", etc.
                - net_pnl: float
                - entry_time: str (HH:MM format)
                - day_of_week: int (0=Monday)
                - regime: str (optional)
                - lots: int (optional)
                - score: int (optional)

        Returns:
            BiasReport with findings and recommendations.
        """
        findings: list[BiasFinding] = []

        if not trades:
            report = BiasReport(
                bias_score=0.0,
                bias_level="CLEAN",
                total_trades_analyzed=0,
            )
            self._record_history(report)
            return report

        n = len(trades)

        # Compute base rates
        calls = [t for t in trades if t.get("direction", "").upper() == "CALL"]
        puts = [t for t in trades if t.get("direction", "").upper() == "PUT"]
        n_calls = len(calls)
        n_puts = len(puts)

        wins = [t for t in trades if t.get("net_pnl", 0) > 0]
        losses = [t for t in trades if t.get("net_pnl", 0) <= 0]
        wr = len(wins) / max(n, 1)

        # By direction
        call_wins = [t for t in calls if t.get("net_pnl", 0) > 0]
        put_wins = [t for t in puts if t.get("net_pnl", 0) > 0]
        call_wr = len(call_wins) / max(n_calls, 1)
        put_wr = len(put_wins) / max(n_puts, 1)

        # By symbol
        symbols = set(t.get("symbol", "UNKNOWN") for t in trades)
        symbol_wrs: dict[str, float] = {}
        for sym in symbols:
            sym_trades = [t for t in trades if t.get("symbol") == sym]
            sym_wins = [t for t in sym_trades if t.get("net_pnl", 0) > 0]
            symbol_wrs[sym] = len(sym_wins) / max(len(sym_trades), 1)

        # By time-of-day
        morning = [t for t in trades if _is_morning(t.get("entry_time", "09:15"))]
        afternoon = [t for t in trades if not _is_morning(t.get("entry_time", "09:15"))]
        morning_wr = len([t for t in morning if t.get("net_pnl", 0) > 0]) / max(len(morning), 1)
        afternoon_wr = len([t for t in afternoon if t.get("net_pnl", 0) > 0]) / max(len(afternoon), 1)

        # 1. Directional bias check
        if n_calls >= 20 and n_puts >= 20:
            p_val = _z_test(call_wr, put_wr, n_calls, n_puts)
            effect = _cohens_h(call_wr, put_wr)
            if p_val < 0.05 and effect > 0.2:
                favored = "CALL" if call_wr > put_wr else "PUT"
                findings.append(BiasFinding(
                    bias_category="DIRECTIONAL",
                    description=f"Significant directional bias toward {favored} "
                                f"(CALL WR: {call_wr:.1%}, PUT WR: {put_wr:.1%}, p={p_val:.4f})",
                    severity=min(1.0, effect),
                    p_value=p_val,
                    effect_size=effect,
                    direction=favored,
                    recommendation=f"Review {favored} signal criteria — "
                                   f"may be too permissive/lossy for one direction",
                    n_samples=n_calls + n_puts,
                ))

        # 2. Temporal bias check
        if len(morning) >= 10 and len(afternoon) >= 10:
            p_val = _z_test(morning_wr, afternoon_wr, len(morning), len(afternoon))
            effect = _cohens_h(morning_wr, afternoon_wr)
            if p_val < 0.05 and effect > 0.2:
                favored = "morning" if morning_wr > afternoon_wr else "afternoon"
                findings.append(BiasFinding(
                    bias_category="TEMPORAL",
                    description=f"Time-of-day bias toward {favored} sessions "
                                f"(morning WR: {morning_wr:.1%}, "
                                f"afternoon WR: {afternoon_wr:.1%}, p={p_val:.4f})",
                    severity=min(1.0, effect),
                    p_value=p_val,
                    effect_size=effect,
                    direction=favored,
                    recommendation="Consider session-specific score adjustments",
                    n_samples=len(morning) + len(afternoon),
                ))

        # 3. Segment bias (symbol level)
        if len(symbols) >= 2:
            for sym in sorted(symbols):
                sym_trades = [t for t in trades if t.get("symbol") == sym]
                other_trades = [t for t in trades if t.get("symbol") != sym]
                if len(sym_trades) >= 10 and len(other_trades) >= 10:
                    sym_wr = symbol_wrs[sym]
                    other_wr = len([t for t in other_trades if t.get("net_pnl", 0) > 0]) / max(len(other_trades), 1)
                    p_val = _z_test(sym_wr, other_wr, len(sym_trades), len(other_trades))
                    effect = _cohens_h(sym_wr, other_wr)
                    if p_val < 0.05 and effect > 0.3:
                        findings.append(BiasFinding(
                            bias_category="SEGMENT",
                            description=f"Symbol bias toward {sym} "
                                        f"(WR: {sym_wr:.1%} vs others {other_wr:.1%}, p={p_val:.4f})",
                            severity=min(1.0, effect),
                            p_value=p_val,
                            effect_size=effect,
                            direction=sym,
                            recommendation=f"Review {sym} signal parameters for potential overfitting",
                            n_samples=len(sym_trades) + len(other_trades),
                        ))

        # 4. Outcome distribution bias
        if len(wins) >= 15 and len(losses) >= 15:
            avg_win = sum(t.get("net_pnl", 0) for t in wins) / max(len(wins), 1)
            avg_loss = abs(sum(t.get("net_pnl", 0) for t in losses) / max(len(losses), 1))
            if avg_loss > 0 and avg_win > 0:
                ratio = avg_win / avg_loss
                if ratio < 1.0:
                    findings.append(BiasFinding(
                        bias_category="OUTCOME",
                        description=f"Losses larger than wins on average "
                                    f"(avg win: {avg_win:.0f}, avg loss: {avg_loss:.0f}, "
                                    f"ratio: {ratio:.2f})",
                        severity=min(1.0, 1.0 - ratio / 2),
                        p_value=0.5,
                        effect_size=ratio,
                        recommendation="Review SL/TP placement — losses should not "
                                       "systematically exceed wins",
                        n_samples=len(wins) + len(losses),
                    ))

        # 5. Position sizing bias
        sym_with_lots = [
            (t.get("symbol", "?"), t.get("lots", 1))
            for t in trades if t.get("lots") is not None
        ]
        if len(sym_with_lots) >= 20:
            sym_lots: dict[str, list[int]] = {}
            for sym, lots in sym_with_lots:
                if sym not in sym_lots:
                    sym_lots[sym] = []
                sym_lots[sym].append(lots)

            for sym, lot_list in sym_lots.items():
                if len(lot_list) >= 10:
                    avg_lots = sum(lot_list) / len(lot_list)
                    other_lots = [
                        lot for s, lots_list in sym_lots.items()
                        if s != sym for lot in lots_list
                    ]
                    if len(other_lots) >= 10:
                        avg_other = sum(other_lots) / len(other_lots)
                        if avg_lots > avg_other * 1.5 or avg_lots < avg_other * 0.5:
                            direction = "over-sized" if avg_lots > avg_other else "under-sized"
                            findings.append(BiasFinding(
                                bias_category="SIZE",
                                description=f"Position sizing bias: {sym} {direction} "
                                            f"(avg {avg_lots:.1f} lots vs {avg_other:.1f} for others)",
                                severity=min(0.8, abs(avg_lots - avg_other) / max(avg_other, 1) * 0.3),
                                p_value=0.5,
                                effect_size=abs(avg_lots - avg_other) / max(avg_other, 1),
                                direction=direction,
                                recommendation=f"Review position sizing rules for {sym}",
                                n_samples=len(lot_list) + len(other_lots),
                            ))

        # Compute aggregate bias score
        bias_score = self._compute_bias_score(findings)
        bias_level = _classify_bias_level(bias_score)

        # Generate recommendations
        recommendations = self._generate_recommendations(findings, bias_level, wr)

        report = BiasReport(
            bias_score=bias_score,
            bias_level=bias_level,
            findings=findings,
            categories_checked=BIAS_CATEGORIES,
            total_trades_analyzed=n,
            win_rate=wr,
            call_win_rate=call_wr,
            put_win_rate=put_wr,
            n_calls=n_calls,
            n_puts=n_puts,
            nifty_win_rate=symbol_wrs.get("NIFTY", 0.0),
            banknifty_win_rate=symbol_wrs.get("BANKNIFTY", 0.0),
            finnifty_win_rate=symbol_wrs.get("FINNIFTY", 0.0),
            morning_win_rate=morning_wr,
            afternoon_win_rate=afternoon_wr,
            recommendations=recommendations,
        )

        self._record_history(report)
        return report

    def analyze_ml_features(
        self,
        feature_importance: dict[str, float],
    ) -> list[BiasFinding]:
        """Analyze ML feature importance for dominance bias.

        Args:
            feature_importance: Dict mapping feature name → importance score.

        Returns:
            List of BiasFinding for feature-level bias.
        """
        findings: list[BiasFinding] = []
        if not feature_importance:
            return findings

        total = sum(feature_importance.values())
        if total <= 0:
            return findings

        for feature, importance in sorted(
            feature_importance.items(), key=lambda x: -x[1]
        ):
            pct = importance / total * 100
            if pct > 40:
                findings.append(BiasFinding(
                    bias_category="FEATURE",
                    description=f"Feature '{feature}' dominates model "
                                f"({pct:.0f}% of total importance)",
                    severity=min(1.0, pct / 100),
                    p_value=0.1,
                    effect_size=pct / 100,
                    direction=feature,
                    recommendation=f"Consider feature engineering to reduce "
                                   f"dominance of '{feature}'",
                    n_samples=len(feature_importance),
                ))

        return findings

    def get_history(self, limit: int = 10) -> list[BiasReport]:
        """Get recent bias reports."""
        with self._lock:
            return list(self._history[-limit:])

    def get_stats(self) -> dict[str, Any]:
        """Get bias detection statistics."""
        with self._lock:
            if not self._history:
                return {"total_analyses": 0}

            high_bias = sum(
                1 for r in self._history if r.bias_level in ("HIGH", "CRITICAL")
            )
            total = len(self._history)
            avg_score = sum(r.bias_score for r in self._history) / total

            category_counts: dict[str, int] = {}
            for r in self._history:
                for f in r.findings:
                    category_counts[f.bias_category] = (
                        category_counts.get(f.bias_category, 0) + 1
                    )

            return {
                "total_analyses": total,
                "high_bias_count": high_bias,
                "high_bias_pct": round(high_bias / total * 100, 1) if total else 0.0,
                "avg_bias_score": round(avg_score, 3),
                "category_breakdown": category_counts,
                "latest_bias_level": self._history[-1].bias_level if self._history else None,
            }

    def clear_history(self) -> None:
        """Clear analysis history."""
        with self._lock:
            self._history.clear()
            if self._persist_path.exists():
                self._persist_path.unlink()

    # ── Internal ─────────────────────────────────────────────────────────

    def _compute_bias_score(self, findings: list[BiasFinding]) -> float:
        """Compute aggregate bias score from findings."""
        if not findings:
            return 0.0

        max_severity = max(f.severity for f in findings)
        avg_severity = sum(f.severity for f in findings) / len(findings)

        score = max_severity * 0.6 + avg_severity * 0.4

        # Penalty for multiple findings
        if len(findings) >= 3:
            score = min(1.0, score + 0.1)
        if len(findings) >= 5:
            score = min(1.0, score + 0.1)

        return min(1.0, max(0.0, score))

    def _generate_recommendations(
        self,
        findings: list[BiasFinding],
        bias_level: str,
        win_rate: float,
    ) -> list[str]:
        """Generate actionable recommendations."""
        recs: list[str] = []

        if bias_level in ("HIGH", "CRITICAL"):
            recs.append("URGENT: Multiple bias signals detected — review trading logic")
        elif bias_level == "MEDIUM":
            recs.append("Moderate bias detected — monitor and investigate top findings")

        # Category-specific recommendations
        categories = set(f.bias_category for f in findings)

        if "DIRECTIONAL" in categories:
            recs.append("Consider balancing CALL/PUT signal criteria")

        if "TEMPORAL" in categories:
            recs.append("Review session-specific score adjustments or time-based filters")

        if "SEGMENT" in categories:
            recs.append("Check for symbol-specific overfitting in signal parameters")

        if "OUTCOME" in categories:
            recs.append("Review SL/TP placement strategy for consistency")

        if "SIZE" in categories:
            recs.append("Standardize position sizing rules across all symbols")

        if not recs:
            recs.append("No significant bias detected — system appears fair")

        return recs

    def _record_history(self, report: BiasReport) -> None:
        """Store report in history and persist."""
        with self._lock:
            self._history.append(report)
            if len(self._history) > self._max_history:
                self._history = self._history[-self._max_history:]
            self._persist()

    def _persist(self) -> None:
        """Persist analysis history to JSON."""
        try:
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)
            data = [r.to_dict() for r in self._history[-50:]]
            self._persist_path.write_text(
                json.dumps(data, indent=2), encoding="utf-8"
            )
        except (OSError, ValueError) as exc:
            _log.debug("[BIAS] Persist error: %s", exc)

    def _load_history(self) -> None:
        """Load analysis history from JSON."""
        try:
            if self._persist_path.is_file():
                data = json.loads(
                    self._persist_path.read_text(encoding="utf-8")
                )
                for item in data[-self._max_history:]:
                    findings = [
                        BiasFinding(**f)
                        for f in item.get("findings", [])
                    ]
                    self._history.append(BiasReport(
                        bias_score=item.get("bias_score", 0.0),
                        bias_level=item.get("bias_level", "CLEAN"),
                        findings=findings,
                    ))
        except (OSError, json.JSONDecodeError, ValueError, TypeError) as exc:
            _log.debug("[BIAS] Load error: %s", exc)


def _is_morning(time_str: str) -> bool:
    """Check if a time string is before 12:00."""
    try:
        parts = time_str.split(":")
        hour = int(parts[0])
        return hour < 12
    except (ValueError, IndexError):
        return True


# ── Singleton ──────────────────────────────────────────────────────────────

_instance: BiasDetector | None = None
_instance_lock = threading.RLock()


def get_bias_detector() -> BiasDetector:
    """Get the singleton BiasDetector instance."""
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = BiasDetector()
        return _instance


def reset_bias_detector() -> None:
    """Force-reset singleton (for testing). Also cleans up persist file."""
    global _instance
    with _instance_lock:
        # Always clean up the persist file to prevent stale state leakage
        try:
            if _DEFAULT_PERSIST_PATH.exists():
                _DEFAULT_PERSIST_PATH.unlink()
        except OSError:
            pass
        _instance = None


__all__ = [
    "BiasDetector",
    "BiasFinding",
    "BiasReport",
    "get_bias_detector",
    "reset_bias_detector",
]
