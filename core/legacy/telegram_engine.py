"""
import warnings
warnings.warn("telegram_engine.py is deprecated - use core.alert_router or infrastructure.adapters.notifications.telegram_adapter instead.", DeprecationWarning, stacklevel=2)
SMART TELEGRAM ALERT ENGINE v1.0
═════════════════════════════════
Multi-channel routing, cooldown management, strong-signal pinning,
strict message formatting.  Used by both trading bots + dashboard.

Alert Rules:
  - Fire ONLY on fresh signal (not repeat / same signal)
  - Cooldown: 15 min per stock, unless signal flips direction
  - High-strength = instant send + pin
  - Route to correct channel by category
"""

import time, logging, threading, hashlib

from datetime import datetime, timezone, timedelta

try:
    import requests
except ImportError:
    requests = None

from core.utils_numeric import safe_num as _safe_num
from core.time_provider import time_provider

log = logging.getLogger("telegram_engine")
IST = timezone(timedelta(hours=5, minutes=30))
R = chr(0x20B9)

# ═══════════════════════════════════════════════════════════════
# CHANNEL ROUTING MAP
# ═══════════════════════════════════════════════════════════════

DEFAULT_CHANNEL_MAP = {
    "INDEX":       None,   # chat_id for #nifty50-alerts
    "LARGE_CAP":   None,   # chat_id for #large-cap-alerts
    "MID_CAP":     None,   # chat_id for #mid-cap-alerts
    "SMALL_CAP":   None,   # chat_id for #small-cap-alerts
    "STRONG":      None,   # chat_id for #strong-signals (ALL high-strength)
    "DEFAULT":     None,   # fallback chat_id (main channel)
}

SECTOR_TO_CATEGORY = {
    "ENERGY": "LARGE_CAP", "IT": "LARGE_CAP", "BANK": "LARGE_CAP",
    "TELECOM": "LARGE_CAP", "FMCG": "LARGE_CAP", "AUTO": "LARGE_CAP",
    "NBFC": "MID_CAP", "PHARMA": "MID_CAP", "CONSUMER": "MID_CAP",
    "INFRA": "MID_CAP", "METAL": "MID_CAP", "POWER": "MID_CAP",
    "MINING": "MID_CAP", "INSURE": "MID_CAP", "HEALTH": "MID_CAP",
    "CEMENT": "LARGE_CAP", "CONGLOM": "MID_CAP",
}


class TelegramEngine:
    """
    Stateful Telegram alert engine with:
    - Multi-channel routing
    - Per-stock cooldown (direction-aware)
    - Strong signal pinning
    - Strict message formatting
    - Rate limiting (max 20 msgs/min per Telegram API)
    """

    def __init__(
        self,
        bot_token: str,
        default_chat_id: str,
        channel_map: dict = None,
        cooldown_seconds: int = 900,
        rate_limit_per_min: int = 18,
        enabled: bool = True,
        send_timeout: int = 10,
        pin_timeout: int = 5,
        rate_window_seconds: int = 60,
    ):
        self.bot_token = bot_token
        self.default_chat_id = default_chat_id
        self.channel_map = {**DEFAULT_CHANNEL_MAP, **(channel_map or {})}
        self.channel_map["DEFAULT"] = default_chat_id
        self.cooldown_seconds = cooldown_seconds
        self.rate_limit = rate_limit_per_min
        self.enabled = enabled
        self.send_timeout = send_timeout
        self.pin_timeout = pin_timeout
        self.rate_window = rate_window_seconds

        self._lock = threading.RLock()
        self._cooldowns: dict = {}
        self._last_signals: dict = {}
        self._send_times: list = []
        self._closed = False
        self._session = requests.Session() if requests else None
        if self._session:
            self._session.headers.update({"Content-Type": "application/json"})
        unset = [k for k, v in self.channel_map.items() if v is None and k != "DEFAULT"]
        if unset:
            msg = (
                "TelegramEngine: optional channel keys are None (%s); routing falls back to default_chat_id"
                % ", ".join(sorted(unset))
            )
            if not str(default_chat_id).strip():
                log.warning("%s - and default_chat_id is empty", msg)
            else:
                log.info(msg)

    def close(self):
        """Close the underlying HTTP session to release resources."""
        with self._lock:
            self._closed = True
            sess = self._session
            self._session = None
        if sess:
            try:
                sess.close()
            except (OSError, ConnectionError):
                pass

    # ─── ROUTING ────────────────────────────────────────────

    def _resolve_channel(self, signal: dict) -> list:
        """Return list of chat_ids to send to."""
        targets = []
        sector = signal.get("sector", "")
        category = signal.get("category", "") or SECTOR_TO_CATEGORY.get(sector, "DEFAULT")
        strength = signal.get("strength", "NONE")

        cat_id = self.channel_map.get(category)
        if cat_id:
            targets.append(cat_id)

        if signal.get("direction") in ("CALL", "PUT") and signal.get("signal") != "HOLD":
            asset_type = signal.get("asset_type", "stock")
            if asset_type == "index":
                idx_id = self.channel_map.get("INDEX")
                if idx_id and idx_id not in targets:
                    targets.append(idx_id)

        if strength == "STRONG":
            strong_id = self.channel_map.get("STRONG")
            if strong_id and strong_id not in targets:
                targets.append(strong_id)

        if not targets:
            targets.append(self.default_chat_id)

        return targets

    # ─── COOLDOWN MANAGEMENT ────────────────────────────────

    def _check_cooldown_fresh(self, signal: dict) -> bool:
        """Check-only: returns True if alert CAN fire (not on cooldown, not duplicate).
        Does NOT commit state - call _commit_cooldown after successful send."""
        symbol = signal.get("symbol", "")
        direction = signal.get("direction", "")
        price = _safe_num(signal.get("price"), 0)
        score = signal.get("score", 0)
        now = time.time()

        sig_hash = hashlib.md5(
            f"{symbol}:{direction}:{score}:{round(price, 0)}".encode(),
            usedforsecurity=False,
        ).hexdigest()[:16]

        with self._lock:
            last = self._cooldowns.get(symbol)
            if last is not None:
                elapsed = now - last.get("ts", 0)
                if last.get("direction") == direction and elapsed < self.cooldown_seconds:
                    return False

            if self._last_signals.get(symbol) == sig_hash:
                return False

        return True

    def _commit_cooldown(self, signal: dict):
        """Commit cooldown state after a successful send."""
        symbol = signal.get("symbol", "")
        direction = signal.get("direction", "")
        price = _safe_num(signal.get("price"), 0)
        score = signal.get("score", 0)
        now = time.time()

        sig_hash = hashlib.md5(
            f"{symbol}:{direction}:{score}:{round(price, 0)}".encode(),
            usedforsecurity=False,
        ).hexdigest()[:16]

        with self._lock:
            self._last_signals[symbol] = sig_hash
            self._cooldowns[symbol] = {
                "ts": now,
                "direction": direction,
                "score": score,
            }

            expired = [k for k, v in self._cooldowns.items()
                       if now - v.get("ts", 0) > self.cooldown_seconds * 3]
            for k in expired:
                del self._cooldowns[k]
            stale = [k for k in self._last_signals
                     if k not in self._cooldowns]
            for k in stale:
                del self._last_signals[k]

    # ─── RATE LIMITING ──────────────────────────────────────

    def _try_reserve_rate_slots(self, count: int = 1) -> bool:
        """Check rate limit AND reserve `count` slots atomically."""
        now = time.time()
        with self._lock:
            self._send_times = [t for t in self._send_times if now - t < self.rate_window]
            if len(self._send_times) + count > self.rate_limit:
                return False
            for _ in range(count):
                self._send_times.append(now)
            return True

    # ─── MESSAGE FORMATTING ─────────────────────────────────

    @staticmethod
    def format_alert(signal: dict) -> str:
        """
        Alert message with full execution intelligence context.
        Includes tier, confidence, regime, and position size from ExecutionPolicy.
        """
        sig_type  = signal.get("signal", "HOLD")
        symbol    = signal.get("symbol", "?")
        price     = _safe_num(signal.get("price"))
        strength  = signal.get("strength", "NONE")
        direction = signal.get("direction", "")
        sl        = _safe_num(signal.get("stop_loss"))
        tp1       = _safe_num(signal.get("tp1"))
        tp2       = _safe_num(signal.get("tp2"))
        tp3       = _safe_num(signal.get("tp3"))
        rsi       = _safe_num(signal.get("rsi"))
        macd_raw  = signal.get("macd")
        macd      = macd_raw if isinstance(macd_raw, dict) else {}
        macd_val  = _safe_num(macd.get("macd"))
        ts        = signal.get("timestamp", time_provider.format_ts("%d-%b-%Y %H:%M:%S"))
        sector    = signal.get("sector", signal.get("category", ""))
        score     = _safe_num(signal.get("score"))
        vix       = _safe_num(signal.get("vix"))

        # ── Execution intelligence fields (from enrich_signal_with_policy) ──
        tier         = signal.get("exec_tier") or signal.get("tier") or strength
        regime       = signal.get("mkt_regime") or signal.get("regime") or "-"
        position_pct = _safe_num(signal.get("exec_position_pct", signal.get("position_pct", 0)))
        exec_lots    = signal.get("exec_lots") or signal.get("lots") or "-"
        quality      = _safe_num(signal.get("exec_quality", signal.get("quality_score", 0)))
        exec_mode    = signal.get("exec_mode") or "-"
        soft_blocks  = signal.get("soft_blocks", [])
        soft_str     = ", ".join(soft_blocks) if soft_blocks else "None"

        # Tier emoji
        tier_emoji = {"STRONG": "💎", "MODERATE": "🟡", "WEAK": "⚠️"}.get(tier, "⚪")
        regime_emoji = {"TRENDING": "📈", "SIDEWAYS": "➡️", "CHOPPY": "🌀",
                        "HIGH_VOLATILITY": "⚡", "EVENT": "🔔"}.get(regime, "📊")

        reasons_list = signal.get("reasons", [])
        if reasons_list and isinstance(reasons_list, list):
            reasons_str = "\n".join([
                f"   • {r.get('name', 'Reason')}: {r.get('msg', 'Matched')}"
                for r in reasons_list if r.get("status") == "PASS"
            ])
            if not reasons_str:
                reasons_str = "   • Core indicators aligned"
        else:
            reasons_str = "   • Core indicators aligned"

        if direction == "CALL":
            dir_emoji, side = "\U0001f7e2", "CE (Call)"
        elif direction == "PUT":
            dir_emoji, side = "\U0001f534", "PE (Put)"
        else:
            dir_emoji, side = "\u26aa", "N/A"

        sep = "\u2500" * 30
        msg = (
            f"{sep}\n"
            f"\U0001f514 [{sig_type}] ALERT  {dir_emoji}\n"
            f"{sep}\n"
            f"\U0001f4cc Stock    : {symbol}\n"
            f"\U0001f4b0 Price    : {R}{price:,.2f}\n"
            f"\U0001f4ca Signal   : {sig_type} {side}\n"
            f"\U0001f4aa Strength : {strength} (Score: {score:.0f}/100)\n"
            # ── Execution intelligence block ──────────────────────────────
            f"{tier_emoji} Tier     : {tier}\n"
            f"{regime_emoji} Regime  : {regime}\n"
            f"\U0001f4b9 Position : {position_pct:.0f}% ({exec_lots} lots) [{exec_mode}]\n"
            f"\U0001f3af Quality  : {quality:.0%}\n"
        )
        if soft_blocks:
            msg += f"⚠️ Soft-blocks: {soft_str}\n"
        msg += (
            f"\U0001f4c9 Stop Loss: {R}{sl:,.2f}\n"
            f"\U0001f3af Targets  : TP1 {R}{tp1:,.2f} | TP2 {R}{tp2:,.2f} | TP3 {R}{tp3:,.2f}\n"
            f"\U0001f50d Reasons  :\n{reasons_str}\n"
            f"\U0001f4c8 RSI : {rsi:.1f} | MACD : {macd_val:+.2f}\n"
        )
        if vix > 0:
            msg += f"\U0001f321 VIX  : {vix:.1f}\n"
        msg += (
            f"\U0001f552 Time  : {ts}\n"
            f"\U0001f3f7 Sector: {sector}\n"
            f"{sep}"
        )
        return msg

    # ─── SENDING ────────────────────────────────────────────

    def _send_message(self, chat_id: str, text: str, pin: bool = False) -> bool:
        with self._lock:
            if self._closed or not self.enabled or not self._session:
                return False
            sess = self._session
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": True,
        }
        try:
            resp = sess.post(url, json=payload, timeout=self.send_timeout)
            if resp.status_code == 200:
                if pin:
                    try:
                        data = resp.json()
                        msg_id = data.get("result", {}).get("message_id")
                        if msg_id:
                            self._pin_message(chat_id, msg_id)
                    except Exception as e:
                        log.warning(f"TG pin parse error (message was sent): {e}")
                return True
            else:
                log.warning(f"TG send failed: {resp.status_code} {(resp.text or '')[:200]}")
                return False
        except Exception as e:
            log.error(f"TG send error: {e}")
            return False

    def _pin_message(self, chat_id: str, message_id: int):
        with self._lock:
            if self._closed or not self._session:
                return
            sess = self._session
        url = f"https://api.telegram.org/bot{self.bot_token}/pinChatMessage"
        try:
            sess.post(url, json={
                "chat_id": chat_id,
                "message_id": message_id,
                "disable_notification": True,
            }, timeout=self.pin_timeout)
        except Exception as e:
            log.warning(f"TG pin failed: {e}")

    # ─── PUBLIC API ─────────────────────────────────────────

    def send_signal_alert(self, signal: dict) -> bool:
        """
        Main entry point. Checks freshness, cooldown, rate limit,
        then formats and sends to the correct channels.
        Cooldown is only committed AFTER successful send (prevents alert loss on rate-limit).
        Returns True if alert was sent.
        """
        if not self.enabled:
            return False

        sig_type = signal.get("signal", "HOLD")
        if sig_type == "HOLD":
            return False

        if not self._check_cooldown_fresh(signal):
            return False

        channels = self._resolve_channel(signal)
        if not self._try_reserve_rate_slots(len(channels)):
            log.warning("TG rate limit reached, skipping alert")
            return False

        msg = self.format_alert(signal)
        strength = signal.get("strength", "NONE")
        should_pin = strength == "STRONG"

        sent = False
        for chat_id in channels:
            if self._send_message(chat_id, msg, pin=should_pin):
                sent = True

        if sent:
            self._commit_cooldown(signal)

        return sent

    def send_raw(self, text: str, chat_id: str = None, critical: bool = False) -> bool:
        """Send arbitrary text to a specific or default channel."""
        cid = chat_id or self.default_chat_id
        if not self._try_reserve_rate_slots(1):
            if not critical:
                return False
            with self._lock:
                self._send_times.append(time.time())
        return self._send_message(cid, text, pin=critical)

    def get_cooldown_status(self) -> dict:
        """Return current cooldown state for all symbols."""
        now = time.time()
        with self._lock:
            return {
                sym: {
                    "direction": v["direction"],
                    "remaining_s": max(0, int(self.cooldown_seconds - (now - v["ts"]))),
                    "score": v["score"],
                }
                for sym, v in self._cooldowns.items()
                if now - v["ts"] < self.cooldown_seconds
            }
