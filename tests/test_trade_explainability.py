"""Tests for core/trade_explainability.py - Trade Explainability Engine."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from core.trade_explainability import (
    TRADE_EXPLANATION_DIR,
    TradeExplainability,
    TradeExplanation,
    get_explainability_engine,
)


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def tmp_output(tmp_path: Path) -> Path:
    """Temporary output directory."""
    return tmp_path / "trade_explanations"


@pytest.fixture
def engine(tmp_output: Path) -> TradeExplainability:
    """TradeExplainability with temp output dir."""
    return TradeExplainability(output_dir=tmp_output)


# ── TradeExplanation dataclass tests ─────────────────────────────────────────


class TestTradeExplanation:
    """Tests for TradeExplanation dataclass."""

    def test_to_dict(self):
        exp = TradeExplanation(
            trade_id=42,
            narrative="Test narrative",
            metrics={"pnl": 100.0},
            summary="+100.00 profit",
            json_path="/tmp/ex.json",
            pdf_path="/tmp/ex.pdf",
            timestamp="2026-01-01T00:00:00",
            metadata={"index": "NIFTY"},
        )
        d = exp.to_dict()
        assert d["trade_id"] == 42
        assert d["narrative"] == "Test narrative"
        assert d["metrics"]["pnl"] == 100.0
        assert d["summary"] == "+100.00 profit"
        assert d["pdf_path"] == "/tmp/ex.pdf"

    def test_from_dict(self):
        d = {
            "trade_id": "99",
            "narrative": "Great trade",
            "metrics": {"pnl": 250.0, "return_pct": 5.0},
            "summary": "+250.00",
            "json_path": "/tmp/t99.json",
            "pdf_path": "",
            "timestamp": "2026-06-01T10:00:00",
            "metadata": {"direction": "LONG"},
        }
        exp = TradeExplanation.from_dict(d)
        assert exp.trade_id == 99
        assert exp.narrative == "Great trade"
        assert exp.metrics["pnl"] == 250.0
        assert exp.metadata["direction"] == "LONG"

    def test_from_dict_empty(self):
        exp = TradeExplanation.from_dict({})
        assert exp.trade_id == 0
        assert exp.narrative == ""

    def test_default_timestamp(self):
        exp = TradeExplanation(trade_id=1)
        d = exp.to_dict()
        assert d["timestamp"]  # Should have a non-empty timestamp


# ── TradeExplainability engine tests ─────────────────────────────────────────


class TestTradeExplainability:
    """Tests for TradeExplainability engine."""

    def test_init_creates_output_dir(self, tmp_output: Path):
        assert not tmp_output.exists()
        TradeExplainability(output_dir=tmp_output)
        assert tmp_output.exists()
        assert tmp_output.is_dir()

    def test_init_default_dir(self):
        engine = TradeExplainability()
        assert engine._output_dir == TRADE_EXPLANATION_DIR

    def test_template_narrative(self, engine: TradeExplainability):
        metrics = {
            "direction": "LONG",
            "pnl": 150.0,
            "return_pct": 3.5,
            "entry_price": 100.0,
            "exit_price": 103.5,
        }
        narrative = engine._template_narrative(42, metrics)
        assert "Trade #42" in narrative
        assert "LONG" in narrative
        assert "profitable" in narrative
        assert "150.00" in narrative

    def test_template_narrative_loss(self, engine: TradeExplainability):
        metrics = {
            "direction": "SHORT",
            "pnl": -200.0,
            "return_pct": -4.0,
            "entry_price": 50.0,
            "exit_price": 52.0,
        }
        narrative = engine._template_narrative(7, metrics)
        assert "loss-making" in narrative
        assert "-200.00" in narrative

    def test_build_summary_profit(self, engine: TradeExplainability):
        metrics = {"direction": "LONG", "pnl": 100.0, "return_pct": 5.0}
        summary = engine._build_summary(1, metrics)
        assert "Trade #1" in summary
        assert "+100" in summary
        assert "+5" in summary

    def test_build_summary_loss(self, engine: TradeExplainability):
        metrics = {"direction": "SHORT", "pnl": -50.0, "return_pct": -2.5}
        summary = engine._build_summary(5, metrics)
        assert "-50" in summary
        assert "-2.5" in summary

    def test_safe_float_valid(self):
        assert TradeExplainability._safe_float(42.5) == 42.5
        assert TradeExplainability._safe_float("10.5") == 10.5
        assert TradeExplainability._safe_float(None) == 0.0
        assert TradeExplainability._safe_float("invalid") == 0.0

    def test_compute_metrics_long(self, engine: TradeExplainability):
        trade = {
            "direction": "LONG",
            "entry_price": 100.0,
            "exit_price": 110.0,
            "quantity": 10,
        }
        m = engine._compute_metrics(trade)
        assert m["pnl"] == 100.0  # (110-100) * 10
        assert m["return_pct"] == 10.0
        assert m["direction"] == "LONG"

    def test_compute_metrics_short(self, engine: TradeExplainability):
        trade = {
            "direction": "SHORT",
            "entry_price": 100.0,
            "exit_price": 90.0,
            "quantity": 5,
        }
        m = engine._compute_metrics(trade)
        assert m["pnl"] == 50.0  # (100-90) * 5
        assert m["return_pct"] == 10.0

    def test_compute_metrics_loss(self, engine: TradeExplainability):
        trade = {
            "direction": "LONG",
            "entry_price": 100.0,
            "exit_price": 80.0,
            "quantity": 5,
        }
        m = engine._compute_metrics(trade)
        assert m["pnl"] == -100.0  # (80-100) * 5
        assert m["return_pct"] == -20.0

    def test_save_json(self, engine: TradeExplainability, tmp_output: Path):
        data = {"trade_id": 1, "summary": "test"}
        path = engine._save_json(1, data)
        assert path.exists()
        loaded = json.loads(path.read_text(encoding="utf-8"))
        assert loaded["trade_id"] == 1
        assert loaded["summary"] == "test"

    @patch("core.trade_explainability.TradeExplainability._load_trade_data")
    def test_explain_trade_no_db(self, mock_load, engine: TradeExplainability):
        mock_load.return_value = {
            "trade_id": 42,
            "direction": "LONG",
            "entry_price": 100.0,
            "exit_price": 105.0,
            "quantity": 10,
            "index": "NIFTY",
            "strategy": "TestStrat",
        }
        result = engine.explain_trade(
            trade_id=42,
            trade_data=None,
            generate_pdf=False,
            generate_narrative=True,
        )
        assert isinstance(result, TradeExplanation)
        assert result.trade_id == 42
        assert result.metrics["pnl"] == 50.0
        assert result.summary
        assert result.narrative
        assert result.json_path
        assert Path(result.json_path).exists()

    @patch("core.trade_explainability.TradeExplainability._load_trade_data")
    def test_explain_trade_with_pdf(self, mock_load, engine: TradeExplainability):
        mock_load.return_value = {
            "trade_id": 7,
            "direction": "SHORT",
            "entry_price": 200.0,
            "exit_price": 180.0,
            "quantity": 1,
        }
        result = engine.explain_trade(
            trade_id=7,
            generate_pdf=True,
            generate_narrative=False,
        )
        assert result.trade_id == 7
        assert result.metrics["pnl"] == 20.0  # (200-180)*1
        assert not result.narrative  # Narrative disabled
        # PDF may be placeholder if report_generator unavailable
        assert result.pdf_path

    def test_aggregate_metrics(self):
        exps = [
            TradeExplanation(trade_id=1, metrics={"pnl": 100.0}),
            TradeExplanation(trade_id=2, metrics={"pnl": -50.0}),
            TradeExplanation(trade_id=3, metrics={"pnl": 200.0}),
            TradeExplanation(trade_id=4, metrics={"pnl": 0.0}),
        ]
        agg = TradeExplainability._aggregate_metrics(exps)
        assert agg["total_trades"] == 4
        assert agg["total_pnl"] == 250.0
        assert agg["win_count"] == 2
        assert agg["loss_count"] == 1
        assert agg["win_rate"] == 50.0
        assert agg["avg_pnl_per_trade"] == 62.5

    def test_generate_trade_explanation_report(
        self, engine: TradeExplainability, tmp_output: Path
    ):
        exps = [
            TradeExplanation(trade_id=1, metrics={"pnl": 100.0}),
            TradeExplanation(trade_id=2, metrics={"pnl": -50.0}),
        ]
        report = engine.generate_trade_explanation_report(exps, "test_report")
        assert "json_path" in report
        json_path = Path(report["json_path"])
        assert json_path.exists()
        data = json.loads(json_path.read_text(encoding="utf-8"))
        assert data["total_trades"] == 2
        assert len(data["explanations"]) == 2

    def test_explain_recent_trades_no_db(self, engine: TradeExplainability):
        results = engine.explain_recent_trades(count=5)
        # Should return empty list since no trades.db exists
        assert isinstance(results, list)

    @patch("core.trade_explainability.TradeExplainability._load_recent_trades")
    def test_explain_recent_trades_with_data(self, mock_load, engine: TradeExplainability):
        mock_load.return_value = [
            {"trade_id": 1, "direction": "LONG", "entry_price": 100, "exit_price": 110, "quantity": 1},
            {"trade_id": 2, "direction": "SHORT", "entry_price": 50, "exit_price": 45, "quantity": 2},
        ]
        results = engine.explain_recent_trades(count=2, include_narrative=True)
        assert len(results) == 2
        assert results[0].trade_id == 1
        assert results[1].trade_id == 2

    def test_load_trade_data_no_db(self, engine: TradeExplainability):
        data = engine._load_trade_data(42)
        assert isinstance(data, dict)
        assert data.get("trade_id") == 42  # fallback when no DB

    def test_get_explainability_engine(self, tmp_output: Path):
        engine = get_explainability_engine(tmp_output)
        assert isinstance(engine, TradeExplainability)
        assert engine._output_dir == tmp_output
