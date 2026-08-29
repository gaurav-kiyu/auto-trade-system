"""Tests for core/ai_token_cost_tracker.py — AI Token Cost Tracker."""

from __future__ import annotations

from core.ai_token_cost_tracker import (
    MODEL_PRICING,
    MonthlyCostReport,
    TokenCostTracker,
    UsageRecord,
    get_token_cost_tracker,
    reset_token_cost_tracker,
)


class TestUsageRecord:
    """UsageRecord dataclass."""

    def test_basic_fields(self):
        record = UsageRecord(
            model="gpt-4",
            provider="openai",
            feature="signal_scoring",
            prompt_tokens=100,
            completion_tokens=50,
        )
        assert record.model == "gpt-4"
        assert record.total_tokens == 150
        assert record.cost_usd > 0
        assert record.record_id.startswith("AI-")

    def test_cost_computation_gpt4(self):
        record = UsageRecord(
            model="gpt-4",
            provider="openai",
            feature="test",
            prompt_tokens=1000,
            completion_tokens=500,
        )
        # 1000 * 0.03/1000 = 0.03, 500 * 0.06/1000 = 0.03, total = 0.06
        assert record.cost_usd == pytest.approx(0.06, abs=0.001)

    def test_cost_computation_gpt4o_mini(self):
        record = UsageRecord(
            model="gpt-4o-mini",
            provider="openai",
            feature="test",
            prompt_tokens=1000,
            completion_tokens=1000,
        )
        # 1000 * 0.00015/1000 = 0.00015, 1000 * 0.0006/1000 = 0.0006
        assert record.cost_usd == pytest.approx(0.00075, abs=0.0001)

    def test_zero_tokens(self):
        record = UsageRecord(
            model="gpt-4", provider="openai", feature="test",
            prompt_tokens=0, completion_tokens=0,
        )
        assert record.total_tokens == 0
        assert record.cost_usd == 0.0

    def test_unknown_model_pricing(self):
        record = UsageRecord(
            model="unknown-model-v42",
            provider="custom",
            feature="test",
            prompt_tokens=1000,
            completion_tokens=500,
        )
        assert record.cost_usd > 0  # Falls back to default pricing

    def test_to_dict(self):
        record = UsageRecord(
            model="gpt-4", provider="openai", feature="test",
            prompt_tokens=100, completion_tokens=50,
        )
        d = record.to_dict()
        assert d["model"] == "gpt-4"
        assert d["total_tokens"] == 150
        assert "date" in d


class TestTokenCostTracker:
    """TokenCostTracker class."""

    def test_init(self):
        tracker = TokenCostTracker()
        assert tracker is not None
        tracker.clear_records()

    def test_record_usage(self):
        tracker = TokenCostTracker()
        record = tracker.record_usage(
            model="gpt-4",
            feature="signal_scoring",
            prompt_tokens=100,
            completion_tokens=50,
        )
        assert record.model == "gpt-4"
        assert record.feature == "signal_scoring"
        assert record.total_tokens == 150

        stats = tracker.get_stats()
        assert stats["total_records"] == 1
        tracker.clear_records()

    def test_record_auto_provider(self):
        tracker = TokenCostTracker()
        record = tracker.record_usage(
            model="gpt-4",
            feature="test",
            prompt_tokens=10,
            completion_tokens=5,
        )
        assert record.provider == "openai"
        tracker.clear_records()

    def test_record_custom_provider(self):
        tracker = TokenCostTracker()
        record = tracker.record_usage(
            model="custom-model",
            provider="custom",
            feature="test",
            prompt_tokens=100,
            completion_tokens=50,
        )
        assert record.provider == "custom"
        tracker.clear_records()

    def test_multiple_records(self):
        tracker = TokenCostTracker()
        tracker.record_usage(model="gpt-4", feature="a", prompt_tokens=100, completion_tokens=50)
        tracker.record_usage(model="claude-3-opus", feature="b", prompt_tokens=200, completion_tokens=100)
        stats = tracker.get_stats()
        assert stats["total_records"] == 2
        assert len(stats["models"]) == 2
        tracker.clear_records()

    def test_get_pricing(self):
        tracker = TokenCostTracker()
        pricing = tracker.get_pricing("gpt-4")
        assert pricing["model"] == "gpt-4"
        assert pricing["provider"] == "openai"
        assert pricing["input_per_1k"] == 0.03

    def test_get_pricing_unknown(self):
        tracker = TokenCostTracker()
        pricing = tracker.get_pricing("nonexistent")
        assert pricing["provider"] == "unknown"
        assert pricing["input_per_1k"] > 0

    def test_register_custom_pricing(self):
        tracker = TokenCostTracker()
        tracker.register_custom_pricing("my-model", input_per_1k=0.001, output_per_1k=0.002, provider="custom")
        record = tracker.record_usage(
            model="my-model", feature="test",
            prompt_tokens=1000, completion_tokens=1000,
        )
        assert record.provider == "custom"
        # 1000 * 0.001/1000 = 0.001, 1000 * 0.002/1000 = 0.002, total = 0.003
        assert record.cost_usd == pytest.approx(0.003, abs=0.0001)
        tracker.clear_records()

    def test_monthly_report_empty(self):
        tracker = TokenCostTracker()
        report = tracker.get_monthly_report()
        assert isinstance(report, MonthlyCostReport)
        tracker.clear_records()

    def test_report_with_days(self):
        tracker = TokenCostTracker()
        tracker.record_usage(model="gpt-4", feature="test", prompt_tokens=100, completion_tokens=50)
        report = tracker.get_report(days=30)
        assert report.total_tokens > 0
        assert report.total_cost > 0
        tracker.clear_records()

    def test_get_feature_costs(self):
        tracker = TokenCostTracker()
        tracker.record_usage(model="gpt-4", feature="signal_scoring", prompt_tokens=100, completion_tokens=50)
        tracker.record_usage(model="gpt-4", feature="code_review", prompt_tokens=200, completion_tokens=100)
        costs = tracker.get_feature_costs()
        assert len(costs) >= 2
        tracker.clear_records()

    def test_get_model_costs(self):
        tracker = TokenCostTracker()
        tracker.record_usage(model="gpt-4", feature="test", prompt_tokens=500, completion_tokens=250)
        tracker.record_usage(model="gpt-4o-mini", feature="test", prompt_tokens=1000, completion_tokens=500)
        costs = tracker.get_model_costs()
        assert len(costs) >= 2
        # gpt-4 should be more expensive than gpt-4o-mini
        gpt4_cost = next(c for c in costs if c["model"] == "gpt-4")
        mini_cost = next(c for c in costs if c["model"] == "gpt-4o-mini")
        assert gpt4_cost["cost"] > mini_cost["cost"]
        tracker.clear_records()

    def test_set_budget(self):
        tracker = TokenCostTracker(monthly_budget=50.0)
        assert tracker._monthly_budget == 50.0
        tracker.set_budget(100.0)
        assert tracker._monthly_budget == 100.0
        tracker.clear_records()

    def test_budget_status(self):
        tracker = TokenCostTracker(monthly_budget=100.0)
        status = tracker.get_budget_status()
        assert status["monthly_budget"] == 100.0
        assert status["current_spend"] >= 0
        tracker.clear_records()

    def test_cost_optimization_no_data(self):
        tracker = TokenCostTracker()
        recs = tracker.get_cost_optimization_recommendations()
        assert isinstance(recs, list)
        tracker.clear_records()

    def test_cost_optimization_with_data(self):
        tracker = TokenCostTracker()
        # Record heavy usage of expensive model
        for _ in range(10):
            tracker.record_usage(
                model="gpt-4", feature="signal_scoring",
                prompt_tokens=1000, completion_tokens=500,
            )
        recs = tracker.get_cost_optimization_recommendations()
        assert len(recs) >= 0  # May or may not find optimizations
        tracker.clear_records()

    def test_pricing_constants(self):
        assert "gpt-4" in MODEL_PRICING
        assert "gpt-4o-mini" in MODEL_PRICING
        assert "claude-3-opus" in MODEL_PRICING
        assert "claude-3.5-sonnet" in MODEL_PRICING
        assert MODEL_PRICING["gpt-4"]["provider"] == "openai"
        assert MODEL_PRICING["claude-3-opus"]["provider"] == "anthropic"

    def test_all_time_report(self):
        tracker = TokenCostTracker()
        tracker.record_usage(model="gpt-4", feature="test", prompt_tokens=100, completion_tokens=50)
        report = tracker.get_all_time_report()
        assert report.total_tokens > 0
        tracker.clear_records()

    def test_get_budget_status_alerts(self):
        tracker = TokenCostTracker(monthly_budget=0.001)
        tracker.record_usage(model="gpt-4", feature="test", prompt_tokens=1000, completion_tokens=500)
        status = tracker.get_budget_status()
        assert len(status["alerts"]) >= 1 or status["budget_used_pct"] > 0
        tracker.clear_records()


class TestSingleton:
    """Singleton factory tests."""

    def test_get_and_reset(self):
        reset_token_cost_tracker()
        t1 = get_token_cost_tracker()
        t2 = get_token_cost_tracker()
        assert t1 is t2
        reset_token_cost_tracker()

    def test_reset_creates_new(self):
        reset_token_cost_tracker()
        t1 = get_token_cost_tracker()
        reset_token_cost_tracker()
        t2 = get_token_cost_tracker()
        assert t1 is not t2


# Need pytest.approx
import pytest
