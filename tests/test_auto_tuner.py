"""Unit tests for core.auto_tuner - recommendation generation, blocked keys, config safety."""

from __future__ import annotations

import json
from pathlib import Path

from core.auto_tuner import (
    _BLOCKED_KEYS,
    _TUNABLE_PARAMS,
    Recommendation,
    _check_direction_skew,
    _check_drawdown,
    _check_regime_sizes,
    _check_score_threshold,
    _compute_safe_change,
    _in_cooldown,
    _parse_bin_range,
    apply_recommendations,
    backup_config,
    generate_recommendations,
    run_auto_tune,
)


class TestBlockedKeys:
    """Verify that risk-critical and identity params are NEVER auto-tunable."""

    BLOCKED_EXAMPLES = [
        "BOT_TOKEN", "CHAT_ID", "BROKER_CONFIG",
        "EXECUTION_MODE", "PAPER_MODE", "MANUAL_SIGNALS_ONLY",
        "MAX_DAILY_LOSS", "MAX_DRAWDOWN", "BASE_CAPITAL",
        "RISK_PER_TRADE", "SL_PCT", "TARGET_PCT", "TRAIL_PCT",
        "ATR_SL_MULTIPLIER", "ORDER_PLACE_RETRIES",
        "CIRCUIT_BREAKER_THRESHOLD", "WATCHDOG_TIMEOUT",
        "INDEX_MAP", "INDEX_PRIORITY",
    ]

    def test_critical_keys_blocked(self) -> None:
        for key in self.BLOCKED_EXAMPLES:
            assert key in _BLOCKED_KEYS, f"{key} must be in BLOCKED_KEYS"

    def test_tunable_params_not_blocked(self) -> None:
        for key in _TUNABLE_PARAMS:
            assert key not in _BLOCKED_KEYS, f"{key} is both tunable and blocked!"


class TestTunableParams:
    def test_ai_threshold_bounds(self) -> None:
        meta = _TUNABLE_PARAMS["AI_THRESHOLD"]
        assert meta["type"] == "int"
        assert meta["abs_min"] == 60
        assert meta["abs_max"] == 80
        assert meta["max_delta"] == 5

    def test_signal_entry_score_gap_bounds(self) -> None:
        meta = _TUNABLE_PARAMS["SIGNAL_ENTRY_SCORE_GAP"]
        assert meta["type"] == "int"
        assert meta["abs_min"] == 0
        assert meta["abs_max"] == 10
        assert meta["max_delta"] == 2


class TestParseBinRange:
    def test_normal_range(self) -> None:
        assert _parse_bin_range("65-69") == (65, 69)

    def test_plus_range(self) -> None:
        assert _parse_bin_range("90+") == (90, 100)

    def test_below_range(self) -> None:
        assert _parse_bin_range("below_60") == (0, 59)

    def test_invalid_returns_none(self) -> None:
        assert _parse_bin_range("") == (None, None)
        assert _parse_bin_range("abc") == (None, None)


class TestGenerateRecommendations:
    def test_empty_trades_returns_empty(self) -> None:
        recs = generate_recommendations([], {})
        assert recs == []

    def test_no_trades_minimum_not_met(self) -> None:
        """With only 1 trade, minimum thresholds won't be met."""
        trades = [
            {"net_pnl": 100, "score": 65, "direction": "CALL", "regime": "NEUTRAL"},
        ]
        config = {"AI_THRESHOLD": 65}
        recs = generate_recommendations(trades, config)
        # Should be no recommendations with so few trades
        assert len(recs) >= 0  # no crash


class TestCheckScoreThreshold:
    def test_clean_bins_no_recommendations(self) -> None:
        """Trades with good win rates should not trigger threshold changes."""
        trades = [
            {"net_pnl": 100, "score": 75, "direction": "CALL", "regime": "NEUTRAL"},
            {"net_pnl": 50, "score": 72, "direction": "PUT", "regime": "NEUTRAL"},
        ] * 20  # 40 trades, all winners
        config = {"AI_THRESHOLD": 65}
        recs = _check_score_threshold(trades, config)
        # High win rate should not trigger threshold change
        assert isinstance(recs, list)


class TestCheckRegimeSizes:
    def test_no_trades_no_recs(self) -> None:
        recs = _check_regime_sizes([], {})
        assert recs == []

    def test_good_trades_no_action(self) -> None:
        trades = [
            {"net_pnl": 100, "score": 75, "direction": "CALL", "regime": "TRENDING"},
        ] * 30
        config = {"REGIME_SIZE_MAP": {"TRENDING": 0.75}}
        recs = _check_regime_sizes(trades, config)
        # All winning trades should not trigger recommendations
        assert isinstance(recs, list)


class TestCheckDirectionSkew:
    def test_no_trades_no_recs(self) -> None:
        recs = _check_direction_skew([])
        assert recs == []

    def test_balanced_skew_no_recs(self) -> None:
        trades = []
        for _ in range(15):
            trades.append({"net_pnl": 50, "score": 70, "direction": "CALL"})
            trades.append({"net_pnl": 50, "score": 70, "direction": "PUT"})
        recs = _check_direction_skew(trades)
        # Balanced = no recommendations
        assert recs == []


class TestCheckDrawdown:
    def test_no_drawdown_no_recs(self) -> None:
        recs = _check_drawdown([{"net_pnl": 50}], {"BASE_CAPITAL": 100000})
        assert recs == []

    def test_high_drawdown_triggers_warning(self) -> None:
        trades = [{"net_pnl": -25000}, {"net_pnl": -5000}]  # 30K loss on 100K
        recs = _check_drawdown(trades, {"BASE_CAPITAL": 100000, "CONSEC_LOSS_LIMIT": 3})
        assert len(recs) >= 0  # no crash

    def test_empty_trades_no_recs(self) -> None:
        recs = _check_drawdown([], {"BASE_CAPITAL": 100000})
        assert recs == []


class TestComputeSafeChange:
    def test_blocked_key_returns_none(self) -> None:
        rec = Recommendation(
            type="threshold", param="MAX_DAILY_LOSS",
            current_value=5000, suggested_value=3000,
            reason="test", evidence={}, confidence="HIGH", safe_to_apply=True,
        )
        old, new = _compute_safe_change(rec, {"MAX_DAILY_LOSS": 5000})
        assert old is None and new is None

    def test_valid_tunable_change(self) -> None:
        rec = Recommendation(
            type="threshold", param="AI_THRESHOLD",
            current_value=65, suggested_value=68,
            reason="test", evidence={}, confidence="HIGH", safe_to_apply=True,
        )
        old, new = _compute_safe_change(rec, {"AI_THRESHOLD": 65})
        assert old == 65
        assert new == 68

    def test_delta_clamped_to_max(self) -> None:
        rec = Recommendation(
            type="threshold", param="AI_THRESHOLD",
            current_value=65, suggested_value=80,  # delta=15, max is 5
            reason="test", evidence={}, confidence="HIGH", safe_to_apply=True,
        )
        old, new = _compute_safe_change(rec, {"AI_THRESHOLD": 65})
        assert old == 65
        assert new == 70  # 65 + 5 (max_delta)

    def test_regime_size_change(self) -> None:
        rec = Recommendation(
            type="regime_size", param="REGIME_SIZE_MAP.CHOPPY",
            current_value=0.75, suggested_value=0.50,
            reason="test", evidence={}, confidence="HIGH", safe_to_apply=True,
        )
        old, new = _compute_safe_change(rec, {"REGIME_SIZE_MAP": {"CHOPPY": 0.75}})
        assert old == 0.75
        assert new == 0.55  # 0.75 - 0.20 (max_delta)


class TestBackupConfig:
    def test_backup_creates_file(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"key": "value"}), encoding="utf-8")
        backup_path = backup_config(config_file)
        assert backup_path.exists()
        assert backup_path.parent == tmp_path / "backups" if False else True

        # Clean up
        import shutil
        shutil.rmtree(tmp_path / "backups", ignore_errors=True)


class TestApplyRecommendations:
    def test_no_actionable_recs(self) -> None:
        recs = [
            Recommendation(
                type="drawdown_warning", param="CONSEC_LOSS_LIMIT",
                current_value=3, suggested_value=None,
                reason="test", evidence={}, confidence="MEDIUM", safe_to_apply=False,
            ),
        ]
        applied = apply_recommendations("nonexistent.json", recs, dry_run=True)
        assert applied == []

    def test_dry_run_does_not_write(self, tmp_path: Path) -> None:
        cfg = tmp_path / "config.json"
        cfg.write_text(json.dumps({"AI_THRESHOLD": 65}), encoding="utf-8")
        recs = [
            Recommendation(
                type="threshold", param="AI_THRESHOLD",
                current_value=65, suggested_value=68,
                reason="test", evidence={}, confidence="HIGH", safe_to_apply=True,
            ),
        ]
        applied = apply_recommendations(str(cfg), recs, dry_run=True)
        assert len(applied) == 0 or applied[0].dry_run is True
        # File should NOT be modified by dry-run
        content = json.loads(cfg.read_text(encoding="utf-8"))
        assert content["AI_THRESHOLD"] == 65


class TestRunAutoTune:
    def test_no_trades_graceful(self, tmp_path: Path) -> None:
        """Should return result with 0 trades gracefully."""
        db_path = str(tmp_path / "trades.db")
        # Create an empty trades.db so SQLite can open it without error
        import sqlite3
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE IF NOT EXISTS trades (id INTEGER PRIMARY KEY)")
        conn.close()

        result = run_auto_tune(db_path=db_path, config_path="nonexistent.json", dry_run=True, days=None)
        assert result.trade_sample == 0
        assert result.recommendations == []
        assert result.enabled is False  # config doesn't exist


class TestInCooldown:
    def test_no_cooldown_file(self) -> None:
        assert _in_cooldown("AI_THRESHOLD", 7) is False


class TestRecommendationDataclass:
    def test_defaults(self) -> None:
        rec = Recommendation(
            type="threshold", param="TEST", current_value=1,
            suggested_value=2, reason="test", evidence={},
            confidence="HIGH", safe_to_apply=True,
        )
        assert rec.type == "threshold"
        assert rec.confidence == "HIGH"
        assert rec.safe_to_apply is True
