from __future__ import annotations

from collections.abc import Callable
from typing import Any

__all__ = [
    "PresentationEngine",
]

class PresentationEngine:
    """Simple operator-facing wording layer for alerts and dashboard text."""

    def __init__(
        self,
        *,
        currency_symbol: str = "₹",
        pnl_formatter: Callable[[float], str] | None = None,
    ) -> None:
        self._currency_symbol = currency_symbol
        self._pnl_formatter = pnl_formatter

    def _money(self, value: float | int | str) -> str:
        try:
            amount = float(value)
        except (TypeError, ValueError):
            return f"{self._currency_symbol}{value}"
        return f"{self._currency_symbol}{round(amount, 2):,}"

    def _pnl(self, value: float | int) -> str:
        if self._pnl_formatter:
            try:
                return str(self._pnl_formatter(float(value)))
            except (TypeError, ValueError):
                pass
        return self._money(value)

    def manual_signal_message(self, *, name: str, signal_type: str, strike: int, entry: float, qty: int, sl: float, target: float, net_rr: float, score: float, why: str) -> str:
        return (
            f"Manual signal for {name}\n"
            f"Side: {signal_type}\n"
            f"Strike: {strike}\n"
            f"Reference entry: {self._money(entry)}\n"
            f"Suggested quantity: {qty}\n"
            f"Stop loss: {self._money(sl)}\n"
            f"Target: {self._money(target)}\n"
            f"Risk/reward: {round(net_rr, 2)}\n"
            f"Score: {int(score)}/100\n"
            f"Reason: {why}\n"
            "Action: check your broker screen and place the order manually if you agree."
        )

    def new_trade_message(self, *, name: str, action: str, strike: int, entry: float, qty: int, target: float, risk_amt: float, profit_amt: float, sl: float, why: str, score: float, iv: float, vix: float, net_rr: float, mode_label: str) -> str:
        return (
            f"New trade opened: {name}\n"
            f"Action: {action}\n"
            f"Strike: {strike}\n"
            f"Entry price: {self._money(entry)}\n"
            f"Quantity: {qty}\n"
            f"Target: {self._money(target)} (approx reward {self._money(profit_amt)})\n"
            f"Stop loss: {self._money(sl)} (approx risk {self._money(risk_amt)})\n"
            f"Reason: {why}\n"
            f"Score: {int(score)}/100 | IV: {iv} | VIX: {vix} | Net RR: {round(net_rr, 2)}\n"
            f"Mode: {mode_label}"
        )

    def dashboard_broker_mode(self, *, execution_mode: str, broker_backend: str, broker_api_enabled: bool) -> str:
        mode = str(execution_mode or "MANUAL").upper()
        backend = str(broker_backend or "NONE").upper()
        if mode == "PAPER":
            return "Paper mode: simulated orders only"
        if mode == "MANUAL":
            return "Manual mode: bot sends signals, you place orders yourself"
        if mode == "AUTO" and broker_api_enabled:
            return f"Auto mode: broker ordering active via {backend}"
        if mode == "SIGNALS":
            return "Signals mode: live alerts only, no order placement"
        return "Broker mode: configuration check needed"

    def dashboard_broker_mode_named(self, *, execution_mode: str, broker_name: str, broker_api_enabled: bool) -> str:
        mode = str(execution_mode or "MANUAL").upper()
        name = str(broker_name or "broker").strip() or "broker"
        if mode == "PAPER":
            return "Paper mode: simulated orders only"
        if mode == "MANUAL":
            return "Manual mode: bot sends signals, you place orders yourself"
        if mode == "AUTO" and broker_api_enabled:
            return f"Auto mode: {name} ordering active"
        if mode == "SIGNALS":
            return "Signals mode: live alerts only, no order placement"
        return "Broker mode: configuration check needed"

    def signal_summary(self, sig: dict[str, Any], *, confidence_text: str = "", learner_text: str = "") -> str:
        name = str(sig.get("name") or "?")
        direction = str(sig.get("direction") or "?")
        score = int(sig.get("score") or 0)
        threshold = int(sig.get("threshold") or 0)
        reason_bits = [bit for bit in (confidence_text, learner_text) if bit]
        why = " | ".join(reason_bits) if reason_bits else "Signal passed filters"
        return f"{name} {direction} | score {score}/{threshold} | {why}"
