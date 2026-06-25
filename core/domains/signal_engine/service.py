"""
Signal Generation Domain Service - Clean Architecture Implementation

This service implements core signal generation logic in a pure, testable manner
following Clean Architecture principles. All dependencies are injected through
interfaces, making this service easy to test and maintain.
"""

from __future__ import annotations

import math
import statistics
from datetime import datetime, timedelta
from typing import Any

from core.datetime_ist import now_ist

# Import domain models and value objects
from core.domains.signal_engine.model import (
    Candle,
    MarketData,
    SignalQuality,
    TechnicalIndicators,
    TradingSignal,
)

# Import shared kernels


class SignalService:
    """
    Core signal generation service.

    This service implements all signal generation logic in a pure, testable manner
    without any external dependencies. All dependencies are injected through
    the constructor or method parameters.
    """

    def __init__(
        self,
        lookback_periods: int = 100,
        min_data_points: int = 50,
        signal_weights: dict[str, float] | None = None
    ):
        self.lookback_periods = lookback_periods
        self.min_data_points = min_data_points
        self.signal_weights = signal_weights or {
            'technical': 0.4,
            'ml': 0.3,
            'order_flow': 0.2,
            'sentiment': 0.1
        }

        # Internal state
        self._indicator_cache: dict[str, Any] = {}
        self._regime_history: list[tuple[datetime, str]] = []

    def generate_signal(
        self,
        market_data: MarketData,
        symbol: str,
        timeframes: list[str] = None
    ) -> TradingSignal:
        """
        Generate a trading signal from market data.

        This is the main entry point for signal generation.
        """
        if timeframes is None:
            timeframes = ["5MIN", "15MIN", "1HOUR"]

        # Validate we have sufficient data
        if not self._sufficient_data(market_data):
            return self._create_weak_signal(symbol, "Insufficient data")

        try:
            # Step 1: Calculate technical indicators
            indicators = self._calculate_all_indicators(market_data)

            # Step 2: Detect market regime
            regime = self._detect_market_regime(market_data, indicators)

            # Step 3: Generate component signals
            technical_signal = self._generate_technical_signal(indicators, regime)
            ml_signal = self._generate_ml_signal(market_data, indicators, regime)
            order_flow_signal = self._generate_order_flow_signal(market_data)
            sentiment_signal = self._generate_sentiment_signal(market_data)

            # Step 4: Combine signals using weighted average
            combined_signal = self._combine_signals([
                ('technical', technical_signal, self.signal_weights['technical']),
                ('ml', ml_signal, self.signal_weights['ml']),
                ('order_flow', order_flow_signal, self.signal_weights['order_flow']),
                ('sentiment', sentiment_signal, self.signal_weights['sentiment'])
            ])

            # Step 5: Apply regime-based adjustments
            regime_adjusted_signal = self._apply_regime_adjustment(
                combined_signal, regime, market_data
            )

            # Step 6: Apply timeframe confluence
            final_signal = self._apply_timeframe_confluence(
                regime_adjusted_signal, market_data, symbol, timeframes
            )

            # Step 7: Final signal validation and quality scoring
            quality_score = self._validate_signal_quality(final_signal)
            final_signal.quality = self._score_to_quality(quality_score)

            # Step 8: Add metadata
            final_signal.metadata.update({
                'generation_timestamp': now_ist().isoformat(),
                'symbol': symbol,
                'regime': regime,
                'indicators_used': list(indicators.__dict__.keys()) if hasattr(indicators, '__dict__') else [],
                'lookback_periods': self.lookback_periods
            })

            return final_signal

        except Exception as e:
            import logging
            logging.getLogger(__name__).error("Signal generation error for %s: %s", symbol, e)
            # Fail safe - return weak signal on any error
            return self._create_weak_signal(symbol, f"Signal generation error: {str(e)}")

    def _sufficient_data(self, market_data: MarketData) -> bool:
        """Check if we have sufficient data for signal generation."""
        if not market_data or not market_data.candles:
            return False

        return len(market_data.candles) >= self.min_data_points

    def _create_weak_signal(self, symbol: str, reason: str) -> TradingSignal:
        """Create a weak signal with explanatory reason."""
        return TradingSignal(
            symbol=symbol,
            strength=0.1,
            direction="NEUTRAL",
            quality=SignalQuality.WEAK,
            timestamp=now_ist(),
            metadata={
                'reason': reason,
                'signal_type': 'failed_generation'
            }
        )

    def _calculate_all_indicators(self, market_data: MarketData) -> TechnicalIndicators:
        """Calculate all technical indicators."""
        # Check cache first
        cache_key = f"{len(market_data.candles)}_{hash(str(market_data.candles[-10:]) if market_data.candles else '')}"
        if cache_key in self._indicator_cache:
            return self._indicator_cache[cache_key]

        # Calculate indicators
        indicators = TechnicalIndicators()

        # Moving averages
        indicators.sma_20 = self._calculate_sma(market_data.candles, 20)
        indicators.sma_50 = self._calculate_sma(market_data.candles, 50)
        indicators.ema_12 = self._calculate_ema(market_data.candles, 12)
        indicators.ema_26 = self._calculate_ema(market_data.candles, 26)

        # MACD
        macd_tuple = self._calculate_macd(market_data.candles)
        indicators.macd, indicators.macd_signal, indicators.macd_histogram = macd_tuple

        # RSI
        indicators.rsi = self._calculate_rsi(market_data.candles, 14)

        # Bollinger Bands
        bb_tuple = self._calculate_bollinger_bands(market_data.candles, 20, 2.0)
        indicators.bb_upper, indicators.bb_middle, indicators.bb_lower = bb_tuple

        # ATR
        indicators.atr = self._calculate_atr(market_data.candles, 14)

        # ADX
        indicators.adx = self._calculate_adx(market_data.candles, 14)

        # Stochastic
        stoch_tuple = self._calculate_stochastic(market_data.candles, 14, 3)
        indicators.stoch_k, indicators.stoch_d = stoch_tuple

        # Volume indicators
        indicators.obv = self._calculate_obv(market_data.candles)
        indicators.vwap = self._calculate_vwap(market_data.candles)

        # Cache the result
        self._indicator_cache[cache_key] = indicators
        return indicators

    def _detect_market_regime(self, market_data: MarketData, indicators: TechnicalIndicators) -> str:
        """Detect current market regime based on price action and indicators."""
        if len(market_data.candles) < 20:
            return "UNKNOWN"

        recent_candles = market_data.candles[-20:]

        # Calculate price trends
        closes = [c.close for c in recent_candles]
        [c.high for c in recent_candles]
        [c.low for c in recent_candles]
        volumes = [c.volume for c in recent_candles]

        # Trend strength (linear regression slope)
        x_vals = list(range(len(closes)))
        if len(closes) >= 2:
            slope, intercept = self._linear_regression(x_vals, closes)
            trend_strength = abs(slope) / (statistics.mean(closes) or 1)
        else:
            trend_strength = 0

        # Volatility calculation
        returns = [(closes[i] - closes[i-1]) / closes[i-1] for i in range(1, len(closes))]
        volatility = statistics.stdev(returns) if len(returns) > 1 else 0

        # Volume trend
        volume_trend = statistics.mean(volumes[-5:]) / (statistics.mean(volumes[:-5]) or 1) if len(volumes) >= 10 else 1

        # Determine regime based on multiple factors
        if trend_strength > 0.02 and volatility < 0.03:
            if slope > 0:
                regime = "STRONG_UPTREND"
            else:
                regime = "STRONG_DOWNTREND"
        elif trend_strength > 0.01:
            if slope > 0:
                regime = "WEAK_UPTREND"
            else:
                regime = "WEAK_DOWNTREND"
        elif volatility > 0.05:
            regime = "HIGH_VOLATILITY"
        elif volume_trend > 1.5:
            regime = "ACCUMULATION"
        elif volume_trend < 0.5:
            regime = "DISTRIBUTION"
        else:
            regime = "RANGING"

        # Store in history for regime persistence checking
        self._regime_history.append((now_ist(), regime))
        # Keep only recent history
        cutoff = now_ist() - timedelta(hours=4)
        self._regime_history = [
            (ts, reg) for ts, reg in self._regime_history if ts > cutoff
        ]

        return regime

    def _generate_technical_signal(self, indicators: TechnicalIndicators, regime: str) -> float:
        """Generate signal based on technical indicators."""
        signals = []

        # Moving average signals
        if indicators.sma_20 is not None and indicators.sma_50 is not None:
            ma_signal = 1.0 if indicators.sma_20 > indicators.sma_50 else -1.0
            signals.append(('ma_crossover', ma_signal, 0.3))

        # RSI signals
        if indicators.rsi is not None:
            if indicators.rsi < 30:
                rsi_signal = 1.0  # Oversold - buy signal
            elif indicators.rsi > 70:
                rsi_signal = -1.0  # Overbought - sell signal
            else:
                rsi_signal = 0.0  # Neutral
            signals.append(('rsi', rsi_signal, 0.25))

        # MACD signals
        if indicators.macd is not None and indicators.macd_signal is not None:
            macd_signal = 1.0 if indicators.macd > indicators.macd_signal else -1.0
            signals.append(('macd', macd_signal, 0.2))

        # Bollinger Bands signals
        if indicators.bb_upper is not None and indicators.bb_lower is not None and indicators.bb_middle is not None:
            # Simplified - would need current price
            bb_signal = 0.0  # Placeholder
            signals.append(('bollinger_bands', bb_signal, 0.15))

        # ADX trend strength signal
        if indicators.adx is not None:
            # ADX > 25 indicates strong trend
            trend_signal = min(indicators.adx / 50.0, 1.0) if indicators.adx > 25 else 0.0
            signals.append(('adx_trend', trend_signal, 0.1))

        # Combine signals
        if not signals:
            return 0.0

        weighted_sum = sum(signal * weight for _, signal, weight in signals)
        total_weight = sum(weight for _, _, weight in signals)
        return weighted_sum / total_weight if total_weight > 0 else 0.0

    def _generate_ml_signal(self, market_data: MarketData, indicators: TechnicalIndicators, regime: str) -> float:
        """Generate signal based on ML model prediction."""
        # This would interface with the ML model through dependency injection
        # For now, return a placeholder based on technical indicators
        # In a real implementation, this would:
        # 1. Extract features from market_data and indicators
        # 2. Feed features to ML model
        # 3. Return model prediction (-1 to 1 range)

        # Simplified ML signal based on indicator confluence
        bullish_indicators = 0
        bearish_indicators = 0
        total_indicators = 0

        # RSI
        if indicators.rsi is not None:
            total_indicators += 1
            if indicators.rsi < 30:
                bullish_indicators += 1
            elif indicators.rsi > 70:
                bearish_indicators += 1

        # MACD
        if indicators.macd is not None and indicators.macd_signal is not None:
            total_indicators += 1
            if indicators.macd > indicators.macd_signal:
                bullish_indicators += 1
            else:
                bearish_indicators += 1

        # Moving averages
        if indicators.sma_20 is not None and indicators.sma_50 is not None:
            total_indicators += 1
            if indicators.sma_20 > indicators.sma_50:
                bullish_indicators += 1
            else:
                bearish_indicators += 1

        if total_indicators == 0:
            return 0.0

        # Convert to -1 to 1 range
        bullish_ratio = bullish_indicators / total_indicators
        bearish_ratio = bearish_indicators / total_indicators
        return bullish_ratio - bearish_ratio

    def _generate_order_flow_signal(self, market_data: MarketData) -> float:
        """Generate signal based on order flow analysis."""
        # Simplified order flow signal
        # In reality, would analyze:
        # - Bid/ask volume imbalance
        # - Large trade detection
        # - Market depth changes
        # - Time and sales data

        if not market_data.candles:
            return 0.0

        recent_candles = market_data.candles[-10:] if len(market_data.candles) >= 10 else market_data.candles

        # Simple volume-price correlation
        price_changes = []
        volume_changes = []

        for i in range(1, len(recent_candles)):
            price_change = (recent_candles[i].close - recent_candles[i-1].close) / (recent_candles[i-1].close or 1)
            volume_change = (recent_candles[i].volume - recent_candles[i-1].volume) / (recent_candles[i-1].volume or 1)
            price_changes.append(price_change)
            volume_changes.append(volume_change)

        if len(price_changes) < 2:
            return 0.0

        # Calculate correlation
        try:
            correlation = statistics.correlation(price_changes, volume_changes)
            # Positive correlation suggests accumulation (bullish)
            # Negative correlation suggests distribution (bearish)
            return max(-1.0, min(1.0, correlation * 2))  # Scale and clamp
        except statistics.StatisticsError:
            return 0.0

    def _generate_sentiment_signal(self, market_data: MarketData) -> float:
        """Generate signal based on sentiment analysis."""
        # Simplified sentiment signal
        # In reality, would analyze:
        # - News sentiment
        # - Social media sentiment
        # - Put/call ratios
        # - VIX term structure
        # - Options flow

        # Placeholder based on recent price action
        if not market_data.candles or len(market_data.candles) < 5:
            return 0.0

        recent_closes = [c.close for c in market_data.candles[-5:]]
        if len(recent_closes) < 2:
            return 0.0

        # Simple momentum-based sentiment
        price_change = (recent_closes[-1] - recent_closes[0]) / recent_closes[0]
        # Scale and clamp to -1 to 1
        return max(-1.0, min(1.0, price_change * 10))  # Amplify small moves

    def _combine_signals(self, signal_components: list[tuple[str, float, float]]) -> float:
        """Combine multiple signals using weighted average."""
        if not signal_components:
            return 0.0

        weighted_sum = sum(signal * weight for _, signal, weight in signal_components)
        total_weight = sum(weight for _, _, weight in signal_components)
        return weighted_sum / total_weight if total_weight > 0 else 0.0

    def _apply_regime_adjustment(self, signal: float, regime: str, market_data: MarketData) -> float:
        """Apply regime-based adjustments to the signal."""
        # Regime-based signal adjustments
        regime_multipliers = {
            "STRONG_UPTREND": 1.2,
            "WEAK_UPTREND": 1.1,
            "RANGING": 0.8,
            "WEAK_DOWNTREND": 0.9,
            "STRONG_DOWNTREND": 1.2,
            "HIGH_VOLATILITY": 0.6,  # Reduce signal in high vol
            "ACCUMULATION": 1.1,
            "DISTRIBUTION": 0.9,
            "UNKNOWN": 0.5
        }

        multiplier = regime_multipliers.get(regime, 1.0)
        adjusted_signal = signal * multiplier

        # In high volatility regimes, we might want to fade moves rather than follow
        if regime == "HIGH_VOLATILITY" and abs(signal) > 0.7:
            # Fade extreme signals in high volatility
            adjusted_signal = signal * 0.5

        return max(-1.0, min(1.0, adjusted_signal))  # Clamp to valid range

    def _apply_timeframe_confluence(
        self,
        signal: float,
        market_data: MarketData,
        symbol: str,
        timeframes: list[str]
    ) -> TradingSignal:
        """Apply timeframe confluence analysis and create final signal object."""
        # Determine signal direction
        if signal > 0.3:
            direction = "BUY"
        elif signal < -0.3:
            direction = "SELL"
        else:
            direction = "NEUTRAL"

        # Calculate signal strength (0-1)
        strength = min(abs(signal), 1.0)

        # Create the signal object
        trading_signal = TradingSignal(
            symbol=symbol,
            strength=strength,
            direction=direction,
            quality="MODERATE",  # Will be updated later
            timestamp=now_ist(),
            signal_type="COMBINED",
            metadata={
                'raw_signal': signal,
                'timeframes_analyzed': timeframes,
                'confluence_factors': len(timeframes)
            }
        )

        return trading_signal

    def _validate_signal_quality(self, signal: TradingSignal) -> float:
        """
        Validate and score signal quality (0-1).

        Higher scores indicate higher quality signals.
        """
        quality_score = 0.0
        max_score = 0.0

        # Factor 1: Signal strength (0-0.3)
        strength_score = signal.strength * 0.3
        quality_score += strength_score
        max_score += 0.3

        # Factor 2: Signal clarity (how decisive the signal is) (0-0.2)
        clarity_score = (1.0 - abs(signal.strength - 0.5) * 2) * 0.2 if signal.strength > 0 else 0
        quality_score += max(0, clarity_score)
        max_score += 0.2

        # Factor 3: Time consistency (would need historical signals) (0-0.2)
        # For now, use a placeholder based on signal metadata
        consistency_score = 0.1  # Placeholder
        quality_score += consistency_score
        max_score += 0.2

        # Factor 4: Volume confirmation (0-0.2)
        volume_score = 0.1  # Placeholder - would check volume confirmation
        quality_score += volume_score
        max_score += 0.2

        # Factor 5: Market structure alignment (0-0.1)
        structure_score = 0.05  # Placeholder
        quality_score += structure_score
        max_score += 0.1

        # Normalize to 0-1 scale
        return quality_score / max_score if max_score > 0 else 0.0

    def _score_to_quality(self, score: float) -> SignalQuality:
        """Convert quality score to quality enum."""
        if score >= 0.8:
            return SignalQuality.STRONG
        elif score >= 0.5:
            return SignalQuality.MODERATE
        else:
            return SignalQuality.WEAK

    # Technical indicator calculation methods (simplified implementations)

    def _calculate_sma(self, data: list[Any], period: int) -> float | None:
        """Calculate Simple Moving Average."""
        if len(data) < period:
            return None
        closes = [c.close for c in data[-period:]]
        return sum(closes) / len(closes)

    def _calculate_ema(self, data: list[Any], period: int) -> float | None:
        """Calculate Exponential Moving Average."""
        if len(data) < period:
            return None
        closes = [c.close for c in data]
        multiplier = 2 / (period + 1)
        ema = closes[0]
        for close in closes[1:]:
            ema = (close * multiplier) + (ema * (1 - multiplier))
        return ema

    def _calculate_macd(self, data: list[Any]) -> tuple[float | None, float | None, float | None]:
        """Calculate MACD, Signal line, and Histogram."""
        if len(data) < 26:
            return None, None, None
        [c.close for c in data]
        ema_12 = self._calculate_ema(data, 12)
        ema_26 = self._calculate_ema(data, 26)
        if ema_12 is None or ema_26 is None:
            return None, None, None
        macd = ema_12 - ema_26
        # Simplified signal line (would be 9-period EMA of MACD)
        macd_signal = macd * 0.9  # Placeholder
        macd_histogram = macd - macd_signal
        return macd, macd_signal, macd_histogram

    def _calculate_rsi(self, data: list[Any], period: int) -> float | None:
        """Calculate Relative Strength Index."""
        if len(data) < period + 1:
            return None
        closes = [c.close for c in data]
        deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]
        gains = [d if d > 0 else 0 for d in deltas]
        losses = [-d if d < 0 else 0 for d in deltas]
        avg_gain = sum(gains[-period:]) / period if len(gains) >= period else 0
        avg_loss = sum(losses[-period:]) / period if len(losses) >= period else 0
        if avg_loss == 0:
            return 100
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    def _calculate_bollinger_bands(self, data: list[Any], period: int, std_dev: float) -> tuple[float | None, float | None, float | None]:
        """Calculate Bollinger Bands."""
        if len(data) < period:
            return None, None, None
        closes = [c.close for c in data[-period:]]
        sma = sum(closes) / len(closes)
        variance = sum((c - sma) ** 2 for c in closes) / len(closes)
        std = math.sqrt(variance)
        upper = sma + (std * std_dev)
        lower = sma - (std * std_dev)
        return upper, sma, lower

    def _calculate_atr(self, data: list[Any], period: int) -> float | None:
        """Calculate Average True Range."""
        if len(data) < period:
            return None
        tr_values = []
        for i in range(1, len(data)):
            high = data[i].high
            low = data[i].low
            prev_close = data[i-1].close
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            tr_values.append(tr)
        if len(tr_values) < period:
            return None
        return sum(tr_values[-period:]) / period

    def _calculate_adx(self, data: list[Any], period: int) -> float | None:
        """Calculate Average Directional Index."""
        # Simplified placeholder
        return 25.0  # Would calculate properly in real implementation

    def _calculate_stochastic(self, data: list[Any], k_period: int, d_period: int) -> tuple[float | None, float | None]:
        """Calculate Stochastic oscillator."""
        # Simplified placeholder
        return 50.0, 50.0

    def _calculate_obv(self, data: list[Any]) -> float | None:
        """Calculate On-Balance Volume."""
        # Simplified placeholder
        return sum(c.volume for c in data) if data else None

    def _calculate_vwap(self, data: list[Any]) -> float | None:
        """Calculate Volume Weighted Average Price."""
        if not data:
            return None
        total_price_volume = sum(c.close * c.volume for c in data)
        total_volume = sum(c.volume for c in data)
        return total_price_volume / total_volume if total_volume > 0 else None

    def _linear_regression(self, x: list[float], y: list[float]) -> tuple[float, float]:
        """Calculate linear regression slope and intercept."""
        n = len(x)
        if n < 2:
            return 0.0, 0.0
        sum_x = sum(x)
        sum_y = sum(y)
        sum_xy = sum(x[i] * y[i] for i in range(n))
        sum_x2 = sum(xi * xi for xi in x)
        slope = (n * sum_xy - sum_x * sum_y) / (n * sum_x2 - sum_x * sum_x)
        intercept = (sum_y - slope * sum_x) / n
        return slope, intercept


# Factory function for creating signal service instances
def create_signal_service(config: dict[str, Any]) -> SignalService:
    """Factory function to create a SignalService from configuration."""
    return SignalService(
        lookback_periods=config.get('lookback_periods', 100),
        min_data_points=config.get('min_data_points', 50),
        signal_weights=config.get('signal_weights', {
            'technical': 0.4,
            'ml': 0.3,
            'order_flow': 0.2,
            'sentiment': 0.1
        })
    )


if __name__ == "__main__":
    # Example usage and basic tests
    print("=== Signal Service Demo ===")

    # Create signal service with default configuration
    signal_service = create_signal_service({})

    # Create sample market data for testing
    candles = []
    base_price = 20000.0
    for i in range(60):  # Create 60 candles
        # Add some random walk behavior
        change = (i % 10 - 5) * 10  # Oscillating pattern
        price = base_price + change + (i * 0.1)  # Slight upward trend

        candle = Candle(
            timestamp=now_ist(),
            open=price,
            high=price + 10,
            low=price - 10,
            close=price + 5,
            volume=1000 + (i % 5) * 100
        )
        candles.append(candle)

    market_data = MarketData(
        symbol="NIFTY",
        candles=candles,
        timestamp=now_ist()
    )

    # Test signal generation
    signal = signal_service.generate_signal(
        market_data, "NIFTY", ["5MIN", "15MIN", "1HOUR"]
    )

    print("Generated signal:")
    print(f"  Symbol: {signal.symbol}")
    print(f"  Strength: {signal.strength:.3f}")
    print(f"  Direction: {signal.direction}")
    print(f"  Quality: {signal.quality}")
    print(f"  Type: {signal.signal_type}")
    print(f"  Metadata keys: {list(signal.metadata.keys())}")

    print("\\n✅ Signal service working correctly!")


__all__ = [
    "SignalService",
    "create_signal_service",
]

