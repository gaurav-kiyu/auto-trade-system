"""Tests for core/strategy_registry.py — Strategy Registry Engine (Phase 13)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from core.strategy_registry import (
    FeatureStoreEntry,
    StrategyRecord,
    StrategyRegistryEngine,
    StrategyRegistryReport,
    get_strategy_registry,
    reset_strategy_registry,
)

# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_registry() -> None:
    """Reset singleton before and after each test."""
    reset_strategy_registry()
    p = Path("json/strategy_registry.json")
    if p.exists():
        p.unlink()
    yield
    reset_strategy_registry()


@pytest.fixture
def engine() -> StrategyRegistryEngine:
    return get_strategy_registry()


@pytest.fixture
def populated_engine(engine: StrategyRegistryEngine) -> StrategyRegistryEngine:
    engine.register_strategy(
        strategy_id="ma_crossover_v1",
        name="MA Crossover",
        version="1.0.0",
        asset_types=["NIFTY", "BANKNIFTY"],
        description="Golden/death cross 20/50 EMA",
        author="quant-team",
        features=["ema_20", "ema_50", "adx", "volume"],
        initial_state="PAPER_ONLY",
        tags=["trend", "ema"],
    )
    engine.register_strategy(
        strategy_id="mean_reversion_v1",
        name="Mean Reversion",
        version="2.1.0",
        asset_types=["NIFTY"],
        description="Bollinger Band reversion",
        features=["bb_upper", "bb_lower", "rsi"],
        initial_state="LIVE_APPROVED",
    )
    engine.register_strategy(
        strategy_id="straddle_v1",
        name="Straddle Strategy",
        version="0.5.0",
        asset_types=["BANKNIFTY", "FINNIFTY"],
        description="ATM straddle debit",
        features=["iv_rank", "implied_move"],
        initial_state="DONT_RUN",
    )
    return engine


# ── StrategyRecord Tests ─────────────────────────────────────────────────────


class TestStrategyRecord:
    def test_default_values(self) -> None:
        record = StrategyRecord(strategy_id="test", name="Test")
        assert record.strategy_id == "test"
        assert record.name == "Test"
        assert record.version == ""
        assert record.state == "PAPER_ONLY"
        assert record.asset_types == []
        assert record.total_trades == 0
        assert record.total_pnl == 0.0

    def test_win_rate_no_trades(self) -> None:
        record = StrategyRecord(strategy_id="t", name="T")
        assert record.win_rate == 0.0

    def test_win_rate_all_wins(self) -> None:
        record = StrategyRecord(strategy_id="t", name="T")
        record.total_wins = 10
        assert record.win_rate == 100.0

    def test_win_rate_mixed(self) -> None:
        record = StrategyRecord(strategy_id="t", name="T")
        record.total_wins = 7
        record.total_losses = 3
        assert record.win_rate == 70.0

    def test_is_runnable_paper(self) -> None:
        record = StrategyRecord(strategy_id="t", name="T", state="PAPER_ONLY")
        assert record.is_runnable is True

    def test_is_runnable_live(self) -> None:
        record = StrategyRecord(strategy_id="t", name="T", state="LIVE_APPROVED")
        assert record.is_runnable is True

    def test_is_runnable_dont_run(self) -> None:
        record = StrategyRecord(strategy_id="t", name="T", state="DONT_RUN")
        assert record.is_runnable is False

    def test_is_runnable_deprecated(self) -> None:
        record = StrategyRecord(strategy_id="t", name="T", state="DEPRECATED")
        assert record.is_runnable is False

    def test_is_live_approved(self) -> None:
        record = StrategyRecord(strategy_id="t", name="T", state="LIVE_APPROVED")
        assert record.is_live_approved is True
        record.state = "PAPER_ONLY"
        assert record.is_live_approved is False

    def test_record_trade_win(self) -> None:
        record = StrategyRecord(strategy_id="t", name="T")
        record.record_trade(pnl=150.0, won=True)
        assert record.total_trades == 1
        assert record.total_wins == 1
        assert record.total_losses == 0
        assert record.total_pnl == 150.0

    def test_record_trade_loss(self) -> None:
        record = StrategyRecord(strategy_id="t", name="T")
        record.record_trade(pnl=-50.0, won=False)
        assert record.total_trades == 1
        assert record.total_wins == 0
        assert record.total_losses == 1
        assert record.total_pnl == -50.0

    def test_record_trade_multiple(self) -> None:
        record = StrategyRecord(strategy_id="t", name="T")
        for _ in range(5):
            record.record_trade(pnl=100.0, won=True)
        for _ in range(3):
            record.record_trade(pnl=-50.0, won=False)
        assert record.total_trades == 8
        assert record.total_wins == 5
        assert record.total_losses == 3
        assert record.total_pnl == 350.0

    def test_to_dict_contains_all_keys(self) -> None:
        record = StrategyRecord(strategy_id="s1", name="S1", version="1.0")
        d = record.to_dict()
        keys = {
            "strategy_id", "name", "version", "state", "asset_types",
            "description", "author", "features", "config_snapshot",
            "registered_at", "last_state_change", "state_change_notes",
            "total_trades", "total_wins", "total_losses", "total_pnl", "tags",
        }
        assert set(d.keys()) == keys


# ── FeatureStoreEntry Tests ─────────────────────────────────────────────────


class TestFeatureStoreEntry:
    def test_default_values(self) -> None:
        entry = FeatureStoreEntry(feature_name="ema_20")
        assert entry.feature_name == "ema_20"
        assert entry.strategies == []
        assert entry.description == ""
        assert entry.feature_type == "indicator"

    def test_to_dict(self) -> None:
        entry = FeatureStoreEntry(
            feature_name="adx",
            strategies=["s1", "s2"],
            description="Average Directional Index",
            feature_type="indicator",
        )
        d = entry.to_dict()
        assert d["feature_name"] == "adx"
        assert d["strategies"] == ["s1", "s2"]
        assert d["feature_type"] == "indicator"


# ── StrategyRegistryReport Tests ─────────────────────────────────────────────


class TestStrategyRegistryReport:
    def test_empty_report(self) -> None:
        report = StrategyRegistryReport()
        assert report.n_strategies == 0
        assert report.summary_text() != ""

    def test_summary_text_contains_counts(self) -> None:
        report = StrategyRegistryReport(
            n_strategies=5,
            n_features=12,
            total_trades_all=100,
            total_pnl_all=5000.0,
        )
        text = report.summary_text()
        assert "5" in text
        assert "12" in text
        assert "100" in text
        assert "5000" in text

    def test_summary_text_recommendations(self) -> None:
        report = StrategyRegistryReport(
            recommendations=["Review deprecated strategies", "Add more features"],
        )
        text = report.summary_text()
        assert "Review" in text or "review" in text
        assert "features" in text

    def test_to_dict_contains_keys(self) -> None:
        report = StrategyRegistryReport(
            n_strategies=3,
            by_state={"PAPER_ONLY": 2, "LIVE_APPROVED": 1},
        )
        d = report.to_dict()
        assert d["n_strategies"] == 3
        assert d["by_state"]["PAPER_ONLY"] == 2


# ── StrategyRegistryEngine Tests ─────────────────────────────────────────────


class TestStrategyRegistryEngine:
    def test_singleton_consistency(self) -> None:
        e1 = get_strategy_registry()
        e2 = get_strategy_registry()
        assert e1 is e2

    def test_reset(self) -> None:
        e1 = get_strategy_registry()
        reset_strategy_registry()
        e2 = get_strategy_registry()
        assert e1 is not e2

    # ── Registration ──────────────────────────────────────────────────────

    def test_register_strategy_basic(self, engine: StrategyRegistryEngine) -> None:
        record = engine.register_strategy(
            strategy_id="test_v1",
            name="Test Strategy",
            version="1.0.0",
        )
        assert record.strategy_id == "test_v1"
        assert record.name == "Test Strategy"
        assert record.version == "1.0.0"
        assert record.state == "PAPER_ONLY"

    def test_register_strategy_with_all_fields(
        self, engine: StrategyRegistryEngine
    ) -> None:
        record = engine.register_strategy(
            strategy_id="full_v1",
            name="Full Strategy",
            version="2.0.0",
            asset_types=["NIFTY", "BANKNIFTY"],
            description="A comprehensive strategy",
            author="quant-team",
            features=["ema_20", "ema_50", "rsi"],
            initial_state="PAPER_ONLY",
            tags=["trend", "momentum"],
        )
        assert record.asset_types == ["NIFTY", "BANKNIFTY"]
        assert "ema_20" in record.features
        assert "trend" in record.tags

    def test_register_strategy_uppercases_state(
        self, engine: StrategyRegistryEngine
    ) -> None:
        record = engine.register_strategy(
            strategy_id="case_test",
            name="Case Test",
            initial_state="paper_only",
        )
        assert record.state == "PAPER_ONLY"

    def test_register_strategy_invalid_state_defaults_to_paper(
        self, engine: StrategyRegistryEngine
    ) -> None:
        record = engine.register_strategy(
            strategy_id="invalid_state",
            name="Invalid",
            initial_state="INVALID_STATE",
        )
        assert record.state == "PAPER_ONLY"

    def test_register_strategy_updates_feature_store(
        self, engine: StrategyRegistryEngine
    ) -> None:
        engine.register_strategy(
            strategy_id="feat_test",
            name="Feature Test",
            features=["alpha", "beta"],
        )
        feats = engine.get_features_for_strategy("feat_test")
        assert len(feats) == 2
        assert feats[0].feature_name == "alpha"

    def test_register_strategy_persists_to_json(
        self, engine: StrategyRegistryEngine
    ) -> None:
        engine.register_strategy(strategy_id="persist_test", name="Persist")
        path = Path("json/strategy_registry.json")
        assert path.exists()
        data = json.loads(path.read_text())
        assert "persist_test" in data["strategies"]

    # ── State Management ──────────────────────────────────────────────────

    def test_set_strategy_state_success(
        self, engine: StrategyRegistryEngine
    ) -> None:
        engine.register_strategy(strategy_id="s1", name="S1")
        result = engine.set_strategy_state(
            "s1", "LIVE_APPROVED", notes="Passed certification"
        )
        assert result is True
        record = engine.get_strategy("s1")
        assert record is not None
        assert record.state == "LIVE_APPROVED"
        assert record.state_change_notes == "Passed certification"

    def test_set_strategy_state_invalid_target(
        self, engine: StrategyRegistryEngine
    ) -> None:
        engine.register_strategy(strategy_id="s1", name="S1")
        result = engine.set_strategy_state("s1", "INVALID")
        assert result is False

    def test_set_strategy_state_nonexistent(
        self, engine: StrategyRegistryEngine
    ) -> None:
        result = engine.set_strategy_state("non_existent", "PAPER_ONLY")
        assert result is False

    def test_set_strategy_state_deprecated(
        self, engine: StrategyRegistryEngine
    ) -> None:
        engine.register_strategy(
            strategy_id="s1", name="S1", initial_state="LIVE_APPROVED"
        )
        engine.set_strategy_state("s1", "DEPRECATED", notes="Replaced by v2")
        record = engine.get_strategy("s1")
        assert record is not None
        assert record.state == "DEPRECATED"

    # ── Query Methods ─────────────────────────────────────────────────────

    def test_get_strategy_by_id(
        self, populated_engine: StrategyRegistryEngine
    ) -> None:
        record = populated_engine.get_strategy("ma_crossover_v1")
        assert record is not None
        assert record.name == "MA Crossover"

    def test_get_strategy_by_id_nonexistent(
        self, engine: StrategyRegistryEngine
    ) -> None:
        record = engine.get_strategy("non_existent")
        assert record is None

    def test_get_strategies_by_state(
        self, populated_engine: StrategyRegistryEngine
    ) -> None:
        paper = populated_engine.get_strategies_by_state("PAPER_ONLY")
        assert len(paper) == 1
        assert paper[0].strategy_id == "ma_crossover_v1"

    def test_get_strategies_by_state_live(
        self, populated_engine: StrategyRegistryEngine
    ) -> None:
        live = populated_engine.get_strategies_by_state("LIVE_APPROVED")
        assert len(live) == 1

    def test_get_strategies_by_state_dont_run(
        self, populated_engine: StrategyRegistryEngine
    ) -> None:
        dont_run = populated_engine.get_strategies_by_state("DONT_RUN")
        assert len(dont_run) == 1

    def test_get_runnable_strategies(
        self, populated_engine: StrategyRegistryEngine
    ) -> None:
        runnable = populated_engine.get_runnable_strategies()
        assert len(runnable) == 2  # PAPER_ONLY + LIVE_APPROVED

    def test_get_approved_strategies(
        self, populated_engine: StrategyRegistryEngine
    ) -> None:
        approved = populated_engine.get_approved_strategies()
        assert len(approved) == 1
        assert approved[0].strategy_id == "mean_reversion_v1"

    def test_get_strategies_for_asset(
        self, populated_engine: StrategyRegistryEngine
    ) -> None:
        """Both ma_crossover_v1 (PAPER_ONLY) and mean_reversion_v1 (LIVE_APPROVED)
        support NIFTY and are runnable, so we expect 2."""
        nifty_strats = populated_engine.get_strategies_for_asset("NIFTY")
        assert len(nifty_strats) == 2

    def test_get_strategies_for_asset_banknifty(
        self, populated_engine: StrategyRegistryEngine
    ) -> None:
        banknifty = populated_engine.get_strategies_for_asset("BANKNIFTY")
        assert len(banknifty) == 1  # only ma_crossover is PAPER_ONLY and runnable

    # ── Trade Recording ───────────────────────────────────────────────────

    def test_record_trade_for_strategy(
        self, engine: StrategyRegistryEngine
    ) -> None:
        engine.register_strategy(strategy_id="t1", name="T1")
        result = engine.record_trade("t1", pnl=250.0, won=True)
        assert result is True
        stats = engine.get_strategy_stats("t1")
        assert stats is not None
        assert stats["total_trades"] == 1
        assert stats["total_pnl"] == 250.0
        assert stats["win_rate"] == 100.0

    def test_record_trade_nonexistent(
        self, engine: StrategyRegistryEngine
    ) -> None:
        result = engine.record_trade("nope", pnl=100.0, won=True)
        assert result is False

    def test_get_strategy_stats_nonexistent(
        self, engine: StrategyRegistryEngine
    ) -> None:
        stats = engine.get_strategy_stats("nope")
        assert stats is None

    def test_get_strategy_stats_returns_avg_pnl(
        self, engine: StrategyRegistryEngine
    ) -> None:
        engine.register_strategy(strategy_id="t1", name="T1")
        engine.record_trade("t1", 200.0, True)
        engine.record_trade("t1", 100.0, True)
        stats = engine.get_strategy_stats("t1")
        assert stats is not None
        assert stats["avg_pnl_per_trade"] == 150.0

    def test_record_multiple_trades_updates_win_rate(
        self, engine: StrategyRegistryEngine
    ) -> None:
        engine.register_strategy(strategy_id="t1", name="T1")
        for _ in range(7):
            engine.record_trade("t1", 100.0, True)
        for _ in range(3):
            engine.record_trade("t1", -50.0, False)
        stats = engine.get_strategy_stats("t1")
        assert stats is not None
        assert stats["total_trades"] == 10
        assert stats["win_rate"] == 70.0

    # ── Feature Store ─────────────────────────────────────────────────────

    def test_register_feature(self, engine: StrategyRegistryEngine) -> None:
        entry = engine.register_feature(
            feature_name="custom_indicator",
            description="Custom volume-weighted indicator",
            feature_type="derived",
            strategies=["strat_a"],
        )
        assert entry.feature_name == "custom_indicator"
        assert entry.feature_type == "derived"

    def test_get_features_for_strategy(
        self, engine: StrategyRegistryEngine
    ) -> None:
        engine.register_strategy(
            strategy_id="feat_strat",
            name="Feat Strat",
            features=["ema_20", "rsi", "adx"],
        )
        feats = engine.get_features_for_strategy("feat_strat")
        assert len(feats) == 3
        names = [f.feature_name for f in feats]
        assert "ema_20" in names
        assert "rsi" in names
        assert "adx" in names

    def test_get_features_for_nonexistent_strategy(
        self, engine: StrategyRegistryEngine
    ) -> None:
        feats = engine.get_features_for_strategy("nope")
        assert feats == []

    # ── Report ────────────────────────────────────────────────────────────

    def test_get_report_counts(
        self, populated_engine: StrategyRegistryEngine
    ) -> None:
        report = populated_engine.get_report()
        assert report.n_strategies == 3

    def test_get_report_by_state(
        self, populated_engine: StrategyRegistryEngine
    ) -> None:
        report = populated_engine.get_report()
        assert report.by_state.get("PAPER_ONLY", 0) >= 1
        assert report.by_state.get("LIVE_APPROVED", 0) >= 1
        assert report.by_state.get("DONT_RUN", 0) >= 1

    def test_get_report_by_asset(
        self, populated_engine: StrategyRegistryEngine
    ) -> None:
        report = populated_engine.get_report()
        assert report.by_asset.get("NIFTY", 0) >= 1
        assert report.by_asset.get("BANKNIFTY", 0) >= 1

    def test_get_report_active_strategies(
        self, populated_engine: StrategyRegistryEngine
    ) -> None:
        report = populated_engine.get_report()
        assert len(report.active_strategies) == 2

    def test_get_report_top_features(
        self, populated_engine: StrategyRegistryEngine
    ) -> None:
        report = populated_engine.get_report()
        assert report.n_features >= 3

    def test_get_report_recommendations(
        self, engine: StrategyRegistryEngine
    ) -> None:
        report = engine.get_report()
        assert len(report.recommendations) > 0

    # ── Stats ─────────────────────────────────────────────────────────────

    def test_get_stats(
        self, populated_engine: StrategyRegistryEngine
    ) -> None:
        stats = populated_engine.get_stats()
        assert stats["n_strategies"] == 3
        assert stats["n_runnable"] == 2
        assert stats["n_live_approved"] == 1

    def test_get_stats_empty(self, engine: StrategyRegistryEngine) -> None:
        stats = engine.get_stats()
        assert stats["n_strategies"] == 0
        assert stats["n_runnable"] == 0

    # ── Edge Cases ────────────────────────────────────────────────────────

    def test_register_strategy_with_same_id_overwrites(
        self, engine: StrategyRegistryEngine
    ) -> None:
        engine.register_strategy(strategy_id="dup", name="Original")
        engine.register_strategy(strategy_id="dup", name="Overwritten")
        record = engine.get_strategy("dup")
        assert record is not None
        assert record.name == "Overwritten"

    def test_state_transitions_all_states(
        self, engine: StrategyRegistryEngine
    ) -> None:
        engine.register_strategy(strategy_id="s1", name="S1")
        for state in ("DONT_RUN", "PAPER_ONLY", "LIVE_APPROVED", "DEPRECATED"):
            assert engine.set_strategy_state("s1", state) is True
            assert engine.get_strategy("s1").state == state

    def test_register_feature_twice_preserves_latest(
        self, engine: StrategyRegistryEngine
    ) -> None:
        engine.register_feature("f1", description="First description")
        engine.register_feature("f1", description="Updated description")
        engine.register_strategy(
            strategy_id="s1", name="S1", features=["f1"]
        )
        feats = engine.get_features_for_strategy("s1")
        assert len(feats) == 1
        assert feats[0].description == "Updated description"
