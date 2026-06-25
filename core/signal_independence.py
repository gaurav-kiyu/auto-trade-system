"""
Signal Independence Validator - Ensures signals come from independent sources
PART 1 - Condition 2: RSI/MACD/ADX count as ONE pillar, need 2 of 3 pillars

MUST BE CALLED during signal generation to validate:
- RSI + MACD + ADX = 1 pillar (price/momentum)
- Options Market (IV, OI, PCR) = 1 pillar
- Institutional Flow (FII, DII, GEX) = 1 pillar
- Structural (session, time, events) = 1 pillar

At least 2 pillars must agree for trade to be allowed.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

_log = logging.getLogger(__name__)


@dataclass
class SignalPillar:
    name: str
    direction: str
    strength: float


class SignalIndependenceValidator:
    def __init__(self):
        self._pillars: dict[str, SignalPillar] = {}

    def reset(self):
        """Clear pillars for new signal evaluation"""
        self._pillars = {}

    def set_price_momentum_signal(
        self,
        rsi: float,
        macd: str,
        adx: float,
    ):
        """
        RSI + MACD + ADX = ONE pillar (not three!)
        These are all derived from same price data - not independent
        """
        if rsi and macd and adx:
            self._pillars["price_momentum"] = SignalPillar(
                name="Price/Momentum (RSI+MACD+ADX = 1 pillar)",
                direction=self._get_direction_from_rsi_macd(rsi, macd),
                strength=min(adx / 50, 1.0),
            )

    def set_options_market_signal(
        self,
        iv_rank: float,
        oi_change_pct: float,
        pcr: float,
    ):
        """
        Options Market = INDEPENDENT pillar
        IV rank, OI changes, PCR are derived from options data
        """
        if iv_rank is not None and oi_change_pct is not None and pcr is not None:
            direction = "BULLISH" if pcr < 1.0 else "BEARISH" if pcr > 1.2 else "NEUTRAL"
            self._pillars["options_market"] = SignalPillar(
                name="Options Market (IV+OI+PCR)",
                direction=direction,
                strength=min(iv_rank / 50, 1.0),
            )

    def set_institutional_flow_signal(
        self,
        fii_net: float,
        dii_net: float,
        gex: float,
    ):
        if fii_net is not None and dii_net is not None:
            total_flow = fii_net + dii_net
            direction = "BULLISH" if total_flow > 0 else "BEARISH" if total_flow < 0 else "NEUTRAL"
            strength = min(abs(total_flow) / 10000000, 1.0) if total_flow else 0.5
            self._pillars["institutional_flow"] = SignalPillar(
                name="Institutional Flow",
                direction=direction,
                strength=strength,
            )

    def set_structural_signal(
        self,
        session_score: float,
        time_context: str,
        event_clear: bool,
    ):
        if session_score is not None:
            direction = "BULLISH" if session_score > 60 else "BEARISH" if session_score < 40 else "NEUTRAL"
            strength = abs(session_score - 50) / 50
            self._pillars["structural"] = SignalPillar(
                name="Structural",
                direction=direction,
                strength=strength,
            )

    def validate_independence(self) -> tuple[bool, str, int]:
        num_pillars = len(self._pillars)

        if num_pillars < 2:
            return False, f"Only {num_pillars} pillar(s) available, need at least 2", num_pillars

        directions = [p.direction for p in self._pillars.values()]
        bullish_count = directions.count("BULLISH")
        bearish_count = directions.count("BEARISH")

        if bullish_count >= 2:
            return True, "Bullish consensus from 2+ pillars", num_pillars
        elif bearish_count >= 2:
            return True, "Bearish consensus from 2+ pillars", num_pillars

        return False, "No consensus (mixed directions)", num_pillars

    def get_aligned_pillars(self) -> list[str]:
        valid, _, _ = self.validate_independence()
        if not valid:
            return []
        # Determine consensus from pillar directions, not from the reason string
        consensus = self._resolve_consensus_direction()
        if consensus is None:
            return []
        return [p.name for p in self._pillars.values() if p.direction in [consensus, "NEUTRAL"]]

    def get_consensus_direction(self) -> str | None:
        valid, _, _ = self.validate_independence()
        if not valid:
            return None
        return self._resolve_consensus_direction()

    def _resolve_consensus_direction(self) -> str | None:
        """Resolve consensus direction from pillar directions."""
        directions = [p.direction for p in self._pillars.values()]
        bullish_count = directions.count("BULLISH")
        bearish_count = directions.count("BEARISH")
        if bullish_count >= 2:
            return "BULLISH"
        if bearish_count >= 2:
            return "BEARISH"
        return None

    def reset(self):
        self._pillars.clear()

    def _get_direction_from_rsi_macd(self, rsi: float, macd: str) -> str:
        rsi_dir = "BULLISH" if rsi > 55 else "BEARISH" if rsi < 45 else "NEUTRAL"
        if rsi_dir == "NEUTRAL":
            return macd if macd in ["BULLISH", "BEARISH"] else "NEUTRAL"
        return rsi_dir

    def get_summary(self) -> dict:
        return {
            "pillars": list(self._pillars.keys()),
            "num_pillars": len(self._pillars),
            "valid": self.validate_independence()[0],
            "direction": self.get_consensus_direction(),
        }


def create_signal_validator() -> SignalIndependenceValidator:
    return SignalIndependenceValidator()


__all__ = [
    "SignalIndependenceValidator",
    "SignalPillar",
    "create_signal_validator",
]

