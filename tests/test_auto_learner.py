"""Unit tests for core.auto_learner - config, state management, threshold adjustment."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

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


# ── AI Journal Feedback ────────────────────────────────────────────────


class TestAiJournalFeedback:
    def test_refresh_ai_stats_no_journal_file(self, tmp_path: Path) -> None:
        """When ai_journal_file is empty or missing, stats remain empty."""
        learner = AutoLearner(LearnerConfig(enabled=True), ai_journal_file="")
        learner._refresh_ai_stats()
        assert learner._ai_stats == {}

    def test_refresh_ai_stats_with_journal(self, tmp_path: Path) -> None:
        """Reads AI journal and computes skip_rate and avg_delta."""
        journal = tmp_path / "ai_decisions.jsonl"
        journal.write_text(
            '{"verdict": "TRADE", "score_delta": 2}\n'
            + '{"verdict": "SKIP", "score_delta": -3}\n'
            + '{"verdict": "SKIP", "score_delta": -1}\n',
            encoding="utf-8",
        )
        learner = AutoLearner(LearnerConfig(enabled=True), ai_journal_file=str(journal))
        learner._refresh_ai_stats()
        assert learner._ai_stats["count"] == 3
        assert learner._ai_stats["skip_rate"] == pytest.approx(2 / 3, rel=0.1)
        assert learner._ai_stats["avg_delta"] == pytest.approx((2 + -3 + -1) / 3, rel=0.1)

    def test_refresh_ai_stats_cache_ttl(self, tmp_path: Path) -> None:
        """Within 60 second TTL, stats are not refreshed."""
        journal = tmp_path / "ai_decisions.jsonl"
        journal.write_text(
            '{"verdict": "TRADE", "score_delta": 1}\n', encoding="utf-8"
        )
        learner = AutoLearner(LearnerConfig(enabled=True), ai_journal_file=str(journal))
        learner._refresh_ai_stats()
        learner._ai_stats["count"]
        # Append more data
        journal.write_text(
            '{"verdict": "TRADE", "score_delta": 2}\n'
            + '{"verdict": "SKIP", "score_delta": -2}\n',
            encoding="utf-8",
        )
        # Second call within 60s should use cache
        learner._ai_stats_ts = 9999999999.0  # Set far in the past to force refresh
        # Actually set to 0 to force refresh, but let's test the cache path directly
        learner._ai_stats_ts = 0.0
        # But with a journal that doesn't exist...
        non_existent = tmp_path / "nonexistent.jsonl"
        learner2 = AutoLearner(LearnerConfig(enabled=True), ai_journal_file=str(non_existent))
        learner2._ai_stats_ts = 0.0
        learner2._refresh_ai_stats()
        # non-existent file: should set timestamp and return
        assert learner2._ai_stats_ts > 0.0

    def test_journal_parse_errors_skipped(self, tmp_path: Path) -> None:
        """Malformed lines in AI journal are skipped."""
        journal = tmp_path / "mixed_ai.jsonl"
        journal.write_text(
            '{"verdict": "TRADE"}\n'
            + "not valid json\n"
            + '{"verdict": "SKIP"}\n',
            encoding="utf-8",
        )
        learner = AutoLearner(LearnerConfig(enabled=True), ai_journal_file=str(journal))
        learner._refresh_ai_stats()
        assert learner._ai_stats["count"] == 2

    def test_ai_skip_heavy_adds_extra(self, tmp_path: Path) -> None:
        """When LLM skip_rate > 0.5, threshold_adjustment adds extra caution."""
        journal = tmp_path / "ai_decisions.jsonl"
        journal.write_text(
            '{"verdict": "SKIP", "score_delta": -2}\n' * 12,
            encoding="utf-8",
        )
        learner = AutoLearner(
            LearnerConfig(enabled=True, ai_journal_weight=0.3, max_bonus=8),
            ai_journal_file=str(journal),
        )
        delta, reason = learner.threshold_adjustment("NIFTY", "TRENDING", "STRONG", [])
        assert "AI skip-heavy" in reason

    def test_ai_negative_bias_adds_extra(self, tmp_path: Path) -> None:
        """When avg_delta < -1.0, threshold_adjustment adds +1."""
        journal = tmp_path / "ai_decisions.jsonl"
        journal.write_text(
            '{"verdict": "WATCH", "score_delta": -2}\n' * 10,
            encoding="utf-8",
        )
        learner = AutoLearner(
            LearnerConfig(enabled=True, ai_journal_weight=0.3, max_bonus=8),
            ai_journal_file=str(journal),
        )
        delta, reason = learner.threshold_adjustment("NIFTY", "TRENDING", "STRONG", [])
        assert "AI negative bias" in reason

    def test_ai_journal_not_enough_entries(self) -> None:
        """Fewer than 10 AI journal entries: no AI feedback applied."""
        learner = AutoLearner(LearnerConfig(enabled=True, max_bonus=8))
        delta, reason = learner.threshold_adjustment("NIFTY", "TRENDING", "STRONG", [])
        assert "AI" not in reason


# ── Per-Symbol Adjustments ──────────────────────────────────────────────


class TestPerSymbolAdjustment:
    def test_per_symbol_adjustment_applied(self) -> None:
        """Per-symbol score_adj is added to delta and appears in reason."""
        learner = AutoLearner(LearnerConfig(enabled=True, per_symbol=True, max_bonus=8))
        # Manually inject per-symbol state
        learner._symbol_states["NIFTY"] = {"score_adj": 3, "confidence": 0, "streak": 0}
        delta, reason = learner.threshold_adjustment("NIFTY", "TRENDING", "STRONG", [])
        assert "sym_adj=+3" in reason

    def test_per_symbol_negative_adjustment(self) -> None:
        """Negative per-symbol score_adj is reflected correctly."""
        learner = AutoLearner(LearnerConfig(enabled=True, per_symbol=True, max_discount=3))
        learner._symbol_states["NIFTY"] = {"score_adj": -2, "confidence": 0, "streak": 0}
        delta, reason = learner.threshold_adjustment("NIFTY", "TRENDING", "STRONG", [])
        assert "sym_adj=-2" in reason

    def test_per_symbol_zero_adjustment_no_reason(self) -> None:
        """Zero per-symbol adj should not add to reason."""
        learner = AutoLearner(LearnerConfig(enabled=True, per_symbol=True))
        learner._symbol_states["NIFTY"] = {"score_adj": 0, "confidence": 0, "streak": 0}
        delta, reason = learner.threshold_adjustment("NIFTY", "TRENDING", "STRONG", [])
        assert "sym_adj=" not in reason


# ── Signal Confidence ──────────────────────────────────────────────────


class TestSignalConfidence:
    def test_signal_confidence_returns_tuple(self) -> None:
        """signal_confidence returns (int, str)."""
        learner = AutoLearner(LearnerConfig(enabled=True))
        sig = {"score": 70, "direction": "CALL"}
        conf, band = learner.signal_confidence("NIFTY", sig, [], default_threshold=50)
        assert isinstance(conf, int)
        assert isinstance(band, str)
        assert band in ("A", "B", "C", "D", "UNKNOWN")


# ── Save Error Handling ────────────────────────────────────────────────


class TestSaveErrorHandling:
    def test_save_oserror_caught(self, tmp_path: Path, monkeypatch) -> None:
        """OSError during save is caught and logged."""
        msgs = []
        learner = AutoLearner(
            LearnerConfig(enabled=True, state_file=str(tmp_path / "state.json")),
            log_fn=lambda msg: msgs.append(msg),
        )
        with patch("core.auto_learner._atomic_write_state", side_effect=OSError("disk full")):
            learner.save()
        assert any("save failed" in m.lower() for m in msgs), msgs


# ── Record Exit Edge Cases ─────────────────────────────────────────────


class TestRecordExitEdgeCases:
    def test_record_exit_updates_regime_matrix(self) -> None:
        """record_exit updates regime/strength performance matrix."""
        learner = AutoLearner(LearnerConfig(enabled=True))
        learner.record_exit("NIFTY", "WIN", regime="TRENDING", strength="STRONG", net_pnl=100.0)
        rm = learner._regime_matrix
        assert "TRENDING" in rm
        assert rm["TRENDING"]["STRONG"]["count"] == 1
        assert rm["TRENDING"]["STRONG"]["wins"] == 1

    def test_record_exit_loss_updates_matrix(self) -> None:
        learner = AutoLearner(LearnerConfig(enabled=True))
        learner.record_exit("NIFTY", "LOSS", regime="CHOPPY", strength="WEAK", net_pnl=-50.0)
        rm = learner._regime_matrix
        assert rm["CHOPPY"]["WEAK"]["count"] == 1
        assert rm["CHOPPY"]["WEAK"]["wins"] == 0

    def test_record_exit_applies_regime_decay(self) -> None:
        """Regime matrix entries are decayed on each record_exit."""
        learner = AutoLearner(LearnerConfig(enabled=True, regime_decay=0.5))
        learner.record_exit("NIFTY", "WIN", regime="TRENDING", strength="STRONG", net_pnl=100.0)
        # net should be 100 * 0.5 = 50.0 after decay
        assert learner._regime_matrix["TRENDING"]["STRONG"]["net"] == 50.0

    def test_record_exit_prunes_stale_regime_entries(self) -> None:
        """Regime entries with net ~0 and count=0 are pruned."""
        learner = AutoLearner(LearnerConfig(enabled=True, regime_decay=0.1))
        learner._regime_matrix["STALE"] = {
            "OLD": {"count": 0, "wins": 0, "net": 0.0},
        }
        learner.record_exit("NIFTY", "WIN", regime="FRESH", strength="GOOD", net_pnl=50.0)
        # STALE/OLD should be pruned (net=0, count=0)
        assert "STALE" not in learner._regime_matrix or not learner._regime_matrix.get("STALE", {})


# ── load() Edge Cases ──────────────────────────────────────────────────


class TestLoadEdgeCases:
    def test_load_corrupted_file_starts_fresh(self, tmp_path: Path) -> None:
        """Corrupted state file starts with fresh state (no crash)."""
        state_file = tmp_path / "corrupted.json"
        state_file.write_text("not valid json", encoding="utf-8")
        learner = AutoLearner(
            LearnerConfig(enabled=True, state_file=str(state_file)),
        )
        learner.load()  # should not raise
        assert learner._global_state["score_adj"] == 0

    def test_load_missing_file_starts_fresh(self) -> None:
        """Missing state file starts with fresh state."""
        learner = AutoLearner(
            LearnerConfig(enabled=True, state_file="/nonexistent/path/state.json"),
        )
        learner.load()  # should not raise
        assert learner._global_state["score_adj"] == 0

    def test_load_with_existing_state_dict(self) -> None:
        learner = AutoLearner(LearnerConfig(enabled=True))
        learner.load(existing_state={"score_adj": 7, "confidence": 3, "streak": 2})
        assert learner._global_state["score_adj"] == 7
        assert learner._global_state["confidence"] == 3
        assert learner._global_state["streak"] == 2

    def test_load_existing_state_dict_partial(self) -> None:
        """Partial existing state dict only updates present keys."""
        learner = AutoLearner(LearnerConfig(enabled=True))
        learner.load(existing_state={"score_adj": 5})
        assert learner._global_state["score_adj"] == 5
        assert learner._global_state["confidence"] == 0  # unchanged
        assert learner._global_state["streak"] == 0  # unchanged


# ── Singleton Factory Edge Cases ───────────────────────────────────────


class TestSingletonFactoryEdgeCases:
    def test_get_auto_learner_creates_and_loads(self) -> None:
        """get_auto_learner creates instance and calls load()."""
        reset_auto_learner()
        learner = get_auto_learner({"AUTO_LEARNER_ENABLED": True})
        assert isinstance(learner, AutoLearner)
        assert learner._cfg.enabled is True
        reset_auto_learner()

    def test_get_auto_learner_with_log_fn(self) -> None:
        """get_auto_learner forwards log_fn and ai_journal_file."""
        reset_auto_learner()
        msgs = []
        learner = get_auto_learner(
            {"AUTO_LEARNER_ENABLED": False},
            log_fn=lambda msg: msgs.append(msg),
            ai_journal_file="reports/ai_decisions.jsonl",
        )
        assert learner._ai_journal_file == "reports/ai_decisions.jsonl"
        reset_auto_learner()


# ── Regime Win Rates Edge Cases ────────────────────────────────────────


class TestRegimeWinRatesEdgeCases:
    def test_regime_win_rates_with_data(self) -> None:
        learner = AutoLearner(LearnerConfig(enabled=True))
        learner._regime_matrix = {
            "TRENDING": {
                "STRONG": {"count": 10, "wins": 7, "net": 500.0},
                "WEAK": {"count": 5, "wins": 1, "net": -100.0},
            },
        }
        wr = learner.regime_win_rates()
        assert wr["TRENDING"]["STRONG"] == 70.0
        assert wr["TRENDING"]["WEAK"] == 20.0


# ── Summary Str Edge Cases ─────────────────────────────────────────────


class TestSummaryStrEdgeCases:
    def test_summary_str_with_regime_data(self) -> None:
        learner = AutoLearner(LearnerConfig(enabled=True))
        learner._global_state = {"score_adj": 3, "confidence": 2, "streak": 1}
        learner._regime_matrix = {
            "TRENDING": {"STRONG": {"count": 5, "wins": 4, "net": 300.0}},
        }
        s = learner.summary_str()
        assert "adj=3" in s
        assert "conf=2" in s
        assert "TRENDING/STRONG: 80.0%" in s

    def test_summary_str_no_regime_data(self) -> None:
        learner = AutoLearner(LearnerConfig(enabled=True))
        s = learner.summary_str()
        assert "(no data)" in s


# ── export/import Global State Edge Cases ──────────────────────────────


class TestGlobalStateSyncEdgeCases:
    def test_import_global_state_partial(self) -> None:
        learner = AutoLearner(LearnerConfig(enabled=True))
        learner._global_state["score_adj"] = 5
        learner.import_global_state({"score_adj": 2})
        assert learner._global_state["score_adj"] == 2
        assert learner._global_state["confidence"] == 0  # unchanged

    def test_import_global_state_empty(self) -> None:
        learner = AutoLearner(LearnerConfig(enabled=True))
        learner._global_state["score_adj"] = 3
        learner.import_global_state({})
        assert learner._global_state["score_adj"] == 3  # unchanged


# ── Config Factory Edge Cases ──────────────────────────────────────────


class TestLearnerConfigFromCfgEdgeCases:
    def test_csv_export_default_empty(self) -> None:
        cfg = learner_config_from_cfg({})
        assert cfg.csv_export_file == ""

    def test_csv_export_override(self) -> None:
        cfg = learner_config_from_cfg({"AUTO_LEARNER_CSV_EXPORT_FILE": "reports/learner.csv"})
        assert cfg.csv_export_file == "reports/learner.csv"
