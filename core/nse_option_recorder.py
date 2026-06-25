"""
NSE Option Chain Recorder

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
- Uses the NSE market data adapter (``infrastructure.adapters.market_data.nse.adapter``)
  to fetch live option chain data.
- Never blocks or raises - all exceptions are caught and logged.
- **Caches the NSEAdapter instance across calls** to maintain session cookies.
"""
from __future__ import annotations

import logging
from typing import Any

from core.oi_snapshot_store import record_snapshot

_log = logging.getLogger(__name__)

# Module-level cache for NSEAdapter instance (preserves session cookies across calls)
_nse_adapter_cache: Any = None


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
    nse_adapter: Any = None,
) -> dict[str, bool]:
    """Fetch option chain data for each index and record OI snapshots.

    Args:
        index_names: List of index names (e.g. ``["NIFTY", "BANKNIFTY", "FINNIFTY"]``).
        config: Merged bot config dict (used to read OI snapshot settings).
        nse_adapter: Optional NSE adapter instance. If None, lazy-imports one.

    Returns:
        Dict mapping each index name to whether a snapshot was recorded.
    """
    if not index_names:
        return {}

    # Read OI snapshot settings from config with safe defaults
    oi_enabled = bool(config.get("oi_snapshot_enabled", config.get("OI_SNAPSHOT_ENABLED", True)))
    if not oi_enabled:
        _log.debug("[NSE_RECORDER] OI snapshot recording is disabled via config")
        return {idx: False for idx in index_names}

    db_path = str(
        config.get("oi_snapshot_db_path", config.get("OI_SNAPSHOT_DB_PATH", "oi_snapshots.db"))
    )
    min_interval = int(
        config.get("oi_snapshot_min_interval", config.get("OI_SNAPSHOT_MIN_INTERVAL", 60))
    )
    archive_days = int(
        config.get("oi_snapshot_archive_days", config.get("OI_SNAPSHOT_ARCHIVE_DAYS", 90))
    )

    # Lazy-import NSE adapter (avoids import errors if infrastructure not available)
    # Uses module-level cache to maintain session cookies across scan cycles
    if nse_adapter is None:
        global _nse_adapter_cache
        if _nse_adapter_cache is not None:
            nse_adapter = _nse_adapter_cache
        else:
            try:
                from infrastructure.adapters.market_data.nse.adapter import NSEAdapter
                nse_adapter = NSEAdapter(
                    enable_rate_limit=True,
                    max_retries=2,
                    requests_per_second=0.5,
                )
                _nse_adapter_cache = nse_adapter  # Cache for next scan cycle
            except ImportError as exc:
                _log.warning("[NSE_RECORDER] NSEAdapter not available: %s", exc)
                return {idx: False for idx in index_names}
            except (ImportError, OSError, RuntimeError) as exc:
                _log.warning("[NSE_RECORDER] Failed to initialize NSEAdapter: %s", exc)
                return {idx: False for idx in index_names}

    results: dict[str, bool] = {}

    for idx_name in index_names:
        try:
            chain = nse_adapter.get_option_chain(idx_name)
            if not chain:
                _log.debug("[NSE_RECORDER] No option chain data for %s", idx_name)
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
    """Reset the module-level NSE adapter cache.

    Used primarily in tests to ensure test isolation when patching
    the NSEAdapter import.
    """
    global _nse_adapter_cache
    _nse_adapter_cache = None


def get_oi_summary(index_names: list[str], config: dict[str, Any]) -> dict[str, Any]:
    """Fetch current OI/PCR summary for the given indices (read-only, no recording).

    Useful for dashboards, Telegram summaries, and health checks.
    Does NOT use the module-level adapter cache (since it's infrequently called).

    Args:
        index_names: List of index names.
        config: Merged bot config dict.

    Returns:
        Dict mapping index name to OI summary dict (pcr, call_oi, put_oi, etc.)
        or error dict if fetching failed.
    """
    summary: dict[str, Any] = {}

    try:
        from infrastructure.adapters.market_data.nse.adapter import NSEAdapter
        nse_adapter = NSEAdapter(
            enable_rate_limit=True,
            max_retries=2,
            requests_per_second=0.5,
        )
    except ImportError as exc:
        _log.warning("[NSE_RECORDER] NSEAdapter not available for summary: %s", exc)
        return {idx: {"error": str(exc)} for idx in index_names}

    for idx_name in index_names:
        try:
            chain = nse_adapter.get_option_chain(idx_name)
            if not chain:
                summary[idx_name] = {"error": "No data"}
                continue
            oi_data = _aggregate_oi_data(chain)
            summary[idx_name] = oi_data
        except (ValueError, TypeError, OSError, RuntimeError) as exc:
            summary[idx_name] = {"error": str(exc)}

    return summary


__all__ = [
    "get_oi_summary",
    "record_oi_snapshots_for_indices",
    "reset_nse_adapter_cache",
]

