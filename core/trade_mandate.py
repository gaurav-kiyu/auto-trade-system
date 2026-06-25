"""
Trade Mandate Enforcer - Comprehensive trading rules based on mandate
PART 1-10: All conditions, position sizing, risk rules, signal standards
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, time

from core.datetime_ist import now_ist

_log = logging.getLogger(__name__)


@dataclass
class MandateConfig:
    risk_per_trade: float = 0.015
    daily_hard_stop: float = 0.025
    weekly_circuit: float = 0.05
    max_drawdown_protection: float = 0.12
    loss_streak_cooldown_hours: float = 2.0
    min_expected_value: float = 40.0
    regime_confidence_min: float = 0.65
    vix_min: float = 12.0
    vix_max: float = 28.0
    vix_hard_block: float = 30.0
    data_staleness_sec: int = 30
    score_trending_min: int = 68
    score_sideways_min: int = 73
    score_range_min: int = 78
    block_high_iv_score: int = 75
    block_high_iv_threshold: float = 26.0
    min_iv_rank: float = 0.20
    finnifty_min_score: int = 72
    finnifty_min_iv_rank: float = 0.25
    finnifty_regime_required: bool = True
    regime_sizing_trending: float = 1.2
    regime_sizing_sideways: float = 0.85
    regime_sizing_range: float = 0.75
    sizing_uncertainty: float = 0.5
    max_positions: int = 2
    event_cooldown_minutes: int = 30
    loss_streak_threshold: int = 3
    cost_stt_pct: float = 0.0005
    cost_brokerage: float = 20.0
    cost_exchange_gst: float = 50.0
    cost_bid_ask_estimate: float = 3.0
    slippage_assume_pct: float = 0.20
    win_reduction_pct: float = 0.20
    limit_order_timeout_sec: int = 90
    validation_min_observations: int = 80


class OperatingMode:
    STANDARD = "STANDARD"
    CAUTIOUS = "CAUTIOUS"
    HIGH_STRESS = "HIGH_STRESS"
    EXTREME = "EXTREME"
    OBSERVE_ONLY = "OBSERVE_ONLY"


class TradeDecision:
    ALLOWED = "ALLOWED"
    BLOCKED = "BLOCKED"
    NEEDS_REVIEW = "NEEDS_REVIEW"


@dataclass
class TradeEligibility:
    decision: str
    reason: str
    risk_amount: float = 0.0
    expected_value: float = 0.0
    mode: str = OperatingMode.STANDARD


class TradeMandateEnforcer:
    def __init__(self, config: dict):
        self.cfg = self._load_config(config)
        self._current_vix: float | None = None
        self._last_data_time: datetime | None = None
        self._loss_streak: int = 0
        self._last_trade_time: datetime | None = None
        self._trades_today: int = 0
        self._daily_pnl: float = 0.0
        self._weekly_pnl: float = 0.0
        self._equity_peak: float = 0.0
        self._current_capital: float = config.get("BASE_CAPITAL", 5000)

    def _load_config(self, config: dict) -> MandateConfig:
        return MandateConfig(
            risk_per_trade=config.get("MANDATE_RISK_PER_TRADE", 0.015),
            daily_hard_stop=config.get("MANDATE_DAILY_HARD_STOP", 0.025),
            weekly_circuit=config.get("MANDATE_WEEKLY_CIRCUIT_BREAKER", 0.05),
            max_drawdown_protection=config.get("MANDATE_MAX_DRAWDOWN_PROTECTION", 0.12),
            loss_streak_cooldown_hours=config.get("MANDATE_LOSS_STREAK_COOLDOWN_HOURS", 2.0),
            min_expected_value=config.get("MANDATE_MIN_EXPECTED_VALUE", 40.0),
            regime_confidence_min=config.get("MANDATE_REGIME_CONFIDENCE_MIN", 0.65),
            vix_min=config.get("MANDATE_VIX_MIN", 12.0),
            vix_max=config.get("MANDATE_VIX_MAX", 28.0),
            vix_hard_block=config.get("MANDATE_VIX_HARD_BLOCK", 30.0),
            data_staleness_sec=config.get("MANDATE_DATA_STALENESS_SEC", 30),
            score_trending_min=config.get("MANDATE_MIN_Score_TRENDING", 68),
            score_sideways_min=config.get("MANDATE_MIN_SCORE_SIDEWAYS", 73),
            score_range_min=config.get("MANDATE_MIN_SCORE_RANGE", 78),
            block_high_iv_score=config.get("MANDATE_BLOCK_HIGH_IV_SCORE", 75),
            block_high_iv_threshold=config.get("MANDATE_BLOCK_HIGH_IV_THRESHOLD", 26.0),
            min_iv_rank=config.get("MANDATE_MIN_IV_RANK", 0.20),
            finnifty_min_score=config.get("MANDATE_FINNIFTY_MIN_SCORE", 72),
            finnifty_min_iv_rank=config.get("MANDATE_FINNIFTY_MIN_IV_RANK", 0.25),
            finnifty_regime_required=config.get("MANDATE_FINNIFTY_REGIME_REQUIRED", True),
            regime_sizing_trending=config.get("MANDATE_REGIME_SIZING_TRENDING", 1.2),
            regime_sizing_sideways=config.get("MANDATE_REGIME_SIZING_SIDEWAYS", 0.85),
            regime_sizing_range=config.get("MANDATE_REGIME_SIZING_RANGE", 0.75),
            sizing_uncertainty=config.get("MANDATE_SIZING_UNCERTAINTY", 0.5),
            max_positions=config.get("MANDATE_MAX_POSITIONS_SAME_TIME", 2),
            event_cooldown_minutes=config.get("MANDATE_EVENT_COOLDOWN_MINUTES", 30),
            loss_streak_threshold=config.get("MANDATE_LOSS_STREAK_THRESHOLD", 3),
            cost_stt_pct=config.get("MANDATE_COST_STT_PCT", 0.0005),
            cost_brokerage=config.get("MANDATE_COST_BROKERAGE", 20.0),
            cost_exchange_gst=config.get("MANDATE_COST_EXCHANGE_GST", 50.0),
            cost_bid_ask_estimate=config.get("MANDATE_COST_BID_ASK_ESTIMATE", 3.0),
            slippage_assume_pct=config.get("MANDATE_SLIPPAGE_ASSUME_PCT", 0.20),
            win_reduction_pct=config.get("MANDATE_WIN_REDUCTION_PCT", 0.20),
            limit_order_timeout_sec=config.get("MANDATE_LIMIT_ORDER_TIMEOUT_SEC", 90),
        )

    def update_market_state(self, vix: float, last_tick_time: datetime):
        self._current_vix = vix
        self._last_data_time = last_tick_time

    def update_capital_state(self, capital: float, equity_peak: float, daily_pnl: float, weekly_pnl: float):
        self._current_capital = capital
        self._equity_peak = equity_peak
        self._daily_pnl = daily_pnl
        self._weekly_pnl = weekly_pnl

    def record_trade_result(self, pnl: float, timestamp: datetime):
        if pnl < 0:
            self._loss_streak += 1
        else:
            self._loss_streak = 0
        self._last_trade_time = timestamp
        self._trades_today += 1
        self._daily_pnl += pnl

    def reset_daily(self):
        self._trades_today = 0

    def get_operating_mode(self) -> str:
        if self._current_vix is None:
            return OperatingMode.STANDARD

        vix = self._current_vix
        drawdown = (self._equity_peak - self._current_capital) / self._equity_peak if self._equity_peak > 0 else 0

        if vix > self.cfg.vix_hard_block or drawdown > 0.08:
            return OperatingMode.OBSERVE_ONLY
        elif vix > 28 or (vix > 25 and self._loss_streak >= 2):
            return OperatingMode.HIGH_STRESS
        elif vix > 20:
            return OperatingMode.CAUTIOUS
        return OperatingMode.STANDARD

    def check_trade_eligibility(
        self,
        index_name: str,
        score: int,
        regime: str,
        regime_confidence: float,
        iv_rank: float,
        avg_win: float,
        avg_loss: float,
        win_rate: float,
        current_positions: int,
    ) -> TradeEligibility:
        mode = self.get_operating_mode()

        if mode == OperatingMode.OBSERVE_ONLY:
            return TradeEligibility(TradeDecision.BLOCKED, f"Operating mode: {mode}", mode=mode)

        if current_positions >= self.cfg.max_positions:
            return TradeEligibility(TradeDecision.BLOCKED, f"Max positions ({self.cfg.max_positions}) reached", mode=mode)

        if self._loss_streak >= self.cfg.loss_streak_threshold and self._last_trade_time:
            from datetime import timedelta
            cooldown_end = self._last_trade_time + timedelta(hours=self.cfg.loss_streak_cooldown_hours)
            if now_ist() < cooldown_end:
                return TradeEligibility(TradeDecision.BLOCKED, "Loss streak cooldown active", mode=mode)

        if self._current_vix is not None:
            if self._current_vix < self.cfg.vix_min:
                return TradeEligibility(TradeDecision.BLOCKED, f"VIX {self._current_vix} below minimum {self.cfg.vix_min}", mode=mode)
            if self._current_vix > self.cfg.vix_hard_block:
                return TradeEligibility(TradeDecision.BLOCKED, f"VIX {self._current_vix} above hard block {self.cfg.vix_hard_block}", mode=mode)

        if not self._is_trading_window():
            return TradeEligibility(TradeDecision.BLOCKED, "Outside trading window (9:20-11:30 or 13:00-14:45 IST)", mode=mode)

        if regime_confidence < self.cfg.regime_confidence_min:
            return TradeEligibility(TradeDecision.BLOCKED, f"Regime confidence {regime_confidence:.2f} below minimum {self.cfg.regime_confidence_min}", mode=mode)

        min_score = self._get_min_score_by_regime(regime)
        if score < min_score:
            return TradeEligibility(TradeDecision.BLOCKED, f"Score {score} below minimum for {regime} ({min_score})", mode=mode)

        if score >= self.cfg.block_high_iv_score and iv_rank >= self.cfg.block_high_iv_threshold:
            return TradeEligibility(TradeDecision.BLOCKED, f"False signal filter: high score ({score}) + high IV ({iv_rank:.1f})", mode=mode)

        if iv_rank < self.cfg.min_iv_rank:
            return TradeEligibility(TradeDecision.BLOCKED, f"IV rank {iv_rank:.1%} below minimum {self.cfg.min_iv_rank:.1%}", mode=mode)

        if index_name == "FINNIFTY":
            if score < self.cfg.finnifty_min_score:
                return TradeEligibility(TradeDecision.BLOCKED, f"FINNIFTY score {score} below minimum {self.cfg.finnifty_min_score}", mode=mode)
            if iv_rank < self.cfg.finnifty_min_iv_rank:
                return TradeEligibility(TradeDecision.BLOCKED, f"FINNIFTY IV rank {iv_rank:.1%} below minimum {self.cfg.finnifty_min_iv_rank:.1%}", mode=mode)
            if self.cfg.finnifty_regime_required and regime.upper() not in ["TRENDING", "BULLISH"]:
                return TradeEligibility(TradeDecision.BLOCKED, f"FINNIFTY requires TRENDING regime, got {regime}", mode=mode)

        expected_value = self._calculate_expected_value(win_rate, avg_win, avg_loss)
        if expected_value < self.cfg.min_expected_value:
            return TradeEligibility(TradeDecision.BLOCKED, f"Expected value {expected_value:.0f} below minimum {self.cfg.min_expected_value}", mode=mode)

        risk_amount = self._calculate_risk_amount(regime)
        return TradeEligibility(TradeDecision.ALLOWED, "All mandate checks passed", risk_amount=risk_amount, expected_value=expected_value, mode=mode)

    def _is_trading_window(self) -> bool:
        now = now_ist()
        ist_hour = now.hour
        ist_minute = now.minute

        morning_start = time(9, 20)
        morning_end = time(11, 30)
        afternoon_start = time(13, 0)
        afternoon_end = time(14, 45)

        current_time = time(ist_hour, ist_minute)

        if morning_start <= current_time <= morning_end:
            return True
        if afternoon_start <= current_time <= afternoon_end:
            return True
        return False

    def _get_min_score_by_regime(self, regime: str) -> int:
        r = regime.upper() if regime else ""
        if r == "TRENDING" or r == "BULLISH":
            return self.cfg.score_trending_min
        elif r == "SIDEWAYS" or r == "NEUTRAL":
            return self.cfg.score_sideways_min
        elif r == "RANGE" or r == "CHOPPY":
            return self.cfg.score_range_min
        return self.cfg.score_sideways_min

    def _calculate_expected_value(self, win_rate: float, avg_win: float, avg_loss: float) -> float:
        loss_rate = 1 - win_rate
        friction = self.cfg.cost_brokerage + self.cfg.cost_exchange_gst + self.cfg.cost_bid_ask_estimate
        adjusted_win = avg_win * (1 - self.cfg.win_reduction_pct)
        adjusted_loss = abs(avg_loss) * (1 + self.cfg.slippage_assume_pct)
        return (win_rate * adjusted_win) - (loss_rate * adjusted_loss) - friction

    def _calculate_risk_amount(self, regime: str) -> float:
        base_risk = self._current_capital * self.cfg.risk_per_trade
        r = regime.upper() if regime else ""
        if r == "TRENDING" or r == "BULLISH":
            return base_risk * self.cfg.regime_sizing_trending
        elif r == "SIDEWAYS" or r == "NEUTRAL":
            return base_risk * self.cfg.regime_sizing_sideways
        elif r == "RANGE" or r == "CHOPPY":
            return base_risk * self.cfg.regime_sizing_range
        return base_risk * self.cfg.sizing_uncertainty

    def get_position_sizing(self, regime: str, uncertainty: bool = False) -> float:
        if uncertainty:
            return self.cfg.sizing_uncertainty
        return self._calculate_risk_amount(regime)


def create_mandate_enforcer(config: dict) -> TradeMandateEnforcer:
    return TradeMandateEnforcer(config)


__all__ = [
    "MandateConfig",
    "OperatingMode",
    "TradeDecision",
    "TradeEligibility",
    "TradeMandateEnforcer",
    "create_mandate_enforcer",
]

