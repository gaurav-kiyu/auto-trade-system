"""OPB Phase D26-A & D26-B: Taxonomy Purity & Futures Contract-Parity Regression Suite.

Governance: OPB-FINAL-PHASE-GOVERNANCE-001
Operating Mode: PRODUCTION application / PAPER trading / SIGNAL_ONLY
Execution Mode: LOCAL-ONLY ENGINEERING

Coverage:
D26-A:
1. Genuine Stock Option contracts -> STOCK_OPTIONS
2. Cash equities in F&O universe -> existing cash-equity classification (LARGE_CAP_EQUITY / MID_SMALL_CAP)
3. Non-F&O cash equities -> EQUITY_SWING_DELIVERY
4. Canonical 10-category taxonomy invariance (0 new categories)
5. Index Options presentation truthfulness (Spot index labeled as Index Spot Proxy)

D26-B:
6. Valid Futures contract -> Futures LTP accepted
7. Spot/cash LTP deliberately supplied -> rejected / not substituted
8. Futures feed unavailable -> fail closed
9. Resolver failure -> no signal dispatch
10. R2 Cooldown suppression -> no persistence/dispatch
11. R2 Burst rate limit suppression -> no persistence/dispatch
12. R2 Daily quota suppression -> no persistence/dispatch
13. FUTURES_ENABLED=False default -> no live futures dispatch
"""

import time
from unittest.mock import MagicMock, patch

import pytest
from core.all_nse_scanner import AllNSEScanner, ScannedStockSignal
from core.fno_universe import (
    classify_instrument_market,
)
from core.futures_contract_resolver import (
    FuturesContractResolver,
)
from core.notifications.rich_signal_formatter import RichSignalFormatter

CANONICAL_10_CATEGORIES = {
    "INDEX_OPTIONS",
    "STOCK_OPTIONS",
    "FUTURES",
    "COMMODITIES",
    "CURRENCIES",
    "ETFS_REITS",
    "PENNY_SME",
    "LARGE_CAP_EQUITY",
    "MID_SMALL_CAP",
    "EQUITY_SWING_DELIVERY",
}


# =============================================================================
# D26-A: TAXONOMY PURITY & PRESENTATION TRUTH
# =============================================================================

class TestD26ATaxonomyPurity:
    """Verify canonical taxonomy purity between stock options, cash equity, and index options."""

    def test_genuine_stock_option_contracts_classified_as_stock_options(self):
        """Genuine option contracts with strike/expiry/type must resolve to STOCK_OPTIONS."""
        # Standard NSE contract format <UNDERLYING><YY><MMM><STRIKE><CE|PE>
        assert classify_instrument_market("RELIANCE24OCT2900CE") == "STOCK_OPTIONS"
        assert classify_instrument_market("INFY24NOV1800PE") == "STOCK_OPTIONS"
        assert classify_instrument_market("TCS24DEC3800CE") == "STOCK_OPTIONS"
        assert classify_instrument_market("DIXON24OCT12000PE") == "STOCK_OPTIONS"

        # Explicit instrument type or series
        assert classify_instrument_market("TCS", instrument_type="OPTSTK") == "STOCK_OPTIONS"
        assert classify_instrument_market("INFY", instrument_type="STOCK_OPTIONS") == "STOCK_OPTIONS"
        assert classify_instrument_market("RELIANCE", series="OPT") == "STOCK_OPTIONS"
        assert classify_instrument_market("SBIN", series="OPTION") == "STOCK_OPTIONS"

    def test_cash_equities_in_fno_universe_not_stock_options(self):
        """Cash equity stocks (series='EQ') in F&O universe must NOT be classified as STOCK_OPTIONS."""
        # NIFTY 50 blue chips -> LARGE_CAP_EQUITY
        assert classify_instrument_market("RELIANCE", series="EQ") == "LARGE_CAP_EQUITY"
        assert classify_instrument_market("INFY", series="EQ") == "LARGE_CAP_EQUITY"
        assert classify_instrument_market("TCS", series="EQ") == "LARGE_CAP_EQUITY"
        assert classify_instrument_market("HDFCBANK", series="EQ") == "LARGE_CAP_EQUITY"
        assert classify_instrument_market("SBIN", series="EQ") == "LARGE_CAP_EQUITY"

        # F&O equities outside NIFTY 50 -> MID_SMALL_CAP
        assert classify_instrument_market("DIXON", series="EQ") == "MID_SMALL_CAP"
        assert classify_instrument_market("AARTIIND", series="EQ") == "MID_SMALL_CAP"
        assert classify_instrument_market("IDEA", series="EQ") == "MID_SMALL_CAP"
        assert classify_instrument_market("VOLTAS", series="EQ") == "MID_SMALL_CAP"
        assert classify_instrument_market("CANBK", series="EQ") == "MID_SMALL_CAP"

        # Verify NONE of these cash equities are STOCK_OPTIONS
        for sym in ["RELIANCE", "INFY", "TCS", "DIXON", "AARTIIND", "IDEA", "CANBK", "VOLTAS"]:
            cat = classify_instrument_market(sym, series="EQ")
            assert cat != "STOCK_OPTIONS", f"Taxonomy violation: Cash stock {sym} misclassified as STOCK_OPTIONS"

    def test_non_fno_cash_equities_delivery_swing(self):
        """Non-F&O cash equities resolve to EQUITY_SWING_DELIVERY."""
        assert classify_instrument_market("XYZNONFNO", series="EQ") == "EQUITY_SWING_DELIVERY"
        assert classify_instrument_market("ADOR", series="EQ") == "EQUITY_SWING_DELIVERY"
        assert classify_instrument_market("ARSSBL", series="EQ") == "EQUITY_SWING_DELIVERY"
        assert classify_instrument_market("CRISIL", series="EQ") == "EQUITY_SWING_DELIVERY"

        # Explicit delivery/swing series or instrument type
        assert classify_instrument_market("RELIANCE", series="SWING") == "EQUITY_SWING_DELIVERY"
        assert classify_instrument_market("INFY", series="CNC") == "EQUITY_SWING_DELIVERY"
        assert classify_instrument_market("TCS", series="DELIVERY") == "EQUITY_SWING_DELIVERY"

    def test_ten_canonical_categories_strictly_preserved(self):
        """Ensure 100% of tested symbols map strictly into the canonical 10 categories (zero new categories)."""
        test_universe = [
            ("NIFTY", "EQ"), ("BANKNIFTY", "EQ"), ("FINNIFTY", "EQ"), ("SENSEX", "EQ"),
            ("NIFTY24DEC25000CE", "OPT"), ("BANKNIFTY24DEC52000PE", "OPT"),
            ("RELIANCE24OCT2900CE", "OPT"), ("INFY24NOV1800PE", "OPT"),
            ("RELIANCE26SEPFUT", "FUT"), ("NIFTY26SEPFUT", "FUT"),
            ("GOLD", "COMMODITY"), ("CRUDEOIL", "COMMODITY"), ("MCX:SILVER", "FUT"),
            ("USDINR", "CURRENCY"), ("EURINR", "CURRENCY"),
            ("NIFTYBEES", "EQ"), ("GOLDBEES", "EQ"), ("EMBASSY-REIT", "EQ"),
            ("SHREE_SME", "SM"), ("ALPHA_ST", "ST"),
            ("RELIANCE", "EQ"), ("TCS", "EQ"), ("INFY", "EQ"),
            ("DIXON", "EQ"), ("AARTIIND", "EQ"), ("IDEA", "EQ"),
            ("XYZNONFNO", "EQ"), ("ADOR", "EQ"), ("CRISIL", "EQ"),
        ]
        observed_categories = set()
        for sym, ser in test_universe:
            cat = classify_instrument_market(sym, series=ser)
            assert cat in CANONICAL_10_CATEGORIES, f"Unknown category '{cat}' produced for {sym}"
            observed_categories.add(cat)

        # Confirm all 10 canonical categories are represented
        assert observed_categories == CANONICAL_10_CATEGORIES, (
            f"Expected all 10 canonical categories, got {len(observed_categories)}: {observed_categories}"
        )

    def test_index_options_presentation_truthfulness(self):
        """Index Options based on spot data must be presented truthfully as 'Index Spot Proxy'."""
        # Spot index signal (evaluated on spot index level 24,850.00)
        spot_meta = RichSignalFormatter.format_human_friendly_symbol("NIFTY", "INDEX_OPTIONS")
        assert spot_meta["display_title"] == "NIFTY Index Spot Proxy"
        assert spot_meta["instrument_type"] == "INDEX SPOT PROXY"
        assert spot_meta["is_option"] is False

        # Subject line for spot index
        subj_call = RichSignalFormatter.build_rich_email_subject(
            symbol="NIFTY", category="INDEX_OPTIONS", direction="CALL",
            price=24850.0, score=90, tier="STRONG", target_1=25000.0, target_2=25200.0,
        )
        assert "BULLISH (INDEX SPOT PROXY)" in subj_call
        assert "BUY CE" not in subj_call

        subj_put = RichSignalFormatter.build_rich_email_subject(
            symbol="BANKNIFTY", category="INDEX_OPTIONS", direction="PUT",
            price=52000.0, score=90, tier="STRONG", target_1=51500.0, target_2=51000.0,
        )
        assert "BEARISH (INDEX SPOT PROXY)" in subj_put
        assert "BUY PE" not in subj_put

        # Telegram card for spot index
        tg_card = RichSignalFormatter.build_rich_telegram_message(
            symbol="NIFTY", category="INDEX_OPTIONS", direction="CALL",
            price=24850.0, score=90, tier="STRONG", stop_loss=24700.0,
            target_1=25000.0, target_2=25200.0,
        )
        assert "INDEX SPOT PROXY: BULLISH (CALL)" in tg_card
        assert "NIFTY Index Spot Proxy" in tg_card

        # Genuine option contract (e.g. NIFTY24AUG24500CE at premium 142.50)
        contract_meta = RichSignalFormatter.format_human_friendly_symbol("NIFTY24AUG24500CE", "INDEX_OPTIONS")
        assert contract_meta["is_option"] is True
        assert "Option" in contract_meta["display_title"]

        contract_subj = RichSignalFormatter.build_rich_email_subject(
            symbol="NIFTY24AUG24500CE", category="INDEX_OPTIONS", direction="CALL",
            price=142.50, score=90, tier="STRONG", target_1=185.0, target_2=220.0,
        )
        assert "BUY CE (CALL)" in contract_subj


# =============================================================================
# D26-B: FUTURES CONTRACT PARITY
# =============================================================================

class MockBrokerWithFutures:
    """Mock broker adapter providing quotes for futures contracts."""
    def __init__(self, fut_prices: dict[str, float] | None = None):
        self.fut_prices = fut_prices or {}

    def get_futures_ltp(self, sym: str) -> float | None:
        return self.fut_prices.get(sym)

    def get_ltp(self, sym: str) -> float | None:
        return self.fut_prices.get(sym)


class TestD26BFuturesContractParity:
    """Verify futures contract pricing, fail-closed feeds, and R2 governance."""

    @pytest.fixture
    def mock_scanner(self):
        """Construct scanner with isolated test configuration and mock credentials."""
        with patch.object(AllNSEScanner, "_reload_config_credentials", lambda self: None):
            cfg = {
                "EXECUTION_MODE": "SIGNAL_ONLY",
                "SIGNAL_DEDUP_COOLDOWN_SECS": 300,
                "MAX_ALERTS_PER_WINDOW": 5,
                "ALERT_RATE_WINDOW_SECS": 60,
                "MAX_ALERTS_PER_DAY": 10,
                "FUTURES_ENABLED": True,
                "MIN_SCORE_THRESHOLD": 70,
                "ALLOW_AFTER_HOURS_SCANNING": True,
            }
            scanner = AllNSEScanner(cfg=cfg)
            scanner._bot_token = ""
            scanner._email_enabled = False
            return scanner

    def _make_parent(self, symbol="RELIANCE", score=85, direction="CALL", price=3000.0):
        return ScannedStockSignal(
            symbol=symbol,
            company_name=f"{symbol} Ltd",
            series="EQ",
            direction=direction,
            score=score,
            raw_score=120,
            tier="STRONG",
            regime="TRENDING_BULL",
            price=price,
            rsi=62.0,
            adx=31.0,
            vwap=price - 10.0,
            confidence=0.88,
            ml_probability=0.72,
            score_components={"momentum": 25, "breakout": 25, "volume": 20, "trend": 15},
            features={"rsi": 62.0, "adx": 31.0, "vwap": price - 10.0, "price": price},
        )

    def test_valid_futures_contract_ltp_accepted(self, mock_scanner):
        """Valid futures contract quote (3025.0) is accepted and used for entry and targets."""
        parent = self._make_parent("RELIANCE", price=3000.0)
        contract = FuturesContractResolver.get_instance().resolve_current_contract("RELIANCE")
        assert contract is not None
        fut_symbol = contract.canonical_symbol

        # Wire live futures quote via broker adapter
        mock_scanner._broker_adapter = MockBrokerWithFutures({fut_symbol: 3025.0})

        with patch("core.fno_universe.is_fno_symbol", return_value=True), \
             patch("core.auth.user_signal_permissions.UserPermissionManager.get_instance") as mock_perm, \
             patch("core.signals.signal_tracker.SignalTracker.get_instance") as mock_tracker:

            mock_user = MagicMock(telegram_enabled=False, email_enabled=False)
            mock_perm.return_value.get_eligible_recipients.return_value = [mock_user]
            mock_tracker.return_value.count_generated_today.return_value = 0
            mock_tracker.return_value.record_generated_signal.return_value = "SIG_FUT_001"

            mock_scanner._dispatch_futures_alert_if_eligible(parent)

            # Assert signal was recorded with futures contract price (3025.0), NOT spot cash (3000.0)
            mock_tracker.return_value.record_generated_signal.assert_called_once()
            call_args = mock_tracker.return_value.record_generated_signal.call_args[0][0]
            assert call_args["price"] == 3025.0
            assert call_args["symbol"] == fut_symbol
            assert call_args["category"] == "FUTURES"
            # Verify target 1 and stop loss are calculated from futures price 3025.0
            assert call_args["target_1"] == round(3025.0 * 1.04, 2)
            assert call_args["stop_loss"] == round(3025.0 * 0.97, 2)

    def test_spot_cash_price_deliberately_supplied_never_substituted(self, mock_scanner):
        """Spot cash price (3000.0) must NEVER be substituted when futures feed is missing."""
        parent = self._make_parent("RELIANCE", price=3000.0)

        # Mock broker returns quote for cash but None for futures contract
        class MockCashOnlyBroker:
            def get_futures_ltp(self, sym):
                return None
            def get_ltp(self, sym):
                return 3000.0 if sym == "RELIANCE" else None

        mock_scanner._broker_adapter = MockCashOnlyBroker()

        with patch("core.fno_universe.is_fno_symbol", return_value=True), \
             patch("core.signals.signal_tracker.SignalTracker.get_instance") as mock_tracker:

            mock_tracker.return_value.count_generated_today.return_value = 0
            mock_scanner._dispatch_futures_alert_if_eligible(parent)

            # Assert fail-closed: NO signal persisted, cash price 3000.0 rejected
            mock_tracker.return_value.record_generated_signal.assert_not_called()

    def test_missing_futures_feed_fails_closed(self, mock_scanner):
        """Missing futures quote returns None and fails closed without dispatch."""
        parent = self._make_parent("RELIANCE")
        contract = FuturesContractResolver.get_instance().resolve_current_contract("RELIANCE")
        assert contract is not None
        fut_symbol = contract.canonical_symbol

        # Empty broker adapter provides no quote
        mock_scanner._broker_adapter = MockBrokerWithFutures({})

        with patch("core.fno_universe.is_fno_symbol", return_value=True), \
             patch("core.signals.signal_tracker.SignalTracker.get_instance") as mock_tracker:

            mock_tracker.return_value.count_generated_today.return_value = 0
            mock_scanner._dispatch_futures_alert_if_eligible(parent)

            mock_tracker.return_value.record_generated_signal.assert_not_called()
            state = mock_scanner._evaluation_states.get(fut_symbol)
            assert state is not None
            assert state["state"] == "FILTERED"
            assert "Futures feed unavailable" in state["reason"]

    def test_resolver_failure_no_signal_dispatch(self, mock_scanner):
        """When resolver cannot resolve active contract, fails closed with zero dispatch."""
        parent = self._make_parent("RELIANCE")

        with patch("core.fno_universe.is_fno_symbol", return_value=True), \
             patch.object(FuturesContractResolver, "resolve_current_contract", return_value=None), \
             patch("core.signals.signal_tracker.SignalTracker.get_instance") as mock_tracker:

            mock_tracker.return_value.count_generated_today.return_value = 0
            mock_scanner._dispatch_futures_alert_if_eligible(parent)
            mock_tracker.return_value.record_generated_signal.assert_not_called()

    def test_r2_cooldown_suppresses_derived_futures(self, mock_scanner):
        """Derived futures signal within cooldown is suppressed without price query or dispatch."""
        parent = self._make_parent("RELIANCE")
        contract = FuturesContractResolver.get_instance().resolve_current_contract("RELIANCE")
        fut_symbol = contract.canonical_symbol

        mock_scanner._last_alert_time[fut_symbol] = time.time() - 30.0  # within 300s cooldown

        with patch("core.fno_universe.is_fno_symbol", return_value=True), \
             patch("core.signals.signal_tracker.SignalTracker.get_instance") as mock_tracker:

            mock_tracker.return_value.count_generated_today.return_value = 0
            mock_scanner._dispatch_futures_alert_if_eligible(parent)

            mock_tracker.return_value.record_generated_signal.assert_not_called()
            state = mock_scanner._evaluation_states.get(fut_symbol)
            assert state["state"] == "COOLDOWN_SUPPRESSED"

    def test_r2_burst_rate_limit_suppresses_derived_futures(self, mock_scanner):
        """Derived futures signal is suppressed when alert window burst limit is exhausted."""
        parent = self._make_parent("RELIANCE")
        contract = FuturesContractResolver.get_instance().resolve_current_contract("RELIANCE")
        fut_symbol = contract.canonical_symbol

        now = time.time()
        for _ in range(5):  # max is 5
            mock_scanner._recent_dispatch_times.append(now)

        with patch("core.fno_universe.is_fno_symbol", return_value=True), \
             patch("core.signals.signal_tracker.SignalTracker.get_instance") as mock_tracker:

            mock_tracker.return_value.count_generated_today.return_value = 0
            mock_scanner._dispatch_futures_alert_if_eligible(parent)
            mock_tracker.return_value.record_generated_signal.assert_not_called()
            state = mock_scanner._evaluation_states.get(fut_symbol)
            assert state["state"] == "FILTERED"
            assert "Rate limit" in state["reason"]

    def test_r2_daily_quota_suppresses_derived_futures(self, mock_scanner):
        """Derived futures signal is blocked when daily quota is exhausted."""
        parent = self._make_parent("RELIANCE")
        contract = FuturesContractResolver.get_instance().resolve_current_contract("RELIANCE")
        fut_symbol = contract.canonical_symbol

        with patch("core.fno_universe.is_fno_symbol", return_value=True), \
             patch("core.signals.signal_tracker.SignalTracker.get_instance") as mock_tracker:

            mock_tracker.return_value.count_generated_today.return_value = 10  # max 10
            mock_scanner._dispatch_futures_alert_if_eligible(parent)

            mock_tracker.return_value.record_generated_signal.assert_not_called()
            state = mock_scanner._evaluation_states.get(fut_symbol)
            assert state["state"] == "FILTERED"
            assert "Daily signal limit reached" in state["reason"]

    def test_futures_disabled_default_fails_closed(self):
        """When FUTURES_ENABLED is omitted or False, zero futures dispatch occurs."""
        with patch.object(AllNSEScanner, "_reload_config_credentials", lambda self: None):
            # Configuration with FUTURES_ENABLED omitted (must default to False)
            scanner_default = AllNSEScanner(cfg={"EXECUTION_MODE": "SIGNAL_ONLY"})
            parent = self._make_parent("RELIANCE")

            with patch("core.signals.signal_tracker.SignalTracker.get_instance") as mock_tracker:
                mock_tracker.return_value.count_generated_today.return_value = 0
                scanner_default._dispatch_futures_alert_if_eligible(parent)
                mock_tracker.return_value.record_generated_signal.assert_not_called()

            # Explicit FUTURES_ENABLED: False
            scanner_explicit_off = AllNSEScanner(cfg={"EXECUTION_MODE": "SIGNAL_ONLY", "FUTURES_ENABLED": False})
            with patch("core.signals.signal_tracker.SignalTracker.get_instance") as mock_tracker:
                mock_tracker.return_value.count_generated_today.return_value = 0
                scanner_explicit_off._dispatch_futures_alert_if_eligible(parent)
                mock_tracker.return_value.record_generated_signal.assert_not_called()
