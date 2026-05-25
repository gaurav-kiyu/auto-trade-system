"""
Telegram Commander (v2.46 Sprint 1C).

Background polling thread that accepts commands from authorized Telegram users.
Builds decision-support rich signal messages and routes commands to the
ManualSignalQueue and SignalApprovalWorkflow.

Designed for SIGNALS_ONLY / FULL_MANUAL modes — position management commands
(live broker) are behind telegram_allow_live_position_cmds=false guard.

Public API
----------
    TelegramCommander             — main class
    build_commander(cfg, queue, workflow, state_fn, send_fn)
                                  → TelegramCommander | None
    build_rich_signal_message(signal_dict, cfg) → str
    build_trade_entry_message(trade_dict, cfg)  → str
    build_trade_exit_message(trade_dict, cfg)   → str

Config keys
-----------
    telegram_commander_enabled         : bool   default false
    telegram_authorized_user_ids       : list   default []
    telegram_admin_user_ids            : list   default []
    telegram_poll_interval_secs        : int    default 5
    telegram_cmd_rate_limit_per_min    : int    default 10
    telegram_allow_live_position_cmds  : bool   default false
    telegram_signal_format             : str    default "RICH"  (RICH | COMPACT)
    BOT_TOKEN                          : str    required
    CHAT_ID                            : str    required
"""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Any

from core.safety_state import hard_halt_reason, is_hard_halted
from core.telegram.audit.manager import TelegramAuditManager
from core.telegram.auth.manager import TelegramAuthManager

_log = logging.getLogger(__name__)

# ── Message builders (standalone — usable without a running commander) ─────────

def build_rich_signal_message(signal: dict[str, Any], cfg: dict[str, Any] | None = None) -> str:
    """
    Build a decision-support Telegram message for a new trading signal.

    The message contains everything a trader needs to make an instant GO/NO-GO
    decision: market context, technical picture, risk parameters, and a command
    shortcut to submit the signal.
    """
    c = cfg or {}
    idx       = signal.get("index_name", signal.get("index", "?"))
    direction = str(signal.get("direction", "?")).upper()
    score     = signal.get("score", 0)
    tier      = str(signal.get("tier", signal.get("strength", "?"))).upper()
    regime    = str(signal.get("regime", "?")).upper()
    session   = str(signal.get("session", "?")).upper()

    # Market context
    vix       = signal.get("vix")
    iv_rank   = signal.get("iv_rank")
    pcr       = signal.get("pcr")
    adx       = signal.get("adx")
    rsi       = signal.get("rsi")
    ltp       = signal.get("ltp", signal.get("spot"))
    entry_px  = signal.get("entry_price")
    sl_px     = signal.get("sl_price")
    tp_px     = signal.get("target_price")
    rr        = signal.get("rr")
    lots      = signal.get("lots", signal.get("lot_count"))
    ml_prob   = signal.get("ml_win_probability")
    soft_blocks = signal.get("soft_blocks", [])
    if isinstance(soft_blocks, str):
        try:
            import json
            soft_blocks = json.loads(soft_blocks)
        except Exception:
            soft_blocks = [soft_blocks] if soft_blocks else []

    # Direction emoji
    dir_emoji = "🟢" if direction == "CALL" else "🔴"
    tier_emoji = {"STRONG": "💪", "MODERATE": "👍", "WEAK": "⚠️"}.get(tier, "📊")
    regime_label = {
        "TRENDING": "📈 Trending", "RANGING": "↔️ Ranging",
        "CHOPPY": "⚡ Choppy", "VOLATILE": "🌪️ Volatile",
    }.get(regime, f"🔘 {regime}")

    # Score bar (visual)
    bar_filled = int(score / 10)
    score_bar = "█" * bar_filled + "░" * (10 - bar_filled)

    lines: list[str] = [
        f"{'─'*32}",
        f"{dir_emoji} *{idx} {direction}* {tier_emoji} {tier}",
        f"Score: [{score_bar}] {score}/100",
        f"{'─'*32}",
    ]

    # ── Market context ─────────────────────────────────────────────────────
    ctx_lines: list[str] = []
    if ltp is not None:
        ctx_lines.append(f"Spot: {ltp:,.0f}")
    if regime:
        ctx_lines.append(regime_label)
    if session:
        ctx_lines.append(f"Session: {session.replace('_',' ').title()}")
    if vix is not None:
        vix_label = "🔥 HIGH" if vix > 20 else ("🟡 MED" if vix > 15 else "🟢 LOW")
        ctx_lines.append(f"India VIX: {vix:.1f} {vix_label}")
    if iv_rank is not None:
        iv_label = "💰 Cheap" if iv_rank < 30 else ("💲 Fair" if iv_rank < 70 else "💸 Expensive")
        ctx_lines.append(f"IV Rank: {iv_rank:.0f} {iv_label}")
    if pcr is not None:
        pcr_label = "Bullish" if pcr > 1.2 else ("Bearish" if pcr < 0.8 else "Neutral")
        ctx_lines.append(f"PCR: {pcr:.2f} ({pcr_label})")
    if ctx_lines:
        lines.append("📊 *Market*")
        lines.extend(f"  {l}" for l in ctx_lines)

    # ── Technical picture ──────────────────────────────────────────────────
    tech_lines: list[str] = []
    if adx is not None:
        adx_label = "Strong trend" if adx > 25 else ("Weak trend" if adx > 15 else "No trend")
        tech_lines.append(f"ADX: {adx:.0f} ({adx_label})")
    if rsi is not None:
        rsi_label = "Overbought" if rsi > 70 else ("Oversold" if rsi < 30 else "Neutral")
        tech_lines.append(f"RSI: {rsi:.1f} ({rsi_label})")
    if ml_prob is not None:
        ml_bar = "▰" * int(ml_prob * 10) + "▱" * (10 - int(ml_prob * 10))
        tech_lines.append(f"ML Win Prob: [{ml_bar}] {ml_prob:.0%}")
    if tech_lines:
        lines.append("🔬 *Technical*")
        lines.extend(f"  {l}" for l in tech_lines)

    # ── Risk parameters ────────────────────────────────────────────────────
    risk_lines: list[str] = []
    if entry_px is not None:
        risk_lines.append(f"Entry: ₹{entry_px:.1f}")
    if sl_px is not None:
        risk_lines.append(f"SL:    ₹{sl_px:.1f}")
    if tp_px is not None:
        risk_lines.append(f"TP:    ₹{tp_px:.1f}")
    if rr is not None:
        rr_label = "✅ Good" if rr >= 2.0 else ("⚠️ Marginal" if rr >= 1.5 else "❌ Poor")
        risk_lines.append(f"R:R    {rr:.1f}x {rr_label}")
    if lots is not None:
        risk_lines.append(f"Lots:  {lots}")
    if risk_lines:
        lines.append("💰 *Risk*")
        lines.extend(f"  {l}" for l in risk_lines)

    # ── Soft blocks (what's working against this signal) ──────────────────
    if soft_blocks:
        lines.append("⚠️ *Cautions*")
        for b in soft_blocks[:3]:  # cap at 3 to avoid message bloat
            lines.append(f"  • {b}")

    # ── Action commands ────────────────────────────────────────────────────
    lines.append(f"{'─'*32}")
    lines.append("📝 *Submit Signal*")
    lines.append(f"  `/signal {idx} {direction} {score}`")

    signal_id = signal.get("signal_id")
    if signal_id:
        lines.append(f"  `/approve {signal_id}` | `/reject {signal_id}`")

    lines.append(f"{'─'*32}")
    return "\n".join(lines)


def build_compact_signal_message(signal: dict[str, Any], cfg: dict[str, Any] | None = None) -> str:
    """One-line compact signal message for low-bandwidth / high-frequency use."""
    idx       = signal.get("index_name", signal.get("index", "?"))
    direction = str(signal.get("direction", "?")).upper()
    score     = signal.get("score", 0)
    tier      = str(signal.get("tier", "?"))[:3].upper()
    vix       = signal.get("vix")
    regime    = str(signal.get("regime", "?"))[:3].upper()
    dir_emoji = "🟢" if direction == "CALL" else "🔴"
    vix_str   = f" VIX={vix:.0f}" if vix else ""
    return f"{dir_emoji} {idx} {direction} | score={score} ({tier}) | {regime}{vix_str}"


def build_trade_entry_message(trade: dict[str, Any], cfg: dict[str, Any] | None = None) -> str:
    """
    Decision-support message when a trade is opened.
    Tells the trader exactly what was done and what to watch.
    """
    idx       = trade.get("index_name", trade.get("index", "?"))
    direction = str(trade.get("direction", "?")).upper()
    entry     = trade.get("entry_price", trade.get("entry", 0))
    sl        = trade.get("sl_price", trade.get("sl", 0))
    tp        = trade.get("target_price", trade.get("target", 0))
    lots      = trade.get("lots", trade.get("qty", 1))
    mode      = str(trade.get("mode", "PAPER")).upper()
    score     = trade.get("score", 0)
    trade_id  = trade.get("trade_id", trade.get("id", "?"))
    lot_size  = trade.get("lot_size", 50)

    dir_emoji = "🟢" if direction == "CALL" else "🔴"
    mode_tag  = "[PAPER]" if mode == "PAPER" else "[LIVE]"

    risk_per_lot  = abs(entry - sl) * lot_size if entry and sl else 0
    total_risk    = risk_per_lot * lots
    reward_per_lot = abs(tp - entry) * lot_size if tp and entry else 0
    total_reward  = reward_per_lot * lots
    rr            = reward_per_lot / risk_per_lot if risk_per_lot else 0

    lines = [
        f"{'─'*30}",
        f"{dir_emoji} *TRADE OPEN* {mode_tag}",
        f"  {idx} {direction} | Score: {score}",
        f"{'─'*30}",
        f"📍 Entry:  ₹{entry:.1f}",
        f"🛑 SL:     ₹{sl:.1f}  (−₹{total_risk:,.0f} if hit)",
        f"🎯 Target: ₹{tp:.1f}  (+₹{total_reward:,.0f} if hit)",
        f"📐 R:R:    {rr:.1f}x | Lots: {lots}",
        f"{'─'*30}",
        f"ID: {trade_id} | Watch SL carefully.",
        f"{'─'*30}",
    ]
    return "\n".join(lines)


def build_trade_exit_message(trade: dict[str, Any], cfg: dict[str, Any] | None = None) -> str:
    """Message when a trade closes — shows P&L and cumulative context."""
    idx       = trade.get("index_name", trade.get("index", "?"))
    direction = str(trade.get("direction", "?")).upper()
    entry     = trade.get("entry_price", trade.get("entry", 0))
    exit_px   = trade.get("exit_price", 0)
    net_pnl   = trade.get("net_pnl", 0)
    gross_pnl = trade.get("gross_pnl", net_pnl)
    reason    = str(trade.get("exit_reason", trade.get("reason", "?"))).upper()
    hold_mins = trade.get("hold_mins")
    mode      = str(trade.get("mode", "PAPER")).upper()
    cum_pnl   = trade.get("cumulative_pnl")
    win_rate  = trade.get("session_win_rate")
    trade_id  = trade.get("trade_id", trade.get("id", "?"))

    dir_emoji  = "🟢" if direction == "CALL" else "🔴"
    pnl_emoji  = "✅" if net_pnl >= 0 else "❌"
    mode_tag   = "[PAPER]" if mode == "PAPER" else "[LIVE]"

    reason_labels = {
        "TARGET": "🎯 Target Hit",
        "SL": "🛑 Stop Loss",
        "TRAIL": "📉 Trailed Out",
        "TIMEOUT": "⏱️ Timeout",
        "EOD": "🌅 EOD Close",
        "MANUAL": "👤 Manual Close",
    }
    reason_label = reason_labels.get(reason, f"Exit: {reason}")

    hold_str = f" | {hold_mins:.0f}min held" if hold_mins else ""
    move_pct = (exit_px - entry) / entry * 100 if entry and exit_px else 0
    if direction == "PUT":
        move_pct = -move_pct

    lines = [
        f"{'─'*30}",
        f"{pnl_emoji} *TRADE CLOSED* {mode_tag}",
        f"  {dir_emoji} {idx} {direction}",
        f"{'─'*30}",
        f"{reason_label}",
        f"  Entry: ₹{entry:.1f} → Exit: ₹{exit_px:.1f}  ({move_pct:+.1f}%)",
        f"  Net P&L:   ₹{net_pnl:+,.0f}",
    ]
    if gross_pnl != net_pnl:
        charges = gross_pnl - net_pnl
        lines.append(f"  Charges:   ₹{charges:,.0f}")
    if hold_str:
        lines.append(f"  Duration:{hold_str}")
    if cum_pnl is not None:
        cum_emoji = "✅" if cum_pnl >= 0 else "❌"
        lines.append(f"{'─'*30}")
        lines.append(f"Day P&L: {cum_emoji} ₹{cum_pnl:+,.0f}")
    if win_rate is not None:
        lines.append(f"Session Win Rate: {win_rate:.0%}")
    lines.append(f"ID: {trade_id}")
    lines.append(f"{'─'*30}")
    return "\n".join(lines)


def build_status_message(state: dict[str, Any], cfg: dict[str, Any] | None = None) -> str:
    """Rich status message for /status command."""
    c = cfg or {}
    mode       = str(state.get("execution_mode", "MANUAL")).upper()
    capital    = state.get("capital", state.get("BASE_CAPITAL", 0))
    daily_pnl  = state.get("daily_pnl", 0)
    daily_loss = state.get("daily_loss_limit", state.get("MAX_DAILY_LOSS", 0))
    daily_tgt  = state.get("daily_target", c.get("DAILY_TARGET", 0))
    open_pos   = state.get("open_positions", 0)
    max_open   = state.get("max_open", c.get("MAX_OPEN", 1))
    trades_day = state.get("trades_today", 0)
    max_trades = state.get("max_trades_day", c.get("MAX_TRADES_DAY", 3))
    vix        = state.get("vix")
    halted     = state.get("hard_halt", False)
    paused     = state.get("paused", False)
    pending_q  = state.get("pending_signals", 0)
    scan_age   = state.get("last_scan_secs")

    pnl_emoji  = "✅" if daily_pnl >= 0 else "❌"
    halt_line  = "🚨 HALTED" if halted else ("⏸️ PAUSED" if paused else "🟢 RUNNING")

    budget_used = abs(daily_pnl / daily_loss) * 100 if daily_loss else 0
    budget_bar  = "█" * int(budget_used / 10) + "░" * (10 - int(budget_used / 10))

    lines = [
        f"{'─'*28}",
        f"📡 *Bot Status* — {halt_line}",
        f"Mode: {mode}",
        f"{'─'*28}",
        f"Capital:    ₹{capital:,.0f}",
        f"Day P&L:    {pnl_emoji} ₹{daily_pnl:+,.0f}",
        f"Loss Budget:[{budget_bar}] {budget_used:.0f}%",
        f"Day Target: ₹{daily_tgt:+,.0f}",
        f"{'─'*28}",
        f"Positions:  {open_pos}/{max_open}",
        f"Trades:     {trades_day}/{max_trades} today",
    ]
    if vix is not None:
        lines.append(f"VIX:        {vix:.1f}")
    if pending_q > 0:
        lines.append(f"⏳ Pending signals: {pending_q}  (/pending to review)")
    if scan_age is not None:
        lines.append(f"Last scan:  {scan_age:.0f}s ago")
    lines.append(f"{'─'*28}")
    return "\n".join(lines)


def build_positions_message(positions: list[dict], cfg: dict[str, Any] | None = None) -> str:
    """Rich positions summary for /positions command."""
    if not positions:
        return "📭 No open positions."
    lines = [f"{'─'*28}", f"📊 *Open Positions* ({len(positions)})", f"{'─'*28}"]
    for p in positions:
        idx     = p.get("index_name", p.get("index", "?"))
        dirn    = str(p.get("direction", "?")).upper()
        entry   = p.get("entry_price", p.get("entry", 0))
        ltp     = p.get("ltp", p.get("current_price", 0))
        sl      = p.get("sl_price", p.get("sl", 0))
        tp      = p.get("target_price", p.get("target", 0))
        unrealised = p.get("unrealised_pnl", (ltp - entry) if ltp and entry else 0)
        dir_e   = "🟢" if dirn == "CALL" else "🔴"
        pnl_e   = "✅" if unrealised >= 0 else "❌"
        distance_to_sl = abs(ltp - sl) / entry * 100 if ltp and sl and entry else 0
        lines.append(
            f"{dir_e} {idx} {dirn}: ₹{entry:.1f}→{ltp:.1f} "
            f"{pnl_e}₹{unrealised:+,.0f} | SL@₹{sl:.1f} ({distance_to_sl:.1f}% away)"
        )
    lines.append(f"{'─'*28}")
    return "\n".join(lines)


def build_pending_signals_message(signals: list, cfg: dict[str, Any] | None = None) -> str:
    """Format pending signals queue for /pending command."""
    if not signals:
        return "✅ No pending signals in queue."
    lines = [f"{'─'*28}", f"⏳ *Pending Signals* ({len(signals)})", f"{'─'*28}"]
    for sig in signals:
        d = sig.to_dict() if hasattr(sig, "to_dict") else sig
        idx    = d.get("index_name", "?")
        dirn   = str(d.get("direction", "?")).upper()
        score  = d.get("score", 0)
        reason = (d.get("reason", "") or "")[:30]
        sid    = d.get("signal_id", "?")
        analyst = d.get("analyst_name", "?")
        dir_e  = "🟢" if dirn == "CALL" else "🔴"
        lines.append(f"{dir_e} [{sid}] {idx} {dirn} score={score}")
        if reason:
            lines.append(f"   {reason}")
        lines.append(f"   by {analyst} | /approve {sid} | /reject {sid}")
    lines.append(f"{'─'*28}")
    return "\n".join(lines)


# ── Commander ──────────────────────────────────────────────────────────────────

class TelegramCommander:
    """
    Background thread that polls Telegram for commands from authorized users.

    All destructive / live-path commands are guarded by
    telegram_allow_live_position_cmds=false (default).

    The commander does NOT call index_trader.py functions directly — it uses
    callbacks (state_fn, send_fn) and the ManualSignalQueue to stay decoupled.
    """

    def __init__(
        self,
        cfg: dict[str, Any],
        queue,
        workflow,
        state_fn: Callable[[], dict],
        send_fn: Callable[[str, bool], None],
        positions_fn: Callable[[], list] | None = None,
        pnl_fn: Callable[[], dict] | None = None,
    ) -> None:
        self._cfg             = cfg
        self._queue           = queue
        self._workflow        = workflow
        self._state_fn        = state_fn
        self._send_fn         = send_fn
        self._positions_fn    = positions_fn or (lambda: [])
        self._pnl_fn          = pnl_fn or (lambda: {})

        self._token           = str(cfg.get("BOT_TOKEN", ""))
        self._chat_id         = str(cfg.get("CHAT_ID", ""))

        # Security Managers
        self._auth = TelegramAuthManager(
            authorized_ids=set(str(x) for x in cfg.get("telegram_authorized_user_ids", [])),
            admin_ids=set(str(x) for x in cfg.get("telegram_admin_user_ids", [])),
            authorized_chat_ids=set(str(x) for x in cfg.get("telegram_authorized_chat_ids", []))
        )
        self._audit = TelegramAuditManager()

        self._poll_secs       = int(cfg.get("telegram_poll_interval_secs", 5))
        self._rate_limit      = int(cfg.get("telegram_cmd_rate_limit_per_min", 10))
        self._live_pos_cmds   = bool(cfg.get("telegram_allow_live_position_cmds", False))
        self._sig_format      = str(cfg.get("telegram_signal_format", "RICH")).upper()
        self._default_analyst = str(cfg.get("manual_signal_default_analyst", "Operator"))

        self._last_update_id  = 0
        self._stop_event      = threading.Event()
        self._thread: threading.Thread | None = None
        self._rate_times: list[float] = []
        self._rate_lock   = threading.Lock()

    def start(self) -> None:
        if not self._token or not self._chat_id:
            _log.warning("[TG_CMD] BOT_TOKEN or CHAT_ID missing — commander not started")
            return
        self._thread = threading.Thread(
            target=self._poll_loop, name="tg_commander", daemon=True
        )
        self._thread.start()
        _log.info("[TG_CMD] Commander started (poll_secs=%d)", self._poll_secs)

    def stop(self) -> None:
        self._stop_event.set()

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ── Polling loop ───────────────────────────────────────────────────────

    def _poll_loop(self) -> None:
        while not self._stop_event.wait(timeout=self._poll_secs):
            try:
                updates = self._get_updates()
                for upd in updates:
                    self._handle_update(upd)
            except Exception as exc:
                _log.warning("[TG_CMD] Poll error: %s", exc)

    def _get_updates(self) -> list[dict]:
        import requests
        try:
            r = requests.get(
                f"https://api.telegram.org/bot{self._token}/getUpdates",
                params={"offset": self._last_update_id + 1, "timeout": self._poll_secs},
                timeout=self._poll_secs + 3,
            )
            if r.status_code != 200:
                return []
            data = r.json()
            updates = data.get("result", [])
            if updates:
                self._last_update_id = updates[-1]["update_id"]
            return updates
        except Exception:
            return []

    def _handle_update(self, upd: dict) -> None:
        msg = upd.get("message") or upd.get("edited_message") or {}
        text = str(msg.get("text", "")).strip()
        if not text.startswith("/"):
            return

        from_user = msg.get("from", {})
        user_id   = str(from_user.get("id", ""))
        username  = from_user.get("username", from_user.get("first_name", "Unknown"))
        chat_id   = str(msg.get("chat", {}).get("id", ""))

        # ── Security Gate 1: chat_id allowlist ─────────────────────────────
        if not self._auth.verify_chat(chat_id):
            self._audit.record_unauthorized_attempt(user_id, username, text)
            _log.warning("[TG_CMD] Unauthorized chat_id=%s from user_id=%s", chat_id, user_id)
            return

        # ── Security Gate 2: user_id allowlist ─────────────────────────────
        perms = self._auth.verify_user(user_id)
        if not perms.is_authorized:
            self._audit.record_unauthorized_attempt(user_id, username, text)
            self._reply("⛔ Not authorized.", critical=False)
            _log.warning("[TG_CMD] Unauthorized command from user_id=%s", user_id)
            return

        if not self._check_rate(user_id):
            self._reply("⚠️ Rate limit — slow down.", critical=False)
            return

        parts = text.split()
        cmd   = parts[0].lower().split("@")[0]  # strip bot username suffix

        try:
            self._dispatch(cmd, parts[1:], user_id, username)
            # Audit successful command
            self._audit.record_command(user_id, username, cmd, parts[1:], "SUCCESS")
        except Exception as exc:
            _log.error("[TG_CMD] Handler error for %r: %s", cmd, exc)
            self._audit.record_command(user_id, username, cmd, parts[1:], f"ERROR: {exc}")
            self._reply(f"⚠️ Command error: {exc}", critical=False)

    # ── Command dispatcher ─────────────────────────────────────────────────

    def _dispatch(self, cmd: str, args: list[str], user_id: str, username: str) -> None:
        # ── Signal submission commands ─────────────────────────────────────
        if cmd in ("/signal", "/sig"):
            self._cmd_signal(args, username)
        elif cmd in ("/signal_call", "/call"):
            self._cmd_signal([args[0]] + ["CALL"] + args[1:] if args else args, username)
        elif cmd in ("/signal_put", "/put"):
            self._cmd_signal([args[0]] + ["PUT"] + args[1:] if args else args, username)

        # ── Approval commands ──────────────────────────────────────────────
        elif cmd == "/approve":
            self._cmd_approve(args, username)
        elif cmd == "/reject":
            self._cmd_reject(args, username)
        elif cmd == "/approve_all":
            self._cmd_approve_all(username)
        elif cmd == "/pending":
            self._cmd_pending()
        elif cmd == "/cancel":
            self._cmd_cancel(args, username)

        # ── Information commands ───────────────────────────────────────────
        elif cmd == "/status":
            self._cmd_status()
        elif cmd == "/positions":
            self._cmd_positions()
        elif cmd == "/pnl":
            self._cmd_pnl()
        elif cmd == "/signals":
            self._cmd_signals_recent()

        # ── Position management (LIVE-PATH-RISK — guarded) ────────────────
        elif cmd in ("/exit", "/exit_all", "/move_sl", "/partial_exit", "/move_target"):
            self._cmd_live_guard(cmd, args)

        # ── Bot control ────────────────────────────────────────────────────
        elif cmd in ("/pause", "/resume", "/mode", "/lots"):
            self._reply(f"⚠️ Bot control commands ({cmd}) require direct config change. "
                        "Set config key and restart.", critical=False)

        # ── Admin ──────────────────────────────────────────────────────────
        elif cmd in ("/retrain_ml", "/backup", "/set_config"):
            if user_id not in self._admin_ids:
                self._reply("⛔ Admin-only command.", critical=False)
                return
            self._reply(f"ℹ️ {cmd} not yet wired in this version. "
                        "Coming in a future release.", critical=False)
        elif cmd == "/emergency_stop":
            self._cmd_emergency_stop(user_id, username)

        # ── Help ──────────────────────────────────────────────────────────
        elif cmd in ("/help", "/start"):
            self._cmd_help()
        else:
            self._reply(f"❓ Unknown command: {cmd}\nUse /help to see available commands.",
                        critical=False)

    # ── Individual command implementations ─────────────────────────────────

    def _cmd_signal(self, args: list[str], username: str) -> None:
        """Submit a manual signal: /signal BANKNIFTY CALL 82 [reason text]"""
        if len(args) < 3:
            self._reply("Usage: /signal {INDEX} {CALL|PUT} {SCORE} [reason]", critical=False)
            return
        index_name = args[0].upper()
        direction  = args[1].upper()
        if direction not in ("CALL", "PUT"):
            self._reply(f"❌ Direction must be CALL or PUT, got: {direction}", critical=False)
            return
        try:
            score = int(args[2])
        except ValueError:
            self._reply(f"❌ Score must be a number, got: {args[2]}", critical=False)
            return
        reason = " ".join(args[3:]) if len(args) > 3 else ""
        if self._queue is None:
            self._reply("⚠️ Signal queue not initialized.", critical=False)
            return
        sig = self._queue.submit(
            index_name, direction, score, reason,
            source="TELEGRAM", analyst_name=username,
        )
        pending_count = len(self._queue.get_pending())
        dir_e = "🟢" if direction == "CALL" else "🔴"
        msg = (
            f"{'─'*28}\n"
            f"📝 *Signal Queued*\n"
            f"{dir_e} {index_name} {direction} | Score: {score}\n"
            f"ID: `{sig.signal_id}`\n"
            f"By: {username}\n"
            f"{'─'*28}\n"
            f"Queue: {pending_count} pending\n"
            f"/approve {sig.signal_id} | /reject {sig.signal_id} {sig.signal_id}\n"
            f"{'─'*28}"
        )
        self._reply(msg, critical=False)

    def _cmd_approve(self, args: list[str], username: str) -> None:
        """Approve a signal: /approve {signal_id} [lots]"""
        if is_hard_halted():
            self._reply(
                f"🚨 HARD HALT ACTIVE — approvals blocked.\n"
                f"Reason: {hard_halt_reason()}\n"
                f"Clear the halt before approving signals.",
                critical=True,
            )
            return

        if not args:
            self._reply("Usage: /approve {signal_id} [lots_override]", critical=False)
            return
        signal_id = args[0]
        lots_override = int(args[1]) if len(args) > 1 else None
        if self._queue is None:
            self._reply("⚠️ Queue not initialized.", critical=False)
            return
        ok = self._queue.approve(signal_id, reviewer=username, lots_override=lots_override)
        if ok:
            sig = self._queue.get_by_id(signal_id)
            dir_e = "🟢" if sig and sig.direction == "CALL" else "🔴"
            idx   = sig.index_name if sig else "?"
            dirn  = sig.direction if sig else "?"
            msg = (
                f"✅ *Approved* [{signal_id}]\n"
                f"{dir_e} {idx} {dirn}"
                + (f" | Lots: {lots_override}" if lots_override else "")
                + f"\nBy: {username}"
            )
        else:
            msg = f"❌ Cannot approve `{signal_id}` — not found or not PENDING."
        self._reply(msg, critical=False)

    def _cmd_reject(self, args: list[str], username: str) -> None:
        """Reject a signal: /reject {signal_id} [reason]"""
        if not args:
            self._reply("Usage: /reject {signal_id} [reason]", critical=False)
            return
        signal_id = args[0]
        reason = " ".join(args[1:]) if len(args) > 1 else "Rejected"
        if self._queue is None:
            self._reply("⚠️ Queue not initialized.", critical=False)
            return
        ok = self._queue.reject(signal_id, reviewer=username, reason=reason)
        if ok:
            msg = f"❌ *Rejected* [{signal_id}]\nReason: {reason}"
        else:
            msg = f"⚠️ Cannot reject `{signal_id}` — not found or not PENDING."
        self._reply(msg, critical=False)

    def _cmd_approve_all(self, username: str) -> None:
        """Approve all pending signals."""
        if is_hard_halted():
            self._reply(
                f"🚨 HARD HALT ACTIVE — bulk approvals blocked.\n"
                f"Reason: {hard_halt_reason()}",
                critical=True,
            )
            return

        if self._queue is None:
            self._reply("⚠️ Queue not initialized.", critical=False)
            return
        pending = self._queue.get_pending()
        if not pending:
            self._reply("✅ No pending signals.", critical=False)
            return
        approved = []
        for sig in pending:
            if self._queue.approve(sig.signal_id, reviewer=username):
                approved.append(sig.signal_id)
        self._reply(f"✅ Approved {len(approved)} signal(s):\n" + "\n".join(approved), critical=False)

    def _cmd_cancel(self, args: list[str], username: str) -> None:
        if not args:
            self._reply("Usage: /cancel {signal_id} [reason]", critical=False)
            return
        signal_id = args[0]
        reason = " ".join(args[1:]) if len(args) > 1 else "Cancelled by user"
        if self._queue is None:
            self._reply("⚠️ Queue not initialized.", critical=False)
            return
        ok = self._queue.cancel(signal_id, reason=reason)
        self._reply(
            f"🚫 Cancelled `{signal_id}`" if ok else f"⚠️ Could not cancel `{signal_id}`",
            critical=False
        )

    def _cmd_pending(self) -> None:
        if self._queue is None:
            self._reply("⚠️ Queue not initialized.", critical=False)
            return
        signals = self._queue.get_pending()
        msg = build_pending_signals_message(signals, self._cfg)
        self._reply(msg, critical=False)

    def _cmd_status(self) -> None:
        try:
            state = self._state_fn()
            if self._queue:
                state["pending_signals"] = len(self._queue.get_pending())
            self._reply(build_status_message(state, self._cfg), critical=False)
        except Exception as exc:
            self._reply(f"⚠️ Status unavailable: {exc}", critical=False)

    def _cmd_positions(self) -> None:
        try:
            positions = self._positions_fn()
            self._reply(build_positions_message(positions, self._cfg), critical=False)
        except Exception as exc:
            self._reply(f"⚠️ Positions unavailable: {exc}", critical=False)

    def _cmd_pnl(self) -> None:
        try:
            pnl = self._pnl_fn()
            daily   = pnl.get("daily_pnl", 0)
            weekly  = pnl.get("weekly_pnl")
            trades  = pnl.get("trades_today", 0)
            wins    = pnl.get("wins_today", 0)
            wr      = wins / trades * 100 if trades else 0
            pnl_e   = "✅" if daily >= 0 else "❌"
            lines = [
                f"{'─'*26}",
                "💰 *P&L Summary*",
                f"Day:    {pnl_e} ₹{daily:+,.0f}",
                f"Trades: {trades} | Wins: {wins} | WR: {wr:.0f}%",
            ]
            if weekly is not None:
                wk_e = "✅" if weekly >= 0 else "❌"
                lines.append(f"Week:   {wk_e} ₹{weekly:+,.0f}")
            lines.append(f"{'─'*26}")
            self._reply("\n".join(lines), critical=False)
        except Exception as exc:
            self._reply(f"⚠️ P&L unavailable: {exc}", critical=False)

    def _cmd_signals_recent(self) -> None:
        if self._queue is None:
            self._reply("⚠️ Queue not initialized.", critical=False)
            return
        recent = self._queue.get_recent(10)
        if not recent:
            self._reply("📭 No signals recorded yet.", critical=False)
            return
        lines = [f"📋 *Recent Signals* ({len(recent)})", f"{'─'*26}"]
        for sig in recent:
            dir_e = "🟢" if sig.direction == "CALL" else "🔴"
            status_e = {"PENDING": "⏳", "APPROVED": "✅", "REJECTED": "❌",
                        "EXECUTED": "💰", "EXPIRED": "💀", "CANCELLED": "🚫"}.get(sig.status, "❓")
            lines.append(f"{status_e} {dir_e} [{sig.signal_id}] {sig.index_name} {sig.direction} "
                         f"score={sig.score}")
        self._reply("\n".join(lines), critical=False)

    def _cmd_live_guard(self, cmd: str, args: list[str]) -> None:
        if not self._live_pos_cmds:
            self._reply(
                "🔒 Position management commands are DISABLED.\n"
                "Set `telegram_allow_live_position_cmds: true` in config to enable.\n"
                "⚠️ Only enable after successful paper trading validation.",
                critical=False,
            )
        else:
            self._reply(
                f"⚠️ {cmd} live execution not yet wired in this build. "
                "Position changes require manual broker action.",
                critical=False,
            )

    def _cmd_emergency_stop(self, user_id: str, username: str) -> None:
        """Emergency stop: trip hard halt immediately."""
        from core.safety_state import is_hard_halted, trip_hard_halt
        if is_hard_halted():
            self._reply("🚨 System is already halted.", critical=True)
            return
        trip_hard_halt(f"Emergency stop triggered by Telegram user {username} ({user_id})", source="telegram_emergency_stop")
        self._reply("🚨 EMERGENCY STOP ACTIVATED. All trading halted.", critical=True)

    def _cmd_help(self) -> None:
        lines = [
            "📋 *Available Commands*",
            f"{'─'*28}",
            "📝 *Signal Commands*",
            "  /signal {IDX} {CALL|PUT} {SCORE} [reason]",
            "  /signal_call {IDX} {SCORE}",
            "  /signal_put  {IDX} {SCORE}",
            f"{'─'*28}",
            "✅ *Approval Commands*",
            "  /approve {id} [lots]",
            "  /reject {id} [reason]",
            "  /approve_all",
            "  /pending",
            "  /cancel {id}",
            f"{'─'*28}",
            "📊 *Information*",
            "  /status    — bot health + P&L",
            "  /positions — open positions",
            "  /pnl       — today's P&L",
            "  /signals   — recent signals",
            f"{'─'*28}",
            "🚨 *Bot Control*",
            "  /emergency_stop — halt ALL trading immediately",
            f"{'─'*28}",
            "🔒 Position mgmt (/exit etc.) requires",
            "   telegram_allow_live_position_cmds=true",
        ]
        self._reply("\n".join(lines), critical=False)

    # ── Utility ────────────────────────────────────────────────────────────

    def _reply(self, text: str, critical: bool = False) -> None:
        try:
            self._send_fn(text, critical)
        except Exception as exc:
            _log.warning("[TG_CMD] Reply failed: %s", exc)

    def _check_rate(self, user_id: str) -> bool:
        now = time.time()
        with self._rate_lock:
            self._rate_times[:] = [t for t in self._rate_times if now - t < 60]
            if len(self._rate_times) >= self._rate_limit:
                return False
            self._rate_times.append(now)
        return True


# ── Factory ────────────────────────────────────────────────────────────────────

def build_commander(
    cfg: dict[str, Any],
    queue,
    workflow,
    state_fn: Callable[[], dict],
    send_fn: Callable[[str, bool], None],
    positions_fn: Callable[[], list] | None = None,
    pnl_fn: Callable[[], dict] | None = None,
) -> TelegramCommander | None:
    """Build and start a TelegramCommander if enabled in config."""
    if not cfg.get("telegram_commander_enabled", False):
        _log.debug("[TG_CMD] Disabled by config")
        return None
    try:
        commander = TelegramCommander(cfg, queue, workflow, state_fn, send_fn,
                                      positions_fn, pnl_fn)
        commander.start()
        return commander
    except Exception as exc:
        _log.error("[TG_CMD] Init failed: %s", exc)
        return None
