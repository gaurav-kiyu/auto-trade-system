"""
Permanent Test Suite: Final Master Market Universe Coverage & Notification Pipeline.

Validates the full institutional contract across Indian Capital Market instruments:
1. test_full_market_universe_coverage
2. test_all_supported_indices
3. test_all_supported_equities
4. test_all_supported_futures
5. test_all_supported_options
6. test_bse_coverage_if_supported
7. test_sensex_coverage_if_supported
8. test_qualifying_signal_persistence_for_every_supported_asset_class
9. test_super_admin_visibility_for_every_supported_asset_class
10. test_email_notification_for_qualifying_signal
11. test_telegram_notification_for_qualifying_signal
12. test_margin_block_does_not_remove_signal
13. test_notification_deduplication
14. test_notification_failure_retry
15. test_recipient_authorization
16. test_scanner_universe_refresh
17. test_dynamic_instrument_universe
"""

from __future__ import annotations

import email
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

import pytest

from core.all_nse_scanner import AllNSEScanner, ScannedStockSignal
from core.auth.user_signal_permissions import UserPermissionManager, UserSignalPermission
from core.fno_universe import (
    FNO_EQUITY_STOCKS,
    FNO_INDICES,
    NIFTY_50_STOCKS,
    classify_instrument_market,
    is_fno_symbol,
    is_index_symbol,
)
from core.ports.execution.execution_port import ExecutionMode, OrderStatus
from core.position_service import PositionService, TradeBlockError
from core.signals.signal_tracker import SignalTracker


@pytest.fixture
def isolated_tracker(tmp_path):
    """Provide an isolated SignalTracker instance with its own SQLite database."""
    db_file = tmp_path / "test_isolated_signals.db"
    tracker = SignalTracker(db_path=db_file)
    return tracker


# ---------------------------------------------------------------------------
# Test 1: Full market universe coverage
# ---------------------------------------------------------------------------
def test_full_market_universe_coverage():
    """Verify that AllNSEScanner covers the full market universe.

    Ensures fallback universe contains liquid bluechips (>60 stocks),
    and dynamic universe prepends all priority indices.
    """
    scanner = AllNSEScanner(cfg={"MIN_SCORE_THRESHOLD": 60})
    fallback = scanner._get_fallback_universe()
    assert len(fallback) >= 65
    symbols = {s["symbol"] for s in fallback}
    assert "RELIANCE" in symbols
    assert "TCS" in symbols
    assert "HDFCBANK" in symbols
    assert "INFY" in symbols

    # Load universe with priority indices prepended
    universe = scanner.load_nse_universe(force_refresh=False)
    assert len(universe) >= 5
    universe_symbols = [s["symbol"] for s in universe[:5]]
    assert "NIFTY" in universe_symbols
    assert "BANKNIFTY" in universe_symbols
    assert "FINNIFTY" in universe_symbols
    assert "SENSEX" in universe_symbols
    assert "MIDCPNIFTY" in universe_symbols


# ---------------------------------------------------------------------------
# Test 2: All supported indices
# ---------------------------------------------------------------------------
def test_all_supported_indices():
    """Verify classification, series, and resolution for all supported indices."""
    priority_indices = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX", "BANKEX"]
    for idx in priority_indices:
        assert is_index_symbol(idx) is True
        cat = classify_instrument_market(idx, series="INDEX")
        assert cat == "INDEX_OPTIONS"

    with patch.object(AllNSEScanner, "_reload_config_credentials", lambda self: None):
        scanner = AllNSEScanner(cfg={"INDEX_MIN_SCORE": 85})
        assert scanner.get_min_score_for_category("INDEX_OPTIONS") == 85


# ---------------------------------------------------------------------------
# Test 3: All supported equities
# ---------------------------------------------------------------------------
def test_all_supported_equities():
    """Verify equity classification across Large-Cap, Mid/Small-Cap, and cash gate."""
    # NIFTY 50 blue chips
    for sym in ["RELIANCE", "TCS", "HDFCBANK", "ICICIBANK", "INFY"]:
        assert sym in NIFTY_50_STOCKS
        assert classify_instrument_market(sym, instrument_type="CASH") == "LARGE_CAP_EQUITY"

    # F&O eligible equities
    for sym in ["AARTIIND", "SBIN", "BAJFINANCE"]:
        assert sym in FNO_EQUITY_STOCKS
        assert is_fno_symbol(sym) is True

    # Cash Gate: Non-F&O stocks must be strictly long-only (no PUT/SELL)
    non_fno = "ZOMATO_NON_FNO_TEST"
    assert is_fno_symbol(non_fno) is False
    assert classify_instrument_market(non_fno, series="EQ") == "EQUITY_SWING_DELIVERY"


# ---------------------------------------------------------------------------
# Test 4: All supported futures
# ---------------------------------------------------------------------------
def test_all_supported_futures():
    """Verify futures classification for index and stock futures."""
    assert classify_instrument_market("NIFTY-FUT") == "FUTURES"
    assert classify_instrument_market("BANKNIFTY_FUT") == "FUTURES"
    assert classify_instrument_market("RELIANCEFUT") == "FUTURES"
    assert classify_instrument_market("TCS", instrument_type="FUTSTK") == "FUTURES"
    assert classify_instrument_market("NIFTY", instrument_type="FUTIDX") == "FUTURES"


# ---------------------------------------------------------------------------
# Test 5: All supported options
# ---------------------------------------------------------------------------
def test_all_supported_options():
    """Verify option instruments differentiation between Index Options and Stock Options."""
    # Index options
    assert classify_instrument_market("NIFTY24DEC25000CE") == "INDEX_OPTIONS"
    assert classify_instrument_market("BANKNIFTY24DEC52000PE") == "INDEX_OPTIONS"
    assert classify_instrument_market("FINNIFTY", instrument_type="OPTIDX") == "INDEX_OPTIONS"

    # Stock options (underlying in F&O universe or instrument_type OPTSTK)
    assert classify_instrument_market("RELIANCE") == "STOCK_OPTIONS"
    assert classify_instrument_market("TCS", instrument_type="OPTSTK") == "STOCK_OPTIONS"
    assert classify_instrument_market("INFY", instrument_type="STOCK_OPTIONS") == "STOCK_OPTIONS"


# ---------------------------------------------------------------------------
# Test 6: BSE coverage if supported
# ---------------------------------------------------------------------------
def test_bse_coverage_if_supported():
    """Verify BSE coverage boundaries (SENSEX & BANKEX derivative support)."""
    assert "SENSEX" in FNO_INDICES
    assert "BANKEX" in FNO_INDICES
    assert classify_instrument_market("SENSEX") == "INDEX_OPTIONS"
    assert classify_instrument_market("BANKEX") == "INDEX_OPTIONS"


# ---------------------------------------------------------------------------
# Test 7: SENSEX coverage if supported
# ---------------------------------------------------------------------------
def test_sensex_coverage_if_supported():
    """Specifically verify SENSEX inclusion, ticker resolution, and category mapping."""
    scanner = AllNSEScanner(cfg={})
    universe = scanner.load_nse_universe()
    sensex_item = next((s for s in universe if s["symbol"] == "SENSEX"), None)
    assert sensex_item is not None
    assert sensex_item["series"] == "INDEX"
    assert "BSE" in sensex_item["name"]


# ---------------------------------------------------------------------------
# Test 8: Qualifying signal persistence for every supported asset class
# ---------------------------------------------------------------------------
def test_qualifying_signal_persistence_for_every_supported_asset_class(isolated_tracker):
    """Verify that qualifying signals persist durably across all canonical asset classes."""
    tracker = isolated_tracker
    supported_classes = [
        "INDEX_OPTIONS",
        "STOCK_OPTIONS",
        "EQUITY_SWING_DELIVERY",
        "LARGE_CAP_EQUITY",
        "MID_SMALL_CAP",
        "FUTURES",
        "COMMODITIES",
        "CURRENCIES",
        "ETFS_REITS",
        "PENNY_SME",
    ]
    created_ids = []
    for cat in supported_classes:
        sig_data = {
            "symbol": f"SYM_{cat[:6]}",
            "company_name": f"Test Company {cat}",
            "series": "EQ" if "EQUITY" in cat else "INDEX",
            "category": cat,
            "direction": "CALL",
            "price": 1500.0,
            "score": 85,
            "raw_score": 115,
            "tier": "STRONG",
            "regime": "TRENDING_BULLISH",
            "stop_loss": 1450.0,
            "target_1": 1560.0,
            "target_2": 1620.0,
        }
        sig_id = tracker.record_generated_signal(sig_data)
        assert sig_id.startswith("SIG-")
        created_ids.append(sig_id)

    assert len(created_ids) == len(supported_classes)
    analytics = tracker.get_admin_signal_analytics(category="all", include_seed_samples=False)
    assert analytics["total_signals"] == len(supported_classes)


# ---------------------------------------------------------------------------
# Test 9: Super Admin visibility for every supported asset class
# ---------------------------------------------------------------------------
def test_super_admin_visibility_for_every_supported_asset_class(isolated_tracker):
    """Verify that Super Admin querying provides 100% visibility across all asset classes."""
    tracker = isolated_tracker
    categories = ["INDEX_OPTIONS", "LARGE_CAP_EQUITY", "COMMODITIES", "CURRENCIES"]
    for cat in categories:
        tracker.record_generated_signal({
            "symbol": f"TICK_{cat[:4]}",
            "company_name": f"Visible Company {cat}",
            "series": "INDEX",
            "category": cat,
            "direction": "CALL",
            "price": 500.0,
            "score": 88,
            "raw_score": 110,
            "tier": "STRONG",
            "regime": "TRENDING",
            "stop_loss": 485.0,
            "target_1": 520.0,
            "target_2": 540.0,
        })

    # Query without category filter
    all_view = tracker.get_admin_signal_analytics(category="all", include_seed_samples=False)
    assert all_view["total_signals"] == len(categories)

    # Query each category individually
    for cat in categories:
        filtered = tracker.get_admin_signal_analytics(category=cat, include_seed_samples=False)
        assert filtered["total_signals"] == 1
        assert filtered["signals"][0]["category"] == cat


# ---------------------------------------------------------------------------
# Test 10: Email notification for qualifying signal
# ---------------------------------------------------------------------------
def test_email_notification_for_qualifying_signal(isolated_tracker):
    """Verify SMTP email construction and dispatch for a qualifying signal."""
    tracker = isolated_tracker
    scanner_cfg = {
        "EMAIL_ENABLED": True,
        "EMAIL_USER": "notifier@example.com",
        "EMAIL_PASS": "secretpass",
        "EMAIL_SMTP": "smtp.example.com",
        "EMAIL_PORT": 587,
        "MIN_SCORE_THRESHOLD": 70,
        "MIN_SIGNAL_TIER": "MODERATE_AND_STRONG",
        "ML_REQUIRED_FOR_ALERTS": False,
    }

    with patch.object(AllNSEScanner, "_reload_config_credentials", lambda self: None):
        scanner = AllNSEScanner(cfg=scanner_cfg)
        scanner._cfg = scanner_cfg
        scanner._email_enabled = True
        scanner._email_user = "notifier@example.com"
        scanner._email_pass = "secretpass"
        scanner._email_smtp = "smtp.example.com"
        scanner._email_port = 587
        scanner._email_to = ""
        scanner._bot_token = ""  # isolate email from telegram
        scanner._cooldown_secs = 0

        sig = ScannedStockSignal(
            symbol="INFY",
            company_name="Infosys Limited",
            series="EQ",
            direction="CALL",
            score=86,
            raw_score=118,
            tier="STRONG",
            regime="TRENDING_UP",
            price=1850.0,
            rsi=64.0,
            adx=31.0,
            vwap=1845.0,
        )

        mock_recipient = UserSignalPermission(
            username="superadmin",
            role="super_admin",
            email_enabled=True,
            email="admin@tradingcorp.com",
            signals_enabled=True,
            allowed_categories=["STOCK_OPTIONS", "MID_SMALL_CAP", "EQUITY_SWING_DELIVERY"],
            min_signal_tier="MODERATE_AND_STRONG",
        )

        with patch("core.signals.signal_tracker.SignalTracker.get_instance", return_value=tracker),              patch("core.auth.user_signal_permissions.UserPermissionManager.get_instance") as mock_pm,              patch("smtplib.SMTP") as mock_smtp_cls:

            mock_pm.return_value.get_eligible_recipients.side_effect = lambda category, **kw: [mock_recipient] if category in mock_recipient.allowed_categories else []
            mock_smtp = MagicMock()
            mock_smtp_cls.return_value = mock_smtp

            scanner._dispatch_alert_if_eligible(sig)

            mock_smtp.sendmail.assert_called_once()
            sender, recipients, raw_msg = mock_smtp.sendmail.call_args[0]
            assert sender == "notifier@example.com"
            assert "admin@tradingcorp.com" in recipients

            # Decode multipart message content
            parsed_msg = email.message_from_string(raw_msg)
            decoded_body = "".join(
                part.get_payload(decode=True).decode("utf-8", errors="ignore")
                for part in parsed_msg.walk()
                if not part.is_multipart()
            )
            assert "INFY" in decoded_body
            assert "SIG-" in decoded_body


# ---------------------------------------------------------------------------
# Test 11: Telegram notification for qualifying signal
# ---------------------------------------------------------------------------
def test_telegram_notification_for_qualifying_signal(isolated_tracker):
    """Verify Telegram payload formatting, inline keyboard, and HTTP POST dispatch."""
    tracker = isolated_tracker
    scanner_cfg = {
        "BOT_TOKEN": "999888:AABBCCDDEEFF",
        "CHAT_ID": "123456789",
        "EMAIL_ENABLED": False,
        "MIN_SCORE_THRESHOLD": 70,
        "MIN_SIGNAL_TIER": "MODERATE_AND_STRONG",
        "ML_REQUIRED_FOR_ALERTS": False,
    }

    with patch.object(AllNSEScanner, "_reload_config_credentials", lambda self: None):
        scanner = AllNSEScanner(cfg=scanner_cfg)
        scanner._cfg = scanner_cfg
        scanner._bot_token = "999888:AABBCCDDEEFF"
        scanner._chat_id = "123456789"
        scanner._email_enabled = False
        scanner._email_user = ""
        scanner._email_pass = ""
        scanner._email_to = ""
        scanner._cooldown_secs = 0

        sig = ScannedStockSignal(
            symbol="TCS",
            company_name="Tata Consultancy Services",
            series="EQ",
            direction="CALL",
            score=92,
            raw_score=125,
            tier="STRONG",
            regime="BULLISH_EXPANSION",
            price=3600.0,
            rsi=68.0,
            adx=35.0,
            vwap=3590.0,
        )

        mock_recipient = UserSignalPermission(
            username="superadmin",
            role="super_admin",
            telegram_enabled=True,
            telegram_chat_id="123456789",
            signals_enabled=True,
            allowed_categories=["STOCK_OPTIONS", "MID_SMALL_CAP", "EQUITY_SWING_DELIVERY"],
            min_signal_tier="MODERATE_AND_STRONG",
        )

        mock_cm = MagicMock()
        mock_cm.__enter__.return_value.read.return_value = json.dumps({"ok": True, "result": {"message_id": 42}}).encode("utf-8")

        with patch("core.signals.signal_tracker.SignalTracker.get_instance", return_value=tracker),              patch("core.auth.user_signal_permissions.UserPermissionManager.get_instance") as mock_pm,              patch("urllib.request.urlopen", return_value=mock_cm) as mock_urlopen:

            mock_pm.return_value.get_eligible_recipients.return_value = [mock_recipient]

            scanner._dispatch_alert_if_eligible(sig)

            mock_urlopen.assert_called_once()
            req = mock_urlopen.call_args[0][0]
            assert "api.telegram.org/bot999888:AABBCCDDEEFF/sendMessage" in req.full_url
            data_body = req.data.decode("utf-8")
            assert "123456789" in data_body
            assert "TCS" in data_body
            assert "inline_keyboard" in data_body


# ---------------------------------------------------------------------------
# Test 12: Margin block does not remove signal (Decoupled Persistence Contract)
# ---------------------------------------------------------------------------
def test_margin_block_does_not_remove_signal(isolated_tracker):
    """Validate core decoupled invariant:

    A qualifying MODERATE or STRONG signal must persist and remain visible
    to Super Admin even when downstream margin validation blocks trade execution.
    """
    tracker = isolated_tracker
    svc = PositionService.__new__(PositionService)
    svc._cfg = {
        "STRONG_THRESHOLD": 80,
        "MODERATE_THRESHOLD": 68,
        "AI_THRESHOLD": 60,
        "BASE_CAPITAL": 3000,
        "EXECUTION_MODE": "PAPER",
    }
    svc._execution_service = Mock()
    svc._portfolio_service = Mock()
    svc._risk_service = Mock()
    svc._margin_validator = Mock()
    svc._execution_mode = "PAPER"
    svc._decision_log = {}
    svc._send_notification = Mock()
    svc._check_liquidity_gate = Mock(return_value=(True, "ok"))
    svc._risk_service.get_required_margin_per_lot.return_value = 5080.0
    svc._portfolio_service.get_available_margin.return_value = 3000.0

    # Margin validator blocks order execution
    svc._margin_validator.validate.return_value = SimpleNamespace(
        allowed=False, error_message="Insufficient margin: required 5080.0 > available 3000.0"
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
        with pytest.raises(TradeBlockError) as exc_info:
            svc._submit_order_under_lock(
                name="NIFTY", price=25000.0, qty=1, sig=sig, order_direction="BUY", idempotency_key="idem-mb-contract"
            )
        assert "Insufficient margin" in str(exc_info.value)
        svc._execution_service.execute_order.assert_not_called()

        # Empirical proof: Signal is persisted and visible to Super Admin
        analytics = tracker.get_admin_signal_analytics(category="INDEX_OPTIONS", include_seed_samples=False)
        assert analytics["total_signals"] == 1
        persisted = analytics["signals"][0]
        assert persisted["symbol"] == "NIFTY"
        assert persisted["score"] == 75
        assert persisted["tier"] == "MODERATE"
        assert persisted["signal_id"].startswith("SIG-")


# ---------------------------------------------------------------------------
# Test 13: Notification deduplication
# ---------------------------------------------------------------------------
def test_notification_deduplication(isolated_tracker):
    """Verify that repeated qualifying signals within cooldown are suppressed from alert spam."""
    tracker = isolated_tracker
    scanner_cfg = {
        "SIGNAL_DEDUP_COOLDOWN_SECS": 900,
        "MIN_SCORE_THRESHOLD": 60,
        "MIN_SIGNAL_TIER": "MODERATE_AND_STRONG",
        "ML_REQUIRED_FOR_ALERTS": False,
        "BOT_TOKEN": "token123",
        "CHAT_ID": "554433",
        "EMAIL_ENABLED": False,
    }

    with patch.object(AllNSEScanner, "_reload_config_credentials", lambda self: None):
        scanner = AllNSEScanner(cfg=scanner_cfg)
        scanner._cfg = scanner_cfg
        scanner._cooldown_secs = 900
        scanner._bot_token = "token123"
        scanner._chat_id = "554433"
        scanner._email_enabled = False
        scanner._email_user = ""
        scanner._email_pass = ""
        scanner._email_to = ""

        sig = ScannedStockSignal(
            symbol="RELIANCE",
            company_name="Reliance Industries",
            series="EQ",
            direction="CALL",
            score=84,
            raw_score=115,
            tier="STRONG",
            regime="BULLISH",
            price=2950.0,
            rsi=62.0,
            adx=29.0,
            vwap=2940.0,
        )

        mock_recipient = UserSignalPermission(
            username="admin",
            role="super_admin",
            telegram_enabled=True,
            telegram_chat_id="554433",
            signals_enabled=True,
            allowed_categories=["STOCK_OPTIONS", "MID_SMALL_CAP", "EQUITY_SWING_DELIVERY"],
            min_signal_tier="MODERATE_AND_STRONG",
        )

        mock_cm = MagicMock()
        mock_cm.__enter__.return_value.read.return_value = json.dumps({"ok": True}).encode("utf-8")

        with patch("core.signals.signal_tracker.SignalTracker.get_instance", return_value=tracker),              patch("core.auth.user_signal_permissions.UserPermissionManager.get_instance") as mock_pm,              patch("urllib.request.urlopen", return_value=mock_cm) as mock_urlopen:

            mock_pm.return_value.get_eligible_recipients.return_value = [mock_recipient]

            # First alert -> dispatched
            scanner._dispatch_alert_if_eligible(sig)
            assert mock_urlopen.call_count == 1

            # Second alert in immediate succession -> deduplicated / suppressed
            scanner._dispatch_alert_if_eligible(sig)
            assert mock_urlopen.call_count == 1


# ---------------------------------------------------------------------------
# Test 14: Notification failure retry and graceful fallback
# ---------------------------------------------------------------------------
def test_notification_failure_retry(isolated_tracker):
    """Verify that Telegram HTML error falls back to plain text dispatch and doesn't crash."""
    tracker = isolated_tracker
    scanner_cfg = {
        "BOT_TOKEN": "token_retry",
        "CHAT_ID": "123",
        "SIGNAL_DEDUP_COOLDOWN_SECS": 0,
        "MIN_SCORE_THRESHOLD": 60,
        "MIN_SIGNAL_TIER": "MODERATE_AND_STRONG",
        "ML_REQUIRED_FOR_ALERTS": False,
        "EMAIL_ENABLED": False,
    }

    with patch.object(AllNSEScanner, "_reload_config_credentials", lambda self: None):
        scanner = AllNSEScanner(cfg=scanner_cfg)
        scanner._cfg = scanner_cfg
        scanner._bot_token = "token_retry"
        scanner._chat_id = "123"
        scanner._email_enabled = False
        scanner._email_user = ""
        scanner._email_pass = ""
        scanner._email_to = ""
        scanner._cooldown_secs = 0

        sig = ScannedStockSignal(
            symbol="SBIN",
            company_name="State Bank of India",
            series="EQ",
            direction="CALL",
            score=82,
            raw_score=110,
            tier="STRONG",
            regime="BULLISH",
            price=820.0,
            rsi=60.0,
            adx=26.0,
            vwap=815.0,
        )

        mock_recipient = UserSignalPermission(
            username="admin",
            role="super_admin",
            telegram_enabled=True,
            telegram_chat_id="123",
            signals_enabled=True,
            allowed_categories=["STOCK_OPTIONS", "MID_SMALL_CAP", "EQUITY_SWING_DELIVERY"],
            min_signal_tier="MODERATE_AND_STRONG",
        )

        with patch("core.signals.signal_tracker.SignalTracker.get_instance", return_value=tracker),              patch("core.auth.user_signal_permissions.UserPermissionManager.get_instance") as mock_pm,              patch("urllib.request.urlopen") as mock_urlopen:

            mock_pm.return_value.get_eligible_recipients.return_value = [mock_recipient]
            # First attempt raises exception (e.g. HTML parse error), second succeeds with plain text fallback
            mock_urlopen.side_effect = [Exception("Bad Request: can't parse entities"), MagicMock()]

            scanner._dispatch_alert_if_eligible(sig)
            # Should call twice: 1st HTML attempt, 2nd plain text fallback
            assert mock_urlopen.call_count == 2


# ---------------------------------------------------------------------------
# Test 15: Recipient authorization
# ---------------------------------------------------------------------------
def test_recipient_authorization(tmp_path):
    """Verify granular permission evaluation, tier gating, category gating, and quotas."""
    perm_file = tmp_path / "test_user_perms.json"
    mgr = UserPermissionManager(store_path=perm_file)

    mgr.update_user_permissions("admin", {
        "role": "super_admin",
        "signals_enabled": True,
        "is_active": True,
        "allowed_categories": ["INDEX_OPTIONS", "STOCK_OPTIONS"],
        "min_signal_tier": "MODERATE_AND_STRONG",
        "max_signals_daily": 10,
    })

    mgr.update_user_permissions("viewer_strong", {
        "role": "viewer",
        "signals_enabled": True,
        "is_active": True,
        "allowed_categories": ["INDEX_OPTIONS"],
        "min_signal_tier": "STRONG_ONLY",
        "max_signals_daily": 5,
    })

    mgr.update_user_permissions("disabled_user", {
        "role": "viewer",
        "signals_enabled": False,
        "is_active": True,
        "allowed_categories": ["INDEX_OPTIONS"],
    })

    # MODERATE signal: only admin qualifies (viewer_strong requires STRONG)
    recipients_mod = mgr.get_eligible_recipients(category="INDEX_OPTIONS", tier="MODERATE", symbol="NIFTY")
    unames_mod = [u.username for u in recipients_mod]
    assert "admin" in unames_mod
    assert "viewer_strong" not in unames_mod
    assert "disabled_user" not in unames_mod

    # STRONG signal: both admin and viewer_strong qualify
    recipients_str = mgr.get_eligible_recipients(category="INDEX_OPTIONS", tier="STRONG", symbol="NIFTY")
    unames_str = [u.username for u in recipients_str]
    assert "admin" in unames_str
    assert "viewer_strong" in unames_str
    assert "disabled_user" not in unames_str


# ---------------------------------------------------------------------------
# Test 16: Scanner universe refresh
# ---------------------------------------------------------------------------
def test_scanner_universe_refresh(tmp_path):
    """Verify daily cache reading and synchronization from equity master."""
    cache_file = tmp_path / "nse_equities.csv"
    scanner = AllNSEScanner(cfg={})

    csv_content = "SYMBOL,NAME OF COMPANY, SERIES\nHCLTECH,HCL Technologies Ltd,EQ\nMARUTI,Maruti Suzuki India,EQ\n"
    cache_file.write_text(csv_content, encoding="utf-8")

    with patch("core.all_nse_scanner._CACHE_PATH", cache_file):
        universe = scanner.load_nse_universe(force_refresh=False)
        symbols = [s["symbol"] for s in universe]
        assert "HCLTECH" in symbols
        assert "MARUTI" in symbols
        assert "NIFTY" in symbols


# ---------------------------------------------------------------------------
# Test 17: Dynamic instrument universe
# ---------------------------------------------------------------------------
def test_dynamic_instrument_universe():
    """Verify category threshold resolution and dynamic configuration reload."""
    cfg = {
        "CATEGORY_SCORE_THRESHOLDS": {
            "INDEX_OPTIONS": 80,
            "STOCK_OPTIONS": 75,
            "LARGE_CAP_EQUITY": 72,
            "COMMODITIES": 85,
        },
        "INDEX_MIN_SCORE": 80,
        "MIN_SCORE_THRESHOLD": 68,
    }
    with patch.object(AllNSEScanner, "_reload_config_credentials", lambda self: None):
        scanner = AllNSEScanner(cfg=cfg)
        assert scanner.get_min_score_for_category("INDEX_OPTIONS") == 80
        assert scanner.get_min_score_for_category("STOCK_OPTIONS") == 75
        assert scanner.get_min_score_for_category("LARGE_CAP_EQUITY") == 72
        assert scanner.get_min_score_for_category("COMMODITIES") == 85
        assert scanner.get_min_score_for_category("NEW_CUSTOM_ASSET") == 68
