"""NSE Option Chain Recorder

Orchestrates fetching option chain data from the NSE adapter and recording
OI snapshots into ``oi_snapshots.db`` via ``core.oi_snapshot_store``.

This module is designed to be called during the main trading loop scan cycle
in ``index_trader.py``.

Usage in trading loop::

    from core.nse_option_recorder import record_oi_snapshots_for_indices
    record_oi_snapshots_for_indices(index_names, config, data_engine)

Architecture
------------
- Depends on ``core.oi_snapshot_store.record_snapshot()`` for persistence.
- Uses the injected central ``MarketDataService`` to fetch live NSE option-chain data.
- Never constructs infrastructure adapters directly.
- Never silently substitutes another provider for an NSE-certified OI snapshot.
"""
from __future__ import annotations

import logging
from typing import Any

from core.oi_snapshot_store import record_snapshot

_log = logging.getLogger(__name__)

def _aggregate_oi_data(chain: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate option chain records into a single OI snapshot dict.

    Args:
        chain: List of option contract dicts from NSE adapter
               (each has strike, lastPrice, openInterest, optionType, etc.)

    Returns:
        Dict with keys: pcr_ratio, call_oi, put_oi, call_volume,
                        put_volume, total_oi, snapshot_source

    """
    call_oi = 0
    put_oi = 0
    call_volume = 0
    put_volume = 0

    for contract in chain:
        oi = int(contract.get("openInterest", 0) or 0)
        vol = int(contract.get("volume", 0) or 0)
        opt_type = str(contract.get("optionType", "")).upper()

        if opt_type == "CALL":
            call_oi += oi
            call_volume += vol
        elif opt_type == "PUT":
            put_oi += oi
            put_volume += vol

    total_oi = call_oi + put_oi
    pcr_ratio = round(put_oi / call_oi, 4) if call_oi > 0 else 1.0

    return {
        "pcr_ratio": pcr_ratio,
        "call_oi": call_oi,
        "put_oi": put_oi,
        "call_volume": call_volume,
        "put_volume": put_volume,
        "total_oi": total_oi,
        "snapshot_source": "nse_recorder",
    }


def record_oi_snapshots_for_indices(
    index_names: list[str],
    config: dict[str, Any],
    market_data_service: Any = None,
    nse_adapter: Any = None,
) -> dict[str, bool]:
    """Fetch option chain data for each index and record OI snapshots.

    Args:
        index_names: List of index names (e.g. ``["NIFTY", "BANKNIFTY", "FINNIFTY"]``).
        config: Merged bot config dict (used to read OI snapshot settings).
        market_data_service: Injected central MarketDataService.

    Returns:
        Dict mapping each index name to whether a snapshot was recorded.

    """
    if not index_names:
        return {}

    # Read OI snapshot settings from config with safe defaults
    # Check both the OI snapshot flag and the NSE data provider flag
    oi_enabled = bool(config.get("oi_snapshot_enabled", config.get("OI_SNAPSHOT_ENABLED", True)))
    if not oi_enabled:
        _log.debug("[NSE_RECORDER] OI snapshot recording disabled via oi_snapshot_enabled")
        return dict.fromkeys(index_names, False)
    # Also respect DATA_PROVIDER_ENABLED.nse (defense-in-depth)
    data_providers = config.get("DATA_PROVIDER_ENABLED", {})
    if isinstance(data_providers, dict) and not data_providers.get("nse", True):
        _log.debug("[NSE_RECORDER] OI snapshot recording disabled via DATA_PROVIDER_ENABLED.nse")
        return dict.fromkeys(index_names, False)

    db_path = str(
        config.get("oi_snapshot_db_path", config.get("OI_SNAPSHOT_DB_PATH", "db/oi_snapshots.db")),
    )
    min_interval = int(
        config.get("oi_snapshot_min_interval", config.get("OI_SNAPSHOT_MIN_INTERVAL", 60)),
    )
    archive_days = int(
        config.get("oi_snapshot_archive_days", config.get("OI_SNAPSHOT_ARCHIVE_DAYS", 90)),
    )

    # ``nse_adapter`` is a test/backward-compatibility injection alias only.
    # Production callers must pass the central MarketDataService.
    if market_data_service is None and nse_adapter is not None:
        market_data_service = nse_adapter

    if market_data_service is None:
        _log.error("[NSE_RECORDER] Central MarketDataService is not wired; refusing direct adapter fallback")
        return dict.fromkeys(index_names, False)

    results: dict[str, bool] = {}

    for idx_name in index_names:
        try:
            if hasattr(market_data_service, "get_option_chain_with_source"):
                result = market_data_service.get_option_chain_with_source(
                    idx_name, asset_class="index", provider="nse"
                )
                if isinstance(result, tuple) and len(result) == 2:
                    chain, source = result
                elif hasattr(market_data_service, "get_option_chain"):
                    chain = market_data_service.get_option_chain(idx_name)
                    source = "nse" if chain else None
                else:
                    chain, source = [], None
            elif hasattr(market_data_service, "get_option_chain"):
                chain = market_data_service.get_option_chain(idx_name)
                source = "nse" if chain else None
            else:
                chain, source = [], None
            if source != "nse" or not chain:
                _log.warning("[NSE_RECORDER] NSE option-chain unavailable for %s; source=%s", idx_name, source)
                results[idx_name] = False
                continue

            # Aggregate CE/PE records into one OI snapshot
            oi_data = _aggregate_oi_data(chain)

            # Record snapshot via OI snapshot store
            recorded = record_snapshot(
                index_name=idx_name,
                chain_data=oi_data,
                db_path=db_path,
                min_interval=min_interval,
                archive_days=archive_days,
            )
            results[idx_name] = recorded

            if recorded:
                _log.info(
                    "[NSE_RECORDER] OI snapshot for %s: PCR=%.4f OI=%d",
                    idx_name,
                    oi_data.get("pcr_ratio", 0),
                    oi_data.get("total_oi", 0),
                )

        except (ValueError, TypeError, OSError, RuntimeError) as exc:
            _log.warning("[NSE_RECORDER] Failed to record OI for %s: %s", idx_name, exc)
            results[idx_name] = False

    return results


def reset_nse_adapter_cache() -> None:
    """Compatibility no-op retained for existing tests/callers.

    Adapter lifetime is now owned by the central DI container.
    """
    return None


def get_oi_summary(
    index_names: list[str],
    config: dict[str, Any],
    market_data_service: Any = None,
) -> dict[str, Any]:
    """Fetch current NSE OI/PCR summaries through the central market-data service."""
    if market_data_service is None or not hasattr(market_data_service, "get_option_chain_with_source"):
        return {idx: {"error": "MarketDataService not wired"} for idx in index_names}

    summary: dict[str, Any] = {}
    for idx_name in index_names:
        try:
            chain, source = market_data_service.get_option_chain_with_source(
                idx_name, asset_class="index", provider="nse"
            )
            if source != "nse" or not chain:
                summary[idx_name] = {"error": "NSE option-chain unavailable", "source": source}
                continue
            oi_data = _aggregate_oi_data(chain)
            oi_data["source"] = source
            summary[idx_name] = oi_data
        except (ValueError, TypeError, OSError, RuntimeError, KeyError) as exc:
            summary[idx_name] = {"error": str(exc), "source": "nse"}
    return summary


__all__ = [
    "get_oi_summary",
    "record_oi_snapshots_for_indices",
    "reset_nse_adapter_cache",
]

