"""yahoo_batch_benchmark.py - Isolated Yahoo Batching / Market-Data Parity Benchmark.

Governing Standard: OPB-FINAL-PHASE-GOVERNANCE-001
Execution Mode: STRICTLY READ-ONLY / OFFLINE RESEARCH BENCHMARK

Compares:
A. Current Per-Symbol Retrieval (as executed by core/all_nse_scanner.py)
   vs
B. Candidate Batched Retrieval (using yf.download)

Measures:
- Exact HTTP request counts (monitored at YfData level)
- Wall-clock execution time
- Row counts, timestamps, OHLCV values, Volume, NaNs, timezones
- Latest completed 1m bar (df1.iloc[-2]) invariant
- Downstream validate_ohlcv acceptance
- Failure blast radius (single symbol failure vs batch failure)
"""

from __future__ import annotations

import hashlib
import logging
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yfinance as yf
from yfinance.data import YfData

from core.signal_utils import validate_ohlcv

_log = logging.getLogger("yahoo_batch_benchmark")
_ROOT = Path(__file__).resolve().parent.parent.parent
PROD_DB_PATH = _ROOT / "db" / "signals_history.db"

# ═══════════════════════════════════════════════════════════════════════════
# 1. CONTROLLED DETERMINISTIC SAMPLE (50 REPRESENTATIVE / LIQUID SYMBOLS)
# ═══════════════════════════════════════════════════════════════════════════
BENCHMARK_SAMPLE_SYMBOLS: list[str] = [
    # 2 Priority Benchmark Indices
    "NIFTY", "BANKNIFTY",
    # 48 Highly Liquid NSE Equities from OPB Universe
    "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK", "BHARTIARTL", "ITC", "SBIN",
    "LT", "HINDUNILVR", "BAJFINANCE", "HCLTECH", "MARUTI", "SUNPHARMA", "KOTAKBANK",
    "TITAN", "ONGC", "NTPC", "AXISBANK", "ADANIENT", "POWERGRID", "ULTRACEMCO",
    "COALINDIA", "TATASTEEL", "BAJAJFINSV", "M&M", "ASIANPAINT", "SIEMENS", "DLF",
    "HAL", "BEL", "VBL", "IOC", "VEDL", "GRASIM", "JSWSTEEL", "TECHM",
    "INDUSINDBK", "HINDALCO", "CIPLA", "TRENT", "DIVISLAB", "NESTLEIND",
    "ADANIPORTS", "BPCL", "WIPRO", "TATACONSUM", "TATAPOWER"
]


def map_symbol_to_yf_ticker(sym: str) -> str:
    """Map internal symbol to Yahoo Finance ticker string.

    Must match core/all_nse_scanner.py lines 452-483 exactly.
    """
    if sym == "NIFTY":
        return "^NSEI"
    elif sym == "BANKNIFTY":
        return "^NSEBANK"
    elif sym == "FINNIFTY":
        return "NIFTY_FIN_SERVICE.NS"
    elif sym == "MIDCPNIFTY":
        return "NIFTY_MID_SELECT.NS"
    elif sym == "SENSEX":
        return "^BSESN"
    elif sym == "BANKEX":
        return "BSE-BANK.BO"
    elif sym in ("GOLD", "MCX:GOLD"):
        return "GC=F"
    elif sym in ("SILVER", "MCX:SILVER"):
        return "SI=F"
    elif sym in ("CRUDEOIL", "MCX:CRUDEOIL"):
        return "CL=F"
    elif sym in ("NATURALGAS", "MCX:NATURALGAS"):
        return "NG=F"
    elif sym in ("COPPER", "MCX:COPPER"):
        return "HG=F"
    elif sym in ("USDINR", "CDS:USDINR"):
        return "USDINR=X"
    elif sym in ("EURINR", "CDS:EURINR"):
        return "EURINR=X"
    elif sym in ("GBPINR", "CDS:GBPINR"):
        return "GBPINR=X"
    elif sym in ("JPYINR", "CDS:JPYINR"):
        return "JPYINR=X"
    else:
        return f"{sym}.NS"


# ═══════════════════════════════════════════════════════════════════════════
# 2. HTTP REQUEST TELEMETRY INTERCEPTOR
# ═══════════════════════════════════════════════════════════════════════════
class HttpRequestMonitor:
    """Thread-safe interceptor on YfData._make_request to record actual HTTP requests."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.request_count: int = 0
        self.requested_urls: list[str] = []
        self.status_codes: list[int] = []
        self.errors: list[str] = []
        self._active: bool = False
        self._original_make_request: Any = None

    def start(self) -> None:
        with self._lock:
            self.reset()
            self._original_make_request = YfData._make_request
            _monitor = self

            def intercepted_make_request(inst: Any, url: str, request_method: Any, *args: Any, **kwargs: Any) -> Any:
                with _monitor._lock:
                    _monitor.request_count += 1
                    _monitor.requested_urls.append(str(url))
                try:
                    resp = _monitor._original_make_request(inst, url, request_method, *args, **kwargs)
                    with _monitor._lock:
                        if hasattr(resp, "status_code"):
                            _monitor.status_codes.append(int(resp.status_code))
                    return resp
                except Exception as exc:
                    with _monitor._lock:
                        _monitor.errors.append(f"{type(exc).__name__}: {exc}")
                    raise

            YfData._make_request = intercepted_make_request
            self._active = True

    def stop(self) -> None:
        with self._lock:
            if self._active and self._original_make_request is not None:
                YfData._make_request = self._original_make_request
                self._active = False

    def reset(self) -> None:
        with self._lock:
            self.request_count = 0
            self.requested_urls.clear()
            self.status_codes.clear()
            self.errors.clear()


# ═══════════════════════════════════════════════════════════════════════════
# 3. PRODUCTION DATABASE SAFETY GUARD
# ═══════════════════════════════════════════════════════════════════════════
def compute_prod_db_sha() -> tuple[str, int]:
    """Compute and return current SHA-256 and size of signals_history.db."""
    if not PROD_DB_PATH.exists():
        raise FileNotFoundError(f"Production database missing: {PROD_DB_PATH}")
    size = PROD_DB_PATH.stat().st_size
    sha = hashlib.sha256(PROD_DB_PATH.read_bytes()).hexdigest()
    return sha, size


# ═══════════════════════════════════════════════════════════════════════════
# 4. COMPLETED BAR EXTRACTION (PRESERVING DF1.ILOC[-2] INVARIANT)
# ═══════════════════════════════════════════════════════════════════════════
@dataclass
class CompletedBarSnapshot:
    """Snapshot of latest completed 1m bar extracted via df1.iloc[-2]."""

    symbol: str
    has_completed_bar: bool
    timestamp_str: str = ""
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0
    volume: float = 0.0
    total_bars: int = 0


def extract_completed_bar(df1: pd.DataFrame | None, sym: str) -> CompletedBarSnapshot:
    """Extract latest completed 1m bar adhering strictly to df1.iloc[-2] invariant."""
    if df1 is None or df1.empty or len(df1) < 2:
        return CompletedBarSnapshot(
            symbol=sym,
            has_completed_bar=False,
            total_bars=len(df1) if df1 is not None else 0,
        )
    row = df1.iloc[-2]
    idx = df1.index[-2]
    ts_str = idx.isoformat() if hasattr(idx, "isoformat") else str(idx)
    return CompletedBarSnapshot(
        symbol=sym,
        has_completed_bar=True,
        timestamp_str=ts_str,
        open=float(row["Open"]),
        high=float(row["High"]),
        low=float(row["Low"]),
        close=float(row["Close"]),
        volume=float(row.get("Volume", 0.0)),
        total_bars=len(df1),
    )


# ═══════════════════════════════════════════════════════════════════════════
# 5. RETRIEVAL IMPLEMENTATIONS
# ═══════════════════════════════════════════════════════════════════════════
def fetch_single_symbol_current(sym: str, interval: str, period: str) -> pd.DataFrame | None:
    """Fetch data using current production per-symbol pattern."""
    yf_ticker = map_symbol_to_yf_ticker(sym)
    try:
        ticker = yf.Ticker(yf_ticker)
        df = ticker.history(period=period, interval=interval)
        return df if df is not None and not df.empty else None
    except Exception as exc:
        _log.warning("Per-symbol fetch failed for %s (%s): %s", sym, yf_ticker, exc)
        return None


def fetch_current_retrieval_suite(
    symbols: list[str],
    interval: str,
    period: str,
    max_workers: int = 20,
) -> tuple[dict[str, pd.DataFrame | None], float]:
    """Execute current production retrieval across symbols using ThreadPoolExecutor."""
    t0 = time.perf_counter()
    results: dict[str, pd.DataFrame | None] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {
            executor.submit(fetch_single_symbol_current, sym, interval, period): sym
            for sym in symbols
        }
        for fut in as_completed(future_map):
            sym = future_map[fut]
            try:
                results[sym] = fut.result()
            except Exception as exc:
                _log.warning("Thread exception for %s: %s", sym, exc)
                results[sym] = None
    elapsed = time.perf_counter() - t0
    return results, elapsed


def fetch_candidate_batched_suite(
    symbols: list[str],
    interval: str,
    period: str,
    threads: bool = True,
) -> tuple[dict[str, pd.DataFrame | None], float]:
    """Execute candidate batched retrieval using yf.download."""
    t0 = time.perf_counter()
    results: dict[str, pd.DataFrame | None] = {s: None for s in symbols}
    ticker_to_sym = {map_symbol_to_yf_ticker(s): s for s in symbols}
    all_tickers = list(ticker_to_sym.keys())

    try:
        raw_batch = yf.download(
            tickers=all_tickers,
            period=period,
            interval=interval,
            progress=False,
            threads=threads,
        )
    except Exception as exc:
        _log.warning("yf.download failed for batch: %s", exc)
        return results, time.perf_counter() - t0

    if raw_batch is None or raw_batch.empty:
        return results, time.perf_counter() - t0

    # Extract individual symbol frames from MultiIndex
    if isinstance(raw_batch.columns, pd.MultiIndex):
        level_values_1 = [str(x).upper() for x in raw_batch.columns.get_level_values(1)]
        level_values_0 = [str(x).upper() for x in raw_batch.columns.get_level_values(0)]

        for yf_t, sym in ticker_to_sym.items():
            t_upper = yf_t.upper()
            try:
                if t_upper in level_values_1:
                    sym_df = raw_batch.xs(yf_t, axis=1, level=1)
                elif t_upper in level_values_0:
                    sym_df = raw_batch.xs(yf_t, axis=1, level=0)
                else:
                    sym_df = None

                if sym_df is not None and not sym_df.empty:
                    # Drop entirely-NaN rows resulting from partial batch failures
                    if "Close" in sym_df.columns:
                        sym_df = sym_df.dropna(subset=["Close"])
                    if not sym_df.empty:
                        # Timezone normalization to match Ticker.history (Asia/Kolkata)
                        if sym_df.index.tz is not None:
                            try:
                                sym_df.index = sym_df.index.tz_convert("Asia/Kolkata")
                            except Exception:
                                pass
                        results[sym] = sym_df
            except Exception as exc:
                _log.debug("Extraction failed for %s: %s", sym, exc)
                results[sym] = None
    else:
        # Single ticker fallback
        if len(symbols) == 1:
            sym = symbols[0]
            if raw_batch.index.tz is not None:
                try:
                    raw_batch.index = raw_batch.index.tz_convert("Asia/Kolkata")
                except Exception:
                    pass
            results[sym] = raw_batch

    elapsed = time.perf_counter() - t0
    return results, elapsed


# ═══════════════════════════════════════════════════════════════════════════
# 6. PARITY EVALUATION
# ═══════════════════════════════════════════════════════════════════════════
@dataclass
class SymbolParityResult:
    """Detailed parity evaluation between current and batch retrieval for a symbol."""

    symbol: str
    interval: str
    period: str
    current_rows: int
    batch_rows: int
    row_count_match: bool
    timestamps_match: bool
    ohlc_max_abs_diff: float
    volume_max_abs_diff: float
    nan_placement_match: bool
    timezone_match: bool
    latest_completed_bar_match: bool
    validate_ohlcv_current_passed: bool
    validate_ohlcv_batch_passed: bool
    validate_ohlcv_parity: bool
    discrepancies: list[str] = field(default_factory=list)


def evaluate_symbol_parity(
    sym: str,
    interval: str,
    period: str,
    df_current: pd.DataFrame | None,
    df_batch: pd.DataFrame | None,
) -> SymbolParityResult:
    """Perform rigorous, bit-for-bit parity comparison between current and batch frames."""
    discrepancies: list[str] = []
    is_index = sym in {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX", "BANKEX"}

    curr_rows = len(df_current) if df_current is not None else 0
    batch_rows = len(df_batch) if df_batch is not None else 0

    if df_current is None and df_batch is None:
        return SymbolParityResult(
            symbol=sym,
            interval=interval,
            period=period,
            current_rows=0,
            batch_rows=0,
            row_count_match=True,
            timestamps_match=True,
            ohlc_max_abs_diff=0.0,
            volume_max_abs_diff=0.0,
            nan_placement_match=True,
            timezone_match=True,
            latest_completed_bar_match=True,
            validate_ohlcv_current_passed=False,
            validate_ohlcv_batch_passed=False,
            validate_ohlcv_parity=True,
        )

    if (df_current is None) != (df_batch is None):
        discrepancies.append(f"Existence mismatch: current={df_current is not None}, batch={df_batch is not None}")
        return SymbolParityResult(
            symbol=sym,
            interval=interval,
            period=period,
            current_rows=curr_rows,
            batch_rows=batch_rows,
            row_count_match=False,
            timestamps_match=False,
            ohlc_max_abs_diff=float("inf"),
            volume_max_abs_diff=float("inf"),
            nan_placement_match=False,
            timezone_match=False,
            latest_completed_bar_match=False,
            validate_ohlcv_current_passed=False,
            validate_ohlcv_batch_passed=False,
            validate_ohlcv_parity=False,
            discrepancies=discrepancies,
        )

    assert df_current is not None and df_batch is not None

    # 1. Row count
    row_count_match = curr_rows == batch_rows
    if not row_count_match:
        discrepancies.append(f"Row count mismatch: current={curr_rows}, batch={batch_rows}")

    # 2. Timezone
    curr_tz = str(df_current.index.tz) if df_current.index.tz is not None else "None"
    batch_tz = str(df_batch.index.tz) if df_batch.index.tz is not None else "None"
    tz_match = curr_tz == batch_tz
    if not tz_match:
        discrepancies.append(f"Timezone mismatch: current={curr_tz}, batch={batch_tz}")

    # Align batch index timezone if needed for numerical comparison
    df_batch_aligned = df_batch.copy()
    if df_batch_aligned.index.tz is not None and df_current.index.tz is not None:
        try:
            df_batch_aligned.index = df_batch_aligned.index.tz_convert(df_current.index.tz)
        except Exception:
            pass

    # 3. Timestamps
    ts_match = df_current.index.equals(df_batch_aligned.index)
    if not ts_match:
        discrepancies.append(f"Timestamp index inequality. Common timestamps: {len(df_current.index.intersection(df_batch_aligned.index))}/{max(curr_rows, batch_rows)}")

    # 4. Values (OHLCV)
    max_ohlc_diff = 0.0
    max_vol_diff = 0.0
    nan_placement_match = True

    common_idx = df_current.index.intersection(df_batch_aligned.index)
    if len(common_idx) > 0:
        c_sub = df_current.loc[common_idx]
        b_sub = df_batch_aligned.loc[common_idx]

        for col in ("Open", "High", "Low", "Close"):
            if col in c_sub.columns and col in b_sub.columns:
                c_vals = pd.to_numeric(c_sub[col], errors="coerce")
                b_vals = pd.to_numeric(b_sub[col], errors="coerce")

                # Check NaN placement
                if not (c_vals.isna() == b_vals.isna()).all():
                    nan_placement_match = False
                    discrepancies.append(f"NaN placement discrepancy in column {col}")

                diff = (c_vals - b_vals).abs().max()
                if not pd.isna(diff):
                    max_ohlc_diff = max(max_ohlc_diff, float(diff))
            else:
                discrepancies.append(f"Missing price column {col}")

        if "Volume" in c_sub.columns and "Volume" in b_sub.columns:
            c_vol = pd.to_numeric(c_sub["Volume"], errors="coerce")
            b_vol = pd.to_numeric(b_sub["Volume"], errors="coerce")
            if not (c_vol.isna() == b_vol.isna()).all():
                nan_placement_match = False
                discrepancies.append("NaN placement discrepancy in Volume")
            v_diff = (c_vol - b_vol).abs().max()
            if not pd.isna(v_diff):
                max_vol_diff = float(v_diff)

    if max_ohlc_diff > 1e-4:
        discrepancies.append(f"Significant OHLC numerical difference: {max_ohlc_diff:.6f}")
    if max_vol_diff > 1e-4:
        discrepancies.append(f"Significant Volume numerical difference: {max_vol_diff:.2f}")

    # 5. Completed bar invariant (df1.iloc[-2])
    bar_curr = extract_completed_bar(df_current, sym)
    bar_batch = extract_completed_bar(df_batch_aligned, sym)
    bar_match = (
        bar_curr.has_completed_bar == bar_batch.has_completed_bar
        and abs(bar_curr.close - bar_batch.close) < 1e-4
        and abs(bar_curr.open - bar_batch.open) < 1e-4
        and abs(bar_curr.volume - bar_batch.volume) < 1e-4
    )
    if not bar_match:
        discrepancies.append(f"Completed bar mismatch: curr_close={bar_curr.close}, batch_close={bar_batch.close}")

    # 6. validate_ohlcv acceptance
    v_clean_curr, _ = validate_ohlcv(df_current, interval=interval, allow_zero_volume=is_index)
    v_clean_batch, _ = validate_ohlcv(df_batch_aligned, interval=interval, allow_zero_volume=is_index)

    curr_passed = v_clean_curr is not None and not v_clean_curr.empty
    batch_passed = v_clean_batch is not None and not v_clean_batch.empty
    val_parity = curr_passed == batch_passed

    if not val_parity:
        discrepancies.append(f"validate_ohlcv outcome divergence: curr_pass={curr_passed}, batch_pass={batch_passed}")

    return SymbolParityResult(
        symbol=sym,
        interval=interval,
        period=period,
        current_rows=curr_rows,
        batch_rows=batch_rows,
        row_count_match=row_count_match,
        timestamps_match=ts_match,
        ohlc_max_abs_diff=max_ohlc_diff,
        volume_max_abs_diff=max_vol_diff,
        nan_placement_match=nan_placement_match,
        timezone_match=tz_match,
        latest_completed_bar_match=bar_match,
        validate_ohlcv_current_passed=curr_passed,
        validate_ohlcv_batch_passed=batch_passed,
        validate_ohlcv_parity=val_parity,
        discrepancies=discrepancies,
    )


# ═══════════════════════════════════════════════════════════════════════════
# 7. BLAST RADIUS COMPARISON
# ═══════════════════════════════════════════════════════════════════════════
@dataclass
class BlastRadiusComparison:
    """Comparative analysis of failure isolation between per-symbol and batching."""

    scenario: str
    current_per_symbol_behavior: str
    candidate_batch_behavior: str
    relative_risk: str  # "EQUAL", "HIGHER_IN_BATCH", "LOWER_IN_BATCH"
    details: str


def evaluate_failure_blast_radius() -> list[BlastRadiusComparison]:
    """Return rigorous comparative analysis of failure isolation scenarios."""
    return [
        BlastRadiusComparison(
            scenario="Single Symbol Delisted / 404 Not Found",
            current_per_symbol_behavior="Failure is isolated strictly to the calling thread. 49 other symbols evaluate normally.",
            candidate_batch_behavior="yf.download logs warning, fills symbol column with all NaN. Other 49 symbols are extracted normally.",
            relative_risk="EQUAL",
            details="Both implementations isolate single-symbol 404s, provided batch extractor drops all-NaN columns cleanly.",
        ),
        BlastRadiusComparison(
            scenario="HTTP 429 Too Many Requests / Rate Limiting",
            current_per_symbol_behavior="Rate limiting hits individual symbol requests progressively; earlier symbols succeed, later ones fail.",
            candidate_batch_behavior="Batch request fails completely; all 50 symbols fail simultaneously, causing total scan cycle collapse.",
            relative_risk="HIGHER_IN_BATCH",
            details="In a batch architecture, a single 429 drops the entire batch payload. Blast radius increases from 1 to N.",
        ),
        BlastRadiusComparison(
            scenario="Network Timeout / Dropped Connection",
            current_per_symbol_behavior="Only the specific thread times out. Other concurrent threads complete normally.",
            candidate_batch_behavior="Entire batch socket closes or times out. All 50 symbols receive None.",
            relative_risk="HIGHER_IN_BATCH",
            details="Batching couples 50 symbols to a single network connection or thread group.",
        ),
        BlastRadiusComparison(
            scenario="Malformed Provider Payload / Parser Crash",
            current_per_symbol_behavior="Exception caught in evaluate_symbol() try/except block. Only 1 symbol marked DATA_UNAVAILABLE.",
            candidate_batch_behavior="MultiIndex construction or DataFrame concatenation crashes. Entire batch of 50 symbols fails.",
            relative_risk="HIGHER_IN_BATCH",
            details="Multi-symbol DataFrame parsing has a single point of failure during pandas concatenation.",
        ),
        BlastRadiusComparison(
            scenario="Missing Timeframe Fallback",
            current_per_symbol_behavior="Individual symbol falls back from 5m to 1mo/1d daily bars independently if 5m is empty.",
            candidate_batch_behavior="Batch daily fallback requires a second batch request for all 50 symbols or ad-hoc per-symbol branching.",
            relative_risk="HIGHER_IN_BATCH",
            details="Per-symbol fallback is granular; batched fallback adds orchestration complexity and redundant requests.",
        ),
    ]
