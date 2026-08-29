"""Unified Signal Evaluator — Dispatches signal generation by AssetType.

Provides a single entry point for evaluating trading signals across all
supported asset classes. Each asset class has its own signal strategy,
wired through a common interface.

Usage:
    from core.services.signal_evaluator import SignalEvaluator
    from core.common.models import AssetType

    evaluator = SignalEvaluator(config)
    result = evaluator.evaluate(
        symbol="RELIANCE",
        asset_type=AssetType.EQUITY,
        df1m=df1,
        df5m=df5,
        df15m=df15,
        vix=vix,
    )
    if result and result.score >= 55:
        # Route to execution
        dispatcher.route(symbol, signal=result.to_dict())
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from core.common.models import AssetType

_log = logging.getLogger(__name__)


# =============================================================================
# Standardised Signal Result
# =============================================================================


@dataclass
class SignalResult:
    """Standardised signal evaluation result across all asset classes.

    Attributes:
        symbol: Trading symbol.
        direction: Trade direction (BUY/SELL or CALL/PUT).
        score: Signal score (0–100).
        strength: Classified strength (STRONG / MODERATE / WEAK / IGNORE).
        confidence: Confidence multiplier (0.0–1.0).
        price: Market price at signal time.
        asset_type: Asset class of the signal.
        regime: Market regime at signal time.
        score_components: Per-component point breakdown.
        features: List of positive-scoring feature names.
        risk: Dict of risk metadata (atr_pct, volatility_tier, etc.).
        rsi: RSI value at signal time.
        atr: ATR value at signal time.
        adx: ADX value at signal time.
        vwap: VWAP value at signal time.
        vol_ratio: Volume ratio at signal time.
        macd: MACD dict (macd, signal, histogram).
        reason: Human-readable signal reason.
        timestamp: Unix timestamp of signal generation.
    """
    symbol: str
    direction: str
    score: int
    strength: str
    confidence: float = 1.0
    price: float = 0.0
    asset_type: AssetType = AssetType.UNKNOWN
    regime: str = "NEUTRAL"
    score_components: dict[str, int] = field(default_factory=dict)
    features: list[str] = field(default_factory=list)
    risk: dict[str, Any] = field(default_factory=dict)
    rsi: float = 50.0
    atr: float = 0.0
    adx: float = 0.0
    vwap: float = 0.0
    vol_ratio: float = 0.0
    macd: dict[str, float] = field(default_factory=dict)
    reason: str = ""
    timestamp: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Convert to a standard signal dict for downstream routing."""
        return {
            "direction": self.direction,
            "score": self.score,
            "price": self.price,
            "strength": self.strength,
            "score_components": self.score_components,
            "features": self.features,
            "regime": self.regime,
            "risk": self.risk,
            "rsi": self.rsi,
            "atr": self.atr,
            "adx": self.adx,
            "vwap": self.vwap,
            "vol_ratio": self.vol_ratio,
            "macd": self.macd,
            "symbol": self.symbol,
            "signal_ts": self.timestamp or time.time(),
            "asset_type": self.asset_type.value,
            "reason": self.reason,
        }

    def is_actionable(self, min_score: int = 35) -> bool:
        """Check if this signal meets the minimum threshold for action.

        Args:
            min_score: Minimum score threshold (default 35 for WEAK).

        Returns:
            True if score >= min_score and strength != IGNORE.
        """
        return self.score >= min_score and self.strength != "IGNORE"


# =============================================================================
# Signal Strategies (one per asset class)
# =============================================================================


class _BaseSignalStrategy:
    """Base class for asset-class-specific signal strategies."""

    def __init__(self, config: dict[str, Any]) -> None:
        self._cfg = config

    def evaluate(
        self,
        symbol: str,
        df1m: pd.DataFrame | None = None,
        df5m: pd.DataFrame | None = None,
        df15m: pd.DataFrame | None = None,
        **kwargs: Any,
    ) -> SignalResult | None:
        """Evaluate a trading signal for a symbol.

        Args:
            symbol: Trading symbol.
            df1m: 1-minute OHLCV DataFrame.
            df5m: 5-minute OHLCV DataFrame.
            df15m: 15-minute OHLCV DataFrame.
            **kwargs: Additional asset-class-specific parameters (vix, pcr, etc.).

        Returns:
            SignalResult if actionable, None if not.
        """
        raise NotImplementedError


class _IndexOptionsSignalStrategy(_BaseSignalStrategy):
    """Signal strategy for index options (NIFTY, BANKNIFTY, FINNIFTY).

    Wraps the existing ``evaluate_adaptive_signal()`` pipeline which uses
    multi-timeframe data, VIX, OI data, and ML validation.
    """

    def evaluate(
        self,
        symbol: str,
        df1m: pd.DataFrame | None = None,
        df5m: pd.DataFrame | None = None,
        df15m: pd.DataFrame | None = None,
        **kwargs: Any,
    ) -> SignalResult | None:
        # Delegate to the existing adaptive signal pipeline
        from core.adaptive_signal import evaluate_adaptive_signal
        from core.pure_index_signal import PureIndexRegimeParams, PureIndexSignalParams

        if df1m is None or df5m is None or df15m is None:
            return None

        vix = float(kwargs.get("vix", 0.0))
        iv = float(kwargs.get("iv", 0.0))
        pcr = float(kwargs.get("pcr", 1.0))
        smart = str(kwargs.get("smart", "NEUTRAL"))
        oi_sup = float(kwargs.get("oi_sup", 0.0))
        oi_res = float(kwargs.get("oi_res", 0.0))
        learning_bonus = int(kwargs.get("learning_score_bonus", 0))
        capital = float(kwargs.get("capital", 100_000.0))

        params = PureIndexSignalParams(
            name=symbol,
            signal_cfg=dict(self._cfg),
            regime=PureIndexRegimeParams(
                vix_block_threshold=float(self._cfg.get("VIX_BLOCK_THRESHOLD", 27)),
                adx_trend_threshold=float(self._cfg.get("REGIME_ADX_TREND", 20)),
                adx_chop_threshold=float(self._cfg.get("REGIME_ADX_RANGE", 15)),
            ),
            iv_spike_threshold=float(self._cfg.get("IV_SPIKE_THRESHOLD", 50)),
            vol_ratio_min=float(self._cfg.get("VOL_RATIO_MIN", 1.2)),
            is_early_session=bool(kwargs.get("is_early_session", False)),
        )

        try:
            adaptive_signal, reason = evaluate_adaptive_signal(
                params=params,
                df1=df1m, df5=df5m, df15=df15m,
                vix=vix, iv=iv,
                oi_sup=oi_sup, oi_res=oi_res,
                pcr=pcr, smart=smart,
                learning_score_bonus=learning_bonus,
                capital=capital,
            )
        except (ValueError, TypeError, KeyError, AttributeError, OSError) as exc:
            _log.debug("[SIGNAL_EVAL] Index options signal failed for %s: %s", symbol, exc)
            return None

        if adaptive_signal is None:
            return None

        return SignalResult(
            symbol=symbol,
            direction=adaptive_signal.direction,
            score=adaptive_signal.score,
            strength=adaptive_signal.tier,
            confidence=adaptive_signal.confidence,
            price=adaptive_signal.price,
            asset_type=AssetType.INDEX_OPTIONS,
            regime=adaptive_signal.regime,
            score_components=adaptive_signal.score_components,
            features=adaptive_signal.features,
            risk=adaptive_signal.risk,
            rsi=adaptive_signal.rsi,
            atr=adaptive_signal.atr,
            adx=adaptive_signal.adx,
            vwap=adaptive_signal.vwap,
            vol_ratio=adaptive_signal.vol_ratio,
            macd=adaptive_signal.macd,
            reason=" | ".join(adaptive_signal.reasons[-3:]),
        )


class _EquitySignalStrategy(_BaseSignalStrategy):
    """Signal strategy for equities, ETFs, REITs, InvITs & SME stocks.

    Uses the existing ``evaluate_equity_signal()`` method from EquityTrader
    which generates signals from 1m OHLCV data using FeatureEngine.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self._trader: Any | None = None  # Lazy-initialized cached trader

    def _get_trader(self) -> Any | None:
        """Get or create cached EquityTrader instance."""
        if self._trader is None:
            try:
                from core.equity_trader import EquityTrader
                self._trader = EquityTrader(cfg=self._cfg)
            except (ImportError, ValueError, TypeError, OSError) as exc:
                _log.warning("[SIGNAL_EVAL] Could not create EquityTrader: %s", exc)
                return None
        return self._trader

    def evaluate(
        self,
        symbol: str,
        df1m: pd.DataFrame | None = None,
        df5m: pd.DataFrame | None = None,
        df15m: pd.DataFrame | None = None,
        **kwargs: Any,
    ) -> SignalResult | None:
        # Equity signal only needs 1m data
        if df1m is None or len(df1m) < 30:
            return None

        trader = self._get_trader()
        if trader is None:
            return None

        try:
            equity_sig = trader.evaluate_equity_signal(symbol, df1m)
        except (ValueError, TypeError, KeyError, IndexError, AttributeError, OSError) as exc:
            _log.debug("[SIGNAL_EVAL] Equity signal failed for %s: %s", symbol, exc)
            return None

        if equity_sig is None:
            return None

        direction = str(equity_sig.get("direction", "BUY"))
        score = int(equity_sig.get("score", 0))
        strength = str(equity_sig.get("strength", "WEAK"))
        price = float(equity_sig.get("price", 0.0))
        regime = str(equity_sig.get("regime", "NEUTRAL"))

        return SignalResult(
            symbol=symbol,
            direction=direction,
            score=score,
            strength=strength,
            price=price,
            asset_type=AssetType.EQUITY,
            regime=regime,
            score_components=dict(equity_sig.get("score_components", {})),
            features=list(equity_sig.get("features", [])),
            risk=dict(equity_sig.get("risk", {})),
            rsi=float(equity_sig.get("rsi", 50.0)),
            atr=float(equity_sig.get("atr", 0.0)),
            adx=float(equity_sig.get("adx", 0.0)),
            vwap=float(equity_sig.get("vwap", 0.0)),
            vol_ratio=float(equity_sig.get("vol_ratio", 1.0)),
            macd=dict(equity_sig.get("macd", {})),
            reason=f"Score: {score} | Regime: {regime}",
        )


class _FuturesSignalStrategy(_BaseSignalStrategy):
    """Signal strategy for futures, commodities, and currency pairs.

    Generates signals using FeatureEngine technical indicators with
    asset-class-specific scoring parameters. Supports:
      - FUTURES: index futures, stock futures
      - COMMODITY: MCX commodity futures (GOLD, SILVER, CRUDEOIL, etc.)
      - CURRENCY: CDS currency futures (USDINR, EURINR, etc.)
    """

    def __init__(self, config: dict[str, Any], asset_type: AssetType) -> None:
        super().__init__(config)
        self._asset_type = asset_type
        # Asset-class-specific scoring thresholds
        if asset_type == AssetType.FUTURES:
            self._score_prefix = "FUTURES"
        elif asset_type == AssetType.COMMODITY:
            self._score_prefix = "COMMODITY"
        elif asset_type == AssetType.CURRENCY:
            self._score_prefix = "CURRENCY"
        else:
            self._score_prefix = "FUTURES"

    def _get_cfg(self, key: str, default: Any) -> Any:
        """Get config key with asset-class prefix, falling back to generic key."""
        prefixed = f"{self._score_prefix}_{key}"
        return self._cfg.get(prefixed, self._cfg.get(key, default))

    def evaluate(
        self,
        symbol: str,
        df1m: pd.DataFrame | None = None,
        df5m: pd.DataFrame | None = None,
        df15m: pd.DataFrame | None = None,
        **kwargs: Any,
    ) -> SignalResult | None:
        # Need at least 1m data
        if df1m is None or len(df1m) < 30:
            return None

        try:
            from core.feature_engine import FeatureEngine as _FE

            price = _FE.get_price(df1m)
            if price <= 0:
                return None

            vwap = _FE.get_vwap(df1m)
            atr = _FE.get_atr(df1m)
            vol_ratio = _FE.get_vol_ratio(df1m)
            rsi_val = _FE.get_rsi(df1m)
            adx_val = _FE.get_adx(df1m)
            macd = _FE.get_macd(df1m)
            d10 = _FE.price_delta(df1m, 10)
            d30 = _FE.price_delta(df1m, 30)
            ema_trend = _FE.ema_trend(df1m)

            # Regime detection
            if adx_val > 25:
                regime = "TRENDING"
            elif adx_val < 20:
                regime = "CHOPPY"
            else:
                regime = "NEUTRAL"

            # ── Scoring ──────────────────────────────────────────────────
            _score = 0
            direction: str | None = None
            score_comps: dict[str, int] = {}

            # EMA trend (15 pts)
            if ema_trend == "UP":
                _score += 15
                score_comps["ema_trend"] = 15
                direction = "BUY"
            elif ema_trend == "DOWN":
                _score += 15
                score_comps["ema_trend"] = 15
                direction = "SELL"
            else:
                score_comps["ema_trend"] = 0

            if direction is None:
                return None  # No clear direction

            # VWAP position (15 pts)
            if (direction == "BUY" and price > vwap) or (direction == "SELL" and price < vwap):
                dist = abs(price - vwap) / max(vwap, 1.0)
                vwap_pts = min(15, 5 + int(min(1.0, dist / 0.005) * 10))
                _score += vwap_pts
                score_comps["vwap"] = vwap_pts
            else:
                score_comps["vwap"] = 0

            # Momentum (12 pts)
            mom_pts = 12 if (direction == "BUY" and d10 > 0) or (direction == "SELL" and d10 < 0) else 0
            _score += mom_pts
            score_comps["momentum"] = mom_pts

            # Longer momentum (8 pts)
            d30_pts = 8 if (direction == "BUY" and d30 > 0) or (direction == "SELL" and d30 < 0) else 0
            _score += d30_pts
            score_comps["momentum_30"] = d30_pts

            # Volume confirmation (12 pts)
            vol_min = float(self._get_cfg("VOL_RATIO_MIN", 1.2))
            if vol_ratio >= vol_min:
                excess = (vol_ratio - vol_min) / max(vol_min, 0.5)
                vol_pts = min(12, 3 + int(min(1.0, excess) * 9))
                _score += vol_pts
                score_comps["volume"] = vol_pts
            else:
                score_comps["volume"] = 0

            # RSI healthy zone (8 pts)
            if (direction == "BUY" and 40 <= rsi_val <= 70) or (direction == "SELL" and 30 <= rsi_val <= 60):
                score_comps["rsi_bonus"] = 8
                _score += 8
            else:
                score_comps["rsi_bonus"] = 0

            # ATR floor (5 pts)
            atr_min_pct = float(self._get_cfg("ATR_MIN_PCT", 0.001))
            if atr > price * atr_min_pct:
                score_comps["atr_floor"] = 5
                _score += 5
            else:
                score_comps["atr_floor"] = 0

            # MACD histogram (5 pts)
            if (macd["histogram"] > 0 and direction == "BUY") or (macd["histogram"] < 0 and direction == "SELL"):
                score_comps["macd"] = 5
                _score += 5
            else:
                score_comps["macd"] = 0

            # ADX trend bonus (5 pts)
            if adx_val >= 25:
                score_comps["adx_trend"] = 5
                _score += 5
            else:
                score_comps["adx_trend"] = 0

            # Regime penalty
            if regime == "CHOPPY":
                _score = max(0, _score - 8)
                score_comps["regime_penalty"] = -8
            elif adx_val < 15:
                _score = max(0, _score - 15)
                score_comps["regime_penalty"] = -15
            else:
                score_comps["regime_penalty"] = 0

            score = min(100, max(0, _score))

            # Strength classification
            if score >= 70:
                strength = "STRONG"
            elif score >= 50:
                strength = "MODERATE"
            elif score >= 35:
                strength = "WEAK"
            else:
                return None

            features = [k for k, v in score_comps.items() if v > 0]

            risk = {
                "atr_pct": round(atr / max(price, 1.0) * 100, 2),
                "regime": regime,
                "adx": round(adx_val, 1),
                "asset_type": self._asset_type.value,
            }

            return SignalResult(
                symbol=symbol,
                direction=direction,
                score=score,
                strength=strength,
                price=price,
                asset_type=self._asset_type,
                regime=regime,
                score_components=score_comps,
                features=features,
                risk=risk,
                rsi=round(rsi_val, 1),
                atr=round(atr, 2),
                adx=round(adx_val, 1),
                vwap=round(vwap, 2),
                vol_ratio=round(vol_ratio, 2),
                macd=macd,
                reason=f"Score: {score} | Regime: {regime} | {direction}",
            )

        except (ValueError, TypeError, KeyError, IndexError, AttributeError) as exc:
            _log.debug("[SIGNAL_EVAL] %s signal failed for %s: %s",
                       self._asset_type.value, symbol, exc)
            return None


# =============================================================================
# Strategy Registry
# =============================================================================

# Maps AssetType to its signal strategy class (lazy-initialized)
_DEFAULT_STRATEGY_MAP: dict[AssetType, type[_BaseSignalStrategy]] = {
    AssetType.INDEX_OPTIONS: _IndexOptionsSignalStrategy,
    AssetType.EQUITY: _EquitySignalStrategy,
    AssetType.ETF: _EquitySignalStrategy,
    AssetType.REIT: _EquitySignalStrategy,
    AssetType.INVIT: _EquitySignalStrategy,
    AssetType.SME: _EquitySignalStrategy,
    AssetType.FUTURES: _FuturesSignalStrategy,
    AssetType.COMMODITY: _FuturesSignalStrategy,
    AssetType.CURRENCY: _FuturesSignalStrategy,
}


# =============================================================================
# SignalEvaluator — Main Entry Point
# =============================================================================


class SignalEvaluator:
    """Unified signal evaluator that dispatches to asset-class-specific strategies.

    Provides a single ``evaluate()`` method for all supported asset classes.
    Automatically selects the correct signal strategy based on AssetType.

    Usage:
        evaluator = SignalEvaluator(config)
        signal = evaluator.evaluate(
            symbol="RELIANCE",
            asset_type=AssetType.EQUITY,
            df1m=df1m_data,
        )
        if signal and signal.is_actionable(min_score=50):
            dispatcher.route(symbol, signal=signal.to_dict())
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._cfg = config or {}
        self._strategies: dict[AssetType, _BaseSignalStrategy] = {}

    def _get_strategy(self, asset_type: AssetType) -> _BaseSignalStrategy | None:
        """Get or create signal strategy for an asset type."""
        if asset_type not in self._strategies:
            strategy_cls = _DEFAULT_STRATEGY_MAP.get(asset_type)
            if strategy_cls is None:
                return None
            # FuturesSignalStrategy needs the asset_type parameter
            if strategy_cls is _FuturesSignalStrategy:
                self._strategies[asset_type] = strategy_cls(self._cfg, asset_type)
            else:
                self._strategies[asset_type] = strategy_cls(self._cfg)
        return self._strategies[asset_type]

    def evaluate(
        self,
        symbol: str,
        asset_type: AssetType = AssetType.INDEX_OPTIONS,
        df1m: pd.DataFrame | None = None,
        df5m: pd.DataFrame | None = None,
        df15m: pd.DataFrame | None = None,
        **kwargs: Any,
    ) -> SignalResult | None:
        """Evaluate a trading signal for any supported asset class.

        Args:
            symbol: Trading symbol (e.g., "NIFTY", "RELIANCE", "GOLD").
            asset_type: Asset class of the symbol.
            df1m: 1-minute OHLCV DataFrame (required for all asset classes).
            df5m: 5-minute OHLCV DataFrame (required for index options).
            df15m: 15-minute OHLCV DataFrame (required for index options).
            **kwargs: Additional parameters:
                - vix (float): VIX value (index options).
                - iv (float): Implied volatility (index options).
                - pcr (float): Put-Call ratio (index options).
                - smart (str): Smart money sentiment (index options).
                - oi_sup (float): OI support level (index options).
                - oi_res (float): OI resistance level (index options).
                - capital (float): Available capital (index options).
                - is_early_session (bool): Early session flag.

        Returns:
            SignalResult if actionable signal found, None otherwise.
        """
        strategy = self._get_strategy(asset_type)
        if strategy is None:
            _log.debug("[SIGNAL_EVAL] No signal strategy for %s (%s) — asset type not supported yet",
                       symbol, asset_type.value)
            return None

        import time
        result = strategy.evaluate(
            symbol=symbol,
            df1m=df1m,
            df5m=df5m,
            df15m=df15m,
            **kwargs,
        )

        if result is not None:
            result.timestamp = time.time()
            _log.info("[SIGNAL_EVAL] %s [%s] score=%d dir=%s strength=%s",
                      symbol, asset_type.value, result.score, result.direction, result.strength)

        return result

    def evaluate_from_signal_dict(
        self,
        signal: dict[str, Any],
    ) -> SignalResult | None:
        """Evaluate using a pre-built signal dict (for external/webhook signals).

        Creates a SignalResult from an already-evaluated signal dict,
        applying basic validation and standardisation.

        Args:
            signal: Signal dict with keys: direction, score, price, strength, etc.

        Returns:
            SignalResult if valid, None if invalid.
        """
        symbol = str(signal.get("symbol", ""))
        if not symbol:
            return None

        asset_type_val = signal.get("asset_type", AssetType.UNKNOWN.value)
        if isinstance(asset_type_val, str):
            try:
                asset_type = AssetType(asset_type_val)
            except ValueError:
                asset_type = AssetType.UNKNOWN
        else:
            asset_type = asset_type_val

        score = int(signal.get("score", 0))
        direction = str(signal.get("direction", ""))
        if not direction or score <= 0:
            return None

        price = float(signal.get("price", 0.0))
        strength = str(signal.get("strength", "WEAK"))

        return SignalResult(
            symbol=symbol,
            direction=direction,
            score=score,
            strength=strength,
            price=price,
            asset_type=asset_type,
            regime=str(signal.get("regime", "NEUTRAL")),
            score_components=dict(signal.get("score_components", {})),
            features=list(signal.get("features", [])),
            risk=dict(signal.get("risk", {})),
            rsi=float(signal.get("rsi", 50.0)),
            atr=float(signal.get("atr", 0.0)),
            adx=float(signal.get("adx", 0.0)),
            vwap=float(signal.get("vwap", 0.0)),
            vol_ratio=float(signal.get("vol_ratio", 1.0)),
            macd=dict(signal.get("macd", {})),
            reason=str(signal.get("reason", "")),
        )


__all__ = [
    "SignalEvaluator",
    "SignalResult",
    "_IndexOptionsSignalStrategy",
    "_EquitySignalStrategy",
    "_FuturesSignalStrategy",
]
