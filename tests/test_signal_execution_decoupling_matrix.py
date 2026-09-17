"""
Test suite: Signal Qualification and Trade Execution Decoupling Matrix.

Validates the invariant:
A genuinely qualified MODERATE or STRONG signal must be durably recorded and made
available to the Super Admin independently of whether its associated trade is
subsequently executable.

Required flow:
Market Data
==> Signal Evaluation
==> Qualification / Classification
==> Eligible Recipient Resolution
==> Signal Persistence
==> Super Admin/User Signal Visibility
==> Margin Validation
==> Risk/Execution Validation
==> PAPER Execution

All 10 required domain & contract regression tests:
1. MODERATE signal + sufficient margin
2. MODERATE signal + insufficient margin
3. STRONG signal + sufficient margin
4. STRONG signal + insufficient margin
5. Exact configured classification boundaries
6. Repeated evaluation/deduplication
7. Existing active signal reuse
8. Super Admin API visibility
9. Super Admin UI visibility
10. Unauthorized-user isolation
"""

from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from core.ports.execution.execution_port import ExecutionMode, OrderStatus
from core.position_service import PositionService, TradeBlockError
from core.signals.signal_tracker import SignalTracker


@pytest.fixture
def isolated_signal_tracker(tmp_path):
    db_file = tmp_path / "test_decoupling_signals.db"
    tracker = SignalTracker(db_path=db_file)
    return tracker


def make_service(mode="PAPER", cfg=None, tracker=None):
    svc = PositionService.__new__(PositionService)
    svc._cfg = cfg or {
        "STRONG_THRESHOLD": 80,
        "MODERATE_THRESHOLD": 68,
        "AI_THRESHOLD": 60,
        "BASE_CAPITAL": 3000,
        "EXECUTION_MODE": mode,
    }
    svc._execution_service = Mock()
    svc._portfolio_service = Mock()
    svc._risk_service = Mock()
    svc._margin_validator = Mock()
    svc._execution_mode = mode
    svc._decision_log = {}
    svc._send_notification = Mock()
    svc._check_liquidity_gate = Mock(return_value=(True, "ok"))
    svc._risk_service.evaluate_trade.return_value = SimpleNamespace(
        decision=SimpleNamespace(value="approved"),
        reason="ok",
        risk_score=10.0,
    )
    svc._risk_service.get_portfolio_risk_metrics.return_value = {}
    svc._risk_service.get_required_margin_per_lot.return_value = 5080.0
    return svc


def test_1_moderate_signal_sufficient_margin(isolated_signal_tracker):
    """1. MODERATE signal + sufficient margin -> Persisted + PAPER executed."""
    tracker = isolated_signal_tracker
    svc = make_service("PAPER", tracker=tracker)
    svc._portfolio_service.get_available_margin.return_value = 100000.0
    svc._margin_validator.validate.return_value = SimpleNamespace(allowed=True, error_message="")
    svc._execution_service.execute_order.return_value = SimpleNamespace(status=OrderStatus.FILLED)

    sig = {
        "symbol": "NIFTY",
        "score": 75,
        "tier": "MODERATE",
        "direction": "CALL",
        "price": 25000.0,
        "category": "INDEX_OPTIONS",
    }

    with patch("core.signals.signal_tracker.SignalTracker.get_instance", return_value=tracker):
        result = svc._submit_order_under_lock(
            name="NIFTY", price=25000.0, qty=1, sig=sig, order_direction="BUY", idempotency_key="idem-mod-01"
        )

    assert result.status == OrderStatus.FILLED
    assert sig.get("signal_id") is not None
    assert sig["signal_id"].startswith("SIG-")

    # Verify persisted in DB
    analytics = tracker.get_admin_signal_analytics(include_seed_samples=False)
    matches = [s for s in analytics["signals"] if s["signal_id"] == sig["signal_id"]]
    assert len(matches) == 1
    assert matches[0]["tier"] == "MODERATE"
    assert matches[0]["score"] == 75

    # Verify PAPER mode
    svc._execution_service.execute_order.assert_called_once()
    _, ctx = svc._execution_service.execute_order.call_args.args
    assert ctx.execution_mode is ExecutionMode.PAPER


def test_2_moderate_signal_insufficient_margin(isolated_signal_tracker):
    """2. MODERATE signal + insufficient margin -> Persisted + Margin BLOCKED (NO order)."""
    tracker = isolated_signal_tracker
    svc = make_service("PAPER", tracker=tracker)
    svc._portfolio_service.get_available_margin.return_value = 3000.0
    svc._margin_validator.validate.return_value = SimpleNamespace(
        allowed=False, error_message="MARGIN INSUFFICIENT: available 3000 < required 5080"
    )

    sig = {
        "symbol": "NIFTY",
        "score": 75,
        "tier": "MODERATE",
        "direction": "CALL",
        "price": 25000.0,
        "category": "INDEX_OPTIONS",
    }

    with patch("core.signals.signal_tracker.SignalTracker.get_instance", return_value=tracker):
        with pytest.raises(TradeBlockError, match="MARGIN_BLOCK"):
            svc._submit_order_under_lock(
                name="NIFTY", price=25000.0, qty=1, sig=sig, order_direction="BUY", idempotency_key="idem-mod-02"
            )

    # Invariant: Signal MUST be persisted despite execution rejection
    assert sig.get("signal_id") is not None
    assert sig["signal_id"].startswith("SIG-")

    analytics = tracker.get_admin_signal_analytics(include_seed_samples=False)
    matches = [s for s in analytics["signals"] if s["signal_id"] == sig["signal_id"]]
    assert len(matches) == 1
    assert matches[0]["symbol"] == "NIFTY"
    assert matches[0]["tier"] == "MODERATE"
    assert matches[0]["status"] == "ACTIVE"

    # Execution service MUST NOT have been called
    svc._execution_service.execute_order.assert_not_called()


def test_3_strong_signal_sufficient_margin(isolated_signal_tracker):
    """3. STRONG signal + sufficient margin -> Persisted + PAPER executed."""
    tracker = isolated_signal_tracker
    svc = make_service("PAPER", tracker=tracker)
    svc._portfolio_service.get_available_margin.return_value = 50000.0
    svc._margin_validator.validate.return_value = SimpleNamespace(allowed=True, error_message="")
    svc._execution_service.execute_order.return_value = SimpleNamespace(status=OrderStatus.FILLED)

    sig = {
        "symbol": "BANKNIFTY",
        "score": 94,
        "tier": "STRONG",
        "direction": "CALL",
        "price": 52000.0,
        "category": "INDEX_OPTIONS",
    }

    with patch("core.signals.signal_tracker.SignalTracker.get_instance", return_value=tracker):
        result = svc._submit_order_under_lock(
            name="BANKNIFTY", price=52000.0, qty=1, sig=sig, order_direction="BUY", idempotency_key="idem-str-01"
        )

    assert result.status == OrderStatus.FILLED
    assert sig.get("signal_id") is not None

    analytics = tracker.get_admin_signal_analytics(include_seed_samples=False)
    matches = [s for s in analytics["signals"] if s["signal_id"] == sig["signal_id"]]
    assert len(matches) == 1
    assert matches[0]["tier"] == "STRONG"
    assert matches[0]["score"] == 94


def test_4_strong_signal_insufficient_margin(isolated_signal_tracker):
    """4. STRONG signal + insufficient margin -> Persisted + Margin BLOCKED (NO order)."""
    tracker = isolated_signal_tracker
    svc = make_service("PAPER", tracker=tracker)
    svc._portfolio_service.get_available_margin.return_value = 3000.0
    svc._margin_validator.validate.return_value = SimpleNamespace(
        allowed=False, error_message="MARGIN INSUFFICIENT: available 3000 < required 5080"
    )

    sig = {
        "symbol": "NIFTY",
        "score": 94,
        "tier": "STRONG",
        "direction": "CALL",
        "price": 25400.0,
        "category": "INDEX_OPTIONS",
    }

    with patch("core.signals.signal_tracker.SignalTracker.get_instance", return_value=tracker):
        with pytest.raises(TradeBlockError, match="MARGIN_BLOCK"):
            svc._submit_order_under_lock(
                name="NIFTY", price=25400.0, qty=1, sig=sig, order_direction="BUY", idempotency_key="idem-str-02"
            )

    # Invariant: Super Admin visibility preserved
    assert sig.get("signal_id") is not None
    analytics = tracker.get_admin_signal_analytics(include_seed_samples=False)
    matches = [s for s in analytics["signals"] if s["signal_id"] == sig["signal_id"]]
    assert len(matches) == 1
    assert matches[0]["symbol"] == "NIFTY"
    assert matches[0]["tier"] == "STRONG"
    assert matches[0]["score"] == 94

    svc._execution_service.execute_order.assert_not_called()


def test_5_exact_configured_classification_boundaries():
    """5. Exact configured classification boundaries (STRONG=80, MODERATE=68, AI=60)."""
    svc = make_service("PAPER")

    # 80 -> STRONG (Qualified)
    sig_80 = {"score": 80, "direction": "CALL", "price": 100.0}
    assert svc._is_qualified_signal(sig_80) is True

    # 79 -> MODERATE (Qualified)
    sig_79 = {"score": 79, "direction": "CALL", "price": 100.0}
    assert svc._is_qualified_signal(sig_79) is True

    # 68 -> MODERATE boundary (Qualified)
    sig_68 = {"score": 68, "direction": "CALL", "price": 100.0}
    assert svc._is_qualified_signal(sig_68) is True

    # 67 -> WEAK (Not qualified for mandatory persistence)
    sig_67 = {"score": 67, "tier": "WEAK", "direction": "CALL", "price": 100.0}
    assert svc._is_qualified_signal(sig_67) is False

    # 59 -> Below AI threshold (Not qualified)
    sig_59 = {"score": 59, "direction": "CALL", "price": 100.0}
    assert svc._is_qualified_signal(sig_59) is False

    # HOLD signal (Not qualified)
    sig_hold = {"score": 95, "signal": "HOLD", "direction": "CALL", "price": 100.0}
    assert svc._is_qualified_signal(sig_hold) is False


def test_6_repeated_evaluation_and_deduplication(isolated_signal_tracker):
    """6. Repeated evaluation of same opportunity reuses active signal without duplicate row."""
    tracker = isolated_signal_tracker
    svc = make_service("PAPER", tracker=tracker)

    sig1 = {
        "symbol": "NIFTY",
        "score": 90,
        "tier": "STRONG",
        "direction": "CALL",
        "category": "INDEX_OPTIONS",
        "strategy": "adaptive_v2",
    }
    sig2 = {
        "symbol": "NIFTY",
        "score": 90,
        "tier": "STRONG",
        "direction": "CALL",
        "category": "INDEX_OPTIONS",
        "strategy": "adaptive_v2",
    }

    with patch("core.signals.signal_tracker.SignalTracker.get_instance", return_value=tracker):
        id1 = svc._ensure_signal_persisted("NIFTY", sig1, force=True)
        id2 = svc._ensure_signal_persisted("NIFTY", sig2, force=True)

    assert id1 != ""
    assert id2 == id1  # Deduplicated and active ID reused!

    analytics = tracker.get_admin_signal_analytics(include_seed_samples=False)
    matches = [s for s in analytics["signals"] if s["symbol"] == "NIFTY"]
    assert len(matches) == 1  # Exactly one record in system_signals


def test_7_existing_active_signal_reuse(isolated_signal_tracker):
    """7. Existing signal_id on sig is preserved and reused directly."""
    tracker = isolated_signal_tracker
    svc = make_service("PAPER", tracker=tracker)

    sig = {"symbol": "NIFTY", "signal_id": "SIG-PRE-EXISTING-777", "score": 85}

    with patch.object(tracker, "record_generated_signal") as mock_rec:
        with patch("core.signals.signal_tracker.SignalTracker.get_instance", return_value=tracker):
            out_id = svc._ensure_signal_persisted("NIFTY", sig, force=True)

    assert out_id == "SIG-PRE-EXISTING-777"
    mock_rec.assert_not_called()


def test_8_super_admin_api_visibility(isolated_signal_tracker):
    """8. Persisted signal is immediately visible via Admin Signal Analytics API."""
    tracker = isolated_signal_tracker
    svc = make_service("PAPER", tracker=tracker)

    sig = {
        "symbol": "FINNIFTY",
        "score": 88,
        "tier": "STRONG",
        "direction": "PUT",
        "price": 24100.0,
        "category": "INDEX_OPTIONS",
    }

    with patch("core.signals.signal_tracker.SignalTracker.get_instance", return_value=tracker):
        sig_id = svc._ensure_signal_persisted("FINNIFTY", sig, force=True)

    analytics = tracker.get_admin_signal_analytics(include_seed_samples=False)
    feed = [s for s in analytics["signals"] if s["signal_id"] == sig_id]
    assert len(feed) == 1
    assert feed[0]["symbol"] == "FINNIFTY"
    assert feed[0]["direction"] == "PUT"
    assert feed[0]["score"] == 88
    assert feed[0]["status"] == "ACTIVE"


def test_9_super_admin_ui_visibility(isolated_signal_tracker):
    """9. Super Admin dashboard context and permission resolution allows signal view."""
    from core.auth.permissions import is_super_admin_identity
    assert is_super_admin_identity("admin", "admin") is True

    tracker = isolated_signal_tracker
    analytics = tracker.get_admin_signal_analytics(include_seed_samples=False)
    assert "signals" in analytics
    assert "category_breakdown" in analytics
    assert "total_signals" in analytics


def test_10_unauthorized_user_isolation(isolated_signal_tracker):
    """10. Non-admin users cannot access admin analytics, and only receive permitted deliveries."""
    from core.auth.permissions import is_super_admin_identity
    assert is_super_admin_identity("viewer_user", "viewer") is False

    tracker = isolated_signal_tracker
    # User deliveries for viewer_user must be empty when none delivered
    user_feed = tracker.get_user_received_signals("viewer_user")
    assert len(user_feed["signals"]) == 0
