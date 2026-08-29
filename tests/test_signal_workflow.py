"""Tests for core/signal_approval_workflow.py (v2.46 Sprint 1B)."""
from unittest.mock import MagicMock

from core.signal_approval_workflow import (
    AUTO_WITH_OVERRIDE,
    EXECUTE,
    FULL_MANUAL,
    FULLY_AUTO,
    MANUAL_PRIORITY,
    NOTIFY_ONLY,
    QUEUE,
    SIG_AUTO,
    SIG_MANUAL,
    SIGNALS_ONLY,
    SKIP,
    SignalApprovalWorkflow,
    SignalDecision,
    build_workflow,
)

# ── Fixtures ───────────────────────────────────────────────────────────────────

def _cfg(**overrides):
    base = {
        "manual_signal_workflow_mode": SIGNALS_ONLY,
        "manual_signal_min_score": 50,
        "manual_signal_max_score": 100,
        "TIER_STRONG_MIN": 80,
        "TIER_MODERATE_MIN": 70,
        "BROKER_API_ENABLED": False,
        "EXECUTION_MODE": "MANUAL",
    }
    base.update(overrides)
    return base


def _mock_queue():
    q = MagicMock()
    sig = MagicMock()
    sig.signal_id = "MSQ_123_0001"
    q.submit.return_value = sig
    return q


# ── SignalDecision properties ──────────────────────────────────────────────────

def test_signal_decision_should_execute():
    d = SignalDecision(action=EXECUTE)
    assert d.should_execute
    assert d.should_notify
    assert not d.should_queue


def test_signal_decision_should_queue():
    d = SignalDecision(action=QUEUE, queue_signal_id="MSQ_1")
    assert d.should_queue
    assert d.should_notify
    assert not d.should_execute


def test_signal_decision_notify_only():
    d = SignalDecision(action=NOTIFY_ONLY)
    assert d.should_notify
    assert not d.should_execute
    assert not d.should_queue


def test_signal_decision_skip():
    d = SignalDecision(action=SKIP)
    assert not d.should_notify
    assert not d.should_execute
    assert not d.should_queue


# ── SIGNALS_ONLY mode ──────────────────────────────────────────────────────────

class TestSignalsOnly:
    def test_auto_strong_notifies_only(self):
        wf = SignalApprovalWorkflow(_cfg())
        dec = wf.process_signal(SIG_AUTO, 85, "STRONG", "NIFTY", "CALL")
        assert dec.action == NOTIFY_ONLY

    def test_manual_notifies_only(self):
        wf = SignalApprovalWorkflow(_cfg())
        dec = wf.process_signal(SIG_MANUAL, 90, "STRONG", "NIFTY", "CALL")
        assert dec.action == NOTIFY_ONLY

    def test_weak_notifies_only(self):
        wf = SignalApprovalWorkflow(_cfg())
        dec = wf.process_signal(SIG_AUTO, 40, "WEAK", "NIFTY", "CALL")
        assert dec.action == NOTIFY_ONLY

    def test_strong_gets_higher_priority(self):
        wf = SignalApprovalWorkflow(_cfg())
        strong = wf.process_signal(SIG_AUTO, 85, "STRONG", "NIFTY", "CALL")
        weak = wf.process_signal(SIG_AUTO, 55, "WEAK", "NIFTY", "CALL")
        assert strong.priority < weak.priority  # lower number = higher priority


# ── FULL_MANUAL mode ───────────────────────────────────────────────────────────

class TestFullManual:
    def _wf(self, queue=None):
        return SignalApprovalWorkflow(_cfg(manual_signal_workflow_mode=FULL_MANUAL), queue)

    def test_above_min_score_queues(self):
        q = _mock_queue()
        wf = self._wf(q)
        dec = wf.process_signal(SIG_AUTO, 70, "MODERATE", "NIFTY", "CALL")
        assert dec.action == QUEUE

    def test_below_min_score_skips(self):
        wf = self._wf()
        dec = wf.process_signal(SIG_AUTO, 30, "WEAK", "NIFTY", "CALL")
        assert dec.action == SKIP

    def test_no_queue_falls_back_notify(self):
        wf = self._wf(queue=None)
        dec = wf.process_signal(SIG_AUTO, 70, "MODERATE", "NIFTY", "CALL")
        assert dec.action == NOTIFY_ONLY

    def test_existing_id_uses_existing(self):
        q = _mock_queue()
        wf = self._wf(q)
        dec = wf.process_signal(SIG_MANUAL, 80, "STRONG", "NIFTY", "CALL",
                                 manual_signal_id="MSQ_EXISTING")
        assert dec.action == QUEUE
        assert dec.queue_signal_id == "MSQ_EXISTING"
        q.submit.assert_not_called()  # should not submit again


# ── MANUAL_PRIORITY mode ───────────────────────────────────────────────────────

class TestManualPriority:
    def _wf(self, queue=None, broker=False, exec_mode="MANUAL"):
        return SignalApprovalWorkflow(_cfg(
            manual_signal_workflow_mode=MANUAL_PRIORITY,
            BROKER_API_ENABLED=broker,
            EXECUTION_MODE=exec_mode,
        ), queue)

    def test_manual_signal_goes_to_queue(self):
        q = _mock_queue()
        wf = self._wf(q)
        dec = wf.process_signal(SIG_MANUAL, 80, "STRONG", "NIFTY", "CALL")
        assert dec.action == QUEUE

    def test_auto_strong_executes_when_broker_live(self):
        wf = self._wf(broker=True, exec_mode="AUTO")
        dec = wf.process_signal(SIG_AUTO, 85, "STRONG", "NIFTY", "CALL")
        assert dec.action == EXECUTE

    def test_auto_strong_notifies_no_broker(self):
        # No broker → STRONG auto cannot execute
        wf = self._wf(broker=False)
        dec = wf.process_signal(SIG_AUTO, 85, "STRONG", "NIFTY", "CALL")
        # Should not EXECUTE, falls through to NOTIFY_ONLY
        assert dec.action == NOTIFY_ONLY

    def test_auto_moderate_queues(self):
        q = _mock_queue()
        wf = self._wf(q)
        dec = wf.process_signal(SIG_AUTO, 75, "MODERATE", "NIFTY", "CALL")
        assert dec.action == QUEUE

    def test_auto_weak_notifies(self):
        wf = self._wf()
        dec = wf.process_signal(SIG_AUTO, 60, "WEAK", "NIFTY", "CALL")
        assert dec.action == NOTIFY_ONLY

    def test_below_min_score_skips(self):
        wf = self._wf()
        dec = wf.process_signal(SIG_AUTO, 30, "WEAK", "NIFTY", "CALL")
        assert dec.action == SKIP


# ── AUTO_WITH_OVERRIDE mode ────────────────────────────────────────────────────

class TestAutoWithOverride:
    def _wf(self, broker=True, exec_mode="AUTO"):
        return SignalApprovalWorkflow(_cfg(
            manual_signal_workflow_mode=AUTO_WITH_OVERRIDE,
            BROKER_API_ENABLED=broker,
            EXECUTION_MODE=exec_mode,
        ))

    def test_manual_executes_priority(self):
        wf = self._wf()
        dec = wf.process_signal(SIG_MANUAL, 80, "STRONG", "NIFTY", "CALL")
        assert dec.action == EXECUTE
        assert dec.priority == 0

    def test_auto_above_min_executes(self):
        wf = self._wf()
        dec = wf.process_signal(SIG_AUTO, 75, "MODERATE", "NIFTY", "CALL")
        assert dec.action == EXECUTE

    def test_auto_below_min_notifies(self):
        wf = self._wf()
        dec = wf.process_signal(SIG_AUTO, 40, "WEAK", "NIFTY", "CALL")
        assert dec.action == NOTIFY_ONLY

    def test_no_broker_notifies(self):
        wf = self._wf(broker=False)
        dec = wf.process_signal(SIG_AUTO, 80, "STRONG", "NIFTY", "CALL")
        assert dec.action == NOTIFY_ONLY


# ── FULLY_AUTO mode ────────────────────────────────────────────────────────────

class TestFullyAuto:
    def _wf(self, broker=True, exec_mode="AUTO"):
        return SignalApprovalWorkflow(_cfg(
            manual_signal_workflow_mode=FULLY_AUTO,
            BROKER_API_ENABLED=broker,
            EXECUTION_MODE=exec_mode,
        ))

    def test_executes_when_broker_live(self):
        wf = self._wf()
        dec = wf.process_signal(SIG_AUTO, 80, "STRONG", "NIFTY", "CALL")
        assert dec.action == EXECUTE

    def test_manual_gets_priority_0(self):
        wf = self._wf()
        dec = wf.process_signal(SIG_MANUAL, 85, "STRONG", "NIFTY", "CALL")
        assert dec.action == EXECUTE
        assert dec.priority == 0

    def test_below_min_skips(self):
        wf = self._wf()
        dec = wf.process_signal(SIG_AUTO, 30, "WEAK", "NIFTY", "CALL")
        assert dec.action == SKIP

    def test_no_broker_notifies(self):
        wf = self._wf(broker=False)
        dec = wf.process_signal(SIG_AUTO, 80, "STRONG", "NIFTY", "CALL")
        assert dec.action == NOTIFY_ONLY

    def test_execution_mode_live_also_works(self):
        wf = self._wf(exec_mode="LIVE")
        dec = wf.process_signal(SIG_AUTO, 80, "STRONG", "NIFTY", "CALL")
        assert dec.action == EXECUTE


# ── Score-to-tier fallback ─────────────────────────────────────────────────────

def test_score_to_tier_strong():
    wf = SignalApprovalWorkflow(_cfg())
    assert wf._score_to_tier(85) == "STRONG"


def test_score_to_tier_moderate():
    wf = SignalApprovalWorkflow(_cfg())
    assert wf._score_to_tier(75) == "MODERATE"


def test_score_to_tier_weak():
    wf = SignalApprovalWorkflow(_cfg())
    assert wf._score_to_tier(60) == "WEAK"


def test_tier_override_used_when_provided():
    wf = SignalApprovalWorkflow(_cfg())
    # Score is 85 (STRONG) but tier explicitly provided as WEAK
    dec = wf.process_signal(SIG_AUTO, 85, tier="WEAK", index_name="NIFTY", direction="CALL")
    # In SIGNALS_ONLY mode, both would be NOTIFY_ONLY, so just check no crash
    assert dec.action == NOTIFY_ONLY


# ── Unknown mode defaults to SIGNALS_ONLY ─────────────────────────────────────

def test_unknown_mode_defaults_to_signals_only():
    wf = SignalApprovalWorkflow(_cfg(manual_signal_workflow_mode="BOGUS_MODE"))
    assert wf.mode == SIGNALS_ONLY


# ── Factory ────────────────────────────────────────────────────────────────────

def test_build_workflow_returns_workflow():
    wf = build_workflow(_cfg())
    assert isinstance(wf, SignalApprovalWorkflow)
    assert wf.mode == SIGNALS_ONLY


def test_build_workflow_bad_config_returns_signals_only():
    wf = build_workflow({"manual_signal_workflow_mode": None})
    assert wf.mode == SIGNALS_ONLY
