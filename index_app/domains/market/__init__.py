"""Market Domain — NSE holiday fetching, intraday data retrieval, and VIX resolution.

Extracted from ``index_trader.py`` inline functions (``_fetch_nse_holidays_dynamic``,
``_fetch_intraday_data``, ``_fetch_intraday_data_cached``, ``_yf_fetch_vix``)
to reduce the monolith and centralise market-data-fetching logic.
"""
