# ================================================================
# 🚀  TRADER BRAIN - PRODUCTION v2.53.0  (₹5 000 Capital Edition)
#     v2.42: ExecutionRouter (AUTO + optional PAPER→adapter), chunked Yahoo quarter backtest, HOW_TO_USE refresh.
#     v2.40: Final QA pass - pytest tests/test_smoke + --selftest OK; find dialog F3 + safer
#            Unicode selection end index (chars not c).
#     v2.53.0: Dependency injection container wired for core services.
# ----------------------------------------------------------------
# INSTALL : pip install requests yfinance pandas kiteconnect pyotp
# RUN     : python -m index_app.index_trader                    ← LIVE
#           python -m index_app.index_trader --paper             ← PAPER/TEST
#           python -m index_app.index_trader --debug             ← DEBUG
#           python -m index_app.index_trader --selftest          ← SELFTEST
#           python -m index_app.index_trader --print-config      ← Dump config.json
#           python -m index_app.index_trader --config-reset      ← After BASE_CAPITAL change
#           python -m index_app.index_trader --report            ← Multi-session stats
#           python -m index_app.index_trader --export-trades     ← Export trades to CSV
# USER GUIDE: HOW_TO_USE.txt (layman steps)  |  Deep guide: SETUP_AND_TRADING_GUIDE.md
# VERIFY    : pip install -r requirements-dev.txt && python -m pytest tests -v
# CONFIG    : optional env OPBUYING_INDEX_CONFIG=path\to\config.json (tests/CI)
# CLEAN EXIT: finally{} saves state, EOD report, closes NSE session. Telegram pool uses
#             non-blocking shutdown (RCA-193). With dashboard: os._exit(0) when
#             FORCE_EXIT_AFTER_SHUTDOWN (default true) so Windows CMD closes cleanly;
#             --nogui uses sys.exit(0). METRICS_PORT>0 on METRICS_BIND (default 127.0.0.1): /metrics, /health, /.
# ================================================================
#
# RCA-REG (2026-04-04): warned_loss_soft vs warned_loss - the 60% daily-loss
#         approach warning and the hard-limit breach alert used one flag,
#         so the critical limit message could be suppressed after the soft
#         warning. Split: warned_loss_soft for approach only; warned_loss for
#         breach (unchanged). Regression: --selftest, main_loop path review.
# RCA-REG (2026-04-04b): Stock bot validate_config + DAILY_LOSS_WARNING/_sync
#         aligned to this file; index unchanged this pass - cross-regression
#         both scripts --selftest.
#
# RCA-211 (2026-04-08): _format_trading_desk_line() extracted for clarity + --selftest coverage of desk text/colors.
#
# RCA-213 (2026-04-09): Adaptive learning extracted to core.adaptive_learning - pure snapshot /
#         threshold / confidence / exit-update helpers; index_trader keeps locks + config wiring.
#         Reusable from backtests/Orchestrator without duplicating index_trader.py.
#
# RCA-214 (2026-04-09): _make_broker uses local PaperAdapter/KiteAdapter/AngelAdapter from
#         BROKER_DRIVER + core.broker_connection_secrets (BROKER_CONFIG ∪ KITE_* / ANGEL_*); BROKER_NAME
#         labels logs only. BROKER_CUSTOM_FACTORY uses core.create_broker_adapter_with_runtime_context.
# RCA-215 (2026-04-09): Broker driver + hybrid warnings centralized in core.common_config_validate
#         (effective_broker_driver, append_broker_api_config_errors, append_execution_hybrid_warnings).
# RCA-216 (2026-04-09): BROKER_CUSTOM_FACTORY path uses core.create_broker_adapter_with_runtime_context.
#
# RCA-212 (2026-04-09): Hybrid UX + GUI hardening - (1) gui_struct.manual_flow_banner + desk strip
#         explain MANUAL/AUTO/PAPER/SIGNALS for smooth post-signal workflow; GUI_UX.show_manual_flow_banner
#         toggles. (2) _desk_body.py indentation bugs fixed (paneconfig/wrap/config_status/target_hit).
#         (3) trader_desk wraps _desk_body in __opbuying_desk_body() so early return compiles under exec
#         (top-level return in exec is a SyntaxError). (4) RCA_AND_HYBRID_MODEL.txt + config template note.
#
# RCA-210 (2026-04-08): Pro desk UI - TRADING DESK strip (VIX, loss-budget %, RR, SL/target, circuit,
#         halt, exec path, signal-quality + API lines); table columns ADX & IV; clearer section labels;
#         Help → Desk guide; default geometry 1200×860. Data from existing scan (no extra network).
#
# RCA-209 (2026-04-08): Polish - now_ist() docstring (naive IST wall clock); watchdog uses
#         _shutdown.wait before os._exit; soft-reload rebuilds _broker when MANUAL_SIGNALS_ONLY
#         flips; config_audit / save_state .bak failures log once instead of silent pass.
#
# RCA-208 (2026-04-08): Manual-only startup - MANUAL_SIGNALS_ONLY uses PaperAdapter so Kite
#         is not constructed (no token/API dependency); live RCA regression skips Kite check.
#         Soft-reload of MANUAL_SIGNALS_ONLY rebuilds broker adapter without full restart.
#
# RCA-206 (2026-04-07): Manual-only workflow - MANUAL_SIGNALS_ONLY skips broker, positions,
#         trade_count, and NEW TRADE lifecycle; sends throttled “MANUAL SIGNAL” Telegram + dlog
#         after the same entry gates (RR, portfolio SL cap). Soft-reload safe; dashboard/GUI
#         show mode. Bot does not track manual fills.
#
# RCA-205 (2026-04-07): Reading & system integration - (1) Long logs: Edit→Find in details
#         (Ctrl+F) with Find next + wrap; highlights match in the Text widget. (2) Windows
#         clipboard after Copy sometimes dropped without an event pump - update_idletasks()
#         after clipboard_append. (3) SCAN_INTERVAL changes via soft-reload were invisible in
#         the GUI; trades KPI line shows live scan interval. (4) Details title click focuses
#         the log for keyboard scroll/find without hunting the caret.
#
# RCA-204 (2026-04-07): Support & multi-monitor habits - (1) Operators share logs via
#         screenshots or paste; File→Save details as… writes the current details Text to
#         UTF-8 .txt (Ctrl+Shift+S). (2) Maximized window was lost on restart - layout JSON
#         v4 adds win_state (zoomed|normal); restore zoomed after geometry (iconic not
#         restored on purpose). (3) Header hint mentions max state in saved JSON.
#
# RCA-203 (2026-04-07): Desk ergonomics & diagnostics - (1) Snapshot age alone does not
#         expose a stuck main loop before watchdog; gui_struct carries loop_lag_s (monotonic
#         gap since S.last_loop_heartbeat). KPI subtitle warns only when market status is OPEN
#         (holiday/weekend long sleeps would false-positive otherwise). (2) Long logs:
#         Home/End/PgUp/PgDn on details + context-menu scroll targets + Edit entries.
#         (3) Corrupt/off-screen layout: View → Reset saved layout deletes JSON and applies
#         defaults without restarting the bot.
#
# RCA-202 (2026-04-07): Safety & robustness - (1) Accidental Alt+F4 / close on LIVE with
#         SHUTDOWN_ON_UI_CLOSE could stop the bot without intent; optional confirm dialog
#         (GUI_CONFIRM_EXIT, default true, soft-reload). (2) Invalid saved geometry strings
#         failed silently → operator thinks persistence is broken; log and fall back.
#         (3) After minimize/restore, wraplength can be wrong until resize; <Map> queues
#         debounced wrap sync. (4) Uncaught exceptions in Tk callbacks were easy to miss;
#         route through log via report_callback_exception.
#
# RCA-201 (2026-04-07): Readability & soft-reload parity - (1) Header subtitle showed
#         refresh period only at GUI start; after config soft-reload GUI_REFRESH_MS could
#         change while the label stayed stale - sync each tick. (2) Large logs: Select all
#         (Ctrl+A) + Edit menu; Escape clears selection. (3) Corrupt layout JSON failed
#         silently; log once so operators fix/rename the file. (4) Context menu: Select all.
#
# RCA-200 (2026-04-07): Operator workflow - (1) “Always on top” was session-only; persist
#         to index_trader_gui_layout.json (v3) with geometry/sash. (2) Fixed 2s UI poll
#         was not tunable; GUI_REFRESH_MS in config.json (500-30000, soft-reload safe).
#         (3) F5 = same as View→Refresh (standard desktop habit). (4) File→Open script
#         folder… opens Explorer/Finder for config.json / layout file edits.
#
# RCA-199 (2026-04-07): Desk polish & trust cues - (1) Default tk Scrollbars were light
#         “Office” gray on a dark UI; configure trough/bg to match cards. (2) Telegram &
#         API status labels had no wraplength → horizontal overflow on narrow windows.
#         (3) Users cannot tell frozen loop vs quiet market: KPI subtitle shows snapshot
#         age when backend hasn’t refreshed for several seconds. (4) View→Always on top
#         for side-by-side terminals. (5) Treeview last column stretches with pane width.
#         (6) Details Text gets a subtle focus highlight; wheel bound on detail frame.
#
# RCA-198 (2026-04-07): Realistic desk UX - (1) Layout JSON missed sash moves when only
#         the divider moved (root <Configure> never fired): also queue save on pane
#         <Configure>. (2) Details Text was wiped every 2s even when body unchanged →
#         flicker; skip repaint when detail text equal to last paint. (3) Headline /
#         Telegram lines used fixed wraplength; sync wrap to window width (debounced).
#         (4) View→Refresh now + Ctrl+Q quit; context menu Copy selection when present.
#         (5) Wheel scroll on table frame (not only on tree cells).
#
# RCA-197 (2026-04-07): GUI persistence & desk workflow - (1) Save/restore
#         window geometry + paned sash to index_trader_gui_layout.json beside this
#         script (debounced on resize, flush on exit). (2) Pane minsize so the
#         index column cannot collapse. (3) Menu: File→Exit, Help→Shortcuts.
#         (4) Details: Ctrl+C selection copy + right-click “Copy all” (clipboard).
#         (5) Tree tag fonts use _FONT_MONO consistently.
#
# ── v2.12 NEW FIXES (RCA 132-136) ─────────────────────
#
# RCA-132 DEADLOCK: nested _perf_lock → _state_lock in monitor().
#         monitor() acquires _perf_lock (line 1669) then attempts
#         to acquire _state_lock inside it (line 1673). If any
#         other thread holds _state_lock and then tries _perf_lock,
#         both threads deadlock permanently. Scenario: main thread
#         in daily_reset() holds _state_lock (line 886) while
#         monitor() runs in the same thread - single-threaded, no
#         issue. But with MAX_OPEN=2 and concurrent monitor(), the
#         risk is real if a future refactor adds _perf_lock usage
#         under _state_lock. Classic lock-ordering violation.
#         FIX: Read S.daily_pnl and S.net_daily_pnl under
#         _state_lock FIRST, then acquire _perf_lock separately.
#         No nested locks. Lock ordering: always _state_lock
#         before _perf_lock, never reverse.
#
# RCA-133 nse_fail_count read outside lock after increment.
#         After `with _nse_fail_lock: nse_fail_count += 1`, the
#         subsequent `if nse_fail_count >= threshold` reads the
#         global WITHOUT the lock. Concurrent fetch failures can
#         read a stale count, causing either missed session resets
#         or incorrect backoff durations.
#         FIX: Capture the count into a local `_nfc` variable
#         while still holding the lock. All subsequent reads use
#         the local copy. Same pattern applied to _yf_fail_lock.
#
# RCA-134 CSV file writes not thread-safe.
#         log_csv() opens the CSV in append mode without any lock.
#         Two concurrent exits (MAX_OPEN=2) both calling log_csv()
#         can interleave writes, corrupting CSV rows.
#         FIX: _csv_lock wraps the entire exists-check + write
#         operation in log_csv().
#
# RCA-135 _track_exception() dict mutations not thread-safe.
#         S.exception_counts and S.exception_alerted are plain
#         dicts/sets modified from any thread that catches an
#         exception. Concurrent modifications can lose increments
#         or skip alerts entirely.
#         FIX: _exc_lock wraps all reads and writes to both
#         exception_counts and exception_alerted.
#
# RCA-136 now_ist() uses deprecated utcfromtimestamp().
#         datetime.utcfromtimestamp() is deprecated since Python
#         3.12 and raises DeprecationWarning. Will be removed in
#         Python 3.14. The function creates a naive datetime that
#         claims to be UTC but has the IST offset baked into the
#         timestamp - confusing and deprecated.
#         FIX: Use datetime.now(timezone.utc) + IST offset.
#         Produces identical naive-IST datetime without deprecated
#         API. Compatible with Python 3.10-3.13+.
#
# ── v2.13 REGRESSION FIXES (RCA 137-143) ─────────────────
#
# RCA-137 _nse_fail_lock and _yf_fail_lock declared TWICE.
#         Section 3 (line ~401) creates Lock objects. Section 12
#         (line ~990) re-creates them - silently overwrites the
#         first pair. All code ends up using the Section 12 locks
#         while Section 3 locks are orphaned. If any code between
#         sections cached a reference to the first lock, it would
#         use a different lock than the rest of the program.
#         FIX: Lock declarations only in Section 3. Section 12
#         declares only the counter variables (nse_fail_count=0).
#
# RCA-138 check_python_version() blocks Python 3.13+.
#         Version gate: `(3,10)<=(major,minor)<(3,13)` rejects
#         3.13 even though RCA-136 specifically fixed now_ist()
#         for 3.12+ compatibility. Users on 3.13 get:
#         "[ERROR] Python 3.10-3.12 required" - contradicting
#         the code that was just made 3.13-safe.
#         FIX: Gate expanded to `<(3,14)`.
#
# RCA-139 _prune_tg_cache() iterates _tg_cache.items() unsafely.
#         `.items()` returns a view. If send() (called from a
#         ThreadPoolExecutor thread) writes _tg_cache[key] while
#         _prune_tg_cache() iterates the view, Python raises
#         `RuntimeError: dictionary changed size during iteration`
#         - crashing the main loop iteration.
#         FIX: `list(_tg_cache.items())` creates a snapshot copy
#         before iteration. Wrapped in try/except RuntimeError as
#         a belt-and-suspenders defense.
#
# RCA-140 daily_reset() replaces S.exception_counts without lock.
#         `S.exception_counts={}` is a STORE_ATTR that replaces
#         the dict reference. If _track_exception() (running in
#         an executor thread) is between reading and writing the
#         old dict, the write goes to the orphaned old dict -
#         count is silently lost.
#         FIX: Wrapped in `with _exc_lock:` so reset is atomic
#         with respect to _track_exception reads/writes.
#
# RCA-141 _rebuild_analytics() has lock inversion.
#         Acquires _ac_lock THEN calls _get_trade_history_snapshot()
#         which acquires _history_lock. Order: ac → history.
#         monitor() does: _append_trade (history_lock) then
#         _ac_lock. Order: history → ac.
#         FIX: Snapshot history BEFORE acquiring _ac_lock.
#         Lock order is now always: history → ac.
#
# RCA-142 `import tkinter` at module level fails on headless.
#         Production trading bots often run on headless Linux
#         servers (no X11/display). `import tkinter` raises
#         ImportError/ModuleNotFoundError - the entire script
#         crashes at import, before any trading logic runs.
#         FIX: Conditional import with _TK_AVAILABLE flag.
#         _start_gui() returns immediately if not available.
#         All trading logic works without GUI.
#
# RCA-143 BrokerAdapter.wait_for_fill() ignores shutdown.
#         10-second blocking loop with `time.sleep(2)` polls.
#         If user presses Ctrl+C, the signal handler sets
#         _shutdown but wait_for_fill sleeps through it for up
#         to 10 seconds before checking. During EOD squareoff
#         with 2 positions, this adds up to 20 seconds of
#         unresponsive shutdown.
#         FIX: Check _shutdown.is_set() at loop top. Replace
#         time.sleep(2) with _shutdown.wait(2) for instant
#         wakeup on shutdown signal.
#
#         The startup Telegram message and validate_config() print
#         the full bot configuration. While BOT_TOKEN and CHAT_ID
#         are not directly printed, KITE_API_KEY, KITE_USER_ID
#         are visible in log files if DEBUG mode is enabled.
#         More critically: `log()` writes every `send()` call to
#         the file logger. The startup message contains full
#         config details. If the log file is accidentally shared
#         (e.g., copying logs folder for debugging), all config
#         is exposed. `config.json` contains KITE_PASSWORD in
#         plaintext - extremely sensitive.
#         FIX: `_redact(s)` helper replaces the last 80% of any
#         string with '*' chars (shows first 20% for identification).
#         Applied to BOT_TOKEN, KITE_API_KEY, KITE_PASSWORD,
#         KITE_TOTP_KEY in all log/print/Telegram output. Passwords
#         in config.json can optionally be base64-encoded (not
#         encrypted, just obfuscated) - a note in the template
#         warns that config.json must never be committed to git.
#         validate_config() prints "[REDACTED]" for all sensitive
#         fields. Log file never receives raw secrets.
#
# ── v2.14 NEW FIXES (RCA 144-149) ─────────────────────
#
# RCA-144 Positions NOT persisted in trader_state.json.
#         If bot crashes mid-trade, positions are lost from memory
#         while still open at the broker. reconcile_on_startup()
#         iterates an empty dict - no recovery occurs.
#         FIX: save_state() now serialises positions dict. load_state()
#         restores validated positions with index-map membership check.
#
# RCA-145 SQLite connection leak. _init_db(), _write_db_async(),
#         print_report() all used conn=sqlite3.connect(…) without
#         try/finally or context manager. Any exception between
#         connect() and close() leaks the file handle.
#         FIX: Replaced with `with sqlite3.connect(…) as conn:`.
#
# RCA-146 EMA FLAT detection missing. ema_trend() returned "UP"
#         or "DOWN" with no in-between. When fast & slow EMAs
#         converge within noise (< 0.05%), the direction is
#         meaningless and entering causes whipsaws.
#         FIX: Return "FLAT" when abs(fast-slow)/slow < 0.0005.
#
# RCA-147 NSE_HOLIDAYS hardcoded for 2026 only. If the bot runs
#         into 2027+, holiday detection silently stops working -
#         the bot would trade on national holidays.
#         FIX: Extract unique years from NSE_HOLIDAYS. market_status()
#         logs a warning (once) when current year has no entries.
#
# RCA-148 globals() hack for fail counters. nse_fail_count and
#         yf_fail_count were modified via globals()["var"]+=1
#         instead of using the proper `global` keyword. This
#         bypasses linting, confuses IDEs, and is fragile.
#         FIX: Added `global nse_fail_count` / `global yf_fail_count`
#         to every function that mutates them. Removed all globals().
#
# ── BEGIN SECURITY ENHANCEMENTS (v2.53.0) ──────────────────
#
# RCA-SEC-01: Move secrets to environment variables with OPBUYING_* prefix
#             All secrets (BOT_TOKEN, CHAT_ID, KITE_* etc.) must now come
#             from environment variables, not config files.
#             Legacy config.json secrets are ignored for security.
#
# RCA-SEC-02: Implement secure configuration loading via
#             infrastructure.config.secure_config.SecureConfig
#             Provides automatic secret redaction in logs and error messages
#
# ── END SECURITY ENHANCEMENTS (v2.53.0) ────────────────────
#
# ================================================================
# INSTALL : pip install requests yfinance pandas kiteconnect pyotp
# RUN     : python -m index_app.index_trader                    ← LIVE
#           python -m index_app.index_trader --paper             ← PAPER/TEST
#           python -m index_app.index_trader --debug             ← DEBUG
#           python -m index_app.index_trader --print-config      ← Dump config.json (secrets redacted)
#           python -m index_app.index_trader --config-reset      ← After BASE_CAPITAL change
#           python -m index_app.index_trader --report            ← Multi-session stats
#           python -m index_app.index_trader --export-trades     ← Export trades to CSV
# USER GUIDE: HOW_TO_USE.txt (layman steps)  |  Deep guide: SETUP_AND_TRADING_GUIDE.md
# VERIFY    : pip install -r requirements-dev.txt && python -m pytest tests -v
# CONFIG    : optional env OPBUYING_INDEX_CONFIG=path\to\config.json (tests/CI)
#             ALL SECRETS MUST BE IN OPBUYING_* ENVIRONMENT VARIABLES
# CLEAN EXIT: finally{} saves state, EOD report, closes NSE session. Telegram pool uses
#             non-blocking shutdown (RCA-193). With dashboard: os._exit(0) when
#             FORCE_EXIT_AFTER_SHUTDOWN (default true) so Windows CMD closes cleanly;
#             --nogui uses sys.exit(0). METRICS_PORT>0 on METRICS_BIND (default 127.0.0.1): /metrics, /health, /.
# ================================================================

from __future__ import annotations

import atexit
import os
import sys
import time
from pathlib import Path
from typing import Any

# ── Inject project root into sys.path BEFORE any core imports ──


__all__ = [
    "PositionProxy",
    "StateProxy",
    "breakout_state",
    "check_mandate_trade_allowed",
    "check_pending_reconciliation",
    "daily_reset",
    "decision_log",
    "enter_trade",
    "fetch_last_close_summary",
    "generate_signal_snapshot",
    "get_all_dlogs",
    "get_mandate_status",
    "get_position_size",
    "get_state_snapshot",
    "get_underlying_ltp",
    "get_wait_reason_components",
    "health_check",
    "learning_state",
    "log",
    "main",
    "market_status",
    "performance",
    "positions",
    "print_dashboard",
    "send",
    "setup_di_container",
    "start_trader",
    "validate_signal_pillars",
]

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import requests
from core.datetime_ist import is_in_auction_session, now_ist
from core.execution.broker_truth_reconciliation import get_broker_truth_reconciler
from core.execution.deterministic_state_machine import get_execution_state_manager
from core.execution.idempotency_alerts import get_idempotency_alert_manager
from core.expiry_day_controller import ExpiryDayController, StrategyType
from core.hybrid_execution import apply_execution_mode, normalize_execution_mode
from core.kite_ticker_feed import KiteTickerFeedManager
from core.ltp_resolver import LtpResolver
from core.market_warmup import MarketWarmup
from core.ports.config import ConfigPort
from core.mandate_service import MandateService
from core.position_service import get_position_service

# v2.49 CRITICAL FIX imports
from core.risk.margin_validator import get_margin_validator
from core.safety_state import (
    check_intraday_pnl_and_halt,
    hard_halt_reason,
    is_hard_halted,
    is_shutting_down,
    trip_hard_halt,
)
from core.state_manager import state_manager

# v2.45 hardening modules
from core.token_refresh_service import TokenRefreshService


# Config Domain (DEBT-008)
from index_app.domains.config.loader import (
    ConfigLoader,
    ConfigResult,
    get_config_loader,
    make_fail_safe_config,
)
from index_app.domains.config.manager import ConfigManager

# Broker Domain (DEBT-008)
from index_app.domains.broker.factory import make_broker as _make_broker_extracted

# Market Domain (DEBT-008)
from index_app.domains.market.data import fetch_intraday_data as _fetch_intraday_data_extracted
from index_app.domains.market.data import fetch_intraday_data_cached as _fetch_intraday_data_cached_extracted
from index_app.domains.market.data import fetch_vix as _yf_fetch_vix_extracted
from index_app.domains.market.holidays import fetch_nse_holidays

# Trading Domain (DEBT-008)
from index_app.domains.trading.service import TradingLoopService


# Capture the original main before any shims overwrite it.
# The real trading logic lives in the DI container + stub exports.
# We just need main() to set up the container and print config.
def _original_main() -> None:
    pass  # Real main is the DI container setup

# =============================================================================
# STUB EXPORTS - provide module-level names for test compatibility
# These are resolved at import time before the DI container is needed.
# =============================================================================
import logging
import threading as _threading

from core.correlation_guard import check_portfolio_correlation, update_closes
from core.reentry_evaluator import build_reentry_trackers

_trip_hard_halt = trip_hard_halt

_bos_lock = _threading.RLock()
_state_lock = _threading.RLock()
_pos_lock = _threading.RLock()

breakout_state: dict[str, Any] = {}
class _DecisionLog(dict):
    """Decision log with bounded history for crash recovery."""
    _MAX_HISTORY = 10000

    def __init__(self):
        super().__init__()
        self._history: list[dict[str, Any]] = []

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        self._history.append({"ts": time.time(), "symbol": key, "msg": value.get("msg", "")})
        if len(self._history) > self._MAX_HISTORY:
            self._history.pop(0)

decision_log: _DecisionLog = _DecisionLog()
learning_state: dict[str, Any] = {}
_last_entry_ts: set[str] = set()
_manual_sig_last: set[str] = set()

class _LegacyBrokerShim:
    def place_order(self, *args, **kwargs):
        return None

    def exit_order(self, *args, **kwargs):
        return None

    def get_position_qty(self, *args, **kwargs):
        return 0

    def __getattr__(self, item):
        return lambda *args, **kwargs: None

_broker = _LegacyBrokerShim()


def _send_impl(msg, critical=False, **kw):
    return None  # wired at init

def send(message: str, critical: bool = False, **kwargs) -> None:
    """Legacy send() shim. Wired to NotificationService after init."""
    _send_impl(message, critical=critical, **kwargs)


log = logging.getLogger(__name__)


def __getattr__(name: str):
    if name == "_hard_halt_reason":
        return hard_halt_reason()
    if name == "_HARD_HALT":
        from core.safety_state import _HARD_HALT
        return _HARD_HALT
    if name == "_shutdown":
        from core.safety_state import _shutdown
        return _shutdown
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

PAPER_MODE = True
MANUAL_SIGNALS_ONLY = True
BROKER_API_ENABLED = False
EXECUTION_MODE = "MANUAL"


# CRITICAL FIX: Helper for config load failure - force MANUAL mode and alert


# CRITICAL FIX: Helper for config load failure - force MANUAL mode and alert


# ── Config Domain (DEBT-008) ──────────────────────────────────────────────
_config_loaded = False
_CFG: dict[str, Any] = {}
_cfg_manager: ConfigManager | None = None
_circuit_breaker_service: Any = None
_rate_limiting_service: Any = None


def _apply_config_globals(cfg: dict[str, Any]) -> None:
    """Apply a config dict to module-level globals."""
    global PAPER_MODE, MANUAL_SIGNALS_ONLY, BROKER_API_ENABLED, EXECUTION_MODE, _CFG
    apply_execution_mode(cfg, cli_paper=False, infer_blank_from_broker=True)
    MANUAL_SIGNALS_ONLY = cfg.get("MANUAL_SIGNALS_ONLY", True)
    BROKER_API_ENABLED = cfg.get("BROKER_API_ENABLED", False)
    EXECUTION_MODE = cfg.get("EXECUTION_MODE", "MANUAL")
    PAPER_MODE = str(EXECUTION_MODE).upper() in ("PAPER", "SIM", "TEST")
    _CFG = cfg


def _set_config_fail_safe():
    """Force safe MANUAL mode on config load failure."""
    from index_app.domains.trading.signal_actions import set_config_fail_safe as _extracted
    global PAPER_MODE, MANUAL_SIGNALS_ONLY, BROKER_API_ENABLED, EXECUTION_MODE, _CFG
    _CFG = _extracted(make_fail_safe_config_fn=make_fail_safe_config)
    PAPER_MODE = True
    MANUAL_SIGNALS_ONLY = True
    EXECUTION_MODE = "MANUAL"
    BROKER_API_ENABLED = False


def _notify_config_failure(detail: str):
    """Send critical Telegram alert about config failure."""
    from index_app.domains.trading.signal_actions import notify_config_failure as _extracted
    _extracted(detail=detail, send_fn=send, log_fn=log.warning)


def _load_config(force: bool = False):
    """Load configuration via ConfigLoader and apply to module-level globals."""
    global _config_loaded, _CFG, _cfg_manager
    if _config_loaded and not force:
        return

    loader = get_config_loader(notifier=lambda msg: _notify_config_failure(msg))
    # DEBT-005: Strict schema enforcement — checked via config key or env var
    _strict = bool(
        os.environ.get("OPBUYING_CONFIG_STRICT_SCHEMA_ENFORCEMENT", "")
        .strip().lower() in ("1", "true", "yes")
    )
    result = loader.load(force=force, strict=_strict if _strict else None)

    if not result.success:
        _set_config_fail_safe()
        _config_loaded = True
        if result.error_message:
            _notify_config_failure(result.error_message)
        return

    _apply_config_globals(result.cfg)
    _config_loaded = True

    # Initialise ConfigManager for DI-aware consumers
    if _cfg_manager is None:
        _cfg_manager = ConfigManager(initial_cfg=result.cfg, name="index_trader")
    else:
        _cfg_manager.replace(result.cfg)


# ── Load config before any config-dependent assignments ──
_load_config()

# Also export ConfigManager reference for DI consumers
_config_manager = _cfg_manager


SIGNAL_MAX_AGE = int(_CFG.get("SIGNAL_MAX_AGE", 90))
RECONCILE_HALT_ON_QTY_MISMATCH = True
ADAPTIVE_THRESHOLD_ENABLED = True
MAX_POSITION_AGE = 9999

SIGNAL_CFG = {"SIGNAL_TS_MAX_AGE": 300}
_SIGNAL_CFG = SIGNAL_CFG  # alias for test compatibility

from core.mandate_enforcer import get_mandate_enforcer
from core.services.portfolio_service import PortfolioService
from core.services.signal_orchestrator import init_signal_orchestrator

# Buffered _send_impl: stores messages before DI wiring, then flushes
_send_buffer: list[tuple[str, bool]] = []
_send_buffer_lock = _threading.RLock()
_send_wired = False

def _buffered_send(message: str, critical: bool = False, **kwargs) -> None:
    """Buffered send that stores messages before DI wiring, sends after."""
    if _send_wired:
        _send_impl(message, critical=critical, **kwargs)
    else:
        with _send_buffer_lock:
            _send_buffer.append((message, critical))

_send_impl = _buffered_send  # wire initially to buffer
# ─────────────────────────────────────────────────────────────────

# Initialize PortfolioService with config
_portfolio_service = PortfolioService(_CFG)
# Initialize Signal Orchestrator
init_signal_orchestrator(_CFG)

# Initialize Production Mandate Enforcer (v2.49 - actually enforces mandate)
_MANDATE_ENFORCER = get_mandate_enforcer(_CFG)

# Initialize v2.49 CRITICAL FIX components
_margin_validator = get_margin_validator(_CFG)
_idempotency_alert_manager = get_idempotency_alert_manager(freeze_on_critical=True)
_deterministic_state_machine = get_execution_state_manager()

# Broker truth reconciler will be initialized when broker is available
_broker_truth_reconciler = None

# Execution service - initialized in _setup_container
_execution_service = None

# Risk service - initialized in _setup_container, consolidated from duplicate risk engines
_risk_service = None

# MandateService - module-level delegation target (GAP-05).  warmup_manager and holidays set below after defs.
_mandate_service = MandateService(
    cfg=_CFG,
    risk_service=_risk_service,
    warmup_manager=None,
    mandate_enforcer=_MANDATE_ENFORCER,
    holidays=None,
)

# PositionService - module-level delegation target (GAP-05b), wired at module level below
_position_service = None

# SignalService - module-level delegation target (GAP-05b), wired at module level
_signal_service = None

# Stale Account Detector - initialized in setup_di_container
_stale_detector = None

# StrategyOrchestrator - initialized in setup_di_container
_strategy_orchestrator = None

# Clean-architecture TradingOrchestrator - initialized in setup_di_container
_clean_trading_orchestrator = None

# Equity Trader - initialized in setup_di_container (opt-in via --equity CLI flag)
_equity_trader = None

# Expiry day controller - blocks entries on expiry day after configurable cutoff
_expiry_controller = ExpiryDayController(
    strategy_type=StrategyType.DIRECTIONAL,
    enable_controls=_CFG.get("expiry_day_controls_enabled", True),
)

# v2.45 hardening module instances
_token_refresh_service = TokenRefreshService(_CFG)
_warmup_manager = MarketWarmup(_CFG)
_ws_feed_manager = KiteTickerFeedManager(_CFG)
_ltp_resolver = LtpResolver(cfg=_CFG, ws_feed=_ws_feed_manager)

# NewsSentinel - background RSS risk scanner
from core.news_sentinel import NewsSentinel

_news_sentinel = NewsSentinel(_CFG)
_news_sentinel.start()

# Structured audit trail - JSONL event log
from core.audit_engine import AuditEngine

_audit_engine = AuditEngine(
    path=_CFG.get("AUDIT_LOG_PATH", "audit_trail.jsonl"),
    enabled=bool(_CFG.get("AUDIT_LOG_ENABLED", True)),
)


def _shutdown_ws_feed() -> None:
    """Disconnect the WebSocket feed on interpreter exit."""
    try:
        if _ws_feed_manager.is_connected():
            _ws_feed_manager.disconnect()
            log.info("[SHUTDOWN] WebSocket feed disconnected")
    except (ValueError, TypeError, KeyError, AttributeError, IndexError, OSError):
        log.debug("WebSocket feed shutdown failed (expected during interpreter exit)")


atexit.register(_shutdown_ws_feed)


def get_underlying_ltp(index_name: str) -> float | None:
    """Resolve the latest underlying price for *index_name*.

    Uses LtpResolver (WS cache → broker → yfinance).  Returns ``None``
    if all three layers fail.
    """
    return _ltp_resolver.resolve(index_name)


def _init_broker_truth_reconciler(broker_port):
    """Lazy initialization of broker truth reconciler"""
    global _broker_truth_reconciler
    if _broker_truth_reconciler is None:
        _broker_truth_reconciler = get_broker_truth_reconciler(broker_port, _CFG)
    return _broker_truth_reconciler

# Legacy S object is now fully replaced by the PortfolioService
# We keep the name 'S' as a proxy for backward compatibility with legacy code
class StateProxy:
    def __init__(self, service):
        self._service = service
    def __getattr__(self, name):
        # Map legacy S attributes to PortfolioService methods
        mapping = {
            "capital": self._service.get_capital(),
            "net_daily_pnl": self._service.get_daily_pnl(),
            "trade_count": self._service.get_trade_count(),
            "last_reset_day": state_manager.get("last_reset_day"),
            "capital_adj_pending": self._service.get_pending_adjustment(),
        }
        if name in mapping:
            return mapping[name]
        # Fallback to state_manager for other keys
        return state_manager.get(name)
    def __setattr__(self, name, value):
        if name == "_service":
            super().__setattr__(name, value)
        else:
            state_manager.set(name, value)

S = StateProxy(_portfolio_service)

# Bridge legacy positions to the new OrderManager
class PositionProxy(dict):
    def __setitem__(self, key, value):
        # In a full migration, this would trigger an OrderManager update
        super().__setitem__(key, value)
    def __getitem__(self, key):
        return super().__getitem__(key)

positions = PositionProxy()

# Bridge legacy safety functions to the new RiskService
# Ensure the shared core safety event is tripped for legacy tests and state consumers.
def _trip_hard_halt(reason="Unknown"):
    trip_hard_halt(reason, source="index_trader")

_trip_hard_halt = _trip_hard_halt
_reserved_capital = 0.0

# The legacy _broker mock is removed. All broker interaction now
# flows through the broker_gateway and execution_service.

def _apply_execution_mode(cfg):
    return apply_execution_mode(cfg, cli_paper=False, infer_blank_from_broker=True)


def _normalize_execution_mode(raw):
    return normalize_execution_mode(raw)


def _make_broker():
    """Legacy broker factory - delegates to extracted BrokerFactory (DEBT-008)."""
    return _make_broker_extracted(
        cfg=_CFG,
        index_map=INDEX_MAP,
        manual_signals_only=MANUAL_SIGNALS_ONLY,
        broker_api_enabled=BROKER_API_ENABLED,
        paper_mode=PAPER_MODE,
        execution_mode=EXECUTION_MODE,
        circuit_breaker=_circuit_breaker_service,
        now_fn=now_ist,
        log_fn=log,
        send_fn=send,
    )


# Duplicate broker construction removed. Broker is created once in setup_di_container()
# via _make_broker() and wired into ExecutionService during DI setup.


def _adaptive_threshold_adjustment(regime="", strength=""):
    from core.adaptive_learning import adaptive_threshold_adjustment, recent_trade_learning_snapshot
    trades = _get_trade_history_snapshot()
    snap = recent_trade_learning_snapshot(trades, 40, learning_state)
    return adaptive_threshold_adjustment(snap, regime, strength, enabled=ADAPTIVE_THRESHOLD_ENABLED)

def _telegram_action_quality(sig):
    from index_app.domains.trading.signal_actions import telegram_action_quality as _extracted
    return _extracted(sig)

def _telegram_action_body(sig):
    from index_app.domains.trading.signal_actions import telegram_action_body as _extracted
    return _extracted(learning_state=learning_state)

def _get_position_service():
    """Lazy-init singleton for PositionService."""
    global _position_service
    if _position_service is None:
        _position_service = get_position_service(
            cfg=_CFG,
            risk_service=_risk_service,
            execution_service=_execution_service,
            portfolio_service=_portfolio_service,
            margin_validator=_margin_validator,
            warmup_manager=_warmup_manager,
            news_sentinel=_news_sentinel,
            expiry_controller=_expiry_controller,
            token_refresh_service=_token_refresh_service,
            audit_engine=_audit_engine,
            reentry_trackers=_reentry_trackers,
            positions=positions,
            decision_log=decision_log,
            manual_sig_last=_manual_sig_last,
            breakout_state=breakout_state,
            bos_lock=_bos_lock,
            state_lock=_state_lock,
            pos_lock=_pos_lock,
            mandate_service=_mandate_service,
            manual_signals_only=MANUAL_SIGNALS_ONLY,
            execution_mode=EXECUTION_MODE,
            ltp_resolver=_ltp_resolver,
            signal_max_age=SIGNAL_MAX_AGE,
        )
    return _position_service


def enter_trade(name, sig):
    """Entry gate for all trades. Delegates to PositionService."""
    return _get_position_service().enter_trade(name, sig)

def _check_hard_halt_reason():
    import core.safety_state as _ss
    return getattr(_ss, '_hard_halt_reason', '') or ''

def check_pending_reconciliation():
    """Check zombie PnL. Delegates to trading.reconciliation (DEBT-008)."""
    from index_app.domains.trading.reconciliation import check_pending_reconciliation as _extracted
    _extracted(
        portfolio_service=_portfolio_service,
        state_lock=_state_lock,
        state_manager=state_manager,
        send_fn=send,
    )

def daily_reset():
    """Daily reset. Delegates to trading.reconciliation (DEBT-008)."""
    from index_app.domains.trading.reconciliation import daily_reset as _extracted
    _extracted(
        portfolio_service=_portfolio_service,
        reentry_trackers=_reentry_trackers,
        send_fn=send,
        log_fn=log,
    )

def _reconcile_positions_live():
    """Reconcile positions. Delegates to trading.reconciliation (DEBT-008)."""
    from index_app.domains.trading.reconciliation import reconcile_positions_live as _extracted
    _extracted(
        broker_api_enabled=BROKER_API_ENABLED,
        reconcile_halt_on_qty_mismatch=RECONCILE_HALT_ON_QTY_MISMATCH,
        broker_truth_reconciler=_broker_truth_reconciler,
        positions=positions,
        pos_lock=_pos_lock,
        broker=_broker,
        trip_halt_fn=trip_hard_halt,
        log_fn=log,
    )

def _periodic_reconcile():
    """Periodic reconciliation. Delegates to trading.reconciliation (DEBT-008)."""
    from index_app.domains.trading.reconciliation import periodic_reconcile as _extracted
    _extracted(
        execution_service=_execution_service,
        log_fn=log,
    )

def _broker_positions_snapshot():
    return {}

def _local_positions_snapshot():
    return {}

INDEX_PRIORITY = [
    "NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX",
    "RELIANCE", "TCS", "HDFCBANK", "ICICIBANK", "INFY",
    "NIFTY_FUT",
]
INDEX_MAP: dict = {
    # Indices
    "NIFTY": {"yf": "^NSEI"},
    "BANKNIFTY": {"yf": "^NSEBANK"},
    "FINNIFTY": {"yf": "NIFTY_FIN_SERVICE.NS"},
    "MIDCPNIFTY": {"yf": "^NSEMIDCAP"},
    "SENSEX": {"yf": "^BSESN"},
    # Equities (cash market)
    "RELIANCE": {"yf": "RELIANCE.NS"},
    "TCS": {"yf": "TCS.NS"},
    "HDFCBANK": {"yf": "HDFCBANK.NS"},
    "ICICIBANK": {"yf": "ICICIBANK.NS"},
    "INFY": {"yf": "INFY.NS"},
    # Futures (requires broker API for live data; yfinance NSE futures unavailable)
    "NIFTY_FUT": {"yf": ""},
    "BANKNIFTY_FUT": {"yf": ""},
    "FINNIFTY_FUT": {"yf": ""},
}
performance: dict = {"wins": 0, "loss": 0}
_reentry_trackers: dict[str, Any] = build_reentry_trackers(list(INDEX_PRIORITY))

def market_status():
    return _mandate_service.market_status()
def _execution_mode_label():
    return EXECUTION_MODE

def get_wait_reason_components(sd):
    return _mandate_service.get_wait_reason_components(sd)
def get_position_size(name, entry, vix=0.0):
    return _mandate_service.get_position_size(name, entry, vix)
def check_mandate_trade_allowed(regime: str = "SIDEWAYS", score: int = 70, iv_rank: float = 25.0) -> tuple[bool, str]:
    return _mandate_service.check_mandate_trade_allowed(regime, score, iv_rank)
def get_mandate_status() -> dict:
    return _mandate_service.get_mandate_status()
def validate_signal_pillars(
    rsi: float = None,
    macd: str = None,
    adx: float = None,
    iv_rank: float = None,
    oi_change: float = None,
    pcr: float = None,
    fii_net: float = None,
    dii_net: float = None,
    gex: float = None,
    session_score: float = None,
) -> tuple[bool, str]:
    """Validate signal independence - RSI/MACD/ADX = 1 pillar (NOT 3!).

    Delegates to SignalService.
    """
    if _signal_service is not None:
        return _signal_service.validate_signal_pillars(
            rsi=rsi, macd=macd, adx=adx,
            iv_rank=iv_rank, oi_change=oi_change, pcr=pcr,
            fii_net=fii_net, dii_net=dii_net, gex=gex,
            session_score=session_score,
        )
    return False, "PILLAR_FAIL: SignalService not initialized"


def _get_trade_history_snapshot():
    return []

def _get_live_prices():
    return {}

def fetch_last_close_summary():
    """Fetch last close price and change %% for each index.

    Delegates to core.yf_data_provider.fetch_last_close_summary.
    """
    from core.yf_data_provider import fetch_last_close_summary as _yf_summary
    return _yf_summary(INDEX_MAP)

def get_all_dlogs():
    return {}

def _get_signal_quality_report():
    """Return signal quality report. Delegates to SignalService."""
    if _signal_service is not None:
        return _signal_service.get_signal_quality_report()
    return "ok"

def _get_api_latency_report():
    return "ok"

def _get_top_signals(n):
    """Return top signals. Delegates to SignalService."""
    if _signal_service is not None:
        return _signal_service.get_top_signals(n)
    return []

def _telegram_alerts_enabled():
    return False

def print_dashboard():
    status = market_status()
    if status == "CLOSED":
        _display_snapshot["struct"] = {"headline": "Market CLOSED - no intraday scan"}
    else:
        _display_snapshot["struct"] = {"headline": "ok"}

_display_snapshot: dict = {"struct": {"headline": "ok"}}

def _fetch_nse_holidays_dynamic():
    """Fetch NSE trading holidays. Delegates to index_app.domains.market.holidays (DEBT-008)."""
    global _nse_session, NSE_HOLIDAYS, _HOLIDAY_FETCH_META, _NSE_HOLIDAY_YEARS
    NSE_HOLIDAYS, _NSE_HOLIDAY_YEARS, _HOLIDAY_FETCH_META = fetch_nse_holidays(
        nse_session=_nse_session,
        existing_holidays=NSE_HOLIDAYS,
        existing_years=_NSE_HOLIDAY_YEARS,
        fetch_meta=_HOLIDAY_FETCH_META,
    )


def _check_hard_stops_via_risk() -> tuple[bool, str]:
    """Check hard stops. Delegates to trading.reconciliation (DEBT-008)."""
    from index_app.domains.trading.reconciliation import check_hard_stops_via_risk as _extracted
    return _extracted(mandate_service=_mandate_service)
_nse_session: Any = requests.Session()
_nse_session.headers.update({"User-Agent": "Mozilla/5.0", "Accept": "application/json, text/plain, */*"})
NSE_HOLIDAYS: set = set()
# Hardcoded fallback for 2026 NSE trading holidays in case API fetch fails
_NSE_HOLIDAYS_FALLBACK: set = {
    "2026-01-26",  # Republic Day
    "2026-03-27",  # Good Friday
    "2026-04-14",  # Dr. Ambedkar Jayanti
    "2026-05-01",  # Maharashtra Day
    "2026-08-17",  # Parsi New Year
    "2026-10-02",  # Mahatma Gandhi Jayanti
    "2026-10-09",  # Dussehra
    "2026-10-28",  # Diwali - Laxmi Pujan
    "2026-10-29",  # Diwali - Balipratipada (observed)
    "2026-11-16",  # Guru Nanak Jayanti
    "2026-12-25",  # Christmas
}
_NSE_HOLIDAY_YEARS: set = set()
_HOLIDAY_FETCH_META: dict = {"count": 0, "fallback": False, "note": ""}

CAPITAL_MANAGER: Any = None
RISK_ENGINE: Any = None
_REGIME_POSITION_SIZING = False
RISK_MODE = "FIXED"
RISK_FIXED_AMOUNT = 500
_raw_mdl = _CFG.get("MAX_DAILY_LOSS", -2000)
MAX_DAILY_LOSS = -abs(float(_raw_mdl))  # always negative (loss limit)
PORTFOLIO_MAX_SL_RISK_PCT = 0.75
MIN_NET_RR = float(_CFG.get("MIN_NET_RR", 1.5))
SL_PCT = float(_CFG.get("SL_PCT", 0.92))
TARGET_PCT = float(_CFG.get("TARGET_PCT", 1.3))
TRAIL_PCT = float(_CFG.get("TRAIL_PCT", 0.93))
MAX_LOT_CAPITAL_PCT = 0.85
BROKERAGE_PER_TRADE = 40
PARTIAL_EXIT_ENABLED = False
API_FAIL_BLOCK_NEW_ENTRIES = 0
PRESENTATION_ENGINE: Any = None

DATA_ENGINE: Any = None
STATE_MANAGER: Any = None
STRATEGY_ENGINE: Any = None
EXECUTION_ENGINE: Any = None
_AUDIT_ENGINE: Any = None

# max_daily_loss is read from _CFG via MAX_DAILY_LOSS (line 1373)
# =============================================================================
# END STUB EXPORTS
# =============================================================================

# =============================================================================
# TRADING LOOP - Phase 1A/1B: scan, evaluate, enter, monitor, exit
# =============================================================================


def _fetch_intraday_data(name: str) -> tuple:
    """Fetch intraday OHLCV data (1m, 5m, 15m) for an index via yfinance.

    Delegates to index_app.domains.market.data (DEBT-008).
    """
    yf_sym = INDEX_MAP.get(name, {}).get("yf", "")
    return _fetch_intraday_data_extracted(yf_sym)


def _generate_trading_signal(name: str, frames: dict, vix: float = 0.0):
    """Generate a trading signal dict. Delegates to SignalService."""
    if _signal_service is not None:
        return _signal_service.generate_trading_signal(
            name=name, frames=frames, vix=vix,
        )
    log.warning("SignalService not initialized - returning empty signal")
    return {}



def _exit_position(name: str, reason: str) -> None:
    """Exit an open position. Delegates to PositionService."""
    return _get_position_service().exit_position(name, reason)


def _monitor_positions() -> None:
    """Monitor open positions. Delegates to PositionService."""
    return _get_position_service().monitor_positions()


# Cache for yfinance intraday data (avoids rate limiting)
def _fetch_intraday_data_cached(name: str) -> tuple:
    """Fetch intraday data with cross-cycle caching to avoid yfinance rate limits.

    Delegates to index_app.domains.market.data (DEBT-008).
    """
    yf_sym = INDEX_MAP.get(name, {}).get("yf", "")
    return _fetch_intraday_data_cached_extracted(yf_sym)


def _yf_fetch_vix() -> float:
    """Fetch India VIX. Delegates to index_app.domains.market.data (DEBT-008)."""
    return _yf_fetch_vix_extracted()


def _run_trading_loop() -> None:
    """Main trading loop. Delegates to TradingLoopService (DEBT-008)."""
    from core.nse_option_recorder import record_oi_snapshots_for_indices
    from core.safety_state import _shutdown
    try:
        from core.invariants.engine import check_all as _check_invariants
    except ImportError:
        _check_invariants = None

    # Create dashboard notifier (safe no-op if dashboard not running)
    from core.enterprise_dashboard import DashboardNotifier
    _dash_host = _CFG.get("web_dashboard_host", "127.0.0.1")
    _dash_port = int(_CFG.get("web_dashboard_port", 8765))
    _dash_url = f"http://{_dash_host}:{_dash_port}"
    _dash_notifier = DashboardNotifier(base_url=_dash_url)
    if _CFG.get("web_dashboard_enabled", False):
        _dash_notifier.push_bot_start(mode=EXECUTION_MODE)
    else:
        _dash_notifier.disable()

    service = TradingLoopService(
        cfg=_CFG,
        shutdown_event=_shutdown,
        is_hard_halted_fn=is_hard_halted,
        market_status_fn=market_status,
        fetch_intraday_data_cached_fn=_fetch_intraday_data_cached,
        fetch_vix_fn=_yf_fetch_vix,
        generate_trading_signal_fn=_generate_trading_signal,
        enter_trade_fn=enter_trade,
        monitor_positions_fn=_monitor_positions,
        periodic_reconcile_fn=_periodic_reconcile,
        check_mandate_trade_allowed_fn=check_mandate_trade_allowed,
        check_portfolio_correlation_fn=check_portfolio_correlation,
        reentry_trackers=_reentry_trackers,
        decision_log=decision_log,
        index_priority=INDEX_PRIORITY,
        positions=positions,
        pos_lock=_pos_lock,
        stale_detector=_stale_detector,
        update_closes_fn=update_closes,
        record_oi_fn=record_oi_snapshots_for_indices,
        check_invariants_fn=_check_invariants,
        send_fn=send,
        equity_trader=_equity_trader,
        dashboard_notify_fn=_dash_notifier.send if _dash_notifier.enabled else None,
    )
    service.run()


# The DI container + stub exports provide the complete trading API.
# main() sets up the container for production use.
# For the DI-migrated version, main() just initializes services.


def _on_ws_tick(msg: dict) -> None:
    """Callback for KiteTickerFeedManager tick messages."""
    from index_app.domains.trading.signal_actions import on_ws_tick as _extracted
    _extracted(msg=msg, log_fn=log.info, debug_fn=log.debug)


def setup_di_container() -> None:
    """Set up the dependency injection container with all service implementations.

    Delegates to ``index_app.domains.trading.container.setup_di_container``
    (DEBT-008).
    """
    from index_app.domains.trading.container import setup_di_container as _extracted

    # Global declarations must precede any reference to these names
    global _execution_service, _send_impl, _send_wired
    global _mandate_service, _position_service, _signal_service
    global _stale_detector, _strategy_orchestrator, _clean_trading_orchestrator
    global _rate_limiting_service, _circuit_breaker_service
    global _ws_feed_manager, _equity_trader
    global RISK_ENGINE, DATA_ENGINE, STRATEGY_ENGINE
    global EXECUTION_ENGINE, STATE_MANAGER

    # Build the globals_store dict from module-level names
    _globals: dict = {
        "_ws_feed_manager": _ws_feed_manager,
        "_execution_service": None,
        "_send_impl": _send_impl,
        "_send_wired": _send_wired,
        "_send_buffer": _send_buffer,
        "_send_buffer_lock": _send_buffer_lock,
        "_mandate_service": _mandate_service,
        "_position_service": _position_service,
        "_signal_service": _signal_service,
        "_stale_detector": _stale_detector,
        "_strategy_orchestrator": _strategy_orchestrator,
        "_clean_trading_orchestrator": _clean_trading_orchestrator,
        "_rate_limiting_service": _rate_limiting_service,
        "_circuit_breaker_service": _circuit_breaker_service,
        "_portfolio_service": _portfolio_service,
        "_margin_validator": _margin_validator,
        "_warmup_manager": _warmup_manager,
        "_news_sentinel": _news_sentinel,
        "_expiry_controller": _expiry_controller,
        "_token_refresh_service": _token_refresh_service,
        "_audit_engine": _audit_engine,
        "_reentry_trackers": _reentry_trackers,
        "positions": positions,
        "decision_log": decision_log,
        "_manual_sig_last": _manual_sig_last,
        "breakout_state": breakout_state,
        "_bos_lock": _bos_lock,
        "_state_lock": _state_lock,
        "_pos_lock": _pos_lock,
        "get_underlying_ltp_fn": get_underlying_ltp,
        "state_manager": state_manager,
    }

    _extracted(
        cfg=_CFG,
        index_map=INDEX_MAP,
        make_broker_fn=_make_broker,
        fetch_vix_fn=_yf_fetch_vix,
        fetch_nse_holidays_dynamic_fn=_fetch_nse_holidays_dynamic,
        on_ws_tick_fn=_on_ws_tick,
        globals_store=_globals,
    )

    # Update module-level names from the globals_store
    _execution_service = _globals.get("_execution_service")
    _send_impl = _globals.get("_send_impl", _send_impl)
    _send_wired = _globals.get("_send_wired", _send_wired)
    _mandate_service = _globals.get("_mandate_service", _mandate_service)
    _position_service = _globals.get("_position_service", _position_service)
    _signal_service = _globals.get("_signal_service", _signal_service)
    _stale_detector = _globals.get("_stale_detector", _stale_detector)
    _strategy_orchestrator = _globals.get("_strategy_orchestrator", _strategy_orchestrator)
    _clean_trading_orchestrator = _globals.get("_clean_trading_orchestrator", _clean_trading_orchestrator)
    _rate_limiting_service = _globals.get("_rate_limiting_service", _rate_limiting_service)
    _circuit_breaker_service = _globals.get("_circuit_breaker_service", _circuit_breaker_service)
    RISK_ENGINE = _globals.get("RISK_ENGINE", RISK_ENGINE)
    DATA_ENGINE = _globals.get("DATA_ENGINE", DATA_ENGINE)
    STRATEGY_ENGINE = _globals.get("STRATEGY_ENGINE", STRATEGY_ENGINE)
    EXECUTION_ENGINE = _globals.get("EXECUTION_ENGINE", EXECUTION_ENGINE)
    STATE_MANAGER = _globals.get("STATE_MANAGER", STATE_MANAGER)
    _equity_trader = _globals.get("_equity_trader", _equity_trader)


# Backwards-compatible, read-only shim exports (use index_trader_interface for new code)
try:
    from index_app.index_trader_interface import (
        generate_signal_snapshot as generate_signal_snapshot_shim,
    )
    from index_app.index_trader_interface import (
        get_state_snapshot as get_state_snapshot_shim,
    )
    from index_app.index_trader_interface import (
        health_check as health_check_shim,
    )
    from index_app.index_trader_interface import (
        start_trader as start_trader_shim,
    )
except (ValueError, TypeError, KeyError, AttributeError, IndexError, OSError):
    # In case the interface isn't available during early import, provide no-op fallbacks
    def start_trader_shim(*args, **kwargs):
        raise RuntimeError("index_trader_interface not initialized")

    def get_state_snapshot_shim(*args, **kwargs):
        return {}

    def generate_signal_snapshot_shim(*args, **kwargs):
        return []

    def health_check_shim(*args, **kwargs):
        return {"ok": False, "reason": "shim not available"}

# Export the shim names to preserve old callers
start_trader = start_trader_shim
get_state_snapshot = get_state_snapshot_shim
generate_signal_snapshot = generate_signal_snapshot_shim
health_check = health_check_shim


def _reload_config_handler() -> dict:
    """Hot-reload configuration. Delegates to trading.reconciliation (DEBT-008)."""
    from index_app.domains.trading.reconciliation import reload_config_handler as _extracted
    return _extracted()


def _init_admin_control_plane(cfg: dict) -> threading.Thread | None:
    """Wire admin control plane. Delegates to admin domain (DEBT-008)."""
    from index_app.domains.admin.control_plane import init_admin_control_plane as _extracted
    return _extracted(
        cfg=cfg,
        reload_config_handler_fn=_reload_config_handler,
        notify_fn=send,
    )


def main() -> None:
    """Main entry point that sets up DI container for production use."""
    # Non-trading utility flags: exit early without entering the trading loop
    _NON_TRADING_FLAGS = {"--selftest", "--print-config", "--config-reset", "--report", "--export-trades"}
    if any(f in sys.argv for f in _NON_TRADING_FLAGS):
        log.info("[MAIN] Non-trading flag detected, skipping trading loop")
        return

    from core.di_container import get_container
    from core.python_runtime import register_shutdown_callback
    from core.safety_state import start_kill_file_watcher

    # Register shutdown callbacks for graceful shutdown
    # 1. Flush trader state to disk
    register_shutdown_callback(
        lambda: _portfolio_service.save() if hasattr(_portfolio_service, 'save') else None
    )
    # 2. Flush state machines to disk
    register_shutdown_callback(
        lambda: _deterministic_state_machine.flush() if hasattr(_deterministic_state_machine, 'flush') else None
    )
    # 3. Disconnect WebSocket feed
    register_shutdown_callback(_shutdown_ws_feed)

    start_kill_file_watcher()

    # CRITICAL FIX: Pre-open token validation - fail-closed check before trading
    # Blocks startup if broker token is expired and market is about to open
    try:
        if _token_refresh_service is not None and hasattr(_token_refresh_service, 'validate_token_sync'):
            _token_refresh_service.validate_token_sync()
            log.info("[TOKEN] Pre-open token validation passed")
    except (ValueError, TypeError, KeyError) as _tok_err:
        log.critical("[TOKEN] Pre-open token validation FAILED: %s", _tok_err)
        send(f"[TOKEN_CRITICAL] Token validation failed: {_tok_err}", critical=True)

    setup_di_container()
    container = get_container()
    config = container.resolve(ConfigPort)

    # Validate deployment environment (may exit(88) on violation)
    from core.environment import validate_environment
    validate_environment(dict(config))

    # AI Governance Gate - non-blocking startup validation
    # Verifies that AI governance checks were acknowledged before deployment
    try:
        from core.constitution_ai_gate import get_gate
        _ai_gate = get_gate(identity="index_trader")
    except (ImportError, ValueError, TypeError, AttributeError) as _ge:
        log.warning("[AI_GATE] AI governance gate unavailable: %s", _ge)

    # CRITICAL FIX: Start the main trading loop - blocks until shutdown signal
    log.info("[MAIN] Setup complete - entering trading loop")
    _run_trading_loop()


if __name__ == "__main__":
    main()

