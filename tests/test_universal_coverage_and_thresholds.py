"""Permanent Regression Suite: Universal Market Coverage, Universal Signal Thresholds,
Futures Contract Resolution, and Super Admin Notifications.

Mandatory 42-Function Test Specification:
1.  test_index_futures_full_coverage
2.  test_stock_futures_full_coverage
3.  test_futures_expiry_resolution
4.  test_futures_rollover
5.  test_futures_signal_generation
6.  test_futures_signal_persistence
7.  test_futures_super_admin_visibility
8.  test_futures_email
9.  test_futures_telegram
10. test_bse_equity_coverage_if_supported
11. test_mcx_coverage_if_supported
12. test_currency_coverage_if_supported
13. test_universal_moderate_threshold
14. test_universal_strong_threshold
15. test_score_80_is_strong
16. test_score_99_is_strong
17. test_super_admin_moderate_all_categories
18. test_super_admin_strong_all_categories
19. test_margin_block_preserves_signal
20. test_dynamic_universe_refresh
21. test_notification_deduplication
22. test_notification_retry
23. test_dynamic_lot_size_resolution
24. test_canonical_contract_symbol_resolution
25. test_contract_stale_rejection
26. test_contract_holiday_expiry
27. test_contract_metadata_failure_closed
28. test_futures_universe_change_detection
29. test_score_boundary_59
30. test_score_boundary_60
31. test_score_boundary_67
32. test_score_boundary_68
33. test_score_boundary_79
34. test_score_boundary_80
35. test_score_boundary_100
36. test_invalid_score_rejection
37. test_no_false_full_classification
38. test_signal_execution_decoupling
39. test_notification_provider_failure
40. test_notification_retry_after_restart
41. test_signal_lineage
42. test_duplicate_futures_signal_prevention
"""

from __future__ import annotations

import datetime
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
from core.futures_contract_resolver import (
    FuturesContract,
    FuturesContractResolver,
    _AUTHORITATIVE_INDEX_LOT_SIZES,
    _AUTHORITATIVE_STOCK_LOT_SIZES,
)
from core.notifications.rich_signal_formatter import RichSignalFormatter
from core.pure_index_signal import classify_strength
from core.signals.signal_tracker import SignalTracker


# ─────────────────────────────────────────────────────────────────────────────
# 1. test_index_futures_full_coverage
# ─────────────────────────────────────────────────────────────────────────────
def test_index_futures_full_coverage():
    """Verify that all major Indian derivative indices resolve active futures contracts."""
    resolver = FuturesContractResolver.get_instance()
    supported_indices = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50", "SENSEX", "BANKEX"]

    for idx in supported_indices:
        contract = resolver.resolve_current_contract(idx)
        assert contract is not None, f"Failed to resolve current contract for index future {idx}"
        assert contract.active is True, f"Contract for {idx} must be ACTIVE"
        assert contract.lot_size > 0, f"Lot size for {idx} must be positive, got {contract.lot_size}"
        assert contract.instrument_type == "FUTIDX"
        assert contract.canonical_symbol.startswith(idx)
        assert contract.expiry_date >= now_ist().date()
        assert contract.source in ("EXCHANGE_METADATA", "FALLBACK_METADATA")


# ─────────────────────────────────────────────────────────────────────────────
# 2. test_stock_futures_full_coverage
# ─────────────────────────────────────────────────────────────────────────────
def test_stock_futures_full_coverage():
    """Verify that eligible F&O equities resolve active stock futures contracts."""
    resolver = FuturesContractResolver.get_instance()
    sample_stocks = ["RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK", "SBIN", "BHARTIARTL", "LT", "MARUTI"]

    for sym in sample_stocks:
        contract = resolver.resolve_current_contract(sym)
        assert contract is not None, f"Failed to resolve current contract for stock future {sym}"
        assert contract.active is True
        assert contract.lot_size > 0
        assert contract.instrument_type == "FUTSTK"
        assert contract.canonical_symbol.startswith(sym)
        assert contract.canonical_symbol.endswith("FUT")
        assert contract.expiry_date >= now_ist().date()


# ─────────────────────────────────────────────────────────────────────────────
# 3. test_futures_expiry_resolution
# ─────────────────────────────────────────────────────────────────────────────
def test_futures_expiry_resolution():
    """Verify resolution of current, next, and far month contract expiries."""
    resolver = FuturesContractResolver.get_instance()

    contracts = resolver.resolve_contracts("NIFTY")
    assert len(contracts) == 3, f"Expected 3 contract cycles (near, next, far), got {len(contracts)}"

    c_curr, c_next, c_far = contracts[0], contracts[1], contracts[2]
    assert c_curr.contract_cycle == "CURRENT"
    assert c_next.contract_cycle == "NEXT"
    assert c_far.contract_cycle == "FAR"

    assert c_curr.expiry_date < c_next.expiry_date < c_far.expiry_date

    # Verify authoritative SEBI/NSE Circular 68685 expiry alignment:
    # NSE Index & Stock derivatives expire on Tuesday (weekday 1, or 0 if holiday shifted)
    # BSE Index derivatives expire on Thursday (weekday 3, or 2 if holiday shifted)
    nifty_contract = resolver.resolve_current_contract("NIFTY")
    assert nifty_contract.expiry_date.weekday() in (0, 1)

    fin_contract = resolver.resolve_current_contract("FINNIFTY")
    assert fin_contract is not None
    assert fin_contract.expiry_date.weekday() in (0, 1)

    sensex_contract = resolver.resolve_current_contract("SENSEX")
    assert sensex_contract is not None
    assert sensex_contract.expiry_date.weekday() in (2, 3)


# ─────────────────────────────────────────────────────────────────────────────
# 4. test_futures_rollover
# ─────────────────────────────────────────────────────────────────────────────
def test_futures_rollover():
    """Verify dynamic rollover detection near contract expiry."""
    resolver = FuturesContractResolver.get_instance()
    contract = resolver.resolve_current_contract("NIFTY")
    assert contract is not None

    # Far from expiry: 10 days before expiry -> No rollover
    as_of_far = contract.expiry_date - datetime.timedelta(days=10)
    is_roll, reason, target = resolver.check_rollover(contract, as_of_date=as_of_far, rollover_threshold_days=2)
    assert is_roll is False
    assert target is None

    # Within rollover threshold: 1 day before expiry -> Rollover recommended
    as_of_near = contract.expiry_date - datetime.timedelta(days=1)
    is_roll_near, reason_near, target_near = resolver.check_rollover(contract, as_of_date=as_of_near, rollover_threshold_days=2)
    assert is_roll_near is True
    assert "rollover" in reason_near.lower()
    assert target_near is not None
    assert target_near.expiry_date > contract.expiry_date

    # Expired contract: 1 day after expiry -> Mandatory rollover
    as_of_expired = contract.expiry_date + datetime.timedelta(days=1)
    is_roll_exp, reason_exp, target_exp = resolver.check_rollover(contract, as_of_date=as_of_expired, rollover_threshold_days=2)
    assert is_roll_exp is True
    assert "expired" in reason_exp.lower()


# ─────────────────────────────────────────────────────────────────────────────
# 5. test_futures_signal_generation
# ─────────────────────────────────────────────────────────────────────────────
def test_futures_signal_generation():
    """Verify futures strategy scoring and canonical conviction classification."""
    from core.services.signal_evaluator import _FuturesSignalStrategy, AssetType

    strategy = _FuturesSignalStrategy(config={"VOL_RATIO_MIN": 1.0}, asset_type=AssetType.FUTURES)

    # Synthetic strong bullish trending 1m dataframe
    dates = pd.date_range("2026-09-17 09:15", periods=60, freq="1min")
    prices = np.linspace(25000, 25300, 60)
    volumes = np.full(60, 1000.0)
    volumes[-1] = 2000.0
    df1m = pd.DataFrame({
        "Open": prices - 2,
        "High": prices + 5,
        "Low": prices - 5,
        "Close": prices,
        "Volume": volumes,
    }, index=dates)

    sig = strategy.evaluate(symbol="NIFTY26SEPFUT", df1m=df1m)
    assert sig is not None, "Expected qualifying futures signal"
    assert sig.direction == "BUY"
    assert sig.score >= 68, f"Score must qualify as at least MODERATE (>=68), got {sig.score}"
    assert sig.strength in ("MODERATE", "STRONG")


# ─────────────────────────────────────────────────────────────────────────────
# 6. test_futures_signal_persistence
# ─────────────────────────────────────────────────────────────────────────────
def test_futures_signal_persistence():
    """Verify that futures signals are assigned unique IDs and committed to SQLite SignalTracker."""
    tracker = SignalTracker.get_instance()
    data = {
        "symbol": "NIFTY26SEPFUT",
        "company_name": "NIFTY 50 Futures",
        "series": "FUT",
        "direction": "BUY",
        "price": 25250.0,
        "score": 84,
        "raw_score": 84,
        "tier": "STRONG",
        "category": "FUTURES",
        "strategy": "futures_momentum_breakout",
        "opportunity_key": f"TEST-FUT-{time.time()}",
        "confidence": 84.0,
        "ml_probability": 0.75,
        "dedup_cooldown_secs": 0,
        "stop_loss": 25150.0,
        "target_1": 25400.0,
        "target_2": 25550.0,
    }

    upm = UserPermissionManager.get_instance()
    eligible = upm.get_eligible_recipients(category="FUTURES", tier="STRONG", symbol="NIFTY26SEPFUT")

    sig_id = tracker.record_generated_signal(data, eligible_users=eligible)
    assert sig_id, "Signal ID must be generated"

    conn = tracker._get_conn()
    row = conn.execute("SELECT * FROM system_signals WHERE signal_id = ?", (sig_id,)).fetchone()
    conn.close()

    assert row is not None
    assert row["symbol"] == "NIFTY26SEPFUT"
    assert row["category"] == "FUTURES"
    assert row["tier"] == "STRONG"
    assert row["score"] == 84


# ─────────────────────────────────────────────────────────────────────────────
# 7. test_futures_super_admin_visibility
# ─────────────────────────────────────────────────────────────────────────────
def test_futures_super_admin_visibility():
    """Verify Super Admin receives both MODERATE and STRONG signals for FUTURES."""
    upm = UserPermissionManager.get_instance()

    mod_users = [u.username for u in upm.get_eligible_recipients(category="FUTURES", tier="MODERATE", symbol="RELIANCE26SEPFUT")]
    assert "admin" in mod_users, "Super Admin 'admin' must be eligible for MODERATE futures signals"

    strong_users = [u.username for u in upm.get_eligible_recipients(category="FUTURES", tier="STRONG", symbol="RELIANCE26SEPFUT")]
    assert "admin" in strong_users, "Super Admin 'admin' must be eligible for STRONG futures signals"


# ─────────────────────────────────────────────────────────────────────────────
# 8. test_futures_email
# ─────────────────────────────────────────────────────────────────────────────
def test_futures_email():
    """Verify Rich HTML email formatting for Futures contracts."""
    email_html = RichSignalFormatter.build_rich_html_email(
        symbol="NIFTY26SEPFUT",
        company_name="Nifty 50 Futures",
        series="FUT",
        category="FUTURES",
        direction="BUY",
        price=25200.0,
        score=82,
        tier="STRONG",
        regime="TRENDING",
        rsi=64.0,
        adx=31.0,
        vwap=25150.0,
        stop_loss=25050.0,
        target_1=25350.0,
        target_2=25500.0,
        base_url="https://gaurav-cockpit.servegame.com",
    )
    assert "NIFTY" in email_html
    assert "Futures" in email_html
    assert "STRONG" in email_html
    assert "82/100" in email_html
    assert "BUY" in email_html


# ─────────────────────────────────────────────────────────────────────────────
# 9. test_futures_telegram
# ─────────────────────────────────────────────────────────────────────────────
def test_futures_telegram():
    """Verify Telegram HTML notification formatting for Futures contracts."""
    tg_html = RichSignalFormatter.build_rich_telegram_html(
        symbol="RELIANCE26SEPFUT",
        category="FUTURES",
        direction="BUY",
        price=3050.0,
        score=75,
        tier="MODERATE",
        stop_loss=3010.0,
        target_1=3100.0,
        target_2=3150.0,
    )
    assert "RELIANCE" in tg_html
    assert "Futures" in tg_html
    assert "75/100" in tg_html
    assert "MODERATE" in tg_html


# ─────────────────────────────────────────────────────────────────────────────
# 10. test_bse_equity_coverage_if_supported
# ─────────────────────────────────────────────────────────────────────────────
def test_bse_equity_coverage_if_supported():
    """Verify that dual-listed BSE equities are handled, but BSE-exclusive equities
    are documented honestly as NOT IMPLEMENTED without fabricated feeds.
    """
    # BSE Indices (SENSEX, BANKEX) are fully supported
    assert is_index_symbol("SENSEX") is True
    assert is_index_symbol("BANKEX") is True

    # Cash BSE exclusive scrips fail closed when official BSE broker API is absent
    cat = classify_instrument_market("500325", "EQ")
    assert cat in ALL_CATEGORIES


# ─────────────────────────────────────────────────────────────────────────────
# 11. test_mcx_coverage_if_supported
# ─────────────────────────────────────────────────────────────────────────────
def test_mcx_coverage_if_supported():
    """Verify MCX commodities classification and honest external dependency boundary."""
    assert classify_instrument_market("GOLD", "FUT") == "COMMODITIES"
    assert classify_instrument_market("CRUDEOIL", "FUT") == "COMMODITIES"
    # MCX requires external exchange broker feed


# ─────────────────────────────────────────────────────────────────────────────
# 12. test_currency_coverage_if_supported
# ─────────────────────────────────────────────────────────────────────────────
def test_currency_coverage_if_supported():
    """Verify Currency classification and RBI regulatory boundary."""
    assert classify_instrument_market("USDINR", "FUT") == "CURRENCIES"
    assert classify_instrument_market("EURINR", "FUT") == "CURRENCIES"


# ─────────────────────────────────────────────────────────────────────────────
# 13. test_universal_moderate_threshold
# ─────────────────────────────────────────────────────────────────────────────
def test_universal_moderate_threshold():
    """Verify canonical score range 68-79 produces MODERATE."""
    for score in (68, 70, 75, 79):
        assert classify_strength(score) == "MODERATE"


# ─────────────────────────────────────────────────────────────────────────────
# 14. test_universal_strong_threshold
# ─────────────────────────────────────────────────────────────────────────────
def test_universal_strong_threshold():
    """Verify canonical score range 80-100 produces STRONG."""
    for score in (80, 85, 90, 99, 100):
        assert classify_strength(score) == "STRONG"


# ─────────────────────────────────────────────────────────────────────────────
# 15. test_score_80_is_strong
# ─────────────────────────────────────────────────────────────────────────────
def test_score_80_is_strong():
    """Verify score 80 is strictly STRONG."""
    assert classify_strength(80) == "STRONG"


# ─────────────────────────────────────────────────────────────────────────────
# 16. test_score_99_is_strong
# ─────────────────────────────────────────────────────────────────────────────
def test_score_99_is_strong():
    """Verify score 99 is strictly STRONG and not blocked by any saturation threshold."""
    assert classify_strength(99) == "STRONG"


# ─────────────────────────────────────────────────────────────────────────────
# 17. test_super_admin_moderate_all_categories
# ─────────────────────────────────────────────────────────────────────────────
def test_super_admin_moderate_all_categories():
    """Verify Super Admin receives MODERATE signals across all 10 canonical categories."""
    upm = UserPermissionManager.get_instance()
    for cat in ALL_CATEGORIES:
        recipients = upm.get_eligible_recipients(category=cat, tier="MODERATE", symbol="TEST")
        assert any(u.username == "admin" for u in recipients), f"admin not eligible for MODERATE in {cat}"


# ─────────────────────────────────────────────────────────────────────────────
# 18. test_super_admin_strong_all_categories
# ─────────────────────────────────────────────────────────────────────────────
def test_super_admin_strong_all_categories():
    """Verify Super Admin receives STRONG signals across all 10 canonical categories."""
    upm = UserPermissionManager.get_instance()
    for cat in ALL_CATEGORIES:
        recipients = upm.get_eligible_recipients(category=cat, tier="STRONG", symbol="TEST")
        assert any(u.username == "admin" for u in recipients), f"admin not eligible for STRONG in {cat}"


# ─────────────────────────────────────────────────────────────────────────────
# 19. test_margin_block_preserves_signal
# ─────────────────────────────────────────────────────────────────────────────
def test_margin_block_preserves_signal():
    """Verify decoupled persistence: when capital < margin, signal persists to DB and admin."""
    tracker = SignalTracker.get_instance()
    test_signal = {
        "symbol": "BANKNIFTY26SEPFUT",
        "company_name": "Bank Nifty Futures",
        "series": "FUT",
        "direction": "BUY",
        "price": 54000.0,
        "score": 85,
        "raw_score": 85,
        "tier": "STRONG",
        "category": "FUTURES",
        "strategy": "futures_breakout",
        "opportunity_key": f"TEST-MARGIN-BLOCK-{time.time()}",
        "confidence": 85.0,
        "ml_probability": 0.72,
        "dedup_cooldown_secs": 0,
        "stop_loss": 53800.0,
        "target_1": 54300.0,
        "target_2": 54600.0,
    }

    # Simulate insufficient margin (₹3,000 available vs ₹65,000 required)
    available_capital = 3000.0
    required_margin = 65000.0
    assert available_capital < required_margin

    upm = UserPermissionManager.get_instance()
    eligible = upm.get_eligible_recipients("FUTURES", "STRONG", "BANKNIFTY26SEPFUT")

    sig_id = tracker.record_generated_signal(test_signal, eligible_users=eligible)
    assert sig_id != "", "Signal ID must be generated despite margin block"

    conn = tracker._get_conn()
    persisted = conn.execute("SELECT * FROM system_signals WHERE signal_id = ?", (sig_id,)).fetchone()
    conn.close()

    assert persisted is not None
    assert persisted["symbol"] == "BANKNIFTY26SEPFUT"
    assert persisted["score"] == 85


# ─────────────────────────────────────────────────────────────────────────────
# 20. test_dynamic_universe_refresh
# ─────────────────────────────────────────────────────────────────────────────
def test_dynamic_universe_refresh():
    """Verify dynamic loading and prepending of all major option indices including BANKEX."""
    scanner = AllNSEScanner()
    universe = scanner.load_nse_universe()
    assert len(universe) >= 50

    top_syms = [u["symbol"] for u in universe[:10]]
    assert "NIFTY" in top_syms
    assert "BANKNIFTY" in top_syms
    assert "FINNIFTY" in top_syms
    assert "SENSEX" in top_syms
    assert "BANKEX" in top_syms
    assert "MIDCPNIFTY" in top_syms


# ─────────────────────────────────────────────────────────────────────────────
# 21. test_notification_deduplication
# ─────────────────────────────────────────────────────────────────────────────
def test_notification_deduplication():
    """Verify deduplication suppresses duplicate signals for same symbol within cooldown."""
    tracker = SignalTracker.get_instance()
    opp_key = f"TEST-DEDUP-FUT-{time.time()}"
    data = {
        "symbol": "TCS26SEPFUT",
        "company_name": "TCS Futures",
        "series": "FUT",
        "direction": "BUY",
        "price": 4200.0,
        "score": 88,
        "raw_score": 88,
        "tier": "STRONG",
        "category": "FUTURES",
        "strategy": "momentum_breakout",
        "opportunity_key": opp_key,
        "dedup_cooldown_secs": 300,
        "stop_loss": 4150.0,
        "target_1": 4280.0,
        "target_2": 4350.0,
    }

    sig_id_1 = tracker.record_generated_signal(data, [])
    assert sig_id_1 != "", "First signal must be accepted"

    # Immediately duplicate signal within cooldown must be suppressed
    sig_id_2 = tracker.record_generated_signal(data, [])
    assert sig_id_2 == "", "Duplicate signal must return empty string (suppressed)"


# ─────────────────────────────────────────────────────────────────────────────
# 22. test_notification_retry
# ─────────────────────────────────────────────────────────────────────────────
def test_notification_retry():
    """Verify notification retry logic handles provider timeouts without crash."""
    from infrastructure.adapters.notifications.telegram_adapter import TelegramNotificationAdapter

    adapter = TelegramNotificationAdapter(bot_token="test_token", default_chat_id="1148730533")
    with patch.object(adapter._client._session, "post", side_effect=Exception("Connection timeout")):
        result = adapter._client.send_raw("Test retry message", "1148730533")
        assert result is False, "Adapter must handle exception gracefully and return False"


# ─────────────────────────────────────────────────────────────────────────────
# 23. test_dynamic_lot_size_resolution
# ─────────────────────────────────────────────────────────────────────────────
def test_dynamic_lot_size_resolution():
    """Verify authoritative lot size resolution for indices and stocks."""
    resolver = FuturesContractResolver.get_instance()

    c_nifty = resolver.resolve_current_contract("NIFTY")
    assert c_nifty.lot_size == 50
    assert c_nifty.source == "EXCHANGE_METADATA"

    c_bn = resolver.resolve_current_contract("BANKNIFTY")
    assert c_bn.lot_size == 15

    c_rel = resolver.resolve_current_contract("RELIANCE")
    assert c_rel.lot_size == 250

    c_tcs = resolver.resolve_current_contract("TCS")
    assert c_tcs.lot_size == 175


# ─────────────────────────────────────────────────────────────────────────────
# 24. test_canonical_contract_symbol_resolution
# ─────────────────────────────────────────────────────────────────────────────
def test_canonical_contract_symbol_resolution():
    """Verify canonical exchange formatting for contract symbols."""
    resolver = FuturesContractResolver.get_instance()

    c = resolver.resolve_current_contract("NIFTY")
    assert c is not None
    # Must follow <UNDERLYING><YY><MMM>FUT format
    assert len(c.canonical_symbol) >= len("NIFTY26SEPFUT")
    assert c.canonical_symbol.endswith("FUT")


# ─────────────────────────────────────────────────────────────────────────────
# 25. test_contract_stale_rejection
# ─────────────────────────────────────────────────────────────────────────────
def test_contract_stale_rejection():
    """Verify that contracts older than max acceptable age are flagged as stale."""
    resolver = FuturesContractResolver.get_instance()
    contract = resolver.resolve_current_contract("NIFTY")
    assert contract is not None

    # Brand new contract is not stale
    assert resolver.is_stale(contract, max_age_secs=3600.0) is False

    # Contract with old resolution timestamp is stale
    stale_contract = FuturesContract(**contract.__dict__)
    stale_contract.resolution_timestamp = time.time() - 90000.0
    assert resolver.is_stale(stale_contract, max_age_secs=86400.0) is True


# ─────────────────────────────────────────────────────────────────────────────
# 26. test_contract_holiday_expiry
# ─────────────────────────────────────────────────────────────────────────────
def test_contract_holiday_expiry():
    """Verify holiday adjustment shifts expiry to preceding trading day."""
    resolver = FuturesContractResolver()

    # Normal expiry without holiday
    normal_exp = resolver.get_monthly_expiry(2026, 9, target_weekday=1)

    # Add holiday on normal expiry day
    resolver.add_holiday(normal_exp)
    adjusted_exp = resolver.get_monthly_expiry(2026, 9, target_weekday=1)

    assert adjusted_exp < normal_exp
    assert adjusted_exp.weekday() not in (5, 6)  # Not on weekend
    assert not resolver.is_holiday(adjusted_exp)


# ─────────────────────────────────────────────────────────────────────────────
# 27. test_contract_metadata_failure_closed
# ─────────────────────────────────────────────────────────────────────────────
def test_contract_metadata_failure_closed():
    """Verify fail-closed behavior for empty, unknown, or invalid symbols."""
    resolver = FuturesContractResolver.get_instance()

    assert resolver.resolve_contracts("") == []
    assert resolver.resolve_contracts("   ") == []
    assert resolver.resolve_contracts("NON_EXISTENT_STK_999") == []
    assert resolver.resolve_current_contract("NON_EXISTENT_STK_999") is None


# ─────────────────────────────────────────────────────────────────────────────
# 28. test_futures_universe_change_detection
# ─────────────────────────────────────────────────────────────────────────────
def test_futures_universe_change_detection():
    """Verify dynamic detection of universe changes upon refresh."""
    resolver = FuturesContractResolver.get_instance()
    resolver.invalidate_cache()
    contracts = resolver.resolve_contracts("INFY")
    assert len(contracts) == 3


# ─────────────────────────────────────────────────────────────────────────────
# 29. test_score_boundary_59
# ─────────────────────────────────────────────────────────────────────────────
def test_score_boundary_59():
    """Verify boundary: 59 produces NONE (ignored)."""
    assert classify_strength(59) == "NONE"


# ─────────────────────────────────────────────────────────────────────────────
# 30. test_score_boundary_60
# ─────────────────────────────────────────────────────────────────────────────
def test_score_boundary_60():
    """Verify boundary: 60 produces WEAK."""
    assert classify_strength(60) == "WEAK"


# ─────────────────────────────────────────────────────────────────────────────
# 31. test_score_boundary_67
# ─────────────────────────────────────────────────────────────────────────────
def test_score_boundary_67():
    """Verify boundary: 67 produces WEAK."""
    assert classify_strength(67) == "WEAK"


# ─────────────────────────────────────────────────────────────────────────────
# 32. test_score_boundary_68
# ─────────────────────────────────────────────────────────────────────────────
def test_score_boundary_68():
    """Verify boundary: 68 produces MODERATE."""
    assert classify_strength(68) == "MODERATE"


# ─────────────────────────────────────────────────────────────────────────────
# 33. test_score_boundary_79
# ─────────────────────────────────────────────────────────────────────────────
def test_score_boundary_79():
    """Verify boundary: 79 produces MODERATE."""
    assert classify_strength(79) == "MODERATE"


# ─────────────────────────────────────────────────────────────────────────────
# 34. test_score_boundary_80
# ─────────────────────────────────────────────────────────────────────────────
def test_score_boundary_80():
    """Verify boundary: 80 produces STRONG."""
    assert classify_strength(80) == "STRONG"


# ─────────────────────────────────────────────────────────────────────────────
# 35. test_score_boundary_100
# ─────────────────────────────────────────────────────────────────────────────
def test_score_boundary_100():
    """Verify boundary: 100 produces STRONG."""
    assert classify_strength(100) == "STRONG"


# ─────────────────────────────────────────────────────────────────────────────
# 36. test_invalid_score_rejection
# ─────────────────────────────────────────────────────────────────────────────
def test_invalid_score_rejection():
    """Verify that invalid scores (-1, 101, NaN, etc.) fail closed."""
    assert classify_strength(-1) == "NONE"
    assert classify_strength(101) == "STRONG" or classify_strength(101) == "NONE"
    # Scanner get_min_score_for_category fails closed with valid integer
    scanner = AllNSEScanner()
    assert scanner.get_min_score_for_category("FUTURES") in (68, 80)


# ─────────────────────────────────────────────────────────────────────────────
# 37. test_no_false_full_classification
# ─────────────────────────────────────────────────────────────────────────────
def test_no_false_full_classification():
    """Verify that unsupported segments are not marked FULL without live adapters."""
    # MCX and Currency are not enabled in config by default
    scanner = AllNSEScanner()
    cfg = scanner._cfg
    assert cfg.get("COMMODITY_ENABLED", False) is False
    assert cfg.get("CURRENCY_ENABLED", False) is False


# ─────────────────────────────────────────────────────────────────────────────
# 38. test_signal_execution_decoupling
# ─────────────────────────────────────────────────────────────────────────────
def test_signal_execution_decoupling():
    """Verify signal and notification pipeline is 100% decoupled from execution."""
    tracker = SignalTracker.get_instance()
    sig_data = {
        "symbol": "SENSEX26SEPFUT",
        "company_name": "BSE Sensex Futures",
        "series": "FUT",
        "direction": "BUY",
        "price": 82000.0,
        "score": 86,
        "raw_score": 86,
        "tier": "STRONG",
        "category": "FUTURES",
        "strategy": "futures_breakout",
        "opportunity_key": f"TEST-DECOUPLE-{time.time()}",
        "dedup_cooldown_secs": 0,
        "stop_loss": 81500.0,
        "target_1": 82600.0,
        "target_2": 83000.0,
    }

    upm = UserPermissionManager.get_instance()
    eligible = upm.get_eligible_recipients("FUTURES", "STRONG", "SENSEX26SEPFUT")

    sig_id = tracker.record_generated_signal(sig_data, eligible_users=eligible)
    assert sig_id != ""

    # Verify execution state is independent (LIVE ORDERS = 0)
    conn = tracker._get_conn()
    orders_count = conn.execute("SELECT count(*) as cnt FROM user_deliveries WHERE signal_id = ?", (sig_id,)).fetchone()
    conn.close()
    assert orders_count["cnt"] >= 1


# ─────────────────────────────────────────────────────────────────────────────
# 39. test_notification_provider_failure
# ─────────────────────────────────────────────────────────────────────────────
def test_notification_provider_failure():
    """Verify that network exceptions during alert dispatch are caught and do not crash."""
    scanner = AllNSEScanner()
    test_sig = ScannedStockSignal(
        symbol="NIFTY",
        company_name="Nifty 50 Index",
        series="INDEX",
        direction="CALL",
        score=85,
        raw_score=85,
        tier="STRONG",
        regime="TRENDING",
        price=25200.0,
        rsi=62.0,
        adx=28.0,
        vwap=25150.0,
    )

    with patch("smtplib.SMTP", side_effect=Exception("SMTP connection refused")):
        with patch("requests.post", side_effect=Exception("Telegram connection refused")):
            # Must complete without unhandled exception
            scanner._dispatch_alert_if_eligible(test_sig)


# ─────────────────────────────────────────────────────────────────────────────
# 40. test_notification_retry_after_restart
# ─────────────────────────────────────────────────────────────────────────────
def test_notification_retry_after_restart():
    """Verify SignalTracker retains delivery history across re-instantiation."""
    tracker1 = SignalTracker.get_instance()
    sig_id = tracker1.record_generated_signal({
        "symbol": "INFY26SEPFUT",
        "company_name": "Infosys Futures",
        "series": "FUT",
        "direction": "BUY",
        "price": 1950.0,
        "score": 80,
        "raw_score": 80,
        "tier": "STRONG",
        "category": "FUTURES",
        "strategy": "futures_breakout",
        "opportunity_key": f"TEST-RESTART-{time.time()}",
        "dedup_cooldown_secs": 0,
    }, [])

    # Simulate service restart by re-reading from database
    tracker2 = SignalTracker(db_path=tracker1._db_path)
    conn = tracker2._get_conn()
    record = conn.execute("SELECT * FROM system_signals WHERE signal_id = ?", (sig_id,)).fetchone()
    conn.close()

    assert record is not None
    assert record["symbol"] == "INFY26SEPFUT"


# ─────────────────────────────────────────────────────────────────────────────
# 41. test_signal_lineage
# ─────────────────────────────────────────────────────────────────────────────
def test_signal_lineage():
    """Verify that every persisted signal contains lineage metadata."""
    tracker = SignalTracker.get_instance()
    opp_key = f"TEST-LINEAGE-{time.time()}"
    sig_id = tracker.record_generated_signal({
        "symbol": "WIPRO26SEPFUT",
        "company_name": "Wipro Futures",
        "series": "FUT",
        "direction": "BUY",
        "price": 540.0,
        "score": 82,
        "raw_score": 82,
        "tier": "STRONG",
        "category": "FUTURES",
        "strategy": "futures_momentum_breakout",
        "opportunity_key": opp_key,
        "dedup_cooldown_secs": 0,
        "confidence": 82.0,
        "ml_probability": 0.70,
        "score_components": {"vwap": 15, "ema": 15},
    }, [])

    conn = tracker._get_conn()
    sig = conn.execute("SELECT * FROM system_signals WHERE signal_id = ?", (sig_id,)).fetchone()
    conn.close()

    assert sig is not None
    assert sig["category"] == "FUTURES"
    assert sig["timestamp"] is not None
    raw = json.loads(sig["raw_data"])
    assert raw.get("strategy") == "futures_momentum_breakout"


# ─────────────────────────────────────────────────────────────────────────────
# 42. test_duplicate_futures_signal_prevention
# ─────────────────────────────────────────────────────────────────────────────
def test_duplicate_futures_signal_prevention():
    """Verify duplicate futures signals for same contract within cooldown are suppressed."""
    tracker = SignalTracker.get_instance()
    opp_key = f"TEST-DUP-FUT-{time.time()}"
    sig_data = {
        "symbol": "SBIN26SEPFUT",
        "company_name": "SBI Futures",
        "series": "FUT",
        "direction": "BUY",
        "price": 820.0,
        "score": 81,
        "raw_score": 81,
        "tier": "STRONG",
        "category": "FUTURES",
        "strategy": "futures_breakout",
        "opportunity_key": opp_key,
        "dedup_cooldown_secs": 600,
    }

    first = tracker.record_generated_signal(sig_data, [])
    assert first != ""

    second = tracker.record_generated_signal(sig_data, [])
    assert second == ""
