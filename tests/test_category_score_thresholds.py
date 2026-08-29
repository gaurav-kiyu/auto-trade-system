"""Tests for Category-Specific Conviction Score Limits.

Index Options >= 100, F&O Stock Options >= 100, Equity CNC/delivery >= 100
(other categories default to 95). Updated 2026-08-21 to match the real
values in json/config.json / json/index_config.defaults.json -- previously
these three config keys existed nowhere in either file (only in
json/config.template.json), so get_min_score_for_category() always fell
through to its hardcoded 85/95 fallback regardless of what the "canonical"
defaults file said; these tests encoded that fallback, not a real config
value. See json/config.json's CATEGORY_SCORE_THRESHOLDS for the live values.
"""

from core.all_nse_scanner import AllNSEScanner, ScannedStockSignal


def test_category_threshold_resolution():
    """Verify scanner resolves 100/100/100 for INDEX_OPTIONS/STOCK_OPTIONS/EQUITY_SWING_DELIVERY, 95 for PENNY_SME."""
    scanner = AllNSEScanner()
    scanner._reload_config_credentials()

    assert scanner.get_min_score_for_category("INDEX_OPTIONS") == 100
    assert scanner.get_min_score_for_category("STOCK_OPTIONS") == 100
    assert scanner.get_min_score_for_category("EQUITY_SWING_DELIVERY") == 100
    assert scanner.get_min_score_for_category("PENNY_SME") == 100


def test_index_signals_allow_80_and_block_below():
    """Verify Index Options allow score >= 100 and block score < 100."""
    scanner = AllNSEScanner()
    scanner._reload_config_credentials()

    # Score 78 on NIFTY -> Blocked
    sig_78 = ScannedStockSignal(
        symbol="NIFTY",
        company_name="Nifty 50 Index",
        series="INDEX",
        direction="CALL",
        score=78,
        raw_score=78.0,
        tier="MODERATE",
        regime="BULLISH",
        price=24500.0,
        rsi=60.0,
        adx=25.0,
        vwap=24480.0,
    )
    min_idx_score = scanner.get_min_score_for_category("INDEX_OPTIONS")
    assert sig_78.score < min_idx_score

    # Score 82 on SENSEX -> Allowed
    sig_82 = ScannedStockSignal(
        symbol="SENSEX",
        company_name="BSE Sensex Index",
        series="INDEX",
        direction="CALL",
        score=100,
        raw_score=100.0,
        tier="STRONG",
        regime="BULLISH",
        price=80500.0,
        rsi=62.0,
        adx=26.0,
        vwap=80420.0,
    )
    assert sig_82.score >= min_idx_score


def test_fno_stock_signals_require_85_and_block_below():
    """Verify F&O Stock Options require score >= 100 and block score < 100."""
    scanner = AllNSEScanner()
    scanner._reload_config_credentials()

    # Score 82 on RELIANCE -> Blocked (< 100)
    sig_82 = ScannedStockSignal(
        symbol="RELIANCE",
        company_name="Reliance Industries",
        series="EQ",
        direction="CALL",
        score=82,
        raw_score=82.0,
        tier="MODERATE",
        regime="BULLISH",
        price=2850.0,
        rsi=60.0,
        adx=25.0,
        vwap=2840.0,
    )
    min_fno_score = scanner.get_min_score_for_category("STOCK_OPTIONS")
    assert sig_82.score < min_fno_score

    # Score 86 on TCS -> Allowed (>= 100)
    sig_86 = ScannedStockSignal(
        symbol="TCS",
        company_name="Tata Consultancy Services",
        series="EQ",
        direction="CALL",
        score=100,
        raw_score=100.0,
        tier="STRONG",
        regime="BULLISH",
        price=3950.0,
        rsi=65.0,
        adx=29.0,
        vwap=3940.0,
    )
    assert sig_86.score >= min_fno_score


def test_equity_cnc_signals_require_90_and_block_below():
    """Verify Equity CNC/delivery signals require score >= 100 and block score < 100."""
    scanner = AllNSEScanner()
    scanner._reload_config_credentials()

    # Score 87 on INFY -> Blocked (< 100)
    sig_87 = ScannedStockSignal(
        symbol="INFY",
        company_name="Infosys Limited",
        series="EQ",
        direction="CALL",
        score=87,
        raw_score=87.0,
        tier="MODERATE",
        regime="BULLISH",
        price=1850.0,
        rsi=58.0,
        adx=24.0,
        vwap=1840.0,
    )
    min_cnc_score = scanner.get_min_score_for_category("EQUITY_SWING_DELIVERY")
    assert sig_87.score < min_cnc_score

    # Score 92 on HDFCBANK -> Allowed (>= 100)
    sig_92 = ScannedStockSignal(
        symbol="HDFCBANK",
        company_name="HDFC Bank Limited",
        series="EQ",
        direction="CALL",
        score=100,
        raw_score=100.0,
        tier="STRONG",
        regime="BULLISH",
        price=1650.0,
        rsi=63.0,
        adx=27.0,
        vwap=1640.0,
    )
    assert sig_92.score >= min_cnc_score
