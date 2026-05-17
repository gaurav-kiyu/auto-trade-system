"""
fetch_broker_data.py -- Download NSE historical OHLCV data from broker APIs.

Produces a CSV in the exact format expected by run_analysis.py / run_backtest.py:
    Columns: Datetime, Open, High, Low, Close, Volume

Supported sources (use --source to select):
    kite     -- Zerodha Kite Connect  (1m up to 60 days; 5m+ unlimited history)
    angel    -- Angel One SmartAPI    (1m up to 30 days;  5m up to 6 months)
    dhan     -- Dhan HQ               (1m up to 90 days;  day unlimited)

Usage examples:

  # Kite: last 60 days of 1m NIFTY bars
  python scripts/fetch_broker_data.py --source kite --api-key KEY --access-token TOK
      --days 60 --interval 1m --symbol NIFTY50 --out data/nifty_1m.csv

  # Angel One: last 30 days of 1m NIFTY bars
  python scripts/fetch_broker_data.py --source angel
      --api-key KEY --client-id ID --password PWD --totp TOTP_SECRET
      --days 30 --interval 1m --symbol NIFTY --out data/nifty_1m_angel.csv

  # Dhan: last 90 days of 1m NIFTY bars
  python scripts/fetch_broker_data.py --source dhan
      --client-id CLIENT_ID --access-token ACCESS_TOKEN
      --days 90 --interval 1m --out data/nifty_1m_dhan.csv

  # Then feed into the analyser
  python run_analysis.py data/nifty_1m.csv --threshold 65
  python run_backtest.py  data/nifty_1m.csv

Instrument tokens / identifiers used by default (NIFTY 50 index):
    Kite   : 256265   (NSE:NIFTY 50)
    Angel  : 99926000 (NSE:NIFTY 50)
    Dhan   : 13        (NSE NIFTY 50 index)
"""
from __future__ import annotations

import argparse
import csv
import sys
from collections.abc import Sequence
from datetime import date, datetime, timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
# Column schema produced by every fetch path
# ---------------------------------------------------------------------------
CSV_COLUMNS = ("Datetime", "Open", "High", "Low", "Close", "Volume")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _date_chunks(start: date, end: date, chunk_days: int) -> list[tuple[date, date]]:
    """Split [start, end] into chunks of at most chunk_days to stay within API limits."""
    chunks: list[tuple[date, date]] = []
    cur = start
    while cur <= end:
        chunk_end = min(cur + timedelta(days=chunk_days - 1), end)
        chunks.append((cur, chunk_end))
        cur = chunk_end + timedelta(days=1)
    return chunks


def _write_csv(rows: list[dict], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(CSV_COLUMNS))
        writer.writeheader()
        writer.writerows(rows)
    print(f"Saved {len(rows):,} bars to {out_path}")


# ---------------------------------------------------------------------------
# Zerodha Kite Connect
# ---------------------------------------------------------------------------

def _kite_interval(interval: str) -> str:
    mapping = {"1m": "minute", "5m": "5minute", "15m": "15minute",
               "30m": "30minute", "60m": "60minute", "1h": "60minute", "1d": "day"}
    v = mapping.get(interval.lower())
    if not v:
        raise ValueError(f"Kite: unsupported interval {interval!r}. Use: {list(mapping)}")
    return v


def fetch_kite(
    api_key: str,
    access_token: str,
    instrument_token: int,
    start: date,
    end: date,
    interval: str,
) -> list[dict]:
    try:
        from kiteconnect import KiteConnect  # type: ignore
    except ImportError:
        sys.exit("kiteconnect not installed. Run: pip install kiteconnect")

    kite = KiteConnect(api_key=api_key)
    kite.set_access_token(access_token)
    kite_interval = _kite_interval(interval)

    # Kite hard limit: 60-day window per call for minute data
    chunk_days = 60 if kite_interval == "minute" else 2000
    chunks = _date_chunks(start, end, chunk_days)

    rows: list[dict] = []
    for chunk_start, chunk_end in chunks:
        print(f"  Kite fetch {chunk_start} -> {chunk_end} ({kite_interval}) ...", end=" ", flush=True)
        data = kite.historical_data(
            instrument_token=instrument_token,
            from_date=datetime.combine(chunk_start, datetime.min.time()),
            to_date=datetime.combine(chunk_end, datetime.max.time().replace(microsecond=0)),
            interval=kite_interval,
            continuous=False,
            oi=False,
        )
        for bar in data:
            rows.append({
                "Datetime": bar["date"].strftime("%Y-%m-%d %H:%M:%S"),
                "Open":     round(float(bar["open"]),   2),
                "High":     round(float(bar["high"]),   2),
                "Low":      round(float(bar["low"]),    2),
                "Close":    round(float(bar["close"]),  2),
                "Volume":   int(bar["volume"]),
            })
        print(f"{len(data)} bars")

    # Sort and deduplicate (overlapping chunk boundaries)
    rows.sort(key=lambda r: r["Datetime"])
    seen: set[str] = set()
    deduped = []
    for r in rows:
        if r["Datetime"] not in seen:
            seen.add(r["Datetime"])
            deduped.append(r)
    return deduped


# ---------------------------------------------------------------------------
# Angel One SmartAPI
# ---------------------------------------------------------------------------

_ANGEL_SYMBOL_MAP = {
    "NIFTY":       ("NSE",   "99926000"),
    "NIFTY50":     ("NSE",   "99926000"),
    "BANKNIFTY":   ("NSE",   "99926009"),
    "FINNIFTY":    ("NSE",   "99926037"),
    "SENSEX":      ("BSE",   "99919000"),
}

_ANGEL_INTERVAL_MAP = {
    "1m":  "ONE_MINUTE",
    "3m":  "THREE_MINUTE",
    "5m":  "FIVE_MINUTE",
    "10m": "TEN_MINUTE",
    "15m": "FIFTEEN_MINUTE",
    "30m": "THIRTY_MINUTE",
    "1h":  "ONE_HOUR",
    "1d":  "ONE_DAY",
}


def fetch_angel(
    api_key: str,
    client_id: str,
    password: str,
    totp_secret: str,
    symbol: str,
    start: date,
    end: date,
    interval: str,
) -> list[dict]:
    try:
        import pyotp  # type: ignore
        from SmartApi import SmartConnect  # type: ignore
    except ImportError:
        sys.exit("Angel One dependencies not installed. Run: pip install smartapi-python pyotp")

    angel_interval = _ANGEL_INTERVAL_MAP.get(interval.lower())
    if not angel_interval:
        raise ValueError(f"Angel: unsupported interval {interval!r}. Use: {list(_ANGEL_INTERVAL_MAP)}")

    sym_upper = symbol.upper().replace(" ", "")
    if sym_upper not in _ANGEL_SYMBOL_MAP:
        raise ValueError(f"Angel: unknown symbol {symbol!r}. Add it to _ANGEL_SYMBOL_MAP.")
    exchange, token = _ANGEL_SYMBOL_MAP[sym_upper]

    totp_val = pyotp.TOTP(totp_secret).now()
    api = SmartConnect(api_key=api_key)
    session = api.generateSession(client_id, password, totp_val)
    if not session or "data" not in session:
        raise RuntimeError(f"Angel login failed: {session}")
    api.setAccessToken(session["data"]["jwtToken"])

    # Angel: max 30-day window per 1m call; 6-month for 5m
    chunk_days = 30 if interval.lower() == "1m" else 180
    chunks = _date_chunks(start, end, chunk_days)

    rows: list[dict] = []
    for chunk_start, chunk_end in chunks:
        from_str = datetime.combine(chunk_start, datetime.min.time()).strftime("%Y-%m-%d %H:%M")
        to_str   = datetime.combine(chunk_end,   datetime.max.time().replace(microsecond=0)).strftime("%Y-%m-%d %H:%M")
        print(f"  Angel fetch {chunk_start} -> {chunk_end} ({angel_interval}) ...", end=" ", flush=True)
        resp = api.getCandleData({
            "exchange":    exchange,
            "symboltoken": token,
            "interval":    angel_interval,
            "fromdate":    from_str,
            "todate":      to_str,
        })
        candles = (resp.get("data") or []) if isinstance(resp, dict) else []
        for bar in candles:
            # Angel returns [timestamp, open, high, low, close, volume]
            dt_str = bar[0][:19].replace("T", " ")
            rows.append({
                "Datetime": dt_str,
                "Open":     round(float(bar[1]), 2),
                "High":     round(float(bar[2]), 2),
                "Low":      round(float(bar[3]), 2),
                "Close":    round(float(bar[4]), 2),
                "Volume":   int(bar[5]),
            })
        print(f"{len(candles)} bars")

    rows.sort(key=lambda r: r["Datetime"])
    seen: set[str] = set()
    deduped: list[dict] = []
    for r in rows:
        if r["Datetime"] not in seen:
            seen.add(r["Datetime"])
            deduped.append(r)
    return deduped


# ---------------------------------------------------------------------------
# Dhan HQ
# ---------------------------------------------------------------------------

_DHAN_INTERVAL_MAP = {
    "1m":  "1",
    "5m":  "5",
    "15m": "15",
    "25m": "25",
    "1h":  "60",
    "1d":  "D",
}

_DHAN_NIFTY_SECURITY_ID  = "13"   # NSE NIFTY 50 index
_DHAN_BANKNIFTY_ID       = "25"
_DHAN_FINNIFTY_ID        = "27"

_DHAN_SYMBOL_MAP = {
    "NIFTY": _DHAN_NIFTY_SECURITY_ID,
    "NIFTY50": _DHAN_NIFTY_SECURITY_ID,
    "BANKNIFTY": _DHAN_BANKNIFTY_ID,
    "FINNIFTY": _DHAN_FINNIFTY_ID,
}


def fetch_dhan(
    client_id: str,
    access_token: str,
    symbol: str,
    start: date,
    end: date,
    interval: str,
) -> list[dict]:
    try:
        from dhanhq import dhanhq  # type: ignore
    except ImportError:
        sys.exit("dhanhq not installed. Run: pip install dhanhq")

    dhan_interval = _DHAN_INTERVAL_MAP.get(interval.lower())
    if not dhan_interval:
        raise ValueError(f"Dhan: unsupported interval {interval!r}. Use: {list(_DHAN_INTERVAL_MAP)}")

    sym_upper = symbol.upper().replace(" ", "")
    if sym_upper not in _DHAN_SYMBOL_MAP:
        raise ValueError(f"Dhan: unknown symbol {symbol!r}. Add it to _DHAN_SYMBOL_MAP.")
    security_id = _DHAN_SYMBOL_MAP[sym_upper]

    dhan = dhanhq(client_id, access_token)

    # Dhan: max 90 days per 1m call
    chunk_days = 90
    chunks = _date_chunks(start, end, chunk_days)

    rows: list[dict] = []
    for chunk_start, chunk_end in chunks:
        from_str = chunk_start.strftime("%Y-%m-%d")
        to_str   = chunk_end.strftime("%Y-%m-%d")
        print(f"  Dhan fetch {chunk_start} -> {chunk_end} ({dhan_interval}m) ...", end=" ", flush=True)
        resp = dhan.historical_minute_charts(
            symbol=sym_upper,
            exchange_segment=dhan.NSE,
            instrument_type="INDEX",
            expiry_code=0,
            from_date=from_str,
            to_date=to_str,
        )
        candles = resp.get("data", {}).get("candles", []) if isinstance(resp, dict) else []
        for bar in candles:
            # Dhan returns [timestamp_epoch_ms, open, high, low, close, volume]
            dt = datetime.fromtimestamp(int(bar[0]) / 1000)
            rows.append({
                "Datetime": dt.strftime("%Y-%m-%d %H:%M:%S"),
                "Open":     round(float(bar[1]), 2),
                "High":     round(float(bar[2]), 2),
                "Low":      round(float(bar[3]), 2),
                "Close":    round(float(bar[4]), 2),
                "Volume":   int(bar[5]),
            })
        print(f"{len(candles)} bars")

    rows.sort(key=lambda r: r["Datetime"])
    seen: set[str] = set()
    deduped: list[dict] = []
    for r in rows:
        if r["Datetime"] not in seen:
            seen.add(r["Datetime"])
            deduped.append(r)
    return deduped


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse(argv: Sequence[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Download NSE historical OHLCV data -> CSV for run_analysis.py / run_backtest.py",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--source", choices=["kite", "angel", "dhan"], required=True,
                   help="Broker data source")
    p.add_argument("--symbol", default="NIFTY50",
                   help="Index symbol: NIFTY50, BANKNIFTY, FINNIFTY (default: NIFTY50)")
    p.add_argument("--interval", default="1m",
                   help="Bar interval: 1m, 5m, 15m, 1h, 1d (default: 1m)")
    p.add_argument("--days", type=int, default=60,
                   help="Number of calendar days to fetch back from today (default: 60)")
    p.add_argument("--from-date", default=None,
                   help="Start date YYYY-MM-DD (overrides --days)")
    p.add_argument("--to-date", default=None,
                   help="End date YYYY-MM-DD (default: today)")
    p.add_argument("--out", default=None,
                   help="Output CSV path (default: data/<symbol>_<interval>_<source>.csv)")
    # Kite auth
    p.add_argument("--api-key",      default=None, help="API key (Kite/Angel)")
    p.add_argument("--access-token", default=None, help="Access token (Kite/Dhan)")
    p.add_argument("--instrument-token", type=int, default=256265,
                   help="Kite instrument token for index (default: 256265 = NSE:NIFTY 50)")
    # Angel auth
    p.add_argument("--client-id",  default=None, help="Client ID (Angel/Dhan)")
    p.add_argument("--password",   default=None, help="Angel One login password")
    p.add_argument("--totp",       default=None, help="Angel One TOTP secret (base32)")
    return p.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    args = _parse(argv)

    to_dt   = date.fromisoformat(args.to_date)   if args.to_date   else date.today()
    from_dt = date.fromisoformat(args.from_date) if args.from_date else (to_dt - timedelta(days=args.days - 1))

    out_path = Path(args.out) if args.out else (
        Path("data") / f"{args.symbol.upper()}_{args.interval}_{args.source}.csv"
    )

    print(f"Fetching {args.symbol} {args.interval} bars from {from_dt} to {to_dt} via {args.source} ...")

    if args.source == "kite":
        if not args.api_key or not args.access_token:
            sys.exit("Kite requires --api-key and --access-token")
        rows = fetch_kite(
            api_key=args.api_key,
            access_token=args.access_token,
            instrument_token=args.instrument_token,
            start=from_dt, end=to_dt,
            interval=args.interval,
        )

    elif args.source == "angel":
        for req in ("api_key", "client_id", "password", "totp"):
            if not getattr(args, req.replace("-", "_")):
                sys.exit(f"Angel One requires --{req.replace('_','-')}")
        rows = fetch_angel(
            api_key=args.api_key,
            client_id=args.client_id,
            password=args.password,
            totp_secret=args.totp,
            symbol=args.symbol,
            start=from_dt, end=to_dt,
            interval=args.interval,
        )

    elif args.source == "dhan":
        if not args.client_id or not args.access_token:
            sys.exit("Dhan requires --client-id and --access-token")
        rows = fetch_dhan(
            client_id=args.client_id,
            access_token=args.access_token,
            symbol=args.symbol,
            start=from_dt, end=to_dt,
            interval=args.interval,
        )

    else:
        sys.exit(f"Unknown source: {args.source}")

    if not rows:
        print("No bars returned. Check credentials, symbol, and date range.")
        sys.exit(1)

    _write_csv(rows, out_path)
    print()
    print("Next steps:")
    print(f"  python run_analysis.py {out_path}  --threshold 65")
    print(f"  python run_backtest.py  {out_path}")


if __name__ == "__main__":
    main()
