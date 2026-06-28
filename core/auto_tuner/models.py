"""
Auto-Tuner Models — data structures, constants, and tunable parameter definitions.

Extracted from core/auto_tuner.py for SRP compliance.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

# ── Tuning constants ──────────────────────────────────────────────────────────

_MIN_TRADES_MEDIUM = 15   # minimum trades for MEDIUM confidence
_MIN_TRADES_HIGH = 30     # minimum trades for HIGH confidence
_MAX_CHANGES_PER_RUN = 2  # hard cap: never change more than 2 params per EOD run

_DEFAULT_CONFIG = "config.json"
_DEFAULT_DB = "trades.db"
_BACKUP_DIR = Path("backups")
_AUDIT_LOG = Path("reports/auto_tune_log.jsonl")
_MAX_BACKUP_FILES = 5


# ── Whitelist: ONLY these keys may ever be written ────────────────────────────

_TUNABLE_PARAMS: dict[str, dict] = {
    "AI_THRESHOLD": {
        "type": "int",
        "abs_min": 60,
        "abs_max": 80,
        "max_delta": 5,
        "description": "Minimum signal score for entry",
    },
    "SIGNAL_ENTRY_SCORE_GAP": {
        "type": "int",
        "abs_min": 0,
        "abs_max": 10,
        "max_delta": 2,
        "description": "Score gap required between consecutive signals",
    },
}

_TUNABLE_REGIME_SIZE = {
    "abs_min": 0.2,
    "abs_max": 1.0,
    "max_delta": 0.2,
}

# ── Blocklist: these keys are permanently frozen ──────────────────────────────

_BLOCKED_KEYS: frozenset[str] = frozenset({
    # Credentials / broker
    "BOT_TOKEN", "CHAT_ID", "BROKER_CONFIG",
    "BROKER_API_ENABLED", "BROKER_DRIVER", "BROKER_NAME", "BROKER_CUSTOM_FACTORY",
    # Execution mode
    "EXECUTION_MODE", "MANUAL_SIGNALS_ONLY", "PAPER_MODE",
    # Risk circuit breakers
    "MAX_DAILY_LOSS", "MAX_DRAWDOWN", "BASE_CAPITAL",
    "RISK_PER_TRADE", "RISK_MODE", "RISK_FIXED_AMOUNT",
    # SL / TP / trail
    "SL_PCT", "TARGET_PCT", "TRAIL_PCT", "TRAIL_ACTIVATE",
    "ATR_SL_MULTIPLIER", "FIB_TP1_RATIO", "FIB_TP2_RATIO", "FIB_TP3_RATIO",
    # Orders / reconciliation
    "ORDER_PLACE_RETRIES", "ORDER_RETRY_WAIT_SEC", "ORDER_FILL_TIMEOUT_SEC",
    "EXIT_ORDER_RETRIES", "EXIT_RETRY_WAIT_SEC", "EXIT_FILL_TIMEOUT_SEC",
    "FORCE_PRE_TRADE_RECON", "RECONCILE_HALT_ON_QTY_MISMATCH",
    "RECONCILE_INTERVAL", "BROKER_STATUS_POLL_SEC",
    # Watchdog / circuit breaker
    "CIRCUIT_BREAKER_THRESHOLD", "WATCHDOG_TIMEOUT", "CONSEC_LOSS_LIMIT",
    # Index / lot config
    "INDEX_MAP", "INDEX_PRIORITY", "NIFTY_LOT_SIZE", "BANKNIFTY_LOT_SIZE", "FINNIFTY_LOT_SIZE",
})


# ── Data structures ───────────────────────────────────────────────────────────

@dataclass
class Recommendation:
    type: str                    # "threshold" | "regime_size" | "regime_avoid" | "drawdown_warning"
    param: str                   # config key or "REGIME_SIZE_MAP.CHOPPY"
    current_value: Any
    suggested_value: Any         # None for informational-only warnings
    reason: str
    evidence: dict
    confidence: str              # "HIGH" | "MEDIUM" | "LOW"
    safe_to_apply: bool          # False for informational items and MEDIUM confidence


@dataclass
class AppliedChange:
    param: str
    old_value: Any
    new_value: Any
    ts: str
    dry_run: bool


@dataclass
class TuneResult:
    generated_at: str
    trade_sample: int
    overall_win_rate: float
    overall_expectancy: float
    overall_pf: Any
    recommendations: list[Recommendation]
    applied: list[AppliedChange]
    dry_run: bool
    enabled: bool
    backup_path: str = ""

    def to_dict(self) -> dict:
        return {
            "generated_at":      self.generated_at,
            "trade_sample":      self.trade_sample,
            "overall_win_rate":  self.overall_win_rate,
            "overall_expectancy": self.overall_expectancy,
            "overall_pf":        self.overall_pf,
            "dry_run":           self.dry_run,
            "enabled":           self.enabled,
            "backup_path":       self.backup_path,
            "recommendations": [asdict(r) for r in self.recommendations],
            "applied":          [asdict(c) for c in self.applied],
        }


__all__ = [
    "AppliedChange",
    "Recommendation",
    "TuneResult",
    "_BLOCKED_KEYS",
    "_TUNABLE_PARAMS",
    "_TUNABLE_REGIME_SIZE",
]
