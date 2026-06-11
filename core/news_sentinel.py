"""
News sentiment guard (Item 12 — v2.44).

Lightweight background RSS scanner that detects high-risk news events.
Runs in a daemon thread; scan loop reads cached result (never blocks).
Free RSS sources only — no paid API.

Config keys
-----------
  news_sentinel_enabled      : bool   default false
  news_poll_interval_mins    : int    default 5
  news_lookback_mins         : int    default 30
  news_extreme_score_mult    : float  default 0.0
  news_high_score_mult       : float  default 0.70
  news_elevated_score_mult   : float  default 0.85
  news_custom_keywords       : list   default []
  news_rss_timeout_secs      : int    default 5
"""
from __future__ import annotations

import logging
import threading
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

_log = logging.getLogger(__name__)

# ── Keyword tiers ──────────────────────────────────────────────────────────────

EXTREME_KEYWORDS = [
    "emergency", "circuit breaker", "market halt", "trading suspended",
    "systemic risk", "banking crisis", "war declared",
]
HIGH_KEYWORDS = [
    "rate hike", "rate cut", "rbi policy", "surprise inflation",
    "gdp shock", "rupee freefall", "election result", "budget announcement",
]
ELEVATED_KEYWORDS = [
    "rbi meeting", "fomc", "nse bulletin", "sebi order",
    "earnings miss", "earnings beat", "fii selling", "global selloff",
]

# Sentiment keywords for news analysis
BULLISH_KEYWORDS = [
    "growth", "gain", "rise", "up", "bullish", "positive", "profit", "surge",
    "rally", "recovery", "strong", "beat", "exceed", "outperform", "upgrade",
    "buy", "accumulate", "outlook", "optimistic", "confidence", "stimulus",
    "support", "incentive", "subsidy", "tariff cut", "rate cut", "liquidity"
]

BEARISH_KEYWORDS = [
    "loss", "fall", "down", "bearish", "negative", "loss", "decline", "drop",
    "crash", "slash", "cut", "weak", "miss", "underperform", "downgrade",
    "sell", "reduce", "cautious", "pessimistic", "concern", "risk", "warning",
    "deficit", "debt", "inflation", "rate hike", "tighten", "restriction",
    "ban", "probe", "investigation", "scandal", "fraud", "default"
]

RSS_SOURCES = [
    "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
]

_SCORE_MAP = {"EXTREME": 1.0, "HIGH": 0.7, "ELEVATED": 0.3, "CLEAR": 0.0}
_MULT_MAP  = {"EXTREME": 0.0, "HIGH": 0.70, "ELEVATED": 0.85, "CLEAR": 1.0}


@dataclass(frozen=True)
class NewsRiskAssessment:
    risk_score:         float
    risk_level:         str         # "CLEAR"|"ELEVATED"|"HIGH"|"EXTREME"
    triggered_keywords: list[str]
    headline:           str | None
    source:             str | None
    assessed_at:        float
    score_multiplier:   float
    sentiment:          str = "NEUTRAL"   # "BULLISH"|"BEARISH"|"NEUTRAL"|"MIXED"



def _classify_headline(
    headline: str,
    cfg: dict | None = None,
) -> tuple[str, list[str]]:
    """
    Module-level helper: classify a headline and return (level, keywords).
    level ∈ {"NONE","ELEVATED","HIGH","EXTREME"}
    """
    c          = cfg or {}
    custom_kws = [k.lower() for k in (c.get("news_custom_keywords") or [])]
    h          = headline.lower()
    for kw in EXTREME_KEYWORDS + custom_kws:
        if kw.lower() in h:
            return "EXTREME", [kw]
    triggered_high = [kw for kw in HIGH_KEYWORDS if kw.lower() in h]
    if triggered_high:
        return "HIGH", triggered_high
    triggered_el = [kw for kw in ELEVATED_KEYWORDS if kw.lower() in h]
    if triggered_el:
        return "ELEVATED", triggered_el
    return "NONE", []


_CLEAR_ASSESSMENT = NewsRiskAssessment(
    risk_score=0.0, risk_level="CLEAR",
    triggered_keywords=[], headline=None, source=None,
    assessed_at=time.time(), score_multiplier=1.0,
    sentiment="NEUTRAL",
)


class NewsSentinel:

    def __init__(self, cfg: dict[str, Any] | None = None) -> None:
        self._cfg     = cfg or {}
        self._lock    = threading.Lock()
        self._cache:  NewsRiskAssessment = _CLEAR_ASSESSMENT
        self._thread: threading.Thread | None = None
        self._stop    = threading.Event()

    def start(self) -> None:
        if not self._cfg.get("news_sentinel_enabled", False):
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._poll_loop, name="news-sentinel", daemon=True
        )
        self._thread.start()
        _log.info("[NEWS] NewsSentinel started")

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=10)

    def get_current_risk(self) -> NewsRiskAssessment:
        """Non-blocking cached read. Safe default (CLEAR) if no assessment yet."""
        with self._lock:
            return self._cache

    def update_config(self, cfg: dict[str, Any]) -> None:
        self._cfg = cfg

    # ── Internal ──────────────────────────────────────────────────────────────

    def _poll_loop(self) -> None:
        interval = int(self._cfg.get("news_poll_interval_mins", 5)) * 60
        while not self._stop.is_set():
            try:
                self._run_one_poll()
            except (ValueError, TypeError, OSError) as exc:
                _log.debug("[NEWS] Poll loop error: %s", exc)
            self._stop.wait(interval)

    def _run_one_poll(self) -> None:
        cfg         = self._cfg
        lookback    = int(cfg.get("news_lookback_mins", 30)) * 60
        custom_kw   = [k.lower() for k in (cfg.get("news_custom_keywords") or [])]
        now         = time.time()
        best: NewsRiskAssessment = _CLEAR_ASSESSMENT

        sources = list(RSS_SOURCES)

        for url in sources:
            items = self._fetch_rss(url)
            for item in items:
                pub_ts = item.get("pub_ts", 0.0)
                if pub_ts and (now - pub_ts) > lookback:
                    continue
                headline = item.get("title", "")
                score, level, kws = self._score_headline(headline, custom_kw)

                # Sentiment analysis
                h_low = headline.lower()
                bull_hits = [kw for kw in BULLISH_KEYWORDS if kw in h_low]
                bear_hits = [kw for kw in BEARISH_KEYWORDS if kw in h_low]
                sentiment = "NEUTRAL"
                if bull_hits and not bear_hits: sentiment = "BULLISH"
                elif bear_hits and not bull_hits: sentiment = "BEARISH"
                elif bull_hits and bear_hits: sentiment = "MIXED"

                if score > best.risk_score:
                    mult = float(cfg.get(f"news_{level.lower()}_score_mult",
                                        _MULT_MAP.get(level, 1.0)))
                    best = NewsRiskAssessment(
                        risk_score=score, risk_level=level,
                        triggered_keywords=kws, headline=headline,
                        source=url, assessed_at=now,
                        score_multiplier=mult,
                        sentiment=sentiment,
                    )
                    _log.info("[NEWS] %s keyword hit in: %s | Sentiment: %s", level, headline[:80], sentiment)

        with self._lock:
            self._cache = best

    def _score_headline(
        self,
        headline:   str,
        custom_kws: list[str],
    ) -> tuple[float, str, list[str]]:
        h = headline.lower()
        for kw in EXTREME_KEYWORDS + custom_kws:
            if kw.lower() in h:
                return 1.0, "EXTREME", [kw]
        triggered_high = [kw for kw in HIGH_KEYWORDS if kw.lower() in h]
        if triggered_high:
            return 0.7, "HIGH", triggered_high
        triggered_el = [kw for kw in ELEVATED_KEYWORDS if kw.lower() in h]
        if triggered_el:
            return 0.3, "ELEVATED", triggered_el
        return 0.0, "CLEAR", []

    def _fetch_rss(self, url: str) -> list[dict]:
        timeout = int(self._cfg.get("news_rss_timeout_secs", 5))
        try:
            req  = Request(url, headers={"User-Agent": "OPBBot/2.44 news-sentinel"})
            with urlopen(req, timeout=timeout) as resp:
                data = resp.read()
            root  = ET.fromstring(data)
            items = []
            for item in root.iter("item"):
                title   = (item.findtext("title") or "").strip()
                pub_raw = (item.findtext("pubDate") or "").strip()
                pub_ts  = 0.0
                try:
                    pub_ts = parsedate_to_datetime(pub_raw).timestamp()
                except (ValueError, TypeError, OSError) as e:
                    _log.debug("[NEWS_SENTINEL] non-critical error: %s", e)
                items.append({"title": title, "pub_ts": pub_ts, "link": item.findtext("link") or ""})
            return items
        except (URLError, ET.ParseError, Exception) as exc:
            _log.debug("[NEWS] RSS fetch error %s: %s", url, exc)
            return []
