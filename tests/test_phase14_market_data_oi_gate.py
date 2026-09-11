"""Phase-14 targeted regression gate for centralized market-data/OI wiring."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from core.services.market_data_service import MarketDataService
from core.notifications.url_resolver import DEFAULT_PRODUCTION_URL, get_external_notification_base_url
from core.nse_option_recorder import _aggregate_oi_data, record_oi_snapshots_for_indices, get_oi_summary


class FakeAdapter:
    def __init__(self, chain=None, error=None):
        self.chain = chain or []
        self.error = error
    def connect(self): return True
    def disconnect(self): pass
    def get_quote(self, symbol): return None
    def get_latest_data(self, symbol): return None
    def is_data_fresh(self, market_data, max_age_seconds=30): return True
    def subscribe_to_market_data(self, symbols, callback): return False
    def unsubscribe_from_market_data(self, symbol): return True
    def get_historical_data(self, symbol, from_date, to_date, interval="day"): return []
    def get_option_chain(self, symbol, expiry_date=None):
        if self.error:
            raise self.error
        return list(self.chain)
    def get_instrument_details(self, symbol): return {"symbol": symbol}


def _chain():
    return [
        {"strike": 22000, "optionType": "CALL", "openInterest": 100, "volume": 10},
        {"strike": 22000, "optionType": "PUT", "openInterest": 150, "volume": 15},
    ]


def test_mds_option_chain_preserves_provider_identity():
    svc = MarketDataService()
    svc.register("nse", FakeAdapter(_chain()), ["index"], priority=10)
    data, source = svc.get_option_chain_with_source("NIFTY", provider="nse")
    assert data and source == "nse"


def test_mds_required_nse_does_not_silently_fallback():
    svc = MarketDataService()
    svc.register("nse", FakeAdapter(error=ConnectionError("blocked")), ["index"], priority=10)
    svc.register("yfinance", FakeAdapter(_chain()), ["index"], priority=1)
    data, source = svc.get_option_chain_with_source("NIFTY", provider="nse")
    assert data == []
    assert source is None


def test_oi_recorder_requires_central_mds(tmp_path: Path):
    result = record_oi_snapshots_for_indices(
        ["NIFTY"], {"oi_snapshot_enabled": True, "DATA_PROVIDER_ENABLED": {"nse": True}}, None
    )
    assert result == {"NIFTY": False}


def test_oi_recorder_uses_nse_only(tmp_path: Path, monkeypatch):
    svc = MarketDataService()
    svc.register("nse", FakeAdapter(_chain()), ["index"], priority=10)
    cfg = {
        "oi_snapshot_enabled": True,
        "DATA_PROVIDER_ENABLED": {"nse": True},
        "oi_snapshot_db_path": str(tmp_path / "oi.db"),
        "oi_snapshot_min_interval": 0,
        "oi_snapshot_archive_days": 90,
    }
    result = record_oi_snapshots_for_indices(["NIFTY"], cfg, svc)
    assert result["NIFTY"] is True


def test_dashboard_summary_preserves_nse_provenance():
    svc = MarketDataService()
    svc.register("nse", FakeAdapter(_chain()), ["index"], priority=10)
    result = get_oi_summary(["NIFTY"], {}, svc)
    assert result["NIFTY"]["source"] == "nse"


def test_architecture_core_oi_recorder_has_no_infrastructure_import():
    text = Path("core/nse_option_recorder.py").read_text(encoding="utf-8")
    assert "from infrastructure." not in text
    assert "import infrastructure." not in text


def test_external_notification_url_never_returns_loopback():
    assert get_external_notification_base_url({"ENVIRONMENT": "dev"}) == DEFAULT_PRODUCTION_URL
    assert get_external_notification_base_url({"PUBLIC_BASE_URL": "http://localhost:8000"}) == DEFAULT_PRODUCTION_URL


def test_legacy_dashboard_fallback_is_absent_from_trading_loop():
    text = Path("index_app/index_trader.py").read_text(encoding="utf-8")
    assert '"web_dashboard_port", 8000' not in text
    assert '"127.0.0.1"' not in text[text.index("def _run_trading_loop"):text.index("def _run_trading_loop") + 5000]
