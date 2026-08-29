"""Full NSE Universe Real-Time Strategy Scanner (v3.0).

Scans the ENTIRE universe of 2,500+ active listed NSE stocks (Large-Cap,
Mid-Cap, Small-Cap, Micro-Cap, Penny, and SME stocks) in parallel against
the 16 Integrated Quantitative Strategies.

Dispatches real-time alerts only for configured conviction thresholds; the
production default is strict 100/100 and a server-side 09:15-15:30 IST market-session gate.
"""

from __future__ import annotations

import csv
import io
import json
import os
import smtplib
import sys
import time
import threading
from collections import deque
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any

# Ensure project root is in sys.path
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from index_app.domains.signal.evaluator import SignalEvaluator

from core.datetime_ist import now_ist
from core.logging import get_logger

_log = get_logger("ALL_NSE_SCANNER")
_NSE_EQUITY_CSV_URL = "https://archives.nseindia.com/content/equities/EQUITY_L.csv"
_CACHE_PATH = _ROOT / "data" / "nse_equities.csv"


@dataclass
class ScannedStockSignal:
    symbol: str
    company_name: str
    series: str
    direction: str
    score: int
    raw_score: int
    tier: str
    regime: str
    price: float
    rsi: float
    adx: float
    vwap: float
    confidence: float = 0.0
    ml_probability: float = 0.5
    score_components: dict[str, int] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: now_ist().isoformat())


class AllNSEScanner:
    """High-Throughput Parallel Scanner for the complete NSE Listed Stock Universe."""

    def __init__(
        self,
        cfg: dict[str, Any] | None = None,
        max_workers: int = 20,
        cooldown_secs: int = 900,
    ) -> None:
        if cfg is None:
            cfg_path = _ROOT / "json" / "config.json"
            if cfg_path.exists():
                with open(cfg_path, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
            else:
                cfg = {}

        self._cfg = cfg
        self._max_workers = max_workers
        self._cooldown_secs = int(cfg.get("SIGNAL_DEDUP_COOLDOWN_SECS", cooldown_secs))
        self._max_alerts_per_cycle = max(1, int(cfg.get("MAX_ALERTS_PER_CYCLE", 10)))
        self._max_alerts_per_window = max(1, int(cfg.get("MAX_ALERTS_PER_WINDOW", 20)))
        self._max_alerts_per_day = max(1, int(cfg.get("MAX_ALERTS_PER_DAY", 100)))
        self._alert_window_secs = max(60, int(cfg.get("ALERT_RATE_WINDOW_SECS", 300)))
        self._recent_dispatch_times: deque[float] = deque()
        self._rate_lock = threading.Lock()
        self._legacy_system_broadcast_enabled = bool(cfg.get("LEGACY_SYSTEM_BROADCAST_ENABLED", False))
        self._telegram_execute_button_enabled = bool(
            cfg.get("ENABLE_TELEGRAM_EXECUTE_BUTTON", False)
            and str(cfg.get("EXECUTION_MODE", "SIGNAL_ONLY")).upper() in {"AUTO", "PAPER"}
        )
        # IV-rank multiplier boosts scores by up to 1.2x based on option premium
        # cost (VIX). This scanner trades cash equities / stock options, not index
        # options, so the premium-cost boost would inflate every score to the 100
        # cap on low-VIX days. Keep the scoring pipeline but neutralise that layer.
        _eval_cfg = dict(cfg)
        _eval_cfg["iv_rank_enabled"] = False
        self._evaluator = SignalEvaluator(_eval_cfg)
        self._last_alert_time: dict[str, float] = {}
        self._stats_lock = threading.Lock()
        self._scan_stats: dict[str, int] = {"evaluated": 0, "accepted": 0, "errors": 0, "duplicates": 0}
        self._symbols_cache: list[dict[str, str]] = []
        self._current_vix: float = 0.0
        self._vix_fetched_at: float = 0.0
        self._vix_cache_ttl: float = 600.0

        self._reload_config_credentials()

    def _market_session_is_open(self) -> bool:
        """Server-side NSE/BSE cash/F&O session gate.

        Live scans are blocked outside 09:15-15:30 IST on weekdays unless an
        explicit replay/backtest/after-hours override is enabled. This gate
        prevents a live scanner from producing signals from stale/off-session
        Yahoo Finance bars.
        """
        mode = str(self._cfg.get("EXECUTION_MODE", "SIGNAL_ONLY")).upper()
        if bool(self._cfg.get("ALLOW_AFTER_HOURS_SCANNING", False)) or mode in {"BACKTEST", "REPLAY", "PAPER_REPLAY"}:
            return True
        now = now_ist()
        if now.weekday() >= 5:
            return False
        start = str(self._cfg.get("MARKET_OPEN", "09:15"))
        end = str(self._cfg.get("MARKET_CLOSE", "15:30"))
        try:
            sh, sm = (int(x) for x in start.split(":")[:2])
            eh, em = (int(x) for x in end.split(":")[:2])
            current = now.hour * 60 + now.minute
            return sh * 60 + sm <= current <= eh * 60 + em
        except (ValueError, TypeError):
            return 9 * 60 + 15 <= now.hour * 60 + now.minute <= 15 * 60 + 30

    def _get_live_vix(self) -> float:
        """Fetch the real India VIX (^INDIAVIX) once per scan cycle with a TTL cache.

        Returns 0.0 (neutral - no score adjustment) on fetch failure or while
        outside market hours so signals are never artificially inflated.
        """
        import time as _time

        now_ts = _time.time()
        if self._vix_fetched_at and (now_ts - self._vix_fetched_at) < self._vix_cache_ttl:
            return self._current_vix
        try:
            from core.yf_data_provider import fetch_vix as _fetch_vix

            _vix = float(_fetch_vix() or 0.0)
        except Exception:
            _vix = 0.0
        self._vix_fetched_at = now_ts
        self._current_vix = _vix if _vix > 0 else 0.0
        _log.info("[VIX] Live India VIX: %s", self._current_vix or "unavailable (using neutral 0.0)")
        return self._current_vix

    def _reload_config_credentials(self) -> None:
        """Dynamically reload notification credentials from json/config.json and .env."""
        try:
            from dotenv import load_dotenv
            load_dotenv(_ROOT / ".env", override=True)
        except Exception:
            pass

        try:
            cfg_path = _ROOT / "json" / "config.json"
            if cfg_path.exists():
                with open(cfg_path, "r", encoding="utf-8") as f:
                    self._cfg = json.load(f)
        except Exception as ex:
            _log.debug("Failed to reload config.json: %s", ex)

        self._cooldown_secs = int(self._cfg.get("TG_COOLDOWN_SECS", self._cfg.get("COOLDOWN_SECS", 300)))
        self._bot_token = str(self._cfg.get("BOT_TOKEN") or os.getenv("OPBUYING_BOT_TOKEN") or os.getenv("OPBUYING_TELEGRAM_BOT_TOKEN") or os.getenv("BOT_TOKEN") or "").strip()
        self._chat_id = str(self._cfg.get("CHAT_ID") or os.getenv("OPBUYING_CHAT_ID") or os.getenv("OPBUYING_TELEGRAM_CHAT_ID") or os.getenv("CHAT_ID") or "1148730533").strip()

        email_enabled_cfg = self._cfg.get("EMAIL_ENABLED")
        if email_enabled_cfg is None:
            self._email_enabled = True
        else:
            self._email_enabled = bool(email_enabled_cfg)

        self._email_user = str(self._cfg.get("EMAIL_USER") or os.getenv("OPBUYING_EMAIL_USER") or os.getenv("SMTP_USERNAME") or "").strip()
        self._email_pass = str(self._cfg.get("EMAIL_PASS") or os.getenv("OPBUYING_EMAIL_PASS") or os.getenv("SMTP_PASSWORD") or "").strip()
        self._email_to = str(self._cfg.get("EMAIL_TO") or os.getenv("OPBUYING_EMAIL_TO") or "").strip()
        self._email_smtp = str(self._cfg.get("EMAIL_SMTP") or os.getenv("SMTP_SERVER") or "smtp.gmail.com").strip()
        self._email_port = int(self._cfg.get("EMAIL_PORT") or os.getenv("SMTP_PORT") or 587)

    def load_nse_universe(self, force_refresh: bool = False) -> list[dict[str, str]]:
        """Load and dynamically synchronize the full active NSE & BSE stock universe (~2,500+ symbols).

        Automatically prepends major Option Indices (NIFTY, BANKNIFTY, FINNIFTY, SENSEX, MIDCPNIFTY)
        so they are prioritized and scanned first on every cycle.
        """
        _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        today = now_ist().date()

        # Priority Option Indices (Always scanned first)
        priority_indices = [
            {"symbol": "NIFTY", "name": "Nifty 50 Index (NSE)", "series": "INDEX"},
            {"symbol": "BANKNIFTY", "name": "Bank Nifty Index (NSE)", "series": "INDEX"},
            {"symbol": "FINNIFTY", "name": "Nifty Fin Services (NSE)", "series": "INDEX"},
            {"symbol": "SENSEX", "name": "BSE Sensex Index (BSE)", "series": "INDEX"},
            {"symbol": "MIDCPNIFTY", "name": "Nifty Midcap Select (NSE)", "series": "INDEX"},
        ]

        # Check if local cache is fresh from TODAY
        cache_is_fresh = False
        if _CACHE_PATH.exists() and _CACHE_PATH.stat().st_size > 1000:
            mtime = datetime.fromtimestamp(_CACHE_PATH.stat().st_mtime, tz=timezone.utc).date()
            if mtime >= today:
                cache_is_fresh = True

        if not force_refresh and cache_is_fresh:
            try:
                stocks = []
                with open(_CACHE_PATH, "r", encoding="utf-8", errors="ignore") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        sym = row.get("SYMBOL", "").strip()
                        if sym:
                            stocks.append({
                                "symbol": sym,
                                "name": row.get("NAME OF COMPANY", sym).strip(),
                                "series": row.get(" SERIES", row.get("SERIES", "EQ")).strip(),
                            })
                if stocks:
                    # Prepend Priority Indices
                    self._symbols_cache = priority_indices + stocks
                    _log.info("[DYNAMIC SYNC] Loaded %d verified symbols (including %d Priority Indices) for %s",
                              len(self._symbols_cache), len(priority_indices), today.isoformat())
                    return self._symbols_cache
            except Exception as ex:
                _log.warning("Cache load failed: %s. Re-fetching from NSE India...", ex)

        # Cache is expired, missing, or force_refresh requested -> Fetch fresh from NSE India
        _log.info("[DYNAMIC SYNC] Initiating live daily synchronization with NSE India Equity Master...")
        try:
            req = urllib.request.Request(
                _NSE_EQUITY_CSV_URL,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
            )
            with urllib.request.urlopen(req, timeout=12) as resp:
                content = resp.read().decode("utf-8", errors="ignore")
                with open(_CACHE_PATH, "w", encoding="utf-8") as f:
                    f.write(content)
                reader = csv.DictReader(io.StringIO(content))
                stocks = [
                    {
                        "symbol": row["SYMBOL"].strip(),
                        "name": row.get("NAME OF COMPANY", row["SYMBOL"]).strip(),
                        "series": row.get(" SERIES", row.get("SERIES", "EQ")).strip(),
                    }
                    for row in reader
                    if row.get("SYMBOL")
                ]
                self._symbols_cache = priority_indices + stocks
                _log.info("[DYNAMIC SYNC] SUCCESS: Daily refreshed & synchronized %d active stocks + %d Indices for %s!",
                          len(stocks), len(priority_indices), today.isoformat())
                return self._symbols_cache
        except Exception as ex:
            _log.error("NSE live sync error: %s. Loading fallback equity universe.", ex)
            return priority_indices + self._get_fallback_universe()

    def _get_fallback_universe(self) -> list[dict[str, str]]:
        """Fallback list of major liquid NSE stocks if network is offline."""
        defaults = [
            "RELIANCE", "TCS", "HDFCBANK", "ICICIBANK", "INFY", "BHARTIARTL", "SBIN", "ITC",
            "LT", "HINDUNILVR", "AXISBANK", "KOTAKBANK", "BAJFINANCE", "MARUTI", "TATAMOTORS",
            "M&M", "SUNPHARMA", "NTPC", "POWERGRID", "TITAN", "ONGC", "ADANIENT", "ADANIPORTS",
            "TATASTEEL", "JSWSTEEL", "HCLTECH", "WIPRO", "TECHM", "LTIM", "BAJAJFINSV",
            "ASIANPAINT", "NESTLEIND", "ULTRACEMCO", "GRASIM", "COALINDIA", "BPCL", "HEROMOTOCO",
            "EICHERMOT", "BAJAJ-AUTO", "CIPLA", "DRREDDY", "APOLLOHOSP", "DIVISLAB", "HINDALCO",
            "VEDL", "BRITANNIA", "TATACONSUM", "SBILIFE", "HDFCLIFE", "BEL", "TRENT", "ZOMATO",
            "JIOFIN", "SUZLON", "IDEA", "YESBANK", "RPOWER", "JPPOWER", "GTLINFRA", "VI",
            "IRFC", "RVNL", "MAZDOCK", "COCHINSHIP", "BHEL", "SAIL", "NMDC", "IOC", "GAIL",
        ]
        return [{"symbol": s, "name": s, "series": "EQ"} for s in defaults]

    def get_min_score_for_category(self, category: str) -> int:
        """Return the configured minimum publication score for an instrument category."""
        cat_upper = category.upper()
        thresholds = self._cfg.get("CATEGORY_SCORE_THRESHOLDS", {})
        if isinstance(thresholds, dict) and cat_upper in thresholds:
            return int(thresholds[cat_upper])
        if "INDEX" in cat_upper or cat_upper == "INDEX_OPTIONS":
            return int(self._cfg.get("INDEX_MIN_SCORE", 100))
        return int(self._cfg.get("MIN_SCORE_THRESHOLD", 100))

    def scan_single_stock(self, stock_info: dict[str, str]) -> ScannedStockSignal | None:
        """Scan a single stock across all 16 quantitative strategies."""
        sym = stock_info["symbol"].upper()
        with self._stats_lock:
            self._scan_stats["evaluated"] += 1

        # Map to accurate Yahoo Finance / Data Ticker
        if sym == "NIFTY":
            yf_ticker = "^NSEI"
        elif sym == "BANKNIFTY":
            yf_ticker = "^NSEBANK"
        elif sym == "FINNIFTY":
            yf_ticker = "NIFTY_FIN_SERVICE.NS"
        elif sym == "MIDCPNIFTY":
            yf_ticker = "NIFTY_MID_SELECT.NS"
        elif sym == "SENSEX":
            yf_ticker = "^BSESN"
        else:
            yf_ticker = f"{sym}.NS"

        try:
            import yfinance as yf
            ticker = yf.Ticker(yf_ticker)
            df1 = ticker.history(period="1d", interval="1m")
            df5 = ticker.history(period="5d", interval="5m")
            df15 = ticker.history(period="5d", interval="15m")

            if df5 is None or df5.empty:
                df5 = ticker.history(period="1mo", interval="1d")
            if df15 is None or df15.empty:
                df15 = df5
            if df1 is None or df1.empty or len(df1) < 5:
                # If 1m intraday is sparse (e.g., off-market hours or initial pre-market), use df5 as primary frame
                df1 = df5

            if df1 is None or df1.empty or df5 is None or df5.empty or df15 is None or df15.empty:
                return None

            sig, reason = self._evaluator.evaluate(
                name=sym,
                frames={"df1m": df1, "df5m": df5, "df15m": df15},
                vix=self._current_vix,
            )

            from core.fno_universe import classify_instrument_market, is_fno_symbol
            is_fno = is_fno_symbol(sym)
            category = classify_instrument_market(sym, stock_info.get("series", "EQ"))

            if sig is None:
                return None

            # LONG-ONLY CASH GATE:
            # If the stock is NOT in the F&O universe, strictly block and suppress PUT/SELL signals.
            # Cash equities are only scanned for BUY (Swing / Positional / CNC Delivery).
            if not is_fno and sig.direction == "PUT":
                _log.debug("[CASH GATE] Filtered PUT/SELL for non-F&O stock %s (Cash is strictly LONG-ONLY)", sym)
                return None

            min_score_threshold = self.get_min_score_for_category(category)
            min_tier_cfg = str(self._cfg.get("MIN_SIGNAL_TIER", "STRONG_ONLY")).upper()
            allowed_tiers = ("STRONG",) if min_tier_cfg in ("STRONG", "STRONG_ONLY") else ("STRONG", "MODERATE")

            # Elite notifications require a live ML probability when ML governance
            # is enabled. The scorer uses 0.5 as a neutral value when a model is
            # unavailable; that neutral fallback must never qualify for the
            # externally governed notification tier.
            ml_required = bool(self._cfg.get("ML_REQUIRED_FOR_ALERTS", True))
            ml_min = float(self._cfg.get("ML_ALERT_MIN_PROBABILITY", self._cfg.get("ML_CONFIDENCE_THRESHOLD", 0.65)))
            if ml_required and float(getattr(sig, "ml_probability", 0.5)) < ml_min:
                _log.info("[ML_GATE] Suppressed %s: probability %.3f < %.3f",
                          sym, float(getattr(sig, "ml_probability", 0.5)), ml_min)
                return None

            # Config-driven score gate.
            # The effective threshold comes from CATEGORY_SCORE_THRESHOLDS
            # with configured fallback rules in get_min_score_for_category().
            if sig and sig.score >= min_score_threshold and sig.tier in allowed_tiers:
                with self._stats_lock:
                    self._scan_stats["accepted"] += 1
                return ScannedStockSignal(
                    symbol=sym,
                    company_name=stock_info.get("name", sym),
                    series=stock_info.get("series", "EQ"),
                    direction=sig.direction,
                    score=sig.score,
                    raw_score=sig.raw_score,
                    tier=sig.tier,
                    regime=sig.regime,
                    price=sig.price,
                    rsi=sig.rsi,
                    adx=sig.adx,
                    vwap=sig.vwap,
                    confidence=sig.confidence,
                    ml_probability=sig.ml_probability,
                    score_components=dict(sig.score_components),
                )
        except Exception:
            with self._stats_lock:
                self._scan_stats["errors"] += 1
            return None
        return None

    @staticmethod
    def _classify_category(signal: ScannedStockSignal) -> str:
        from core.fno_universe import classify_instrument_market
        return classify_instrument_market(signal.symbol, signal.series)

    def _rate_limit_allows_dispatch(self) -> bool:
        now = time.time()
        with self._rate_lock:
            cutoff = now - self._alert_window_secs
            while self._recent_dispatch_times and self._recent_dispatch_times[0] < cutoff:
                self._recent_dispatch_times.popleft()
            if len(self._recent_dispatch_times) >= self._max_alerts_per_window:
                return False
            self._recent_dispatch_times.append(now)
            return True

    def scan_universe(
        self,
        symbols_limit: int | None = None,
        send_alerts: bool = True,
    ) -> list[ScannedStockSignal]:
        """Run parallel scan across the NSE stock universe."""
        if not self._market_session_is_open():
            _log.info("[MARKET_SESSION_GATE] Live scan suppressed outside 09:15-15:30 IST.")
            return []

        with self._stats_lock:
            self._scan_stats = {"evaluated": 0, "accepted": 0, "errors": 0, "duplicates": 0}
        stocks = self.load_nse_universe()
        if symbols_limit:
            stocks = stocks[:symbols_limit]

        _log.info("Starting parallel 16-strategy scan across %d NSE stocks (Workers: %d)...",
                  len(stocks), self._max_workers)

        self._get_live_vix()

        detected_signals: list[ScannedStockSignal] = []

        with ThreadPoolExecutor(max_workers=self._max_workers) as executor:
            future_to_sym = {
                executor.submit(self.scan_single_stock, stock): stock["symbol"]
                for stock in stocks
            }

            for future in as_completed(future_to_sym):
                sym = future_to_sym[future]
                try:
                    res = future.result()
                    if res is not None:
                        detected_signals.append(res)
                        _log.info(">> DETECTED %s SIGNAL for %s (Score: %d/100, Tier: %s, Price: Rs %.2f)",
                                  res.direction, res.symbol, res.score, res.tier, res.price)

                except Exception as ex:
                    _log.debug("Scan error for %s: %s", sym, ex)

        # Rank only after the full parallel scan.  The previous implementation
        # dispatched each future as soon as it completed, so a burst of 100/100
        # candidates could generate notifications before the scanner knew which
        # candidates were globally strongest.  Select a small, diversified top-N
        # set first, then apply persistent deduplication/rate limits at dispatch.
        detected_signals.sort(key=lambda s: (s.score, s.confidence, s.ml_probability), reverse=True)

        # Preserve category diversity where possible: take up to two leaders per
        # category before filling remaining slots by global score.
        selected: list[ScannedStockSignal] = []
        category_counts: dict[str, int] = {}
        for candidate in detected_signals:
            category = self._classify_category(candidate)
            if category_counts.get(category, 0) >= 2:
                continue
            selected.append(candidate)
            category_counts[category] = category_counts.get(category, 0) + 1
            if len(selected) >= self._max_alerts_per_cycle:
                break
        if len(selected) < self._max_alerts_per_cycle:
            selected_ids = {id(x) for x in selected}
            for candidate in detected_signals:
                if id(candidate) in selected_ids:
                    continue
                selected.append(candidate)
                if len(selected) >= self._max_alerts_per_cycle:
                    break

        if send_alerts:
            for candidate in selected:
                self._dispatch_alert_if_eligible(candidate)

        with self._stats_lock:
            stats = dict(self._scan_stats)
        stats["delivered_candidates"] = len(selected)
        stats["candidate_pool"] = len(detected_signals)
        try:
            from core.signals.signal_tracker import SignalTracker
            SignalTracker.get_instance().record_scan_cycle(
                stats, symbols_scanned=len(stocks), timestamp=now_ist().isoformat()
            )
        except Exception as ex:
            _log.debug("[SCAN_AUDIT] Failed to persist cycle metrics: %s", ex)
        _log.info("[SCAN_METRICS] evaluated=%d accepted=%d returned=%d errors=%d",
                  stats["evaluated"], stats["accepted"], len(detected_signals), stats["errors"])
        return detected_signals

    def _log_signal_audit_record(
        self,
        signal: ScannedStockSignal,
        category: str,
        threshold_applied: int,
        decision: str,  # "ACCEPTED" or "NO_TRADE"
        rejection_reason: str = "",
    ) -> None:
        """Persist 11 Core Audit Invariant Fields for both Accepted and Counterfactual opportunities."""
        try:
            import datetime
            import json
            from pathlib import Path

            logs_dir = _ROOT / "logs"
            logs_dir.mkdir(parents=True, exist_ok=True)
            audit_file = logs_dir / "forward_audit_signals.jsonl"

            # Compute virtual risk bounds for counterfactual tracking
            sl_price = round(signal.price * 0.97 if signal.direction == "CALL" else signal.price * 1.03, 2)
            t1_price = round(signal.price * 1.04 if signal.direction == "CALL" else signal.price * 0.96, 2)
            t2_price = round(signal.price * 1.08 if signal.direction == "CALL" else signal.price * 0.92, 2)

            record = {
                "signal_id": f"SIG-{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}-{signal.symbol}-{signal.direction}",
                "symbol": signal.symbol,
                "category": category,
                "composite_score": signal.score,
                "raw_score": signal.raw_score,
                "direction": signal.direction,
                "tier": signal.tier,
                "decision": decision,
                "rejection_reason": rejection_reason,
                "threshold_applied": threshold_applied,
                "threshold_policy_version": "v6.0-policy-03",
                "model_version": "v6.0-LOCKED-PROD",
                "calibration_version": "isotonic-platt-v2.1",
                # Do not fabricate probability/expectancy figures from the UI
                # score. They must come from a calibrated model or remain null.
                "expected_value_r": None,
                "calibrated_p_t1": None,
                "entry_price": signal.price,
                "sl_price": sl_price,
                "t1_price": t1_price,
                "t2_price": t2_price,
                "timestamp": datetime.datetime.now().isoformat(),
                "engine_version": "v6.0.4",
                "weight_matrix_version": "wm-v6-canonical",
                "risk_policy_version": "rp-v6-strict",
                "regime": signal.regime,
            }

            with open(audit_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")
        except Exception as e:
            _log.debug("[AUDIT] Failed to persist signal audit record: %s", e)

    def _daily_signal_limit_allows_dispatch(self) -> bool:
        try:
            from core.signals.signal_tracker import SignalTracker
            count = SignalTracker.get_instance().count_generated_today()
            if count >= self._max_alerts_per_day:
                _log.warning("[DAILY_RATE_LIMIT] Suppressed alert: %d/%d signals already generated today",
                             count, self._max_alerts_per_day)
                return False
        except Exception as ex:
            # Fail closed for external notifications when the persistent rate
            # ledger is unavailable; do not risk an SMTP/Telegram flood.
            _log.error("[DAILY_RATE_LIMIT] Unable to verify daily signal count: %s", ex)
            return False
        return True

    def _dispatch_alert_if_eligible(self, signal: ScannedStockSignal) -> None:
        """Dispatch real-time trade signals via Telegram and Email."""
        # Cooldown gate - at most one alert per symbol per cooldown window
        now = time.time()
        last_sent = self._last_alert_time.get(signal.symbol, 0.0)
        if now - last_sent < self._cooldown_secs:
            _log.info("[COOLDOWN] Alert for %s suppressed (%.0fs cooldown remaining)",
                      signal.symbol, self._cooldown_secs - (now - last_sent))
            return
        if not self._rate_limit_allows_dispatch():
            _log.warning("[RATE_LIMIT] Suppressed %s: maximum %d alerts per %ds window",
                         signal.symbol, self._max_alerts_per_window, self._alert_window_secs)
            return
        from core.fno_universe import classify_instrument_market
        category = classify_instrument_market(signal.symbol, signal.series)

        if not self._daily_signal_limit_allows_dispatch():
            return

        # Commit the in-memory cooldown only after all pre-dispatch
        # safety/rate gates have passed. A blocked signal must not consume
        # the symbol cooldown.
        self._last_alert_time[signal.symbol] = now

        # Format trade signal message using RichSignalFormatter
        from core.notifications.rich_signal_formatter import RichSignalFormatter
        from core.notifications.url_resolver import get_public_base_url
        base_url = get_public_base_url(self._cfg)

        sl_price = round(signal.price * (0.97 if signal.direction == "CALL" else 1.03), 2)
        t1_price = round(signal.price * (1.04 if signal.direction == "CALL" else 0.96), 2)
        t2_price = round(signal.price * (1.08 if signal.direction == "CALL" else 0.92), 2)

        rich_html_email = RichSignalFormatter.build_rich_html_email(
            symbol=signal.symbol,
            company_name=signal.company_name,
            series=signal.series,
            category=category,
            direction=signal.direction,
            price=signal.price,
            score=signal.score,
            tier=signal.tier,
            regime=signal.regime,
            rsi=signal.rsi,
            adx=signal.adx,
            vwap=signal.vwap,
            stop_loss=sl_price,
            target_1=t1_price,
            target_2=t2_price,
            base_url=base_url,
        )

        rich_tg_msg = RichSignalFormatter.build_rich_telegram_html(
            symbol=signal.symbol,
            category=category,
            direction=signal.direction,
            price=signal.price,
            score=signal.score,
            tier=signal.tier,
            stop_loss=sl_price,
            target_1=t1_price,
            target_2=t2_price,
        )

        # Make score provenance visible in every alert; this prevents a capped
        # 100/100 from being mistaken for an uncapped perfect score.
        score_evidence = (
            f"<br><b>Raw Component Score:</b> {signal.raw_score} / "
            f"{int(self._cfg.get('COMPOSITE_BASE_MAX_SCORE', 150))}"
            f"<br><b>ML Win Probability:</b> {signal.ml_probability:.1%}"
        )
        rich_tg_msg += "\n\n<b>Score Evidence</b>\n"
        rich_tg_msg += f"Raw Component Score: {signal.raw_score} / {int(self._cfg.get('COMPOSITE_BASE_MAX_SCORE', 150))}\n"
        rich_tg_msg += f"ML Win Probability: {signal.ml_probability:.1%}"
        rich_html_email = rich_html_email.replace("</body>", score_evidence + "</body>") if "</body>" in rich_html_email else rich_html_email + score_evidence

        # Plain text fallback
        direction_label = "STRONG BUY / ACCUMULATE" if signal.direction == "CALL" else "STRONG SELL / SHORT BREAKDOWN"
        plain_msg_body = f"""🎯 [OPB ALL-NSE UNIVERSE STRATEGY SIGNAL]

📊 Stock: {signal.symbol} ({signal.company_name})
• Series: {signal.series} (NSE Listed)
• Signal: {direction_label}
• Live Spot LTP: ₹{signal.price:,.2f}
• 16-Strategy Composite Score: {signal.score}/100 (Tier: {signal.tier})
• Market Regime: {signal.regime}
• Indicators: RSI: {signal.rsi:.1f} | ADX: {signal.adx:.1f} | VWAP: ₹{signal.vwap:,.2f}

🛡️ Risk Parameters:
• Stop Loss: ₹{sl_price:,.2f} (3.0%)
• Target 1: ₹{t1_price:,.2f} (4.0%)
• Target 2: ₹{t2_price:,.2f} (8.0%)

📐 Score Evidence:
• Raw Component Score: {signal.raw_score} / {int(self._cfg.get("COMPOSITE_BASE_MAX_SCORE", 150))}
• Normalized Score: {signal.score}/100
• ML Win Probability: {signal.ml_probability:.1%}

⚡ Scanned in real-time across 2,500+ NSE active listed stocks."""

        self._reload_config_credentials()

        # Config-driven score gate.
        # Do not impose a universal 100/100 requirement here.
        min_score_threshold = self.get_min_score_for_category(category)

        if signal.score < min_score_threshold:
            _log.info(
                "[GATE] Suppressed signal for %s (%s, Score: %d) - below configured threshold %d",
                signal.symbol,
                category,
                signal.score,
                min_score_threshold,
            )
            self._log_signal_audit_record(
                signal=signal,
                category=category,
                threshold_applied=min_score_threshold,
                decision="NO_TRADE",
                rejection_reason=(f"Score {signal.score} < configured threshold {min_score_threshold}"),
            )
            return

        # Persist Accepted Signal Audit Record
        self._log_signal_audit_record(
            signal=signal,
            category=category,
            threshold_applied=min_score_threshold,
            decision="ACCEPTED",
        )

        # Check granular permissions & quota per user via UserPermissionManager
        from core.auth.user_signal_permissions import UserPermissionManager
        perm_mgr = UserPermissionManager.get_instance()
        eligible_users = perm_mgr.get_eligible_recipients(category=category, tier=signal.tier, symbol=signal.symbol)

        # Aggregate authorized Telegram chats and Email recipients from eligible users
        authorized_chat_ids: set[str] = set()
        authorized_emails: set[str] = set()

        for u in eligible_users:
            if u.telegram_enabled and u.telegram_chat_id:
                for cid in u.telegram_chat_id.split(","):
                    clean_cid = cid.strip()
                    if clean_cid and not clean_cid.startswith("YOUR_"):
                        authorized_chat_ids.add(clean_cid)
            if u.email_enabled and u.email:
                for em_addr in u.email.split(","):
                    clean_em = em_addr.strip()
                    if clean_em and "@" in clean_em:
                        authorized_emails.add(clean_em)

        # Legacy system-level broadcast recipients are opt-in only.  The previous
        # unconditional union bypassed per-user privilege/notification settings
        # and could multiply SMTP traffic even when a user had opted out.
        if self._legacy_system_broadcast_enabled:
            if self._chat_id:
                for cid in str(self._chat_id).split(","):
                    clean_cid = cid.strip()
                    if clean_cid and not clean_cid.startswith("YOUR_"):
                        authorized_chat_ids.add(clean_cid)
            if self._email_to:
                for em_addr in str(self._email_to).split(","):
                    clean_em = em_addr.strip()
                    if clean_em and "@" in clean_em:
                        authorized_emails.add(clean_em)

        if not authorized_chat_ids and not authorized_emails:
            _log.info("[GATE] Signal for %s (%s, Tier: %s) suppressed - no authorized recipients configured",
                      signal.symbol, category, signal.tier)
            return

        # 0. Real-Time Signal & Delivery History Logging - runs BEFORE dispatch
        # (not after, as previously) so the returned signal_id can be embedded
        # into the Telegram/email message below. That lets the recipient reply
        # "/placed {signal_id}" via the already-live TelegramCommander polling
        # bot (core/telegram_commander.py) to mark it as traded - the same
        # SignalTracker.mark_order_placed() call the admin dashboard checkbox
        # uses, so there is one persisted history, not a second data path.
        signal_id = ""
        try:
            from core.signals.signal_tracker import SignalTracker
            tracker = SignalTracker.get_instance()
            signal_id = tracker.record_generated_signal({
                "symbol": signal.symbol,
                "company_name": signal.company_name,
                "series": signal.series,
                "direction": signal.direction,
                "price": signal.price,
                "score": signal.score,
                "raw_score": signal.raw_score,
                "normalized_score": signal.score,
                "score_saturated": bool(signal.score >= 100 and signal.raw_score >= int(self._cfg.get("COMPOSITE_BASE_MAX_SCORE", 150))),
                "confidence": signal.confidence,
                "ml_probability": signal.ml_probability,
                "score_components": signal.score_components,
                "tier": signal.tier,
                "regime": signal.regime,
                "category": category,
                "strategy": "all_nse_16_strategy",
                "dedup_cooldown_secs": self._cooldown_secs,
                "stop_loss": sl_price,
                "target_1": t1_price,
                "target_2": t2_price,
            }, eligible_users=eligible_users) or ""
        except Exception as trk_ex:
            _log.warning("Signal tracking log exception: %s", trk_ex)

        # A failed/duplicate persistence result must never fall through to
        # external notification.  v18 previously could suppress the DB record
        # but still send Telegram/SMTP because it continued with signal_id="".
        if not signal_id:
            _log.info("[DELIVERY_GUARD] No persisted signal id for %s; external dispatch suppressed", signal.symbol)
            return

        if signal_id:
            plain_msg_body += (
                f"\n\n🆔 Signal ID: {signal_id}\n"
                f"Reply /placed {signal_id} in Telegram once you place the order "
                "(or use the dashboard checkbox)."
            )
            rich_tg_msg += (
                f"\n\n🆔 <b>Signal ID:</b> <code>{signal_id}</code>\n"
                f"Reply <code>/placed {signal_id}</code> once you place the order."
            )
            rich_html_email += (
                f"<br><br>🆔 <b>Signal ID:</b> <code>{signal_id}</code>"
                f"<br>Reply <code>/placed {signal_id}</code> in Telegram once you place the order."
            )

        # 1. Telegram Dispatch with Rich HTML & 1-Click Interactive Inline Action Buttons
        if self._bot_token and authorized_chat_ids:
            first_row = [
                {"text": "⚡ 1-Click Paper Trade", "callback_data": f"paper:{signal.symbol}"}
            ]
            if self._telegram_execute_button_enabled:
                first_row.append({"text": "🚀 1-Click Execute", "callback_data": f"exec:{signal.symbol}"})
            inline_keyboard = {
                "inline_keyboard": [
                    first_row,
                    [
                        {"text": "📊 View Chart", "url": f"https://in.tradingview.com/chart/?symbol=NSE:{signal.symbol}"},
                        {"text": "🏛️ Cockpit Dashboard", "url": f"{base_url}/my-signals"},
                    ]
                ]
            }
            for cid in authorized_chat_ids:
                try:
                    data = urllib.parse.urlencode({
                        "chat_id": cid,
                        "text": rich_tg_msg,
                        "parse_mode": "HTML",
                        "reply_markup": json.dumps(inline_keyboard),
                    }).encode("utf-8")
                    req = urllib.request.Request(
                        f"https://api.telegram.org/bot{self._bot_token}/sendMessage",
                        data=data,
                    )
                    with urllib.request.urlopen(req, timeout=10) as resp:
                        res = json.loads(resp.read().decode())
                        if res.get("ok"):
                            _log.info("[OK] Telegram alert with interactive buttons sent to %s for %s (%s, MsgID: %s)",
                                      cid, signal.symbol, category, res.get("result", {}).get("message_id"))
                except Exception as ex:
                    # Fallback to plain text if HTML parse error
                    try:
                        fallback_data = urllib.parse.urlencode({
                            "chat_id": cid,
                            "text": plain_msg_body,
                            "reply_markup": json.dumps(inline_keyboard),
                        }).encode("utf-8")
                        fallback_req = urllib.request.Request(
                            f"https://api.telegram.org/bot{self._bot_token}/sendMessage",
                            data=fallback_data,
                        )
                        urllib.request.urlopen(fallback_req, timeout=10)
                    except Exception:
                        pass
                    _log.error("[ERROR] Telegram dispatch failed for chat %s on %s: %s", cid, signal.symbol, ex)

        # 2. Gmail SMTP Dispatch with Rich Multipart HTML Email
        if self._email_enabled and self._email_user and self._email_pass and authorized_emails:
            try:
                server = smtplib.SMTP(self._email_smtp, self._email_port, timeout=10)
                server.starttls()
                server.login(self._email_user, self._email_pass)

                msg = MIMEMultipart("alternative")
                msg["Subject"] = RichSignalFormatter.build_rich_email_subject(
                    symbol=signal.symbol,
                    category=category,
                    direction=signal.direction,
                    price=signal.price,
                    score=signal.score,
                    tier=signal.tier,
                    target_1=t1_price,
                    target_2=t2_price,
                )
                msg["From"] = self._email_user
                msg["To"] = ", ".join(authorized_emails)

                # Attach plain text and HTML alternatives
                msg.attach(MIMEText(plain_msg_body, "plain", "utf-8"))
                msg.attach(MIMEText(rich_html_email, "html", "utf-8"))

                server.sendmail(self._email_user, list(authorized_emails), msg.as_string())
                server.quit()
                _log.info("[OK] Rich HTML Gmail alert sent to %d authorized recipients (%s) for %s (%s)",
                          len(authorized_emails), ", ".join(authorized_emails), signal.symbol, category)
            except Exception as ex:
                _log.error("[ERROR] Gmail dispatch failed for %s: %s", signal.symbol, ex)


def run_all_nse_scanner():
    """CLI Entrypoint for the Full NSE Universe Strategy Scanner."""
    scanner = AllNSEScanner(max_workers=20)
    print("=" * 70)
    print("OPB ALL-NSE UNIVERSE REAL-TIME STRATEGY SCANNER")
    print("=" * 70)

    # Scan universe
    signals = scanner.scan_universe(symbols_limit=100, send_alerts=True)

    print("\n" + "=" * 70)
    print(f"SCAN COMPLETE — Found {len(signals)} Actionable Setups:")
    print("=" * 70)
    for s in signals:
        name_clean = s.company_name[:25].encode('ascii', 'ignore').decode()
        print(f"* {s.symbol:<12} ({name_clean}): {s.direction:<4} | Score: {s.score:<3}/100 ({s.tier}) | LTP: Rs {s.price:,.2f} | RSI: {s.rsi:.1f}")


if __name__ == "__main__":
    run_all_nse_scanner()
