from __future__ import annotations

import csv
import importlib.util
import json
import os
import sys
from pathlib import Path

import pandas as pd
from core import DataEngine

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"
INDEX_IMPL = ROOT / "index_app" / "index_trader.py"


def _load_index_module(tag: str):
    os.environ["OPBUYING_INDEX_CONFIG"] = str(ROOT / "config.json")
    argv_prev = sys.argv[:]
    sys.argv = ["index_app/index_trader.py"]
    try:
        spec = importlib.util.spec_from_file_location(tag, INDEX_IMPL)
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(module)
        return module, argv_prev
    except (ValueError, TypeError, OSError):
        sys.argv = argv_prev
        raise


def _restore_argv(argv_prev: list[str]) -> None:
    sys.argv = argv_prev


def test_data_engine_prefers_websocket_fixture():
    ws_fixture = json.loads((FIXTURES / "websocket_snapshot.json").read_text(encoding="utf-8"))
    fb_fixture = json.loads((FIXTURES / "fallback_frames.json").read_text(encoding="utf-8"))
    engine = DataEngine(
        fetch_all_frames_fn=lambda indices: fb_fixture,
        websocket_snapshot_fn=lambda: ws_fixture,
    )
    snap = engine.fetch_market_snapshot(["NIFTY"])
    assert snap.source == "websocket"
    assert snap.healthy is True
    assert snap.frames == ws_fixture


def test_data_engine_fallback_fixture_and_provider_failure():
    fb_fixture = json.loads((FIXTURES / "fallback_frames.json").read_text(encoding="utf-8"))
    engine = DataEngine(
        fetch_all_frames_fn=lambda indices: fb_fixture,
        websocket_snapshot_fn=lambda: {},
    )
    snap = engine.fetch_market_snapshot(["NIFTY"])
    assert snap.source == "fallback"
    assert snap.healthy is True
    assert snap.frames == fb_fixture

    failing = DataEngine(
        fetch_all_frames_fn=lambda indices: (_ for _ in ()).throw(RuntimeError("fixture failure")),
        websocket_snapshot_fn=lambda: {},
        last_close_fn=lambda: (_ for _ in ()).throw(RuntimeError("summary down")),
        live_prices_fn=lambda: (_ for _ in ()).throw(RuntimeError("live down")),
    )
    bad = failing.fetch_market_snapshot(["NIFTY"])
    assert bad.healthy is True
    assert "fixture" in bad.note.lower() or "fallback" in bad.note.lower()
    assert failing.fetch_last_close_summary() == {}
    assert failing.get_live_prices() == {}


def test_index_holiday_fetch_uses_non_json_fixture_fallback():
    module, argv_prev = _load_index_module("index_app_holiday_non_json_fixture")
    try:
        fallback = {"2026-01-26", "2026-03-14"}
        module.NSE_HOLIDAYS = set(fallback)
        module._NSE_HOLIDAY_YEARS = {d[:4] for d in fallback}
        module._HOLIDAY_FETCH_META = {"count": 0, "fallback": False, "note": ""}

        body = (FIXTURES / "nse_holiday_api_non_json.txt").read_text(encoding="utf-8")

        class FakeResponse:
            status_code = 200
            headers = {"Content-Type": "text/html"}
            text = body

            def json(self):
                raise AssertionError("json() should not be called for non-json fixture")

        module._nse_session.get = lambda *args, **kwargs: FakeResponse()
        module._fetch_nse_holidays_dynamic()
        assert module.NSE_HOLIDAYS == fallback
        assert module._HOLIDAY_FETCH_META["fallback"] is True
        assert module._HOLIDAY_FETCH_META["note"] == "non-json"
    finally:
        _restore_argv(argv_prev)


def test_index_holiday_fetch_merges_success_fixture():
    module, argv_prev = _load_index_module("index_app_holiday_success_fixture")
    try:
        baseline = {"2026-01-26"}
        module.NSE_HOLIDAYS = set(baseline)
        module._NSE_HOLIDAY_YEARS = {d[:4] for d in baseline}
        module._HOLIDAY_FETCH_META = {"count": 0, "fallback": True, "note": ""}
        payload = json.loads((FIXTURES / "nse_holiday_api_success.json").read_text(encoding="utf-8"))

        class FakeResponse:
            status_code = 200
            headers = {"Content-Type": "application/json"}
            text = json.dumps(payload)

            def json(self):
                return payload

        module._nse_session.get = lambda *args, **kwargs: FakeResponse()
        module._fetch_nse_holidays_dynamic()
        assert "2026-12-31" in module.NSE_HOLIDAYS
        assert "2026-08-14" in module.NSE_HOLIDAYS
        assert module._HOLIDAY_FETCH_META["fallback"] is False
        assert module._HOLIDAY_FETCH_META["note"] == "ok"
    finally:
        _restore_argv(argv_prev)


def test_index_last_close_summary_uses_fixture_history():
    module, argv_prev = _load_index_module("index_app_last_close_fixture")
    try:
        rows = []
        with (FIXTURES / "last_close_history.csv").open("r", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                rows.append(
                    {
                        "date": row["date"],
                        "Open": float(row["Open"]),
                        "High": float(row["High"]),
                        "Low": float(row["Low"]),
                        "Close": float(row["Close"]),
                    }
                )
        frame = pd.DataFrame(rows).set_index(pd.to_datetime([r["date"] for r in rows]))
        frame = frame.drop(columns=["date"])

        class FakeTicker:
            def __init__(self, _symbol: str):
                self.symbol = _symbol

            def history(self, period: str, interval: str):
                assert period == "5d"
                assert interval == "1d"
                return frame.copy()

        original_ticker = module.yf.Ticker
        original_map = module.INDEX_MAP
        module.yf.Ticker = FakeTicker
        module.INDEX_MAP = {"NIFTY": {"yf": "^NSEI"}}
        module._last_close_cache = {}
        module._last_close_cache_ts = 0
        summary = module.fetch_last_close_summary()
        assert summary["NIFTY"]["close"] == 22680.0
        assert summary["NIFTY"]["change"] == 155.0
        assert summary["NIFTY"]["pct"] == 0.69
        assert summary["NIFTY"]["date"] == "08-Apr-2026"
        module.yf.Ticker = original_ticker
        module.INDEX_MAP = original_map
    finally:
        _restore_argv(argv_prev)
