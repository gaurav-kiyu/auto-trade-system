"""Unit tests for the 4 Institutional Strategic Upgrades (v3.0)."""

from core.options.gex_iv_engine import GammaExposureEngine
from core.market.sector_rotation_radar import SectorRotationRadar
from core.telegram.callback_handler import TelegramActionHandler
from core.ai.post_market_debrief import PostMarketDebriefEngine


def test_gamma_exposure_and_iv_engine():
    spot = 24500.0
    options_sample = [
        {"strike": 24300, "call_oi": 15000, "put_oi": 65000, "call_iv": 14.0, "put_iv": 15.5, "dte": 4.0},
        {"strike": 24400, "call_oi": 25000, "put_oi": 55000, "call_iv": 14.2, "put_iv": 15.2, "dte": 4.0},
        {"strike": 24500, "call_oi": 45000, "put_oi": 42000, "call_iv": 14.5, "put_iv": 14.8, "dte": 4.0},
        {"strike": 24600, "call_oi": 68000, "put_oi": 22000, "call_iv": 15.0, "put_iv": 14.5, "dte": 4.0},
        {"strike": 24700, "call_oi": 85000, "put_oi": 12000, "call_iv": 15.5, "put_iv": 14.2, "dte": 4.0},
    ]

    res = GammaExposureEngine.analyze_options_chain(spot_price=spot, options_data=options_sample)
    assert res.spot_price == 24500.0
    assert len(res.strikes_gex) == 5
    assert res.call_wall_strike == 24700.0
    assert res.put_wall_strike == 24300.0
    assert res.zero_gamma_flip > 0
    assert res.iv_rank_pct >= 0
    assert res.iv_percentile_pct >= 0


def test_sector_rotation_radar():
    matrix = SectorRotationRadar.get_live_sector_matrix()
    assert len(matrix) == 12

    # Check quadrants present
    quads = {s["quadrant"] for s in matrix}
    assert "LEADING" in quads
    assert "IMPROVING" in quads
    assert "WEAKENING" in quads
    assert "LAGGING" in quads

    # Stock sector resolution
    assert SectorRotationRadar.get_sector_for_stock("TCS") == "NIFTY IT"
    assert SectorRotationRadar.get_sector_for_stock("TATAMOTORS") == "NIFTY AUTO"
    assert SectorRotationRadar.get_sector_for_stock("HDFCBANK") == "NIFTY BANK"

    # Sector boost
    tcs_boost = SectorRotationRadar.get_sector_boost("TCS")
    assert tcs_boost == 5  # IT is Leading


def test_telegram_action_handler():
    # 1. Paper trade callback
    res1 = TelegramActionHandler.process_callback_action("paper:SIG-2026-TCS", "1148730533")
    assert res1["success"] is True
    assert "Paper Trade Filled" in res1["alert_text"]

    # 2. Broker execution callback - regression: this used to claim an order
    # was dispatched via a canned success message with no execution behind
    # it at all (core.adapters.broker_adapters is never called here).
    res2 = TelegramActionHandler.process_callback_action("exec:SIG-2026-RELIANCE", "1148730533")
    assert res2["success"] is False
    assert "authenticated web confirmation" in res2["alert_text"]
    assert "Dispatched" not in res2["alert_text"]


def test_post_market_ai_debrief():
    debrief = PostMarketDebriefEngine.generate_daily_debrief()
    assert "market_summary" in debrief
    assert "performance_scorecard" in debrief
    assert debrief["performance_scorecard"]["win_rate_pct"] > 80
    assert len(debrief["dominant_success_factors"]) >= 3
    assert len(debrief["actionable_recommendations"]) >= 2
