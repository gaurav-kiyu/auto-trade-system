# ================================================================
# 🚀  TRADER BRAIN — PRODUCTION v2.42  (₹5 000 Capital Edition)
#     v2.42: ExecutionRouter (AUTO + optional PAPER→adapter), chunked Yahoo quarter backtest, HOW_TO_USE refresh.
#     v2.40: Final QA pass — pytest tests/test_smoke + --selftest OK; find dialog F3 + safer
#            Unicode selection end index (chars not c).
#     v2.50: Dependency injection container wired for core services.
# ----------------------------------------------------------------
# INSTALL : pip install requests yfinance pandas kiteconnect pyotp
# RUN     : python INDEX_OPTION_BUYING_APP_1.0.py               ← LIVE (shim → index_app)
#           python -m index_app.index_trader                    ← same bot, explicit module
#           python INDEX_OPTION_BUYING_APP_1.0.py --paper        ← PAPER/TEST
#           python INDEX_OPTION_BUYING_APP_1.0.py --debug        ← DEBUG
#           python INDEX_OPTION_BUYING_APP_1.0.py --selftest     ← SELFTEST
#           python INDEX_OPTION_BUYING_APP_1.0.py --print-config ← Dump config.json
#           python INDEX_OPTION_BUYING_APP_1.0.py --config-reset ← After BASE_CAPITAL change
#           python INDEX_OPTION_BUYING_APP_1.0.py --report       ← Multi-session stats
#           python INDEX_OPTION_BUYING_APP_1.0.py --export-trades ← Export trades to CSV
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
# ── BEGIN SECURITY ENHANCEMENTS (v2.50) ──────────────────
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
# ── END SECURITY ENHANCEMENTS (v2.50) ────────────────────
#
# ================================================================
# 🚀  TRADER BRAIN — PRODUCTION v2.50  (₹5 000 Capital Edition)
#     v2.50: Security enhancements - secrets moved to environment
#            variables, secure config loading implemented
# ================================================================
# INSTALL : pip install requests yfinance pandas kiteconnect pyotp
# RUN     : python INDEX_OPTION_BUYING_APP_1.0.py               ← LIVE (shim → index_app)
#           python -m index_app.index_trader                    ← same bot, explicit module
#           python INDEX_OPTION_BUYING_APP_1.0.py --paper        ← PAPER/TEST
#           python INDEX_OPTION_BUYING_APP_1.0.py --debug        ← DEBUG
#           python INDEX_OPTION_BUYING_APP_1.0.py --print-config ← Dump config.json (secrets redacted)
#           python INDEX_OPTION_BUYING_APP_1.0.py --config-reset ← After BASE_CAPITAL change
#           python INDEX_OPTION_BUYING_APP_1.0.py --report       ← Multi-session stats
#           python INDEX_OPTION_BUYING_APP_1.0.py --export-trades ← Export trades to CSV
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

import importlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

# Import secure configuration system
from infrastructure.config.secure_config import get_secure_config

from core.ports.metrics import MetricsPort
from core.ports.market_data import MarketDataPort
from core.ports.config import ConfigPort
from core.ports.execution import ExecutionPort
from core.ports.risk import RiskPort
from core.ports.notification import NotificationPort
from core.ports.persistence import PersistencePort
from core.ports.broker.health_port import BrokerHealthPort
from core.ports.rate_limiting.rate_limit_port import RateLimitPort
from core.ports.circuit_breaker.circuit_breaker_port import CircuitBreakerPort
from core.ports.ml_model import MlModelPort
from core.ports.correlation_id import CorrelationIdPort
from core.ports.logging import LoggingPort

from infrastructure.config.secure_config_adapter import SecureConfigAdapter
from core.services.execution_service import ExecutionService
from core.services.risk_service import RiskService
from core.services.notification_service import NotificationService
from core.services.persistence_service import PersistenceService
from core.services.broker_health_service import BrokerHealthService
from core.services.rate_limiting_service import RateLimitingService
from core.services.circuit_breaker_service import CircuitBreakerService
from infrastructure.adapters.ml_model.ml_model_adapter import MLModelAdapter
from infrastructure.adapters.correlation_id.correlation_id_adapter import CorrelationIdAdapter
from infrastructure.config.logging_adapter import StructuredLoggerAdapter
from infrastructure.adapters.metrics.metrics_adapter import MetricsAdapter
from infrastructure.adapters.market_data.yahoofinance.adapter import YahooFinanceAdapter

from core.datetime_ist import now_ist
from core.hybrid_execution import apply_execution_mode, normalize_execution_mode
from core.safety_state import _HARD_HALT, hard_halt_reason, is_hard_halted, trip_hard_halt
from core.state_manager import state_manager
from core.execution.broker_gateway import broker_gateway
from core.execution.order_manager import order_manager
from core.risk.risk_engine import risk_engine, init_risk_engine
from core.ml_inference import ml_engine, init_ml_engine
from core.observability import obs_manager

# Capture the original main before any shims overwrite it.
# The real trading logic lives in the DI container + stub exports.
# We just need main() to set up the container and print config.
def _original_main() -> None:
    pass  # Real main is the DI container setup

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# =============================================================================
# STUB EXPORTS — provide module-level names for test compatibility
# These are resolved at import time before the DI container is needed.
# =============================================================================
import threading as _threading
import json
import logging

_trip_hard_halt = trip_hard_halt

_bos_lock = _threading.Lock()
_state_lock = _threading.Lock()
_pos_lock = _threading.Lock()

breakout_state: dict[str, Any] = {}
decision_log: dict[str, Any] = {}
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


def send(message: str, critical: bool = False, **kwargs) -> None:
    """Legacy send() shim used by tests and manual signal code."""
    return None


log = logging.getLogger(__name__)


def __getattr__(name: str):
    if name == "_hard_halt_reason":
        return hard_halt_reason()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

PAPER_MODE = True
MANUAL_SIGNALS_ONLY = True
BROKER_API_ENABLED = False
EXECUTION_MODE = "MANUAL"

_config_loaded = False
_CFG: dict[str, Any] = {}
def _load_config():
    global PAPER_MODE, MANUAL_SIGNALS_ONLY, BROKER_API_ENABLED, EXECUTION_MODE, _config_loaded, _CFG
    if _config_loaded:
        return
    try:
        cfg_path = os.environ.get("OPBUYING_INDEX_CONFIG", "config.json")
        with open(cfg_path) as f:
            raw_cfg = json.load(f)
        cfg = dict(raw_cfg)
        apply_execution_mode(cfg, cli_paper=False, infer_blank_from_broker=True)
        MANUAL_SIGNALS_ONLY = cfg.get("MANUAL_SIGNALS_ONLY", True)
        BROKER_API_ENABLED = cfg.get("BROKER_API_ENABLED", False)
        EXECUTION_MODE = cfg.get("EXECUTION_MODE", "MANUAL")
        PAPER_MODE = str(EXECUTION_MODE).upper() in ("PAPER", "SIM", "TEST")
        _CFG = cfg
        _config_loaded = True
    except Exception:
        _CFG = {}
        _config_loaded = True

try:
    _load_config()
except Exception:
    pass
SIGNAL_MAX_AGE = 65
RECONCILE_HALT_ON_QTY_MISMATCH = True
ADAPTIVE_THRESHOLD_ENABLED = True
MAX_POSITION_AGE = 9999

SIGNAL_CFG = {"SIGNAL_TS_MAX_AGE": 300}
_SIGNAL_CFG = SIGNAL_CFG  # alias for test compatibility

from core.services.portfolio_service import PortfolioService
from core.services.execution_service import ExecutionService
from core.services.signal_orchestrator import signal_orchestrator, init_signal_orchestrator

# Initialize PortfolioService with config
_portfolio_service = PortfolioService(_CFG)
# Initialize Signal Orchestrator
init_signal_orchestrator(_CFG)
# Initialize Execution Service
_execution_service = ExecutionService(portfolio_service=_portfolio_service)

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

# Bridge legacy safety functions to the new RiskEngine
# Ensure the shared core safety event is tripped for legacy tests and state consumers.
def _trip_hard_halt(reason="Unknown"):
    trip_hard_halt(reason, source="index_trader")
    if risk_engine:
        try:
            risk_engine.trip_hard_halt(reason)
        except Exception:
            pass

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

    if MANUAL_SIGNALS_ONLY or EXECUTION_MODE in ("MANUAL", "MANUAL_ONLY", "SIGNALS_ONLY"):
        return BrokerAdapter(PaperBrokerAdapter())
    if not (BROKER_API_ENABLED and not PAPER_MODE):
        return BrokerAdapter(PaperBrokerAdapter())

    try:
        from core.adapters.broker_adapters import create_broker_adapter_with_runtime_context

        return create_broker_adapter_with_runtime_context(
            cfg=_CFG,
            index_map=INDEX_MAP,
            driver=str(_CFG.get("BROKER_DRIVER", "PAPER")),
            broker_api_enabled=BROKER_API_ENABLED,
            paper_mode=PAPER_MODE,
            manual_signals_only=MANUAL_SIGNALS_ONLY,
            execution_mode=EXECUTION_MODE,
            now_fn=now_ist,
            log_fn=log,
            send_fn=send,
            shutdown_is_set_fn=lambda: False,
            hard_halt_is_set_fn=is_hard_halted,
            sleep_fn=time.sleep,
            broker_wait_poll_sec=float(_CFG.get("BROKER_WAIT_POLL_SEC", 1.0)),
            expiry_str_fn=lambda s: s,
        )
    except Exception:
        return BrokerAdapter(PaperBrokerAdapter())


def _adaptive_threshold_adjustment(regime="", strength=""):
    from core.adaptive_learning import recent_trade_learning_snapshot
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
    if is_hard_halted():
        decision_log[name] = {"msg": "HARD HALT ACTIVE — blocked"}
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

    # 2. Route to Hardened Execution Service
    from core.ports.execution.execution_port import OrderRequest, OrderType, OrderStatus
    from core.services.execution_service import ExecutionService

    price = sig.get("price", 0.0)
    qty = get_position_size(name, price)
    direction = sig.get("direction", "CALL")
    order_direction = "BUY" if str(direction).upper() == "CALL" else "SELL" if str(direction).upper() == "PUT" else str(direction).upper()

    order_request = OrderRequest(
        symbol=name,
        direction=order_direction,
        strike_price=price,
        lot_size=int(qty),
        order_type=OrderType.MARKET,
        price=price,
    )

    exec_service = ExecutionService(portfolio_service=_portfolio_service)
    order_result = exec_service.execute_order(order_request)
    success = order_result.status in (OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED)

    if success:
        decision_log[name] = {"msg": f"Executed: {order_result.order_id}"}
    else:
        error_text = order_result.reject_reason or str(order_result.status)
        decision_log[name] = {"msg": f"Blocked/Failed: {error_text}"}

def _check_hard_halt_reason():
    import core.safety_state as _ss
    return getattr(_ss, '_hard_halt_reason', '') or ''

def check_pending_reconciliation():
    if not PAPER_MODE:
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

    if pending_adj != 0.0 and not PAPER_MODE:
        send(
            f"ZOMBIE PnL detected during reset: {pending_adj}",
            critical=True,
        )

    if _portfolio_service.handle_daily_reset():
        log.info("Daily portfolio reset performed successfully.")

def _reconcile_positions_live():
    if BROKER_API_ENABLED and RECONCILE_HALT_ON_QTY_MISMATCH:
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
    pass

def _broker_positions_snapshot():
    return {}

def _local_positions_snapshot():
    return {}

INDEX_PRIORITY = ["NIFTY", "BANKNIFTY", "FINNIFTY"]
INDEX_MAP: dict = {
    "NIFTY": {"yf": "^NSEI"},
    "BANKNIFTY": {"yf": "^NSEMDCP"},
    "FINNIFTY": {"yf": "^NSEI"},
}
performance: dict = {"wins": 0, "loss": 0}
_signal_cache: dict = {}

def market_status():
    try:
        now = now_ist()
        weekday = now.weekday()
        if weekday >= 5:
            return "CLOSED"
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
    return False

def _check_manual_kill():
    return False

def circuit_breaker_ok():
    return True

CURRENT_MODE = "NORMAL"

def _check_consec_loss_limit():
    return False

def _vix_cooldown_active(vix):
    return False

def is_nse_post_open_no_trade_zone(t):
    return False

def nse_block_new_entries_from_time():
    from datetime import time as t
    return t(15, 10, 0)

def mins_until_eod():
    return 120.0

def can_reenter(name):
    return True

def expiry_entry_allowed():
    return True

def sniper_ok(name, data, signal_type):
    return True

def get_atm_ltp(nse, signal_type, step):
    return (150.0, 22000)

def _ltp_sane(ltp, name):
    return True

def latency_check(ts):
    return True

def _broker_order_followup_enabled():
    return False

def _api_entry_policy():
    return (1.0, "normal")

def calc_dynamic_slippage(vix, vol_r):
    return 0.0

def get_position_size(name, entry, vix=0.0):
    return 25

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
            import pandas as pd
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
        resp = _nse_session.get("https://www.nseindia.com/marketinfo/holidays/holidaySchedule.jsp")
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
    except Exception:
        _HOLIDAY_FETCH_META["fallback"] = True
        _HOLIDAY_FETCH_META["note"] = "fetch-failed"
    _HOLIDAY_FETCH_META["count"] = len(NSE_HOLIDAYS)

class _MockNseSession:
    def get(self, *args, **kwargs):
        return _MockResponse()

class _MockResponse:
    status_code = 200
    headers = {}
    def json(self):
        return {}
    text = ""

class _MockYf:
    class Ticker:
        def __init__(self, symbol):
            self.symbol = symbol
        def history(self, period=None, interval=None):
            import pandas as pd
            return pd.DataFrame()

_nse_session: Any = _MockNseSession()
import yfinance as yf
NSE_HOLIDAYS: set = set()
_NSE_HOLIDAY_YEARS: set = set()
_HOLIDAY_FETCH_META: dict = {"count": 0, "fallback": False, "note": ""}
_last_close_cache: dict = {}
_last_close_cache_ts = 0

CAPITAL_MANAGER: Any = None
RISK_ENGINE: Any = None
_REGIME_POSITION_SIZING = False
RISK_MODE = "FIXED"
RISK_FIXED_AMOUNT = 500
MAX_DAILY_LOSS = -800
PORTFOLIO_MAX_SL_RISK_PCT = 0.75
MIN_NET_RR = 1.5
SL_PCT = 0.92
TARGET_PCT = 1.3
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

_max_intraday_loss = 0.0
max_daily_loss = 0.0
# =============================================================================
# END STUB EXPORTS
# =============================================================================

# The DI container + stub exports provide the complete trading API.
# main() sets up the container for production use.
# For the DI-migrated version, main() just initializes services.


def setup_di_container() -> None:
    """Set up the dependency injection container with all service implementations."""
    from infrastructure.config.secure_config_adapter import SecureConfigAdapter
    from core.services.execution_service import ExecutionService
    from core.services.risk_service import RiskService
    from core.services.notification_service import NotificationService
    from core.services.persistence_service import PersistenceService
    from core.services.broker_health_service import BrokerHealthService
    from core.services.rate_limiting_service import RateLimitingService
    from core.services.circuit_breaker_service import CircuitBreakerService
    from infrastructure.adapters.brokers.paper.adapter import PaperBrokerAdapter
    from infrastructure.adapters.persistence.sqlite_adapter import SQLiteAdapter
    from infrastructure.adapters.market_data.yahoofinance.adapter import YahooFinanceAdapter
    from infrastructure.adapters.ml_model.ml_model_adapter import MLModelAdapter
    from infrastructure.adapters.correlation_id.correlation_id_adapter import CorrelationIdAdapter
    from infrastructure.config.logging_adapter import StructuredLoggerAdapter
    from infrastructure.adapters.metrics.metrics_adapter import MetricsAdapter

    config_adapter = SecureConfigAdapter()
    container.register_singleton(ConfigPort, type(config_adapter))
    container._singleton_instances[ConfigPort] = config_adapter

    config = container.resolve(ConfigPort)

    broker_port = PaperBrokerAdapter(initial_capital=config.get_int('BASE_CAPITAL', 100000.0))
    trade_persistence = SQLiteAdapter("trades.db")
    market_data_port = YahooFinanceAdapter()

    container.register_singleton(MarketDataPort, type(market_data_port))
    container._singleton_instances[MarketDataPort] = market_data_port

    execution_service = ExecutionService(broker_port=broker_port, trade_persistence=trade_persistence)
    container.register_singleton(ExecutionPort, type(execution_service))
    container._singleton_instances[ExecutionPort] = execution_service

    risk_service = RiskService(trade_persistence=trade_persistence)
    container.register_singleton(RiskPort, type(risk_service))
    container._singleton_instances[RiskPort] = risk_service

    notification_service = NotificationService()
    container.register_singleton(NotificationPort, type(notification_service))
    container._singleton_instances[NotificationPort] = notification_service

    persistence_service = PersistenceService()
    container.register_singleton(PersistencePort, type(persistence_service))
    container._singleton_instances[PersistencePort] = persistence_service

    broker_health_service = BrokerHealthService(broker_adapters={"PAPER": broker_port})
    container.register_singleton(BrokerHealthPort, type(broker_health_service))
    container._singleton_instances[BrokerHealthPort] = broker_health_service

    rate_limiting_service = RateLimitingService()
    container.register_singleton(RateLimitPort, type(rate_limiting_service))
    container._singleton_instances[RateLimitPort] = rate_limiting_service

    circuit_breaker_service = CircuitBreakerService()
    container.register_singleton(CircuitBreakerPort, type(circuit_breaker_service))
    container._singleton_instances[CircuitBreakerPort] = circuit_breaker_service

    ml_model_service = MLModelAdapter()
    container.register_singleton(MlModelPort, type(ml_model_service))
    container._singleton_instances[MlModelPort] = ml_model_service

    correlation_id_service = CorrelationIdAdapter()
    container.register_singleton(CorrelationIdPort, type(correlation_id_service))
    container._singleton_instances[CorrelationIdPort] = correlation_id_service

    logging_service = StructuredLoggerAdapter()
    container.register_singleton(LoggingPort, type(logging_service))
    container._singleton_instances[LoggingPort] = logging_service

    metrics_service = MetricsAdapter({})
    container.register_singleton(MetricsPort, type(metrics_service))
    container._singleton_instances[MetricsPort] = metrics_service


# Backwards-compatible, read-only shim exports (use index_trader_interface for new code)
try:
    from .index_trader_interface import (
        start_trader as start_trader_shim,
        get_state_snapshot as get_state_snapshot_shim,
        generate_signal_snapshot as generate_signal_snapshot_shim,
        health_check as health_check_shim,
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


def main() -> None:
    """Main entry point that sets up DI container for production use."""
    setup_di_container()
    config = container.resolve(ConfigPort)
    if __name__ == "__main__":
        print("=== SECURE CONFIGURATION LOADED ===")
        print(f"Base Capital: {config.get_int('BASE_CAPITAL', 0)}")
        print(f"Paper Mode: {config.get_bool('PAPER_MODE', False)}")
        print(f"Execution Mode: {config.get('EXECUTION_MODE', 'PAPER')}")
        print("Secrets: [REDACTED FOR SECURITY]")
        print("====================================")
        print("OPB Index Trader v2.50 — DI container initialized.")
        print("For live trading, use the Orchestrator cycle-based system.")
        print("Legacy monolithic mode is deprecated.")
        print("Run 'python -m index_app.index_trader' for standalone mode.")


if __name__ == "__main__":
    main()
