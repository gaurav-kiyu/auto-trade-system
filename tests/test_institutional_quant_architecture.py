"""Integration Test Suite for 6-Layer Institutional Architecture (v6.0 Production)."""

from core.quant import (
    CalibratedMetaModel,
    FactorClusterEvaluator,
    MarketRegimeEngine,
    PreGuardDataQualityEngine,
    RiskVetoEngine,
)


def test_layer_0_preguard_validations():
    engine = PreGuardDataQualityEngine()
    
    # 1. Invalid Contract
    res = engine.validate_quote("INVALID_SYM", "INDEX_OPTION", 100.0, is_active_contract=False)
    assert res.passed is False
    assert res.status_code == "PREGUARD_INVALID_CONTRACT_MASTER"
    
    # 2. Excessive Spread
    res = engine.validate_quote("NIFTY_CE", "INDEX_OPTION", 100.0, bid=90.0, ask=98.0)
    assert res.passed is False
    assert res.status_code == "PREGUARD_SPREAD_EXCESSIVE"
    
    # 3. Healthy Quote Pass
    res = engine.validate_quote("NIFTY_CE", "INDEX_OPTION", 100.0, bid=99.5, ask=100.2)
    assert res.passed is True
    assert res.status_code == "PASS"


def test_layer_1_regime_transitions_and_hysteresis():
    engine = MarketRegimeEngine(trend_enter_adx=26.0, trend_exit_adx=22.0)
    
    # 1. Low ADX -> Range Bound
    st1 = engine.detect_regime(adx=15.0, price=100.0, vwap=100.0)
    assert st1.regime == "RANGE_BOUND_CHOPPY"
    
    # 2. High ADX + Bullish -> Trending Bullish
    st2 = engine.detect_regime(adx=28.0, price=105.0, vwap=100.0, supertrend_dir="BULLISH")
    assert st2.regime == "TRENDING_BULLISH"
    
    # 3. Hysteresis: ADX drops to 24.0 -> remains Trending Bullish because > exit threshold 22.0
    st3 = engine.detect_regime(adx=24.0, price=105.0, vwap=100.0, supertrend_dir="BULLISH")
    assert st3.regime == "TRENDING_BULLISH"
    
    # 4. ADX drops to 20.0 -> drops out of trend into Transitional/Range
    st4 = engine.detect_regime(adx=20.0, price=100.0, vwap=100.0)
    assert st4.regime == "TRANSITIONAL_UNCERTAIN"


def test_full_6_layer_end_to_end_flow():
    preguard = PreGuardDataQualityEngine()
    regime_eng = MarketRegimeEngine()
    clusters = FactorClusterEvaluator()
    meta = CalibratedMetaModel()
    veto = RiskVetoEngine()
    
    # 1. L0 Pre-Guard
    quote_res = preguard.validate_quote("TCS", "EQUITY_INTRADAY", 2268.0, bid=2267.5, ask=2268.5)
    assert quote_res.passed is True
    
    # 2. L1 Regime
    regime_res = regime_eng.detect_regime(adx=28.0, price=2268.0, vwap=2260.0, supertrend_dir="BULLISH")
    assert regime_res.regime == "TRENDING_BULLISH"
    
    # 3. L2 & L3 Clusters & Weights
    evidence = clusters.evaluate(
        asset_class="EQUITY_INTRADAY",
        regime=regime_res.regime,
        raw_strategy_scores={
            "OPB": 90.0,
            "SUPERTREND": 88.0,
            "VOLATILITY_SQUEEZE": 85.0,
            "CVD_ORDERFLOW": 88.0,
            "GEX": 85.0,
            "SECTOR_RELATIVE_STRENGTH": 85.0,
            "FII_DII_FLOW": 80.0,
        },
    )
    assert evidence.composite_score >= 75.0
    
    # 4. L4 Meta Model
    meta_res = meta.evaluate(
        composite_score=evidence.composite_score,
        regime=regime_res.regime,
        cluster_scores={k: v.cluster_score for k, v in evidence.cluster_evidences.items()},
        entry_price=2268.0,
        stop_loss_price=2200.0,
        target_1_price=2358.70,
        target_2_price=2449.40,
    )
    assert meta_res.direction == "BUY"
    assert meta_res.expected_value > 0.15
    
    # 5. L5 Risk & Veto
    final_res = veto.arbitrate(quote_res, regime_res.regime, meta_res)
    assert final_res.final_decision == "BUY"
    assert final_res.final_reason_code == "SUCCESS_PASS"
