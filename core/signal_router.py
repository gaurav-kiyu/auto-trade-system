"""
Signal Router — distributes approved signals to Telegram, execution, and dashboard.

Execution path (auto mode):
    OLD: only "STRONG" class → execution_fn()
    NEW: ExecutionPolicy.apply() → decision.trade → execution_fn()

This means MODERATE signals can now trigger auto-execution at reduced size,
WEAK signals can trigger if trade_weak=True, and STRONG signals at full size.
The router never needs to know tier boundaries — ExecutionPolicy owns that logic.
"""

import logging
import threading
from collections.abc import Callable
from typing import Any

from core.execution_policy import ExecutionDecision, ExecutionPolicy, enrich_signal_with_policy

log = logging.getLogger("signal_router")


class SignalRouter:
    """
    Distributes approved signals to respective outputs (Telegram, Execution, Dashboard).
    Uses ExecutionPolicy for all execution gating — no hardcoded tier rules here.
    """

    def __init__(
        self,
        config: dict[str, Any],
        telegram_fn: Callable[[dict], None],
        execution_fn: Callable[[dict], None],
        dashboard_fn: Callable[[dict], None],
        max_lots: int = 1,
        capital: float = 100_000.0,
    ):
        self.config    = config
        self.telegram_fn  = telegram_fn
        self.execution_fn = execution_fn
        self.dashboard_fn = dashboard_fn
        self.max_lots  = max_lots
        self.capital   = capital

    def route(
        self,
        decision: dict[str, Any],
        risk_status: dict[str, Any],
        raw_signal_data: dict[str, Any],
    ) -> ExecutionDecision | None:
        """
        Route the signal.

        Returns:
            ExecutionDecision if an execution was attempted, else None.
        """
        # ── Dashboard always receives everything ─────────────────────────
        self.dashboard_fn({
            "symbol":   raw_signal_data.get("symbol", "UNKNOWN"),
            "decision": decision,
            "risk":     risk_status,
            "raw":      raw_signal_data,
        })

        # ── Not eligible (WATCH / below threshold) → no Telegram, no exec
        if not decision.get("eligible", False):
            return None

        # ── Evaluate execution policy (tier + regime + quality) ──────────
        regime = str(
            raw_signal_data.get("mkt_regime")
            or raw_signal_data.get("regime")
            or "NEUTRAL"
        )
        exec_decision = ExecutionPolicy.apply(
            signal=raw_signal_data,
            config=self.config,
            regime=regime,
            max_lots=self.max_lots,
            capital=self.capital,
        )

        # Enrich raw signal with execution metadata (for Telegram formatting)
        enriched = enrich_signal_with_policy(raw_signal_data, self.config, self.max_lots, self.capital)

        # ── Telegram: EARLY and STRONG both get alerts ───────────────────
        tg_payload = self._format_telegram_payload(enriched, decision, risk_status, exec_decision)
        self.telegram_fn(tg_payload)

        # ── Auto-mode execution ───────────────────────────────────────────
        # ARCHITECTURE NOTE: This gate (config["features"]["enable_auto"]) is the
        # STOCK app auto-execution switch.  The INDEX app controls auto-execution
        # via EXECUTION_MODE / MANUAL_SIGNALS_ONLY in index_trader.py.  These are
        # two independent gates on different code paths.  Do NOT share this router
        # across both paths without reconciling them into a single authority.
        features  = self.config.get("features", {})
        auto_mode = features.get("enable_auto", False)

        if auto_mode and risk_status.get("allowed", False) and exec_decision.trade:
            # Pass enriched signal (includes exec_lots, exec_sl_mult, etc.)
            self.execution_fn(enriched)

            # Execute webhooks if configured
            for url in self.config.get("webhooks", []):
                threading.Thread(
                    target=self._fire_webhook, args=(url, enriched), daemon=True
                ).start()

            log.info(
                "Executed: %s %s tier=%s lots=%d mode=%s quality=%.2f",
                enriched.get("symbol"), enriched.get("direction"),
                exec_decision.tier, exec_decision.lots,
                exec_decision.mode, exec_decision.quality_score,
            )
        elif exec_decision.trade and not auto_mode:
            log.info(
                "Signal ready (auto_mode off): %s %s tier=%s lots=%d",
                enriched.get("symbol"), enriched.get("direction"),
                exec_decision.tier, exec_decision.lots,
            )
        else:
            log.info(
                "Execution skipped: %s — %s",
                enriched.get("symbol"),
                "; ".join(exec_decision.reasons),
            )

        return exec_decision

    def _fire_webhook(self, url: str, payload: dict[str, Any]) -> None:
        try:
            import requests
            resp = requests.post(url, json=payload, timeout=5)
            log.info("Webhook fired to %s. Status: %d", url, resp.status_code)
        except Exception as e:
            log.error("Failed to fire webhook to %s: %s", url, e)

    def _format_telegram_payload(
        self,
        raw: dict,
        decision: dict,
        risk: dict,
        exec_dec: ExecutionDecision,
    ) -> dict:
        """
        Constructs the explainable signal payload for Telegram.
        Includes tier, confidence, regime, and position size.
        """
        signal_class = decision.get("class", "WEAK")
        icon = "🔵" if signal_class == "STRONG" else ("🟡" if signal_class == "EARLY" else "⚪")

        title = f"{icon} {signal_class} {raw.get('direction', 'BUY')} SIGNAL"

        reasons_text = []
        for r in decision.get("reasons", []):
            status_icon = "✔" if r.get("status") else "✖"
            reasons_text.append(f"{status_icon} {r.get('name')}: {r.get('msg')}")

        # Compact score breakdown: only components that contributed non-zero points,
        # sorted descending so the biggest drivers appear first in Telegram alerts.
        _raw_comps = raw.get("score_components") or {}
        _score_breakdown = {k: v for k, v in sorted(_raw_comps.items(), key=lambda x: -abs(x[1])) if v != 0}

        return {
            "title":         title,
            "symbol":        raw.get("symbol"),
            "score":         decision.get("confidence"),
            "tier":          exec_dec.tier,
            "confidence_pct": round(float(decision.get("confidence_pct", 0)), 1),
            "regime":        raw.get("mkt_regime") or raw.get("regime", "NEUTRAL"),
            "position_pct":  round(exec_dec.position_pct * 100, 1),
            "lots":          exec_dec.lots,
            "exec_mode":     exec_dec.mode,
            "quality":       exec_dec.quality_score,
            "sl_mult":       exec_dec.sl_mult,
            "tp_mult":       exec_dec.tp_mult,
            "reasons":       "\n".join(reasons_text),
            "risk_allowed":  risk.get("allowed"),
            "risk_msg":      risk.get("reason"),
            "exec_trade":    exec_dec.trade,
            "exec_reasons":  exec_dec.reasons,
            "score_breakdown": _score_breakdown,
        }
