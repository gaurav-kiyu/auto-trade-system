import json
import os
from pathlib import Path
from typing import Any

# Basic dotenv loader to avoid external dependencies


__all__ = [
    "get_legacy_flat_config",
    "load_config_v2",
    "load_dotenv",
]

def load_dotenv(env_path: str | Path | None = None) -> None:
    path = Path(env_path) if env_path is not None else Path(__file__).resolve().parent.parent / ".env"
    if not path.exists():
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, val = line.split("=", 1)
                os.environ[key.strip()] = val.strip()

def load_config_v2(config_path: str = "config_v2.json") -> dict[str, Any]:
    """Load the V2 nested configuration and inject secrets from .env"""
    load_dotenv()

    path = Path(config_path)
    if not path.exists():
        # Fallback to empty if not found, though should exist
        return {}

    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)

    # Inject secrets
    if "secrets" not in cfg:
        cfg["secrets"] = {}
    cfg["secrets"]["bot_token"] = os.getenv("BOT_TOKEN", "")
    cfg["secrets"]["chat_id"] = os.getenv("CHAT_ID", "")

    return cfg

def get_legacy_flat_config(v2_cfg: dict[str, Any]) -> dict[str, Any]:
    """
    Returns a flattened dictionary containing the legacy keys so that
    older modules (like index_trader.py) don't break during the transition.
    """
    flat = dict(v2_cfg.get("legacy_flat", {}))

    # Map back core keys that might have been moved
    flat["BOT_TOKEN"] = v2_cfg.get("secrets", {}).get("bot_token", "")
    flat["CHAT_ID"] = v2_cfg.get("secrets", {}).get("chat_id", "")

    # Map from thresholds
    th = v2_cfg.get("thresholds", {})
    flat["STRONG_THRESHOLD"] = th.get("strong", 75)
    flat["RSI_OVERBOUGHT"] = th.get("rsi_overbought", 70)
    flat["RSI_OVERSOLD"] = th.get("rsi_oversold", 30)
    flat["VOL_RATIO_MIN"] = th.get("vol_ratio_min", 1.2)
    flat["AI_THRESHOLD"] = th.get("ai_threshold", 70)
    flat["IV_SPIKE_THRESHOLD"] = th.get("iv_spike_threshold", 60.0)
    flat["ATR_MIN_THRESHOLD"] = th.get("atr_min_threshold", 0.5)

    # Map from risk
    rk = v2_cfg.get("risk", {})
    flat["MAX_DAILY_LOSS"] = rk.get("max_daily_loss", -400)
    flat["MAX_DRAWDOWN"] = rk.get("max_drawdown", 0.3)
    flat["DAILY_TARGET"] = rk.get("daily_target", 400)
    flat["RISK_MODE"] = rk.get("risk_mode", "FIXED")
    flat["RISK_FIXED_AMOUNT"] = rk.get("risk_fixed_amount", 90)
    flat["RISK_PER_TRADE"] = rk.get("risk_per_trade", 0.03)
    flat["MAX_LOT_CAPITAL_PCT"] = rk.get("lot_pct", 0.6)
    flat["MAX_OPEN"] = rk.get("max_open", 1)
    flat["MAX_TRADES_DAY"] = rk.get("max_trades_day", 2)
    flat["BROKERAGE_PER_TRADE"] = rk.get("brokerage_per_trade", 40)

    # Map from features
    ft = v2_cfg.get("features", {})
    flat["EXECUTION_MODE"] = ft.get("execution_mode", "MANUAL")
    flat["MANUAL_SIGNALS_ONLY"] = ft.get("manual_signals_only", True)
    flat["DATA_CROSS_VALIDATE"] = ft.get("data_cross_validate", True)

    # Map from timing
    tm = v2_cfg.get("timing", {})
    flat["SCAN_INTERVAL"] = tm.get("scan_interval", 30)
    flat["COOLDOWN"] = tm.get("cooldown", 300)
    flat["SIGNAL_MAX_AGE"] = tm.get("signal_max_age", 65)
    flat["MAX_POSITION_AGE"] = tm.get("max_position_age", 120)
    flat["SUMMARY_INTERVAL"] = tm.get("summary_interval", 600)

    # Preserve nested legacy that legacy index_trader expects as dicts
    flat["INDEX_MAP"] = v2_cfg.get("index_map", {})
    flat["DATA_PROVIDER_ENABLED"] = v2_cfg.get("data_provider_enabled", {})
    flat["BROKER_CONFIG"] = v2_cfg.get("broker_config", {})

    return flat
