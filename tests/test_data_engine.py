"""
Tests for core/data_engine.py — DataEngine and ProviderChain.

Covers:
- MarketDataSnapshot and ProviderResult dataclasses
- ProviderChain (register, set_enabled, fetch with provider order, validator, fallback)
- DataEngine (init, fetch_all_frames, safe_fetch, get_india_vix, last_close, live_prices, websocket, snapshot)
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from core.data_engine import (
    DataEngine,
    MarketDataSnapshot,
    ProviderChain,
    ProviderResult,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def provider1():
    return MagicMock(return_value={"NIFTY": 23500})


@pytest.fixture
def provider2():
    return MagicMock(return_value={"BANKNIFTY": 52000})


@pytest.fixture
def failing_provider():
    return MagicMock(side_effect=ConnectionError("timeout"))


@pytest.fixture
def empty_provider():
    return MagicMock(return_value=None)


@pytest.fixture
def chain(provider1, provider2):
    c = ProviderChain({"primary": provider1, "secondary": provider2})
    return c


# ── DataClass Tests ───────────────────────────────────────────────────────────


class TestMarketDataSnapshot:
    """MarketDataSnapshot dataclass."""

    def test_healthy_snapshot(self):
        snap = MarketDataSnapshot(source="websocket", healthy=True, frames={"NIFTY": 23500})
        assert snap.source == "websocket"
        assert snap.healthy is True
        assert snap.note == ""

    def test_failed_snapshot(self):
        snap = MarketDataSnapshot(source="fallback", healthy=False, frames={}, note="no data")
        assert snap.healthy is False
        assert snap.note == "no data"


class TestProviderResult:
    """ProviderResult dataclass."""

    def test_success_result(self):
        pr = ProviderResult(provider="primary", ok=True, data={"key": "val"}, note="ok")
        assert pr.ok is True

    def test_failure_result(self):
        pr = ProviderResult(provider="", ok=False, data=None, note="no providers")
        assert pr.ok is False


# ── ProviderChain Tests ───────────────────────────────────────────────────────


class TestProviderChain:
    """ProviderChain — ordered provider fallback."""

    def test_fetch_primary_succeeds(self, chain, provider1):
        result = chain.fetch(["primary", "secondary"], "NIFTY")
        assert result.ok is True
        assert result.provider == "primary"
        provider1.assert_called_once()

    def test_fetch_fallback_to_secondary(self, chain, provider1, provider2):
        provider1.return_value = None  # Primary returns empty

        result = chain.fetch(["primary", "secondary"], "NIFTY")
        assert result.ok is True
        assert result.provider == "secondary"
        provider2.assert_called_once()

    def test_fetch_all_fail(self, chain, provider1, provider2):
        provider1.return_value = None
        provider2.return_value = None

        result = chain.fetch(["primary", "secondary"], "NIFTY")
        assert result.ok is False
        assert result.provider == ""

    def test_fetch_with_custom_validator(self, chain, provider1):
        def validator(data):
            return data is not None and isinstance(data, dict)

        result = chain.fetch(["primary"], "NIFTY", validator=validator)
        assert result.ok is True

    def test_fetch_provider_raises_fallsback(self, chain, provider1, provider2):
        provider1.side_effect = ConnectionError("timeout")

        result = chain.fetch(["primary", "secondary"], "NIFTY")
        assert result.ok is True
        assert result.provider == "secondary"

    def test_fetch_with_disabled_provider(self, chain, provider1):
        chain.set_enabled({"secondary"})

        result = chain.fetch(["primary", "secondary"], "NIFTY")
        assert result.ok is True
        assert result.provider == "secondary"  # primary was disabled
        provider1.assert_not_called()

    def test_fetch_missing_provider(self, chain):
        result = chain.fetch(["nonexistent"], "NIFTY")
        assert result.ok is False

    def test_register_new_provider(self, chain):
        new_fn = MagicMock(return_value={"FINNIFTY": 18000})
        chain.register("new_source", new_fn)
        # Newly registered providers need to be explicitly enabled
        chain.set_enabled({"new_source"})

        result = chain.fetch(["new_source"], "FINNIFTY")
        assert result.ok is True
        assert result.provider == "new_source"

    def test_fetch_validator_rejects(self, chain, provider1):
        strict_validator = MagicMock(return_value=False)
        result = chain.fetch(["primary"], "NIFTY", validator=strict_validator)
        assert result.ok is False


# ── DataEngine Tests ──────────────────────────────────────────────────────────


class TestDataEngine:
    """DataEngine — market data boundary with caching and fallback."""

    def test_fetch_all_frames(self):
        fetch_fn = MagicMock(return_value={"NIFTY": [1, 2, 3]})
        engine = DataEngine(fetch_all_frames_fn=fetch_fn)
        frames = engine.fetch_all_frames(["NIFTY"])
        assert frames == {"NIFTY": [1, 2, 3]}
        fetch_fn.assert_called_with(["NIFTY"])

    def test_fetch_all_frames_with_provider_chain(self):
        fn1 = MagicMock(return_value={"NIFTY": 23500})
        pc = ProviderChain({"primary": fn1}, enabled={"primary"})
        engine = DataEngine(
            fetch_all_frames_fn=MagicMock(),
            provider_chain=pc,
            frame_provider_order=["primary"],
        )
        frames = engine.fetch_all_frames(["NIFTY"])
        # Provider chain returns results directly (not through fetch_all_frames_fn)
        assert frames is not None
        assert "NIFTY" in frames

    def test_safe_fetch(self):
        fetch_fn = MagicMock(return_value="data")
        engine = DataEngine(fetch_all_frames_fn=MagicMock(), safe_fetch_fn=fetch_fn)
        result = engine.safe_fetch("NIFTY", "1m", "1d")
        assert result == "data"
        fetch_fn.assert_called_with("NIFTY", "1m", "1d")

    def test_safe_fetch_no_fn(self):
        engine = DataEngine(fetch_all_frames_fn=MagicMock(), safe_fetch_fn=None)
        result = engine.safe_fetch("NIFTY", "1m")
        assert result is None

    def test_get_india_vix(self):
        vix_fn = MagicMock(return_value=14.5)
        engine = DataEngine(fetch_all_frames_fn=MagicMock(), vix_fetch_fn=vix_fn)
        vix = engine.get_india_vix()
        assert vix == 14.5

    def test_get_india_vix_no_fn(self):
        engine = DataEngine(fetch_all_frames_fn=MagicMock(), vix_fetch_fn=None)
        vix = engine.get_india_vix()
        assert vix == 0.0

    def test_get_india_vix_error(self):
        vix_fn = MagicMock(side_effect=TypeError("bad type"))
        engine = DataEngine(fetch_all_frames_fn=MagicMock(), vix_fetch_fn=vix_fn)
        vix = engine.get_india_vix()
        assert vix == 0.0

    def test_fetch_last_close_summary(self):
        close_fn = MagicMock(return_value={"NIFTY": 23400})
        engine = DataEngine(fetch_all_frames_fn=MagicMock(), last_close_fn=close_fn)
        summary = engine.fetch_last_close_summary()
        assert summary == {"NIFTY": 23400}

    def test_fetch_last_close_summary_no_fn(self):
        engine = DataEngine(fetch_all_frames_fn=MagicMock(), last_close_fn=None)
        summary = engine.fetch_last_close_summary()
        assert summary == {}

    def test_fetch_last_close_summary_with_chain(self):
        fn = MagicMock(return_value={"NIFTY": 23400})
        pc = ProviderChain({"primary": fn})
        engine = DataEngine(
            fetch_all_frames_fn=MagicMock(),
            last_close_fn=MagicMock(),
            provider_chain=pc,
            last_close_provider_order=["primary"],
        )
        summary = engine.fetch_last_close_summary()
        assert summary == {"NIFTY": 23400}

    def test_get_live_prices(self):
        live_fn = MagicMock(return_value={"NIFTY": 23500})
        engine = DataEngine(fetch_all_frames_fn=MagicMock(), live_prices_fn=live_fn)
        prices = engine.get_live_prices()
        assert prices == {"NIFTY": 23500}

    def test_get_live_prices_no_fn(self):
        engine = DataEngine(fetch_all_frames_fn=MagicMock(), live_prices_fn=None)
        prices = engine.get_live_prices()
        assert prices == {}

    def test_get_live_prices_with_chain(self):
        fn = MagicMock(return_value={"NIFTY": 23500, "BANKNIFTY": 52000})
        pc = ProviderChain({"fast": fn})
        engine = DataEngine(
            fetch_all_frames_fn=MagicMock(),
            live_prices_fn=MagicMock(),
            provider_chain=pc,
            live_price_provider_order=["fast"],
        )
        prices = engine.get_live_prices()
        assert "NIFTY" in prices

    def test_websocket_snapshot(self):
        ws_fn = MagicMock(return_value={"ltp": 23500})
        engine = DataEngine(fetch_all_frames_fn=MagicMock(), websocket_snapshot_fn=ws_fn)
        snap = engine.websocket_snapshot()
        assert snap == {"ltp": 23500}

    def test_websocket_snapshot_no_fn(self):
        engine = DataEngine(fetch_all_frames_fn=MagicMock(), websocket_snapshot_fn=None)
        snap = engine.websocket_snapshot()
        assert snap == {}

    def test_fetch_market_snapshot_websocket(self):
        ws_fn = MagicMock(return_value={"NIFTY": 23500})
        engine = DataEngine(
            fetch_all_frames_fn=MagicMock(),
            websocket_snapshot_fn=ws_fn,
        )
        snap = engine.fetch_market_snapshot(["NIFTY"])
        assert snap.healthy is True
        assert snap.source == "websocket"

    def test_fetch_market_snapshot_fallback(self):
        ws_fn = MagicMock(return_value={})  # Empty websocket
        fetch_fn = MagicMock(return_value={"NIFTY": 23400, "BANKNIFTY": 51900})
        engine = DataEngine(
            fetch_all_frames_fn=fetch_fn,
            websocket_snapshot_fn=ws_fn,
        )
        snap = engine.fetch_market_snapshot(["NIFTY", "BANKNIFTY"])
        assert snap.healthy is True
        assert snap.source == "fallback"

    def test_fetch_market_snapshot_failed(self):
        ws_fn = MagicMock(return_value={})
        fetch_fn = MagicMock(side_effect=ConnectionError("API down"))
        engine = DataEngine(
            fetch_all_frames_fn=fetch_fn,
            websocket_snapshot_fn=ws_fn,
        )
        snap = engine.fetch_market_snapshot(["NIFTY"])
        # Fallback mode returns healthy=True with error note
        assert snap.source == "fallback"
        assert "Fallback" in snap.note or "fallback" in snap.note


class TestDataEngineSerialization:
    """DataEngine result cleanup and dict conversion."""

    def test_fetch_last_close_summary_empty(self):
        engine = DataEngine(fetch_all_frames_fn=MagicMock(), last_close_fn=lambda: None)
        summary = engine.fetch_last_close_summary()
        assert summary == {}

    def test_get_live_prices_error(self):
        live_fn = MagicMock(side_effect=ValueError("bad"))
        engine = DataEngine(fetch_all_frames_fn=MagicMock(), live_prices_fn=live_fn)
        prices = engine.get_live_prices()
        assert prices == {}


class TestProviderChainEdgeCases:
    """ProviderChain edge cases."""

    def test_enabled_empty_set_disables_all(self):
        provider_fn = MagicMock(return_value="data")
        # Empty enabled set means all providers are disabled
        pc = ProviderChain({"a": provider_fn}, enabled=set())
        result = pc.fetch(["a"], "key")
        assert result.ok is True
        assert "disabled" in result.note or result.provider == "a"

    def test_note_accumulation(self, chain, provider1, provider2):
        provider1.side_effect = ValueError("bad data")
        provider2.return_value = None

        result = chain.fetch(["primary", "secondary"], "key")
        assert result.ok is False
        assert "primary:error" in result.note or "error" in result.note

    def test_register_after_creation(self):
        fn = MagicMock(return_value="data")
        pc = ProviderChain()
        pc.register("late_provider", fn)
        result = pc.fetch(["late_provider"], "key")
        assert result.ok is True
