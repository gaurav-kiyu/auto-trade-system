"""
Trade-history-driven adaptive rules (threshold bias, signal confidence bands).

Pure functions + small state helpers: no threading, no I/O. The index bot (and tests)
pass in trade snapshots and config caps so the same logic is reusable in backtests
or a future Orchestrator cycle without copying from index_trader.py.
"""
from __future__ import annotations

from typing import Any


def recent_trade_learning_snapshot(
    trades: list[dict[str, Any]],
    lookback: int,
    learning_state: dict[str, Any],
) -> dict[str, Any]:
    """
    Summarise recent EXIT trades plus current learner scalars (confidence, score_adj, streak).

    `trades` is typically the full in-memory history; only EXIT / net_pnl rows are used.
    """
    lb = max(5, int(lookback or 40))
    closed = [
        t
        for t in trades
        if isinstance(t, dict) and (t.get("action") == "EXIT" or t.get("net_pnl") is not None)
    ]
    recent = closed[-lb:]
    total = len(recent)
    wins = [t for t in recent if float(t.get("net_pnl", t.get("pnl", 0)) or 0) >= 0]
    avg_net = (
        round(sum(float(t.get("net_pnl", t.get("pnl", 0)) or 0) for t in recent) / total, 2) if total else 0.0
    )
    loss_streak = 0
    for t in reversed(recent):
        npv = float(t.get("net_pnl", t.get("pnl", 0)) or 0)
        if npv < 0:
            loss_streak += 1
        else:
            break
    by_regime: dict[str, dict[str, Any]] = {}
    by_strength: dict[str, dict[str, Any]] = {}
    for t in recent:
        reg = str(t.get("regime") or "UNKNOWN")
        st = str(t.get("strength") or "MODERATE")
        npv = float(t.get("net_pnl", t.get("pnl", 0)) or 0)
        for bucket, key in ((by_regime, reg), (by_strength, st)):
            b = bucket.setdefault(key, {"count": 0, "wins": 0, "net": 0.0})
            b["count"] += 1
            if npv >= 0:
                b["wins"] += 1
            b["net"] = round(float(b["net"]) + npv, 2)
    conf = int(learning_state.get("confidence", 0))
    adj = int(learning_state.get("score_adj", 0))
    streak = int(learning_state.get("streak", 0))
    wr = round(len(wins) / total * 100, 1) if total else 0.0
    return {
        "count": total,
        "win_rate": wr,
        "avg_net": avg_net,
        "loss_streak": loss_streak,
        "by_regime": by_regime,
        "by_strength": by_strength,
        "confidence": conf,
        "score_adj": adj,
        "streak": streak,
        "lookback": lb,
    }


def adaptive_threshold_adjustment(
    snap: dict[str, Any],
    regime: str = "",
    strength: str = "",
    *,
    enabled: bool = True,
    max_bonus: int = 8,
    max_discount: int = 3,
) -> tuple[int, str]:
    """Return (delta_points, reason) to apply on top of base AI threshold."""
    if not enabled:
        return (0, "adaptive off")
    delta = max(0, int(snap.get("score_adj", 0)))
    reasons: list[str] = []
    conf = int(snap.get("confidence", 0))
    if conf <= -2:
        delta += 2
        reasons.append("low confidence")
    elif conf >= 3:
        delta -= 1
        reasons.append("healthy confidence")
    total = int(snap.get("count", 0))
    wr = float(snap.get("win_rate", 0.0))
    avg_net = float(snap.get("avg_net", 0.0))
    if total >= 6:
        if wr < 45.0:
            delta += 3
            reasons.append("recent WR weak")
        elif wr >= 62.0 and avg_net > 0:
            delta -= 1
            reasons.append("recent WR strong")
        if avg_net < 0:
            delta += 2
            reasons.append("avg net negative")
    if int(snap.get("loss_streak", 0)) >= 2:
        delta += 2
        reasons.append("loss streak")
    reg_key = str(regime or "").strip() or "UNKNOWN"
    reg_stats = snap.get("by_regime", {}).get(reg_key)
    if isinstance(reg_stats, dict) and int(reg_stats.get("count", 0)) >= 4:
        reg_wr = 100.0 * float(reg_stats.get("wins", 0)) / max(1, int(reg_stats.get("count", 0)))
        reg_net = float(reg_stats.get("net", 0.0)) / max(1, int(reg_stats.get("count", 0)))
        if reg_wr < 40.0:
            delta += 2
            reasons.append(f"{reg_key} regime weak")
        elif reg_wr >= 65.0 and reg_net > 0:
            delta -= 1
            reasons.append(f"{reg_key} regime strong")
    st_key = str(strength or "").strip() or "MODERATE"
    st_stats = snap.get("by_strength", {}).get(st_key)
    if isinstance(st_stats, dict) and int(st_stats.get("count", 0)) >= 4:
        st_wr = 100.0 * float(st_stats.get("wins", 0)) / max(1, int(st_stats.get("count", 0)))
        if st_wr < 45.0:
            delta += 1
            reasons.append(f"{st_key} quality weak")
        elif st_wr >= 68.0:
            delta -= 1
            reasons.append(f"{st_key} quality strong")
    delta = max(-int(max_discount), min(int(max_bonus), delta))
    why = ", ".join(reasons[:3]) if reasons else "stable"
    return (int(delta), why)


def live_signal_confidence(
    sig: dict[str, Any],
    *,
    default_threshold: int,
    trade_snap: dict[str, Any],
) -> tuple[int, str]:
    """Heuristic 1-99 confidence score and A/B/C/D band; `trade_snap` from recent_trade_learning_snapshot."""
    score = int(sig.get("score") or 0)
    threshold = int(sig.get("threshold") or default_threshold)
    gap = max(-20, min(20, score - threshold))
    vol_r = float(sig.get("vol_ratio") or 0.0)
    conf = 50 + gap * 2
    if sig.get("breakout_ok"):
        conf += 8
    if str(sig.get("mkt_regime") or "") == "TRENDING":
        conf += 7
    if str(sig.get("strength") or "") == "STRONG":
        conf += 8
    elif str(sig.get("strength") or "") == "MODERATE":
        conf += 3
    conf += max(-5, min(10, int(round((vol_r - 1.0) * 10))))
    # confidence ∈ [-5,5]; ×2 → [-10,+10]; bounds match the multiplied range
    conf += max(-10, min(10, int(trade_snap.get("confidence", 0)) * 2))
    if float(trade_snap.get("avg_net", 0.0)) < 0 and int(trade_snap.get("count", 0)) >= 6:
        conf -= 5
    conf = max(1, min(99, int(conf)))
    band = "A" if conf >= 80 else ("B" if conf >= 68 else ("C" if conf >= 58 else "D"))
    return (conf, band)


def clamp_learning_state(state: dict[str, Any]) -> None:
    """Clamp score_adj, confidence, streak to safe ranges (mutates `state`)."""
    state["score_adj"] = max(-10, min(10, int(state.get("score_adj", 0))))
    state["confidence"] = max(-5, min(5, int(state.get("confidence", 0))))
    state["streak"] = max(0, min(20, int(state.get("streak", 0))))


def update_learning_after_exit(state: dict[str, Any], tag: str) -> None:
    """Apply WIN/LOSS learning nudge after an exit (mutates `state`). ZOMBIE skips loss path."""
    if tag == "WIN":
        state["streak"] = int(state.get("streak", 0)) + 1
        state["score_adj"] = max(-10, int(state.get("score_adj", 0)) - 2)
        state["confidence"] = min(5, int(state.get("confidence", 0)) + 1)
    elif tag not in ("ZOMBIE",):
        state["streak"] = 0
        state["score_adj"] = min(10, int(state.get("score_adj", 0)) + 3)
        state["confidence"] = max(-5, int(state.get("confidence", 0)) - 1)
    clamp_learning_state(state)
