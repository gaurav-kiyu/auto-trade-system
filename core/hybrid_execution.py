"""Shared EXECUTION_MODE normalization and hybrid flags for index + stock bots."""

from __future__ import annotations

from typing import Any

__all__ = [
    "apply_execution_mode",
    "normalize_execution_mode",
]

def normalize_execution_mode(raw: Any) -> str:
    mode = str(raw or "MANUAL").strip().upper()
    alias_map = {
        "LIVE": "AUTO",
        "AUTOMATIC": "AUTO",
        "AUTO_LIVE": "AUTO",
        "BROKER": "AUTO",
        "MANUAL_ONLY": "MANUAL",
        "SIGNALS_ONLY": "SIGNAL_ONLY",
        "SIGNALS": "SIGNAL_ONLY",
        "PAPER_MODE": "PAPER",
        "SIM": "PAPER",
    }
    mode = alias_map.get(mode, mode)
    return mode if mode in ("PAPER", "MANUAL", "AUTO", "SIGNAL_ONLY") else "MANUAL"


def apply_execution_mode(
    cfg: dict,
    *,
    cli_paper: bool,
    infer_blank_from_broker: bool = False,
) -> dict:
    """Set EXECUTION_MODE and derived MANUAL_SIGNALS_ONLY / BROKER_API_ENABLED.

    CRITICAL SAFETY: infer_blank_from_broker defaults to False. When True (stock legacy),
    missing or blank EXECUTION_MODE becomes MANUAL regardless of BROKER_API_ENABLED.
    Never auto-default to AUTO - explicit EXECUTION_MODE=AUTO is required.
    cli_paper forces PAPER (``--paper``), matching index _CLI_PAPER_MODE / stock PAPER_MODE.
    """
    if infer_blank_from_broker:
        _ex = cfg.get("EXECUTION_MODE")
        if _ex is None or (isinstance(_ex, str) and not str(_ex).strip()):
            # SAFETY: Never auto-default to AUTO. Explicit EXECUTION_MODE=AUTO required.
            cfg["EXECUTION_MODE"] = "MANUAL"
            import logging
            _log = logging.getLogger(__name__)
            _log.critical(
                "[HYBRID_EXECUTION] CRITICAL: EXECUTION_MODE is blank/missing and "
                "BROKER_API_ENABLED=%s. Defaulting to MANUAL - never auto-AUTO. "
                "Set EXECUTION_MODE=AUTO explicitly to enable automated trading.",
                cfg.get("BROKER_API_ENABLED"),
            )
    mode = "PAPER" if cli_paper else normalize_execution_mode(cfg.get("EXECUTION_MODE", "MANUAL"))
    cfg["EXECUTION_MODE"] = mode
    if mode == "PAPER":
        cfg["MANUAL_SIGNALS_ONLY"] = False
        cfg["BROKER_API_ENABLED"] = False
    elif mode == "MANUAL":
        cfg["MANUAL_SIGNALS_ONLY"] = True
        cfg["BROKER_API_ENABLED"] = False
    elif mode == "AUTO":
        cfg["MANUAL_SIGNALS_ONLY"] = False
        cfg["BROKER_API_ENABLED"] = True
    elif mode == "SIGNAL_ONLY":
        cfg["MANUAL_SIGNALS_ONLY"] = True
        cfg["BROKER_API_ENABLED"] = False
    else:  # fallback - MANUAL
        cfg["MANUAL_SIGNALS_ONLY"] = True
        cfg["BROKER_API_ENABLED"] = False
    return cfg
