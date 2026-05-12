"""Shared EXECUTION_MODE normalization and hybrid flags for index + stock bots."""

from __future__ import annotations

from typing import Any


def normalize_execution_mode(raw: Any) -> str:
    mode = str(raw or "MANUAL").strip().upper()
    alias_map = {
        "LIVE": "AUTO",
        "AUTOMATIC": "AUTO",
        "AUTO_LIVE": "AUTO",
        "BROKER": "AUTO",
        "MANUAL_ONLY": "MANUAL",
        "SIGNALS_ONLY": "MANUAL",
        "PAPER_MODE": "PAPER",
        "SIM": "PAPER",
    }
    mode = alias_map.get(mode, mode)
    return mode if mode in ("PAPER", "MANUAL", "AUTO", "SIGNALS") else "MANUAL"


def apply_execution_mode(
    cfg: dict,
    *,
    cli_paper: bool,
    infer_blank_from_broker: bool = False,
) -> dict:
    """Set EXECUTION_MODE and derived MANUAL_SIGNALS_ONLY / BROKER_API_ENABLED.

    When infer_blank_from_broker is True (stock legacy): missing or blank EXECUTION_MODE
    becomes AUTO if BROKER_API_ENABLED else MANUAL before normalization.
    cli_paper forces PAPER (``--paper``), matching index _CLI_PAPER_MODE / stock PAPER_MODE.
    """
    if infer_blank_from_broker:
        _ex = cfg.get("EXECUTION_MODE")
        if _ex is None or (isinstance(_ex, str) and not str(_ex).strip()):
            cfg["EXECUTION_MODE"] = "AUTO" if cfg.get("BROKER_API_ENABLED") else "MANUAL"
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
    else:  # SIGNALS
        cfg["MANUAL_SIGNALS_ONLY"] = False
        cfg["BROKER_API_ENABLED"] = False
    return cfg
