"""AI Token Cost Tracker — Tracks token usage and costs per model/provider/feature.

Provides:
  - Per-model cost tracking (OpenAI, Anthropic, local LLMs)
  - Per-feature attribution (which feature consumed how many tokens)
  - Budget monitoring with alerts
  - Cost optimization recommendations
  - Historical trending and reporting

Integrates with:
  - CostGovernance (for overall platform cost tracking)
  - BIDashboard (for cost visualization)
  - RecommendationEngine (for optimization suggestions)

Usage:
    from core.ai_token_cost_tracker import get_token_cost_tracker

    tracker = get_token_cost_tracker()
    tracker.record_usage(
        model="gpt-4",
        provider="openai",
        feature="signal_scoring",
        prompt_tokens=450,
        completion_tokens=120,
    )
    report = tracker.get_monthly_report()
    print(f"Total AI cost this month: ${report.total_cost:.2f}")
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)

# ── Cost Constants (per 1K tokens, USD) ───────────────────────────────────

MODEL_PRICING: dict[str, dict[str, float]] = {
    # OpenAI models
    "gpt-4": {"input_per_1k": 0.03, "output_per_1k": 0.06, "provider": "openai"},
    "gpt-4-turbo": {"input_per_1k": 0.01, "output_per_1k": 0.03, "provider": "openai"},
    "gpt-4o": {"input_per_1k": 0.005, "output_per_1k": 0.015, "provider": "openai"},
    "gpt-4o-mini": {"input_per_1k": 0.00015, "output_per_1k": 0.0006, "provider": "openai"},
    "gpt-3.5-turbo": {"input_per_1k": 0.0005, "output_per_1k": 0.0015, "provider": "openai"},
    # Anthropic models
    "claude-3-opus": {"input_per_1k": 0.015, "output_per_1k": 0.075, "provider": "anthropic"},
    "claude-3-sonnet": {"input_per_1k": 0.003, "output_per_1k": 0.015, "provider": "anthropic"},
    "claude-3-haiku": {"input_per_1k": 0.00025, "output_per_1k": 0.00125, "provider": "anthropic"},
    "claude-3.5-sonnet": {"input_per_1k": 0.003, "output_per_1k": 0.015, "provider": "anthropic"},
    # Google models
    "gemini-pro": {"input_per_1k": 0.000125, "output_per_1k": 0.000375, "provider": "google"},
    "gemini-ultra": {"input_per_1k": 0.001, "output_per_1k": 0.002, "provider": "google"},
    # Local models (approximate, based on compute cost)
    "llama-3-70b": {"input_per_1k": 0.001, "output_per_1k": 0.001, "provider": "local"},
    "llama-3-8b": {"input_per_1k": 0.0001, "output_per_1k": 0.0001, "provider": "local"},
    "mistral-large": {"input_per_1k": 0.002, "output_per_1k": 0.006, "provider": "mistral"},
    "deepseek-v3": {"input_per_1k": 0.0005, "output_per_1k": 0.0015, "provider": "deepseek"},
    "deepseek-r1": {"input_per_1k": 0.0005, "output_per_1k": 0.002, "provider": "deepseek"},
}

DEFAULT_UNKNOWN_MODEL_PRICE = {"input_per_1k": 0.01, "output_per_1k": 0.03, "provider": "unknown"}

# Feature categories for attribution
FEATURE_CATEGORIES = [
    "signal_scoring",
    "trade_analysis",
    "journal_narrative",
    "market_analysis",
    "code_generation",
    "code_review",
    "test_generation",
    "documentation",
    "incident_analysis",
    "report_generation",
    "sentiment_analysis",
    "recommendation",
    "chat_assistant",
    "other",
]

MONTHLY_BUDGET_DEFAULT = 100.0  # Default monthly AI token budget in USD


# ── Data Models ───────────────────────────────────────────────────────────


@dataclass
class UsageRecord:
    """A single token usage record."""

    model: str
    provider: str
    feature: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int = 0
    cost_usd: float = 0.0
    timestamp: float = 0.0
    record_id: str = ""

    def __post_init__(self) -> None:
        self.total_tokens = self.prompt_tokens + self.completion_tokens
        if self.cost_usd == 0.0 and self.total_tokens > 0:
            self.cost_usd = self._compute_cost()
        if not self.timestamp:
            self.timestamp = time.time()
        if not self.record_id:
            self.record_id = f"AI-{int(self.timestamp)}-{hash(str(self)) % 10000:04d}"

    def _compute_cost(self) -> float:
        """Compute cost based on model pricing."""
        pricing = MODEL_PRICING.get(self.model, DEFAULT_UNKNOWN_MODEL_PRICE)
        input_cost = (self.prompt_tokens / 1000) * pricing["input_per_1k"]
        output_cost = (self.completion_tokens / 1000) * pricing["output_per_1k"]
        return round(input_cost + output_cost, 6)

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "model": self.model,
            "provider": self.provider,
            "feature": self.feature,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "cost_usd": round(self.cost_usd, 6),
            "timestamp": self.timestamp,
            "date": datetime.fromtimestamp(self.timestamp, tz=timezone.utc).strftime("%Y-%m-%d"),
        }


@dataclass
class MonthlyCostReport:
    """Monthly AI cost report."""

    year_month: str  # "2026-07"
    total_cost: float = 0.0
    total_tokens: int = 0
    by_model: dict[str, dict[str, Any]] = field(default_factory=dict)
    by_provider: dict[str, dict[str, Any]] = field(default_factory=dict)
    by_feature: dict[str, dict[str, Any]] = field(default_factory=dict)
    budget_usd: float = MONTHLY_BUDGET_DEFAULT
    budget_used_pct: float = 0.0
    n_records: int = 0
    avg_cost_per_request: float = 0.0
    recommendations: list[str] = field(default_factory=list)
    top_features_by_cost: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "year_month": self.year_month,
            "total_cost": round(self.total_cost, 2),
            "total_tokens": self.total_tokens,
            "budget_usd": self.budget_usd,
            "budget_used_pct": round(self.budget_used_pct, 1),
            "n_records": self.n_records,
            "avg_cost_per_request": round(self.avg_cost_per_request, 4),
            "by_model": {
                m: {
                    "cost": round(d["cost"], 2),
                    "tokens": d["tokens"],
                    "requests": d["requests"],
                    "cost_pct": round(d["cost"] / max(self.total_cost, 0.01) * 100, 1),
                }
                for m, d in sorted(
                    self.by_model.items(), key=lambda x: -x[1]["cost"]
                )
            },
            "by_provider": {
                p: {
                    "cost": round(d["cost"], 2),
                    "tokens": d["tokens"],
                    "requests": d["requests"],
                }
                for p, d in sorted(
                    self.by_provider.items(), key=lambda x: -x[1]["cost"]
                )
            },
            "by_feature": {
                f: {
                    "cost": round(d["cost"], 2),
                    "tokens": d["tokens"],
                    "requests": d["requests"],
                }
                for f, d in sorted(
                    self.by_feature.items(), key=lambda x: -x[1]["cost"]
                )
            },
            "top_features_by_cost": self.top_features_by_cost[:5],
            "recommendations": self.recommendations[:5],
        }


# ── Token Cost Tracker ────────────────────────────────────────────────────


class TokenCostTracker:
    """Tracks AI token usage and costs across models, providers, and features.

    Thread-safe. Persisted to JSON.
    """

    def __init__(
        self,
        monthly_budget: float = MONTHLY_BUDGET_DEFAULT,
    ) -> None:
        self._lock = threading.RLock()
        self._records: list[UsageRecord] = []
        self._max_records = 10_000
        self._monthly_budget = monthly_budget
        self._persist_path = Path("json/ai_token_costs.json")
        self._load_records()

    # ── Recording ────────────────────────────────────────────────────────

    def record_usage(
        self,
        model: str,
        provider: str = "",
        feature: str = "other",
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
    ) -> UsageRecord:
        """Record token usage for an AI call.

        Args:
            model: Model name (e.g., "gpt-4", "claude-3-opus").
            provider: Provider name (auto-detected if not specified).
            feature: Feature category using the tokens.
            prompt_tokens: Number of input/prompt tokens.
            completion_tokens: Number of output/completion tokens.

        Returns:
            UsageRecord with computed cost.
        """
        # Auto-detect provider if not specified
        if not provider:
            pricing = MODEL_PRICING.get(model, DEFAULT_UNKNOWN_MODEL_PRICE)
            provider = pricing["provider"]

        # Validate feature
        if feature not in FEATURE_CATEGORIES:
            feature = "other"

        record = UsageRecord(
            model=model,
            provider=provider,
            feature=feature,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )

        with self._lock:
            self._records.append(record)
            if len(self._records) > self._max_records:
                self._records = self._records[-self._max_records:]
            self._persist()

        _log.debug(
            "[TOKEN_COST] %s | %s | %s | %d tok | $%.6f",
            record.model, record.provider, record.feature,
            record.total_tokens, record.cost_usd,
        )

        # Check budget alert
        monthly = self._get_current_month_records()
        total_cost = sum(r.cost_usd for r in monthly)
        if total_cost > self._monthly_budget:
            _log.warning(
                "[TOKEN_COST] Monthly AI budget exceeded: "
                "$%.2f > $%.2f budget",
                total_cost, self._monthly_budget,
            )

        return record

    def get_pricing(self, model: str) -> dict[str, Any]:
        """Get pricing info for a model."""
        pricing = MODEL_PRICING.get(model, DEFAULT_UNKNOWN_MODEL_PRICE)
        return {
            "model": model,
            "provider": pricing["provider"],
            "input_per_1k": pricing["input_per_1k"],
            "output_per_1k": pricing["output_per_1k"],
            "estimated_cost_per_1k": round(
                (pricing["input_per_1k"] + pricing["output_per_1k"]) / 2, 6
            ),
        }

    def register_custom_pricing(
        self,
        model: str,
        input_per_1k: float,
        output_per_1k: float,
        provider: str = "custom",
    ) -> None:
        """Register custom pricing for a new or existing model."""
        with self._lock:
            MODEL_PRICING[model] = {
                "input_per_1k": input_per_1k,
                "output_per_1k": output_per_1k,
                "provider": provider,
            }

    # ── Reporting ───────────────────────────────────────────────────────

    def get_monthly_report(
        self,
        year: int = 0,
        month: int = 0,
    ) -> MonthlyCostReport:
        """Get cost report for a specific month.

        Args:
            year: Year (default: current year).
            month: Month (default: current month).

        Returns:
            MonthlyCostReport with breakdowns.
        """
        now = datetime.now(timezone.utc)
        year = year or now.year
        month = month or now.month
        year_month = f"{year}-{month:02d}"

        with self._lock:
            records = [
                r for r in self._records
                if datetime.fromtimestamp(r.timestamp, tz=timezone.utc).year == year
                and datetime.fromtimestamp(r.timestamp, tz=timezone.utc).month == month
            ]

        return self._build_report(year_month, records)

    def get_report(
        self,
        days: int = 30,
    ) -> MonthlyCostReport:
        """Get cost report for the last N days."""
        cutoff = time.time() - (days * 86400)
        year_month = datetime.now(timezone.utc).strftime("%Y-%m")

        with self._lock:
            records = [
                r for r in self._records if r.timestamp >= cutoff
            ]

        return self._build_report(year_month, records)

    def get_all_time_report(self) -> MonthlyCostReport:
        """Get all-time cost report."""
        with self._lock:
            return self._build_report("all_time", list(self._records))

    def get_stats(self) -> dict[str, Any]:
        """Get quick statistics."""
        with self._lock:
            total_cost = sum(r.cost_usd for r in self._records)
            total_tokens = sum(r.total_tokens for r in self._records)
            monthly = self._get_current_month_records()
            monthly_cost = sum(r.cost_usd for r in monthly)

            unique_models = set(r.model for r in self._records)
            unique_features = set(r.feature for r in self._records)

            return {
                "total_records": len(self._records),
                "total_cost_usd": round(total_cost, 2),
                "total_tokens": total_tokens,
                "avg_cost_per_token": round(
                    total_cost / max(total_tokens, 1), 8
                ),
                "monthly_cost_usd": round(monthly_cost, 2),
                "monthly_budget_usd": self._monthly_budget,
                "budget_used_pct": round(
                    monthly_cost / max(self._monthly_budget, 0.01) * 100, 1
                ),
                "unique_models": len(unique_models),
                "unique_features": len(unique_features),
                "models": sorted(unique_models),
                "features": sorted(unique_features),
            }

    def get_feature_costs(
        self, days: int = 30
    ) -> list[dict[str, Any]]:
        """Get cost breakdown by feature."""
        report = self.get_report(days=days)
        return sorted(
            [
                {
                    "feature": f,
                    "cost": round(d["cost"], 2),
                    "tokens": d["tokens"],
                    "requests": d["requests"],
                }
                for f, d in report.by_feature.items()
            ],
            key=lambda x: -x["cost"],
        )

    def get_model_costs(
        self, days: int = 30
    ) -> list[dict[str, Any]]:
        """Get cost breakdown by model."""
        report = self.get_report(days=days)
        total = max(report.total_cost, 0.01)
        return sorted(
            [
                {
                    "model": m,
                    "cost": round(d["cost"], 2),
                    "tokens": d["tokens"],
                    "requests": d["requests"],
                    "cost_pct": round(d["cost"] / total * 100, 1),
                }
                for m, d in report.by_model.items()
            ],
            key=lambda x: -x["cost"],
        )

    # ── Budget Management ───────────────────────────────────────────────

    def set_budget(self, monthly_budget_usd: float) -> None:
        """Set the monthly budget for AI token costs."""
        with self._lock:
            self._monthly_budget = monthly_budget_usd

    def get_budget_status(self) -> dict[str, Any]:
        """Get current budget status with alerts."""
        monthly = self._get_current_month_records()
        total_cost = sum(r.cost_usd for r in monthly)
        pct = total_cost / max(self._monthly_budget, 0.01) * 100

        alerts: list[str] = []
        if pct >= 100:
            alerts.append(
                f"CRITICAL: Monthly AI budget exceeded: "
                f"${total_cost:.2f} > ${self._monthly_budget:.2f}"
            )
        elif pct >= 90:
            alerts.append(
                f"WARNING: AI budget at {pct:.0f}% "
                f"(${total_cost:.2f}/${self._monthly_budget:.2f})"
            )
        elif pct >= 75:
            alerts.append(f"INFO: AI budget at {pct:.0f}%")

        return {
            "monthly_budget": self._monthly_budget,
            "current_spend": round(total_cost, 2),
            "budget_used_pct": round(pct, 1),
            "remaining": round(max(0, self._monthly_budget - total_cost), 2),
            "alerts": alerts,
        }

    def get_cost_optimization_recommendations(
        self,
    ) -> list[dict[str, Any]]:
        """Get cost optimization recommendations."""
        recommendations: list[dict[str, Any]] = []
        monthly = self._get_current_month_records()

        # Analyze by model
        model_costs: dict[str, float] = {}
        model_requests: dict[str, int] = {}
        for r in monthly:
            model_costs[r.model] = model_costs.get(r.model, 0.0) + r.cost_usd
            model_requests[r.model] = model_requests.get(r.model, 0) + 1

        total_cost = sum(model_costs.values())

        for model, cost in sorted(
            model_costs.items(), key=lambda x: -x[1]
        ):
            pct = cost / max(total_cost, 0.01) * 100
            if pct > 30:
                # Check if there's a cheaper alternative
                pricing = MODEL_PRICING.get(model, {})
                provider = pricing.get("provider", "unknown")

                # Find cheapest model from same provider
                cheaper = [
                    (m, p["input_per_1k"] + p["output_per_1k"])
                    for m, p in MODEL_PRICING.items()
                    if p.get("provider") == provider
                    and (p["input_per_1k"] + p["output_per_1k"])
                    < (pricing.get("input_per_1k", 1) + pricing.get("output_per_1k", 1))
                ]
                if cheaper:
                    cheapest = min(cheaper, key=lambda x: x[1])
                    potential_savings = (
                        cost
                        - cost * cheapest[1]
                        / max(
                            pricing.get("input_per_1k", 1)
                            + pricing.get("output_per_1k", 1),
                            0.01,
                        )
                    )
                    if potential_savings > 1.0:
                        recommendations.append({
                            "type": "model_optimization",
                            "current_model": model,
                            "suggested_model": cheapest[0],
                            "current_cost": round(cost, 2),
                            "estimated_savings": round(potential_savings, 2),
                            "savings_pct": round(
                                potential_savings / max(cost, 0.01) * 100, 1
                            ),
                            "action": (
                                f"Switch from {model} to {cheapest[0]} "
                                f"to save ~${potential_savings:.0f}/month"
                            ),
                        })

        # Feature-level optimization
        feature_costs: dict[str, float] = {}
        for r in monthly:
            feature_costs[r.feature] = (
                feature_costs.get(r.feature, 0.0) + r.cost_usd
            )

        for feature, cost in sorted(
            feature_costs.items(), key=lambda x: -x[1]
        ):
            pct = cost / max(total_cost, 0.01) * 100
            if pct > 20:
                recommendations.append({
                    "type": "feature_cost",
                    "feature": feature,
                    "cost": round(cost, 2),
                    "cost_pct": round(pct, 1),
                    "action": (
                        f"Feature '{feature}' consumes {pct:.0f}% of AI budget "
                        f"(${cost:.2f}) — consider caching or using cheaper model"
                    ),
                })

        return recommendations

    def clear_records(self) -> None:
        """Clear all records (for testing)."""
        with self._lock:
            self._records.clear()
            if self._persist_path.exists():
                self._persist_path.unlink()

    # ── Internal ────────────────────────────────────────────────────────

    def _get_current_month_records(self) -> list[UsageRecord]:
        """Get records for the current month."""
        now = datetime.now(timezone.utc)
        return [
            r for r in self._records
            if datetime.fromtimestamp(r.timestamp, tz=timezone.utc).year == now.year
            and datetime.fromtimestamp(r.timestamp, tz=timezone.utc).month == now.month
        ]

    def _build_report(
        self,
        year_month: str,
        records: list[UsageRecord],
    ) -> MonthlyCostReport:
        """Build a cost report from records."""
        if not records:
            return MonthlyCostReport(year_month=year_month)

        total_cost = sum(r.cost_usd for r in records)
        total_tokens = sum(r.total_tokens for r in records)

        # By model
        by_model: dict[str, dict[str, Any]] = {}
        for r in records:
            if r.model not in by_model:
                by_model[r.model] = {"cost": 0.0, "tokens": 0, "requests": 0}
            by_model[r.model]["cost"] += r.cost_usd
            by_model[r.model]["tokens"] += r.total_tokens
            by_model[r.model]["requests"] += 1

        # By provider
        by_provider: dict[str, dict[str, Any]] = {}
        for r in records:
            if r.provider not in by_provider:
                by_provider[r.provider] = {"cost": 0.0, "tokens": 0, "requests": 0}
            by_provider[r.provider]["cost"] += r.cost_usd
            by_provider[r.provider]["tokens"] += r.total_tokens
            by_provider[r.provider]["requests"] += 1

        # By feature
        by_feature: dict[str, dict[str, Any]] = {}
        for r in records:
            if r.feature not in by_feature:
                by_feature[r.feature] = {"cost": 0.0, "tokens": 0, "requests": 0}
            by_feature[r.feature]["cost"] += r.cost_usd
            by_feature[r.feature]["tokens"] += r.total_tokens
            by_feature[r.feature]["requests"] += 1

        # Top features
        top_features = sorted(
            [
                {
                    "feature": f,
                    "cost": round(d["cost"], 2),
                    "tokens": d["tokens"],
                    "requests": d["requests"],
                }
                for f, d in by_feature.items()
            ],
            key=lambda x: -x["cost"],
        )

        # Recommendations
        recommendations = [
            f"Total AI cost: ${total_cost:.2f} for {total_tokens:,} tokens"
        ]
        if total_cost > self._monthly_budget:
            recommendations.append(
                f"Monthly budget of ${self._monthly_budget:.2f} exceeded!"
            )

        # Check for model concentration risk
        for model, data in by_model.items():
            pct = data["cost"] / max(total_cost, 0.01) * 100
            if pct > 50:
                recommendations.append(
                    f"High concentration on {model} ({pct:.0f}% of cost) — "
                    f"consider diversifying"
                )

        return MonthlyCostReport(
            year_month=year_month,
            total_cost=total_cost,
            total_tokens=total_tokens,
            by_model=by_model,
            by_provider=by_provider,
            by_feature=by_feature,
            budget_usd=self._monthly_budget,
            budget_used_pct=total_cost / max(self._monthly_budget, 0.01) * 100,
            n_records=len(records),
            avg_cost_per_request=total_cost / max(len(records), 1),
            recommendations=recommendations,
            top_features_by_cost=top_features,
        )

    # ── Persistence ─────────────────────────────────────────────────────

    def _persist(self) -> None:
        """Persist records to JSON."""
        try:
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)
            data = [r.to_dict() for r in self._records[-1000:]]
            self._persist_path.write_text(
                json.dumps(data, indent=2), encoding="utf-8"
            )
        except (OSError, ValueError) as exc:
            _log.debug("[TOKEN_COST] Persist error: %s", exc)

    def _load_records(self) -> None:
        """Load records from JSON."""
        try:
            if self._persist_path.is_file():
                data = json.loads(
                    self._persist_path.read_text(encoding="utf-8")
                )
                for item in data:
                    try:
                        self._records.append(UsageRecord(**{
                            k: v for k, v in item.items()
                            if k in UsageRecord.__dataclass_fields__
                        }))
                    except (TypeError, ValueError, KeyError) as exc:
                        _log.debug(
                            "[TOKEN_COST] Load skip: %s", exc
                        )
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            _log.debug("[TOKEN_COST] Load error: %s", exc)


# ── CLI ────────────────────────────────────────────────────────────────────


def _cli() -> None:
    import argparse

    ap = argparse.ArgumentParser(
        prog="python -m core.ai_token_cost_tracker",
        description="AI Token Cost Tracker — Monitor AI spending",
    )
    ap.add_argument("--stats", action="store_true", help="Show cost statistics")
    ap.add_argument("--report", type=int, default=0, nargs="?",
                    help="Show report for last N days (default: 30)")
    ap.add_argument("--monthly", action="store_true", help="Show monthly report")
    ap.add_argument("--optimize", action="store_true",
                    help="Get cost optimization recommendations")
    ap.add_argument("--record", type=str,
                    help="Record usage: model:feature:prompt_tokens:completion_tokens")
    ap.add_argument("--json", action="store_true", help="Output as JSON")
    args = ap.parse_args()

    tracker = get_token_cost_tracker()

    if args.record:
        parts = args.record.split(":")
        if len(parts) < 4:
            print("Usage: model:feature:prompt_tokens:completion_tokens")
            return
        model, feature, prompt_str, completion_str = parts[:4]
        record = tracker.record_usage(
            model=model,
            feature=feature,
            prompt_tokens=int(prompt_str),
            completion_tokens=int(completion_str),
        )
        if args.json:
            import json
            print(json.dumps(record.to_dict(), indent=2))
        else:
            print(f"Recorded: {record.model} | {record.feature} | "
                  f"{record.total_tokens} tokens | ${record.cost_usd:.6f}")
        return

    if args.stats:
        stats = tracker.get_stats()
        if args.json:
            import json
            print(json.dumps(stats, indent=2))
        else:
            print(f"Total records: {stats['total_records']}")
            print(f"Total cost: ${stats['total_cost_usd']:.2f}")
            print(f"Total tokens: {stats['total_tokens']:,}")
            print(f"Monthly cost: ${stats['monthly_cost_usd']:.2f}")
            print(f"Monthly budget: ${stats['monthly_budget_usd']:.2f}")
            print(f"Budget used: {stats['budget_used_pct']}%")
            print(f"Unique models: {stats['unique_models']}")
            print(f"Unique features: {stats['unique_features']}")
        return

    if args.report is not None:
        days = args.report if args.report > 0 else 30
        report = tracker.get_report(days=days)
        if args.json:
            import json
            print(json.dumps(report.to_dict(), indent=2))
        else:
            print(f"AI Cost Report — Last {days} days")
            print(f"Total cost: ${report.total_cost:.2f}")
            print(f"Total tokens: {report.total_tokens:,}")
            print("By model:")
            for m, d in sorted(report.by_model.items(),
                               key=lambda x: -x[1]["cost"]):
                print(f"  {m}: ${d['cost']:.2f} ({d['tokens']:,} tok, "
                      f"{d['requests']} req)")
        return

    if args.monthly:
        report = tracker.get_monthly_report()
        if args.json:
            import json
            print(json.dumps(report.to_dict(), indent=2))
        else:
            print(f"Monthly AI Cost Report — {report.year_month}")
            print(f"Total: ${report.total_cost:.2f} | "
                  f"Budget: ${report.budget_usd:.2f} | "
                  f"Used: {report.budget_used_pct:.1f}%")
            print(f"Total tokens: {report.total_tokens:,}")
            print("\nBy Model:")
            for m, d in sorted(report.by_model.items(),
                               key=lambda x: -x[1]["cost"]):
                print(f"  {m}: ${d['cost']:.2f} ({d['cost_pct']:.1f}%)")
        return

    if args.optimize:
        recs = tracker.get_cost_optimization_recommendations()
        if args.json:
            import json
            print(json.dumps(recs, indent=2))
        else:
            print("Cost Optimization Recommendations:")
            if not recs:
                print("  No optimizations found.")
            for r in recs:
                print(f"  → {r['action']}")
        return

    ap.print_help()


if __name__ == "__main__":
    _cli()


# ── Singleton ──────────────────────────────────────────────────────────────

_instance: TokenCostTracker | None = None
_instance_lock = threading.RLock()


def get_token_cost_tracker(
    monthly_budget: float = MONTHLY_BUDGET_DEFAULT,
) -> TokenCostTracker:
    """Get the singleton TokenCostTracker instance."""
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = TokenCostTracker(monthly_budget=monthly_budget)
        return _instance


def reset_token_cost_tracker() -> None:
    """Force-reset singleton (for testing)."""
    global _instance
    with _instance_lock:
        _instance = None


__all__ = [
    "TokenCostTracker",
    "UsageRecord",
    "MonthlyCostReport",
    "get_token_cost_tracker",
    "reset_token_cost_tracker",
]
