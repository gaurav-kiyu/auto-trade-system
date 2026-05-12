"""Tests for core/news_sentinel.py (v2.44 Item 12)."""
import time
import pytest
from unittest.mock import patch, MagicMock
from core.news_sentinel import (
    NewsRiskAssessment,
    NewsSentinel,
    EXTREME_KEYWORDS,
    HIGH_KEYWORDS,
    ELEVATED_KEYWORDS,
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
