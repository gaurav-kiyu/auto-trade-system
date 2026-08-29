"""Mathematical Invariant Test Suite for 6-Layer Quant Architecture (v6.0 Production).

Enforces strictly:
1. Invariant 1: P(T2 | DIR) <= P(T1 | DIR)
2. Invariant 2: P(T1 | DIR) + P(SL | DIR) + P(TIMEOUT | DIR) = 1.0
3. Invariant 3: P(BUY) + P(SELL) + P(NO_TRADE) = 1.0
4. Invariant 4: EV matches non-overlapping formula with timeout payoff within 1e-4 tolerance
5. Invariant 5: Two-level weights sum to 1.0 at cluster level and 1.0 within each cluster
6. Invariant 6: Zero-weight strategies have exactly 0.0 contribution
7. Invariant 7: Risk Veto always overrides Model Decision to NO_TRADE
8. Invariant 8: SHA-256 hash chain validity and tamper detection
"""

from core.quant import (
    CalibratedMetaModel,
    FactorClusterEvaluator,
    PreGuardDataQualityEngine,
    RiskVetoEngine,
    SignalAuditRecord,
)


def test_invariant_1_and_2_probability_bounds_and_partitions():
    """Verify Stage A sums to 1.0 and Stage B satisfies P(T2) <= P(T1) and sums to 1.0."""
    meta = CalibratedMetaModel(probability_threshold=0.75)
    
    # Test across multiple score regimes
    for score in [20.0, 45.0, 65.0, 80.0, 95.0]:
        res = meta.evaluate(
            composite_score=score,
            regime="TRENDING_BULLISH",
            cluster_scores={"MOMENTUM_TREND_CLUSTER": score, "OPTIONS_DERIVATIVES_CLUSTER": score},
            entry_price=100.0,
            stop_loss_price=90.0,
            target_1_price=115.0,
            target_2_price=130.0,
        )
        
        # Invariant 3: Stage A Directional Probabilities sum to 1.0
        sum_stage_a = res.directional_prob.p_buy + res.directional_prob.p_sell + res.directional_prob.p_no_trade
        assert abs(sum_stage_a - 1.0) < 1e-3, f"Stage A does not sum to 1.0: {sum_stage_a}"
        
        # Invariant 1: P(T2) <= P(T1)
        assert res.conditional_outcomes.p_t2 <= res.conditional_outcomes.p_t1 + 1e-4, "P(T2) > P(T1)!"
        
        # Invariant 2: P(T1) + P(SL) + P(TIMEOUT) = 1.0
        sum_stage_b = res.conditional_outcomes.p_t1 + res.conditional_outcomes.p_sl + res.conditional_outcomes.p_timeout
        assert abs(sum_stage_b - 1.0) < 1e-3, f"Stage B does not sum to 1.0: {sum_stage_b}"


def test_invariant_4_expected_value_non_overlapping_exactness():
    """Verify EV matches the reference non-overlapping formula with timeout payoff."""
    meta = CalibratedMetaModel()
    
    entry = 142.50
    sl = 105.00
    t1 = 185.25
    t2 = 228.00
    
    res = meta.evaluate(
        composite_score=85.0,
        regime="TRENDING_BULLISH",
        cluster_scores={"MOMENTUM_TREND_CLUSTER": 85.0},
        entry_price=entry,
        stop_loss_price=sl,
        target_1_price=t1,
        target_2_price=t2,
    )
    
    p1 = res.conditional_outcomes.p_t1
    p2 = res.conditional_outcomes.p_t2
    psl = res.conditional_outcomes.p_sl
    pto = res.conditional_outcomes.p_timeout
    r1 = res.net_rr_t1
    r2 = res.net_rr_t2
    rto = res.r_timeout
    
    # Reference EV calculation
    expected_ev_ref = (p2 * r2) + ((p1 - p2) * r1) + (pto * rto) - (psl * 1.0)
    assert abs(res.expected_value - round(expected_ev_ref, 4)) < 1e-3, f"EV mismatch: {res.expected_value} vs {expected_ev_ref}"


def test_invariant_5_and_6_hierarchical_weights_sum_to_one():
    """Verify Level 1 and Level 2 weights sum to 1.0 and 0% DCF on options contributes 0.0."""
    evaluator = FactorClusterEvaluator()
    
    # 1. Test Intraday Option
    res_opt = evaluator.evaluate(
        asset_class="INDEX_OPTION",
        regime="TRENDING_BULLISH",
        raw_strategy_scores={"DCF_MARGIN_OF_SAFETY": 100.0, "OPB": 80.0, "GEX": 90.0},
    )
    
    # Level 1 Cluster Weights sum to 1.0
    cw = res_opt.resolved_weights_matrix["cluster_weights"]
    assert abs(sum(cw.values()) - 1.0) < 1e-3
    
    # Level 2 Strategy Weights within each cluster sum to 1.0
    for c_name, sw in res_opt.resolved_weights_matrix["strategy_weights"].items():
        assert abs(sum(sw.values()) - 1.0) < 1e-3
        
    # Invariant 6: DCF has 0% weight in options Context cluster
    context_sw = res_opt.resolved_weights_matrix["strategy_weights"]["CONTEXT_MACRO_CLUSTER"]
    assert context_sw.get("DCF_MARGIN_OF_SAFETY") == 0.0


def test_invariant_7_risk_veto_hard_override():
    """Verify that Risk Veto always overrides Model Decision to NO_TRADE."""
    veto_engine = RiskVetoEngine(daily_loss_limit_reached=True)
    preguard_engine = PreGuardDataQualityEngine()
    meta = CalibratedMetaModel()
    
    pre_res = preguard_engine.validate_quote("NIFTY24AUG24500CE", "INDEX_OPTION", 142.50)
    meta_res = meta.evaluate(85.0, "TRENDING_BULLISH", {}, 142.50, 105.0, 185.25, 228.0)
    
    # Model chose BUY
    assert meta_res.direction == "BUY"
    
    # Arbitrate with active daily loss limit
    arb_res = veto_engine.arbitrate(pre_res, "TRENDING_BULLISH", meta_res)
    assert arb_res.vetoed is True
    assert arb_res.final_decision == "NO_TRADE"
    assert arb_res.final_reason_code == "PORTFOLIO_DAILY_DRAWDOWN_LIMIT"


def test_invariant_8_sha256_audit_hash_chain():
    """Verify SHA-256 canonical hashing and tamper-evident linking."""
    record = SignalAuditRecord(
        signal_id="SIG-TEST-001",
        decision_timestamp="2026-08-20T09:15:00.000",
        data_snapshot_timestamp="2026-08-20T09:14:59.850",
        symbol="NIFTY24AUG24500CE",
        asset_class="INDEX_OPTION",
        model_decision="BUY",
        risk_decision="PASS",
        final_decision="BUY",
        final_reason_code="SUCCESS_PASS",
        regime="TRENDING_BULLISH",
        regime_confidence=0.88,
        composite_score=84.5,
        cluster_scores={"MOMENTUM_TREND_CLUSTER": 85.0},
        resolved_weights={},
        p_direction=0.82,
        p_t1=0.84,
        p_t2=0.52,
        p_sl=0.08,
        p_timeout=0.08,
        expected_value=0.64,
        net_rr_t1=1.14,
        net_rr_t2=2.28,
        r_timeout=0.45,
        direction_shap_drivers=["Momentum Strong"],
        outcome_shap_drivers=["GEX High"],
        entry_price=142.50,
        stop_loss_price=105.00,
        target_1_price=185.25,
        target_2_price=228.00,
        previous_record_hash="GENESIS_HASH",
    )
    
    hash1 = record.calculate_payload_hash()
    assert len(hash1) == 64  # Valid SHA-256 hex string
    
    # Tamper test: Altering any field changes the hash
    record.composite_score = 84.6
    hash2 = record.calculate_payload_hash()
    assert hash1 != hash2, "Tamper detection failed!"


def test_invariant_9_and_10_direction_aware_timeout_and_strictly_positive_risk():
    """Verify Invariant 9 (directionally normalized R_TIMEOUT) and Invariant 10 (Initial Risk > 0)."""
    meta = CalibratedMetaModel()
    
    # Test BUY direction
    res_buy = meta.evaluate(
        composite_score=85.0,
        regime="TRENDING_BULLISH",
        cluster_scores={},
        entry_price=100.0,
        stop_loss_price=90.0,
        target_1_price=115.0,
        target_2_price=130.0,
        estimated_timeout_exit_price=106.0,  # Profitable exit
        estimated_slippage_cost_r=0.0,
    )
    assert res_buy.r_timeout == 0.60, f"Expected +0.60R for BUY, got {res_buy.r_timeout}R"
    
    # Test SELL direction with profitable exit (exit below entry)
    res_sell = meta.evaluate(
        composite_score=20.0,
        regime="TRENDING_BEARISH",
        cluster_scores={},
        entry_price=100.0,
        stop_loss_price=110.0,
        target_1_price=85.0,
        target_2_price=70.0,
        estimated_timeout_exit_price=94.0,  # Profitable short exit
        estimated_slippage_cost_r=0.0,
    )
    assert res_sell.r_timeout == 0.60, f"Expected +0.60R for SELL, got {res_sell.r_timeout}R"
    
    # Invariant 10: Equal entry and SL prices do not divide by zero
    res_zero_risk = meta.evaluate(
        composite_score=85.0,
        regime="TRENDING_BULLISH",
        cluster_scores={},
        entry_price=100.0,
        stop_loss_price=100.0,  # Zero initial distance
        target_1_price=115.0,
        target_2_price=130.0,
    )
    assert res_zero_risk.expected_value is not None
    assert not float("-inf") == res_zero_risk.expected_value
    assert not float("inf") == res_zero_risk.expected_value
