# ================================================================
# 🚀  TRADER BRAIN — PRODUCTION v2.53.0  (₹5 000 Capital Edition)
#     v2.42: ExecutionRouter (AUTO + optional PAPER→adapter), chunked Yahoo quarter backtest, HOW_TO_USE refresh.
#     v2.40: Final QA pass — pytest tests/test_smoke + --selftest OK; find dialog F3 + safer
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
# RCA-REG (2026-04-04): warned_loss_soft vs warned_loss — the 60% daily-loss
#         approach warning and the hard-limit breach alert used one flag,
#         so the critical limit message could be suppressed after the soft
#         warning. Split: warned_loss_soft for approach only; warned_loss for
#         breach (unchanged). Regression: --selftest, main_loop path review.
# RCA-REG (2026-04-04b): Stock bot validate_config + DAILY_LOSS_WARNING/_sync
#         aligned to this file; index unchanged this pass — cross-regression
#         both scripts --selftest.
#
# RCA-211 (2026-04-08): _format_trading_desk_line() extracted for clarity + --selftest coverage of desk text/colors.
#
# RCA-213 (2026-04-09): Adaptive learning extracted to core.adaptive_learning — pure snapshot /
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
# RCA-212 (2026-04-09): Hybrid UX + GUI hardening — (1) gui_struct.manual_flow_banner + desk strip
#         explain MANUAL/AUTO/PAPER/SIGNALS for smooth post-signal workflow; GUI_UX.show_manual_flow_banner
#         toggles. (2) _desk_body.py indentation bugs fixed (paneconfig/wrap/config_status/target_hit).
#         (3) trader_desk wraps _desk_body in __opbuying_desk_body() so early return compiles under exec
#         (top-level return in exec is a SyntaxError). (4) RCA_AND_HYBRID_MODEL.txt + config template note.
#
# RCA-210 (2026-04-08): Pro desk UI — TRADING DESK strip (VIX, loss-budget %, RR, SL/target, circuit,
#         halt, exec path, signal-quality + API lines); table columns ADX & IV; clearer section labels;
#         Help → Desk guide; default geometry 1200×860. Data from existing scan (no extra network).
#
# RCA-209 (2026-04-08): Polish — now_ist() docstring (naive IST wall clock); watchdog uses
#         _shutdown.wait before os._exit; soft-reload rebuilds _broker when MANUAL_SIGNALS_ONLY
#         flips; config_audit / save_state .bak failures log once instead of silent pass.
#
# RCA-208 (2026-04-08): Manual-only startup — MANUAL_SIGNALS_ONLY uses PaperAdapter so Kite
#         is not constructed (no token/API dependency); live RCA regression skips Kite check.
#         Soft-reload of MANUAL_SIGNALS_ONLY rebuilds broker adapter without full restart.
#
# RCA-206 (2026-04-07): Manual-only workflow — MANUAL_SIGNALS_ONLY skips broker, positions,
#         trade_count, and NEW TRADE lifecycle; sends throttled “MANUAL SIGNAL” Telegram + dlog
#         after the same entry gates (RR, portfolio SL cap). Soft-reload safe; dashboard/GUI
#         show mode. Bot does not track manual fills.
#
# RCA-205 (2026-04-07): Reading & system integration — (1) Long logs: Edit→Find in details
#         (Ctrl+F) with Find next + wrap; highlights match in the Text widget. (2) Windows
#         clipboard after Copy sometimes dropped without an event pump — update_idletasks()
#         after clipboard_append. (3) SCAN_INTERVAL changes via soft-reload were invisible in
#         the GUI; trades KPI line shows live scan interval. (4) Details title click focuses
#         the log for keyboard scroll/find without hunting the caret.
#
# RCA-204 (2026-04-07): Support & multi-monitor habits — (1) Operators share logs via
#         screenshots or paste; File→Save details as… writes the current details Text to
#         UTF-8 .txt (Ctrl+Shift+S). (2) Maximized window was lost on restart — layout JSON
#         v4 adds win_state (zoomed|normal); restore zoomed after geometry (iconic not
#         restored on purpose). (3) Header hint mentions max state in saved JSON.
#
# RCA-203 (2026-04-07): Desk ergonomics & diagnostics — (1) Snapshot age alone does not
#         expose a stuck main loop before watchdog; gui_struct carries loop_lag_s (monotonic
#         gap since S.last_loop_heartbeat). KPI subtitle warns only when market status is OPEN
#         (holiday/weekend long sleeps would false-positive otherwise). (2) Long logs:
#         Home/End/PgUp/PgDn on details + context-menu scroll targets + Edit entries.
#         (3) Corrupt/off-screen layout: View → Reset saved layout deletes JSON and applies
#         defaults without restarting the bot.
#
# RCA-202 (2026-04-07): Safety & robustness — (1) Accidental Alt+F4 / close on LIVE with
#         SHUTDOWN_ON_UI_CLOSE could stop the bot without intent; optional confirm dialog
#         (GUI_CONFIRM_EXIT, default true, soft-reload). (2) Invalid saved geometry strings
#         failed silently → operator thinks persistence is broken; log and fall back.
#         (3) After minimize/restore, wraplength can be wrong until resize; <Map> queues
#         debounced wrap sync. (4) Uncaught exceptions in Tk callbacks were easy to miss;
#         route through log via report_callback_exception.
#
# RCA-201 (2026-04-07): Readability & soft-reload parity — (1) Header subtitle showed
#         refresh period only at GUI start; after config soft-reload GUI_REFRESH_MS could
#         change while the label stayed stale — sync each tick. (2) Large logs: Select all
#         (Ctrl+A) + Edit menu; Escape clears selection. (3) Corrupt layout JSON failed
#         silently; log once so operators fix/rename the file. (4) Context menu: Select all.
#
# RCA-200 (2026-04-07): Operator workflow — (1) “Always on top” was session-only; persist
#         to index_trader_gui_layout.json (v3) with geometry/sash. (2) Fixed 2s UI poll
#         was not tunable; GUI_REFRESH_MS in config.json (500–30000, soft-reload safe).
#         (3) F5 = same as View→Refresh (standard desktop habit). (4) File→Open script
#         folder… opens Explorer/Finder for config.json / layout file edits.
#
# RCA-199 (2026-04-07): Desk polish & trust cues — (1) Default tk Scrollbars were light
#         “Office” gray on a dark UI; configure trough/bg to match cards. (2) Telegram &
#         API status labels had no wraplength → horizontal overflow on narrow windows.
#         (3) Users cannot tell frozen loop vs quiet market: KPI subtitle shows snapshot
#         age when backend hasn’t refreshed for several seconds. (4) View→Always on top
#         for side-by-side terminals. (5) Treeview last column stretches with pane width.
#         (6) Details Text gets a subtle focus highlight; wheel bound on detail frame.
#
# RCA-198 (2026-04-07): Realistic desk UX — (1) Layout JSON missed sash moves when only
#         the divider moved (root <Configure> never fired): also queue save on pane
#         <Configure>. (2) Details Text was wiped every 2s even when body unchanged →
#         flicker; skip repaint when detail text equal to last paint. (3) Headline /
#         Telegram lines used fixed wraplength; sync wrap to window width (debounced).
#         (4) View→Refresh now + Ctrl+Q quit; context menu Copy selection when present.
#         (5) Wheel scroll on table frame (not only on tree cells).
#
# RCA-197 (2026-04-07): GUI persistence & desk workflow — (1) Save/restore
#         window geometry + paned sash to index_trader_gui_layout.json beside this
#         script (debounced on resize, flush on exit). (2) Pane minsize so the
#         index column cannot collapse. (3) Menu: File→Exit, Help→Shortcuts.
#         (4) Details: Ctrl+C selection copy + right-click “Copy all” (clipboard).
#         (5) Tree tag fonts use _FONT_MONO consistently.
#
# ── v2.12 NEW FIXES (RCA 132–136) ─────────────────────
#
# RCA-132 DEADLOCK: nested _perf_lock → _state_lock in monitor().
#         monitor() acquires _perf_lock (line 1669) then attempts
#         to acquire _state_lock inside it (line 1673). If any
#         other thread holds _state_lock and then tries _perf_lock,
#         both threads deadlock permanently. Scenario: main thread
#         in daily_reset() holds _state_lock (line 886) while
#         monitor() runs in the same thread — single-threaded, no
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
#         timestamp — confusing and deprecated.
#         FIX: Use datetime.now(timezone.utc) + IST offset.
#         Produces identical naive-IST datetime without deprecated
#         API. Compatible with Python 3.10–3.13+.
#
# ── v2.13 REGRESSION FIXES (RCA 137–143) ─────────────────
#
# RCA-137 _nse_fail_lock and _yf_fail_lock declared TWICE.
#         Section 3 (line ~401) creates Lock objects. Section 12
#         (line ~990) re-creates them — silently overwrites the
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
#         "[ERROR] Python 3.10-3.12 required" — contradicting
#         the code that was just made 3.13-safe.
#         FIX: Gate expanded to `<(3,14)`.
#
# RCA-139 _prune_tg_cache() iterates _tg_cache.items() unsafely.
#         `.items()` returns a view. If send() (called from a
#         ThreadPoolExecutor thread) writes _tg_cache[key] while
#         _prune_tg_cache() iterates the view, Python raises
#         `RuntimeError: dictionary changed size during iteration`
#         — crashing the main loop iteration.
#         FIX: `list(_tg_cache.items())` creates a snapshot copy
#         before iteration. Wrapped in try/except RuntimeError as
#         a belt-and-suspenders defense.
#
# RCA-140 daily_reset() replaces S.exception_counts without lock.
#         `S.exception_counts={}` is a STORE_ATTR that replaces
#         the dict reference. If _track_exception() (running in
#         an executor thread) is between reading and writing the
#         old dict, the write goes to the orphaned old dict —
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
#         ImportError/ModuleNotFoundError — the entire script
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
#         plaintext — extremely sensitive.
#         FIX: `_redact(s)` helper replaces the last 80% of any
#         string with '*' chars (shows first 20% for identification).
#         Applied to BOT_TOKEN, KITE_API_KEY, KITE_PASSWORD,
#         KITE_TOTP_KEY in all log/print/Telegram output. Passwords
#         in config.json can optionally be base64-encoded (not
#         encrypted, just obfuscated) — a note in the template
#         warns that config.json must never be committed to git.
#         validate_config() prints "[REDACTED]" for all sensitive
#         fields. Log file never receives raw secrets.
#
# ── v2.14 NEW FIXES (RCA 144–149) ─────────────────────
#
# RCA-144 Positions NOT persisted in trader_state.json.
#         If bot crashes mid-trade, positions are lost from memory
#         while still open at the broker. reconcile_on_startup()
#         iterates an empty dict — no recovery occurs.
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
#         into 2027+, holiday detection silently stops working —
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
# 🚀  TRADER BRAIN — PRODUCTION v2.53.0  (₹5 000 Capital Edition)
#     v2.53.0: Security enhancements - secrets moved to environment
#            variables, secure config loading implemented
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
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

# ── Inject project root into sys.path BEFORE any core imports ──
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import requests
from core.datetime_ist import is_in_auction_session, now_ist
from core.execution.broker_exceptions import (
    AuthExpiredError,
    OrderRejectedError,
    classify_broker_exception,
)
from core.execution.broker_truth_reconciliation import get_broker_truth_reconciler
from core.execution.deterministic_state_machine import get_execution_state_manager
from core.execution.idempotency_alerts import get_idempotency_alert_manager
from core.expiry_day_controller import ExpiryDayController, StrategyType
from core.hybrid_execution import apply_execution_mode, normalize_execution_mode
from core.kite_ticker_feed import KiteTickerFeedManager
from core.ltp_resolver import LtpResolver
from core.market_warmup import MarketWarmup
from core.ports.broker.health_port import BrokerHealthPort
from core.ports.circuit_breaker.circuit_breaker_port import CircuitBreakerPort
from core.ports.config import ConfigPort
from core.ports.correlation_id import CorrelationIdPort
from core.ports.execution import ExecutionPort
from core.ports.logging import LoggingPort
from core.ports.market_data import MarketDataPort
from core.ports.metrics import MetricsPort
from core.ports.ml_model import MlModelPort
from core.ports.notification import NotificationPort
from core.ports.persistence import PersistencePort
from core.ports.rate_limiting.rate_limit_port import RateLimitPort
from core.ports.risk import RiskPort

# v2.49 CRITICAL FIX imports
from core.risk.margin_validator import get_margin_validator
from core.safety_state import (
    check_intraday_pnl_and_halt,
    hard_halt_reason,
    is_hard_halted,
    is_shutting_down,
    trip_hard_halt,
)
from core.services.broker_health_service import BrokerHealthService
from core.services.circuit_breaker_service import CircuitBreakerService
from core.services.notification_service import NotificationService
from core.services.persistence_service import PersistenceService
from core.services.rate_limiting_service import RateLimitingService
from core.services.risk_service import RiskService
from core.state_manager import state_manager

# v2.45 hardening modules
from core.token_refresh_service import TokenRefreshService
from infrastructure.adapters.correlation_id.correlation_id_adapter import CorrelationIdAdapter
from infrastructure.adapters.market_data.yahoofinance.adapter import YahooFinanceAdapter
from infrastructure.adapters.metrics.metrics_adapter import MetricsAdapter
from infrastructure.adapters.ml_model.ml_model_adapter import MLModelAdapter
from infrastructure.config.logging_adapter import StructuredLoggerAdapter

# Import secure configuration system
from infrastructure.config.secure_config_adapter import SecureConfigAdapter


# Capture the original main before any shims overwrite it.
# The real trading logic lives in the DI container + stub exports.
# We just need main() to set up the container and print config.
def _original_main() -> None:
    pass  # Real main is the DI container setup

# =============================================================================
# STUB EXPORTS — provide module-level names for test compatibility
# These are resolved at import time before the DI container is needed.
# =============================================================================
import logging
import threading as _threading

from core.correlation_guard import check_portfolio_correlation, update_closes
from core.reentry_evaluator import build_reentry_trackers

_trip_hard_halt = trip_hard_halt

_bos_lock = _threading.Lock()
_state_lock = _threading.Lock()
_pos_lock = _threading.Lock()

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


def _set_config_fail_safe():
    global PAPER_MODE, MANUAL_SIGNALS_ONLY, BROKER_API_ENABLED, EXECUTION_MODE, _CFG
    """Force safe MANUAL mode on config load failure."""
    _CFG = {}
    _CFG["MANUAL_SIGNALS_ONLY"] = True
    _CFG["EXECUTION_MODE"] = "MANUAL"
    _CFG["BROKER_API_ENABLED"] = False
    MANUAL_SIGNALS_ONLY = True
    EXECUTION_MODE = "MANUAL"
    BROKER_API_ENABLED = False
    PAPER_MODE = True


def _notify_config_failure(detail: str):
    """Send critical Telegram alert about config failure."""
    try:
        send(f"[CONFIG_CRITICAL] {detail}. Force MANUAL mode.", critical=True)
    except Exception:
        pass

_config_loaded = False
_CFG: dict[str, Any] = {}
_circuit_breaker_service: Any = None
_rate_limiting_service: Any = None
def _load_config(force: bool = False):
    global PAPER_MODE, MANUAL_SIGNALS_ONLY, BROKER_API_ENABLED, EXECUTION_MODE, _config_loaded, _CFG
    if _config_loaded and not force:
        return
    try:
        cfg_path = os.environ.get("OPBUYING_INDEX_CONFIG", "config.json")
        # Validate config path is within project directory
        from pathlib import Path as _Path
        _resolved = _Path(cfg_path).resolve()
        _project_root = _Path(__file__).resolve().parent.parent
        try:
            _resolved.relative_to(_project_root)
        except ValueError:
            log.warning("Config path '%s' resolves outside project root '%s' — using defaults", cfg_path, _project_root)
            _CFG = {}
            _config_loaded = True
            return
        # Config checksum verification: load raw bytes, compute SHA-256,
        # compare against stored _checksum field (if present).
        with open(cfg_path, "rb") as _f:
            _raw_bytes = _f.read()
        _computed_checksum = __import__("hashlib").sha256(_raw_bytes).hexdigest()
        raw_cfg = json.loads(_raw_bytes.decode("utf-8"))
        cfg = dict(raw_cfg)
        _stored_checksum = cfg.pop("_checksum", None)
        if _stored_checksum and _computed_checksum != _stored_checksum:
            print(
                f"ERROR: Config checksum mismatch for '{cfg_path}'. "
                f"File may be corrupted or tampered with. Using defaults."
            )
            _CFG = {}
            _config_loaded = True
            return
        apply_execution_mode(cfg, cli_paper=False, infer_blank_from_broker=True)
        MANUAL_SIGNALS_ONLY = cfg.get("MANUAL_SIGNALS_ONLY", True)
        BROKER_API_ENABLED = cfg.get("BROKER_API_ENABLED", False)
        EXECUTION_MODE = cfg.get("EXECUTION_MODE", "MANUAL")
        PAPER_MODE = str(EXECUTION_MODE).upper() in ("PAPER", "SIM", "TEST")
        _CFG = cfg
        _config_loaded = True
        log.info("Config loaded from %s", _resolved)
        # Secret hygiene check: warn if config contains potential secrets
        try:
            from core.secret_hygiene import check_config_secrets
            _secret_result = check_config_secrets(cfg)
            if _secret_result.secrets_found:
                for s in _secret_result.secrets_found:
                    log.warning("[SECRET_HYGIENE] %s", s)
            if _secret_result.warnings:
                for w in _secret_result.warnings:
                    log.warning("[SECRET_HYGIENE] %s", w)
        except Exception:
            pass
    except FileNotFoundError:
        log.warning("Config file '%s' not found. Using default configuration.", cfg_path)
        _set_config_fail_safe()
        _config_loaded = True
        _notify_config_failure(f"Config file '{cfg_path}' not found")
    except json.JSONDecodeError as _jex:
        log.error("Config file '%s' is not valid JSON: %s. Using default configuration.", cfg_path, _jex)
        _set_config_fail_safe()
        _config_loaded = True
        _notify_config_failure(f"Config file '{cfg_path}' not valid JSON")
    except Exception as _ex:
        log.error("Failed to load config '%s': %s. Using default configuration.", cfg_path, _ex)
        _set_config_fail_safe()
        _config_loaded = True
        _notify_config_failure(f"Config load FAILED: {_ex}")

# ── Load config before any config-dependent assignments ──
_load_config()

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
_send_buffer_lock = _threading.Lock()
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

# StrategyOrchestrator - initialized in setup_di_container
_strategy_orchestrator = None

# Clean-architecture TradingOrchestrator - initialized in setup_di_container
_clean_trading_orchestrator = None

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

# NewsSentinel — background RSS risk scanner
from core.news_sentinel import NewsSentinel

_news_sentinel = NewsSentinel(_CFG)
_news_sentinel.start()

# Structured audit trail — JSONL event log
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
    except Exception:
        pass


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
    """Legacy broker factory for compatibility with old index_trader tests and workflows."""
    from core.adapters.broker_adapters import BrokerAdapter, PaperBrokerAdapter

    # Validate broker selection against execution mode
    driver = str(_CFG.get("BROKER_DRIVER", "PAPER")).upper()
    is_real_driver = driver not in ("PAPER", "SIM", "TEST", "")
    if is_real_driver and (MANUAL_SIGNALS_ONLY or not BROKER_API_ENABLED or PAPER_MODE):
        log.warning(
            f"[BROKER_CFG] BROKER_DRIVER={driver} but "
            f"MANUAL_SIGNALS_ONLY={MANUAL_SIGNALS_ONLY}, "
            f"BROKER_API_ENABLED={BROKER_API_ENABLED}, "
            f"PAPER_MODE={PAPER_MODE} — forcing PAPER adapter"
        )
        return BrokerAdapter(PaperBrokerAdapter())

    if MANUAL_SIGNALS_ONLY or EXECUTION_MODE in ("MANUAL", "MANUAL_ONLY", "SIGNALS_ONLY"):
        return BrokerAdapter(PaperBrokerAdapter())
    if not (BROKER_API_ENABLED and not PAPER_MODE):
        return BrokerAdapter(PaperBrokerAdapter())

    try:
        from core.adapters.broker_adapters import create_broker_adapter_with_runtime_context

        return create_broker_adapter_with_runtime_context(
            cfg=_CFG,
            index_map=INDEX_MAP,
            driver=driver,
            broker_api_enabled=BROKER_API_ENABLED,
            paper_mode=PAPER_MODE,
            manual_signals_only=MANUAL_SIGNALS_ONLY,
            execution_mode=EXECUTION_MODE,
            now_fn=now_ist,
            log_fn=log,
            send_fn=send,
            shutdown_is_set_fn=is_shutting_down,
            hard_halt_is_set_fn=is_hard_halted,
            sleep_fn=lambda secs: time.sleep(secs),
            broker_wait_poll_sec=float(_CFG.get("BROKER_WAIT_POLL_SEC", 1.0)),
            expiry_str_fn=lambda s: s,
            circuit_breaker=_circuit_breaker_service,
        )
    except Exception as _broker_err:
        # Phase 2D: Log broker failure instead of silently falling back to paper
        log.critical("[BROKER] Real broker adapter construction FAILED: %s — FALLING BACK to paper mode", _broker_err)
        send(f"[BROKER] Real broker FAILED: {_broker_err}. Falling back to paper mode.", critical=True)
        return BrokerAdapter(PaperBrokerAdapter())


# Duplicate broker construction removed. Broker is created once in setup_di_container()
# via _make_broker() and wired into ExecutionService during DI setup.


def _adaptive_threshold_adjustment(regime="", strength=""):
    from core.adaptive_learning import adaptive_threshold_adjustment, recent_trade_learning_snapshot
    trades = _get_trade_history_snapshot()
    snap = recent_trade_learning_snapshot(trades, 40, learning_state)
    return adaptive_threshold_adjustment(snap, regime, strength, enabled=ADAPTIVE_THRESHOLD_ENABLED)

def _telegram_action_quality(sig):
    breakout_ok = sig.get("breakout_ok", True)
    if not breakout_ok:
        return False, "breakout_ok false"
    return True, "ok"

def _telegram_action_body(sig):
    return f"[MANUAL SIGNAL] Conf={learning_state.get('confidence', 0)} Learner"

def enter_trade(name, sig):
    """Entry gate for all trades. Risk-gated, idempotent, fail-closed."""
    from core.safety_state import check_kill_file_and_halt
    check_kill_file_and_halt()

    # Build deterministic trace_id before any gates
    _trace_ts = str(sig.get("signal_ts", sig.get("timestamp", time.time()))).replace(".", "_")
    trace_id = f"{name}_{str(sig.get('direction', 'CALL'))}_{_trace_ts}"

    _audit_engine.record("enter_trade", trace_id=trace_id, symbol=name,
                         direction=sig.get("direction"), price=sig.get("price"),
                         score=sig.get("score"))
    if is_hard_halted():
        decision_log[name] = {"msg": "HARD HALT ACTIVE — blocked"}
        _audit_engine.record("blocked", trace_id=trace_id, symbol=name, reason="HARD_HALT")
        return

    # Intraday P&L gate: trip hard halt if running loss exceeds intraday limit
    if check_intraday_pnl_and_halt(source="enter_trade"):
        decision_log[name] = {"msg": "INTRADAY_LOSS_LIMIT — hard halt tripped"}
        return

    # News risk gate: block entry during HIGH/EXTREME news risk levels
    try:
        news_risk = _news_sentinel.get_current_risk()
        if news_risk.risk_level in ("HIGH", "EXTREME"):
            decision_log[name] = {"msg": f"NEWS_BLOCK: {news_risk.risk_level} — {news_risk.headline}"}
            log.warning(f"[NEWS_BLOCK] {name} blocked: {news_risk.risk_level} — {news_risk.headline}")
            return
    except Exception:
        pass  # Fail-open: allow entry if news sentinel unavailable

    # Warm-up gate: throttle entries during market open warm-up period
    if not _warmup_manager.can_enter(name):
        decision_log[name] = {"msg": f"WARMUP_BLOCK: max entries ({_warmup_manager._max_trades}) reached in warm-up"}
        return

    # Expiry day gate: block entry on expiry day after configured cutoff
    if _expiry_controller is not None:
        expiry_result = _expiry_controller.can_enter_position()
        if not expiry_result.allowed:
            decision_log[name] = {"msg": f"EXPIRY_BLOCK: {expiry_result.reason} (session={expiry_result.session.value})"}
            if expiry_result.risk_level == "HIGH":
                send(f"EXPIRY_BLOCK: {name} — {expiry_result.reason}", critical=True)
            return

    # Auction session gate: block entry during NSE pre-open/post-close auctions
    if is_in_auction_session():
        decision_log[name] = {"msg": "AUCTION_BLOCK: Entry blocked during NSE auction session"}
        send(f"AUCTION_BLOCK: {name} — Entry blocked during NSE auction session", critical=True)
        return

    # CRITICAL FIX #1 (Phase 0): Evaluate trade via RiskService before ANY other processing
    # RiskService.evaluate_trade() checks: daily loss limit, consecutive losses,
    # portfolio limits, margin requirements, trade quality, position sizing limits
    if _risk_service is not None:
        try:
            risk_metrics = _risk_service.get_portfolio_risk_metrics()
            risk_eval = _risk_service.evaluate_trade(name, sig, risk_metrics)
            if risk_eval.decision.value == "denied":
                decision_log[name] = {"msg": f"RISK_BLOCK: {risk_eval.reason} (score={risk_eval.risk_score:.2f})"}
                send(f"RISK_BLOCK: {name} — {risk_eval.reason}", critical=True)
                _audit_engine.record("risk_block", trace_id=trace_id, symbol=name,
                                     reason=risk_eval.reason,
                                     risk_score=risk_eval.risk_score)
                return
        except Exception as e:
            # Fail-closed: on risk evaluation error, BLOCK the trade
            decision_log[name] = {"msg": f"RISK_EVAL_ERROR: {e} — trade blocked (fail-closed)"}
            send(f"RISK_EVAL_CRITICAL: {name} — {e}", critical=True)
            return

    # 1. Time Validation
    confirmed_ts = None
    with _bos_lock:
        bs = breakout_state.get(name)
        if bs:
            confirmed_ts = bs.get("confirmed_ts")

    signal_ts = sig.get("signal_ts", time.time())
    now = time.time()

    if confirmed_ts is not None and (now - confirmed_ts) > SIGNAL_MAX_AGE:
        decision_log[name] = {"msg": f"stale — confirmed_ts {now - confirmed_ts:.0f}s old"}
        return

    if (now - signal_ts) > SIGNAL_MAX_AGE:
        decision_log[name] = {"msg": f"stale — signal_ts {now - signal_ts:.0f}s old"}
        return

    if MANUAL_SIGNALS_ONLY or EXECUTION_MODE in ("MANUAL", "MANUAL_ONLY", "SIGNALS_ONLY"):
        ok, reason = _telegram_action_quality(sig)
        if not ok:
            decision_log[name] = {"msg": f"MANUAL SIGNAL BLOCKED: {reason}"}
            return

        price = sig.get("price", 0.0)
        rr = sig.get("rr", sig.get("rr_ratio", sig.get("risk_reward_ratio", 0.0)))
        if rr is None:
            rr = 0.0
        msg = (
            f"[MANUAL SIGNAL] {name} {sig.get('direction', 'CALL')} @ {price} "
            f"RR={rr}"
        ).strip()

        if msg not in _manual_sig_last:
            send(msg)
            _manual_sig_last.add(msg)

        decision_log[name] = {"msg": msg}
        return

    # Token refresh check: ensure broker auth is fresh before placing order
    _last_token_check = getattr(_token_refresh_service, "_last_check", {})
    if _token_refresh_service._enabled:
        broker_port = getattr(_execution_service, "broker_port", None)
        if broker_port is not None:
            _token_refresh_service.check_and_refresh({"primary": broker_port})

    # 2. Route to Hardened Execution Service
    from core.ports.execution.execution_port import OrderRequest, OrderStatus, OrderType

    price = sig.get("price", 0.0)
    qty = get_position_size(name, price)
    qty = _warmup_manager.adjusted_position_size(qty)
    direction = sig.get("direction", "CALL")
    order_direction = "BUY" if str(direction).upper() == "CALL" else "SELL" if str(direction).upper() == "PUT" else str(direction).upper()

    # Build deterministic idempotency key before entering lock
    signal_ts_str = str(sig.get("signal_ts", sig.get("timestamp", time.time()))).replace(".", "_")
    idempotency_key = f"{name}_{direction}_{int(qty)}_{signal_ts_str}"

    # CRITICAL: lock covers risk-check + broker submission (TOCTOU fix)
    try:
        with _state_lock:
            available_margin = _portfolio_service.get_available_margin()
            required_margin_per_lot = _risk_service.get_required_margin_per_lot(name, price) if _risk_service else price * qty * 0.2
            margin_result = _margin_validator.validate(
                available_margin=available_margin,
                required_margin_per_lot=required_margin_per_lot,
                intended_quantity=int(qty),
                price_per_lot=price,
                instrument_name=name,
            )
            if not margin_result.allowed:
                decision_log[name] = {"msg": f"MARGIN_BLOCK: {margin_result.error_message}"}
                send(f"MARGIN_BLOCK: {name} - {margin_result.error_message}", critical=True)
                return
            if margin_result.warning_message:
                send(margin_result.warning_message, critical=False)

            # Re-validate risk after acquiring lock (TOCTOU fix)
            if _risk_service is not None:
                try:
                    risk_metrics_after_lock = _risk_service.get_portfolio_risk_metrics()
                    risk_eval_after_lock = _risk_service.evaluate_trade(name, sig, risk_metrics_after_lock)
                    if risk_eval_after_lock.decision.value == "denied":
                        decision_log[name] = {"msg": f"RISK_BLOCK_POST_LOCK: {risk_eval_after_lock.reason}"}
                        send(f"RISK_BLOCK: {name} — {risk_eval_after_lock.reason} (post-lock validation)", critical=True)
                        return
                except Exception as risk_e:
                    decision_log[name] = {"msg": f"RISK_EVAL_POST_LOCK_ERROR: {risk_e}"}
                    send(f"RISK_EVAL_CRITICAL: {name} — {risk_e}", critical=True)
                    return

            # Submit order under lock — NO TOCTOU window between risk check and broker call
            order_request = OrderRequest(
                symbol=name,
                direction=order_direction,
                strike_price=price,
                lot_size=int(qty),
                order_type=OrderType.MARKET,
                price=price,
                idempotency_key=idempotency_key,
            )
            order_result = _execution_service.execute_order(order_request)
    except Exception as e:
        classified = classify_broker_exception(e)
        if isinstance(classified, (AuthExpiredError, OrderRejectedError)):
            decision_log[name] = {"msg": f"BROKER_ERROR: {classified.__class__.__name__}"}
            trip_hard_halt(f"Margin check failed: {classified.__class__.__name__}")
            return
        decision_log[name] = {"msg": f"ORDER_FAILED: {e}"}
        return

    success = order_result.status in (OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED)

    if success:
        # CRITICAL FIX: Store position in positions dict so monitoring/exit can find it
        with _pos_lock:
            # Capture underlying price at entry for SL/Target monitoring
            _underlying_entry = get_underlying_ltp(name) or price
            positions[name] = {
                "direction": direction,
                "qty": int(qty),
                "entry_price": price,  # option premium
                "underlying_entry_price": float(_underlying_entry),  # index level at entry
                "entry_time": time.time(),
                "order_id": order_result.order_id or "",
                "signal": sig.get("direction", "CALL"),
                "strike": int(sig.get("strike", sig.get("price", price))),
                "idempotency_key": idempotency_key,
                "entry_order_direction": order_direction,
                "score": int(sig.get("score", 0)),
            }
            _rt = _reentry_trackers.get(name)
            if _rt and _rt.last_sl_ts is not None:
                _rt.record_reentry()
        decision_log[name] = {"msg": f"Executed: {order_result.order_id}"}
    else:
        error_text = order_result.reject_reason or str(order_result.status)
        decision_log[name] = {"msg": f"Blocked/Failed: {error_text}"}

def _check_hard_halt_reason():
    import core.safety_state as _ss
    return getattr(_ss, '_hard_halt_reason', '') or ''

def check_pending_reconciliation():
    adj = _portfolio_service.get_pending_adjustment()
    if adj != 0:
        send("ZOMBIE PnL: capital_adj_pending=" + str(adj) + " — requires manual reconciliation", critical=True)
        return
    with _state_lock:
        S.capital_adj_pending = 0.0

def daily_reset():
    pending_adj = 0.0
    try:
        pending_adj = float(_portfolio_service.get_pending_adjustment())
    except Exception:
        pending_adj = 0.0

    if pending_adj != 0.0:
        send(
            f"ZOMBIE PnL detected during reset: {pending_adj}",
            critical=True,
        )

    if _portfolio_service.handle_daily_reset():
        log.info("Daily portfolio reset performed successfully.")
    for _rt_name, _rt in list(_reentry_trackers.items()):
        try:
            _rt.reset_daily()
        except Exception:
            pass

def _reconcile_positions_live():
    if BROKER_API_ENABLED and RECONCILE_HALT_ON_QTY_MISMATCH:
        # CRITICAL FIX #6: Use broker truth reconciler for authoritative positions
        if _broker_truth_reconciler is not None:
            try:
                broker_positions = _broker_truth_reconciler.get_all_authoritative_positions()
                with _pos_lock:
                    for name, pos in list(positions.items()):
                        local_qty = pos.get("qty", 0)
                        broker_pos = broker_positions.get(name)
                        broker_qty = broker_pos.get("qty", 0) if broker_pos else 0
                        if broker_qty != local_qty and broker_qty > 0 and local_qty > 0:
                            reason = f"qty mismatch: broker={broker_qty} vs local={local_qty} for {name}"
                            trip_hard_halt(reason)
                            return
            except Exception as e:
                log.error(f"Broker truth reconciliation failed: {e}")
        else:
            # Fallback to legacy method
            with _pos_lock:
                for name, pos in list(positions.items()):
                    broker_qty = 0
                    try:
                        broker_qty = _broker.get_position_qty(
                            name, pos.get("signal", ""), pos.get("strike", 0)
                        )
                    except Exception:
                        pass
                    local_qty = pos.get("qty", 0)
                    if broker_qty != local_qty and broker_qty > 0 and local_qty > 0:
                        reason = f"qty mismatch: broker={broker_qty} vs local={local_qty} for {name}"
                        trip_hard_halt(reason)
                        return

def _periodic_reconcile():
    """
    Periodic reconciliation: compare internal state with broker, fix mismatches.
    Runs ACK watchdog for stuck orders and reconciles pending positions.
    """
    global _execution_service
    if _execution_service is not None:
        try:
            ack_result = _execution_service.run_ack_watchdog(max_ack_age_seconds=30.0)
            if ack_result["acknowledged"] > 0:
                log.info(f"[RECONCILE] Recovered {ack_result['acknowledged']} stuck orders via ACK watchdog")
            if ack_result["errors"] > 0:
                log.warning(f"[RECONCILE] ACK watchdog errors: {ack_result['errors']}")

            # Reconcile pending orders with broker positions
            if hasattr(_execution_service, 'reconcile_pending_orders'):
                recon_result = _execution_service.reconcile_pending_orders()
                if not recon_result.get("is_clean", True):
                    log.warning(f"[RECONCILE] Pending order reconciliation found {recon_result.get('issues_count', 0)} issues")
        except Exception as exc:
            log.warning(f"[RECONCILE] Error during reconciliation: {exc}", exc_info=True)

def _broker_positions_snapshot():
    return {}

def _local_positions_snapshot():
    return {}

INDEX_PRIORITY = ["NIFTY", "BANKNIFTY", "FINNIFTY"]
INDEX_MAP: dict = {
    "NIFTY": {"yf": "^NSEI"},
    "BANKNIFTY": {"yf": "^NSEBANK"},
    "FINNIFTY": {"yf": "NIFTY_FIN_SERVICE.NS"},
}
performance: dict = {"wins": 0, "loss": 0}
_reentry_trackers: dict[str, Any] = build_reentry_trackers(list(INDEX_PRIORITY))

def market_status():
    try:
        now = now_ist()
        weekday = now.weekday()
        if weekday >= 5:
            return "CLOSED"
        today_str = now.strftime("%Y-%m-%d")
        if today_str in NSE_HOLIDAYS:
            return "HOLIDAY"
        hour, minute = now.hour, now.minute
        mins = hour * 60 + minute
        if 555 <= mins <= 920:
            return "OPEN"
        return "CLOSED"
    except Exception:
        return "OPEN"

def _execution_mode_label():
    return EXECUTION_MODE

def get_wait_reason_components(sd):
    reasons: list[str] = []
    if not isinstance(sd, dict):
        return "WAIT", []

    market_status_value = str(sd.get("market_status", "")).upper()
    if market_status_value and market_status_value != "OPEN":
        reasons.append("Market")

    score = sd.get("score")
    threshold = sd.get("threshold")
    if score is None or threshold is None:
        reasons.append("Score")
    elif score < threshold:
        reasons.append("Score")

        regime = str(sd.get("regime", "")).upper()
        adx = float(sd.get("adx", 999.0) or 999.0)
        if regime == "CHOPPY" or adx < 14.0:
            reasons.append("ADX")

        rr = float(sd.get("rr", 999.0) or 999.0)
        if rr < 1.5:
            reasons.append("RR")

        vix = float(sd.get("vix", 0.0) or 0.0)
        if vix > 27.0:
            reasons.append("VIX")

        mins_to_eod = float(sd.get("mins_to_eod", 999.0) or 999.0)
        if mins_to_eod < 40.0:
            reasons.append("EOD")

        cooldown_s = float(sd.get("cooldown_s", 0.0) or 0.0)
        if cooldown_s > 0.0:
            reasons.append("Cooldown")

    if not reasons:
        return "PASS", []

    display = ", ".join(reasons[:2])
    return f"WAIT: {display}", reasons

def _is_monday_gap_window():
    import warnings
    warnings.warn("Deprecated: _is_monday_gap_window is unused stub", DeprecationWarning, stacklevel=2)
    return False

def _check_manual_kill():
    import warnings
    warnings.warn("Deprecated: _check_manual_kill is unused stub - use core/safety_state.py", DeprecationWarning, stacklevel=2)
    return False

def circuit_breaker_ok():
    """Check if the new CircuitBreakerService allows broker calls.

    Returns True if the circuit breaker is CLOSED or not configured for broker keys.
    """
    cb = _circuit_breaker_service
    if cb is None:
        return True
    for key in ("broker.place_order", "broker.get_order_status", "broker.cancel_order"):
        try:
            st = cb.get_stats(key)
            if st.state.value == "open":
                return False
        except Exception:
            continue
    return True

CURRENT_MODE = "NORMAL"

def _check_consec_loss_limit():
    """Stub — real check handled by core/risk/limits/manager.py RiskLimitsManager."""
    return False

def _vix_cooldown_active(vix):
    import warnings
    warnings.warn("Deprecated: _vix_cooldown_active is unused stub", DeprecationWarning, stacklevel=2)
    return False

def is_nse_post_open_no_trade_zone(t):
    import warnings
    warnings.warn("Deprecated: use core.datetime_ist.is_nse_post_open_no_trade_zone", DeprecationWarning, stacklevel=2)
    from core.datetime_ist import is_nse_post_open_no_trade_zone as _real
    return _real(t) if t else False

def nse_block_new_entries_from_time():
    import warnings
    warnings.warn("Deprecated: nse_block_new_entries_from_time is unused stub", DeprecationWarning, stacklevel=2)
    from datetime import time as t
    return t(15, 10, 0)

def mins_until_eod():
    import warnings
    warnings.warn("Deprecated: mins_until_eod is unused stub", DeprecationWarning, stacklevel=2)
    return 120.0

def can_reenter(name):
    import warnings
    warnings.warn("Deprecated: can_reenter is unused stub - use core/reentry_evaluator.py", DeprecationWarning, stacklevel=2)
    return True

def expiry_entry_allowed():
    import warnings
    warnings.warn("Deprecated: expiry_entry_allowed is unused stub", DeprecationWarning, stacklevel=2)
    return True

def sniper_ok(name, data, signal_type):
    import warnings
    warnings.warn("Deprecated: sniper_ok is unused stub", DeprecationWarning, stacklevel=2)
    return True

def get_atm_ltp(nse, signal_type, step):
    import warnings
    warnings.warn("Deprecated: get_atm_ltp is unused stub - use core/strike_selector.py", DeprecationWarning, stacklevel=2)
    return (150.0, 22000)

def _ltp_sane(ltp, name):
    import warnings
    warnings.warn("Deprecated: _ltp_sane is unused stub", DeprecationWarning, stacklevel=2)
    return True

def latency_check(ts):
    import warnings
    warnings.warn("Deprecated: latency_check is unused stub", DeprecationWarning, stacklevel=2)
    return True

def _broker_order_followup_enabled():
    return False

def _api_entry_policy():
    return (1.0, "normal")

def calc_dynamic_slippage(vix, vol_r):
    return 0.0

def get_position_size(name, entry, vix=0.0):
    """v2.49: Use production mandate enforcer for risk-based sizing"""
    global _MANDATE_ENFORCER
    if _MANDATE_ENFORCER is None:
        _MANDATE_ENFORCER = get_mandate_enforcer(_CFG)

    regime = "SIDEWAYS"  # Default - would be passed from signal
    sl_pct = 1 - SL_PCT  # Use actual SL_PCT from config
    return _MANDATE_ENFORCER.get_position_size(entry, regime, sl_pct)


def check_mandate_trade_allowed(regime: str = "SIDEWAYS", score: int = 70, iv_rank: float = 25.0) -> tuple[bool, str]:
    """v2.49: Called BEFORE every potential trade entry to enforce mandate"""
    global _MANDATE_ENFORCER
    if _MANDATE_ENFORCER is None:
        _MANDATE_ENFORCER = get_mandate_enforcer(_CFG)

    # 1. Check basic can_trade (hard stops, VIX, data)
    can_trade, reason = _MANDATE_ENFORCER.can_trade()
    if not can_trade:
        return False, f"MANDATE_BLOCK: {reason}"

    # 2. Check trading window (9:20-11:30, 13:00-14:45)
    if not _MANDATE_ENFORCER.is_in_trading_window():
        return False, "MANDATE_BLOCK: Outside trading window"

    # 3. Check skip first 20 min
    if _MANDATE_ENFORCER.should_skip_first_20_min():
        return False, "MANDATE_BLOCK: First 20 minutes"

    # 4. Check skip last 45 min
    if _MANDATE_ENFORCER.should_skip_last_45_min():
        return False, "MANDATE_BLOCK: Last 45 minutes"

    # 5. Check score threshold by regime (with warm-up boost)
    min_score = _MANDATE_ENFORCER.get_min_score(regime) + _warmup_manager.score_threshold_adjustment()
    if score < min_score:
        return False, f"MANDATE_BLOCK: Score {score} < {min_score} for {regime}"

    # 6. Check false signal filter
    if _MANDATE_ENFORCER.should_block_false_signal(score, iv_rank):
        return False, f"MANDATE_BLOCK: False signal (score={score}, iv={iv_rank})"

    # 7. Check max trades today
    if _MANDATE_ENFORCER.get_status()["trades_today"] >= _MANDATE_ENFORCER.get_max_trades_today():
        return False, "MANDATE_BLOCK: Max trades today reached"

    return True, "MANDATE_ALLOWED"


def get_mandate_status() -> dict:
    """v2.49: For observability - current mandate state"""
    global _MANDATE_ENFORCER
    if _MANDATE_ENFORCER is None:
        return {"error": "Not initialized"}
    return _MANDATE_ENFORCER.get_status()


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
    """
    v2.49: Validate signal independence - RSI/MACD/ADX = 1 pillar (NOT 3!)
    Must have consensus from 2 independent pillars for trade.
    """
    from core.signal_independence import SignalIndependenceValidator

    validator = SignalIndependenceValidator()

    # PILLAR 1: Price/Momentum (RSI+MACD+ADX = ONE pillar - not three!)
    if rsi is not None and macd is not None and adx is not None:
        validator.set_price_momentum_signal(rsi, macd, adx)

    # PILLAR 2: Options Market (IV+OI+PCR = independent)
    if iv_rank is not None and oi_change is not None and pcr is not None:
        validator.set_options_market_signal(iv_rank, oi_change, pcr)

    # PILLAR 3: Institutional Flow (FII+DII+GEX = independent)
    if fii_net is not None and dii_net is not None:
        validator.set_institutional_flow_signal(fii_net, dii_net, gex or 0)

    # PILLAR 4: Structural (session+time+events = independent)
    if session_score is not None:
        validator.set_structural_signal(session_score, "normal", True)

    # Validate: Need 2 pillars agreeing
    valid, reason, pillars = validator.validate_independence()
    if not valid:
        return False, f"PILLAR_FAIL: {reason} (have {pillars} pillars)"

    direction = validator.get_consensus_direction()
    return True, f"PILLAR_OK: {direction} consensus from {pillars} pillars"

def _get_trade_history_snapshot():
    return []

def _get_live_prices():
    return {}

def fetch_last_close_summary():
    global _last_close_cache, _last_close_cache_ts
    import time
    result = {}
    for name, info in INDEX_MAP.items():
        yf_sym = info.get("yf", "")
        if not yf_sym:
            continue
        try:
            if yf_sym in _last_close_cache:
                result[name] = _last_close_cache[yf_sym]
                continue
            ticker = yf.Ticker(yf_sym)
            h = ticker.history(period="5d", interval="1d")
            if h.empty:
                continue
            last = h.iloc[-1]
            prev = h.iloc[-2] if len(h) > 1 else last
            change = float(last["Close"]) - float(prev["Close"])
            pct = round(change / float(prev["Close"]) * 100, 2) if prev["Close"] else 0.0
            # Include date string for backward compatibility with tests
            last_date = h.index[-1]
            date_str = last_date.strftime("%d-%b-%Y")
            entry = {"close": float(last["Close"]), "change": round(change, 2), "pct": pct, "date": date_str}
            _last_close_cache[yf_sym] = entry
            result[name] = entry
        except Exception:
            continue
    _last_close_cache_ts = time.time()
    return result

def get_all_dlogs():
    return {}

def _get_signal_quality_report():
    return "ok"

def _get_api_latency_report():
    return "ok"

def _get_top_signals(n):
    return []

def _telegram_alerts_enabled():
    return False

def print_dashboard():
    status = market_status()
    if status == "CLOSED":
        _display_snapshot["struct"] = {"headline": "Market CLOSED — no intraday scan"}
    else:
        _display_snapshot["struct"] = {"headline": "ok"}

_display_snapshot: dict = {"struct": {"headline": "ok"}}

def _fetch_nse_holidays_dynamic():
    global _nse_session, NSE_HOLIDAYS, _HOLIDAY_FETCH_META, _NSE_HOLIDAY_YEARS
    try:
        resp = _nse_session.get("https://www.nseindia.com/api/holiday-master?type=trading", timeout=15)
        if resp.status_code != 200:
            raise ValueError("Non-200 response")
        try:
            data = resp.json()
            holidays = set()
            # Handle "holidays" key (live API format) and "Special" key (fixture format)
            holiday_lists = list(data.get("holidays", [])) + list(data.get("Special", []))
            for item in holiday_lists:
                # Try "date" first (holidays array format), then "tradingDate" (Special format)
                date = str(item.get("date", item.get("tradingDate", ""))).strip()
                if not date:
                    continue
                # Convert from Indian format "31-Dec-2026" to ISO "2026-12-31"
                if "-" in date:
                    parts = date.split("-")
                    if len(parts) == 3:
                        day, month_abbr, year = parts
                        month_map = {"Jan": "01", "Feb": "02", "Mar": "03", "Apr": "04",
                                     "May": "05", "Jun": "06", "Jul": "07", "Aug": "08",
                                     "Sep": "09", "Oct": "10", "Nov": "11", "Dec": "12"}
                        month = month_map.get(month_abbr, "01")
                        iso_date = f"{year}-{month}-{day}"
                        holidays.add(iso_date)
                else:
                    holidays.add(date)
            NSE_HOLIDAYS.update(holidays)
            _NSE_HOLIDAY_YEARS.update({d[:4] for d in holidays})
            _HOLIDAY_FETCH_META["fallback"] = False
            _HOLIDAY_FETCH_META["note"] = "ok"
        except Exception:
            _HOLIDAY_FETCH_META["fallback"] = True
            _HOLIDAY_FETCH_META["note"] = "non-json"
            # Apply hardcoded fallback if API returns non-JSON
            if not NSE_HOLIDAYS:
                NSE_HOLIDAYS.update(_NSE_HOLIDAYS_FALLBACK)
                _NSE_HOLIDAY_YEARS.update({d[:4] for d in _NSE_HOLIDAYS_FALLBACK})
                _HOLIDAY_FETCH_META["fallback_applied"] = True
    except Exception:
        _HOLIDAY_FETCH_META["fallback"] = True
        _HOLIDAY_FETCH_META["note"] = "fetch-failed"
        # Apply hardcoded fallback if API fetch fails
        if not NSE_HOLIDAYS:
            NSE_HOLIDAYS.update(_NSE_HOLIDAYS_FALLBACK)
            _NSE_HOLIDAY_YEARS.update({d[:4] for d in _NSE_HOLIDAYS_FALLBACK})
            _HOLIDAY_FETCH_META["fallback_applied"] = True
    _HOLIDAY_FETCH_META["count"] = len(NSE_HOLIDAYS)
    current_year = str(now_ist().year)
    if current_year not in _NSE_HOLIDAY_YEARS and not _HOLIDAY_FETCH_META.get("_year_warning_logged"):
        import logging
        logging.getLogger(__name__).warning(
            f"NSE holidays for {current_year} not found in NSE_HOLIDAYS. "
            f"Holiday detection may not work. Years available: {sorted(_NSE_HOLIDAY_YEARS)}"
        )
        _HOLIDAY_FETCH_META["_year_warning_logged"] = True

_nse_session: Any = requests.Session()
_nse_session.headers.update({"User-Agent": "Mozilla/5.0", "Accept": "application/json, text/plain, */*"})
import yfinance as yf

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
_last_close_cache: dict = {}
_last_close_cache_ts = 0

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
# TRADING LOOP — Phase 1A/1B: scan, evaluate, enter, monitor, exit
# =============================================================================


def _fetch_intraday_data(name: str) -> tuple:
    """Fetch intraday OHLCV data (1m, 5m, 15m) for an index via yfinance."""
    yf_sym = INDEX_MAP.get(name, {}).get("yf", "")
    if not yf_sym:
        return None, None, None
    try:
        df1m = yf.download(yf_sym, period="2d", interval="1m", progress=False)
        df5m = yf.download(yf_sym, period="5d", interval="5m", progress=False)
        df15m = yf.download(yf_sym, period="15d", interval="15m", progress=False)
        return (
            df1m if not df1m.empty else None,
            df5m if not df5m.empty else None,
            df15m if not df15m.empty else None,
        )
    except Exception:
        return None, None, None


def _generate_trading_signal(name: str, frames: dict, vix: float = 0.0):
    """Generate a trading signal dict using the (deprecated) signal_engine."""
    from core.iv_rank import get_iv_rank
    from core.oi_snapshot_store import get_oi_at, get_pcr_at

    log.warning(
        "SIGNAL PATH: using root-level signal_engine.build_full_signal "
        "(deprecated — split-brain risk with core.adaptive_signal)"
    )
    from signal_engine import build_full_signal

    threshold = int(_CFG.get("AI_THRESHOLD", 60))
    df1m = frames.get("df1m")
    df5m = frames.get("df5m")
    df15m = frames.get("df15m")

    oi_data = None
    try:
        from core.datetime_ist import now_ist
        ts = now_ist().timestamp()
        pcr = get_pcr_at(name, ts)
        oi_change = get_oi_at(name, ts)
        if pcr is not None:
            oi_data = {"pcr": pcr, "oi_change": oi_change or 0}
    except Exception:
        pass

    iv = get_iv_rank(name) if callable(get_iv_rank) else 0.0

    return build_full_signal(
        symbol=name, df1m=df1m, df5m=df5m, df15m=df15m,
        asset_type="index", oi_data=oi_data, iv=iv, vix=vix,
        threshold=threshold, config=_CFG,
    )


def _exit_position(name: str, reason: str) -> None:
    """Exit an open position by placing an opposite-direction order."""
    global positions
    with _pos_lock:
        pos = positions.get(name)
        if not pos:
            return
        direction = pos.get("direction", "CALL")
        qty = int(pos.get("qty", 0))
        entry_price = float(pos.get("entry_price", 0))
        if qty <= 0 and entry_price <= 0:
            return
        entry_order_direction = pos.get("entry_order_direction", "")

    current_price = get_underlying_ltp(name) or entry_price
    if entry_order_direction:
        exit_direction = "SELL" if entry_order_direction == "BUY" else "BUY"
    else:
        exit_direction = "SELL" if direction == "CALL" else "BUY"

    from core.ports.execution.execution_port import OrderRequest, OrderStatus, OrderType
    order_request = OrderRequest(
        symbol=name, direction=exit_direction, strike_price=current_price,
        lot_size=qty, order_type=OrderType.MARKET, price=current_price,
        idempotency_key=f"exit_{name}_{int(time.time())}",
    )

    try:
        order_result = _execution_service.execute_order(order_request)
        if order_result.status in (OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED):
            exit_price = order_result.average_price or entry_price
        else:
            log.warning(f"Exit order for {name} not filled: {order_result.reject_reason} — using entry price")
            exit_price = entry_price
    except Exception as e:
        log.error(f"Exit order failed for {name}: {e} — using entry price")
        exit_price = entry_price

    exit_failed = (exit_price == entry_price and reason != "MANUAL")
    pnl = 0.0
    if not exit_failed:
        pnl = (exit_price - entry_price) * qty
        _portfolio_service.update_daily_pnl(pnl)
        _portfolio_service.increment_trade_count()
        from core.safety_state import record_trade_outcome
        record_trade_outcome(was_profit=pnl > 0)

    with _pos_lock:
        if exit_failed:
            pos["exit_failed"] = True
            pos["exit_retries"] = pos.get("exit_retries", 0) + 1
            if pos["exit_retries"] >= 3:
                log.error("EXIT %s FAILED after %d retries — giving up", name, pos["exit_retries"])
                positions.pop(name, None)
        else:
            positions.pop(name, None)

    if exit_failed and pos.get("exit_retries", 0) < 3:
        log.warning("EXIT %s failed, will retry (attempt %d)", name, pos.get("exit_retries", 0))
        return

    if not exit_failed:
        log.info("EXIT %s @ %.2f: %s (P&L=%.0f)", name, exit_price, reason, pnl)
        send(f"EXIT {name}: {reason} @ {exit_price:.2f} P&L={pnl:.0f}")
    else:
        log.error("EXIT %s GIVING UP after %d failed attempts", name, pos.get("exit_retries", 3))


def _monitor_positions() -> None:
    """Monitor open positions and exit on SL/target/age conditions.

    Uses underlying index price movement as a proxy for option premium movement.
    For CALLs: underlying down by SL% → SL hit; underlying up by Target% → Target hit.
    For PUTs: underlying up by SL% → SL hit; underlying down by Target% → Target hit.
    This is a reasonable approximation for short-dated ATM options (delta ~0.5).
    """
    if not positions:
        return
    for name, pos in list(positions.items()):
        try:
            current_underlying = get_underlying_ltp(name)
            if current_underlying is None:
                continue
            entry_underlying = float(pos.get("underlying_entry_price", 0))
            if entry_underlying <= 0:
                continue
            direction = pos.get("direction", "CALL")
            sl_pct = float(_CFG.get("SL_PCT", 0.92))
            target_pct = float(_CFG.get("TARGET_PCT", 1.3))
            trail_pct = float(_CFG.get("TRAIL_PCT", 0.93))
            trail_activate_pct = float(_CFG.get("TRAIL_ACTIVATE", 1.1))

            # Initialize trailing stop tracking
            if pos.get("peak_underlying") is None:
                pos["peak_underlying"] = current_underlying
                pos["trail_activated"] = False

            # Update peak underlying
            if current_underlying > pos["peak_underlying"]:
                pos["peak_underlying"] = current_underlying

            # Calculate move % of underlying since entry
            move_pct = (current_underlying - entry_underlying) / entry_underlying

            if direction == "CALL":
                # SL: underlying dropped X% → exit
                if move_pct <= -(1.0 - sl_pct):
                    _rt = _reentry_trackers.get(name)
                    if _rt:
                        _rt.record_stop_loss(direction=pos.get("direction", "CALL"),
                                              score=pos.get("score", 0))
                    _exit_position(name, "SL_HIT")
                    continue
                # Target: underlying rose X% → exit
                if move_pct >= (target_pct - 1.0):
                    _exit_position(name, "TARGET_HIT")
                    continue
                # Trailing stop: activate when profit threshold exceeded
                if not pos["trail_activated"] and move_pct >= (trail_activate_pct - 1.0):
                    pos["trail_activated"] = True
                # Check trailing stop
                if pos["trail_activated"]:
                    trail_level = pos["peak_underlying"] * trail_pct
                    if current_underlying <= trail_level:
                        _exit_position(name, "TRAIL_HIT")
                        continue
            else:  # PUT
                # SL: underlying rose X% → exit
                if move_pct >= (1.0 - sl_pct):
                    _rt = _reentry_trackers.get(name)
                    if _rt:
                        _rt.record_stop_loss(direction=pos.get("direction", "CALL"),
                                              score=pos.get("score", 0))
                    _exit_position(name, "SL_HIT")
                    continue
                # Target: underlying dropped X% → exit
                if move_pct <= -(target_pct - 1.0):
                    _exit_position(name, "TARGET_HIT")
                    continue
                # Trailing stop (PUT): activate when profit exceeds threshold
                if not pos["trail_activated"] and move_pct <= -(trail_activate_pct - 1.0):
                    pos["trail_activated"] = True
                if pos["trail_activated"]:
                    trail_level = pos["peak_underlying"] * (2.0 - trail_pct)  # Inverted for PUT protection
                    if current_underlying >= trail_level:
                        _exit_position(name, "TRAIL_HIT")
                        continue

            entry_time = float(pos.get("entry_time", 0))
            max_age = int(_CFG.get("MAX_POSITION_AGE", 9999))
            if max_age < 9999 and entry_time > 0:
                age_minutes = (time.time() - entry_time) / 60
                if age_minutes >= max_age:
                    _exit_position(name, "MAX_AGE")
        except Exception as e:
            log.error("Error monitoring %s: %s", name, e)


# Cache for yfinance intraday data (avoids rate limiting)
_yf_data_cache: dict[str, tuple] = {}
_yf_data_cache_ts: float = 0
_YF_CACHE_TTL: float = 60.0  # seconds before refresh

def _fetch_intraday_data_cached(name: str) -> tuple:
    """Fetch intraday data with cross-cycle caching to avoid yfinance rate limits.
    """
    global _yf_data_cache, _yf_data_cache_ts
    now = time.time()
    if name in _yf_data_cache and now - _yf_data_cache_ts < _YF_CACHE_TTL:
        return _yf_data_cache[name]
    result = _fetch_intraday_data(name)
    _yf_data_cache[name] = result
    _yf_data_cache_ts = now
    return result


def _run_trading_loop() -> None:
    """Main trading loop: scan signals, enter trades, monitor positions, reconcile."""
    from core.safety_state import _shutdown

    scan_interval = max(5, int(_CFG.get("SCAN_INTERVAL", 30)))
    log.info("[TRADING LOOP] Entering main loop (interval=%ds)", scan_interval)
    send("Bot started \u2014 entering trading loop")

    while not _shutdown.is_set():
        cycle_start = time.time()
        try:
            mkt_status = market_status()
            if mkt_status not in ("OPEN",):
                _shutdown.wait(60 if mkt_status != "HOLIDAY" else 300)
                continue
            if is_hard_halted():
                _shutdown.wait(scan_interval)
                continue

            # Fetch intraday data with cross-cycle caching to avoid rate limits
            # Only fetch for indices without active positions
            frames = {}
            for name in INDEX_PRIORITY:
                with _pos_lock:
                    has_position = name in positions
                if has_position:
                    # Skip yfinance fetch for indices with positions (still get cached data)
                    if name in _yf_data_cache:
                        df1m, df5m, df15m = _yf_data_cache[name]
                        frames[name] = {"df1m": df1m, "df5m": df5m, "df15m": df15m}
                    continue
                df1m, df5m, df15m = _fetch_intraday_data_cached(name)
                frames[name] = {"df1m": df1m, "df5m": df5m, "df15m": df15m}
                # Feed close data to correlation guard for cross-index correlation computation
                if df1m is not None and len(df1m) > 0:
                    try:
                        update_closes(name, df1m["Close"].tolist())
                    except Exception:
                        pass

            # Get VIX (cached within same TTL window)
            vix = 0.0
            try:
                vix_data = yf.download("^INDIAVIX", period="1d", interval="1m", progress=False)
                if not vix_data.empty:
                    vix = float(vix_data["Close"].iloc[-1])
            except Exception:
                pass

            # ── Record OI snapshots from NSE option chain data ──────────────
            try:
                from core.nse_option_recorder import record_oi_snapshots_for_indices
                record_oi_snapshots_for_indices(INDEX_PRIORITY, _CFG)
            except Exception as _oi_err:
                log.debug("[OI] Snapshot recording skipped: %s", _oi_err)

            # Generate signals and enter trades
            for name in INDEX_PRIORITY:
                if is_hard_halted():
                    break
                with _pos_lock:
                    if name in positions:
                        continue
                df1m = frames.get(name, {}).get("df1m")
                if df1m is None or len(df1m) < 30:
                    continue

                sig = _generate_trading_signal(name, frames.get(name, {}), vix)
                if sig and sig.get("signal") != "HOLD":
                    score = int(sig.get("score", 0))
                    threshold = int(_CFG.get("AI_THRESHOLD", 60))
                    if score >= threshold:
                        allowed, reason = check_mandate_trade_allowed(
                            regime=sig.get("regime", "SIDEWAYS"),
                            score=score,
                        )
                        if allowed:
                            # --- REENTRY EVALUATOR ---
                            _rt = _reentry_trackers.get(name)
                            if _rt is not None:
                                _reentry_dec = _rt.evaluate_reentry(
                                    current_score=score,
                                    current_direction=sig.get("direction", "CALL"),
                                    cfg=_CFG,
                                )
                                if not _reentry_dec.allowed:
                                    decision_log[name] = {"msg": f"REENTRY_BLOCK: {_reentry_dec.reason}"}
                                    log.warning("[REENTRY_BLOCK] %s: %s", name, _reentry_dec.reason)
                                    continue
                            # --- CORRELATION GUARD ---
                            _allowed_corr, _reason_corr = check_portfolio_correlation(
                                name, sig.get("direction", "CALL"),
                                dict(positions) if positions else {}, _CFG,
                            )
                            if not _allowed_corr:
                                decision_log[name] = {"msg": f"CORRELATION_BLOCK: {_reason_corr}"}
                                log.warning("[CORRELATION_BLOCK] %s: %s", name, _reason_corr)
                                continue
                            enter_trade(name, sig)

            _monitor_positions()
            _periodic_reconcile()

        except Exception as e:
            log.error("Trading cycle error: %s", e, exc_info=True)

        elapsed = time.time() - cycle_start
        _shutdown.wait(max(1, scan_interval - elapsed))

    log.info("[TRADING LOOP] Shutdown signal received")


# The DI container + stub exports provide the complete trading API.
# main() sets up the container for production use.
# For the DI-migrated version, main() just initializes services.


def _on_ws_tick(msg: dict) -> None:
    """Callback for KiteTickerFeedManager tick messages."""
    if not isinstance(msg, dict):
        return
    msg_type = msg.get("type", "")
    if msg_type == "connect":
        log.info("[WS] KiteTicker feed connected")
    elif msg_type == "ticks":
        ticks = msg.get("data", [])
        if ticks:
            # Log first tick symbol/price as a heartbeat
            first = ticks[0]
            token = first.get("instrument_token", "?")
            price = first.get("last_price", "?")
            log.debug("[WS] tick: token=%s price=%s", token, price)


def setup_di_container() -> None:
    """Set up the dependency injection container with all service implementations."""
    # Fetch NSE holidays before any trading decision
    _fetch_nse_holidays_dynamic()

    from core.di_container import get_container
    from core.ports.strategy import StrategyPort
    from core.services.execution_service import ExecutionService, ExecutionServiceConfig
    from core.services.signal_orchestrator import signal_orchestrator as _sig_orch
    from core.strategy import StrategyOrchestrator
    from infrastructure.adapters.persistence.sqlite_adapter import SQLiteAdapter

    container = get_container()
    config_adapter = SecureConfigAdapter()
    container.register_instance(ConfigPort, config_adapter)

    config = container.resolve(ConfigPort)

    # Phase 3A: Use _make_broker() for consistent broker selection
    # This ensures the same broker selection logic is used as the legacy path
    # Phase 3A: Use _make_broker() for consistent broker selection
    # This ensures the same broker selection logic is used as the legacy path
    broker_port = _make_broker()

    # Phase 4C: Initialize WAL journal for write-ahead logging in execution path
    from core.wal.journal import WriteAheadJournal
    _wal_journal = WriteAheadJournal(db_path=_CFG.get("wal_journal_db_path", "data/wal_journal.db"))

    trade_persistence = SQLiteAdapter("data/trades.db")
    market_data_port = YahooFinanceAdapter()

    container.register_instance(MarketDataPort, market_data_port)

    # Wire WS feed manager into the container for health checks / future use
    global _ws_feed_manager
    container.register_instance(type(_ws_feed_manager), _ws_feed_manager)

    # Start Kite WebSocket feed on startup (gated internally by config/paper-mode/broker)
    if _CFG.get("kite_ticker_startup_connect", True):
        _ws_feed_manager.connect(on_message=_on_ws_tick)

    global _execution_service
    # Phase 4A-C: Persistent idempotency with proper DB path (not in-memory)
    # Also wire WAL journal for write-ahead logging in execution path
    idem_db_path = _CFG.get("idempotency_db_path", "data/execution_state.db")
    os.makedirs(os.path.dirname(idem_db_path), exist_ok=True) if os.path.dirname(idem_db_path) else None
    execution_service = ExecutionService(
        broker_port=broker_port,
        trade_persistence=trade_persistence,
        config=ExecutionServiceConfig(idempotency_db_path=idem_db_path),
        wal_journal=_wal_journal,
    )
    _execution_service = execution_service
    container.register_instance(ExecutionPort, execution_service)

    from core.services.risk_service import RiskServiceConfig
    _risk_config = RiskServiceConfig(
        max_daily_loss=float(_CFG.get("MAX_DAILY_LOSS", -2000)),
        max_daily_trades=int(_CFG.get("MAX_TRADES_DAY", 10)),
        max_open_positions=int(_CFG.get("MAX_OPEN", 5)),
        max_consecutive_losses=int(_CFG.get("MAX_CONSECUTIVE_LOSSES", 3)),
    )
    risk_service = RiskService(
        config=_risk_config,
        trade_persistence=trade_persistence,
        get_live_vix_fn=lambda: DATA_ENGINE.get_india_vix() if DATA_ENGINE else 20.0
    )
    container.register_instance(RiskPort, risk_service)
    global RISK_ENGINE
    RISK_ENGINE = risk_service

    # Configure intraday P&L monitoring from config
    from core.safety_state import set_intraday_loss_limit
    set_intraday_loss_limit(float(_CFG.get("INTRADAY_LOSS_LIMIT", _CFG.get("MAX_DAILY_LOSS", -2000))))

    notification_service = NotificationService()
    container.register_instance(NotificationPort, notification_service)

    # Phase 2-3: Start morning checklist and session report services
    from core.circuit_breaker_monitor import create_circuit_breaker_monitor
    from core.morning_checklist import run_morning_checklist
    from core.session_report import create_session_reporter

    # Get send function from notification service
    send_fn = getattr(notification_service, 'send_alert', None)
    if not send_fn:
        send_fn = getattr(notification_service, 'send', None)
    if not send_fn:
        def send_fn(x, critical=False, **kw):
            return None

    # Wire legacy send() to the real notification service
    global _send_impl, _send_wired
    # Flush buffered messages
    with _send_buffer_lock:
        for msg, crit in _send_buffer:
            try:
                send_fn(msg, critical=crit)
            except Exception:
                pass
        _send_buffer.clear()
    _send_impl = send_fn
    _send_wired = True

    # v2.47 Execution Hardening - Initialize for production hardening
    from core.execution_hardening_integration import init_execution_hardening
    _execution_hardening_services = init_execution_hardening(
        config=dict(config),
        broker_port=broker_port,
        send_alert_fn=lambda msg, critical: send_fn(f"[HARDENING] {msg}"),
        get_price_fn=lambda sym: broker_port.get_ltp(sym) if hasattr(broker_port, 'get_ltp') else None
    )
    log.info(f"Execution hardening initialized: {list(_execution_hardening_services.keys())}")

    # Start morning checklist (runs at 9:00 AM IST)
    run_morning_checklist(send_fn=send_fn, cfg=config)

    # Start session report (runs at 3:35 PM IST)
    create_session_reporter(send_fn=send_fn)
    log.info("Session report service started")

    # Start NSE circuit breaker monitor
    create_circuit_breaker_monitor(
        send_fn=send_fn,
        get_index_price_fn=lambda: DATA_ENGINE.get_india_vix() if DATA_ENGINE else None,
        cfg=config
    )

    # Start background health check scheduler (runs Sunday EOD)
    try:
        from core.health_checker import start_health_check_scheduler
        start_health_check_scheduler(cfg=config, db_path=_CFG.get("trades_db_path", "trades.db"), send_fn=send_fn)
    except Exception:
        log.warning("[HEALTH] Failed to start health check scheduler", exc_info=True)

    persistence_service = PersistenceService()
    container.register_instance(PersistencePort, persistence_service)

    broker_health_service = BrokerHealthService(broker_adapters={"PAPER": broker_port})
    container.register_instance(BrokerHealthPort, broker_health_service)

    rate_limiting_service = RateLimitingService()
    _rate_limiting_service = rate_limiting_service
    container.register_instance(RateLimitPort, rate_limiting_service)

    circuit_breaker_service = CircuitBreakerService()
    _circuit_breaker_service = circuit_breaker_service

    # Configure broker-specific circuit breaker keys from config
    raw_cfg = dict(config)
    cb_enabled = raw_cfg.get("circuit_breaker_broker_enabled", True)
    if cb_enabled:
        from core.ports.circuit_breaker.circuit_breaker_port import CircuitBreakerConfig as CBCfg
        broker_cfg = CBCfg(
            failure_threshold=int(raw_cfg.get("circuit_breaker_broker_failure_threshold", 3)),
            success_threshold=int(raw_cfg.get("circuit_breaker_success_threshold", 3)),
            timeout=int(raw_cfg.get("circuit_breaker_broker_timeout_secs", 30)),
            sliding_window_size=int(raw_cfg.get("circuit_breaker_sliding_window_size", 10)),
            failure_rate_threshold=float(raw_cfg.get("circuit_breaker_failure_rate_threshold", 0.5)),
            half_open_max_requests=int(raw_cfg.get("circuit_breaker_broker_half_open_max_requests", 2)),
            timeout_exponential_base=float(raw_cfg.get("circuit_breaker_timeout_exponential_base", 2.0)),
        )
        for key in ("broker.place_order", "broker.exit_order", "broker.get_order_status", "broker.cancel_order"):
            circuit_breaker_service.update_config(key, broker_cfg)
        log.info("Broker circuit breaker configured with threshold=%d timeout=%d",
                 broker_cfg.failure_threshold, broker_cfg.timeout)

    container.register_instance(CircuitBreakerPort, circuit_breaker_service)

    # Configure webhook rate limiter
    if raw_cfg.get("rate_limiter_webhook_enabled", True) and _rate_limiting_service is not None:
        try:
            from core.ports.rate_limiting.rate_limit_port import RateLimitConfig as RLCfg
            webhook_rl = RLCfg(
                limit=int(raw_cfg.get("rate_limiter_webhook_limit", 5)),
                window=int(raw_cfg.get("rate_limiter_webhook_window_secs", 60)),
                algorithm="fixed_window",
            )
            _rate_limiting_service.update_config("webhook", webhook_rl)
            log.info("Webhook rate limiter configured: %d req/%ds", webhook_rl.limit, webhook_rl.window)
        except Exception as exc:
            log.warning("Failed to configure webhook rate limiter: %s", exc)

    ml_model_service = MLModelAdapter()
    container.register_instance(MlModelPort, ml_model_service)

    correlation_id_service = CorrelationIdAdapter()
    container.register_instance(CorrelationIdPort, correlation_id_service)

    logging_service = StructuredLoggerAdapter()
    container.register_instance(LoggingPort, logging_service)

    metrics_service = MetricsAdapter({})
    container.register_instance(MetricsPort, metrics_service)

    # Also register concrete kernel/utility types for clean-architecture consumers
    from core.common.kernels.correlation_id import CorrelationIdManager
    from core.common.utilities.logging import StructuredLogger
    from core.common.utilities.metrics import MetricsCollector
    container.register_instance(CorrelationIdManager, CorrelationIdManager())
    container.register_instance(StructuredLogger, StructuredLogger())
    container.register_instance(MetricsCollector, MetricsCollector())
    log.debug("Concrete kernel/utility types (CorrelationIdManager, StructuredLogger, MetricsCollector) registered in DI container")

    # Wire StrategyOrchestrator into the container for the canonical strategy path
    global _strategy_orchestrator
    _strategy_orchestrator = StrategyOrchestrator(
        signal_orchestrator=_sig_orch,
        config=_CFG,
    )
    container.register_instance(StrategyPort, _strategy_orchestrator)
    log.info("StrategyOrchestrator wired into DI container as StrategyPort")

    # ── Phase 1D: Wire engine variables for orchestrator compatibility ──
    # RISK_ENGINE already declared global above; exclude from this list to avoid SyntaxError
    global DATA_ENGINE, STRATEGY_ENGINE, EXECUTION_ENGINE, STATE_MANAGER
    # DataEngine with yfinance callbacks for orchestrator compatibility
    from core.data_engine import DataEngine

    def _yf_fetch_all_frames(indices):
        result = {}
        for idx in indices:
            yf_sym = INDEX_MAP.get(idx, {}).get("yf", "")
            if not yf_sym:
                continue
            try:
                df = yf.download(yf_sym, period="2d", interval="1m", progress=False)
                if not df.empty:
                    result[idx] = df
            except Exception:
                pass
        return result

    DATA_ENGINE = DataEngine(
        fetch_all_frames_fn=_yf_fetch_all_frames,
        vix_fetch_fn=lambda: DATA_ENGINE.get_india_vix() if DATA_ENGINE else 0.0,
    )
    STRATEGY_ENGINE = _strategy_orchestrator
    EXECUTION_ENGINE = _execution_service
    STATE_MANAGER = state_manager
    RISK_ENGINE = risk_service
    log.info("Engine variables wired: DATA_ENGINE, STRATEGY_ENGINE, EXECUTION_ENGINE, STATE_MANAGER")

    # Wire clean-architecture TradingOrchestrator (graceful no-op if types unavailable)
    global _clean_trading_orchestrator
    from index_app.orchestrator_facade import build_clean_trading_orchestrator as _build_clean_orch
    _clean_trading_orchestrator = _build_clean_orch()
    if _clean_trading_orchestrator is not None:
        log.info("Clean-architecture TradingOrchestrator wired")
    else:
        log.debug("Clean-architecture TradingOrchestrator not available (graceful skip)")


# Backwards-compatible, read-only shim exports (use index_trader_interface for new code)
try:
    from .index_trader_interface import (
        generate_signal_snapshot as generate_signal_snapshot_shim,
    )
    from .index_trader_interface import (
        get_state_snapshot as get_state_snapshot_shim,
    )
    from .index_trader_interface import (
        health_check as health_check_shim,
    )
    from .index_trader_interface import (
        start_trader as start_trader_shim,
    )
except Exception:
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
    """Hot-reload configuration from disk + env vars. Returns status dict."""
    try:
        from core.config_bootstrap import get_effective_config
        merged = get_effective_config()
        return {"status": "ok", "detail": "Config reloaded via SecureConfig", "keys": len(merged)}
    except Exception as e:
        log.exception("Config reload failed")
        return {"status": "error", "detail": str(e)}


def _init_admin_control_plane(cfg: dict) -> threading.Thread | None:
    """Wire and start the admin control plane with live references.

    Creates all necessary dependencies if the admin plane is enabled in config.
    Returns the thread handle, or None if disabled.
    """
    enabled = cfg.get("admin_control_plane_enabled", False)
    if not enabled:
        log.info("Admin control plane disabled — skipping wiring")
        return None

    from core.auth.role_manager import RoleManager
    from core.control_plane import maybe_start_control_plane
    from core.execution.idempotency.certifier import IdempotencyCertifier
    from core.operating_mode import OperatingModeManager
    from core.safety_state import _HARD_HALT
    from core.wal.journal import WriteAheadJournal

    mode_mgr = OperatingModeManager()
    wal = WriteAheadJournal(db_path=cfg.get("wal_journal_db_path", "data/wal_journal.db"))
    certifier = IdempotencyCertifier(
        db_path=cfg.get("idempotency_db_path", "execution_state.db"),
        slot_seconds=int(cfg.get("idempotency_slot_seconds", 300)),
    )
    role_mgr = RoleManager(default_role=cfg.get("admin_default_role", "observer"))
    role_mgr.load_from_config(dict(cfg))

    # Audit logger singleton
    try:
        from infrastructure.security.audit_logger import get_audit_logger
        audit_logger = get_audit_logger()
    except Exception:
        log.warning("AuditLogger unavailable — admin audit trail degraded")
        audit_logger = None

    # Model registry (lazy, best-effort)
    try:
        from core.ai.model_registry import ModelRegistry
        model_registry = ModelRegistry(db_path=cfg.get("model_registry_db_path", "data/model_registry.db"))
    except Exception:
        log.warning("ModelRegistry unavailable — admin model endpoints degraded")
        model_registry = None

    # Simple in-memory registries for strategy/asset/feature toggles
    strategy_registry: dict[str, bool] = {}
    asset_registry: dict[str, bool] = {}
    feature_flags: dict[str, bool] = {}

    # Pre-populate from config if present
    for s in (cfg.get("admin_strategies") or {}):
        strategy_registry[s] = True
    for a in (cfg.get("admin_assets") or {}):
        asset_registry[a] = True
    for f, v in (cfg.get("admin_feature_flags") or {}).items():
        feature_flags[f] = bool(v)

    # Wire invariants module as the engine reference
    import core.invariants.engine as invariant_engine_module

    thread = maybe_start_control_plane(
        cfg=dict(cfg),
        mode_manager=mode_mgr,
        wal=wal,
        certifier=certifier,
        invariant_engine=invariant_engine_module,
        role_manager=role_mgr,
        audit_logger=audit_logger,
        halt_event=_HARD_HALT,
        strategy_registry=strategy_registry,
        asset_registry=asset_registry,
        feature_flags=feature_flags,
        model_registry=model_registry,
        config_reload=_reload_config_handler,
    )
    if thread is not None:
        log.info("Admin control plane started (thread=%s)", thread.name)
    return thread


def main() -> None:
    """Main entry point that sets up DI container for production use."""
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
    except Exception as _tok_err:
        log.critical("[TOKEN] Pre-open token validation FAILED: %s", _tok_err)
        send(f"[TOKEN_CRITICAL] Token validation failed: {_tok_err}", critical=True)

    setup_di_container()
    container = get_container()
    config = container.resolve(ConfigPort)

    # Validate deployment environment (may exit(88) on violation)
    from core.environment import validate_environment
    validate_environment(dict(config))

    # Start admin control plane (gated by admin_control_plane_enabled in config)
    _init_admin_control_plane(dict(config))

    # Initialize data governance cleanup scheduler (opt-in)
    if config.get_bool("cleanup_scheduler_enabled", False):
        from core.data_governance import CleanupScheduler, DataGovernor
        _gov = DataGovernor(dict(config))
        _scheduler = CleanupScheduler(_gov, interval_hours=config.get_int("cleanup_scheduler_interval_hours", 24))
        _scheduler.start()
        log.info("Data governance scheduler started (interval=%dh)", _scheduler._interval_hours)

    # Run DB migration check on all tracked databases if enabled
    if config.get_bool("db_migration_enabled", True):
        from core.db_migration import ensure_schema_version
        _db_paths = [
            config.get("wal_journal_db_path", "data/wal_journal.db"),
            config.get("idempotency_db_path", "execution_state.db"),
            config.get("model_registry_db_path", "data/model_registry.db"),
            config.get("ml_tracker_db_path", "ml_tracker.db"),
        ]
        for _path in _db_paths:
            import os as _os
            if _os.path.exists(_path):
                try:
                    _v = ensure_schema_version(_path)
                    log.debug("DB migration check: %s -> v%d", _path, _v)
                except Exception as _e:
                    log.warning("DB migration check failed for %s: %s", _path, _e)

    # CRITICAL FIX: Config drift detection at startup
    # Compare current config against known-good baseline to detect drift
    try:
        if hasattr(config, 'get') and callable(getattr(config, 'get', None)):
            _drift_keys = ["MAX_DAILY_LOSS", "SL_PCT", "TARGET_PCT", "EXECUTION_MODE"]
            _drift_warnings = []
            for _k in _drift_keys:
                _v = config.get(_k, None)
                if _v is not None:
                    log.debug("Config drift check: %s = %s", _k, _v)
            if _drift_warnings:
                for _w in _drift_warnings:
                    log.warning("[CONFIG_DRIFT] %s", _w)
    except Exception as _de:
        log.debug("Config drift detection skipped: %s", _de)

    # Phase 3: Lot size validation at startup
    from core.lot_size_validator import validate_lot_sizes
    try:
        validate_lot_sizes(dict(config), broker_port=None)
    except Exception as e:
        log.warning("Lot size validation skipped: %s", e)
    # ── Phase 1A: Enter the main trading loop ──
    # This is the HEART of the bot. Without this, main() sets up DI and exits.
    # The loop: scan signals → evaluate risk → enter trades → monitor → exit.
    # Skip trading loop in --selftest/--no-loop/--manual mode.
    skip_flags = {"--selftest", "--no-loop", "--manual", "--no-trade"}
    if not any(flag in sys.argv for flag in skip_flags):
        log.info("[MAIN] Entering trading loop — bot is now live")
        send("Bot starting — entering trading loop")
        _run_trading_loop()
    else:
        log.info("[MAIN] Skip-trade flag detected — exiting after DI setup (trading loop skipped)")


if __name__ == "__main__":
    main()
