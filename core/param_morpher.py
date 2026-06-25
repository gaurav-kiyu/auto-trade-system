import logging
from dataclasses import dataclass
from typing import Any


__all__ = [
    "MorphedParams",
    "ParamMorpher",
]

@dataclass
class MorphedParams:
    sl_mult: float
    tgt_mult: float
    risk_mult: float
    label: str

class ParamMorpher:
    """
    Adjusts trading parameters dynamically based on the discovered market regime.
    """
    def __init__(self, cfg: dict[str, Any]):
        self.cfg = cfg
        self.logger = logging.getLogger(__name__)

        # Regime -> (SL_Mult, TGT_Mult, RISK_Mult)
        self.regime_map = {
            "TRENDING": (1.2, 1.5, 1.0),  # Give room to breathe, aim higher
            "CHOPPY": (0.8, 0.7, 0.6),    # Tighten everything, reduce risk
            "PANIC": (0.5, 0.4, 0.3),     # Extreme protection, minimal targets
            "NEUTRAL": (1.0, 1.0, 1.0)    # Standard config
        }

    def get_morphed_params(self, regime: str) -> MorphedParams:
        """Returns the multipliers for the given regime."""
        mults = self.regime_map.get(regime.upper(), self.regime_map["NEUTRAL"])
        return MorphedParams(
            sl_mult=mults[0],
            tgt_mult=mults[1],
            risk_mult=mults[2],
            label=regime.upper()
        )

    def apply_to_config(self, base_val: float, multiplier: float) -> float:
        """Applies a multiplier to a base config value."""
        return round(base_val * multiplier, 4)
