"""Sector Rotation & Smart Money Inflow Radar (v3.0).

Tracks all 12 major NSE Sectors against Nifty 50 benchmark.
Ranks sectors into 4 Relative Strength (RS) Quadrants:
- LEADING (Green): High RS-Ratio & Rising RS-Momentum (Strong Institutional Outperformance)
- IMPROVING (Blue): Recovering RS-Momentum (Early Reversal Accumulation)
- WEAKENING (Yellow): Slowing RS-Momentum (Distribution Phase)
- LAGGING (Red): Low RS-Ratio & Falling RS-Momentum (Underperformance)
"""

from __future__ import annotations

from typing import Any

NSE_SECTOR_MAP = {
    "NIFTY BANK": ["HDFCBANK", "ICICIBANK", "SBIN", "KOTAKBANK", "AXISBANK", "INDUSINDBK", "BANKBARODA", "PNB"],
    "NIFTY IT": ["TCS", "INFY", "WIPRO", "HCLTECH", "TECHM", "LTIM", "PERSISTENT", "COFORGE"],
    "NIFTY AUTO": ["TATAMOTORS", "M&M", "MARUTI", "BAJAJ-AUTO", "EICHERMOT", "HEROMOTOCO", "TVSMOTOR"],
    "NIFTY METAL": ["TATASTEEL", "JSWSTEEL", "HINDALCO", "VEDL", "COALINDIA", "NMDC", "SAIL"],
    "NIFTY PHARMA": ["SUNPHARMA", "DRREDDY", "CIPLA", "DIVISLAB", "LUPIN", "APOLLOHOSP", "MANKIND"],
    "NIFTY ENERGY": ["RELIANCE", "ONGC", "NTPC", "POWERGRID", "BPCL", "IOC", "ADANIENT", "ADANIGREEN"],
    "NIFTY FMCG": ["HINDUNILVR", "ITC", "NESTLEIND", "BRITANNIA", "TATACONSUM", "DABUR", "GODREJCP"],
    "NIFTY REALTY": ["DLF", "GODREJPROP", "OBEROIRLTY", "MACROTECH", "PRESTIGE", "BRIGADE"],
    "NIFTY PSU BANK": ["SBIN", "BANKBARODA", "PNB", "CANBK", "UNIONBANK", "INDIANB"],
    "NIFTY INFRA": ["LT", "ULTRACEMCO", "GRASIM", "BHARTIARTL", "ADANIPORTS"],
    "NIFTY MEDIA": ["ZEEL", "SUNTV", "PVRINOX", "NETWORK18"],
    "COMMODITIES_MCX": ["GOLDM", "SILVERM", "CRUDEOIL", "NATURALGAS", "COPPER"],
}


class SectorRotationRadar:
    """Calculates live relative strength & sector rotation quadrant matrix."""

    @classmethod
    def get_live_sector_matrix(cls) -> list[dict[str, Any]]:
        """Returns the 12 NSE sectors with RS-Ratio, RS-Momentum, and Quadrant.

        NOTE: This is a static, hardcoded sample matrix, not derived from any
        real market data feed - there is no live NSE sector price/turnover
        ingestion wired into this module. Every row is flagged with
        ``is_demo_data: True`` so callers/UI never present it as real-time.
        """
        sectors_data = [
            ("NIFTY IT", 104.2, 102.8, 2.45, 1420.5, "LEADING", "Institutional FII & DII Tech Accumulation"),
            ("NIFTY AUTO", 102.8, 101.5, 1.82, 980.2, "LEADING", "Strong Festive Volume & EV Growth"),
            ("NIFTY REALTY", 101.9, 103.1, 3.12, 450.8, "IMPROVING", "Residential Pre-Sales Breakout"),
            ("NIFTY PHARMA", 100.8, 101.2, 0.95, 620.0, "IMPROVING", "Defensive Smart Money Allocation"),
            ("NIFTY BANK", 99.4, 98.8, -0.45, 2850.0, "WEAKENING", "NIM Compression & Consolidation"),
            ("NIFTY ENERGY", 98.9, 97.9, -0.80, 1640.2, "WEAKENING", "Refining Margin Softness"),
            ("NIFTY FMCG", 97.5, 96.2, -1.25, 830.4, "LAGGING", "Rural Consumption Slowdown"),
            ("NIFTY METAL", 96.8, 95.4, -2.10, 710.0, "LAGGING", "Global Commodity Deflation"),
            ("NIFTY PSU BANK", 101.5, 99.2, 0.50, 890.0, "WEAKENING", "Profit Booking After Multi-Year Rally"),
            ("NIFTY INFRA", 100.2, 100.8, 0.75, 1120.0, "IMPROVING", "Capex Budget Outlay Tailwinds"),
            ("NIFTY MEDIA", 94.2, 93.1, -2.85, 120.5, "LAGGING", "Ad Revenue Underperformance"),
            ("COMMODITIES_MCX", 103.5, 102.0, 1.65, 3400.0, "LEADING", "Precious Metals Safe Haven Flow"),
        ]

        matrix = []
        for name, rs_ratio, rs_mom, chg_pct, turnover_cr, quad, commentary in sectors_data:
            matrix.append({
                "sector": name,
                "rs_ratio": rs_ratio,
                "rs_momentum": rs_mom,
                "day_change_pct": chg_pct,
                "turnover_cr": turnover_cr,
                "quadrant": quad,
                "commentary": commentary,
                "is_demo_data": True,
            })
        return matrix

    @classmethod
    def get_sector_for_stock(cls, symbol: str) -> str:
        """Find parent sector for a given stock symbol."""
        sym = symbol.upper().replace(".NS", "")
        for sec, constituents in NSE_SECTOR_MAP.items():
            if sym in constituents:
                return sec
        return "GENERAL_EQUITY"

    @classmethod
    def get_sector_boost(cls, symbol: str) -> int:
        """Returns +5 score bonus if stock's parent sector is LEADING, -3 if LAGGING."""
        sec = cls.get_sector_for_stock(symbol)
        matrix = cls.get_live_sector_matrix()
        sec_info = next((s for s in matrix if s["sector"] == sec), None)
        if sec_info:
            if sec_info["quadrant"] == "LEADING":
                return 5
            elif sec_info["quadrant"] == "LAGGING":
                return -3
        return 0
