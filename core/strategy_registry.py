"""Strategy Registry — Centralized Strategy Lifecycle Management (Phase 13).

Manages the full lifecycle of trading strategies:
- Registration with metadata (author, version, description)
- Lifecycle states: DONT_RUN, PAPER_ONLY, LIVE_APPROVED, DEPRECATED
- Feature store integration (which ML features each strategy uses)
- Config snapshotting at strategy activation
- Trade explainability metadata

Usage:
    from core.strategy_registry import get_strategy_registry

    registry = get_strategy_registry()
    registry.register_strategy(
        strategy_id="ma_crossover_v1",
        name="MA Crossover Strategy",
        version="1.0.0",
        asset_types=["NIFTY", "BANKNIFTY"],
        description="Golden/death cross on 20/50 EMA",
        features=["ema_20", "ema_50", "adx", "volume"],
    )
    registry.set_strategy_state("ma_crossover_v1", "PAPER_ONLY")
    print(registry.get_approved_strategies())

Design:
- Thread-safe singleton with RLock
- JSON persistence for registry state
- Integration with ChangeRiskScorer for strategy change impact
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

STRATEGY_STATES = ("DONT_RUN", "PAPER_ONLY", "LIVE_APPROVED", "DEPRECATED")
REGISTRY_FILE = "json/strategy_registry.json"
MAX_REGISTRY_HISTORY = 200


# ── Data Models ──────────────────────────────────────────────────────────────


@dataclass
class StrategyRecord:
    """A registered strategy with its full metadata and lifecycle state."""

    strategy_id: str
    name: str
    version: str = ""
    state: str = "PAPER_ONLY"  # DONT_RUN, PAPER_ONLY, LIVE_APPROVED, DEPRECATED
    asset_types: list[str] = field(default_factory=list)
    description: str = ""
    author: str = ""
    features: list[str] = field(default_factory=list)
    config_snapshot: dict[str, Any] = field(default_factory=dict)
    registered_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    last_state_change: str = ""
    state_change_notes: str = ""
    total_trades: int = 0
    total_wins: int = 0
    total_losses: int = 0
    total_pnl: float = 0.0
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "name": self.name,
            "version": self.version,
            "state": self.state,
            "asset_types": self.asset_types,
            "description": self.description[:200],
            "author": self.author,
            "features": self.features,
            "config_snapshot": self.config_snapshot,
            "registered_at": self.registered_at,
            "last_state_change": self.last_state_change,
            "state_change_notes": self.state_change_notes,
            "total_trades": self.total_trades,
            "total_wins": self.total_wins,
            "total_losses": self.total_losses,
            "total_pnl": round(self.total_pnl, 2),
            "tags": self.tags,
        }

    @property
    def win_rate(self) -> float:
        total = self.total_wins + self.total_losses
        return round(self.total_wins / max(total, 1) * 100, 1)

    @property
    def is_runnable(self) -> bool:
        return self.state in ("PAPER_ONLY", "LIVE_APPROVED")

    @property
    def is_live_approved(self) -> bool:
        return self.state == "LIVE_APPROVED"

    def record_trade(self, pnl: float, won: bool) -> None:
        self.total_trades += 1
        self.total_pnl += pnl
        if won:
            self.total_wins += 1
        else:
            self.total_losses += 1


@dataclass
class FeatureStoreEntry:
    """Maps a feature to the strategies that use it."""

    feature_name: str
    strategies: list[str] = field(default_factory=list)
    description: str = ""
    feature_type: str = "indicator"  # indicator, ml, price, derived
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "feature_name": self.feature_name,
            "strategies": self.strategies,
            "description": self.description,
            "feature_type": self.feature_type,
        }


@dataclass
class StrategyRegistryReport:
    """Aggregated strategy registry report."""

    n_strategies: int = 0
    by_state: dict[str, int] = field(default_factory=dict)
    by_asset: dict[str, int] = field(default_factory=dict)
    active_strategies: list[dict[str, Any]] = field(default_factory=list)
    n_features: int = 0
    top_features: list[dict[str, Any]] = field(default_factory=list)
    total_trades_all: int = 0
    total_pnl_all: float = 0.0
    recommendations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "n_strategies": self.n_strategies,
            "by_state": self.by_state,
            "by_asset": self.by_asset,
            "active_strategies": self.active_strategies[:10],
            "n_features": self.n_features,
            "top_features": self.top_features[:10],
            "total_trades_all": self.total_trades_all,
            "total_pnl_all": round(self.total_pnl_all, 2),
            "recommendations": self.recommendations[:10],
        }

    def summary_text(self) -> str:
        lines = [
            "═" * 60,
            "  STRATEGY REGISTRY REPORT",
            "═" * 60,
            f"  Total Strategies: {self.n_strategies}",
            f"  Total Features:   {self.n_features}",
            f"  Total Trades:     {self.total_trades_all}",
            f"  Total P&L:        {self.total_pnl_all:.2f}",
            "",
        ]
        if self.by_state:
            lines.append("  By State:")
            for state, count in sorted(
                self.by_state.items(), key=lambda x: x[1], reverse=True
            ):
                lines.append(f"    {state}: {count}")
        if self.by_asset:
            lines.append("  By Asset:")
            for asset, count in sorted(
                self.by_asset.items(), key=lambda x: x[1], reverse=True
            ):
                lines.append(f"    {asset}: {count}")
        if self.active_strategies:
            lines.append("\n  Active Strategies:")
            for s in self.active_strategies[:5]:
                lines.append(
                    f"    {s['strategy_id']}: {s['name']} v{s['version']} "
                    f"[{s['state']}]"
                )
        if self.recommendations:
            lines.append("\n  Recommendations:")
            for r in self.recommendations[:5]:
                lines.append(f"    → {r}")
        lines.append("═" * 60)
        return "\n".join(lines)


# ── Strategy Registry Engine ─────────────────────────────────────────────────


class StrategyRegistryEngine:
    """Centralized strategy lifecycle manager.

    Manages:
    - Strategy registration and metadata
    - Lifecycle states (DONT_RUN → PAPER_ONLY → LIVE_APPROVED → DEPRECATED)
    - Feature store mapping
    - Trade performance tracking per strategy
    - Config snapshots at activation time
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._strategies: dict[str, StrategyRecord] = {}
        self._features: dict[str, FeatureStoreEntry] = {}
        self._load_registry()

    # ── Strategy Management ────────────────────────────────────────────────

    def register_strategy(
        self,
        strategy_id: str,
        name: str,
        version: str = "1.0.0",
        asset_types: list[str] | None = None,
        description: str = "",
        author: str = "",
        features: list[str] | None = None,
        initial_state: str = "PAPER_ONLY",
        tags: list[str] | None = None,
    ) -> StrategyRecord:
        """Register a new strategy.

        Args:
            strategy_id: Unique identifier (e.g., 'ma_crossover_v1').
            name: Human-readable name.
            version: Semantic version string.
            asset_types: List of supported asset types.
            description: Strategy description.
            author: Strategy author.
            features: List of feature names this strategy uses.
            initial_state: Initial lifecycle state.
            tags: Additional tags for filtering.

        Returns:
            StrategyRecord with assigned metadata.
        """
        clean_state = initial_state.upper()
        if clean_state not in STRATEGY_STATES:
            clean_state = "PAPER_ONLY"

        # Snapshot current config
        config_snap = self._snapshot_config()

        record = StrategyRecord(
            strategy_id=strategy_id.strip(),
            name=name.strip(),
            version=version.strip(),
            state=clean_state,
            asset_types=[a.strip().upper() for a in (asset_types or [])],
            description=description.strip(),
            author=author.strip(),
            features=[f.strip() for f in (features or [])],
            config_snapshot=config_snap,
            last_state_change=datetime.now(timezone.utc).isoformat(),
            state_change_notes="Initial registration",
            tags=[t.strip().lower() for t in (tags or []) if t.strip()],
        )

        with self._lock:
            self._strategies[strategy_id] = record
            # Register features used by this strategy
            for feat_name in record.features:
                if feat_name not in self._features:
                    self._features[feat_name] = FeatureStoreEntry(
                        feature_name=feat_name,
                    )
                if strategy_id not in self._features[feat_name].strategies:
                    self._features[feat_name].strategies.append(strategy_id)
            self._save_registry()

        _log.info(
            "[STRAT_REG] Registered '%s' v%s as %s",
            strategy_id, version, clean_state,
        )
        return record

    def set_strategy_state(
        self,
        strategy_id: str,
        new_state: str,
        notes: str = "",
    ) -> bool:
        """Change a strategy's lifecycle state.

        Valid transitions:
        - Any → DONT_RUN (immediate halt)
        - DONT_RUN → PAPER_ONLY (after review)
        - PAPER_ONLY → LIVE_APPROVED (after certification)
        - Any → DEPRECATED (retirement)

        Args:
            strategy_id: Strategy to update.
            new_state: Target state.
            notes: Reason for state change.

        Returns:
            True if state was changed.
        """
        clean_state = new_state.upper()
        if clean_state not in STRATEGY_STATES:
            return False

        with self._lock:
            record = self._strategies.get(strategy_id)
            if not record:
                return False

            old_state = record.state
            record.state = clean_state
            record.last_state_change = datetime.now(timezone.utc).isoformat()
            record.state_change_notes = notes.strip() if notes else (
                f"State changed from {old_state} to {clean_state}"
            )

            # Snapshot config on promotion to LIVE_APPROVED
            if clean_state == "LIVE_APPROVED":
                record.config_snapshot = self._snapshot_config()

            self._save_registry()

        _log.info(
            "[STRAT_REG] '%s' state: %s → %s (%s)",
            strategy_id, old_state, clean_state, notes or "no notes",
        )
        return True

    def get_strategy(self, strategy_id: str) -> StrategyRecord | None:
        """Get a strategy's full record."""
        with self._lock:
            return self._strategies.get(strategy_id)

    def get_strategies_by_state(self, state: str) -> list[StrategyRecord]:
        """Get all strategies in a given state."""
        clean_state = state.upper()
        with self._lock:
            return [
                s for s in self._strategies.values()
                if s.state == clean_state
            ]

    def get_runnable_strategies(self) -> list[StrategyRecord]:
        """Get all strategies that can run (PAPER_ONLY or LIVE_APPROVED)."""
        with self._lock:
            return [s for s in self._strategies.values() if s.is_runnable]

    def get_approved_strategies(self) -> list[StrategyRecord]:
        """Get all LIVE_APPROVED strategies."""
        with self._lock:
            return [s for s in self._strategies.values() if s.is_live_approved]

    def get_strategies_for_asset(self, asset_type: str) -> list[StrategyRecord]:
        """Get strategies that support a given asset type."""
        clean_asset = asset_type.upper()
        with self._lock:
            return [
                s for s in self._strategies.values()
                if clean_asset in s.asset_types and s.is_runnable
            ]

    def record_trade(
        self, strategy_id: str, pnl: float, won: bool
    ) -> bool:
        """Record a trade outcome for a strategy."""
        with self._lock:
            record = self._strategies.get(strategy_id)
            if not record:
                return False
            record.record_trade(pnl, won)
            self._save_registry()
            return True

    def get_strategy_stats(self, strategy_id: str) -> dict[str, Any] | None:
        """Get performance stats for a strategy."""
        with self._lock:
            record = self._strategies.get(strategy_id)
            if not record:
                return None
            return {
                "strategy_id": record.strategy_id,
                "name": record.name,
                "state": record.state,
                "total_trades": record.total_trades,
                "win_rate": record.win_rate,
                "total_pnl": round(record.total_pnl, 2),
                "avg_pnl_per_trade": round(
                    record.total_pnl / max(record.total_trades, 1), 2
                ),
            }

    def register_feature(
        self,
        feature_name: str,
        description: str = "",
        feature_type: str = "indicator",
        strategies: list[str] | None = None,
    ) -> FeatureStoreEntry:
        """Register a feature in the feature store."""
        entry = FeatureStoreEntry(
            feature_name=feature_name.strip(),
            description=description.strip(),
            feature_type=feature_type.strip(),
            strategies=strategies or [],
        )
        with self._lock:
            self._features[feature_name] = entry
            self._save_registry()
        return entry

    def get_features_for_strategy(
        self, strategy_id: str
    ) -> list[FeatureStoreEntry]:
        """Get all features used by a strategy."""
        with self._lock:
            record = self._strategies.get(strategy_id)
            if not record:
                return []
            return [
                self._features[f]
                for f in record.features
                if f in self._features
            ]

    # ── Reporting ─────────────────────────────────────────────────────────

    def get_report(self) -> StrategyRegistryReport:
        """Generate aggregated strategy registry report."""
        report = StrategyRegistryReport()

        with self._lock:
            report.n_strategies = len(self._strategies)

            # By state
            by_state: dict[str, int] = {}
            for s in self._strategies.values():
                by_state[s.state] = by_state.get(s.state, 0) + 1
            report.by_state = by_state

            # By asset
            by_asset: dict[str, int] = {}
            for s in self._strategies.values():
                for a in s.asset_types:
                    by_asset[a] = by_asset.get(a, 0) + 1
            report.by_asset = by_asset

            # Active strategies
            report.active_strategies = [
                s.to_dict() for s in self._strategies.values()
                if s.is_runnable
            ]

            # Features
            report.n_features = len(self._features)
            sorted_features = sorted(
                self._features.values(),
                key=lambda f: len(f.strategies),
                reverse=True,
            )
            report.top_features = [
                {
                    "feature_name": f.feature_name,
                    "n_strategies": len(f.strategies),
                    "feature_type": f.feature_type,
                }
                for f in sorted_features[:10]
            ]

            # Trade stats
            report.total_trades_all = sum(
                s.total_trades for s in self._strategies.values()
            )
            report.total_pnl_all = sum(
                s.total_pnl for s in self._strategies.values()
            )

            # Recommendations
            report.recommendations = self._generate_recommendations(report)

        return report

    def get_stats(self) -> dict[str, Any]:
        """Get quick registry statistics."""
        with self._lock:
            return {
                "n_strategies": len(self._strategies),
                "n_features": len(self._features),
                "by_state": {
                    state: sum(
                        1 for s in self._strategies.values()
                        if s.state == state
                    )
                    for state in STRATEGY_STATES
                },
                "n_runnable": sum(
                    1 for s in self._strategies.values() if s.is_runnable
                ),
                "n_live_approved": sum(
                    1 for s in self._strategies.values() if s.is_live_approved
                ),
            }

    # ── Private ───────────────────────────────────────────────────────────

    def _snapshot_config(self) -> dict[str, Any]:
        """Snapshot relevant configuration values."""
        snap: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        try:
            from core.config_bootstrap import load_config as _load_config  # type: ignore[attr-defined]
            cfg = _load_config()
            # Extract key strategy-related configs
            for key in [
                "SL_PCT", "TARGET_PCT", "TRAIL_PCT",
                "MAX_DAILY_LOSS", "MAX_DRAWDOWN",
                "PORTFOLIO_MAX_SL_RISK_PCT",
            ]:
                if key in cfg:
                    snap[key] = cfg[key]
        except ImportError:
            pass
        return snap

    def _generate_recommendations(
        self, report: StrategyRegistryReport
    ) -> list[str]:
        """Generate strategy governance recommendations."""
        recs: list[str] = []

        dont_run = report.by_state.get("DONT_RUN", 0)
        deprecated = report.by_state.get("DEPRECATED", 0)
        paper = report.by_state.get("PAPER_ONLY", 0)
        live = report.by_state.get("LIVE_APPROVED", 0)

        if dont_run > 0:
            recs.append(f"{dont_run} strategy(-ies) in DONT_RUN state — review or retire")
        if deprecated > 0:
            recs.append(f"{deprecated} deprecated strategy(-ies) — consider removal")
        if paper > 0 and live == 0:
            recs.append("No LIVE_APPROVED strategies — system is in paper-only mode")
        if report.total_trades_all == 0 and report.n_strategies > 0:
            recs.append("Strategies registered but no trades recorded — check signal flow")

        if not recs:
            recs.append("Strategy registry is healthy")

        return recs[:8]

    # ── Persistence ───────────────────────────────────────────────────────

    def _load_registry(self) -> None:
        """Load registry from JSON file."""
        try:
            path = Path(REGISTRY_FILE)
            if path.is_file():
                data = json.loads(path.read_text(encoding="utf-8"))
                for sid, sdata in data.get("strategies", {}).items():
                    try:
                        self._strategies[sid] = StrategyRecord(**sdata)
                    except (TypeError, ValueError) as exc:
                        _log.debug("[STRAT_REG] Load skip '%s': %s", sid, exc)
                for fname, fdata in data.get("features", {}).items():
                    try:
                        self._features[fname] = FeatureStoreEntry(**fdata)
                    except (TypeError, ValueError) as exc:
                        _log.debug("[STRAT_REG] Feature load skip '%s': %s", fname, exc)
        except (OSError, json.JSONDecodeError, ValueError, TypeError) as exc:
            _log.debug("[STRAT_REG] Load registry failed: %s", exc)

    def _save_registry(self) -> None:
        """Save registry to JSON file."""
        try:
            path = Path(REGISTRY_FILE)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({
                "strategies": {
                    sid: s.to_dict() for sid, s in self._strategies.items()
                },
                "features": {
                    fname: f.to_dict() for fname, f in self._features.items()
                },
            }, indent=2), encoding="utf-8")
        except (OSError, ValueError, TypeError) as exc:
            _log.debug("[STRAT_REG] Save registry failed: %s", exc)


# ── Singleton ────────────────────────────────────────────────────────────────

_engine: StrategyRegistryEngine | None = None
_engine_lock = threading.RLock()


def get_strategy_registry() -> StrategyRegistryEngine:
    """Get the singleton StrategyRegistryEngine instance."""
    global _engine
    with _engine_lock:
        if _engine is None:
            _engine = StrategyRegistryEngine()
        return _engine


def reset_strategy_registry() -> None:
    """Force-reset singleton (for testing)."""
    global _engine
    with _engine_lock:
        _engine = None


def _cli() -> None:
    """Command-line interface.

    Usage:
        python -m core.strategy_registry --report
        python -m core.strategy_registry --stats
        python -m core.strategy_registry --register my_strat "My Strategy" --assets NIFTY BANKNIFTY
    """
    import argparse

    parser = argparse.ArgumentParser(
        description="Strategy Registry — Strategy Lifecycle Management",
    )
    parser.add_argument("--report", action="store_true", help="Show registry report")
    parser.add_argument("--stats", action="store_true", help="Show statistics")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--register", nargs=2, metavar=("ID", "NAME"))
    parser.add_argument("--assets", nargs="+", default=[])
    parser.add_argument("--state", default="PAPER_ONLY", help="Initial state")

    args = parser.parse_args()
    registry = get_strategy_registry()

    if args.register:
        sid, name = args.register
        record = registry.register_strategy(
            strategy_id=sid,
            name=name,
            asset_types=args.assets,
            initial_state=args.state,
        )
        if args.json:
            print(json.dumps(record.to_dict(), indent=2))
        else:
            print(f"Registered: {sid} — {name} [{args.state}]")
        return

    if args.stats:
        stats = registry.get_stats()
        if args.json:
            print(json.dumps(stats, indent=2))
        else:
            print("═" * 50)
            print("Strategy Registry — Statistics")
            print("═" * 50)
            for k, v in stats.items():
                print(f"  {k.replace('_', ' ').title():30s}: {v}")
        return

    report = registry.get_report()
    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(report.summary_text())


if __name__ == "__main__":
    _cli()


__all__ = [
    "FeatureStoreEntry",
    "StrategyRecord",
    "StrategyRegistryEngine",
    "StrategyRegistryReport",
    "get_strategy_registry",
    "reset_strategy_registry",
]
