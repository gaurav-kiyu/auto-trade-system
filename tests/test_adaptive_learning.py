# Unit tests for core.adaptive_learning (pure; no index_trader import).
from __future__ import annotations

from core.adaptive_learning import (
    adaptive_threshold_adjustment,
    clamp_learning_state,
    live_signal_confidence,
    recent_trade_learning_snapshot,
    update_learning_after_exit,
)


def _exit_trade(net_pnl: float, regime: str = "TRENDING", strength: str = "STRONG") -> dict:
    return {"action": "EXIT", "net_pnl": net_pnl, "regime": regime, "strength": strength}


def test_recent_snapshot_counts_wins_and_loss_streak():
    trades = [_exit_trade(40), _exit_trade(30), _exit_trade(-10), _exit_trade(-5)]
    ls = {"confidence": 0, "score_adj": 0, "streak": 0}
    snap = recent_trade_learning_snapshot(trades, 40, ls)
    assert snap["count"] == 4
    assert snap["loss_streak"] == 2
    assert snap["win_rate"] == 50.0


def test_adaptive_tightens_on_weak_history():
    trades = [
        _exit_trade(-120),
        _exit_trade(-90),
        _exit_trade(-80),
        _exit_trade(-60),
        _exit_trade(80),
        _exit_trade(50),
    ]
    ls = {"confidence": -3, "score_adj": 2, "streak": -2}
    snap = recent_trade_learning_snapshot(trades, 40, ls)
    delta, why = adaptive_threshold_adjustment(snap, regime="TRENDING", strength="STRONG", enabled=True, max_bonus=8, max_discount=3)
    assert delta >= 6
    assert "confidence" in why.lower() or "weak" in why.lower() or "loss streak" in why.lower()


def test_adaptive_disabled_returns_zero():
    snap = recent_trade_learning_snapshot([], 40, {"confidence": 0, "score_adj": 0, "streak": 0})
    d, w = adaptive_threshold_adjustment(snap, enabled=False)
    assert d == 0 and w == "adaptive off"


def test_live_signal_confidence_band():
    snap = recent_trade_learning_snapshot(
        [_exit_trade(40), _exit_trade(30), _exit_trade(20), _exit_trade(25), _exit_trade(10), _exit_trade(15)],
        40,
        {"confidence": 0, "score_adj": 0, "streak": 0},
    )
    sig = {
        "score": 88,
        "threshold": 75,
        "vol_ratio": 1.3,
        "mkt_regime": "TRENDING",
        "strength": "STRONG",
        "breakout_ok": True,
    }
    conf, band = live_signal_confidence(sig, default_threshold=75, trade_snap=snap)
    assert 1 <= conf <= 99
    assert band in ("A", "B", "C", "D")


def test_update_learning_after_exit_win_then_loss():
    st = {"streak": 0, "score_adj": 0, "confidence": 0}
    update_learning_after_exit(st, "WIN")
    assert st["streak"] >= 1
    update_learning_after_exit(st, "LOSS")
    assert st["streak"] == 0


def test_clamp_learning_state():
    st = {"score_adj": 99, "confidence": -99, "streak": 999}
    clamp_learning_state(st)
    assert st["score_adj"] == 10
    assert st["confidence"] == -5
    assert st["streak"] == 20
