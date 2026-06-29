"""Tests for core.news_sentinel — NewsSentinel background RSS risk scanner."""

from __future__ import annotations

import time
from unittest.mock import patch

from core.news_sentinel import (
    _CLEAR_ASSESSMENT,
    NewsRiskAssessment,
    NewsSentinel,
    _classify_headline,
)

# ── _classify_headline tests ─────────────────────────────────────────────────

class TestClassifyHeadline:
    """Unit tests for the module-level _classify_headline helper."""

    def test_extreme_keyword_detected(self):
        """EXTREME keywords should return EXTREME level."""
        level, kws = _classify_headline("Emergency meeting called by RBI")
        assert level == "EXTREME"
        assert any("emergency" in kw.lower() for kw in kws)

    def test_high_keyword_detected(self):
        """HIGH keywords should return HIGH level."""
        level, kws = _classify_headline("RBI announces surprise rate hike")
        assert level == "HIGH"
        assert any("rate hike" in kw.lower() for kw in kws)

    def test_elevated_keyword_detected(self):
        """ELEVATED keywords should return ELEVATED level."""
        level, kws = _classify_headline("FOMC meeting minutes released")
        assert level == "ELEVATED"
        assert any("fomc" in kw.lower() for kw in kws)

    def test_no_keyword_match(self):
        """Headline with no keywords should return NONE."""
        level, kws = _classify_headline("Markets trade flat amid low volumes")
        assert level == "NONE"
        assert kws == []

    def test_empty_headline(self):
        """Empty headline should return NONE."""
        level, kws = _classify_headline("")
        assert level == "NONE"

    def test_case_insensitive(self):
        """Keyword matching should be case-insensitive."""
        level, kws = _classify_headline("BANKING CRISIS LOOMS")
        assert level == "EXTREME"
        assert any("banking crisis" in kw.lower() for kw in kws)

    def test_extreme_overrides_high(self):
        """EXTREME keywords should take precedence over HIGH."""
        level, kws = _classify_headline("Emergency rate hike by RBI")
        assert level == "EXTREME"

    def test_high_overrides_elevated(self):
        """HIGH keywords should take precedence over ELEVATED."""
        level, kws = _classify_headline("Rate hike expected after FOMC meeting")
        assert level == "HIGH"

    def test_custom_keywords(self):
        """Custom keywords from config should be treated as EXTREME level."""
        cfg = {"news_custom_keywords": ["crisis"]}
        level, kws = _classify_headline("Major crisis unfolding", cfg)
        assert level == "EXTREME"
        assert "crisis" in [k.lower() for k in kws]

    def test_custom_keywords_in_config_cases(self):
        """Custom keywords should work with config that has lowercase keywords."""
        cfg = {"news_custom_keywords": ["BREAKING"]}
        level, kws = _classify_headline("BREAKING news alert", cfg)
        assert level == "EXTREME"

    def test_multiple_high_keywords(self):
        """Multiple HIGH keywords should all be returned."""
        level, kws = _classify_headline("Rate hike and GDP shock data")
        assert level == "HIGH"
        assert len(kws) >= 1


# ── NewsRiskAssessment tests ─────────────────────────────────────────────────

class TestNewsRiskAssessment:
    """Test the NewsRiskAssessment dataclass."""

    def test_clear_assessment_default(self):
        """The CLEAR assessment should have score 0.0 and multiplier 1.0."""
        assert _CLEAR_ASSESSMENT.risk_score == 0.0
        assert _CLEAR_ASSESSMENT.risk_level == "CLEAR"
        assert _CLEAR_ASSESSMENT.score_multiplier == 1.0
        assert _CLEAR_ASSESSMENT.sentiment == "NEUTRAL"

    def test_custom_assessment(self):
        """Creating a custom assessment should work."""
        now = time.time()
        a = NewsRiskAssessment(
            risk_score=0.7,
            risk_level="HIGH",
            triggered_keywords=["rate hike"],
            headline="RBI rate hike",
            source="https://example.com",
            assessed_at=now,
            score_multiplier=0.7,
            sentiment="BEARISH",
        )
        assert a.risk_score == 0.7
        assert a.risk_level == "HIGH"
        assert a.sentiment == "BEARISH"


# ── _score_headline tests (via NewsSentinel) ─────────────────────────────────

class TestScoreHeadline:
    """Test the internal _score_headline method."""

    def test_extreme_score(self):
        """EXTREME keywords should return score 1.0."""
        ns = NewsSentinel({})
        score, level, kws = ns._score_headline("market halt triggered", [])
        assert score == 1.0
        assert level == "EXTREME"

    def test_high_score(self):
        """HIGH keywords should return score 0.7."""
        ns = NewsSentinel({})
        score, level, kws = ns._score_headline("surprise inflation data", [])
        assert score == 0.7
        assert level == "HIGH"

    def test_elevated_score(self):
        """ELEVATED keywords should return score 0.3."""
        ns = NewsSentinel({})
        score, level, kws = ns._score_headline("sebi order on F&O", [])
        assert score == 0.3
        assert level == "ELEVATED"

    def test_clear_score(self):
        """No keyword match should return score 0.0/CLEAR."""
        ns = NewsSentinel({})
        score, level, kws = ns._score_headline("normal market day", [])
        assert score == 0.0
        assert level == "CLEAR"

    def test_custom_keywords_in_score(self):
        """Custom keywords should be treated as EXTREME in scoring too."""
        ns = NewsSentinel({})
        score, level, kws = ns._score_headline("crash alert issued", ["crash"])
        assert score == 1.0
        assert level == "EXTREME"


# ── NewsSentinel start/stop tests ────────────────────────────────────────────

class TestNewsSentinelLifecycle:
    """Test NewsSentinel start/stop and basic lifecycle."""

    def test_default_disabled(self):
        """NewsSentinel should not start if config has news_sentinel_enabled=False."""
        cfg = {"news_sentinel_enabled": False}
        ns = NewsSentinel(cfg)
        ns.start()
        assert ns._thread is None or not ns._thread.is_alive()

    def test_enabled_starts_thread(self):
        """With enabled=True, start() should create a daemon thread."""
        cfg = {"news_sentinel_enabled": True, "news_poll_interval_mins": 60}
        ns = NewsSentinel(cfg)
        ns.start()
        assert ns._thread is not None
        assert ns._thread.is_alive()
        assert ns._thread.daemon is True
        ns.stop()

    def test_stop_clears_thread(self):
        """stop() should join the thread."""
        cfg = {"news_sentinel_enabled": True, "news_poll_interval_mins": 60}
        ns = NewsSentinel(cfg)
        ns.start()
        ns.stop()
        assert ns._stop.is_set()

    def test_start_twice(self):
        """Starting twice should not create a second thread."""
        cfg = {"news_sentinel_enabled": True, "news_poll_interval_mins": 60}
        ns = NewsSentinel(cfg)
        ns.start()
        thread_id = id(ns._thread)
        ns.start()
        assert id(ns._thread) == thread_id
        ns.stop()

    def test_stop_without_start(self):
        """Calling stop() on a never-started sentinel should not raise."""
        ns = NewsSentinel({})
        ns.stop()

    def test_get_current_risk_default(self):
        """Before any poll, get_current_risk() should return CLEAR."""
        ns = NewsSentinel({})
        risk = ns.get_current_risk()
        assert risk.risk_level == "CLEAR"
        assert risk.risk_score == 0.0

    def test_get_current_risk_thread_safe(self):
        """Concurrent reads should not raise."""
        ns = NewsSentinel({"news_sentinel_enabled": True})
        import threading as _t
        errors = []

        def _read():
            try:
                for _ in range(50):
                    ns.get_current_risk()
            except Exception as e:
                errors.append(e)

        threads = [_t.Thread(target=_read) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors


# ── NewsSentinel RSS polling tests ───────────────────────────────────────────

class TestNewsSentinelPolling:
    """Test the RSS polling and caching logic."""

    @patch("core.news_sentinel.urlopen")
    def test_fetch_rss_parses_items(self, mock_urlopen):
        """_fetch_rss should parse RSS XML into item dicts."""
        mock_urlopen.return_value.__enter__.return_value.read.return_value = (
            b'<?xml version="1.0"?><rss><channel>'
            b"<item><title>Market Update</title>"
            b"<pubDate>Mon, 01 Jan 2024 12:00:00 +0000</pubDate>"
            b"<link>https://example.com/1</link></item>"
            b"<item><title>Economy News</title>"
            b"<pubDate>Mon, 01 Jan 2024 13:00:00 +0000</pubDate>"
            b"<link>https://example.com/2</link></item>"
            b"</channel></rss>"
        )
        ns = NewsSentinel({"news_sentinel_enabled": False})
        items = ns._fetch_rss("https://example.com/rss")
        assert len(items) == 2
        assert items[0]["title"] == "Market Update"
        assert items[1]["title"] == "Economy News"
        assert "link" in items[0]
        assert "pub_ts" in items[0]

    @patch("core.news_sentinel.urlopen")
    def test_fetch_rss_handles_parse_error(self, mock_urlopen):
        """Malformed XML should return empty list, not crash."""
        mock_urlopen.return_value.__enter__.return_value.read.return_value = (
            b"not xml"
        )
        ns = NewsSentinel({"news_sentinel_enabled": False})
        items = ns._fetch_rss("https://example.com/rss")
        assert items == []

    @patch("core.news_sentinel.urlopen")
    def test_fetch_rss_handles_network_error(self, mock_urlopen):
        """Network errors should return empty list, not crash."""
        from urllib.error import URLError
        mock_urlopen.side_effect = URLError("connection failed")
        ns = NewsSentinel({"news_sentinel_enabled": False})
        items = ns._fetch_rss("https://example.com/rss")
        assert items == []

    @patch("core.news_sentinel.urlopen")
    def test_fetch_rss_respects_timeout_config(self, mock_urlopen):
        """The RSS timeout should come from config."""
        mock_urlopen.return_value.__enter__.return_value.read.return_value = (
            b'<?xml version="1.0"?><rss><channel></channel></rss>'
        )
        ns = NewsSentinel({"news_rss_timeout_secs": 3})
        ns._fetch_rss("https://example.com/rss")
        _call_kwargs = mock_urlopen.call_args[1]
        assert _call_kwargs.get("timeout") == 3

    @patch.object(NewsSentinel, "_fetch_rss")
    def test_run_one_poll_stores_worst_hit(self, mock_fetch):
        """_run_one_poll should cache the highest-risk headline found."""
        mock_fetch.return_value = [
            {"title": "Market halt triggered", "pub_ts": time.time()},
            {"title": "Normal market activity", "pub_ts": time.time()},
        ]
        ns = NewsSentinel({"news_sentinel_enabled": True})
        ns._run_one_poll()
        risk = ns.get_current_risk()
        assert risk.risk_level == "EXTREME"
        assert risk.risk_score == 1.0

    @patch.object(NewsSentinel, "_fetch_rss")
    def test_run_one_poll_skips_old_items(self, mock_fetch):
        """Items outside lookback window should be skipped."""
        mock_fetch.return_value = [
            {"title": "Rate hike announced", "pub_ts": time.time() - 7200},  # 2 hours old
        ]
        ns = NewsSentinel({"news_sentinel_enabled": True, "news_lookback_mins": 30})
        ns._run_one_poll()
        risk = ns.get_current_risk()
        assert risk.risk_level == "CLEAR"  # Too old to trigger

    @patch.object(NewsSentinel, "_fetch_rss")
    def test_run_one_poll_detects_highest_risk(self, mock_fetch):
        """If multiple articles, the highest risk level should be stored."""
        mock_fetch.return_value = [
            {"title": "FOMC meeting outcome", "pub_ts": time.time()},  # ELEVATED
            {"title": "Banking crisis warning", "pub_ts": time.time()},  # EXTREME
            {"title": "Rate hike speculation", "pub_ts": time.time()},  # HIGH
        ]
        ns = NewsSentinel({"news_sentinel_enabled": True, "news_lookback_mins": 120})
        ns._run_one_poll()
        risk = ns.get_current_risk()
        assert risk.risk_level == "EXTREME"
        assert "banking crisis" in str(risk.triggered_keywords).lower()

    @patch.object(NewsSentinel, "_fetch_rss")
    def test_run_one_poll_empty_feed(self, mock_fetch):
        """An empty RSS feed should leave the cache as CLEAR."""
        mock_fetch.return_value = []
        ns = NewsSentinel({"news_sentinel_enabled": True})
        ns._run_one_poll()
        risk = ns.get_current_risk()
        assert risk.risk_level == "CLEAR"

    @patch.object(NewsSentinel, "_fetch_rss")
    def test_sentiment_bullish(self, mock_fetch):
        """Headlines with bullish keywords should get BULLISH sentiment."""
        # Headline must include ELEVATED/HIGH/EXTREME risk keyword so _score_headline
        # returns a non-zero score that replaces the CLEAR baseline AND includes
        # bullish keywords for sentiment detection.
        mock_fetch.return_value = [
            {"title": "Earnings beat sparks strong rally and growth", "pub_ts": time.time()},
        ]
        ns = NewsSentinel({"news_sentinel_enabled": True})
        ns._run_one_poll()
        risk = ns.get_current_risk()
        assert risk.sentiment == "BULLISH"

    @patch.object(NewsSentinel, "_fetch_rss")
    def test_sentiment_bearish(self, mock_fetch):
        """Headlines with bearish keywords should get BEARISH sentiment."""
        mock_fetch.return_value = [
            {"title": "Rate hike sparks market crash and loss warning", "pub_ts": time.time()},
        ]
        ns = NewsSentinel({"news_sentinel_enabled": True})
        ns._run_one_poll()
        risk = ns.get_current_risk()
        assert risk.sentiment == "BEARISH"

    @patch.object(NewsSentinel, "_fetch_rss")
    def test_sentiment_mixed(self, mock_fetch):
        """Headlines with both bullish and bearish keywords should get MIXED."""
        mock_fetch.return_value = [
            {"title": "Earnings miss creates buying opportunity for strong recovery", "pub_ts": time.time()},
        ]
        ns = NewsSentinel({"news_sentinel_enabled": True})
        ns._run_one_poll()
        risk = ns.get_current_risk()
        assert risk.sentiment == "MIXED"

    @patch.object(NewsSentinel, "_fetch_rss")
    def test_sentiment_no_keywords(self, mock_fetch):
        """Headlines with no bullish/bearish keywords should be NEUTRAL."""
        mock_fetch.return_value = [
            {"title": "Markets open flat today", "pub_ts": time.time()},
        ]
        ns = NewsSentinel({"news_sentinel_enabled": True})
        ns._run_one_poll()
        risk = ns.get_current_risk()
        assert risk.sentiment == "NEUTRAL"


# ── Config update tests ──────────────────────────────────────────────────────

class TestNewsSentinelConfig:
    """Test update_config behavior."""

    def test_update_config(self):
        """update_config should replace the internal cfg dict."""
        ns = NewsSentinel({"news_sentinel_enabled": False})
        assert ns._cfg.get("news_sentinel_enabled") is False
        ns.update_config({"news_sentinel_enabled": True})
        assert ns._cfg.get("news_sentinel_enabled") is True
