"""Unit tests for Signal Tracker, Admin Accuracy Analytics & User Signal History (v3.0)."""

import pytest
from core.signals.signal_tracker import SignalTracker


@pytest.fixture
def temp_signal_tracker(tmp_path):
    db_file = tmp_path / "test_signals_history.db"
    tracker = SignalTracker(db_path=db_file)
    return tracker


def test_seed_and_initial_signals(temp_signal_tracker):
    tracker = temp_signal_tracker
    analytics = tracker.get_admin_signal_analytics()
    assert analytics["total_signals"] >= 10
    assert analytics["win_rate_pct"] > 0
    assert "INDEX_OPTIONS" in analytics["category_breakdown"]
    assert "LARGE_CAP_EQUITY" in analytics["category_breakdown"]


def test_seeded_sample_signals_are_flagged_as_demo_data(temp_signal_tracker):
    """Regression: the 12 hardcoded sample signals seeded into every fresh
    install were presented with zero indication they weren't real - neither
    the admin analytics nor a user's own received-signals feed distinguished
    them from genuine delivered signals."""
    tracker = temp_signal_tracker
    analytics = tracker.get_admin_signal_analytics()
    assert analytics["contains_demo_data"] is True

    user_history = tracker.get_user_received_signals("admin")
    assert user_history["contains_demo_data"] is True
    assert all(s["is_demo_data"] for s in user_history["signals"])


def test_real_generated_signal_is_not_flagged_as_demo_data(temp_signal_tracker):
    tracker = temp_signal_tracker
    tracker.record_generated_signal(
        {"symbol": "TESTSTOCK", "category": "LARGE_CAP_EQUITY", "direction": "CALL",
         "score": 91, "tier": "STRONG", "price": 100.0, "stop_loss": 95.0,
         "target_1": 108.0, "target_2": 115.0},
        eligible_users=[type("U", (), {"username": "admin"})()],
    )
    user_history = tracker.get_user_received_signals("admin")
    real_rows = [s for s in user_history["signals"] if s["symbol"] == "TESTSTOCK"]
    assert len(real_rows) == 1
    assert real_rows[0]["is_demo_data"] is False


def test_record_generated_signal_and_user_delivery(temp_signal_tracker):
    tracker = temp_signal_tracker

    class MockUser:
        def __init__(self, uname, tg=True, em=True):
            self.username = uname
            self.telegram_enabled = tg
            self.email_enabled = em

    mock_users = [MockUser("alice_trader"), MockUser("bob_trader", tg=True, em=False)]

    sig_id = tracker.record_generated_signal({
        "symbol": "INFY",
        "company_name": "Infosys Ltd",
        "category": "LARGE_CAP_EQUITY",
        "direction": "CALL",
        "score": 94,
        "tier": "STRONG",
        "price": 1820.0,
        "stop_loss": 1765.4,
        "target_1": 1892.8,
        "target_2": 1965.6,
    }, eligible_users=mock_users)

    assert sig_id.startswith("SIG-")

    # Verify admin analytics contains the new signal
    admin_data = tracker.get_admin_signal_analytics(category="LARGE_CAP_EQUITY")
    assert any(s["symbol"] == "INFY" for s in admin_data["signals"])

    # Verify user received signal feed
    user_feed = tracker.get_user_received_signals("alice_trader")
    assert user_feed["total_received"] == 1
    assert user_feed["signals"][0]["symbol"] == "INFY"
    assert "Telegram" in user_feed["signals"][0]["channels_sent"]
    assert "Email" in user_feed["signals"][0]["channels_sent"]


def test_admin_signal_timeframe_and_category_filters(temp_signal_tracker):
    tracker = temp_signal_tracker

    # 1. Filter by category
    opt_data = tracker.get_admin_signal_analytics(category="INDEX_OPTIONS")
    assert all(s["category"] == "INDEX_OPTIONS" for s in opt_data["signals"])

    penny_data = tracker.get_admin_signal_analytics(category="PENNY_SME")
    assert all(s["category"] == "PENNY_SME" for s in penny_data["signals"])

    # 2. Filter by tier
    strong_data = tracker.get_admin_signal_analytics(tier="STRONG")
    assert all(s["tier"] == "STRONG" for s in strong_data["signals"])


def test_user_timeframe_filters(temp_signal_tracker):
    tracker = temp_signal_tracker
    res = tracker.get_user_received_signals("admin", category="INDEX_OPTIONS")
    assert res["total_received"] > 0
    assert all(s["category"] == "INDEX_OPTIONS" for s in res["signals"])
