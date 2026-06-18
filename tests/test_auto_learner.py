"""Unit tests for core.auto_learner - config, state management, threshold adjustment."""

from __future__ import annotations

import json

from pathlib import Path


import pytest

from core.auto_learner import (
    AutoLearner,
    LearnerConfig,
    _atomic_write_state,
    get_auto_learner,
    learner_config_from_cfg,
    reset_auto_learner,
)


class TestLearnerConfig:
    def test_defaults(self) -> None:
        cfg = learner_config_from_cfg({})
        assert cfg.enabled is True
        assert cfg.lookback == 40
        assert cfg.win_score_decay == 2.0
        assert cfg.loss_score_inc == 3.0
        assert cfg.max_bonus == 8
        assert cfg.max_discount == 3
        assert cfg.ai_journal_weight == 0.3

    def test_override(self) -> None:
        cfg = learner_config_from_cfg({
            "AUTO_LEARNER_ENABLED": False,
            "AUTO_LEARNER_LOOKBACK": 20,
            "AUTO_LEARNER_MAX_BONUS": 5,
        })
        assert cfg.enabled is False
        assert cfg.lookback == 20
        assert cfg.max_bonus == 5

    def test_partial_override_preserves_defaults(self) -> None:
        cfg = learner_config_from_cfg({"AUTO_LEARNER_ENABLED": False})
        assert cfg.lookback == 40  # default preserved
        assert cfg.win_score_decay == 2.0


class TestAtomicWrite:
    def test_atomic_write(self, tmp_path: Path) -> None:
        target = tmp_path / "state.json"
        _atomic_write_state(target, json.dumps({"key": "value"}))
        assert target.exists()
        data = json.loads(target.read_text(encoding="utf-8"))
        assert data["key"] == "value"

    def test_atomic_write_creates_parent_dirs(self, tmp_path: Path) -> None:
        target = tmp_path / "subdir" / "nested" / "state.json"
        _atomic_write_state(target, json.dumps({"a": 1}))
        assert target.exists()

    def test_atomic_write_overwrites(self, tmp_path: Path) -> None:
        target = tmp_path / "state.json"
        target.write_text(json.dumps({"old": "data"}), encoding="utf-8")
        _atomic_write_state(target, json.dumps({"new": "data"}))
        data = json.loads(target.read_text(encoding="utf-8"))
        assert data["new"] == "data"


class TestAutoLearnerInit:
    def test_default_state(self) -> None:
        learner = AutoLearner(LearnerConfig(enabled=True))
        assert learner._global_state["score_adj"] == 0
        assert learner._global_state["confidence"] == 0
        assert learner._global_state["streak"] == 0

    def test_disabled_by_config(self) -> None:
        learner = AutoLearner(LearnerConfig(enabled=False))
        delta, reason = learner.threshold_adjustment("NIFTY", "TRENDING", "STRONG", [])
        assert delta == 0
        assert reason == "learner disabled"


class TestAutoLearnerThresholdAdjustment:
    def test_no_trades_returns_zero(self) -> None:
        learner = AutoLearner(LearnerConfig(enabled=True))
        delta, reason = learner.threshold_adjustment("NIFTY", "TRENDING", "STRONG", [])
        # Without trades, should return minimal adjustment
        assert isinstance(delta, int)
        assert isinstance(reason, str)

    def test_capped_at_max_bonus(self) -> None:
        learner = AutoLearner(LearnerConfig(enabled=True, max_bonus=8, max_discount=3))
        trades = [{"net_pnl": 100, "score": 80, "is_winner": True}] * 50
        delta, reason = learner.threshold_adjustment("NIFTY", "TRENDING", "STRONG", trades)
        assert -3 <= delta <= 8

    def test_per_symbol_adjustment(self) -> None:
        learner = AutoLearner(LearnerConfig(enabled=True, per_symbol=True))
        # Manually inject per-symbol state
        learner._symbol_states["NIFTY"] = {"score_adj": 3, "confidence": 0, "streak": 0}
        delta, reason = learner.threshold_adjustment("NIFTY", "TRENDING", "STRONG", [])
        assert "sym_adj" in reason or delta != 0


class TestAutoLearnerRecordExit:
    def test_win_reduces_score_adj(self) -> None:
        learner = AutoLearner(LearnerConfig(enabled=True, win_score_decay=2.0))
        learner._global_state["score_adj"] = 5
        learner.record_exit("NIFTY", "WIN", regime="TRENDING", strength="STRONG", net_pnl=100)
        assert learner._global_state["score_adj"] < 5  # should decrease on win
        assert learner._global_state["confidence"] >= 0

    def test_loss_increases_score_adj(self) -> None:
        learner = AutoLearner(LearnerConfig(enabled=True, loss_score_inc=3.0))
        learner._global_state["score_adj"] = 0
        learner.record_exit("NIFTY", "LOSS", net_pnl=-100)
        assert learner._global_state["score_adj"] > 0  # should increase on loss

    def test_zombie_does_not_change_state(self) -> None:
        learner = AutoLearner(LearnerConfig(enabled=True))
        original_adj = learner._global_state["score_adj"]
        original_conf = learner._global_state["confidence"]
        learner.record_exit("NIFTY", "ZOMBIE")
        assert learner._global_state["score_adj"] == original_adj
        assert learner._global_state["confidence"] == original_conf

    def test_breakeven_treated_as_loss(self) -> None:
        learner = AutoLearner(LearnerConfig(enabled=True, loss_score_inc=3.0))
        learner._global_state["score_adj"] = 0
        learner.record_exit("NIFTY", "BREAKEVEN", net_pnl=0)
        assert learner._global_state["score_adj"] > 0

    def test_disabled_skips_update(self) -> None:
        learner = AutoLearner(LearnerConfig(enabled=False))
        original_adj = learner._global_state["score_adj"]
        learner.record_exit("NIFTY", "LOSS", net_pnl=-100)
        assert learner._global_state["score_adj"] == original_adj


class TestAutoLearnerPersistence:
    def test_save_and_load(self, tmp_path: Path) -> None:
        state_file = str(tmp_path / "learner_state.json")
        cfg = LearnerConfig(enabled=True, state_file=state_file)

        # Create and modify
        learner = AutoLearner(cfg)
        learner._global_state["score_adj"] = 5
        learner._global_state["confidence"] = 3
        learner.save()

        # Load into a new instance
        learner2 = AutoLearner(cfg)
        learner2.load()
        assert learner2._global_state["score_adj"] == 5
        assert learner2._global_state["confidence"] == 3

    def test_load_missing_file_starts_fresh(self) -> None:
        learner = AutoLearner(LearnerConfig(enabled=True, state_file="/nonexistent/path.json"))
        learner.load()  # should not raise
        assert learner._global_state["score_adj"] == 0

    def test_load_from_existing_state_dict(self) -> None:
        learner = AutoLearner(LearnerConfig(enabled=True, state_file="/nonexistent/path.json"))
        learner.load(existing_state={"score_adj": 7, "confidence": 2, "streak": 3})
        assert learner._global_state["score_adj"] == 7
        assert learner._global_state["confidence"] == 2
        assert learner._global_state["streak"] == 3

    def test_disabled_save_skips_write(self, tmp_path: Path) -> None:
        state_file = str(tmp_path / "disabled_state.json")
        cfg = LearnerConfig(enabled=False, state_file=state_file)
        learner = AutoLearner(cfg)
        learner.save()
        assert not Path(state_file).exists()


class TestAutoLearnerStateSync:
    def test_export_global_state(self) -> None:
        learner = AutoLearner(LearnerConfig(enabled=True))
        learner._global_state["score_adj"] = 3
        exported = learner.export_global_state()
        assert exported["score_adj"] == 3
        # Verify it's a copy
        exported["score_adj"] = 99
        assert learner._global_state["score_adj"] == 3

    def test_import_global_state(self) -> None:
        learner = AutoLearner(LearnerConfig(enabled=True))
        learner.import_global_state({"score_adj": 4, "confidence": 2, "streak": 1})
        assert learner._global_state["score_adj"] == 4
        assert learner._global_state["confidence"] == 2


class TestRegimeWinRates:
    def test_empty_regime_matrix(self) -> None:
        learner = AutoLearner(LearnerConfig(enabled=True))
        wr = learner.regime_win_rates()
        assert wr == {}

    def test_with_data(self) -> None:
        learner = AutoLearner(LearnerConfig(enabled=True))
        learner._regime_matrix = {
            "TRENDING": {
                "STRONG": {"count": 10, "wins": 7, "net": 500.0},
            },
        }
        wr = learner.regime_win_rates()
        assert wr["TRENDING"]["STRONG"] == pytest.approx(70.0, rel=0.1)

    def test_avoid_division_by_zero(self) -> None:
        learner = AutoLearner(LearnerConfig(enabled=True))
        learner._regime_matrix = {
            "TEST": {
                "WEAK": {"count": 0, "wins": 0, "net": 0.0},
            },
        }
        wr = learner.regime_win_rates()
        assert wr["TEST"]["WEAK"] == 0.0


class TestSummaryStr:
    def test_empty_summary(self) -> None:
        learner = AutoLearner(LearnerConfig(enabled=True))
        summary = learner.summary_str()
        assert "AutoLearner" in summary
        assert "score_adj" in summary or "adj=" in summary

    def test_with_regime_data(self) -> None:
        learner = AutoLearner(LearnerConfig(enabled=True))
        learner._regime_matrix = {
            "TRENDING": {"STRONG": {"count": 5, "wins": 4, "net": 300.0}},
        }
        summary = learner.summary_str()
        assert "TRENDING" in summary


class TestSingletonFactory:
    def test_get_auto_learner_singleton(self) -> None:
        reset_auto_learner()
        l1 = get_auto_learner({"AUTO_LEARNER_ENABLED": True})
        l2 = get_auto_learner({"AUTO_LEARNER_ENABLED": True})
        assert l1 is l2
        reset_auto_learner()

    def test_reset_auto_learner(self) -> None:
        reset_auto_learner()
        l1 = get_auto_learner({})
        reset_auto_learner()
        l2 = get_auto_learner({})
        assert l1 is not l2


class TestPerSymbolState:
    def test_per_symbol_tracking(self) -> None:
        learner = AutoLearner(LearnerConfig(enabled=True, per_symbol=True))
        learner.record_exit("NIFTY", "WIN", net_pnl=100)
        learner.record_exit("NIFTY", "WIN", net_pnl=50)
        assert "NIFTY" in learner._symbol_states
        # Two wins should reduce score_adj
        assert learner._symbol_states["NIFTY"]["score_adj"] <= 0

    def test_per_symbol_disabled(self) -> None:
        learner = AutoLearner(LearnerConfig(enabled=True, per_symbol=False))
        learner.record_exit("NIFTY", "WIN", net_pnl=100)
        assert learner._symbol_states == {}  # no per-symbol tracking
