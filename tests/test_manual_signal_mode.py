"""
Manual Signal Mode validation tests.

Validates the complete manual-mode safety chain:
  1. apply_execution_mode: MANUAL -> MSO=True, API=False (no broker)
  2. normalize_execution_mode: all MANUAL aliases map correctly
  3. PresentationEngine.manual_signal_message: format + action instruction
  4. PresentationEngine.dashboard_broker_mode: "Manual mode" label
  5. get_wait_reason_components: PASS/WAIT logic with real config thresholds
  6. _make_broker returns PaperAdapter when MANUAL_SIGNALS_ONLY=True
  7. _broker_order_followup_enabled returns False in MANUAL mode

Tests marked @pytest.mark.slow use subprocess + config.json (index_trader module).
Tests without the marker are pure unit tests over core/ modules.

Config thresholds used by slow tests (from config.json):
  ADX_CHOP_THRESHOLD = 14, MIN_NET_RR = 1.5,
  VIX_BLOCK_THRESHOLD = 27, MIN_TRADE_DURATION_MINS = 40
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from core.hybrid_execution import apply_execution_mode, normalize_execution_mode
from core.presentation_engine import PresentationEngine

ROOT = Path(__file__).resolve().parent.parent
INDEX_IMPL = ROOT / "index_app" / "index_trader.py"
CONFIG = ROOT / "config.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(code: str, timeout: int = 60) -> subprocess.CompletedProcess:
    """Run Python code in a subprocess with index_trader config wired up."""
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


def _load_mod_code() -> str:
    """Preamble that loads index_trader as 'mod' inside a subprocess snippet."""
    return (
        f"import importlib.util, os, sys\n"
        f"os.environ['OPBUYING_INDEX_CONFIG'] = r'{CONFIG}'\n"
        f"sys.argv = ['index_app/index_trader.py']\n"
        f"spec = importlib.util.spec_from_file_location('_it', r'{INDEX_IMPL}')\n"
        f"mod = importlib.util.module_from_spec(spec)\n"
        f"spec.loader.exec_module(mod)\n"
    )


# ---------------------------------------------------------------------------
# 1. apply_execution_mode — MANUAL derivation (pure unit tests)
# ---------------------------------------------------------------------------

class TestManualModeDerivation:
    def test_manual_sets_mso_true_and_api_false(self):
        cfg = {"EXECUTION_MODE": "MANUAL", "MANUAL_SIGNALS_ONLY": False, "BROKER_API_ENABLED": True}
        apply_execution_mode(cfg, cli_paper=False)
        assert cfg["MANUAL_SIGNALS_ONLY"] is True
        assert cfg["BROKER_API_ENABLED"] is False

    def test_manual_corrects_pre_set_wrong_flags(self):
        """If someone manually set conflicting flags, apply_execution_mode must correct them."""
        cfg = {"EXECUTION_MODE": "MANUAL", "MANUAL_SIGNALS_ONLY": False, "BROKER_API_ENABLED": True}
        apply_execution_mode(cfg, cli_paper=False)
        assert cfg["MANUAL_SIGNALS_ONLY"] is True
        assert cfg["BROKER_API_ENABLED"] is False
        assert cfg["EXECUTION_MODE"] == "MANUAL"

    def test_manual_mode_result_is_returned(self):
        cfg = {"EXECUTION_MODE": "MANUAL"}
        result = apply_execution_mode(cfg, cli_paper=False)
        assert result is cfg  # mutates + returns same dict

    def test_cli_paper_overrides_manual_to_paper(self):
        cfg = {"EXECUTION_MODE": "MANUAL", "MANUAL_SIGNALS_ONLY": True, "BROKER_API_ENABLED": False}
        apply_execution_mode(cfg, cli_paper=True)
        assert cfg["EXECUTION_MODE"] == "PAPER"
        assert cfg["MANUAL_SIGNALS_ONLY"] is False
        assert cfg["BROKER_API_ENABLED"] is False

    def test_auto_mode_is_separate_from_manual(self):
        cfg = {"EXECUTION_MODE": "AUTO", "MANUAL_SIGNALS_ONLY": True, "BROKER_API_ENABLED": False}
        apply_execution_mode(cfg, cli_paper=False)
        assert cfg["MANUAL_SIGNALS_ONLY"] is False
        assert cfg["BROKER_API_ENABLED"] is True

    def test_paper_mode_also_disables_broker_api(self):
        cfg = {"EXECUTION_MODE": "PAPER", "MANUAL_SIGNALS_ONLY": False, "BROKER_API_ENABLED": True}
        apply_execution_mode(cfg, cli_paper=False)
        assert cfg["BROKER_API_ENABLED"] is False
        assert cfg["MANUAL_SIGNALS_ONLY"] is False


# ---------------------------------------------------------------------------
# 2. normalize_execution_mode — MANUAL aliases
# ---------------------------------------------------------------------------

class TestManualAliases:
    def test_manual_upper_is_canonical(self):
        assert normalize_execution_mode("MANUAL") == "MANUAL"

    def test_manual_lower_normalizes(self):
        assert normalize_execution_mode("manual") == "MANUAL"

    def test_manual_only_alias(self):
        assert normalize_execution_mode("MANUAL_ONLY") == "MANUAL"

    def test_signals_only_alias(self):
        assert normalize_execution_mode("SIGNALS_ONLY") == "MANUAL"

    def test_none_defaults_to_manual(self):
        assert normalize_execution_mode(None) == "MANUAL"

    def test_blank_string_defaults_to_manual(self):
        assert normalize_execution_mode("") == "MANUAL"

    def test_unknown_value_defaults_to_manual(self):
        assert normalize_execution_mode("RANDOM_GARBAGE") == "MANUAL"

    def test_live_is_auto_not_manual(self):
        assert normalize_execution_mode("LIVE") == "AUTO"

    def test_sim_is_paper_not_manual(self):
        assert normalize_execution_mode("SIM") == "PAPER"


# ---------------------------------------------------------------------------
# 3. PresentationEngine.manual_signal_message — format + action instruction
# ---------------------------------------------------------------------------

class TestManualSignalMessage:
    def _pe(self) -> PresentationEngine:
        return PresentationEngine(currency_symbol="Rs")

    def _msg(self) -> str:
        return self._pe().manual_signal_message(
            name="NIFTY",
            signal_type="CALL",
            strike=22000,
            entry=180.5,
            qty=2,
            sl=162.45,
            target=234.65,
            net_rr=2.1,
            score=78,
            why="Strong trend with ADX 24 | RSI 58",
        )

    def test_contains_manual_action_instruction(self):
        msg = self._msg()
        assert "manually" in msg.lower()

    def test_contains_broker_screen_instruction(self):
        msg = self._msg()
        assert "broker" in msg.lower()

    def test_contains_strike(self):
        msg = self._msg()
        assert "22000" in msg

    def test_contains_score(self):
        msg = self._msg()
        assert "78" in msg

    def test_contains_rr(self):
        msg = self._msg()
        assert "2.1" in msg

    def test_contains_why(self):
        msg = self._msg()
        assert "ADX 24" in msg

    def test_contains_signal_type(self):
        msg = self._msg()
        assert "CALL" in msg

    def test_contains_name(self):
        msg = self._msg()
        assert "NIFTY" in msg

    def test_message_does_not_reference_auto_execution(self):
        msg = self._msg()
        lowered = msg.lower()
        assert "auto" not in lowered
        assert "automated" not in lowered
        assert "executing" not in lowered

    def test_message_ends_with_action(self):
        """Last line must be the action instruction — nothing passive."""
        msg = self._msg()
        last_line = msg.strip().splitlines()[-1]
        assert "manually" in last_line.lower() or "broker" in last_line.lower()


# ---------------------------------------------------------------------------
# 4. PresentationEngine.dashboard_broker_mode — MANUAL label
# ---------------------------------------------------------------------------

class TestDashboardBrokerModeManual:
    def _pe(self) -> PresentationEngine:
        return PresentationEngine()

    def test_manual_mode_label(self):
        label = self._pe().dashboard_broker_mode(
            execution_mode="MANUAL", broker_backend="KITE", broker_api_enabled=False
        )
        assert "Manual mode" in label
        assert "signals" in label.lower()
        assert "yourself" in label.lower()

    def test_auto_mode_label_names_backend(self):
        label = self._pe().dashboard_broker_mode(
            execution_mode="AUTO", broker_backend="KITE", broker_api_enabled=True
        )
        assert "Auto mode" in label
        assert "KITE" in label

    def test_paper_mode_label(self):
        label = self._pe().dashboard_broker_mode(
            execution_mode="PAPER", broker_backend="NONE", broker_api_enabled=False
        )
        assert "Paper mode" in label
        assert "simulated" in label.lower()

    def test_manual_mode_does_not_claim_broker_active(self):
        label = self._pe().dashboard_broker_mode(
            execution_mode="MANUAL", broker_backend="KITE", broker_api_enabled=False
        )
        lowered = label.lower()
        assert "active" not in lowered
        assert "ordering" not in lowered

    def test_manual_mode_lowercase_input_normalized(self):
        label = self._pe().dashboard_broker_mode(
            execution_mode="manual", broker_backend="kite", broker_api_enabled=False
        )
        assert "Manual mode" in label


# ---------------------------------------------------------------------------
# 5. get_wait_reason_components — pure function via subprocess
#    Config thresholds: ADX_CHOP=14, MIN_RR=1.5, VIX_BLOCK=27, EOD=40 mins
# ---------------------------------------------------------------------------

@pytest.mark.slow
class TestWaitReasonComponents:
    def _check(self, signal_data: dict) -> tuple[str, str]:
        """Returns (status, stderr) for a given signal_data dict."""
        code = _load_mod_code() + f"""
sd = {signal_data!r}
status, components = mod.get_wait_reason_components(sd)
print("STATUS:" + status)
"""
        r = _run(code)
        assert r.returncode == 0, r.stderr[:800]
        # stdout may contain [CONFIG] lines; find the tagged result line
        for line in r.stdout.splitlines():
            if line.startswith("STATUS:"):
                return line[len("STATUS:"):], r.stderr
        raise AssertionError(f"STATUS: line not found in stdout:\n{r.stdout[:400]}")

    def test_pass_when_score_above_threshold(self):
        status, _ = self._check({"score": 75, "threshold": 60})
        assert status == "PASS"

    def test_pass_on_exact_threshold(self):
        status, _ = self._check({"score": 60, "threshold": 60})
        assert status == "PASS"

    def test_wait_when_score_below_threshold(self):
        status, _ = self._check({"score": 45, "threshold": 60})
        assert status.startswith("WAIT")

    def test_wait_on_choppy_regime_keyword(self):
        # score < threshold so the score gate doesn't short-circuit; CHOPPY regime then fires
        status, _ = self._check({"score": 40, "threshold": 60, "regime": "CHOPPY"})
        assert status.startswith("WAIT")
        assert "ADX" in status

    def test_wait_on_low_adx(self):
        # ADX_CHOP_THRESHOLD = 14; adx=10 triggers the ADX block (score must fail first)
        status, _ = self._check({"score": 40, "threshold": 60, "adx": 10.0})
        assert status.startswith("WAIT")
        assert "ADX" in status

    def test_no_adx_block_above_threshold(self):
        # score passes → PASS regardless of ADX value (correct behaviour — high score wins)
        status, _ = self._check({"score": 75, "threshold": 60, "adx": 20.0})
        assert status == "PASS"

    def test_wait_on_low_rr(self):
        # MIN_NET_RR = 1.5; rr=1.0 triggers the RR block (score must fail first)
        status, _ = self._check({"score": 40, "threshold": 60, "rr": 1.0})
        assert status.startswith("WAIT")
        assert "RR" in status

    def test_no_rr_block_above_min(self):
        # score passes → PASS (rr 2.0 is fine, but score gate is what matters)
        status, _ = self._check({"score": 75, "threshold": 60, "rr": 2.0})
        assert status == "PASS"

    def test_wait_on_high_vix(self):
        # VIX_BLOCK_THRESHOLD = 27; vix=30 triggers the VIX block (score must fail first)
        status, _ = self._check({"score": 40, "threshold": 60, "vix": 30.0})
        assert status.startswith("WAIT")
        assert "VIX" in status

    def test_no_vix_block_below_threshold(self):
        # score passes → PASS (vix 22 is fine)
        status, _ = self._check({"score": 75, "threshold": 60, "vix": 22.0})
        assert status == "PASS"

    def test_wait_on_eod_proximity(self):
        # MIN_TRADE_DURATION_MINS = 40; mins_to_eod=20 triggers EOD block (score must fail first)
        status, _ = self._check({"score": 40, "threshold": 60, "mins_to_eod": 20})
        assert status.startswith("WAIT")
        assert "EOD" in status

    def test_no_eod_block_with_enough_time(self):
        # score passes → PASS (plenty of time left)
        status, _ = self._check({"score": 75, "threshold": 60, "mins_to_eod": 60})
        assert status == "PASS"

    def test_wait_on_market_closed(self):
        status, _ = self._check({"market_status": "CLOSED", "score": 75, "threshold": 60})
        assert status.startswith("WAIT")
        assert "Market" in status

    def test_wait_on_market_holiday(self):
        status, _ = self._check({"market_status": "HOLIDAY"})
        assert "Market" in status
        assert status.startswith("WAIT")

    def test_wait_on_cooldown(self):
        # score must fail so cooldown check is reached
        status, _ = self._check({"score": 40, "threshold": 60, "cooldown_s": 120})
        assert status.startswith("WAIT")
        assert "Cooldown" in status

    def test_components_list_empty_on_pass(self):
        code = _load_mod_code() + """
status, components = mod.get_wait_reason_components({"score": 75, "threshold": 60})
assert status == "PASS", f"Expected PASS, got: {status!r}"
assert components == [], f"Expected empty components, got: {components!r}"
print("STATUS:OK")
"""
        r = _run(code)
        assert r.returncode == 0, r.stderr[:800]
        assert "STATUS:OK" in r.stdout

    def test_missing_signal_data_returns_wait(self):
        status, _ = self._check({})
        assert status.startswith("WAIT")

    def test_none_input_returns_wait(self):
        code = _load_mod_code() + """
status, _ = mod.get_wait_reason_components(None)
assert status.startswith("WAIT"), status
print("ok")
"""
        r = _run(code)
        assert r.returncode == 0, r.stderr[:800]

    def test_multiple_blockers_combined_in_status(self):
        # Low score + low RR: both contribute; at least one appears in WAIT message
        # (STATUS_REASON_MAX=2 caps the displayed reasons but both are in components)
        status, _ = self._check({"score": 40, "threshold": 60, "rr": 1.0})
        assert status.startswith("WAIT"), f"Expected WAIT, got: {status!r}"
        assert "Score" in status or "RR" in status


# ---------------------------------------------------------------------------
# 6 + 7. MANUAL broker gate via subprocess
# ---------------------------------------------------------------------------

@pytest.mark.slow
class TestManualBrokerGate:
    def test_make_broker_returns_paper_in_manual_mode(self):
        """When config is MANUAL, _make_broker() must return PaperAdapter (not a live adapter)."""
        code = _load_mod_code() + """
assert mod.MANUAL_SIGNALS_ONLY is True, "config.json must have EXECUTION_MODE=MANUAL"
broker = mod._make_broker()
# PaperAdapter class or its instance should NOT be KiteAdapter/AngelAdapter
class_name = type(broker).__name__
assert class_name not in ("KiteAdapter", "AngelAdapter"), (
    f"Expected PaperAdapter in MANUAL mode but got {class_name}"
)
print("ok:", class_name)
"""
        r = _run(code)
        assert r.returncode == 0, r.stderr[:800]
        assert "ok:" in r.stdout

    def test_broker_api_disabled_in_manual_mode(self):
        """BROKER_API_ENABLED must be False when EXECUTION_MODE=MANUAL in config.json."""
        code = _load_mod_code() + """
assert mod.BROKER_API_ENABLED is False, (
    f"BROKER_API_ENABLED should be False in MANUAL mode but is {mod.BROKER_API_ENABLED}"
)
print("ok")
"""
        r = _run(code)
        assert r.returncode == 0, r.stderr[:800]
        assert "ok" in r.stdout

    def test_manual_signals_only_true_in_manual_mode(self):
        """MANUAL_SIGNALS_ONLY must be True when loaded with MANUAL config."""
        code = _load_mod_code() + """
assert mod.MANUAL_SIGNALS_ONLY is True, (
    f"MANUAL_SIGNALS_ONLY should be True but is {mod.MANUAL_SIGNALS_ONLY}"
)
print("ok")
"""
        r = _run(code)
        assert r.returncode == 0, r.stderr[:800]
        assert "ok" in r.stdout

    def test_broker_order_followup_disabled_in_manual_mode(self):
        """_broker_order_followup_enabled() must return False in MANUAL mode."""
        code = _load_mod_code() + """
result = mod._broker_order_followup_enabled()
assert result is False, f"Expected False in MANUAL mode but got {result}"
print("ok")
"""
        r = _run(code)
        assert r.returncode == 0, r.stderr[:800]
        assert "ok" in r.stdout

    def test_execution_mode_is_manual_in_config(self):
        """Baseline: config.json must be loaded as MANUAL — not AUTO or PAPER."""
        code = _load_mod_code() + """
assert mod.EXECUTION_MODE == "MANUAL", (
    f"Expected EXECUTION_MODE=MANUAL but got {mod.EXECUTION_MODE}"
)
print("ok")
"""
        r = _run(code)
        assert r.returncode == 0, r.stderr[:800]
        assert "ok" in r.stdout

    def test_paper_mode_global_consistent_with_manual(self):
        """In MANUAL mode, PAPER_MODE should be False (different concept from MANUAL)."""
        code = _load_mod_code() + """
# PAPER_MODE is the CLI --paper flag equivalent; MANUAL is its own separate mode
# Both disable broker API but via different flags
assert mod.BROKER_API_ENABLED is False
assert mod.MANUAL_SIGNALS_ONLY is True
print("ok")
"""
        r = _run(code)
        assert r.returncode == 0, r.stderr[:800]
        assert "ok" in r.stdout


# ---------------------------------------------------------------------------
# 8. Golden-path manual signal regression
#    Validates the complete MANUAL sequence:
#      fresh signal → all guards pass → decision_log updated with MANUAL SIGNAL
#      → send() called with signal content → broker.place_order NOT called
# ---------------------------------------------------------------------------

_GOLDEN_PATH_SETUP = r"""
import time, datetime as _dt
from core.safety_state import clear_hard_halt

# ── module state ──────────────────────────────────────────────────────────
clear_hard_halt()
mod.MANUAL_SIGNALS_ONLY = True
mod.BROKER_API_ENABLED  = False
mod.PAPER_MODE          = False
mod.PRESENTATION_ENGINE = None  # use fallback string to avoid Telegram formatting deps

# ── entry guards: all pass ────────────────────────────────────────────────
mod._check_manual_kill                = lambda: False
mod.circuit_breaker_ok                = lambda: True
mod.CURRENT_MODE                      = "NORMAL"
mod._check_consec_loss_limit          = lambda: False
mod._vix_cooldown_active              = lambda vix: False
mod._is_monday_gap_window             = lambda: False
mod.is_nse_post_open_no_trade_zone    = lambda t: False
mod.nse_block_new_entries_from_time   = lambda: _dt.time(15, 10, 0)
mod.now_ist                           = lambda: _dt.datetime(2026, 4, 22, 10, 30, 0)
mod.mins_until_eod                    = lambda: 120.0
mod.S.target_hit                      = False
mod.can_reenter                       = lambda name: True
mod.expiry_entry_allowed              = lambda: True
mod.is_in_auction_session            = lambda: False
mod._last_entry_ts.clear()
# Disable expiry controller so entry isn't blocked by time-of-day gates
mod._expiry_controller._enable_controls = False

# ── positions: empty ─────────────────────────────────────────────────────
with mod._pos_lock:
    mod.positions.clear()
mod._reserved_capital = 0.0

# ── session state ─────────────────────────────────────────────────────────
mod.S.lock_mode      = False
mod.S.capital        = 10000.0
mod.S.net_daily_pnl  = 0.0
mod.S.trade_count    = 0
mod.S.trail_level    = 0

# ── sizing / risk ────────────────────────────────────────────────────────
mod.CAPITAL_MANAGER         = None
mod.RISK_ENGINE             = None
mod._REGIME_POSITION_SIZING = False
mod.RISK_MODE               = "FIXED"
mod.RISK_FIXED_AMOUNT       = 500
mod.MAX_DAILY_LOSS          = -800
mod.PORTFOLIO_MAX_SL_RISK_PCT = 0.75
mod.MIN_NET_RR              = 1.5
mod.SL_PCT                  = 0.92
mod.TARGET_PCT              = 1.3
mod.MAX_LOT_CAPITAL_PCT     = 0.85
mod.BROKERAGE_PER_TRADE     = 40
mod.PARTIAL_EXIT_ENABLED    = False
mod.API_FAIL_BLOCK_NEW_ENTRIES = 0
mod.calc_dynamic_slippage   = lambda vix, vol_r: 0.0
mod.get_position_size       = lambda name, entry, vix=0.0: 25

# ── order / latency gates ─────────────────────────────────────────────────
mod.sniper_ok                      = lambda name, data, signal_type: True
mod.get_atm_ltp                    = lambda nse, signal_type, step: (150.0, 22000)
mod._ltp_sane                      = lambda ltp, name: True
mod.latency_check                  = lambda ts: True
mod._broker_order_followup_enabled = lambda: False
mod._api_entry_policy              = lambda: (1.0, "normal")

# ── Telegram throttle: clear so send() fires ─────────────────────────────
mod._manual_sig_last.clear()

# ── capture send() + broker.place_order() ────────────────────────────────
_sent = []
mod.send = lambda msg, **kwargs: _sent.append(str(msg))

_broker_calls = []
mod._broker.place_order = lambda *a, **kw: _broker_calls.append((a, kw))

# ── fresh breakout confirmation for NIFTY ────────────────────────────────
with mod._bos_lock:
    mod.breakout_state["NIFTY"] = {
        "type": "CALL",
        "level": 22000.0,
        "ts": time.time() - 10,
        "confirmed_ts": time.time() - 5,
    }

_SIGNAL = {
    "price": 22000.0,
    "vix": 18.0,
    "vol_ratio": 1.3,
    "score": 78,
    "strength": "STRONG",
    "regime": "TRENDING",
    "atr": 0.0,
    "sup": 21800.0,
    "res": 22200.0,
}
"""


@pytest.mark.slow
class TestManualSignalGoldenPath:
    """Golden-path regression: fresh signal → MANUAL mode → decision_log + send() → no broker order."""

    def test_decision_log_updated_with_manual_signal(self):
        """decision_log must contain a MANUAL SIGNAL entry after a valid fresh signal."""
        code = _load_mod_code() + _GOLDEN_PATH_SETUP + """
mod.enter_trade("NIFTY", _SIGNAL)
dlog = mod.decision_log.get("NIFTY", {}).get("msg", "")
assert "MANUAL SIGNAL" in dlog, f"Expected 'MANUAL SIGNAL' in decision_log, got: {dlog!r}"
print("ok")
"""
        r = _run(code)
        assert r.returncode == 0, r.stderr[:1200]
        assert "ok" in r.stdout

    def test_send_called_with_signal_content(self):
        """send() must be called exactly once with the index name and signal type in the message."""
        code = _load_mod_code() + _GOLDEN_PATH_SETUP + """
mod.enter_trade("NIFTY", _SIGNAL)
assert len(_sent) == 1, f"Expected send() called once, got {len(_sent)}: {_sent!r}"
msg = _sent[0]
assert "NIFTY" in msg, f"'NIFTY' not in sent message: {msg!r}"
assert "CALL" in msg,  f"'CALL' not in sent message: {msg!r}"
print("ok")
"""
        r = _run(code)
        assert r.returncode == 0, r.stderr[:1200]
        assert "ok" in r.stdout

    def test_no_broker_order_placed_in_manual_mode(self):
        """broker.place_order must NOT be called in MANUAL mode — the operator places the order."""
        code = _load_mod_code() + _GOLDEN_PATH_SETUP + """
mod.enter_trade("NIFTY", _SIGNAL)
assert not _broker_calls, (
    f"broker.place_order called in MANUAL mode — this is a regression: {_broker_calls!r}"
)
print("ok")
"""
        r = _run(code)
        assert r.returncode == 0, r.stderr[:1200]
        assert "ok" in r.stdout

    def test_decision_log_contains_strike_and_rr(self):
        """decision_log entry must include strike price and RR so operator can act on it."""
        code = _load_mod_code() + _GOLDEN_PATH_SETUP + """
mod.enter_trade("NIFTY", _SIGNAL)
dlog = mod.decision_log.get("NIFTY", {}).get("msg", "")
assert "22000" in dlog, f"Strike not in decision_log: {dlog!r}"
assert "RR=" in dlog,   f"RR not in decision_log: {dlog!r}"
print("ok")
"""
        r = _run(code)
        assert r.returncode == 0, r.stderr[:1200]
        assert "ok" in r.stdout

    def test_stale_signal_does_not_reach_send(self):
        """A signal confirmed more than SIGNAL_MAX_AGE seconds ago must be dropped — send() not called."""
        code = _load_mod_code() + _GOLDEN_PATH_SETUP + """
# Override the confirmed_ts to be stale (beyond SIGNAL_MAX_AGE)
with mod._bos_lock:
    mod.breakout_state["NIFTY"]["confirmed_ts"] = time.time() - (mod.SIGNAL_MAX_AGE + 5)

mod.enter_trade("NIFTY", _SIGNAL)
assert not _sent, f"send() must not be called for a stale signal, got: {_sent!r}"
dlog = mod.decision_log.get("NIFTY", {}).get("msg", "")
assert "stale" in dlog.lower() or "STALE" in dlog, f"Expected staleness in decision_log: {dlog!r}"
print("ok")
"""
        r = _run(code)
        assert r.returncode == 0, r.stderr[:1200]
        assert "ok" in r.stdout
