"""Unit tests for Institutional Pinnacle Enhancements (SHAP Explainer, Stress Testing, AutoML)."""
from core.ai.automl_optimizer import AutoMLHyperparameterOptimizer
from core.ai.shap_signal_explainer import SHAPSignalExplainer
from core.risk.stress_testing_engine import ExtremeStressTestingEngine


def test_shap_signal_explainer():
    explainer = SHAPSignalExplainer(base_value=50.0)
    report = explainer.explain_signal(
        symbol="NIFTY",
        direction="BUY",
        features={
            "rsi": 62.0,
            "vwap_distance_pct": 0.008,
            "ema_aligned": True,
            "volume_ratio": 1.8,
        },
    )
    assert report.symbol == "NIFTY"
    assert report.final_score > 70.0
    assert len(report.attributions) == 4
    assert report.confidence_score >= 0.90


def test_extreme_stress_testing_engine():
    engine = ExtremeStressTestingEngine(portfolio_value=100000.0)
    report = engine.run_stress_tests()
    assert report.portfolio_value == 100000.0
    assert report.var_99_1d_inr > 0
    assert report.cvar_99_1d_inr > report.var_99_1d_inr
    assert len(report.scenarios) == 4
    for sc in report.scenarios:
        assert sc.survived is True


def test_automl_hyperparameter_optimizer():
    optimizer = AutoMLHyperparameterOptimizer(target_win_rate=90.0)
    result = optimizer.optimize(iterations=20)
    assert result.iterations == 20
    assert result.best_win_rate >= 90.0
    assert result.best_profit_factor > 2.0
    assert result.status == "OPTIMIZED"
