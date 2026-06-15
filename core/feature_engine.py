from typing import Any

import pandas as pd

from core.market_calc import calc_adx
from core.utils_numeric import safe_float


class FeatureEngine:
    """
    Extracts structured features from raw OHLCV data.
    Separates calculation from decision-making logic.
    """
    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}

    @staticmethod
    def _safe_float(v: Any, default: float = 0.0) -> float:
        return safe_float(v, default)

    @classmethod
    def get_price(cls, df: pd.DataFrame) -> float:
        if df is None or df.empty: return 0.0
        return round(cls._safe_float(df["Close"].iloc[-1]), 2)

    @classmethod
    def get_vwap(cls, df: pd.DataFrame) -> float:
        """
        Session VWAP: volume-weighted typical price for the **last calendar day** in the series.

        If the index is timezone-aware, the day boundary uses **Asia/Kolkata** so the session
        matches NSE IST. Naive indices are treated as already in market-local time.
        """
        if df is None or df.empty:
            return 0.0
        try:
            work = df
            idx = df.index
            if isinstance(idx, pd.DatetimeIndex) and len(idx) > 0:
                try:
                    if idx.tz is not None:
                        idx_for_day = idx.tz_convert("Asia/Kolkata")
                    else:
                        idx_for_day = idx
                except (TypeError, ValueError, IndexError):
                    idx_for_day = idx
                day = idx_for_day[-1].normalize()
                day_mask = idx_for_day.normalize() == day
                sub = df.loc[day_mask]
                if sub is not None and not sub.empty:
                    work = sub
            tp = (work["High"] + work["Low"] + work["Close"]) / 3
            cum_vol = cls._safe_float(work["Volume"].cumsum().iloc[-1])
            if cum_vol <= 0:
                return cls.get_price(df)
            return round(cls._safe_float((tp * work["Volume"]).cumsum().iloc[-1] / cum_vol), 2)
        except (TypeError, ValueError, ZeroDivisionError, IndexError):
            return cls.get_price(df)

    @classmethod
    def get_ema(cls, series: pd.Series, span: int) -> float:
        if series is None or series.empty: return 0.0
        try:
            return round(cls._safe_float(series.ewm(span=span, adjust=False).mean().iloc[-1]), 2)
        except (ValueError, TypeError, IndexError):
            return 0.0

    @classmethod
    def ema_trend(cls, df: pd.DataFrame, fast: int = 5, slow: int = 20) -> str:
        if df is None or df.empty: return "FLAT"
        try:
            ef = cls._safe_float(df["Close"].ewm(span=fast, adjust=False).mean().iloc[-1])
            es = cls._safe_float(df["Close"].ewm(span=slow, adjust=False).mean().iloc[-1])
            if es > 0 and abs(ef - es) / es < 0.0005:
                return "FLAT"
            return "UP" if ef > es else "DOWN"
        except (ValueError, TypeError, IndexError):
            return "FLAT"

    @classmethod
    def get_rsi(cls, df: pd.DataFrame, period: int = 14) -> float:
        if df is None or df.empty: return 50.0
        try:
            delta = df["Close"].diff()
            gain = delta.where(delta > 0, 0.0).ewm(alpha=1/period, adjust=False).mean()
            loss = (-delta.where(delta < 0, 0.0)).ewm(alpha=1/period, adjust=False).mean()
            rs = gain / loss.replace(0, 1e-6)
            rsi = 100 - (100 / (1 + rs))
            val = cls._safe_float(rsi.iloc[-1])
            return round(max(0.0, min(100.0, val)), 2)
        except (ValueError, TypeError, IndexError):
            return 50.0

    @classmethod
    def get_macd(cls, df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9) -> dict[str, float]:
        if df is None or df.empty: return {"macd": 0.0, "signal": 0.0, "histogram": 0.0}
        try:
            close = df["Close"]
            ema_fast = close.ewm(span=fast, adjust=False).mean()
            ema_slow = close.ewm(span=slow, adjust=False).mean()
            macd_line = ema_fast - ema_slow
            signal_line = macd_line.ewm(span=signal, adjust=False).mean()
            histogram = macd_line - signal_line
            return {
                "macd": round(cls._safe_float(macd_line.iloc[-1]), 4),
                "signal": round(cls._safe_float(signal_line.iloc[-1]), 4),
                "histogram": round(cls._safe_float(histogram.iloc[-1]), 4)
            }
        except (ValueError, TypeError, IndexError):
            return {"macd": 0.0, "signal": 0.0, "histogram": 0.0}

    @classmethod
    def get_atr(cls, df: pd.DataFrame, period: int = 14) -> float:
        if df is None or df.empty: return 0.0
        try:
            high = df["High"]
            low = df["Low"]
            close = df["Close"].shift(1)
            tr = pd.concat([high - low, (high - close).abs(), (low - close).abs()], axis=1).max(axis=1)
            val = cls._safe_float(tr.rolling(period).mean().iloc[-1])
            if val <= 0:
                val = cls._safe_float((df["High"] - df["Low"]).mean())
            return round(val, 2)
        except (ValueError, TypeError, IndexError):
            return 0.0

    @classmethod
    def get_vol_ratio(cls, df: pd.DataFrame, period: int = 20) -> float:
        if df is None or df.empty: return 1.0
        try:
            current = cls._safe_float(df["Volume"].iloc[-1])
            avg = cls._safe_float(df["Volume"].rolling(min(period, len(df))).mean().iloc[-1])
            if avg <= 0 or current <= 0: return 1.0
            return round(current / avg, 2)
        except (ValueError, TypeError, ZeroDivisionError):
            return 1.0

    @classmethod
    def price_delta(cls, df: pd.DataFrame, n: int) -> float:
        if df is None or len(df) < n: return 0.0
        try:
            return round(cls._safe_float(df["Close"].iloc[-1]) - cls._safe_float(df["Close"].iloc[-n]), 4)
        except (ValueError, TypeError, IndexError):
            return 0.0

    @classmethod
    def get_adx(cls, df: pd.DataFrame, period: int = 14) -> float:
        """ADX aligned with :func:`core.market_calc.calc_adx` (regime vs scoring consistency)."""
        if df is None or df.empty or len(df) < period + 1:
            return 20.0
        try:
            val = float(calc_adx(df, period=period))
            if val <= 0.0:
                return 20.0
            return round(max(0.0, min(100.0, val)), 2)
        except (ValueError, TypeError, IndexError):
            return 20.0

    def extract_features(self, df1m: pd.DataFrame, df5m: pd.DataFrame, df15m: pd.DataFrame, oi_data: dict | None = None) -> dict[str, Any]:
        """Returns a structured dictionary of all computed features."""
        if df1m is None or df5m is None or df15m is None:
            return {}

        ind_cfg = self.config.get("indicators", {})
        ema_fast = ind_cfg.get("ema_fast", 5)
        ema_slow = ind_cfg.get("ema_slow", 20)
        macd_fast = ind_cfg.get("macd_fast", 12)
        macd_slow = ind_cfg.get("macd_slow", 26)
        macd_signal = ind_cfg.get("macd_signal", 9)
        rsi_period = ind_cfg.get("rsi_period", 14)
        atr_period = ind_cfg.get("atr_period", 14)
        adx_period = ind_cfg.get("adx_period", 14)
        vol_ratio_period = ind_cfg.get("vol_ratio_period", 20)

        price = self.get_price(df1m)
        vwap = self.get_vwap(df1m)
        trend_5m = self.ema_trend(df5m, fast=ema_fast, slow=ema_slow)
        trend_15m = self.ema_trend(df15m, fast=ema_fast, slow=ema_slow)
        macd_data = self.get_macd(df5m, fast=macd_fast, slow=macd_slow, signal=macd_signal)

        # Determine breakout status safely
        try:
            prev_close = self._safe_float(df1m["Close"].iloc[-2]) if len(df1m) >= 2 else 0.0
            breakout_ok = abs(price - prev_close) / prev_close > 0.001 if prev_close > 0 else False
        except (ValueError, TypeError, IndexError):
            breakout_ok = False

        oi = oi_data or {}

        # Determine regime based on ADX (15m is best for intraday regime)
        adx_15m = self.get_adx(df15m, adx_period)
        regime = "TRENDING" if adx_15m > 25 else ("CHOPPY" if adx_15m < 20 else "NEUTRAL")

        features = {
            "price": price,
            "vwap": vwap,
            "vwap_position": "above" if price > vwap else ("below" if price < vwap else "on"),
            "trend_5m": trend_5m,
            "trend_15m": trend_15m,
            "timeframe_aligned": trend_5m == trend_15m and trend_5m != "FLAT",
            "rsi": self.get_rsi(df5m, rsi_period),
            "macd": macd_data,
            "macd_cross": macd_data["histogram"] > 0, # Positive histogram means macd > signal
            "atr": self.get_atr(df5m, atr_period),
            "adx": adx_15m,
            "regime": regime,
            "vol_ratio": self.get_vol_ratio(df1m, vol_ratio_period),
            "volume_spike": self.get_vol_ratio(df1m, vol_ratio_period) >= 1.2,
            "delta_10m": self.price_delta(df1m, 10),
            "delta_15m": self.price_delta(df5m, 3),
            "breakout_ok": breakout_ok,
            "pcr": oi.get("pcr", 1.0),
            "smart_money": oi.get("smart", "NEUTRAL")
        }
        return features
