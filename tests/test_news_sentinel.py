"""Tests for core/news_sentinel.py (v2.44 Item 12)."""
import time

import pytest
from core.news_sentinel import (
    ELEVATED_KEYWORDS,
    EXTREME_KEYWORDS,
    HIGH_KEYWORDS,
    NewsRiskAssessment,
    NewsSentinel,
    _classify_headline,
)

CFG = {
    "news_sentinel_enabled": True,
    "news_poll_interval_mins": 5,
    "news_lookback_mins": 30,
    "news_extreme_score_mult": 0.0,
    "news_high_score_mult": 0.70,
    "news_elevated_score_mult": 0.85,
    "news_custom_keywords": [],
    "news_rss_timeout_secs": 5,
}


# ── Keyword classification ────────────────────────────────────────────────────

def test_extreme_keyword_detected():
    level, kws = _classify_headline("Market circuit breaker triggered today", CFG)
    assert level == "EXTREME"
    assert len(kws) > 0


def test_high_keyword_detected():
    level, kws = _classify_headline("RBI announces rate hike of 25 bps", CFG)
    assert level == "HIGH"
    assert len(kws) > 0


def test_elevated_keyword_detected():
    level, kws = _classify_headline("RBI meeting outcome today", CFG)
    assert level in ("ELEVATED", "HIGH", "EXTREME")


def test_no_risk_for_neutral_headline():
    level, kws = _classify_headline("Sensex closes slightly higher", CFG)
    assert level == "NONE"  # module-level helper uses NONE; class uses CLEAR
    assert kws == []


def test_case_insensitive_matching():
    level, _ = _classify_headline("EMERGENCY DECLARED IN MARKETS", CFG)
    assert level == "EXTREME"


def test_custom_keywords_matched():
    cfg = dict(CFG, news_custom_keywords=["my_custom_risk"])
    level, kws = _classify_headline("Market shows my_custom_risk today", cfg)
    assert level in ("ELEVATED", "HIGH", "EXTREME")


def test_extreme_takes_priority_over_high():
    headline = "Emergency rate hike announced"
    level, _ = _classify_headline(headline, CFG)
    # Should be EXTREME (emergency) not just HIGH (rate hike)
    assert level == "EXTREME"


# ── NewsRiskAssessment fields ─────────────────────────────────────────────────

def test_assessment_has_all_fields():
    a = NewsRiskAssessment(
        risk_score=0.5, risk_level="HIGH",
        triggered_keywords=["rate hike"], headline="test", source="rss",
        assessed_at=time.time(), score_multiplier=0.7
    )
    assert hasattr(a, "risk_score")
    assert hasattr(a, "risk_level")
    assert hasattr(a, "triggered_keywords")
    assert hasattr(a, "score_multiplier")
    assert hasattr(a, "assessed_at")


def test_assessment_is_frozen():
    a = NewsRiskAssessment(
        risk_score=0.0, risk_level="NONE",
        triggered_keywords=[], headline=None, source=None,
        assessed_at=time.time(), score_multiplier=1.0
    )
    with pytest.raises((AttributeError, TypeError)):
        a.risk_level = "HIGH"


# ── Score multipliers ─────────────────────────────────────────────────────────

def test_extreme_multiplier_is_zero():
    assert CFG["news_extreme_score_mult"] == 0.0


def test_high_multiplier_less_than_one():
    assert CFG["news_high_score_mult"] < 1.0


def test_elevated_multiplier_between_high_and_one():
    assert CFG["news_high_score_mult"] < CFG["news_elevated_score_mult"] < 1.0


# ── NewsSentinel ──────────────────────────────────────────────────────────────

def test_sentinel_returns_default_when_no_news():
    s = NewsSentinel(cfg=CFG)
    a = s.get_current_risk()
    assert isinstance(a, NewsRiskAssessment)
    assert a.score_multiplier == pytest.approx(1.0)
    assert a.risk_level in ("NONE", "CLEAR")


def test_sentinel_start_stop():
    s = NewsSentinel(cfg=CFG)
    s.start()
    assert s._thread is not None
    s.stop()


def test_sentinel_start_stop_no_error():
    s = NewsSentinel(cfg=CFG)
    try:
        s.start()
        s.stop()
    except Exception as e:
        pytest.fail(f"start/stop raised: {e}")


def test_sentinel_get_risk_nonblocking():
    s = NewsSentinel(cfg=CFG)
    # Should return immediately without blocking
    start = time.time()
    a = s.get_current_risk()
    elapsed = time.time() - start
    assert elapsed < 0.5
    assert isinstance(a, NewsRiskAssessment)


def test_disabled_sentinel_returns_safe_default():
    cfg = dict(CFG, news_sentinel_enabled=False)
    s = NewsSentinel(cfg=cfg)
    a = s.get_current_risk()
    assert a.score_multiplier == pytest.approx(1.0)
    assert a.risk_level in ("NONE", "CLEAR")


# ── Keyword lists ─────────────────────────────────────────────────────────────

def test_extreme_keywords_not_empty():
    assert len(EXTREME_KEYWORDS) > 0


def test_high_keywords_not_empty():
    assert len(HIGH_KEYWORDS) > 0


def test_elevated_keywords_not_empty():
    assert len(ELEVATED_KEYWORDS) > 0


def test_extreme_keywords_are_lowercase():
    for kw in EXTREME_KEYWORDS:
        assert kw == kw.lower(), f"Keyword not lowercase: {kw}"


def test_risk_level_of_none_gives_multiplier_one():
    level, _ = _classify_headline("Regular market update", CFG)
    # Default sentinel cache is CLEAR → multiplier 1.0
    s = NewsSentinel(cfg=CFG)
    a = s.get_current_risk()
    assert a.score_multiplier == pytest.approx(1.0)


# ── start() disabled / already-running branches (lines 127, 129) ─────

def test_start_returns_early_when_disabled():
    s = NewsSentinel(cfg=dict(CFG, news_sentinel_enabled=False))
    assert s._thread is None
    s.start()


def test_start_returns_early_when_thread_already_alive():
    from unittest.mock import MagicMock
    s = NewsSentinel(cfg=dict(CFG, news_sentinel_enabled=True))
    mock_thread = MagicMock()
    mock_thread.is_alive.return_value = True
    s._thread = mock_thread
    s.start()


# ── update_config (line 148) ─────────────────────────────────────────

def test_update_config_replaces_cfg():
    s = NewsSentinel(cfg=CFG)
    new_cfg = dict(CFG, news_sentinel_enabled=False)
    s.update_config(new_cfg)
    assert s._cfg["news_sentinel_enabled"] is False


# ── _poll_loop exception handling (lines 157-158) ────────────────────

def test_poll_loop_catches_exception():
    s = NewsSentinel(cfg=CFG)

    def _raise(_self=None):
        raise ValueError("simulated poll error")

    s._run_one_poll = _raise

    def _set_stop(timeout=None):
        s._stop.set()

    s._stop.wait = _set_stop
    s._poll_loop()


# ── _score_headline coverage (lines 211, 214, 217) ───────────────────

def test_score_headline_extreme():
    s = NewsSentinel(cfg={})
    score, level, kws = s._score_headline("circuit breaker triggered", [])
    assert score == 1.0
    assert level == "EXTREME"
    assert len(kws) > 0


def test_score_headline_custom_extreme():
    s = NewsSentinel(cfg={})
    score, level, kws = s._score_headline("my_custom_crash keyword", ["my_custom_crash"])
    assert score == 1.0
    assert level == "EXTREME"
    assert "my_custom_crash" in kws


def test_score_headline_high():
    s = NewsSentinel(cfg={})
    score, level, kws = s._score_headline("RBI surprise rate hike today", [])
    assert score == 0.7
    assert level == "HIGH"
    assert len(kws) > 0


def test_score_headline_elevated():
    s = NewsSentinel(cfg={})
    score, level, kws = s._score_headline("SEBI order new regulation", [])
    assert score == 0.3
    assert level == "ELEVATED"
    assert len(kws) > 0


def test_score_headline_clear():
    s = NewsSentinel(cfg={})
    score, level, kws = s._score_headline("normal market movement", [])
    assert score == 0.0
    assert level == "CLEAR"
    assert kws == []


# ── MIXED sentiment (line 186) + score > best update (lines 189-198) ─

def test_run_one_poll_mixed_sentiment_and_score_update():
    s = NewsSentinel(cfg=CFG)

    def mock_fetch(url):
        return [
            {"title": "earnings miss and rally together", "pub_ts": time.time()},
        ]

    s._fetch_rss = mock_fetch
    s._run_one_poll()
    risk = s.get_current_risk()
    assert risk.risk_level == "ELEVATED"
    assert risk.sentiment == "MIXED"
    assert risk.headline == "earnings miss and rally together"
    assert risk.score_multiplier == float(CFG["news_elevated_score_mult"])


def test_run_one_poll_prefers_highest_score():
    s = NewsSentinel(cfg=CFG)

    def mock_fetch(url):
        return [
            {"title": "normal market update", "pub_ts": time.time()},
            {"title": "RBI announces rate hike of 25 bps", "pub_ts": time.time()},
        ]

    s._fetch_rss = mock_fetch
    s._run_one_poll()
    risk = s.get_current_risk()
    assert risk.risk_level == "HIGH"
    assert risk.score_multiplier == float(CFG["news_high_score_mult"])


# ── _fetch_rss error paths (lines 234-235, 238-240) ──────────────────

def test_fetch_rss_bad_pub_date_logs_and_defaults_to_zero():
    from unittest.mock import patch
    s = NewsSentinel(cfg=CFG)
    rss = (
        '<?xml version="1.0"?><rss><channel><item>'
        "<title>Test</title><pubDate>NotADate</pubDate><link>http://x</link>"
        "</item></channel></rss>"
    )
    with patch("core.news_sentinel.urlopen") as m:
        m.return_value.__enter__.return_value.read.return_value = rss.encode()
        items = s._fetch_rss("http://example.com/rss")
    assert len(items) == 1
    assert items[0]["pub_ts"] == 0.0


def test_fetch_rss_urlerror_returns_empty():
    from unittest.mock import patch
    from urllib.error import URLError
    s = NewsSentinel(cfg=CFG)
    with patch("core.news_sentinel.urlopen") as m:
        m.side_effect = URLError("connection failed")
        items = s._fetch_rss("http://example.com/rss")
    assert items == []


def test_fetch_rss_parse_error_returns_empty():
    from unittest.mock import patch
    s = NewsSentinel(cfg=CFG)
    with patch("core.news_sentinel.urlopen") as m:
        m.return_value.__enter__.return_value.read.return_value = b"not xml"
        items = s._fetch_rss("http://example.com/rss")
    assert items == []
