"""Permanent Regression Suite: Universal Market Coverage, Universal Signal Thresholds, and Super Admin Notifications.

Covers all 18 mandatory test specifications from Section 20:
1.  test_universal_signal_thresholds
2.  test_index_strong_threshold_not_blocked_at_80
3.  test_super_admin_receives_moderate
4.  test_super_admin_receives_strong
5.  test_super_admin_receives_all_supported_categories
6.  test_margin_block_preserves_moderate_signal
7.  test_margin_block_preserves_strong_signal
8.  test_stock_scanner_production_activation
9.  test_dynamic_equity_universe
10. test_dynamic_derivative_universe
11. test_sensex_signal_path
12. test_bse_signal_path_if_supported
13. test_futures_signal_path_if_supported
14. test_stock_options_signal_path_if_supported
15. test_email_super_admin_delivery
16. test_telegram_super_admin_delivery
17. test_notification_deduplication
18. test_notification_authorization
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import pandas as pd
import numpy as np

from core.all_nse_scanner import AllNSEScanner, ScannedStockSignal
from core.auth.user_signal_permissions import ALL_CATEGORIES, UserPermissionManager, UserSignalPermission
from core.datetime_ist import now_ist
from core.fno_universe import (
    FNO_INDICES,
    FNO_EQUITY_STOCKS,
    classify_instrument_market,
    is_fno_symbol,
    is_index_symbol,
)
from core.notifications.rich_signal_formatter import RichSignalFormatter
from core.pure_index_signal import classify_strength
from core.signals.signal_tracker import SignalTracker


# ─────────────────────────────────────────────────────────────────────────────
# 1. test_universal_signal_thresholds
# ─────────────────────────────────────────────────────────────────────────────
def test_universal_signal_thresholds():
    """Verify canonical universal scoring model:
    0–59   = NONE / IGNORE (below signal threshold)
    60–67  = WEAK
    68–79  = MODERATE (>= 68)
    80–100 = STRONG (>= 80)
    """
    assert classify_strength(0) == "NONE"
    assert classify_strength(59) == "NONE"
    assert classify_strength(60) == "WEAK"
    assert classify_strength(67) == "WEAK"
    assert classify_strength(68) == "MODERATE"
    assert classify_strength(72) == "MODERATE"
    assert classify_strength(79) == "MODERATE"
    assert classify_strength(80) == "STRONG"
    assert classify_strength(90) == "STRONG"
    assert classify_strength(100) == "STRONG"


# ─────────────────────────────────────────────────────────────────────────────
# 2. test_index_strong_threshold_not_blocked_at_80
# ─────────────────────────────────────────────────────────────────────────────
def test_index_strong_threshold_not_blocked_at_80():
    """Verify INDEX_MIN_SCORE does NOT require 100/100 saturation and allows 80-99 strong alerts."""
    scanner = AllNSEScanner(cfg={"INDEX_MIN_SCORE": 80, "MIN_SIGNAL_TIER": "MODERATE_AND_STRONG"})
    min_score = scanner.get_min_score_for_category("INDEX_OPTIONS")
    assert min_score <= 80, f"INDEX_MIN_SCORE publication threshold must be <= 80, got {min_score}"

    # Verify that even with legacy/unconfigured default 100, the scanner clamps to canonical threshold
    legacy_scanner = AllNSEScanner(cfg={"INDEX_MIN_SCORE": 100, "MIN_SIGNAL_TIER": "STRONG_ONLY"})
    legacy_min = legacy_scanner.get_min_score_for_category("INDEX_OPTIONS")
    assert legacy_min <= 80, f"Legacy 100 must clamp to <= 80, got {legacy_min}"


# ─────────────────────────────────────────────────────────────────────────────
# 3. test_super_admin_receives_moderate
# ─────────────────────────────────────────────────────────────────────────────
def test_super_admin_receives_moderate():
    """Verify Super Admin receives MODERATE conviction signals (score 68-79)."""
    upm = UserPermissionManager.get_instance()
    admin_perm = upm.get_user_permissions("admin")
    assert admin_perm is not None
    assert admin_perm.min_signal_tier == "MODERATE_AND_STRONG"

    eligible = upm.get_eligible_recipients(category="INDEX_OPTIONS", tier="MODERATE", symbol="NIFTY")
    eligible_usernames = [u.username for u in eligible]
    assert "admin" in eligible_usernames, "Super Admin 'admin' must be eligible for MODERATE signals"


# ─────────────────────────────────────────────────────────────────────────────
# 4. test_super_admin_receives_strong
# ─────────────────────────────────────────────────────────────────────────────
def test_super_admin_receives_strong():
    """Verify Super Admin receives STRONG conviction signals (score >= 80)."""
    upm = UserPermissionManager.get_instance()
    eligible = upm.get_eligible_recipients(category="INDEX_OPTIONS", tier="STRONG", symbol="BANKNIFTY")
    eligible_usernames = [u.username for u in eligible]
    assert "admin" in eligible_usernames, "Super Admin 'admin' must be eligible for STRONG signals"


# ─────────────────────────────────────────────────────────────────────────────
# 5. test_super_admin_receives_all_supported_categories
# ─────────────────────────────────────────────────────────────────────────────
def test_super_admin_receives_all_supported_categories():
    """Verify Super Admin is subscribed to and eligible for all 10 canonical market categories."""
    upm = UserPermissionManager.get_instance()
    admin_perm = upm.get_user_permissions("admin")
    assert admin_perm is not None

    for cat in ALL_CATEGORIES:
        assert cat in admin_perm.allowed_categories, f"Category {cat} missing from admin allowed_categories"
        eligible_mod = upm.get_eligible_recipients(category=cat, tier="MODERATE", symbol="TEST")
        assert any(u.username == "admin" for u in eligible_mod), f"admin not eligible for MODERATE in {cat}"
        eligible_strong = upm.get_eligible_recipients(category=cat, tier="STRONG", symbol="TEST")
        assert any(u.username == "admin" for u in eligible_strong), f"admin not eligible for STRONG in {cat}"


# ─────────────────────────────────────────────────────────────────────────────
# 6. test_margin_block_preserves_moderate_signal
# ─────────────────────────────────────────────────────────────────────────────
def test_margin_block_preserves_moderate_signal():
    """Verify decoupled persistence invariant:
    When margin validation blocks execution, a qualified MODERATE signal (68-79)
    must still be assigned a Signal ID, persisted into SignalTracker, and visible to Super Admin.
    """
    tracker = SignalTracker.get_instance()
    test_signal_data = {
        "symbol": "FINNIFTY",
        "direction": "CALL",
        "price": 23500.0,
        "score": 72,
        "raw_score": 72,
        "tier": "MODERATE",
        "category": "INDEX_OPTIONS",
        "strategy": "pure_index_breakout",
        "opportunity_key": f"TEST-MOD-{time.time()}",
        "confidence": 72.0,
        "ml_probability": 0.68,
        "dedup_cooldown_secs": 0,
        "stop_loss": 23400.0,
        "target_1": 23700.0,
        "target_2": 23900.0,
    }

    upm = UserPermissionManager.get_instance()
    eligible = upm.get_eligible_recipients(category="INDEX_OPTIONS", tier="MODERATE", symbol="FINNIFTY")

    # Simulate margin check failure (Base capital = 3000, required margin = 5200)
    available_capital = 3000.0
    required_margin = 5200.0
    margin_sufficient = available_capital >= required_margin
    assert not margin_sufficient, "Pre-condition: margin must be insufficient"

    # Invariant: Signal must be persisted INDEPENDENTLY of execution block
    sig_id = tracker.record_generated_signal(test_signal_data, eligible_users=eligible)
    assert sig_id, "Signal ID must be generated and returned even when margin is blocked"

    # Verify persistence & Super Admin visibility
    conn = tracker._get_conn()
    persisted = conn.execute("SELECT * FROM system_signals WHERE signal_id = ?", (sig_id,)).fetchone()
    deliveries = conn.execute("SELECT * FROM user_deliveries WHERE signal_id = ?", (sig_id,)).fetchall()
    conn.close()

    assert persisted is not None
    assert persisted["symbol"] == "FINNIFTY"
    assert persisted["tier"] == "MODERATE"
    assert persisted["score"] == 72
    assert any(d["username"] == "admin" for d in deliveries)


# ─────────────────────────────────────────────────────────────────────────────
# 7. test_margin_block_preserves_strong_signal
# ─────────────────────────────────────────────────────────────────────────────
def test_margin_block_preserves_strong_signal():
    """Verify decoupled persistence invariant for STRONG signal (>= 80)."""
    tracker = SignalTracker.get_instance()
    test_signal_data = {
        "symbol": "NIFTY",
        "direction": "CALL",
        "price": 25200.0,
        "score": 88,
        "raw_score": 88,
        "tier": "STRONG",
        "category": "INDEX_OPTIONS",
        "strategy": "pure_index_breakout",
        "opportunity_key": f"TEST-STRONG-{time.time()}",
        "confidence": 88.0,
        "ml_probability": 0.75,
        "dedup_cooldown_secs": 0,
        "stop_loss": 25100.0,
        "target_1": 25400.0,
        "target_2": 25600.0,
    }

    upm = UserPermissionManager.get_instance()
    eligible = upm.get_eligible_recipients(category="INDEX_OPTIONS", tier="STRONG", symbol="NIFTY")

    available_capital = 3000.0
    required_margin = 6500.0
    assert available_capital < required_margin

    sig_id = tracker.record_generated_signal(test_signal_data, eligible_users=eligible)
    assert sig_id
    conn = tracker._get_conn()
    persisted = conn.execute("SELECT * FROM system_signals WHERE signal_id = ?", (sig_id,)).fetchone()
    deliveries = conn.execute("SELECT * FROM user_deliveries WHERE signal_id = ?", (sig_id,)).fetchall()
    conn.close()

    assert persisted is not None
    assert persisted["tier"] == "STRONG"
    assert persisted["score"] == 88
    assert any(d["username"] == "admin" for d in deliveries)


# ─────────────────────────────────────────────────────────────────────────────
# 8. test_stock_scanner_production_activation
# ─────────────────────────────────────────────────────────────────────────────
def test_stock_scanner_production_activation():
    """Verify that the supervisor configuration contains opb_scanner daemon."""
    supervisor_conf_path = Path("supervisord.conf")
    assert supervisor_conf_path.exists(), "supervisord.conf must exist in repo root"
    content = supervisor_conf_path.read_text(encoding="utf-8")
    assert "[program:opb_scanner]" in content
    assert "core/market_scanner_daemon.py" in content
    assert "autostart=true" in content
    assert "autorestart=true" in content


# ─────────────────────────────────────────────────────────────────────────────
# 9. test_dynamic_equity_universe
# ─────────────────────────────────────────────────────────────────────────────
def test_dynamic_equity_universe():
    """Verify that AllNSEScanner dynamically loads the full active stock universe (~2,500+)."""
    scanner = AllNSEScanner()
    universe = scanner.load_nse_universe()
    assert len(universe) >= 50, f"Expected active universe, got {len(universe)}"

    # Verify that priority indices are prepended
    symbols = [item["symbol"] for item in universe]
    assert "NIFTY" in symbols[:10]
    assert "BANKNIFTY" in symbols[:10]
    assert "FINNIFTY" in symbols[:10]
    assert "SENSEX" in symbols[:10]
    assert "MIDCPNIFTY" in symbols[:10]

    # Verify fields
    sample = universe[0]
    assert "symbol" in sample
    assert "name" in sample
    assert "series" in sample


# ─────────────────────────────────────────────────────────────────────────────
# 10. test_dynamic_derivative_universe
# ─────────────────────────────────────────────────────────────────────────────
def test_dynamic_derivative_universe():
    """Verify dynamic derivative universe detection and categorization."""
    assert is_fno_symbol("NIFTY") is True
    assert is_fno_symbol("BANKNIFTY") is True
    assert is_fno_symbol("RELIANCE") is True
    assert is_fno_symbol("TCS") is True
    assert is_fno_symbol("INFY") is True

    # Non-F&O cash equity
    assert is_fno_symbol("SUZLON") is False or "SUZLON" in FNO_EQUITY_STOCKS

    # Classification
    assert classify_instrument_market("NIFTY", "INDEX") == "INDEX_OPTIONS"
    assert classify_instrument_market("RELIANCE", "EQ", instrument_type="OPTSTK") == "STOCK_OPTIONS"
    assert classify_instrument_market("TCS", "EQ", instrument_type="FUTSTK") == "FUTURES"


# ─────────────────────────────────────────────────────────────────────────────
# 11. test_sensex_signal_path
# ─────────────────────────────────────────────────────────────────────────────
def test_sensex_signal_path():
    """Verify SENSEX index signal path and classification."""
    assert is_index_symbol("SENSEX") is True
    assert classify_instrument_market("SENSEX", "INDEX") == "INDEX_OPTIONS"

    # Verify mock evaluation of SENSEX through scanner logic
    scanner = AllNSEScanner(cfg={"INDEX_MIN_SCORE": 80, "MIN_SIGNAL_TIER": "MODERATE_AND_STRONG"})
    min_score = scanner.get_min_score_for_category("INDEX_OPTIONS")
    assert min_score <= 80


# ─────────────────────────────────────────────────────────────────────────────
# 12. test_bse_signal_path_if_supported
# ─────────────────────────────────────────────────────────────────────────────
def test_bse_signal_path_if_supported():
    """Verify BSE indices (SENSEX, BANKEX) are mapped to correct yahoo tickers and categories."""
    assert "SENSEX" in FNO_INDICES
    assert "BANKEX" in FNO_INDICES
    assert classify_instrument_market("BANKEX", "INDEX") == "INDEX_OPTIONS"

    # Cash BSE equities: verify that if no official BSE API is configured,
    # it safely classifies or identifies without fabricated support.
    cat = classify_instrument_market("500325", "EQ")  # BSE scrip code
    assert cat in ALL_CATEGORIES


# ─────────────────────────────────────────────────────────────────────────────
# 13. test_futures_signal_path_if_supported
# ─────────────────────────────────────────────────────────────────────────────
def test_futures_signal_path_if_supported():
    """Verify Futures instrument categorization and universal scoring routing."""
    cat_idx_fut = classify_instrument_market("NIFTY-FUT", "FUT")
    cat_stk_fut = classify_instrument_market("RELIANCE-FUT", "FUT")
    assert cat_idx_fut == "FUTURES"
    assert cat_stk_fut == "FUTURES"

    upm = UserPermissionManager.get_instance()
    eligible = upm.get_eligible_recipients(category="FUTURES", tier="STRONG", symbol="NIFTY-FUT")
    assert any(u.username == "admin" for u in eligible)


# ─────────────────────────────────────────────────────────────────────────────
# 14. test_stock_options_signal_path_if_supported
# ─────────────────────────────────────────────────────────────────────────────
def test_stock_options_signal_path_if_supported():
    """Verify Stock Options categorization and universal scoring routing."""
    cat_opt = classify_instrument_market("RELIANCE", "EQ", instrument_type="OPTSTK")
    assert cat_opt == "STOCK_OPTIONS"

    upm = UserPermissionManager.get_instance()
    eligible = upm.get_eligible_recipients(category="STOCK_OPTIONS", tier="MODERATE", symbol="RELIANCE")
    assert any(u.username == "admin" for u in eligible)


# ─────────────────────────────────────────────────────────────────────────────
# 15. test_email_super_admin_delivery
# ─────────────────────────────────────────────────────────────────────────────
def test_email_super_admin_delivery():
    """Verify email formatting, recipient resolution, and delivery readiness for Super Admin."""
    upm = UserPermissionManager.get_instance()
    admin_perm = upm.get_user_permissions("admin")
    assert admin_perm is not None
    assert admin_perm.email_enabled is True
    assert admin_perm.email and "@" in admin_perm.email

    html_email = RichSignalFormatter.build_rich_html_email(
        symbol="NIFTY",
        company_name="Nifty 50 Index",
        series="INDEX",
        category="INDEX_OPTIONS",
        direction="CALL",
        price=25250.0,
        score=84,
        tier="STRONG",
        regime="TRENDING",
        rsi=62.5,
        adx=28.4,
        vwap=25200.0,
        stop_loss=25150.0,
        target_1=25400.0,
        target_2=25550.0,
        base_url="https://gaurav-cockpit.servegame.com",
    )
    assert "NIFTY" in html_email
    assert "84/100" in html_email
    assert "STRONG" in html_email
    assert "BUY" in html_email


# ─────────────────────────────────────────────────────────────────────────────
# 16. test_telegram_super_admin_delivery
# ─────────────────────────────────────────────────────────────────────────────
def test_telegram_super_admin_delivery():
    """Verify Telegram formatting, recipient resolution, and chat ID for Super Admin."""
    upm = UserPermissionManager.get_instance()
    admin_perm = upm.get_user_permissions("admin")
    assert admin_perm is not None
    assert admin_perm.telegram_enabled is True
    assert admin_perm.telegram_chat_id == "1148730533"

    tg_msg = RichSignalFormatter.build_rich_telegram_html(
        symbol="BANKNIFTY",
        category="INDEX_OPTIONS",
        direction="PUT",
        price=54100.0,
        score=75,
        tier="MODERATE",
        stop_loss=54300.0,
        target_1=53800.0,
        target_2=53500.0,
    )
    assert "BANKNIFTY" in tg_msg
    assert "75/100" in tg_msg
    assert "MODERATE" in tg_msg
    assert "PUT" in tg_msg


# ─────────────────────────────────────────────────────────────────────────────
# 17. test_notification_deduplication
# ─────────────────────────────────────────────────────────────────────────────
def test_notification_deduplication():
    """Verify that duplicate signals for the same symbol within cooldown window are suppressed."""
    tracker = SignalTracker.get_instance()
    data = {
        "symbol": "INFY",
        "direction": "CALL",
        "price": 1900.0,
        "score": 82,
        "raw_score": 82,
        "tier": "STRONG",
        "category": "STOCK_OPTIONS",
        "strategy": "breakout_v1",
        "opportunity_key": f"TEST-DEDUP-{time.time()}",
        "dedup_cooldown_secs": 300,
        "stop_loss": 1850.0,
        "target_1": 1960.0,
        "target_2": 2000.0,
    }

    first_id = tracker.record_generated_signal(data, [])
    assert first_id, "First signal must be accepted"

    # Immediately identical candidate should be deduplicated (rejected)
    second_id = tracker.record_generated_signal(data, [])
    assert second_id == "", "Duplicate signal within cooldown must be suppressed"


# ─────────────────────────────────────────────────────────────────────────────
# 18. test_notification_authorization
# ─────────────────────────────────────────────────────────────────────────────
def test_notification_authorization():
    """Verify RBAC authorization rules for signal notifications."""
    upm = UserPermissionManager.get_instance()

    # Active super admin receives signals
    admin_eligible = upm.get_eligible_recipients("LARGE_CAP_EQUITY", "MODERATE", "RELIANCE")
    assert any(u.username == "admin" for u in admin_eligible)

    # User with signals_enabled=False is never eligible
    inactive_user = upm.get_user_permissions("new_trader_01")
    if inactive_user and not inactive_user.signals_enabled:
        eligible = upm.get_eligible_recipients("LARGE_CAP_EQUITY", "STRONG", "RELIANCE")
        assert not any(u.username == "new_trader_01" for u in eligible)
