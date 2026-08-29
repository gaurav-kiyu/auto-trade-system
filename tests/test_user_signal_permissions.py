"""Tests for User Signal Permissions & Multi-Timeframe Quota Control (v3.0)."""

import pytest
from core.auth.user_signal_permissions import UserPermissionManager


@pytest.fixture
def temp_perm_manager(tmp_path):
    store_file = tmp_path / "test_user_permissions.json"
    mgr = UserPermissionManager(store_path=store_file)
    return mgr


def test_seed_and_list_permissions(temp_perm_manager):
    mgr = temp_perm_manager
    perms = mgr.list_all_permissions()
    assert len(perms) >= 1
    admin_p = [p for p in perms if p["username"] == "admin"][0]
    assert admin_p["signals_enabled"] is True
    assert admin_p["role"] == "admin"
    assert "INDEX_OPTIONS" in admin_p["allowed_categories"]
    assert "PENNY_SME" in admin_p["allowed_categories"]


def test_update_user_permissions(temp_perm_manager):
    mgr = temp_perm_manager
    ok, msg, created = mgr.update_user_permissions(
        "trader_bob",
        {
            "display_name": "Bob Trader",
            "role": "viewer",
            "signals_enabled": True,
            "allowed_categories": ["PENNY_SME", "COMMODITIES"],
            "min_signal_tier": "STRONG_ONLY",
            "max_signals_daily": 5,
            "max_signals_weekly": 20,
            "max_signals_monthly": 80,
            "telegram_enabled": True,
            "telegram_chat_id": "999888777",
            "email_enabled": True,
            "email": "bob@trading.com",
        },
        admin_username="admin",
    )
    assert ok is True
    assert created["username"] == "trader_bob"
    assert created["allowed_categories"] == ["PENNY_SME", "COMMODITIES"]
    assert created["max_signals_daily"] == 5

    # Retrieve permissions
    perm = mgr.get_user_permissions("trader_bob")
    assert perm is not None
    assert perm.display_name == "Bob Trader"
    assert perm.min_signal_tier == "STRONG_ONLY"


def test_one_click_toggle_signals(temp_perm_manager):
    mgr = temp_perm_manager
    mgr.update_user_permissions("alice", {"signals_enabled": True}, admin_username="admin")

    # Toggle OFF
    ok, msg, state = mgr.toggle_user_signals("alice", admin_username="admin")
    assert ok is True
    assert state is False
    assert mgr.get_user_permissions("alice").signals_enabled is False

    # Toggle ON
    ok, msg, state = mgr.toggle_user_signals("alice", admin_username="admin")
    assert ok is True
    assert state is True
    assert mgr.get_user_permissions("alice").signals_enabled is True


def test_eligible_recipients_category_filtering(temp_perm_manager):
    mgr = temp_perm_manager
    # User 1: Only Penny & SME
    mgr.update_user_permissions(
        "penny_trader",
        {
            "signals_enabled": True,
            "allowed_categories": ["PENNY_SME"],
            "min_signal_tier": "MODERATE_AND_STRONG",
            "max_signals_daily": 10,
        },
        admin_username="admin",
    )
    # User 2: Only Index Options
    mgr.update_user_permissions(
        "index_trader",
        {
            "signals_enabled": True,
            "allowed_categories": ["INDEX_OPTIONS"],
            "min_signal_tier": "MODERATE_AND_STRONG",
            "max_signals_daily": 10,
        },
        admin_username="admin",
    )

    # 1. Send PENNY_SME signal
    penny_recipients = mgr.get_eligible_recipients(category="PENNY_SME", tier="STRONG")
    penny_unames = [u.username for u in penny_recipients]
    assert "penny_trader" in penny_unames
    assert "index_trader" not in penny_unames

    # 2. Send INDEX_OPTIONS signal
    index_recipients = mgr.get_eligible_recipients(category="INDEX_OPTIONS", tier="STRONG")
    index_unames = [u.username for u in index_recipients]
    assert "index_trader" in index_unames
    assert "penny_trader" not in index_unames


def test_eligible_recipients_tier_filtering(temp_perm_manager):
    mgr = temp_perm_manager
    # Strong only trader
    mgr.update_user_permissions(
        "vip_trader",
        {
            "signals_enabled": True,
            "allowed_categories": ["INDEX_OPTIONS"],
            "min_signal_tier": "STRONG_ONLY",
            "max_signals_daily": 10,
        },
        admin_username="admin",
    )

    # Moderate signal should NOT be delivered to vip_trader
    mod_recipients = mgr.get_eligible_recipients(category="INDEX_OPTIONS", tier="MODERATE")
    mod_unames = [u.username for u in mod_recipients]
    assert "vip_trader" not in mod_unames

    # Strong signal SHOULD be delivered
    strong_recipients = mgr.get_eligible_recipients(category="INDEX_OPTIONS", tier="STRONG")
    strong_unames = [u.username for u in strong_recipients]
    assert "vip_trader" in strong_unames


def test_multi_timeframe_quota_enforcement(temp_perm_manager):
    mgr = temp_perm_manager
    mgr.update_user_permissions(
        "quota_trader",
        {
            "signals_enabled": True,
            "allowed_categories": ["LARGE_CAP_EQUITY"],
            "min_signal_tier": "MODERATE_AND_STRONG",
            "max_signals_daily": 2,  # Limit is 2 signals per day
            "max_signals_weekly": 10,
            "max_signals_monthly": 30,
        },
        admin_username="admin",
    )

    # 1st signal: allowed
    r1 = mgr.get_eligible_recipients(category="LARGE_CAP_EQUITY", tier="STRONG")
    assert "quota_trader" in [u.username for u in r1]

    # 2nd signal: allowed
    r2 = mgr.get_eligible_recipients(category="LARGE_CAP_EQUITY", tier="STRONG")
    assert "quota_trader" in [u.username for u in r2]

    # 3rd signal: quota exceeded, blocked!
    r3 = mgr.get_eligible_recipients(category="LARGE_CAP_EQUITY", tier="STRONG")
    assert "quota_trader" not in [u.username for u in r3]

    # Check quota counters
    p = mgr.get_user_permissions("quota_trader")
    assert p.daily_signals_used == 2
    assert p.weekly_signals_used == 2
    assert p.monthly_signals_used == 2


def test_registration_wires_email_and_telegram_via_update(temp_perm_manager):
    """Mirror the auth/routes.py register flow: channels are saved via update_user_permissions."""
    mgr = temp_perm_manager
    ok, msg, created = mgr.update_user_permissions(
        "web_user",
        {
            "display_name": "Web User",
            "role": "viewer",
            "email": "web@trading.com",
            "email_enabled": True,
            "telegram_chat_id": "555444333",
            "telegram_enabled": True,
        },
        admin_username="self-register",
    )
    assert ok is True
    perm = mgr.get_user_permissions("web_user")
    assert perm is not None
    assert perm.email == "web@trading.com"
    assert perm.email_enabled is True
    assert perm.telegram_chat_id == "555444333"
    assert perm.telegram_enabled is True

    recipients = mgr.get_eligible_recipients(category="INDEX_OPTIONS", tier="STRONG")
    assert "web_user" in [u.username for u in recipients]


def test_admin_create_user_wires_channels_and_role(temp_perm_manager):
    """Mirror the auth/routes.py admin create_user flow: role + channels persisted."""
    mgr = temp_perm_manager
    ok, msg, created = mgr.update_user_permissions(
        "ops_user",
        {
            "display_name": "Ops User",
            "role": "operator",
            "email": "ops@trading.com",
            "email_enabled": True,
        },
        admin_username="admin",
    )
    assert ok is True
    perm = mgr.get_user_permissions("ops_user")
    assert perm is not None
    assert perm.role == "operator"
    assert perm.email == "ops@trading.com"
    assert perm.email_enabled is True
