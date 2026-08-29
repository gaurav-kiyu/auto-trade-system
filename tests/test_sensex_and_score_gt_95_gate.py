"""Tests for Sensex Option Index Support and Category-Level Conviction Gates."""

from core.fno_universe import is_fno_symbol, is_index_symbol, classify_instrument_market
from core.all_nse_scanner import AllNSEScanner, ScannedStockSignal


def test_sensex_in_fno_and_index_universe():
    """Verify SENSEX is classified as an F&O Index derivative."""
    assert is_fno_symbol("SENSEX") is True
    assert is_index_symbol("SENSEX") is True
    assert classify_instrument_market("SENSEX") == "INDEX_OPTIONS"


def test_priority_indices_in_universe_loader():
    """Verify load_nse_universe includes SENSEX, NIFTY, BANKNIFTY at the top."""
    scanner = AllNSEScanner()
    universe = scanner.load_nse_universe()
    
    top_symbols = [s["symbol"] for s in universe[:5]]
    assert "SENSEX" in top_symbols
    assert "NIFTY" in top_symbols
    assert "BANKNIFTY" in top_symbols


def test_index_score_below_100_is_suppressed():
    """Verify Index signals with score < 100 are rejected by the conviction gate."""
    scanner = AllNSEScanner()
    scanner._reload_config_credentials()

    # Sub-threshold signal (Score 75 on NIFTY)
    sig_75 = ScannedStockSignal(
        symbol="NIFTY",
        company_name="Nifty 50 Index",
        series="INDEX",
        direction="CALL",
        score=75,
        raw_score=75.0,
        tier="MODERATE",
        regime="BULLISH",
        price=24500.0,
        rsi=60.0,
        adx=25.0,
        vwap=244100.0,
    )

    min_score = scanner.get_min_score_for_category("INDEX_OPTIONS")
    assert min_score == 100
    assert sig_75.score < min_score


def test_index_score_100_and_above_is_permitted():
    """Verify Index signals with score >= 100 (e.g. 100) pass the conviction gate."""
    scanner = AllNSEScanner()
    scanner._reload_config_credentials()
    
    # Index conviction signal (Score 88 on SENSEX)
    ultra_sig = ScannedStockSignal(
        symbol="SENSEX",
        company_name="BSE Sensex Index",
        series="INDEX",
        direction="CALL",
        score=100,
        raw_score=100.0,
        tier="STRONG",
        regime="TRENDING_BULLISH",
        price=100500.0,
        rsi=68.0,
        adx=32.0,
        vwap=100420.0,
    )
    
    min_score = scanner.get_min_score_for_category("INDEX_OPTIONS")
    assert ultra_sig.score >= min_score
