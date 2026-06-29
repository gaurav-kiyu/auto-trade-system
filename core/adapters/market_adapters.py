from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ..data_engine import ProviderChain

__all__ = [
    "DataRuntimeContext",
    "build_provider_chain",
    "fetch_yfinance_frames",
]

@dataclass(frozen=True)
class DataRuntimeContext:
    index_map: dict[str, Any]
    safe_fetch_fn: Callable[[str, str, str], Any]
    fetch_all_frames_fn: Callable[[list[str]], dict]
    fetch_last_close_fn: Callable[[], dict]
    get_live_prices_fn: Callable[[], dict]
    data_provider_enabled: dict[str, bool]


def fetch_yfinance_frames(indices: list[str], *, context: DataRuntimeContext) -> dict:
    frames: dict = {}
    for name in indices:
        meta = context.index_map.get(name, {})
        yf_symbol = meta.get("yf")
        if not yf_symbol:
            continue
        for interval, period in (("1m", "1d"), ("5m", "5d"), ("15m", "15d")):
            df = context.safe_fetch_fn(yf_symbol, interval, period=period)
            if df is not None and len(df) >= 5:
                frames[(yf_symbol, interval)] = df
    return frames


def build_provider_chain(*, context: DataRuntimeContext) -> ProviderChain:
    enabled = {name for name, flag in context.data_provider_enabled.items() if bool(flag)}
    providers = {
        "nse": lambda indices: context.fetch_all_frames_fn(indices),
        "yfinance": lambda indices: fetch_yfinance_frames(indices, context=context),
        "websocket": lambda indices: {},
        "broker": lambda indices: fetch_yfinance_frames(indices, context=context),
        "last_close": lambda: context.fetch_last_close_fn(),
        "live_prices": lambda: context.get_live_prices_fn(),
    }
    return ProviderChain(providers, enabled=enabled)
