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


# Official NSE NIFTY 50 Blue-Chip Equities (Top 50 Large-Cap Cash Equities)
NIFTY_50_STOCKS: set[str] = {
    "ADANIENT", "ADANIPORTS", "APOLLOHOSP", "ASIANPAINT", "AXISBANK",
    "BAJAJ-AUTO", "BAJFINANCE", "BAJAJFINSV", "BEL", "BHARTIARTL",
    "BPCL", "BRITANNIA", "CIPLA", "COALINDIA", "DRREDDY",
    "EICHERMOT", "GRASIM", "HCLTECH", "HDFCBANK", "HDFCLIFE",
    "HEROMOTOCO", "HINDALCO", "HINDUNILVR", "ICICIBANK", "INDUSINDBK",
    "INFY", "ITC", "JSWSTEEL", "KOTAKBANK", "LT",
    "M&M", "MARUTI", "NESTLEIND", "NTPC", "ONGC",
    "POWERGRID", "RELIANCE", "SBILIFE", "SBIN", "SHRIRAMFIN",
    "SUNPHARMA", "TATACONSUM", "TATAMOTORS", "TATASTEEL", "TCS",
    "TECHM", "TITAN", "TRENT", "ULTRACEMCO", "WIPRO",
}


def is_fno_symbol(symbol: str) -> bool:
    """Check if a symbol has active Options & Futures contracts on NSE."""
    clean_sym = symbol.strip().upper().replace(".NS", "")
    return clean_sym in FNO_INDICES or clean_sym in FNO_EQUITY_STOCKS


def is_index_symbol(symbol: str) -> bool:
    """Check if a symbol is an index derivative."""
    clean_sym = symbol.strip().upper().replace(".NS", "")
    return clean_sym in FNO_INDICES


def classify_instrument_market(
    symbol: str,
    series: str = "EQ",
    instrument_type: str | None = None,
    market_cap: str | None = None,
) -> str:
    """Classify instrument into exact trading category across canonical 10-class taxonomy.

    Supported Categories:
    1. INDEX_OPTIONS
    2. STOCK_OPTIONS
    3. FUTURES
    4. COMMODITIES
    5. CURRENCIES
    6. ETFS_REITS
    7. PENNY_SME
    8. LARGE_CAP_EQUITY
    9. MID_SMALL_CAP
    10. EQUITY_SWING_DELIVERY
    """
    clean_sym = symbol.strip().upper().replace(".NS", "")
    ser_up = (series or "EQ").strip().upper()
    itype_up = (instrument_type or "").strip().upper()
    mcap_up = (market_cap or "").strip().upper()

    # 1. Commodities (MCX)
    if clean_sym in {"CRUDEOIL", "NATURALGAS", "GOLD", "GOLDM", "SILVER", "SILVERM", "COPPER", "ZINC", "LEAD", "ALUMINIUM", "NICKEL"} or clean_sym.startswith("MCX:"):
        return "COMMODITIES"

    # 2. Currencies (CDS)
    if clean_sym in {"USDINR", "EURINR", "GBPINR", "JPYINR"} or clean_sym.startswith("CDS:"):
        return "CURRENCIES"

    # 3. ETFs & REITs
    if any(k in clean_sym for k in ("BEES", "ETF", "INVIT", "REIT", "GOLDSHARE")):
        return "ETFS_REITS"

    # 4. Penny & SME
    if ser_up in ("SM", "ST", "BZ") or ser_up in ("SME", "PENNY") or clean_sym.endswith(("_SME", "-SME")):
        return "PENNY_SME"

    # 5. Futures
    if clean_sym.endswith(("-FUT", "_FUT", "FUT")) or clean_sym.endswith("FUTURES") or itype_up in ("FUTIDX", "FUTSTK", "FUTURES"):
        return "FUTURES"

    # 6. Index Options
    if clean_sym in FNO_INDICES or clean_sym in {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX", "BANKEX"}:
        return "INDEX_OPTIONS"
    if (clean_sym.startswith(("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX", "BANKEX")) and
            (clean_sym.endswith(("CE", "PE")) or itype_up in ("OPTIDX", "INDEX_OPTIONS"))):
        return "INDEX_OPTIONS"

    # Boundary handling: Cash Equity vs Derivatives vs Swing/Delivery
    # 7. Explicit Equity Swing & Delivery (Delivery / CNC / Swing Strategy)
    if ser_up in ("SWING", "DELIVERY", "CNC") or itype_up in ("SWING", "DELIVERY", "CNC"):
        return "EQUITY_SWING_DELIVERY"

    # 8. Explicit Large-Cap Equity
    if ser_up in ("LC", "LARGE_CAP") or mcap_up in ("LARGE_CAP", "LARGE"):
        return "LARGE_CAP_EQUITY"

    # 9. Explicit Mid/Small-Cap
    if ser_up in ("SMC", "MID_CAP", "SMALL_CAP") or mcap_up in ("MID_CAP", "SMALL_CAP", "MID_SMALL"):
        return "MID_SMALL_CAP"

    # 10. Cash Equity Instruments (explicit CASH / EQUITY instrument type)
    if itype_up in ("CASH", "EQUITY"):
        if clean_sym in NIFTY_50_STOCKS:
            return "LARGE_CAP_EQUITY"
        if clean_sym in FNO_EQUITY_STOCKS or ser_up == "EQ":
            return "MID_SMALL_CAP"
        return "EQUITY_SWING_DELIVERY"

    # Stock options (derivatives on F&O listed stocks)
    if clean_sym in FNO_EQUITY_STOCKS or itype_up in ("OPTSTK", "STOCK_OPTIONS"):
        return "STOCK_OPTIONS"

    # Default fallback for cash equity
    return "EQUITY_SWING_DELIVERY"


