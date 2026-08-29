
import json
import sqlite3
from pathlib import Path

from core.pure_index_signal import compute_index_score
from core.signals.signal_tracker import SignalTracker


def test_compute_index_score_supports_uncapped_raw_mode():
    cfg = {}
    raw = compute_index_score(
        "UP", "UP", 100.0, 99.0, 1.0, 2.0, 1.0, 1.0, 1.3, "BULLISH",
        signal_cfg=cfg, vol_ratio_min=1.2, learning_score_bonus=8, rsi=55,
        return_raw=True,
    )
    normalized = compute_index_score(
        "UP", "UP", 100.0, 99.0, 1.0, 2.0, 1.0, 1.0, 1.3, "BULLISH",
        signal_cfg=cfg, vol_ratio_min=1.2, learning_score_bonus=8, rsi=55,
    )
    assert raw >= normalized
    assert raw > 100
    assert normalized == 100


def test_active_opportunity_is_suppressed_even_if_price_changes(tmp_path):
    db = tmp_path / "signals.db"
    tracker = SignalTracker(db)
    base = {
        "symbol": "RELIANCE",
        "category": "LARGE_CAP_EQUITY",
        "direction": "CALL",
        "price": 100.0,
        "stop_loss": 97.0,
        "target_1": 104.0,
        "target_2": 108.0,
        "score": 100,
        "raw_score": 145,
        "tier": "STRONG",
        "regime": "TREND",
        "dedup_cooldown_secs": 900,
    }
    first = tracker.record_generated_signal(base, [])
    changed = dict(base)
    changed.update(price=101.25, stop_loss=98.21, target_1=105.30, target_2=109.08)
    second = tracker.record_generated_signal(changed, [])
    assert first
    assert second == ""


def test_v18_config_defaults_protect_manual_signal_mode():
    cfg = json.loads(Path("json/config.json").read_text(encoding="utf-8"))
    assert cfg["EXECUTION_MODE"] == "SIGNAL_ONLY"
    assert cfg["ENABLE_TELEGRAM_EXECUTE_BUTTON"] is False
    assert cfg["ML_REQUIRED_FOR_ALERTS"] is True
    assert cfg["MAX_ALERTS_PER_CYCLE"] == 10
    assert cfg["MAX_ALERTS_PER_WINDOW"] == 20
    assert cfg["MAX_ALERTS_PER_DAY"] == 100
    assert cfg["LEGACY_SYSTEM_BROADCAST_ENABLED"] is False
