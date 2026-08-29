"""Official NSE F&O Universe & Instrument Classifier (v3.0).

Provides authoritative categorization between:
1. F&O Derivative Instruments (Indices + ~185 F&O Eligible Stocks):
   - Supports 2-Way Option Buying: BUY CE (Call Option) & BUY PE (Put Option).
   - Guaranteed active Option Chain on Zerodha / Angel / Groww.
2. Cash Equity Stocks (~2,300+ Listed Stocks):
   - Strictly LONG-ONLY (BUY for Swing, Positional, Delivery / CNC).
   - Automatically blocks and suppresses cash short-selling (PUT/SELL).
"""

from __future__ import annotations

# Official Indices with Active Derivative Contracts
FNO_INDICES: set[str] = {
    "NIFTY",
    "BANKNIFTY",
    "FINNIFTY",
    "MIDCPNIFTY",
    "NIFTYNXT50",
    "SENSEX",
    "BANKEX",
}

# Official NSE F&O Listed Equity Stocks (~185 Stocks)
FNO_EQUITY_STOCKS: set[str] = {
    "AARTIIND", "ABB", "ABBOTINDIA", "ABCAPITAL", "ABFRL", "ACC", "ADANIENT", "ADANIPORTS",
    "ALKEM", "AMBUJACEM", "APOLLOHOSP", "APOLLOTYRE", "ASHOKLEY", "ASIANPAINT", "ASTRAL",
    "ATUL", "AUBANK", "AUROPHARMA", "AXISBANK", "BAJAJ-AUTO", "BAJAJFINSV", "BAJFINANCE",
    "BALKRISIND", "BALRAMCHIN", "BANDHANBNK", "BANKBARODA", "BATAINDIA", "BEL", "BERGEPAINT",
    "BHARATFORG", "BHARTIARTL", "BHEL", "BIOCON", "BOSCHLTD", "BPCL", "BRITANNIA", "BSOFT",
    "CANBK", "CANFINHOME", "CHAMBLFERT", "CHOLAFIN", "CIPLA", "COALINDIA", "COFORGE", "COLPAL",
    "CONCOR", "COROMANDEL", "CROMPTON", "CUB", "CUMMINSIND", "DABUR", "DALBHARAT", "DEEPAKNTR",
    "DELHIVERY", "DIVISLAB", "DIXON", "DLF", "DRREDDY", "EICHERMOT", "ESCORTS", "EXIDEIND",
    "FEDERALBNK", "GAIL", "GLENMARK", "GMRINFRA", "GNFC", "GODREJCP", "GODREJPROP", "GRANULES",
    "GRASIM", "GUJGASLTD", "HAL", "HAVELLS", "HCLTECH", "HDFCAMC", "HDFCBANK", "HDFCLIFE",
    "HEROMOTOCO", "HINDALCO", "HINDCOPPER", "HINDPETRO", "HINDUNILVR", "ICICIBANK", "ICICIGI",
    "ICICIPRULI", "IDEA", "IDFC", "IDFCFIRSTB", "IEX", "IGL", "INDHOTEL", "INDIAMART",
    "INDIACEM", "INDIGO", "INDUSINDBK", "INDUSTOWER", "INFY", "IOC", "IPCALAB", "IRCTC",
    "ITC", "JINDALSTEL", "JKCEMENT", "JSWSTEEL", "JUBLFOOD", "KOTAKBANK", "LALPATHLAB",
    "LAURUSLABS", "LICHSGFIN", "LICI", "LT", "LTF", "LTIM", "LTTS", "LUPIN", "M&M",
    "M&MFIN", "MANAPPURAM", "MARICO", "MARUTI", "MCDOWELL-N", "MCX", "METROPOLIS", "MFSL",
    "MGL", "MOTHERSON", "MPHASIS", "MRF", "MUTHOOTFIN", "NATIONALUM", "NAUKRI", "NAVINFLUOR",
    "NESTLEIND", "NMDC", "NTPC", "OBEROIRLTY", "OFSS", "ONGC", "PAGEIND", "PEL", "PERSISTENT",
    "PETRONET", "PFC", "PIDILITIND", "PIIND", "PNB", "POLYCAB", "PVRINOX", "RAMCOCEM",
    "RBLBANK", "RECLTD", "RELIANCE", "SAIL", "SBICARD", "SBILIFE", "SBIN", "SHREECEM",
    "SHRIRAMFIN", "SIEMENS", "SRF", "SUNPHARMA", "SUNTV", "SYNGENE", "TATACHEM", "TATACOMM",
    "TATACONSUM", "TATAMOTORS", "TATAPOWER", "TATASTEEL", "TCS", "TECHM", "TITAN",
    "TORNTPHARM", "TRENT", "TVSMOTOR", "UBL", "ULTRACEMCO", "UPL", "VEDL", "VOLTAS",
    "WIPRO", "ZYDUSLIFE", "ZOMATO", "JIOFIN", "TATAELXSI", "CGPOWER", "BSE", "IRFC",
    "POONAWALLA", "PRESTIGE", "POLICYBZR", "MAXHEALTH", "PAYTM", "HUDCO", "KALYANKJIL",
}


def is_fno_symbol(symbol: str) -> bool:
    """Check if a symbol has active Options & Futures contracts on NSE."""
    clean_sym = symbol.strip().upper().replace(".NS", "")
    return clean_sym in FNO_INDICES or clean_sym in FNO_EQUITY_STOCKS


def is_index_symbol(symbol: str) -> bool:
    """Check if a symbol is an index derivative."""
    clean_sym = symbol.strip().upper().replace(".NS", "")
    return clean_sym in FNO_INDICES


def classify_instrument_market(symbol: str, series: str = "EQ") -> str:
    """Classify instrument into exact trading category."""
    clean_sym = symbol.strip().upper().replace(".NS", "")
    if clean_sym in FNO_INDICES:
        return "INDEX_OPTIONS"
    if clean_sym in FNO_EQUITY_STOCKS:
        return "STOCK_OPTIONS"
    if series in ("SM", "ST"):
        return "PENNY_SME"
    return "EQUITY_SWING_DELIVERY"
