from __future__ import annotations

from typing import Any


class DashboardEngine:
    """Frontend text builder for operator-friendly dashboard summaries."""

    def __init__(self, *, execution_label_fn=None) -> None:
        self._execution_label_fn = execution_label_fn

    def format_trading_desk_line(self, dsk: dict[str, Any] | None) -> tuple[str, str]:
        if not isinstance(dsk, dict):
            return ("Desk metrics will appear after the next scan cycle.", "#8b949e")
        parts: list[str] = []
        vx = dsk.get("vix")
        vb = dsk.get("vix_block")
        vh = dsk.get("vix_halt")
        if vx is not None:
            try:
                parts.append(f"India VIX {float(vx):.1f} (block<={vb} / halt<={vh})")
            except (TypeError, ValueError):
                parts.append(f"VIX thresholds block<={vb} halt<={vh}")
        else:
            parts.append(f"VIX n/a (cfg block<={vb} / halt<={vh})")
        lp = dsk.get("loss_pct_limit")
        if lp is not None:
            try:
                parts.append(f"Daily loss budget used ~{float(lp):.0f}%")
            except (TypeError, ValueError):
                pass
        try:
            parts.append(f"Min net RR >={float(dsk.get('min_rr', 0)):.2f}")
        except (TypeError, ValueError):
            parts.append("Min net RR >=?")
        try:
            parts.append(f"SL/Target {float(dsk.get('sl_pct', 0))*100:.0f}% / {float(dsk.get('tgt_pct', 0))*100:.0f}%")
        except (TypeError, ValueError):
            pass
        parts.append(f"Circuit {dsk.get('circuit', '?')}")
        if dsk.get("hard_halt"):
            parts.append("HARD HALT")
        if self._execution_label_fn:
            try:
                parts.append(f"Exec: {self._execution_label_fn(dsk)}")
            except (TypeError, ValueError):
                pass
        for key in ("sig_quality", "api_health", "learning_quality"):
            if dsk.get(key):
                parts.append(str(dsk.get(key)))
        fg = "#c9d1d9"
        if dsk.get("hard_halt"):
            fg = "#f85149"
        elif "TRIP" in str(dsk.get("circuit", "")).upper():
            fg = "#f0883e"
        return ("   -   ".join(parts), fg)
