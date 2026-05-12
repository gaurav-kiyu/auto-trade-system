"""
UNIFIED REAL-TIME TRADING DASHBOARD v1.1
═════════════════════════════════════════
Flask + Socket.IO server connecting both Stock and Index data
into a single live dashboard.  All prices, indicators, and levels
are calculated dynamically from OHLCV data — zero hardcoded values.

Data: REST polling via yfinance (5s configurable interval)
      WebSocket push to browser via Socket.IO
UI  : templates/dashboard.html  (served by Flask)

Usage:
    python dashboard_server.py                  # default port 5100, bind 127.0.0.1 if host omitted
    python dashboard_server.py --port 8080      # custom port
    python dashboard_server.py --debug           # debug mode
    LAN only if needed: set DASHBOARD_HOST to 0.0.0.0 in dashboard_config.json (exposes the service).
"""

import os, sys, json, time, threading, logging, argparse, signal as _signal
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FuturesTimeoutError
from pathlib import Path

import pandas as pd
import yfinance as yf

try:
    from flask import Flask, render_template, jsonify
    from flask_socketio import SocketIO, emit
    _FLASK_OK = True
except ImportError:
    _FLASK_OK = False
    print("[FATAL] Flask and flask-socketio required.  Run: pip install flask flask-socketio")
    sys.exit(1)

from signal_engine import build_full_signal, validate_ohlcv, explain_signal
from telegram_engine import TelegramEngine
from core.index_map_loader import load_index_map
from core.time_provider import time_provider

# ═══════════════════════════════════════════════════════════════
# CONSTANTS + CONFIG
# ═══════════════════════════════════════════════════════════════

IST = timezone(timedelta(hours=5, minutes=30))
VERSION = "1.1"
BASE_DIR = Path(__file__).parent
CONFIG_FILE = BASE_DIR / "dashboard_config.json"

NSE_HOLIDAYS = {
    "2026-01-26","2026-03-14","2026-03-30","2026-03-31","2026-04-03",
    "2026-04-14","2026-04-18","2026-05-01","2026-08-15","2026-08-27",
    "2026-10-02","2026-10-20","2026-10-21","2026-11-09","2026-11-12",
    "2026-12-25",
}

STOCK_MAP = {
    "RELIANCE":   {"yf":"RELIANCE.NS","nse":"RELIANCE","lot":250,"step":20,"sector":"ENERGY","tags":["BLUE_CHIP","LONG_TERM"],"div_yield":0.7,"category":"LARGE_CAP"},
    "TCS":        {"yf":"TCS.NS","nse":"TCS","lot":175,"step":50,"sector":"IT","tags":["BLUE_CHIP","DIVIDEND","BONUS"],"div_yield":1.5,"category":"LARGE_CAP"},
    "INFY":       {"yf":"INFY.NS","nse":"INFY","lot":400,"step":20,"sector":"IT","tags":["BLUE_CHIP","DIVIDEND","BONUS"],"div_yield":2.5,"category":"LARGE_CAP"},
    "HDFCBANK":   {"yf":"HDFCBANK.NS","nse":"HDFCBANK","lot":550,"step":20,"sector":"BANK","tags":["BLUE_CHIP","LONG_TERM"],"div_yield":1.1,"category":"LARGE_CAP"},
    "ICICIBANK":  {"yf":"ICICIBANK.NS","nse":"ICICIBANK","lot":700,"step":20,"sector":"BANK","tags":["BLUE_CHIP","LONG_TERM","DIVIDEND"],"div_yield":0.8,"category":"LARGE_CAP"},
    "SBIN":       {"yf":"SBIN.NS","nse":"SBIN","lot":750,"step":10,"sector":"BANK","tags":["BLUE_CHIP","DIVIDEND","SHORT_TERM"],"div_yield":1.8,"category":"LARGE_CAP"},
    "BHARTIARTL": {"yf":"BHARTIARTL.NS","nse":"BHARTIARTL","lot":475,"step":20,"sector":"TELECOM","tags":["BLUE_CHIP","LONG_TERM"],"div_yield":0.5,"category":"LARGE_CAP"},
    "ITC":        {"yf":"ITC.NS","nse":"ITC","lot":1600,"step":5,"sector":"FMCG","tags":["DIVIDEND","BLUE_CHIP","LONG_TERM","PENNY"],"div_yield":3.2,"category":"LARGE_CAP"},
    "KOTAKBANK":  {"yf":"KOTAKBANK.NS","nse":"KOTAKBANK","lot":400,"step":20,"sector":"BANK","tags":["BLUE_CHIP","LONG_TERM"],"div_yield":0.1,"category":"LARGE_CAP"},
    "LT":         {"yf":"LT.NS","nse":"LT","lot":150,"step":50,"sector":"INFRA","tags":["BLUE_CHIP","LONG_TERM"],"div_yield":1.0,"category":"LARGE_CAP"},
    "HINDUNILVR": {"yf":"HINDUNILVR.NS","nse":"HINDUNILVR","lot":300,"step":20,"sector":"FMCG","tags":["BLUE_CHIP","DIVIDEND","LONG_TERM"],"div_yield":1.6,"category":"LARGE_CAP"},
    "BAJFINANCE": {"yf":"BAJFINANCE.NS","nse":"BAJFINANCE","lot":125,"step":100,"sector":"NBFC","tags":["SHORT_TERM","LONG_TERM"],"div_yield":0.4,"category":"LARGE_CAP"},
    "AXISBANK":   {"yf":"AXISBANK.NS","nse":"AXISBANK","lot":625,"step":20,"sector":"BANK","tags":["SHORT_TERM","BLUE_CHIP"],"div_yield":0.1,"category":"LARGE_CAP"},
    "MARUTI":     {"yf":"MARUTI.NS","nse":"MARUTI","lot":100,"step":100,"sector":"AUTO","tags":["BLUE_CHIP","DIVIDEND"],"div_yield":0.9,"category":"LARGE_CAP"},
    "TITAN":      {"yf":"TITAN.NS","nse":"TITAN","lot":375,"step":20,"sector":"CONSUMER","tags":["LONG_TERM","BLUE_CHIP"],"div_yield":0.3,"category":"LARGE_CAP"},
    "SUNPHARMA":  {"yf":"SUNPHARMA.NS","nse":"SUNPHARMA","lot":700,"step":20,"sector":"PHARMA","tags":["LONG_TERM","SHORT_TERM"],"div_yield":0.5,"category":"MID_CAP"},
    "NTPC":       {"yf":"NTPC.NS","nse":"NTPC","lot":2250,"step":5,"sector":"POWER","tags":["DIVIDEND","LONG_TERM","BONUS","PENNY"],"div_yield":3.5,"category":"MID_CAP"},
    "POWERGRID":  {"yf":"POWERGRID.NS","nse":"POWERGRID","lot":2700,"step":5,"sector":"POWER","tags":["DIVIDEND","LONG_TERM","BONUS","PENNY"],"div_yield":4.5,"category":"MID_CAP"},
    "EICHERMOT":  {"yf":"EICHERMOT.NS","nse":"EICHERMOT","lot":350,"step":25,"sector":"AUTO","tags":["BLUE_CHIP","LONG_TERM"],"div_yield":0.5,"category":"LARGE_CAP"},
    "M&M":        {"yf":"M&M.NS","nse":"M&M","lot":350,"step":20,"sector":"AUTO","tags":["BLUE_CHIP","LONG_TERM","DIVIDEND"],"div_yield":0.8,"category":"LARGE_CAP"},
    "WIPRO":      {"yf":"WIPRO.NS","nse":"WIPRO","lot":1500,"step":5,"sector":"IT","tags":["DIVIDEND","BONUS","BLUE_CHIP","PENNY"],"div_yield":0.2,"category":"LARGE_CAP"},
    "HCLTECH":    {"yf":"HCLTECH.NS","nse":"HCLTECH","lot":350,"step":20,"sector":"IT","tags":["DIVIDEND","BONUS","BLUE_CHIP"],"div_yield":3.8,"category":"LARGE_CAP"},
    "TATASTEEL":  {"yf":"TATASTEEL.NS","nse":"TATASTEEL","lot":5500,"step":2,"sector":"METAL","tags":["SHORT_TERM","DIVIDEND","BONUS","PENNY"],"div_yield":2.5,"category":"MID_CAP"},
    "COALINDIA":  {"yf":"COALINDIA.NS","nse":"COALINDIA","lot":2100,"step":5,"sector":"MINING","tags":["DIVIDEND","BONUS","PENNY"],"div_yield":5.0,"category":"MID_CAP"},
    "ADANIENT":   {"yf":"ADANIENT.NS","nse":"ADANIENT","lot":500,"step":20,"sector":"CONGLOM","tags":["SHORT_TERM"],"div_yield":0.1,"category":"LARGE_CAP"},
    "ADANIPORTS": {"yf":"ADANIPORTS.NS","nse":"ADANIPORTS","lot":800,"step":10,"sector":"INFRA","tags":["SHORT_TERM","LONG_TERM"],"div_yield":0.5,"category":"LARGE_CAP"},
    "ONGC":       {"yf":"ONGC.NS","nse":"ONGC","lot":3250,"step":5,"sector":"ENERGY","tags":["DIVIDEND","BONUS","PENNY"],"div_yield":4.0,"category":"MID_CAP"},
    "JSWSTEEL":   {"yf":"JSWSTEEL.NS","nse":"JSWSTEEL","lot":675,"step":10,"sector":"METAL","tags":["SHORT_TERM"],"div_yield":0.8,"category":"MID_CAP"},
    "TECHM":      {"yf":"TECHM.NS","nse":"TECHM","lot":600,"step":20,"sector":"IT","tags":["SHORT_TERM","BONUS"],"div_yield":1.8,"category":"MID_CAP"},
    "INDUSINDBK": {"yf":"INDUSINDBK.NS","nse":"INDUSINDBK","lot":500,"step":20,"sector":"BANK","tags":["SHORT_TERM"],"div_yield":0.5,"category":"MID_CAP"},
    "BAJAJFINSV": {"yf":"BAJAJFINSV.NS","nse":"BAJAJFINSV","lot":500,"step":20,"sector":"NBFC","tags":["LONG_TERM","BLUE_CHIP"],"div_yield":0.1,"category":"LARGE_CAP"},
    "ASIANPAINT": {"yf":"ASIANPAINT.NS","nse":"ASIANPAINT","lot":300,"step":20,"sector":"CONSUMER","tags":["LONG_TERM","BLUE_CHIP"],"div_yield":0.7,"category":"LARGE_CAP"},
    "ULTRACEMCO": {"yf":"ULTRACEMCO.NS","nse":"ULTRACEMCO","lot":100,"step":100,"sector":"CEMENT","tags":["LONG_TERM","BLUE_CHIP"],"div_yield":0.4,"category":"LARGE_CAP"},
    "NESTLEIND":  {"yf":"NESTLEIND.NS","nse":"NESTLEIND","lot":200,"step":50,"sector":"FMCG","tags":["LONG_TERM","DIVIDEND","BLUE_CHIP"],"div_yield":1.3,"category":"LARGE_CAP"},
    "DIVISLAB":   {"yf":"DIVISLAB.NS","nse":"DIVISLAB","lot":100,"step":50,"sector":"PHARMA","tags":["LONG_TERM"],"div_yield":0.8,"category":"MID_CAP"},
    "DRREDDY":    {"yf":"DRREDDY.NS","nse":"DRREDDY","lot":125,"step":50,"sector":"PHARMA","tags":["LONG_TERM","DIVIDEND"],"div_yield":0.6,"category":"MID_CAP"},
    "CIPLA":      {"yf":"CIPLA.NS","nse":"CIPLA","lot":650,"step":10,"sector":"PHARMA","tags":["LONG_TERM","DIVIDEND"],"div_yield":0.6,"category":"MID_CAP"},
    "APOLLOHOSP": {"yf":"APOLLOHOSP.NS","nse":"APOLLOHOSP","lot":125,"step":50,"sector":"HEALTH","tags":["LONG_TERM"],"div_yield":0.2,"category":"MID_CAP"},
    "HEROMOTOCO": {"yf":"HEROMOTOCO.NS","nse":"HEROMOTOCO","lot":150,"step":50,"sector":"AUTO","tags":["DIVIDEND","BLUE_CHIP"],"div_yield":2.5,"category":"LARGE_CAP"},
    "BPCL":       {"yf":"BPCL.NS","nse":"BPCL","lot":1800,"step":5,"sector":"ENERGY","tags":["DIVIDEND","SHORT_TERM","PENNY"],"div_yield":4.2,"category":"MID_CAP"},
    "HINDALCO":   {"yf":"HINDALCO.NS","nse":"HINDALCO","lot":1075,"step":10,"sector":"METAL","tags":["SHORT_TERM"],"div_yield":0.6,"category":"MID_CAP"},
    "TATACONSUM": {"yf":"TATACONSUM.NS","nse":"TATACONSUM","lot":675,"step":10,"sector":"FMCG","tags":["LONG_TERM"],"div_yield":0.7,"category":"MID_CAP"},
    "SBILIFE":    {"yf":"SBILIFE.NS","nse":"SBILIFE","lot":375,"step":20,"sector":"INSURE","tags":["LONG_TERM"],"div_yield":0.4,"category":"MID_CAP"},
    "HDFCLIFE":   {"yf":"HDFCLIFE.NS","nse":"HDFCLIFE","lot":1100,"step":10,"sector":"INSURE","tags":["LONG_TERM"],"div_yield":0.3,"category":"MID_CAP"},
    "DABUR":      {"yf":"DABUR.NS","nse":"DABUR","lot":1250,"step":5,"sector":"FMCG","tags":["DIVIDEND","LONG_TERM","BONUS","PENNY"],"div_yield":1.5,"category":"SMALL_CAP"},
    "SAIL":       {"yf":"SAIL.NS","nse":"SAIL","lot":4000,"step":2,"sector":"METAL","tags":["PENNY","SHORT_TERM","DIVIDEND"],"div_yield":2.8,"category":"SMALL_CAP"},
    "PNB":        {"yf":"PNB.NS","nse":"PNB","lot":8000,"step":1,"sector":"BANK","tags":["PENNY","SHORT_TERM","DIVIDEND"],"div_yield":2.0,"category":"SMALL_CAP"},
    "BANKBARODA": {"yf":"BANKBARODA.NS","nse":"BANKBARODA","lot":2925,"step":5,"sector":"BANK","tags":["PENNY","SHORT_TERM","DIVIDEND"],"div_yield":2.2,"category":"SMALL_CAP"},
    "IOC":        {"yf":"IOC.NS","nse":"IOC","lot":4800,"step":2,"sector":"ENERGY","tags":["PENNY","DIVIDEND"],"div_yield":6.5,"category":"SMALL_CAP"},
    "BHEL":       {"yf":"BHEL.NS","nse":"BHEL","lot":2250,"step":5,"sector":"INFRA","tags":["PENNY","SHORT_TERM"],"div_yield":0.5,"category":"SMALL_CAP"},
    "GAIL":       {"yf":"GAIL.NS","nse":"GAIL","lot":4575,"step":2,"sector":"ENERGY","tags":["PENNY","DIVIDEND","BONUS"],"div_yield":3.5,"category":"SMALL_CAP"},
    "PFC":        {"yf":"PFC.NS","nse":"PFC","lot":1650,"step":5,"sector":"NBFC","tags":["PENNY","DIVIDEND"],"div_yield":4.0,"category":"SMALL_CAP"},
    "RECLTD":     {"yf":"RECLTD.NS","nse":"RECLTD","lot":1500,"step":5,"sector":"NBFC","tags":["PENNY","DIVIDEND"],"div_yield":3.8,"category":"SMALL_CAP"},
}

_INDEX_MAP_FALLBACK = {
    "NIFTY":     {"yf":"^NSEI","nse":"NIFTY","step":50,"lot":50,"sector":"INDEX","category":"INDEX","tags":["INDEX"]},
    "BANKNIFTY": {"yf":"^NSEBANK","nse":"BANKNIFTY","step":100,"lot":15,"sector":"INDEX","category":"INDEX","tags":["INDEX"]},
    "FINNIFTY":  {"yf":"NIFTY_FIN_SERVICE.NS","nse":"FINNIFTY","step":50,"lot":40,"sector":"INDEX","category":"INDEX","tags":["INDEX"]},
}
_LOADED_INDEX = load_index_map(BASE_DIR)
INDEX_MAP = _LOADED_INDEX if _LOADED_INDEX else _INDEX_MAP_FALLBACK

ALL_INSTRUMENTS = {**INDEX_MAP, **STOCK_MAP}

# ═══════════════════════════════════════════════════════════════
# FLASK APP
# ═══════════════════════════════════════════════════════════════

app = Flask(__name__, template_folder=str(BASE_DIR / "templates"), static_folder=str(BASE_DIR / "static"))
app.config["SECRET_KEY"] = os.environ.get("FLASK_SECRET_KEY", os.urandom(24).hex())
_cors_origins = os.environ.get("CORS_ORIGINS", "*")
socketio = SocketIO(app, cors_allowed_origins=_cors_origins, async_mode="threading")

# ═══════════════════════════════════════════════════════════════
# DATA LAYER — Background fetcher
# ═══════════════════════════════════════════════════════════════

_shutdown = threading.Event()
_data_lock = threading.Lock()
_signals_store: dict = {}
_last_update: float = 0
_fetch_executor: ThreadPoolExecutor = None
_tg_engine: TelegramEngine = None
_app_config: dict = {}


def _load_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception as e:
            logging.error(f"Config load failed: {e}")
    return {}


_symbol_fail_counts: dict = {}
_symbol_blacklist: dict = {}
_fail_lock = threading.Lock()
_SYMBOL_BLACKLIST_THRESHOLD = 10
_SYMBOL_BLACKLIST_RECOVERY_S = 600

def _safe_fetch(symbol: str, interval: str, period: str = "1d"):
    with _fail_lock:
        bl_ts = _symbol_blacklist.get(symbol)
        if bl_ts is not None:
            if time.time() - bl_ts < _SYMBOL_BLACKLIST_RECOVERY_S:
                return None
            del _symbol_blacklist[symbol]
            _symbol_fail_counts.pop(symbol, None)
            logging.info(f"Symbol {symbol} recovered from blacklist")
    try:
        df = yf.Ticker(symbol).history(period=period, interval=interval)
        if df is None or df.empty:
            with _fail_lock:
                _symbol_fail_counts[symbol] = _symbol_fail_counts.get(symbol, 0) + 1
                if _symbol_fail_counts[symbol] >= _SYMBOL_BLACKLIST_THRESHOLD:
                    _symbol_blacklist[symbol] = time.time()
                    logging.warning(f"Symbol {symbol} blacklisted for {_SYMBOL_BLACKLIST_RECOVERY_S}s after {_SYMBOL_BLACKLIST_THRESHOLD} failures")
            return None
        with _fail_lock:
            _symbol_fail_counts.pop(symbol, None)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df, _ = validate_ohlcv(df, interval)
        min_bars = _app_config.get("MIN_OHLCV_BARS", 10)
        return df if df is not None and len(df) >= min_bars else None
    except Exception as e:
        with _fail_lock:
            _symbol_fail_counts[symbol] = _symbol_fail_counts.get(symbol, 0) + 1
            if _symbol_fail_counts[symbol] >= _SYMBOL_BLACKLIST_THRESHOLD:
                _symbol_blacklist[symbol] = time.time()
                logging.warning(f"Symbol {symbol} blacklisted for {_SYMBOL_BLACKLIST_RECOVERY_S}s after {_SYMBOL_BLACKLIST_THRESHOLD} failures")
        logging.debug(f"Fetch {symbol}/{interval} failed: {e}")
        return None


def _fetch_frames(symbol: str) -> dict:
    """Fetch 1m, 5m, 15m frames for a single symbol."""
    frames = {}
    for iv in ("1m", "5m", "15m"):
        frames[iv] = _safe_fetch(symbol, iv)
    return frames


def _scan_all_instruments():
    """Full scan: fetch data for all instruments and compute signals."""
    global _last_update
    results = {}
    names = list(ALL_INSTRUMENTS.keys())

    if _shutdown.is_set():
        return results

    def _worker(name):
        meta = ALL_INSTRUMENTS[name]
        yf_sym = meta["yf"]
        frames = _fetch_frames(yf_sym)
        asset_type = "index" if name in INDEX_MAP else "stock"
        sig = build_full_signal(
            symbol=name,
            df1m=frames.get("1m"),
            df5m=frames.get("5m"),
            df15m=frames.get("15m"),
            asset_type=asset_type,
            sector=meta.get("sector", ""),
            category=meta.get("category", ""),
            tags=meta.get("tags", []),
            threshold=_app_config.get("AI_THRESHOLD", 60),
            config=_app_config,
        )
        if sig:
            sig["lot"] = meta.get("lot", 0)
            sig["div_yield"] = meta.get("div_yield", 0)
            sig["why"] = explain_signal(sig, "Index" if asset_type == "index" else "Stock")
        return name, sig

    futures = {}
    for name in names:
        if _shutdown.is_set():
            break
        try:
            f = _fetch_executor.submit(_worker, name)
            futures[f] = name
        except RuntimeError:
            break

    tg_alerts = []
    scan_timeout = _app_config.get("SCAN_TIMEOUT", 45)
    try:
        for fut in as_completed(futures, timeout=scan_timeout):
            try:
                name, sig = fut.result()
                if sig:
                    results[name] = sig
                    if sig.get("signal") != "HOLD":
                        tg_alerts.append(sig)
            except Exception as e:
                logging.warning(f"Scan error for {futures[fut]}: {e}")
    except (TimeoutError, FuturesTimeoutError):
        logging.warning("as_completed timed out — saving partial results")

    with _data_lock:
        stale_keys = [k for k in _signals_store if k not in results]
        for k in stale_keys:
            _signals_store.pop(k, None)
        _signals_store.update(results)
        _last_update = time.time()

    if _tg_engine and tg_alerts and not _shutdown.is_set():
        def _send_tg_batch():
            for sig in tg_alerts:
                try:
                    _tg_engine.send_signal_alert(sig)
                except Exception as e:
                    logging.warning(f"TG alert error for {sig.get('symbol','?')}: {e}")
        threading.Thread(target=_send_tg_batch, daemon=True).start()

    return results


def _background_scanner(interval: int = 5):
    """Continuous background scanner thread."""
    while not _shutdown.is_set():
        try:
            now = time_provider.now()
            hour, minute = now.hour, now.minute
            mkt_open_h, mkt_open_m = _app_config.get("MARKET_OPEN_HOUR", 9), _app_config.get("MARKET_OPEN_MIN", 15)
            mkt_close_h, mkt_close_m = _app_config.get("MARKET_CLOSE_HOUR", 15), _app_config.get("MARKET_CLOSE_MIN", 30)
            t_now = hour * 60 + minute
            t_open = mkt_open_h * 60 + mkt_open_m
            t_close = mkt_close_h * 60 + mkt_close_m
            is_market_hours = t_open <= t_now <= t_close
            weekday = now.weekday()
            is_holiday = now.strftime("%Y-%m-%d") in NSE_HOLIDAYS
            off_hours_sleep = _app_config.get("OFF_HOURS_SLEEP", 60)
            if weekday >= 5 or is_holiday or not is_market_hours:
                _shutdown.wait(off_hours_sleep)
                continue

            results = _scan_all_instruments()
            if results:
                socketio.emit("market_update", _build_ui_payload(), namespace="/")
        except Exception as e:
            logging.error(f"Scanner error: {e}")

        _shutdown.wait(interval)


def _build_ui_payload() -> dict:
    """Build the JSON payload sent to the browser."""
    with _data_lock:
        data = dict(_signals_store)
        ts = _last_update

    rows = []
    for name, sig in data.items():
        s_price = sig.get("price", 0) or 0
        s_open = sig.get("open", 0) or 0
        macd_raw = sig.get("macd", {})
        macd_dict = macd_raw if isinstance(macd_raw, dict) else {}
        change_pct = round((s_price - s_open) / s_open * 100, 2) if s_open > 0 else 0
        rows.append({
            "symbol": name,
            "price": s_price,
            "open": s_open,
            "high": sig.get("high", 0),
            "low": sig.get("low", 0),
            "change_pct": change_pct,
            "signal": sig.get("signal", "HOLD"),
            "strength": sig.get("strength", "NONE"),
            "direction": sig.get("direction", ""),
            "score": sig.get("score", 0),
            "rsi": sig.get("rsi", 0),
            "macd": macd_dict.get("histogram", 0),
            "macd_full": macd_dict,
            "ema20": sig.get("ema20", 0),
            "ema50": sig.get("ema50", 0),
            "ema200": sig.get("ema200", 0),
            "vwap": sig.get("vwap", 0),
            "vol_ratio": sig.get("vol_ratio", 0),
            "atr": sig.get("atr", 0),
            "support": sig.get("support", 0),
            "resistance": sig.get("resistance", 0),
            "stop_loss": sig.get("stop_loss", 0),
            "tp1": sig.get("tp1", 0),
            "tp2": sig.get("tp2", 0),
            "tp3": sig.get("tp3", 0),
            "sector": sig.get("sector", ""),
            "category": sig.get("category", ""),
            "tags": sig.get("tags", []),
            "lot": sig.get("lot", 0),
            "iv": sig.get("iv", 0),
            "vix": sig.get("vix", 0),
            "pcr": sig.get("pcr", 0),
            "smart_money": sig.get("smart_money", ""),
            "timestamp": sig.get("timestamp", ""),
            "why": sig.get("why", ""),
            "asset_type": sig.get("asset_type", "stock"),
        })

    return {
        "rows": rows,
        "last_update": datetime.fromtimestamp(ts, IST).strftime("%H:%M:%S") if ts > 0 else "--:--:--",
        "total_stocks": len([r for r in rows if r["asset_type"] == "stock"]),
        "total_indices": len([r for r in rows if r["asset_type"] == "index"]),
        "buy_signals": len([r for r in rows if r["signal"] == "BUY"]),
        "sell_signals": len([r for r in rows if r["signal"] == "SELL"]),
        "strong_signals": len([r for r in rows if r["strength"] == "STRONG"]),
    }

    # Load metrics from trading bot
    metrics = {}
    try:
        if os.path.exists("metrics_report.json"):
            with open("metrics_report.json", "r", encoding="utf-8") as f:
                metrics = json.load(f)
    except Exception as e:
        metrics = {"error": f"Failed to load metrics: {str(e)[:50]}"}

    payload = {
        "rows": rows,
        "last_update": datetime.fromtimestamp(ts, IST).strftime("%H:%M:%S") if ts > 0 else "--:--:--",
        "total_stocks": len([r for r in rows if r["asset_type"] == "stock"]),
        "total_indices": len([r for r in rows if r["asset_type"] == "index"]),
        "buy_signals": len([r for r in rows if r["signal"] == "BUY"]),
        "sell_signals": len([r for r in rows if r["signal"] == "SELL"]),
        "strong_signals": len([r for r in rows if r["strength"] == "STRONG"]),
        "metrics": metrics,
    }

    return payload

# ═══════════════════════════════════════════════════════════════
# ROUTES
# ═══════════════════════════════════════════════════════════════

@app.route("/")
def index():
    return render_template("dashboard.html", version=VERSION)

@app.route("/api/data")
def api_data():
    return jsonify(_build_ui_payload())

@app.route("/api/signal/<symbol>")
def api_signal(symbol):
    with _data_lock:
        sig = _signals_store.get(symbol.upper())
    if sig:
        return jsonify(sig)
    return jsonify({"error": "Symbol not found"}), 404

@app.route("/api/health")
def api_health():
    with _data_lock:
        last = _last_update
    return jsonify({
        "status": "ok",
        "version": VERSION,
        "instruments": len(ALL_INSTRUMENTS),
        "last_update": last,
        "uptime_s": int(time.time() - _start_time),
    })

# ─── SOCKET.IO EVENTS ──────────────────────────────────────

@socketio.on("connect")
def handle_connect():
    emit("market_update", _build_ui_payload())

@socketio.on("request_refresh")
def handle_refresh():
    emit("market_update", _build_ui_payload())

# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════

_start_time = 0

def main():
    global _tg_engine, _fetch_executor, _app_config, _start_time
    _start_time = time.time()

    parser = argparse.ArgumentParser(description="Trading Dashboard Server")
    parser.add_argument("--port", type=int, default=5100, help="Server port")
    parser.add_argument("--debug", action="store_true", help="Debug mode")
    parser.add_argument("--interval", type=int, default=5, help="Scan interval in seconds")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    cfg = _load_config()
    _app_config = cfg
    max_workers = cfg.get("MAX_FETCH_WORKERS", 12)
    _fetch_executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="dash_yf")
    bot_token = cfg.get("BOT_TOKEN", "")
    chat_id = cfg.get("CHAT_ID", "")
    if bot_token and chat_id and "YOUR_TELEGRAM" not in bot_token:
        _tg_engine = TelegramEngine(
            bot_token=bot_token,
            default_chat_id=chat_id,
            channel_map=cfg.get("CHANNEL_MAP", {}),
            cooldown_seconds=cfg.get("ALERT_COOLDOWN_SECONDS", 900),
            send_timeout=cfg.get("SEND_TIMEOUT", 10),
            pin_timeout=cfg.get("PIN_TIMEOUT", 5),
            rate_window_seconds=cfg.get("RATE_WINDOW_SECONDS", 60),
        )
        logging.info("Telegram engine initialised")

    scan_interval = cfg.get("SCAN_INTERVAL", args.interval)

    def _graceful_shutdown(*a):
        logging.info("Shutdown requested")
        _shutdown.set()
        scanner.join(timeout=5)
        try:
            _fetch_executor.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass
        if _tg_engine:
            try:
                _tg_engine.close()
            except Exception:
                pass
        logging.info("Shutdown complete")

    scanner = threading.Thread(target=_background_scanner, args=(scan_interval,), daemon=True)
    scanner.start()

    _signal.signal(_signal.SIGINT, _graceful_shutdown)
    _signal.signal(_signal.SIGTERM, _graceful_shutdown)
    if sys.platform == "win32":
        _signal.signal(_signal.SIGBREAK, _graceful_shutdown)
    logging.info(f"Scanner started (interval={scan_interval}s, instruments={len(ALL_INSTRUMENTS)})")

    # Default loopback: avoid binding all interfaces if DASHBOARD_HOST omitted from config.
    host = cfg.get("DASHBOARD_HOST", "127.0.0.1")
    port = cfg.get("DASHBOARD_PORT", args.port)
    debug = cfg.get("DASHBOARD_DEBUG", args.debug)
    logging.info(f"Dashboard server starting on http://localhost:{port}")
    socketio.run(app, host=host, port=port, debug=debug, allow_unsafe_werkzeug=True)

if __name__ == "__main__":
    main()
