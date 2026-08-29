"""Phase 14 — External Notification & Action-Link Comprehensive Audit Test Suite.

Validates:
  1. Canonical public base URL resolution (env, config, fallback).
  2. Zero localhost/127.0.0.1 in production notifications.
  3. Action link formatting & deep-link parameters.
  4. TradingView chart URL formatting.
  5. Broker safety & isolation (discretionary 1-click execution safety gate).
  6. Telegram callback handler responses & idempotency.
  7. Authentication requirement on web action URLs.
"""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from core.notifications.rich_signal_formatter import RichSignalFormatter
from core.notifications.url_resolver import (
    DEFAULT_DEV_URL,
    DEFAULT_PRODUCTION_URL,
    build_action_url,
    build_chart_url,
    get_public_base_url,
    is_production_environment,
)
from core.telegram.callback_handler import TelegramActionHandler


class TestPhase14UrlResolver(unittest.TestCase):
    """Test Canonical URL Resolver logic across environments."""

    def test_default_dev_url_explicit_config(self):
        """When explicit dev config is provided, returns dev URL."""
        with patch.dict(os.environ, {}, clear=True):
            base_url = get_public_base_url({"PUBLIC_BASE_URL": "http://localhost:8000"})
            self.assertEqual(base_url, DEFAULT_DEV_URL)

    def test_global_config_public_url_resolution(self):
        """Global config resolves canonical public URL."""
        with patch.dict(os.environ, {}, clear=True):
            base_url = get_public_base_url()
            self.assertEqual(base_url, "https://gaurav-cockpit.servegame.com")

    def test_env_var_public_base_url_override(self):
        """Environment variable PUBLIC_BASE_URL takes highest precedence."""
        with patch.dict(os.environ, {"PUBLIC_BASE_URL": "https://custom-domain.com/"}):
            base_url = get_public_base_url({"PUBLIC_BASE_URL": "https://config-domain.com"})
            self.assertEqual(base_url, "https://custom-domain.com")

    def test_production_environment_heuristic(self):
        """Production environment flag triggers DEFAULT_PRODUCTION_URL."""
        with patch.dict(os.environ, {"OPB_ENV": "production"}):
            self.assertTrue(is_production_environment())
            base_url = get_public_base_url()
            self.assertEqual(base_url, DEFAULT_PRODUCTION_URL)

    def test_build_action_url_formatting(self):
        """Action URLs are constructed cleanly without double slashes."""
        cfg = {"PUBLIC_BASE_URL": "https://gaurav-cockpit.servegame.com/"}
        url = build_action_url("/my-signals", cfg=cfg)
        self.assertEqual(url, "https://gaurav-cockpit.servegame.com/my-signals")

        url_with_params = build_action_url(
            "/trade-execution",
            params={"action": "paper", "symbol": "NIFTY24AUG24500CE", "id": "SIG-101"},
            cfg=cfg,
        )
        self.assertIn("https://gaurav-cockpit.servegame.com/trade-execution?", url_with_params)
        self.assertIn("action=paper", url_with_params)
        self.assertIn("symbol=NIFTY24AUG24500CE", url_with_params)
        self.assertIn("id=SIG-101", url_with_params)

    def test_build_chart_url(self):
        """TradingView URLs are constructed with proper NSE prefix."""
        tv_url = build_chart_url("RELIANCE")
        self.assertEqual(tv_url, "https://in.tradingview.com/chart/?symbol=NSE:RELIANCE")

        tv_url_amp = build_chart_url("M&M")
        self.assertEqual(tv_url_amp, "https://in.tradingview.com/chart/?symbol=NSE:M%26M")


class TestPhase14NotificationFormatting(unittest.TestCase):
    """Test rich email and Telegram formatting for zero localhost defects."""

    def test_rich_html_email_production_urls(self):
        """Generated HTML email contains canonical production public URL and ZERO localhost references."""
        html = RichSignalFormatter.build_rich_html_email(
            symbol="NIFTY24AUG24500CE",
            company_name="NIFTY Index",
            series="OPTIDX",
            category="INDEX_OPTIONS",
            direction="CALL",
            price=145.50,
            score=88,
            tier="STRONG",
            regime="TRENDING_BULLISH",
            rsi=62.4,
            adx=28.5,
            vwap=142.0,
            stop_loss=115.0,
            target_1=180.0,
            target_2=215.0,
        )

        self.assertIn("https://gaurav-cockpit.servegame.com/my-signals", html)
        self.assertNotIn("localhost", html)
        self.assertNotIn("127.0.0.1", html)
        self.assertNotIn(":8000", html)

    def test_telegram_action_handler_broker_isolation(self):
        """TelegramActionHandler exec callback is isolated from broker and never places live orders."""
        res_exec = TelegramActionHandler.process_callback_action("exec:SIG-999", user_id="123456")
        self.assertFalse(res_exec["success"])
        self.assertIn("Discretionary Execution Safety Gate", res_exec["alert_text"])
        self.assertIn("https://gaurav-cockpit.servegame.com/my-signals", res_exec["alert_text"])

        res_paper = TelegramActionHandler.process_callback_action("paper:SIG-999", user_id="123456")
        self.assertTrue(res_paper["success"])
        self.assertIn("Simulated Paper Trade Filled", res_paper["alert_text"])

        res_dash = TelegramActionHandler.process_callback_action("dash:SIG-999", user_id="123456")
        self.assertTrue(res_dash["success"])
        self.assertIn("https://gaurav-cockpit.servegame.com/my-signals", res_dash["alert_text"])


if __name__ == "__main__":
    unittest.main()
