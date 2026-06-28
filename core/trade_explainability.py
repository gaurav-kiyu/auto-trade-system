"""
Trade Explainability Engine (Master Prompt Phase 13).

Generates post-trade explanations in both JSON and PDF formats, wrapping:
  - core/report_generator.py  → PDF trade reports (ReportLab)
  - core/nlp_journal.py       → Narrative explanations (Claude API)

Usage:
    from core.trade_explainability import TradeExplainability, trade_explanation_dir

    te = TradeExplainability()
    result = te.explain_trade(trade_id=42)
    print(result.narrative)
    print(f"Explanation saved to {result.json_path}")
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.datetime_ist import now_ist

_log = logging.getLogger(__name__)

# Default output directory for trade explanations
TRADE_EXPLANATION_DIR = Path("trade_explanations")


@dataclass
class TradeExplanation:
    """A structured explanation of a single trade.

    Attributes:
        trade_id: Trade identifier from the trade log.
        narrative: Human-readable narrative (from NLP journal or generated).
        metrics: Key trade metrics (PnL, return%, holding period, etc.).
        summary: One-line summary suitable for dashboard display.
        json_path: Path to the saved JSON explanation file.
        pdf_path: Path to the saved PDF explanation file (if generated).
        timestamp: When this explanation was generated.
        metadata: Additional context (strategy, index, regime, etc.).
    """
    trade_id: int
    narrative: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)
    summary: str = ""
    json_path: str = ""
    pdf_path: str = ""
    timestamp: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON-compatible dict."""
        return {
            "trade_id": self.trade_id,
            "narrative": self.narrative,
            "metrics": self.metrics,
            "summary": self.summary,
            "json_path": self.json_path,
            "pdf_path": self.pdf_path,
            "timestamp": self.timestamp or str(now_ist()),
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TradeExplanation:
        """Deserialize from dict."""
        return cls(
            trade_id=int(data.get("trade_id", 0)),
            narrative=str(data.get("narrative", "")),
            metrics=dict(data.get("metrics", {})),
            summary=str(data.get("summary", "")),
            json_path=str(data.get("json_path", "")),
            pdf_path=str(data.get("pdf_path", "")),
            timestamp=str(data.get("timestamp", "")),
            metadata=dict(data.get("metadata", {})),
        )


class TradeExplainability:
    """Post-trade explainability engine.

    Generates structured trade explanations in JSON (for machine consumption)
    and PDF (for human review). Delegates heavy lifting to existing modules:

      - ``core.report_generator.generate_pdf_report``  → PDF reports
      - ``core.nlp_journal.generate_trade_narrative``   → NLP narratives

    Explanation files are saved to ``trade_explanations/`` by default.
    """

    def __init__(self, output_dir: str | Path | None = None):
        """Initialize the explainability engine.

        Args:
            output_dir: Directory for explanation output files.
                        Defaults to ``trade_explanations/``.
        """
        self._output_dir = Path(output_dir or TRADE_EXPLANATION_DIR)
        self._output_dir.mkdir(parents=True, exist_ok=True)

    # ── Core explainability ──────────────────────────────────────────────

    def explain_trade(
        self,
        trade_id: int,
        trade_data: dict[str, Any] | None = None,
        generate_pdf: bool = False,
        generate_narrative: bool = True,
    ) -> TradeExplanation:
        """Generate a complete explanation for a single trade.

        Args:
            trade_id:   Trade ID from the trade log DB.
            trade_data: Optional pre-loaded trade data dict. If omitted,
                        the engine attempts to load from the trade log.
            generate_pdf:   Whether to also generate a PDF report.
            generate_narrative: Whether to generate an NLP narrative.

        Returns:
            A TradeExplanation with narrative, metrics, and file paths.
        """
        ts = str(now_ist())

        # 1. Load trade data if not provided
        if trade_data is None:
            trade_data = self._load_trade_data(trade_id)

        # 2. Compute key metrics
        metrics = self._compute_metrics(trade_data)

        # 3. Generate one-line summary
        summary = self._build_summary(trade_id, metrics)

        # 4. Generate NLP narrative
        narrative = ""
        if generate_narrative:
            narrative = self._generate_narrative(trade_id, trade_data, metrics)

        # 5. Build metadata
        metadata = {
            "trade_id": trade_id,
            "index": str(trade_data.get("index", "")),
            "direction": str(trade_data.get("direction", "")),
            "regime": str(trade_data.get("regime", "")),
            "strategy": str(trade_data.get("strategy", "")),
            "generated_at": ts,
        }

        # 6. Save JSON explanation
        json_path = str(self._save_json(trade_id, {
            "trade_id": trade_id,
            "timestamp": ts,
            "summary": summary,
            "narrative": narrative,
            "metrics": metrics,
            "metadata": metadata,
            "pdf_path": "",
        }))

        # 7. Generate PDF if requested
        pdf_path = ""
        if generate_pdf:
            pdf_path = str(self._generate_pdf(trade_id, trade_data, metrics))

        return TradeExplanation(
            trade_id=trade_id,
            narrative=narrative,
            metrics=metrics,
            summary=summary,
            json_path=json_path,
            pdf_path=pdf_path,
            timestamp=ts,
            metadata=metadata,
        )

    # ── Batch explanation ────────────────────────────────────────────────

    def explain_recent_trades(
        self,
        count: int = 10,
        generate_pdf: bool = False,
        include_narrative: bool = True,
    ) -> list[TradeExplanation]:
        """Explain the most recent trades.

        Args:
            count: Number of recent trades to explain.
            generate_pdf: Whether to generate PDF for each.
            include_narrative: Whether to include NLP narratives.

        Returns:
            List of TradeExplanation objects, newest first.
        """
        recent = self._load_recent_trades(count)
        explanations: list[TradeExplanation] = []
        for trade in recent:
            tid = int(trade.get("trade_id", 0))
            if tid > 0:
                exp = self.explain_trade(
                    trade_id=tid,
                    trade_data=trade,
                    generate_pdf=generate_pdf,
                    generate_narrative=include_narrative,
                )
                explanations.append(exp)
        return explanations

    def generate_trade_explanation_report(
        self,
        explanations: list[TradeExplanation],
        output_name: str = "trade_explanation_report",
    ) -> dict[str, Any]:
        """Generate a consolidated report from multiple trade explanations.

        Args:
            explanations: List of TradeExplanation objects.
            output_name: Base name for output files.

        Returns:
            Dict with ``json_path`` and optionally ``pdf_path``.
        """
        report = {
            "generated_at": str(now_ist()),
            "total_trades": len(explanations),
            "explanations": [e.to_dict() for e in explanations],
            "aggregate_metrics": self._aggregate_metrics(explanations),
        }
        json_path = self._output_dir / f"{output_name}.json"
        json_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        _log.info("Trade explanation report saved to %s", json_path)
        return {"json_path": str(json_path), "pdf_path": ""}

    # ── Internal helpers ─────────────────────────────────────────────────

    def _load_trade_data(self, trade_id: int) -> dict[str, Any]:
        """Load trade data from the trade log database.

        Falls back to empty dict if loading fails.
        """
        try:
            import sqlite3
            from pathlib import Path

            db_path = Path("trades.db")
            if not db_path.exists():
                _log.warning("Trade DB not found at %s", db_path)
                return {"trade_id": trade_id}

            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM trades WHERE trade_id = ?",
                (trade_id,),
            )
            row = cursor.fetchone()
            conn.close()

            if row:
                return dict(row)
            _log.warning("Trade %d not found in DB", trade_id)
            return {"trade_id": trade_id}
        except Exception as e:
            _log.warning("Failed to load trade %d: %s", trade_id, e)
            return {"trade_id": trade_id}

    def _load_recent_trades(self, count: int = 10) -> list[dict[str, Any]]:
        """Load recent trades from the trade log."""
        try:
            import sqlite3
            from pathlib import Path

            db_path = Path("trades.db")
            if not db_path.exists():
                return []

            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM trades ORDER BY trade_id DESC LIMIT ?",
                (count,),
            )
            rows = [dict(r) for r in cursor.fetchall()]
            conn.close()
            return rows
        except Exception as e:
            _log.warning("Failed to load recent trades: %s", e)
            return []

    def _compute_metrics(self, trade_data: dict[str, Any]) -> dict[str, Any]:
        """Compute key trade metrics from raw trade data."""
        entry_price = self._safe_float(trade_data.get("entry_price", 0))
        exit_price = self._safe_float(trade_data.get("exit_price", 0))
        quantity = self._safe_float(trade_data.get("quantity", 0))
        direction = str(trade_data.get("direction", ""))

        pnl = (exit_price - entry_price) * quantity if direction.upper() == "LONG" \
            else (entry_price - exit_price) * quantity

        return_pct = 0.0
        if entry_price > 0:
            if direction.upper() == "LONG":
                return_pct = (exit_price - entry_price) / entry_price * 100
            else:
                return_pct = (entry_price - exit_price) / entry_price * 100

        return {
            "entry_price": entry_price,
            "exit_price": exit_price,
            "quantity": quantity,
            "direction": direction,
            "pnl": pnl,
            "return_pct": round(return_pct, 2),
            "entry_time": str(trade_data.get("entry_time", "")),
            "exit_time": str(trade_data.get("exit_time", "")),
        }

    def _build_summary(self, trade_id: int, metrics: dict[str, Any]) -> str:
        """Build a one-line summary from metrics."""
        direction = metrics.get("direction", "").upper()
        pnl = metrics.get("pnl", 0.0)
        ret = metrics.get("return_pct", 0.0)
        emoji = "🟢" if pnl >= 0 else "🔴"
        return (
            f"{emoji} Trade #{trade_id}: {direction} {emoji} "
            f"PnL={pnl:+.2f} ({ret:+.2f}%) "
        )

    def _generate_narrative(
        self,
        trade_id: int,
        trade_data: dict[str, Any],
        metrics: dict[str, Any],
    ) -> str:
        """Generate an NLP narrative for the trade.

        Attempts to use the NLP journal module. Falls back to a
        template-based narrative if the module is unavailable.
        """
        try:
            from core.nlp_journal import generate_trade_narrative
            narrative = generate_trade_narrative(
                trade_id=trade_id,
                trade_data=trade_data,
                metrics=metrics,
            )
            return narrative or self._template_narrative(trade_id, metrics)
        except ImportError:
            _log.info("nlp_journal not available; using template narrative")
        except Exception as e:
            _log.warning("NLP narrative failed: %s", e)
        return self._template_narrative(trade_id, metrics)

    def _template_narrative(self, trade_id: int, metrics: dict[str, Any]) -> str:
        """Generate a simple template-based narrative."""
        direction = metrics.get("direction", "").upper()
        pnl = metrics.get("pnl", 0.0)
        ret = metrics.get("return_pct", 0.0)
        entry_px = metrics.get("entry_price", 0.0)
        exit_px = metrics.get("exit_price", 0.0)

        sentiment = "profitable" if pnl >= 0 else "loss-making"
        return (
            f"Trade #{trade_id}: {direction} position entered at {entry_px:.2f} "
            f"and exited at {exit_px:.2f}, yielding a {sentiment} outcome "
            f"of {pnl:+.2f} ({ret:+.2f}%)."
        )

    def _generate_pdf(
        self,
        trade_id: int,
        trade_data: dict[str, Any],
        metrics: dict[str, Any],
    ) -> Path:
        """Generate a PDF explanation for a single trade.

        Delegates to core.report_generator for PDF layout.
        Falls back to a simple text PDF if the module is unavailable.
        """
        try:
            from core.report_generator import generate_pdf_report

            pdf_path = self._output_dir / f"trade_{trade_id}_explanation.pdf"
            generate_pdf_report(
                trade_data=trade_data,
                metrics=metrics,
                output_path=str(pdf_path),
                title=f"Trade #{trade_id} Explanation",
            )
            _log.info("PDF explanation saved to %s", pdf_path)
            return pdf_path
        except ImportError:
            _log.info("report_generator not available; skipping PDF for trade %d", trade_id)
        except Exception as e:
            _log.warning("PDF generation failed for trade %d: %s", trade_id, e)
        return self._output_dir / f"trade_{trade_id}_explanation.pdf"

    def _save_json(self, trade_id: int, data: dict[str, Any]) -> Path:
        """Save trade explanation as a JSON file."""
        json_path = self._output_dir / f"trade_{trade_id}_explanation.json"
        json_path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
        _log.info("JSON explanation saved to %s", json_path)
        return json_path

    @staticmethod
    def _safe_float(value: Any) -> float:
        """Safely convert a value to float."""
        try:
            return float(value) if value is not None else 0.0
        except (ValueError, TypeError):
            return 0.0

    @staticmethod
    def _aggregate_metrics(explanations: list[TradeExplanation]) -> dict[str, Any]:
        """Compute aggregate metrics across multiple explanations."""
        total_pnl = sum(e.metrics.get("pnl", 0.0) for e in explanations)
        wins = sum(1 for e in explanations if e.metrics.get("pnl", 0.0) > 0)
        losses = sum(1 for e in explanations if e.metrics.get("pnl", 0.0) < 0)
        total = len(explanations)
        return {
            "total_trades": total,
            "total_pnl": round(total_pnl, 2),
            "win_count": wins,
            "loss_count": losses,
            "win_rate": round(wins / total * 100, 1) if total > 0 else 0.0,
            "avg_pnl_per_trade": round(total_pnl / total, 2) if total > 0 else 0.0,
        }


# ── Convenience accessors ────────────────────────────────────────────────────


def get_explainability_engine(output_dir: str | Path | None = None) -> TradeExplainability:
    """Get a configured TradeExplainability instance.

    Args:
        output_dir: Optional custom output directory.

    Returns:
        TradeExplainability instance.
    """
    return TradeExplainability(output_dir=output_dir)


__all__ = [
    "TradeExplanation",
    "TradeExplainability",
    "get_explainability_engine",
    "TRADE_EXPLANATION_DIR",
]
