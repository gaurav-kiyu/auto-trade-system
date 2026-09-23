"""Tests for Category-Specific Conviction Score Limits.

Index Options >= 80, F&O Stock Options >= 80, Equity CNC/delivery >= 70, Penny/SME >= 80.
Canonical release-gate threshold governance established in OPB v2.59.4.
See json/config.json's CATEGORY_SCORE_THRESHOLDS and json/index_config.defaults.json.
"""

from core.all_nse_scanner import AllNSEScanner, ScannedStockSignal


def test_category_threshold_resolution():
    """Verify scanner resolves 80/80/70 for INDEX_OPTIONS/STOCK_OPTIONS/EQUITY_SWING_DELIVERY, 80 for PENNY_SME."""
    scanner = AllNSEScanner()
    scanner._reload_config_credentials()

    assert scanner.get_min_score_for_category("INDEX_OPTIONS") == 80
    assert scanner.get_min_score_for_category("STOCK_OPTIONS") == 80
    assert scanner.get_min_score_for_category("EQUITY_SWING_DELIVERY") == 70
    assert scanner.get_min_score_for_category("PENNY_SME") == 80


def test_index_signals_allow_80_and_block_below():
    """Verify Index Options allow score >= 80 and block score < 80."""
    scanner = AllNSEScanner()
    scanner._reload_config_credentials()

    # Score 78 on NIFTY -> Blocked (< 80)
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

    # Score 82 on SENSEX -> Allowed (>= 80)
    sig_82 = ScannedStockSignal(
        symbol="SENSEX",
        company_name="BSE Sensex Index",
        series="INDEX",
        direction="CALL",
        score=82,
        raw_score=82.0,
        tier="STRONG",
        regime="BULLISH",
        price=80500.0,
        rsi=62.0,
        adx=26.0,
        vwap=80420.0,
    )
    assert sig_82.score >= min_idx_score


def test_fno_stock_signals_require_85_and_block_below():
    """Verify F&O Stock Options require score >= 80 and block score < 80."""
    scanner = AllNSEScanner()
    scanner._reload_config_credentials()

    # Score 78 on RELIANCE -> Blocked (< 80)
    sig_78 = ScannedStockSignal(
        symbol="RELIANCE",
        company_name="Reliance Industries",
        series="EQ",
        direction="CALL",
        score=78,
        raw_score=78.0,
        tier="MODERATE",
        regime="BULLISH",
        price=2850.0,
        rsi=60.0,
        adx=25.0,
        vwap=2840.0,
    )
    min_fno_score = scanner.get_min_score_for_category("STOCK_OPTIONS")
    assert sig_78.score < min_fno_score

    # Score 86 on TCS -> Allowed (>= 80)
    sig_86 = ScannedStockSignal(
        symbol="TCS",
        company_name="Tata Consultancy Services",
        series="EQ",
        direction="CALL",
        score=86,
        raw_score=86.0,
        tier="STRONG",
        regime="BULLISH",
        price=3950.0,
        rsi=65.0,
        adx=29.0,
        vwap=3940.0,
    )
    assert sig_86.score >= min_fno_score


def test_equity_cnc_signals_require_90_and_block_below():
    """Verify Equity CNC/delivery signals require score >= 70 and block score < 70."""
    scanner = AllNSEScanner()
    scanner._reload_config_credentials()

    # Score 68 on INFY -> Blocked (< 70)
    sig_68 = ScannedStockSignal(
        symbol="INFY",
        company_name="Infosys Limited",
        series="EQ",
        direction="CALL",
        score=68,
        raw_score=68.0,
        tier="WEAK",
        regime="BULLISH",
        price=1850.0,
        rsi=58.0,
        adx=24.0,
        vwap=1840.0,
    )
    min_cnc_score = scanner.get_min_score_for_category("EQUITY_SWING_DELIVERY")
    assert sig_68.score < min_cnc_score

    # Score 75 on HDFCBANK -> Allowed (>= 70)
    sig_75 = ScannedStockSignal(
        symbol="HDFCBANK",
        company_name="HDFC Bank Limited",
        series="EQ",
        direction="CALL",
        score=75,
        raw_score=75.0,
        tier="MODERATE",
        regime="BULLISH",
        price=1650.0,
        rsi=63.0,
        adx=27.0,
        vwap=1640.0,
    )
    assert sig_75.score >= min_cnc_score
