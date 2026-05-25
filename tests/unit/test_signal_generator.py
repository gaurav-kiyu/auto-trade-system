"""
Unit tests for the SignalService domain service.
"""

from datetime import datetime

import pytest
from core.domains.signal_engine.model import Candle, MarketData, SignalQuality, TradingSignal
from core.domains.signal_engine.service import create_signal_service


class TestSignalService:
    """Test cases for the SignalService domain service."""

    def setup_method(self):
        """Set up test fixtures before each test method."""
        self.config = {
            'lookback_periods': 100,
            'min_data_points': 50,
            'signal_weights': {
                'technical': 0.4,
                'ml': 0.3,
                'order_flow': 0.2,
                'sentiment': 0.1
            }
        }
        self.signal_service = create_signal_service(self.config)
        self.sample_symbol = "NIFTY"

        # Create sample market data for testing
        self.sample_market_data = self._create_sample_market_data()

    def _create_sample_market_data(self) -> MarketData:
        """Create sample market data for testing."""
        candles = []
        base_price = 20000.0

        for i in range(100):  # Create 100 candles
            # Add some random walk behavior
            change = (i % 10 - 5) * 10  # Oscillating pattern
            price = base_price + change + (i * 0.1)  # Slight upward trend

            candle = Candle(
                timestamp=datetime.now(),
                open=price,
                high=price + 10,
                low=price - 10,
                close=price + 5,
                volume=1000 + (i % 5) * 100
            )
            candles.append(candle)

        return MarketData(
            symbol=self.sample_symbol,
            candles=candles,
            timestamp=datetime.now()
        )

    def test_signal_service_initialization(self):
        """Test that the signal generator initializes correctly."""
        assert self.signal_service is not None
        assert self.signal_service.lookback_periods == 100
        assert self.signal_service.min_data_points == 50
        assert self.signal_service.signal_weights['technical'] == 0.4

    def test_sufficient_data_check(self):
        """Test the sufficient data check."""
        # Test with sufficient data
        assert self.signal_service._sufficient_data(self.sample_market_data) is True

        # Test with insufficient data
        insufficient_data = MarketData(
            symbol=self.sample_symbol,
            candles=self.sample_market_data.candles[:30],  # Only 30 candles
            timestamp=datetime.now()
        )
        assert self.signal_service._sufficient_data(insufficient_data) is False

        # Test with no data
        no_data = MarketData(
            symbol=self.sample_symbol,
            candles=[],
            timestamp=datetime.now()
        )
        assert self.signal_service._sufficient_data(no_data) is False

    def test_create_weak_signal(self):
        """Test creation of weak signals."""
        weak_signal = self.signal_service._create_weak_signal(
            self.sample_symbol, "Test reason"
        )

        assert isinstance(weak_signal, TradingSignal)
        assert weak_signal.symbol == self.sample_symbol
        assert weak_signal.strength == 0.1
        assert weak_signal.direction == "NEUTRAL"
        assert weak_signal.quality == SignalQuality.WEAK
        assert weak_signal.metadata['reason'] == "Test reason"

    def test_sma_calculation(self):
        """Test SMA calculation."""
        # Create simple test data
        prices = [10, 20, 30, 40, 50]
        candles = []
        for price in prices:
            candle = Candle(
                timestamp=datetime.now(),
                open=price,
                high=price+1,
                low=price-1,
                close=price,
                volume=100
            )
            candles.append(candle)

        sma_3 = self.signal_service._calculate_sma(candles, 3)
        # Should be average of last 3: (30+40+50)/3 = 40
        assert sma_3 == 40.0

        # Test with insufficient data
        sma_10 = self.signal_service._calculate_sma(candles, 10)
        assert sma_10 is None

    def test_ema_calculation(self):
        """Test EMA calculation."""
        # Create simple test data
        prices = [10, 20, 30, 40, 50]
        candles = []
        for price in prices:
            candle = Candle(
                timestamp=datetime.now(),
                open=price,
                high=price+1,
                low=price-1,
                close=price,
                volume=100
            )
            candles.append(candle)

        ema_3 = self.signal_service._calculate_ema(candles, 3)
        assert ema_3 is not None
        assert isinstance(ema_3, float)
        # EMA should be somewhere between the values
        assert 10 <= ema_3 <= 50

    def test_rsi_calculation(self):
        """Test RSI calculation."""
        # Create trending upward data
        prices = [10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24]  # Consistently up
        candles = []
        for price in prices:
            candle = Candle(
                timestamp=datetime.now(),
                open=price,
                high=price+1,
                low=price-1,
                close=price,
                volume=100
            )
            candles.append(candle)

        rsi = self.signal_service._calculate_rsi(candles, 14)
        # With all gains and no losses, RSI should be 100
        assert rsi == 100.0

        # Create trending downward data
        prices = [24, 23, 22, 21, 20, 19, 18, 17, 16, 15, 14, 13, 12, 11, 10]  # Consistently down
        candles = []
        for price in prices:
            candle = Candle(
                timestamp=datetime.now(),
                open=price,
                high=price+1,
                low=price-1,
                close=price,
                volume=100
            )
            candles.append(candle)

        rsi = self.signal_service._calculate_rsi(candles, 14)
        # With all losses and no gains, RSI should be 0
        assert rsi == 0.0

    def test_generate_signal_with_sufficient_data(self):
        """Test signal generation with sufficient market data."""
        signal = self.signal_service.generate_signal(
            self.sample_market_data, self.sample_symbol
        )

        assert isinstance(signal, TradingSignal)
        assert signal.symbol == self.sample_symbol
        assert isinstance(signal.strength, float)
        assert 0.0 <= signal.strength <= 1.0
        assert signal.direction in ["BUY", "SELL", "NEUTRAL"]
        assert signal.quality in [SignalQuality.STRONG, SignalQuality.MODERATE, SignalQuality.WEAK]
        assert isinstance(signal.timestamp, datetime)

    def test_generate_signal_with_insufficient_data(self):
        """Test signal generation with insufficient market data."""
        insufficient_data = MarketData(
            symbol=self.sample_symbol,
            candles=[],  # No data
            timestamp=datetime.now()
        )

        signal = self.signal_service.generate_signal(
            insufficient_data, self.sample_symbol
        )

        # Should return a weak signal
        assert signal.quality == SignalQuality.WEAK
        assert signal.strength == 0.1
        assert "Insufficient data" in signal.metadata.get('reason', '')

    def test_signal_quality_scoring(self):
        """Test signal quality scoring."""
        # Create a strong signal
        strong_signal = TradingSignal(
            symbol=self.sample_symbol,
            strength=0.9,
            direction="BUY",
            quality=SignalQuality.MODERATE,  # Will be overridden
            timestamp=datetime.now()
        )

        # Test that quality scoring works
        quality_score = self.signal_service._validate_signal_quality(strong_signal)
        assert 0.0 <= quality_score <= 1.0

        # Test with weak signal
        weak_signal = TradingSignal(
            symbol=self.sample_symbol,
            strength=0.1,
            direction="BUY",
            quality=SignalQuality.MODERATE,  # Will be overridden
            timestamp=datetime.now()
        )

        quality_score = self.signal_service._validate_signal_quality(weak_signal)
        assert 0.0 <= quality_score <= 1.0
        # Weak signal should get lower quality score

    def test_signal_quality_to_enum_conversion(self):
        """Test conversion from quality score to SignalQuality enum."""
        assert self.signal_service._score_to_quality(0.9) == SignalQuality.STRONG
        assert self.signal_service._score_to_quality(0.7) == SignalQuality.MODERATE
        assert self.signal_service._score_to_quality(0.3) == SignalQuality.WEAK
        assert self.signal_service._score_to_quality(0.0) == SignalQuality.WEAK

    def test_combine_signals(self):
        """Test signal combination functionality."""
        signals = [
            ('tech', 0.8, 0.4),
            ('ml', -0.5, 0.3),
            ('flow', 0.3, 0.2),
            ('sent', 0.1, 0.1)
        ]

        combined = self.signal_service._combine_signals(signals)
        # Expected: (0.8*0.4 + -0.5*0.3 + 0.3*0.2 + 0.1*0.1) / (0.4+0.3+0.2+0.1)
        # Expected: (0.32 - 0.15 + 0.06 + 0.01) / 1.0 = 0.24
        assert abs(combined - 0.24) < 0.001

    def test_create_signal_services_from_config(self):
        """Test factory function."""
        # Test with full config
        generator = create_signal_service(self.config)
        assert generator.lookback_periods == 100
        assert generator.min_data_points == 50

        # Test with partial config (should use defaults)
        partial_config = {
            'lookback_periods': 50
        }
        generator = create_signal_service(partial_config)
        assert generator.lookback_periods == 50
        assert generator.min_data_points == 50  # Default
        assert generator.signal_weights['technical'] == 0.4  # Default

if __name__ == "__main__":
    pytest.main([__file__])
