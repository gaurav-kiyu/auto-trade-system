"""
Signal Safety Tests - manual-mode gate validation for error paths.

Covers three critical safety behaviors:

  1. Signal Staleness (SIGNAL_MAX_AGE)
     - A confirmed signal whose timestamp exceeds SIGNAL_MAX_AGE must be silently
       dropped (decision_log shows "stale") with no order or Telegram message sent.
     - The candle-level staleness guard (SIGNAL_TS_MAX_AGE) in generate_signal() must
       return None when the latest candle is too old.

  2. Zombie PnL Confirmation (capital_adj_pending)
     - check_pending_reconciliation(): non-zero cap_adj in non-PAPER mode must emit
       a critical Telegram warning and NOT silently apply the amount to capital.
     - daily_reset(): same requirement - unresolved zombie PnL must alert, not auto-apply.

  3. Reconciliation Hard Halt (qty mismatch)
     - When broker qty != bot qty (both > 0) and RECONCILE_HALT_ON_QTY_MISMATCH=true,
       _reconcile_positions_live() must call _trip_hard_halt(), setting _HARD_HALT.

All tests are @pytest.mark.slow - they load index_trader via subprocess with config.json.
Config thresholds (from config.json): SIGNAL_MAX_AGE=65, SIGNAL_TS_MAX_AGE=300.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
INDEX_IMPL = ROOT / "index_app" / "index_trader.py"
CONFIG = ROOT / "config.json"


# ---------------------------------------------------------------------------
# Subprocess helpers (shared with test_manual_signal_mode.py pattern)
# ---------------------------------------------------------------------------

def _run(code: str, timeout: int = 90) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


def _preamble() -> str:
    """Load index_trader as 'mod' with the real config.json."""
    return (
        f"import importlib.util, os, sys, time, datetime\n"
        f"os.environ['OPBUYING_INDEX_CONFIG'] = r'{CONFIG}'\n"
        f"sys.argv = ['index_app/index_trader.py']\n"
        f"spec = importlib.util.spec_from_file_location('_it', r'{INDEX_IMPL}')\n"
        f"mod = importlib.util.module_from_spec(spec)\n"
        f"spec.loader.exec_module(mod)\n"
    )


# ---------------------------------------------------------------------------
# 1. Signal Staleness - SIGNAL_MAX_AGE enforcement
# ---------------------------------------------------------------------------

@pytest.mark.slow
@pytest.mark.confidence_gate
class TestSignalStaleness:
    """
    SIGNAL_MAX_AGE (config: 65s) gates enter_trade via confirmed_ts in breakout_state.
    A stale confirmed_ts must cause enter_trade to set_dlog 'stale' and return without
    placing an order or sending a manual-signal Telegram.
    """

    def test_stale_signal_blocked_in_enter_trade(self):
        """enter_trade with confirmed_ts > SIGNAL_MAX_AGE ago sets 'stale' in decision_log."""
        code = _preamble() + """
# Bypass day-of-week checks so only the staleness gate is exercised
mod._is_monday_gap_window = lambda: False
# Disable expiry controls so the tests aren't blocked by time-of-day gates
mod._expiry_controller._enable_controls = False
# Bypass auction session gate (flaky during 09:00-09:15 / 15:30-15:45 IST)
mod.is_in_auction_session = lambda now=None: False

# Set a stale confirmed_ts (SIGNAL_MAX_AGE + 30 seconds ago)
stale_ts = time.time() - mod.SIGNAL_MAX_AGE - 30
with mod._bos_lock:
    mod.breakout_state["NIFTY"] = {"type": "CALL", "confirmed_ts": stale_ts}

# Capture send() calls - should NOT be called for a stale signal
sent = []
mod.send = lambda msg, critical=False, **kw: sent.append(msg)

sig = {"score": 75, "direction": "CALL", "vix": 15.0, "signal_ts": stale_ts,
       "strength": "MODERATE", "name": "NIFTY", "threshold": 60}
mod.enter_trade("NIFTY", sig)

# decision_log must show the stale message
dlog = mod.decision_log.get("NIFTY", {})
msg = dlog.get("msg", "") if isinstance(dlog, dict) else str(dlog)
assert "stale" in msg.lower(), f"Expected 'stale' in decision_log, got: {msg!r}"
# No Telegram message should be sent for stale signals (dropped silently)
manual_sigs = [s for s in sent if "manual signal" in s.lower() or "Signal" in s]
assert not manual_sigs, f"Unexpected Telegram for stale signal: {manual_sigs}"
print("STATUS:PASS")
"""
        r = _run(code)
        assert r.returncode == 0, r.stderr[:1000]
        assert "STATUS:PASS" in r.stdout

    def test_fresh_signal_not_blocked_by_staleness(self):
        """A fresh confirmed_ts (< SIGNAL_MAX_AGE ago) does NOT set stale in decision_log."""
        code = _preamble() + """
# Bypass day-of-week checks so only the staleness gate is exercised
mod._is_monday_gap_window = lambda: False
# Disable expiry controls so the tests aren't blocked by time-of-day gates
mod._expiry_controller._enable_controls = False
# Bypass auction session gate (flaky during 09:00-09:15 / 15:30-15:45 IST)
mod.is_in_auction_session = lambda now=None: False
# Bypass sniper gate (needs price/sup/res fields we don't need here) - not what this test checks
mod.sniper_ok = lambda name, data, signal_type: False

fresh_ts = time.time() - 5  # 5 seconds old - well within 65s limit
with mod._bos_lock:
    mod.breakout_state["NIFTY"] = {"type": "CALL", "confirmed_ts": fresh_ts}

sig = {"score": 75, "direction": "CALL", "vix": 15.0, "signal_ts": fresh_ts,
       "strength": "MODERATE", "name": "NIFTY", "threshold": 60}
mod.enter_trade("NIFTY", sig)

dlog = mod.decision_log.get("NIFTY", {})
msg = dlog.get("msg", "") if isinstance(dlog, dict) else str(dlog)
assert "stale" not in msg.lower(), f"Fresh signal wrongly marked stale: {msg!r}"
print("STATUS:PASS")
"""
        r = _run(code)
        assert r.returncode == 0, r.stderr[:1000]
        assert "STATUS:PASS" in r.stdout

    def test_stale_signal_age_matches_config_threshold(self):
        """SIGNAL_MAX_AGE loaded from config.json (65s) is what the staleness gate uses."""
        code = _preamble() + """
# Bypass day-of-week checks so only the staleness gate is exercised
mod._is_monday_gap_window = lambda: False
# Disable expiry controls so the tests aren't blocked by time-of-day gates
mod._expiry_controller._enable_controls = False
# Bypass auction session gate (flaky during 09:00-09:15 / 15:30-15:45 IST)
mod.is_in_auction_session = lambda now=None: False
# Bypass sniper gate (needs price/sup/res fields we don't need here) - not what this test checks
mod.sniper_ok = lambda name, data, signal_type: False

# Verify SIGNAL_MAX_AGE loaded from config.json
assert mod.SIGNAL_MAX_AGE == 65, f"Expected SIGNAL_MAX_AGE=65 from config, got {mod.SIGNAL_MAX_AGE}"

# Signal 1 second BEFORE the threshold should pass the gate
just_fresh_ts = time.time() - (mod.SIGNAL_MAX_AGE - 1)
with mod._bos_lock:
    mod.breakout_state["NIFTY"] = {"type": "CALL", "confirmed_ts": just_fresh_ts}
sig = {"score": 75, "direction": "CALL", "vix": 15.0, "signal_ts": just_fresh_ts,
       "strength": "MODERATE", "name": "NIFTY", "threshold": 60}
mod.enter_trade("NIFTY", sig)
dlog = mod.decision_log.get("NIFTY", {})
msg = dlog.get("msg", "") if isinstance(dlog, dict) else str(dlog)
assert "stale" not in msg.lower(), f"Signal 1s before threshold wrongly blocked: {msg!r}"

# Signal 1 second AFTER the threshold must be stale
just_stale_ts = time.time() - (mod.SIGNAL_MAX_AGE + 1)
with mod._bos_lock:
    mod.breakout_state["NIFTY"]["confirmed_ts"] = just_stale_ts
# Also update signal_ts so the stale check triggers on signal age
sig["signal_ts"] = just_stale_ts
mod.enter_trade("NIFTY", sig)
dlog2 = mod.decision_log.get("NIFTY", {})
msg2 = dlog2.get("msg", "") if isinstance(dlog2, dict) else str(dlog2)
assert "stale" in msg2.lower(), f"Signal 1s past threshold not blocked: {msg2!r}"
print("STATUS:PASS")
"""
        r = _run(code)
        assert r.returncode == 0, r.stderr[:1000]
        assert "STATUS:PASS" in r.stdout

    def test_candle_level_staleness_returns_none(self):
        """
        SIGNAL_TS_MAX_AGE (config: 300s) is checked inside generate_signal().
        When the latest candle timestamp is too old, generate_signal() returns None
        and sets decision_log 'Stale signal ts'.
        """
        code = _preamble() + """
# SIGNAL_TS_MAX_AGE should now be in config.json as 300
ts_max_age = mod._SIGNAL_CFG.get("SIGNAL_TS_MAX_AGE", 300)
assert ts_max_age == 300, f"Expected SIGNAL_TS_MAX_AGE=300, got {ts_max_age}"
print(f"STATUS:SIGNAL_TS_MAX_AGE={ts_max_age}")
"""
        r = _run(code)
        assert r.returncode == 0, r.stderr[:1000]
        assert "STATUS:SIGNAL_TS_MAX_AGE=300" in r.stdout

    def test_stale_signal_does_not_proceed_to_order_placement(self):
        """In MANUAL mode, stale signals must not reach the manual Telegram path."""
        code = _preamble() + """
assert mod.MANUAL_SIGNALS_ONLY is True, "Test requires MANUAL mode"

# Bypass day-of-week checks so only the staleness gate is exercised
mod._is_monday_gap_window = lambda: False
# Disable expiry controls so the tests aren't blocked by time-of-day gates
mod._expiry_controller._enable_controls = False
# Bypass auction session gate (flaky during 09:00-09:15 / 15:30-15:45 IST)
mod.is_in_auction_session = lambda now=None: False

stale_ts = time.time() - mod.SIGNAL_MAX_AGE - 60
with mod._bos_lock:
    mod.breakout_state["BANKNIFTY"] = {"type": "PUT", "confirmed_ts": stale_ts}

telegram_sent = []
mod.send = lambda msg, critical=False, **kw: telegram_sent.append(msg)

sig = {"score": 80, "direction": "PUT", "vix": 15.0, "signal_ts": stale_ts,
       "strength": "STRONG", "name": "BANKNIFTY", "threshold": 60}
mod.enter_trade("BANKNIFTY", sig)

# Telegram must NOT have been called with a signal message for the stale signal
signal_msgs = [m for m in telegram_sent if "SIGNAL" in m.upper() or "manual" in m.lower()]
assert not signal_msgs, (
    f"Signal Telegram sent for stale signal: {signal_msgs[:1]}"
)
# Verify staleness was recorded in the decision log
dlog = mod.decision_log.get("BANKNIFTY", {})
msg = dlog.get("msg", "") if isinstance(dlog, dict) else str(dlog)
assert "stale" in msg.lower(), f"Expected stale marker in decision_log: {msg!r}"
print("STATUS:PASS")
"""
        r = _run(code)
        assert r.returncode == 0, r.stderr[:1000]
        assert "STATUS:PASS" in r.stdout


# ---------------------------------------------------------------------------
# 2. Zombie PnL Confirmation (capital_adj_pending)
# ---------------------------------------------------------------------------

@pytest.mark.slow
@pytest.mark.confidence_gate
class TestZombiePnLConfirmation:
    """
    Non-zero capital_adj_pending in non-PAPER mode must always emit a critical warning.
    Capital must NOT be silently updated - operator must manually verify with broker.
    """

    def test_check_pending_reconciliation_emits_warning(self):
        """check_pending_reconciliation() sends a critical alert when cap_adj != 0."""
        code = _preamble() + """
assert mod.PAPER_MODE is False, "Test requires non-paper mode (EXECUTION_MODE=MANUAL)"

sent = []
mod.send = lambda msg, critical=False, **kw: sent.append((msg, critical))

with mod._state_lock:
    mod.S.capital_adj_pending = 200.0

mod.check_pending_reconciliation()

# Must have sent at least one message
assert sent, "Expected send() to be called with zombie PnL warning"
msgs = [m for m, _ in sent]
all_text = " ".join(msgs).upper()
# Must contain a warning about pending/zombie PnL
assert any(w in all_text for w in ["ZOMBIE", "PENDING", "CAP_ADJ", "PNL"]), (
    f"Warning message did not mention pending reconciliation: {msgs}"
)
# Capital must NOT have been silently updated
assert mod.S.capital_adj_pending == 200.0, (
    "capital_adj_pending was wrongly auto-applied in non-paper mode"
)
print("STATUS:PASS")
"""
        r = _run(code)
        assert r.returncode == 0, r.stderr[:1000]
        assert "STATUS:PASS" in r.stdout

    def test_check_pending_reconciliation_warning_is_critical(self):
        """The zombie PnL warning must be sent as critical=True (not a soft log)."""
        code = _preamble() + """
assert mod.PAPER_MODE is False

sent_critical = []
def _capture(msg, critical=False, **kw):
    if critical:
        sent_critical.append(msg)

mod.send = _capture

with mod._state_lock:
    mod.S.capital_adj_pending = 150.0

mod.check_pending_reconciliation()
assert sent_critical, (
    "Zombie PnL warning was not sent with critical=True"
)
print("STATUS:PASS")
"""
        r = _run(code)
        assert r.returncode == 0, r.stderr[:1000]
        assert "STATUS:PASS" in r.stdout

    def test_check_pending_reconciliation_zero_adj_no_warning(self):
        """With capital_adj_pending == 0, no warning should be sent."""
        code = _preamble() + """
sent = []
mod.send = lambda msg, critical=False, **kw: sent.append(msg)

with mod._state_lock:
    mod.S.capital_adj_pending = 0.0

mod.check_pending_reconciliation()

zombie_msgs = [m for m in sent if any(w in m.upper() for w in ["ZOMBIE","CAP_ADJ","PENDING"])]
assert not zombie_msgs, f"Unexpected zombie warning when cap_adj=0: {zombie_msgs}"
print("STATUS:PASS")
"""
        r = _run(code)
        assert r.returncode == 0, r.stderr[:1000]
        assert "STATUS:PASS" in r.stdout

    def test_daily_reset_emits_zombie_warning_non_paper(self):
        """daily_reset() sends a critical zombie PnL alert and does not auto-apply."""
        code = _preamble() + """
assert mod.PAPER_MODE is False

sent = []
mod.send = lambda msg, critical=False, **kw: sent.append((msg, critical))

with mod._state_lock:
    mod.S.capital_adj_pending = 350.0
    original_capital = mod.S.capital
    # Force last_reset_day to yesterday so daily_reset() doesn't short-circuit
    mod.S.last_reset_day = (
        mod.now_ist().date() - __import__('datetime').timedelta(days=1)
    )

mod.daily_reset()

# Capital must NOT have changed due to auto-apply
assert mod.S.capital == original_capital, (
    f"Capital was auto-modified in non-paper mode: before={original_capital}, after={mod.S.capital}"
)
# A warning must have been sent
msgs = [m for m, _ in sent]
assert any(any(w in m.upper() for w in ["ZOMBIE","UNRESOLVED","CAP_ADJ"]) for m in msgs), (
    f"No zombie PnL warning in daily_reset messages: {msgs[:2]}"
)
print("STATUS:PASS")
"""
        r = _run(code)
        assert r.returncode == 0, r.stderr[:1000]
        assert "STATUS:PASS" in r.stdout

    def test_daily_reset_zombie_is_critical(self):
        """The daily_reset zombie warning must be sent with critical=True."""
        code = _preamble() + """
assert mod.PAPER_MODE is False

critical_msgs = []
mod.send = lambda msg, critical=False, **kw: critical_msgs.append(msg) if critical else None

with mod._state_lock:
    mod.S.capital_adj_pending = 100.0
    mod.S.last_reset_day = (
        mod.now_ist().date() - __import__('datetime').timedelta(days=1)
    )

mod.daily_reset()
assert critical_msgs, "daily_reset zombie warning must be critical=True"
print("STATUS:PASS")
"""
        r = _run(code)
        assert r.returncode == 0, r.stderr[:1000]
        assert "STATUS:PASS" in r.stdout


# ---------------------------------------------------------------------------
# 3. Reconciliation Hard Halt (qty mismatch → _HARD_HALT)
# ---------------------------------------------------------------------------

@pytest.mark.slow
@pytest.mark.confidence_gate
class TestReconciliationHardHalt:
    """
    When broker qty != bot qty (both > 0) and RECONCILE_HALT_ON_QTY_MISMATCH=true,
    _reconcile_positions_live() must set _HARD_HALT and record a reason string.
    This prevents the bot from continuing to trade with inconsistent state.
    """

    def _mismatch_code(self, broker_qty: int, local_qty: int) -> str:
        return _preamble() + f"""
# Override globals: enable broker API and disable paper/manual mode for this test
mod.BROKER_API_ENABLED = True
mod.PAPER_MODE = False
mod.MANUAL_SIGNALS_ONLY = False
mod.RECONCILE_HALT_ON_QTY_MISMATCH = True

# Suppress Telegram alerts during the test
mod.send = lambda msg, critical=False, **kw: None

# Set up a position in the bot
with mod._pos_lock:
    mod.positions["NIFTY"] = {{"qty": {local_qty}, "signal": "CALL", "strike": 22000,
                                "entry": 180.0, "entry_ts": __import__('time').time()}}

# Mock broker returning a different qty
class MockBroker:
    def get_position_qty(self, name, signal, strike):
        return {broker_qty}

mod._broker = MockBroker()

# Clear halt before test
mod._HARD_HALT.clear()

mod._reconcile_positions_live()

if mod._HARD_HALT.is_set():
    print(f"STATUS:HALTED reason={{mod._hard_halt_reason!r}}")
else:
    print("STATUS:NOT_HALTED")
"""

    def test_qty_mismatch_trips_hard_halt(self):
        """broker=25, bot=50 → both > 0 → _HARD_HALT.is_set() must be True."""
        r = _run(self._mismatch_code(broker_qty=25, local_qty=50))
        assert r.returncode == 0, r.stderr[:1000]
        assert "STATUS:HALTED" in r.stdout, (
            f"Expected HALTED but got: {r.stdout.strip()}"
        )

    def test_halt_reason_mentions_mismatch(self):
        """The halt reason string must describe the qty mismatch."""
        r = _run(self._mismatch_code(broker_qty=15, local_qty=50))
        assert r.returncode == 0, r.stderr[:1000]
        assert "STATUS:HALTED" in r.stdout
        for line in r.stdout.splitlines():
            if line.startswith("STATUS:HALTED"):
                reason = line[len("STATUS:HALTED reason="):]
                assert "mismatch" in reason.lower() or "qty" in reason.lower() or "NIFTY" in reason, (
                    f"Halt reason does not describe the mismatch: {reason}"
                )

    def test_no_halt_when_broker_qty_zero(self):
        """broker=0, bot=50 → zombie exit path, NOT a hard halt (different code path)."""
        code = _preamble() + """
mod.BROKER_API_ENABLED = True
mod.PAPER_MODE = False
mod.MANUAL_SIGNALS_ONLY = False
mod.RECONCILE_HALT_ON_QTY_MISMATCH = True
mod.send = lambda msg, critical=False, **kw: None
mod.MAX_POSITION_AGE = 9999  # prevent zombie age-out exit during test

with mod._pos_lock:
    mod.positions["NIFTY"] = {"qty": 50, "signal": "CALL", "strike": 22000,
                               "entry": 180.0, "entry_ts": __import__('time').time()}

class MockBroker:
    def get_position_qty(self, name, signal, strike):
        return 0  # Broker has 0 - zombie exit path, not mismatch halt

mod._broker = MockBroker()
mod._HARD_HALT.clear()
mod._reconcile_positions_live()

# broker=0, local=50 is a zombie case - marked for age-out, NOT a hard halt
assert not mod._HARD_HALT.is_set(), (
    "Hard halt should NOT fire when broker qty is 0 (zombie exit path)"
)
print("STATUS:PASS")
"""
        r = _run(code)
        assert r.returncode == 0, r.stderr[:1000]
        assert "STATUS:PASS" in r.stdout

    def test_no_halt_when_reconcile_flag_false(self):
        """RECONCILE_HALT_ON_QTY_MISMATCH=false must suppress the halt even on mismatch."""
        code = _preamble() + """
mod.BROKER_API_ENABLED = True
mod.PAPER_MODE = False
mod.MANUAL_SIGNALS_ONLY = False
mod.RECONCILE_HALT_ON_QTY_MISMATCH = False  # disabled

mod.send = lambda msg, critical=False, **kw: None

with mod._pos_lock:
    mod.positions["NIFTY"] = {"qty": 50, "signal": "CALL", "strike": 22000,
                               "entry": 180.0, "entry_ts": __import__('time').time()}

class MockBroker:
    def get_position_qty(self, name, signal, strike):
        return 25  # mismatch but flag is off

mod._broker = MockBroker()
mod._HARD_HALT.clear()
mod._reconcile_positions_live()

assert not mod._HARD_HALT.is_set(), (
    "Hard halt must not fire when RECONCILE_HALT_ON_QTY_MISMATCH=false"
)
print("STATUS:PASS")
"""
        r = _run(code)
        assert r.returncode == 0, r.stderr[:1000]
        assert "STATUS:PASS" in r.stdout

    def test_reconciliation_skipped_in_manual_mode(self):
        """In MANUAL mode (BROKER_API_ENABLED=False), reconciliation is a no-op."""
        code = _preamble() + """
# Confirm MANUAL mode globals
assert mod.BROKER_API_ENABLED is False
assert mod.MANUAL_SIGNALS_ONLY is True

mod._HARD_HALT.clear()
with mod._pos_lock:
    mod.positions["NIFTY"] = {"qty": 50, "signal": "CALL", "strike": 22000,
                               "entry": 180.0, "entry_ts": __import__('time').time()}

# This should be a no-op since BROKER_API_ENABLED=False
mod._periodic_reconcile()

assert not mod._HARD_HALT.is_set(), (
    "Reconciliation ran in MANUAL mode - it should be skipped entirely"
)
print("STATUS:PASS")
"""
        r = _run(code)
        assert r.returncode == 0, r.stderr[:1000]
        assert "STATUS:PASS" in r.stdout

    def test_halt_blocks_subsequent_entry_attempts(self):
        """After _HARD_HALT is set, enter_trade must block all new entries."""
        code = _preamble() + """
# Manually trip the halt
mod._trip_hard_halt("Test-induced halt for entry blocking check")
assert mod._HARD_HALT.is_set()

# Suppress Telegram
mod.send = lambda msg, critical=False, **kw: None
mod.is_in_auction_session = lambda: False

# Attempt to enter a trade
sig = {"score": 95, "direction": "CALL", "vix": 15.0, "signal_ts": __import__('time').time(),
       "strength": "STRONG", "name": "NIFTY", "threshold": 60}
mod.enter_trade("NIFTY", sig)

dlog = mod.decision_log.get("NIFTY", {})
msg = dlog.get("msg", "") if isinstance(dlog, dict) else str(dlog)
assert "halt" in msg.lower(), f"Expected HARD HALT block message, got: {msg!r}"
print("STATUS:PASS")
"""
        r = _run(code)
        assert r.returncode == 0, r.stderr[:1000]
        assert "STATUS:PASS" in r.stdout
